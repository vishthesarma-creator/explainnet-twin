> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# Completion Prompt 2: trained diagnosis, observable twin and gated recovery

Execution: 27–28 October 2026 UTC. This stage integrates existing components and performs bounded development checks. It does not retrain, expand dataset membership, rescore sealed tests, run final ablations/scale campaigns or redesign the dashboard. The final machine-readable record is `artifacts/completion_stage2_validation.json`. Its timestamps and terminal status supersede intermediate progress snapshots.

## Prerequisites and preserved state

`AGENTS.md`, `ENVIRONMENT.md`, the completion audit/Stage 1 report and validation, architecture, model/feature/service/twin/recovery policies and relevant code were read. Stage 1 was rechecked with 31 passing lifecycle/transport cases before integration. A recoverable 241-file source/configuration/test/document checkpoint is recorded by `artifacts/completion_stage2/checkpoint.json`; the prior working tree was entirely untracked. Source changes are compared against that checkpoint, rather than assuming Git HEAD is a recoverable baseline.

The canonical **trained** profile is dashboard **http://127.0.0.1:8501**, API **38223**, configuration `artifacts/stage6/runtime/config.json`, database `/home/USER/.local/share/explainnet/stage13/data/explainnet.sqlite3`, root socket `/run/explainnet-stage6-38223/agent.sock`. Launcher/backend configuration identity is checked before native verification. The active model is **m20261016T074751_a92c0db8f44e**.

The separate **observed-only** application remains dashboard **8502**, API **43989**, configuration `artifacts/stage14/rehearsals/bb745a91/config.json`, Stage 14 rehearsal store/socket/root owner. It has no active model. Its unrelated `teachlive_cacc533e6c` network and running process identities are left untouched; its previously bounded traffic/collector expired. Its backend remains the previously loaded `workflow_v1` process until an explicit idle deployment; it does not provide this stage's trained-path acceptance. No model/store rows were copied, merged or disabled.

Frozen model bundle/report/manifest, datasets, dependency declarations, sealed result bytes and earlier audit/failure artifacts remain preserved. Model file SHA-256 values are:

- Bundle: `f59033802dcd52de13bf6fbec1d4fede2b5dd2fc3728ae85ddf65a0b130cd67d`.
- Validation report: `e5d61fff6b2faff5afb5755f5db489a7419e2161cf0323d8cebcea07395a7aab`.
- Manifest: `8bb5f2ad41dc4999a74b604a2975d73c572eaf346b10408f613866eb1d7cd692`.

## Integration and concrete defects fixed

1. **Consistent service evidence.** `critical_service_v2` inherits the existing recovery critical class: RTT **p95 ≤20 ms**, loss ≤0.02, UDP jitter ≤5 ms and delivered critical demand ≥0.90. A generic 100 ms application objective may not relax this class. Monitoring, trained-model corroboration, ranking and original verification share the resolver/evaluator, including missing values and demand handling. Optional nominal references may tighten monitoring. See `SERVICE_REQUIREMENTS.md`. These bounds were not selected from the 66 ms demonstration outcome.
2. **Actual trained lineage.** Normal loading verifies the 21-feature order, units, schema, preprocessing/class map, dependencies and immutable hashes. Current IF/RF/calibration and asynchronous training-background SHAP run on fresh complete observations. The primary coordinator diagnosis/explanation refers to the same immutable snapshot window; initial diagnosis remains recorded. Raw RF SHAP contributions/additivity remain separate from calibrated confidence. Pending/failed/unsupported explanation or model abstention prevents integrated recommendation/application. Live incident identity now joins collector/capture/monitor observations through actual traffic-run/agent/path identity, avoiding duplicate incidents for one workload.
3. **Capture protocol and snapshots.** Schema-2 snapshots add the hashed shared service contract and fixed measurement protocol, preserving the explicit observable allowlist and schema-1 history. Symmetric three-echo probe warmup is recorded outside the measurement interval; all in-window samples remain. Reconstructed impairment settles for a fixed three seconds after installation. No sample-dependent retry, RTT clipping or fidelity relaxation was introduced.
4. **Concrete cadence overhead.** Ownership was repeatedly checked with per-bridge subprocesses under the shared manager lock, including duplicate observation checks. One fresh coherent OVSDB transaction now validates every required bridge's instance/token. Authorization is not cached. Observer lock-wait/ownership/total durations are recorded separately from collection duration. The corrected latency controls have sufficient coverage; initial failures remain failures.
5. **Correct reset comparison.** Native QoS reset restored the installed hierarchy, classes, filters and seed, but raw `qdisc show` differed only in `direct_packets_stat 0 → 1`. Reset now excludes only this changing packet counter from configuration comparison and preserves the raw before/after evidence. Changes to delay, seed, limits/classes/filters still fail verification. The original failed QoS job and inspected readback remain; its verification instance was explicitly torn down through the scoped API before owner deployment. Fresh QoS reset/cleanup subsequently succeeded.
6. **Candidate diversity and bounded lifetime.** `workflow_v2` defaults to two distinct feasible repairs plus C0, two repetitions and at most two hypotheses; captures last 15 seconds. Existing reroute, broader reroute, background-shaping and approved-QoS families retain capacity, no-op, forbidden-target and protected-traffic constraints. A typed streamed `workflow_observation_v1` workload route and explicitly bounded collector duration (maximum 1200 s, default 180) support the declared 900 s verification workload. Preflight derives the required remaining lifetime from actual trial count plus verification/rollback. Nothing silently renews expiry.
7. **Recovery and evidence usability.** Original permission remains **reroute only**. Existing ownership/version/drift/expiry, one mutation owner, idempotency, pre-mutation journal, readback, two post-action windows, connectivity/protected traffic, rollback/Undo, cooldown and attempt bounds remain. A lifetime countdown is excluded from installed-configuration equality so it cannot falsely invalidate Undo. Dashboard large GET evidence now hydrates explicit bounded pages with offset/size/SHA-256 checks; the 4 MB normal response limit and no mutation retry remain. Nested rejection rows show actual residuals/tolerances, missing/contaminated/stale evidence and candidate constraints. No dark/four-page redesign was performed.

