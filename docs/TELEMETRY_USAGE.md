# Stage 5 telemetry

ExplainNet Twin 0.5.0 collects real observations through the typed root agent. The application owns storage, windows and rule-based monitoring. Collection reads the dataplane and sends bounded modest ping probes; it does not modify forwarding, queues, capacities or faults.

## Collection and queries

Run inside WSL from the project directory. Initialize schema 3, then launch the agent and ordinary-user API as documented in `ARCHITECTURE.md`.

```bash
.venv/bin/explainnet --config config/example.yaml init
.venv/bin/explainnet --config config/example.yaml network-start pilot
.venv/bin/explainnet --config config/example.yaml job JOB_ID
.venv/bin/explainnet --config config/example.yaml telemetry-start pilot --duration 180
.venv/bin/explainnet --config config/example.yaml traffic-start pilot --profiles critical bulk --duration 40
.venv/bin/explainnet --config config/example.yaml telemetry-status pilot
.venv/bin/explainnet --config config/example.yaml telemetry-windows pilot
.venv/bin/explainnet --config config/example.yaml telemetry-latest pilot
.venv/bin/explainnet --config config/example.yaml telemetry-reference QUALIFIED_WINDOW_ID
.venv/bin/explainnet --config config/example.yaml telemetry-alerts pilot
.venv/bin/explainnet --config config/example.yaml telemetry-stop pilot
.venv/bin/explainnet --config config/example.yaml network-stop pilot
```

Poll each mutation's returned job ID before depending on completion. Traffic submission launches a separate run; receiver measurements arrive at run completion. Start collection before traffic. One collector is allowed per instance; identical active requests are idempotent. Collection duration is bounded to 25..600 seconds. Shutdown joins collectors. Restart marks lost collectors interrupted rather than presenting stored data as live.

HTTP mutations: `POST /v1/telemetry/start` with `{"instance_id":"pilot","duration_s":180}`, `/stop` with the instance, `/reference` with `{"window_id":"..."}`. They return HTTP 202/job IDs. GET: `/v1/telemetry/pilot/status`, `/latest`, `/windows?limit=100&ready_only=true`, `/alerts`. Queries include observation time and freshness; stopped/unavailable/overdue collectors report stale while history remains queryable.

Reuse scenarios from `SCENARIO_USAGE.md`. The Stage 4 default eight-second measurement is too short for a stable ten-second window. Real telemetry pilots used two-second omitted warmup, twenty-second measurement, and explicitly configured one-window alert/recovery persistence. Shipped defaults remain two consecutive windows, verified by tests. Short fault trials under defaults may show pending violations.

## Feature schema 1

The exact 21-column allowlist lives in `telemetry_contracts.FEATURES`. Windows record its version/hash. IDs, times, configuration/path/run context, quality and provenance are metadata. Injector labels, severity, intended locations and schedules are excluded; the collector does not read experimental truth.

| Columns | Unit/source |
|---|---|
| `rtt_mean_ms`, `rtt_p95_ms`, `rtt_variability_ms` | ms; individual ping replies, nearest-rank p95, population standard deviation |
| `ping_loss_fraction` | total transmitted minus received / transmitted |
| `udp_loss_fraction` | summed native receiver lost packets / summed receiver packet counts |
| `critical_goodput_bps` | receiver bytes × 8 / actual eligible interval duration |
| `udp_jitter_ms` | latest eligible native receiver jitter estimator; separate from RTT variability |
| `shared_utilization_fraction`, `qos_utilization_fraction` | directional TX byte delta × 8 / monotonic elapsed / physical capacity in bps |
| `shared_drop_rate_pps`, `critical_drop_rate_pps`, `bulk_drop_rate_pps` | supported netem leaf drop deltas / elapsed seconds |
| `critical_class_rate_bps`, `bulk_class_rate_bps` | actual HTB class bytes × 8 / elapsed seconds |
| `queue_backlog_bytes` | compatible peak backlog; root/leaf maximum avoids nested double counting |
| `offered_demand_bps`, `critical_offered_bps` | configured pacing demand of observed active clients, not receiver delivery |
| `active_flow_count`, `primary_path_fraction` | active profile count and selected pair primary-route fraction |
| `cpu_busy_fraction`, `memory_used_fraction` | Linux VM CPU tick deltas and MemAvailable/MemTotal |

