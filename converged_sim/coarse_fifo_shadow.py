"""FIFO cross-check via cumulative-service coordinates, separate integrator."""
from bisect import bisect_right
from collections import deque
import math


def shadow(events,starts,ends,rates,capacity,begin,end):
    prefix=[0.]
    for a,b,r in zip(starts,ends,rates):prefix.append(prefix[-1]+(b-a)*r)
    def cumulative(t):
        j=bisect_right(starts,t)-1
        return prefix[j]+(t-starts[j])*rates[j]
    def inverse(work):
        j=bisect_right(prefix,work)-1
        if j>=len(rates):return ends[-1] if work==prefix[-1] else math.inf
        return starts[j]+(work-prefix[j])/rates[j]
    scheduled=deque();pending_work=0.;ready_work=0.;answer={}
    for arrival,flow,pid,work in sorted(events,key=lambda p:(p[0],p[1],p[2])):
        while scheduled and scheduled[0][0]<=arrival:
            _,w=scheduled.popleft();pending_work-=w
        # The first pending packet is in service, not in the waiting buffer.
        waiting=pending_work-(scheduled[0][1] if scheduled else 0.)
        if scheduled and waiting+work>capacity+1e-10:
            status='dropped';at=None
        else:
            ready_work=max(ready_work,cumulative(arrival))+work
            at=inverse(ready_work);status='completed' if math.isfinite(at) else 'unresolved'
            scheduled.append((at,work));pending_work+=work
        if begin<=arrival<end:answer[(flow,pid)]=(status,at)
    return answer