## Controlled investigations and declared experiments

The historical failed control (`e1be0accd25e3472f8ddf13590b93147c`, workflow `wdface540327049068407aa887e0efa1e`) had original echoes about 66.2–66.8 ms; its first twin echo was 97 ms, with later echoes about 66.2–66.8 ms. This explains its p95/variability residual but does **not** prove the physical cause. `historical_fidelity.json` preserves the inspected probe data.

The fixed investigation ran **two fresh-runtime C0 controls with the legacy protocol** and **two with fixed warmup/settling**. All four passed unchanged tolerances. Thus the historical outlier was not reproduced, and a cold-start/queue/scheduler cause is not established. These controls had no continuous collector, unlike the later integrated experiment. An earlier rejected setup/version request remains in `investigation_legacy_setup_failure.json` and is not counted as a packet control.

`main/plan.json` declares one independent source episode each for healthy, latency, loss, saturation and QoS. All attempts remain preserved. Latency/loss had supported trained diagnoses but insufficient first-control sampling; saturation/QoS refused unsuitable coordinator observations. Main QoS's reset error is retained separately from its workflow refusal.

After the concrete ownership-cadence/reset fixes, **one corrected implementation set**, `verified/`, was declared before execution. It uses the same recipes/models/confidence/fidelity/protected gates and one new source per condition. Each candidate trial uses a fresh twin reset; two repetitions per retained hypothesis are **trial units**, not independent source episodes or independent packets. No failed control was discarded or rerun within an experiment. Exactly one further fresh automatic latency episode was conditional on trained assisted success. There is no favorable-sample retry loop.

**Sampling-bound erratum:** the initial protocol-amendment prose said five seconds. The unchanged capture materializer actually declares a 2.5 s interval and aggregation permits at most 2.5 times that interval: **6.25 s**. The checkpoint confirms this was already present. Initial original gaps about 7.075/5.293 s yielded 0.3528 coverage; the twin gap about 6.342 s and later out-of-window point yielded zero coverage. `verified/sampling_bound_erratum.json` preserves the correction without rewriting the earlier declaration.

## Measured per-condition results

| Condition, corrected set | Actual trained diagnosis/SHAP | Twin/candidates | Original result |
|---|---|---|---|
| Healthy | Healthy argmax, calibrated confidence **0.6343**, uncertain below 0.70; matching SHAP ready | Service acceptable; no twin/candidate mutation required | Correct no-action refusal; active owner released |
| Latency, assisted | Snapshot calibrated confidence **0.938904**, supported; matching SHAP ready; raw RF output **0.981458** | **Four passing C0 controls**, both distinct reroutes measured in two repeats across both hypotheses: **12 trials total**, 8 repair measurements; both qualify | **Succeeded**, two fresh suitable original windows, connectivity/protected checks; Undo restored previous route; scoped cleanup succeeded |
| Loss | Snapshot confidence **0.935444**, supported, matching SHAP | First C0 refused: probe-loss original **0.142857**, twin **0.388889**, residual **0.246032 >0.03**. No repair measurement after failed control | No application; scoped cleanup succeeded |
| Saturation | Snapshot confidence **0.936457**, supported, matching SHAP | First C0 insufficient: RTT variability original **1.257079**, twin **11.165472 ms**, error **9.908393 >3.628539 ms**, plus insufficient twin sampling/quality. No repair measurement | No application; scoped cleanup succeeded |
| QoS | Preliminary current-observation confidence **0.940623**, supported, matching SHAP | Coordinator's later fresh window lacked required RTT mean/p95 (15 probes transmitted, zero received). Refused before snapshot/candidate experiment | No application; reset and scoped cleanup succeeded |

