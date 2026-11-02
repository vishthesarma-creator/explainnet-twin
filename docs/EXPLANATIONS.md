# ExplainNet Twin explanations and incidents - Stage 8

## Readiness and actual evidence

Package 0.8.0 implements the independent interfaces. **Measured SHAP validation is blocked: no production model bundle exists.** Main collection stopped at 32/60 accepted episodes and 192/360 accepted windows, all train, after receiver intervals failed to reach the collector. The supervisor verified cleanup; collection was not restarted during Stage 8. Validation/test inputs remain unavailable for this stage. The Stage 7 model report is an earlier 180-window snapshot; the Stage 8 report records the current checkpoint.

`artifacts/explanation_validation_report.json` separates software checks, measured localization and unavailable measured SHAP. Its SHAP cases are empty and additivity/runtime/stability results are null. No background or production explanation is manufactured from unit fixtures.

Software checks used real sklearn Random Forests and SHAP 0.52.0 on **isolated unit fixtures**, covering all five native class indices and additivity. These are software correctness checks, not measured model performance. The initial regression run passed 104 tests; subsequent focused checks passed 23 tests, followed by two checks for the final monitoring/evaluation query changes. Ruff and pip check passed. The existing Starlette/httpx deprecation warning remains.

Independent localization used the earliest accepted window in each of 32 eligible measured episodes, selected without labels. Predictions were saved before separate ground-truth lookup. Outcomes:

| Experimental reference class | Cases | Saved localization outcome |
| --- | ---: | --- |
| healthy | 8 | No intended fault location; candidate rankings remain descriptive |
| saturation | 6 | Leading suspect matched intended experimental link |
| loss | 6 | Leading suspect matched intended experimental link |
| latency | 6 | Ambiguous candidates included intended link |
| qos | 6 | Leading suspect matched intended experimental link |

No selected fault case ranked an incorrect link in this small train sample. This is not an accuracy/generalization claim: related repetitions share recipe families, examples are train observations, ambiguity remains explicit, and intended location is an experimental reference. No parameters were tuned after inspecting these outcomes. Files: `artifacts/stage8/localization_predictions.json` and `localization_evaluation.json` (including prediction checksum).

Migration 6 -> 7 was first checked on a backup, then applied to the stopped runtime after verifying owner PIDs were absent and no batch was running. Hashes/counts for all existing application tables were unchanged. Evidence is in `artifacts/stage8/migration_verification.json` and `applied_migration.json`. No collector or network was started.

## Classifier and explanation scale

The engine uses `bundle['classifier'].named_steps['random_forest']`, not the calibrated wrapper or Isolation Forest. It transforms measurements once with the frozen `preprocessing` step and uses:

```python
shap.TreeExplainer(rf, data=transformed_train_background,
    feature_perturbation='interventional', model_output='probability')
```

The installed API signature and source were inspected; the call and multiclass shapes were tested. Current SHAP returns `(samples, transformed_features, native_classes)`. The normalizer also handles the older list-per-class shape, rejecting ambiguous/nonfinite shapes. The selected diagnosis class is mapped explicitly through `rf.classes_`; the diagnosis order `healthy, saturation, loss, latency, qos` is stored separately.

For that selected class:

`base_value + sum(signed_contributions) = underlying RF predict_proba`

Every ready result checks absolute error <= `1e-6`; a saved raw diagnosis probability, when present, must also match the underlying output within `1e-9`. Failure produces a failed explanation, never a replacement diagnosis. The scale is `underlying_random_forest_class_probability`: contributions are changes in a probability value, not calibrated confidence contributions. Positive supports that selected class relative to the background; negative opposes it. Calibrated probabilities and diagnosis confidence are separate fields. Isolation Forest anomaly scores are not explained as probabilities.

Interventional SHAP makes assumptions about feature dependence. Network measurements are correlated, and changing one measured feature independently need not describe a physically achievable intervention. Attribution describes model influence, not a physical cause or repair guarantee.

## Background and feature mapping

