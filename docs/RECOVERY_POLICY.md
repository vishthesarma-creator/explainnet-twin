# Recovery policy — Stage 10

## Scope and eligibility

Completion stage 2 supersedes runtime defaults with `recovery_v2` (`config/recovery_policy_v2.json`) and the shared `critical_service_v2`. Old v1 declarations/evidence remain preserved. RTT scoring now consistently uses p95, and monitoring/model corroboration resolve the same inherited 20 ms critical class. Action families, cost, meaningful margin, repeat consistency, protected-flow and capacity gates are unchanged. The default workflow measures two distinct feasible configuration changes plus a separate no-change control, two repetitions per retained hypothesis, with 15-second matched captures. Candidate generation is not measurement evidence. All controls must pass; a failed control stops that experiment and is never omitted. Actual measured coverage and precise refusals are in `COMPLETION_STAGE2.md` and its JSON report.

`recovery_v1` is a declared laboratory service/action policy, stored in `config/recovery_policy_v1.json` and enforced by `recovery_spec.py` on both sides of the privilege boundary. Its content hash is persisted with plans, root applications, experiments and recommendations. A change requires a new version and matching root implementation. No original-network execution operation is implemented here.

Stage 9 established limited healthy and added-delay fidelity. Each new Stage 10 experiment must independently pass the unchanged, pilot-frozen fidelity policy for every matched no-change control. Saturation, loss, QoS, missing receiver, resource contamination and unsupported reconstructions cannot inherit eligibility from a different condition. Null measurements remain null. Existing dataset/model/SHAP gates remain incomplete; absent incident, diagnosis or model lineage is recorded explicitly. These independent observed-topology experiments do not claim a working production classifier or SHAP causality.

## Permitted actions

| Family | Exact bounded change | Preconditions |
|---|---|---|
| No change | Empty diff | Required fresh-runtime control in every repetition/hypothesis block. |
| Affected-flow reroute | Change the declared `critical` pair to a different approved simple path. | Same logical endpoints, real links, current path matches snapshot, no new physical overload. |
| Broader reroute | Change `critical` and `bulk` together to approved alternatives. | Same checks for both; at most two logical pairs. |
| Selected-background shaping | Limit `h5→h6` at its owned source access HTB class to 80 Mbps. | Observable offered demand above 80 Mbps, supported existing access hierarchy, unchanged client demand and switch impairment. |
| Approved QoS restoration | On logical `s3→s5`, critical `h1→h3` class rate/ceiling 3/4 Mbps; bulk rate/ceiling 16/20 Mbps. | Existing supported flow mapping/child classes, 20 Mbps physical parent; guarantees sum to 19 Mbps. Restore class service only; retain netem leaves. |

The library also permits a bulk-only reroute as a bounded plausibility/ineffectiveness comparison. Shape/QoS candidates are rejected when absent or already satisfied. Candidate generation records exact logical changes, snapshot/path preconditions, cost/disruption, diagnosis/localization evidence and rejection reasons. Duplicates, equivalent paths, no-ops, loops, missing links, forbidden endpoints, unsupported operations and new overloaded paths are rejected. Two meaningful bypass alternatives are available for the demonstrated latency topology. Fewer feasible repairs remain explicit.

The permitted pair identities refer specifically to `critical=h1→h3` and `bulk=h2→h4`; aliases cannot authorize different endpoints. Source-access shaping is refused if `h5` has another observed destination, because this implementation cannot selectively shape that mixed source workload.

Root execution first verifies the twin registry, distinct source ID, actual owner role, snapshot hash, bridge/interface ownership and unchanged starting plane. Every action records pre/post twin netem parameters and physical parent rates. They must be identical. Offered workload must also remain identical. Forwarding can bypass an impairment; it cannot remove it. No scenario stop/reset, injector journal read, loss/delay clearing, bandwidth creation or healthy workload replacement is a repair.

