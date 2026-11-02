> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# ExplainNet Twin completion audit

**Date:** 26 October 2026, Asia/Calcutta. Exact UTC snapshots are in `artifacts/completion_audit/current_state.json`.

**Conclusion:** substantial implementation and a valid limited academic submission exist. Completion against the requested original review targets is not demonstrated. The largest gaps are accepted dataset size, two measured repair alternatives per fault, fair ablations, reliable integrated diagnosis/recovery and the decision-time target. Production-network auto-remediation is outside the original scope.

## 1. Scope, references and method

This was a read-only audit. No application code, dependencies, configuration, database contents or laboratory resources were intentionally modified; no services were restarted and no faults, training, dataset collection or experimental campaigns were run. Application tests were not rerun. Only the two requested reports were written. `PROGRESS.md` was read and preserved under the user's stricter audit-only instruction.

Neither reference presentation was found in the project or supplied attachment directory:

- `ExplainNet_Twin_Revised_Zeroth_Review_with_VIT_Logo.pptx`
- `ExplainNet_Twin_Review_1_Progress_Presentation.pptx`

**These missing decks were not inspected.** The matrix below provisionally uses the audit request's review targets plus `PROJECT_SPEC.md`, `ARCHITECTURE.md`, README, model/dataset cards, evaluation protocols, startup/demo guides and persisted validation evidence. Slide-level traceability remains pending. Existing `ExplainNet_Twin_Final_Presentation.pptx` is a different presentation.

Following the requested scope distinction, the original review concerns emulated faults, IF/RF diagnosis, explanations, twin-based comparison, evaluation and research deliverables. Native original-laboratory application, verification, rollback, Undo and laboratory automation are later extensions. They must not be described as production deployment or used to replace missing original research requirements. This scope classification is provisional until the decks are available.

SQLite was queried with `mode=ro` and `PRAGMA query_only=ON`. Process identities, selected non-mutating endpoints, root journals and OVS ownership were read. Model binaries were hashed, not loaded or executed. Existing archive CRC/hash checks were read-only. Absence of inspected evidence means **unverified coverage**, not necessarily absent implementation elsewhere.

## 2. Current applications and evidence identity

| Item | Canonical application | Teacher demonstration |
| --- | --- | --- |
| Dashboard | `http://127.0.0.1:8501` | `http://127.0.0.1:8502` |
| API | `http://127.0.0.1:38223` | `http://127.0.0.1:43989` |
| Configuration | `artifacts/stage6/runtime/config.json` | `artifacts/stage14/rehearsals/bb745a91/config.json` |
| SQLite store | `/home/USER/.local/share/explainnet/stage13/data/explainnet.sqlite3` | `/home/USER/.local/share/explainnet/stage14/rehearsals/bb745a91/data/explainnet.sqlite3` |
| API/UI PIDs | 38962 / 86483 | 206571 / 206618 |
| Model | Active `m20261016T074751_a92c0db8f44e` | No registered/active model |
| Accepted data | 360 main windows, 60 episodes; 240/60/60 split; 10 separate pilot windows | No dataset members |
| Explanations | 67 ready, 6 failed, 4 unsupported | None |
| Recovery history | No workflows or candidate experiments | Three refused workflows; two insufficient-evidence experiments |
| Current original | No active original | `teachlive_a8b5a0ea5c`, with five ownership-matching OVS bridges |
| Current measurements | Historical; collectors stopped | Original persists, but collector stopped and traffic completed; telemetry historical |
| Operating control | Recommend; automatic repair off; exception off; no active workflow | Same |

Actual PID/start-ticks/UID/cwd/argv and the running dashboards' API environment matched their launcher receipts. Both root agents remain separate OS-Python processes: 41416 for the canonical lab and 92037 for the demo lab. The current demo has zero recorded traffic processes; its latest root run is succeeded. A running topology does not establish fresh traffic or telemetry.

The older guide's `teachlive_03f4798225` is now stopped. The reported failed workflow belongs to another stopped original, `teachlive_d9a1784587`; it must not be confused with the current original. Port 8501's empty twin history is accurate for its own store, not evidence that the project lost all experiments. Conversely, port 8502's observed-only history does not establish trained-model recovery.

The model bundle and its validation report matched the manifest SHA-256 values. No compatibility inference or new model execution was performed. Observed database job/state-row counts remained unchanged over the visual-check interval; no mutation requests were submitted.