Multiply fractions by 100 for display percentages. Directional interface/OVS bytes and packets, per-flow TCP/UDP rates/loss, invalid deltas and source IDs remain in observation/window metadata. TCP does not fabricate UDP loss/jitter. Missing HTB children have null class features with reasons. CPU/memory measure WSL Linux, not outer Windows.

Installed iperf3 3.20 emits server receiver JSON at completion. Preserve native interval boundaries, bytes/counts/jitter, availability time and native receiver epoch aligned to the local monotonic clock. Missing native epoch/receiver intervals are unavailable. Omitted warmup intervals and sender summaries are excluded. No whole-session summary is repeated across windows. Late receiver intervals update pending windows and recompute monitoring chronologically.

## Timing, storage and quality

Defaults: one-second sampling, three small bounded probes, non-overlapping ten-second windows anchored to collector monotonic start. Only wholly contained intervals contribute; no prorating/interpolation across boundaries or transitions. Interface counters have capture times. UTC is for display; monotonic deltas determine rates. Clock discontinuities invalidate affected windows.

Raw JSONL: `<data_dir>/raw/telemetry/<collector_run_id>.jsonl`. SQLite indexes IDs, source, UTC, byte offset, configuration and content SHA256. Append/fsync precedes transactional indexing. Duplicate IDs require identical content. Recovery indexes complete orphan lines and saves/truncates only an incomplete tail; corrupt complete lines raise errors. Migration 3 adds collector/sample/window/reference/alert tables. `inference_ready_windows` exposes exact allowlisted feature JSON with separate provenance IDs.

Required readiness: complete window, at least 65% compatible counter coverage, six transmitted valid probes, valid shared utilization, and 65% receiver duration when critical offered demand reaches 100 kbps. All-lost ping batches have measured loss and null RTT. Optional jitter, QoS counters and absent classes do not invalidate every window. Pending receiver data, partial windows, path/configuration/traffic/interface/agent transitions, resets and resource contamination carry reasons. CPU/memory gates default to 95%.

Values are never silently clipped. Invalid elapsed times, decrements and utilization above physical capacity retain raw quotients and reasons. Invalid required shared utilization excludes the window. Inconsistent optional QoS utilization becomes null with a warning; valid receiver/class evidence can still qualify. Short HTB bursts exposed this in the real QoS pilot. Coverage, successful probes, timeouts, resets, missing metric reasons and stale age are explicit.

## Rule-based baseline

Rules use configured RTT/loss/jitter objectives where available, shared utilization (90%) and delivered/offered ratio (80%) above the 100 kbps demand floor. Absolute minimum goodput is checked only when offered demand meets that objective. An explicitly selected completed ready reference must satisfy service rules and have measured RTT; RTT p95 ceiling is the stricter of the objective and reference p95 plus 15 ms. Qualification uses observations, not labels.

Default alert persistence/recovery each require two valid consecutive windows. Recovery uses a 0.9 hysteresis factor. Invalid windows interrupt consecutive evidence. Status is healthy, alert, insufficient-data or stale, with pending violations, actual metrics, units, thresholds, affected flow/link and limitations. No trained diagnosis, confidence or definitive root cause is claimed.

## Evidence and reconstruction

`artifacts/telemetry_smoke_report.json` contains real API/CLI/worker/agent trials, references, all four faults/resets, quality and final checks. `artifacts/stage5/measured_summary.json` is the compact summary. Two archives retain unchanged raw JSONL, SQLite, native traffic output and separate experimental journals. Derived archived windows were refreshed after feature/quality fixes; subsequent replay without refresh matched all final values. Raw packet evidence was never edited.

```bash
.venv/bin/python scripts/reconstruct_telemetry_stage5.py --data-dir artifacts/stage5/raw_and_storage_1fce27cc/app/data
.venv/bin/python scripts/reconstruct_telemetry_stage5.py --data-dir artifacts/stage5/raw_and_storage_2c4fa76c/app/data
```

Replay verified 732 records, 33 windows and 14 ready windows across seven bounded collections. Partial/transition/pending windows remain stored. Synthetic unit fixtures are identified separately from real packet evidence. No full training dataset or later-stage model, SHAP, twin, repair or dashboard was created.
