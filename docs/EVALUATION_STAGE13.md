# ExplainNet Twin — Stage 13 evaluation

Recorded UTC: 2026-10-19T11:16:38.593175+00:00

Status: **complete_with_declared_limits**

## Dataset

360/360 windows; 60/60 episodes. Splits: {'test': 60, 'train': 240, 'validation': 60}.

## Model and held-out diagnosis

Trusted bundles: 1. Real backend SHAP ready cases: 5/5.

Test: 60 windows from 10 episodes. Macro F1 1.0000; accuracy 1.0000; coverage 0.9667.

Brier (five-class sum convention): 0.0215; log loss 0.1083. Episode bootstrap: {'estimated': True, 'limitation': 'Only two held-out episodes per class, sharing one family; interval does not represent broad network/fault diversity.', 'macro_f1_95_percentile_interval': [1.0, 1.0], 'repetitions': 500, 'seed': 20261016, 'unit': 'whole episodes; stratified by class'}.

Online detection delay was not measured by historical replay. See separately labeled window replay times and source availability.

## Recovery, baselines and scale

Current packet trials and their failures/rejections are checkpointed in `artifacts/stage13/labs/`. Matched twin baselines and original applied outcomes are separate in the JSON/CSV report.

Independent primary attempts by outcome: `{"fixed_rule_with_safety_qualification": {"succeeded": 3}, "no_change": {"retained_impaired": 3}, "twin_guided": {"refused": 1, "succeeded": 2}}`. All attempted sources count, including those without usable metrics. Within-snapshot trials are not independent repetitions.

### Original-network comparison

| Approach | Attempts | Sources with post data | Mean RTT (ms) | Mean critical (Mbps) | Outcomes |
| --- | ---: | ---: | ---: | ---: | --- |
| fixed_rule_with_safety_qualification | 3 | 3 sources | 4.249 | 8.000 | {'succeeded': 3} |
| no_change | 3 | 3 sources | 66.314 | 8.000 | {'retained_impaired': 3} |
| twin_guided | 3 | 2 sources | 4.239 | 8.000 | {'refused': 1, 'succeeded': 2} |

### Actual scale trials

| Switches | Healthy RTT (ms) | Fault RTT (ms) | Original outcome |
| ---: | ---: | ---: | --- |
| 5 | 6.258855311355312 | 66.27575757575758 | refused |
| 10 | 6.237575757575758 | 66.2074074074074 | refused |
| 15 | 6.2439583333333335 | 66.26190476190476 | refused |

### Other-fault qualification

- {"bulk_protocol": "udp", "critical_protocol": "udp", "fault": "loss", "original_application_attempted": false, "qualification_details": ["no-change fidelity failed: fail"], "reasons": ["twin recommendation not eligible: insufficient-evidence"], "source_episode": "s13_loss_e5eccfdb", "state": "refused", "switches": 5, "trial_refusals": [["no-change fidelity failed: fail"]], "twin_state": "insufficient-evidence", "workflow_error": null}

- {"bulk_protocol": "udp", "critical_protocol": "udp", "fault": "saturation", "original_application_attempted": false, "qualification_details": ["suitable measured window unavailable"], "reasons": ["twin recommendation not eligible: unsupported"], "source_episode": "s13_saturation_7c283589", "state": "refused", "switches": 5, "trial_refusals": [], "twin_state": "unsupported", "workflow_error": null}

- {"bulk_protocol": "udp", "critical_protocol": "udp", "fault": "qos", "original_application_attempted": false, "qualification_details": [], "reasons": null, "source_episode": "s13_qos_528c4269", "state": "refused", "switches": 5, "trial_refusals": [], "twin_state": null, "workflow_error": "insufficient fresh incident evidence: ['missing required metric: rtt_mean_ms']"}

- {"bulk_protocol": "tcp", "critical_protocol": "udp", "fault": "latency", "original_application_attempted": false, "qualification_details": ["no-change fidelity failed: fail"], "reasons": ["twin recommendation not eligible: insufficient-evidence"], "source_episode": "s13_latency_tcp_1db800be", "state": "refused", "switches": 5, "trial_refusals": [["no-change fidelity failed: fail"]], "twin_state": "insufficient-evidence", "workflow_error": null}

### Trained-model recovery path

{"application_gate_passed": null, "confidence": 0.9405051923395705, "diagnosis_reasons": ["fault classifier lacks corroborating anomaly or service evidence"], "diagnosis_status": "uncertain", "explanation_status": "pending", "freshness": "fresh", "margin": 0.92267572502634, "measurement_source": "Current real five-switch UDP latency case; separate from observed-only primary trials", "mode": "trained-model", "model_id": "m20261016T074751_a92c0db8f44e", "original_application_state": null, "probability_status": "calibrated", "reasons": ["twin recommendation not eligible: no-safe-repair"], "source_episode": "s13_trained_30b1587a", "state": "refused", "twin_reasons": [], "twin_state": "no-safe-repair", "workflow_error": null}

Primary comparisons above use explicit observed-only opt-in. They are not evidence of trained AI repair. Healthy controls: `{"primary_0": true, "scale_10": true, "scale_15": true}`.

## Blockers

## Reproduction

```bash
.venv/bin/python scripts/status_stage13.py
.venv/bin/python scripts/stage13_provenance.py
.venv/bin/python scripts/evaluate_stage13.py score
.venv/bin/python scripts/status_stage13_lab.py
sudo env PYTHONPATH=src /usr/bin/python3 scripts/stage13_lab_supervisor.py --resume 492fca67 --detach
.venv/bin/python scripts/evaluate_stage13.py report
```

The score command verifies the saved freeze and dependency receipt, then reuses the original test metrics without rescoring. Resume skips finished cases. A fresh full campaign omits `--resume`; it retains the same declared protocol/order and writes a new campaign directory. Never run native campaigns concurrently.

## Limits

- Five-switch emulation training; correlated windows and few episode families.

- Original freeze did not bind all imported modules/settings; a dated post hoc receipt now guards reuse without retroactive pre-test claims or rescoring.

- Replay evidence availability includes backfill and is not historical online detection latency.

- Observed-only opt-in and trained-model gates remain separate.

- Recovery and scale uncertainty intervals are not estimated: three primary sources per approach and one source per additional topology. Within-snapshot repeats are not independent source episodes.

- Twin-only baseline results are not original-network repair results.

- Fixed rule may choose the same action as twin ranking; no superiority claim follows from coincident actions.

Stopped after Stage 13; Stages 14 and 15 remain pending.
