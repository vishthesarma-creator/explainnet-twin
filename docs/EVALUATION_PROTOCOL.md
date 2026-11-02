# Stage 13 evaluation protocol

## Completion3 prospective successor (28 October2026)

The historical Stage13 protocol/results below remain sealed and preserved. New protocol: `artifacts/completion_stage3/protocol.json`; concrete native order/seeds: `labs/plan.json`;600-window untouched test/100independent episodes/10families. The new pipeline freezes model/background/full project source/config/protocol/native plan before access. `completion_evaluation.py` retains RF argmax/support/calibration, IF ranking, episode/family uncertainty, actual per-event raw-scale SHAP/additivity/stability and post-hoc no-XAI identity/overhead. Backend compatibility uses measured train examples, separately from frozen offline holdout scoring; fresh native sources exercise live trained paths. Three matched sources/primary approach retain impaired controls. Larger-topology transfer and every refusal stay explicit; no gate relaxation/test tuning. Current execution, blockers and timing boundaries: `COMPLETION_STAGE3.md`. Missing experiments remain pending.

The predeclared machine-readable configuration is `config/evaluation_stage13.json`; `artifacts/stage13/experiment_manifest.json` records execution intent. `collection_progress.json`, each lab case and the final evaluation report are checkpoints. The original target remains **360 main windows from 60 independent episodes**, with 240/60/60 train/validation/test windows and 40/10/10 episodes. The separate pilot is excluded from held-out evaluation.

## Collection and provenance

Accepted episode IDs, window IDs, labels, family assignments and raw hashes are preserved. Invalid, transition, incomplete and unsuccessful-attempt windows stay in the raw/index evidence and rejection lists, with no accepted membership. Injector settings remain solely in ground-truth/setup records. The inference matrix is the existing 21-feature measurement allowlist; no identifier, split, recipe, seed, fault location or recovery outcome is an input.

Stage 13 measured a final-receiver ingestion stall and a separate Windows-mount sampling bottleneck. Receiver arrivals now use one bounded fsynced append/index transaction, retaining JSONL recovery semantics. Hot data is in the Linux directory declared in the runtime config; the old Windows database is retained. Checksummed amendments preserve all collection gates and grant bounded further attempts only after a concrete fix. Early and resumed sampling/storage conditions differ; this can confound the compact dataset and is a reported limitation.

## Training, calibration and freezing

The explicit `stage13` training profile reuses the Random Forest, Isolation Forest, preprocessing, schema, decision policy and bundle registry. Every CV fold fits preprocessing on its training families. Four training families per class form four group folds. Three predeclared RF configurations are fit on all training data and selected using validation raw macro F1; first candidate wins ties. This is one bounded search, not a test-driven search.

The selected RF/preprocessor is frozen before sigmoid calibration on validation. Isolation Forest uses healthy training data only; its threshold uses the existing bounded validation tradeoff. Validation is reused for selection/calibration/thresholds, so all validation metrics are **development evidence**. The independent test is reserved for the frozen result. The earlier `stage7` profile is retained for historical reproducibility and is not silently relabeled.

`frozen_evaluation.json` binds the model registry manifest, complete dataset manifest, evaluation configuration and evaluator source hash before any test feature payload is read. Conflicting resume is rejected. Normal backend inference and SHAP continue to reject sealed test windows. The offline Stage 13 evaluator has the narrowly scoped test access; it persists predictions before separately reading labels/injector truth for scoring. There is no test-based tuning or repeated model search.

SHAP uses the existing underlying RF, its fitted preprocessing and a deterministic background sampled only from estimator-fit training groups. It explains raw RF probability, which is distinct from calibrated confidence and from physical causality. Actual backend checks use one measured validation observation per class, not fabricated test examples.

## Diagnosis and localization metrics

The report includes per-class precision/recall/F1, macro F1, accuracy, confusion matrix, five-class Brier sum (range 0–2), explicit class-ordered log loss, reliability bins, supported coverage and abstention/unknown rate. Both window and independent episode counts are stated. Episode predictions average class probabilities within an episode.

Uncertainty resamples complete episodes within each class with a recorded seed. Windows are never treated as independent repetitions. Only two held-out episodes per class share one family, so even the episode bootstrap has limited generality.

