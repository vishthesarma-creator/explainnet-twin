"""Explicit nominal capture using existing packet/quality machinery; no injection."""
import fcntl
import json
import os
from pathlib import Path
from uuid import uuid4

from explainnet.agent import RPC_CONTEXT
from explainnet.storage import utc_now
from explainnet.twin_spec import digest


def capture_reference(worker, request):
    control=worker.coordinator.control() | worker.coordinator.lifecycle()
    if any(control.get(k) for k in ['auto_enabled','active_workflow_id','monitor_active','unsettled_action_ids','cleanup_pending_workflow_ids']):
        raise ValueError('Stop automation and settle workflow/action/cleanup before nominal capture')
    with Path(f'/var/tmp/explainnet-experiment-{os.geteuid()}.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ValueError('Shared emulator campaign is active; nominal capture was not started') from exc
        network=worker.agent.network_inspect(request)
        journal=worker.agent.scenario_inspect(request).get('laboratory_journal') or {}
        if (journal.get('state') not in {None,'stopped'} and journal.get('configuration',{}).get('kind')!='healthy'):
            raise ValueError('An active fault cannot be designated as the healthy nominal reference')
        if network['state']!='running' or not network.get('live_verified'):
            raise ValueError('Verified running owned original required')
        if any(path!='primary' for path in network.get('selected_paths',{}).values()):
            raise ValueError('Restore selected routes before capturing a nominal reference')
        windows=[]
        parent=RPC_CONTEXT.get()
        for ordinal in range(2):
            token=RPC_CONTEXT.set(str(parent or 'nominal')+'_capture_'+str(ordinal))
            try:windows.append(worker.twins.capture(request.instance_id,15)['window'])
            finally:RPC_CONTEXT.reset(token)
        if any(w['instance_id']!=request.instance_id for w in windows):raise ValueError('Nominal source lineage mismatch')
        baseline={'window_ids':[w['window_id'] for w in windows],'definition_hash':digest(network['definition'])}
        reference,policy=worker.twins.pilot_reference(**baseline)
        result={'kind':'demo_nominal_reference','instance_id':request.instance_id,'created_utc':utc_now(),
            'baseline':baseline,'reference':reference,'policy':policy,'network_changes':False,
            'nominal_designation':'Explicit operator capture while no active fault is present; not injector input to inference'}
        worker.store.insert_record('runs','nominal_'+uuid4().hex,result,config_hash=baseline['definition_hash'])
        return result


def latest_reference(store,instance_id):
    with store.connection() as db:
        row=db.execute("SELECT payload_json FROM runs WHERE json_extract(payload_json,'$.kind')='demo_nominal_reference' "
            "AND json_extract(payload_json,'$.instance_id')=? ORDER BY created_utc DESC LIMIT 1",(instance_id,)).fetchone()
    return json.loads(row[0]) if row else None


def campaign_status(root):
    path=root/'artifacts/completion_stage3/pipeline.json'
    try:
        value=json.loads(path.read_text());pid=value['pid']
        proc=Path('/proc')/str(pid)
        argv=proc.joinpath('cmdline').read_bytes().split(b'\0')
        live=any(b'completion_stage3_pipeline.py' in a for a in argv)
        active=live and value['state'] not in {'finished','blocked'}
        return {'active':active,'state':value['state'],'reason':'Prospective campaign owns shared emulator capacity; live demo operations wait until it releases the laboratory.' if active else None}
    except (OSError,KeyError,ValueError):return {'active':False,'state':'no live campaign detected','reason':None}
