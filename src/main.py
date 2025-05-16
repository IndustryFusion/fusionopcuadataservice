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



import logging
import os
import socket
import time
import yaml

# ------ Fill the relevant protocol connection address and port URL here. ------
discovery_url = os.environ.get('DISCOVERY_URL')

# These are the environment variables set in the deployment coming from IFF suite
# (use it to send data to PDT iot agent and also use username and password for protect connections)
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
# This is device config file which comes from IFF suite, mounted using configmap in runtime
f = open("../resources/config.yaml")
target_configs = yaml.safe_load(f)
f.close()


# Method to fetch the OPC-UA Node value with given namespace and identifier
async def fetchOneDataPoint(identifier, client):
    try:
        # Fill value from your data server connected client w.r.t to identifier (for example, in MQTT, identifier here is topic )
        value = ""
    except Exception as e:
        print(e)
        print("Could not fetch data from server")
    
    return value


# Method to send the value to IFF PDT with its property name
# n is the PDT property name and v is the value
def sendPdtData(parameter, value):
    try:
        msgFromClient = '{"n": "' + parameter + '", "v": "' + str(value) + '", "t": "Property"}'
        s.send(str.encode(msgFromClient))
        print("Sent data to PDT: " + parameter + " " + str(value))
        print(msgFromClient)
    except Exception as e:
        print(e)
        print("Could not send data to PDT, check whether it is running or not")


async def run_loop():
    while True:
        try:
            # Connect to your client (if needed use username and password) and create the client object here
            # Replace with actual client connection code
            client = None

            async with client:
                # Continously fetch the properties, OPC-UA namespace and identifier from OPC-UA config
                # Fetch the respective value from the OPC_UA server and sending it to PDT with the property
                while True:
                    for item in target_configs['fusiondataservice']['specification']:
                        time.sleep(1)
                        identifier = item['identifier']
                        parameter = item['parameter']
                        try:
                            opc_value = await fetchOneDataPoint(identifier=identifier, client=client)
                        except Exception as e:
                            logging.error(f"Error fetching data from OPC UA: {e}")
                            raise  # This will trigger outer reconnect
                        opc_value = str(opc_value)

                        sendPdtData(parameter=parameter, opc_value=opc_value)

        except (ConnectionError) as e:
            logging.warning(f"Connection lost or failed: {e}. Reconnecting in 5 seconds...")

        except Exception as e:
            logging.error(f"Unexpected error: {e}")


async def main():
    await run_loop()


if __name__ == "__main__":
    time.sleep(20)
    logging.basicConfig(level=logging.INFO)