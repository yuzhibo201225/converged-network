"""Python replay of the declared ns-3 nanosecond source-gate contract.

Separate implementation language, not independent authorship or proof review.
"""
import math
from collections import deque


def replay(row, bulk):
    rho=float(row['rho']);nominal=float(row['nominal_bps']) if 'nominal_bps' in row else 6000000.
    T=float(row['T']);lag=float(row['lag'])*T;dwell=float(row['tauS'])*T
    phase=float(row['service_phase_fraction'])*2*dwell;bias=float(row['bias'])
    bucket=.1*nominal*T;capacity=float(row['capacity'])*nominal*T;bits=12000.
    def rate_at(t):
        if row['shape']=='fixed': return (rho-.03)*nominal
        position=math.fmod(t-lag-1+phase,2*dwell)
        if position<0: position+=2*dwell
        return (rho*((.7 if position<dwell else 1.3)+bias)-.03)*nominal
    def next_boundary(t):
        if row['shape']!='feedback': return math.inf
        position=math.fmod(t-lag-1+phase,2*dwell)
        if position<0: position+=2*dwell
        width=dwell-math.fmod(position,dwell)
        if width<2e-9: width=dwell
        return t+width
    def ns_after(now, delay): return now+math.floor(max(1e-9,delay)*1e9+.5)
    arrivals=[round(float(p['generated_s'])*1e9) for p in bulk]
    if row['shape']=='none': return [t*1e-9 for t in arrivals]
    released=[None]*len(bulk);pending=deque();tokens=bucket;last=1.;rate=rate_at(last)
    next_wake=math.inf;i=0
    while i<len(bulk) or pending:
        arriving=i<len(bulk) and arrivals[i]<=next_wake
        now_ns=arrivals[i] if arriving else next_wake
        now=now_ns*1e-9
        tokens=min(bucket,tokens+rate*(now-last));last=now;rate=rate_at(now+1e-9)
        while pending and tokens+rate*1e-9>=bits:
            released[pending.popleft()]=now;tokens-=bits
        if arriving:
            if not pending and tokens+rate*1e-9>=bits: tokens-=bits;released[i]=now
            elif (len(pending)+1)*bits<=capacity+1e-3: pending.append(i)
            i+=1
        boundary=next_boundary(now)
        next_wake=ns_after(now_ns,boundary-now) if math.isfinite(boundary) else math.inf
        if pending: next_wake=min(next_wake,ns_after(now_ns,(bits-tokens)/rate))
    return released
