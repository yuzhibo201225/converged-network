"""Development-only intermediate planned-release diagnostic, not received latency."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import zipfile
from .coarse_observation import sha
from .cellreplay_development_screen import lines,quantile
from .cellreplay_release_model import ReleasePlanner


def load(z,name,kind):
    rows=[];receipt=None
    for row in lines(z,name):
        if isinstance(row,dict):receipt=row;continue
        tokens=row.split(' ')
        if kind=='light':
            if len(tokens)<3 or any(not s.isdigit() for s in tokens):raise ValueError('light schema')
            t,d,*p=map(int,tokens)
            if rows and t<=rows[-1][0]:raise ValueError('strict light times required for interpolation')
            if any(b<a for a,b in zip(p,p[1:])):raise ValueError('PDO order')
            rows.append((t,d,p))
        else:
            size,value=int(tokens[0]),float(tokens[1])
            if len(tokens)!=2 or size!=100*(len(rows)+1):raise ValueError('offset schema')
            rows.append(value)
    if receipt is None:raise ValueError('complete source member required')
    return rows,receipt


def run(source,split,development,code_source,out):
    source=Path(source);split=Path(split);development=Path(development);code_source=Path(code_source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    sm=json.loads((source/'manifest.json').read_text());sp=json.loads(split.read_text())
    da=json.loads((development/'audit.json').read_text());df=json.loads((development/'frozen.json').read_text())
    if da['status']!='DEVELOPMENT_SCREEN_COMPLETE_NOT_CONTROL_VALIDATION' or sha(development/'development.json')!=da['development_sha256'] or sha(development/'frozen.json')!=da['frozen_sha256']:raise ValueError('verified development screen required')
    if sha(split)!=df['split_sha256'] or sha(code_source/'manifest.json')!=df['implementation_manifest_sha256'] or sha(source/'manifest.json')!=sp['source_manifest_sha256']:raise ValueError('sealed sources changed')
    archive=source/'traces/cellular-traces.zip'
    if sha(archive)!=sp['archive_sha256']:raise ValueError('archive changed')
    screened={r['member_path']:r for r in json.loads((development/'development.json').read_text())}
    groups=sorted({r['group'] for r in sp['members'] if r['role']=='development'})
    if groups!=['tmobile/stationary-good','tmobile/weak-signal']:raise ValueError('development-only groups')
    root=Path(__file__).parents[1];out.mkdir(parents=True)
    names=('converged_sim/cellreplay_release_model.py','converged_sim/cellreplay_release_probe.py',
           'converged_sim/cellreplay_development_screen.py','q2_upgrade/RELEASE_FLOOR_PROTOCOL_V22.md')
    frozen=dict(status='FROZEN_BEFORE_CONTROL_PLANNING',model_sha256={p:sha(root/p) for p in names},
                development_audit_sha256=sha(development/'audit.json'),split_sha256=sha(split),
                settings=dict(period_ms=20,warm=400,cohort=10000,content_sizes=[150,182],timers_ms=[0,5]),
                scope='translated release stage only; no heavy PDO/native/received data')
    (out/'frozen.json').write_text(json.dumps(frozen,indent=2));summary=[];receipts=[];rowcount=0
    try:
        with zipfile.ZipFile(archive) as z:
            for group in groups:
                for direction in ('up','down'):
                    light_name=f'{group}/{direction}-delay-light-pdo';offset_name=f'{group}/latency-offset-{direction}'
                    records,lr=load(z,light_name,'light');offsets,orr=load(z,offset_name,'offset')
                    if lr!=screened[light_name]['member_receipt'] or orr!=screened[offset_name]['member_receipt']:raise ValueError('numeric input changed')
                    cohorts=(records[-1][0]-8000)//200000
                    if cohorts<1:raise ValueError('no complete control cohort')
                    for size in (150,182):
                        for timer in (0,5):
                            planner=ReleasePlanner(records,offsets,timer);path=f'{len(receipts)}-planned.csv.gz'
                            measured=[]
                            with gzip.open(out/path,'wt',newline='') as h:
                                writer=None
                                for packet in range(400+cohorts*10000):
                                    row=planner.plan(packet*20,size)
                                    if packet<400:continue
                                    cohort=(packet-400)//10000
                                    row=dict(packet_id=packet,cohort=cohort,**row)
                                    if writer is None:writer=csv.DictWriter(h,fieldnames=list(row));writer.writeheader()
                                    writer.writerow(row);measured.append(row)
                            receipts.append(dict(file=path,sha256=sha(out/path),rows=len(measured),group=group,
                                                 direction=direction,content_bytes=size,timer_ms=timer))
                            rowcount+=len(measured)
                            for cohort in range(cohorts):
                                rows=measured[cohort*10000:(cohort+1)*10000];ds=[r['planned_delay_ms'] for r in rows]
                                summary.append(dict(group=group,direction=direction,content_bytes=size,timer_ms=timer,cohort=cohort,
                                    count=len(rows),planned_delay_p99_ms=quantile(ds,.99),fraction_planned_ge20ms=sum(d>=20 for d in ds)/len(ds),
                                    fraction_planned_ge40ms=sum(d>=40 for d in ds)/len(ds),planned_heavy_flags=sum(not r['planned_light_bypass'] for r in rows),
                                    release_clamps=sum(r['release_clamped'] for r in rows),planned_file=path))
                            print(f'planned {group}/{direction}, bytes{size}, timer{timer}: {cohorts} cohorts',flush=True)
        with (out/'cohorts.csv').open('w',newline='') as h:
            w=csv.DictWriter(h,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)
        (out/'manifest.json').write_text(json.dumps(dict(status='PLANNED_RELEASE_ONLY_NOT_END_TO_END',
            frozen_sha256=sha(out/'frozen.json'),cohorts_sha256=sha(out/'cohorts.csv'),receipts=receipts,
            planned_control_records=rowcount,cohorts=len(summary),native_upstream_executed=False,
            heavy_members_opened=0,calibration_members_opened=0,reserved_members_opened=0),indent=2))
    except BaseException as e:
        (out/'failure.json').write_text(json.dumps(dict(status='FAILED_PRESERVED',error=str(e)),indent=2));raise


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('source','split','development','code-source','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.source,a.split,a.development,a.code_source,a.out)
