"""Plot control protection alongside bulk delivery loss and source waiting."""
import argparse
import csv
import json
import math
from pathlib import Path
from .scientific_figures import start,text,line,save


def plot(directory,out):
    directory=Path(directory)
    if json.loads((directory/"audit.json").read_text())["status"]!="PASS": raise ValueError("raw audit required")
    with (directory/"points.csv").open() as h: rows=list(csv.DictReader(h))
    rows=[r for r in rows if float(r["rho"])==.95 and float(r["pmr"])==3 and float(r["tau_b"])==8]
    svg=start(1210,720,"Finite source memory: protection, bulk delivery and source to sink delay")
    fields=("control_p99_latency","bulk_delivery_ratio","bulk_p99_latency")
    labels=("Control P99 / T (log)","Bulk delivered / generated","Delivered bulk P99 / T")
    for ri,lag in enumerate((.5,2.)):
        for ci,field in enumerate(fields):
            x0,y0,w,h=70+ci*400,80+ri*270,310,200
            subset=[r for r in rows if r["mode"]!="feedback" or float(r["lag"])==lag]
            ymax=1 if ci==1 else max(float(r[field+"_max"]) for r in subset)*1.1
            ymin=.05 if ci==0 else 0
            def xy(bias,v):
                yy=math.log(v/ymin)/math.log(ymax/ymin) if ci==0 else v/ymax
                return x0+(bias+.1)/.2*w,y0+h-yy*h
            text(svg,x0,y0-20,f"Lag {lag:g}T: {labels[ci]}",13)
            line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
            ticks=[.1,.2,.5,1,2,5,10,20] if ci==0 else [ymax*i/4 for i in range(5)]
            for v in ticks:
                if ci==0 and not ymin<=v<=ymax: continue
                _,y=xy(-.1,v);text(svg,x0-8,y+4,f"{v:.2g}",11,"end")
            for bias in (-.1,0,.1):
                x,_=xy(bias,1);text(svg,x,y0+h+18,f"{bias:+.1f}",11,"middle")
            if ci==0:
                _,y=xy(-.1,1);line(svg,x0,y,x0+w,y,"#aaa")
            for capacity,color in ((2.,"#009E73"),(16.,"#0072B2")):
                curve=sorted((r for r in subset if r["mode"]=="feedback" and float(r["capacity"])==capacity),key=lambda r:float(r["bias"]))
                coords=[]
                for r in curve:
                    x,y=xy(float(r["bias"]),float(r[field+"_median"]));coords.append((x,y))
                    _,lo=xy(float(r["bias"]),float(r[field+"_min"]));_,hi=xy(float(r["bias"]),float(r[field+"_max"]))
                    line(svg,x,lo,x,hi,color);svg.append(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{color}"/>')
                for a,b in zip(coords,coords[1:]): line(svg,*a,*b,color)
                fixed=next(r for r in subset if r["mode"]=="fixed" and float(r["capacity"])==capacity)
                _,y=xy(0,float(fixed[field+"_median"]));line(svg,x0,y,x0+w,y,color,True)
            for mode,color in (("fifo","#333333"),("priority","#CC79A7")):
                r=next(r for r in subset if r["mode"]==mode);_,y=xy(0,float(r[field+"_median"]))
                line(svg,x0,y,x0+w,y,color,True)
            text(svg,x0+w/2,y0+h+37,"Additive capacity bias / (work per T)",11,"middle")
    legend=[("Feedback Q=2","#009E73",False),("Feedback Q=16","#0072B2",False),
        ("Fixed Q=2","#009E73",True),("Fixed Q=16","#0072B2",True),("FIFO","#333333",True),("Priority","#CC79A7",True)]
    for i,(label,color,dash) in enumerate(legend):
        x=60+i*190;line(svg,x,635,x+22,635,color,dash);text(svg,x+28,639,label,11)
    text(svg,60,675,"Load .95; PMR 3; bulk/service scales 8T; five paired seeds. Bars: seed ranges, not confidence intervals.",12)
    text(svg,60,696,"Bulk P99 is conditional on delivery and includes source waiting. Source loss reduces actual link load; not a free win.",12)
    save(svg,out)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();plot(a.input,a.out)
