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

discovery_url = os.environ.get('PROTOCOL_URL')
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
    except ua.UaStatusCodeError as e:
        print(e)
        print("Could not fetch data from OPC UA")
        return None
    
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
        print("Could not send data to OISP, check whether it is running or not")


async def run_opc_loop():
    while True:
        try:
            client = Client(discovery_url, timeout=5)
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
                        opc_value = None
                        try:
                            opc_value = await fetchOpcData(n=opc_n, i=opc_i, client=client)
                        except Exception as e:
                            logging.error(f"Error fetching data from OPC UA: {e}")
                            sendOispData(n="https://industry-fusion.org/base/v0.1/machine_state", v="0")
                            continue
                        check = str(oisp_n).split("_")
                        if "state" in check and opc_value != "0.0" or opc_value == "Running":
                            opc_value = 2
                        elif "state" in check and opc_value == "0.0" or opc_value is None or opc_value == 0 or opc_value == "Idle":
                            opc_value = 1
                        elif opc_value is None:
                            sendOispData(n="https://industry-fusion.org/base/v0.1/machine_state", v="0")
                            continue
                        else:
                            opc_value = str(opc_value)

                        sendOispData(n=oisp_n, v=opc_value)

        except (ua.UaError, ConnectionError, asyncio.TimeoutError) as e:
            logging.warning(f"Connection lost or failed: {e}. Reconnecting in 5 seconds...")
            sendOispData(n="https://industry-fusion.org/base/v0.1/machine_state", v="0")
            await asyncio.sleep(5)
            
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            sendOispData(n="https://industry-fusion.org/base/v0.1/machine_state", v="0")
            await asyncio.sleep(10)
            

async def main():
    await run_opc_loop()

if __name__ == "__main__":
    time.sleep(20)

    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())