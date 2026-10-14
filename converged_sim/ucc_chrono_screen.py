"""Metadata-only split repair before opening rates; future dates stay sealed."""
import argparse
import csv
import io
import json
import math
import re
import statistics
import zipfile
from collections import Counter
from pathlib import Path
from .ucc_split_screen import timestamp,role as failed_hash_role
from ns3_validation.renewal_cli import digest,dump


def chronology(paths):
    grouped={}
    for path in paths:
        m=re.search(r'(20\d\d\.\d\d\.\d\d)',path)
        if not m:raise ValueError('unknown session date')
        grouped[path]=m.group(1)
    dates=sorted(set(grouped.values()))
    if len(dates)<3:raise ValueError('three distinct dates required')
    return {p:(day,'validation' if day==dates[-1] else 'calibration' if day==dates[-2] else 'development') for p,day in grouped.items()}


def run(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text())
    if m['status']!='FETCHED_NOT_MODEL_VALIDATED' or any(digest(source/p)!=v['sha256'] for p,v in m['files'].items()):raise ValueError('pinned source required')
    out.mkdir(parents=True)
    with zipfile.ZipFile(source/'5G-production-dataset.zip') as z:
        files=sorted(i.filename for i in z.infolist() if '/Download/' in i.filename and i.filename.lower().endswith('.csv') and not i.filename.startswith('__MACOSX/'))
        roles=chronology(files)
        rows=[dict(session_path=p,day=roles[p][0],role=roles[p][1]) for p in files]
        with (out/'sessions.csv').open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        split=dict(status='CHRONOLOGY_FROZEN_BEFORE_RATE_SCREEN',scope='last date validation, penultimate calibration, earlier dates development; all sessions on a date grouped',
                   source_manifest_sha256=digest(source/'manifest.json'),sessions_sha256=digest(out/'sessions.csv'),
                   original_hash_roles=dict(Counter(failed_hash_role(p)[1] for p in files)),
                   amendment='hash split lacked a role and stopped before any rates read; original failed directory/code retained',
                   roles=dict(Counter(r['role'] for r in rows)),dates=sorted({r['day'] for r in rows}),code_sha256=digest(__file__))
        dump(out/'split.json',split)
        screens=[]
        for s in rows:
            if s['role']!='development':continue
            if z.getinfo(s['session_path']).file_size>20_000_000:raise ValueError('oversized source member')
            with z.open(s['session_path']) as h:
                reader=csv.DictReader(io.TextIOWrapper(h,encoding='utf-8-sig'))
                if not {'Timestamp','DL_bitrate'}<=set(reader.fieldnames or []):raise ValueError('required fields absent')
                values=[];times=[];count=bad_rate=bad_time=0;example=[]
                for r in reader:
                    count+=1;t=timestamp(r['Timestamp'])
                    if t is None:
                        bad_time+=1
                        if not example:example=[r['Timestamp']]
                    else:times.append(t)
                    try:v=float(r['DL_bitrate'])
                    except ValueError:bad_rate+=1;continue
                    if v<0 or not math.isfinite(v):bad_rate+=1;continue
                    values.append(v)
            steps=[(b-a).total_seconds() for a,b in zip(times,times[1:])]
            screens.append(dict(session_path=s['session_path'],rows=count,bad_rate=bad_rate,bad_time=bad_time,
                                unknown_time_examples=json.dumps(example),duplicate_steps=sum(v==0 for v in steps),negative_steps=sum(v<0 for v in steps),
                                median_step_s=statistics.median(steps) if steps else '',max_step_s=max(steps) if steps else '',
                                zero_rate_rows=sum(v==0 for v in values),raw_numeric_rate_min=min(values) if values else '',
                                raw_numeric_rate_median=statistics.median(values) if values else '',raw_numeric_rate_max=max(values) if values else ''))
    with (out/'development_screen.csv').open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(screens[0]));w.writeheader();w.writerows(screens)
    result=dict(status='SCREENED_NOT_SERVICE_MODEL_VALIDATED',reserved_rate_values_inspected=False,
                scope='development-only raw numeric/clock diagnostics; no capacity interpretation/unit conversion or radio-tail guarantee',
                sessions=len(rows),development_sessions=len(screens),split_sha256=digest(out/'split.json'),
                screen_sha256=digest(out/'development_screen.csv'),code_sha256=digest(__file__))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.input,a.out))