The automatic latency outcome, final timings/software receipts and safe runtime state are in the terminal-readback appendix below. The validation JSON retains exact IDs, all quality counts, residuals, candidates/rejections, lineage, original windows, durations, Undo/rollback and source hashes. Saturation's twin coverage was **0.515513**, below **0.65** (original 0.819268). QoS's missing-RTT coordinator capture is `wfb39af5ecaba4e5e87a074ed380dfe0f`. Its aggregate window was inference-ready for the frozen model's permitted missing-value treatment, but recovery independently requires observed RTT; model imputation does not satisfy that requirement.

The assisted latency workflow is `c2w_070bb955220c4224bcfc6629d16d4ddb`, experiment `e51d56aa193a6442084726c588bc6936f`, action `c2a_800dc08f2703432b8a47ee129df6bb49`. Original pre-action p95 was **66.7 ms**, post-action p95 **5.16 / 5.05 ms**, critical receiver delivery **7,999,188 / 7,999,973 bps**, UDP loss **0 / 0**, coverage **0.9253 / 0.9384**. The source workload and impairment stayed active during verification. Undo was a real root restoration, not scenario reset or traffic cessation. Transient disruption is recorded separately from settled windows.

Loss probe counts are small: the strict 0.03 loss tolerance is much smaller than the binomial uncertainty of a short lossy probe sample. This is a protocol/identifiability acceptance blocker, not proof of a particular physical cause. Saturation's variability/coverage failure is also preserved without attributing it solely to warmup or host pressure. QoS retains null RTT rather than manufacturing a value. **Two measured feasible repairs per fault remains open for these three conditions.** Software feasibility fixtures are not packet evidence. Loss reconstruction also retains untried directional hypotheses; reverse-path probe loss is not proof of forward UDP loss, and resolving direction/location requires observable evidence.

## Model support and scientific limits

The existing development validation report records IF detection **12/48 faults**, healthy false alerts **0/12**, original-policy support **24/60**. These are development/threshold-selection observations. The IF threshold remains **0.6224401399531727**; confidence/margin remain **0.70/0.15**. Current latency can be non-anomalous by IF yet supported by measured service degradation and high calibrated RF confidence. That is the intended separation of anomaly, diagnosis and service evidence. The compatible frozen model and training-only SHAP background were actually used; no observed-only fallback closes this acceptance.

No feature/domain incompatibility prevented the successful trained latency path. All four fault preliminary observations produced supported predictions; QoS's coordinator refusal is measurement quality, not replacement of a missing model. Healthy uncertainty is retained. These limited source episodes do not establish broad model/recovery effectiveness or calibration generalization.

Historical Stage 11 verification-failure, partial-application and interruption/restart rollbacks are retained in `artifacts/recovery_validation_report.json` and the linked native directories. They provide separately labeled real rollback evidence under the existing safety mechanisms; they were **observed-only**, and are not new trained-path rollback successes. Normal failure hooks remain disabled.

## Launch, review and bounded reproduction

From Windows PowerShell in `/path/to/user\Desktop\CN project`:

```powershell
function en { wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/app.py @args }
en start
en status
```

If the trained privileged owner is absent and its journals/resources have been explicitly reconciled, use a separate root OS-Python command:

```powershell
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- /usr/bin/python3 scripts/manage_agent.py --profile trained start
```

Review recorded evidence at **http://127.0.0.1:8501/recovery** → **Refresh now** → **Recorded recovery workflow** → select the workflow above. Read the original action's verification/Undo separately from the experiment's later stale status: cleaned/expired evidence is historical and cannot be applied now. **Digital Twin & Recommendations** selects the experiment and shows all controls, both candidate actions, residuals and ranking; **Incidents & Diagnosis** shows the same model/window explanation. Keep the shared profile/automatic-repair status visible.

