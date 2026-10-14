# SPDX-License-Identifier: GPL-3.0-only
"""Established priority/push-out component baseline, not new pFabric transport."""
import argparse
from collections import deque
import csv
import gzip
import itertools
import json
from pathlib import Path
from .coarse_observation import sha
from .audit_cellreplay_mixed import read_rows
from .cellreplay_mixed import save_rows,summarize

def simulate(planned,pdos,capacity,end):
    rows=[dict(r,status='unfinished',finish_ms='',delay_ms='',actual_bypass=False,evicted_by='') for r in planned]
    queues={f:deque() for f in (1,2,3)};waiting=0;counter=0;transit=None;remaining=0
    position=0;maximum=0;evictions=0
    def flush(completed,t):
        nonlocal counter
        for pid in completed:
            row=rows[pid];row.update(status='completed',finish_ms=t,delay_ms=t-row['arrival_ms'])
            assert counter>0;counter-=1
    def deliver(budget):
        nonlocal transit,remaining,waiting
        completed=[]
        while budget>0:
            if transit is None:
                if not waiting:break
                transit=next(queues[f].popleft() for f in (1,2,3) if queues[f]);waiting-=1
                remaining=rows[transit]['content_bytes']
            amount=min(budget,remaining);budget-=amount;remaining-=amount
            if not remaining:completed.append(transit);transit=None
        return completed
    for t,batch in itertools.groupby(enumerate(rows),key=lambda pair:pair[1]['release_ms']):
        if t>end:break
        while position<len(pdos) and pdos[position][0]<t:
            st,n=pdos[position];flush(deliver(1400*n),st);position+=1
        held=[]
        if position<len(pdos) and pdos[position][0]==t:
            st,n=pdos[position];held=deliver(1400*n);position+=1
        for pid,row in batch:
            if row['planned_light_bypass'] and counter==0:
                row.update(status='completed',finish_ms=t,delay_ms=t-row['arrival_ms'],actual_bypass=True)
                continue
            if waiting==capacity:
                lower=[f for f in (3,2) if f>row['flow'] and queues[f]]
                if lower:
                    victim=queues[lower[0]].pop();rows[victim].update(status='dropped',evicted_by=pid)
                    waiting-=1;counter-=1;evictions+=1
            if waiting<capacity:
                queues[row['flow']].append(pid);waiting+=1;counter+=1;maximum=max(maximum,waiting)
            else:row.update(status='dropped')
        flush(held,t)
    while position<len(pdos) and pdos[position][0]<=end:
        st,n=pdos[position];flush(deliver(1400*n),st);position+=1
    resident=waiting+int(transit is not None)
    assert counter==resident
    return rows,dict(max_waiting_packets=maximum,final_counter=counter,final_resident=resident,evictions=evictions)

def run(input_path,out):
    p=Path(input_path);out=Path(out);root=Path(__file__).resolve().parents[1]
    if out.exists():raise FileExistsError(out)
    manifest=json.loads((p/'manifest.json').read_text());frozen=json.loads((p/'frozen.json').read_text())
    assert sha(p/'frozen.json')==manifest['frozen_sha256'] and sha(p/'runs.csv')==manifest['runs_sha256']
    with (p/'runs.csv').open(newline='') as h:baselines=list(csv.DictReader(h))
    cfg=frozen['config'];hs=json.loads((root/'results/cellreplay_heavy_v25/summary.json').read_text())
    member=f"{cfg['group']}/{cfg['direction']}-heavy-pdo";prefix=root/'results/cellreplay_heavy_v25'/hs[member]['prefix_file']
    assert sha(prefix)==frozen['prefix_sha256']
    with gzip.open(prefix,'rt') as h:pdos=[(int(r['timestamp_ms']),int(r['opportunities'])) for r in csv.DictReader(h)]
    out.mkdir(parents=True)
    freeze=dict(config=cfg,input_manifest_sha256=sha(p/'manifest.json'),service_sha256=sha(prefix),
        model_sha256={n:sha(root/n) for n in ('converged_sim/cellreplay_pushout.py',
            'converged_sim/cellreplay_mixed.py','q2_upgrade/PUSHOUT_PROTOCOL_V29.md')},
        scope='existing class-priority push-out component; no new algorithm',reserved_members_opened=0)
    (out/'frozen.json').write_text(json.dumps(freeze,indent=2));results=[];receipts=[]
    for r in manifest['native_release_receipts']:
        key=r['config'];path=p/r['planned_file'];assert sha(path)==r['planned_sha256']
        planned=list(read_rows(path));rows,diag=simulate(planned,pdos,cfg['capacity_packets'],cfg['end_ms'])
        baseline=next(b for b in baselines if f"{float(b['rho_target']):g}-{b['pmr']}"==key and b['policy']=='priority' and b['accounting']=='accepted')
        metrics=summarize(rows,cfg['warm_ms'],cfg['deadlines_ms']);assert metrics['control_count']==10000
        filename=f'{key}-pushout-packets.csv.gz';save_rows(out/filename,rows)
        summary=dict(rho_target=baseline['rho_target'],rho_actual=baseline['rho_actual'],pmr=baseline['pmr'],
            policy='priority_pushout',source_arrival_sha256=baseline['source_arrival_sha256'],
            planned_sha256=r['planned_sha256'],service_sha256=sha(prefix),packet_file=filename,**diag,**metrics)
        results.append(summary);receipts.append(dict(file=filename,rows=len(rows),sha256=sha(out/filename),planned_file=r['planned_file']))
        print(f'completed existing push-out {key}',flush=True)
    with (out/'runs.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    (out/'manifest.json').write_text(json.dumps(dict(status='COMPLETED_EXISTING_COMPONENT_BASELINE',
        frozen_sha256=sha(out/'frozen.json'),runs_sha256=sha(out/'runs.csv'),receipts=receipts),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.out)
