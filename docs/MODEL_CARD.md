# ExplainNet Twin local models

## Completion3 prospective model — not yet trained (28 October2026)

The historical active8501 model below is preserved. New completion3 training is gated on the separate audited3600-window corpus. It uses four family folds across8train families/class, bounded3candidate160tree RF search, healthy-training-only160tree IF, training-only preprocessing, validation selection/calibration/thresholds, unchanged support policy and embedded24-row train-only SHAP background. Immutable metadata binds dataset/split/protocol hashes, seed20261028, dependencies, topology and service versions. Larger-topology predictions retain RF outputs but abstain from supported application. Test access requires the full pipeline freeze; actual new performance/SHAP readiness remains pending in `COMPLETION_STAGE3.md`, not implied by software checks. No confidence forcing/observed-only substitution.

## Completion stage 2 runtime-policy addendum (2026-10-28)

The active frozen bundle remains `m20261016T074751_a92c0db8f44e`. No fitting, new publication, calibration or sealed-test rescoring occurs here. The normal loader checks the exact 21-feature order/units/schema hash, training-fitted preprocessing, class order and registered file/dependency hashes. Training-only estimator-fit SHAP background and raw RF contribution scale remain separate from calibrated confidence.

Fresh inference uses `critical_service_v2`, shared with monitoring/ranking/verification, for corroborating service evidence. This resolves the 100 ms diagnosis versus 20 ms recovery mismatch using the existing critical class. It does not lower the IF threshold (0.6224401399531727), confidence (0.70), margin (0.15) or domain gates. `service_evidence` records actual values, thresholds, missing inputs and version. Healthy uncertainty remains valid.

The immutable development validation report records IF detection **12/48 fault windows**, healthy false alerts **0/12**, and original runtime-policy support **24/60**. These are threshold-selection/development observations, not independent final evaluation. A non-anomalous IF result does not negate measured service degradation. Historical validation diagnoses retain their original policy. Fresh per-episode support, uncertainty, raw/calibrated probabilities and matching explanations are reported separately in `COMPLETION_STAGE2.md`; observed-only evidence cannot close trained-path acceptance.

## Stage 13 measured model (2026-10-19)

Model `m20261016T074751_a92c0db8f44e` is trained, calibrated and registered. The main measured dataset is complete: 360 windows / 60 episodes, split 240/60/60 across train/validation/test with disjoint recipe families and episodes. The explicit `stage13` profile fits preprocessing and the final Random Forest on all 240 training windows; validation selects among the three declared candidates and fits sigmoid calibration without refitting the estimator. Healthy training data fits Isolation Forest; validation selects its bounded threshold. The legacy Stage 7 profile remains available for reproducibility.

The October 16 frozen evaluation reports test accuracy and macro F1 **1.000**, Brier sum **0.02147**, log loss **0.10833**, and supported coverage **58/60** (two unknown). This is only ten episodes, two per class sharing one held-out family per class. The episode bootstrap interval [1,1] does not establish broad generalization. Five real validation SHAP cases passed backend checks with training-only background; SHAP explains raw RF probabilities, not calibrated confidence or physical causality. Fresh train-window inference also passed the actual backend compatibility path.

The frozen artifacts and predictions are retained unchanged. `artifacts/stage13/posthoc_provenance.json` explicitly records a later dependency/settings receipt: the original freeze bound the evaluator file, evaluation configuration, dataset and model manifests, but did not bind every imported policy/localization module. No test was rescored or tuned to address this limitation. `evaluate_stage13.py score` now verifies and reuses saved results, refusing changed dependencies.

Only five-switch training is validated. Observed-only recovery results and model-gated attempts are reported separately. Current packet qualification is recorded in `artifacts/stage13/lab_report.json`; model accuracy does not qualify repair. See `docs/EVALUATION_STAGE13.md` and the machine-readable evaluation report for current limits.

## Historical Stage 7 checkpoint

The following records the earlier incomplete state and original training profile; the Stage 13 evidence above supersedes its readiness statement.

## Current evidence

Implementation is available. **No production model has been trained or published at this checkpoint.** The measured main dataset remains incomplete; the reserved validation partition is not yet usable. Macro-F1, calibration reliability, anomaly detection, abstention coverage and measured validation inference are therefore **unavailable**, not zero and not inferred from unit fixtures. Stage 8 is not ready.

