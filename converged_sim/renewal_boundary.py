"""Fresh-seed load boundary confirmation with simultaneous binomial bounds."""
import argparse
import csv
import gzip
import itertools
import json
import statistics
from collections import defaultdict,deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .robustness_model import run
from .robustness_cli import digest
from .reliability_boundary import clopper_pearson_lower


def execute(item):
    spec,rho,arm,seed=item
    result=run(rho,arm["pmr"],arm["tau_b"],spec["tau_s"],seed,
        measured=spec["measured"],warmup=spec["warmup"],jitter_bulk=True,jitter_service=True)
    c=result["summaries"]["control"]
    return dict(rho=rho,pmr=arm["pmr"],tau_b=arm["tau_b"],seed=seed,
        p99=c["p99_latency"],miss_ratio=c["deadline_miss_ratio"],generated=c["generated"],
        dropped=c["dropped"],bulk_offered_work=result["bulk_offered_work"],service_digest=result["service_digest"],service_mean=result["service_mean"]),[p for p in result["packets"] if p["class"]=="control"]


def sweep(config,out,workers):
    spec=json.loads(Path(config).read_text());out=Path(out)
    if out.exists(): raise FileExistsError(out)
    grid=list(itertools.product(spec["loads"],spec["arms"],spec["seeds"]))
    if len({(rho,arm["pmr"],arm["tau_b"],seed) for rho,arm,seed in grid})!=len(grid): raise ValueError("duplicate grid")
    out.mkdir(parents=True)
    manifest=dict(status="RUNNING",planned_runs=len(grid),completed_runs=0,spec=spec,
        config_sha256=digest(config),source_sha256={name:digest(Path(__file__).with_name(name)) for name in ("renewal_boundary.py","robustness_model.py","timescale_model.py","reliability_boundary.py")})
    def save(): (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    save()
    fields=["run_id","class","packet_id","arrival","release","shaper_delay","work","completion","status","latency","deadline_miss"]
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool,(out/"runs.csv").open("w",newline="") as handle,gzip.open(out/"control_packets.csv.gz","wt",newline="",compresslevel=1) as raw:
            packet_writer=csv.DictWriter(raw,fieldnames=fields);packet_writer.writeheader()
            iterator=iter(grid);pending=deque()
            for _ in range(workers):
                item=next(iterator,None)
                if item is not None: pending.append(pool.submit(execute,(spec,*item)))
            writer,index=None,0
            while pending:
                row,packets=pending.popleft().result()
                if writer is None: writer=csv.DictWriter(handle,fieldnames=list(row));writer.writeheader()
                writer.writerow(row);packet_writer.writerows(dict(run_id=index,**p) for p in packets)
                handle.flush();manifest["completed_runs"]=index+1;save()
                if (index+1)%20==0: print(f"{index+1}/{len(grid)} confirmation runs",flush=True)
                item=next(iterator,None)
                if item is not None: pending.append(pool.submit(execute,(spec,*item)))
                index+=1
        manifest.update(status="COMPLETE",outputs_sha256={name:digest(out/name) for name in ("runs.csv","control_packets.csv.gz")});save()
    except Exception as error:
        manifest.update(status="FAILED",error=repr(error));save();raise
    return manifest


def analyze(source,out):
    source,out=Path(source),Path(out);manifest=json.loads((source/"manifest.json").read_text())
    if manifest["status"]!="COMPLETE": raise ValueError("incomplete confirmation")
    if out.exists(): raise FileExistsError(out)
    for name,h in manifest["outputs_sha256"].items():
        if digest(source/name)!=h: raise ValueError("changed raw data")
    with (source/"runs.csv").open() as handle: rows=list(csv.DictReader(handle))
    spec=manifest["spec"]
    expected={(rho,arm["pmr"],arm["tau_b"],seed) for rho,arm,seed in itertools.product(spec["loads"],spec["arms"],spec["seeds"])}
    keys=[(float(r["rho"]),float(r["pmr"]),float(r["tau_b"]),int(r["seed"])) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=expected: raise ValueError("grid mismatch")
    def check(index,packets):
        row=rows[index]
        if len(packets)!=spec["measured"] or len(packets)!=int(row["generated"]): raise ValueError("wrong packet count")
        if len({p["packet_id"] for p in packets})!=len(packets): raise ValueError("duplicate packet")
        for p in packets:
            if p["class"]!="control" or p["status"] not in ("delivered","dropped"): raise ValueError("bad control record")
            if p["status"]=="delivered":
                if abs(float(p["completion"])-float(p["arrival"])-float(p["latency"]))>1e-9: raise ValueError("bad latency")
            miss=p["status"]!="delivered" or float(p["latency"])>=1
            if miss!=(p["deadline_miss"]=="True"): raise ValueError("bad miss flag")
        if sum(p["status"]=="dropped" for p in packets)!=int(row["dropped"]): raise ValueError("bad drop count")
        values=sorted(float(p["latency"]) for p in packets if p["status"]=="delivered")
        if values:
            pos=(len(values)-1)*.99;lo=int(pos)
            q=values[lo]*(1-pos+lo)+values[min(lo+1,len(values)-1)]*(pos-lo)
            if abs(q-float(row["p99"]))>1e-9: raise ValueError("bad raw P99")
        misses=sum(p["deadline_miss"]=="True" for p in packets)/len(packets)
        if abs(misses-float(row["miss_ratio"]))>1e-12: raise ValueError("bad raw miss ratio")
    index,count,cohort=0,0,[]
    with gzip.open(source/"control_packets.csv.gz","rt") as handle:
        for p in csv.DictReader(handle):
            next_index=int(p["run_id"])
            if next_index!=index:
                if next_index!=index+1: raise ValueError("raw order mismatch")
                check(index,cohort);index=next_index;cohort=[]
            cohort.append(p);count+=1
    check(index,cohort)
    if index!=len(rows)-1: raise ValueError("missing final cohort")
    paired,groups=defaultdict(list),defaultdict(list)
    for row in rows:
        paired[(row["rho"],row["seed"])].append(row)
        groups[(float(row["pmr"]),float(row["tau_b"]),float(row["rho"]))].append(row)
    for cohort in paired.values():
        for field in ("service_digest","service_mean","bulk_offered_work"):
            if len({row[field] for row in cohort})!=1: raise ValueError(f"unpaired {field}")
    points=[]
    family=len(spec["loads"])*len(spec["arms"])
    for (pmr,tb,rho),cohort in sorted(groups.items()):
        successes=sum(bool(r["p99"]) and float(r["p99"])<1 and float(r["miss_ratio"])<.01 for r in cohort)
        values=[float(r["p99"]) for r in cohort if r["p99"]]
        points.append(dict(pmr=pmr,tau_b=tb,rho=rho,n=len(cohort),successes=successes,
            pass_fraction=successes/len(cohort),pointwise_lower=clopper_pearson_lower(successes,len(cohort),spec["alpha"]),
            familywise_lower=clopper_pearson_lower(successes,len(cohort),spec["alpha"]/family),
            p99_median=statistics.median(values),p99_min=min(values),p99_max=max(values),
            miss_median=statistics.median(float(r["miss_ratio"]) for r in cohort)))
    boundaries=[]
    for arm in spec["arms"]:
        curve=sorted((p for p in points if p["pmr"]==arm["pmr"] and p["tau_b"]==arm["tau_b"]),key=lambda p:p["rho"])
        for estimator in ("median_rule","empirical","pointwise_lower","familywise_lower"):
            prefix=[]
            for point in curve:
                eligible=(point["p99_median"]<1 and point["miss_median"]<.01) if estimator=="median_rule" else point["pass_fraction" if estimator=="empirical" else estimator]>=spec["q"]
                if not eligible: break
                prefix.append(point)
            boundaries.append(dict(pmr=arm["pmr"],tau_b=arm["tau_b"],estimator=estimator,
                boundary=prefix[-1]["rho"] if prefix else None,
                censoring="right" if len(prefix)==len(curve) else ("left" if not prefix else "interval"),
                first_failing=curve[len(prefix)]["rho"] if len(prefix)<len(curve) else None))
    out.mkdir(parents=True)
    for name,data in (("points.csv",points),("boundaries.csv",boundaries)):
        with (out/name).open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    result=dict(status="PASS",runs=len(rows),raw_control_packets=count,
        q=spec["q"],alpha=spec["alpha"],familywise_points=family,source_receipt=manifest["outputs_sha256"])
    (out/"audit.json").write_text(json.dumps(result,indent=2))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("sweep");p.add_argument("--config",required=True);p.add_argument("--out",required=True);p.add_argument("--workers",type=int,default=4)
    p.add_argument("--analyze-out")
    p=sub.add_parser("analyze");p.add_argument("--input",required=True);p.add_argument("--out",required=True)
    args=parser.parse_args()
    if args.command=="sweep":
        result=sweep(args.config,args.out,args.workers)
        if args.analyze_out: result=analyze(args.out,args.analyze_out)
    else: result=analyze(args.input,args.out)
    print(json.dumps(result),flush=True)