Native `tc` preservation evidence retains its original JSON units: netem delay options are seconds and class `rate`/`ceil` are bytes/second. These raw fields are not objective inputs. Policy changes, topology capacities and measured objective rates use bits/second; RTT/jitter metrics use milliseconds.

## Experiment protocol

- Sequential execution with one live twin. Default: at most three repairs plus no-change, two fresh-runtime repetitions, two hypotheses, ten-second observation windows and a recorded shuffle seed. Bounds: three repetitions, two hypotheses, twenty-second windows and 700-second job timeout. Controls anchor each block; only repair order is shuffled.
- Before **every** control and candidate, rebuild the same immutable snapshot/hypothesis, including fresh traffic and three-second warmup. Each reset has a new owner token. After application allow one additional settling second. Do not apply actions cumulatively.
- Capture original and twin independently within a matched monotonic window. Preserve native JSONL, receiver intervals, window IDs, packet/probe counts, resource observations, applications, failures and source configuration digests. Use the existing Stage 5 aggregation; no output fitting or changed metric definitions.
- Every control must pass all frozen fidelity metrics, including protected delivery, queues/classes, RTT/loss/jitter, resource limits and sampling coverage. Any failed control terminates the job as insufficient evidence. Candidate windows require complete inference-ready telemetry, receiver coverage ≥0.65, at least six transmitted probes and VM CPU/memory usage ≤0.85.
- The requested snapshot lifetime is finite and immutable. Stage 9's 180-second default remains; Stage 10 extends the explicit request ceiling from 300 to **900 seconds** for bounded repeated trials. The job reserves `trials × (window_seconds + 20) + 30` seconds before construction and refuses requests that cannot fit the remaining lifetime or timeout. It never renews expiry. Actual age, source owner token, forwarding/topology/class-policy/workload fingerprints, configuration versions, agent epoch and opaque original observation digest are rechecked during the job and before publication/retrieval.
- The verification setup uses the separate `recovery_observation_v1` configuration to run the same permitted train fault/demand parameters for up to 900 seconds. Ordinary traffic/dataset recipe bounds remain unchanged. Each twin workload remains bounded to 100 seconds and is restarted through reset before every trial. The original scenario continues throughout each case.
- No automatic retries. A failed candidate is recorded and its snapshot reconstructed before proceeding. Cancellation interrupts capture/construction and destroys only the owned twin. Final teardown also destroys only that twin. Startup marks interrupted recovery work failed and uses the existing twin reconciliation cleanup. No partial result supports success.

## Objective and constraints

The independent recovery service declaration is: critical mean RTT ≤20 ms, ping/UDP loss ≤0.02, UDP jitter ≤5 ms, delivered critical demand ≥90% of the observed offered rate. This recovery declaration is separate from the unchanged Stage 9 fidelity reference objective (100 ms). It is fixed before Stage 10 comparisons; fidelity tolerances are not loosened.

For each measured window:

```
rtt_violation    = max(0, mean_rtt_ms / 20 - 1)
loss_violation   = max(0, max(ping_loss, udp_loss) / 0.02 - 1)
jitter_violation = max(0, udp_jitter_ms / 5 - 1)
demand_violation = max(0, 1 - delivered_bps / (0.9 * offered_bps))
health_penalty   = rtt_violation + loss_violation
                 + 0.25*jitter_violation + demand_violation
score           = health_penalty(matched_no_change)
                 - health_penalty(action) - action_cost - uncertainty
```

All components are dimensionless. Loss is a fraction; rates are bits/second; delay/jitter are milliseconds. TCP critical traffic has no UDP jitter component. Safe denominator floors protect arithmetic; missing required metrics prevent scoring. Goodput uses declared delivered demand, never an invented maximum.

Costs: 0 for control; 0.02 per changed forwarding pair; 0.08 for shaping; 0.04 for QoS restoration. The initial uncertainty cost is 0.02 for repairs. The descriptive repeat uncertainty penalty is half the observed score range across repeats and tested hypotheses. Report minimum/mean/maximum, range and counts; no confidence intervals are calculated from these small correlated packet samples.

