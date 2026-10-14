# SPDX-License-Identifier: GPL-3.0-only
"""Development replay of verified release model + modeled heavy queue semantics."""
import argparse
from collections import deque
import csv
import gzip
import io
import itertools
import json
import math
from pathlib import Path
import subprocess
import zipfile
from .coarse_observation import sha,digest
from .cellreplay_release_model import ReleasePlanner
from .cellreplay_release_probe import load
from .cellreplay_development_screen import quantile

CONFIG=dict(group='tmobile/weak-signal',direction='up',end_ms=208000,warm_ms=8000,
    loads=[.2,.6,.9],pmrs=[1,3],cycle_ms=300,timer_ms=0,capacity_packets=16,
    policies=['fifo','priority'],accounting=['original','accepted'],deadlines_ms=[10,20,40])

def arrivals(bulk_count,pmr,cfg):
    end=cfg['end_ms']; cycle=cfg['cycle_ms']
    events=[(t,1,t//20,150) for t in range(0,end,20)]
    events.extend((t,2,t//200,256) for t in range(0,end,200))
    pid=0; counts=[]
    for at in range(0,end,cycle):
        stop=min(at+cycle,end)
        n=bulk_count*stop//end-bulk_count*at//end
        counts.append(n)
        for k in range(n):
            time=at+k*(stop-at)//(pmr*n)
            events.append((time,3,pid,1400));pid+=1
    assert pid==bulk_count
    return sorted(events),counts

def simulate(planned,pdos,policy,accounting,capacity,end):
    if policy not in ('fifo','priority') or accounting not in ('original','accepted'):
        raise ValueError('variant')
    rows=[dict(r,status='unfinished',finish_ms='',delay_ms='',actual_bypass=False) for r in planned]
    waiting=deque(); queues={f:deque() for f in (1,2,3)}
    waiting_n=0; transit=None; remaining=0; counter=0; position=0; maximum=0
    def flush(completed,t):
        nonlocal counter
        for pid in completed:
            row=rows[pid];row.update(status='completed',finish_ms=t,delay_ms=t-row['arrival_ms'])
            assert counter>0;counter-=1
    def deliver(budget,t):
        nonlocal transit,remaining,waiting_n
        completed=[]
        while budget>0:
            if transit is None:
                if not waiting_n: break
                if policy=='fifo':transit=waiting.popleft()
                else:transit=next(queues[f].popleft() for f in (1,2,3) if queues[f])
                waiting_n-=1;remaining=rows[transit]['content_bytes']
            amount=min(budget,remaining);budget-=amount;remaining-=amount
            if not remaining:completed.append(transit);transit=None
        return completed
    for t,batch in itertools.groupby(enumerate(rows),key=lambda pair:pair[1]['release_ms']):
        if t>end: break
        while position<len(pdos) and pdos[position][0]<t:
            st,n=pdos[position];flush(deliver(1400*n,st),st);position+=1
        held=[]
        if position<len(pdos) and pdos[position][0]==t:
            st,n=pdos[position];held=deliver(1400*n,t);position+=1
        for pid,row in batch:
            if row['planned_light_bypass'] and counter==0:
                row.update(status='completed',finish_ms=t,delay_ms=t-row['arrival_ms'],actual_bypass=True)
            else:
                if waiting_n<capacity:
                    if policy=='fifo':waiting.append(pid)
                    else:queues[row['flow']].append(pid)
                    waiting_n+=1;maximum=max(maximum,waiting_n);counter+=1
                else:
                    row.update(status='dropped')
                    if accounting=='original':counter+=1
        flush(held,t)
    while position<len(pdos) and pdos[position][0]<=end:
        st,n=pdos[position];flush(deliver(1400*n,st),st);position+=1
    resident=waiting_n+int(transit is not None)
    drops=sum(r['status']=='dropped' for r in rows)
    assert counter-resident==(drops if accounting=='original' else 0)
    return rows,dict(max_waiting_packets=maximum,final_counter=counter,final_resident=resident)

def summarize(rows,warm,deadlines):
    result={}
    for flow,label in ((1,'control'),(2,'sensor'),(3,'bulk')):
        subset=[r for r in rows if r['flow']==flow and r['arrival_ms']>=warm]
        completed=[r for r in subset if r['status']=='completed']
        ds=[r['delay_ms'] for r in completed]
        result[label+'_count']=len(subset)
        result[label+'_p99_ms']=quantile(ds,.99) if ds else None
        result[label+'_drops']=sum(r['status']=='dropped' for r in subset)
        result[label+'_unfinished']=sum(r['status']=='unfinished' for r in subset)
        result[label+'_delivery']=len(completed)/len(subset) if subset else None
        for deadline in deadlines:
            miss=sum(r['status']!='completed' or r['delay_ms']>=deadline for r in subset)
            result[f'{label}_miss_{deadline}ms']=miss/len(subset) if subset else None
    for deadline in deadlines:
        p99=result['control_p99_ms']
        result[f'control_pass_{deadline}ms']=p99 is not None and p99<deadline and result[f'control_miss_{deadline}ms']<.01
    return result

def save_rows(path,rows):
    with path.open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as gz:
            with io.TextIOWrapper(gz,newline='') as h:
                w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def run(out,cfg=CONFIG):
    root=Path(__file__).resolve().parents[1];out=Path(out)
    if out.exists():raise FileExistsError(out)
    heavy=root/'results/cellreplay_heavy_v25'; native=root/'results/native_release_v23b'
    screen=root/'results/cellreplay_development_v21/development.json'
    archive=root/'results/cellreplay_source_v20/traces/cellular-traces.zip'
    split=root/'results/cellreplay_split_v20/split.json'
    sp=json.loads(split.read_text());hs=json.loads((heavy/'summary.json').read_text())
    ha=json.loads((heavy/'audit.json').read_text());na=json.loads((native/'audit.json').read_text())
    if sha(archive)!=sp['archive_sha256'] or sha(heavy/'summary.json')!=ha['summary_sha256']:
        raise ValueError('input receipt mismatch')
    if na['status']!='PASS_SELECTED_NATIVE_METHODS':raise ValueError('native release gate')
    if sha(native/'native-fixture.exe')!=na['executable_sha256']:
        raise ValueError('native executable mismatch')
    member=f"{cfg['group']}/{cfg['direction']}-heavy-pdo"
    assert next(m['role'] for m in sp['members'] if m['member_path']==member)=='development'
    prefix=heavy/hs[member]['prefix_file'];assert sha(prefix)==hs[member]['prefix_sha256']
    with gzip.open(prefix,'rt') as h:pdos=[(int(r['timestamp_ms']),int(r['opportunities'])) for r in csv.DictReader(h)]
    budget=sum(n for t,n in pdos if t<=cfg['end_ms'])*1400
    out.mkdir(parents=True)
    frozen=dict(config=cfg,archive_sha256=sha(archive),split_sha256=sha(split),prefix_sha256=sha(prefix),
        native_audit_sha256=sha(native/'audit.json'),screen_sha256=sha(screen),
        model_sha256={p:sha(root/p) for p in ('converged_sim/cellreplay_mixed.py',
            'converged_sim/cellreplay_release_model.py','q2_upgrade/MIXED_REPLAY_PROTOCOL_V27.md')},
        scope='development translated queue replay; every mixed release checked natively',
        native_queue_equivalence=False,reserved_members_opened=0)
    (out/'frozen.json').write_text(json.dumps(frozen,indent=2))
    results=[];receipts=[];native_receipts=[]
    screened={r['member_path']:r for r in json.loads(screen.read_text())}
    with zipfile.ZipFile(archive) as z:
        name=f"{cfg['group']}/{cfg['direction']}-delay-light-pdo";off=f"{cfg['group']}/latency-offset-{cfg['direction']}"
        records,lr=load(z,name,'light');offsets,orr=load(z,off,'offset')
        assert lr==screened[name]['member_receipt'] and orr==screened[off]['member_receipt']
        (out/'light.txt').write_bytes(z.read(name));(out/'offset.txt').write_bytes(z.read(off))
    critical_bytes=(cfg['end_ms']//20)*150+(cfg['end_ms']//200)*256
    for rho in cfg['loads']:
        bulk_count=max(0,math.floor((rho*budget-critical_bytes)/1400))
        expected_cycles=None
        for pmr in cfg['pmrs']:
            events,cycles=arrivals(bulk_count,pmr,cfg)
            if expected_cycles is None:expected_cycles=cycles
            else:assert cycles==expected_cycles
            planner=ReleasePlanner(records,offsets,cfg['timer_ms']);planned=[]
            key=f'{rho:g}-{pmr}'
            event_file=out/f'{key}-events.txt'
            with event_file.open('w') as h:
                for pid,(t,f,local,size) in enumerate(events):
                    h.write(f'{t} {size}\n')
                    planned.append(dict(packet_id=pid,flow=f,flow_id=local,**planner.plan(t,size)))
            planned_path=out/f'{key}-planned.csv.gz';save_rows(planned_path,planned)
            native_path=out/f'{key}-native.csv'
            command=[str((native/'native-fixture.exe').resolve()),str((out/'light.txt').resolve()),
                str((out/'offset.txt').resolve()),'150',str(cfg['timer_ms']),str(native_path.resolve()),str(event_file.resolve())]
            completed=subprocess.run(command,capture_output=True,text=True,timeout=180,check=True)
            comparisons=0
            with native_path.open(newline='') as h:
                for r in csv.DictReader(h):
                    pid=int(r['packet_id']);expect=planned[pid]
                    for field in expect:
                        if field not in r:continue
                        actual=r[field];value=expect[field]
                        if actual!=str(value):raise AssertionError((key,pid,field,actual,value))
                    comparisons+=1
            assert comparisons==len(planned)
            native_receipts.append(dict(config=key,rows=comparisons,native_file=native_path.name,
                native_sha256=sha(native_path),planned_file=planned_path.name,planned_sha256=sha(planned_path),
                events_file=event_file.name,events_sha256=sha(event_file),cycle_counts=cycles))
            for policy in cfg['policies']:
                for accounting in cfg['accounting']:
                    rows,diagnostic=simulate(planned,pdos,policy,accounting,cfg['capacity_packets'],cfg['end_ms'])
                    metrics=summarize(rows,cfg['warm_ms'],cfg['deadlines_ms'])
                    assert metrics['control_count']==10000
                    filename=f'{key}-{policy}-{accounting}-packets.csv.gz';save_rows(out/filename,rows)
                    summary=dict(rho_target=rho,rho_actual=(critical_bytes+1400*bulk_count)/budget,pmr=pmr,
                        policy=policy,accounting=accounting,source_arrival_sha256=digest(events),
                        planned_sha256=sha(planned_path),service_sha256=sha(prefix),packet_file=filename,
                        **diagnostic,**metrics)
                    results.append(summary);receipts.append(dict(file=filename,sha256=sha(out/filename),rows=len(rows)))
                    print(f'completed {key}/{policy}/{accounting}',flush=True)
    with (out/'runs.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    (out/'manifest.json').write_text(json.dumps(dict(status='COMPLETED_DEVELOPMENT_REPLAY_NOT_NOVELTY',
        frozen_sha256=sha(out/'frozen.json'),runs_sha256=sha(out/'runs.csv'),receipts=receipts,
        native_release_receipts=native_receipts,reserved_members_opened=0),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);run(p.parse_args().out)
