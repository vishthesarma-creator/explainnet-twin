> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# Stage 6 experiment collection

Completion3 (28 October2026): legacy `expansion_v1` repeats compact recipe signatures/seeds. Separately declared `artifacts/completion_stage3/schedule.json` reserves600 new episodes/60families/3600 accepted windows,2400/600/600 plus a separate qualified10-window pilot. Actual running/resumable status and exact PowerShell commands: `COMPLETION_STAGE3.md`. Do not pool the examined old holdout or count pilot/debug windows toward3600. Collection readiness does not qualify per-fault reconstruction/repair.

The runner reuses the root network/traffic/scenario agent, application telemetry and durable job worker. Collection is sequential under an application experiment lock and a per-user Linux process lock. An independent network instance is created per episode attempt. Only exact owned instances are reset/stopped. General shell commands, global Mininet cleanup and later repair operations are not used.

## Reserved schedules

`config/datasets/pilot_v1.json`: five independent episodes, two accepted ten-second windows each, all five classes, separate `pilot` partition. `main_v1.json`: 60 episodes / 360 target windows. Each class has six recipe families with two repetitions: four train, one validation, one test. The resulting 40/10/10 episodes explicitly adjusts the suggested 60/20/20 to **66.7/16.7/16.7%** to retain eight training episodes per class and keep related repetitions together. All baseline/recovery observations inherit their episode partition. Evaluation has reserved load/packet-size/direction combinations; no class is omitted from training.

`expansion_v1.json`: optional 600 episodes / 3,600 windows. It is a declaration only and is never launched automatically. Inspect schedule JSON before submission. `scripts/plan_dataset_stage6.py` deterministically regenerates these declarations and prints hashes/counts/runtime estimates; it does not collect data. Changing a declared schedule requires a new schedule ID/version. Existing IDs reject incompatible hashes or application configuration.

The versioned `dataset_v1` scenario extension permits 4..100 measurement seconds, bounded critical demand, bulk TCP/UDP, packet sizes 600..1400 and supported netem seeds. The original `pilot_v1` remains limited to 20 seconds and retains its original defaults. Native traffic requests remain bounded, now to 100 seconds. Location is restricted to existing s2→s3 shared impairment and s3→s5 QoS; loss/delay may also use s3→s2. No unsupported arbitrary location is claimed.

Each compact episode declares 85 measurement seconds to obtain six suitable ten-second windows after settling and alignment. Two-second native omission precedes measurement, with five-second conservative settling after actual activation/warmup. Baseline and recovery each measure eight seconds and verify native critical receiver service. Warmup/control/transition/reset/partial/invalid/surplus windows are excluded from the steady membership table. Labels use actual successfully applied/reset receipts, not submission time. A failed injection never receives accepted fault membership.

## Start, query, cancel and resume

Inside WSL from the project directory, initialize schema 5 and run the existing ordinary-user API/root agent. Migration 4 stores datasets; migration 5 distinguishes internal runner jobs so the experiment lock also prevents unrelated laboratory mutations and cancels orphan queued runner operations after restart. With those services available:

```bash
.venv/bin/explainnet --config CONFIG init
.venv/bin/explainnet --config CONFIG dataset-plan config/datasets/pilot_v1.json
.venv/bin/explainnet --config CONFIG job PLAN_JOB_ID
.venv/bin/explainnet --config CONFIG dataset-start BATCH_ID
.venv/bin/explainnet --config CONFIG dataset-status BATCH_ID
.venv/bin/explainnet --config CONFIG dataset-cancel BATCH_ID
.venv/bin/explainnet --config CONFIG dataset-resume BATCH_ID
.venv/bin/explainnet --config CONFIG dataset-export BATCH_ID
```

Mutation commands return prompt job IDs. `dataset-start` succeeds when a separately checkpointed collection thread starts; it does not mean the dataset is complete. Cancellation sets a signal, waits for any in-flight mutation, then performs owned restoration and cleanup. Failed/interrupted/canceled batches require explicit resume. Verified completed episodes are skipped after raw/hash/member audits. Interrupted attempts undergo owned cleanup and use a new attempt/collector ID; raw evidence is retained. The predeclared maximum is two attempts per episode, including interrupted attempts. Exhaustion or failed cleanup is an explicit shortfall, never duplicate membership or a silently missing class.

