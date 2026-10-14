"""Stream only presealed development light/offset members; no heavy/reserve data."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import zipfile
from .coarse_observation import sha


def quantile(values,q):return sorted(values)[math.ceil(q*len(values))-1]


def lines(archive,name,limit=5_000_000):
    total=0;h=hashlib.sha256()
    with archive.open(name) as stream:
        for row in stream:
            total+=len(row)
            if total>limit or len(row)>65536:raise ValueError('bounded member/line exceeded')
            h.update(row);yield row.decode('ascii').rstrip('\r\n')
    yield {'sha256':h.hexdigest(),'bytes':total,'complete_member_read':True}


def parse_light(source):
    timestamps=[];delays=[];pdo_lengths=[];pdo_ends=[];receipt=None
    for row in source:
        if isinstance(row,dict):receipt=row;continue
        tokens=row.split(' ')
        if len(tokens)<3 or any(not s.isdigit() for s in tokens):raise ValueError('strict light schema')
        t,d,*pdo=map(int,tokens)
        if timestamps and t<timestamps[-1]:raise ValueError('decreasing light timestamp')
        if any(b<a for a,b in zip(pdo,pdo[1:])):raise ValueError('decreasing light PDO')
        timestamps.append(t);delays.append(d);pdo_lengths.append(len(pdo));pdo_ends.append(pdo[-1])
    if len(timestamps)<3 or receipt is None:raise ValueError('complete light member required')
    gaps=[b-a for a,b in zip(timestamps,timestamps[1:])]
    return dict(records=len(timestamps),first_timestamp_ms=timestamps[0],last_timestamp_ms=timestamps[-1],
                duplicate_timestamp_steps=sum(x==0 for x in gaps),gap_median_ms=statistics.median(gaps),gap_max_ms=max(gaps),
                base_delay_min_ms=min(delays),base_delay_p50_ms=statistics.median(delays),
                base_delay_p99_ms=quantile(delays,.99),base_delay_max_ms=max(delays),
                fraction_base_ge20ms=sum(x>=20 for x in delays)/len(delays),
                fraction_base_ge40ms=sum(x>=40 for x in delays)/len(delays),
                light_pdo_count_min=min(pdo_lengths),light_pdo_count_max=max(pdo_lengths),
                light_pdo_end_p99_ms=quantile(pdo_ends,.99),member_receipt=receipt)


def parse_offset(source):
    values=[];receipt=None
    for row in source:
        if isinstance(row,dict):receipt=row;continue
        tokens=row.split(' ')
        if len(tokens)!=2 or not tokens[0].isdigit():raise ValueError('strict offset schema')
        size=int(tokens[0]);offset=float(tokens[1])
        if size!=100*(len(values)+1) or not math.isfinite(offset):raise ValueError('offset ordering/finite values')
        values.append(offset)
    if not values or receipt is None:raise ValueError('complete offset member required')
    def compensate(size):
        idx=size//100-1;rem=size%100
        if idx<0:return values[0]
        if idx>=len(values)-1:return values[-1]
        return values[idx]+rem/100*(values[idx+1]-values[idx])
    return dict(rows=len(values),max_size_bytes=100*len(values),offset_min_ms=min(values),offset_max_ms=max(values),
                content_150_offset_ms=compensate(150),content_600_offset_ms=compensate(600),
                content_1200_offset_ms=compensate(1200),member_receipt=receipt)


def screen(source,split,code_source,out):
    source=Path(source);split=Path(split);code_source=Path(code_source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    sm=json.loads((source/'manifest.json').read_text());sp=json.loads(split.read_text());cm=json.loads((code_source/'manifest.json').read_text())
    archive=source/'traces/cellular-traces.zip'
    if sp['source_manifest_sha256']!=sha(source/'manifest.json') or sp['archive_sha256']!=sha(archive):raise ValueError('sealed source changed')
    if cm['commit']!=sm['commit'] or any(sha(code_source/name)!=r['sha256'] for name,r in cm['files'].items()):raise ValueError('pinned implementation changed')
    selected=[r for r in sp['members'] if r['role']=='development' and ('delay-light-pdo' in r['member_path'] or 'latency-offset' in r['member_path'])]
    if len(selected)!=8 or any(not r['group'].startswith('tmobile/') for r in selected):raise ValueError('development-only coverage')
    root=Path(__file__).parents[1];out.mkdir(parents=True)
    (out/'frozen.json').write_text(json.dumps(dict(split_sha256=sha(split),source_manifest_sha256=sha(source/'manifest.json'),
        implementation_manifest_sha256=sha(code_source/'manifest.json'),
        model_sha256={p:sha(root/p) for p in ('converged_sim/cellreplay_development_screen.py','q2_upgrade/CELLREPLAY_SEMANTICS_PROTOCOL_V21.md')},
        selected_member_paths=[r['member_path'] for r in selected],status='FROZEN_BEFORE_DEVELOPMENT_VALUES'),indent=2))
    results=[]
    try:
        with zipfile.ZipFile(archive) as z:
            for member in selected:
                name=member['member_path']
                result=parse_light(lines(z,name)) if 'delay-light-pdo' in name else parse_offset(lines(z,name))
                results.append(dict(member_path=name,role='development',**result));print(f'screened {name}',flush=True)
        (out/'development.json').write_text(json.dumps(results,indent=2))
        (out/'audit.json').write_text(json.dumps(dict(status='DEVELOPMENT_SCREEN_COMPLETE_NOT_CONTROL_VALIDATION',
            members_screened=len(results),reserved_members_opened=0,calibration_members_opened=0,heavy_members_opened=0,
            frozen_sha256=sha(out/'frozen.json'),development_sha256=sha(out/'development.json')),indent=2))
    except BaseException as e:
        (out/'audit.json').write_text(json.dumps(dict(status='FAILED_PRESERVED',error=str(e),completed_members=len(results)),indent=2));raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--split',required=True);p.add_argument('--code-source',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();screen(a.source,a.split,a.code_source,a.out)
