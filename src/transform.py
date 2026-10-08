#
# Copyright (c) 2026 IB Systems GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Value transforms: turn what a machine sends into what the digital twin expects.

The rules come from Factory Manager's onboarding form, inside the app config:

    fusionopcuadataservice:
      specification: [...]
      transforms:
        version: 1
        rules:
          - parameter: <property IRI>
            map: {cases: [{eq: "1", out: "2"}, {min: 3, max: 9, out: "1"}, {bit: 4, out: "1"}],
                  fallback: drop | raw | {value: "1"}}
            on_error: "0"
          - parameter: <property IRI>
            linear: {factor: 1000, offset: 0, decimals: 3, from: kW, to: W}
          - parameter: <property IRI>          # both: map first, then convert numbers
            map: {cases: [{eq: "0", out: "10"}], fallback: raw}
            linear: {factor: 60, offset: 0, from: m/s, to: m/min}

This module knows nothing about OPC UA or sockets, and nothing about what any
property means. Factory Manager mirrors it in
frontend/src/utility/value-transform/engine.ts; tests/transform_cases.json pins
both to the same results, so change them together.
"""

from __future__ import annotations

import logging
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

SUPPORTED_VERSION = 1
DEFAULT_DECIMALS = 6
MAX_LOGGED_VALUES = 50

# Relative tolerance for numeric equality: a Float32 node holding 0.1 reads back
# as 0.10000000149011612.
REL_TOL = 1e-6
ABS_TOL = 1e-9

# Above this, numbers are formatted as they are rather than rounded, because
# fixed-point formatting stops being exact (and differs between Python and JS).
FIXED_LIMIT = 1e15

# Bit tests stay within the integers a double holds exactly, so JS agrees.
MAX_BIT = 52

# What counts as a number when it arrives as text. Deliberately narrower than
# float(): no "1_000", "inf", "nan" or hex, which JS's Number() reads differently.
_NUMBER_RE = re.compile(r'^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$')


class _Marker:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


NO_VALUE = _Marker('NO_VALUE')        # nothing usable was read
UNSUPPORTED = _Marker('UNSUPPORTED')  # a list, struct, bytes, date, ...

Canon = Union[float, str, _Marker]


class RuleError(ValueError):
    """A rule that cannot be compiled."""


# ─── Normalising raw values ──────────────────────────────────────────────────

def canon(raw: Any) -> Canon:
    """The value a rule matches against: a float, lower-case text, or a marker."""
    if raw is None:
        return NO_VALUE
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) else NO_VALUE
    if isinstance(raw, str):
        text = raw.strip()
        lowered = text.lower()
        if lowered == 'true':
            return 1.0
        if lowered == 'false':
            return 0.0
        if _NUMBER_RE.match(text):
            value = float(text)
            if math.isfinite(value):
                return value
        return lowered
    # OPC UA LocalizedText: match on its text
    if hasattr(raw, 'Text') and hasattr(raw, 'Locale'):
        return canon(raw.Text)
    return UNSUPPORTED


def format_number(value: float) -> str:
    """A number as the twin should receive it: "2", not "2.0"."""
    if value == 0:
        return '0'
    if value.is_integer() and abs(value) < FIXED_LIMIT:
        return str(int(value))
    return repr(value)


def format_raw(raw: Any) -> str:
    """A value sent without any rule."""
    if isinstance(raw, bool):
        return 'true' if raw else 'false'
    if isinstance(raw, (int, float)):
        return format_number(float(raw))
    if hasattr(raw, 'Text') and hasattr(raw, 'Locale'):
        return '' if raw.Text is None else str(raw.Text)
    return str(raw)


def round_half_up(value: float, decimals: int) -> str:
    """Round half away from zero on the exact binary value, as JS toFixed does,
    then drop trailing zeros."""
    if abs(value) >= FIXED_LIMIT:
        return format_number(value)
    quantum = Decimal(1).scaleb(-decimals)
    text = format(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP), 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


# ─── Rules ───────────────────────────────────────────────────────────────────

def _number(value: Any, what: str) -> float:
    if isinstance(value, str) and _NUMBER_RE.match(value.strip()):
        result = float(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
    else:
        raise RuleError(f'{what} must be a number, not {value!r}')
    if not math.isfinite(result):
        raise RuleError(f'{what} must be finite, not {value!r}')
    return result


def _text(value: Any, what: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_number(float(value))
    raise RuleError(f'{what} must be text, not {value!r}')


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


class _Case:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        if not isinstance(cfg, dict):
            raise RuleError(f'a case must be a mapping, not {cfg!r}')
        self.out = _text(cfg.get('out'), 'case "out"')
        kinds = [k for k in ('eq', 'bit') if k in cfg] + (['range'] if 'min' in cfg or 'max' in cfg else [])
        if len(kinds) != 1:
            raise RuleError(f'a case needs exactly one of eq, min/max or bit: {cfg!r}')
        self.kind = kinds[0]
        if self.kind == 'eq':
            self.eq = canon(_text(cfg['eq'], 'case "eq"'))
            if isinstance(self.eq, _Marker):
                raise RuleError(f'case "eq" has no usable value: {cfg!r}')
        elif self.kind == 'range':
            self.min = None if cfg.get('min') is None else _number(cfg['min'], 'case "min"')
            self.max = None if cfg.get('max') is None else _number(cfg['max'], 'case "max"')
            if self.min is None and self.max is None:
                raise RuleError(f'a range needs min or max: {cfg!r}')
        else:
            bit = cfg['bit']
            if isinstance(bit, bool) or not isinstance(bit, int) and not (isinstance(bit, float) and bit.is_integer()):
                raise RuleError(f'case "bit" must be a whole number: {cfg!r}')
            self.bit = int(bit)
            if not 0 <= self.bit <= MAX_BIT:
                raise RuleError(f'case "bit" must be between 0 and {MAX_BIT}: {cfg!r}')

    def matches(self, value: Canon) -> bool:
        if self.kind == 'eq':
            if isinstance(self.eq, float) and isinstance(value, float):
                return _close(self.eq, value)
            return isinstance(self.eq, str) and isinstance(value, str) and self.eq == value
        if not isinstance(value, float):
            return False
        if self.kind == 'range':
            return (self.min is None or value >= self.min) and (self.max is None or value <= self.max)
        if value < 0 or not value.is_integer() or value >= 2 ** (MAX_BIT + 1):
            return False
        return math.floor(value / 2 ** self.bit) % 2 == 1


DROP = _Marker('DROP')


class Rule:
    """What happens to one parameter's values: an optional map, then an
    optional linear conversion of any number the map lets through."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        if not isinstance(cfg, dict):
            raise RuleError(f'a rule must be a mapping, not {cfg!r}')
        parameter = cfg.get('parameter')
        if not isinstance(parameter, str) or not parameter:
            raise RuleError(f'a rule needs a parameter: {cfg!r}')
        self.parameter = parameter
        self.on_error = None if cfg.get('on_error') is None else _text(cfg['on_error'], 'on_error')

        has_map, has_linear = cfg.get('map') is not None, cfg.get('linear') is not None
        if not (has_map or has_linear):
            raise RuleError(f'rule for {parameter} needs a map, a linear conversion or both')

        self.cases: Optional[List[_Case]] = None
        if has_map:
            spec = cfg['map']
            if not isinstance(spec, dict) or not isinstance(spec.get('cases', []), list):
                raise RuleError(f'map for {parameter} needs a list of cases')
            self.cases = [_Case(c) for c in spec.get('cases', [])]
            fallback = spec.get('fallback', 'drop')
            if fallback in ('drop', 'raw'):
                self.fallback: Union[str, _Marker] = DROP if fallback == 'drop' else 'raw'
                self.fallback_value: Optional[str] = None
            elif isinstance(fallback, dict) and 'value' in fallback:
                self.fallback, self.fallback_value = 'value', _text(fallback['value'], 'fallback value')
            else:
                raise RuleError(f'map fallback for {parameter} must be drop, raw or {{value: ...}}')

        self.linear = has_linear
        if has_linear:
            spec = cfg['linear']
            if not isinstance(spec, dict):
                raise RuleError(f'linear for {parameter} must be a mapping')
            self.factor = _number(spec.get('factor', 1), 'linear factor')
            self.offset = _number(spec.get('offset', 0), 'linear offset')
            decimals = spec.get('decimals', DEFAULT_DECIMALS)
            decimals = DEFAULT_DECIMALS if decimals is None else _number(decimals, 'linear decimals')
            if not decimals.is_integer() or not 0 <= decimals <= 10:
                raise RuleError('linear decimals must be a whole number from 0 to 10')
            self.decimals = int(decimals)

    def _convert(self, value: float) -> Union[str, _Marker]:
        result = value * self.factor + self.offset
        return round_half_up(result, self.decimals) if math.isfinite(result) else DROP

    def apply(self, raw: Any, value: Canon) -> Union[str, _Marker]:
        """The text to send for a readable value, or DROP.

        The map runs first. What it puts out (a case's out or the fallback
        value) is converted when it is a number and sent as it is when it is
        text. A value the map lets through unchanged (no map, or fallback raw)
        is converted when it is a number and dropped when it is not, because a
        conversion was asked for and cannot be made."""
        mapped: Optional[str] = None
        if self.cases is not None:
            if value is not UNSUPPORTED:
                for case in self.cases:
                    if case.matches(value):
                        mapped = case.out
                        break
            if mapped is None:
                if self.fallback is DROP:
                    return DROP
                if self.fallback == 'value':
                    mapped = self.fallback_value

        if not self.linear:
            return mapped if mapped is not None else format_raw(raw)
        if mapped is not None:
            number = canon(mapped)
            return self._convert(number) if isinstance(number, float) else mapped
        return self._convert(value) if isinstance(value, float) else DROP