## 3. Requirement matrix

Code filenames below are under `src/explainnet/` unless another path is shown. **Partial** means some implementation/evidence exists but the stated acceptance is not established. Requirements attributed to the original reviews remain provisional because the decks are absent.

| Requirement | Implementation files | Actual evidence | Verified coverage | Missing work / defect | Acceptance criterion |
| --- | --- | --- | --- | --- | --- |
| Four fault classes | `scenario_spec.py`, `scenario_runtime.py`, `model_policy.py` | Dataset card; model/evaluation validation reports | Saturation, loss, latency and QoS have 72 accepted windows each; healthy is a fifth label. Four-class fault generation and narrow held-out classification exist. | General repair is unqualified for loss, saturation and QoS. QoS recipes cover a declared HTB service restriction, not every possible classification error. | Measured independent episodes for all four classes, explicit workload/domain coverage and preserved refusals; validate diagnosis and repair comparison separately. |
| Isolation Forest | `model_training.py`, `model_features.py`, `model_policy.py` | Registered bundle; `model_validation_report.json` | Healthy-training fit and bounded validation threshold selection implemented. Validation detection is 12/48 faulty windows, with 0/12 healthy false alerts. | Presence of IF is not evidence of strong anomaly sensitivity; validation threshold selection is development evidence. | Report standalone IF sensitivity/false-alert/abstention results on fresh held-out families and operating conditions. |
| Random Forest | `model_training.py`, `model_bundle.py`, `model_policy.py` | Trusted active bundle; frozen `held_out_metrics.json` | Calibrated five-label RF, 21 original numeric features; test macro-F1 1.000 on 60 windows/10 episodes. | Limited families; actual live support differs from offline argmax accuracy. | Predeclared episode/family-separated evaluation, calibration, coverage and confidence intervals; no test-driven tuning. |
| Per-event SHAP | `explanation_engine.py`, `explanation_service.py`, `incident_service.py` | Five real validation cases; current explanation/diagnosis rows | Training-background TreeSHAP and model/window lineage implemented. Five current canonical live incident diagnoses have matching ready explanations. | Coverage is not established across every live fault/workload. Demo has no model/SHAP. Some other requests failed/unsupported; counts alone do not prove current explanations. | Matching model/window/version explanation for every supported in-scope event, or explicit failure/abstention; measure latency and additivity. |
| Observable twin reconstruction and measured fidelity | `twin_spec.py`, `twin_service.py`, `twin_runtime.py`, `twin_fidelity.py` | Twin validation report; native experiment payloads | Observed topology, forwarding, workload and queue reconstruction; isolated hypotheses, fresh matched controls and measured residuals exist. | Reliable all-fault fidelity and continuous synchronization are unverified. Latest no-change control failed two RTT metrics. | Demonstrate refresh/version/expiry handling and repeated C0 agreement across all relevant faults/workloads; preserve ambiguity and failures. |
| At least two feasible repair candidates per fault | `recovery_spec.py`, `recovery_service.py`; manual session script | Generated/rejected actions and experiment payloads | Generator supports several distinct actions; feasibility and budget rejection are recorded. | Demo uses `max_repairs=1`; latest experiment has one repair plus no-change. No-change is not a second repair. Two measured alternatives per fault are unverified. | At least two distinct feasible configuration-changing actions per fault, plus separate C0, with capacity/protected-flow checks and measured results. |
| Rerouting | `recovery_spec.py`, `recovery_runtime.py`, `workflow_service.py` | Stage 13/14 packet evidence | Declared alternate routes, forwarding checks and conditional five-switch UDP latency recovery verified historically. | Wider protocol/topology/fault and trained-model application coverage unqualified. | Compare appropriate alternatives and validate selected scope; later native application additionally needs fresh verification and rollback. |
| Capacity-respecting allocation/shaping | `recovery_spec.py`, `recovery_runtime.py`, topology definitions | Feasibility records; candidate validation report | Directional load/capacity checks and approved background shaping exist; physical capacity is not increased. | Fixed shaping is not a general allocation optimizer; robust per-fault native coverage incomplete. | Measured feasible allocations obey actual capacities and protected service; reject infeasible/no-op actions explicitly. |
| QoS correction | `scenario_runtime.py`, `recovery_spec.py`, `recovery_runtime.py` | Declared HTB hierarchy, counters and candidate checks | Approved correction policy exists: critical 3 Mbps guarantee/4 Mbps ceiling, bulk 16/20 Mbps, shared parent 20 Mbps. | Broad QoS repair fidelity and original-lab qualification not established. | At least two applicable alternatives for the declared QoS fault; verify mapping, parent/rate invariants, delivery and protected flows. |
| Dataset: 3,000–5,000 windows | `dataset_contracts.py`, `dataset_service.py`; `config/datasets/expansion_v1.json` | Canonical memberships and dataset card | 360 main accepted windows, not 3,000. A 600-episode/3,600-window expansion schedule already exists. | No accepted expansion batch in inspected stores. Raw/rejected/pilot windows cannot inflate the main total. | Versioned accepted corpus in target range, balanced independent recipe families/episodes, quality/provenance and frozen train/validation/test split. |
| Threshold comparison | `telemetry_monitor.py`, `evaluation.py`, `scripts/evaluate_stage13.py` | Frozen held-out metrics | Rule detection: 40/48 faulty windows; combined model detection: 48/48; both 0/12 healthy false alerts. | Detection comparison is not a four-fault classifier comparison or broad effectiveness claim. | Same held-out episodes, denominators, persistence, abstention and timing definitions; report per-class results. |
| No-twin comparison | Evaluation protocol and Stage 13 lab driver/results | Three no-change, three fixed-rule, three twin-guided original trials | No-change retained impairment 3/3; fixed rule succeeded 3/3; twin-guided succeeded 2/3 and refused 1/3. | All approaches received shadow twin evaluation; fixed-rule application was safety-qualified against the selected action. This is not an independent no-twin timing/selection ablation. | Define an independently computed no-twin recommendation baseline; separate shared safety/verification overhead and selection censoring. |
| No-XAI comparison | Explanation/evaluation infrastructure | No dedicated ablation in inspected protocol/config/results | Unverified; not claimed implemented merely because SHAP can be omitted. | No matched no-XAI result or defined causal role of XAI in action selection. | Freeze data/model/policy, specify removed inputs, compare decisions, latency and explanation utility. Removing post-hoc SHAP alone need not change RF predictions. |
| 5/10/15-switch benchmarks | `scripts/write_scale_topologies_stage13.py`, topology/twin services | `scale_summary.csv`, evaluation report | Native construction/connectivity and healthy/latency measurements at all three sizes, one episode per size. | Recommendation refused in these scale rows; larger-size model transfer and comprehensive repeated benchmarks unvalidated. | Repeated matched workloads at each size, construction/detection/decision/resources/fidelity/error bars and explicit transfer tests. |
| Macro-F1 ≥0.85 | Model/evaluation pipeline | Frozen five-class test macro-F1 1.000 | Numerical target exceeded on the existing small holdout. | Ten episodes, one held-out family per class; does not establish generalization to the requested corpus/live workload domain. | Preserve baseline; meet target with uncertainty/coverage reported on a new untouched, representative holdout. |
| Decision time <10 seconds | Model, explanation, twin and workflow timing fields | Inference mean 36.37 ms/p95 51.88 ms; validation SHAP 277–363 ms; latest workflow about 76 s | Fast inference/XAI components exist. Integrated twin-based decision under 10 s is not demonstrated. | Detection alone about 24.54 s and snapshot 17.18 s; serial fresh trials structurally exceed the target. | Agree clock start/end, then measure full decision distribution including abstentions, cold/warm runs and load. Do not relabel inference-only time as total decision time. |
| Reproducibility | `app_launcher.py`, configs, migrations, `scripts/stage13_provenance.py`, reproduction guide | Native archives, frozen hashes, package receipt | Existing-machine reproduction, provenance and isolated ownership supported. | Absolute machine paths; clean-machine restoration untested; original freeze omissions have a post-hoc receipt, not retroactive protection. | Reproduce from a documented clean environment with explicit profile/store identity, manifests, commands, failures and resource accounting. |
| Research report and final presentation | `deliverables/` | Report DOCX/PDF; 18-slide final PPTX; submission index | Final artifacts exist. ZIP has 22 members, passes CRC, and matches recorded SHA-256. Report is documented as 22 pages by existing validation. | October 19 cutoff predates later demo defects; existing decks are not the two missing review references. | Update requirements traceability and results after acceptance; preserve cutoff/versioning and do not rewrite failures as successes. |