Read-only status and complete JSON evidence collation:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/completion_stage2.py status --run-id verified
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/record_completion_stage2.py
```

A **new intentional demonstration** of latency can use a new run ID, for example:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/completion_stage2.py run --case latency --run-id teacher_stage2_demo
```

That command creates its own original, healthy pilots, fault, collector, trained explanation and repeated twin comparison; it applies an assisted repair **only if currently eligible**, verifies, performs safe Undo and cleans only its own verification resources. It refuses an already attempted run ID and any existing canonical live original/unsettled action. It is a bounded development demonstration, not a dataset campaign, guaranteed success or a leave-running healthy session. Watch 8501 while it runs. No foreground terminal is needed for detached API/UI/root services; keep WSL running. The driver terminal must remain open until its final report/scoped cleanup.

To resume an interrupted verification plan, inspect `status` and the persisted jobs/control/root state first. Once safe, `run --case all --run-id verified --resume` skips already attempted files; it never silently repeats a refused or failed episode. Unknown mutations and blocked cleanup require explicit reconciliation, not deleting case files or databases. The final-state appendix says whether any such reconciliation remains necessary.

## Dependencies for Prompt 3

Use `COMPLETION_TRACEABILITY.md` with the preserved audit. First resolve the three open fidelity/measurement requirements with predeclared observable hypotheses and sufficiently informative bounded sampling, retaining these failures and strict gates. Measure two distinct feasible candidate changes for each remaining fault. Revisit loss direction/data-versus-probe identification and QoS RTT observability; a higher RF confidence does not fix either issue. Original QoS/shaping application is still outside the current allowlist and requires separate verification before expansion.

Prompt 3 must explicitly predeclare permitted corpus expansion/splits, calibrated support/IF sensitivity evaluation, fair threshold/no-twin/no-XAI comparisons, independent repeated 5/10/15-switch measurements and end-to-end timing. Preserve this frozen model/test cutoff and do not tune on sealed tests. The 3,000–5,000 window target, broader macro-F1 ≥0.85 and integrated decision <10 s remain unclosed. Normal application startup never starts those campaigns. Prompt 4 retains the four-page/dashboard design work. Stop here after Prompt 2.

## Terminal readback, software and timing appendix

Final acceptance is **implemented with open all-fault qualification blockers**. Trained assisted and explicitly enabled automatic latency succeeded; loss/saturation/QoS recovery and their two-candidate measurement requirements remain open. No observed-only result is used to close trained acceptance.

The independent automatic latency workflow `c2w_ac796ce4c5d34c3ebbc4b7278f579425`, experiment `e8cae1159a357497cbbeaa986c47c9aa4`, action `a3758b721710843dda8c52e70dbbf85fc` used snapshot confidence **0.939887**, ready matching SHAP (raw RF **0.990833**, additivity error about **2.22e-8**) and IF score **0.572629**, below its unchanged anomaly threshold. Actual shared service degradation corroborated the fault. It passed four C0 controls and both reroute candidates across all 12 trials, applied through the automatic gate and verified two original windows: p95 **4.42 / 4.54 ms**, delivery **8,000,112 / 8,000,102 bps**, UDP loss **0 / 0**. Safe Undo and scoped cleanup succeeded. The assisted and automatic actions/workflows are now **rolled_back** in the backend because of intentional Undo; the saved pre-Undo action results retain the successful verification. Current experiment GETs correctly say **stale** after source cleanup; historical eligibility is not executable permission.

**Software:** final focused unit/API/AppTest regression **175 passed**, **0 failures**, **129.50 s**, `final_acceptance.xml`; the earlier 130-case batch also passed. Ruff passed changed implementation/test/helpers. Existing Starlette/httpx TestClient deprecation remains; no dependency was changed. Intermediate failing fixture/setup receipts remain preserved and are not the authoritative final result. New fixtures cover shared service consistency/missing demand, model corroboration/healthy abstention, snapshot allowlists, two feasible distinct actions for all four observable testbed conditions, paged detail integrity/shape, ownership batching, counter-only reset comparison, incident deduplication and countdown-safe readback. Fixtures are not packet measurements.

**Actual dashboard transport:** `check_completion_stage2_reads.py` retrieved the **580,842-byte** completed workflow through schema-2 hash-addressed pages with all 12 trial rows/two repair candidates intact. The experiment detail contained 283,997 compact bytes. Hashes of the selected persisted workflow/experiment rows were identical before and after reads. Historical/stale semantics were correct. The same checks passed after the final ordinary API/UI reload.

