"""Reconstruct prefix budgets from saved rows, without reopening reserved data."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
from .coarse_observation import sha

def run(input_path,out):
    p=Path(input_path);out=Path(out)
    if out.exists():raise FileExistsError(out)
    audit=json.loads((p/'audit.json').read_text())
    assert sha(p/'frozen.json')==audit['frozen_sha256']
    assert sha(p/'summary.json')==audit['summary_sha256']
    summary=json.loads((p/'summary.json').read_text())
    reconstructed=0
    for name,s in summary.items():
        assert name.startswith('tmobile/') and ('stationary-good' in name or 'weak-signal' in name)
        path=p/s['prefix_file'];assert sha(path)==s['prefix_sha256']
        bins=Counter();events=0;previous=-1
        with gzip.open(path,'rt',newline='') as f:
            for row in csv.DictReader(f):
                t,n=int(row['timestamp_ms']),int(row['opportunities'])
                assert previous<t<=208000 and n>0
                previous=t;events+=n;bins[t//1000]+=n
        assert events==s['prefix_events']
        for b in range(208):assert bins[b]==s['bins_1000ms'].get(str(b),0)
        assert bins[208]<=s['bins_1000ms'].get('208',0)
        reconstructed+=events
    out.mkdir(parents=True)
    result=dict(status='PASS_SAVED_PREFIX_RECONSTRUCTION',members=len(summary),
        reconstructed_opportunities=reconstructed,source_audit_sha256=sha(p/'audit.json'),
        scope='saved-prefix consistency; not independent radio/expert verification')
    (out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.out)
