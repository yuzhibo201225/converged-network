"""Exploratory integrated-service diagnostic; no measured wireless claims."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import random
from collections import deque

from .timescale_model import _ServiceTrace
from .traffic_contract import emissions

CONFIG = dict(loads=[.2,.4,.6,.7,.8,.85,.9,.95], seeds=list(range(1,6)),
              profiles=['constant','fine','coarse'], queues=['fifo','priority'],
              warm=400, measured=10000, guard=400, horizon=11000,
              phase_seed=20261020, capacity=16, pmr=3, bulk_cycle=8,
              T=.02, nominal_bps=6000000, deadline_T=1)
FIELDS=['flow','id','arrival_T','finish_T','delay_T','status','after_live_guard']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def trace(profile,seed,cfg):
    end=cfg['warm']+cfg['measured']+cfg['guard']; horizon=cfg['horizon']
    if end%50 or horizon<=end: raise ValueError('complete bins and tail required')
    starts=[]; rates=[]
    if profile=='constant': starts=[0.];rates=[1.]
    elif profile in ('fine','coarse'):
        width=1 if profile=='fine' else 50
        rng=random.Random(f'coarse-observation-v18:{profile}:{seed}')
        for at in range(0,end,width):
            high_first=rng.getrandbits(1)
            starts.extend([float(at),at+width/2])
            rates.extend([1.3,.7] if high_first else [.7,1.3])
        starts.append(float(end));rates.append(1.)
    else: raise ValueError('unknown profile')
    ends=starts[1:]+[float(horizon)]
    return _ServiceTrace(starts,ends,rates,end,horizon,False,0,.7,1.3,
                         digest([starts,rates]),'', '')


def simulate(events,service,queue,capacity,begin,end,live_end):
    """Input events=(arrival,flow,id,work); no source/transport/access links."""
    if queue not in ('fifo','priority') or capacity<=0: raise ValueError('queue')
    pending={k:deque() for k in (1,2,3)}; fifo=deque(); waiting=0.; max_waiting=0.
    rows=[]; in_service=None; finish=math.inf; pos=0
    events=sorted(events,key=lambda p:(p[0],p[1],p[2]))
    def receive(p,at,status):
        arrival,flow,pid,work=p
        if begin<=arrival<end:
            rows.append(dict(flow=flow,id=pid,arrival_T=arrival,
                             finish_T=at if status=='completed' else '',
                             delay_T=at-arrival if status=='completed' else '',
                             status=status,after_live_guard=int(status=='completed' and at>live_end)))
    def pop():
        if queue=='fifo': return fifo.popleft() if fifo else None
        for k in (1,2,3):
            if pending[k]: return pending[k].popleft()
        return None
    while pos<len(events) or in_service is not None:
        arrival=events[pos][0] if pos<len(events) else math.inf
        if in_service is not None and finish<=arrival:
            if not math.isfinite(finish):break
            receive(in_service,finish,'completed');p=pop()
            if p is None:in_service=None;finish=math.inf
            else:waiting=max(0.,waiting-p[3]);in_service=p;finish=service.finish_time(finish,p[3])
        else:
            p=events[pos];pos+=1
            if in_service is None:in_service=p;finish=service.finish_time(p[0],p[3])
            elif waiting+p[3]>capacity+1e-10:receive(p,math.inf,'dropped')
            else:
                if queue=='fifo':fifo.append(p)
                else:pending[p[1]].append(p)
                waiting+=p[3];max_waiting=max(max_waiting,waiting)
    if in_service is not None:receive(in_service,math.inf,'unresolved')
    for p in fifo:receive(p,math.inf,'unresolved')
    for q in pending.values():
        for p in q:receive(p,math.inf,'unresolved')
    rows.sort(key=lambda r:(r['flow'],r['id']))
    return rows,max_waiting


def summarize(rows,deadline):
    result={}
    for flow,label in ((1,'control'),(2,'sensor'),(3,'bulk')):
        subset=[r for r in rows if r['flow']==flow]
        delays=sorted(r['delay_T'] for r in subset if r['status']=='completed')
        result[label+'_count']=len(subset)
        result[label+'_p99_T']=delays[math.ceil(.99*len(delays))-1] if delays else math.inf
        result[label+'_delivery']=len(delays)/len(subset) if subset else 0.
        result[label+'_drop_count']=sum(r['status']=='dropped' for r in subset)
        result[label+'_unresolved_count']=sum(r['status']=='unresolved' for r in subset)
        result[label+'_after_live_guard']=sum(r['after_live_guard'] for r in subset)
        result[label+'_miss_ratio']=sum(r['status']!='completed' or r['delay_T']>=deadline for r in subset)/len(subset) if subset else 1.
    result['joint_pass']=result['control_p99_T']<deadline and result['control_miss_ratio']<.01 and result['bulk_delivery']==1.
    return result


def run(out,cfg=CONFIG):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True)
    root=Path(__file__).parents[1]
    models=['converged_sim/coarse_observation.py','converged_sim/timescale_model.py',
            'converged_sim/traffic_contract.py','converged_sim/scenario_predictor.py',
            'q2_upgrade/COARSE_OBSERVATION_PROTOCOL_V18.md']
    frozen={'config':cfg,'model_sha256':{p:sha(root/p) for p in models},
            'status':'FROZEN_BEFORE_FIRST_OUTCOME','scope':'synthetic exploratory'}
    (out/'frozen.json').write_text(json.dumps(frozen,indent=2),encoding='utf8')
    summaries=[];receipts=[]
    for rho in cfg['loads']:
        for seed in cfg['seeds']:
            all_events=[((e.generated_s-1)/cfg['T'],e.flow,e.packet_id,
                         {1:.01,2:.04,3:.1}[e.flow]) for e in emissions(
                rho,cfg['pmr'],cfg['bulk_cycle'],cfg['warm'],cfg['measured']+cfg['guard'],cfg['phase_seed'],seed)]
            # Remove insignificant conversion roundoff at periodic control boundaries.
            all_events=[(round(t,10),f,i,w) for t,f,i,w in all_events]
            arrivals_sha=digest(all_events)
            for profile in cfg['profiles']:
                service=trace(profile,seed,cfg)
                bins=[service.integrate(t,t+50) for t in range(0,int(service.observation_duration),50)]
                if any(abs(v-50)>1e-8 for v in bins):raise ValueError('coarse budgets')
                for queue in cfg['queues']:
                    rows,max_wait=simulate(all_events,service,queue,cfg['capacity'],cfg['warm'],
                                          cfg['warm']+cfg['measured'],service.observation_duration)
                    if sum(r['flow']==1 for r in rows)!=cfg['measured']:raise ValueError('control cohort')
                    name=f'{len(summaries)}-packets.csv.gz'
                    with gzip.open(out/name,'wt',newline='',encoding='utf8') as h:
                        w=csv.DictWriter(h,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
                    summary=dict(rho=rho,seed=seed,profile=profile,queue=queue,
                                 arrival_sha256=arrivals_sha,service_sha256=service.digest,
                                 bin_budget_max_error=max(abs(v-50) for v in bins),max_waiting_work=max_wait,
                                 packet_file=name,**summarize(rows,cfg['deadline_T']))
                    summaries.append(summary);receipts.append(dict(file=name,sha256=sha(out/name),rows=len(rows)))
        print(f'completed rho={rho:g}: {len(summaries)} runs',flush=True)
    with (out/'runs.csv').open('w',newline='',encoding='utf8') as h:
        w=csv.DictWriter(h,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    (out/'manifest.json').write_text(json.dumps(dict(frozen_sha256=sha(out/'frozen.json'),
        runs_sha256=sha(out/'runs.csv'),receipts=receipts),indent=2),encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True)
    run(p.parse_args().out)
