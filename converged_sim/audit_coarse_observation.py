"""Raw record and pairing audit; descriptive summaries, no novelty verdict."""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import statistics

from .coarse_observation import sha,trace
from .coarse_fifo_shadow import shadow
from .traffic_contract import emissions


def audit(folder,out):
    folder=Path(folder);out=Path(out)
    if out.exists():raise FileExistsError(out)
    frozen=json.loads((folder/'frozen.json').read_text());cfg=frozen['config']
    manifest=json.loads((folder/'manifest.json').read_text())
    root=Path(__file__).parents[1]
    if manifest['frozen_sha256']!=sha(folder/'frozen.json'):raise ValueError('freeze changed')
    if manifest['runs_sha256']!=sha(folder/'runs.csv'):raise ValueError('summary changed')
    if any(sha(root/name)!=v for name,v in frozen['model_sha256'].items()):raise ValueError('model/protocol changed')
    with (folder/'runs.csv').open() as h:runs=list(csv.DictReader(h))
    expected={(str(rho),str(seed),p,q) for rho in cfg['loads'] for seed in cfg['seeds'] for p in cfg['profiles'] for q in cfg['queues']}
    keys=[tuple(r[k] for k in ('rho','seed','profile','queue')) for r in runs]
    if len(set(keys))!=len(keys) or set(keys)!=expected:raise ValueError('configuration coverage')
    receipts={r['file']:r for r in manifest['receipts']};rowcount=0;pairings={};control_records=0
    for r in runs:
        name=r['packet_file'];receipt=receipts[name]
        if receipt['sha256']!=sha(folder/name):raise ValueError('raw hash changed')
        with gzip.open(folder/name,'rt') as h:rows=list(csv.DictReader(h))
        if len(rows)!=receipt['rows']:raise ValueError('rowcount')
        rowcount+=len(rows)
        ids=[(x['flow'],x['id']) for x in rows]
        if len(set(ids))!=len(ids):raise ValueError('duplicate packet')
        cohort=tuple((x['flow'],x['id'],x['arrival_T']) for x in rows)
        key=(r['rho'],r['seed']);signature=(r['arrival_sha256'],cohort)
        if key in pairings and pairings[key]!=signature:raise ValueError('arrival pairing')
        pairings[key]=signature
        service=trace(r['profile'],int(r['seed']),cfg)
        if service.digest!=r['service_sha256']:raise ValueError('trace reconstruction')
        if any(abs(service.integrate(t,t+50)-50)>1e-8 for t in range(0,int(service.observation_duration),50)):raise ValueError('bin budgets')
        if r['queue']=='fifo':
            events=[(round((e.generated_s-1)/cfg['T'],10),e.flow,e.packet_id,{1:.01,2:.04,3:.1}[e.flow])
                    for e in emissions(float(r['rho']),cfg['pmr'],cfg['bulk_cycle'],cfg['warm'],
                    cfg['measured']+cfg['guard'],cfg['phase_seed'],int(r['seed']))]
            alt=shadow(events,service.starts,service.ends,service.rates,cfg['capacity'],cfg['warm'],cfg['warm']+cfg['measured'])
            if len(alt)!=len(rows):raise ValueError('shadow cohort')
            for x in rows:
                status,at=alt[(int(x['flow']),int(x['id']))]
                if status!=x['status'] or (status=='completed' and abs(at-float(x['finish_T']))>1e-7):raise ValueError('cumulative-coordinate cross-check')
        joint=True
        for flow,label in (('1','control'),('2','sensor'),('3','bulk')):
            records=[x for x in rows if x['flow']==flow]
            completed=[x for x in records if x['status']=='completed']
            for x in records:
                if x['status'] not in ('completed','dropped','unresolved'):raise ValueError('status')
                a=float(x['arrival_T'])
                if not cfg['warm']<=a<cfg['warm']+cfg['measured']:raise ValueError('measurement cohort')
                if x['status']=='completed':
                    f=float(x['finish_T']);d=float(x['delay_T'])
                    if f<a or not math.isclose(f-a,d,abs_tol=1e-9):raise ValueError('causality')
                    if int(x['after_live_guard'])!=int(f>service.observation_duration):raise ValueError('guard accounting')
                elif x['finish_T'] or x['delay_T']:raise ValueError('unfinished delay')
            delays=sorted(float(x['delay_T']) for x in completed)
            quantile=delays[math.ceil(len(delays)*.99)-1] if delays else math.inf
            miss=sum(x['status']!='completed' or float(x['delay_T'])>=cfg['deadline_T'] for x in records)/len(records)
            delivery=len(completed)/len(records)
            numeric={'count':len(records),'p99_T':quantile,'miss_ratio':miss,'delivery':delivery,
                     'drop_count':sum(x['status']=='dropped' for x in records),
                     'unresolved_count':sum(x['status']=='unresolved' for x in records),
                     'after_live_guard':sum(int(x['after_live_guard']) for x in records)}
            if any(not math.isclose(float(r[label+'_'+k]),v,abs_tol=1e-10,rel_tol=1e-10) for k,v in numeric.items()):raise ValueError('raw summary differs')
            if label=='control':
                if len(records)!=cfg['measured']:raise ValueError('control count')
                control_records+=len(records);joint=quantile<cfg['deadline_T'] and miss<.01
            if label=='bulk':joint=joint and delivery==1.
        if joint!=(r['joint_pass']=='True'):raise ValueError('joint decision')
        if float(r['max_waiting_work'])>cfg['capacity']+1e-9:raise ValueError('buffer capacity')
        print(f'audited {name}',flush=True)
    points=[];boundaries=[]
    for profile in cfg['profiles']:
        for queue in cfg['queues']:
            for rho in cfg['loads']:
                group=[r for r in runs if r['profile']==profile and r['queue']==queue and float(r['rho'])==rho]
                points.append(dict(profile=profile,queue=queue,rho=rho,n=len(group),
                    control_p99_median_T=statistics.median(float(r['control_p99_T']) for r in group),
                    control_p99_min_T=min(float(r['control_p99_T']) for r in group),
                    control_p99_max_T=max(float(r['control_p99_T']) for r in group),
                    control_miss_median=statistics.median(float(r['control_miss_ratio']) for r in group),
                    bulk_delivery_min=min(float(r['bulk_delivery']) for r in group),
                    joint_pass_count=sum(r['joint_pass']=='True' for r in group)))
            for seed in cfg['seeds']:
                boundary=None;failed=None
                for rho in cfg['loads']:
                    r=next(r for r in runs if r['profile']==profile and r['queue']==queue and float(r['rho'])==rho and int(r['seed'])==seed)
                    if r['joint_pass']!='True':failed=rho;break
                    boundary=rho
                boundaries.append(dict(profile=profile,queue=queue,seed=seed,highest_contiguous_tested_pass=boundary,first_tested_failure=failed))
    out.mkdir(parents=True)
    for name,rows in (('points.csv',points),('boundaries.csv',boundaries)):
        with (out/name).open('w',newline='') as h:
            w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    report=dict(status='PASS',scope='synthetic raw reconstruction, not independent implementation',
                runs=len(runs),all_flow_records=rowcount,control_records=control_records,arrival_pair_groups=len(pairings),
                fifo_shadow_runs=sum(r['queue']=='fifo' for r in runs),
                manifest_sha256=sha(folder/'manifest.json'),points_sha256=sha(out/'points.csv'),
                boundaries_sha256=sha(out/'boundaries.csv'))
    (out/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();audit(a.input,a.out)
