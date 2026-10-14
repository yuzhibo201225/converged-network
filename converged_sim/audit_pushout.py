"""Exact raw reconstruction and deterministic replay of V29 component baseline."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
from .coarse_observation import sha
from .audit_cellreplay_mixed import read_rows
from .cellreplay_mixed import summarize
from .cellreplay_pushout import simulate

def run(input_path,baseline,out):
    p=Path(input_path);baseline=Path(baseline);out=Path(out)
    if out.exists():raise FileExistsError(out)
    root=Path(__file__).resolve().parents[1]
    m=json.loads((p/'manifest.json').read_text());f=json.loads((p/'frozen.json').read_text());cfg=f['config']
    assert sha(p/'frozen.json')==m['frozen_sha256'] and sha(p/'runs.csv')==m['runs_sha256']
    assert sha(baseline/'manifest.json')==f['input_manifest_sha256']
    for n,h in f['model_sha256'].items():assert sha(root/n)==h
    bm=json.loads((baseline/'manifest.json').read_text())
    with (baseline/'runs.csv').open(newline='') as h:original=list(csv.DictReader(h))
    hs=json.loads((root/'results/cellreplay_heavy_v25/summary.json').read_text())
    member=f"{cfg['group']}/{cfg['direction']}-heavy-pdo";prefix=root/'results/cellreplay_heavy_v25'/hs[member]['prefix_file']
    assert sha(prefix)==f['service_sha256']
    with gzip.open(prefix,'rt') as h:pdos=[(int(r['timestamp_ms']),int(r['opportunities'])) for r in csv.DictReader(h)]
    with (p/'runs.csv').open(newline='') as h:summaries=list(csv.DictReader(h))
    total=0;controls=0;evicted=0
    for receipt,s in zip(m['receipts'],summaries):
        path=p/receipt['file'];assert sha(path)==receipt['sha256'] and s['packet_file']==path.name
        rows=list(read_rows(path));assert len(rows)==receipt['rows']
        key=f"{float(s['rho_target']):g}-{s['pmr']}"
        plan_receipt=next(r for r in bm['native_release_receipts'] if r['config']==key)
        plan=baseline/plan_receipt['planned_file'];assert sha(plan)==plan_receipt['planned_sha256']==s['planned_sha256']
        b=next(b for b in original if f"{float(b['rho_target']):g}-{b['pmr']}"==key and b['policy']=='priority' and b['accounting']=='accepted')
        for field in ('rho_actual','source_arrival_sha256','service_sha256'):assert s[field]==b[field]
        regenerated,diag=simulate(list(read_rows(plan)),pdos,cfg['capacity_packets'],cfg['end_ms'])
        for pid,(r,exact) in enumerate(zip(rows,regenerated)):
            assert r['packet_id']==pid
            for k,v in exact.items():assert str(r[k])==str(v),(key,pid,k)
            if r['evicted_by']!='':
                incoming=rows[int(r['evicted_by'])]
                assert r['status']=='dropped' and r['flow']>incoming['flow']
                assert r['release_ms']<=incoming['release_ms'];evicted+=1
        for k,v in diag.items():assert s[k]==str(v)
        metrics=summarize(rows,cfg['warm_ms'],cfg['deadlines_ms'])
        for k,v in metrics.items():assert s[k]==str(v) if v is not None else s[k]==''
        total+=len(rows);controls+=metrics['control_count']
        assert metrics['control_count']==10000
        print(f'raw and exact replay passed {key}',flush=True)
    out.mkdir(parents=True)
    audit=dict(status='PASS_RAW_AND_EXACT_PUSHOUT_REPLAY',runs=len(summaries),all_flow_records=total,
        measured_control_records=controls,evicted_packets=evicted,manifest_sha256=sha(p/'manifest.json'),
        scope='same-code exact replay and raw consistency; not independent implementation or novel method')
    (out/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--baseline',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.baseline,a.out)
