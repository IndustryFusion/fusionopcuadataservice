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

import json
from opcua import Client
import os
import socket
import time
import oisp

# Fetching all environment variables

for key, value in os.environ.items():
    if key.startswith('OPCUA_DISCOVERY_URL'):
        opcua_discovery_url = os.environ.get(key)

oisp_url = os.environ.get('IFF_AGENT_URL')
oisp_port = os.environ.get('IFF_AGENT_PORT')
opc_username = os.environ.get('USERNAME')
opc_password = os.environ.get('PASSWORD')

# Explicit sleep to wait for OISP agent to work
time.sleep(30)

# Printing the Akri discovered URL 
print('env name: ' + opcua_discovery_url)

# TCP socket config for OISP
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# OPC-UA client instance creation
try:
    client = Client(opcua_discovery_url)
    print("Connected to OPC UA server")
except:
    print("Could not connect to OPC UA server")
    exit()

async def make_connection():
    global client
    client.set_user(opc_username)
    client.set_password(opc_password)
    await client.connect()

# OPCUA connection with or without password
if opc_username != "" and opc_password != "":
    make_connection()
else:
    client.connect()
    
# PDT client connection
s.connect((str(oisp_url), int(oisp_port)))
root = client.get_root_node()

# Prinitng the OPC applicationName and Uri to confirm the AKri config
for i in client.find_servers():
    print(str(i.ApplicationName.Text))
    print(str(i.ApplicationUri))

# Opening JSON config file for OPCUA - machine specific config from mounted path in runtime
f = open("../resources/config.json")
target_configs = json.load(f)
f.close()


# Method to fetch the OPC-UA Node value with given namespace and identifier
def fetchOpcData(n, i):
    try:
        var = client.get_node(n + ";" + i)
        print("Fetched data from OPC UA: " + n + " " + i)
        print(var.get_value())
    except Exception as e:
        print(e)
        print("Could not fetch data from OPC UA")
        return "0.0"
    
    return var.get_value()


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


if __name__ == "__main__":
    time.sleep(20)

    # Continously fetch the properties, OPC-UA namespace and identifier from OPC-UA config
    # Fetch the respective value from the OPC_UA server and sending it to PDT with the property
    while 1:
        for item in target_configs['fusionopcuadataservice']['specification']:
            time.sleep(0.5)
            opc_n = item['node_id']
            opc_i = item['identifier']
            oisp_n = "http://www.industry-fusion.org/fields#" + item['parameter']
            opc_value = fetchOpcData(n=opc_n, i=opc_i)
            check = str(oisp_n).split("-")
            if "state" in check and opc_value != "0.0":
                opc_value = 2
            elif "state" in check and opc_value == "0.0":
                opc_value = 0
            else:
                opc_value = str(opc_value)

            sendOispData(n=oisp_n, v=opc_value)