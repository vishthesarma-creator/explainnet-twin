# Recovery workflow and safeguards

## Completion stage 2 integration (2026-10-28)

`workflow_v2` defaults to Recommend and two repairs. It binds the primary live trained diagnosis, calibrated confidence, raw RF SHAP and immutable snapshot to one observation, while retaining initial diagnosis and separate timings. Model/schema/domain abstention and pending/failed/mismatched explanation remain explicit and prevent integrated recommendation. Independent twin testing may still collect useful evidence for an uncertain diagnosis; it cannot authorize application.

Explicit streamed workloads/collectors must have enough remaining life for the generated trial count, original verification and rollback. There is no silent extension. Automatic repair remains disabled on startup and requires explicit Lab Auto-Repair mode with current trained support. The original application allowlist remains **reroute only**; measuring shaping/QoS candidates does not authorize those families on the original. Existing durable root journals, ownership/freshness/version/drift checks, two fresh post-action windows, protected traffic/connectivity, rollback/unsafe-Undo checks, cooldown and attempt bounds remain enforced. Workload and impairment remain active throughout verification.

`scripts/completion_stage2.py` declares sequential healthy/four-fault episodes with two nominal pilots, two candidate repetitions and at most two hypotheses. It never fits a model or falls back to observed-only. A single additional explicit automatic latency episode is conditional on actual trained assisted success. All source attempts, control residuals, candidate failures, lifetimes, application/verification and scoped cleanup are persisted. `--resume` skips already attempted episodes; it does not rerun failed samples. Native historical rollback evidence remains separately labeled observed-only and cannot close trained acceptance. See `COMPLETION_STAGE2.md` for results and safe resume commands.

## Stage 14 current readiness

The complete main dataset, registered calibrated model `m20261016T074751_a92c0db8f44e`, actual validation SHAP and six-page dashboard are available. Current original actuation remains qualified only for explicit observed-only five-switch UDP latency at 8 Mbps critical / 5 Mbps bulk. The separate trained live attempt remained uncertain and was refused. Fresh Stage 14 rehearsal `207c58ab` verified an original repair, two post-windows and intentional Undo; its actual metrics and cleanup are in `artifacts/integration_validation_report.json` and `PROJECT_STATUS.md`.

Workflow reads now refresh matching asynchronous explanation status without changing stored history. The dashboard reads current backend applicability and rejection reasons before enabling Apply. This preview grants no actuation permission; normal application rechecks remain mandatory. See `DEMO_GUIDE.md` and README for current startup/shutdown and recorded fallback. Historical Stage 11 measurements below remain unchanged.

## Scope and operating modes

The coordinator reuses the existing network/traffic/TC agent, telemetry aggregation, incident service, diagnosis/explanations, immutable twins, fidelity policy and candidate ranking. It never selects an action using the test driver's label or reads its injector journal. All original mutations target verified ExplainNet-created bridges, veth links and namespaces. Physical interfaces, external networks and unrelated resources are outside its action API.

`workflow_v1` is declared in `workflow_spec.py`, with a persisted content hash. Original execution currently permits qualified reroutes of the declared critical/bulk pairs. Shaping and QoS remain typed Stage 10 twin capabilities; they have no currently demonstrated eligible original repair and are refused at the original boundary. The dashboard exposes these services and their current gates.

| Mode | Behaviour |
|---|---|
| Observe | Fresh health/incident/diagnosis evidence only. No twin testing or original actuation. |
| Recommend (default) | Observed incident, fresh snapshot, fidelity and repeated candidate tests; no original change. |
| Assisted Repair | An explicit eligible application request, with fresh service and ownership checks. |
| Lab Auto-Repair | An explicitly enabled bounded monitor of fresh telemetry; same application/verification gates. |

Modes and changes are stored/audited. The automatic monitor requires a completed suitable window no older than 30 seconds, then independently captures two fresh persistence windows. Restart retains nonautomatic mode preferences but clears automatic enablement and the observed-only exception. Auto mode becomes Recommend until explicitly enabled again. Stop Automation disables new automatic actuation; an applied change must finish verification or roll back. Cancellation after application always requires restoration rather than abandoning state.