### Fault-specific native recovery limits

Five-switch UDP latency has limited observed-only original recovery evidence. Stage 13 loss, saturation and QoS qualification cases were refused; UDP-critical/TCP-bulk latency was also refused. Healthy/fault generation or perfect offline class scores do not establish successful repairs. Later original-lab actuation qualification should remain a separately labeled extension.

## 4. Exact failure findings

### A. Requested workflow and experiment

- Workflow: `wdface540327049068407aa887e0efa1e`.
- Experiment: `e1be0accd25e3472f8ddf13590b93147c`.
- Source: `teachlive_d9a1784587`; this was **observed-only**, not trained-model diagnosis.
- Workflow observed at `2026-10-26T03:38:32.113480+00:00`; refused at `03:39:48.058357+00:00`.
- Experiment state: `insufficient-evidence`; nested reason: `no-change fidelity failed: fail`.
- Actual trial: `e1be0accd25e3472f8ddf13590b93147c_0`, family `no_change`, hypothesis `h0`, repetition 0.

| Failed fidelity metric | Original | Twin | Absolute difference | Allowed tolerance |
| --- | ---: | ---: | ---: | ---: |
| RTT p95, ms | 66.8 | 97.0 | 30.20 | 30.04 |
| RTT variability, ms | 0.1483448 | 7.6377542 | 7.4894094 | 3.0741724 |

