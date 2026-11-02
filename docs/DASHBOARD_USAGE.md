# Dashboard implementation and usage

## Stage 14 current integration

Use `scripts/manage_app.py --config artifacts/stage6/runtime/config.json start|status|stop` for owned ordinary-user lifecycle management. The original foreground launcher below remains supported. `PROJECT_STATUS.md` supersedes historical readiness counts; `DEMO_GUIDE.md` gives live/recorded walkthroughs and cleanup. Dataset/model/validation SHAP readiness is now established, while trained-model original actuation remains unqualified.

Recovery reads `/v1/dashboard/applicable/{workflow_id}` for the current backend prerequisite reason. The preview does not save a workflow or submit an action; backend application repeats its checks. Read-only workflow retrieval shows actual completed SHAP only with matching model/window lineage. The evidence allowlist includes Stage 13 evaluation and Stage 14 integration. All six pages are checked against actual canonical and isolated rehearsal backends with unchanged job/audit counts and control mode; browser/pixel QA is not claimed.

The normal interface is the six-page Streamlit app at `http://127.0.0.1:8501`. Launch with:

```bash
.venv/bin/python scripts/launch_dashboard.py --config artifacts/stage6/runtime/config.json
```

The launcher derives the API URL from the existing configuration. `--api-url` accepts a loopback HTTP override; `--port` changes the UI port. `EXPLAINNET_API_URL` configures the client when Streamlit is invoked directly. The backend, OS-Python privileged agent and UI have separate lifetimes. See the root README for exact commands and the teacher walkthrough.

## Presentation and sources

Light/navy/teal styling, readable cards, compact tables and progressive JSON details are shared across pages. Plotly/NetworkX render an actual inspected definition; no old topology or capacity is substituted when live ownership is unavailable. Stored receiver/probe/counter windows drive charts. UTC times and provenance accompany measurements; RTT/jitter use ms, rates bps, and loss/utilization are stored as fractions and explicitly converted to percent for display. Missing measurements remain unavailable or chart gaps. Historical sources are separately selectable and never become mutation targets.

Readiness distinguishes the API, privileged owner, current originals, complete quality-audited main dataset, activated model, actual ready explanation count and per-experiment twin/fidelity gates. Main-database records and earlier validation artifacts are separate views. A registered model is not assumed activated or compatible. Calibrated confidence is displayed only when the prediction explicitly reports calibrated probability status. SHAP must be ready for the same observation and a model present in its actual diagnosis history. Heuristic scores are never relabeled probabilities.

The twin table includes the no-change treatment, actual measured trials, RTT/delivery, backend feasibility proof, action cost, conservative score and backend rejection reasons. Current retrieval reuses the existing service's freshness checks. Original post-action windows and application-overlap disruption appear under Recovery; they are not presented as twin measurements.

## HTTP and mutation boundaries

`dashboard/client.py` centralizes loopback configuration, connect/read timeouts, maximum response size, JSON/response validation and actionable errors. It has no subprocess or Mininet access. `presentation.py` contains display transformations and intent receipts; it does not diagnose, rank, qualify or execute repairs.

Migration 11 adds `job_idempotency` with an operation/input hash and unique durable job receipt. The existing job submission route accepts `Idempotency-Key`; check/insert and job creation are transactional. Identical retries return the same job, conflicting reuse is rejected, and existing coordinator/dataset locks remain effective for new requests. Startup does not replay claimed jobs. A UI intent is latched before network I/O and kept across reruns. Polling is read-only; mutations are never automatically retried. A user can explicitly retry an unresolved intent with the same key.

Mutation forms run only on intentional submit. Repair, auto-repair, observed-only enablement and teardown require confirmations. Requested mode/exception controls do not change the backend until submitted; actual mode is always read separately. Stop/cancel retain their existing direct, responsive and semantically idempotent endpoints. Long work stays in existing jobs/coordinator threads. Refresh is opt-in every ten seconds using a Streamlit fragment, with no busy loops. Request activity displays rejection, failure, interruption and unknown outcomes without automatically resubmitting.

Undo is enabled only after a backend readback identifies a kept action whose current owned configuration matches its recorded after-state. The actual Undo still rechecks applicability. No UI checkbox bypasses server ownership, freshness, model, fidelity, qualification, concurrency or rollback checks. Failure hooks, arbitrary commands, external repair, dataset campaigns, model training and calibration campaigns are not exposed.

