# Fusion Data Service

This Python script facilitates the integration between a data server and the PDT IOT agent service by performing the following tasks:

1. Establishing a connection with the your desired server.
2. Connecting to the PDT Gateway platform via IoT agent.
3. Fetching configuration details from provided config and then data from the server.
4. Registering and continuously updating device properties on the PDT platform.

## Prerequisites

1. Python 3.8.10 or more.
2. Process Digital Twin is already setup either locally or in cloud.
3. Working data server. (Eg. OPC-UA, MQTT, etc.)

## Local Setup & Run

From the root directory of this project run the below commands to install and activate venv. For the second time, just use the activate command.

**To install venv**

`python3 -m venv .venv`

**To activate**

`source .venv/bin/activate`

**Install required modules**

`pip3 install -r requirements.txt`

**Run the project (export environment varibales first as shown below)**

`export DISCOVERY_URL=<Data server URL>`

Example: "opc.tcp://192.168.49.171:4840" or "mqtt://192.168.49.171:1883"

`export USERNAME=<Username of data server, if any>`

`export PASSWORD=<Password of data server, if any>`

In kubernetes, these ENV will come directly from deployment configs.

Also, the service expects a config file with the name config.json in the 'resources' folder in the root project folder containing parameter and identifier as shown below in the example. In kubernetes, this will come directly from a mounted resource.

```json
{
    "fusiondataservice": {
        "specification": [
            {
                "identifier": "ns=2;s=1:MergedRootGroupNode/MsncCoreRootNode/ActualStateOfCuttingMachine/ActualState?msnc.aSpd",
                "parameter": "cutter-head-speed"
            },
            {
                "identifier": "Some identifier",
                "parameter": "Some property"
            }
        ]
    }
}
```

**Run the service**

`python src/main.py`


## Docker build and run

To build this project using Docker and run it, follow the below instructions.

From the root project folder.

`docker build -t <image name> .`