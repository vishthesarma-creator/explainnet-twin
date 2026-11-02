# Datasets models and local evidence

The public repository includes collection/training/evaluation code and safe schedule declarations. It intentionally does not distribute local databases, packet captures, root ownership journals, job receipts, trained executable model bundles or generated submission packages. No public download of those private artifacts is promised.

## Generate a dataset in a new isolated laboratory

Follow the portable installation and separate-agent startup in the README. These are deliberate, potentially long-running operations for your own environment; they are not run by cloning, startup or this publication. Never run them concurrently with an existing campaign on the same emulator host.

```bash
# Ordinary-user terminal, API and separate privileged agent already running.
.venv/bin/explainnet --config config/local.json dataset-plan config/datasets/pilot_v1.json
.venv/bin/explainnet --config config/local.json job PLAN_JOB_ID
.venv/bin/explainnet --config config/local.json dataset-start BATCH_ID
.venv/bin/explainnet --config config/local.json dataset-status BATCH_ID
```

Read the actual job and batch IDs from the response. A successful start job does not mean collection completed. Wait for complete suitable windows, successful restoration/cleanup and a passing pilot audit. Then explicitly plan/start `config/datasets/main_v1.json` using the same commands. Do not count pilot windows toward main acceptance.

```bash
.venv/bin/explainnet --config config/local.json dataset-export BATCH_ID
.venv/bin/explainnet --config config/local.json dataset-cancel BATCH_ID
# Explicit resume only after inspecting the failure and remaining attempt budget.
.venv/bin/explainnet --config config/local.json dataset-resume BATCH_ID
```

Exports live below the configured `data_dir/datasets/BATCH_ID/`. Preserve `manifest.json`, the schedule, checksums, feature CSV, separate ground-truth labels, episode/family splits, provenance, rejected observations and quality report. IDs, labels, injection settings and split membership must never enter inference features. Keep missing values null. Existing stores are migrated, never deleted during setup.

The compact historical schedule targets360 main windows and is a development reproduction, not fulfillment of the3000–5000-window research target. The legacy `expansion_v1` repeats compact signatures/seeds and must not be advertised as a fresh confirmatory holdout. `completion_protocol.py` declares the later representative protocol, whose local campaign stopped at402/3600 windows. Its exhausted episode attempts require diagnosis and a reviewed protocol decision before resume; this publication does not start or repair that campaign.

## Generate and load a local model

Only after a complete eligible main corpus and passing provenance/quality checks:

```bash
.venv/bin/explainnet --config config/local.json model-train BATCH_ID
.venv/bin/explainnet --config config/local.json job TRAIN_JOB_ID
.venv/bin/explainnet --config config/local.json model-status
.venv/bin/explainnet --config config/local.json model-inspect MODEL_ID
.venv/bin/explainnet --config config/local.json model-load MODEL_ID
```

Training fits preprocessing/RF and healthy Isolation Forest on training observations. Validation handles declared selection/calibration/thresholds. Keep the final holdout sealed until the dataset/model/background/protocol/evaluator are frozen. The new representative freeze/evaluation remains unfinished. Do not use the old narrow score as acceptance for a new corpus.

Model files and manifests are generated inside the configured store, with compatibility and trusted-hash checks. Restore only a trusted complete archive from its owner, with matching manifests, versions and checksums. Joblib/pickle files can execute code; do not load untrusted downloaded models. A fresh clone has no compatible active model or saved SHAP until these prerequisites are supplied/generated. Rules alone never establish trained-model recovery.

## Recreate an explanation

With an actual suitable observation and registered compatible model:

```bash
.venv/bin/explainnet --config config/local.json model-infer MODEL_ID WINDOW_ID --mode live
.venv/bin/explainnet --config config/local.json explain MODEL_ID WINDOW_ID --mode live
.venv/bin/explainnet --config config/local.json explanation EXPLANATION_ID
```

Inspect returned job/explanation status. A matching ready result must bind the same observation/model/mode and training-derived background. SHAP explains raw RF probability, not calibrated confidence or proof of physical cause. No example values substitute for measurements.
