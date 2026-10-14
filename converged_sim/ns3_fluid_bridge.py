"""Post-hoc matched-input fluid FIFO diagnostic, not a primary experiment.

Same ns-3 source-release records/periodic service; fluid service integrates
changes within a frame. Infinite buffer diagnostic only; ns-3 loss is checked.
"""
import argparse
import csv
import gzip
import json
import math
from pathlib import Path
from ns3_validation.feedback_cli import digest,p99
from .timescale_model import _ServiceTrace


def run(source,analysis,out):
    source=Path(source);analysis=Path(analysis);out=Path(out)
    if out.exists(): raise FileExistsError(out)
    a=json.loads((analysis/'audit.json').read_text());m=json.loads((source/'manifest.json').read_text())
    if a['status']!='PASS' or digest(source/'manifest.json')!=a['manifest_sha256']: raise ValueError('source audit required')
    out.mkdir(parents=True);rows=[];raw_count=0;input_count=0
    with gzip.open(out/'control_pairs.csv.gz','wt',newline='') as handle:
        writer=csv.writer(handle);writer.writerow(('run_id','control_id','fluid_latency_T','ns3_latency_T'))
        for i in range(m['planned_runs']):
            with (source/f'{i}-summary.csv').open() as h: r=list(csv.DictReader(h))[0]
            if r['shape']=='none': continue
            if digest(source/f'{i}-packets.csv')!=m['receipts'][str(i)]['packets']: raise ValueError('input changed')
            with (source/f'{i}-packets.csv').open() as h: packets=list(csv.DictReader(h))
            if any(p['status']!='delivered' for p in packets): raise ValueError('loss-free bridge required; do not silently select delivered packets')
            T=float(r['T']);mean=float(r['nominal_bps']);dwell=float(r['tauS']);phase=float(r['service_phase_fraction'])*2*dwell
            horizon=(float(r['stop_s'])-1)/T+1
            starts=[0.]+[k*dwell-phase for k in range(1,math.ceil((horizon+phase)/dwell)) if 0<k*dwell-phase<horizon]
            rates=[.7 if (t+phase+1e-8)%(2*dwell)<dwell else 1.3 for t in starts]
            trace=_ServiceTrace(starts,starts[1:]+[horizon],rates,horizon,horizon,False,0,.7,1.3,'','','')
            sizes={'1':150,'2':600,'3':1500};events=[];previous_release={}
            for p in packets:
                flow=p['flow'];release=float(p['released_s']);frame=(sizes[flow]+2)*8
                if flow in previous_release and release-previous_release[flow]<frame/1e8-1e-8:
                    raise ValueError('access overlap requires a fuller access-queue model')
                previous_release[flow]=release
                # Constant access serialization + propagation; PPP framing included.
                arrival=(release-1+.00005+frame/1e8)/T
                events.append((arrival,int(flow),int(p['id']),frame/(mean*T),p))
            ready=0.;control=[];bulk=[]
            for arrival,flow,pid,work,p in sorted(events,key=lambda e:e[:3]):
                ready=trace.finish_time(max(ready,arrival),work)
                if not math.isfinite(ready): raise ValueError('fluid horizon exhausted')
                latency=ready+.0002/T-(float(p['generated_s'])-1)/T
                if p['measured']=='1':
                    if flow==1:
                        control.append(latency);writer.writerow((i,pid,latency,p['latency_T']));raw_count+=1
                    elif flow==3: bulk.append(latency)
            if len(control)!=int(r['control_generated']): raise ValueError('control bridge cohort')
            row={k:r[k] for k in ('rho','R','tauB','shape','bias','run')};row['run_id']=i
            row.update(fluid_control_p99_T=p99(control),ns3_control_p99_T=float(r['control_p99_T']),
                       fluid_control_miss_ratio=sum(t>=1 for t in control)/len(control),ns3_control_miss_ratio=float(r['control_miss_ratio']),
                       fluid_bulk_p99_T=p99(bulk),ns3_bulk_p99_T=float(r['bulk_p99_T']))
            rows.append(row);input_count+=len(packets)
            if len(rows)%10==0: print(f'fluid bridge {len(rows)}/80',flush=True)
    # Independently recompute control endpoints from the retained paired raw file.
    cohorts={}
    with gzip.open(out/'control_pairs.csv.gz','rt') as h:
        for p in csv.DictReader(h): cohorts.setdefault(int(p['run_id']),[]).append(float(p['fluid_latency_T']))
    for r in rows:
        v=cohorts[r['run_id']]
        if len(v)!=10000 or abs(p99(v)-r['fluid_control_p99_T'])>1e-10: raise ValueError('bridge raw P99')
    with (out/'runs.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    receipt=dict(status='PASS',runs=len(rows),input_all_flow_records=input_count,raw_control_pairs=raw_count,
                 scope='post-hoc loss-free shaped FIFO matched-input fluid diagnostic; raw control P99 replay',
                 source_manifest_sha256=a['manifest_sha256'],source_audit_sha256=digest(analysis/'audit.json'),
                 code_sha256=digest(__file__),outputs_sha256={n:digest(out/n) for n in ('runs.csv','control_pairs.csv.gz')})
    (out/'audit.json').write_text(json.dumps(receipt,indent=2));return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--analysis',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.input,a.analysis,a.out),flush=True)