Mean RTT passed: 66.32778 versus 68.42667 ms. Missing-required-metrics, contamination and stale-reasons lists were empty. Source/twin coverage was approximately 94.47%/74.50%; received/transmitted probes 18/18 and 15/15. These passed sampling minima. The failure was the measured RTT distribution disagreement, not generic missing probes or model confidence.

Only that first control ran; the candidate repair was not measured in this experiment. The planned budget was eight trials, but early refusal preserved the fidelity gate. Twin cleanup says destroyed and `original_modified: false`. The physical cause of the RTT variation is **not established** by these residuals; scheduling, warmup or shaping explanations require future controlled evidence. Do not weaken tolerances.

The earlier October 20 experiment is distinct: it measured one promising reroute before another C0 failed RTT variability. Its result cannot substitute for the October 26 trial. Also, the demo's `twin_trials` table is empty while recovery experiment payloads contain actual nested trials; a table count alone would miss this evidence.

### B. Refused workflow marked active

The saved session contains a refused workflow alongside `active_workflow_id` equal to that workflow. Source confirms the lifecycle defect: `RecoveryCoordinator.launch()` assigns `self.active`; `_run()` finally records elapsed time but never clears it. `busy()` tests thread liveness, while the helper rejects any non-null active ID. Those definitions can disagree after refusal.

**Current** read-only API control reports no active workflow after an intervening API startup. That does not resolve the source defect. Acceptance needs consistent terminal-state release on refusal, error, cancellation and timeout, without releasing an owner that is still verifying/rolling back. No restart or corrective action was performed in this audit.

### C. Oversized traffic-stop and scenario-reset responses

The preserved October 22 traffic-stop failure returned a valid 2,648,024-byte newline-terminated frame against the former 2,097,152-byte cap. Root traffic had already succeeded. The later fix permits 8 MiB only for `traffic_status` and `traffic_stop`, and renewal reconciles actual terminal state before starting replacement traffic. Existing focused validation records 23 passing tests; these were not rerun during this audit.

The remaining failure is exact: job `jfa542a860bcd413b9d5207eeda1de49b`, `scenario_reset`, at `2026-10-26T03:04:35.054098+00:00`, failed with **`oversized agent response: limit 2097152 bytes`**. `ScenarioEngine.reset()` returns `inspect()`, whose response embeds full owned traffic runs. The preserved run JSON alone serializes to 2,648,473 bytes, before journal/TC/envelope overhead. The traffic-only exemption does not cover this operation.

Root evidence says this old scenario was already stopped at `2026-10-22T18:22:48.867574+00:00`, with empty restore errors, before the October 26 reset request. Therefore the failed reply does not demonstrate failed restoration. Reconciliation must distinguish the physical outcome from missing acknowledgement. Prefer bounded control acknowledgements plus preserved/hash-referenced or paged native evidence; audit all response layers, including the dashboard's 4,000,000-byte cap. No limits were changed here.

### D. Cleanup, restart and short lifetimes

