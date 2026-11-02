> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# Completion Prompt 1: operation and lifecycle stabilization

Implementation date: 28 October 2026 IST (execution receipts use UTC).
Scope: lifecycle, bounded transport, non-mutating reads, explicit profiles and persistent controls. No Prompt 2 diagnosis changes, dataset expansion, retraining, fault-repair campaign, scale benchmark or visual redesign.

## Recoverable checkpoint and preservation

`artifacts/completion_stage1/checkpoint.json` records the source/configuration ZIP, file hashes and initial Git status. The workspace was entirely untracked, so Git HEAD was not a recoverable baseline. A supplemental ZIP preserves pre-edit test content by reversing the three recorded test edits; its text is newline-normalized. These are source checkpoints, not database/runtime backups. Restore only with services stopped and after reviewing the manifest; never overwrite models or evidence directories.

Both existing databases, root journals, native files, model registration, sealed members and failed jobs remain in place. Original audit files are preserved; this document is the dated operational addendum. Historical fidelity failures and trained-path limitations are not relabeled as successes.

## Root causes and contracts

### Execution and ownership

`workflow_service.py` separates `latest_workflow_id` from `active_workflow_id`. The execution wrapper finalizes after saving results and waiting for cancellation cleanup. Its finalizer checks both workflow identity and thread identity, so an older worker cannot clear a newer owner. Request-key/workflow-ID conflicts and duplicate pending applications are checked before launch.

An execution result becoming terminal is not permission to tear down an action or an unfinished twin. Interrupted/degraded actions and failed/pending twin cleanup retain explicit blockers. Cancellation sets events; Stop Automation prevents new application while verification/rollback completes. Undo reserves ownership without holding the coordinator lock across the root RPC, keeping Stop responsive.

Startup disables automatic repair and observed-only consent, cancels abandoned queued mutation jobs, reads back interrupted action/twin state and records interruption. It does not replay application, rollback or twin destruction. `POST /v1/lab/reconcile` inspects outcomes. `POST /v1/lab/actions/ACTION_ID/rollback` is an explicit operator rollback of an interrupted action. Pending owned twin destruction uses the existing `/v1/twins/destroy` job, followed by read-only reconciliation. No database field needs manual clearing.

### Transport and evidence

The old traffic exception did not cover scenario reset, which embedded full native runs. Protocol 2 now returns a typed acknowledgement (`ack_version`, operation, outcome, bounded result projection and integrity reference). Wire frames are capped at 256 KiB; evidence pages contain at most 48 KiB of native bytes, base64 encoded. Hydration is independently capped at 32 MiB. Full native JSON remains preserved, never silently truncated.

Control acknowledgements/evidence and RPC intents are persisted under the selected root owner's `response_evidence/` and `rpc_receipts/`. Repeating a completed RPC identity returns its acknowledgement. A pending RPC after failure is an unknown outcome and cannot execute again. Worker job identity supplies stable RPC identity. Protocol negotiation uses a read-only version-1 health request before any mutation; old owners retain their documented version-1 limits until deliberately upgraded. There is no mutation fallback/retry between versions.

Read acknowledgements use a bounded 64 MiB memory cache, without journal/database writes. Hash-addressed read caches can expire; refresh the source to obtain a new reference. The client validates frame terminators, size, protocol/request/operation identity, JSON/schema, chunk offsets, total length and final SHA-256. Malformed, oversized and truncated replies remain failures.

Large HTTP reads use a compact version-2 projection and `/v1/evidence/SHA256?offset=OFFSET`; full job evidence is available through `/v1/jobs/JOB_ID/evidence?offset=OFFSET`. Job details remain complete in SQLite. Normal reads fit well below the dashboard's unchanged 4 MB budget. Oversize details are explicitly marked as evidence-only.

A failed acknowledgement does not establish failure of the physical operation. Worker failure records say `requires_reconciliation`; network read-back is attempted without replay. UI activity retains the failed job and offers explicit owner reconciliation before a new intent. The session helper durably records submission keys before HTTP, inspects actual root state before renewal and refuses untracked running traffic after a lost acknowledgement.