# ─── The transformer used by the service ─────────────────────────────────────

class Transformer:
    def __init__(self, transforms: Any) -> None:
        self.rules: Dict[str, Rule] = {}
        self.broken: set = set()
        self._seen: Dict[str, set] = {}
        if transforms is None:
            return

        rule_cfgs = transforms.get('rules') if isinstance(transforms, dict) else None
        if not isinstance(rule_cfgs, list):
            logger.error('transforms has no list of rules; ignoring it: %r', transforms)
            return
        named = [r.get('parameter') for r in rule_cfgs if isinstance(r, dict) and isinstance(r.get('parameter'), str)]

        version = transforms.get('version')
        if version != SUPPORTED_VERSION:
            # Fail closed: an unknown format must not let raw values through.
            logger.error('transforms version %r is not supported (expected %s); '
                         'dropping %s', version, SUPPORTED_VERSION, named)
            self.broken.update(named)
            return

        for cfg in rule_cfgs:
            try:
                rule = Rule(cfg)
            except RuleError as e:
                parameter = cfg.get('parameter') if isinstance(cfg, dict) else None
                logger.error('Invalid transform rule, its values will be dropped: %s', e)
                if isinstance(parameter, str):
                    self.broken.add(parameter)
                continue
            if rule.parameter in self.rules:
                logger.error('Two transform rules for %s; using the first', rule.parameter)
                continue
            self.rules[rule.parameter] = rule
        logger.info('Loaded %d transform rule(s)', len(self.rules))

    def convert(self, parameter: str, raw: Any) -> Optional[str]:
        """The text to send for a read value, or None to send nothing."""
        if parameter in self.broken:
            return None
        value = canon(raw)
        if value is NO_VALUE:
            return self.on_error(parameter)
        rule = self.rules.get(parameter)
        if rule is None:
            return format_raw(raw)
        try:
            out = rule.apply(raw, value)
        except Exception:  # a bug here must never stop the other parameters
            logger.exception('Transform for %s failed on %r; dropping it', parameter, raw)
            return None
        result = None if out is DROP else out
        self._log_first(parameter, raw, result)
        return result  # type: ignore[return-value]

    def on_error(self, parameter: str) -> Optional[str]:
        """What to send when the parameter could not be read, or None."""
        rule = self.rules.get(parameter)
        return None if rule is None else rule.on_error

    def error_values(self, parameters: List[str]) -> Dict[str, str]:
        """on_error values for the given parameters, for when the whole server is unreachable."""
        values = {}
        for parameter in parameters:
            value = self.on_error(parameter)
            if value is not None:
                values[parameter] = value
        return values

    def _log_first(self, parameter: str, raw: Any, result: Optional[str]) -> None:
        # Shows integrators which codes a machine sends (kubectl logs), without
        # growing forever on continuous values.
        seen = self._seen.setdefault(parameter, set())
        key = repr(raw)
        if key in seen or len(seen) >= MAX_LOGGED_VALUES:
            return
        seen.add(key)
        logger.info('%s: machine sent %r -> %s', parameter, raw,
                    'dropped' if result is None else repr(result))
