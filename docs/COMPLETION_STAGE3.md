> Public copy: personal paths and student registration numbers are anonymized. This dated guide may reference excluded local evidence; use README.md for portable current startup.

# Completion Prompt 3 — measured status and reproducible handover

Snapshot UTC: **2026-10-28T16:20:15.425249+00:00**. State: **blocked**. This is an in-progress report until all declared branches have terminal evidence. Missing experiments/metrics are not complete. Independent Prompt4 interface/documentation work is tracked separately in `COMPLETION_STAGE4.md`; it cannot close pending scientific acceptance.

## Corpus and pilot

Prospective target **3,600 accepted windows /600 independently constructed episodes /60 recipe families**, balanced720 windows/class. Reserved split: **2400 train /600 validation /600 untouched test**,400/100/100 episodes,40/10/10 families. Actual new accepted: **402/3600**; completed episodes **67/600**; actual partitions `{'test': 78, 'train': 258, 'validation': 66}`. Pilot: **10/10**, `completed`, five classes/two windows each, excluded from the corpus. No synthetic/padded/duplicated samples are counted.

Main batch: `dbf62937922dc4648be0771de44855170`. Actual represented families: **42**, by partition `{'test': 8, 'train': 26, 'validation': 8}`; declared families60. Mean completed full episode: `145.2909536924773` seconds. Estimated remaining collection: **Blocked or not running; no reliable completion ETA until quality/retry reconciliation**. The pilot averaged92.39 s with45 s main measurements; the prospective100 s full episodes were initially estimated at about25 hours total before growing audit costs/retries. Current full-episode/cadence measurements supersede that estimate. Window acceptance fraction `0.39762611275964393` uses **all captured windows**, including baseline/recovery, transitions and surplus; it is not a quality-only pass rate. Completed-attempt fraction: `0.9571428571428572` (includes currently running attempts in its denominator); failed attempts `3`.

The audited `expansion_v1` template repeats all30 compact recipe signatures and its seeds. The complete historical360-window cohort (240/60/60 plus separate10 pilot) and examined tests remain separate historical evidence. The new prospective cohort uses12 joint families/class (8/2/2),10 independent repetitions/family and fresh seeds. New holdout joint recipes do not overlap the old cohort. The live8Mbps critical/5Mbps bulk UDP1200 domain is explicitly in training. Fixed fault locations remain a limitation.

## Frozen model, heldout and explanations

New model state: **pending complete audited corpus**. Registered new models: `[]`. A complete audited corpus is mandatory before fitting. The bounded search uses three160-tree RF configurations, four family-separated folds, training-only preprocessing/healthy IF, validation selection/sigmoid calibration/IF thresholds, confidence0.70/margin0.15 unchanged, and a24-row training-derived SHAP background embedded before immutable publication. New bundles bind five-switch topology identity; larger-domain predictions abstain from qualified support.

New heldout macro-F1: `None`; episode count: `None`; family count: `None`; calibration: `None`; operational coverage: `None`. Null means **not evaluated**, never zero performance. RF argmax metrics, operational abstention, IF sensitivity/false alerts/ROC-AUC/AP, combined detection, class matrices and whole-episode/family uncertainty are separate in the JSON/CSV.

The pipeline freezes model/background/dataset/splits/protocol/evaluator and imported source hashes before opening new test inputs. A post-freeze source change refuses a fresh confirmatory claim; no test-driven tuning is allowed. The historical active model remains `m20261016T074751_a92c0db8f44e` in the separate normal8501/API38223 store and is not substituted for new-cohort acceptance.

SHAP readiness: `None`. Actual backend compatibility checks use measured **training** observations and are not independent accuracy evidence. Test explanations are explicitly frozen offline results; backend test sealing remains. Native cases exercise fresh live trained diagnosis/matching explanations. Additivity is on raw RF probability, separate from calibrated confidence; neighboring-window top3 stability is descriptive and not a user study.

## Baselines, recovery and scale

New native campaign finished: **False**; attempted independent sources: **0**. Primary comparisons declare three independent5-switch latency sources per impaired-control, independent no-twin and full trained-twin approach, with paired seeds and randomized order. A threshold-only detector is evaluated separately. No-twin computes its proposal before twin results; common shadow qualification time is excluded from intrinsic decision time and separately reported. Original actuation keeps the same trained support, ready explanation, ownership, feasibility, service, freshness, verification and rollback gates; differing/unqualified baseline proposals are refused. Twin-only outcomes are not original repairs.

No-XAI results: `None`. SHAP is post-hoc and not a candidate selector input. The model/data/policy remain fixed; accuracy/choice changes and user-study benefits are not invented. Actual explanation overhead is measured. Original actuation safeguards are not disabled for this ablation.

Each fault retains two distinct feasible-changing-candidate budget plus C0, two within-source repetitions and at most two retained hypotheses. Fidelity tolerances, ≥0.65 coverage and probe/resource requirements remain unchanged. Saturation/loss/QoS had precise unresolved measurement/fidelity gates in Stage2; dataset collector qualification is an independent branch and does not close repair qualification. This stage records new-model bounded qualifications, preserving every refusal. Historical observed-only successes are not new trained acceptance.

Scale declares5/10/15 switches ×healthy/latency ×three independent sources/condition, sequentially, one live twin maximum. Source construction, all-pair/alternate connectivity, collection quality, CPU/memory, repeated C0, candidate timing and supported outcomes are separate. Five-switch training does not establish larger-topology transfer. Faster refusal is not a scaling improvement. Larger-domain application remains prohibited unless its model domain is qualified.

## Timing and targets