### Read-only status and renewal

Network, traffic and scenario GETs no longer write cached rows; twin status no longer saves its projection. Root network inspection projects lost ownership without saving a changed journal. Explicit `POST /v1/laboratory/reconcile` updates only the selected instance's cache and existing run/scenario records from the privileged owner. It never starts, stops or replays a resource.

Healthy renewal checks coordinator/action/actual scenario state before stopping a collector or traffic. It refuses a fault, repair verification, interrupted action or untracked running traffic. Cleanup checks actions and ownership, reconciles the selected instance and skips an already-restored scenario. A new preparation creates fresh session/network/run/collector identifiers. Current-run window selection and rule freshness cannot promote previous-collector measurements. Collector status reports bounded UTC expiry, monotonic remaining time and expiration.

## One normal application entry point

Use ordinary Windows PowerShell in the project directory:

```powershell
function en { wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/app.py @args }
en start
en status
```

`trained` is the default profile: dashboard **http://127.0.0.1:8501**, API **38223**, configuration `artifacts/stage6/runtime/config.json`, existing Stage 13 Linux model/evidence store. The existing trained model remains active. Its full recovery integration is still unqualified and belongs to Prompt 2.

The explicitly selected laboratory profile uses the same launcher:

```powershell
en --profile observed-only start
en --profile observed-only status
```

It opens **http://127.0.0.1:8502**, API **43989**, configuration `artifacts/stage14/rehearsals/bb745a91/config.json`, its separate Stage 14 store/owner. It has no trained model and says **observed-only**. No stores, model rows or ownership journals are copied/merged. Startup never enables the exception. The UI shows the profile, mode, model availability, and optional technical API/store/configuration identity. Launcher, UI environment and API hashes must agree; conflicting API overrides are refused.

Start the separate privileged owner only when needed, using OS Python:

```powershell
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- /usr/bin/python3 scripts/manage_agent.py --profile trained start
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- /usr/bin/python3 scripts/manage_agent.py --profile observed-only start
```

The root helper checks exact PID/start-tick/UID/cwd/argv identity. Stop refuses nonterminal owned networks and unsettled actions; it never runs global cleanup or force-kills a pending owner. Existing healthy owners are reused. New owners refuse stale journals requiring reconciliation.

### Healthy laboratory commands

```powershell
function demo { wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/teacher_demo_session.py @args }
demo status
demo renew
```

Renewal is intentional and bounded: traffic 900 seconds, collector 600 seconds. It does not remove a fault or reset repair verification. `demo fault` and `demo recommend --observed-only` remain separate deliberate stages with their existing gates; no fault or recommendation eligibility was qualified in this stage.

For a **fresh** original after reviewing that actions/Undo are settled:

```powershell
demo cleanup
demo prepare
demo status
```

Cleanup is explicit, selected-session only. Preparation captures healthy reference measurements; it is not a dataset expansion or model-training command. On failure retain the receipt and inspect the saved job/request IDs; do not generate a different request to bypass an unknown outcome.

### Stop after use

```powershell
demo cleanup
en --profile observed-only stop
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- /usr/bin/python3 scripts/manage_agent.py --profile observed-only stop
en stop
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- /usr/bin/python3 scripts/manage_agent.py --profile trained stop
```

Clean/reconcile any selected trained original first if one has since been created. App stop finishes verification/rollback and stops collectors, but does not automatically tear down a laboratory owned by the separate agent. These launchers detach their services: no foreground terminal must remain open, but WSL must remain running. Traffic/collectors expire; original networks persist until explicit cleanup.

## Shared shell and refresh

All six existing pages remain. They are registered only through `st.navigation` from `dashboard/app.py`; thin routes live in `page_routes/`, outside Streamlit's legacy autodiscovered `pages/` directory. This prevents a fresh deep link from bypassing the shared entry point. No four-page redesign was started.

Every page/direct route/reload has Refresh now, the ten-second refresh toggle, last successful read, observation time, measurement freshness, selected original, collector state/expiry/remaining time, API/agent readiness, operating mode and explicit profile. A single active-view fragment refreshes its status and body. Refresh/navigation make only reads and preserve mutation intent receipts. Missing values remain unavailable. Identity errors are actionable and block the selected view instead of redirecting it.