The authoritative status snapshot is `artifacts/model_validation_report.json`. Collection status continues in `artifacts/stage6/runtime/supervisor.json`, the authoritative dataset manifest, `artifacts/dataset_quality_report.json` and `DATASET_CARD.md`. Initial Stage 7 inspection found 28 completed episodes, 168 stored accepted windows, 167 exported windows, and train-only coverage: healthy/saturation/loss/latency 36 each, QoS 24 stored. Tight timestamp tolerance restored the 168th export without modifying any raw observations or features. Structural reconstruction and partition checks then passed.

Duration-only recovery failed twice. Separate checksummed amendments retain the original schedule hash, recipe families, seeds, target windows and partitions; they declare 100-second measurements and bounded additional attempts for unfinished episodes. Sampling recovery removes the extra ping deadline and publishes feature history on window cadence or native receiver completion. Coverage, probe-count, receiver and contamination gates remain unchanged. Failed attempts and the startup delay failure are retained under `artifacts/stage7/` and existing native/raw archives.

Recovery also exposed SQLite contention between the polling worker, dataset and collector threads. The shared Store now serializes short transactions; transient polling locks are retried without killing the worker. Compact status/checkpoints avoid repeatedly embedding every earlier native receiver payload. Failure/thread liveness is explicit, and the same batch is resumed only after its previous supervisor verifies cleanup. The failed network-start attempt and terminal diagnostic are retained; no window from it is accepted.

The next measured attempt still had only four steady windows and failed while awaiting recovery ingestion, despite an actual native recovery of 1.9999 Mbps with 0% loss and a verified reset. It remains rejected. `cadence_recovery_v3` explicitly declares two-second sampling to match the observed observation latency, 35-second native-arrival grace and a 300-second collector bound. Existing 65% coverage, six-probe, required receiver and contamination gates are retained. Up to two further attempts are recorded for unfinished episodes. Sampling cadence differs between early and recovered episodes; this is an additional dataset limitation and must be carried into Stage 13 interpretation.

At **2026-10-07 09:10 UTC**, the seventh QoS attempt passed all application/restoration/cleanup gates and yielded six accepted windows. Actual coverage was 65.9–81.4%, with 12–15 transmitted probes and approximately nine seconds of receiver coverage per ten-second window. Native baseline/recovery delivered 1.9997/1.9999 Mbps at 0% loss; the active fault delivered 0.2898 Mbps with 85.28% receiver loss. `artifacts/stage7/cadence_recovery_verification.json` records the unchanged raw hash and window IDs. This is collection recovery evidence, **not model validation**. Main coverage reached **174/360 windows and 29/60 episodes**, still train-only. The same batch continues; no duplicate batch or trained model was created.

The closing `model_validation_report.json` snapshot records **180/360 windows and 30/60 episodes**, 36 windows/six episodes per class, all in train. Structural reconstruction and split checks pass. Validation/test collection and all measured ML results remain pending. Software verification passed 88 regression tests, then 38 focused checks including the additional cadence amendment test; Ruff and pip check passed. Full commands and the unassessed 0.85 ambition remain below.

## Intended inputs and preprocessing

The unchanged Stage 5 schema has 21 numeric measurement features, ordered lexically. Feature names, schema hash and per-feature units are persisted and checked. Labels, scenario recipes, fault locations, injection parameters, IDs, timestamps, seeds, paths and partition metadata never enter the input matrix. Test rows are skipped before numeric conversion; only their structural membership/checksums are checked.

Every Random Forest fold fits its own preprocessing on that fold's training windows. Final classifier preprocessing uses only estimator-fit training families. Optional missing values use training medians plus deterministic missing indicators. Optional columns wholly unavailable during fit are omitted, with explicit original-to-transformed mappings. Required all-missing inputs are rejected. RTT after all-lost probes remains null; the median is a model transformation, not an edited measurement. No scaling, row duplication or oversampling is used. Class-counter availability and missing indicators may encode workload/capability confounding; explanations must retain that limitation.

## Models and selection

- Seed: `20261007`; one process/thread per estimator to limit collection interference.
- Random Forest: 160 trees; three candidates `(depth=None, leaf=2, features=sqrt)`, `(depth=8, leaf=2, features=0.7)`, `(depth=None, leaf=1, features=0.7)`.
- Before selection, one randomly seeded training family per class is reserved for calibration. The remaining three families per class form three group CV folds with all five classes in each fold. Related repetitions/windows stay together. Selection metric is mean training group-CV macro-F1; first candidate wins ties. Class weighting is enabled only if the observed largest/smallest class count ratio exceeds 1.25.
- One underlying final RF and preprocessing pipeline remains accessible. Calibration uses sigmoid `CalibratedClassifierCV(FrozenEstimator(classifier))` on disjoint reserved training families. The frozen estimator's fit is a no-op; calibration cannot refit preprocessing/RF. The installed 1.9.1 API was inspected and tested. At least ten calibration windows and two episodes per class are required; otherwise probabilities remain explicitly raw/uncalibrated. One family per class is still weak evidence. [scikit-learn calibration API](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.CalibratedClassifierCV) documents the frozen-estimator and disjoint-data requirement.
- Isolation Forest: 160 trees, healthy training windows only, its own healthy-fitted preprocessing. No configuration sweep. Score is **negative `score_samples`**, so larger means more anomalous. It is not a probability. A bounded 21-quantile validation threshold search maximizes detection subject to at most 10% observed healthy false alerts. Every candidate and tradeoff is reported. Validation is development evidence because it selects this threshold; Stage 13 remains the independent test.

