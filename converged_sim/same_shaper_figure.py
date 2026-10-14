"""Plot source-matched scheduling effects from audited per-run pairs."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from .scientific_figures import start,text,line,save
from ns3_validation.renewal_cli import digest


def plot(source,out):
    source=Path(source);a=json.loads((source/'audit.json').read_text())
    if a['status']!='PASS' or digest(source/'pairs.csv')!=a['outputs_sha256']['pairs.csv']:raise ValueError('audited actual-source pairs required')
    with (source/'pairs.csv').open() as h:rows=list(csv.DictReader(h))
    settings=[(.9,4),(.95,4),(.9,12),(.95,12)]
    svg=start(1080,540,'Identical source shaping and buffer: FIFO versus priority scheduling')
    for panel,name,limit in ((0,'control_p99_T',2.),(1,'bulk_p99_T',12.)):
        x0,y0,w,h=65+panel*540,75,435,300
        def yy(v):return y0+h-v/limit*h
        text(svg,x0,y0-22,'Control P99 / T' if panel==0 else 'Bulk source-to-sink P99 / T',14)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        for k in range(5):text(svg,x0-8,yy(limit*k/4)+4,f'{limit*k/4:g}',11,'end')
        if panel==0:line(svg,x0,yy(1),x0+w,yy(1),'#999',True)
        for j,(rho,ts) in enumerate(settings):
            cohort=[r for r in rows if float(r['rho'])==rho and float(r['tauS'])==ts]
            if len(cohort)!=70:raise ValueError('complete source-matched cohort')
            x=x0+(j+.5)*w/4
            for k,r in enumerate(cohort):
                jitter=((k*13)%17-8)*.45
                line(svg,x-13+jitter,yy(float(r['fifo_'+name])),x+13+jitter,yy(float(r['priority_'+name])),'#ddd')
            for policy,dx,color in (('fifo',-13,'#0072B2'),('priority',13,'#D55E00')):
                v=statistics.median(float(r[policy+'_'+name]) for r in cohort)
                svg.append(f'<circle cx="{x+dx}" cy="{yy(v)}" r="4" fill="{color}"/>')
            text(svg,x,y0+h+22,f'rho {rho:g}',11,'middle');text(svg,x,y0+h+39,f'scale {ts:g}T',11,'middle')
    text(svg,65,447,'Blue: shaped FIFO; orange: identically shaped priority. Lines join the same source-release/service input.',12)
    text(svg,65,471,'70 pairs/cell; source Q16/B.1, bias .06, lag .5T. Both policies fully deliver bulk in every run.',12)
    text(svg,65,495,'Priority control improves in every pair. At high load, small bulk-P99 increases remain; not strict Pareto dominance.',11)
    text(svg,65,519,'Post-V15 matched intervention, not 280 new independent service draws or proof of a novel algorithm.',11)
    save(svg,out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();plot(a.input,a.out)