## Verification and limits

Actual command results, native IDs/timestamps/metrics, latest test receipts and screenshots are indexed in `artifacts/completion_stage1_validation.json`. Fixture checks are labeled separately from native evidence. Initial test/browser failures are retained alongside final results.

The native healthy check completed prepare → connectivity → fresh complete suitable measurements → scoped cleanup → prepare with new IDs → healthy renewal. It also transferred a historical completed native traffic result via a small acknowledgement and byte-exact hash-verified retrieval. No healthy reference or fidelity tolerance was widened.

The original audit's failed fidelity experiments and uncertain trained diagnosis remain unchanged. No current original repair, fault recovery, SHAP-supported application, no-XAI/no-twin comparison, dataset target or scale result is claimed by this operational stage.

## Prompt 2 handover

Keep the trained model enabled. Inspect `diagnosis_service.py:diagnose`, `model_policy.py:infer`, `workflow_service.py:_run/_eligible`, `recovery_ranking.py:health/quality`, and the configured objective/reference contracts. The audited high-confidence latency case lacked anomaly/service corroboration; one candidate repeat also failed coverage. The objective/recovery-policy discrepancy and workload/domain/calibration evidence need investigation without lowering gates or replacing trained diagnosis with observed-only operation. Repeated no-change fidelity failures require their actual nested metrics/native distributions, not the generic insufficient-evidence label.

Completion status and final left-running state are recorded in the validation JSON and the measured appendix below. Prompt 2 has not begun.


## Measured acceptance and final state

Acceptance: **passed for Completion Prompt 1, with the scientific limitations above**. No Prompt 2 work began.

- Five overlapping software batches passed: 95 in 213.08 s; 98 in 67.73 s; 29 in 64.96 s; 88 in 180.53 s; and 46 in 59.38 s. There are **178 distinct test cases**, not the sum of batch counts. These are fixture/unit/API/AppTest checks. The existing Starlette/httpx TestClient deprecation warning remains; dependencies were not changed.
- Ruff passed all changed source/test/deployment-helper files; browser scripts passed Node syntax/runtime checks.
- Actual Brave: **12/12 profile/page combinations**, each direct URL and browser reload, passed. Manual refresh and the configured ten-second auto-refresh both published new status. The observed read gap during the timer check was about 34.1 s under this WSL/browser load; ten seconds is the scheduling interval, not a guaranteed end-to-end paint SLA. Screenshots and a visually inspected contact sheet are under `artifacts/completion_stage1/browser/`. Earlier capture/font/hidden-input/timing harness failures remain alongside the final passing report.
- Native healthy lifecycle: first original `teachlive_16a431a51a`, scoped cleanup, second original `teachlive_92464b70ed`, new traffic/collector IDs and healthy renewal passed. Representative renewal RTT 6.352 ms, critical delivery 7,999,867 bps, UDP loss fraction 0.0. Status-read checks preserved job/control/workflow/action/network rows while independently started collection continued.
- Large native traffic result: **2,408,083 compact JSON bytes**, **940-byte acknowledgement**, SHA-256 `86e0bbc928b993b34a6ce2f6aaceac1a07b2ea307b7ee7a249a93c291589266e`; full retrieval equaled the original native record. Different wire whitespace explains the difference from the old 2,648,024-byte frame; no evidence fields were removed. The 2.6 MB scenario-reset regression uses synthetic complete evidence because no new latency fault was authorized for this operational check.
- Final deployment revalidated ownership at mutation boundaries independently of read-only status. Only idle owned services were gracefully reloaded. The expired second original was explicitly cleaned before upgrading its root owner; there was no global cleanup.
- Final source **`teachlive_cacc533e6c`**, collector **`t9f0dfe2aa8be498681c0469635cf24b3`**, current complete suitable window **`wdd2e5231b87544243de70f7c268913c5`** at **2026-10-27T19:06:02.382577+00:00**: RTT **6.397 ms**, critical delivery **8,001,160 bps**, receiver loss fraction **0.0**. HTTP and configured SQLite window equality passed.
- Actual healthy workflow **`c1healthy_13a227f9bd59433d9c6d`** refused with **service acceptable; anomaly-only actuation prohibited**, elapsed **12099.49 ms**. `active_workflow_id` then became null while `latest_workflow_id` retained that result. No new candidate experiment/action was created.
- Both API/agent pairs are ready on protocol 2. Both profiles retain Recommend mode, automatic repair false, observed-only exception false, no active workflow/monitor/unsettled action. The trained model remains `m20261016T074751_a92c0db8f44e`; its bundle/report hashes match the audit. Dataset membership remains 240 train / 60 validation / 60 sealed test plus 10 separately tagged pilot windows. All checked configurations, dependency declarations and the original audit Markdown remain byte-identical.