HTTP routes: POST `/v1/datasets/plan` with `{"schedule":...}`, `/start`, `/resume`, `/cancel`, `/export` with `{"batch_id":"..."}`; GET `/v1/datasets/{batch_id}`. Existing `/v1/jobs/{job_id}` tracks submissions. Episode actions themselves use the existing durable network/scenario/collector jobs.

The persistent supervisor used for actual collection starts the root agent with Linux-owned journals and launches the API as UID 1000. From PowerShell:

```powershell
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- env PYTHONPATH=src python3 scripts/dataset_supervisor.py --schedule config/datasets/pilot_v1.json --runtime artifacts/stage6/runtime --uid 1000 --detach
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- env PYTHONPATH=src python3 scripts/dataset_supervisor.py --schedule config/datasets/main_v1.json --runtime artifacts/stage6/runtime --uid 1000 --detach
```

Run main only after the pilot has completed and its quality/restoration checks pass. Do not launch another supervisor against the same runtime while collection is active. The supervisor owns agent/API subprocesses and checks the runner periodically; conversational polling is unnecessary. It writes actual PIDs, batch/job IDs, counts and terminal cleanup to `artifacts/stage6/runtime/supervisor.json`. Collection survives the initiating terminal/tool call, but a WSL shutdown interrupts it.

Use the offline checkpoint reader during or after collection:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/dataset_status_stage6.py --runtime artifacts/stage6/runtime
```

During collection, CLI queries/cancellation use `--config artifacts/stage6/runtime/config.json`. After interruption/failure, restart the supervisor with `--schedule config/datasets/main_v1.json --runtime artifacts/stage6/runtime --uid 1000 --resume BATCH_ID --detach`. Keep the same application configuration and state directory. Terminal successful batches shut down the owned API and agent; the offline reader and manifest remain available. Agent journals live at the Linux path recorded in `supervisor.json` and are copied to a workspace root archive on terminal shutdown.

## Authoritative export and readiness

Exports are under `<data_dir>/datasets/<batch_id>/`. `manifest.json` is authoritative and includes schema/configuration hashes, feature column allowlist, units, actual counts, raw/export file SHA256 checksums and collection parameters. `artifacts/dataset_manifest.json` points to that main manifest; pilot reports are separate. Export updates after every completed episode and terminal state. The dataset card also updates from actual main counts. During the active batch, query those automatic checkpoints; use an explicit export command after collection stops or completes.

- `features.csv`: `window_id` metadata followed by exactly the 21 established numeric features. Null CSV fields are empty, not imputed zeros.
- `labels.jsonl`: separate window/episode-linked labels, actual activation/reset times and injection configuration.
- `splits.json`: reserved episode/family assignments and accepted window membership. Control phases inherit the same assignment.
- `provenance.jsonl`: UTC/monotonic interval, raw path, source observation IDs, stored-window hash and quality/context.
- `episodes.jsonl`: all attempts, baseline/recovery native results, receipts, raw hashes, errors and cleanup state.
- `schedule.json`, `quality_report.json`: exact declared parameters, structural checks, counts, missingness, rejected reasons and explicit shortfalls.

Structural audits verify feature schema/units/numeric finiteness, unique IDs, raw/index alignment, feature reconstruction, valid steady phase and separate ground-truth agreement, complete class/episode coverage, and no episode/family/raw-measurement overlap across partitions. They do not perform exploratory test-feature analysis. Scenario names, IDs, schedules, seeds, filenames and partitions are not model inputs. No oversampling, perturbation, imputation, normalization, feature selection or model training occurs.

`dataset_ready: true` requires a completed **main** batch with all declared episode targets and passing required checks. A passing pilot or partial running batch is insufficient for Stage 7. See `DATASET_CARD.md` and `artifacts/dataset_quality_report.json` for current actual readiness. Existing dependencies are retained; the current TestClient deprecation warning remains.
