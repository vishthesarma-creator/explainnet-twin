"""Assemble actual integration/handover evidence; never train or score test observations."""
import argparse
import hashlib
import json
from pathlib import Path

from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/stage14'


def read(path,default=None):
    return json.loads(path.read_text()) if path.exists() else (default if default is not None else {})


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def mean(values):
    return sum(values)/len(values) if values and all(v is not None for v in values) else None


def rehearsal_summary(folder):
    raw=read(folder/'report.json')
    supervisor=read(folder/'supervisor.json')
    w=raw.get('workflow') or {}; action=raw.get('action_before_undo') or {}
    exp=w.get('candidate_result') or {}
    pre=action.get('pre_window') or raw.get('impaired_window') or {}
    post=[p['window'] for p in action.get('post_windows',[])]
    def feature(window,key): return window.get('features',{}).get(key)
    def bulk(window): return window.get('per_flow',{}).get('h2->h4:udp',{}).get('delivered_bps')
    return {'tag':folder.name,'status':raw.get('status','not_started'),'mode':raw.get('mode'),
        'measurement_source':raw.get('measurement_source'),'started_utc':raw.get('started_utc'),'ended_utc':raw.get('ended_utc'),
        'source_id':raw.get('instance_id'),'workflow_id':w.get('workflow_id'),'incident_id':w.get('incident_id'),
        'snapshot_id':w.get('snapshot_id'),'twin_id':exp.get('twin_id'),'action_id':action.get('action_id'),
        'original_repair_state_before_undo':action.get('state'),'final_workflow_state':(raw.get('undo') or {}).get('state',w.get('state')),
        'healthy_no_unnecessary_repair':raw.get('healthy_no_unnecessary_repair'),
        'healthy_window_count':len(raw.get('healthy_windows',[])),'post_window_count':len(post),
        'before_rtt_ms':feature(pre,'rtt_mean_ms'),'before_critical_bps':feature(pre,'critical_goodput_bps'),
        'after_rtt_ms':mean([feature(p,'rtt_mean_ms') for p in post]),
        'after_critical_bps':mean([feature(p,'critical_goodput_bps') for p in post]),
        'after_bulk_bps':mean([bulk(p) for p in post]),'after_loss_fraction':mean([feature(p,'udp_loss_fraction') for p in post]),
        'predicted_rtt_ms':mean([v for p in action.get('post_windows',[]) for v in p.get('predicted_rtt_mean_ms',[])]),
        'restored_rtt_ms':feature(raw.get('restored_window') or {},'rtt_mean_ms'),
        'application_ms':action.get('application',{}).get('application_elapsed_ms'),'verification_ms':action.get('verification_ms'),
        'workflow_ms':w.get('elapsed_ms'),'total_rehearsal_ms':raw.get('total_elapsed_ms'),
        'twin_evaluation_ms':exp.get('elapsed_ms'),'stop_response_ms':raw.get('stop_response_ms'),
        'health_response_ms':raw.get('health_latency_ms'),'collector_continued_during_twin':raw.get('collector_continued_during_twin'),
        'transient_disruption':action.get('transient_disruption'),
        'refusal_reasons':w.get('reasons',[]),'workflow_error':w.get('error'),'twin_reasons':exp.get('reasons',[]),
        'errors':raw.get('errors',[]),'driver_exit_code':supervisor.get('driver_exit_code'),
        'owned_cleanup':supervisor.get('owned_bridges_removed'),'unrelated_bridges_preserved':supervisor.get('preexisting_bridges_preserved'),
        'socket_removed':supervisor.get('socket_removed'),'final_control':raw.get('final_control'),
        'source_report':str((folder/'report.json').relative_to(ROOT)),
        'source_report_sha256':sha(folder/'report.json') if (folder/'report.json').exists() else None,
        'dashboard_check':read(folder/'dashboard.json')}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--final',action='store_true'); args=parser.parse_args()
    starting=read(OUT/'starting_state.json')
    software=read(OUT/'software_checks.json')
    lifecycle=read(OUT/'lifecycle_check.json')
    dashboard=read(OUT/'dashboard_canonical.json')
    final=read(OUT/'final_audit.json')
    evaluation=read(ROOT/'artifacts/evaluation_validation_report.json')
    folders=sorted((OUT/'rehearsals').glob('*'),key=lambda p:p.stat().st_mtime_ns) if (OUT/'rehearsals').exists() else []
    rehearsals=[rehearsal_summary(p) for p in folders if (p/'report.json').exists()]
    latest=rehearsals[-1] if rehearsals else {}
    complete=all([starting.get('status')=='passed_with_declared_limits',software.get('status')=='passed',
        lifecycle.get('status')=='passed',dashboard.get('status')=='passed',final.get('status')=='passed',
        latest.get('driver_exit_code')==0,latest.get('owned_cleanup') is True,
        not software.get('retained_test_finding') or software['retained_test_finding'].get('resolved',False)])
    limits=['Trained-model original actuation remains unqualified; the Stage 13 live attempt was uncertain and refused.',
        'Original recovery qualification is limited to explicit observed-only five-switch UDP latency at 8/5 Mbps.',
        'Loss/saturation/QoS/TCP-bulk latency and larger-topology repairs remain refused/unqualified; model transfer is unvalidated.',
        'Held-out diagnosis covers ten episodes from one held-out family per class; correlated windows limit generalization.',
        'The original Stage 13 freeze omitted some imported modules/settings; its dated post hoc receipt is preserved without rescoring.',
        'No browser/pixel QA, clean-machine installation or cross-machine restoration was verified.']
    value={'schema_version':1,'stage':14,'status':'complete_with_declared_limits' if complete and args.final else 'in_progress',
        'finalized_utc':utc_now(),'summary':{'dataset_counts':starting.get('main_partitions'),
            'model_ids':[m['model_id'] for m in starting.get('models',[])],'canonical_ready_shap':dashboard.get('ready_shap_count'),
            'historical_lineage_checks':len(starting.get('historical_integrated_lineage',[])),
            'implementation_defects_fixed':['Repair UI now reads existing backend applicability and shows uncertainty/staleness/exception reasons without saving a workflow.',
                'Workflow reads refresh completed SHAP status with matching model/window lineage without rewriting history.',
                'Lifecycle validates recognized project commands plus PID start ticks, user, cwd and argv, rejects forged/unowned receipts or changed settings, and gracefully signals only its verified services.',
                'README/recovery readiness and demo instructions distinguish current model/data readiness, observed-only recovery and recorded/live evidence.']},
        'checks':{'software':software,'fresh_shell_lifecycle':{'status':lifecycle.get('status'),'checks':lifecycle.get('checks'),
            'source':'artifacts/stage14/lifecycle_check.json'},'canonical_dashboard':dashboard,'final_audit':final},
        'rehearsal':rehearsals,'limitations':limits,'remaining_blockers':limits,
        'failures':{'rehearsal_errors':[{'tag':r['tag'],'errors':r['errors']} for r in rehearsals if r['errors']],
            'retained_software_finding':software.get('retained_test_finding'),
            'audit_finding':read(OUT/'audit_initial_finding.json'),
            'lint_finding':software.get('lint_initial_failure')},
        'historical_evidence':{'stage13_evaluation_sha256':sha(ROOT/'artifacts/evaluation_validation_report.json'),
            'stage11_native_failures_sha256':sha(ROOT/'artifacts/recovery_validation_report.json'),
            'reuse':'Unchanged root partial-application, verification-failure, restart/restoration and degraded failure behavior is covered by retained Stage 11 native evidence and current focused regressions; no expensive failure campaign repeated.',
            'stage13_baseline_outcomes':evaluation.get('summary',{}).get('primary_outcomes')},
        'measurement_sources':{'automated':'Explicit software fixtures, fresh-shell lifecycle and Streamlit AppTest',
            'rehearsal':'One current real packet experiment; separate ordinary-user API/UI and root owner',
            'model':'Existing actual calibrated model/validation SHAP; no new training or test scoring',
            'historical':'Earlier run IDs/timestamps retained and never displayed as live telemetry'},
        'stage15_readiness':{'can_begin':bool(complete and args.final),'stage15_started':False,'full_project_complete':False,
            'permitted_claims':['Local integrated application, complete measured dataset, calibrated held-out results with stated sample limits, real SHAP, isolated twin comparisons, conditional observed-only verified repair/Undo and honest refusals.',
                'All current recorded rehearsal outcomes must be described with their actual status, workload, mode, counts and source IDs.'],
            'unsupported_claims':['All-fault repair','production trained-AI actuation','generalization to arbitrary networks','larger-topology model transfer','zero-disruption forwarding','clean-machine deployment']},
        'reproduce':['.venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json check',
            '.venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json start',
            '.venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json status',
            'sudo env PYTHONPATH=src /usr/bin/python3 scripts/rehearse_stage14.py --detach',
            '.venv/bin/python scripts/manage_app.py --config artifacts/stage6/runtime/config.json stop']}
    atomic_json(ROOT/'artifacts/integration_validation_report.json',value)
    if args.final and not complete: raise RuntimeError('Integration completion gate incomplete; preserved report remains in_progress')
    if args.final:
        checklist=ROOT/'docs/STAGE14_CHECKLIST.md'
        checklist.write_text(checklist.read_text().replace('- [ ]','- [x]'))
        progress=ROOT/'docs/PROGRESS.md'
        marker='## Stage 14 — integrated verification and handover (2026-10-19)'
        if marker not in progress.read_text():
            with progress.open('a') as output:
                output.write('\n\n'+marker+'\n\n'
                    '**Stage 14 complete with declared limits; Stage 15 not started.** Package/API 0.14.0 preserves the complete Stage 13 dataset, '
                    'calibrated bundle, held-out predictions/metrics and actual SHAP. All scientific artifact hashes and the full membership digest were checked unchanged; '
                    'there was no model training, threshold change, test scoring, full dataset collection, scale or baseline campaign.\n\n'
                    'Fixed the repair UI eligibility gap by reading the existing backend gates without persisting explanation/workflow state; '
                    'application still independently rechecks. Fixed stale pending SHAP in workflow reads using model/window-validated in-memory projections. '
                    'Added ordinary-user lifecycle commands with recognized program/PID/ticks/UID/cwd/argv checks, occupied-port and changed-config refusal, '
                    'forged-receipt rejection and graceful owned shutdown. Root agent/Mininet remain separately launched with OS Python.\n\n'
                    'Software receipts retain 18 focused initial/recovery tests, 44 integration/failure regressions, 21 post-fix tests and the later targeted '
                    'ownership checks. One fixture-scoping failure and initial lint findings were preserved and corrected. Ruff/pip checks passed. '
                    'Fresh-shell lifecycle verification preserved an unrelated listener, created no network/jobs on startup, retained mode-off restart and scoped shutdown. '
                    'The root partial/interruption/rollback failure campaign was not repeated; compatible Stage 11 native evidence plus current regressions remain separate.\n\n'
                    'One fresh packet rehearsal, `'+latest['tag']+'`, completed in '+str(round(latest['total_rehearsal_ms']/1000,2))+' seconds. '
                    'Explicit observed-only UDP 8/5 Mbps source `'+latest['source_id']+'`, incident `'+latest['incident_id']+'`, '
                    'workflow `'+latest['workflow_id']+'`, action `'+latest['action_id']+'`: '
                    'critical RTT '+str(round(latest['before_rtt_ms'],3))+' → '+str(round(latest['after_rtt_ms'],3))+' ms in two settled original windows; '
                    'approximately 8.001/5.000 Mbps delivered, zero measured settled UDP loss. Twin mean prediction was '+str(round(latest['predicted_rtt_ms'],3))+' ms. '
                    'Application 955.53 ms; verification 27.11 seconds. Whole native intervals overlapping application recorded critical 136/1717 packets lost '
                    '(7.92%) and bulk 0/1042, over about two seconds including adjacent traffic; no seamless/sub-interval claim. '
                    'Intentional applicable Undo restored 66.261 ms RTT with impairment/workload still active; source then cleaned.\n\n'
                    'Fresh collector progress during twins, responsive health endpoints and Stop Automation were recorded. Retained actual SHAP took 160.69 ms '
                    'between sampler ticks; bracketing observations showed continuity at sampling resolution, and an explicit blocked-explanation-worker fixture '
                    'verified concurrent collector progress. Both real canonical and rehearsal backends passed all six Streamlit AppTest pages, approved downloads, '
                    'unchanged navigation job/audit counts and control mode. Browser/pixel QA is unavailable and not claimed.\n\n'
                    'Final SQLite/foreign-key, model compatibility, incident/snapshot/action/verification/Undo lineage, runtime isolation and OS resource audits passed. '
                    'No rehearsal processes, OVS bridges or socket remain; auto-repair/observed-only flags are off. Canonical API/dashboard remain available '
                    'under the ordinary-user launcher. `README.md`, `DEMO_GUIDE.md`, `PROJECT_STATUS.md`, architecture, environment, recovery and dashboard usage '
                    'are updated. `artifacts/integration_validation_report.json` separates implementation, fixtures, current packets, historical evidence and failures. '
                    'Stage 15 may begin with these conditional claims; trained-model actuation, all-fault/scale repair, arbitrary-network transfer, zero disruption and '
                    'clean-machine deployment remain unsupported. No final report or presentation was created.\n')
        receipt={'stage':14,'status':value['status'],'completed_utc':utc_now(),'stage15_started':False,'full_project_complete':False,
            'hashes':{str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'artifacts/integration_validation_report.json',
                OUT/'final_audit.json',OUT/'software_checks.json',ROOT/'docs/DEMO_GUIDE.md',ROOT/'docs/PROJECT_STATUS.md',
                ROOT/'README.md',ROOT/'docs/ARCHITECTURE.md',ROOT/'docs/PROGRESS.md']}}
        atomic_json(OUT/'completion.json',receipt)
    print(json.dumps({'status':value['status'],'rehearsal_tag':latest.get('tag'),'rehearsal_outcome':latest.get('status'),
        'stage15_can_begin':value['stage15_readiness']['can_begin']},indent=2))


if __name__=='__main__': main()