The background contains at most 24 windows. Eligible candidates come exclusively from **estimator-fit train groups**, excluding calibration groups, validation and test. Selection sorts `SHA256(seed:window_id)` without replacement. Dataset hashes must exactly match the immutable bundle; the checked training report supplies fit groups. The existing gated loader skips test values before numeric conversion. Frozen preprocessing is transformed, never refitted.

The separate SQLite background record retains model/dataset hashes, train window/group/episode IDs, selection recipe/seed, transformed matrix, column names and original mappings. Its content SHA256 is checked before constructing an explainer. Bundle files stay immutable. No production background exists at the current checkpoint.

There are 21 original measurements in lexical order. Optional missing values use training medians; deterministic missing flags follow the retained measurements. Optional columns wholly missing at fit are omitted explicitly. No scaling is introduced. Each contribution retains transformed/original names, original value (including null), original unit, transformed value/unit, training median and preprocessing/missingness flags. All original measurements and dropped-column information are also retained.

Missing indicators are labelled as flags, **not network measurements**. A median is a model transformation, not an observed RTT or throughput. At most three nonzero transformed contributions are ranked by absolute value, with deterministic tie ordering. No extra influential feature is invented when fewer exist.

Deterministic templates preserve supported/uncertain qualifications, original observations and units, affected service/path, raw influence signs, confidence availability and localization ambiguity. They use no external LLM, unsupported "high" comparisons or invented confidence. Observation time and saved diagnosis freshness are retained; an explanation of a saved diagnosis does not certify current network health.

## Incident lifecycle

`IncidentService` extends the existing incident table with indexed state and append-only events. Context is network instance, collector run, critical affected flow, observed selected path, forwarding version and recorded/live mode. The critical pair follows Stage 5 service objectives/probes. A new collector/path/forwarding context is a distinct incident scope. Historical replay is kept separate from live monitoring.

- A persisted latched baseline alert or incident-bearing diagnosis can create/update an ongoing incident. No new incident is created for each repeated window.
- Event IDs deduplicate repeated sources. Multiple sources for one window cannot count it twice as healthy evidence. Diagnosis/model/cause changes append evidence and explanation versions; prior results are retained.
- Start/update times are observation UTC timestamps. Severity distinguishes service violation, anomaly and unknown; service status is degraded, healthy or unknown. No injection timestamps are read.
- Resolution requires the configured number of consecutive, contiguous, fresh, complete, inference-ready healthy live observations (default two), without service violations, latched incident or anomaly. With an activated classifier, baseline-only healthy evidence cannot resolve its incident; the diagnosis must agree.
- Missing, stale, insufficient or uncertain evidence does not establish recovery. A gap resets the healthy streak. Out-of-order evidence is retained without advancing lifecycle state; late cause evidence within an already resolved interval remains linked to that incident. Historical healthy diagnoses never resolve a live incident.
- An unresolved incident with a stopped collector remains open with its last observed state; there is no automatic recovery timeout. A later incident in another collector scope does not imply the earlier one recovered.

The asynchronous worker polls fresh windows only from running collectors, skips active dataset collection and sealed/pending test members, and can create baseline incidents without any model. Recorded inference/explanations require eligible persisted diagnoses. Failures remain isolated from monitoring.

## Link localization

Classification and localization are separate outputs. `link_localization.py` uses the operator-visible critical path, valid directional utilization and this window's indexed network-agent samples. It uses matching interface identities and stable configuration/forwarding intervals; counter resets, invalid utilization and intervals outside the window are excluded. Queue counter intervals are bounded to five seconds. Class throughput samples are shown as observations, without inferred policy settings. End-to-end RTT/loss/goodput are retained but do not distinguish a particular link.

For each forward/reverse switch-link direction on the observed path:

| Observation | Score |
| --- | ---: |
| Measured queue drop rate > 0 | +3 |
| Valid utilization > 0.9 | +2 |
| Observed backlog > 0 bytes | +1 |

Queue hierarchy counters can overlap: per-interval maximum drop rate and maximum backlog prevent adding overlapping counters. These thresholds/weights are declared heuristics, not fitted probabilities. Tied top candidates remain a set; all-zero evidence is ambiguous. A unique leading score is labelled a ranked suspect, not proof of location. Host access links and receiver/host faults are not localized by these counters. Shared traffic can account for queue evidence. Reverse directions are retained because RTT/loss probes traverse both directions.

