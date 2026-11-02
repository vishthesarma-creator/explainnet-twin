"""Small read-only dashboard adapter. Existing services still own every mutation."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from explainnet import __version__
from explainnet.agent import AgentUnavailable
from explainnet.config import load_profiles
from explainnet.contracts import Identifier
from explainnet.storage import utc_now
from explainnet.workflow_contracts import LabID

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = {
    'completion4': ('completion_stage4_validation.json','Completion 4: integrated application and final acceptance','Explicit cutoff; incomplete research targets remain blockers'),
    'completion3': ('completion_stage3_validation.json', 'Completion 3: prospective corpus and frozen evaluation', 'Current checkpoint; pending results remain unverified'),
    'dataset': ('dataset_quality_report.json', 'Dataset collection and quality', 'Measured dataset audit'),
    'models': ('model_validation_report.json', 'Model readiness', 'Readiness and evaluation gates'),
    'explanations': ('explanation_validation_report.json', 'Explanation validation', 'Measured and software results separated'),
    'twin': ('twin_validation_report.json', 'Digital twin validation', 'Historical laboratory measurements'),
    'candidates': ('candidate_validation_report.json', 'Candidate validation', 'Historical laboratory measurements'),
    'recovery': ('recovery_validation_report.json', 'Recovery validation', 'Historical laboratory and software evidence'),
    'evaluation': ('evaluation_validation_report.json', 'Stage 13 evaluation', 'Current measured evaluation, held-out results and explicit blockers'),
    'integration': ('integration_validation_report.json', 'Stage 14 integration', 'Integration checks and separately labeled fresh rehearsal/historical evidence'),
}
SAFE_FIELDS = {'schema_version', 'stage', 'status', 'summary', 'per_fault', 'limitations', 'blockers', 'dataset_ready','at_utc',
    'dataset_state', 'accepted_windows', 'accepted_export_windows', 'expected_windows', 'completed_episodes',
    'expected_episodes', 'partitions', 'structural_checks_passed', 'measured_performance_readiness',
    'usable_model_exists', 'batch_id', 'model_id', 'actual_measured_shap_cases', 'software_verification', 'software_verification_summary',
    'implementation', 'stage12_eligibility', 'verification_limitations', 'finalized_utc', 'snapshot_utc',
    'dataset_audit', 'model_metadata', 'held_out_metrics', 'baseline_results', 'scale_results', 'checks',
    'measurement_sources', 'reproduce', 'fault_qualification', 'rehearsal', 'failures', 'remaining_blockers', 'stage15_readiness'}
HIDDEN_KEYS = {'native_intervals', 'observation', 'server_json', 'client_json', 'parameters', 'ground_truth',
    'command', 'commands', 'traceback', 'secret', 'password', 'token', 'api_key', 'request_key'}


def public_value(value):
    """No secrets, native payloads, local paths or arbitrary artifact traversal."""
    if isinstance(value, dict):
        return {k: public_value(v) for k, v in value.items() if k.lower() not in HIDDEN_KEYS
            and not any(word in k.lower() for word in ('password', 'secret', 'token', 'directory', 'config_file'))}
    if isinstance(value, list):
        return [public_value(v) for v in value[:200]]
    if isinstance(value, str):
        value = re.sub(r'(?:[A-Za-z]:[\\/]|/(?:mnt|var|tmp|home|run|proc|usr|etc)/)[^\s,;\"\']+', '[local resource]', value)
    return value


@lru_cache(maxsize=16)
def evidence_bytes(artifact_id, modified_ns, root=ROOT):
    del modified_ns  # cache identity comes from the approved file's mtime
    filename = ARTIFACTS[artifact_id][0]
    path = root / 'artifacts' / filename
    if path.parent.is_symlink() or path.is_symlink() or path.stat().st_size > 30_000_000:
        raise ValueError('evidence unavailable: unsupported file size or symlink')
    raw = json.loads(path.read_text(encoding='utf-8'))
    result = {'artifact_id': artifact_id, 'source': 'Prospective campaign checkpoint; inspect its timestamp/status, pending results are unverified' if artifact_id=='completion3' else 'Existing project evidence; historical, not a live status',
        'projection': 'Approved summary fields; native logs, local paths and credentials excluded',
        'evidence': public_value({k: v for k, v in raw.items() if k in SAFE_FIELDS})}
    return (json.dumps(result, indent=2, allow_nan=False) + '\n').encode()


class Records(BaseModel):
    records: list[dict[str, Any]]


class DashboardStatus(BaseModel):
    schema_version: Literal[1] = 1
    at_utc: str
    api_version: str
    database: str
    agent: dict[str, Any]
    dataset: dict[str, Any]
    models: dict[str, Any]
    explanations: dict[str, Any]
    twin: dict[str, Any]
    control: dict[str, Any]
    traffic_profiles: list[str]


class Reversible(BaseModel):
    available: bool
    action_id: str | None = None
    reason: str


COLLECTIONS = {
    'workflows': ('recovery_workflows', ['workflow_id', 'instance_id', 'incident_id', 'state', 'created_utc',
        'snapshot_id', 'experiment_id', 'action_id', 'reasons', 'error', 'diagnosis', 'finished']),
    'actions': ('lab_action_state', ['action_id', 'workflow_id', 'instance_id', 'incident_id', 'state', 'created_utc',
        'ended_utc', 'logical_diff', 'error', 'degraded', 'snapshot_id', 'automated']),
    'snapshots': ('twin_snapshots', ['snapshot_id', 'original_instance_id', 'created_utc', 'expires_utc', 'snapshot_hash']),
    'experiments': ('recovery_experiments', ['operation_id', 'snapshot_id', 'twin_id', 'state', 'created_utc', 'progress', 'error']),
    'twins': ('twin_instances', ['twin_id', 'snapshot_id', 'state', 'instance_id', 'reason']),
    'incidents': ('incident_state', ['incident_id', 'instance_id', 'state', 'severity', 'last_observation_utc',
        'observed_start_utc', 'observed_update_utc', 'last_window_id', 'service_status', 'flow', 'path', 'affected_links']),
}


def mount_dashboard(app, settings, store, worker):
    @app.get('/v1/dashboard/status', response_model=DashboardStatus)
    def dashboard_status():
        if not store.healthy():
            raise HTTPException(503, 'Storage unavailable. Run init/migrations and check the backend log.')
        with store.connection() as db:
            counts = dict(db.execute('SELECT partition,count(*) FROM dataset_members GROUP BY partition'))
            batches = []
            for row in db.execute('SELECT payload_json FROM dataset_batches ORDER BY rowid DESC LIMIT 20'):
                b = json.loads(row[0])
                schedule = b['schedule']
                target = sum(e['target_windows'] for e in schedule['episodes'])
                accepted = db.execute('SELECT count(*) FROM dataset_members WHERE batch_id=?', (b['batch_id'],)).fetchone()[0]
                batches.append({'batch_id': b['batch_id'], 'purpose': schedule['purpose'], 'state': b['state'],
                    'accepted_windows': accepted, 'target_windows': target, 'updated_utc': b.get('updated_utc'),
                    'reason': public_value(b.get('error'))})
            model_count = db.execute('SELECT count(*) FROM model_bundles').fetchone()[0]
            explanation_count = db.execute("SELECT count(*) FROM explanations WHERE state='ready'").fetchone()[0]
            snapshot_count = db.execute('SELECT count(*) FROM twin_snapshots').fetchone()[0]
        main = next((b for b in batches if b['purpose'] == 'main'), None)
        try:
            quality = json.loads((ROOT / 'artifacts/dataset_quality_report.json').read_text())
        except (OSError, ValueError):
            quality = {}
        dataset_ready = bool(main and main['state'] == 'completed' and main['accepted_windows'] == main['target_windows']
            and quality.get('batch_id') == main['batch_id'] and quality.get('dataset_ready')
            and quality.get('structural_checks_passed'))
        try:
            inventory = worker.agent.inventory()
            agent = {'available': True, 'reason': None, 'instances': public_value(inventory.get('instances', []))}
        except AgentUnavailable:
            agent = {'available': False, 'reason': 'Privileged agent is unavailable. Start it separately for live laboratory operations.', 'instances': []}
        try:
            profiles = list(load_profiles(settings.traffic_profiles_file))
        except (OSError, ValueError, TypeError):
            profiles = []
        return DashboardStatus(at_utc=utc_now(), api_version=__version__, database='available', agent=agent,
            dataset={'ready': dataset_ready, 'counts_by_split': counts, 'batches': batches},
            models={'registered_count': model_count, 'active_model_id': worker.diagnosis.status()['active_model_id']},
            explanations={'ready_count': explanation_count, 'worker_live': worker.explanations.status()['worker_live']},
            twin={'snapshot_count': snapshot_count, 'live_ready': None,
                'reason': 'A live source, qualified nominal reference, fresh snapshot and passing fidelity are required per experiment.'},
            control=worker.coordinator.control() | worker.coordinator.lifecycle(), traffic_profiles=profiles)

    @app.get('/v1/dashboard/telemetry/{instance_id}')
    def telemetry_history(instance_id: Identifier, limit: int = Query(default=60, ge=1, le=100)):
        with store.connection() as db:
            rows = db.execute("SELECT w.payload_json FROM telemetry_windows w WHERE w.instance_id=? AND NOT EXISTS "
                "(SELECT 1 FROM dataset_members m WHERE m.window_id=w.window_id AND m.partition='test') "
                "AND w.run_id NOT IN (SELECT json_extract(a.payload_json,'$.collector_run_id') FROM dataset_attempts a "
                "WHERE json_extract(a.payload_json,'$.partition')='test' AND json_extract(a.payload_json,'$.collector_run_id') IS NOT NULL) "
                "ORDER BY w.end_monotonic_s DESC LIMIT ?", (instance_id, limit)).fetchall()
        return {'collector': worker.telemetry.status(instance_id), 'windows': [json.loads(r[0]) for r in rows],
            'source': 'Stored receiver/probe/counter windows; sealed test measurements excluded'}

    @app.get('/v1/dashboard/telemetry-sources', response_model=Records)
    def telemetry_sources():
        with store.connection() as db:
            rows = db.execute("SELECT w.instance_id,count(*) AS window_count,max(json_extract(w.payload_json,'$.at_utc')) AS last_observation_utc "
                "FROM telemetry_windows w WHERE NOT EXISTS (SELECT 1 FROM dataset_members m WHERE m.window_id=w.window_id AND m.partition='test') "
                "AND w.run_id NOT IN (SELECT json_extract(a.payload_json,'$.collector_run_id') FROM dataset_attempts a "
                "WHERE json_extract(a.payload_json,'$.partition')='test' AND json_extract(a.payload_json,'$.collector_run_id') IS NOT NULL) "
                "GROUP BY w.instance_id ORDER BY last_observation_utc DESC LIMIT 100").fetchall()
        return Records(records=[dict(r) for r in rows])

    @app.get('/v1/dashboard/windows/{window_id}')
    def observed_window(window_id: Identifier):
        with store.connection() as db:
            row = db.execute("SELECT w.payload_json FROM telemetry_windows w WHERE w.window_id=? AND NOT EXISTS "
                "(SELECT 1 FROM dataset_members m WHERE m.window_id=w.window_id AND m.partition='test') "
                "AND w.run_id NOT IN (SELECT json_extract(a.payload_json,'$.collector_run_id') FROM dataset_attempts a "
                "WHERE json_extract(a.payload_json,'$.partition')='test' AND json_extract(a.payload_json,'$.collector_run_id') IS NOT NULL)", (window_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Observation unavailable or sealed.')
            alert = db.execute('SELECT payload_json FROM baseline_alerts WHERE window_id=?', (window_id,)).fetchone()
        return {'window': json.loads(row[0]), 'rule_findings': json.loads(alert[0]) if alert else None,
            'source': 'Stored observation and transparent rules; not a trained prediction'}

    @app.get('/v1/dashboard/records/{collection}', response_model=Records)
    def dashboard_records(collection: Literal['workflows', 'actions', 'snapshots', 'experiments', 'twins', 'incidents', 'jobs', 'audit'],
            limit: int = Query(default=30, ge=1, le=100)):
        with store.connection() as db:
            if collection == 'jobs':
                rows = [dict(r) for r in db.execute('SELECT id,type,state,created_utc,ended_utc,elapsed_ms,error FROM jobs ORDER BY created_utc DESC LIMIT ?', (limit,))]
            elif collection == 'audit':
                rows = [dict(r) for r in db.execute('SELECT at_utc,actor,event_type,subject_id,payload_json FROM audit_events ORDER BY id DESC LIMIT ?', (limit,))]
                for r in rows:
                    r['details'] = public_value(json.loads(r.pop('payload_json')))
            else:
                table, fields = COLLECTIONS[collection]
                order = 'last_observation_utc DESC' if collection == 'incidents' else 'rowid DESC'
                rows = [{k: v for k, v in json.loads(r[0]).items() if k in fields}
                    for r in db.execute(f'SELECT payload_json FROM {table} ORDER BY {order} LIMIT ?', (limit,))]
        return Records(records=public_value(rows))

    @app.get('/v1/dashboard/submissions/{key}')
    def submission(key: Identifier):
        job_id = store.idempotent_job(key)
        return {'found': job_id is not None, 'job_id': job_id}

    @app.get('/v1/dashboard/reversible/{instance_id}', response_model=Reversible)
    def reversible(instance_id: Identifier):
        if worker.coordinator.busy(instance_id):
            return Reversible(available=False, reason='A recovery workflow is active.')
        with store.connection() as db:
            row = db.execute("SELECT action_id FROM lab_action_state WHERE instance_id=? AND state='succeeded' ORDER BY created_utc DESC LIMIT 1", (instance_id,)).fetchone()
        if not row:
            return Reversible(available=False, reason='No successful current action is available to undo.')
        try:
            actual = worker.agent.lab_status(LabID(action_id=row[0]))
            valid = actual['state'] == 'kept' and actual['current'] == actual['after']
            return Reversible(available=valid, action_id=row[0] if valid else None,
                reason='Current owned state matches the kept action. Undo rechecks it again.' if valid else 'Intervening configuration or workload change makes Undo unsafe.')
        except (AgentUnavailable, KeyError, ValueError):
            return Reversible(available=False, reason='Live ownership and configuration could not be verified.')

    @app.get('/v1/dashboard/applicable/{workflow_id}')
    def application_eligibility(workflow_id: Identifier):
        return public_value(worker.coordinator.eligibility(workflow_id))

    @app.get('/v1/dashboard/evidence', response_model=Records)
    def evidence_list():
        records = []
        for key, (filename, title, kind) in ARTIFACTS.items():
            path = ROOT / 'artifacts' / filename
            try:
                data = evidence_bytes(key, path.stat().st_mtime_ns)
                records.append({'artifact_id': key, 'title': title, 'kind': kind, 'available': True,
                    'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            except (OSError, ValueError, TypeError):
                records.append({'artifact_id': key, 'title': title, 'kind': kind, 'available': False})
        return Records(records=records)

    @app.get('/v1/dashboard/evidence/{artifact_id}')
    def evidence_download(artifact_id: Literal['dataset', 'models', 'explanations', 'twin', 'candidates', 'recovery', 'evaluation', 'integration','completion3','completion4']):
        path = ROOT / 'artifacts' / ARTIFACTS[artifact_id][0]
        try:
            data = evidence_bytes(artifact_id, path.stat().st_mtime_ns)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(404, 'Approved evidence is unavailable.') from exc
        return Response(data, media_type='application/json', headers={'Content-Disposition': f'attachment; filename="explainnet-{artifact_id}.json"'})

    documents={
        'report-docx':('ExplainNet_Twin_Report_Reviewed.docx','Final report DOCX','application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
        'report-pdf':('ExplainNet_Twin_Report_Reviewed.pdf','Final report PDF','application/pdf'),
        'slides':('ExplainNet_Twin_Presentation.pptx','Final presentation PPTX','application/vnd.openxmlformats-officedocument.presentationml.presentation'),
        'slides-pdf':('ExplainNet_Twin_Presentation.pdf','Final presentation PDF','application/pdf'),
        'script':('Group_Demo_Script.pdf','Group speaking and demo script','application/pdf'),
        'viva':('Viva_Guide.pdf','Viva guide','application/pdf'),
        'package':('ExplainNet_Twin_Submission.zip','Submission package with stated blockers','application/zip')}

    def approved_document(identifier):
        path=ROOT/'deliverables/completion4'/documents[identifier][0]
        base=ROOT/'deliverables/completion4'
        if (path.is_symlink() or base.is_symlink() or not path.resolve().is_relative_to(base.resolve())
                or not path.is_file() or path.stat().st_size>50_000_000):
            raise HTTPException(404,'Approved current-edition document unavailable')
        return path

    @app.get('/v1/dashboard/deliverables',response_model=Records)
    def document_list():
        rows=[]
        for identifier,(_name,title,_mime) in documents.items():
            try:
                path=approved_document(identifier)
                rows.append({'id':identifier,'title':title,'bytes':path.stat().st_size})
            except HTTPException:continue
        return Records(records=rows)

    @app.get('/v1/dashboard/deliverables/{document_id}')
    def document_download(document_id:Literal['report-docx','report-pdf','slides','slides-pdf','script','viva','package']):
        path=approved_document(document_id)
        return Response(path.read_bytes(),media_type=documents[document_id][2],
            headers={'Content-Disposition':f'attachment; filename="{path.name}"'})
