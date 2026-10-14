"""Seed variability and simultaneous run reliability, audited V10 only."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from .scientific_figures import start,text,line,save
from ns3_validation.renewal_cli import digest


def plot(analysis,reliability,out):
    analysis=Path(analysis);reliability=Path(reliability)
    a=json.loads((analysis/'audit.json').read_text());r=json.loads((reliability/'audit.json').read_text())
    if a['status']!='PASS' or r['status']!='PASS' or r['audit_sha256']!=digest(analysis/'audit.json'):
        raise ValueError('matched endpoint and reliability audits required')
    with (analysis/'runs.csv').open() as h: rows=list(csv.DictReader(h))
    with (reliability/'points.csv').open() as h: points=list(csv.DictReader(h))
    ymax=max(1.2,max(float(x['control_p99_T']) for x in rows)*1.1)
    svg=start(1040,495,'Nonperiodic service: seed-level tail delay and run reliability')
    settings=[('feedback',0,'Feedback e=0','#0072B2'),('feedback',.06,'Feedback e=.06','#D55E00'),('none',0,'Priority','#009E73')]
    for ci in (0,1):
        x0,y0,w,h=75+ci*520,80,405,280
        text(svg,x0,y0-24,'Control P99 / T' if ci==0 else 'Joint SLO pass probability',14)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        def yy(v): return y0+h-v/(ymax if ci==0 else 1)*h
        for j in range(5):
            value=(ymax if ci==0 else 1)*j/4
            text(svg,x0-8,yy(value)+4,f'{value:.3g}',11,'end')
        line(svg,x0,yy(1 if ci==0 else .9),x0+w,yy(1 if ci==0 else .9),'#999',True)
        for j,(mode,bias,label,color) in enumerate(settings):
            x=x0+(j+.5)*w/3
            cohort=[p for p in rows if p['shape']==mode and float(p['bias'])==bias]
            p=next(p for p in points if p['shape']==mode and float(p['bias'])==bias)
            if len(cohort)!=70: raise ValueError('expected 70 fresh trials')
            if ci==0:
                for k,row in enumerate(cohort):
                    jitter=((k*37)%70-34.5)/70*25
                    svg.append(f'<circle cx="{x+jitter}" cy="{yy(float(row["control_p99_T"]))}" r="2" fill="{color}" opacity=".5"/>')
                median=statistics.median(float(p['control_p99_T']) for p in cohort)
                line(svg,x-15,yy(median),x+15,yy(median),'black')
            else:
                y=yy(float(p['observed_run_pass_fraction']));lower=yy(float(p['familywise_lower_95']))
                svg.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>')
                svg.append(f'<rect x="{x-4}" y="{lower-4}" width="8" height="8" fill="{color}"/>')
                text(svg,x,y0-8,f'{p["successes"]}/70',12,'middle')
            text(svg,x,y0+h+24,label,12,'middle')
    text(svg,70,416,'70 fresh paired service seeds; generated load .95; PMR3/8T; delayed telemetry .5T; source Q=16.',12)
    text(svg,70,441,'Left: individual run P99 and median tick, not independent packets. Right: circles observed pass fraction;',12)
    text(svg,70,461,'squares one-sided Clopper-Pearson lower bounds (95% simultaneous over 3 cells). Target q=.90.',12)
    text(svg,70,483,'Synthetic balanced random-duration service, not a measured radio trace. Bulk loss/source waiting reported separately.',12)
    save(svg,out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--analysis',required=True);p.add_argument('--reliability',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();plot(a.analysis,a.reliability,a.out)
