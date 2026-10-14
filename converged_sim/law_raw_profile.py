"""Adopt completed child raw audit when legacy parent requires three modes.

Preserve failed parent audit directory; do not rerun or modify native packets.
"""
import argparse
import csv
import json
from pathlib import Path
from ns3_validation.renewal_cli import cases,digest,dump
from ns3_validation.orientation_cli import trace_rows
from ns3_validation.order_cli import trace_signature


def verify(source,partial,out):
    source=Path(source).resolve();partial=Path(partial).resolve();out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text())
    if m['status']!='COMPLETE' or m['spec']['modes']!=['coinflip']:raise ValueError('complete single-mode native profile required')
    if (partial/'audit.json').exists():raise ValueError('not a preserved incomplete parent audit')
    folder=source/'coinflip';child=json.loads((folder/'manifest.json').read_text())
    a=json.loads((partial/'coinflip'/'audit.json').read_text());root=Path(__file__).parents[1]
    if a['status']!='PASS' or digest(folder/'manifest.json')!=a['manifest_sha256'] or a['runs']!=m['planned_runs']:
        raise ValueError('completed child all-flow audit required')
    if a['analysis_sha256']!=digest(root/'ns3_validation/renewal_cli.py') or a['gate_replay_sha256']!=digest(root/'ns3_validation/renewal_gate.py'):
        raise ValueError('child audit implementation changed')
    if m['spec']!=child['spec'] or child['completed_runs']!=m['planned_runs'] or child['status']!='COMPLETE':raise ValueError('child/parent native agreement')
    if any(digest(root/p)!=v for p,v in m['source_sha256'].items()):raise ValueError('frozen native sources changed')
    with (partial/'coinflip'/'runs.csv').open() as h:rows=list(csv.DictReader(h))
    grid=list(cases(m['spec']))
    if len(rows)!=len(grid):raise ValueError('complete child run table')
    for i,(r,case) in enumerate(zip(rows,grid)):
        for name in ('summary','packets'):
            if digest(folder/f'{i}-{name}.csv')!=child['receipts'][str(i)][name]:raise ValueError('audited raw data changed')
        with (folder/f'{i}-summary.csv').open() as h:native=list(csv.DictReader(h))[0]
        if any(r[k]!=v for k,v in native.items()):raise ValueError('child endpoint table changed')
        for k,v in case.items():
            if (r[k]!=v) if k in ('shape','queue') else (float(r[k])!=float(v)):raise ValueError('full configuration coverage')
        r['ordering']='coinflip'
    for run in m['spec']['runs']:
        path=folder/'traces'/f'{run}.csv'
        if digest(path)!=child['trace_sha256'][str(run)]:raise ValueError('service trace changed')
        with path.open() as h:observed=[(float(t),float(v)) for t,v in csv.reader(h)]
        if observed!=trace_rows(m['spec'],run,'coinflip') or child['dwell_signatures'][str(run)]!=trace_signature(m['spec'],run):
            raise ValueError('declared service-law mismatch')
    out.mkdir(parents=True)
    with (out/'runs.csv').open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    # Child audit remains in the preserved legacy directory; downstream reads it
    # via an explicit pointer and byte hashes, not a fictitious copied audit.
    result=dict(status='PASS',scope='completed child raw audit + exact raw/export/trace recheck; legacy multi-mode parent failure retained',
                manifest_sha256=digest(source/'manifest.json'),runs_sha256=digest(out/'runs.csv'),
                child_analysis=str(partial/'coinflip'),child_audit_sha256=digest(partial/'coinflip'/'audit.json'),
                child_runs_sha256=digest(partial/'coinflip'/'runs.csv'),raw_all_flow_packets=a['raw_all_flow_packets'],
                runs=len(rows),code_sha256=digest(__file__))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--partial',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(verify(a.raw,a.partial,a.out))
