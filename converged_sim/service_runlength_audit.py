"""Post-hoc trace diagnostics: merge adjacent equal-rate service segments."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from ns3_validation.renewal_cli import digest, dump


def low_durations(rows, begin, end, period=.02):
    left=round(begin*1e9);right=round(end*1e9)
    merged=[]
    for i,(at,rate) in enumerate(rows):
        a=max(left,round(at*1e9)); b=min(right,round(rows[i+1][0]*1e9) if i+1<len(rows) else right)
        if b<=a: continue
        if merged and merged[-1][2]==rate and merged[-1][1]==a:
            merged[-1]=(merged[-1][0],b,rate)
        else: merged.append((a,b,rate))
    if sum(b-a for a,b,_ in merged)!=right-left: raise ValueError('uncovered window')
    return [(b-a)/(period*1e9) for a,b,rate in merged if rate==.7]


def describe(raw, label):
    raw=Path(raw)
    manifest=json.loads((raw/'manifest.json').read_text())
    if manifest['status']!='COMPLETE': raise ValueError('incomplete trace family')
    spec=manifest['spec'];begin=1+spec['warm']*.02;end=begin+spec['measured']*.02
    records=[]
    for run in spec['runs']:
        path=raw/'traces'/f'{run}.csv'
        if digest(path)!=manifest['trace_sha256'][str(run)]: raise ValueError('trace hash mismatch')
        with path.open() as handle: rows=[(float(t),float(v)) for t,v in csv.reader(handle)]
        values=low_durations(rows,begin,end)
        records.append(dict(family=label,run=run,low_segments=len(values),max_low_dwell_T=max(values),
                            mean_low_dwell_T=statistics.mean(values),low_total_T=sum(values),trace_sha256=digest(path)))
    maxima=[r['max_low_dwell_T'] for r in records]
    summary=dict(family=label,traces=len(records),max_low_dwell_T_median=statistics.median(maxima),
                 max_low_dwell_T_min=min(maxima),max_low_dwell_T_max=max(maxima))
    return records,summary,digest(raw/'manifest.json')


def run(renewal,order,out):
    out=Path(out)
    if out.exists(): raise FileExistsError(out)
    rows=[];points=[];hashes={}
    for label,source in [('V10 renewal',Path(renewal))]+[(f'V11 {mode}',Path(order)/mode) for mode in ('random','ascending','descending')]:
        records,point,sha=describe(source,label);rows.extend(records);points.append(point);hashes[label]=sha
    out.mkdir(parents=True)
    with (out/'runs.csv').open('w',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    receipt=dict(status='PASS',scope='post-hoc trace-only characterization; V10/V11 are NOT matched causal cohorts',
                 points=points,source_manifest_sha256=hashes,code_sha256=digest(__file__),runs_sha256=digest(out/'runs.csv'))
    dump(out/'audit.json',receipt);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--renewal',required=True);p.add_argument('--order',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.renewal,a.order,a.out))
