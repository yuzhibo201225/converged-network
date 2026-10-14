"""Source-method native synthetic counter/service reproduction; not radio."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess
from .coarse_observation import sha

def run(out):
    root=Path(__file__).resolve().parents[1];out=Path(out)
    if out.exists():raise FileExistsError(out)
    source=root/'results/cellreplay_code_source_v21/src/frontend/cellular_queue.cc'
    text=source.read_text()
    methods=text[text.index('uint64_t CellularQueue::next_delivery_time'):text.index('DelayQueuePacket CellularQueue::get_next_from_delay_queue')]
    if methods.count('CellularQueue::')!=3:raise ValueError('method boundary mismatch')
    queue=root/'results/cellreplay_queue_source_v24'
    manifest=json.loads((queue/'manifest.json').read_text())
    for name,info in manifest['files'].items():
        if sha(queue/name)!=info['sha256']:raise ValueError('queue source mismatch')
    template=root/'ns3_validation/cellreplay_service_fixture.cc'
    out.mkdir(parents=True)
    freeze=dict(source_sha256=sha(source),queue_manifest_sha256=sha(queue/'manifest.json'),
        template_sha256=sha(template),runner_sha256=sha(__file__),
        protocol_sha256=sha(root/'q2_upgrade/SERVICE_COUNTER_PROTOCOL_V26.md'),
        source_methods='three contiguous methods; only class qualifier renamed',
        heavy_schedule_ms=[100,200,300,400],light_probe_ms=201,
        reserved_members_opened=0,radio_measurement=False)
    (out/'frozen.json').write_text(json.dumps(freeze,indent=2))
    generated=template.read_text().replace('// INJECT_PINNED_METHODS',methods.replace('CellularQueue::','Fixture::'))
    (out/'generated.cc').write_text(generated)
    (out/'exception.hh').write_text('#pragma once\n#include <stdexcept>\n')
    (out/'ezio.hh').write_text('#pragma once\n#include <string>\ninline unsigned myatoi(const std::string& s) { return std::stoul(s); }\n')
    compiler=Path('C:/msys64/mingw64/bin/g++.exe');env=dict(os.environ)
    env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
    command=[str(compiler),'-std=c++17','-O2','-static','-include','cstdint','-I',str(queue/'src/packet'),'-I',str(out),
        str(out/'generated.cc'),str(queue/'src/packet/dropping_packet_queue.cc'),'-o',str(out/'service.exe')]
    build=subprocess.run(command,env=env,capture_output=True,text=True)
    (out/'build.json').write_text(json.dumps(dict(command=command,returncode=build.returncode,stdout=build.stdout,stderr=build.stderr),indent=2))
    build.check_returncode()
    result=subprocess.run([str((out/'service.exe').resolve())],capture_output=True,text=True,check=True)
    (out/'outcomes.csv').write_text(result.stdout)
    rows=list(csv.DictReader(io.StringIO(result.stdout)))
    assert [r['excess_ms'] for r in rows]==['99','0','0']
    assert [r['final_counter'] for r in rows]==['1','0','0']
    audit=dict(status='PASS_NATIVE_SYNTHETIC_TIMING_COUNTEREXAMPLE',outcomes=rows,
        freeze_sha256=sha(out/'frozen.json'),generated_sha256=sha(out/'generated.cc'),
        raw_sha256=sha(out/'outcomes.csv'),synthetic=True,full_emulator=False,new_method=False)
    (out/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);run(p.parse_args().out)
