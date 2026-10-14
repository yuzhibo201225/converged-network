"""Frozen finite-memory calibration-bias sweep and raw endpoint audit."""
import argparse
import csv
import gzip
import itertools
import json
import statistics
from collections import deque,defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .finite_source import run
from .robustness_cli import digest


def parameters(spec):
    for rho,arm,setting,seed in itertools.product(spec["loads"],spec["arms"],spec["settings"],spec["seeds"]):
        yield dict(rho=rho,pmr=arm["pmr"],tau_b=arm["tau_b"],tau_s=spec["tau_s"],
            mode=setting["mode"],capacity=setting.get("capacity"),bias=setting.get("bias",0.),
            lag=setting.get("lag",0.),seed=seed)


def key(r):
    return tuple(float(r[n]) for n in ("rho","pmr","tau_b","tau_s"))+(r["mode"],
        float(r["capacity"]) if r["capacity"] not in (None,"") else None,
        float(r["bias"]),float(r["lag"]),int(r["seed"]))


def execute(item):
    spec,p=item
    result=run(**p,bucket=spec["bucket"],measured=spec["measured"],warmup=spec["warmup"])
    row=dict(p)
    for kind in ("control","sensor","bulk"):
        for field in ("generated","delivered","dropped","p99_latency","deadline_miss_ratio","delivery_ratio","goodput_work_per_time"):
            row[kind+"_"+field]=result["summaries"][kind][field]
    for n in ("service_digest","bulk_digest","service_mean","source_bulk_dropped","link_bulk_dropped",
            "source_max_queued_work","shaper_max_delay","link_offered_rho","sink_bulk_goodput","refill_digest"):
        row[n]=result[n]
    return row,result["packets"]


