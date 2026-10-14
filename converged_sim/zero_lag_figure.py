"""Plot audited within-input control tails before/after removing staleness."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from .scientific_figures import start,text,line,save
from ns3_validation.renewal_cli import digest


def plot(source,out):
    source=Path(source);a=json.loads((source/'audit.json').read_text())
    if a['status']!='PASS' or digest(source/'pairs.csv')!=a['pairs_sha256']:raise ValueError('audited pairs required')
    with (source/'pairs.csv').open() as h:rows=list(csv.DictReader(h))
    ymax=max(1.4,max(float(r['lag05_control_p99_T']) for r in rows)*1.08)
    svg=start(1060,480,'Removing stale feedback does not eliminate biased-feedback failure')
    for panel,bias in enumerate((0,.06)):
        x0,y0,w,h=70+panel*530,70,420,285
        def yy(v):return y0+h-v/ymax*h
        text(svg,x0,y0-25,f'Control P99 / T, additive bias e={bias:g}',14)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        for j in range(5):
            v=ymax*j/4;text(svg,x0-8,yy(v)+4,f'{v:.3g}',11,'end')
        line(svg,x0,yy(1),x0+w,yy(1),'#999',True)
        for j,mode in enumerate(('lowfirst','highfirst','coinflip')):
            cohort=[r for r in rows if r['ordering']==mode and float(r['bias'])==bias]
            if len(cohort)!=10:raise ValueError('ten pairs required')
            x=x0+(j+.5)*w/3
            for k,row in enumerate(cohort):
                jitter=((k*7)%11-5)*.8
                line(svg,x-14+jitter,yy(float(row['lag05_control_p99_T'])),x+14+jitter,yy(float(row['lag0_control_p99_T'])),'#bbb')
            for lag,offset,color in (('lag05',-14,'#888'),('lag0',14,'#0072B2')):
                values=[float(r[lag+'_control_p99_T']) for r in cohort]
                for k,v in enumerate(values):
                    jitter=((k*7)%11-5)*.8
                    svg.append(f'<circle cx="{x+offset+jitter}" cy="{yy(v)}" r="2.5" fill="{color}"/>')
                median=statistics.median(values);line(svg,x+offset-9,yy(median),x+offset+9,yy(median),color)
            text(svg,x,y0+h+24,mode,12,'middle')
    text(svg,70,413,'Gray: lag .5T; blue: lag0. Lines join the same seed/source/service input. Bars show run-P99 medians.',12)
    text(svg,70,440,'Generated rho .95, PMR3/8T, source Q16. All bulk delivered; cost metrics are reported separately.',12)
    text(svg,70,464,'Ten paired inputs per cell, exploratory follow-up; not new independent reliability trials or a novelty certificate.',11)
    save(svg,out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();plot(a.input,a.out)