The final original, healthy traffic and collector are **left running**. Current bounded expiry:

- Collector: **2026-10-27T19:22:08.383336+00:00** (28 October **00:52:08 IST**).
- Traffic: approximately **2026-10-27T19:27:07.697933+00:00** (28 October **00:57:07 IST**), plus the existing warmup/finalization allowance.
- No foreground terminal must remain open for detached services. Keep WSL running. Original resources persist after traffic/collector expiry; `demo renew` deliberately starts a new healthy run/collector only after its state checks. After the demonstration use **`demo cleanup`**; it is not run automatically.

Immediate click: **http://127.0.0.1:8502/network ? Refresh now**. Verify profile observed-only, the selected original above, Fresh/current observation and the expiry. The normal trained application remains **http://127.0.0.1:8501**.

Actual focused commands (ordinary WSL application venv, project root):

```bash
.venv/bin/python -m pytest tests/test_completion_stage1.py tests/test_workflow.py tests/test_agent_response_frames.py tests/test_teacher_demo_session.py tests/test_network_api.py tests/test_telemetry_api.py tests/test_twin_api.py tests/test_recovery_api.py tests/test_dashboard.py -q --junitxml=artifacts/completion_stage1/final_tests.xml
.venv/bin/python -m pytest tests/test_completion_stage1.py tests/test_foundation.py tests/test_dataset.py tests/test_telemetry.py tests/test_network.py tests/test_scenarios.py tests/test_twin.py -q --junitxml=artifacts/completion_stage1/delta_tests.xml
.venv/bin/python -m pytest tests/test_completion_stage1.py tests/test_telemetry_api.py tests/test_foundation.py -q --junitxml=artifacts/completion_stage1/final_delta.xml
.venv/bin/python -m pytest tests/test_completion_stage1.py tests/test_workflow.py tests/test_teacher_demo_session.py tests/test_dashboard.py -q --junitxml=artifacts/completion_stage1/handover_tests.xml
.venv/bin/python -m pytest tests/test_completion_stage1.py tests/test_network.py tests/test_scenarios.py -q --junitxml=artifacts/completion_stage1/ownership_tests.xml
.venv/bin/python scripts/check_completion_stage1.py
.venv/bin/python artifacts/completion_stage1/final_live_check.py
.venv/bin/python scripts/record_completion_stage1.py
```

The two healthy lifecycle scripts intentionally change laboratory state and leave healthy resources running; do not rerun them as read-only status commands. `node scripts/check_completion_stage1_browser.mjs` is the actual GET-only Brave UI check. JUnit receipts retain the exact run-time case lists; new test additions mean a later rerun can have a different count.


Latest handover renewal at 2026-10-27T19:12:19.012847+00:00: original `teachlive_cacc533e6c` remains healthy, collector `t0d196d7bf4df4398995d6cf699e8d714`, fresh complete window `wa15d0088fb77b254150a94015a98b6d7`. RTT 6.293 ms, critical delivery 7,999,703 bps, UDP loss fraction 0.0. Collector expires 00:52:08 IST; traffic approximately 00:57:07 IST on 28 October 2026. These renewed bounds supersede the earlier deployment snapshot. Automation/exception remain off; no end cleanup.
