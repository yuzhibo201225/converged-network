"""Seal complete carrier/scenario roles without opening ZIP members."""
import argparse
import csv
import json
from pathlib import Path
from .coarse_observation import sha

ROLES={'tmobile/stationary-good':'development','tmobile/weak-signal':'development',
       'tmobile/driving':'calibration','verizon/stationary-good':'reserved',
       'verizon/walking':'reserved','verizon/crowded':'reserved'}
COMPONENTS={'up-delay-light-pdo','down-delay-light-pdo','up-heavy-pdo','down-heavy-pdo',
            'latency-offset-up','latency-offset-down'}


def assign(rows):
    assigned=[];seen=set()
    for r in rows:
        path=r['member_path'];parts=path.split('/')
        if len(parts)!=3:raise ValueError('unexpected member path')
        group='/'.join(parts[:2])
        if group not in ROLES or parts[2] not in COMPONENTS or path in seen:raise ValueError('unexpected or duplicate group/component')
        seen.add(path);assigned.append(dict(group=group,role=ROLES[group],member_path=path,
                          uncompressed_bytes=int(r['uncompressed_bytes']),compressed_bytes=int(r['compressed_bytes'])))
    if seen!={f'{g}/{c}' for g in ROLES for c in COMPONENTS}:raise ValueError('complete source groups required')
    return assigned


def seal(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text())
    if m['status']!='FETCHED_METADATA_ONLY_NOT_VALIDATED' or m['numeric_trace_values_inspected'] or m['archive_members_decompressed']:raise ValueError('uninspected acquisition required')
    if sha(source/'inventory.csv')!=m['inventory_sha256'] or sha(source/'traces/cellular-traces.zip')!=m['files']['traces/cellular-traces.zip']['sha256']:raise ValueError('source changed')
    with (source/'inventory.csv').open() as h:rows=list(csv.DictReader(h))
    assigned=assign(rows);out.mkdir(parents=True)
    (out/'split.json').write_text(json.dumps(dict(status='SEALED_METADATA_ROLES_NO_NUMERIC_PARSE',
         source_manifest_sha256=sha(source/'manifest.json'),archive_sha256=m['files']['traces/cellular-traces.zip']['sha256'],
         source_commit=m['commit'],roles=ROLES,members=assigned,numeric_trace_values_inspected=False,
         external_blinding=False,code_sha256=sha(__file__),
         scope='two-operator six-scenario source; not six independent days or live control experiments'),indent=2))
    print(json.dumps(dict(status='SEALED_METADATA_ROLES_NO_NUMERIC_PARSE',group_count=len(ROLES),
                         counts={role:sum(a['role']==role for a in assigned) for role in ('development','calibration','reserved')},
                         split_sha256=sha(out/'split.json'))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();seal(a.source,a.out)