Before selection, every repair window must satisfy the critical requirements and protected traffic must lose no more than 15% delivered rate or 0.03 additional UDP loss relative to its matched control. Physical/routing/policy/fidelity/quality/freshness gates also apply. Every requested repetition/hypothesis must be present. A repair qualifies only if its minimum repeat score minus the repeat uncertainty penalty exceeds **0.05**. No-change compares against itself: zero improvement, cost, uncertainty and score. It remains the correct choice when repairs do not meet the gates.

Candidates within 0.03 of the best conservative score are practically tied; choose lower disruption cost, then fewer changes, then stable candidate ID. Untested plausible directions or omitted hypotheses prevent a robust recommendation: qualifying benefit is provisional and status is uncertain. Both tested delay directions may support a conditional recommendation when the background probes constrain the candidate set to exactly those two. Fidelity verifies observational similarity, not unique fault causation.

## Durable results and commands

Migration 9 adds `recovery_experiments`; existing `candidates`, snapshots, telemetry, jobs and audit storage are reused. Each record includes request/hash, lineage (including absent-model reasons), policy versions, hypotheses, randomized order, trials, failures, rejected candidates, score components, original logical diff, preconditions and expiry. Runtime owner tokens remain trial evidence and never enter the original logical diff. Retrieval rechecks current original freshness; historical eligibility cannot become an executable current recommendation after expiry or original teardown.

```bash
# Run in the documented Ubuntu project directory; launch the existing agent/API first.
.venv/bin/python -m explainnet.cli --config CONFIG recovery-plan REQUEST.json
.venv/bin/python -m explainnet.cli --config CONFIG recovery-test REQUEST.json
.venv/bin/python -m explainnet.cli --config CONFIG job JOB_ID
.venv/bin/python -m explainnet.cli --config CONFIG recovery-get OPERATION_ID
.venv/bin/python -m explainnet.cli --config CONFIG recovery-cancel OPERATION_ID

# Bounded native verification, root supervisor and unprivileged application/driver.
sudo env PYTHONPATH=src python3 scripts/check_candidate_stage10.py latency
```

`REQUEST.json` contains `twin_id`, `snapshot_id`, `operation_id`, `max_repairs`, `repetitions`, `max_hypotheses`, `duration_s`, `seed`, `timeout_s`; unknown original target fields are rejected. API routes: POST `/v1/recovery/plan`, `/test`, `/cancel`; GET `/v1/recovery/{operation_id}`. Test/plan submissions use existing asynchronous jobs. Duplicate operation IDs return persisted trials without re-execution; changed inputs under the same ID are rejected. Cancellation bypasses the sequential worker.

## Limitations

Measured coverage and all earlier attempts are in `artifacts/candidate_validation_report.json` and `artifacts/stage10/`. Packet timing, TCP dynamics and netem random outcomes are not exactly reproducible from an order seed. VM resource checks cannot observe all outer Windows scheduling pressure. Snapshot reconstruction is effective observational inference, not full state cloning. Model/incident/SHAP lineage remains unavailable where no production records exist. Finite-lived results require new current evidence for later use. Original repair efficacy, rollback and automation are Stage 11 work; nothing here establishes real-world recovery effectiveness.

## Actual Stage 10 verification

Completed on 2026-10-10 (client local date); stored timestamps are UTC. Main measured evidence is in `artifacts/stage10/09b0ae1d/`, controls in `7b0bb2dd/`, earlier failed planning and TCP-control attempts in `6c7d1d90/` and `e4434d57/`. The final report retains every attempt. Main runs used permitted train recipes with the documented finite observation override; sealed test measurements were never accessed.

