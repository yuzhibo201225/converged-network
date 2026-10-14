"""Finite source queue and biased delayed capacity telemetry.

Separate engine extension; frozen v3-v6 source files are not modified.
Source and link drop locations are retained for every measured source packet.
"""
import math
from collections import deque
from . import robustness_model as base
from .adaptive_shaper import refill_trace
from .timescale_model import _ServiceTrace,_FifoScheduler,_PriorityScheduler,_Packet,_class_summary,_canonical_digest


def biased_refill(trace,rho,lag,bias):
    if not math.isfinite(bias): raise ValueError("finite additive bias required")
    perfect=refill_trace(trace,rho,lag)
    rates=[r+rho*bias for r in perfect.rates]
    if min(rates)<=0: raise ValueError("nonpositive refill rate")
    h=_canonical_digest([perfect.starts,perfect.ends,rates])
    return _ServiceTrace(perfect.starts,perfect.ends,rates,trace.observation_duration,
        trace.drain_horizon,False,0.,min(rates),max(rates),h,h,h)


def finite_shape(arrivals,refill,bucket,capacity,work=.1):
    if bucket<work or capacity<work or not math.isfinite(capacity):
        raise ValueError("finite capacity and bucket must fit a packet")
    pending=deque();tokens=bucket;previous=0.;releases=[];maximum=0
    for arrival in arrivals:
        while pending and pending[0]<=arrival: pending.popleft()
        if (len(pending)+1)*work>capacity+1e-12:
            releases.append(None);continue
        at=max(arrival,previous)
        tokens=min(bucket,tokens+refill.integrate(previous,at))
        if tokens<work:
            at=refill.finish_time(at,work-tokens);tokens=0.
            if not math.isfinite(at): raise RuntimeError("source horizon exhausted")
        else: tokens-=work
        releases.append(at);previous=at
        # Capacity counts full unreleased packets; instantaneous releases take
        # precedence over arrivals at the same time and consume no queue space.
        if at>arrival: pending.append(at)
        maximum=max(maximum,len(pending))
    return releases,maximum*work


def constant_refill(trace,rate):
    h=_canonical_digest([rate,trace.drain_horizon])
    return _ServiceTrace([0.],[trace.drain_horizon],[rate],trace.observation_duration,
        trace.drain_horizon,False,0.,rate,rate,h,h,h)


def run(rho,pmr,tau_b,tau_s,seed,*,mode,capacity=None,bias=0.,lag=0.,bucket=.1,measured=10000,warmup=256):
    if mode not in ("fifo","priority","fixed","feedback"): raise ValueError("unknown mode")
    if not .03<rho<=1 or pmr<1 or min(tau_b,tau_s,measured,warmup)<=0: raise ValueError("invalid inputs")
    end=float(warmup+measured);guard=max(512.,32*tau_b,32*tau_s)
    traffic_end=end+guard;horizon=traffic_end+64
    trace=base.service_trace(float(warmup),end,horizon,tau_s,seed,True)
    bulk=base.bulk_arrivals(float(warmup),end,traffic_end,rho-.03,pmr,tau_b,seed,True)
    refill=None;source_max=0.
    if mode in ("fifo","priority"):
        releases=bulk
    else:
        refill=constant_refill(trace,rho-.03) if mode=="fixed" else biased_refill(trace,rho,lag,bias)
        releases,source_max=finite_shape(bulk,refill,bucket,capacity)
    if any(warmup<=a<end and r is not None and r>=traffic_end for a,r in zip(bulk,releases)):
        raise RuntimeError("source cohort exceeds live guard")
    original={"control":[float(i) for i in range(math.ceil(traffic_end))],
        "sensor":[float(i) for i in range(0,math.ceil(traffic_end),2)],"bulk":bulk}
    released={**original,"bulk":releases};work={"control":.01,"sensor":.04,"bulk":.1}
    rows=[];lookup={};events=[]
    for rank,kind in enumerate(("control","sensor","bulk")):
        for packet_id,(arrival,release) in enumerate(zip(original[kind],released[kind])):
            if warmup<=arrival<end:
                lookup[(kind,packet_id)]=len(rows)
                rows.append(dict(class_=kind,packet_id=packet_id,arrival=arrival,release=release,
                    shaper_delay=None if release is None else release-arrival,work=work[kind],
                    completion=None,status="dropped" if release is None else "unfinished",
                    drop_stage="source" if release is None else "",latency=None,
                    deadline_miss=True if kind=="control" else None))
                rows[-1]["class"]=rows[-1].pop("class_")
            if release is not None and release<traffic_end: events.append((release,rank,kind,packet_id))
    events.sort();scheduler=_PriorityScheduler() if mode=="priority" else _FifoScheduler()
    occupied=0.;in_service=None;started=0.;departure=math.inf;sink_bulk=0.
    def start(at):
        nonlocal in_service,started,departure
        in_service=scheduler.pop_next();started=at
        departure=trace.finish_time(at,in_service.work) if in_service else math.inf
        if in_service and not math.isfinite(departure): raise RuntimeError("service horizon exhausted")
    def finish(at):
        nonlocal occupied,sink_bulk
        p=in_service;occupied=max(0.,occupied-p.work)
        if p.kind=="bulk" and warmup<=at<end: sink_bulk+=p.work
        if p.row_index is not None:
            row=rows[p.row_index];latency=at-row["arrival"]
            row.update(completion=at,status="delivered",latency=latency)
            if p.kind=="control": row["deadline_miss"]=latency>=1
        start(at)
    for at,rank,kind,packet_id in events:
        while departure<=at: finish(departure)
        residual=occupied
        if in_service: residual-=min(in_service.work,trace.integrate(started,at))
        index=lookup.get((kind,packet_id))
        if residual+work[kind]>10.:
            if index is not None: rows[index].update(status="dropped",drop_stage="link")
        else:
            occupied+=work[kind];scheduler.push(_Packet(kind,packet_id,at,work[kind],index))
            if in_service is None: start(at)
    while departure<=traffic_end: finish(departure)
    if any(r["status"]=="unfinished" for r in rows): raise RuntimeError("unresolved measured cohort")
    summaries={kind:_class_summary(rows,kind,float(measured)) for kind in original}
    tagged=[r for r in rows if r["class"]=="bulk"]
    return dict(packets=rows,summaries=summaries,service_digest=trace.digest,
        bulk_digest=_canonical_digest(bulk),service_mean=trace.integrate(float(warmup),end)/measured,
        source_bulk_dropped=sum(r["drop_stage"]=="source" for r in tagged),
        link_bulk_dropped=sum(r["drop_stage"]=="link" for r in tagged),
        source_max_queued_work=source_max,
        shaper_max_delay=max((r["shaper_delay"] for r in tagged if r["shaper_delay"] is not None),default=0.),
        link_offered_rho=.03+sum(r is not None and warmup<=r<end for r in releases)*.1/measured,
        sink_bulk_goodput=sink_bulk/measured,refill_digest=refill.digest if refill else "")
