"""Pinned public source acquisition; ZIP metadata only, no code execution."""
import argparse
import csv
import json
from pathlib import Path
import re
import urllib.request
import zipfile
from .coarse_observation import sha


def fetch(commit,out):
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('exact observed commit required')
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True)
    m=dict(status='FETCHING',repository='https://github.com/williamsentosa95/cellreplay',
           commit=commit,scope='public source/ZIP-metadata only; no numeric trace access',files={})
    def save(): (out/'manifest.json').write_text(json.dumps(m,indent=2))
    save()
    try:
        for name in ('README.md','LICENSE','COPYING','traces/cellular-traces.zip'):
            url=f'https://raw.githubusercontent.com/williamsentosa95/cellreplay/{commit}/{name}'
            request=urllib.request.Request(url,headers={'User-Agent':'converged-research-public-source-intake'})
            with urllib.request.urlopen(request,timeout=30) as response:body=response.read(64_000_001)
            if len(body)>64_000_000:raise ValueError('bounded64MB fetch exceeded; no archive processing')
            target=out/name;target.parent.mkdir(exist_ok=True);target.write_bytes(body)
            m['files'][name]=dict(url=url,bytes=len(body),sha256=sha(target));save()
            print(f'fetched {name}: {len(body)} bytes',flush=True)
        if b'GNU GENERAL PUBLIC LICENSE' not in (out/'LICENSE').read_bytes():raise ValueError('license identification failed')
        inventory=[]
        with zipfile.ZipFile(out/'traces/cellular-traces.zip') as z:
            for item in z.infolist():
                if item.is_dir():continue
                inventory.append(dict(member_path=item.filename,uncompressed_bytes=item.file_size,
                                      compressed_bytes=item.compress_size))
        if not inventory:raise ValueError('empty archive inventory')
        with (out/'inventory.csv').open('w',newline='') as h:
            w=csv.DictWriter(h,fieldnames=list(inventory[0]));w.writeheader();w.writerows(inventory)
        m.update(status='FETCHED_METADATA_ONLY_NOT_VALIDATED',member_count=len(inventory),
                 inventory_sha256=sha(out/'inventory.csv'),numeric_trace_values_inspected=False,
                 archive_members_decompressed=False,external_code_executed=False,code_sha256=sha(__file__))
        save();return m
    except BaseException as e:
        m.update(status='FAILED',error=str(e));save();raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--commit',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();m=fetch(a.commit,a.out);print(json.dumps({k:m[k] for k in ('status','member_count')}))
