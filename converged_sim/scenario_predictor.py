"""Input-only scenario planning baseline; standard FIFO recurrence, not new theory.

Whole prescribed service scenarios are allowed. This is NOT an online guard.
Actual source releases/sink outcomes are excluded from the prediction interface.
"""
import argparse
import csv
import gzip
import json
import math
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from ns3_validation.renewal_cli import cases,digest,dump,p99
from ns3_validation.renewal_gate import replay
from .timescale_model import _ServiceTrace

INPUT_FIELDS=('rho','shape','queue','bias','lag','capacity','T','tauS','nominal_bps',
              'traceCsv','warm','measured','begin_s','end_s','stop_s','service_phase_fraction')
SIZES={1:150,2:600,3:1500}


@dataclass(frozen=True)
class Emission:
    flow:int
    packet_id:int
    generated_s:float


def predict(parameters,emissions):
    if set(parameters)!=set(INPUT_FIELDS):raise ValueError('prediction accepts declared inputs only')
    if parameters['queue']!='fifo' or parameters['shape'] not in ('feedback','fixed'):
        raise ValueError('only shaped FIFO scenarios supported')
    if any(not isinstance(e,Emission) for e in emissions):raise ValueError('emission interface excludes outcome fields')
    if len({(e.flow,e.packet_id) for e in emissions})!=len(emissions):raise ValueError('duplicate emission ID')
    with Path(parameters['traceCsv']).open() as h:tr=[(float(t),float(v)) for t,v in csv.reader(h)]
    T=float(parameters['T']);nominal=float(parameters['nominal_bps']);stop=float(parameters['stop_s'])
    starts_ns=[round(t*1e9) for t,_ in tr];rates=[v for _,v in tr]
    horizon=(stop-1)/T+1
    starts=[(t-1)/T for t,_ in tr]
    trace=_ServiceTrace(starts,starts[1:]+[horizon],rates,horizon,horizon,False,0,.7,1.3,'','','')
    bulk=[e for e in emissions if e.flow==3]
    releases=replay(parameters,[{'generated_s':e.generated_s} for e in bulk])
    release_map={e.packet_id:at for e,at in zip(bulk,releases)}
    events=[];access_ready={};access_pending={flow:deque() for flow in SIZES};source_drops=0
    for e in emissions:
        release=release_map[e.packet_id] if e.flow==3 else e.generated_s
        if release is None:
            if float(parameters['begin_s'])<=e.generated_s<float(parameters['end_s']):source_drops+=1
            continue
        release_ns=round(release*1e9);frame_bits=(SIZES[e.flow]+2)*8
        pending=access_pending[e.flow]
        while pending and pending[0]<=release_ns:pending.popleft()
        if len(pending)>=20:raise ValueError('access queue requires explicit drop model')
        access_start=max(release_ns,access_ready.get(e.flow,0))
        access_ready[e.flow]=access_start+round(frame_bits*1e9/100_000_000)
        pending.append(access_ready[e.flow])
        events.append((access_ready[e.flow]+50_000,e.flow,e.packet_id,frame_bits,e.generated_s))
    ready_ns=0;fluid_ready=0.;outstanding=deque();pending_bytes=0;max_pending=0
    delays={kind:{1:{},3:{}} for kind in ('packet','fluid')}
    begin=float(parameters['begin_s']);end=float(parameters['end_s'])
    for arrival,flow,pid,bits,generated in sorted(events):
        while outstanding and outstanding[0][0]<=arrival:
            _,size=outstanding.popleft();pending_bytes-=size
        # A conservative scope guard, not a loss model: includes the in-service
        # frame, so staying below the qdisc byte capacity is sufficient here.
        pending_bytes+=SIZES[flow];max_pending=max(max_pending,pending_bytes)
        if pending_bytes>150000:raise ValueError('finite router buffer requires explicit drop model')
        tx_start=max(ready_ns,arrival)
        rate=round(nominal*rates[max(0,bisect_right(starts_ns,tx_start)-1)])
        ready_ns=tx_start+math.floor(bits*1e9/rate+.5)
        outstanding.append((ready_ns,SIZES[flow]))
        fluid_ready=trace.finish_time(max(fluid_ready,(arrival/1e9-1)/T),bits/(nominal*T))
        if not math.isfinite(fluid_ready):raise ValueError('insufficient fluid horizon')
        if flow in (1,3) and begin-1e-9<=generated<end-1e-9:
            delays['packet'][flow][pid]=(ready_ns/1e9+.0002-generated)/T
            delays['fluid'][flow][pid]=fluid_ready+.0002/T-(generated-1)/T
    return dict(delays=delays,source_drop_count=source_drops,max_outstanding_ip_bytes=max_pending)


def model_hashes():
    root=Path(__file__).parents[1]
    return {name:digest(root/name) for name in ('converged_sim/scenario_predictor.py','ns3_validation/renewal_gate.py','converged_sim/timescale_model.py')}


