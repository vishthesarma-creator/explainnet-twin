> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# Stage 3 network and traffic usage

The project remains in `/path/to/user\Desktop\CN project`, visible to Ubuntu WSL2 at `/mnt/c/Users/Dell/Desktop/CN project`. Run PowerShell commands below from that project folder. The API and its venv use the ordinary WSL user; the agent uses Ubuntu system Python and root.

## Start services

Initialize or migrate storage in place:

```powershell
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml init
```

Start the agent in one terminal:

```powershell
$appUid = (wsl.exe -d Ubuntu -- id -u).Trim()
wsl.exe -d Ubuntu -u root -- env PYTHONPATH=src python3 -m explainnet.agent_server --allow-uid $appUid --state-dir /var/lib/explainnet-agent
```

Start the API in a second terminal:

```powershell
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml serve
```

Use a third terminal for controls:

```powershell
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml status
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml network-start lab1
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml job JOB_ID
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml network-status lab1
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml probe lab1
```

Mutation commands return a job ID. Wait for that job to succeed before the next dependent operation. A probe without endpoints checks all 30 directed pairs and ARP resolution; `probe lab1 --source h1 --target h3` checks one pair.

## Traffic and path control

```powershell
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml traffic-start lab1
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml job JOB_ID
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml traffic-status lab1 RUN_ID
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml path lab1 critical alternative
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml traffic-start lab1 --profiles critical --duration 4 --rate-bps 2000000 --packet-size 1200
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml traffic-start lab1 --profiles background --duration 10
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml traffic-stop lab1 RUN_ID
```

The start job returns a traffic run ID in its result. Run status is independent of job status. Rate and packet overrides apply to a single selected profile; packet size is only valid for UDP. All profiles may override duration. Configure other rates and directional links in `config/traffic.yaml` and `config/topology.yaml`; both are validated before privileged work. The configured critical and bulk pairs allow `primary` and `alternative`; other pair forwarding is deterministic and unaffected by these controls.

## Topology and fixed logical mapping

Primary: `s1 -> s2 -> s3 -> s5`. Alternative: `s1 -> s4 -> s5`. Reverse paths use the reverse switch order.

| Host | Role | Attachment | Address offset |
|---|---|---|---|
| h1 | Critical UDP client | s1 | 1 |
| h2 | Bulk TCP client | s1 | 2 |
| h3 | Critical receiver | s5 | 3 |
| h4 | Bulk receiver | s5 | 4 |
| h5 | Background sender | s2 | 5 |
| h6 | Background receiver | s3 | 6 |

| Switch | Port mappings |
|---|---|
| s1 | 1=h1, 2=h2, 3=s2, 4=s4 |
| s2 | 1=h5, 2=s1, 3=s3 |
| s3 | 1=h6, 2=s2, 3=s5 |
| s4 | 1=s1, 2=s5 |
| s5 | 1=h3, 2=h4, 3=s3, 4=s4 |

Each instance leases its own `/24` from private pool `10.80.0.0/16`. IPs use the fixed host offsets. The token determines locally administered MACs, unique DPIDs and names `en<TOKEN>sN`/`en<TOKEN>hN`; switch interfaces remain at most 15 characters. IP/MAC/DPID/port assignments are fixed throughout an instance's lifetime and saved by `network-status` and the ownership journal. Hosts use separate process network namespaces, whose PIDs and namespace identities are recorded. Restarting a stopped instance allocates a new token; active instances never share a subnet.

## Healthy baseline and evidence

`pilot_v1` uses 100 Mbps access links, 100 Mbps inter-switch links except `s3 -> s5` (20 Mbps) and `s4 -> s5` (30 Mbps), with independently configurable reverse capacities and 1 ms per switch-link direction. `healthy_v1` offers critical UDP at 2 Mbps with 1200-byte payloads and bulk TCP at 5 Mbps, each for 4 seconds. Their combined 7 Mbps is 35% of the primary bottleneck; optional background TCP is 1 Mbps. TCP uses the installed iperf3 3.20 `-b` pacing option rather than unlimited traffic.

`artifacts/network_smoke_report.json` records actual receiver rates, UDP loss/jitter and critical-flow counters on both paths. `artifacts/stage3/` preserves all-pair ping output, port/address mappings, OpenFlow dumps, job/run records and raw iperf3 client/server stdout/JSON. The first failed attempt is retained: iperf3 rejected a receive-only timeout on sending clients, which was removed. Mininet logs kernel HTB quantum warnings for the configured high-rate classes; forwarding and traffic tests passed. This baseline is not a capacity benchmark, and the QoS hierarchy will be extended through the same owner in Stage 4.

Repeat the bounded real scenario (temporary services, unique test names, isolated dataplanes and targeted cleanup):

```powershell
$appUid = (wsl.exe -d Ubuntu -- id -u).Trim()
wsl.exe -d Ubuntu -u root -- timeout 240 python3 scripts/check_network_stage3.py --app-uid $appUid
```

## Stop and recover ownership

```powershell
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml network-stop lab1
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml job JOB_ID
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml stop
```

Stop the agent with Ctrl+C in its terminal; it stops its traffic and Mininet instances. API stop alone leaves the agent owning running networks. After an agent crash/restart, inspect the instance, then use `network-cleanup lab1` and wait for its job before `network-start lab1`. Cleanup refuses ownership mismatches and preserves other instances and unrelated OVS resources. No global Mininet cleanup is used.