Terminal-but-active workflow bookkeeping can prevent helper renewal/cleanup despite a finished worker. Response failures can also leave API caches behind root state. A new API process clears the in-memory active pointer but is not a substitute for sound lifecycle reconciliation. Stop/cancel/Undo, cleanup and restart need one consistent ownership/action-state contract.

Collector requests are bounded to 600 seconds. Qualified traffic is 900 seconds; the earlier canonical quick check used 120/100 seconds. An idle topology survives their expiry, making “agent connected” and “network running” insufficient live-readiness indicators. Current demo traffic completed and its collector stopped; the audit deliberately left that state unchanged. UTC timestamps and monotonic elapsed durations must remain distinct, especially across host/WSL suspension.

## 5. Trained-model recovery assessment

The separate Stage 13 trained attempt `s13_trained_30b1587a` is important counter-evidence to a confidence-only explanation:

- Calibrated latency confidence **0.940505**, margin **0.922676**: both exceed 0.70/0.15 policy minima.
- `unsupported_features` was empty. A feature-range rejection was not recorded.
- Diagnosis was nevertheless **uncertain**: `fault classifier lacks corroborating anomaly or service evidence`.
- IF score **0.568212** was below threshold **0.622440**; baseline alert and diagnosis service violation were false.
- Diagnosis configuration uses a 100 ms RTT objective, while recovery policy uses 20 ms. The observed approximately 66 ms case exposes a service-evidence consistency issue to investigate, not permission to lower gates.

The actual candidate ranking additionally refused `no-safe-repair`: reroute repeat `e9a6b85f3f13a4269845c0504a0a33541_3`, h0/repetition 1, had **56.834%** coverage below **65%**. It received all 9/9 probes; coverage, not actual probe loss, was the numerical defect. Other measured repeats do not erase it. Stored SHAP was pending in the historical workflow; later lineage-safe refresh may project completion, but that cannot repair the sampling failure.

The canonical database currently contains 67 live diagnoses: **63 uncertain, four stale, zero supported**. Five live incident diagnoses have matching ready SHAP; most other live records concern healthy observations. Recent healthy confidences around 0.54–0.59 are below policy. These observations do not contradict narrow offline argmax accuracy, and they do not prove every live regime fails.

Training/domain differences, including the canonical 2 Mbps UDP/TCP workload versus the repair demo's 8/5 Mbps UDP workload, require stratified validation. They are a plausible transfer risk, not the documented hard range failure in the cited attempt. Preserve the active model. Do not disable it or count observed-only outcomes as completed trained-model recovery.

## 6. Dashboard findings and proposed four-page design

### Current visual inspection

An isolated Brave session captured all six canonical pages and five demo pages: Overview, Incidents, Twin, Recovery and Evidence. The demo's live Network page was not navigated because `GET /v1/networks/{id}` writes `network_instances`. Other write-bearing GETs include traffic status and twin status. This limitation follows the no-database-change constraint, not lack of browser tooling.

Eleven current PNG screenshots, page text and a visually inspected contact sheet are embedded in `current_state.json`; no additional image files were created. These are new-session observations, not inspection of a pre-existing private browser tab. The present design is light blue/white with teal accents and six overlapping navigation areas.

Refresh disappearance reproduced on the initial direct demo `/incidents` visit: **zero Refresh now buttons and zero auto-refresh controls**; its legacy sidebar differed from the registered navigation. Both controls appeared on the home page and subsequent captured registered pages. They remain in `dashboard/app.py`. Leaf page scripts call `render_selected()` without rendering that shared shell. Installed Streamlit source initializes legacy `pages/` routing and disables it only when `st.navigation` executes. Together, source and reproduction identify a bootstrap/deep-link path problem, not deleted controls.

### Proposed navigation — recommendation only

| Page | Contents |
| --- | --- |
| **Live Network** | Owned topology, selected routes/capacities, measured rate/RTT/loss, current collector/run/window, freshness/expiry and deliberately confirmed laboratory operations. |
| **Diagnosis** | Current incident and symptoms; rules versus IF/RF; support/abstention reasons, calibrated probabilities and matching per-event SHAP. Clearly label recorded observations. |
| **Twin & Recovery** | Snapshot/version/expiry, reconstruction uncertainty, C0 residuals, at least two repair candidates, rejection reasons, recommendation, gated assisted apply, original verification/disruption, rollback/Undo and audit. |
| **Results** | Dataset/split/episode coverage, held-out metrics, threshold/no-twin/no-XAI comparisons, scale benchmarks, runtime distributions, reproducibility and report/presentation downloads. |

