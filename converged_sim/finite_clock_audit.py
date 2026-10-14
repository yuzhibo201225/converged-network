"""Source-clock replay plus independently counted finite queue events.

Reuses frozen source/refill generators, not the link endpoint engine. This is
deterministic source-scheduling replay, not independent theorem verification.
"""
import argparse
import csv
import json
from pathlib import Path
from .robustness_cli import digest
from . import robustness_model as base
from .finite_source import finite_shape,biased_refill,constant_refill


def replay(row,spec):
    warm=float(spec["warmup"]);end=warm+spec["measured"]
    rho,pmr,tb,ts=(float(row[n]) for n in ("rho","pmr","tau_b","tau_s"));seed=int(row["seed"])
    guard=max(512.,32*tb,32*ts);traffic_end=end+guard
    trace=base.service_trace(warm,end,traffic_end+64,ts,seed,True)
    original=base.bulk_arrivals(warm,end,traffic_end,rho-.03,pmr,tb,seed,True)
    if row["mode"] in ("fifo","priority"):
        releases=original;maximum=0.;refill=None
    else:
        refill=constant_refill(trace,rho-.03) if row["mode"]=="fixed" else biased_refill(trace,rho,float(row["lag"]),float(row["bias"]))
        releases,ignored=finite_shape(original,refill,spec["bucket"],float(row["capacity"]))
        events=[]
        for a,r in zip(original,releases):
            if r is not None and r>a:
                events.extend(((a,1),(r,-1)))
        occupancy=0;max_packets=0
        for at,change in sorted(events):
            occupancy+=change
            if occupancy<0: raise ValueError("negative source queue")
            max_packets=max(max_packets,occupancy)
        if occupancy!=0: raise ValueError("unreleased source queue")
        maximum=max_packets*.1
        if maximum>float(row["capacity"])+1e-10: raise ValueError("event replay exceeds source capacity")
        tokens=spec["bucket"];previous=0.
        for r in releases:
            if r is None: continue
            tokens=min(spec["bucket"],tokens+refill.integrate(previous,r))
            if tokens<.1-1e-8: raise ValueError("released without tokens")
            tokens=max(0.,tokens-.1);previous=r
    expected={i:(a,r) for i,(a,r) in enumerate(zip(original,releases)) if warm<=a<end}
    load=.03+sum(r is not None and warm<=r<end for r in releases)*.1/spec["measured"]
    if abs(load-float(row["link_offered_rho"]))>1e-12: raise ValueError("realized link load mismatch")
    if abs(maximum-float(row["source_max_queued_work"]))>1e-10: raise ValueError("source occupancy summary mismatch")
    if base._canonical_digest(original)!=row["bulk_digest"] or trace.digest!=row["service_digest"]: raise ValueError("replay digest mismatch")
    generated_work=len(expected)*.1
    lower=max(0.,generated_work-float(row["capacity"])-spec["bucket"]-refill.integrate(warm,end)) if refill else 0.
    observed=float(row["source_bulk_dropped"])*.1
    if observed<lower-1e-7: raise ValueError("source loss below work-conservation lower bound")
    detail={n:row[n] for n in ("rho","pmr","tau_b","tau_s","mode","capacity","bias","lag","seed")}
    detail.update(source_loss_fraction=observed/generated_work,source_loss_fraction_lower_bound=lower/generated_work,
        window_refill_work=refill.integrate(warm,end) if refill else None,link_offered_rho=float(row["link_offered_rho"]))
    return expected,detail


def audit(source,endpoint,out):
    import pandas as pd
    source,endpoint,out=map(Path,(source,endpoint,out))
    m=json.loads((source/"manifest.json").read_text());r=json.loads((endpoint/"audit.json").read_text())
    if m["status"]!="COMPLETE" or r["status"]!="PASS": raise ValueError("complete endpoint audit required")
    if out.exists(): raise FileExistsError(out)
    if m["outputs_sha256"]!=r["source_receipt"]: raise ValueError("wrong endpoint audit")
    for name,h in m["outputs_sha256"].items():
        if digest(source/name)!=h: raise ValueError("changed input")
    with (source/"runs.csv").open() as handle: rows=list(csv.DictReader(handle))
    expected=None;current=-1;seen=set();count=0;details=[]
    def finish():
        if seen!=set(expected): raise ValueError("missing bulk source cohort")
    for chunk in pd.read_csv(source/"packets.csv.gz",usecols=["run_id","class","packet_id","arrival","release","drop_stage"],
            chunksize=200000,float_precision="round_trip",dtype={"run_id":"int64","class":"category","packet_id":"int64","drop_stage":"string"}):
        for i,group in chunk.groupby("run_id",sort=False):
            i=int(i)
            if i!=current:
                if current>=0: finish()
                if i!=current+1: raise ValueError("run order mismatch")
                expected,detail=replay(rows[i],m["spec"]);details.append(detail);seen=set();current=i
                if i%50==0: print(f"source clock {i}/{len(rows)}",flush=True)
            for p in group[group["class"]=="bulk"].itertuples(index=False):
                pid=int(p.packet_id)
                if pid in seen or pid not in expected: raise ValueError("invalid source ID")
                a,release=expected[pid];seen.add(pid);count+=1
                if abs(p.arrival-a)>1e-9: raise ValueError("source arrival mismatch")
                if release is None:
                    if not pd.isna(p.release) or p.drop_stage!="source": raise ValueError("source admission/drop mismatch")
                elif pd.isna(p.release) or abs(p.release-release)>1e-9 or (not pd.isna(p.drop_stage) and p.drop_stage=="source"):
                    raise ValueError("source release mismatch")
    finish()
    if current!=len(rows)-1: raise ValueError("missing source run")
    out.mkdir(parents=True)
    with (out/"source_conservation.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(details[0]));writer.writeheader();writer.writerows(details)
    result=dict(status="PASS",runs=len(rows),raw_bulk_packets=count,
        scope="deterministic source clock replay, independent occupancy-event counting and token budget check",
        source_receipt=m["outputs_sha256"],analysis_sha256=digest(__file__))
    (out/"audit.json").write_text(json.dumps(result,indent=2));return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--endpoint",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();print(json.dumps(audit(a.input,a.endpoint,a.out)),flush=True)
