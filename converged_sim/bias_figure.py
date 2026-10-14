"""Exploratory calibration-error curves, only from raw-audited tables."""
import argparse
import csv
import json
from pathlib import Path
from .scientific_figures import start, text, line, save
from .telemetry_budget import condition


def plot(directory, source_audit, out):
    directory=Path(directory)
    receipts=[json.loads(p.read_text()) for p in (directory/"audit.json",Path(source_audit)/"audit.json")]
    for receipt in receipts:
        if receipt["status"]!="PASS":
            raise ValueError("endpoint and source audits required")
    if receipts[0]["source_receipt"]!=receipts[1]["source_receipt"]:
        raise ValueError("audits refer to different source data")
    with (directory/"points.csv").open() as h:
        rows=list(csv.DictReader(h))
    if len(rows)!=16 or any(float(r["rho"])!=.95 or float(r["lag"])!=.5 or float(r["capacity"])!=16 for r in rows):
        raise ValueError("unexpected V8 grid")
    svg=start(1050,500,"Capacity overestimation breaks control protection at unchanged mean link load")
    budget=condition(.95,0,.5)["error_upper_budget"]
    for ci,(field,label,ymax) in enumerate((("control_p99_latency","Control P99 / T",3.),
                                          ("control_deadline_miss_ratio","Control deadline miss ratio",.35))):
        x0,y0,w,h=70+ci*520,75,410,285
        def xy(x,y): return x0+x/.1*w,y0+h-y/ymax*h
        xb,_=xy(budget,0)
        svg.append(f'<rect x="{x0}" y="{y0}" width="{xb-x0}" height="{h}" fill="#e8f3e8"/>')
        text(svg,x0,y0-18,label,14)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        line(svg,xb,y0,xb,y0+h,"#777",True)
        for i in range(6):
            x,_=xy(i*.02,0);text(svg,x,y0+h+20,f"{i*.02:.2f}",11,"middle")
        for i in range(5):
            _,y=xy(0,ymax*i/4);text(svg,x0-8,y+4,f"{ymax*i/4:.3g}",11,"end")
        _,dy=xy(0,1 if ci==0 else .01);line(svg,x0,dy,x0+w,dy,"#999",True)
        for pmr,color in ((1,"#0072B2"),(3,"#D55E00")):
            arm=sorted((r for r in rows if float(r["pmr"])==pmr),key=lambda r:float(r["bias"]))
            coords=[]
            for r in arm:
                x,y=xy(float(r["bias"]),float(r[field+"_median"]));coords.append((x,y))
                _,lo=xy(float(r["bias"]),float(r[field+"_min"]));_,hi=xy(float(r["bias"]),float(r[field+"_max"]))
                line(svg,x,lo,x,hi,color);svg.append(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{color}"/>')
            for a,b in zip(coords,coords[1:]): line(svg,*a,*b,color)
        text(svg,x0+w/2,y0+h+41,"Additive upper capacity error / (work per T)",12,"middle")
    for i,(label,color) in enumerate((("PMR1 / period2T","#0072B2"),("PMR3 / period8T","#D55E00"))):
        x=70+i*270;line(svg,x,425,x+25,425,color);text(svg,x+32,429,label,12)
    text(svg,650,429,"Shaded: local sufficient error budget",12)
    text(svg,70,461,"Five fresh paired seeds; bars are seed ranges, not CIs. Median-rule crossing bracket [.05,.06] in both arms.",12)
    if any(float(r["bulk_delivery_ratio_min"])!=1 for r in rows):
        raise ValueError("V8 full-delivery caption would be false")
    lo=min(float(r["link_offered_rho_min"]) for r in rows)
    hi=max(float(r["link_offered_rho_max"]) for r in rows)
    text(svg,70,483,f"Q=16, lag=.5T, generated load=.95. All bulk delivered; actual mean link load {lo:.5f}-{hi:.5f}. No hardware claim.",12)
    save(svg,out)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--source-audit",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();plot(a.input,a.source_audit,a.out)