Detection replay starts at actual injector activation and records the first predicted-incident window timestamp. Window-end delay and native evidence-availability delay are separate. Historical replay does not supply an actual online detector timestamp; online delay remains null. Per-window inference runtime and real backend explanation runtime are separate from packet collection and HTTP/polling overhead.

Link localization remains an observed-counter heuristic. After predictions are saved, intended injector location is used only as an evaluation reference. Outcomes are correct, incorrect, ambiguous or abstained, with healthy false suspects explicitly retained. A suspect set containing truth is not counted as a unique correct localization. SHAP importance is not a link probability.

## Recovery comparison

The primary case is a new owned five-switch source, one-way high latency, 8 Mbps critical UDP, 5 Mbps bulk UDP and 1200-byte datagrams. Each approach has three independent sources with paired recipe seeds and fresh nominal pilots. The first trial is the already qualified twin-guided UDP latency case; remaining primary order is shuffled with seed 20261016. Workloads, durations, policy and severity are equivalent. Two within-snapshot repetitions do not replace independent source episodes.

The existing engine measures no-change and candidate trials after verified fresh twin resets. The fixed rule recommends the critical alternative route on a measured latency violation. The twin-guided approach selects only when all existing fidelity, feasibility, service, ambiguity, freshness and ranking gates pass. The fixed policy can coincide with the twin choice; no adaptive advantage is assumed.

All approaches receive the same read-only shadow twin evaluation, then matched fresh-pre/settling/two-window original verification. No change retains the impaired configuration. The fixed rule is applied only if its deterministic proposal is identical to the qualified selected action; otherwise it is explicitly rejected. Shared shadow-evaluation overhead is recorded separately and is not an intrinsic computational requirement of a no-change or fixed-rule algorithm.

The common twin measurement plane is summarized separately from original outcomes. Original results retain actual verification, disruption, rollback/rejection and prediction-versus-observation error. A twin-only result is never pooled as an original repair outcome. Fixed policy may match the twin choice; no superiority claim is presumed.

Observed-only operation requires an explicit mode request and is labeled separately. The trained path is attempted only with a real model, confidence/support, matching ready explanation and all unchanged recovery gates. A pending asynchronous explanation is re-read with matching lineage; pending, failed or mismatched SHAP still refuses application. Failure hooks are disabled. Healthy service must refuse unnecessary actuation.

Loss, saturation, QoS and TCP bulk latency are rechecked through the existing qualification workflow; refusals are evidence, not repaired cases. No fidelity or ranking threshold is lowered. Every attempted case, failure and cleanup result is retained.

## Scale and resources

The 10/15-switch definitions deterministically extend the alternate path and retain the six hosts, primary fault links and declared bottleneck capacities. Runtime switch names preserve the owner token and fit Linux's 15-byte interface bound. Each size is actually constructed, probed and observed under healthy/latency conditions. Construction/evaluation time, coverage and VM CPU/memory are recorded when available.

The corpus was collected on five switches. Unchanged feature names do not establish transfer to larger topologies; larger-size model validity is explicitly unvalidated. A size failing construction, sampling or fidelity retains its exact measured reason. Mocks are software evidence only. Resource measurements describe WSL and the shared emulator host, not separate physical network devices or total Windows usage.

## Resume and stop

From the documented Ubuntu workspace:

```bash
.venv/bin/python scripts/status_stage13.py
sudo env PYTHONPATH=src /usr/bin/python3 scripts/dataset_supervisor.py --schedule config/datasets/main_v1.json --runtime artifacts/stage6/runtime --resume db5a15991774142f0a8ef871522face4d --detach
.venv/bin/python scripts/evaluate_stage13.py audit
.venv/bin/python scripts/evaluate_stage13.py train
.venv/bin/python scripts/evaluate_stage13.py score
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json serve
# In a separate terminal while that API is serving:
.venv/bin/python scripts/evaluate_stage13.py backend
sudo env PYTHONPATH=src /usr/bin/python3 scripts/stage13_lab_supervisor.py --detach
# Use --resume CAMPAIGN_ID for an interrupted lab campaign; completed cases are skipped.
.venv/bin/python scripts/evaluate_stage13.py report
.venv/bin/python scripts/check_stage13_dashboard.py
```

Use the configured dataset cancel operation to stop collection. Lab campaigns run sequentially under the existing experiment lock, preserve each case, remove only owned resources and disable auto-repair/observed-only enablement afterward. Root agent and unprivileged API/venv remain separate. No Stage 14 work or final presentation is included.