## Small backend additions

- `/v1/dashboard/status`: bounded structural counts/readiness, owned inventory, current mode and configured traffic profile IDs.
- `/v1/dashboard/records/{collection}`: closed collection enum and bounded recent metadata for jobs/audit/incidents/snapshots/twins/experiments/workflows/actions.
- `/v1/dashboard/telemetry-sources`, `/telemetry/{instance_id}`, `/windows/{window_id}`: stored observations and rule support, excluding sealed test membership before measurement payloads are read.
- `/v1/dashboard/submissions/{key}`: recover a durable job receipt without retrying a mutation.
- `/v1/dashboard/reversible/{instance_id}`: read-only current kept-state applicability.
- `/v1/dashboard/evidence` and `/{artifact_id}`: closed allowlist of existing report summaries. Unknown IDs, traversal and symlinks are rejected. Native payloads, credentials and local filesystem paths are removed; files are size-bounded and cached by mtime. No arbitrary filesystem read/download interface exists.
- Detailed network inspection now includes its actual validated definition, and inventory reports original/twin role. These are inspection metadata additions, not new mutation operations.

## Current gates and evidence

The repository database was inspected rather than assuming old reports were current. At Stage 12 implementation it contained 192 train + 10 pilot accepted windows, a failed/incomplete main batch, zero production bundles, zero ready explanations and no current incidents/actions. Existing candidate/twin/recovery reports document historical conditional UDP latency evidence. No dataset, training, calibration or repair campaign is required or launched by this stage.

Software fixtures in `tests/test_dashboard.py` exercise empty and populated pages, transport failures, confirmation/idempotency, sealed-data exclusion, reversible-state checks and model/window-scoped explanation presentation. Fixture output is not saved as live network evidence. `scripts/check_dashboard_stage12.py` verifies real read-only API integration, actual stored history/evidence, all six AppTest pages, the navigation entrypoint, unchanged job counts/mode and the running Streamlit health endpoint.

Browser inventory was empty, so browser automation and pixel/screenshot verification were unavailable. Supported Streamlit AppTest is used instead; layout styling is implemented but pixel-level visual verification is explicitly not claimed. The generated `artifacts/dashboard_validation_report.json` records actual checks and live-integration limitations.

Framework references: [Streamlit multipage navigation](https://docs.streamlit.io/develop/concepts/multipage-apps/page-and-navigation), [bounded fragment refresh](https://docs.streamlit.io/develop/concepts/architecture/fragments). Installed APIs were also inspected locally (Streamlit 1.65.0).


## Recorded verification (2026-10-16)

- 52 focused UI/client/backend regression checks passed in 131.01 seconds. Additional targeted retry/navigation checks passed, followed by four final confirmation/ambiguous-response checks in 75.68 seconds. Cold AppTest startup uses a bounded 60-second allowance; application network timeouts were not loosened.
- Actual registered navigation across all six pages passed against the existing backend. AppTest reported no page exceptions or normal-interface errors. The Network page correctly warned that the latest stored window had configuration transitions and insufficient coverage; it was not represented as inference-ready.
- Read-only integration found 45 historical telemetry sources, fetched ten actual windows from the latest source, and loaded all six approved evidence summaries. Mode and job counts were unchanged by page rendering. Current mode was Recommend, auto-repair off, observed-only exception off.
- Migration 10 to 11 preserved every existing count, dataset state and train/pilot membership digest. Both API/UI run unprivileged and listen on 127.0.0.1; final HTTP health checks passed. Editable metadata is 0.12.0, Ruff passed, and pip reported no broken requirements. No new runtime package was installed.
- The privileged agent was unavailable and no current original network existed in the connected backend. Live topology, actual mutation/repair, trained inference and real SHAP were therefore not exercised in this stage. Their UI branches use explicitly labeled software fixtures where applicable. Historical reports remain experiment evidence from earlier stages.
- Browser automation returned no available browser. No pixel-level review or screenshots are claimed. Streamlit AppTest verified pages, navigation, widget confirmation and duplicate behavior.

Final local services remain available at dashboard http://127.0.0.1:8501, API http://127.0.0.1:38223, and Swagger http://127.0.0.1:38223/docs. The canonical validation report and final audit are `artifacts/dashboard_validation_report.json` and `artifacts/stage12/final_audit.json`.
