"""Posthoc finite-witness admission ceiling, not a deployable classifier."""
import argparse
import csv
import json
from pathlib import Path
from .coarse_observation import sha


def ceiling(rows):
    groups={}
    for row in rows:
        if row['mode']!='budget':continue
        key=(row['rho'],row['queue'],row['seed'])
        groups.setdefault(key,[]).append(row)
    result=[]
    for key,group in groups.items():
        if len(group)!=3 or {r['profile'] for r in group}!={'constant','fine','coarse'}:raise ValueError('complete three-world information class required')
        decisions={r['qualified']=='True' for r in group}
        if len(decisions)!=1:raise ValueError('same-information decisions differ')
        qualified=decisions.pop();passes=sum(r['observed_joint_pass']=='True' for r in group)
        result.append(dict(rho=key[0],queue=key[1],seed=key[2],qualified=qualified,
            all_observed_worlds_pass=passes==3,passing_worlds=passes,failing_worlds=3-passes,
            unsafe_witness_blocks_universal_qualification=passes<3,
            observed_ceiling_matches_budget=qualified==(passes==3)))
    return result


def run(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    a=json.loads((source/'audit.json').read_text())
    if a['status']!='PASS' or sha(source/'comparisons.csv')!=a['comparisons_sha256']:raise ValueError('audited comparisons required')
    with (source/'comparisons.csv').open() as h:rows=list(csv.DictReader(h))
    groups=ceiling(rows)
    if len(groups)!=80:raise ValueError('all80 load/scheduler/seed information classes required')
    out.mkdir(parents=True)
    with (out/'information_classes.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(groups[0]));w.writeheader();w.writerows(groups)
    report=dict(status='PASS',scope='posthoc ceiling for this finite observed witness set only',
        information_classes=len(groups),classes_with_failing_witness=sum(g['failing_worlds']>0 for g in groups),
        max_qualifiable_observed_outcomes_with_no_failing_world=sum(3 for g in groups if g['all_observed_worlds_pass']),
        safe_observed_outcomes_sharing_input_with_failure=sum(g['passing_worlds'] for g in groups if g['failing_worlds']>0),
        budget_rule_matches_every_finite_witness_ceiling=all(g['observed_ceiling_matches_budget'] for g in groups),
        global_uncertainty_set_optimality_proven=False,new_data_draws=0,
        parent_audit_sha256=sha(source/'audit.json'),classes_sha256=sha(out/'information_classes.csv'))
    (out/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.out)
