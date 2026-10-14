"""Raw counts/metrics and saved native release parity for one sealed V31 case."""
import argparse
import csv
import json
from pathlib import Path
from .coarse_observation import sha,digest
from .audit_cellreplay_mixed import read_rows
from .cellreplay_mixed import summarize

def run(input_path,native_queue,out):
    p=Path(input_path);nq=Path(native_queue);out=Path(out)
    if out.exists():raise FileExistsError(out)
    root=Path(__file__).resolve().parents[1]
    m=json.loads((p/'manifest.json').read_text());f=json.loads((p/'frozen.json').read_text());cfg=f['config']
    assert sha(p/'frozen.json')==m['frozen_sha256'] and sha(p/'runs.csv')==m['runs_sha256']
    for name,value in f['model_sha256'].items():assert sha(root/name)==value
    for filename,field in (('exposure.json','exposure_sha256'),('heavy_summary.json','heavy_summary_sha256'),
                           ('native.csv','native_release_sha256'),('planned.csv.gz','planned_sha256'),('invariant.json','invariant_sha256')):
        assert sha(p/filename)==m[field]
    native=json.loads((nq/'audit.json').read_text())
    assert native['status']=='PASS_ONE_HELDOUT_ALL_PACKET_NATIVE_FIFO_DIFFERENTIAL'
    nf=json.loads((nq/'frozen.json').read_text());assert nf['input_manifest_sha256']==sha(p/'manifest.json')
    planned=list(read_rows(p/'planned.csv.gz'));count=0
    with (p/'native.csv').open(newline='') as h:
        for count,row in enumerate(csv.DictReader(h),1):
            assert int(row['packet_id'])==count-1
            for key,value in planned[count-1].items():
                if key in row:assert row[key]==str(value)
    assert count==len(planned)==m['native_release_rows']
    with (p/'runs.csv').open(newline='') as h:runs=list(csv.DictReader(h))
    receipts={r['file']:r for r in m['receipts']};total=0;controls=0
    expected_events=digest([(r['arrival_ms'],r['flow'],r['flow_id'],r['content_bytes']) for r in planned])
    for c in runs:
        path=p/c['packet_file'];assert sha(path)==receipts[path.name]['sha256']
        rows=list(read_rows(path));assert len(rows)==len(planned)==receipts[path.name]['rows']
        assert expected_events==c['source_arrival_sha256']
        first=None;eligible=0;bypasses=0
        for pid,(r,plan) in enumerate(zip(rows,planned)):
            for key,value in plan.items():assert r[key]==value
            assert r['packet_id']==pid
            if r['status']=='completed':
                assert cfg['end_ms']>=r['finish_ms']>=r['release_ms']
                assert r['delay_ms']==r['finish_ms']-r['arrival_ms']
            else:
                assert r['status'] in ('dropped','unfinished') and r['finish_ms']==r['delay_ms']==''
            if first is None and r['status']=='dropped':first=pid
            elif first is not None and r['release_ms']<=cfg['end_ms'] and r['planned_light_bypass']:
                eligible+=1;bypasses+=int(r['actual_bypass'])
        if c['accounting']=='original':assert bypasses==0
        saved=next(i for i in json.loads((p/'invariant.json').read_text()) if i['accounting']==c['accounting'])
        assert saved==dict(accounting=c['accounting'],first_refusal_id=first,eligible_after_refusal=eligible,bypasses_after_refusal=bypasses)
        metrics=summarize(rows,cfg['warm_ms'],cfg['deadlines_ms'])
        for k,v in metrics.items():assert c[k]==str(v) if v is not None else c[k]==''
        assert metrics['control_count']==10000
        total+=len(rows);controls+=metrics['control_count']
        print(f"held-out raw audit {c['accounting']} passed",flush=True)
    assert len({r['rho_actual'] for r in runs})==1 and len({r['planned_sha256'] for r in runs})==1
    out.mkdir(parents=True)
    result=dict(status='PASS_ONE_HELDOUT_RAW_AND_NATIVE_CHAIN',runs=len(runs),all_flow_records=total,
        measured_control_records=controls,native_release_rows=count,native_fifo_rows=native['rows'],
        manifest_sha256=sha(p/'manifest.json'),native_audit_sha256=sha(nq/'audit.json'),
        scope='one sealed-prefix implementation-artifact validation; not novelty/expert/physical-radio certification')
    (out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--native-queue',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.native_queue,a.out)
