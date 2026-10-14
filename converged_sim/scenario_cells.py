"""Complete-configuration cell audit; never merge different feedback lags."""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from ns3_validation.renewal_cli import cases,digest,dump

FIELDS=('rho','R','tauB','tauS','shape','queue','bias','lag','capacity','seed','warm','measured')


def key(row):
    return tuple(row[f] if f in ('shape','queue') else float(row[f]) for f in FIELDS)


def run(raw,analysis,prediction,out):
    raw=Path(raw);analysis=Path(analysis);prediction=Path(prediction);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((raw/'manifest.json').read_text());a=json.loads((analysis/'audit.json').read_text());p=json.loads((prediction/'audit.json').read_text())
    if a['status']!='PASS' or digest(raw/'manifest.json')!=a['manifest_sha256'] or digest(analysis/'runs.csv')!=a['runs_sha256']:
        raise ValueError('checked raw runs required')
    if p['status']!='PASS' or p['source_audit_sha256']!=digest(analysis/'audit.json') or digest(prediction/'runs.csv')!=p['outputs_sha256']['runs.csv']:
        raise ValueError('matched predictions required')
    with (analysis/'runs.csv').open() as h:rows=list(csv.DictReader(h))
    with (prediction/'runs.csv').open() as h:pred=list(csv.DictReader(h))
    forecasts={(r['ordering'],int(r['run_index'])):r for r in pred}
    expected={(mode,key(case),int(case['run'])) for mode in m['spec']['modes'] for case in cases(m['spec'])}
    observed={(r['ordering'],key(r),int(r['run'])) for r in rows}
    if observed!=expected or len(rows)!=len(expected):raise ValueError('complete configuration/run coverage')
    groups=defaultdict(list);mode_index=defaultdict(int)
    for r in rows:
        i=mode_index[r['ordering']];mode_index[r['ordering']]+=1
        f=forecasts[(r['ordering'],i)]
        for name in ('rho','R','tauB','tauS','bias','lag','run'):
            if float(r[name])!=float(f[name]):raise ValueError('forecast matched case')
        if float(r['control_p99_T'])!=float(f['observed_control_p99_T']):raise ValueError('forecast endpoint')
        groups[(r['ordering'],key(r))].append((r,f))
    points=[]
    for (mode,config),cohort in sorted(groups.items()):
        if len(cohort)!=len(m['spec']['runs']):raise ValueError('incorrect cell repetition count')
        r=dict(zip(FIELDS,config),ordering=mode,n=len(cohort))
        r['observed_successes']=sum(x['joint_pass']=='True' for x,_ in cohort)
        for name in ('control_p99_T','control_miss_ratio','bulk_p99_T','bulk_delivery_ratio','admitted_rho'):
            values=[float(x[name]) for x,_ in cohort]
            for suffix,value in (('median',statistics.median(values)),('min',min(values)),('max',max(values))):r[name+'_'+suffix]=value
        for model in ('packet','fluid'):
            r[model+'_false_safe']=sum(f[model+'_joint_pass']=='True' and x['joint_pass']!='True' for x,f in cohort)
            r[model+'_disagreements']=sum((f[model+'_joint_pass']=='True')!=(x['joint_pass']=='True') for x,f in cohort)
            r[model+'_max_abs_p99_error_T']=max(abs(float(f[model+'_p99_error_T'])) for _,f in cohort)
        points.append(r)
    out.mkdir(parents=True)
    with (out/'points.csv').open('w',newline='') as h:
        writer=csv.DictWriter(h,fieldnames=list(points[0]));writer.writeheader();writer.writerows(points)
    result=dict(status='PASS',runs=len(rows),cells=len(points),replicates_per_cell=len(m['spec']['runs']),
                scope='complete configuration grouping including lag/capacity/warm/measured; original parent points superseded only for cell interpretation',
                raw_audit_sha256=digest(analysis/'audit.json'),prediction_audit_sha256=digest(prediction/'audit.json'),
                code_sha256=digest(__file__),points_sha256=digest(out/'points.csv'))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('raw','analysis','prediction','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(run(a.raw,a.analysis,a.prediction,a.out))
