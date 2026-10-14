"""Exact packet/trace replay, with explicit summary trace-path exception."""
import argparse
import csv
import json
from pathlib import Path
from .renewal_cli import cases, digest, dump


def verify(original, replay, out):
    original=Path(original);replay=Path(replay);out=Path(out)
    if out.exists(): raise FileExistsError(out)
    am=json.loads((original/'manifest.json').read_text());bm=json.loads((replay/'manifest.json').read_text())
    if am['status']!='COMPLETE' or bm['status']!='COMPLETE': raise ValueError('incomplete sweep')
    if am['source_sha256']!=bm['source_sha256'] or am['executable_sha256']!=bm['executable_sha256']:
        raise ValueError('code/executable mismatch')
    count=0
    for mode in bm['spec']['modes']:
        a=original/mode;b=replay/mode
        ra=json.loads((a/'manifest.json').read_text());rb=json.loads((b/'manifest.json').read_text())
        lookup={tuple(sorted(c.items())):i for i,c in enumerate(cases(am['spec']))}
        for j,c in enumerate(cases(bm['spec'])):
            i=lookup[tuple(sorted(c.items()))]
            for folder,index,manifest in ((a,i,ra),(b,j,rb)):
                for name in ('summary','packets'):
                    if digest(folder/f'{index}-{name}.csv')!=manifest['receipts'][str(index)][name]:
                        raise ValueError('receipt mismatch')
            if digest(a/f'{i}-packets.csv')!=digest(b/f'{j}-packets.csv'): raise ValueError('packet bytes differ')
            ta=a/'traces'/f'{c["run"]}.csv';tb=b/'traces'/f'{c["run"]}.csv'
            if digest(ta)!=ra['trace_sha256'][str(c['run'])] or digest(tb)!=rb['trace_sha256'][str(c['run'])] or digest(ta)!=digest(tb):
                raise ValueError('trace bytes differ')
            summaries=[]
            for folder,index in ((a,i),(b,j)):
                with (folder/f'{index}-summary.csv').open() as handle: r=list(csv.DictReader(handle))[0]
                if Path(r.pop('traceCsv')).resolve()!=(folder/'traces'/f'{c["run"]}.csv').resolve():
                    raise ValueError('summary trace path')
                summaries.append(r)
            if summaries[0]!=summaries[1]: raise ValueError('summary field difference beyond declared path')
            count+=1
    out.mkdir(parents=True)
    result=dict(status='PASS',replayed_runs=count,packet_and_trace_bytes='identical',
                summaries='identical fields except validated output traceCsv path',
                scope='deterministic replication; not additional independent scientific trials',
                original_manifest_sha256=digest(original/'manifest.json'),replay_manifest_sha256=digest(replay/'manifest.json'),
                code_sha256=digest(__file__))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',required=True);p.add_argument('--replay',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(verify(a.original,a.replay,a.out))
