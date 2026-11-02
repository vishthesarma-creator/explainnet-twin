# Digital twin — Stage 9

## Implementation and measured coverage

Completion stage 2 adds schema-2 immutable snapshots with `critical_service_v2` and `paired_capture_v2_fixed_probe_warmup`; schema-1 history remains supported. The explicit observable allowlist/hidden-field rejection and hash validation remain enforced. Probe preconditioning is symmetric and outside the fixed measurement window, with raw warmup samples retained separately. Every in-window sample and failed repeat is retained. Reconstructed impairment settles for a fixed three seconds after installation. No fidelity tolerance or minimum count/coverage is weakened. The historical 97 ms first echo was not reproduced by the two declared legacy or two declared warm controls; its physical cause remains unresolved. Continuous-collector cadence defects and all new controls are separately documented in `COMPLETION_STAGE2.md`.

Snapshot lifetime may explicitly reach 900 seconds for the bounded coordinator; the workflow checks actual remaining streamed traffic and collector lifetimes before testing. These are finite declarations, not automatic renewal. End-to-end loss/delay remain effective bounded hypotheses with preserved untried directions/non-identifiability; queue configuration and aggregate demand are reconstructed directly from observations without reading scenario journals. Rerouting, shaping and approved QoS remain candidate families subject to unchanged physical/protected constraints. Actual all-fault qualification requires the measured report, not existence of the reconstruct/generate functions.

Version 0.9.0 adds a real second Mininet instance to the existing privileged owner. The application remains unprivileged. `artifacts/twin_validation_report.json` is the measured report; per-run reports, requests, native telemetry JSONL, SQLite indexes and process logs are in `artifacts/stage9/`. Laboratory recipe files named `ground_truth_*.json` are separate evidence used to create original experiments. They are never twin inputs.

The Stage 6 main batch remains failed at 192 accepted train windows. No verified production classifier or measured SHAP bundle exists. Snapshots explicitly record unavailable diagnosis and use the existing observed-link heuristic. This limitation does not prevent independent packet reconstruction tests; it prevents claiming completion of the full diagnosis/explanation pipeline.

Initial real batch, with the same frozen policy throughout:

| Condition | Result | Evidence |
|---|---|---|
| Healthy, correct competing QoS policy | Pass twice | Fresh twin and reset measurement passed all required metrics. |
| Saturation | Fail | Ping loss differed by 0.08333 and critical receiver loss by 0.04082, above the fixed 0.03 absolute tolerance. |
| Loss | Fail | Ping loss differed by 0.06061, above 0.03; receiver metrics passed. |
| Added latency | Pass twice | Both tested allocations of excess RTT to a single shared-link direction passed. This does not identify a unique direction. |
| QoS fault | Insufficient evidence | Goodput, UDP loss/jitter, protected TCP delivery, utilization, backlog and class rates passed; both networks received zero RTT probes. RTT values remain null. |
| Missing live receiver stream | Refused | Actual running workloads provided no complete live native receiver intervals; snapshot reconstruction was unsupported. |
| Expired snapshot | Stale/refused | Actual expiry elapsed before construction; no twin was created. |

Drift, cancellation, calibration and cleanup results, including earlier failed verification attempts, are retained in the report. The first cancellation run exposed a durable-job terminal-state defect; the storage transition was corrected and tested. The original workload in some long checks naturally reached its 100-second deadline after comparison. This is distinct from preservation evidence gathered while a run was still active; inspect each recorded traffic state.

Final checks: bounded calibration passed and was idempotent; cancellation returned a canceled job and preserved the running original; demand drift marked old results stale, scoped destruction preserved the running original, and refresh produced a distinct current snapshot. Native cross-network probes failed in both directions with no default routes. All four supervisors returned the bridge set to its initial empty state. Earlier failed cancellation and late-publication checks remain saved; they were not reclassified as successes.

Verification passed **125 regression tests** (133.57 s) and the **final 17 focused twin/API tests** (6.09 s), including the additional keyed-reset retry check. Ruff, dependency checks and installed CLI help passed. Sixteen saved immutable snapshot hashes were verified, and the Stage 9 evidence database passed SQLite integrity checking. Migration 7→8 preserved existing table counts, dataset state and membership hashes: 192 train + 10 pilot members, no test members, no production model/explanation records. Actual job submissions took 60.8–548.8 ms; maximum mean VM CPU busy fraction was 0.2324 and memory-used fraction 0.0943 across current reported comparison windows, below the 0.85 limits.

