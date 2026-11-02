"""Checkpointed typed API jobs; unknown submissions are reconciled, never replayed."""
import base64
import hashlib
import time
from pathlib import Path
from uuid import uuid4

from explainnet.config import load_settings
from explainnet.dashboard.client import ApiClient, ClientSettings
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now


class CompletionClient:
    def __init__(self,config,directory):
        self.settings=load_settings(Path(config));self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.client=ApiClient(ClientSettings(api_url=f'http://127.0.0.1:{self.settings.port}',timeout_s=30))
        identity=self.get('/v1/config')
        if identity['config_hash']!=self.settings.config_hash or identity['identity']['database_path']!=str(self.settings.database_path):
            raise ValueError('API/config/store identity mismatch; no mutation submitted')

    def get(self,path):return self.client.get(path)

    def post(self,path,body):return self.client.request(path,'POST',body)

    def job_evidence(self,jid):
        raw=bytearray();offset=0;expected=None;total=1
        while offset<total:
            page=self.get(f'/v1/jobs/{jid}/evidence?offset={offset}')
            if expected is None:expected=page['sha256'];total=page['total_bytes']
            block=base64.b64decode(page['base64'],validate=True)
            if (total>32*1024*1024 or page['sha256']!=expected or page['offset']!=offset
                    or page['total_bytes']!=total or not block or len(block)>49152 or page['next_offset']!=offset+len(block)):
                raise ValueError('Job evidence integrity/size/offset mismatch')
            raw.extend(block);offset=page['next_offset']
        if len(raw)!=total or hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Job evidence hash mismatch')
        import json
        return json.loads(raw)

    def job(self,name,route,body,timeout=180):
        import json
        if not name.replace('_','').isalnum():raise ValueError('bounded logical job name required')
        path=self.directory/(name+'.json');first=not path.exists()
        intent=json.loads(path.read_text()) if not first else {'request_key':'c3'+uuid4().hex,'route':route,
            'body':body,'created_utc':utc_now(),'state':'pending_submission'}
        if intent['route']!=route or intent['body']!=body:raise ValueError('Job intent changed; no replay')
        atomic_json(path,intent)
        if not intent.get('job_id'):
            if not first:
                prior=self.get('/v1/dashboard/submissions/'+intent['request_key'])
                if not prior['found']:raise RuntimeError('Unknown submission '+intent['request_key']+'; reconcile before retry')
                intent['job_id']=prior['job_id']
            else:
                ack=self.client.submit(route,body,intent['request_key']);intent['job_id']=ack['job_id']
            atomic_json(path,intent)
        start=time.monotonic()
        while time.monotonic()-start<timeout:
            value=self.get('/v1/jobs/'+intent['job_id'])
            if value['state'] in {'succeeded','failed','interrupted','canceled'}:
                full=self.job_evidence(intent['job_id'])
                intent.update(state=value['state'],elapsed_ms=(time.monotonic()-start)*1000,
                    error=value.get('error'),ended_utc=utc_now())
                atomic_json(path,intent)
                if value['state']!='succeeded':raise RuntimeError(route+': '+str(value.get('error') or value['state'])+'; no automatic retry')
                return full['result']
            time.sleep(.3)
        raise TimeoutError('Outcome unknown for '+intent['job_id']+'; inspect its saved intent before resuming')