The calibrated classifier and measured validation SHAP are available in the canonical backend. Their presence does not qualify every current observation or action: default actuation requires a supported diagnosis and matching ready explanation. A separate **explicit observed-only laboratory opt-in** permits the independently validated observed-topology workflow; this is audited and does not claim trained diagnosis or physical cause identification. The isolated rehearsal declares this scope before execution and does not deactivate a model after a rejection. It uses actual service violations, logical topology/localization and fresh repeated twin evidence. Recommendations still require all tested hypotheses, fidelity, quality and meaningful benefit. An anomaly alone while service is acceptable cannot trigger an action.

## Lifecycle and execution

Workflow states: observing → diagnosing → validating → recommended → applying → verifying → succeeded, or refused/interrupted/failed; application or verification failures enter rolling_back → rolled_back or degraded failed. All state transitions have UTC timestamps. Separate bounded coordinator threads call the existing services directly; they do not enqueue nested jobs and wait in the single job worker. Request handlers submit typed short jobs and return promptly. The existing telemetry sampler remains available during recovery.

Before twin testing, two suitable fresh violating windows establish persistence under the original ownership context. This fixes the integration issue where separate capture run IDs would otherwise fragment the same observed incident. The snapshot remains immutable; Stage 10 resets, warmup, matched controls, two repetitions, hypothesis budget, random seed and objective remain unchanged. Finite job/snapshot lifetime is never extended to force eligibility.

Before original application the coordinator checks: open incident and still-failing fresh service; recommendation status/expiry; all diagnosis, model, snapshot, policy, topology, queue, forwarding and workload versions; owned original identity; action eligibility and bounded attempts. A per-instance workflow constraint and the root mutation lease prevent concurrent recovery/mutations. Already queued mutation jobs are checked again before execution. Mode and laboratory-exception revocation are checked at the actuation boundary, not only at request submission. Action IDs and request keys prevent replay and reject changed duplicates. A successful or rolled-back action starts a 120-second cooldown. At most two attempts are permitted for an incident; new healthy windows do not cause repeated actuation.

## Durable journal and forwarding strategy

Migration 10 adds coordinator control, workflows and action-state indexes, while reusing `actions`, incidents/events, snapshots, candidates, raw telemetry, jobs and audit storage. The application records an action ID before root preparation, so a lost prepare reply remains reconcilable. Root preparation fsyncs and durably records the logical diff, resolved owned hosts/switches, current forwarding/class policy, ownership token, snapshot/policy versions and restoration paths **before the first mutation**. Native original impairment evidence is held in the root journal; only equality digests cross the actuation boundary, and those values are never used as diagnosis/builder inputs.

Forwarding uses the existing route-cookie owner: delete only the affected pair's old rules, then install both directions using per-switch OpenFlow bundles. Paths are prevalidated as connected and simple. This is a bounded delete/install update with possible temporary packet loss; it is **not globally atomic across switches**. Per-switch acknowledgements, UTC/monotonic application bounds, duration, errors and partial updates are journaled. Complete native receiver intervals overlapping the application are retained separately, including loss and delivered rate. Their one-second resolution includes adjacent traffic and does not prove sub-interval or zero disruption. Readback checks intended paths, both source directions, flow configuration, physical parents and impairment equality. No scenario stop, network reset or impairment clearing is used as recovery.

At least two fresh settled original windows are required. They must satisfy the declared Stage 10 critical service, protected delivery, quality/resource and workload gates and improve against a fresh pre-action reference. Connectivity and forwarding readback must also pass. Predicted twin RTT observations and actual original observations are stored together. Action deadlines are checked after measurements and before keep, so an over-budget final window cannot become success. The two-second settling delay separates the settled measurements from the recorded application interval/disruption. A passing twin trial alone cannot mark an original action successful.

Only verified actions are kept. Incident resolution references the two actual healthy post-action windows and records recovery **through an active repair**, with `physical_impairment_removed=false`.

## Rollback, Undo and restart

On partial application, verification failure, cancellation after application, timeout or material invalidation, restore the recorded owned paths/cookies in both directions. Readback must equal the previous forwarding configuration, physical parent/impairment digest and workload; connectivity must be verified. Versions remain monotonic, so restored logical state is not permission to reuse an old recommendation.

Undo Last Lab Action selects the last successful action for the original instance. It checks the exact current owned configuration, workload, flow readback and version against the kept state. Any intervening change is refused with a reason. Undo restores previous forwarding while leaving the active impairment and offered demand in place. It never performs a global network reset.

