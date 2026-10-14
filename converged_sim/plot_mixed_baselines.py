"""Dependency-free scientific SVG from audited saved baseline summaries only."""
import argparse
import csv
import json
import math
from pathlib import Path
from .coarse_observation import sha
from .scientific_figures import start,text,line,save

def run(mixed,pushout,out):
    mixed=Path(mixed);pushout=Path(pushout);out=Path(out)
    if out.exists():raise FileExistsError(out)
    combined=[]
    for directory in (mixed,pushout):
        manifest=json.loads((directory/'manifest.json').read_text())
        assert sha(directory/'runs.csv')==manifest['runs_sha256']
        with (directory/'runs.csv').open(newline='') as h:
            combined.extend(r for r in csv.DictReader(h) if r.get('accounting','accepted')=='accepted')
    colors={'fifo':'#333333','priority':'#0072B2','priority_pushout':'#D55E00'}
    labels={'fifo':'FIFO','priority':'Priority','priority_pushout':'Priority + push-out'}
    svg=start(1000,510,'Paired mean load: delivered tails and deadline failures')
    for panel in (0,1):
        x0,y0,w,h=70+panel*505,85,380,250
        def xx(v):return x0+(v-.18)/.75*w
        def yy(v):
            fraction=(v-.8)/1.8 if panel==0 else math.log(v/.00007)/math.log(.09/.00007)
            return y0+h-fraction*h
        text(svg,x0,y0-22,'(a) Delivered control P99 / T' if panel==0 else '(b) Control miss fraction at 40 ms',13)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        for v in (.2,.6,.9):text(svg,xx(v),y0+h+20,f'{v:g}',11,'middle')
        for v in ((1,1.5,2,2.5) if panel==0 else (.0001,.001,.01)):
            line(svg,x0,yy(v),x0+w,yy(v),'#dddddd');text(svg,x0-8,yy(v)+4,f'{v:g}',11,'end')
        references=[(1,'Primary D/T = 1'),(2,'Sensitivity D/T = 2')] if panel==0 else [(.01,'1% miss limit')]
        for value,label in references:
            line(svg,x0,yy(value),x0+w,yy(value),'#777777',True);text(svg,x0+8,yy(value)-7,label,10)
        for policy,color in colors.items():
            for pmr in ('1','3'):
                chosen=sorted([r for r in combined if r['policy']==policy and r['pmr']==pmr],key=lambda r:float(r['rho_actual']))
                assert len(chosen)==3
                coords=[(xx(float(r['rho_actual'])),yy(float(r['control_p99_ms'])/20 if panel==0 else float(r['control_miss_40ms']))) for r in chosen]
                for a,b in zip(coords,coords[1:]):line(svg,*a,*b,color,pmr=='1')
                for x,y in coords:
                    svg.append(f'<circle cx="{x}" cy="{y}" r="3" fill="white" stroke="{color}"/>' if pmr=='1' else f'<rect x="{x-3}" y="{y-3}" width="6" height="6" fill="{color}"/>')
        text(svg,x0+w/2,y0+h+44,'Offered work / trace PDO budget',12,'middle')
    for i,(policy,pmr) in enumerate((p,m) for p in colors for m in ('1','3')):
        x=75+(i//2)*300;y=407+(i%2)*23
        line(svg,x,y,x+24,y,colors[policy],pmr=='1');text(svg,x+32,y+4,f'{labels[policy]}, PMR {pmr}',12)
    caption='One reused development prefix; no independent-trial CI. All primary 20-ms cases fail.'
    text(svg,70,470,caption,12)
    text(svg,70,492,'40 ms is prespecified sensitivity; miss includes losses/unfinished. Push-out is an existing baseline.',11)
    out.mkdir(parents=True);save(svg,out/'paired_baselines.svg')
    full_caption=caption+' Source volumes and service are paired within each load; accepted-only accounting, 16 waiting slots. Nominal PMR uses integer-ms timing. Lines join measured grid points, not fitted collapse thresholds. Delivered-only P99 may increase when previously lost controls are recovered.'
    (out/'caption.txt').write_text(full_caption)
    (out/'manifest.json').write_text(json.dumps(dict(renderer='existing project SVG primitives',
        input_runs_sha256=[sha(d/'runs.csv') for d in (mixed,pushout)],
        svg_sha256=sha(out/'paired_baselines.svg'),caption=full_caption),indent=2))
    print(json.dumps(dict(status='FIGURE_FROM_SAVED_SUMMARIES',out=str(out))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mixed',required=True);p.add_argument('--pushout',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.mixed,a.pushout,a.out)
