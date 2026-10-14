"""Parallel deterministic robustness sweep and all-class raw endpoint audit."""
import argparse
import csv
import gzip
import hashlib
import itertools
import json
import statistics
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .robustness_model import run


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def execute(item):
    cfg, params = item
    result = run(**params, measured=cfg["measured"],warmup=cfg["warmup"])
    row = dict(params)
    for kind in ("control","sensor","bulk"):
        summary = result["summaries"][kind]
        for field in ("generated","delivered","dropped","p99_latency","deadline_miss_ratio","goodput_work_per_time"):
            row[f"{kind}_{field}"] = summary[field]
    for key in ("service_digest","bulk_digest","bulk_offered_work","service_mean","sink_bulk_goodput","shaper_max_delay"):
        row[key] = result[key]
    return row,result["packets"]


def parameters(cfg):
    for rho,arm,tau_s,profile,policy,seed in itertools.product(
        cfg["loads"],cfg["arms"],cfg["tau_ss"],cfg["profiles"],cfg["policies"],cfg["seeds"]):
        yield dict(rho=rho,pmr=arm["pmr"],tau_b=arm["tau_b"],tau_s=tau_s,
            jitter_bulk=profile["jitter_bulk"],jitter_service=profile["jitter_service"],
            policy=policy["policy"],bucket=policy.get("bucket"),seed=seed)