On process restart automatic actuation is disabled first. Interrupted journals are compared/restored against the actual root owner. Mutations are never silently replayed and interrupted actions are never inferred successful. Unavailable ownership or failed restoration is degraded failed, stops automation and requires operator reconciliation. Storage failure cannot skip the root rollback RPC: persistence failures are retained in memory/root evidence, the coordinator becomes degraded, and automatic enablement is refused until reconciliation. Restart also retries previously degraded action restoration against verified ownership. Restarted workflows are historical interrupted records, not resumed nested jobs.

## Live telemetry and time handling

Continuous collection now consumes complete live native receiver events. A bounded header/tail view keeps the last 30 measured intervals plus actual omitted/warmup intervals; the full native server file remains raw evidence. Stable interval timing IDs and collector deduplication prevent repeated live events from conflicting. Rates, RTT/jitter and loss retain existing definitions and units.

The privileged traffic owner records paired UTC/monotonic client-launch clocks. Receiver-native connection timestamps are mapped through that observed launch pair, with a bounded connection-offset check, so later WSL wall-clock correction cannot move receiver intervals outside a valid monotonic window. Actual native omitted duration is retained rather than substituting configured warmup. Missing or inconsistent timing is refused, not fabricated. UTC still governs snapshot expiry; monotonic time governs elapsed measurement/job duration.

## Commands

From the documented Ubuntu project directory, with the existing API/root agent running:

```bash
.venv/bin/python -m explainnet.cli --config CONFIG lab-mode MODE.json
.venv/bin/python -m explainnet.cli --config CONFIG lab-workflow WORKFLOW.json
.venv/bin/python -m explainnet.cli --config CONFIG lab-workflow-get WORKFLOW_ID
.venv/bin/python -m explainnet.cli --config CONFIG lab-apply APPLY.json
.venv/bin/python -m explainnet.cli --config CONFIG lab-action-get ACTION_ID
.venv/bin/python -m explainnet.cli --config CONFIG lab-undo UNDO.json
.venv/bin/python -m explainnet.cli --config CONFIG lab-automation-start WORKFLOW.json
.venv/bin/python -m explainnet.cli --config CONFIG lab-stop
.venv/bin/python -m explainnet.cli --config CONFIG lab-cancel WORKFLOW_ID
.venv/bin/python -m explainnet.cli --config CONFIG lab-control
```

`MODE.json`: `{"mode":"assisted-repair","allow_observed_only":true}` is the explicit laboratory exception; leave the flag false for the production-model gate. `WORKFLOW.json` contains original `instance_id`, unique `workflow_id`/`request_key`, registered nominal `baseline` IDs/definition hash, frozen fidelity `policy`, candidate/hypothesis bounds and timeout. `APPLY.json` contains `workflow_id`, unique `action_id`/`request_key`. `UNDO.json` contains original `instance_id`, request key and optional latest action ID. APIs are under `/v1/lab`; automation stop and workflow cancel bypass the job worker. Submission success means the bounded workflow/application was accepted; poll workflow/action status for actual verification or refusal.

## Verification and test-only hooks

`scripts/check_recovery_stage11.py` launches a root agent and UID 1000 API/driver in isolated evidence storage. The separate driver selects permitted train setup; recovery sees only observed telemetry. The original workload stays active. `workflow_observation_v1` permits a finite 2400-second source workload for the bounded multi-case verification batch; normal traffic/dataset bounds remain unchanged. Snapshots still expire at their predeclared finite limit.

Failure hooks require both root `--allow-lab-test-hooks` and API `lab_test_hooks=true`, and explicit bounded hook values. They are disabled in normal operation. The verification failure hook installs a scoped critical-flow drop on an owned alternative-path bridge, producing real missing delivery/probes; rollback removes only that test cookie. Partial failure interrupts after the first acknowledged switch bundle. The interruption hook stops the coordinator after root acknowledgement so restart can reconcile the genuine applied state. Simulated unit failures and actual packet-level evidence are reported separately.

Verification uses an ordinary-user database on the Linux filesystem after a measured DrvFS polling I/O failure. Polling storage errors remain visible, the worker stays responsive, and new recovery actuation is prohibited while storage is degraded. The scoped supervisor archives native journals and the database after cleanup.

Actual results, earlier failed attempts, predicted-versus-observed metrics, refusals, timing, restoration and clean-state proof are recorded in `artifacts/recovery_validation_report.json` and per-run `artifacts/stage11/` evidence. Coverage remains conditional; no unsupported fault or unavailable production model is declared repaired.


## Measured completion evidence (2026-10-16)

