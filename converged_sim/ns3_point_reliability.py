"""Fresh-run model-conditional reliability at a frozen point, not a load boundary."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from ns3_validation.renewal_cli import digest
from .reliability_boundary import clopper_pearson_lower


def summarize(rows,spec):
    if len(spec.get('loads',[None]))!=1 or len(spec.get('arms',[None]))!=1:
        raise ValueError('point reliability requires one load and one traffic arm')
    groups=defaultdict(list)
    keys=('shape','queue','bias','lag','capacity')
    for r in rows: groups[tuple(r[k] if k in ('shape','queue') else float(r[k]) for k in keys)].append(r)
    expected={tuple(s[k] for k in keys) for s in spec['settings']}
    if set(groups)!=expected: raise ValueError('reliability family mismatch')
    alpha=spec['alpha'];target=spec['reliability_target'];family=len(groups);points=[]
    for key,cohort in groups.items():
        if {int(r['run']) for r in cohort}!=set(spec['runs']) or len(cohort)!=len(spec['runs']):
            raise ValueError('missing/duplicate independent trial')
        successes=sum(float(r['control_p99_T'])<1 and float(r['control_miss_ratio'])<.01 for r in cohort)
        n=len(cohort);lower=clopper_pearson_lower(successes,n,alpha/family)
        p=dict(zip(keys,key),trials=n,successes=successes,observed_run_pass_fraction=successes/n,
               pointwise_lower_95=clopper_pearson_lower(successes,n,alpha),familywise_lower_95=lower,
               family_size=family,alpha=alpha,reliability_target=target,qualified=lower>=target)
        delivery=[int(r['bulk_delivered'])/int(r['bulk_generated']) for r in cohort]
        p.update(bulk_delivery_min=min(delivery),source_bulk_drops_total=sum(int(r['bulk_source_drop']) for r in cohort),
                 control_p99_min=min(float(r['control_p99_T']) for r in cohort),
                 control_p99_max=max(float(r['control_p99_T']) for r in cohort))
        points.append(p)
    return points


def report(source,analysis,out):
    source=Path(source);analysis=Path(analysis);out=Path(out)
    if out.exists(): raise FileExistsError(out)
    a=json.loads((analysis/'audit.json').read_text());m=json.loads((source/'manifest.json').read_text())
    if a['status']!='PASS' or digest(source/'manifest.json')!=a['manifest_sha256']: raise ValueError('raw audit required')
    with (analysis/'runs.csv').open() as h: audited=list(csv.DictReader(h))
    rows=[]
    for i in range(m['planned_runs']):
        path=source/f'{i}-summary.csv'
        if digest(path)!=m['receipts'][str(i)]['summary']: raise ValueError('summary changed')
        with path.open() as h: r=list(csv.DictReader(h))[0]
        if any(audited[i][k]!=v for k,v in r.items()): raise ValueError('audit summary disagreement')
        rows.append(r)
    points=summarize(rows,m['spec']);out.mkdir(parents=True)
    with (out/'points.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(points[0]));w.writeheader();w.writerows(points)
    receipt=dict(status='PASS',scope='model-conditional run reliability at one preselected load/arm; NOT deployment or boundary certification',
                 cells=len(points),trials_per_cell=len(m['spec']['runs']),qualified_cells=sum(p['qualified'] for p in points),
                 audit_sha256=digest(analysis/'audit.json'),manifest_sha256=a['manifest_sha256'],
                 code_sha256=digest(__file__),points_sha256=digest(out/'points.csv'))
    (out/'audit.json').write_text(json.dumps(receipt,indent=2));return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--analysis',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(report(a.input,a.analysis,a.out),flush=True)
