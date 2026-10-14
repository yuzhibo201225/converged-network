"""Protection/cost figure for audited V9 packet-engine corroboration."""
import argparse
import csv
import json
from pathlib import Path
from .scientific_figures import start,text,line,save


SETTINGS=[('none','fifo',0,'FIFO','#333333'),('none','priority',0,'Priority','#CC79A7'),
          ('none','fifo_packet',0,'Packet FIFO','#888888'),('none','fq_codel',0,'FQ-CoDel','#009E73'),
          ('fixed','fifo',0,'Fixed Q16','#E69F00'),('feedback','fifo',0,'Feedback e=0','#0072B2'),
          ('feedback','fifo',.06,'Feedback e=.06','#56B4E9'),('feedback','fifo',.1,'Feedback e=.10','#D55E00')]


def plot(directory,out):
    directory=Path(directory)
    if json.loads((directory/'audit.json').read_text())['status']!='PASS': raise ValueError('raw audit required')
    with (directory/'points.csv').open() as h: rows=list(csv.DictReader(h))
    svg=start(1190,795,'Packet-engine corroboration: control protection and bulk source-to-sink cost')
    for ri,pmr in enumerate((1,3)):
        for ci,rho in enumerate((.8,.95)):
            subset=[r for r in rows if float(r['R'])==pmr and float(r['rho'])==rho]
            if len(subset)!=8: raise ValueError('incomplete V9 cell')
            xmax=max(float(r['bulk_p99_T_max']) for r in subset)*1.08
            ymax=max(1.2,max(float(r['control_p99_T_max']) for r in subset)*1.08)
            x0,y0,w,h=70+ci*580,80+ri*310,455,230
            def xy(x,y): return x0+x/xmax*w,y0+h-y/ymax*h
            text(svg,x0,y0-19,f'Load {rho:g}; PMR{pmr}; source period {2 if pmr==1 else 8}T',14)
            line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
            _,dy=xy(0,1);line(svg,x0,dy,x0+w,dy,'#888',True)
            for j in range(5):
                x,y=xy(xmax*j/4,ymax*j/4)
                text(svg,x,y0+h+18,f'{xmax*j/4:.2g}',11,'middle')
                text(svg,x0-8,y+4,f'{ymax*j/4:.2g}',11,'end')
            text(svg,x0+w/2,y0+h+38,'Delivered bulk source-to-sink P99 / T',12,'middle')
            text(svg,x0,y0-37,'Control P99 / T',12)
            for r in subset:
                shape,queue,bias,label,color=next(s for s in SETTINGS if s[:3]==(r['shape'],r['queue'],float(r['bias'])))
                x,y=xy(float(r['bulk_p99_T_median']),float(r['control_p99_T_median']))
                lo,_=xy(float(r['bulk_p99_T_min']),0);hi,_=xy(float(r['bulk_p99_T_max']),0)
                _,bottom=xy(0,float(r['control_p99_T_min']));_,top=xy(0,float(r['control_p99_T_max']))
                line(svg,lo,y,hi,y,color);line(svg,x,bottom,x,top,color)
                # Filled diamonds distinguish feedback; matching packet-capacity pair squares.
                if shape=='feedback': svg.append(f'<path d="M{x},{y-5} L{x+5},{y} L{x},{y+5} L{x-5},{y} Z" fill="{color}"/>')
                elif queue in ('fifo_packet','fq_codel'): svg.append(f'<rect x="{x-4}" y="{y-4}" width="8" height="8" fill="{color}"/>')
                else: svg.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')
    for i,(_,_,_,label,color) in enumerate(SETTINGS):
        x=60+(i%4)*290;y=702+(i//4)*25
        line(svg,x,y,x+22,y,color);text(svg,x+29,y+4,label,12)
    text(svg,60,762,'Five paired phase runs per point; bars are seed ranges, not CIs. Bulk delivery/loss and admitted load are in the result table.',12)
    text(svg,60,784,'Alternating service, 8T dwell; feedback lag .5T. Only packet FIFO vs FQ-CoDel has matched packet capacity. No wireless MAC.',12)
    save(svg,out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();plot(a.input,a.out)
