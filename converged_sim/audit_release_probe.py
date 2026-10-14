"""Audit intermediate raw records; does not certify native replay equivalence."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from .coarse_observation import sha
from .cellreplay_development_screen import quantile


def audit(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text());f=json.loads((source/'frozen.json').read_text())
    root=Path(__file__).parents[1]
    if m['frozen_sha256']!=sha(source/'frozen.json') or m['cohorts_sha256']!=sha(source/'cohorts.csv'):raise ValueError('receipts changed')
    if any(sha(root/p)!=v for p,v in f['model_sha256'].items()):raise ValueError('model/protocol changed')
    with (source/'cohorts.csv').open() as h:cohorts=list(csv.DictReader(h))
    if len(cohorts)!=m['cohorts']:raise ValueError('cohort coverage')
    total=0;logical={};reconstructed=[]
    for receipt in m['receipts']:
        name=receipt['file']
        if sha(source/name)!=receipt['sha256']:raise ValueError('raw changed')
        with gzip.open(source/name,'rt') as h:rows=list(csv.DictReader(h))
        if len(rows)!=receipt['rows'] or len(rows)%10000:raise ValueError('raw cohort count')
        digest=hashlib.sha256();previous_release=-1
        for index,row in enumerate(rows):
            packet=int(row['packet_id']);arrival=int(row['arrival_ms']);release=int(row['release_ms'])
            if packet!=400+index or arrival!=20*packet or int(row['cohort'])!=index//10000:raise ValueError('period/cohort')
            if release<arrival or release<previous_release or int(row['planned_delay_ms'])!=release-arrival:raise ValueError('causality/order')
            if int(row['content_bytes'])!=receipt['content_bytes']:raise ValueError('content size')
            previous_release=release;digest.update(json.dumps(row,sort_keys=True,separators=(',',':')).encode())
        key=(receipt['group'],receipt['direction'],receipt['content_bytes'])
        logical.setdefault(key,[]).append(digest.hexdigest());total+=len(rows)
        expected=[c for c in cohorts if c['planned_file']==name]
        if len(expected)!=len(rows)//10000:raise ValueError('summary cohorts')
        for c in expected:
            subset=rows[int(c['cohort'])*10000:(int(c['cohort'])+1)*10000];ds=[int(r['planned_delay_ms']) for r in subset]
            values=dict(count=len(subset),planned_delay_p99_ms=quantile(ds,.99),
                fraction_planned_ge20ms=sum(d>=20 for d in ds)/len(ds),fraction_planned_ge40ms=sum(d>=40 for d in ds)/len(ds),
                planned_heavy_flags=sum(r['planned_light_bypass']=='False' for r in subset),
                release_clamps=sum(r['release_clamped']=='True' for r in subset))
            if any(float(c[k])!=v for k,v in values.items()):raise ValueError('raw summary')
            reconstructed.append(dict(group=c['group'],direction=c['direction'],content_bytes=int(c['content_bytes']),
                timer_ms=int(c['timer_ms']),cohort=int(c['cohort']),**values))
    if total!=m['planned_control_records'] or len(logical)!=8 or any(len(v)!=2 for v in logical.values()):raise ValueError('complete fixture/config coverage')
    out.mkdir(parents=True)
    (out/'audit.json').write_text(json.dumps(dict(status='PASS_INTERMEDIATE_RECORDS_ONLY',
        raw_manifest_sha256=sha(source/'manifest.json'),planned_control_records=total,cohorts=len(reconstructed),
        timer0_and5_logical_records_exact=all(a==b for a,b in logical.values()),
        native_equivalence_verified=False,real_control_delivery_measured=False),indent=2))
    (out/'cohorts.json').write_text(json.dumps(reconstructed,indent=2));print((out/'audit.json').read_text())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();audit(a.input,a.out)
