"""Descriptive paired stage/loss accounting, not a causal novelty test."""
import argparse
import csv
import json
from pathlib import Path
from .coarse_observation import sha
from .audit_cellreplay_mixed import read_rows
from .cellreplay_development_screen import quantile

def run(input_path,out):
    p=Path(input_path);out=Path(out)
    if out.exists():raise FileExistsError(out)
    cfg=json.loads((p/'frozen.json').read_text())['config']
    manifest=json.loads((p/'manifest.json').read_text());receipts={r['file']:r for r in manifest['receipts']}
    assert sha(p/'runs.csv')==manifest['runs_sha256']
    with (p/'runs.csv').open(newline='') as h:configs=list(csv.DictReader(h))
    stats=[]
    for c in configs:
        path=p/c['packet_file'];assert sha(path)==receipts[path.name]['sha256']
        rows=[r for r in read_rows(path) if r['flow']==1 and r['arrival_ms']>=cfg['warm_ms']]
        delivered=[r for r in rows if r['status']=='completed']
        values=dict(rho=c['rho_target'],pmr=c['pmr'],policy=c['policy'],accounting=c['accounting'],
            count=len(rows),planned_p99_ms=quantile([r['planned_delay_ms'] for r in rows],.99),
            delivered_total_p99_ms=quantile([r['delay_ms'] for r in delivered],.99),
            delivered_post_plan_p99_ms=quantile([r['finish_ms']-r['release_ms'] for r in delivered],.99),
            planned_heavy_flags=sum(not r['planned_light_bypass'] for r in rows),
            release_clamps=sum(r['release_clamped'] for r in rows))
        for d in cfg['deadlines_ms']:
            categories=dict(admission_loss=0,unfinished=0,planned_late_delivered=0,post_plan_late_delivered=0,on_time=0)
            for r in rows:
                if r['status']=='dropped':category='admission_loss'
                elif r['status']=='unfinished':category='unfinished'
                elif r['planned_delay_ms']>=d:category='planned_late_delivered'
                elif r['delay_ms']>=d:category='post_plan_late_delivered'
                else:category='on_time'
                categories[category]+=1
            assert sum(categories.values())==len(rows)
            for k,v in categories.items():values[f'{d}ms_{k}']=v
        stats.append(values)
    out.mkdir(parents=True)
    with (out/'stages.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(stats[0]));w.writeheader();w.writerows(stats)
    audit=dict(status='COMPLETE_DESCRIPTIVE_STAGE_ACCOUNTING',runs=len(stats),
        source_manifest_sha256=sha(p/'manifest.json'),stages_sha256=sha(out/'stages.csv'),
        scope='disjoint miss accounting; quantiles of stages do not sum')
    (out/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.input,a.out)
