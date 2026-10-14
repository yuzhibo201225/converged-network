"""Native primary FIFO service/admission differential on all V27 packets."""
import argparse
import csv
import gzip
import json
import os
from pathlib import Path
import subprocess
from .coarse_observation import sha

def run(input_path,out):
    p=Path(input_path);out=Path(out);root=Path(__file__).resolve().parents[1]
    if out.exists():raise FileExistsError(out)
    manifest=json.loads((p/'manifest.json').read_text());freeze=json.loads((p/'frozen.json').read_text())
    assert sha(p/'frozen.json')==manifest['frozen_sha256'] and sha(p/'runs.csv')==manifest['runs_sha256']
    with (p/'runs.csv').open(newline='') as h:runs=list(csv.DictReader(h))
    queue=root/'results/cellreplay_queue_source_v24';qm=json.loads((queue/'manifest.json').read_text())
    for name,info in qm['files'].items():assert sha(queue/name)==info['sha256']
    source=root/'results/cellreplay_code_source_v21/src/frontend/cellular_queue.cc';text=source.read_text()
    methods=text[text.index('uint64_t CellularQueue::next_delivery_time'):text.index('DelayQueuePacket CellularQueue::get_next_from_delay_queue')]
    assert methods.count('CellularQueue::')==3
    template=root/'ns3_validation/cellreplay_mixed_queue_fixture.cc';compiler=Path('C:/msys64/mingw64/bin/g++.exe')
    out.mkdir(parents=True)
    nf=dict(model_sha256={name:sha(root/name) for name in ('converged_sim/native_mixed_queue_check.py',
        'ns3_validation/cellreplay_mixed_queue_fixture.cc','q2_upgrade/MIXED_NATIVE_QUEUE_PROTOCOL_V28.md')},
        source_sha256=sha(source),queue_manifest_sha256=sha(queue/'manifest.json'),
        input_manifest_sha256=sha(p/'manifest.json'),compiler_sha256=sha(compiler),
        scope='native FIFO semantic differential; no OS or priority equivalence')
    (out/'frozen.json').write_text(json.dumps(nf,indent=2))
    (out/'generated.cc').write_text(template.read_text().replace('// INJECT_PINNED_METHODS',methods.replace('CellularQueue::','Fixture::')))
    (out/'exception.hh').write_text('#pragma once\n#include <stdexcept>\n')
    (out/'ezio.hh').write_text('#pragma once\n#include <string>\ninline unsigned myatoi(const std::string& s) { return std::stoul(s); }\n')
    env=dict(os.environ);env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
    executable=out/'mixed_queue.exe'
    command=[str(compiler),'-std=c++17','-O2','-static','-include','cstdint',
        '-I',str(queue/'src/packet'),'-I',str(out),str(out/'generated.cc'),
        str(queue/'src/packet/dropping_packet_queue.cc'),'-o',str(executable)]
    build=subprocess.run(command,env=env,capture_output=True,text=True)
    (out/'build.json').write_text(json.dumps(dict(command=command,returncode=build.returncode,stdout=build.stdout,stderr=build.stderr),indent=2))
    build.check_returncode()
    heavy_summary=json.loads((root/'results/cellreplay_heavy_v25/summary.json').read_text())
    cfg=freeze['config'];member=f"{cfg['group']}/{cfg['direction']}-heavy-pdo"
    prefix=root/'results/cellreplay_heavy_v25'/heavy_summary[member]['prefix_file']
    assert sha(prefix)==freeze['prefix_sha256']
    heavy_path=out/'heavy.txt'
    with gzip.open(prefix,'rt') as h,heavy_path.open('w') as dest:
        for r in csv.DictReader(h):dest.write(f"{r['timestamp_ms']} {r['opportunities']}\n")
    raw_receipts={r['file']:r for r in manifest['receipts']};receipts=[];total=0
    for planned in manifest['native_release_receipts']:
        key=planned['config'];path=p/planned['planned_file'];assert sha(path)==planned['planned_sha256']
        plan_path=out/f'{key}-input.txt'
        with gzip.open(path,'rt') as h,plan_path.open('w') as dest:
            for r in csv.DictReader(h):dest.write(f"{r['packet_id']} {r['arrival_ms']} {r['release_ms']} {r['content_bytes']} {int(r['planned_light_bypass']=='True')}\n")
        for accounting in ('original','accepted'):
            s=next(s for s in runs if f"{float(s['rho_target']):g}-{s['pmr']}"==key and s['policy']=='fifo' and s['accounting']==accounting)
            expected=p/s['packet_file'];assert sha(expected)==raw_receipts[expected.name]['sha256']
            result_path=out/f'{key}-{accounting}-native.csv'
            command=[str(executable.resolve()),str(heavy_path.resolve()),str(plan_path.resolve()),accounting,str(result_path.resolve()),str(cfg['end_ms'])]
            result=subprocess.run(command,capture_output=True,text=True,timeout=180,check=True)
            counters=list(map(int,result.stdout.split()));assert counters==[int(s['final_counter']),int(s['final_resident'])]
            count=0
            with result_path.open(newline='') as nh,gzip.open(expected,'rt',newline='') as eh:
                native_reader=csv.DictReader(nh);expected_reader=csv.DictReader(eh)
                for count,r in enumerate(expected_reader,1):
                    n=next(native_reader);assert int(n['packet_id'])==count-1
                    for keyfield in n:
                        if n[keyfield]!=r[keyfield]:raise AssertionError((key,accounting,count,keyfield,n[keyfield],r[keyfield]))
                assert next(native_reader,None) is None
            total+=count;receipts.append(dict(file=result_path.name,rows=count,sha256=sha(result_path),fields_exact=True))
            print(f'native FIFO exact {key}/{accounting}: {count}',flush=True)
    audit=dict(status='PASS_ALL_PACKET_NATIVE_FIFO_DIFFERENTIAL',runs=len(receipts),rows=total,
        receipts=receipts,freeze_sha256=sha(out/'frozen.json'),executable_sha256=sha(executable),
        priority_equivalence=False,full_emulator_equivalence=False,independent_expert=False)
    (out/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps({k:v for k,v in audit.items() if k!='receipts'}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.out)
