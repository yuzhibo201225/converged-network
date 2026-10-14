"""Verify a deliberately single-orientation native sweep from its child audit."""
import argparse
import csv
import json
from pathlib import Path
from ns3_validation.renewal_cli import cases,digest,dump
from ns3_validation.orientation_cli import trace_rows
from ns3_validation.order_cli import trace_signature


def verify(source,analysis,out):
    source=Path(source).resolve();analysis=Path(analysis).resolve();out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text())
    if m['status']!='COMPLETE' or m['spec']['modes']!=['coinflip']:raise ValueError('complete single-orientation sweep required')
    folder=source/'coinflip';child=json.loads((folder/'manifest.json').read_text())
    a=json.loads((analysis/'coinflip'/'audit.json').read_text());root=Path(__file__).parents[1]
    if a['status']!='PASS' or digest(folder/'manifest.json')!=a['manifest_sha256'] or a['runs']!=m['planned_runs']:
        raise ValueError('completed child raw audit required')
    if a['analysis_sha256']!=digest(root/'ns3_validation/renewal_cli.py') or a['gate_replay_sha256']!=digest(root/'ns3_validation/renewal_gate.py'):
        raise ValueError('child audit source drift')
    if m['spec']!=child['spec'] or child['completed_runs']!=m['planned_runs'] or child['status']!='COMPLETE':raise ValueError('native child/parent mismatch')
    if any(digest(root/p)!=v for p,v in m['source_sha256'].items()):raise ValueError('native source drift')
    with (analysis/'coinflip'/'runs.csv').open() as h:rows=list(csv.DictReader(h))
    grid=list(cases(m['spec']))
    if len(rows)!=len(grid):raise ValueError('complete child row coverage')
    for i,(r,case) in enumerate(zip(rows,grid)):
        for name in ('summary','packets'):
            if digest(folder/f'{i}-{name}.csv')!=child['receipts'][str(i)][name]:raise ValueError('raw data changed')
        with (folder/f'{i}-summary.csv').open() as h:native=list(csv.DictReader(h))[0]
        if any(r[k]!=v for k,v in native.items()):raise ValueError('audited/native summary mismatch')
        for k,v in case.items():
            if (r[k]!=v) if k in ('shape','queue') else (float(r[k])!=float(v)):raise ValueError('configuration coverage')
        r['ordering']='coinflip'
    for run in m['spec']['runs']:
        path=folder/'traces'/f'{run}.csv'
        if digest(path)!=child['trace_sha256'][str(run)]:raise ValueError('trace changed')
        with path.open() as h:observed=[(float(t),float(v)) for t,v in csv.reader(h)]
        if observed!=trace_rows(m['spec'],run,'coinflip') or child['dwell_signatures'][str(run)]!=trace_signature(m['spec'],run):raise ValueError('service law mismatch')
    out.mkdir(parents=True)
    with (out/'runs.csv').open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    result=dict(status='PASS',scope='intentional single-orientation native sweep; child raw audit plus exact raw/trace/configuration checks; no failed-parent claim',
                manifest_sha256=digest(source/'manifest.json'),runs_sha256=digest(out/'runs.csv'),
                child_analysis=str(analysis/'coinflip'),child_audit_sha256=digest(analysis/'coinflip'/'audit.json'),
                child_runs_sha256=digest(analysis/'coinflip'/'runs.csv'),raw_all_flow_packets=a['raw_all_flow_packets'],
                runs=len(rows),code_sha256=digest(__file__))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--analysis',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(verify(a.raw,a.analysis,a.out))