| Condition | Actual result |
|---|---|
| UDP latency, train `main_latency_f2_r0` | 16 trials: no-change plus critical, broader and bulk-only reroutes; two repetitions for each of two plausible shared-link directions. All four controls passed. Critical and broader bypasses qualified. |
| Nominal correct QoS | Six trials, two passing controls. Service requirements already met; repair scores −0.04, no-change score 0. Result: no safe repair needed. Broader rerouting was rejected for new offered overload of the 30 Mbps alternative. |
| Saturation | First control refused: RTT residual 28.96 ms exceeded 22.76 ms tolerance; ping-loss residual 0.16667 exceeded 0.03. No repairs tested. |
| Loss | First control refused: ping-loss residual 0.05556 exceeded 0.03. No repairs tested. |
| QoS fault | Control insufficient: required RTT statistics null and twin probe/window evidence insufficient. No repairs tested. |
| Earlier TCP latency | Three candidate measurements followed by a refused second control: RTT and queue-backlog residuals exceeded frozen tolerances. No recommendation. |

UDP latency mean RTT across four observations per candidate:

| Candidate | Mean RTT (ms) | Range of window means (ms) | Conservative score |
|---|---:|---:|---:|
| No change | 66.6533 | 66.5444–66.8400 | 0 |
| Critical pair only | 4.3146 | 4.2622–4.4373 | 2.27983 |
| Critical and bulk | 4.3086 | 4.2800–4.3417 | 2.25983 |
| Bulk only | 66.6342 | 66.6000–66.6667 | −0.05250; critical SLO fails |

Critical delivery remained approximately 8 Mbps. The two qualifying bypass scores differ by 0.02, within the 0.03 practical tie; critical-only wins on lower cost and fewer changes. The preserved diff is `critical: primary → alternative`, corresponding to logical path `[s1,s4,s5]`. No twin interface names are in it. These results apply only to fresh snapshots that reproduce the tested workload/conditions and pass every current gate.

All five main cases retained the original fingerprint, runtime token, offered workload, observation digest and running traffic across testing and twin teardown. Every captured trial retained the twin's impairment and physical parent configuration; every trial reset used a distinct runtime token. The explicit adversarial drift check added 1 Mbps background demand to its separate source to verify refusal; it is recorded as a deliberate external stimulus, not as original preservation or a repair.

Actual cancellation acknowledged in 73.87 ms, produced a canceled job and retained a running, unchanged source. Root execution rejected an original ID and rejected a second action without reset. A ten-second snapshot was stale after expiry; external demand drift produced stale plans/refusals without trials. All four native supervisors removed only their owned bridges and left the initial empty bridge set unchanged.

VM maximum mean CPU busy fraction was 0.3656 and memory-used fraction 0.1015, below 0.85; outer Windows pressure is not measured. Main job submissions took 99.27–515.44 ms. UDP latency job duration was 564.88 s within its predeclared 700 s timeout and immutable 900 s snapshot lifetime. The regression suite passed **144 tests in 159.37 s**, and the final recovery/twin check passed **36 tests in 8.14 s**; Ruff, dependency checks, installed CLI retrieval/help, API version 0.10.0 and stdlib-only privileged-module imports passed. Canonical migration 8→9 preserved all prior counts, dataset states and membership digest (192 train, 10 pilot, no test members), with no models or original actions added.

Actual bounded verification commands, from the documented Ubuntu project directory:

```bash
sudo env PYTHONPATH=src python3 scripts/check_candidate_stage10.py latency
sudo env PYTHONPATH=src python3 scripts/check_candidate_stage10.py latency_udp healthy saturation loss qos
sudo env PYTHONPATH=src python3 scripts/check_candidate_stage10.py controls
.venv/bin/python -m pytest -q
```

Recorded request examples are `artifacts/stage10/09b0ae1d/latency_udp_plan_request.json` and `latency_udp_test_request.json`; successful CLI output is `cli_recommendation.json`. Their snapshots are now historical because verification sources were cleaned up. Create a new current snapshot and request IDs for future experiments; idempotent reuse retrieves previous evidence without rerunning it. Limited Stage 11 original-verification implementation may begin for the demonstrated condition. Full production recovery and the unqualified fault conditions remain blocked.