No SHAP importance, hidden journal, intended location, scenario label or configured injection loss/delay enters ranking. Observation configuration digests are used only to reject changing intervals, never as scored predictors. Approved QoS configuration corroboration is currently unavailable and explicitly null; observed class counters are not substituted for a policy. A separate evaluator reads experimental truth only after predictions are saved, records their checksum and never changes ranking or parameters. Test evaluation remains sealed.

## Persistence, cache and cost

Migration 7 adds incident state/events, background registry and durable explanation requests. Explanation records link window/model/diagnosis/incident, scale/class/base/output, signed mappings, top features, localization, background provenance, qualifications and runtime.

Requests return `pending`, `ready`, `failed` or `unsupported`. Missing persisted diagnoses or selected classes, stale/insufficient diagnoses and changed telemetry are unsupported. Pending work resumes after restart; terminal results/failures remain inspectable. Each ready/failed update is conditional on the request still being pending.

Cache keys include window content/feature version, model manifest, saved diagnosis/mode/class, transformed mapping, SHAP/algorithm/output scale and the background recipe/dataset hashes. The immutable recipe determines train matrix selection; the actual content hash is stored in ready results and validated. Changed model, features, diagnosis or recipe creates a new explanation record rather than overwriting history. The loaded RF/TreeExplainer is reused per model/background recipe.

The diagnosis callback only persists incident/request metadata. A dedicated `read-only-explanations` thread builds backgrounds and runs SHAP/localization. SQL reads fetch only indexed samples belonging to the window; decoding/scoring happens outside the database lock. There is one worker and a maximum 24-row background; no parallel estimator jobs or telemetry-thread SHAP calls. Total request runtime includes initial setup; repeated cached requests avoid computation. Storage is shared with telemetry, so short database transactions still contend; this is not a hard latency guarantee.

## API and CLI

The API returns a job ID for `POST /v1/explanations/request` with `model_id`, `window_id`, optional `mode` (`recorded` default). The completed job contains an explanation ID/state; SHAP may still be pending. Query:

| Route | Result |
| --- | --- |
| `GET /v1/explanations` | Worker state/errors/cache count |
| `GET /v1/explanations/{explanation_id}` | Stored result/status |
| `GET /v1/explanations/window/{window_id}` | Explanation versions |
| `GET /v1/incidents?instance_id=INSTANCE` | Observed incidents |
| `GET /v1/incidents/{incident_id}` | State, evidence history and explanations |

After the same dataset completes, Stage 7 publishes a usable trusted bundle, and the unprivileged API is serving the migrated configuration:

```bash
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json model-infer MODEL_ID WINDOW_ID --mode recorded
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json explain MODEL_ID WINDOW_ID --mode recorded
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json job JOB_ID
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json explanation EXPLANATION_ID
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json explanation-history WINDOW_ID
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json explanation-status
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json incidents --instance-id INSTANCE
.venv/bin/explainnet --config artifacts/stage6/runtime/config.json incident INCIDENT_ID
```

This checkpoint has no production IDs to substitute. The collector/API were not restarted just to demonstrate endpoints; API/job routes were verified in isolated integration tests, and installed CLI help lists the commands.

Reproduce reporting without training or network operations:

```bash
.venv/bin/python scripts/validate_stage8.py --config artifacts/stage6/runtime/config.json
```

Currently this saves actual train localization plus the blocked SHAP report. With an existing trusted bundle it selects the latest registered version (or `--model-id MODEL_ID`), processes actual validation windows, checks additivity/runtime, reports adjacent same-path/class attribution changes and seeks an actual insufficient validation-collector observation without modifying its measurements. No retraining occurs. The guarded snapshot/apply migration scripts are under `scripts/`; applying refuses a live old owner or running batch.

## Remaining gate

Stage 9 is **not ready**. Complete collection and Stage 7 measured training/validation first. Then run actual SHAP on all available validation classes, inspect uncertain/insufficient output, neighboring comparable windows and saved localization evaluation. Measured additivity, background provenance and stability remain unverified until that bundle exists. No twin, candidate repair ranking, repair execution or dashboard is implemented here.
