"""Post-hoc service-family contrast with identical generated packet streams."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from ns3_validation.feedback_cli import digest


def checked(raw,analysis):
    raw=Path(raw);analysis=Path(analysis)
    a=json.loads((analysis/'audit.json').read_text());m=json.loads((raw/'manifest.json').read_text())
    if a['status']!='PASS' or digest(raw/'manifest.json')!=a['manifest_sha256']: raise ValueError('matched raw audit required')
    with (analysis/'runs.csv').open() as h: rows=list(csv.DictReader(h))
    if len(rows)!=m['planned_runs']: raise ValueError('audit run count')
    for i,r in enumerate(rows):
        path=raw/f'{i}-summary.csv'
        if digest(path)!=m['receipts'][str(i)]['summary']: raise ValueError('summary changed')
        with path.open() as h: original=list(csv.DictReader(h))[0]
        if any(r[k]!=v for k,v in original.items()): raise ValueError('summary audit mismatch')
    return {int(r['run']):r for r in rows if r['shape']=='feedback' and float(r['bias'])==.06},a


def compare(periodic,periodic_analysis,renewal,renewal_analysis,out):
    out=Path(out)
    if out.exists(): raise FileExistsError(out)
    left,a=checked(periodic,periodic_analysis);right,b=checked(renewal,renewal_analysis)
    if set(left)!=set(range(1,71)) or set(right)!=set(left): raise ValueError('70 paired runs required')
    pairs=[]
    for i in sorted(left):
        p=left[i];r=right[i]
        for key in ('seed','rho','R','tauB','T','warm','measured','bias','lag','capacity','arrival_digest','bulk_phase_fraction','lattice_fraction'):
            if p[key]!=r[key]: raise ValueError('unpaired source/config '+key)
        pair=dict(run=i,source_digest=p['arrival_digest'])
        for label,row in (('periodic',p),('renewal',r)):
            for field in ('control_p99_T','control_miss_ratio','bulk_p99_T','bulk_delivery_ratio','admitted_rho'):
                pair[label+'_'+field]=float(row[field])
            pair[label+'_joint_pass']=float(row['control_p99_T'])<1 and float(row['control_miss_ratio'])<.01
        pair['control_p99_delta_T']=pair['renewal_control_p99_T']-pair['periodic_control_p99_T']
        pairs.append(pair)
    out.mkdir(parents=True)
    with (out/'pairs.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(pairs[0]));w.writeheader();w.writerows(pairs)
    delta=[p['control_p99_delta_T'] for p in pairs]
    result=dict(status='PASS',pairs=70,scope='post-hoc paired service-family contrast, not additional reliability certification',
                periodic_successes=sum(p['periodic_joint_pass'] for p in pairs),renewal_successes=sum(p['renewal_joint_pass'] for p in pairs),
                delta_p99_median_T=statistics.median(delta),delta_p99_min_T=min(delta),delta_p99_max_T=max(delta),
                periodic_manifest_sha256=a['manifest_sha256'],renewal_manifest_sha256=b['manifest_sha256'],
                code_sha256=digest(__file__),pairs_sha256=digest(out/'pairs.csv'))
    (out/'audit.json').write_text(json.dumps(result,indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for arg in ('periodic','periodic-analysis','renewal','renewal-analysis','out'): p.add_argument('--'+arg,required=True)
    a=p.parse_args();print(compare(a.periodic,a.periodic_analysis,a.renewal,a.renewal_analysis,a.out),flush=True)
