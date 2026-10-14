"""Post-primary deadline sensitivity and seed-level contiguous boundaries.

Uses audited v4 raw controls; does not change primary alpha=.05/48 analysis.
The two sensitivity deadlines form their own exploratory 96-point family.
"""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from .robustness_cli import digest
from .reliability_boundary import clopper_pearson_lower


def contiguous(curve,eligible):
    prefix=[]
    for row in sorted(curve,key=lambda r:float(r["rho"])):
        if not eligible(row): break
        prefix.append(row)
    ordered=sorted(curve,key=lambda r:float(r["rho"]))
    return dict(boundary=float(prefix[-1]["rho"]) if prefix else None,
        first_failing=float(ordered[len(prefix)]["rho"]) if len(prefix)<len(ordered) else None,
        censoring="right" if len(prefix)==len(ordered) else ("left" if not prefix else "interval"))


def analyze(source,primary,out):
    import numpy as np
    import pandas as pd
    source,primary,out=map(Path,(source,primary,out))
    receipt=json.loads((primary/"audit.json").read_text())
    if receipt["status"]!="PASS": raise ValueError("primary audit required")
    if out.exists(): raise FileExistsError(out)
    for name,h in receipt["source_receipt"].items():
        if digest(source/name)!=h: raise ValueError("changed data")
    with (source/"runs.csv").open() as h: rows=list(csv.DictReader(h))
    counts=np.zeros(len(rows),dtype=np.int64)
    misses={d:np.zeros(len(rows),dtype=np.int64) for d in (.5,1.,2.)}
    for chunk in pd.read_csv(source/"control_packets.csv.gz",usecols=["run_id","status","latency"],
            dtype={"run_id":"int64","status":"category","latency":"float64"},chunksize=200000,float_precision="round_trip"):
        ids=chunk["run_id"].to_numpy();values=chunk["latency"].to_numpy()
        delivered=(chunk["status"]=="delivered").to_numpy()
        if (ids<0).any() or (ids>=len(rows)).any(): raise ValueError("invalid raw run")
        counts+=np.bincount(ids,minlength=len(rows))
        for d in misses:
            misses[d]+=np.bincount(ids[~delivered|(values>=d)],minlength=len(rows))
    if not all(counts[i]==int(r["generated"]) for i,r in enumerate(rows)): raise ValueError("raw counts mismatch")
    if not all(abs(misses[1.][i]/counts[i]-float(r["miss_ratio"]))<1e-12 for i,r in enumerate(rows)): raise ValueError("primary miss recomputation mismatch")
    groups=defaultdict(list);seeds=defaultdict(list)
    for i,r in enumerate(rows):
        for d in misses:
            row=dict(r,deadline=d,miss_recomputed=float(misses[d][i]/counts[i]))
            row["pass"]=bool(r["p99"]) and float(r["p99"])<d and row["miss_recomputed"]<.01
            groups[(d,float(r["pmr"]),float(r["tau_b"]),float(r["rho"]))].append(row)
            seeds[(d,float(r["pmr"]),float(r["tau_b"]),int(r["seed"]))].append(row)
    points=[]
    for (d,pmr,tb,rho),cohort in sorted(groups.items()):
        k=sum(r["pass"] for r in cohort);n=len(cohort);family=48 if d==1 else 96
        points.append(dict(deadline=d,pmr=pmr,tau_b=tb,rho=rho,n=n,successes=k,
            fraction=k/n,lower=clopper_pearson_lower(k,n,.05/family),familywise_points=family,
            median_p99=statistics.median(float(r["p99"]) for r in cohort),
            median_miss=statistics.median(r["miss_recomputed"] for r in cohort)))
    curves=defaultdict(list)
    for p in points: curves[(p["deadline"],p["pmr"],p["tau_b"])].append(p)
    boundaries=[]
    for (d,pmr,tb),curve in curves.items():
        for estimator in ("median","simultaneous"):
            check=(lambda p:p["median_p99"]<d and p["median_miss"]<.01) if estimator=="median" else (lambda p:p["lower"]>=.9)
            boundaries.append(dict(deadline=d,pmr=pmr,tau_b=tb,estimator=estimator,**contiguous(curve,check)))
    seedrows=[dict(deadline=d,pmr=pmr,tau_b=tb,seed=seed,**contiguous(curve,lambda r:r["pass"])) for (d,pmr,tb,seed),curve in sorted(seeds.items())]
    out.mkdir(parents=True)
    for name,data in (("points.csv",points),("boundaries.csv",boundaries),("seed_boundaries.csv",seedrows)):
        with (out/name).open("w",newline="") as h:
            writer=csv.DictWriter(h,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    result=dict(status="PASS",raw_controls=int(counts.sum()),deadlines=[.5,1,2],
        primary_unchanged=True,sensitivity="post-primary exploratory 96-point family",source_receipt=receipt["source_receipt"])
    (out/"audit.json").write_text(json.dumps(result,indent=2));return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--primary",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();print(json.dumps(analyze(a.input,a.primary,a.out)),flush=True)
