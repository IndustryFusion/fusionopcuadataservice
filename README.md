[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2FIndustryFusion%2Ffusionopcuadataservice.svg?type=shield&issueType=license)](https://app.fossa.com/projects/git%2Bgithub.com%2FIndustryFusion%2Ffusionopcuadataservice?ref=badge_shield&issueType=license)


# Fusion OPC-UA Data Service

This Python script facilitates the integration between an OPC-UA server and the PDT Gateway services by performing the following tasks:

1. Establishing a connection with the OPC-UA server.
2. Connecting to the PDT Gateway platform.
3. Fetching configuration details from provided configuration and data from the OPC-UA server.
4. Registering and continuously updating device properties on the PDT platform.

## Prerequisites

1. Python 3.8.10 or more.
2. Process Digital Twin is already setup either locally or in cloud. [https://github.com/IndustryFusion/DigitalTwin/blob/main/helm/README.md#building-and-installation-of-platform-locally]
3. Working OPC-UA server.
4. The IFF IoT agent must be started in the same system using Docker Container. Use the following command to start the IFF IoT agent in local for development usage.

IFF IoT agent docker image must be built from here - [https://github.com/IndustryFusion/DigitalTwin/tree/main/NgsildAgent/Dockerfile]

`docker run -d -e DEVICE_ID=<Device ID of the asset in PDT> GATEWAY_ID=<Device ID of the asset in PDT> -e KEYCLOAK_URL=<PDT Keycloak URL> -e REALM_ID=iff -e REALM_USER_PASSWORD=<Password of Keycloak REALM_USER> -v /volume/config:/volume/config --security-opt=privileged=true --cap-drop=all -p 41234:41234 -p 7070:7070 <IFF IoT agent docker image>`

To get the REALM_USER_PASSWORD, run the following command on the PDT cluster.

`kubectl -n iff get secret/credential-iff-realm-user-iff -o jsonpath='{.data.password}'| base64 -d | xargs echo`

The above docker container also expects a config file with the name config.json located in the /volume/config folder of the host system for mounting. The contents of this file are as follows.

```json
 {
        "data_directory": "./data",
        "listeners": {
                "udp_port": 41234,
                "tcp_port": 7070
        },
        "logger": {
                "level": "info",
                "path": "/tmp/",
                "max_size": 134217728
        },
        "dbManager": {
                "file": "metrics.db",
                "retentionInSeconds": 3600,
                "housekeepingIntervalInSeconds": 60,
                "enabled": false
        },
        "connector": {
                "mqtt": {
                        "host": "PDT URL",
                        "port": 8883,
                        "websockets": false,
                        "qos": 1,
                        "retain": false,
                        "secure": true,
                        "retries": 5,
                        "strictSSL": false,
                        "sparkplugB": true,
                        "version": "spBv1.0"        
                }
        }
    }
```

Update the "host" variable with the correct PDT URL.


## Configuration

All settings come from environment variables. In a gateway deployment the
onboarding controller (iff-akri-controller) sets them from the Factory Manager
onboarding form.

| Variable | Meaning | Default |
|---|---|---|
| `PROTOCOL_URL` | OPC-UA server endpoint, e.g. `opc.tcp://192.168.49.171:4840` | required |
| `USERNAME` / `PASSWORD` | OPC-UA user and password, if any | empty |
| `IFF_AGENT_URL` | Host of the IFF IoT agent | `127.0.0.1` |
| `IFF_AGENT_UDP_PORT` | UDP port of the IFF IoT agent (`listeners.udp_port`) | `41234` |
| `SAMPLING_RATE` | Seconds between two reads of all nodes | `1.0` |
| `CONFIG_PATH` | Path of the node configuration | `../resources/config.yaml` |
| `STARTUP_DELAY` | Seconds to wait for the agent before the first read | `50` |
| `LOG_LEVEL` | `DEBUG` also logs every value sent | `INFO` |

Values are sent to the agent over UDP, one JSON array per datagram.
`IFF_AGENT_PORT` (TCP) is no longer used.

The node configuration (`config.yaml`) lists the nodes to read and, optionally,
how to transform their values:

```yaml
fusionopcuadataservice:
  specification:
    - node_id: "ns=4"
      identifier: "i=39"
      parameter: "https://industry-fusion.org/base/v0.1/machine_state"
    - node_id: "ns=2"
      identifier: "s=Power"
      parameter: "https://industry-fusion.org/base/v0.1/power_consumption"
  transforms:
    version: 1
    rules:
      - parameter: "https://industry-fusion.org/base/v0.1/machine_state"
        map:
          cases:                         # first match wins
            - { eq: "1", out: "2" }      # this machine's 1 means Online Running
            - { min: 3, max: 9, out: "1" }
            - { bit: 4, out: "1" }       # bit 4 of a status word
          fallback: { value: "1" }       # or drop (default) or raw
        on_error: "0"                    # sent when the node or server cannot be read
      - parameter: "https://industry-fusion.org/base/v0.1/power_consumption"
        linear: { factor: 1000, offset: 0, decimals: 3, from: kW, to: W }
      - parameter: "https://industry-fusion.org/base/v0.1/cutting_velocity"
        map:                             # map first ...
          cases:
            - { eq: "0", out: "10" }
          fallback: raw
        linear: { factor: 60, offset: 0, from: m/s, to: m/min }   # ... then convert
```

## Value transforms

The service sends what it reads. It has no built-in knowledge of what any
property means. Every interpretation comes from `transforms`, which Factory
Manager writes from the "Value Transforms" step of its onboarding form:

- **No rule:** the value is sent as read. Whole numbers are sent without `.0`,
  booleans as `true`/`false`, and everything else as text.
- **`map`:** cases are tried in order and the first match wins.
  - `eq` compares numbers numerically (`1`, `"1"`, `1.0`, `"1.0"` and `true` are
    all `1`), and text without regard to case or surrounding spaces.
  - `min`/`max` is an inclusive range; either end may be left out.
  - `bit` matches when that bit of a whole, non-negative value is set.
  - If nothing matches, `fallback` decides: `drop` (send nothing), `raw` (send
    the value as read), or `{value: ...}`.
- **`linear`:** sends `value × factor + offset`, rounded half away from zero to
  `decimals` (default 6). `from` and `to` are only labels for Factory Manager.
- **`map` and `linear` together:** the map runs first. What it puts out (a
  case's `out` or the fallback value) is converted when it is a number and sent
  as it is when it is text. A value it lets through (`fallback: raw`) is
  converted when it is a number and dropped when it is not. Data service
  images older than this ignore a rule with both and drop that parameter.
- **`on_error`:** sent when the node cannot be read or the server cannot be
  reached. Without it, nothing is sent for that parameter.
- **A rule that is not valid** drops its parameter's values and logs an error.
  The other parameters are not affected.

The first time a parameter sends a new value, it is logged at INFO with its
result. This shows which codes a machine actually sends.

## Local Setup

From the root directory of this project:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
export PROTOCOL_URL=opc.tcp://192.168.49.171:4840
export IFF_AGENT_URL=127.0.0.1
export CONFIG_PATH=$PWD/resources/config.yaml
export STARTUP_DELAY=0
python src/main.py
```

## Tests

The transform rules are tested against `tests/transform_cases.json`. Factory
Manager's preview runs the same file, so change both together. The image runs
Python 3.8, so run the tests there:

```sh
docker run --rm -v "$PWD":/work -w /work python:3.8 \
  sh -c 'pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -q tests'
```

## Docker build and run

From the root project folder:

```sh
docker build -t <image name> .
docker run -d --network host -e PROTOCOL_URL=<OPC-UA Server URL> -e IFF_AGENT_URL=127.0.0.1 \
  -e USERNAME=<user> -e PASSWORD=<password> -v <config file path>:/resources/config.yaml <image name>
```