def sweep(config,out,workers):
    cfg = json.loads(Path(config).read_text())
    params = list(parameters(cfg))
    if len({_key(p) for p in params}) != len(params): raise ValueError("duplicate grid")
    out = Path(out)
    if out.exists(): raise FileExistsError(out)
    out.mkdir(parents=True)
    manifest = dict(status="RUNNING",planned_runs=len(params),completed_runs=0,spec=cfg,
        config_sha256=digest(config),source_sha256={name:digest(Path(__file__).with_name(name))
            for name in ("robustness_cli.py","robustness_model.py","timescale_model.py")})
    def save(): (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    save()
    packet_fields = ["run_id","class","packet_id","arrival","release","shaper_delay","work","completion","status","latency","deadline_miss"]
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool, (out/"runs.csv").open("w",newline="") as summaries, gzip.open(out/"packets.csv.gz","wt",newline="",compresslevel=1) as raw:
            packet_writer = csv.DictWriter(raw,fieldnames=packet_fields)
            packet_writer.writeheader()
            writer = None
            # Bound outstanding large packet results; Executor.map on Python
            # 3.11 eagerly schedules the whole grid and can exhaust memory.
            iterator = iter(params)
            pending = deque()
            for _ in range(workers):
                item = next(iterator,None)
                if item is not None: pending.append(pool.submit(execute,(cfg,item)))
            index = 0
            while pending:
                row,packets = pending.popleft().result()
                if writer is None:
                    writer = csv.DictWriter(summaries,fieldnames=list(row)); writer.writeheader()
                writer.writerow(row)
                packet_writer.writerows(dict(run_id=index,**packet) for packet in packets)
                manifest["completed_runs"] = index+1
                summaries.flush(); save()
                if (index+1)%10==0: print(f"{index+1}/{len(params)} robustness runs",flush=True)
                item = next(iterator,None)
                if item is not None: pending.append(pool.submit(execute,(cfg,item)))
                index += 1
        manifest["outputs_sha256"] = {name:digest(out/name) for name in ("runs.csv","packets.csv.gz")}
        manifest["status"]="COMPLETE"; save()
    except Exception as error:
        manifest.update(status="FAILED",error=repr(error)); save(); raise
    return manifest


def _key(p):
    def boolean(x): return x is True or x=="True"
    return (float(p["rho"]),float(p["pmr"]),float(p["tau_b"]),float(p["tau_s"]),
        boolean(p["jitter_bulk"]),boolean(p["jitter_service"]),p["policy"],
        None if p["bucket"] in (None,"") else float(p["bucket"]),int(p["seed"]))


def analyze(source,out):
    source,out = Path(source),Path(out)
    manifest = json.loads((source/"manifest.json").read_text())
    if manifest["status"]!="COMPLETE": raise ValueError("incomplete experiment")
    if out.exists(): raise FileExistsError(out)
    for name,h in manifest["outputs_sha256"].items():
        if digest(source/name)!=h: raise ValueError("source hash changed")
    with (source/"runs.csv").open() as handle: runs = list(csv.DictReader(handle))
    keys = [_key(row) for row in runs]
    if len(keys)!=len(set(keys)) or set(keys)!={_key(p) for p in parameters(manifest["spec"])}:
        raise ValueError("incomplete/duplicate grid")
    raw_count = 0
    def check(index,packets):
        row = runs[index]
        if len({(p["class"],p["packet_id"]) for p in packets})!=len(packets): raise ValueError("duplicate packet IDs")
        for p in packets:
            a,r,d = float(p["arrival"]),float(p["release"]),float(p["shaper_delay"])
            if r<a-1e-10 or abs(r-a-d)>1e-10: raise ValueError("bad source delay")
            if p["status"] not in ("delivered","dropped"): raise ValueError("unresolved/unknown status")
            if p["status"]=="delivered":
                if abs(float(p["completion"])-a-float(p["latency"]))>1e-9 or float(p["completion"])<r-1e-10:
                    raise ValueError("bad end-to-end latency")
            if p["class"]=="control":
                miss = p["status"]!="delivered" or float(p["latency"])>=1.
                if miss!=(p["deadline_miss"]=="True"): raise ValueError("bad deadline flag")
        for kind in ("control","sensor","bulk"):
            cohort = [p for p in packets if p["class"]==kind]
            values = sorted(float(p["latency"]) for p in cohort if p["status"]=="delivered")
            if len(cohort)!=int(row[f"{kind}_generated"]) or len(values)!=int(row[f"{kind}_delivered"]): raise ValueError("bad delivery counts")
            if sum(p["status"]=="dropped" for p in cohort)!=int(row[f"{kind}_dropped"]): raise ValueError("bad drop count")
            if values:
                pos = (len(values)-1)*.99; lo=int(pos)
                p99=values[lo]*(1-pos+lo)+values[min(lo+1,len(values)-1)]*(pos-lo)
                if abs(p99-float(row[f"{kind}_p99_latency"]))>1e-9: raise ValueError("bad P99")
            if kind=="control" and abs(sum(p["deadline_miss"]=="True" for p in cohort)/len(cohort)-float(row["control_deadline_miss_ratio"]))>1e-12:
                raise ValueError("bad miss fraction")
            goodput=sum(float(p["work"]) for p in cohort if p["status"]=="delivered")/manifest["spec"]["measured"]
            if abs(goodput-float(row[f"{kind}_goodput_work_per_time"]))>1e-9: raise ValueError("bad goodput")
    cohort,index = [],0
    with gzip.open(source/"packets.csv.gz","rt") as handle:
        for p in csv.DictReader(handle):
            next_index = int(p["run_id"])
            if next_index!=index:
                if next_index!=index+1: raise ValueError("raw order mismatch")
                check(index,cohort); cohort=[]; index=next_index
            cohort.append(p); raw_count+=1
    check(index,cohort)
    if index!=len(runs)-1: raise ValueError("missing raw cohorts")
    paired,source_pairs,groups = defaultdict(list),defaultdict(list),defaultdict(list)
    for row in runs:
        key=_key(row)
        paired[(key[0],key[3],key[5],key[-1])].append(row)
        source_pairs[(key[0],key[1],key[2],key[4],key[-1])].append(row)
        groups[key[:-1]].append(row)
    for rows in paired.values():
        for field in ("service_digest","service_mean","bulk_offered_work"):
            if len({row[field] for row in rows})!=1: raise ValueError(f"unpaired {field}")
    for rows in source_pairs.values():
        if len({row["bulk_digest"] for row in rows})!=1: raise ValueError("unpaired source arrivals")
    points=[]
    for key,rows in groups.items():
        point=dict(zip(("rho","pmr","tau_b","tau_s","jitter_bulk","jitter_service","policy","bucket"),key))
        point["n"]=len(rows)
        for field in ("control_p99_latency","control_deadline_miss_ratio","bulk_p99_latency","bulk_goodput_work_per_time","sink_bulk_goodput","shaper_max_delay"):
            values=[float(r[field]) for r in rows if r[field]]
            point[field+"_median"]=statistics.median(values) if values else None
            point[field+"_min"]=min(values) if values else None
            point[field+"_max"]=max(values) if values else None
        point["joint_pass_fraction"]=sum(bool(r["control_p99_latency"]) and float(r["control_p99_latency"])<1 and float(r["control_deadline_miss_ratio"])<.01 for r in rows)/len(rows)
        points.append(point)
    out.mkdir(parents=True)
    with (out/"points.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(points[0])); writer.writeheader();writer.writerows(points)
    receipt=dict(status="PASS",runs=len(runs),raw_packets=raw_count,points=len(points),source_receipt=manifest["outputs_sha256"])
    (out/"audit.json").write_text(json.dumps(receipt,indent=2))
    return receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    sweep_parser=sub.add_parser("sweep");sweep_parser.add_argument("--config",required=True);sweep_parser.add_argument("--out",required=True);sweep_parser.add_argument("--workers",type=int,default=4)
    analysis_parser=sub.add_parser("analyze");analysis_parser.add_argument("--input",required=True);analysis_parser.add_argument("--out",required=True)
    args=parser.parse_args()
    print(json.dumps(sweep(args.config,args.out,args.workers) if args.command=="sweep" else analyze(args.input,args.out)),flush=True)
