"""Balanced jittered waveforms and source-accounted token-bucket experiments.

Separate from the frozen v2 implementation. Units: T=1, mean service=1.
Jittered cycles are bounded uniform renewal-like cycles, balanced within each
cycle and clipped at declared window boundaries; not a measured radio trace.
"""
import heapq
import math
import random
from .timescale_model import (_ServiceTrace, _Packet, _FifoScheduler,
    _PriorityScheduler, _DrrScheduler, _class_summary, _canonical_digest)


def cycles(start, end, mean_width, seed, stream, jitter):
    rng = random.Random(f"robust-v3:{stream}:{seed}")
    at = start
    while at < end - 1e-10:
        width = mean_width * (rng.uniform(.5, 1.5) if jitter else 1.)
        right = min(end, at + width)
        yield at, right
        at = right


def service_trace(warmup, end, horizon, tau_s, seed, jitter):
    starts, ends, rates = [], [], []
    state_rng = random.Random(f"robust-v3:service-state:{seed}")
    for window, (left, right) in enumerate(((0., warmup), (warmup, end), (end, horizon))):
        for a, b in cycles(left, right, 2*tau_s, seed, f"service-{window}", jitter):
            mid = (a+b)/2
            high_first = bool(state_rng.getrandbits(1))
            starts.extend((a, mid)); ends.extend((mid,b))
            rates.extend((1.3,.7) if high_first else (.7,1.3))
    digest = _canonical_digest([starts, ends, rates])
    trace = _ServiceTrace(starts, ends, rates, end, horizon, False, 0., .7, 1.3,
                          digest, digest, digest)
    for a,b in ((0.,warmup),(warmup,end)):
        if not math.isclose(trace.integrate(a,b),b-a,abs_tol=1e-8):
            raise RuntimeError("unbalanced service window")
    return trace


def bulk_arrivals(warmup, end, horizon, mean, pmr, tau_b, seed, jitter, work=.1):
    threshold = (1-random.Random(f"robust-v3:lattice:{seed}").random())*work
    cumulative = 0.
    arrivals = []
    for window,(left,right) in enumerate(((0.,warmup),(warmup,end),(end,horizon))):
        for a,b in cycles(left,right,tau_b,seed,f"bulk-{window}",jitter):
            on_end = a+(b-a)/pmr
            interval_work = (b-a)*mean
            next_cumulative = cumulative + interval_work
            while threshold <= next_cumulative:
                at = a+(threshold-cumulative)/(pmr*mean)
                if at < horizon:
                    arrivals.append(max(a,min(at,on_end)))
                threshold += work
            cumulative = next_cumulative
    return arrivals


def shape(arrivals, rate, bucket, work=.1):
    """Lossless source FIFO token bucket; full initially; releases never early."""
    if not math.isfinite(rate) or rate <= 0 or not math.isfinite(bucket) or bucket < work:
        raise ValueError("rate must be positive and bucket at least one packet")
    tokens, previous = bucket, 0.
    releases = []
    for arrival in arrivals:
        at = max(arrival,previous)
        tokens = min(bucket,tokens+(at-previous)*rate)
        if tokens < work:
            at += (work-tokens)/rate
            tokens = 0.
        else:
            tokens -= work
        releases.append(at)
        previous = at
    return releases


