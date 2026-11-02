> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# ExplainNet Twin project status — Stage 15 submission

<!-- completion4-current -->
## Current completion handover — 28 October 2026

The **four-page** normal trained application is http://127.0.0.1:8501 (API38223); observed-only8502/API43989 remains separate. Normal launcher: `scripts/app.py start|status|stop` in the existing WSL `.venv`. [Completion Stage4](COMPLETION_STAGE4.md) and [current submission index](../deliverables/completion4/SUBMISSION_INDEX.md) supersede historical stage descriptions below.

**Full review acceptance is blocked.** The prospective collection stopped at402/3600 windows (67/600 episodes), with both permitted attempts for c3m_latency_f11_r06 exhausted. New freeze/holdout, independent baselines/no-XAI/repeated scale and all-fault trained recovery remain pending; the integrated below10s target is unmet. No new training/test tuning or campaign is claimed by this handover. Fresh trained latency qualified12 trials/four C0/two changing alternatives, assisted verification and Undo. Healthy and loss refusals are retained. Automatic repair is OFF. See docs/FINAL_ACCEPTANCE.md, artifacts/completion_stage4_validation.json and the teacher quickstart for exact evidence, commands and finite expiry.
<!-- /completion4-current -->

The Stage 15 academic submission is **ready with stated limitations**. Final files and validation are indexed in `deliverables/DELIVERABLES.md`. The table below summarizes implemented and measured scope through Stage 14 completion at 2026-10-19T12:10:41.318707+00:00. The authoritative integration result is `artifacts/integration_validation_report.json`; frozen evaluation and raw artifacts are preserved. Historical receipts retain their original status rather than being rewritten as new experimental evidence.

| Component | Implemented | Software checks | Live evidence | Limitation |
| --- | --- | --- | --- | --- |
| Privilege boundary | Ordinary-user API/UI/model; separate root OS-Python agent | Typed RPC, ownership, invalid target and root-hook rejection | Stage 14 separate UID/API/UI and root owner, isolated source/twin | Linux/Mininet privileges needed for live labs; no physical/external network repair |
| Startup/shutdown | Configurable loopback launcher with exact PID/ticks/UID/cwd/argv ownership | Occupied port, PID reuse, changed config and no automatic network/jobs | Fresh-shell start/stop/restart; unrelated listener preserved; Stop Automation about 50 ms in lifecycle check | Existing working WSL environment only; no clean-machine installation |
| Topology/traffic/fault driver | Five-switch source and deterministic 10/15-switch extensions; separate setup labels | Validation, bounded arguments and isolation checks | Real 5/10/15-switch construction/connectivity; Stage 14 8/5 Mbps UDP latency rehearsal | Larger topology model transfer and original repair unqualified |
| Telemetry/incidents | Native receiver/probe/counter windows, persistence and observed incidents | Units/nulls, contamination, worker isolation, stale/partial refusal | Collector continued during the fresh twin experiment; persistent incident linked to action | Sampling resolution limits exact overlap claims for very short SHAP work |
| Dataset | Complete 360-window / 60-episode main dataset | Split/provenance checks and unchanged membership digest | Measured 240 train / 60 validation / 60 test; ten pilot windows separate | Few recipe families; cadence/storage amendments documented |
| Local model/calibration | Trusted calibrated bundle `m20261016T074751_a92c0db8f44e` | Compatible preprocessing/order/classes/dependencies and immutable-result guards | Real backend train-window inference and validation predictions | Five-switch emulation only; confidence alone does not permit actuation |
| SHAP/localization | Training-background RF explanations; observation-based link localization | Actual RF additivity/class mapping, lineage and async status checks | Five real validation SHAP cases; ten ready canonical records. Fault-only localization 33/48 uniquely correct, 15 ambiguous | Raw RF output explanation is not calibrated confidence or physical causality |
| Twin/fidelity/ranking | Separate runtime owner, immutable snapshot, matched controls/repeats and hard gates | Stale, failed, canceled, drifted and original-target refusals | Stage 14 measured candidate evaluation with disjoint source/twin runtime names | Fidelity/quality refusal remains valid; repeats within one source are not independent episodes |
| Assisted original repair | Qualified reroute only; explicit observed-only opt-in; fresh verification | Eligibility, mode revocation, journal, concurrency and rollback regressions | Stage 14 RTT 67.112 → 4.229 ms; two post-windows, about 8.001 Mbps critical / 5.000 Mbps bulk, zero measured settled UDP loss | Observed-only five-switch UDP latency scope; trained actuation remains unqualified |
| Undo/rollback/restart | Owned readback, restoration and no mutation replay | Partial application, storage failure, interrupted/degraded restoration fixtures | Fresh Stage 14 successful repair then Undo to 66.261 ms; compatible Stage 11 native failure/interruption evidence retained | Fresh Stage 14 did not repeat the expensive injected-failure campaign; transient loss can occur |
| Dashboard/audit/downloads | Six pages, confirmations, receipts, read-only backend applicability and closed evidence allowlist | All six fixture pages, duplicate-click/timeout, no navigation mutation and download checks | Six actual pages passed against both canonical and rehearsal backends; approved Stage 14 evidence exposed | Supported Streamlit AppTest/HTTP, no browser/pixel layout verification |
| Evaluation | Frozen held-out diagnosis and nine independent original baseline sources | Metric class order, episode bootstrap and saved-result reuse | Test accuracy/macro F1 1.000 on 60 windows/ten episodes; Brier 0.02147, log loss 0.10833, supported coverage 58/60 | One held-out family per class; narrow generalization. Original freeze coverage gap is documented with a dated post hoc receipt |

