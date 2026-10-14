"""Exploratory seed-level delay and bulk cost under matched service reordering."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from .scientific_figures import start, text, line, save
from ns3_validation.renewal_cli import digest


def plot(analysis, out):
    analysis=Path(analysis)
    receipt=json.loads((analysis/'audit.json').read_text())
    if receipt['status']!='PASS' or digest(analysis/'runs.csv')!=receipt['runs_sha256']:
        raise ValueError('matched raw audit required')
    with (analysis/'runs.csv').open() as handle: rows=list(csv.DictReader(handle))
    settings=[('feedback',0,'Feedback e=0','#0072B2'),('feedback',.06,'Feedback e=.06','#D55E00'),('none',0,'Priority','#009E73')]
    modes=('random','ascending','descending')
    svg=start(1080,500,'Same dwell multiset, different service order')
    for panel,field in enumerate(('control_p99_T','bulk_p99_T')):
        x0,y0,w,h=70+panel*540,75,430,290
        ymax=max(1.2,max(float(r[field]) for r in rows)*1.12)
        def yy(value): return y0+h-value/ymax*h
        text(svg,x0,y0-25,'Control P99 / T' if panel==0 else 'Bulk P99 / T (includes source waiting)',14)
        line(svg,x0,y0,x0,y0+h); line(svg,x0,y0+h,x0+w,y0+h)
        for tick in range(5):
            v=ymax*tick/4; text(svg,x0-8,yy(v)+4,f'{v:.3g}',11,'end')
        if panel==0: line(svg,x0,yy(1),x0+w,yy(1),'#999',True)
        for m,mode in enumerate(modes):
            center=x0+(m+.5)*w/3
            for j,(shape,bias,label,color) in enumerate(settings):
                cohort=[r for r in rows if r['ordering']==mode and r['shape']==shape and float(r['bias'])==bias]
                if len(cohort)!=10: raise ValueError('expected ten paired seeds')
                x=center+(j-1)*32
                values=[float(r[field]) for r in cohort]
                for r,v in zip(cohort,values):
                    jitter=((int(r['run'])*7)%11-5)*1.1
                    svg.append(f'<circle cx="{x+jitter}" cy="{yy(v)}" r="2.4" fill="{color}" opacity=".65"/>')
                median=statistics.median(values);line(svg,x-9,yy(median),x+9,yy(median),color)
            text(svg,center,y0+h+22,mode,12,'middle')
    for j,(_,_,label,color) in enumerate(settings):
        x=100+j*310;line(svg,x,413,x+20,413,color);text(svg,x+27,418,label,13)
    text(svg,70,450,'Ten fresh paired seeds per cell; offered load .95; PMR3/8T. Dots are run P99; bars are medians.',12)
    text(svg,70,473,'Low/high capacity, mean service and dwell multisets fixed. Sorting changes temporal trend and source alignment.',12)
    text(svg,70,494,'Exploratory mechanism test, not a stationary radio trace, reliability certificate or held-out safety-guard test.',11)
    save(svg,out)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--out',required=True)
    a=parser.parse_args();plot(a.input,a.out)
