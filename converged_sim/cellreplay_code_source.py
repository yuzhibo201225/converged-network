"""Acquire only observed pinned source files; no build or trace-member reads."""
import argparse
import json
from pathlib import Path
import urllib.request
from .coarse_observation import sha

COMMIT='2ca662cb01a222dd7fcc10f9ed79293803b4ef21'
FILES=('src/frontend/cellular_queue.cc','src/frontend/cellular_queue.hh','src/frontend/cellularshell.cc')


def fetch(out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    out.mkdir(parents=True);m=dict(commit=COMMIT,status='FETCHING',files={},external_code_executed=False,
                                 scope='primary implementation text inspection only')
    def save():(out/'manifest.json').write_text(json.dumps(m,indent=2))
    save()
    try:
        for name in FILES:
            url=f'https://raw.githubusercontent.com/williamsentosa95/cellreplay/{COMMIT}/{name}'
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'converged-research-source-inspection'}),timeout=30) as h:body=h.read(1_000_001)
            if len(body)>1_000_000:raise ValueError('source file limit')
            target=out/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
            m['files'][name]=dict(url=url,bytes=len(body),sha256=sha(target));save()
        m.update(status='FETCHED_NOT_REPLAY_VERIFIED',code_sha256=sha(__file__));save()
        print(json.dumps({'status':m['status'],'files':list(m['files'])}))
    except BaseException as e:
        m.update(status='FAILED',error=str(e));save();raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();fetch(a.out)
