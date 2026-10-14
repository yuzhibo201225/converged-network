"""Audited synthetic observation-ambiguity figure, no physical-radio inference."""
import argparse
import csv
import json
import math
from pathlib import Path
from .coarse_observation import sha
from .scientific_figures import start,text,line,save


def plot(source,out):
    source=Path(source);audit=json.loads((source/'audit.json').read_text())
    if audit['status']!='PASS' or sha(source/'points.csv')!=audit['points_sha256']:raise ValueError('audited points required')
    with (source/'points.csv').open() as h:rows=list(csv.DictReader(h))
    svg=start(1100,570,'Same one-second service totals, different within-second schedules')
    colors={'constant':'#333333','fine':'#0072B2','coarse':'#D55E00'}
    for panel,queue in enumerate(('fifo','priority')):
        group=[r for r in rows if r['queue']==queue]
        maximum=max(float(r['control_p99_max_T']) for r in group)
        limit=math.ceil(max(1.1,maximum)*10)/10
        x0,y0,w,h=70+panel*545,80,440,320
        def xx(v):return x0+(v-.2)/.75*w
        def yy(v):return y0+h-v/limit*h
        text(svg,x0,y0-23,f'{queue.upper()}: Control P99 / T',14)
        text(svg,x0,y0-5,'Separate vertical scales; bars are five-seed ranges',11)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        for v in (.2,.4,.6,.8,.95):text(svg,xx(v),y0+h+20,f'{v:g}',11,'middle')
        for i in range(6):
            v=limit*i/5;text(svg,x0-8,yy(v)+4,f'{v:.2g}',11,'end')
        line(svg,x0,yy(1),x0+w,yy(1),'#999',True)
        for profile,color in colors.items():
            curve=sorted((r for r in group if r['profile']==profile),key=lambda r:float(r['rho']))
            previous=None
            for r in curve:
                x=xx(float(r['rho']));y=yy(float(r['control_p99_median_T']))
                line(svg,x,yy(float(r['control_p99_min_T'])),x,yy(float(r['control_p99_max_T'])),color)
                if previous:line(svg,*previous,x,y,color)
                svg.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"/>');previous=(x,y)
        text(svg,x0+w/2,y0+h+43,'Total mean offered load / nominal capacity',12,'middle')
        if queue=='priority':
            r=next(r for r in group if r['profile']=='coarse' and float(r['rho'])==.95)
            text(svg,x0+30,y0+142,f'Coarse rho .95: joint SLO {r["joint_pass_count"]}/{r["n"]}',13)
            text(svg,x0+30,y0+165,f'Median control miss: {100*float(r["control_miss_median"]):.2f}% (includes drops)',12)
            text(svg,x0+30,y0+188,'Good delivered-only P99 does not mean full delivery.',12)
    for i,(profile,color) in enumerate(colors.items()):
        x=80+330*i;line(svg,x,473,x+25,473,color);text(svg,x+32,478,profile,13)
    text(svg,70,506,'T=20ms; coarse observation=50T. Fine/coarse rates .7/1.3; constant rate1; identical arrival packets within pairs.',11)
    text(svg,70,531,'Synthetic integrated-service queue, no source shaping or MAC/TCP. Dashed: deadline1T. Not proof of innovation.',11)
    text(svg,70,551,'Delivered-only P99: see audited miss/drop/delivery tables before interpreting protection or admission.',11)
    save(svg,out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();plot(a.input,a.out)
