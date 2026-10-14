"""Falsifiable source invariant on saved paired development replay outputs."""
import argparse
import csv
import gzip
import json
from pathlib import Path
from .coarse_observation import sha

def run(input_path,out):
    p=Path(input_path);out=Path(out);root=Path(__file__).resolve().parents[1]
    if out.exists():raise FileExistsError(out)
    manifest=json.loads((p/'manifest.json').read_text());f=json.loads((p/'frozen.json').read_text())
    assert sha(p/'runs.csv')==manifest['runs_sha256']
    with (p/'runs.csv').open(newline='') as h:runs=list(csv.DictReader(h))
    source=root/'results/cellreplay_code_source_v21/src/frontend/cellular_queue.cc'
    source_manifest=json.loads((root/'results/cellreplay_code_source_v21/manifest.json').read_text())
    assert sha(source)==source_manifest['files']['src/frontend/cellular_queue.cc']['sha256']
    text=source.read_text()
    for fragment in ('current_link_queue_size_ += 1;',
                     'current_link_queue_size_ = current_link_queue_size_ - 1;',
                     'next_packet.is_bypass_link_queue && current_link_queue_size_ == 0'):
        assert fragment in text
    receipts={r['file']:r for r in manifest['receipts']}
    out.mkdir(parents=True)
    frozen=dict(input_manifest_sha256=sha(p/'manifest.json'),source_sha256=sha(source),
        model_sha256={name:sha(root/name) for name in ('converged_sim/absorbing_counter_check.py',
            'q2_upgrade/ABSORBING_COUNTER_PROTOCOL_V30.md')},scope='implementation invariant; not novelty confirmation')
    (out/'frozen.json').write_text(json.dumps(frozen,indent=2));results=[]
    for config in [r for r in runs if r['accounting']=='original']:
        path=p/config['packet_file'];assert sha(path)==receipts[path.name]['sha256']
        first=None;eligible=0;violation=0;all_rows=0
        with gzip.open(path,'rt') as h:
            for r in csv.DictReader(h):
                all_rows+=1
                if first is None and r['status']=='dropped':first=(int(r['packet_id']),int(r['release_ms']))
                elif first is not None and int(r['release_ms'])<=f['config']['end_ms'] and r['planned_light_bypass']=='True':
                    eligible+=1;violation+=int(r['actual_bypass']=='True')
        assert violation==0
        corrected=next(r for r in runs if r['rho_target']==config['rho_target'] and r['pmr']==config['pmr']
            and r['policy']==config['policy'] and r['accounting']=='accepted')
        fixed=p/corrected['packet_file'];assert sha(fixed)==receipts[fixed.name]['sha256']
        recovered=0
        if first is not None:
            with gzip.open(fixed,'rt') as h:
                for r in csv.DictReader(h):
                    if int(r['packet_id'])>first[0] and int(r['release_ms'])<=f['config']['end_ms']:
                        recovered+=int(r['actual_bypass']=='True')
        results.append(dict(rho=config['rho_target'],pmr=config['pmr'],policy=config['policy'],rows=all_rows,
            first_refusal_id=first[0] if first else None,first_refusal_release_ms=first[1] if first else None,
            subsequent_planned_light_packets=eligible,observed_bypass_violations=violation,
            corrected_recovered_bypasses=recovered))
        print(f"checked absorbing invariant {config['rho_target']}/{config['pmr']}/{config['policy']}",flush=True)
    (out/'results.json').write_text(json.dumps(results,indent=2))
    audit=dict(status='PASS_SAVED_ABSORBING_INVARIANT',original_runs=len(results),
        refusal_runs=sum(r['first_refusal_id'] is not None for r in results),
        subsequent_planned_light_packets=sum(r['subsequent_planned_light_packets'] for r in results),
        contradictions=sum(r['observed_bypass_violations'] for r in results),
        corrected_recovered_bypasses=sum(r['corrected_recovered_bypasses'] for r in results),
        frozen_sha256=sha(out/'frozen.json'),results_sha256=sha(out/'results.json'),
        scope='source conservation plus development raw falsification; no expert/novelty certificate')
    (out/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.out)
