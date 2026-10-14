"""Paired trace-run diagnostics and explicitly post-hoc interaction contrast."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from .service_runlength_audit import describe
from ns3_validation.renewal_cli import digest, dump


def analyze(raw,analysis,out):
    raw=Path(raw).resolve();analysis=Path(analysis);out=Path(out)
    if out.exists(): raise FileExistsError(out)
    audit=json.loads((analysis/'audit.json').read_text())
    if audit['status']!='PASS' or audit['manifest_sha256']!=digest(raw/'manifest.json') or audit['runs_sha256']!=digest(analysis/'runs.csv'):
        raise ValueError('matched all-flow audit required')
    with (analysis/'runs.csv').open() as handle: rows=list(csv.DictReader(handle))
    lookup={(r['ordering'],int(r['run']),float(r['bias'])):r for r in rows if r['shape']=='feedback'}
    if len(lookup)!=60: raise ValueError('expected complete paired feedback grid')
    traces=[];points=[];records=[]
    for mode in ('lowfirst','highfirst','coinflip'):
        r,p,_=describe(raw/mode,mode);traces.extend(r);points.append(p)
    for run in range(1,11):
        def val(mode,bias): return float(lookup[(mode,run,bias)]['control_p99_T'])
        delta0=val('coinflip',0)-val('lowfirst',0)
        delta06=val('coinflip',.06)-val('lowfirst',.06)
        records.append(dict(run=run,coinflip_minus_lowfirst_e0_T=delta0,
                            coinflip_minus_lowfirst_e06_T=delta06,
                            interaction_T=delta06-delta0))
    out.mkdir(parents=True)
    for name,data in (('trace_runs',traces),('interaction',records)):
        with (out/f'{name}.csv').open('w',newline='') as handle:
            w=csv.DictWriter(handle,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    summary={}
    for field in ('coinflip_minus_lowfirst_e0_T','coinflip_minus_lowfirst_e06_T','interaction_T'):
        v=[r[field] for r in records]
        summary[field]=dict(median=statistics.median(v),min=min(v),max=max(v),positive=sum(x>0 for x in v))
    result=dict(status='PASS',scope='merged run-lengths predeclared; difference-in-differences is post-hoc descriptive, not independent confirmation',
                trace_points=points,paired_contrasts=summary,source_audit_sha256=digest(analysis/'audit.json'),
                code_sha256=digest(__file__),trace_runs_sha256=digest(out/'trace_runs.csv'),interaction_sha256=digest(out/'interaction.csv'))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--analysis',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(analyze(a.raw,a.analysis,a.out))