The canonical report is `artifacts/recovery_validation_report.json`. It aggregates eight actual attempts, preserves their earlier failures, and keeps software fixtures separate from native packet evidence. All use permitted training setups; no sealed measurements or model retraining were used.

| Actual case | Measured result |
|---|---|
| Assisted UDP latency repair (`afbf702c`) | Critical RTT 66.4909 ms before, then 4.3542 and 4.3539 ms; approximately 8 Mbps delivered in both settled windows. Twin predictions were 4.3272..4.4422 ms. Application took 1294.88 ms. |
| Telemetry-triggered automatic UDP latency repair (`1b4e29c0`) | RTT 66.4111 ms before, then 4.2712 and 4.2830 ms; approximately 8 Mbps delivered. Twin predictions were 4.2600..4.3220 ms. Application took 1161.80 ms. No repeated change followed the healthy windows. |
| Actual Undo (`afbf702c`) | Recorded previous forwarding restored with readback and connectivity; a fresh window returned to 66.4778 ms while the impairment/workload continued. |
| Verification failure (`206c6951`) | An explicitly enabled owned packet-drop hook failed actual service verification. Scoped rollback passed readback/connectivity; fresh restored RTT was 66.3444 ms. |
| Partial application (`206c6951`) | Failure after one acknowledged switch bundle triggered real restoration; fresh restored RTT was 66.3455 ms. |
| Interrupted API (`7bd59c66`) | Before the verified API kill, actual repaired RTT was 4.2536 ms. Restart restored the prior route without application replay; fresh RTT was 66.4222 ms. Auto-repair and the observed-only exception were both disabled. Offered traffic remained running through the final measurement. |

The two successful original repairs preserved the impairment digest and workload, passed critical/protected service, data quality, forwarding and connectivity, and resolved their incidents using the two fresh post-action windows. Historical sources were then cleaned by their verification owner; saved recommendations/actions are not permission for new actuation.

Application was disruptive: whole native intervals overlapping the assisted and automatic changes contained critical loss fractions 0.11059 and 0.08212 respectively, with protected bulk loss 0. These are roughly two-second receiver intervals including adjacent traffic, not exact sub-interval loss measurements. Older successes use application UTC receipts mapped through surrounding measured paired clocks (spread under 0.0005 seconds); newer journals record explicit monotonic bounds. Full raw native intervals and method/availability timestamps are retained. Settled success does not imply zero transient loss.

Healthy operation caused no repair. An actually omitted hypothesis produced uncertain refusal. Duplicate application was idempotent; an old post-Undo recommendation was refused and a new workflow hit the declared cooldown. Stop during validation acknowledged in 1263.53 ms and canceled without original application. Existing Stage 10 expiry/drift/poor-fidelity packet evidence remains linked for unsupported conditions; Stage 11 software guards separately verify missing-model opt-in, uncertainty, stale applicability, unsafe Undo, queued mutation rejection, mode revocation and database-failure rollback handling.

Earlier failures remain explicit: receiver omission trimming, WSL time mapping, cancellation classification, invalid test collector duration, monitor polling, DrvFS SQLite I/O, and a restart test driver that polled before readiness. Those specific integration defects were corrected. The premature restart attempt did not prove reconciliation; the fresh bounded `7bd59c66` rerun did. Old failed/interrupted records are retained, and their test-owner destruction is not reported as rollback.

The full software suite passed 154 tests before the final concurrency/storage review; the final focused suite passed 53 tests covering those subsequent changes. Ruff, dependency consistency, editable installation/API version 0.11.0, and actual CLI mode/control/stop checks passed. Native mode/application commands also passed. Migration 9 to 10 preserved all existing counts, dataset states and the train/pilot membership digest: 192 train and 10 pilot members, no production model or explanation bundle.

All eight native databases passed integrity checks and persisted automatic enablement off. Every cleanup receipt preserved preexisting bridges and removed owned bridges; every source journal ended stopped. Final inspection found no OVS bridges or Stage 11 API/agent/driver processes. Default settings leave test hooks disabled.

Original measured coverage is limited to the permitted 8 Mbps critical / 5 Mbps bulk UDP latency condition. Saturation, loss, QoS and the previously tested TCP latency condition have no qualified original repair. Production Stage 6/7/8 gates remain incomplete. Stage 12 interface work may begin if it clearly displays these gates, the explicit laboratory exception, current freshness and actual refused/rollback/degraded states; production recovery is not ready.