## Observable snapshot contract

`twin_spec.py` validates schema 1, a canonical SHA-256 content hash, UTC timestamps, bounded expiry and explicit field allowlists. Logical switch/host/pair names remain unchanged. Source ownership and source runtime identifiers are evidence, not identifiers to reuse.

Allowed inputs:

- Approved original definition: nominal directional capacity/delay, host access settings, logical connectivity, configured path choices and configuration version.
- Observed selected paths; operator-visible HTB class rate/ceiling, queue type/handle/packet limit and actual flower/matchall flow mapping.
- Active flow endpoints, protocol, offered bit rate, packet size and profile role.
- Recent complete telemetry window, native sample IDs, per-flow measurements and quality flags; h5–h6 probe counts and RTT.
- Existing diagnosis probabilities and uncertainty when an active verified model exists, otherwise explicit unavailability; observed suspect candidates and uncertainty.
- Stored nominal pilot IDs/reference values, fixed fidelity policy/hash, ownership, observation epoch, forwarding version, observation age and capture provenance.

The agent's ordinary network/scenario inspection is not a snapshot source. `TwinEngine.view()` creates an operator view. It does not return reserved injector locations, scenario identity, severity, schedule, seed, or active netem delay/loss/jitter. Hidden experimental keys are rejected recursively. An opaque configuration digest from the existing collector may detect changes during comparison; it cannot supply impairment parameters. No configured impairment value is copied or inferred from a hash.

Nominal references must resolve to two to four stored, suitable Stage 9 pilot windows with the same approved definition. The operator designates these as nominal; the software cannot prove health from a scenario label. Sealed test membership is refused before reading a window. Tolerances are derived from those pilot records and the configured service objective, rather than accepting arbitrary supplied reference values or tolerances.

Snapshots are immutable rows in `snapshots` and `twin_snapshots`, with unique request keys. Reusing a key with different inputs fails. A refresh creates a new ID/hash and new capture; it does not overwrite history.

## Reconstruction and uncertainty

`reconstruct()` reads only the snapshot allowlist:

1. **Demand/capacity:** sum offered demand along observed logical routes, respecting directional nominal capacities. Saturation uses fresh copies of all observed flows, including h5–h6 competing demand. Capacity stays fixed.
2. **QoS:** reproduce the observed supported s3→s5 HTB hierarchy and actual critical flower/default bulk mapping through the existing TC implementation. Unknown hierarchies, mappings or queue limits are refused. Twin provenance is distinct from the original laboratory injector journal.
3. **Effective loss/delay:** compare actual critical RTT and UDP receiver loss with the nominal pilot. A bounded hypothesis allocates all excess RTT to **one direction**, retaining the approved nominal delay. It does not divide RTT by two or assume symmetric impairment. Receiver loss is an effective independent-drop hypothesis, not a copy of the laboratory random-loss process.
4. **Path constraint:** excess h5–h6 RTT alongside critical excess RTT can constrain the shared s2–s3 segment. It still cannot distinguish directions. Lack of useful background evidence does not prove that segment faulty.

Limits are at most two constructed directional hypotheses by default, added delay ≤150 ms and effective loss ≤0.2. Heuristic leaders and their reverses are preferred; other critical-path explanations remain recorded as untried ambiguity. Existing measured queue policy or demand exceeding fixed capacity is recreated directly without adding a second inferred netem impairment solely to explain its queue outcomes. Thus combined or unfamiliar faults can fail fidelity; this is not a universal state estimator.

`calibrate` accepts a budget of 1–3 sequential trials and visits only the available bounded hypotheses. It saves each parameter set, separate actual original/twin observations, per-metric residuals, progress and a termination reason. Identical operation IDs return the stored result; changed parameters fail. There is no repair operation, output correction, throughput scaling, capacity fitting or unbounded optimizer.

## Isolation and ownership

The original NetworkManager supplies separate random runtime names, OVS DPIDs/cookies, /24 address allocations, host namespaces, interfaces, iperf processes, ports, run directories and ownership tokens. Five switches and six hosts retain their logical names. The twin has no controller or external/default route and no links to the original.

