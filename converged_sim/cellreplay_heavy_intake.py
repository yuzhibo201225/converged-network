"""Streaming development-only heavy trace parser; no replay/policy outcomes."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import zipfile
from .coarse_observation import sha

def parse(stream):
    digest=hashlib.sha256(); size=0; count=0; duplicates=0
    first=None; previous=None; max_gap=0; bins=Counter(); prefix=Counter()
    while True:
        line=stream.readline(1025)
        if not line: break
        if len(line)>1024: raise ValueError('line limit')
        digest.update(line); size+=len(line)
        stripped=line.strip()
        if not stripped.isdigit(): raise ValueError('integer timestamp required')
        timestamp=int(stripped)
        if timestamp >= 2**64: raise ValueError('uint64 overflow')
        if previous is not None:
            if timestamp<previous: raise ValueError('decreasing time')
            duplicates+=int(timestamp==previous)
            max_gap=max(max_gap,timestamp-previous)
        else: first=timestamp
        previous=timestamp; count+=1; bins[timestamp//1000]+=1
        if timestamp<=208000: prefix[timestamp]+=1
    if not count or not previous: raise ValueError('nonzero trace duration required')
    return dict(sha256=digest.hexdigest(),bytes=size,events=count,
                duplicate_times=duplicates,first_ms=first,last_ms=previous,
                max_gap_ms=max_gap,opportunity_bytes=1400,
                bins_1000ms=dict(sorted(bins.items()))), prefix

def run(out):
    root=Path(__file__).resolve().parents[1]; out=Path(out)
    if out.exists(): raise FileExistsError(out)
    archive=root/'results/cellreplay_source_v20/traces/cellular-traces.zip'
    split_path=root/'results/cellreplay_split_v20/split.json'
    split=json.loads(split_path.read_text())
    if sha(archive)!=split['archive_sha256']: raise ValueError('archive SHA mismatch')
    members=[m for m in split['members'] if m['role']=='development' and m['member_path'].endswith('heavy-pdo')]
    if len(members)!=4: raise ValueError('development scope mismatch')
    out.mkdir(parents=True)
    freeze=dict(split_sha256=sha(split_path),archive_sha256=sha(archive),
                code_sha256=sha(__file__),protocol_sha256=sha(root/'q2_upgrade/HEAVY_TRACE_INTAKE_PROTOCOL_V25.md'),
                members=[m['member_path'] for m in members],prefix_end_ms=208000,
                reserved_members_opened=0,calibration_members_opened=0)
    (out/'frozen.json').write_text(json.dumps(freeze,indent=2))
    result={}
    with zipfile.ZipFile(archive) as z:
        for i,m in enumerate(members):
            with z.open(m['member_path']) as stream: stats,prefix=parse(stream)
            if stats['bytes']!=m['uncompressed_bytes']: raise ValueError('byte count mismatch')
            target=out/f'{i}-prefix.csv.gz'
            with gzip.open(target,'wt',newline='') as f:
                f.write('timestamp_ms,opportunities\n')
                for t,n in sorted(prefix.items()): f.write(f'{t},{n}\n')
            stats.update(prefix_file=target.name,prefix_sha256=sha(target),
                         prefix_events=sum(prefix.values()),prefix_end_ms=208000)
            result[m['member_path']]=stats
            print(json.dumps(dict(member=m['member_path'],events=stats['events'],last_ms=stats['last_ms'])),flush=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2))
    (out/'audit.json').write_text(json.dumps(dict(status='PASS_DEVELOPMENT_HEAVY_SCHEMA_ONLY',
        frozen_sha256=sha(out/'frozen.json'),summary_sha256=sha(out/'summary.json'),
        members_opened=4,reserved_members_opened=0,calibration_members_opened=0,
        replay_executed=False),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);run(p.parse_args().out)