def run(raw,analysis,out,scope='development',freeze=None):
    raw=Path(raw).resolve();analysis=Path(analysis);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((raw/'manifest.json').read_text());a=json.loads((analysis/'audit.json').read_text())
    if scope=='heldout':
        if freeze is None:raise ValueError('frozen model/config receipt required for heldout label')
        f=json.loads(Path(freeze).read_text())
        if f['model_hashes']!=model_hashes() or m['config_sha256'] not in f['allowed_config_sha256']:
            raise ValueError('heldout model/config not frozen')
        if m['spec']['trace_seed_base']==110000 or m['spec']['tauS']==8:raise ValueError('development-family leakage')
    if a['status']!='PASS' or digest(raw/'manifest.json')!=a['manifest_sha256'] or digest(analysis/'runs.csv')!=a['runs_sha256']:
        raise ValueError('all-flow raw audit required')
    out.mkdir(parents=True);runs=[];input_count=0;control_count=0
    with gzip.open(out/'control_predictions.csv.gz','wt',newline='') as target:
        writer=csv.writer(target);writer.writerow(('ordering','run_index','control_id','packet_prediction_T','fluid_prediction_T','observed_T'))
        for mode in m['spec']['modes']:
            folder=raw/mode;child=json.loads((folder/'manifest.json').read_text())
            ca=json.loads((analysis/mode/'audit.json').read_text())
            if digest(folder/'manifest.json')!=ca['manifest_sha256']:raise ValueError('child audit mismatch')
            for i,case in enumerate(cases(child['spec'])):
                if case['queue']!='fifo' or case['shape']=='none':continue
                for name in ('summary','packets'):
                    if digest(folder/f'{i}-{name}.csv')!=child['receipts'][str(i)][name]:raise ValueError('raw changed')
                with (folder/f'{i}-summary.csv').open() as h:r=list(csv.DictReader(h))[0]
                trace=folder/'traces'/f'{r["run"]}.csv'
                if digest(trace)!=child['trace_sha256'][r['run']]:raise ValueError('trace changed')
                with (folder/f'{i}-packets.csv').open() as h:packets=list(csv.DictReader(h))
                emissions=[Emission(int(p['flow']),int(p['id']),float(p['generated_s'])) for p in packets]
                parameters={k:r[k] for k in INPUT_FIELDS}
                prediction=predict(parameters,emissions) # no observed release/receive fields
                control=[p for p in packets if p['flow']=='1' and p['measured']=='1']
                record={k:r[k] for k in ('rho','R','tauB','tauS','bias','lag','run')}
                record.update(ordering=mode,run_index=i,observed_control_p99_T=float(r['control_p99_T']),
                              observed_control_miss_ratio=float(r['control_miss_ratio']),observed_bulk_p99_T=float(r['bulk_p99_T']),
                              observed_joint_pass=float(r['control_p99_T'])<1 and float(r['control_miss_ratio'])<.01,
                              max_predicted_outstanding_ip_bytes=prediction['max_outstanding_ip_bytes'])
                if len(control)!=int(r['measured']):raise ValueError('control cohort')
                for name in ('packet','fluid'):
                    delays=prediction['delays'][name]
                    if len(delays[1])!=len(control):raise ValueError('predicted control cohort')
                    record[name+'_control_p99_T']=p99(list(delays[1].values()))
                    record[name+'_control_miss_ratio']=sum(v>=1 for v in delays[1].values())/len(control)
                    record[name+'_bulk_p99_T']=p99(list(delays[3].values()))
                    record[name+'_joint_pass']=record[name+'_control_p99_T']<1 and record[name+'_control_miss_ratio']<.01
                    record[name+'_p99_error_T']=record[name+'_control_p99_T']-record['observed_control_p99_T']
                for p in control:
                    if p['status']!='delivered':raise ValueError('observed loss not covered by finite-buffer scope guard')
                    pid=int(p['id']);writer.writerow((mode,i,pid,prediction['delays']['packet'][1][pid],prediction['delays']['fluid'][1][pid],p['latency_T']))
                if prediction['source_drop_count']!=int(r['bulk_source_drop']):raise ValueError('source-loss prediction mismatch')
                runs.append(record);input_count+=len(packets);control_count+=len(control)
                if len(runs)%10==0:print(f'input-only predicted {len(runs)}',flush=True)
    with (out/'runs.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(runs[0]));w.writeheader();w.writerows(runs)
    metrics={}
    for model in ('packet','fluid'):
        metrics[model]=dict(classification_disagreements=sum(r[model+'_joint_pass']!=r['observed_joint_pass'] for r in runs),
                            false_safe=sum(r[model+'_joint_pass'] and not r['observed_joint_pass'] for r in runs),
                            max_abs_control_p99_error_T=max(abs(r[model+'_p99_error_T']) for r in runs))
    result=dict(status='PASS',evaluation_scope=scope,runs=len(runs),input_all_flow_records=input_count,control_predictions=control_count,
                information='full prescribed scenario + generated arrivals; offline planning, NOT online safety',metrics=metrics,
                freeze_sha256=digest(freeze) if freeze is not None else None,
                source_manifest_sha256=digest(raw/'manifest.json'),source_audit_sha256=digest(analysis/'audit.json'),
                code_sha256=digest(__file__),gate_sha256=digest(Path(__file__).parents[1]/'ns3_validation/renewal_gate.py'),
                outputs_sha256={n:digest(out/n) for n in ('runs.csv','control_predictions.csv.gz')})
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--analysis',required=True);p.add_argument('--out',required=True)
    p.add_argument('--scope',choices=('development','heldout'),default='development')
    p.add_argument('--freeze')
    a=p.parse_args();print(run(a.raw,a.analysis,a.out,a.scope,a.freeze))
