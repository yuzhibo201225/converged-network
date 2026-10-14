"""Bounded native-source method fixtures; no upstream networking is executed."""
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
from .coarse_observation import sha
from .cellreplay_release_model import ReleasePlanner


def selected(body,a,b):
    i=body.index(a);j=body.index(b,i+len(a));return body[i:j]


def run(source,split,development,code_source,planned,out):
    source=Path(source);split=Path(split);development=Path(development);code_source=Path(code_source);planned=Path(planned);out=Path(out)
    if out.exists():raise FileExistsError(out)
    root=Path(__file__).parents[1];compiler=Path('C:/msys64/mingw64/bin/g++.exe')
    native=root/'ns3_validation/cellreplay_release_fixture.cc'
    env=dict(os.environ);env['PATH']=str(compiler.parent)+';'+env.get('PATH','')
    cm=json.loads((code_source/'manifest.json').read_text());sp=json.loads(split.read_text())
    pm=json.loads((planned/'manifest.json').read_text());df=json.loads((development/'frozen.json').read_text())
    if sha(split)!=df['split_sha256'] or sha(code_source/'manifest.json')!=df['implementation_manifest_sha256']:raise ValueError('source split changed')
    if sha(planned/'frozen.json')!=pm['frozen_sha256']:raise ValueError('planned freeze changed')
    if any(sha(code_source/p)!=r['sha256'] for p,r in cm['files'].items()):raise ValueError('primary code changed')
    archive=source/'traces/cellular-traces.zip'
    if sha(archive)!=sp['archive_sha256']:raise ValueError('source archive changed')
    body=(code_source/'src/frontend/cellular_queue.cc').read_bytes();fixture=native.read_bytes()
    fragments=[selected(body,b'uint64_t CellularQueue::get_pkt_release_time_from_trace(',b'string CellularQueue::get_pkt_header_info('),
               selected(body,b'double CellularQueue::get_psize_latency_offset(',b'void CellularQueue::read_packet(')]
    if any(fragment not in fixture for fragment in fragments):raise ValueError('selected native methods are not byte-exact')
    out.mkdir(parents=True);exe=out/'native-fixture.exe'
    command=[str(compiler),'-std=c++17','-O2','-ffp-contract=off','-static',str(native),'-o',str(exe)]
    versions=subprocess.run([str(compiler),'--version'],capture_output=True,text=True,timeout=30,check=True,env=env)
    names=('converged_sim/native_release_check.py','converged_sim/cellreplay_release_model.py',
           'ns3_validation/cellreplay_release_fixture.cc','q2_upgrade/NATIVE_RELEASE_PROTOCOL_V23.md')
    frozen=dict(status='FROZEN_BEFORE_NATIVE_BUILD',model_sha256={p:sha(root/p) for p in names},
                selected_method_sha256=[hashlib.sha256(f).hexdigest() for f in fragments],
                planned_manifest_sha256=sha(planned/'manifest.json'),split_sha256=sha(split),
                compiler_sha256=sha(compiler),compiler_version=versions.stdout,command=command,
                runtime_path_prefix=str(compiler.parent))
    (out/'frozen.json').write_text(json.dumps(frozen,indent=2))
    try:
        built=subprocess.run(command,capture_output=True,text=True,timeout=90,env=env)
        (out/'build.json').write_text(json.dumps(dict(exit_code=built.returncode,stdout=built.stdout,stderr=built.stderr),indent=2))
        if built.returncode:raise RuntimeError('native fixture build failed')
        screens={r['member_path']:r for r in json.loads((development/'development.json').read_text())}
        allowed={r['member_path'] for r in sp['members'] if r['role']=='development'}
        inputs={};native_receipts=[];total=0
        with zipfile.ZipFile(archive) as z:
            for receipt in pm['receipts']:
                group=receipt['group'];direction=receipt['direction'];key=(group,direction)
                if key not in inputs:
                    pair=[]
                    for suffix,name in (('light',f'{group}/{direction}-delay-light-pdo'),('offset',f'{group}/latency-offset-{direction}')):
                        if name not in allowed or z.getinfo(name).file_size>5_000_000:raise ValueError('bounded development input required')
                        target=out/f'input-{len(inputs)}-{suffix}.txt';target.write_bytes(z.read(name))
                        if sha(target)!=screens[name]['member_receipt']['sha256']:raise ValueError('development values changed')
                        pair.append(target)
                    inputs[key]=pair
                target=out/f'{len(native_receipts)}-native.csv'
                command=[str(exe),*[str(p) for p in inputs[key]],str(receipt['content_bytes']),str(receipt['timer_ms']),str(target)]
                process=subprocess.run(command,capture_output=True,text=True,timeout=60,env=env)
                if process.returncode:raise RuntimeError(f'native case failed: {process.stderr}')
                reference=planned/receipt['file']
                if sha(reference)!=receipt['sha256']:raise ValueError('planned raw changed')
                with target.open() as a,gzip.open(reference,'rt') as b:
                    na=csv.DictReader(a);py=csv.DictReader(b);count=0
                    for expected in py:
                        actual=next(na,None)
                        if actual!=expected:raise ValueError(f'native row mismatch at {receipt["file"]}/{count}: {actual} != {expected}')
                        count+=1
                    if next(na,None) is not None or count!=receipt['rows']:raise ValueError('native rowcount')
                native_receipts.append(dict(file=target.name,sha256=sha(target),rows=count,reference_file=receipt['file'],fields_exact=True))
                total+=count;print(f'native exact {group}/{direction}, size{receipt["content_bytes"]}, timer{receipt["timer_ms"]}: {count}',flush=True)
        # Small synthetic fixtures exercise active/light exhaustion and exact timer boundaries.
        light=out/'synthetic-light.txt';offset=out/'synthetic-offset.txt';events_path=out/'synthetic-events.txt'
        light.write_text('0 20 0 3 5\n100 30 0 4 8\n200 20 0 2 4\n')
        offset.write_text('100 -4.9\n200 -4.3\n')
        records=[(0,20,[0,3,5]),(100,30,[0,4,8]),(200,20,[0,2,4])];offsets=[-4.9,-4.3]
        events=[(0,1400),(1,1400),(2,1400),(3,1400),(3,150),(20,150),(21,182),(50,150),(80,150)]
        events_path.write_text(''.join(f'{t} {size}\n' for t,size in events));synthetic=[]
        for timer in (0,5,20,25):
            target=out/f'synthetic-{timer}.csv'
            subprocess.run([str(exe),str(light),str(offset),'150',str(timer),str(target),str(events_path)],capture_output=True,text=True,timeout=30,check=True,env=env)
            model=ReleasePlanner(records,offsets,timer)
            with target.open() as h:actual=list(csv.DictReader(h))
            expected=[{k:str(v) for k,v in dict(packet_id=i,cohort=0,**model.plan(t,size)).items()} for i,(t,size) in enumerate(events)]
            if actual!=expected:raise ValueError(f'synthetic native mismatch timer{timer}')
            synthetic.append(dict(timer_ms=timer,rows=len(actual),sha256=sha(target),fields_exact=True))
        report=dict(status='PASS_SELECTED_NATIVE_METHODS',planned_controls_compared=total,native_configurations=len(native_receipts),
                    synthetic_rows=sum(s['rows'] for s in synthetic),native_receipts=native_receipts,synthetic=synthetic,
                    executable_sha256=sha(exe),frozen_sha256=sha(out/'frozen.json'),
                    upstream_networking_executed=False,reserved_members_opened=0,calibration_members_opened=0,
                    heavy_members_opened=0,full_cellreplay_equivalence_verified=False,independent_expert_review=False)
        (out/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:report[k] for k in ('status','planned_controls_compared','synthetic_rows')}))
    except BaseException as e:
        (out/'failure.json').write_text(json.dumps(dict(status='FAILED_PRESERVED',error=str(e)),indent=2));raise


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('source','split','development','code-source','planned','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.source,a.split,a.development,a.code_source,a.planned,a.out)
