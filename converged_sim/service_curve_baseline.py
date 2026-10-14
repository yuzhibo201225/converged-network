"""Separate contract-only predictions from retrospective audited comparison."""
import argparse
import csv
import json
from pathlib import Path
from .coarse_observation import sha
from .coarse_service_curve import qualify


def write_rows(path,rows):
    with Path(path).open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def predict(contract,out):
    contract=Path(contract);out=Path(out)
    if out.exists():raise FileExistsError(out)
    data=json.loads(contract.read_text());cfg=data['config']
    if (cfg['T'],cfg['nominal_bps'],cfg['capacity'],cfg['pmr'],cfg['bulk_cycle'],cfg['warm'],cfg['measured'],cfg['guard'])!=(.02,6000000,16,3,8,400,10000,400):raise ValueError('frozen V18 contract required')
    root=Path(__file__).parents[1]
    model_names=['converged_sim/coarse_service_curve.py','converged_sim/service_curve_baseline.py',
                 'q2_upgrade/SERVICE_CURVE_PROTOCOL_V19.md']
    out.mkdir(parents=True)
    frozen=dict(contract_sha256=sha(contract),model_sha256={p:sha(root/p) for p in model_names},
                status='FROZEN_BEFORE_BOUND_CALCULATION',scope='known synthetic contract; retrospective V18')
    (out/'frozen.json').write_text(json.dumps(frozen,indent=2))
    predictions=[]
    for rho in cfg['loads']:
        for queue in cfg['queues']:
            inputs=dict(rho=rho,queue=queue,capacity=cfg['capacity'],guard=cfg['guard'],
                        pmr=cfg['pmr'],bulk_cycle=cfg['bulk_cycle'],deadline_T=cfg['deadline_T'],observation_bin_T=50)
            for mode in ('mean','minimum','budget'):
                predictions.append(dict(rho=rho,queue=queue,**qualify(inputs,mode)))
    write_rows(out/'predictions.csv',predictions)
    (out/'manifest.json').write_text(json.dumps(dict(frozen_sha256=sha(out/'frozen.json'),
        predictions_sha256=sha(out/'predictions.csv'),prediction_count=len(predictions),
        actual_trace_access=False,actual_packet_access=False,actual_outcome_access=False),indent=2))
    print(f'completed {len(predictions)} contract-only predictions',flush=True)


def compare(prediction,observed,audit,out):
    prediction=Path(prediction);observed=Path(observed);out=Path(out);audit=Path(audit)
    if out.exists():raise FileExistsError(out)
    a=json.loads(audit.read_text());pm=json.loads((prediction/'manifest.json').read_text())
    f=json.loads((prediction/'frozen.json').read_text());rm=json.loads((observed.parent/'manifest.json').read_text())
    root=Path(__file__).parents[1]
    if a['status']!='PASS' or a['manifest_sha256']!=sha(observed.parent/'manifest.json') or rm['runs_sha256']!=sha(observed):raise ValueError('verified raw input required')
    if pm['frozen_sha256']!=sha(prediction/'frozen.json') or pm['predictions_sha256']!=sha(prediction/'predictions.csv'):raise ValueError('prediction receipts')
    if f['contract_sha256']!=sha(observed.parent/'frozen.json') or any(sha(root/p)!=v for p,v in f['model_sha256'].items()):raise ValueError('frozen contract/model changed')
    with (prediction/'predictions.csv').open() as h:ps=list(csv.DictReader(h))
    with observed.open() as h:rs=list(csv.DictReader(h))
    comparisons=[];cohorts=[]
    for p in ps:
        group=[r for r in rs if float(r['rho'])==float(p['rho']) and r['queue']==p['queue']]
        if len(group)!=15:raise ValueError('all profiles/seeds required')
        # Rebuild every decision without access to this group's outcome.
        cfg=json.loads((observed.parent/'frozen.json').read_text())['config']
        x=dict(rho=float(p['rho']),queue=p['queue'],capacity=cfg['capacity'],guard=cfg['guard'],
               pmr=cfg['pmr'],bulk_cycle=cfg['bulk_cycle'],deadline_T=cfg['deadline_T'],observation_bin_T=50)
        replay=qualify(x,p['mode'])
        if any(('' if v is None else str(v))!=p[k] for k,v in replay.items()):raise ValueError('prediction reconstruction')
        safe=p['qualified']=='True'
        cohorts.append(dict(mode=p['mode'],rho=p['rho'],queue=p['queue'],qualified=safe,
                       backlog_upper_work=p['backlog_work'],control_delay_upper_T=p['control_delay_upper_T'],
                       observed_joint_pass=sum(r['joint_pass']=='True' for r in group),n=len(group)))
        for r in group:
            comparisons.append(dict(mode=p['mode'],rho=p['rho'],queue=p['queue'],profile=r['profile'],seed=r['seed'],
                qualified=safe,observed_joint_pass=r['joint_pass']=='True',
                category=('qualified_success' if r['joint_pass']=='True' else 'false_qualification') if safe else
                         ('passing_abstention' if r['joint_pass']=='True' else 'failing_abstention')))
    expected={(mode,float(r['rho']),r['queue'],r['profile'],r['seed']) for mode in ('mean','minimum','budget') for r in rs}
    if {(c['mode'],float(c['rho']),c['queue'],c['profile'],c['seed']) for c in comparisons}!=expected or len(comparisons)!=len(expected):raise ValueError('comparison coverage')
    counts={mode:{category:sum(c['mode']==mode and c['category']==category for c in comparisons)
             for category in ('qualified_success','false_qualification','passing_abstention','failing_abstention')}
            for mode in ('mean','minimum','budget')}
    out.mkdir(parents=True);write_rows(out/'comparisons.csv',comparisons);write_rows(out/'cells.csv',cohorts)
    report=dict(status='PASS',scope='retrospective existing-theory baseline; no new experimental draws',
        original_runs=len(rs),prediction_count=len(ps),counts=counts,
        valid_rules_have_zero_observed_false_qualifications=all(counts[m]['false_qualification']==0 for m in ('minimum','budget')),
        prediction_manifest_sha256=sha(prediction/'manifest.json'),raw_audit_sha256=sha(audit),
        comparisons_sha256=sha(out/'comparisons.csv'),cells_sha256=sha(out/'cells.csv'))
    (out/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();subs=p.add_subparsers(dest='command',required=True)
    q=subs.add_parser('predict');q.add_argument('--contract',required=True);q.add_argument('--out',required=True)
    q=subs.add_parser('compare');q.add_argument('--prediction',required=True);q.add_argument('--observed',required=True);q.add_argument('--audit',required=True);q.add_argument('--out',required=True)
    a=p.parse_args()
    if a.command=='predict':predict(a.contract,a.out)
    else:compare(a.prediction,a.observed,a.audit,a.out)
