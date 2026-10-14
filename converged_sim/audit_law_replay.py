"""Exact endpoint re-run of selected forecast draws, not new statistical trials."""
import argparse
import csv
import json
from pathlib import Path
from .law_admission import one
from ns3_validation.renewal_cli import digest,dump


def verify(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text())
    if m['status']!='COMPLETE' or digest(source/'draws.csv')!=m['outputs_sha256']['draws.csv']:raise ValueError('checked completed forecasts required')
    if any(digest(Path(__file__).parents[1]/p)!=v for p,v in m['source_sha256'].items()):raise ValueError('forecast code changed')
    with (source/'draws.csv').open() as h:rows=list(csv.DictReader(h))
    selected=[r for r in rows if int(r['draw']) in (1,m['spec']['draws'])];checks=[]
    for r in selected:
        current=one(m['spec'],float(r['rho']),int(float(r['tauS'])),int(r['draw']),source)
        for k,v in current.items():
            if k=='runtime_s':continue
            if isinstance(v,bool):equal=(str(v)==r[k])
            elif isinstance(v,(int,float)):equal=(float(v)==float(r[k]))
            else:equal=(v==r[k])
            if not equal:raise ValueError('forecast exact re-run mismatch: '+k)
        checks.append(dict(rho=r['rho'],tauS=r['tauS'],draw=r['draw'],runtime_s=current['runtime_s']))
        print(f'forecast replay {len(checks)}/{len(selected)}',flush=True)
    out.mkdir(parents=True)
    result=dict(status='PASS',scope='exact selected forecast endpoint re-runs; same implementation/authorship, NOT new independent trials',
                replays=checks,source_manifest_sha256=digest(source/'manifest.json'),code_sha256=digest(__file__))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(verify(a.input,a.out))
