"""SHA-checked within-input staleness intervention, not independent replication."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from ns3_validation.renewal_cli import cases, digest, dump


def checked(raw,analysis):
    raw=Path(raw).resolve();analysis=Path(analysis)
    a=json.loads((analysis/'audit.json').read_text());m=json.loads((raw/'manifest.json').read_text())
    if a['status']!='PASS' or digest(raw/'manifest.json')!=a['manifest_sha256'] or digest(analysis/'runs.csv')!=a['runs_sha256']:
        raise ValueError('matched all-flow audit required')
    with (analysis/'runs.csv').open() as handle:rows=list(csv.DictReader(handle))
    lookup={}
    for mode in m['spec']['modes']:
        folder=raw/mode;child=json.loads((folder/'manifest.json').read_text())
        audit=json.loads((analysis/mode/'audit.json').read_text())
        if audit['status']!='PASS' or digest(folder/'manifest.json')!=audit['manifest_sha256']:
            raise ValueError('child provenance')
        cohort=[r for r in rows if r['ordering']==mode]
        if len(cohort)!=len(list(cases(child['spec']))):raise ValueError('child run count')
        for i,r in enumerate(cohort):
            path=folder/f'{i}-summary.csv'
            if digest(path)!=child['receipts'][str(i)]['summary']:raise ValueError('summary receipt')
            with path.open() as handle:original=list(csv.DictReader(handle))[0]
            if any(r[k]!=v for k,v in original.items()):raise ValueError('summary fields changed')
            trace=folder/'traces'/f'{r["run"]}.csv'
            if digest(trace)!=r['service_trace_digest']:raise ValueError('trace changed')
            if r['shape']=='feedback':
                key=(mode,int(r['run']),float(r['bias']))
                if key in lookup:raise ValueError('duplicate configuration')
                lookup[key]=r
    if len(lookup)!=60:raise ValueError('expected complete60-run feedback grid')
    return lookup,m,a


def compare(reference,reference_analysis,zero,zero_analysis,out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    left,lm,la=checked(reference,reference_analysis);right,rm,ra=checked(zero,zero_analysis)
    if lm['source_sha256']!=rm['source_sha256'] or lm['executable_sha256']!=rm['executable_sha256']:
        raise ValueError('engine/code not identical')
    if set(left)!=set(right):raise ValueError('pair grid')
    pairs=[];points=[]
    for key in sorted(left):
        a=left[key];b=right[key]
        for field in ('rho','R','tauB','tauS','seed','run','T','warm','measured','shape','queue','bias','capacity',
                      'arrival_digest','service_trace_digest','bulk_phase_fraction','lattice_fraction'):
            if a[field]!=b[field]:raise ValueError('unpaired '+field)
        if float(a['lag'])!=.5 or float(b['lag'])!=0:raise ValueError('lag intervention mismatch')
        row=dict(ordering=key[0],run=key[1],bias=key[2])
        for metric in ('control_p99_T','control_miss_ratio','bulk_p99_T','bulk_delivery_ratio','admitted_rho'):
            row['lag05_'+metric]=float(a[metric]);row['lag0_'+metric]=float(b[metric])
            row['delta_'+metric]=float(b[metric])-float(a[metric])
        row['lag05_pass']=a['joint_pass']=='True';row['lag0_pass']=b['joint_pass']=='True'
        pairs.append(row)
    for mode in ('lowfirst','highfirst','coinflip'):
        for bias in (0,.06):
            cohort=[r for r in pairs if r['ordering']==mode and r['bias']==bias]
            p=dict(ordering=mode,bias=bias,n=len(cohort))
            if len(cohort)!=10:raise ValueError('ten paired seeds required')
            for lag in ('lag0','lag05'):
                p[lag+'_successes']=sum(r[lag+'_pass'] for r in cohort)
                for metric in ('control_p99_T','control_miss_ratio','bulk_p99_T','bulk_delivery_ratio','admitted_rho'):
                    p[lag+'_'+metric+'_median']=statistics.median(r[lag+'_'+metric] for r in cohort)
            for metric in ('control_p99_T','bulk_p99_T'):
                v=[r['delta_'+metric] for r in cohort]
                p['delta_'+metric+'_median']=statistics.median(v);p['delta_'+metric+'_min']=min(v);p['delta_'+metric+'_max']=max(v)
            points.append(p)
    out.mkdir(parents=True)
    for name,rows in (('pairs',pairs),('points',points)):
        with (out/f'{name}.csv').open('w',newline='') as handle:
            w=csv.DictWriter(handle,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    result=dict(status='PASS',pairs=len(pairs),scope='exploratory same-input lag intervention, not independent reliability trials',
                reference_audit_sha256=digest(Path(reference_analysis)/'audit.json'),zero_audit_sha256=digest(Path(zero_analysis)/'audit.json'),
                code_sha256=digest(__file__),pairs_sha256=digest(out/'pairs.csv'),points_sha256=digest(out/'points.csv'),points=points)
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('reference','reference-analysis','zero','zero-analysis','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(compare(a.reference,a.reference_analysis,a.zero,a.zero_analysis,a.out))
