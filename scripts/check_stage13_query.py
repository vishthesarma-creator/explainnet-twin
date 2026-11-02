"""Bounded real-store read benchmark for the sealed-source query correction."""
import json
import sqlite3
import time
from pathlib import Path

from explainnet.config import load_settings
from explainnet.dataset_export import atomic_json
from explainnet.storage import utc_now

ROOT=Path(__file__).resolve().parents[1]
settings=load_settings(ROOT/'artifacts/stage6/runtime/config.json')
base="SELECT w.instance_id,count(*) FROM telemetry_windows w WHERE NOT EXISTS (SELECT 1 FROM dataset_members m WHERE m.window_id=w.window_id AND m.partition='test') "
tail=' GROUP BY w.instance_id'
queries={
    'original_correlated':base+"AND NOT EXISTS (SELECT 1 FROM dataset_attempts a WHERE json_extract(a.payload_json,'$.collector_run_id')=w.run_id AND json_extract(a.payload_json,'$.partition')='test')"+tail,
    'corrected_materialized_list':base+"AND w.run_id NOT IN (SELECT json_extract(a.payload_json,'$.collector_run_id') FROM dataset_attempts a WHERE json_extract(a.payload_json,'$.partition')='test' AND json_extract(a.payload_json,'$.collector_run_id') IS NOT NULL)"+tail}
results=[]
with sqlite3.connect('file:'+str(settings.database_path)+'?mode=ro',uri=True) as db:
    for name,query in queries.items():
        start=time.monotonic()
        db.set_progress_handler(lambda start=start: int(time.monotonic()-start>3),1000)
        try:
            rows=db.execute(query).fetchall()
            result={'name':name,'state':'finished','returned_sources':len(rows),'returned_windows':sum(r[1] for r in rows)}
        except sqlite3.OperationalError as exc:
            result={'name':name,'state':'bounded_interrupt','error':str(exc)}
        result['elapsed_ms']=(time.monotonic()-start)*1000
        results.append(result)
receipt={'at_utc':utc_now(),'kind':'read_only_real_store_query_benchmark','limit_s':3,'results':results}
atomic_json(ROOT/'artifacts/stage13/dashboard_query_benchmark.json',receipt)
print(json.dumps(receipt,indent=2))
