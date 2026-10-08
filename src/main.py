#
# Copyright (c) 2023 IB Systems GmbH
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

# Reads the configured OPC UA nodes and sends their values to the IFF agent.
# Values are sent as read; what they mean for the digital twin is decided only
# by the transform rules from Factory Manager (see transform.py).

import asyncio
import json
import logging
import os
import socket
import time

import yaml
from asyncua import Client, ua

from transform import Transformer

logger = logging.getLogger('fusionopcuadataservice')

discovery_url = os.environ.get('PROTOCOL_URL')
agent_host = os.environ.get('IFF_AGENT_URL', '127.0.0.1')
agent_udp_port = int(os.environ.get('IFF_AGENT_UDP_PORT', '41234'))
opc_username = os.environ.get('USERNAME')
opc_password = os.environ.get('PASSWORD')
sampling_rate = float(os.environ.get('SAMPLING_RATE', '1.0'))
config_path = os.environ.get('CONFIG_PATH', '../resources/config.yaml')
# Time for the IFF agent in the same pod to come up before the first send
startup_delay = float(os.environ.get('STARTUP_DELAY', '50'))

# Messages per UDP datagram; keeps each datagram far below the UDP size limit
BATCH_SIZE = 50

# Bad statuses that mean the session or connection is gone, not just one node
CONNECTION_STATUS_NAMES = (
    'BadCommunicationError', 'BadConnectionClosed', 'BadDisconnect', 'BadNoCommunication',
    'BadNotConnected', 'BadSecureChannelClosed', 'BadSecureChannelIdInvalid', 'BadServerHalted',
    'BadServerNotConnected', 'BadSessionClosed', 'BadSessionIdInvalid', 'BadShutdown', 'BadTimeout',
)
CONNECTION_STATUS_CODES = {getattr(ua.StatusCodes, name) for name in CONNECTION_STATUS_NAMES
                           if hasattr(ua.StatusCodes, name)}


class AgentSender:
    """Sends to the IFF agent over UDP: one datagram is one JSON array, so
    messages can never run together the way they can on the TCP listener."""

    def __init__(self, host, port):
        self.address = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, values):
        messages = [{'n': parameter, 'v': value, 't': 'Property'} for parameter, value in values]
        for start in range(0, len(messages), BATCH_SIZE):
            batch = messages[start:start + BATCH_SIZE]
            try:
                self.sock.sendto(json.dumps(batch).encode('utf-8'), self.address)
            except OSError as e:
                logger.warning('Could not send to the IFF agent at %s:%s: %s', *self.address, e)
                return
            logger.debug('Sent %s', batch)


def load_config(path):
    with open(path) as f:
        service_config = yaml.safe_load(f)['fusionopcuadataservice']
    return service_config['specification'], Transformer(service_config.get('transforms'))


# Nodes currently failing, so each failure is logged once rather than every cycle
failing_nodes = set()


def node_failed(node_id, reason):
    if node_id not in failing_nodes:
        failing_nodes.add(node_id)
        logger.warning('Could not read %s: %s', node_id, reason)
    return None


async def read_item(client, item):
    """The node's value, or None when this node cannot be read right now.
    Connection-level failures are raised so the client reconnects."""
    node_id = item['node_id'] + ';' + item['identifier']
    try:
        node = client.get_node(node_id)
    except Exception as e:  # a malformed node id only affects this item
        return node_failed(node_id, e)
    try:
        value = await node.read_value()
    except ua.UaStatusCodeError as e:
        if getattr(e, 'code', None) in CONNECTION_STATUS_CODES:
            raise
        return node_failed(node_id, e)
    if node_id in failing_nodes:
        failing_nodes.discard(node_id)
        logger.info('%s can be read again', node_id)
    return value


async def poll_once(client, specification, transformer, sender):
    results = await asyncio.gather(*[read_item(client, item) for item in specification],
                                   return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result

    values = []
    for item, raw in zip(specification, results):
        value = transformer.convert(item['parameter'], raw)
        if value is not None:
            values.append((item['parameter'], value))
    sender.send(values)


async def run_opc_loop(specification, transformer, sender):
    parameters = [item['parameter'] for item in specification]
    while True:
        try:
            client = Client(discovery_url, timeout=5)
            client.set_user(opc_username)
            client.set_password(opc_password)

            async with client:
                logger.info('Connected to %s', discovery_url)
                while True:
                    await client.check_connection()
                    await poll_once(client, specification, transformer, sender)
                    await asyncio.sleep(sampling_rate)

        except (ua.UaError, ConnectionError, OSError, asyncio.TimeoutError) as e:
            logger.warning('Connection lost or failed: %s. Reconnecting in 5 seconds...', e)
            sender.send(transformer.error_values(parameters).items())
            await asyncio.sleep(5)

        except Exception:
            logger.exception('Unexpected error. Reconnecting in 10 seconds...')
            sender.send(transformer.error_values(parameters).items())
            await asyncio.sleep(10)


def main():
    logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    specification, transformer = load_config(config_path)
    logger.info('Reading %d node(s) from %s every %ss', len(specification), discovery_url, sampling_rate)
    time.sleep(startup_delay)
    asyncio.run(run_opc_loop(specification, transformer, AgentSender(agent_host, agent_udp_port)))


if __name__ == '__main__':
    main()
