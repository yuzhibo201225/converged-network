"""Recompute exported prediction endpoints using NumPy's quantile implementation."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import numpy as np
from ns3_validation.renewal_cli import digest,dump


def verify(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    a=json.loads((source/'audit.json').read_text())
    if a['status']!='PASS':raise ValueError('completed prediction receipt required')
    for name,sha in a['outputs_sha256'].items():
        if digest(source/name)!=sha:raise ValueError('prediction export changed')
    cohorts={};ids=set();count=0
    with gzip.open(source/'control_predictions.csv.gz','rt') as handle:
        for r in csv.DictReader(handle):
            key=(r['ordering'],r['run_index']);identity=key+(r['control_id'],)
            if identity in ids:raise ValueError('duplicate exported control')
            ids.add(identity);count+=1
            cohorts.setdefault(key,[]).append([float(r[k]) for k in ('packet_prediction_T','fluid_prediction_T','observed_T')])
    with (source/'runs.csv').open() as handle:runs=list(csv.DictReader(handle))
    if len(runs)!=a['runs'] or count!=a['control_predictions']:raise ValueError('export counts')
    for r in runs:
        values=np.asarray(cohorts[(r['ordering'],r['run_index'])])
        if len(values)!=10000:raise ValueError('control run cohort')
        for i,name in enumerate(('packet','fluid','observed')):
            p99=float(np.quantile(values[:,i],.99));miss=float(np.mean(values[:,i]>=1))
            if abs(p99-float(r[name+'_control_p99_T']))>1e-10 or abs(miss-float(r[name+'_control_miss_ratio']))>1e-12:
                raise ValueError('exported endpoint recomputation')
    out.mkdir(parents=True)
    result=dict(status='PASS',runs=len(runs),control_records=count,
                scope='SHA-checked export endpoint recomputation via NumPy; not independent authorship',
                source_receipt_sha256=digest(source/'audit.json'),code_sha256=digest(__file__),numpy_version=np.__version__)
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(verify(a.input,a.out))
