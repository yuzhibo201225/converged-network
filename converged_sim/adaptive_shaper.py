"""Delayed perfect-capacity feedback shaping, separated from frozen models.

Offline DES solves eventual release timestamps. A release at t depends only on
source arrivals up to t and capacity up to t-lag; it does not predict capacity.
Exact delayed telemetry is an explicit privileged modelling assumption.
"""
import math
from unittest.mock import patch
from . import robustness_model
from .timescale_model import _ServiceTrace,_canonical_digest


def refill_trace(trace,rho,lag,reserve=.03):
    if lag<0 or not math.isfinite(lag) or not 0<rho<=1:
        raise ValueError("require nonnegative finite lag and 0 < rho <= 1")
    horizon=trace.drain_horizon
    starts=[0.]
    rates=[rho*trace.rates[0]-reserve]
    for start,rate in zip(trace.starts,trace.rates):
        at=start+lag
        if 0<at<horizon:
            starts.append(at);rates.append(rho*rate-reserve)
    ends=starts[1:]+[horizon]
    if min(rates)<=0: raise ValueError("feedback rate cannot be positive after reserve")
    h=_canonical_digest([starts,ends,rates])
    return _ServiceTrace(starts,ends,rates,trace.observation_duration,horizon,
        False,0.,min(rates),max(rates),h,h,h)


def shape(arrivals,refill,bucket,work=.1):
    if bucket<work: raise ValueError("bucket must fit one packet")
    tokens,previous=bucket,0.
    releases=[]
    for arrival in arrivals:
        at=max(arrival,previous)
        tokens=min(bucket,tokens+refill.integrate(previous,at))
        if tokens<work:
            at=refill.finish_time(at,work-tokens);tokens=0.
            if not math.isfinite(at): raise RuntimeError("adaptive source queue exceeded horizon")
        else: tokens-=work
        releases.append(at);previous=at
    return releases


def run(rho,pmr,tau_b,tau_s,seed,*,lag,bucket=.1,measured=10000,warmup=256):
    end=float(warmup+measured);guard=max(512.,32*tau_b,32*tau_s)
    trace=robustness_model.service_trace(float(warmup),end,end+guard+64,tau_s,seed,True)
    refill=refill_trace(trace,rho,lag)
    def adapter(arrivals,ignored_rate,ignored_bucket,work=.1):
        return shape(arrivals,refill,bucket,work)
    # Scoped injection avoids changing the frozen v3/v4 event engine or any
    # running process. Each process executes experiments sequentially; this
    # adapter is deliberately not a thread-safe shared-library API.
    with patch.object(robustness_model,"shape",adapter):
        result=robustness_model.run(rho,pmr,tau_b,tau_s,seed,bucket=bucket,
            measured=measured,warmup=warmup,jitter_bulk=True,jitter_service=True)
    result["lag"]=lag
    result["feedback_refill_digest"]=refill.digest
    result["control_delay_sufficient_bound"]=(bucket+.05+.6*rho*lag)/.7
    count=sum(warmup<=r<end for r in shape(
        robustness_model.bulk_arrivals(float(warmup),end,end+guard,rho-.03,pmr,tau_b,seed,True),refill,bucket))
    result["link_offered_rho"] = .03+count*.1/measured
    return result
