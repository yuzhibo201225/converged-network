"""Transparent cycle-length repair with zero slow endpoints, model unchanged."""
import argparse
import json
from pathlib import Path
from .scenario_predictor import model_hashes
from ns3_validation.renewal_cli import digest,dump


def amend(parent,failed,original,revised,out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    f=json.loads(Path(parent).read_text());m=json.loads((Path(failed)/'manifest.json').read_text())
    a=json.loads(Path(original).read_text());b=json.loads(Path(revised).read_text())
    if f['model_hashes']!=model_hashes():raise ValueError('prediction model changed')
    if m['status']!='FAILED' or m['completed_runs']!=0 or 'non-whole measurement cycles' not in m['error']:
        raise ValueError('zero-endpoint cycle failure required')
    if m['config_sha256']!=digest(original) or digest(original) not in f['allowed_config_sha256']:
        raise ValueError('original config not frozen')
    if (a['warm'],a['measured'],b['warm'],b['measured'])!=(256,10000,264,10008):raise ValueError('undeclared repair')
    if {k:v for k,v in a.items() if k not in ('purpose','warm','measured')}!={k:v for k,v in b.items() if k not in ('purpose','warm','measured')}:
        raise ValueError('other experimental settings changed')
    result=dict(f,status='FROZEN_AMENDED',allowed_config_sha256=[sha for sha in f['allowed_config_sha256'] if sha!=digest(original)]+[digest(revised)],
                parent_freeze_sha256=digest(parent),failed_manifest_sha256=digest(Path(failed)/'manifest.json'),
                amendment='slow profile warm264/measured10008 for integer cycles; zero slow endpoints; not original preregistration',
                amendment_code_sha256=digest(__file__))
    dump(out,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('parent','failed','original','revised','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(amend(a.parent,a.failed,a.original,a.revised,a.out))
