"""Existing-theory input-only NC baseline; not a claimed new method."""
import math

LOW=.7
HIGH=1.3


def beta(t,width=50.,mode='budget'):
    if t<0 or width<=0 or mode not in ('budget','minimum','mean'):raise ValueError('curve inputs')
    if mode=='mean':return t
    if mode=='minimum':return LOW*t
    if t<=width:return LOW*t
    n=math.floor(t/width);r=t-n*width
    return n*width+min(LOW*r,HIGH*r-(1-LOW)*width)


def inverse(y,width=50.,mode='budget'):
    if y<0 or width<=0 or mode not in ('budget','minimum','mean'):raise ValueError('inverse inputs')
    if mode=='mean':return y
    if mode=='minimum':return y/LOW
    if y<=LOW*width:return y/LOW
    n=max(1,math.floor(y/width+1-LOW));base=(n-(1-LOW))*width
    middle=(n+LOW/2)*width
    if y<=middle:return n*width+(y-base)/HIGH
    return n*width+width/2+(y-middle)/LOW


def arrival_right(t,rho,pmr=3.,cycle=8.):
    """Right-limit upper envelope; value at0 means0+, not alpha(0)."""
    if t<0 or not(.03<rho<1) or pmr<1 or cycle<=0:raise ValueError('arrival inputs')
    n=math.floor(t/cycle);r=t-n*cycle
    bulk=(rho-.03)*(cycle*n+pmr*min(r,cycle/pmr))+.1
    return .01*(math.floor(t)+1)+.04*(math.floor(t/2)+1)+bulk


def curve_knots(limit,width,mode):
    if mode!='budget':return [0.,limit]
    knots={0.,limit,width}
    for n in range(1,math.ceil(limit/width)+1):knots.update((n*width,(n+.5)*width))
    return sorted(t for t in knots if 0<=t<=limit)


def bounds(rho,width=50.,mode='budget',pmr=3.,cycle=8.):
    sigma=.15+(rho-.03)*cycle*(1-1/pmr)
    if mode=='minimum' and rho>LOW:
        return dict(backlog_work=math.inf,delay_T=math.inf,tail_cutoff_T=None,
                    backlog_at_T=None,delay_at_T=None)
    if mode=='minimum' and rho==LOW:
        if not float(cycle).is_integer():raise ValueError('equal-rate periodic cutoff needs integer cycle')
        horizon=math.lcm(2,int(cycle))
    else:
        service_rate=LOW if mode=='minimum' else 1.
        deficit=(1-LOW)*width if mode=='budget' else 0.
        horizon=(sigma+deficit)/(service_rate-rho)+1.
    knots={0.,float(horizon)}
    knots.update(float(t) for t in range(math.ceil(horizon)+1) if t<=horizon)
    for n in range(math.ceil(horizon/cycle)+1):
        knots.update(t for t in (n*cycle,n*cycle+cycle/pmr) if t<=horizon)
    knots.update(curve_knots(horizon,width,mode))
    ordered=sorted(knots)
    inv_levels=[beta(t,width,mode) for t in curve_knots(inverse(arrival_right(horizon,rho,pmr,cycle),width,mode)+width,width,mode)]
    backlog=(-math.inf,0.);delay=(-math.inf,0.)
    for i,t in enumerate(ordered):
        value=arrival_right(t,rho,pmr,cycle)
        candidate=(value-beta(t,width,mode),t)
        if candidate[0]>backlog[0]:backlog=candidate
        candidate=(inverse(value,width,mode)-t,t)
        if candidate[0]>delay[0]:delay=candidate
        if i+1<len(ordered):
            hi=ordered[i+1];mid=(t+hi)/2
            slope=pmr*(rho-.03) if mid%cycle<cycle/pmr else 0.
            if slope:
                for level in inv_levels:
                    crossing=t+(level-value)/slope
                    if t<crossing<hi:
                        candidate=(inverse(level,width,mode)-crossing,crossing)
                        if candidate[0]>delay[0]:delay=candidate
            # Left endpoint limit at hi can matter for nonconvex inverse slopes;
            # arrival right jumps upward there, so its right value dominates.
    return dict(backlog_work=backlog[0],delay_T=delay[0],tail_cutoff_T=horizon,
                backlog_at_T=backlog[1],delay_at_T=delay[1])


ALLOWED=('rho','queue','capacity','guard','pmr','bulk_cycle','deadline_T','observation_bin_T')


def qualify(inputs,mode='budget'):
    if set(inputs)!=set(ALLOWED):raise ValueError('only declared contract inputs allowed')
    if inputs['queue'] not in ('fifo','priority'):raise ValueError('queue')
    b=bounds(float(inputs['rho']),float(inputs['observation_bin_T']),mode,
             float(inputs['pmr']),float(inputs['bulk_cycle']))
    control_bound=b['delay_T'] if inputs['queue']=='fifo' else .11/LOW
    # Future high-class arrivals<=.03t+.05; bulk class is internally FIFO.
    # beta(t)>=t-.3Delta in the budget contract. Clearing old work<=Q+.1
    # is sufficient despite high-class overtaking; lower classes cannot overtake
    # the bulk FIFO, and for higher classes this is also conservative.
    if mode=='minimum':
        finish_bound=(inputs['capacity']+.15)/(LOW-.03)
    else:
        deficit=.3*inputs['observation_bin_T'] if mode=='budget' else 0.
        finish_bound=(inputs['capacity']+.15+deficit)/.97
    safe=control_bound<inputs['deadline_T'] and b['backlog_work']<inputs['capacity']-1e-8 and finish_bound<inputs['guard']
    return dict(mode=mode,qualified=bool(safe),valid_for_uncertainty_set=mode!='mean',
                control_delay_upper_T=control_bound,old_packet_finish_upper_T=finish_bound,**b)
