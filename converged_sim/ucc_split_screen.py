"""Date-group split before rates are inspected; screen development data only.

Observed throughput is not radio capacity. No GPS/cell/operator fields exported.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import re
import statistics
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from ns3_validation.renewal_cli import digest,dump


def role(path):
    match=re.search(r'(20\d\d\.\d\d\.\d\d)',path)
    if match is None:raise ValueError('unrecognized session date')
    day=match.group(1);bucket=int(hashlib.sha256(('ucc-date-split-v17:'+day).encode()).hexdigest()[:8],16)%5
    return day,('validation' if bucket==0 else 'calibration' if bucket==1 else 'development')


def timestamp(value):
    for fmt in ('%Y.%m.%d_%H.%M.%S','%Y.%m.%d_%H:%M:%S','%Y.%m.%d %H:%M:%S','%Y-%m-%d %H:%M:%S'):
        try:return datetime.strptime(value,fmt)
        except ValueError:pass
    return None


def run(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text())
    if m['status']!='FETCHED_NOT_MODEL_VALIDATED' or any(digest(source/p)!=r['sha256'] for p,r in m['files'].items()):raise ValueError('pinned source receipt required')
    out.mkdir(parents=True)
    sessions=[];screens=[]
    with zipfile.ZipFile(source/'5G-production-dataset.zip') as archive:
        members=[r for r in archive.infolist() if '/Download/' in r.filename and r.filename.lower().endswith('.csv') and not r.filename.startswith('__MACOSX/')]
        if not members or sum(r.file_size for r in members)>50_000_000:raise ValueError('bounded Download members required')
        for r in sorted(members,key=lambda x:x.filename):
            day,split=role(r.filename);sessions.append(dict(session_path=r.filename,day=day,role=split,bytes=r.file_size))
        if {r['role'] for r in sessions}!={'development','calibration','validation'}:raise ValueError('fixed date split lacks a role; preserve failure, do not tune on rates')
        with (out/'sessions.csv').open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(sessions[0]));w.writeheader();w.writerows(sessions)
        split_receipt=dict(status='SPLIT_FROZEN_BEFORE_RATE_SCREEN',source_manifest_sha256=digest(source/'manifest.json'),
                           archive_sha256=m['files']['5G-production-dataset.zip']['sha256'],sessions_sha256=digest(out/'sessions.csv'),
                           method='SHA256(ucc-date-split-v17:calendar-date) first8hex modulo5; validation0, calibration1, development2-4',
                           roles=dict(Counter(r['role'] for r in sessions)),code_sha256=digest(__file__))
        dump(out/'split.json',split_receipt)
        for s in sessions:
            if s['role']!='development':continue # reserved rate values not read
            with archive.open(s['session_path']) as h:
                reader=csv.DictReader(io.TextIOWrapper(h,encoding='utf-8-sig'))
                if not {'Timestamp','DL_bitrate'}<=set(reader.fieldnames or []):raise ValueError('required schema absent')
                rates=[];times=[];bad_rate=bad_time=rows=0;examples=[]
                for r in reader:
                    rows+=1;t=timestamp(r['Timestamp'])
                    if t is None:
                        bad_time+=1
                        if len(examples)<1:examples.append(r['Timestamp'])
                    else:times.append(t)
                    try:v=float(r['DL_bitrate'])
                    except ValueError:bad_rate+=1;continue
                    if not math.isfinite(v) or v<0:bad_rate+=1;continue
                    rates.append(v)
            steps=[(b-a).total_seconds() for a,b in zip(times,times[1:])]
            screens.append(dict(session_path=s['session_path'],rows=rows,bad_rate=bad_rate,bad_time=bad_time,
                                unknown_timestamp_examples=json.dumps(examples),duplicate_steps=sum(v==0 for v in steps),
                                negative_steps=sum(v<0 for v in steps),median_step_s=statistics.median(steps) if steps else '',
                                max_step_s=max(steps) if steps else '',zero_rate_rows=sum(v==0 for v in rates),
                                raw_numeric_rate_min=min(rates) if rates else '',raw_numeric_rate_median=statistics.median(rates) if rates else '',
                                raw_numeric_rate_max=max(rates) if rates else ''))
    with (out/'development_screen.csv').open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(screens[0]));w.writeheader();w.writerows(screens)
    result=dict(status='SCREENED_NOT_SERVICE_MODEL_VALIDATED',scope='development-only schema/timestamp/rate diagnostics; numeric units not converted; zeros not labeled outages',
                reserved_rate_values_inspected=False,sessions=len(sessions),development_sessions=len(screens),
                split_sha256=digest(out/'split.json'),screen_sha256=digest(out/'development_screen.csv'),code_sha256=digest(__file__))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.input,a.out))
