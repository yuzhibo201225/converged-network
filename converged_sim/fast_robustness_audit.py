"""Independent C-parser/NumPy audit of all v3 class packet endpoints.

Run using the bundled workspace Python with pandas and numpy. The original
standard-library audit remains available as a separate reproducibility path.
"""
import argparse
import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from .robustness_cli import digest,parameters,_key


def audit(source,out):
    source,out=Path(source),Path(out)
    manifest=json.loads((source/"manifest.json").read_text())
    if manifest["status"]!="COMPLETE": raise ValueError("incomplete experiment")
    if out.exists(): raise FileExistsError(out)
    for name,h in manifest["outputs_sha256"].items():
        if digest(source/name)!=h: raise ValueError("hash mismatch")
    with (source/"runs.csv").open() as handle: runs=list(csv.DictReader(handle))
    adaptive=manifest["spec"].get("model")=="delayed_capacity_feedback"
    if adaptive:
        from .adaptive_cli import parameters as grid_parameters
        def key_of(row): return _key(row)[:-1]+(float(row["lag"]),int(row["seed"]))
    else:
        grid_parameters=parameters;key_of=_key
    keys=[key_of(r) for r in runs]
    if len(keys)!=len(set(keys)) or set(keys)!={key_of(p) for p in grid_parameters(manifest["spec"])}: raise ValueError("incomplete grid")
    def check(index,d):
        row=runs[index]
        if d.duplicated(["class","packet_id"]).any(): raise ValueError("duplicate IDs")
        if not set(d["class"].unique()) <= {"control","sensor","bulk"}: raise ValueError("unknown class")
        if not d["status"].isin(("delivered","dropped")).all(): raise ValueError("unknown/unresolved status")
        if not np.isfinite(d[["arrival","release","shaper_delay","work"]].to_numpy()).all(): raise ValueError("nonfinite source fields")
        if (d["release"]<d["arrival"]-1e-10).any() or (abs(d["release"]-d["arrival"]-d["shaper_delay"])>1e-10).any(): raise ValueError("bad source timestamps")
        delivered=d["status"]=="delivered"
        if not np.isfinite(d.loc[delivered,["completion","latency"]].to_numpy()).all(): raise ValueError("nonfinite delivery")
        if (abs(d.loc[delivered,"completion"]-d.loc[delivered,"arrival"]-d.loc[delivered,"latency"])>1e-9).any() or (d.loc[delivered,"completion"]<d.loc[delivered,"release"]-1e-10).any(): raise ValueError("bad e2e timestamps")
        for kind,size in (("control",.01),("sensor",.04),("bulk",.1)):
            cohort=d[d["class"]==kind];values=cohort.loc[cohort["status"]=="delivered","latency"].to_numpy()
            if len(cohort)!=int(row[kind+"_generated"]) or len(values)!=int(row[kind+"_delivered"]) or (cohort["status"]=="dropped").sum()!=int(row[kind+"_dropped"]): raise ValueError("bad endpoint counts")
            if (abs(cohort["work"]-size)>1e-12).any(): raise ValueError("wrong packet size")
            if len(values):
                if abs(float(np.quantile(values,.99,method="linear"))-float(row[kind+"_p99_latency"]))>1e-9: raise ValueError("bad raw P99")
            elif row[kind+"_p99_latency"]: raise ValueError("P99 without deliveries")
            goodput=float(cohort.loc[cohort["status"]=="delivered","work"].sum())/manifest["spec"]["measured"]
            if abs(goodput-float(row[kind+"_goodput_work_per_time"]))>1e-9: raise ValueError("bad goodput")
            if kind=="bulk" and abs(float(cohort["work"].sum())-float(row["bulk_offered_work"]))>1e-8: raise ValueError("bad bulk source work")
            if kind=="control":
                misses=(cohort["status"]!="delivered")|(cohort["latency"]>=1.)
                if not (misses.to_numpy()==(cohort["deadline_miss"]=="True").to_numpy()).all(): raise ValueError("bad miss flag")
                if abs(float(misses.mean())-float(row["control_deadline_miss_ratio"]))>1e-12: raise ValueError("bad miss ratio")
                if adaptive:
                    maximum=float(values.max())
                    if abs(maximum-float(row["control_max_latency"]))>1e-9: raise ValueError("bad control maximum")
                    if maximum>float(row["control_delay_sufficient_bound"])+1e-8 or len(values)!=len(cohort): raise ValueError("candidate bound violated or control lost")
        shaped=d[d["class"]=="bulk"]
        if abs(float(shaped["shaper_delay"].max())-float(row["shaper_max_delay"]))>1e-9: raise ValueError("bad shaper maximum")
    parts,current,count=[],0,0
    dtype={"run_id":"int64","class":"category","packet_id":"int64","status":"category","deadline_miss":"string"}
    for name in ("arrival","release","shaper_delay","work","completion","latency"): dtype[name]="float64"
    for chunk in pd.read_csv(source/"packets.csv.gz",chunksize=150000,dtype=dtype,float_precision="round_trip"):
        for index,group in chunk.groupby("run_id",sort=False):
            index=int(index)
            if index!=current:
                if index!=current+1: raise ValueError("raw run order mismatch")
                check(current,pd.concat(parts,ignore_index=True));parts=[];current=index
                if current%50==0: print(f"audited {current}/{len(runs)} all-class cohorts",flush=True)
            parts.append(group);count+=len(group)
    check(current,pd.concat(parts,ignore_index=True))
    if current!=len(runs)-1: raise ValueError("missing raw cohorts")
    paired,source_pairs,groups=defaultdict(list),defaultdict(list),defaultdict(list)
    for row in runs:
        key=key_of(row);paired[(key[0],key[3],key[5],key[-1])].append(row)
        source_pairs[(key[0],key[1],key[2],key[4],key[-1])].append(row);groups[key[:-1]].append(row)
    for rows in paired.values():
        for field in ("service_digest","service_mean","bulk_offered_work"):
            if len({r[field] for r in rows})!=1: raise ValueError(f"unpaired {field}")
    for rows in source_pairs.values():
        if len({r["bulk_digest"] for r in rows})!=1: raise ValueError("unpaired source arrivals")
    points=[]
    for key,rows in groups.items():
        names=("rho","pmr","tau_b","tau_s","jitter_bulk","jitter_service","policy","bucket")+(("lag",) if adaptive else ())
        point=dict(zip(names,key));point["n"]=len(rows)
        fields=("control_p99_latency","control_deadline_miss_ratio","bulk_p99_latency","bulk_goodput_work_per_time","sink_bulk_goodput","shaper_max_delay")
        if adaptive: fields+=("control_max_latency","control_delay_sufficient_bound","link_offered_rho")
        for field in fields:
            values=[float(r[field]) for r in rows if r[field]]
            point[field+"_median"]=statistics.median(values) if values else None
            point[field+"_min"]=min(values) if values else None;point[field+"_max"]=max(values) if values else None
        point["joint_pass_fraction"]=sum(bool(r["control_p99_latency"]) and float(r["control_p99_latency"])<1 and float(r["control_deadline_miss_ratio"])<.01 for r in rows)/len(rows)
        points.append(point)
    out.mkdir(parents=True)
    with (out/"points.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(points[0]));writer.writeheader();writer.writerows(points)
    result=dict(status="PASS",runs=len(runs),raw_packets=count,points=len(points),
        backend="pandas C parser and NumPy linear R7 quantile",numpy=np.__version__,pandas=pd.__version__,
        analysis_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        source_receipt=manifest["outputs_sha256"])
    (out/"audit.json").write_text(json.dumps(result,indent=2));return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--input",required=True);parser.add_argument("--out",required=True)
    args=parser.parse_args();print(json.dumps(audit(args.input,args.out)),flush=True)
