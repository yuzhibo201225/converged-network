"""Generate declared arrivals from a contract; never import packet outcomes."""
import math
from .scenario_predictor import Emission

MASK=(1<<64)-1


def uniform(seed,run,salt):
    x=(((seed<<32)^run^salt)+0x9e3779b97f4a7c15)&MASK
    x=((x^(x>>30))*0xbf58476d1ce4e5b9)&MASK
    x=((x^(x>>27))*0x94d049bb133111eb)&MASK
    return (x^(x>>31))>>11


def fractions(seed,run):
    def u(salt):return uniform(seed,run,salt)/9007199254740992.
    return u(0x42554c4b),1-u(0x4c415454),u(0x53455256)


def emissions(rho,R,tauB,warm,measured,seed,run):
    if not(.03<rho<1 and R>=1 and tauB>0 and warm>=0 and measured>0):raise ValueError('invalid traffic contract')
    T=.02;start=1.;end=start+(warm+measured)*T
    phase,lattice,_=fractions(seed,run);cycle=tauB*T;on=cycle/R
    origin=start-phase*cycle;rate=R*(rho-.03)*6000000.
    result=[Emission(1,i,start+i*T) for i in range(warm+measured)]
    result.extend(Emission(2,i,start+i*2*T) for i in range((warm+measured)//2))
    cumulative=0.;seq=0;threshold=lattice*12000.
    for c in range(math.floor((start-origin)/cycle)-1,math.ceil((end-origin)/cycle)+2):
        lo=max(start,origin+c*cycle);hi=min(end,origin+c*cycle+on)
        if hi<=lo+1e-9:continue
        amount=(hi-lo)*rate
        while threshold<=cumulative+amount+1e-6:
            at=lo+(threshold-cumulative)/rate
            if at>=start-1e-9 and at<end-1e-9:result.append(Emission(3,seq,max(start,at)))
            seq+=1;threshold=(seq+lattice)*12000.
        cumulative+=amount
    return result