Use a shared persistent shell on every route: Refresh now, 10-second refresh toggle, last successful read, API/agent readiness, selected original, collector state/expiry and operating mode. Show an explicit profile label and configuration hash/API/store identity in a details panel. A saved SHAP count must not imply a current explanation; Active model must not imply supported diagnosis. Missing values remain unavailable, not zero.

Use charcoal `#0F141C`, navy panels `#151F2E` and restrained teal `#37B5AD`, with accessible text contrast, visible focus and status text/icons rather than color alone. Expose nested rejection reasons directly. Do not hide workload/store distinctions behind an apparently healthy application header.

Provide one normal application URL/entry point with explicit profile selection. Preserve separate stores and privileged owners; do not merge sealed datasets or silently redirect commands. Startup, browser and CLI must share an identity contract. Switching profiles must not start traffic, train, enable automatic repair or grant observed-only permission.

## 7. Prioritized completion plan and dependencies

1. **P0 — Confirm scope and provenance.** Obtain the missing decks or approve the provisional matrix. Separate original review acceptance from later laboratory actuation. Preserve the existing frozen submission and failures. Define exactly what the <10 s decision clock includes.
2. **P1 — Stabilize lifecycle and transport before further packet work.** Resolve terminal active-ID bookkeeping, unknown-outcome reconciliation, scenario/reset response budgets and cleanup/restart ownership. Make status GETs genuinely read-only. Provide visible bounded collector/traffic lifetimes. Depends on P0; gates stay unchanged.
3. **P2 — Establish coherent diagnosis/service evidence.** Trace 100 ms versus 20 ms objectives, nominal references, live feature distributions, IF sensitivity, calibration and abstention. Define representative workload families and new evaluation splits. Do not tune the old test set. Depends on P0/P1.
4. **P3 — Qualify candidate diversity and reconstruction.** Budget at least two feasible changing actions per fault, retain separate C0, and investigate RTT-tail/variability disagreement using controlled repeated measurements. Measure protected traffic and capacity/QoS invariants. Depends on P1/P2. Original-lab application remains a separately gated extension.
5. **P4 — Complete the corpus after the protocol is stable.** Reuse/review the existing 3,600-window expansion schedule, then collect a new version only after authorization. Keep the 360-window baseline immutable; enforce independent families, quality and split/provenance rules. Depends on P1/P2 and coverage decisions from P3.
6. **P5 — Freeze and evaluate the research claims.** Train/select/calibrate using the declared development split, then evaluate an untouched holdout; run fair threshold/no-twin/no-XAI and repeated scale comparisons. Record failure/refusal denominators and end-to-end timing. Depends on P3/P4. Observed-only experiments cannot close trained-path acceptance.
7. **P6 — Implement the four-page application and acceptance tests.** Shared identity/refresh shell can follow P1; complete result/diagnosis presentation after P2–P5 contracts stabilize. Keep safety logic in backend services. Resolve every-page/deep-link behavior before a teacher demonstration.
8. **P7 — Reproduce and update deliverables.** Perform a clean-environment reproduction, reconcile the requirement matrix and publish versioned report/presentation evidence with the new cutoff. Depends on P5/P6. Current package existence is not proof of the revised claims.

## 8. Acceptance tests and measured experiments to schedule

**Software checks:** terminal release on success/refusal/cancel/error/timeout; busy/active consistency; idempotency and unknown acknowledgements; fragmented/oversized/truncated/mismatched responses for all run/scenario operations; no evidence truncation; PID/UID/start-tick ownership; no unrelated cleanup; safe restart during verification/rollback; current-collector window boundaries; nulls/units; model/schema/domain/SHAP-lineage refusal; pure read routes; all-page/deep-link persistent controls; refresh creates no jobs; double-click applies once. These are proposed future checks, not newly passed tests.

**Measured work:** independent episodes for all four faults and healthy controls; two feasible changing candidates plus C0 per fault; repeated matched fidelity and protected-flow measurements; workload/domain/calibration/abstention cohorts; a representative 3,000–5,000 accepted-window corpus; frozen threshold/no-twin/no-XAI comparisons; repeated 5/10/15-switch runs and transfer checks; complete decision latency distributions. Predeclare episode counts and analysis before execution; repeated windows/trials within one source are not independent episodes.