Expected complete compact coverage is 240 train / 60 validation / 60 sealed test windows across 40/10/10 episodes. The RF uses 180 estimator-fit windows and 60 calibration windows from train; IF uses all 48 verified healthy training windows. These are **targets**, not current completed model evidence.

## Decision policy

Predeclared confidence ≥0.70 and top-two margin ≥0.15 determine support alongside anomaly and service evidence. They are conservative heuristics, without test tuning or guaranteed error bounds. Raw and calibrated probabilities are separate and explicitly ordered `healthy, saturation, loss, latency, qos`.

Statuses are supported, uncertain, insufficient-data and stale. Schema/order/unit errors, physical-invalid values, required missing inputs, incomplete/unready windows and stale live observations abstain. Training-range checks allow half the observed span, at least 25% of the training maximum and small unit-specific floors; substantial excursions or new missing capabilities cause uncertainty. This does not guarantee unknown-fault detection. Healthy predictions conflicting with an anomaly, serious service violation or latched Stage 5 alert retain the incident and uncertainty. Fault predictions without corroborating service/anomaly evidence also abstain. Diagnosis never calls networking operations.

Recorded inference is historical and does not pretend old windows are fresh. Live inference requires a running collector and a completed observation no older than the configured 30 seconds. Native receiver data may arrive only at traffic completion, so earlier windows can already be stale. Live diagnosis skips dataset collectors to protect pending test membership; direct inference rejects accepted and pending test episodes. Results are persisted once per window/model/mode. Changed telemetry after a diagnosis retains the original result and returns uncertainty; stale views do not overwrite historical records.

## Artifacts and reporting

Bundles are written to `<data_dir>/models/<model_id>/` through staged verification, fsync and atomic rename. Their preprocessing, IF/threshold, RF/calibrator, schema/order/units, transformed mappings, class order, policy, training/validation/split hashes, dependencies, seed and selected parameters are retained. Older versions are preserved. A local SQLite registry anchors manifest/file checksums; API loading accepts a registered model ID, never an uploaded pickle or arbitrary path. Joblib artifacts are trusted local code artifacts, not a safe format for outside submissions.

When real training is permitted, the immutable validation report records per-class precision/recall/F1, macro-F1 and confusion matrices separately for training CV and validation; anomaly detection/false alerts; raw/calibrated Brier convention, reliability bins and episode counts; baseline and combined monitoring; abstention reasons/coverage; and inference runtime. Validation windows receive linked recorded diagnoses. The 0.85 macro-F1 ambition is checked against measured results. No SHAP, twin, repairs, dashboard or complete recovery evaluation is included.

## Reproduction (inside the existing WSL project)

Inspect collection first:

```bash
.venv/bin/python scripts/dataset_status_stage6.py --runtime artifacts/stage6/runtime
```

After the existing batch completes and passes its gates, explicit offline training creates a durable job and bundle:

```bash
.venv/bin/python scripts/train_stage7.py --config artifacts/stage6/runtime/config.json --batch-id db5a15991774142f0a8ef871522face4d
.venv/bin/python scripts/report_stage7.py
```

With the unprivileged API serving the same config, the job/API/CLI commands are:

```bash
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json model-train db5a15991774142f0a8ef871522face4d
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json model-status
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json model-inspect MODEL_ID
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json model-load MODEL_ID
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json model-infer MODEL_ID WINDOW_ID --mode recorded
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json diagnoses WINDOW_ID
```

Train/load/infer return job IDs; `job JOB_ID` retrieves results. Startup restores an explicitly activated trusted bundle but never trains. Training refuses incomplete data and repeated training against the same completed dataset hash. Focused unit fixtures are isolated under `tests/test_models*.py`; they provide software checks only. Before Stage 8, update this card with the completed measured report and actual trusted bundle ID.
