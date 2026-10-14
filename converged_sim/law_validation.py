"""Audit frozen law-admission decisions against independent native draws."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from .reliability_boundary import clopper_pearson_lower
from ns3_validation.renewal_cli import digest,dump


def evaluate(sources,analyses,forecast,freeze,out):
    out=Path(out);forecast=Path(forecast);freeze=Path(freeze)
    if out.exists():raise FileExistsError(out)
    if len(sources)!=len(analyses):raise ValueError('matched raw/audit profiles required')
    f=json.loads(freeze.read_text());fm=json.loads((forecast/'manifest.json').read_text())
    if f['status']!='FROZEN' or digest(forecast/'manifest.json')!=f['forecast_manifest_sha256'] or digest(forecast/'decisions.csv')!=f['decisions_sha256']:
        raise ValueError('frozen forecast receipt mismatch')
    root=Path(__file__).parents[1]
    if any(digest(root/p)!=v for p,v in f['model_sha256'].items()):raise ValueError('frozen forecast code changed')
    with (forecast/'decisions.csv').open() as h:decisions=list(csv.DictReader(h))
    calls={(float(r['rho']),float(r['tauS'])):r for r in decisions}
    points=[];pairs=[];total_records=0;sources_sha={}
    for raw,checked in zip(map(Path,sources),map(Path,analyses)):
        parent=json.loads((raw/'manifest.json').read_text());check=json.loads((checked/'audit.json').read_text())
        if check['status']!='PASS' or parent['status']!='COMPLETE' or parent['config_sha256'] not in f['allowed_native_config_sha256']:
            raise ValueError('complete frozen native audit required')
        if parent['executable_sha256']!=f['native_executable_sha256']:raise ValueError('native engine changed')
        if digest(raw/'manifest.json')!=check['manifest_sha256']:raise ValueError('raw manifest changed')
        if digest(checked/'runs.csv')!=check['runs_sha256']:raise ValueError('parent audited runs changed')
        with (checked/'runs.csv').open() as h:parent_rows=list(csv.DictReader(h))
        folder=raw/'coinflip';child=json.loads((folder/'manifest.json').read_text())
        child_analysis=Path(check['child_analysis']) if 'child_analysis' in check else checked/'coinflip'
        if 'child_analysis' in check and (digest(child_analysis/'audit.json')!=check['child_audit_sha256'] or digest(child_analysis/'runs.csv')!=check['child_runs_sha256']):
            raise ValueError('preserved child audit changed')
        ca=json.loads((child_analysis/'audit.json').read_text())
        if digest(folder/'manifest.json')!=ca['manifest_sha256']:
            raise ValueError('child audit mismatch')
        with (child_analysis/'runs.csv').open() as h:rows=list(csv.DictReader(h))
        if len(rows)!=parent['planned_runs']:raise ValueError('native raw/audit row count')
        if len(parent_rows)!=len(rows) or any(any(p[k]!=v for k,v in r.items()) for p,r in zip(parent_rows,rows)):
            raise ValueError('parent/child checked rows differ')
        for i,r in enumerate(rows):
            path=folder/f'{i}-summary.csv'
            if digest(path)!=child['receipts'][str(i)]['summary']:raise ValueError('native summary changed')
            with path.open() as h:native=list(csv.DictReader(h))[0]
            if any(r[k]!=v for k,v in native.items()):raise ValueError('summary/raw-audit disagreement')
        total_records+=ca['raw_all_flow_packets']
        ts=float(parent['spec']['tauS']);sources_sha[str(raw)]=dict(manifest=digest(raw/'manifest.json'),audit=digest(checked/'audit.json'))
        for rho in parent['spec']['loads']:
            policy_rows={}
            for policy in ('fifo','priority'):
                cohort=[r for r in rows if float(r['rho'])==rho and r['queue']==policy]
                if len(cohort)!=70 or {int(r['run']) for r in cohort}!=set(range(1,71)):raise ValueError('70 complete native draws')
                policy_rows[policy]={int(r['run']):r for r in cohort}
                if any(float(r['tauS'])!=ts or r['shape']!=('feedback' if policy=='fifo' else 'none') or
                       float(r['bias'])!=(fm['spec']['bias'] if policy=='fifo' else 0) or
                       float(r['lag'])!=(fm['spec']['lag'] if policy=='fifo' else 0) or float(r['capacity'])!=fm['spec']['capacity'] for r in cohort):
                    raise ValueError('complete native cell configuration')
                control=sum(float(r['control_p99_T'])<1 and float(r['control_miss_ratio'])<.01 for r in cohort)
                joint=sum(float(r['control_p99_T'])<1 and float(r['control_miss_ratio'])<.01 and int(r['bulk_delivered'])==int(r['bulk_generated']) for r in cohort)
                lower=clopper_pearson_lower(joint,70,f['alpha']/f['validation_family_size'])
                p=dict(rho=rho,tauS=ts,queue=policy,n=70,control_successes=control,joint_successes=joint,simultaneous_lower=lower,
                       native_qualified=lower>=f['q'],bulk_delivery_min=min(int(r['bulk_delivered'])/int(r['bulk_generated']) for r in cohort))
                for field in ('control_p99_T','control_miss_ratio','bulk_p99_T','admitted_rho','source_max_work'):
                    values=[float(r[field]) for r in cohort]
                    p.update({field+'_median':statistics.median(values),field+'_min':min(values),field+'_max':max(values)})
                if policy=='fifo':
                    decision=calls[(rho,ts)]
                    for rule,col in (('law','qualified'),('mean','mean_load'),('fluid','fluid_sufficient_condition')):
                        accepted=decision[col]=='True';p[rule+'_accept']=accepted
                        p[rule+'_failed_admitted_runs']=70-joint if accepted else 0
                        p[rule+'_successful_abstained_runs']=joint if not accepted else 0
                points.append(p)
            for run in range(1,71):
                a=policy_rows['fifo'][run];b=policy_rows['priority'][run]
                if a['arrival_digest']!=b['arrival_digest'] or a['traceCsv']!=b['traceCsv']:raise ValueError('policy pairing changed')
                path=Path(a['traceCsv'])
                if digest(path)!=child['trace_sha256'][str(run)]:raise ValueError('validation trace changed')
                pairs.append(dict(rho=rho,tauS=ts,run=run,
                                  control_delta=float(a['control_p99_T'])-float(b['control_p99_T']),
                                  bulk_delta=float(a['bulk_p99_T'])-float(b['bulk_p99_T'])))
    if len(points)!=f['validation_family_size'] or len({(p['rho'],p['tauS'],p['queue']) for p in points})!=len(points):raise ValueError('complete native confidence family')
    out.mkdir(parents=True)
    for name,rows in (('points.csv',points),('pairs.csv',pairs)):
        fields=list(dict.fromkeys(k for r in rows for k in r))
        with (out/name).open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
    result=dict(status='PASS',scope='prospective frozen known-law admission validation; native eight-cell conditional run probability',
                native_runs=sum(p['n'] for p in points),all_flow_records=total_records,measured_control_packets=sum(p['n'] for p in points)*fm['spec']['measured'],
                alpha=f['alpha'],q=f['q'],family_size=f['validation_family_size'],
                freeze_sha256=digest(freeze),source_sha256=sources_sha,code_sha256=digest(__file__),
                outputs_sha256={n:digest(out/n) for n in ('points.csv','pairs.csv')})
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',nargs='+',required=True);p.add_argument('--analysis',nargs='+',required=True)
    p.add_argument('--forecast',required=True);p.add_argument('--freeze',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(evaluate(a.raw,a.analysis,a.forecast,a.freeze,a.out))