## Teacher demonstration preparation — 21 October 2026

**Ready with limitations for 22 October.** The [beginner quickstart](TEACHER_DEMO_QUICKSTART.md) gives verified PowerShell commands, terminal lifetimes, actual controls, timings, refusal handling, scoped cleanup and a recorded fallback. The canonical API/UI were running without their separately privileged agent; starting the existing OS-Python owner restored connectivity without changing configuration. A real healthy original, traffic, telemetry, trusted active model and matching new SHAP explanation were checked. The current healthy model prediction was uncertain (confidence 0.5841), not actuation-qualified.

The one new bounded observed-only UDP latency fault run `bb745a91` measured healthy RTT about 6.25 ms and impaired RTT 66.22 ms. One twin reroute reached 4.28 ms, but a repeated no-change control failed RTT-variability fidelity. The workflow refused original repair; original recovery, verification and application loss were not measured in this run. No thresholds changed and no fault retry sought a success. See `artifacts/teacher_demo/20261021/report.json` for exact IDs, timings, refusal and handover evidence.

The dashboard now requires actual fresh suitable measurements for its checklist and displays the current collection's latest completed window while the next one accumulates, retaining quality failures/history. Focused software checks passed; Brave visibly showed fresh native RTT/delivery/loss and topology on 21 October at 03:32 UTC. These later preparation checks do not alter the frozen submission scope above or qualify trained-model actuation.

**Later manual handover:** the user's subsequent leave-running request uses the [manual live-session guide](TEACHER_DEMO_LIVE_SESSION.md). The existing qualified store is running on **8502/API43989**, with original `teachlive_03f4798225`, healthy 8/5 Mbps UDP, bounded 900-second traffic/600-second collector, measured qualified baseline and no new fault/workflow yet. Commands and UI/store binding were verified. This is an explicit observed-only repair demo; canonical 8501 retains the trained model. `artifacts/teacher_demo/interactive/handover.json` records current-window proof and expiry times. No automatic end cleanup was run; no new original repair success is claimed.

## Recorded successful Stage 14 rehearsal — 19 October 2026

- Run: `207c58ab`, source `demo14_207c58ab`; executed 2026-10-19 UTC.
- Incident `if160fe414bf940f48e4cf992f2bf33d5`, workflow `wfb0c4667d62145f2a5cb23b9f0f9ae7a`, action `a8dd81442902d4b03b511cd4ca932c8d3`.
- Actual twin mean RTT prediction: 4.175 ms; original settled mean: 4.229 ms. The impairment/workload stayed active through verification and Undo.
- Application: 955.53 ms; verification: 27.11 s; complete rehearsal including UI/Undo/cleanup: 414.08 s (6.90 minutes).
- Whole native intervals overlapping application recorded critical loss **136/1717 packets (7.92%)**, and bulk **0/1042** over approximately two seconds. They include adjacent traffic and do not locate sub-interval loss. Settled verification's zero measured loss is a separate outcome.
- Healthy control refused unnecessary repair. Collector continued during twin work. Health responses were 40.25 ms mean / 69.62 ms max; Stop Automation acknowledged in 30.99 ms.
- Undo was intentional after verified success. It is recorded separately from failed verification/automatic rollback. Final source stopped, socket removed, no rehearsal services/bridges remained, auto-repair and observed-only exception disabled.
- Raw evidence: `artifacts/stage14/rehearsals/207c58ab/`; summary: `artifacts/integration_validation_report.json`. These completed measurements are now recorded evidence, not live telemetry.

## Remaining limits and final claims

The final submission describes the integrated local application, complete measured dataset, calibrated held-out results with sample limits, real SHAP, isolated twin comparisons, qualified observed-only original recovery, fresh Undo and honest rejection behavior. Stage 15 created a 22-page report, 18-slide deck, eight-page group script and three-page viva guide, plus reproduction/index/evidence files and a verified ZIP. No new training, held-out scoring, packet campaigns or policy changes were performed.

Trained-model original actuation remains unqualified: the separate Stage 13 live diagnosis was uncertain despite high calibrated confidence and its repair was refused. Loss, saturation, QoS, TCP-bulk latency and larger-topology repairs remain refused/unqualified. All-fault repair, arbitrary-network generalization, larger-topology model transfer, globally atomic/zero-loss forwarding and clean-machine deployment are unsupported. Stage 15 submission work is complete; these research and production limits remain explicit.

## Group members

- Visweswar Sarma — [registration redacted]
- Shafin Khan — [registration redacted]
- Anushka Jain — [registration redacted]

See [DEMO_GUIDE.md](DEMO_GUIDE.md) for exact startup, readiness, demonstration, recorded fallback, shutdown and troubleshooting commands. No raw corpus, environment credentials or machine-specific temporary audit files are packaged for handover.
