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

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

from transform import Transformer  # noqa: E402

with open(os.path.join(HERE, 'transform_cases.json'), encoding='utf-8') as f:
    CASES = json.load(f)['cases']

SPECIAL = {'nan': float('nan'), 'inf': float('inf'), 'list': [1, 2]}


def decode(raw):
    if isinstance(raw, dict) and '$special' in raw:
        return SPECIAL[raw['$special']]
    return raw


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_shared_case(case):
    transformer = Transformer(case['transforms'])
    assert transformer.convert(case['parameter'], decode(case['raw'])) == case['expected']


class LocalizedText:
    def __init__(self, text):
        self.Text = text
        self.Locale = 'en'


MS = 'https://industry-fusion.org/base/v0.1/machine_state'
STATE_RULES = {'version': 1, 'rules': [
    {'parameter': MS, 'map': {'cases': [{'eq': 'Running', 'out': '2'}], 'fallback': 'raw'}, 'on_error': '0'}]}


def test_localized_text_matches_on_its_text():
    assert Transformer(STATE_RULES).convert(MS, LocalizedText('Running')) == '2'


def test_localized_text_without_rule_sends_its_text():
    assert Transformer(None).convert(MS, LocalizedText('Auto')) == 'Auto'


def test_localized_text_without_text_is_no_value():
    assert Transformer(STATE_RULES).convert(MS, LocalizedText(None)) == '0'


def test_error_values_only_for_rules_with_on_error():
    transformer = Transformer({'version': 1, 'rules': STATE_RULES['rules'] + [
        {'parameter': 'https://example.org/p', 'linear': {'factor': 2}}]})
    assert transformer.error_values([MS, 'https://example.org/p', 'https://example.org/q']) == {MS: '0'}


def test_transforms_without_rules_list_is_ignored():
    assert Transformer({'version': 1}).convert(MS, 3) == '3'


def test_duplicate_rule_keeps_the_first():
    rules = {'version': 1, 'rules': [
        {'parameter': MS, 'map': {'cases': [{'eq': '1', 'out': '2'}]}},
        {'parameter': MS, 'map': {'cases': [{'eq': '1', 'out': '1'}]}}]}
    assert Transformer(rules).convert(MS, 1) == '2'
