"""Measured stage-3 handover/plots; pending experiments stay null and incomplete."""
import json

from explainnet.application_profiles import ROOT
from explainnet.dataset_export import atomic_json

OUT=ROOT/'artifacts/completion_stage3'


def write_handover(r):
    main=r['dataset_audit']['cohort'] or {};pilot=r['dataset_audit']['pilot'] or {}
    metrics=r.get('held_out_metrics') or {};labs=json.loads((OUT/'labs/report.json').read_text()) if (OUT/'labs/report.json').exists() else {}
    expected=main.get('estimated_remaining_s');eta=f'{expected/3600:.2f} hours from measured completed episodes, plus audit/retry uncertainty' if expected is not None else 'Blocked or not running; no reliable completion ETA until quality/retry reconciliation'
    text=f'''# Completion Prompt 3 — measured status and reproducible handover

Snapshot UTC: **{r['at_utc']}**. State: **{r['status']}**. This is an in-progress report until all declared branches have terminal evidence. Missing experiments/metrics are not complete. Independent Prompt4 interface/documentation work is tracked separately in `COMPLETION_STAGE4.md`; it cannot close pending scientific acceptance.

## Corpus and pilot

Prospective target **3,600 accepted windows /600 independently constructed episodes /60 recipe families**, balanced720 windows/class. Reserved split: **2400 train /600 validation /600 untouched test**,400/100/100 episodes,40/10/10 families. Actual new accepted: **{r['accepted_windows']}/3600**; completed episodes **{r['completed_episodes']}/600**; actual partitions `{r['partitions']}`. Pilot: **{pilot.get('accepted_windows',0)}/10**, `{pilot.get('state','pending')}`, five classes/two windows each, excluded from the corpus. No synthetic/padded/duplicated samples are counted.

Main batch: `{main.get('batch_id','not planned')}`. Actual represented families: **{main.get('represented_families')}**, by partition `{main.get('represented_families_by_partition')}`; declared families60. Mean completed full episode: `{main.get('mean_completed_episode_s')}` seconds. Estimated remaining collection: **{eta}**. The pilot averaged92.39 s with45 s main measurements; the prospective100 s full episodes were initially estimated at about25 hours total before growing audit costs/retries. Current full-episode/cadence measurements supersede that estimate. Window acceptance fraction `{main.get('steady_acceptance_fraction_of_all_windows')}` uses **all captured windows**, including baseline/recovery, transitions and surplus; it is not a quality-only pass rate. Completed-attempt fraction: `{main.get('completed_attempt_fraction')}` (includes currently running attempts in its denominator); failed attempts `{main.get('failed_attempts')}`.

The audited `expansion_v1` template repeats all30 compact recipe signatures and its seeds. The complete historical360-window cohort (240/60/60 plus separate10 pilot) and examined tests remain separate historical evidence. The new prospective cohort uses12 joint families/class (8/2/2),10 independent repetitions/family and fresh seeds. New holdout joint recipes do not overlap the old cohort. The live8Mbps critical/5Mbps bulk UDP1200 domain is explicitly in training. Fixed fault locations remain a limitation.

## Frozen model, heldout and explanations

New model state: **{r['model_metadata']['status']}**. Registered new models: `{r['model_metadata']['new_models']}`. A complete audited corpus is mandatory before fitting. The bounded search uses three160-tree RF configurations, four family-separated folds, training-only preprocessing/healthy IF, validation selection/sigmoid calibration/IF thresholds, confidence0.70/margin0.15 unchanged, and a24-row training-derived SHAP background embedded before immutable publication. New bundles bind five-switch topology identity; larger-domain predictions abstain from qualified support.

New heldout macro-F1: `{metrics.get('window_classification',{}).get('macro_f1')}`; episode count: `{metrics.get('episodes')}`; family count: `{metrics.get('families')}`; calibration: `{metrics.get('calibration')}`; operational coverage: `{metrics.get('abstention',{}).get('coverage_fraction')}`. Null means **not evaluated**, never zero performance. RF argmax metrics, operational abstention, IF sensitivity/false alerts/ROC-AUC/AP, combined detection, class matrices and whole-episode/family uncertainty are separate in the JSON/CSV.

The pipeline freezes model/background/dataset/splits/protocol/evaluator and imported source hashes before opening new test inputs. A post-freeze source change refuses a fresh confirmatory claim; no test-driven tuning is allowed. The historical active model remains `m20261016T074751_a92c0db8f44e` in the separate normal8501/API38223 store and is not substituted for new-cohort acceptance.

SHAP readiness: `{metrics.get('SHAP')}`. Actual backend compatibility checks use measured **training** observations and are not independent accuracy evidence. Test explanations are explicitly frozen offline results; backend test sealing remains. Native cases exercise fresh live trained diagnosis/matching explanations. Additivity is on raw RF probability, separate from calibrated confidence; neighboring-window top3 stability is descriptive and not a user study.

## Baselines, recovery and scale

New native campaign finished: **{labs.get('finished',False)}**; attempted independent sources: **{len(labs.get('cases',[]))}**. Primary comparisons declare three independent5-switch latency sources per impaired-control, independent no-twin and full trained-twin approach, with paired seeds and randomized order. A threshold-only detector is evaluated separately. No-twin computes its proposal before twin results; common shadow qualification time is excluded from intrinsic decision time and separately reported. Original actuation keeps the same trained support, ready explanation, ownership, feasibility, service, freshness, verification and rollback gates; differing/unqualified baseline proposals are refused. Twin-only outcomes are not original repairs.

No-XAI results: `{metrics.get('no_XAI')}`. SHAP is post-hoc and not a candidate selector input. The model/data/policy remain fixed; accuracy/choice changes and user-study benefits are not invented. Actual explanation overhead is measured. Original actuation safeguards are not disabled for this ablation.

Each fault retains two distinct feasible-changing-candidate budget plus C0, two within-source repetitions and at most two retained hypotheses. Fidelity tolerances, ≥0.65 coverage and probe/resource requirements remain unchanged. Saturation/loss/QoS had precise unresolved measurement/fidelity gates in Stage2; dataset collector qualification is an independent branch and does not close repair qualification. This stage records new-model bounded qualifications, preserving every refusal. Historical observed-only successes are not new trained acceptance.

Scale declares5/10/15 switches ×healthy/latency ×three independent sources/condition, sequentially, one live twin maximum. Source construction, all-pair/alternate connectivity, collection quality, CPU/memory, repeated C0, candidate timing and supported outcomes are separate. Five-switch training does not establish larger-topology transfer. Faster refusal is not a scaling improvement. Larger-domain application remains prohibited unless its model domain is qualified.

## Timing and targets

The ≥0.85 macro-F1 target is `{None if not metrics else metrics['window_classification']['macro_f1']>=.85}` on the **new frozen holdout**. The integrated <10 s target is assessed from actual native clocks, not inference alone. Reports distinguish onset→first detection, observation-ready→diagnosis/explanation, SHAP queue/computation, snapshot/reconstruction, trials, eligible recommendation, application, verification and onset→outcome (before intentional Undo/cleanup). Native clocks use the shared WSL monotonic clock; unavailable historical onset clocks remain null. Cold SHAP setup, warmed computation, fresh runtimes, failures/refusals and host load are labeled. Stage2's minute-scale decisions remain historical unmet-target evidence, not new Stage3 timing.

Postcollection native planning range: **1.5–5 hours**, uncertain. This uses preserved Stage2 complete source durations: healthy69.84s; successful latency670.79s; loss182.42s; saturation205.09s; QoS102.00s. Added healthy C0/larger topologies and new-model support can change durations; refusals do not count as faster successful scaling. The12-hour native cap,1-hour training cap and2-hour evaluation cap are safety budgets, not measured Stage3 runtimes.

## Runtime identity, safety and resume

Campaign config: `artifacts/completion_stage3/runtime/config.json`; API **{r['summary']['api_port']}**; authoritative store **{r['summary']['data_store']}**. The root OS-Python owner and unprivileged application/model children remain separate. Both existing dashboard stores/owners are preserved. Automatic repair is disabled; native application uses only explicit Assisted mode when qualified. No global Mininet/OVS cleanup, dependency rebuild or final UI redesign occurs.

Collection is sequential, checkpointed after every episode, maximum two attempts/episode; identical repeated failure stops the branch. The root supervisor is detached: **no foreground terminal must stay open**, but **WSL and the computer must remain awake/running**. A shutdown can interrupt an episode; accepted checkpoints remain. Finite collector/workload expiry is not silently renewed. A48-hour supervisory collection bound is separate from the episode/workflow/action bounds. Avoid concurrent laboratory campaigns on the shared emulator host.

From Windows PowerShell in `/path/to/user\\Desktop\\CN project`:

```powershell
# Read progress; refreshes requested reports, no laboratory mutation.
wsl.exe -d Ubuntu --cd '/path/to/user\\Desktop\\CN project' -- .venv/bin/python scripts/status_completion_stage3.py
# Resume/adopt the same checkpoint; an existing live controller refuses a duplicate.
wsl.exe -d Ubuntu -u root --cd '/path/to/user\\Desktop\\CN project' -- env PYTHONPATH=src /usr/bin/python3 scripts/completion_stage3_pipeline.py run --resume --detach
```

Typed cancellation uses the same config and recorded main batch:

```powershell
wsl.exe -d Ubuntu --cd '/path/to/user\\Desktop\\CN project' -- .venv/bin/python -m explainnet.cli --config artifacts/completion_stage3/runtime/config.json dataset-cancel {main.get('batch_id','BATCH_ID')}
```

Cancellation finishes in-flight mutation and scoped restoration/cleanup; do not delete case files/databases or use `mn -c`. Failed/unknown jobs and unsettled original actions require inspection of the recorded intent/job/root journal before retry. Accepted episodes are skipped on explicit resume. Root checkpoints: `pipeline.json`, `runtime/supervisor.json`; authoritative per-batch manifests/checkpoints/raw files remain in the Linux store. Postcollection training/evaluation/native phases execute only after the preceding gates and preserve phase logs/intents. Final owned laboratory cleanup follows the recorded outcomes; unsafe unresolved ownership is retained and reported.

## Checks, blockers and Prompt4 readiness

Historical preservation checks pass: **{r['summary']['historical_assets_unchanged']}**. Current blockers: `{r['blockers']}`. Software receipts: `{r['software_verification']}`. The initial focused fixture key error is preserved; later passing regressions/final checks supersede it. Software fixtures do not establish packet efficacy and overlapping suites are not added together. No new heldout, baseline, recovery or scale experiment is marked complete while pending. Full result interfaces expose `artifacts/completion_stage3_validation.json` with current counts/status rather than hardcoded outcomes. Scientific readiness for a final Prompt4 verdict: **{r['stage15_readiness']['prompt4']}**. The separately authorized interface/documentation work must preserve these limits.
'''
    (ROOT/'docs/COMPLETION_STAGE3.md').write_text(text)