def run(rho, pmr, tau_b, tau_s, seed, *, policy="fifo", bucket=None,
        jitter_bulk=True, jitter_service=True, measured=10000, warmup=256):
    if not (0.03 < rho < 1.5 and pmr >= 1 and tau_b > 0 and tau_s > 0):
        raise ValueError("invalid waveform inputs")
    if policy not in ("fifo","strict_priority","drr"):
        raise ValueError("unknown policy")
    if measured < 1 or warmup < 1:
        raise ValueError("positive observation counts required")
    end = float(warmup+measured)
    guard = max(512.,32*tau_b,32*tau_s)
    traffic_end, horizon = end+guard, end+guard+64
    trace = service_trace(float(warmup),end,horizon,tau_s,seed,jitter_service)
    original_bulk = bulk_arrivals(float(warmup),end,traffic_end,rho-.03,pmr,tau_b,seed,jitter_bulk)
    released_bulk = original_bulk if bucket is None else shape(original_bulk,rho-.03,bucket)
    if any(a < end and a >= warmup and r >= traffic_end for a,r in zip(original_bulk,released_bulk)):
        raise RuntimeError("measured source packet exceeded live-background guard")
    original = {"control":[float(i) for i in range(math.ceil(traffic_end))],
                "sensor":[float(i) for i in range(0,math.ceil(traffic_end),2)],
                "bulk":original_bulk}
    released = {**original,"bulk":released_bulk}
    work = {"control":.01,"sensor":.04,"bulk":.1}
    scheduler = {"fifo":_FifoScheduler,"strict_priority":_PriorityScheduler}.get(policy)
    scheduler = scheduler() if scheduler else _DrrScheduler({"control":.01,"sensor":.01,"bulk":.18})
    rows, lookup, events = [], {}, []
    for rank,kind in enumerate(("control","sensor","bulk")):
        for packet_id,(arrival,release) in enumerate(zip(original[kind],released[kind])):
            if warmup <= arrival < end:
                lookup[(kind,packet_id)] = len(rows)
                rows.append(dict(class_=kind,packet_id=packet_id,arrival=arrival,
                    release=release,shaper_delay=release-arrival,work=work[kind],
                    completion=None,status="unfinished",latency=None,
                    deadline_miss=True if kind=="control" else None))
                rows[-1]["class"] = rows[-1].pop("class_")
            if release < traffic_end:
                events.append((release,rank,kind,packet_id))
    events.sort()
    occupied, in_service, started, departure = 0.,None,0.,math.inf
    sink_work = {kind:0. for kind in original}
    def start(at):
        nonlocal in_service,started,departure
        in_service = scheduler.pop_next()
        started = at
        departure = trace.finish_time(at,in_service.work) if in_service else math.inf
        if in_service and not math.isfinite(departure):
            raise RuntimeError("insufficient service horizon")
    def finish(at):
        nonlocal occupied
        packet = in_service
        occupied = max(0.,occupied-packet.work)
        if warmup <= at < end:
            sink_work[packet.kind] += packet.work
        if packet.row_index is not None:
            row = rows[packet.row_index]
            latency = at-row["arrival"]
            row.update(completion=at,status="delivered",latency=latency)
            if packet.kind=="control": row["deadline_miss"] = latency >= 1.
        start(at)
    for at,rank,kind,packet_id in events:
        while departure <= at:
            finish(departure)
        residual = occupied
        if in_service:
            residual -= min(in_service.work,trace.integrate(started,at))
        row_index = lookup.get((kind,packet_id))
        if residual + work[kind] > 10.:
            if row_index is not None: rows[row_index]["status"] = "dropped"
        else:
            occupied += work[kind]
            scheduler.push(_Packet(kind,packet_id,at,work[kind],row_index))
            if in_service is None: start(at)
    while departure <= traffic_end:
        finish(departure)
    if any(row["status"]=="unfinished" for row in rows):
        raise RuntimeError("unresolved measured packet at live-background guard")
    summaries = {kind:_class_summary(rows,kind,float(measured)) for kind in original}
    measured_bulk = [row for row in rows if row["class"]=="bulk"]
    return dict(packets=rows,summaries=summaries,service_digest=trace.digest,
        bulk_digest=_canonical_digest(original_bulk),
        bulk_offered_work=summaries["bulk"]["generated_work"],
        service_mean=trace.integrate(float(warmup),end)/measured,
        sink_bulk_goodput=sink_work["bulk"]/measured,
        shaper_max_delay=max((row["shaper_delay"] for row in measured_bulk),default=0.),
        rho=rho,pmr=pmr,tau_b=tau_b,tau_s=tau_s,seed=seed,policy=policy,bucket=bucket)