**Visual limitation:** the native browser helper stopped because it could not determine Brave's current URL confidently. UI automation stopped immediately; no alternative automation bypass was used. There are **no fresh Stage 2 screenshots or completed visual page inspection**. Stage 1's 12 profile/page route/reload checks and screenshots remain historical prerequisite evidence. Final AppTest/API checks passed, but they do not substitute for the missing post-integration visual inspection. The current pages/refresh controls still need a manual browser review. The computer-use skill was read at `/path/to/user/.codex/plugins/cache/openai-bundled/computer-use/26.1021.31345/skills/computer-use/SKILL.md`.

Measured runtime components use monotonic clocks:

| Component | Trained assisted latency | Trained automatic latency |
|---|---:|---:|
| Initial two-window observation | 25.155 s | 24.092 s |
| Primary model inference computation | 90.852 ms | 129.106 ms |
| Matching SHAP computation | 490.727 ms | 386.188 ms |
| Snapshot capture/materialization | 21.659 s | 18.132 s |
| Initial twin construction | 10.095 s | 10.015 s |
| Candidate experiment, 12 trials including construction/reset/cleanup | 478.133 s | 475.152 s |
| Coordinator workflow | 530.682 s before assisted application | 573.525 s including automatic application/verification |
| Native original application | 713.928 ms | 1,029.131 ms |
| Original settled verification | 29.367 s | 31.621 s |
| Whole action including preflight/verification | 47.534 s | 51.334 s |
| Independent source episode including pilots, Undo and cleanup | 670.790 s | 662.518 s |

`native_capture_timings.json` extracts **28 saved trial captures**, zero missing native references: two initial refused controls and 26 corrected-set trial captures. Corrected matched-capture elapsed durations ranged **15.749–18.193 s**; in-window sampling gaps **1.755–4.607 s**, below the unchanged 6.25 s overrun bound. Mean ownership-check time across corrected plane summaries was about **9.975 ms**. Exact per-trial reset, paired-capture, warmup and observer-component durations are retained. The completed packet set did not independently instrument every full trial's application/materialization wall time; source instrumentation for these separate fields and pre-application `decision_total` was added/tested for subsequent runs. Missing historical fields stay null. This is not an integrated <10 s success: observation alone exceeds that target and measured candidate decisions take minutes.

Practical future demonstration estimate: about **11 minutes per qualified latency episode** on this host, based on the two measured episodes above; expect scheduling uncertainty, and a refused control can end earlier. The corrected healthy/four-fault/conditional-auto set totaled about **31.5 minutes of source-episode work**. This is a local development estimate, not a runtime guarantee or a forecast for the full corpus/scale campaign. Source traffic/collectors were explicitly 900 s, candidate timeout 700 s, workflow timeout 900 s and maximum original action 150 s, with lifetime gates enforced.

Final read-only identity/safety proof is `artifacts/completion_stage2/final_state.json` (UTC timestamp in that artifact):

- Both APIs/agents and dashboards respond; trained profile/model/store binding is correct. After final deployment trained API PID **482722**, UI PID **482768**, root owner PID **360469**. Root remains separate OS Python. No observed-only process was restarted.
- Both profiles are **Recommend**, automatic repair **false**, observed-only consent **false**, active workflow **null**, no active monitor, unsettled actions or pending workflow cleanup.
- All new Stage 2 originals/twins are stopped; raw files/root journals/failed experiments remain. There is no Stage 2 traffic/collector expiry or foreground terminal to keep open. Keep WSL running for the detached services.
- The unrelated observed-only original `teachlive_cacc533e6c` remains verified running, with its earlier finite traffic/collector expired. It was not reset, renewed, torn down or used as trained evidence.
- Dataset membership is still **240 train /60 validation /60 sealed test /10 pilot**, model registrations **one** in the trained profile and **zero** in observed-only. All **30** preservation checks pass, including model/dependency/configuration/audit and sealed-result byte hashes. Sealed results were hashed, not rescored/interpreted.

No global cleanup is needed. A future bounded Stage 2 demo cleans its own original after Undo. To stop only the idle canonical application and root owner afterward, preserving evidence:

```powershell
en stop
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- /usr/bin/python3 scripts/manage_agent.py --profile trained stop
```

These commands refuse unsafe owner shutdown where applicable and do not touch the observed-only laboratory. Immediate next click: **http://127.0.0.1:8501/recovery → Refresh now**, then select the assisted workflow above. Prompt 3 begins only with a new explicit instruction and the open-blocker plan; no dataset/evaluation campaign is running.
