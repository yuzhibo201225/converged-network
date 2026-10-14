"""Saved raw mixed-replay audit; no independent implementation claim."""
import argparse
from collections import Counter,defaultdict
import csv
import gzip
import json
from pathlib import Path
from .coarse_observation import sha,digest
from .cellreplay_mixed import summarize

def read_rows(path):
    with gzip.open(path,'rt',newline='') as h:
        for r in csv.DictReader(h):
            for key in ('packet_id','flow','flow_id','arrival_ms','content_bytes','raw_release_ms',
                        'release_ms','planned_delay_ms','base_delay_ms'):
                r[key]=int(r[key])
            for key in ('light_reset','planned_light_bypass','release_clamped','actual_bypass'):
                if key in r:
                    assert r[key] in ('True','False');r[key]=r[key]=='True'
            for key in ('finish_ms','delay_ms'):
                if key in r and r[key]!='':r[key]=int(r[key])
            yield r

def run(input_path,out):
    p=Path(input_path);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((p/'manifest.json').read_text());freeze=json.loads((p/'frozen.json').read_text())
    assert sha(p/'frozen.json')==m['frozen_sha256'] and sha(p/'runs.csv')==m['runs_sha256']
    cfg=freeze['config'];root=Path(__file__).resolve().parents[1]
    for name,value in freeze['model_sha256'].items():assert sha(root/name)==value
    receipts={r['file']:r for r in m['receipts']}
    with (p/'runs.csv').open(newline='') as h:summaries=list(csv.DictReader(h))
    total=0;control=0;plan_rows=0;pairings=defaultdict(list);cycles_by_load={}
    for r in m['native_release_receipts']:
        planned_path=p/r['planned_file'];native_path=p/r['native_file']
        assert sha(planned_path)==r['planned_sha256'] and sha(native_path)==r['native_sha256']
        assert sha(p/r['events_file'])==r['events_sha256']
        planned=list(read_rows(planned_path));plan_rows+=len(planned)
        with native_path.open(newline='') as h:
            count=0
            for count,native in enumerate(csv.DictReader(h),1):
                expect=planned[count-1];assert int(native['packet_id'])==count-1
                for key,value in expect.items():
                    if key in native:assert native[key]==str(value)
        assert count==len(planned)==r['rows']
        cycle_counts=Counter(row['arrival_ms']//cfg['cycle_ms'] for row in planned if row['flow']==3)
        assert [cycle_counts[i] for i in range(len(r['cycle_counts']))]==r['cycle_counts']
        load=r['config'].split('-')[0]
        if load in cycles_by_load:assert cycles_by_load[load]==r['cycle_counts']
        else:cycles_by_load[load]=r['cycle_counts']
    for s in summaries:
        path=p/s['packet_file'];receipt=receipts[path.name];assert sha(path)==receipt['sha256']
        rows=list(read_rows(path));assert len(rows)==receipt['rows']
        total+=len(rows)
        source_events=[];planned_fields=[]
        for pid,r in enumerate(rows):
            assert pid==r['packet_id']
            assert r['planned_delay_ms']==r['release_ms']-r['arrival_ms']
            assert r['release_ms']>=r['arrival_ms']
            assert r['status'] in ('completed','dropped','unfinished')
            if r['status']=='completed':
                assert r['finish_ms']>=r['release_ms'] and r['finish_ms']<=cfg['end_ms']
                assert r['delay_ms']==r['finish_ms']-r['arrival_ms']
                if r['actual_bypass']:assert r['finish_ms']==r['release_ms']
            else:assert r['finish_ms']==r['delay_ms']==''
            if r['flow']==1:assert r['arrival_ms']==20*r['flow_id'] and r['content_bytes']==150
            if r['flow']==2:assert r['arrival_ms']==200*r['flow_id'] and r['content_bytes']==256
            if r['flow']==3:assert r['content_bytes']==1400
            source_events.append((r['arrival_ms'],r['flow'],r['flow_id'],r['content_bytes']))
            planned_fields.append({k:v for k,v in r.items() if k not in ('status','finish_ms','delay_ms','actual_bypass')})
        assert digest(source_events)==s['source_arrival_sha256']
        metrics=summarize(rows,cfg['warm_ms'],cfg['deadlines_ms'])
        for key,value in metrics.items():assert s[key]==str(value) if value is not None else s[key]==''
        control+=metrics['control_count'];assert metrics['control_count']==10000
        key=(s['rho_target'],s['pmr'])
        pairings[key].append((s['source_arrival_sha256'],s['planned_sha256'],s['service_sha256'],digest(planned_fields)))
        drops=sum(r['status']=='dropped' for r in rows)
        assert int(s['final_counter'])-int(s['final_resident'])==(drops if s['accounting']=='original' else 0)
    for key,paired in pairings.items():assert len(paired)==4 and len(set(paired))==1
    by_load=defaultdict(list)
    for s in summaries:by_load[s['rho_target']].append(s)
    for load,group in by_load.items():
        assert len({s['rho_actual'] for s in group})==1 and len({s['service_sha256'] for s in group})==1
    out.mkdir(parents=True)
    audit=dict(status='PASS_SAVED_MIXED_RAW_RECONSTRUCTION',runs=len(summaries),
        all_flow_records=total,measured_control_records=control,native_mixed_release_rows=plan_rows,
        paired_policy_groups=len(pairings),volume_paired_loads=len(by_load),
        manifest_sha256=sha(p/'manifest.json'),scope='raw consistency and native release parity; not independent queue/radio validation')
    (out/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.out)
