"""Plot checked prospective law admission outcomes and full-delivery costs."""
import argparse
import csv
import json
from pathlib import Path
from .scientific_figures import start,text,line,save
from ns3_validation.renewal_cli import digest


def plot(source,out):
    source=Path(source);a=json.loads((source/'audit.json').read_text())
    if a['status']!='PASS' or digest(source/'points.csv')!=a['outputs_sha256']['points.csv']:raise ValueError('checked native points required')
    with (source/'points.csv').open() as h:rows=list(csv.DictReader(h))
    svg=start(1090,555,'Known-law admission: independent native validation and delivery costs')
    settings=[(.9,4),(.95,4),(.9,12),(.95,12)]
    for panel in (0,1):
        x0,y0,w,h=65+panel*550,80,440,300
        yy=(lambda v:y0+h-v/2*h) if panel==0 else (lambda v:y0+h-v*h)
        text(svg,x0,y0-23,'Run-level control P99 / T' if panel==0 else 'Run fraction meeting control + full bulk delivery',14)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        for v in ((0,.5,1,1.5,2) if panel==0 else (0,.25,.5,.75,1)):
            text(svg,x0-7,yy(v)+4,f'{v:g}',11,'end')
        if panel==0:line(svg,x0,yy(1),x0+w,yy(1),'#aaa',True)
        for j,(rho,ts) in enumerate(settings):
            offset=12 if panel==0 else 23
            for policy,dx,color in (('fifo',-offset,'#0072B2'),('priority',offset,'#D55E00')):
                cohort=[r for r in rows if float(r['rho'])==rho and float(r['tauS'])==ts and r['queue']==policy]
                if len(cohort)!=1:raise ValueError('unique native cell')
                r=cohort[0];x=x0+(j+.5)*w/4+dx
                if panel==0:
                    v=float(r['control_p99_T_median']);line(svg,x,yy(float(r['control_p99_T_min'])),x,yy(float(r['control_p99_T_max'])),color)
                else:
                    v=int(r['joint_successes'])/int(r['n']);line(svg,x,yy(float(r['simultaneous_lower'])),x,yy(v),color)
                svg.append(f'<circle cx="{x}" cy="{yy(v)}" r="4" fill="{color}"/>')
                if panel==1:text(svg,x,yy(v)-10,r['joint_successes']+'/70',10,'middle')
            x=x0+(j+.5)*w/4
            text(svg,x,y0+h+23,f'rho {rho:g}',11,'middle');text(svg,x,y0+h+40,f'scale {ts:g}T',11,'middle')
    text(svg,65,452,'Blue: feedback FIFO (source Q16); orange: unshaped priority (no active source waiting).',12)
    text(svg,65,476,'Control bars: median/range across 70 draws. Joint bars: eight-cell simultaneous 95% lower bound.',12)
    text(svg,65,500,'Frozen known-law rule admits first three cells. All priority control cells pass; slow-profile bulk non-delivery retained.',11)
    text(svg,65,524,'Unequal active buffering is a confound: this is NOT proof of superiority or novelty. Same-shaper priority test required.',11)
    save(svg,out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();plot(a.input,a.out)
