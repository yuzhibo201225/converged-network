"""Bind the offline planner and reserved configurations before new endpoints."""
import argparse
import json
from pathlib import Path
from .scenario_predictor import model_hashes
from ns3_validation.renewal_cli import digest,dump


def freeze(development,configs,out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    receipts=[]
    for directory in development:
        directory=Path(directory);a=json.loads((directory/'audit.json').read_text())
        if a['status']!='PASS' or a['evaluation_scope']!='development':raise ValueError('development receipt required')
        for name,sha in a['outputs_sha256'].items():
            if digest(directory/name)!=sha:raise ValueError('development changed')
        if a['code_sha256']!=model_hashes()['converged_sim/scenario_predictor.py']:raise ValueError('model changed since development')
        receipts.append(dict(path=str(directory.resolve()),audit_sha256=digest(directory/'audit.json')))
    planned=[]
    for config in configs:
        spec=json.loads(Path(config).read_text())
        if spec['trace_seed_base']!=120000 or spec['seed']!=20261016 or spec['tauS'] not in (4,12) or spec['runs']!=[1,2,3,4,5]:
            raise ValueError('reserved input family mismatch')
        planned.append(digest(config))
    result=dict(status='FROZEN',model_hashes=model_hashes(),allowed_config_sha256=planned,development=receipts,
                scope='offline full-scenario baseline; no coefficients fitted; not an online or novelty certificate',code_sha256=digest(__file__))
    dump(out,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--development',nargs='+',required=True);p.add_argument('--configs',nargs='+',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(freeze(a.development,a.configs,a.out))
