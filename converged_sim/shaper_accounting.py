"""Regenerate source/release envelopes to expose finite-window shaping load costs.

This is deterministic generator replay, not independent packet-endpoint replay.
It includes warm-up carry-in that measured source-cohort raw files omit.
"""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from .robustness_model import bulk_arrivals,shape


def account(source,analysis,out):
    source,analysis,out=Path(source),Path(analysis),Path(out)
    manifest=json.loads((source/"manifest.json").read_text())
    receipt=json.loads((analysis/"audit.json").read_text())
    if manifest["status"]!="COMPLETE" or receipt["status"]!="PASS" or receipt["source_receipt"]!=manifest["outputs_sha256"]: raise ValueError("unaudited data")
    if out.exists(): raise FileExistsError(out)
    with (source/"runs.csv").open() as handle: rows=list(csv.DictReader(handle))
    cache,points={},defaultdict(list)
    start=float(manifest["spec"]["warmup"]);width=float(manifest["spec"]["measured"]);end=start+width
    for row in rows:
        bucket=float(row["bucket"]) if row["bucket"] else None
        key=(float(row["rho"]),float(row["pmr"]),float(row["tau_b"]),row["jitter_bulk"]=="True",bucket,int(row["seed"]))
        if key not in cache:
            rho,pmr,tb,jitter,bucket,seed=key
            guard=max(512.,32*tb,32*float(row["tau_s"]))
            arrivals=bulk_arrivals(start,end,end+guard,rho-.03,pmr,tb,seed,jitter)
            releases=arrivals if bucket is None else shape(arrivals,rho-.03,bucket)
            source_count=sum(start<=a<end for a in arrivals)
            link_count=sum(start<=r<end for r in releases)
            events=[];area=0.
            for a,r in zip(arrivals,releases):
                if r>a and a<end and r>start:
                    events.extend(((max(a,start),1),(min(r,end),-1)))
                    area+=(min(r,end)-max(a,start))*.1
            pending,maximum=0,0
            for at,delta in sorted(events):
                pending+=delta;maximum=max(maximum,pending)
            cache[key]=dict(rho=rho,pmr=pmr,tau_b=tb,jitter_bulk=jitter,bucket=bucket,seed=seed,
                source_bulk_work=source_count*.1,link_bulk_work=link_count*.1,
                link_offered_rho=.03+link_count*.1/width,
                link_minus_source_rho=(link_count-source_count)*.1/width,
                source_queue_max_work=maximum*.1,source_queue_mean_work=area/width)
        replay=cache[key]
        if abs(replay["source_bulk_work"]-float(row["bulk_offered_work"]))>1e-8: raise ValueError("source replay count mismatch")
    out.mkdir(parents=True)
    records=list(cache.values())
    for row in records:
        key=tuple(row[k] for k in ("rho","pmr","tau_b","jitter_bulk","bucket"))
        points[key].append(row)
    medians=[]
    for key,group in points.items():
        row=dict(zip(("rho","pmr","tau_b","jitter_bulk","bucket"),key));row["n"]=len(group)
        for field in ("link_offered_rho","link_minus_source_rho","source_queue_max_work","source_queue_mean_work"):
            row[field+"_median"]=statistics.median(r[field] for r in group)
            row[field+"_min"]=min(r[field] for r in group);row[field+"_max"]=max(r[field] for r in group)
        medians.append(row)
    for filename,data in (("runs.csv",records),("points.csv",medians)):
        with (out/filename).open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    result=dict(status="PASS",kind="source generator replay",unique_envelopes=len(records),
        maximum_abs_finite_window_load_shift=max(abs(r["link_minus_source_rho"]) for r in records),
        source_receipt=receipt["source_receipt"])
    (out/"audit.json").write_text(json.dumps(result,indent=2))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--input",required=True);parser.add_argument("--analysis",required=True);parser.add_argument("--out",required=True)
    args=parser.parse_args();print(json.dumps(account(args.input,args.analysis,args.out)))
