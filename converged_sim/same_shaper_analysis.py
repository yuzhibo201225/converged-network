"""Pair actual source releases before attributing effects to queue scheduling."""
import argparse
import csv
import hashlib
import json
import statistics
from collections import defaultdict
from itertools import zip_longest
from pathlib import Path
from ns3_validation.renewal_cli import digest,dump

SOURCE_FIELDS=('flow','id','measured','generated_s','released_s','source_drop','source_send_ok','source_wait_T')


def source_pair(left,right):
    signature=hashlib.sha256();count=0
    with Path(left).open() as a,Path(right).open() as b:
        for x,y in zip_longest(csv.DictReader(a),csv.DictReader(b)):
            if x is None or y is None:raise ValueError('full source-cohort lengths differ')
            key=tuple(x[k] for k in SOURCE_FIELDS)
            if key!=tuple(y[k] for k in SOURCE_FIELDS):raise ValueError('actual source release/drop/send inputs differ')
            signature.update(('|'.join(key)+'\n').encode());count+=1
    return count,signature.hexdigest()


def read_profile(raw,analysis):
    raw=Path(raw);analysis=Path(analysis);m=json.loads((raw/'manifest.json').read_text());a=json.loads((analysis/'audit.json').read_text())
    if a['status']!='PASS' or digest(raw/'manifest.json')!=a['manifest_sha256'] or digest(analysis/'runs.csv')!=a['runs_sha256']:
        raise ValueError('checked profile table required')
    child=Path(a['child_analysis'])
    if digest(child/'audit.json')!=a['child_audit_sha256'] or digest(child/'runs.csv')!=a['child_runs_sha256']:raise ValueError('child audit changed')
    with (analysis/'runs.csv').open() as h:rows=list(csv.DictReader(h))
    return m,a,rows


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:groups[(float(r['rho']),float(r['tauS']))].append(r)
    points=[]
    for (rho,ts),cohort in sorted(groups.items()):
        if len(cohort)!=70 or {int(r['run']) for r in cohort}!=set(range(1,71)):raise ValueError('70 complete same-input pairs required')
        p=dict(rho=rho,tauS=ts,n=70)
        for policy in ('fifo','priority'):
            p[policy+'_control_successes']=sum(r[policy+'_control_pass'] for r in cohort)
            p[policy+'_joint_successes']=sum(r[policy+'_joint_pass'] for r in cohort)
            for name in ('control_p99_T','bulk_p99_T','control_miss_ratio','bulk_delivery','source_max_work'):
                values=[float(r[policy+'_'+name]) for r in cohort]
                p[policy+'_'+name+'_median']=statistics.median(values)
                p[policy+'_'+name+'_min']=min(values);p[policy+'_'+name+'_max']=max(values)
        for name in ('control_delta','bulk_delta'):
            values=[r[name] for r in cohort]
            p[name+'_median']=statistics.median(values);p[name+'_min']=min(values);p[name+'_max']=max(values)
            p[name+'_negative_pairs']=sum(v<0 for v in values);p[name+'_positive_pairs']=sum(v>0 for v in values)
        points.append(p)
    return points


