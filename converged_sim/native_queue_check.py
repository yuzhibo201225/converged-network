"""Native finite-queue admission/counter coupling check, not full CellReplay."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess
from .coarse_observation import sha

def audit_rows(rows):
    final = {r['variant']: r for r in rows if r['event']=='drained'}
    expected = {'original_drop': ('0','1','1','0'),
                'original_no_drop': ('0','0','0','1'),
                'corrected_drop': ('0','0','1','1')}
    for variant, values in expected.items():
        actual = tuple(final[variant][k] for k in ('resident','counter','dropped','light_bypass'))
        if actual != values: raise AssertionError((variant, actual, values))
    for r in rows:
        if r['variant'].startswith('original'):
            assert int(r['counter'])-int(r['resident']) == int(r['dropped'])
        else: assert r['counter'] == r['resident']
    return final

def run(out):
    out = Path(out)
    if out.exists(): raise FileExistsError(out)
    root = Path(__file__).resolve().parents[1]
    source = root/'results/cellreplay_queue_source_v24'
    m = json.loads((source/'manifest.json').read_text())
    for name, info in m['files'].items():
        if sha(source/name) != info['sha256']: raise ValueError('source hash mismatch')
    cellular = root/'results/cellreplay_code_source_v21/src/frontend/cellular_queue.cc'
    text = cellular.read_text()
    for snippet in ('current_link_queue_size_ += 1;',
                    'current_link_queue_size_ = current_link_queue_size_ - 1;',
                    'next_packet.is_bypass_link_queue && current_link_queue_size_ == 0'):
        if snippet not in text: raise ValueError('coupling snippet mismatch')
    fixture = root/'ns3_validation/cellreplay_queue_fixture.cc'
    compiler = Path('C:/msys64/mingw64/bin/g++.exe')
    out.mkdir(parents=True)
    env = dict(os.environ)
    env['PATH'] = str(compiler.parent) + os.pathsep + env.get('PATH', '')
    freeze = dict(source_manifest_sha256=sha(source/'manifest.json'),
                  cellular_sha256=sha(cellular), fixture_sha256=sha(fixture),
                  runner_sha256=sha(__file__), compiler_sha256=sha(compiler),
                  scope='native queue core and source-derived counter/bypass coupling only',
                  no_network=True, reserved_members_opened=0,
                  in_transit_and_output_buffers='omitted; all accepted packets drained before probe',
                  adapters='exception header empty; ezio myatoi delegates to std::stoul')
    (out/'freeze.json').write_text(json.dumps(freeze, indent=2))
    # Explicit tiny build adapters, not replacements for queue admission code.
    (out/'exception.hh').write_text('#pragma once\n#include <stdexcept>\n')
    (out/'ezio.hh').write_text('#pragma once\n#include <string>\ninline unsigned myatoi(const std::string& s) { return std::stoul(s); }\n')
    executable = out/'queue_fixture.exe'
    command = [str(compiler), '-std=c++17', '-O2', '-ffp-contract=off', '-static',
               '-include', 'cstdint', '-I', str(source/'src/packet'), '-I', str(out),
               str(fixture), str(source/'src/packet/dropping_packet_queue.cc'), '-o', str(executable)]
    build = subprocess.run(command, env=env, capture_output=True, text=True)
    (out/'build.json').write_text(json.dumps(dict(command=command, returncode=build.returncode,
                                             stdout=build.stdout, stderr=build.stderr), indent=2))
    build.check_returncode()
    native = subprocess.run([str(executable.resolve())], capture_output=True, text=True, check=True)
    (out/'events.csv').write_text(native.stdout)
    rows = list(csv.DictReader(io.StringIO(native.stdout)))
    final = audit_rows(rows)
    audit = dict(status='PASS_NATIVE_CORE_COUNTEREXAMPLE', rows=len(rows),
                 source_queue_compiled_unchanged=True, events_sha256=sha(out/'events.csv'),
                 executable_sha256=sha(executable), freeze_sha256=sha(out/'freeze.json'),
                 native_full_cellreplay=False, radio_measurement=False,
                 new_congestion_method=False, drained_outcomes=final)
    (out/'audit.json').write_text(json.dumps(audit, indent=2))
    print(json.dumps(audit))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True)
    run(p.parse_args().out)
