# Shared service requirements — completion stage 2

The executable contract is `src/explainnet/service_requirements.py`, version `critical_service_v2`; `config/service_requirements_v2.json` is its reviewable declaration. It inherits the **existing** `recovery_v1` critical class: RTT p95 ≤20 ms, probe/UDP loss ≤0.02, UDP jitter ≤5 ms and delivered critical demand ≥0.90. The application objective may tighten these bounds. Its historical 100 ms generic objective cannot relax this declared class. These limits were not derived from an injected delay or a selected outcome.

Monitoring, model corroboration, recovery health/ranking and original post-action verification call the same resolver/evaluator. Delivered rate uses observed declared critical demand and the configured minimum where applicable; the monitor's low-demand floor remains 100,000 bps. An optional qualified reference may tighten monitoring with its predeclared 15 ms RTT margin. Missing measurements remain null and are reported as missing. UDP requirements apply to UDP service. Rates are bits/s, RTT/jitter milliseconds, loss/utilization fractions.

| Independent decision | Policy |
|---|---|
| IF anomaly | Frozen negative `score_samples` ≥0.6224401399531727; not a probability |
| RF support | Calibrated confidence ≥0.70, top-two margin ≥0.15, compatible schema/domain and corroborating evidence |
| Service violation | Shared service contract, independent of predicted class or injector state |
| Twin fidelity | Unchanged `fidelity_v1`, nominal pilots, per-metric residuals, ≥0.65 coverage and ≥6 transmitted probes |
| Required repair benefit | `recovery_v2`: every matched repeat passes constraints and conservative score >0.05 |
| Protected traffic | At most 15% throughput degradation and 0.03 added UDP loss; physical capacity cannot increase |

The model binary, validation report, manifest, IF threshold, calibration and SHAP training background remain immutable. This runtime correction does not rescore frozen results or establish full-corpus model qualification. See `COMPLETION_STAGE2.md` and its validation JSON for fresh observations and refusals.
