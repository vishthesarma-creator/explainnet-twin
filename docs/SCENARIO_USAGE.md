# Stage 4 laboratory scenarios

Start the agent/API as described in ARCHITECTURE.md, initialize SQLite, and start the five-switch instance. From PowerShell in the project root:

```powershell
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml network-start pilot
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml scenario-start pilot config/scenarios/loss.json
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml scenario-status pilot
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml scenario-reset pilot
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml scenario-stop pilot
wsl.exe -d Ubuntu -- .venv/bin/explainnet --config config/example.yaml job JOB_ID
```

Mutations return queued job IDs; inspect each job before submitting a different scenario. Start/reset/stop use `/v1/laboratory/scenarios/{start,reset,stop}`; live laboratory inspection uses `GET /v1/laboratory/scenarios/{instance_id}`. These are injector controls, separate from future diagnostic outputs. Reset is laboratory cleanup; repair remains unsupported.

The seven JSON examples are also valid YAML. Change `severity` to `low`, `medium` or `high`. Version `pilot_v1` permits warmup 1..5 seconds and measurement 4..20 seconds. Native iperf `-O` omits warmup from receiver summaries. The existing traffic engine bounds process lifetime to warmup + measurement + 8 seconds for control-channel completion; the scenario then automatically resets. Start waits for warmup in the background job, while HTTP submission returns immediately. Stop/reset may end the workload early, producing a canceled result with missing fields retained as null.

## Recipes and fixed capacities

All ordinary moderate/shared primary workloads are UDP h1→h3 at 8 Mbps and h2→h4 at 5 Mbps, packets 1,200 bytes. Both must cross s2→s3 on the currently selected routes. These 13 Mbps are below both the shared 100 Mbps link and the downstream 20 Mbps egress. Profiles, exact commands, route revision and receiver JSON remain ordinary run records.

| Scenario | Low / medium / high parameters | Direction and workload |
|---|---|---|
| Healthy | No impairment | Moderate 13 Mbps |
| Saturation | Background 92 / 97 / 100 Mbps | h5→h6 UDP competes on **fixed** s2→s3, total demand 105 / 110 / 113 Mbps |
| Loss | 0.03 / 0.08 / 0.15 fraction | s2→s3, moderate traffic; converted to 3 / 8 / 15 percent for netem |
| Latency | Added 15 / 35 / 60 ms | s2→s3, moderate traffic; existing 1 ms remains |
| QoS fault | Critical ceiling 0.8 / 0.5 / 0.3 Mbps | s3→s5; **same** 2 Mbps critical + 30 Mbps bulk UDP as correct policy |
| Healthy high utilization | Background 70 Mbps, total 83 Mbps | Shared link control; critical loss <0.02 and mean RTT <100 ms in smoke verification |
| Correct QoS control | Critical guarantee 3 Mbps, ceiling 4 Mbps; bulk guarantee 16 Mbps, ceiling 20 Mbps | Parent physical capacity remains 20 Mbps |

`bidirectional: true` applies loss/delay additionally on s3→s2; it is rejected for other kinds. `variation_ms` is 0..10 and allowed only for latency. Constant added delay supports an RTT claim, not an increased-jitter claim. Optional variation has its own setting and observed configuration; compare measured variability before claiming a jitter effect.

Loss/delay start after the workload's healthy warmup, so iperf's TCP control connection is established before stochastic impairment. Where the live qdisc reports seed support, the injector uses seed 20261007. The installed kernel/tool accepted it. A seed fixes the PRNG initialization, but timing and interleaving of packets still vary in WSL; exact packet sequences are not reproducible. The previous netem seed is restored, including after recreating a QoS leaf.

## One hierarchy owner and actual classification

NetworkManager extends its existing TCLink Linux HTB root `5:` and physical parent class `5:1`. Loss/delay replace only its owned netem child `10:`. No link capacity changes for saturation or impairment.

QoS replaces the s3→s5 parent leaf with child classes `5:10` (critical) and `5:20` (bulk), each with the original 1 ms delay and a 100-packet queue. An explicit Linux flower filter at priority 10 matches h1/h3 source/destination IPv4 addresses and selects `5:10`; an all-protocol fallback at priority 100 selects `5:20`. This also protects the pair's TCP control/probe packets. The two guarantees fit within the physical parent. Bulk can borrow unused service, while the parent enforces aggregate capacity. The faulty variant restricts the critical ceiling; the offered workload and bulk service stay the same.

This is Linux queue selection and shaping, with OpenFlow routes preserved. OVS does not own another hierarchy. No OVS QoS/Queue records are created, modified or globally removed. Inspection supplies actual `tc -j -s` class/queue counters and filters; receiver results and nonzero critical/bulk class bytes prove real treatment. A port already attached to another OVS QoS owner or an unexpected live hierarchy is rejected.

## Ownership, restoration and experimental truth

Before mutation, the root journal snapshots owned qdiscs/classes/filters, forwarding, selected paths and the exact workload. Base shaping must match the approved definition. Interface indexes and OVS ownership tags are rechecked before modification. Only one scenario can own an instance; identical active starts return its existing run. Changing its recipe, adding uncontrolled traffic or changing forwarding while active is rejected. Other instances and unrelated bridge resources remain independent.

Reset cancels only the scenario's traffic run, removes its two classifier priorities and child classes when present, restores base netem including its prior seed, checks the complete prior shaping/filter configuration, and probes connectivity. Packet verification separately runs restored matched workloads. Partial restoration is `restore_failed`, keeps its errors and null deactivation time, blocks new scenarios, and can be retried. Failed apply attempts invoke restoration and preserve both errors. Network teardown can remove the owned instance after a failed reset, recording a separate teardown error and actual termination time. No blanket namespace, bridge, queue or process cleanup is used.

The root stores `laboratory_ground_truth.json` beside each run's ordinary `result.json`. SQLite stores observed runs in `runs` and labels/injection parameters/location/actual activation-deactivation UTC in the separate `ground_truth` table. Inspection, start and stop/reset jobs synchronize these records; a new start synchronizes the prior journal first. During API downtime the root journal remains authoritative and is synchronized on inspection. Agent restart does not invent a deactivation time or replay scenarios: prior networks require owned cleanup. Ground truth must never be used as features, diagnosis evidence or twin instructions.

## Verification

```powershell
wsl.exe -d Ubuntu -u root -- env PYTHONPATH=src timeout 270 python3 scripts/check_fault_stage4.py
wsl.exe -d Ubuntu -u root -- env PYTHONPATH=src timeout 100 python3 scripts/check_scenario_api_stage4.py 1000
wsl.exe -d Ubuntu -- .venv/bin/python -m pytest -q
wsl.exe -d Ubuntu -- .venv/bin/python -m ruff check src tests scripts
```

The first runner owns unique instances and a sentinel bridge, runs baseline→fault→reset→restored for all four faults plus healthy high utilization, and saves native iperf, ping, directional tc counters and root ownership journals. Utilization comes from fixed-capacity class byte deltas after warmup, divided by actual monotonic elapsed time; it includes protocol overhead. Raw vendor JSON retains native percent/byte units; summaries convert loss to fractions and throughput to bps. The second runner uses an ordinary-user API/CLI, real agent and isolated SQLite for idempotence, rejection, bidirectional variation configuration, deadline reset and separate persisted ground truth. Test doubles in `test_scenarios.py` cover validation, conversion and partial restoration; they are not packet evidence. No Stage 5 telemetry pipeline or full dataset is collected.
