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


import asyncio
import logging
from asyncua import Client, ua
import os
import socket
import time
import yaml
import re
# Fetching all environment variables

for key, value in os.environ.items():
    if key.startswith('OPCUA_DISCOVERY_URL'):
        # Regular expression pattern to match the desired part of the string
        pattern = r"(opc\.tcp://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)"

        # Search for the pattern in the string
        match = re.search(pattern, value)

        if match:
            opcua_discovery_url = match.group(1)  # Extract the matched part
            # Printing the Akri discovered URL 
            print('env name: ' + opcua_discovery_url)
        else:
            print("Pattern not found")

oisp_url = os.environ.get('IFF_AGENT_URL')
oisp_port = os.environ.get('IFF_AGENT_PORT')
opc_username = os.environ.get('USERNAME')
opc_password = os.environ.get('PASSWORD')

# Explicit sleep to wait for OISP agent to work
time.sleep(30)

# TCP socket config for OISP
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# PDT client connection
s.connect((str(oisp_url), int(oisp_port)))

# Opening JSON config file for OPCUA - machine specific config from mounted path in runtime
f = open("../resources/config.yaml")
target_configs = yaml.safe_load(f)
f.close()


# Method to fetch the OPC-UA Node value with given namespace and identifier
async def fetchOpcData(n, i, client):
    try:
        var = client.get_node(n + ";" + i)
        print("Fetched data from OPC UA: " + n + " " + i)
        print(await var.read_value())
    except Exception as e:
        print(e)
        print("Could not fetch data from OPC UA")
        return "0.0"
    
    return await var.read_value()


# Method to send the value of the OPC-UA node to PDT with its property
def sendOispData(n, v):
    try:
        msgFromClient = '{"n": "' + n + '", "v": "' + str(v) + '", "t": "Property"}'
        s.send(str.encode(msgFromClient))
        print("Sent data to OISP: " + n + " " + str(v))
        print(msgFromClient)
    except Exception as e:
        print(e)
        print("Could not send data to OISP")


async def run_opc_loop():
    while True:
        try:
            client = Client(opcua_discovery_url, timeout=5)
            client.set_user(opc_username)
            client.set_password(opc_password)

            async with client:
                root = client.nodes.root
                print("Root node is: ", root)

                # Continously fetch the properties, OPC-UA namespace and identifier from OPC-UA config
                # Fetch the respective value from the OPC_UA server and sending it to PDT with the property
                while True:
                    for item in target_configs['fusionopcuadataservice']['specification']:
                        time.sleep(1)
                        opc_n = item['node_id']
                        opc_i = item['identifier']
                        oisp_n = item['parameter']
                        try:
                            opc_value = await fetchOpcData(n=opc_n, i=opc_i, client=client)
                        except Exception as e:
                            logging.error(f"Error fetching data from OPC UA: {e}")
                            raise  # This will trigger outer reconnect
                        check = str(oisp_n).split("_")
                        if "state" in check and opc_value != "0.0" or opc_value == "Running":
                            opc_value = 2
                        elif "state" in check and opc_value == "0.0" or opc_value == "Idle":
                            opc_value = 0
                        else:
                            opc_value = str(opc_value)

                        sendOispData(n=oisp_n, v=opc_value)

        except (ua.UaError, ConnectionError, asyncio.TimeoutError) as e:
            logging.warning(f"Connection lost or failed: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            await asyncio.sleep(10)


async def main():
    await run_opc_loop()

if __name__ == "__main__":
    time.sleep(20)

    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())