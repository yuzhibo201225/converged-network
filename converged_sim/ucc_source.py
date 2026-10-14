"""Fetch a pinned public data archive; inventory headers, never execute its code.

No coordinate/cell/IP values are exported. This is not service-model validation.
"""
import argparse
import csv
import json
import re
import urllib.request
import zipfile
from pathlib import Path
from ns3_validation.renewal_cli import digest,dump


def fetch(commit,out):
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('exact observed commit required')
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True)
    m=dict(status='FETCHING',repository='https://github.com/uccmisl/5Gdataset',commit=commit,
           scope='public archive acquisition/header inventory only; goodput is not instantaneous capacity',files={})
    dump(out/'manifest.json',m)
    try:
        for name in ('README.md','LICENSE','5G-production-dataset.zip'):
            url=f'https://raw.githubusercontent.com/uccmisl/5Gdataset/{commit}/{name}'
            request=urllib.request.Request(url,headers={'User-Agent':'converged-research-public-dataset-ingest'})
            with urllib.request.urlopen(request,timeout=30) as response:body=response.read(20_000_001)
            if len(body)>20_000_000:raise ValueError('bounded fetch exceeded')
            (out/name).write_bytes(body)
            m['files'][name]=dict(url=url,bytes=len(body),sha256=digest(out/name));dump(out/'manifest.json',m)
        if b'GNU GENERAL PUBLIC LICENSE' not in (out/'LICENSE').read_bytes():raise ValueError('observed source license changed')
        inventory=[]
        with zipfile.ZipFile(out/'5G-production-dataset.zip') as archive:
            for item in archive.infolist():
                if item.is_dir() or item.filename.startswith('__MACOSX/') or not item.filename.lower().endswith(('.csv','.txt')):continue
                if item.file_size>20_000_000:raise ValueError('unexpected member size')
                with archive.open(item) as h:head=h.read(4096)
                decoded=head.decode('utf-8-sig',errors='replace');first=decoded.splitlines()[0] if decoded.splitlines() else ''
                delimiter=max((',',';','\t'),key=lambda d:first.count(d))
                fields=next(csv.reader([first],delimiter=delimiter),[])
                inventory.append(dict(session_path=item.filename,uncompressed_bytes=item.file_size,delimiter=repr(delimiter),header_fields=json.dumps(fields)))
        if not inventory:raise ValueError('no tabular source members')
        with (out/'inventory.csv').open('w',newline='',encoding='utf-8') as h:
            w=csv.DictWriter(h,fieldnames=list(inventory[0]));w.writeheader();w.writerows(inventory)
        m.update(status='FETCHED_NOT_MODEL_VALIDATED',tabular_members=len(inventory),inventory_sha256=digest(out/'inventory.csv'),code_sha256=digest(__file__))
        dump(out/'manifest.json',m);return m
    except BaseException as error:
        m.update(status='FAILED',error=str(error));dump(out/'manifest.json',m);raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--commit',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(fetch(a.commit,a.out))
