"""Five paired phase repetitions for course core evidence, not radio trials."""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import random
import subprocess
from .coarse_observation import sha,digest
from .audit_cellreplay_mixed import read_rows
from .cellreplay_mixed import arrivals,simulate,summarize,save_rows
from .cellreplay_pushout import simulate as pushout
from .cellreplay_release_probe import load
from .cellreplay_release_model import ReleasePlanner
import zipfile

PHASES={seed:0 if seed==0 else random.Random('course-v32:'+str(seed)).randrange(300) for seed in range(5)}
SETTINGS=dict(end_ms=208000,warm_ms=8000,cycle_ms=300,timer_ms=0,capacity_packets=16,deadlines_ms=[10,20,40],rho=.6,seeds=list(range(5)))

def rotated_events(count,pmr,phase,cfg):
    events,cycles=arrivals(count,pmr,cfg)
    changed=[]
    for t,flow,pid,size in events:
        if flow==3:
            start=t//cfg['cycle_ms']*cfg['cycle_ms'];length=min(cfg['cycle_ms'],cfg['end_ms']-start)
            t=start+(t-start+phase)%length
        changed.append((t,flow,pid,size))
    return sorted(changed),cycles

def run(out):
    root=Path(__file__).resolve().parents[1];out=Path(out)
    if out.exists():raise FileExistsError(out)
    archive=root/'results/cellreplay_source_v20/traces/cellular-traces.zip'
    native=root/'results/native_release_v23b';na=json.loads((native/'audit.json').read_text())
    assert sha(native/'native-fixture.exe')==na['executable_sha256']
    groups=[('tmobile/weak-signal','up',[1,3]),('verizon/stationary-good','up',[3])]
    out.mkdir(parents=True)
    frozen=dict(config=SETTINGS,phases_ms=PHASES,groups=groups,archive_sha256=sha(archive),
        model_sha256={n:sha(root/n) for n in ('converged_sim/course_repeats.py',
            'converged_sim/cellreplay_mixed.py','converged_sim/cellreplay_pushout.py',
            'converged_sim/cellreplay_release_model.py','q2_upgrade/COURSE_REPEAT_PROTOCOL_V32.md')},
        scope='five traffic phases on two opened prefixes; not independent radio sessions')
    (out/'frozen.json').write_text(json.dumps(frozen,indent=2));summaries=[];receipts=[];plans=[]
    def checkpoint():
        if summaries:
            with (out/'runs.csv').open('w',newline='') as h:
                w=csv.DictWriter(h,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
        (out/'progress.json').write_text(json.dumps(dict(completed_runs=len(summaries),planned_inputs=len(plans)),indent=2))
    checkpoint()
    with zipfile.ZipFile(archive) as z:
        for group,direction,pmrs in groups:
            records,lr=load(z,f'{group}/{direction}-delay-light-pdo','light')
            offsets,orr=load(z,f'{group}/latency-offset-{direction}','offset')
            base=out/('tmobile' if group.startswith('tmobile') else 'verizon');base.mkdir()
            (base/'light.txt').write_bytes(z.read(f'{group}/{direction}-delay-light-pdo'))
            (base/'offset.txt').write_bytes(z.read(f'{group}/latency-offset-{direction}'))
            if group.startswith('tmobile'):
                hs=json.loads((root/'results/cellreplay_heavy_v25/summary.json').read_text())
                item=hs[f'{group}/{direction}-heavy-pdo'];prefix=root/'results/cellreplay_heavy_v25'/item['prefix_file']
            else:
                hs=json.loads((root/'results/heldout_artifact_v31/heavy_summary.json').read_text())
                item=hs[f'{group}/{direction}-heavy-pdo'];prefix=root/'results/heldout_artifact_v31'/item['prefix_file']
            assert sha(prefix)==item['prefix_sha256']
            with gzip.open(prefix,'rt') as h:pdos=[(int(r['timestamp_ms']),int(r['opportunities'])) for r in csv.DictReader(h)]
            budget=sum(n for t,n in pdos)*1400
            critical=10400*150+1040*256;count=math.floor((.6*budget-critical)/1400)
            for seed,phase in PHASES.items():
                for pmr in pmrs:
                    key=f'{base.name}-{pmr}-{seed}';events,cycles=rotated_events(count,pmr,phase,SETTINGS)
                    planner=ReleasePlanner(records,offsets,0);planned=[];event_path=out/f'{key}-events.txt'
                    with event_path.open('w') as h:
                        for pid,(t,flow,local,size) in enumerate(events):
                            h.write(f'{t} {size}\n');planned.append(dict(packet_id=pid,flow=flow,flow_id=local,**planner.plan(t,size)))
                    plan_path=out/f'{key}-planned.csv.gz';save_rows(plan_path,planned)
                    native_path=out/f'{key}-native.csv'
                    command=[str((native/'native-fixture.exe').resolve()),str((base/'light.txt').resolve()),str((base/'offset.txt').resolve()),'150','0',str(native_path.resolve()),str(event_path.resolve())]
                    subprocess.run(command,capture_output=True,text=True,timeout=180,check=True)
                    compared=0
                    with native_path.open(newline='') as h:
                        for compared,n in enumerate(csv.DictReader(h),1):
                            assert int(n['packet_id'])==compared-1
                            for field,value in planned[compared-1].items():
                                if field in n:assert n[field]==str(value),(key,compared,field)
                    assert compared==len(planned)
                    plans.append(dict(key=key,group=group,pmr=pmr,seed=seed,phase_ms=phase,rows=compared,
                        planned_file=plan_path.name,planned_sha256=sha(plan_path),native_file=native_path.name,native_sha256=sha(native_path),
                        source_sha256=digest(events),service_sha256=sha(prefix),cycles=cycles))
                    variants=[('fifo','original'),('fifo','accepted')]
                    if group.startswith('tmobile'):variants.extend([('priority','accepted'),('pushout','accepted')])
                    for policy,accounting in variants:
                        if policy=='pushout':rows,diag=pushout(planned,pdos,16,208000)
                        else:rows,diag=simulate(planned,pdos,policy,accounting,16,208000)
                        if 'evictions' not in diag:diag['evictions']=0
                        metrics=summarize(rows,8000,[10,20,40]);assert metrics['control_count']==10000
                        filename=f'{key}-{policy}-{accounting}-packets.csv.gz';save_rows(out/filename,rows)
                        summaries.append(dict(group=group,rho_target=.6,rho_actual=(critical+1400*count)/budget,pmr=pmr,
                            seed=seed,phase_ms=phase,policy=policy,accounting=accounting,packet_file=filename,
                            planned_file=plan_path.name,planned_sha256=sha(plan_path),source_sha256=digest(events),service_sha256=sha(prefix),
                            **diag,**metrics))
                        receipts.append(dict(file=filename,sha256=sha(out/filename),rows=len(rows)))
                        checkpoint();print(f'course repeat completed {key}/{policy}/{accounting}',flush=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='COMPLETED_FIVE_PHASE_COURSE_REPEATS',
        frozen_sha256=sha(out/'frozen.json'),runs_sha256=sha(out/'runs.csv'),receipts=receipts,plans=plans,
        newly_opened_reserved_members=0),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);run(p.parse_args().out)
