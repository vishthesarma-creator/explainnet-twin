"""Root read-only extraction of saved stage-2 capture timing; writes one report."""
import hashlib
import json
import statistics
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = Path('/var/lib/explainnet-teacher-demo')


def main():
    wanted = {}
    for group in ['main','verified']:
        for path in (ROOT/'artifacts/completion_stage2'/group).glob('*.json'):
            case = json.loads(path.read_text())
            for trial in (case.get('workflow',{}).get('candidate_result') or {}).get('trials',[]):
                if trial.get('capture_id'):
                    wanted[trial['capture_id']] = {'set':group,'case':case['name'],'trial_id':trial['trial_id'],
                        'reset_ms':trial.get('reset_ms')}
    results = {}
    for path in (OWNER/'rpc_receipts').glob('*.json'):
        receipt = json.loads(path.read_text())
        if receipt.get('operation') != 'twin_capture' or receipt.get('state') != 'completed': continue
        reference = receipt['ack']['evidence']
        native = OWNER/'response_evidence'/(reference['sha256']+'.json')
        raw = native.read_bytes()
        if hashlib.sha256(raw).hexdigest() != reference['sha256']: raise ValueError('native hash mismatch')
        capture = json.loads(raw); cid = capture['capture_id']
        if cid not in wanted: continue
        row = wanted[cid] | {k:capture.get(k) for k in ['capture_id','measurement_protocol',
            'warmup_elapsed_ms','elapsed_ms','duration_s','started_monotonic_s','started_utc']}
        row['source_evidence_sha256'] = reference['sha256']
        row['planes'] = {}
        for instance, samples in capture['series'].items():
            points = [s for s in samples if s['monotonic_s'] <= capture['started_monotonic_s']+capture['duration_s']]
            fields = {}
            for field in ['lock_wait_ms','ownership_check_ms','collection_duration_ms','total_observation_ms']:
                values = [s[field] for s in samples if s.get(field) is not None]
                fields[field] = {'n':len(values),'mean':statistics.mean(values) if values else None,
                    'max':max(values) if values else None}
            fields['in_window_intervals_s'] = [b['monotonic_s']-a['monotonic_s'] for a,b in pairwise(points)]
            fields['warmup_probe_rtts_ms'] = [s['probe']['rtt_values_ms'] for s in capture.get('warmup_series',{}).get(instance,[])]
            row['planes'][instance] = fields
        results[cid] = row
    out = ROOT/'artifacts/completion_stage2/native_capture_timings.json'
    out.write_text(json.dumps({'captures':results,'missing_capture_ids':sorted(set(wanted)-set(results)),
        'units':'all elapsed and observer components milliseconds; sample gaps seconds',
        'limitation':'reset and matched-capture components measured separately; full candidate trial wall time was not independently instrumented'},indent=2)+'\n')
    print(json.dumps({'captures':len(results),'missing':len(set(wanted)-set(results))}))


if __name__ == '__main__': main()
