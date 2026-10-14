"""Dependency-free scientific figures from audited endpoint tables only."""
import argparse
import csv
import json
import math
from pathlib import Path

COLORS=["#333333","#0072B2","#D55E00","#009E73","#CC79A7"]


def read(directory):
    directory=Path(directory)
    if json.loads((directory/"audit.json").read_text())["status"]!="PASS": raise ValueError("unaudited input")
    with (directory/"points.csv").open() as handle: return list(csv.DictReader(handle))


def text(svg,x,y,label,size=13,anchor="start"):
    svg.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Arial" font-size="{size}">{label}</text>')


def line(svg,x1,y1,x2,y2,color="black",dash=False):
    svg.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}"'+(' stroke-dasharray="5 4"' if dash else '')+'/>')


def start(width,height,title):
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',f'<rect width="{width}" height="{height}" fill="white"/>']
    text(svg,width/2,25,title,18,"middle")
    return svg


def save(svg,path):
    path=Path(path)
    if path.exists(): raise FileExistsError(path)
    svg.append('</svg>');path.write_text("\n".join(svg),encoding="utf-8")


def robustness(directory,path):
    points=read(directory)
    subset=[p for p in points if float(p["pmr"])==3 and float(p["tau_b"])==8]
    xmax=max(float(p["bulk_p99_latency_max"]) for p in subset)*1.08
    ymax=max(1.2,max(float(p["control_p99_latency_max"]) for p in subset)*1.08)
    svg=start(1120,810,"Protection and end to end bulk delay under long bursts")
    settings=[("fifo","", "FIFO"),("strict_priority","","Priority"),("drr","","DRR"),("fifo","0.1","Shaper B=0.1"),("fifo","0.5","Shaper B=0.5")]
    for ri,ts in enumerate((2.,8.)):
        for ci,rho in enumerate((.6,.8)):
            x0,y0,w,h=70+ci*540,75+ri*310,430,235
            text(svg,x0,y0-12,f"Load {rho}; service scale {ts:g}T")
            def xy(x,y): return x0+x/xmax*w,y0+h-y/ymax*h
            line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
            _,dy=xy(0,1);line(svg,x0,dy,x0+w,dy,"#888",True)
            for f in (0,.25,.5,.75,1):
                x,y=xy(f*xmax,f*ymax)
                text(svg,x,y0+h+16,f"{f*xmax:.1f}",11,"middle")
                text(svg,x0-8,y+4,f"{f*ymax:.1f}",11,"end")
            text(svg,x0+w/2,y0+h+34,"Bulk source to sink P99 / T",12,"middle")
            text(svg,x0,y0-28,"Control P99 / T",12)
            for p in subset:
                if float(p["rho"])!=rho or float(p["tau_s"])!=ts: continue
                color=COLORS[next(i for i,(pol,b,_) in enumerate(settings) if p["policy"]==pol and p["bucket"]==b)]
                x,y=xy(float(p["bulk_p99_latency_median"]),float(p["control_p99_latency_median"]))
                lo,_=xy(float(p["bulk_p99_latency_min"]),0);hi,_=xy(float(p["bulk_p99_latency_max"]),0)
                _,bottom=xy(0,float(p["control_p99_latency_min"]));_,top=xy(0,float(p["control_p99_latency_max"]))
                line(svg,lo,y,hi,y,color);line(svg,x,bottom,x,top,color)
                svg.append(f'<rect x="{x-4}" y="{y-4}" width="8" height="8" fill="{color}"/>' if p["jitter_service"]=="True" else f'<circle cx="{x}" cy="{y}" r="4" fill="white" stroke="{color}" stroke-width="2"/>')
    for i,(_,_,label) in enumerate(settings):
        x=60+i*210;line(svg,x,730,x+18,730,COLORS[i]);text(svg,x+23,735,label,12)
    text(svg,60,765,"Circles: fixed cycle widths; squares: jittered widths. Bars: five seed ranges, not confidence intervals.",12)
    text(svg,60,785,"PMR 3; nominal bulk cycle 8T. Bulk latency includes source shaper waiting. Dashed: control deadline.",12)
    save(svg,path)


def boundary(directory,path):
    points=read(directory);directory=Path(directory)
    svg=start(1160,570,"FIFO tail latency and reliability indexed load boundary")
    ymax=max(2.,max(float(p["p99_max"]) for p in points)*1.1)
    ymin=min(.05,min(float(p["p99_min"]) for p in points)*.9)
    arms=[(1.,2.,"PMR 1"),(3.,.5,"PMR 3 cycle 0.5T"),(3.,8.,"PMR 3 cycle 8T")]
    for ci in range(2):
        x0,y0,w,h=70+ci*570,75,450,350
        def xy(rho,value):
            y=(math.log(value/ymin)/math.log(ymax/ymin) if ci==0 else value)
            return x0+(rho-.2)/.75*w,y0+h-y*h
        text(svg,x0,y0-15,"Control P99 / T (log scale)" if ci==0 else "Run success fraction and simultaneous lower bound",13)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        for rho in (.2,.4,.6,.8,.95):
            x,_=xy(rho,1);text(svg,x,y0+h+20,f"{rho:.2f}",11,"middle")
        for value in ((.05,.1,.2,.5,1,2,5,10,20) if ci==0 else (0,.2,.4,.6,.8,.9,1)):
            if ci==0 and not ymin<=value<=ymax: continue
            _,y=xy(.2,value);line(svg,x0,y,x0+w,y,"#ddd");text(svg,x0-8,y+4,f"{value:g}",11,"end")
        _,y=xy(.2,1 if ci==0 else .9);line(svg,x0,y,x0+w,y,"#888",True)
        for ai,(pmr,tb,_) in enumerate(arms):
            curve=sorted((p for p in points if float(p["pmr"])==pmr and float(p["tau_b"])==tb),key=lambda p:float(p["rho"]))
            for field,dashed in (([("p99_median",False)]) if ci==0 else [("pass_fraction",False),("familywise_lower",True)]):
                coords=[xy(float(p["rho"]),float(p[field])) for p in curve]
                for a,b in zip(coords,coords[1:]): line(svg,*a,*b,COLORS[ai],dashed)
                for p,(x,y) in zip(curve,coords):
                    if ci==0:
                        _,lo=xy(float(p["rho"]),float(p["p99_min"]));_,hi=xy(float(p["rho"]),float(p["p99_max"]))
                        line(svg,x,lo,x,hi,COLORS[ai])
                    if not dashed: svg.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="{COLORS[ai]}"/>')
        text(svg,x0+w/2,y0+h+40,"Mean offered load / capacity",12,"middle")
    for i,(_,_,label) in enumerate(arms):
        x=70+i*350;line(svg,x,493,x+20,493,COLORS[i]);text(svg,x+28,498,label,12)
    text(svg,70,525,"70 paired seeds per point; 10,000 control packets per run. Jittered balanced cycles; service scale 2T.",12)
    text(svg,70,545,"P99 bars are seed ranges. Right panel dashed curves: 95% lower bounds simultaneous over all 48 load arm points.",12)
    save(svg,path)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("kind",choices=("robustness","boundary"));parser.add_argument("--input",required=True);parser.add_argument("--out",required=True)
    args=parser.parse_args();globals()[args.kind](args.input,args.out)