def run(baselines,baseline_audits,treatments,treatment_audits,freeze,out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    if not(len(baselines)==len(baseline_audits)==len(treatments)==len(treatment_audits)==2):raise ValueError('both paired profiles required')
    f=json.loads(Path(freeze).read_text());rows=[];provenance=[];new_count=0;paired_count=0
    if f['status']!='FROZEN':raise ValueError('frozen experiment required')
    for b,ba,t,ta in zip(map(Path,baselines),map(Path,baseline_audits),map(Path,treatments),map(Path,treatment_audits)):
        bm,bcheck,brows=read_profile(b,ba);tm,tcheck,trows=read_profile(t,ta)
        frozen=[r for r in f['profiles'] if r['tauS']==tm['spec']['tauS']]
        if len(frozen)!=1:raise ValueError('unique frozen profile')
        frozen=frozen[0]
        if digest(b/'manifest.json')!=frozen['baseline_manifest_sha256'] or digest(ba/'audit.json')!=frozen['baseline_audit_sha256'] or tm['config_sha256']!=frozen['new_config_sha256']:
            raise ValueError('frozen source/baseline/configuration mismatch')
        for m in (bm,tm):
            if m['source_sha256']!=frozen['source_sha256'] or m['executable_sha256']!=frozen['executable_sha256']:raise ValueError('engine/source mismatch')
        for k,v in bm['spec'].items():
            if k not in ('purpose','settings') and tm['spec'][k]!=v:raise ValueError('only scheduling may change')
        bc=json.loads((b/'coinflip'/'manifest.json').read_text());tc=json.loads((t/'coinflip'/'manifest.json').read_text())
        base={(float(r['rho']),int(r['run'])):(i,r) for i,r in enumerate(brows) if r['shape']=='feedback' and r['queue']=='fifo'}
        if len(base)!=len(trows):raise ValueError('complete paired grid')
        for i,r in enumerate(trows):
            bi,left=base[(float(r['rho']),int(r['run']))]
            if r['shape']!='feedback' or r['queue']!='priority':raise ValueError('shaped priority treatment required')
            for name in ('rho','R','tauB','tauS','bias','lag','capacity','seed','run','warm','measured','source_max_work','bulk_source_drop'):
                if float(left[name])!=float(r[name]):raise ValueError('source budget/configuration/occupancy mismatch')
            run_id=str(int(r['run']))
            if bc['trace_sha256'][run_id]!=tc['trace_sha256'][run_id]:raise ValueError('same-input service mismatch')
            for folder,child,j in ((b/'coinflip',bc,bi),(t/'coinflip',tc,i)):
                if any(digest(folder/f'{j}-{name}.csv')!=child['receipts'][str(j)][name] for name in ('packets','summary')):raise ValueError('raw pairing input changed')
                if digest(folder/'traces'/f'{run_id}.csv')!=child['trace_sha256'][run_id]:raise ValueError('paired trace changed')
            count,signature=source_pair(b/'coinflip'/f'{bi}-packets.csv',t/'coinflip'/f'{i}-packets.csv');paired_count+=count
            p=dict(rho=float(r['rho']),tauS=float(r['tauS']),run=int(r['run']),source_records=count,source_signature=signature)
            for policy,s in (('fifo',left),('priority',r)):
                cp=float(s['control_p99_T'])<1 and float(s['control_miss_ratio'])<.01
                p[policy+'_control_pass']=cp;p[policy+'_joint_pass']=cp and int(s['bulk_generated'])==int(s['bulk_delivered'])
                for name in ('control_p99_T','bulk_p99_T','control_miss_ratio','source_max_work'):p[policy+'_'+name]=float(s[name])
                p[policy+'_bulk_delivery']=int(s['bulk_delivered'])/int(s['bulk_generated'])
            p['control_delta']=p['priority_control_p99_T']-p['fifo_control_p99_T']
            p['bulk_delta']=p['priority_bulk_p99_T']-p['fifo_bulk_p99_T'];rows.append(p)
            if len(rows)%10==0:print(f'source-matched pairs {len(rows)}/280',flush=True)
        new_count+=tcheck['raw_all_flow_packets']
        provenance.append(dict(baseline=digest(b/'manifest.json'),treatment=digest(t/'manifest.json'),
                               baseline_audit=digest(ba/'audit.json'),treatment_audit=digest(ta/'audit.json')))
    points=summarize(rows)
    if len(points)!=4:raise ValueError('four complete pair cells')
    out.mkdir(parents=True)
    for name,data in (('pairs.csv',rows),('points.csv',points)):
        with (out/name).open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    result=dict(status='PASS',scope='post-V15 same-input source-shaper/scheduling contrast; no new independent service draws',
                pairs=len(rows),new_native_all_flow_records=new_count,paired_all_flow_input_records=paired_count,
                freeze_sha256=digest(freeze),provenance=provenance,code_sha256=digest(__file__),
                outputs_sha256={n:digest(out/n) for n in ('pairs.csv','points.csv')})
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('baselines','baseline-audits','treatments','treatment-audits'):p.add_argument('--'+name,nargs='+',required=True)
    p.add_argument('--freeze',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.baselines,a.baseline_audits,a.treatments,a.treatment_audits,a.freeze,a.out))
