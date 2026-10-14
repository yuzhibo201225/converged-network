"""Fixed first reserved source opening; tests an implementation subclaim only."""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import subprocess
import zipfile
from .coarse_observation import sha,digest
from .cellreplay_heavy_intake import parse
from .cellreplay_release_probe import load
from .cellreplay_release_model import ReleasePlanner
from .cellreplay_mixed import arrivals,simulate,summarize,save_rows

CONFIG=dict(group='verizon/stationary-good',direction='up',end_ms=208000,warm_ms=8000,
    loads=[.6],pmrs=[3],cycle_ms=300,timer_ms=0,capacity_packets=16,
    policies=['fifo'],accounting=['original','accepted'],deadlines_ms=[10,20,40])

def run(out):
    root=Path(__file__).resolve().parents[1];out=Path(out);cfg=CONFIG
    if out.exists():raise FileExistsError(out)
    archive=root/'results/cellreplay_source_v20/traces/cellular-traces.zip'
    split=root/'results/cellreplay_split_v20/split.json';sp=json.loads(split.read_text())
    if sha(split)!='041490a80060ea4ce445de65580fde31330d2c3483421cb5aeed0053af922b31':raise ValueError('sealed split')
    assert sha(archive)==sp['archive_sha256']
    names=[f"{cfg['group']}/{cfg['direction']}-heavy-pdo",f"{cfg['group']}/{cfg['direction']}-delay-light-pdo",f"{cfg['group']}/latency-offset-{cfg['direction']}"]
    assert all(next(m['role'] for m in sp['members'] if m['member_path']==n)=='reserved' for n in names)
    native=root/'results/native_release_v23b';na=json.loads((native/'audit.json').read_text())
    assert sha(native/'native-fixture.exe')==na['executable_sha256']
    out.mkdir(parents=True)
    freeze=dict(config=cfg,selected_reserved_members=names,split_sha256=sha(split),archive_sha256=sha(archive),
        prior_pushout_audit_sha256=sha(root/'results/cellreplay_pushout_audit_v29/audit.json'),
        model_sha256={n:sha(root/n) for n in ('converged_sim/heldout_artifact.py',
            'converged_sim/cellreplay_mixed.py','converged_sim/cellreplay_release_model.py',
            'converged_sim/cellreplay_heavy_intake.py','q2_upgrade/HELDOUT_ARTIFACT_PROTOCOL_V31.md')},
        status='FROZEN_BEFORE_FIRST_RESERVED_NUMERIC_PARSE',scope='one held-out implementation-artifact case')
    (out/'frozen.json').write_text(json.dumps(freeze,indent=2))
    exposure=dict(reserved_member_reads_started=[],complete_member_receipts={})
    def save_exposure():(out/'exposure.json').write_text(json.dumps(exposure,indent=2))
    save_exposure()
    with zipfile.ZipFile(archive) as z:
        exposure['reserved_member_reads_started'].append(names[0]);save_exposure()
        with z.open(names[0]) as h:hs,prefix=parse(h)
        exposure['complete_member_receipts'][names[0]]={k:hs[k] for k in ('sha256','bytes')};save_exposure()
        print('held-out heavy member parsed',flush=True)
        exposure['reserved_member_reads_started'].append(names[1]);save_exposure()
        records,lr=load(z,names[1],'light');exposure['complete_member_receipts'][names[1]]=lr;save_exposure()
        exposure['reserved_member_reads_started'].append(names[2]);save_exposure()
        offsets,orr=load(z,names[2],'offset');exposure['complete_member_receipts'][names[2]]=orr;save_exposure()
        (out/'light.txt').write_bytes(z.read(names[1]));(out/'offset.txt').write_bytes(z.read(names[2]))
    assert records[-1][0]>cfg['end_ms'] and hs['last_ms']>cfg['end_ms']
    pdos=sorted(prefix.items());budget=sum(n for t,n in pdos)*1400
    with gzip.open(out/'prefix.csv.gz','wt',newline='') as h:
        h.write('timestamp_ms,opportunities\n')
        for t,n in pdos:h.write(f'{t},{n}\n')
    hs.update(prefix_file='prefix.csv.gz',prefix_sha256=sha(out/'prefix.csv.gz'))
    (out/'heavy_summary.json').write_text(json.dumps({names[0]:hs},indent=2))
    critical=(cfg['end_ms']//20)*150+(cfg['end_ms']//200)*256
    count=math.floor((.6*budget-critical)/1400);assert count>0
    events,cycles=arrivals(count,3,cfg);planner=ReleasePlanner(records,offsets,0);planned=[]
    with (out/'events.txt').open('w') as h:
        for pid,(t,flow,local,size) in enumerate(events):
            h.write(f'{t} {size}\n');planned.append(dict(packet_id=pid,flow=flow,flow_id=local,**planner.plan(t,size)))
    save_rows(out/'planned.csv.gz',planned)
    command=[str((native/'native-fixture.exe').resolve()),str((out/'light.txt').resolve()),
        str((out/'offset.txt').resolve()),'150','0',str((out/'native.csv').resolve()),str((out/'events.txt').resolve())]
    result=subprocess.run(command,capture_output=True,text=True,timeout=180,check=True)
    compared=0
    with (out/'native.csv').open(newline='') as h:
        for compared,row in enumerate(csv.DictReader(h),1):
            assert int(row['packet_id'])==compared-1
            for k,v in planned[compared-1].items():
                if k in row:assert row[k]==str(v),(compared,k,row[k],v)
    assert compared==len(planned)
    results=[];receipts=[];invariant=[]
    for accounting in cfg['accounting']:
        rows,diag=simulate(planned,pdos,'fifo',accounting,16,cfg['end_ms'])
        metrics=summarize(rows,8000,cfg['deadlines_ms']);assert metrics['control_count']==10000
        filename=f'fifo-{accounting}-packets.csv.gz';save_rows(out/filename,rows)
        results.append(dict(rho_target=.6,rho_actual=(critical+1400*count)/budget,pmr=3,policy='fifo',accounting=accounting,
            source_arrival_sha256=digest(events),planned_sha256=sha(out/'planned.csv.gz'),service_sha256=sha(out/'prefix.csv.gz'),
            packet_file=filename,**diag,**metrics))
        receipts.append(dict(file=filename,rows=len(rows),sha256=sha(out/filename)))
        first=next((i for i,r in enumerate(rows) if r['status']=='dropped'),None)
        eligible=[r for r in rows[(first+1 if first is not None else len(rows)):] if r['release_ms']<=cfg['end_ms'] and r['planned_light_bypass']]
        bypasses=sum(r['actual_bypass'] for r in eligible)
        if accounting=='original':assert bypasses==0
        invariant.append(dict(accounting=accounting,first_refusal_id=first,eligible_after_refusal=len(eligible),bypasses_after_refusal=bypasses))
        print(f'held-out FIFO {accounting} completed',flush=True)
    with (out/'runs.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    (out/'invariant.json').write_text(json.dumps(invariant,indent=2))
    manifest=dict(status='COMPLETED_ONE_HELDOUT_CASE_QUEUE_NATIVE_CHECK_PENDING',frozen_sha256=sha(out/'frozen.json'),
        runs_sha256=sha(out/'runs.csv'),receipts=receipts,exposure_sha256=sha(out/'exposure.json'),
        heavy_summary_sha256=sha(out/'heavy_summary.json'),native_release_rows=compared,
        native_release_sha256=sha(out/'native.csv'),planned_sha256=sha(out/'planned.csv.gz'),
        invariant_sha256=sha(out/'invariant.json'),reserved_member_paths_opened=names)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({k:v for k,v in manifest.items() if k not in ('receipts','reserved_member_paths_opened')}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);run(p.parse_args().out)
