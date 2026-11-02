"""One bounded healthy lifecycle, no fault/model/dataset/repair campaign."""
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from teacher_demo_session import Session

from explainnet.agent import AgentClient
from explainnet.application_profiles import PROFILES
from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.network_contracts import TrafficRunRequest
from explainnet.storage import Store

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'artifacts/completion_stage1/live.json'


def now():
    return datetime.now(UTC).isoformat()


def fresh(session):
    end = time.monotonic() + 90
    while time.monotonic() < end:
        data = session.http('/v1/dashboard/telemetry/' + session.current() + '?limit=30')
        run = (data['collector'].get('session') or {}).get('run_id')
        candidates = [w for w in data['windows'] if w['run_id'] == run and w['complete']]
        if candidates:
            w = candidates[0]
            if data['collector']['live'] and w['inference_ready'] and 0 <= (datetime.now(UTC) - datetime.fromisoformat(w['at_utc'])).total_seconds() <= 30:
                with session.store.connection() as db:
                    row = db.execute('SELECT payload_json FROM telemetry_windows WHERE window_id=?', (w['window_id'],)).fetchone()
                assert row and json.loads(row[0]) == w
                return {'at_utc': now(), 'instance_id': session.current(), 'collector': data['collector'],
                    'window': w, 'same_store_verified': True, 'traffic': session.data['healthy_traffic']}
        time.sleep(1)
    raise RuntimeError('no fresh complete inference-suitable CURRENT collector window within 90 seconds; no gate changed')


def corpus_state():
    result = {}
    for profile, (config, _) in PROFILES.items():
        cfg = load_settings(config)
        store = Store(cfg.database_path)
        with store.connection() as db:
            result[profile] = {'dataset_members': db.execute('SELECT count(*) FROM dataset_members').fetchone()[0],
                'models': db.execute('SELECT count(*) FROM model_bundles').fetchone()[0]}
    return result


def main():
    report = {'started_utc': now(), 'kind': 'native healthy lifecycle; not fault/repair qualification',
        'before': corpus_state(), 'steps': []}
    def save():
        atomic_json(REPORT, report)
    save()
    try:
        session = Session()
        report['binding'] = session.binding
        # Exercise a previously oversized native record without affecting a live run.
        request = TrafficRunRequest(instance_id='teachlive_03f4798225', run_id='r50f8abad2313461db95a4be87fa86baa')
        agent = AgentClient(session.cfg.agent_socket)
        native = agent.traffic_status(request)
        assert native['state'] in {'succeeded', 'failed', 'canceled', 'interrupted'}
        ack = agent.call('traffic_stop', request.model_dump(), hydrate=False)
        restored = agent.read_evidence(ack['evidence'])
        assert native == restored and ack['ack_version'] == 2
        report['large_native_evidence'] = {'state': native['state'], 'ack_bytes': len(json.dumps(ack).encode()),
            'full_bytes': ack['evidence']['bytes'], 'sha256': ack['evidence']['sha256'], 'retrieval_equal': True}
        for index in range(2):
            start = time.monotonic()
            session.prepare()
            measured = fresh(session)
            measured['preparation_elapsed_ms'] = (time.monotonic() - start) * 1000
            report['steps'].append({'step': 'prepare_' + str(index + 1), **measured})
            save()
            if index == 0:
                original = session.current()
                session.cleanup()
                assert session.http('/v1/networks/' + original)['state'] == 'stopped'
                report['steps'].append({'step': 'scoped_cleanup', 'at_utc': now(), 'instance_id': original, 'state': 'stopped'})
                save()
        first, second = report['steps'][0], report['steps'][2]
        assert first['instance_id'] != second['instance_id']
        assert first['collector']['session']['run_id'] != second['collector']['session']['run_id']
        assert first['traffic']['run_id'] != second['traffic']['run_id']
        # Exercise intentional healthy renewal and the new current-run boundary.
        session.healthy_traffic()
        renewal = fresh(session)
        assert renewal['collector']['session']['run_id'] != second['collector']['session']['run_id']
        report['steps'].append({'step': 'healthy_renewal', **renewal})
        # Refresh/status must not write jobs, control, cached network/run records.
        def control_rows():
            with session.store.connection() as db:
                return {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
                    for table in ['jobs', 'recovery_control', 'recovery_workflows', 'lab_action_state', 'network_instances']}
        before_reads = control_rows()
        for _ in range(2):
            for route in ['/v1/dashboard/status', '/v1/lab/control', '/v1/config', '/v1/networks/' + session.current(),
                    '/v1/traffic/' + session.current() + '/' + session.data['healthy_traffic']['run_id'],
                    '/v1/laboratory/scenarios/' + session.current(), '/v1/dashboard/telemetry/' + session.current()]:
                session.http(route)
        assert control_rows() == before_reads
        report['status_reads_non_mutating'] = True
        report['final_control'] = session.http('/v1/lab/control')
        assert not report['final_control']['auto_enabled'] and not report['final_control']['allow_observed_only']
        assert not report['final_control']['active_workflow_id']
        report['after'] = corpus_state()
        assert report['before'] == report['after']
        report['state'] = 'passed_healthy_left_running'
        report['cleanup_command'] = '.venv/bin/python scripts/teacher_demo_session.py cleanup'
    except Exception as exc:
        report.update(state='failed_state_retained', error=str(exc))
        raise
    finally:
        report['ended_utc'] = now()
        save()


if __name__ == '__main__':
    main()