def sweep(config,out,workers):
    spec=json.loads(Path(config).read_text());out=Path(out);grid=list(parameters(spec))
    if out.exists(): raise FileExistsError(out)
    if len({key(p) for p in grid})!=len(grid): raise ValueError("duplicate grid")
    out.mkdir(parents=True)
    manifest=dict(status="RUNNING",planned_runs=len(grid),completed_runs=0,spec=spec,
        config_sha256=digest(config),source_sha256={n:digest(Path(__file__).with_name(n)) for n in
            ("finite_source_cli.py","finite_source.py","adaptive_shaper.py","robustness_model.py","timescale_model.py")})
    def save(): (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    save()
    fields=["run_id","class","packet_id","arrival","release","shaper_delay","work","completion","status","drop_stage","latency","deadline_miss"]
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool,(out/"runs.csv").open("w",newline="") as summary,gzip.open(out/"packets.csv.gz","wt",newline="",compresslevel=1) as raw:
            pw=csv.DictWriter(raw,fieldnames=fields);pw.writeheader();writer=None;it=iter(grid);pending=deque();index=0
            for _ in range(workers):
                p=next(it,None)
                if p is not None: pending.append(pool.submit(execute,(spec,p)))
            while pending:
                row,packets=pending.popleft().result()
                if writer is None: writer=csv.DictWriter(summary,fieldnames=list(row));writer.writeheader()
                writer.writerow(row);pw.writerows(dict(run_id=index,**p) for p in packets);summary.flush()
                index+=1;manifest["completed_runs"]=index;save()
                if index%10==0: print(f"{index}/{len(grid)} finite-source runs",flush=True)
                p=next(it,None)
                if p is not None: pending.append(pool.submit(execute,(spec,p)))
        manifest.update(status="COMPLETE",outputs_sha256={n:digest(out/n) for n in ("runs.csv","packets.csv.gz")});save()
    except Exception as error:
        manifest.update(status="FAILED",error=repr(error));save();raise
    return manifest


def audit(source,out):
    import numpy as np
    import pandas as pd
    source,out=Path(source),Path(out);m=json.loads((source/"manifest.json").read_text())
    if m["status"]!="COMPLETE": raise ValueError("incomplete sweep")
    if out.exists(): raise FileExistsError(out)
    for name,h in m["outputs_sha256"].items():
        if digest(source/name)!=h: raise ValueError("changed raw data")
    with (source/"runs.csv").open() as handle: rows=list(csv.DictReader(handle))
    keys=[key(r) for r in rows]
    if len(set(keys))!=len(keys) or set(keys)!={key(p) for p in parameters(m["spec"])}: raise ValueError("grid mismatch")
    def check(i,d):
        r=rows[i]
        d=d.copy();d["drop_stage"]=d["drop_stage"].fillna("")
        if not d["drop_stage"].isin(("","source","link")).all(): raise ValueError("invalid drop stage")
        if d.duplicated(["class","packet_id"]).any(): raise ValueError("duplicate packet")
        if not d["status"].isin(("delivered","dropped")).all(): raise ValueError("unresolved/invalid status")
        if not set(d["class"].unique())<={"control","sensor","bulk"}: raise ValueError("bad class")
        source_drop=d["drop_stage"]=="source";link_drop=d["drop_stage"]=="link";delivered=d["status"]=="delivered"
        if not ((source_drop|link_drop)==(d["status"]=="dropped")).all(): raise ValueError("drop location mismatch")
        if not (d.loc[source_drop,"class"]=="bulk").all(): raise ValueError("critical source drop")
        if d.loc[source_drop,["release","shaper_delay","completion","latency"]].notna().any().any(): raise ValueError("source drop has endpoints")
        if not np.isfinite(d[["arrival","work"]].to_numpy()).all(): raise ValueError("nonfinite arrival/work")
        if (d["arrival"]<m["spec"]["warmup"]).any() or (d["arrival"]>=m["spec"]["warmup"]+m["spec"]["measured"]).any(): raise ValueError("outside measured source cohort")
        emitted=~source_drop
        if not np.isfinite(d.loc[emitted,["release","shaper_delay"]].to_numpy()).all(): raise ValueError("missing release")
        if (d.loc[emitted,"release"]<d.loc[emitted,"arrival"]-1e-10).any() or (abs(d.loc[emitted,"release"]-d.loc[emitted,"arrival"]-d.loc[emitted,"shaper_delay"])>1e-9).any(): raise ValueError("source timestamp mismatch")
        if not np.isfinite(d.loc[delivered,["completion","latency"]].to_numpy()).all(): raise ValueError("missing delivered endpoint")
        if (d.loc[delivered,"completion"]<d.loc[delivered,"release"]-1e-10).any() or (abs(d.loc[delivered,"completion"]-d.loc[delivered,"arrival"]-d.loc[delivered,"latency"])>1e-9).any(): raise ValueError("e2e timestamp mismatch")
        if d.loc[link_drop,["completion","latency"]].notna().any().any(): raise ValueError("link drop has delivery")
        for kind,size in (("control",.01),("sensor",.04),("bulk",.1)):
            cohort=d[d["class"]==kind];values=cohort.loc[cohort["status"]=="delivered","latency"].to_numpy()
            if len(cohort)!=int(r[kind+"_generated"]) or len(values)!=int(r[kind+"_delivered"]) or len(cohort)-len(values)!=int(r[kind+"_dropped"]): raise ValueError("cohort count mismatch")
            if (abs(cohort["work"]-size)>1e-12).any(): raise ValueError("work mismatch")
            if len(values) and abs(float(np.quantile(values,.99,method="linear"))-float(r[kind+"_p99_latency"]))>1e-9: raise ValueError("P99 mismatch")
            if not len(values) and r[kind+"_p99_latency"]: raise ValueError("P99 without delivered packets")
            if abs(len(values)/len(cohort)-float(r[kind+"_delivery_ratio"]))>1e-12: raise ValueError("delivery ratio mismatch")
            if abs(len(values)*size/m["spec"]["measured"]-float(r[kind+"_goodput_work_per_time"]))>1e-9: raise ValueError("goodput mismatch")
            if kind=="control":
                miss=(cohort["status"]!="delivered")|(cohort["latency"]>=1)
                if not (miss.to_numpy()==(cohort["deadline_miss"]=="True").to_numpy()).all() or abs(miss.mean()-float(r["control_deadline_miss_ratio"]))>1e-12: raise ValueError("control miss mismatch")
        if source_drop.sum()!=int(r["source_bulk_dropped"]) or ((d["class"]=="bulk")&link_drop).sum()!=int(r["link_bulk_dropped"]): raise ValueError("bulk drop split mismatch")
        if r["capacity"] and float(r["source_max_queued_work"])>float(r["capacity"])+1e-10: raise ValueError("source exceeds finite capacity")
        if abs(float(d.loc[(d["class"]=="bulk")&emitted,"shaper_delay"].max())-float(r["shaper_max_delay"]))>1e-9: raise ValueError("shaper max mismatch")
    parts=[];current=0;count=0
    for chunk in pd.read_csv(source/"packets.csv.gz",chunksize=150000,float_precision="round_trip",dtype={"run_id":"int64","class":"category","status":"category","drop_stage":"string","deadline_miss":"string"}):
        for i,d in chunk.groupby("run_id",sort=False):
            i=int(i)
            if i!=current:
                if i!=current+1: raise ValueError("raw order mismatch")
                check(current,pd.concat(parts,ignore_index=True));parts=[];current=i
                if current%50==0: print(f"audited {current}/{len(rows)} finite-source cohorts",flush=True)
            parts.append(d);count+=len(d)
    check(current,pd.concat(parts,ignore_index=True))
    if current!=len(rows)-1: raise ValueError("missing final run")
    paired=defaultdict(list);groups=defaultdict(list)
    for r in rows:
        k=key(r);paired[(k[0],k[1],k[2],k[3],k[-1])].append(r);groups[k[:-1]].append(r)
    for cohort in paired.values():
        for n in ("service_digest","bulk_digest","service_mean","bulk_generated"):
            if len({r[n] for r in cohort})!=1: raise ValueError("unpaired "+n)
    points=[]
    fields=("control_p99_latency","control_deadline_miss_ratio","bulk_p99_latency","bulk_delivery_ratio","source_bulk_dropped","link_bulk_dropped","bulk_goodput_work_per_time","source_max_queued_work","shaper_max_delay","link_offered_rho")
    for k,cohort in sorted(groups.items(),key=lambda item:str(item[0])):
        p=dict(zip(("rho","pmr","tau_b","tau_s","mode","capacity","bias","lag"),k),n=len(cohort))
        for n in fields:
            values=[float(r[n]) for r in cohort if r[n]]
            p[n+"_median"]=statistics.median(values) if values else None
            p[n+"_min"]=min(values) if values else None;p[n+"_max"]=max(values) if values else None
        p["joint_pass_fraction"]=sum(bool(r["control_p99_latency"]) and float(r["control_p99_latency"])<1 and float(r["control_deadline_miss_ratio"])<.01 for r in cohort)/len(cohort)
        points.append(p)
    out.mkdir(parents=True)
    with (out/"points.csv").open("w",newline="") as handle:
        w=csv.DictWriter(handle,fieldnames=list(points[0]));w.writeheader();w.writerows(points)
    receipt=dict(status="PASS",runs=len(rows),raw_packets=count,points=len(points),
        source_receipt=m["outputs_sha256"],analysis_sha256=digest(__file__),
        scope="raw endpoint and finite-capacity-summary consistency; queue trajectory not independently replayed")
    (out/"audit.json").write_text(json.dumps(receipt,indent=2));return receipt


if __name__=="__main__":
    p=argparse.ArgumentParser();s=p.add_subparsers(dest="command",required=True)
    x=s.add_parser("sweep");x.add_argument("--config",required=True);x.add_argument("--out",required=True);x.add_argument("--workers",type=int,default=4)
    x=s.add_parser("audit");x.add_argument("--input",required=True);x.add_argument("--out",required=True)
    a=p.parse_args();result=sweep(a.config,a.out,a.workers) if a.command=="sweep" else audit(a.input,a.out)
    print(json.dumps(result),flush=True)