def create_report():
    from status_completion_stage3 import record
    r=record();write_handover(r)
    plots=OUT/'plots';plots.mkdir(exist_ok=True)
    import plotly.graph_objects as go
    main=r['dataset_audit']['cohort'] or {};counts=main.get('class_counts',{})
    classes=['healthy','saturation','loss','latency','qos']
    fig=go.Figure(go.Bar(x=classes,y=[counts.get(c,0) for c in classes],name='actual accepted windows'))
    fig.add_hline(y=720,line_dash='dash',annotation_text='prospective target per class')
    fig.update_layout(title='New cohort: actual accepted windows (pilot excluded); '+r['at_utc'],yaxis_title='accepted windows')
    fig.write_html(plots/'collection.html',include_plotlyjs=True)
    metrics=r.get('held_out_metrics')
    if metrics:
        matrix=metrics['window_classification']['confusion_matrix']
        go.Figure(go.Heatmap(z=matrix,x=classes,y=classes)).update_layout(title='Frozen new holdout confusion matrix',xaxis_title='predicted',yaxis_title='actual').write_html(plots/'confusion.html',include_plotlyjs=True)
        bins=metrics['calibration']['bins'];valid=[b for b in bins if b['count']]
        go.Figure(go.Scatter(x=[b['mean_confidence'] for b in valid],y=[b['accuracy'] for b in valid],mode='lines+markers',text=[str(b['count'])+' windows' for b in valid])).update_layout(title='New frozen holdout reliability; correlated windows',xaxis_title='mean confidence',yaxis_title='accuracy').write_html(plots/'calibration.html',include_plotlyjs=True)
    labs=json.loads((OUT/'labs/report.json').read_text()) if (OUT/'labs/report.json').exists() else {}
    cases=labs.get('cases',[])
    if cases:
        go.Figure(go.Bar(x=[c['name'] for c in cases],y=[c['timings'].get('eligible_recommendation_ms') for c in cases],
            text=[c['state'] for c in cases])).update_layout(title='Actual eligible recommendation clocks; unavailable/refused values remain null',
                yaxis_title='milliseconds').write_html(plots/'native_timing.html',include_plotlyjs=True)
        go.Figure(go.Bar(x=[c['name'] for c in cases],y=[c['construction_rpc_ms'] for c in cases],
            text=[str(c['switches'])+' switches; '+c['state'] for c in cases])).update_layout(
                title='Actual original construction RPC time; success/transfer separate',yaxis_title='milliseconds').write_html(plots/'construction.html',include_plotlyjs=True)
    atomic_json(OUT/'plots/manifest.json',{'source':'completion_stage3_validation.json','files':[p.name for p in plots.glob('*.html')],
        'missing_metric_plots':'Not generated until actual metric evidence exists'})
    return r


if __name__=='__main__':create_report()
