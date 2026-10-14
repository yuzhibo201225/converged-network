"""Exact six-case replay, not six additional independent trials."""
import argparse
import csv
import gzip
import json
from pathlib import Path
from .coarse_observation import sha,trace,simulate
from .traffic_contract import emissions


def replay(folder,out):
    folder=Path(folder);out=Path(out)
    if out.exists():raise FileExistsError(out)
    frozen=json.loads((folder/'frozen.json').read_text());cfg=frozen['config']
    root=Path(__file__).parents[1]
    if any(sha(root/p)!=v for p,v in frozen['model_sha256'].items()):raise ValueError('frozen inputs changed')
    with (folder/'runs.csv').open() as h:runs=list(csv.DictReader(h))
    selected=[r for r in runs if float(r['rho'])==.95 and int(r['seed'])==1]
    if len(selected)!=6:raise ValueError('six fixed stress cases required')
    comparisons=[]
    for r in selected:
        events=[(round((e.generated_s-1)/cfg['T'],10),e.flow,e.packet_id,{1:.01,2:.04,3:.1}[e.flow])
                for e in emissions(.95,cfg['pmr'],cfg['bulk_cycle'],cfg['warm'],
                                   cfg['measured']+cfg['guard'],cfg['phase_seed'],1)]
        s=trace(r['profile'],1,cfg)
        rows,_=simulate(events,s,r['queue'],cfg['capacity'],cfg['warm'],cfg['warm']+cfg['measured'],s.observation_duration)
        with gzip.open(folder/r['packet_file'],'rt') as h:original=list(csv.DictReader(h))
        if [{k:str(v) for k,v in row.items()} for row in rows]!=original:raise ValueError('exact logical raw replay differs')
        comparisons.append(dict(profile=r['profile'],queue=r['queue'],rows=len(rows),logical_records_exact=True))
        print(f'replayed {r["profile"]}/{r["queue"]}',flush=True)
    out.mkdir(parents=True)
    (out/'replay.json').write_text(json.dumps(dict(status='PASS',new_independent_draws=0,
        selection='rho .95 / seed1, all policies/profiles; internal deterministic cross-check',
        frozen_sha256=sha(folder/'frozen.json'),comparisons=comparisons),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();replay(a.input,a.out)
