"""Paired, audited fresh-seed feedback/reference comparison and figure."""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from .robustness_cli import digest
from .scientific_figures import start,text,line,save


def read_source(source,analysis):
    source,analysis=Path(source),Path(analysis)
    receipt=json.loads((analysis/"audit.json").read_text())
    if receipt["status"]!="PASS": raise ValueError("raw audit required")
    for name,h in receipt["source_receipt"].items():
        if digest(source/name)!=h: raise ValueError("changed raw input")
    with (source/"runs.csv").open() as handle: rows=list(csv.DictReader(handle))
    return rows,receipt


def key(r): return tuple(float(r[f]) for f in ("rho","pmr","tau_b","tau_s"))+(int(r["seed"]),)


def reference(r):
    if r["policy"]=="strict_priority": return "priority"
    return "fixed_shaper" if r["bucket"] else "fifo"


def compare(feedback,feedback_analysis,baseline,baseline_analysis,out):
    out=Path(out)
    if out.exists(): raise FileExistsError(out)
    candidates,cr=read_source(feedback,feedback_analysis)
    references,rr=read_source(baseline,baseline_analysis)
    indexed={}
    for r in references:
        k=(key(r),reference(r))
        if k in indexed: raise ValueError("duplicate reference")
        indexed[k]=r
    if {key(r) for r in references}!={key(r) for r in candidates}: raise ValueError("unmatched seed grid")
    pairs=[]
    for c in candidates:
        for name in ("fifo","priority","fixed_shaper"):
            r=indexed[(key(c),name)]
            for field in ("service_digest","bulk_digest","bulk_offered_work","service_mean"):
                if r[field]!=c[field]: raise ValueError("unpaired "+field)
            p=dict(zip(("rho","pmr","tau_b","tau_s","seed"),key(c)),lag=float(c["lag"]),reference=name)
            for kind in ("control","bulk"):
                field=kind+"_p99_latency"
                p[kind+"_p99_difference"]=float(c[field])-float(r[field])
            p["miss_difference"]=float(c["control_deadline_miss_ratio"])-float(r["control_deadline_miss_ratio"])
            pairs.append(p)
    groups=defaultdict(list)
    for p in pairs: groups[tuple(p[f] for f in ("rho","pmr","tau_b","tau_s","lag","reference"))].append(p)
    points=[]
    for k,rows in sorted(groups.items()):
        p=dict(zip(("rho","pmr","tau_b","tau_s","lag","reference"),k),n=len(rows))
        for field in ("control_p99_difference","bulk_p99_difference","miss_difference"):
            values=[r[field] for r in rows]
            p[field+"_median"]=statistics.median(values);p[field+"_min"]=min(values);p[field+"_max"]=max(values)
        points.append(p)
    out.mkdir(parents=True)
    for name,rows in (("pairs.csv",pairs),("points.csv",points)):
        with (out/name).open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    receipt=dict(status="PASS",matched_feedback_runs=len(candidates),reference_runs=len(references),
        paired_contrasts=len(pairs),feedback_receipt=cr,reference_receipt=rr,
        uncertainty="five paired seed ranges, not confidence intervals")
    (out/"audit.json").write_text(json.dumps(receipt,indent=2))
    figure(candidates,references,out/"feedback_cost.svg")
    return receipt


def figure(candidates,references,path):
    candidates=[r for r in candidates if float(r["pmr"])==3 and float(r["tau_b"])==8 and float(r["tau_s"])==8]
    references=[r for r in references if float(r["pmr"])==3 and float(r["tau_b"])==8 and float(r["tau_s"])==8]
    svg=start(1200,720,"Delayed capacity feedback: protection and end to end bulk cost")
    colors={"feedback":"#009E73","fifo":"#333333","priority":"#0072B2","fixed_shaper":"#CC79A7"}
    for col,rho in enumerate((.6,.8,.95)):
        cs=[r for r in candidates if float(r["rho"])==rho];rs=[r for r in references if float(r["rho"])==rho]
        for row,kind in enumerate(("control","bulk")):
            x0,y0,w,h=65+col*395,80+row*275,310,200
            field=kind+"_p99_latency"
            ymax=max(float(r[field]) for r in cs+rs)*1.1
            if kind=="control": ymax=max(ymax,max(float(r["control_delay_sufficient_bound"]) for r in cs)*1.1)
            def xy(lag,value): return x0+lag/2*w,y0+h-value/ymax*h
            text(svg,x0,y0-20,f"Load {rho:g}: {kind} P99 / T",13)
            line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
            for tick in range(5):
                v=ymax*tick/4;_,y=xy(0,v);text(svg,x0-8,y+4,f"{v:.1f}",11,"end")
            for lag in (0,.5,1,2):
                x,_=xy(lag,0);text(svg,x,y0+h+18,f"{lag:g}",11,"middle")
            coords=[];bounds=[]
            for lag in (0,.5,1,2):
                cohort=[r for r in cs if float(r["lag"])==lag];values=[float(r[field]) for r in cohort]
                x,y=xy(lag,statistics.median(values));coords.append((x,y))
                _,lo=xy(lag,min(values));_,hi=xy(lag,max(values));line(svg,x,lo,x,hi,colors["feedback"])
                svg.append(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{colors["feedback"]}"/>')
                if kind=="control": bounds.append(xy(lag,float(cohort[0]["control_delay_sufficient_bound"])))
            for a,b in zip(coords,coords[1:]): line(svg,*a,*b,colors["feedback"])
            for a,b in zip(bounds,bounds[1:]): line(svg,*a,*b,"#D55E00",True)
            for name in ("fifo","priority","fixed_shaper"):
                values=[float(r[field]) for r in rs if reference(r)==name]
                _,y=xy(0,statistics.median(values));line(svg,x0,y,x0+w,y,colors[name],True)
            if kind=="control":
                _,y=xy(0,1);line(svg,x0,y,x0+w,y,"#888")
            text(svg,x0+w/2,y0+h+37,"Perfect telemetry lag / T",12,"middle")
    labels=[("feedback","Feedback: seed median and range"),("fifo","FIFO reference"),("priority","Priority reference"),("fixed_shaper","Fixed mean shaper")]
    for i,(name,label) in enumerate(labels):
        x=55+i*290;line(svg,x,640,x+18,640,colors[name]);text(svg,x+24,644,label,11)
    text(svg,55,675,"PMR 3, bulk cycle 8T, service scale 8T; five paired fresh seeds. Bulk includes source waiting.",12)
    text(svg,55,696,"Orange dashed: sufficient link delay bound, not fitted. Grey solid: T deadline. Exploratory, not hardware validation.",12)
    save(svg,path)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("feedback","feedback-analysis","baseline","baseline-analysis","out"): p.add_argument("--"+name,required=True)
    a=p.parse_args();print(json.dumps(compare(a.feedback,a.feedback_analysis,a.baseline,a.baseline_analysis,a.out)),flush=True)