Construction verifies actual bridge port attachments and runs native namespace pings in both cross-network directions; unexpected attachments, cross reachability or default routes cause scoped cleanup. Ownership tags and interface indexes guard every TC operation and teardown. Destruction addresses a `tw`-prefixed twin registry entry, never an arbitrary instance or the source ID. There is no global `mn -c` or OVS cleanup.

Twin workloads run for a bounded 100 seconds with three seconds of warmup. Live receiver observation uses iperf3 3.20 native `--json-stream --forceflush` events, ignoring incomplete final lines. Fresh clients/servers recreate observable demand; TCP socket state, initial queue occupancy and future random drops are not cloned. Reset destroys and rebuilds only the twin with a new token and new traffic files/processes.

The privileged agent uses OS Python and stdlib modules. Application contracts, storage, aggregation and diagnosis remain in the existing venv. API shutdown cancels and destroys its owned twins while leaving the agent's original networks available; agent shutdown separately tears down the networks that agent owns.

## Fidelity policy

Matched captures use the same monotonic 10–20 second duration for original and twin; the verification batch used 15 seconds. Both original and twin workloads remain active. Existing Stage 5 aggregation converts native receiver bytes, durations and packet counts, ping RTT samples, directional/class counter deltas and queue backlog. Raw values are never clipped or adjusted. Captures can slightly overrun while a bounded observation finishes; intervals crossing the measurement boundary are excluded rather than prorated.

The two measured nominal pilots froze policy `fidelity_v1` before fault verification, hash `62cbb11d0a21f211acce8dbcfd88fb64ef812e4c2272724798f565608e5feac0`.

For each metric: `absolute_error <= absolute_floor + relative * abs(original)`.

| Metric | Engineering absolute floor | Relative term |
|---|---:|---:|
| RTT mean / p95 / variability | 5 / 10 / 3 ms | 0.25 / 0.30 / 0.50 |
| Ping and UDP receiver loss | 0.03 | 0 |
| UDP jitter | 2 ms | 0.50 |
| Critical goodput / critical class rate | 100,000 bps | 0.15 |
| Bulk class / protected flow goodput | 100,000 bps | 0.20 |
| Shared and QoS utilization | 0.10 | 0 |
| Queue backlog | 65,536 bytes | 0.50 |

Absolute floors also consider twice the measured pilot range and 5% of the RTT service objective. Fixed caps reject overly variable pilots. The initial pilot raised the backlog absolute term to 87,812 bytes. Metrics unavailable in a pilot use the engineering floor and report a null pilot range. These tolerances were not changed to pass failed fault classes.

Required metrics include critical RTT mean/p95/variability, ping loss, receiver goodput, relevant utilization/backlog, UDP receiver loss/jitter where supported, observed child-class rates, and all active protected bulk/background receiver rates and UDP loss. Missing metrics, insufficient coverage, incompatible duration or missing resource observations prevent a pass. Protected flow coverage must also meet the fixed threshold. A lost ping is not zero RTT. TCP interval packet loss is unavailable; protected TCP goodput is required, UDP packet loss is required where supported.

Results store actual sample/packet/probe counts, receiver durations and coverage. Binomial loss standard errors and RTT mean standard errors are descriptive; correlated drops/probes violate independence assumptions. Small probe counts can cause genuine failed comparisons under the strict frozen loss tolerance. A pass is specific to the tested workload, snapshot age and hypothesis, not proof of fault causality or future repair safety.

## Freshness, resources and failure handling

Snapshots expire after 10–300 seconds (default 180). Fingerprints cover approved topology, observed paths, queue policy/mapping and active offered workload; ownership token changes are stale. Collection configuration transitions and changed opaque observation digests also prevent current fidelity. Status reports current validity separately from saved historical results. Retrieving an idempotent trial retains its original historical verdict; inspect current status before reuse. A drift/expiry refusal needs an explicit new snapshot. Refresh is not automatic.

The original and twin share the WSL kernel/VM. The detected budget was eight CPUs and at least 1 GiB available memory. Only one live twin is permitted. Construction records CPU count/available memory; captures record CPU ticks and memory pressure, with 0.85 pressure limits. Contaminated or missing-resource trials cannot pass. Outer Windows host pressure is not measured. VM isolation is dataplane isolation, not hardware isolation.

