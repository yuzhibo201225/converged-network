"""Fresh-seed delayed-feedback experiment; all-class source-cohort records."""
import argparse
import csv
import gzip
import itertools
import json
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .adaptive_shaper import run
from .robustness_cli import digest


def parameters(spec):
    for rho,arm,ts,lag,seed in itertools.product(spec["loads"],spec["arms"],spec["tau_ss"],spec["lags"],spec["seeds"]):
        yield dict(rho=rho,pmr=arm["pmr"],tau_b=arm["tau_b"],tau_s=ts,lag=lag,
            seed=seed,policy="fifo",bucket=spec["bucket"],jitter_bulk=True,jitter_service=True)


def execute(item):
    spec,p=item
    result=run(p["rho"],p["pmr"],p["tau_b"],p["tau_s"],p["seed"],lag=p["lag"],bucket=p["bucket"],measured=spec["measured"],warmup=spec["warmup"])
    row=dict(p)
    for kind in ("control","sensor","bulk"):
        for field in ("generated","delivered","dropped","p99_latency","deadline_miss_ratio","goodput_work_per_time"):
            row[kind+"_"+field]=result["summaries"][kind][field]
    for key in ("service_digest","bulk_digest","bulk_offered_work","service_mean","sink_bulk_goodput","shaper_max_delay","control_delay_sufficient_bound","link_offered_rho","feedback_refill_digest"):
        row[key]=result[key]
    row["control_max_latency"]=max(p["latency"] for p in result["packets"] if p["class"]=="control" and p["status"]=="delivered")
    return row,result["packets"]


def sweep(config,out,workers):
    spec=json.loads(Path(config).read_text());out=Path(out)
    if out.exists(): raise FileExistsError(out)
    params=list(parameters(spec))
    if len({tuple(p.values()) for p in params})!=len(params): raise ValueError("duplicate grid")
    out.mkdir(parents=True)
    manifest=dict(status="RUNNING",planned_runs=len(params),completed_runs=0,spec=spec,
        config_sha256=digest(config),source_sha256={name:digest(Path(__file__).with_name(name)) for name in ("adaptive_cli.py","adaptive_shaper.py","robustness_model.py","timescale_model.py")})
    def save(): (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    save()
    fields=["run_id","class","packet_id","arrival","release","shaper_delay","work","completion","status","latency","deadline_miss"]
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool,(out/"runs.csv").open("w",newline="") as handle,gzip.open(out/"packets.csv.gz","wt",newline="",compresslevel=1) as raw:
            raw_writer=csv.DictWriter(raw,fieldnames=fields);raw_writer.writeheader()
            iterator=iter(params);pending=deque();writer=None;index=0
            for _ in range(workers):
                p=next(iterator,None)
                if p is not None: pending.append(pool.submit(execute,(spec,p)))
            while pending:
                row,packets=pending.popleft().result()
                if writer is None: writer=csv.DictWriter(handle,fieldnames=list(row));writer.writeheader()
                writer.writerow(row);raw_writer.writerows(dict(run_id=index,**p) for p in packets)
                handle.flush();manifest["completed_runs"]=index+1;save()
                if (index+1)%10==0: print(f"{index+1}/{len(params)} feedback runs",flush=True)
                p=next(iterator,None)
                if p is not None: pending.append(pool.submit(execute,(spec,p)))
                index+=1
        manifest.update(status="COMPLETE",outputs_sha256={name:digest(out/name) for name in ("runs.csv","packets.csv.gz")});save()
    except Exception as error:
        manifest.update(status="FAILED",error=repr(error));save();raise
    return manifest


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--config",required=True);parser.add_argument("--out",required=True);parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args();print(json.dumps(sweep(args.config,args.out,args.workers)),flush=True)