Where actuation is included, keep demand/impairment active through fresh original verification, measure transient disruption separately, exercise rollback/Undo and verify scoped cleanup. These later extension tests do not authorize production-network automation. No test should pass by disabling the model, substituting observed-only operation, clearing the fault, dropping a failed repeat or weakening fidelity/confidence gates.

## 9. Runtime estimates and uncertainty

These are observed execution durations, not estimates of developer labor. No new timing campaign ran.

| Work | Existing measurement | Planning interpretation |
| --- | --- | --- |
| Single frozen inference | Mean 36.37 ms; p95 51.88 ms | Does not include collection, HTTP, XAI or candidate testing. |
| Five validation SHAP cases | 277–363 ms each | Background/host/cache dependent; not universal per-event latency. |
| Training on existing 360-window corpus | 7.07 s recorded | Cannot safely extrapolate selection/explanation time to a different corpus by row count alone. |
| Latest refused workflow | 24.54 s observation + 17.18 s snapshot + 34.10 s candidate experiment; about 76 s total | Early first-control refusal, not a successful repair runtime. |
| Earlier bounded demo drivers | 218 s refused; 414 s verified repair/Undo/checks | Roughly 3.6–6.9 min for those scopes, without a success guarantee. |
| Nine Stage 13 primary comparison trials | About 46.4 min summed full trial time | Excludes wider qualification/scale cases and environment failures; not a genuine no-twin benchmark. |
| 5/10/15-switch construction | 1.29 / 2.79 / 3.82 s | One episode per size; not a stable distribution. |
| 5/10/15-switch twin evaluation | 206.8 / 115.7 / 59.2 s | Different refusal paths; the apparent decrease is not improved scaling. |
| Additional target dataset | Recent observed episode mean 136.8 s for six accepted windows | Approximately 17–30 active hours for 2,640–4,640 additional windows, optimistically excluding failed attempts. |
| Existing 600-episode expansion schedule | Same 136.8 s reference gives about 22.8 active hours | Prospective estimate only; failures, broader recipes, host pauses and recovery can extend it substantially. No credible upper bound is established. |

The current sequential packet-window workflow cannot be called <10 s simply because inference is fast. First reconcile the review's decision definition with later physical verification overhead; any redesigned fast path needs its own measured acceptance. Engineering effort and clean-machine recovery time are not reliably estimated from these artifacts.

## 10. Evidence index and final assessment

- Requirements/context: README; `docs/PROJECT_SPEC.md`, `ARCHITECTURE.md`, `MODEL_CARD.md`, `DATASET_CARD.md`, `EVALUATION_PROTOCOL.md`, `EVALUATION_STAGE13.md`, startup/demo guides and `PROGRESS.md`.
- Scientific results: `artifacts/model_validation_report.json`, `explanation_validation_report.json`, `twin_validation_report.json`, `candidate_validation_report.json`, `recovery_validation_report.json`, `evaluation_validation_report.json`; `artifacts/stage13/held_out_metrics.json`, `backend_shap.json`, `lab_report.json`, `scale_summary.csv` and frozen/post-hoc provenance receipts.
- Requested failure: demo SQLite `recovery_workflows`/`recovery_experiments`; saved `artifacts/teacher_demo/interactive/sessions/20261026T033350Z_bb6e42/session.json` and its workflow request.
- Transport: demo failed jobs and logs; `artifacts/teacher_demo/renewal_fix/`; read-only root journals. Ownership tokens are redacted in the audit export.
- Release: `deliverables/DELIVERABLES.md`, `REPRODUCE.md`, report/deck files and Stage 15 validation receipts. ZIP SHA-256: `74915e5f9bfd81998ad79dbc88930516027bd32fe46e48710e3fa83a40cfebc8`; 22 members, CRC valid; final PPTX has 18 slides.
- Machine-readable snapshots, exact nested failures, hashes and screenshots: `artifacts/completion_audit/current_state.json`.

**Original research blockers:** unconfirmed review traceability, accepted corpus shortfall, unverified two-candidate/all-fault comparisons, incomplete fair ablations/repeated scale evidence and no demonstrated integrated <10 s decision. **Later integration/actuation blockers:** terminal-state bookkeeping, scenario response sizing, route bootstrap/refresh behavior and unqualified trained-model application. Trained diagnosis support/domain consistency also needs investigation as research evidence; an original-lab application success is not a substitute for that work. Existing native successes and final submission artifacts remain valid within their recorded limits. No implementation was started by this audit.