Long operations are durable jobs and immediately return a job ID. `GET /v1/twins/{id}` exposes constructing/current/stale ownership and persisted trials. Cancellation bypasses the orchestration lock, sets the agent event and schedules scoped destruction. The worker records canceled jobs as canceled and continues processing. Partial construction uses the same scoped teardown. On service restart, interrupted trials become failed and cached active twins are cleaned, with ownership failures retained for explicit cleanup. Root ownership journals survive application failures.

## Commands and reproduction

Run from `/mnt/c/Users/Dell/Desktop/CN project` in Ubuntu WSL. Initialize/migrate an existing database without deleting it:

```bash
.venv/bin/python -m explainnet.cli --config config/example.yaml init
sudo env PYTHONPATH=src python3 -m explainnet.agent_server \
  --allow-uid 1000 --socket /run/explainnet/agent.sock \
  --state-dir /var/lib/explainnet-agent --stream-receivers
.venv/bin/python -m explainnet.cli --config config/example.yaml serve
```

The ordinary agent default remains compatible with end-only receivers. For twin comparison, explicitly streamed traffic or the agent's scenario streaming default is necessary. Start fresh original workloads before taking pilots/snapshots; the verification harness shows the complete bounded procedure.

For ordinary workloads, use `explainnet --config /absolute/config.json traffic-start original_id --duration 100 --stream-receiver`. `POST /v1/traffic/start` accepts the same `stream_receiver: true` flag. An explicitly false profile supports end-only observation and will be refused for a live twin comparison requiring receiver metrics.

Actual real verification supervisor commands used:

```bash
sudo env PYTHONPATH=src python3 scripts/check_twin_stage9.py
sudo env PYTHONPATH=src python3 scripts/check_twin_stage9.py artifacts/stage9/0c234087/report.json
sudo env PYTHONPATH=src python3 scripts/check_twin_stage9.py artifacts/stage9/e855e2b8/report.json recovery
sudo env PYTHONPATH=src python3 scripts/check_twin_stage9.py artifacts/stage9/fc06cf91/report.json timing
```

The root supervisor launches the restricted agent and an ordinary UID 1000 API/driver. It selects only fresh train recipes, uses a separate Stage 9 database, and checks scoped bridge cleanup. It does not resume/export/train/evaluate the Stage 6 batch. Historical reports remain in each run directory, including failures and corrections.

Typed operations and installed CLI:

```bash
explainnet --config /absolute/config.json twin-snapshot /absolute/snapshot_request.json
explainnet --config /absolute/config.json twin-construct /absolute/construct_request.json
explainnet --config /absolute/config.json twin-measure /absolute/measure_request.json
explainnet --config /absolute/config.json twin-reset /absolute/reset_request.json
explainnet --config /absolute/config.json twin-calibrate /absolute/calibrate_request.json
explainnet --config /absolute/config.json twin-status tw_example
explainnet --config /absolute/config.json twin-cancel tw_example
explainnet --config /absolute/config.json twin-destroy tw_example
explainnet --config /absolute/config.json job j_returned_job_id
```

Concrete executed request files are saved in `artifacts/stage9/0c234087/healthy_{snapshot,construct,measure,reset}_request.json` and later verification directories. Their network IDs are historical; replay needs new running originals and new snapshots.

These map to `POST /v1/twins/{snapshot,construct,measure,reset,calibrate,destroy,cancel}`, `GET /v1/twins/{twin_id}`, and `GET /v1/twins/snapshots/{snapshot_id}`. Snapshot bodies contain `instance_id`, unique `request_key`, `baseline: {window_ids, definition_hash}`, the exact frozen `policy`, duration and expiry. Construct bodies contain `twin_id`, `snapshot_id`, optional hypothesis ID; measure bodies add a unique trial ID/duration. Reset optionally selects another available hypothesis. Calibration adds an operation ID and maximum trials.

For reset retries, supply a stable optional `request_key`: repeating it returns the saved reset result and changed inputs fail. An unkeyed explicit reset requests another fresh rebuild. Historical keyed results need a separate current-status check before reuse, like stored trial results.

## Stage 10 gate

Measured healthy and latency cases provide limited eligibility for subsequent isolated twin experimentation with fresh suitable snapshots. Saturation and loss require adequate fidelity under the frozen policy, and the tested QoS fault requires suitable RTT evidence. Expired, drifting, missing or contaminated states are ineligible. The full production pipeline still requires Stage 6 completion and measured Stage 7/8 model/explanation verification. Stage 9 performs no candidate repair ranking, original repair, remediation or dashboard work.
