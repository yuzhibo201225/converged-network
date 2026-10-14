# SPDX-License-Identifier: GPL-3.0-only
"""Modeling translation of selected CellReplay release semantics, not native replay.

Based on CellularQueue at commit2ca662cb01a222dd7fcc10f9ed79293803b4ef21,
https://github.com/williamsentosa95/cellreplay . Original GPL notices retained
in acquired source. This notice applies to this translation, not the whole repo.
"""
import math
import struct


def f32(x):return struct.unpack('f',struct.pack('f',x))[0]
def cpp_round(x):return math.floor(x+.5) if x>=0 else math.ceil(x-.5)


class ReleasePlanner:
    def __init__(self,records,offsets,timer=0):
        if len(records)<3 or timer<0:raise ValueError('records/timer')
        self.records=records;self.offsets=offsets;self.timer=timer
        self.index=0;self.base=-1;self.last_raw_release=0;self.end_release=0
        self.pdo_origin=0;self.pdo_index=0;self.remaining=1400;self.previous_arrival=-1

    def offset(self,size):
        if not self.offsets:return 0.
        idx=size//100-1;rem=size%100
        if idx<0:return self.offsets[0]
        if idx>=len(self.offsets)-1:return self.offsets[-1]
        return self.offsets[idx]+rem/100*(self.offsets[idx+1]-self.offsets[idx])

    def plan(self,time,size):
        if time<self.previous_arrival or time>=self.records[-1][0] or not(0<size<=1400):raise ValueError('bounded ordered input; no wrap or oversized content')
        self.previous_arrival=time
        reset=self.base<0 or time+self.base>self.last_raw_release+self.timer
        if reset:
            while self.records[self.index+1][0]<=time:self.index+=1
            t,d,pdo=self.records[self.index];nt,nd,_=self.records[self.index+1]
            ratio=f32(f32(time-t)/f32(nt-t));adjusted=f32(ratio*f32(nd-d))
            self.base=int(f32(f32(d)+adjusted));raw=time+self.base;bypass=True
            self.pdo_origin=time;self.pdo_index=0;self.remaining=1400-size
        else:
            _,_,pdo=self.records[self.index];relative=time-self.pdo_origin
            while self.pdo_index<len(pdo) and relative>pdo[self.pdo_index]:
                self.pdo_index+=1;self.remaining=1400
            if self.remaining<size:self.pdo_index+=1;self.remaining=1400
            self.remaining-=size
            if self.pdo_index>=len(pdo):raw=max(time+self.base,time+pdo[-1]);bypass=False
            else:raw=time+self.base+pdo[self.pdo_index]-relative;bypass=True
        self.last_raw_release=raw
        compensation=cpp_round(self.offset(size))
        release=raw+compensation if raw+compensation>=self.end_release else raw
        clamped=release<self.end_release
        if clamped:release=self.end_release;bypass=False
        self.end_release=release
        return dict(arrival_ms=time,content_bytes=size,raw_release_ms=raw,release_ms=release,
                    planned_delay_ms=release-time,base_delay_ms=self.base,light_reset=reset,
                    planned_light_bypass=bypass,release_clamped=clamped)