The ≥0.85 macro-F1 target is `None` on the **new frozen holdout**. The integrated <10 s target is assessed from actual native clocks, not inference alone. Reports distinguish onset→first detection, observation-ready→diagnosis/explanation, SHAP queue/computation, snapshot/reconstruction, trials, eligible recommendation, application, verification and onset→outcome (before intentional Undo/cleanup). Native clocks use the shared WSL monotonic clock; unavailable historical onset clocks remain null. Cold SHAP setup, warmed computation, fresh runtimes, failures/refusals and host load are labeled. Stage2's minute-scale decisions remain historical unmet-target evidence, not new Stage3 timing.

Postcollection native planning range: **1.5–5 hours**, uncertain. This uses preserved Stage2 complete source durations: healthy69.84s; successful latency670.79s; loss182.42s; saturation205.09s; QoS102.00s. Added healthy C0/larger topologies and new-model support can change durations; refusals do not count as faster successful scaling. The12-hour native cap,1-hour training cap and2-hour evaluation cap are safety budgets, not measured Stage3 runtimes.

## Runtime identity, safety and resume

Campaign config: `artifacts/completion_stage3/runtime/config.json`; API **36759**; authoritative store **/home/USER/.local/share/explainnet/completion3_v1/data**. The root OS-Python owner and unprivileged application/model children remain separate. Both existing dashboard stores/owners are preserved. Automatic repair is disabled; native application uses only explicit Assisted mode when qualified. No global Mininet/OVS cleanup, dependency rebuild or final UI redesign occurs.

Collection is sequential, checkpointed after every episode, maximum two attempts/episode; identical repeated failure stops the branch. The root supervisor is detached: **no foreground terminal must stay open**, but **WSL and the computer must remain awake/running**. A shutdown can interrupt an episode; accepted checkpoints remain. Finite collector/workload expiry is not silently renewed. A48-hour supervisory collection bound is separate from the episode/workflow/action bounds. Avoid concurrent laboratory campaigns on the shared emulator host.

From Windows PowerShell in `/path/to/user\Desktop\CN project`:

```powershell
# Read progress; refreshes requested reports, no laboratory mutation.
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python scripts/status_completion_stage3.py
# Resume/adopt the same checkpoint; an existing live controller refuses a duplicate.
wsl.exe -d Ubuntu -u root --cd '/path/to/user\Desktop\CN project' -- env PYTHONPATH=src /usr/bin/python3 scripts/completion_stage3_pipeline.py run --resume --detach
```

Typed cancellation uses the same config and recorded main batch:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\Desktop\CN project' -- .venv/bin/python -m explainnet.cli --config artifacts/completion_stage3/runtime/config.json dataset-cancel dbf62937922dc4648be0771de44855170
```

Cancellation finishes in-flight mutation and scoped restoration/cleanup; do not delete case files/databases or use `mn -c`. Failed/unknown jobs and unsettled original actions require inspection of the recorded intent/job/root journal before retry. Accepted episodes are skipped on explicit resume. Root checkpoints: `pipeline.json`, `runtime/supervisor.json`; authoritative per-batch manifests/checkpoints/raw files remain in the Linux store. Postcollection training/evaluation/native phases execute only after the preceding gates and preserve phase logs/intents. Final owned laboratory cleanup follows the recorded outcomes; unsafe unresolved ownership is retained and reported.

## Checks, blockers and Prompt4 readiness

Historical preservation checks pass: **True**. Current blockers: `['Representative corpus incomplete or final dataset audit not ready; training/final-test gate stays closed.', 'Collection stopped at c3m_latency_f11_r06: steady window shortfall: 1/6. Preserve failed attempts and maximum retry budget.', 'New frozen heldout metrics, calibration, IF ranking and SHAP/no-XAI results are pending.', 'Declared native baseline/fault/scale comparisons are not all terminal; pending work is not complete.']`. Software receipts: `[{'artifact': 'bundle_and_evaluator_final.xml', 'tests': 41, 'failures': 0, 'errors': 0, 'elapsed_s': 31.215, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': True}, {'artifact': 'evaluator_fixture.xml', 'tests': 1, 'failures': 0, 'errors': 0, 'elapsed_s': 21.285, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': False}, {'artifact': 'final_binding_checks.xml', 'tests': 5, 'failures': 0, 'errors': 0, 'elapsed_s': 21.724, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': True}, {'artifact': 'final_report_checks.xml', 'tests': 1, 'failures': 0, 'errors': 0, 'elapsed_s': 17.491, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': True}, {'artifact': 'final_software.xml', 'tests': 94, 'failures': 0, 'errors': 0, 'elapsed_s': 180.323, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': True}, {'artifact': 'focused.xml', 'tests': 15, 'failures': 1, 'errors': 0, 'elapsed_s': 56.797, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': False}, {'artifact': 'prerequisites.xml', 'tests': 66, 'failures': 0, 'errors': 0, 'elapsed_s': 41.826, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': False}, {'artifact': 'regressions.xml', 'tests': 240, 'failures': 0, 'errors': 0, 'elapsed_s': 211.675, 'evidence_type': 'software fixtures, not packet efficacy', 'authoritative_final': False}]`. The initial focused fixture key error is preserved; later passing regressions/final checks supersede it. Software fixtures do not establish packet efficacy and overlapping suites are not added together. No new heldout, baseline, recovery or scale experiment is marked complete while pending. Full result interfaces expose `artifacts/completion_stage3_validation.json` with current counts/status rather than hardcoded outcomes. Scientific readiness for a final Prompt4 verdict: **False**. The separately authorized interface/documentation work must preserve these limits.
