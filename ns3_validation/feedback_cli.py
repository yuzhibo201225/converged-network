"""Frozen ns-3 feedback sweep and all-flow/source-clock audit."""
import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import statistics
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def dump(path,data):
    Path(path).write_text(json.dumps(data,indent=2),encoding='utf-8')


def cases(spec):
    for rho,arm,setting,run in itertools.product(spec['loads'],spec['arms'],spec['settings'],spec['runs']):
        yield dict(rho=rho,R=arm['R'],tauB=arm['tauB'],tauS=spec['tauS'],seed=spec['seed'],run=run,
                   measured=spec['measured'],warm=spec['warm'],**setting)


def sweep(config,out,workers=4):
    config=Path(config);out=Path(out).resolve()
    if out.exists(): raise FileExistsError(out)
    spec=json.loads(config.read_text());grid=list(cases(spec))
    exe=ROOT/'ns3_validation/_build_mingw/bin/feedback-validation.exe'
    if not exe.is_file(): raise FileNotFoundError(exe)
    env=dict(os.environ);env['PATH']=str(ROOT/'third_party/msys_extract/ns-3.47/build-mingw/lib')+';C:/msys64/mingw64/bin;'+env['PATH']
    sources=[ROOT/'ns3_validation'/n for n in ('feedback-validation.cc','burst-tail-validation.cc','feedback_cli.py')]
    sources.append(ROOT/'third_party/msys_extract/ns-3.47/src/core/model/time.cc')
    manifest=dict(status='RUNNING',planned_runs=len(grid),completed_runs=0,spec=spec,
                  config_sha256=digest(config),source_sha256={p.name:digest(p) for p in sources},
                  executable_sha256=digest(exe),receipts={})
    out.mkdir(parents=True);dump(out/'manifest.json',manifest)
    def one(i,case):
        args=[str(exe)]+[f'--{k}={v}' for k,v in case.items()]
        args += [f'--summaryCsv={out}/{i}-summary.csv',f'--packetCsv={out}/{i}-packets.csv']
        p=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,timeout=1800,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/f'{i}-log.txt').write_text(p.stdout+p.stderr,encoding='utf-8')
        if p.returncode: raise RuntimeError(f'run {i} failed {p.returncode}: {p.stderr[-1000:]}')
        return i,{name:digest(out/f'{i}-{name}.csv') for name in ('summary','packets')}
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(one,i,c) for i,c in enumerate(grid)]
            for f in as_completed(futures):
                i,receipt=f.result();manifest['receipts'][str(i)]=receipt;manifest['completed_runs']+=1
                dump(out/'manifest.json',manifest)
                if manifest['completed_runs']%10==0: print(f"ns3 feedback {manifest['completed_runs']}/{len(grid)}",flush=True)
        if {p.name:digest(p) for p in sources}!=manifest['source_sha256'] or digest(exe)!=manifest['executable_sha256']:
            raise RuntimeError('source/executable changed during sweep')
        manifest['status']='COMPLETE';dump(out/'manifest.json',manifest)
    except BaseException as e:
        manifest['status']='FAILED';manifest['error']=str(e);dump(out/'manifest.json',manifest);raise
    return dict(status='COMPLETE',runs=len(grid))


def p99(values):
    if not values: return None
    values=sorted(values);p=(len(values)-1)*.99;i=int(p);a=p-i
    return values[i]*(1-a)+values[min(i+1,len(values)-1)]*a


def source_replay(row,bulk):
    from .quantized_gate import replay
    T=float(row['T']);expected=replay(row,bulk)
    for packet,release in zip(bulk,expected):
        if release is None:
            if packet['source_drop']!='1' or packet['released_s']: raise ValueError('source admission replay')
        elif packet['source_drop']=='1' or not packet['released_s'] or abs(float(packet['released_s'])-release)/T>2e-5:
            raise ValueError('source release clock replay')
    # Count the discrete ns-3 statistic from actual timestamps, not infinitesimal
    # waits in the counterfactual unquantized Python replay.
    events=[]
    for p in bulk:
        if p['released_s']:
            a=round(float(p['generated_s'])*1e9);release=round(float(p['released_s'])*1e9)
            if release>a: events.extend(((a,1),(release,-1)))
    occupied=observed_max=0
    for _,change in sorted(events):
        occupied+=change
        if occupied<0: raise ValueError('negative source occupancy')
        observed_max=max(observed_max,occupied)
    if occupied or abs(observed_max*.1-float(row['source_max_work']))>1e-8 or observed_max*.1>float(row['capacity'])+1e-8:
        raise ValueError('source timestamp occupancy/capacity')


def audit(source,out):
    source=Path(source);out=Path(out)
    if out.exists(): raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text());spec=m['spec'];grid=list(cases(spec))
    if m['status']!='COMPLETE' or m['completed_runs']!=len(grid): raise ValueError('incomplete sweep')
    rows=[];pairs=defaultdict(list);groups=defaultdict(list);count=0
    for i,case in enumerate(grid):
        for name in ('summary','packets'):
            if digest(source/f'{i}-{name}.csv')!=m['receipts'][str(i)][name]: raise ValueError('receipt mismatch')
        with (source/f'{i}-summary.csv').open() as h: summaries=list(csv.DictReader(h))
        if len(summaries)!=1: raise ValueError('summary count')
        r=summaries[0]
        for k,v in case.items():
            if k in ('shape','queue'):
                if r[k]!=v: raise ValueError('grid setting')
            elif abs(float(r[k])-float(v))>1e-12: raise ValueError('grid number')
        with (source/f'{i}-packets.csv').open() as h: packets=list(csv.DictReader(h))
        if len({(p['flow'],p['id']) for p in packets})!=len(packets): raise ValueError('duplicate raw ID')
        T=float(r['T']);begin=float(r['begin_s']);end=float(r['end_s']);nominal=float(r['nominal_bps'])
        actual=0.;sizes={1:150,2:600,3:1500};arrival_digest=hashlib.sha256()
        for p in packets:
            flow=int(p['flow']);a=float(p['generated_s']);rel=float(p['released_s']) if p['released_s'] else None
            rec=float(p['received_s']) if p['received_s'] else None
            cohort=begin-1e-9<=a<end-1e-9
            if int(p['measured'])!=cohort: raise ValueError('cohort flag')
            arrival_digest.update(f"{flow}:{p['id']}:{p['generated_s']}\n".encode())
            if p['source_drop']=='1':
                if rel is not None or rec is not None or p['source_send_ok']!='0' or p['status']!='source_drop': raise ValueError('source drop endpoint')
            else:
                if rel is None or rel<a-1e-9: raise ValueError('source release endpoint')
                if abs(float(p['source_wait_T'])-(rel-a)/T)>1e-8: raise ValueError('source waiting')
                if p['source_send_ok']=='1' and begin-1e-9<=rel<end-1e-9: actual+=sizes[flow]*8
                expected_status='source_send_failed' if p['source_send_ok']!='1' else ('delivered' if rec is not None else 'undelivered_after_drain')
                if p['status']!=expected_status: raise ValueError('status mismatch')
            if rec is not None:
                if rel is None or rec<rel or p['source_send_ok']!='1' or abs(float(p['latency_T'])-(rec-a)/T)>1e-8:
                    raise ValueError('sink timing')
            elif p['latency_T']: raise ValueError('undelivered delay')
        control=[p for p in packets if p['flow']=='1' and p['measured']=='1']
        bulk=[p for p in packets if p['flow']=='3' and p['measured']=='1']
        if len(control)!=spec['measured'] or len(control)!=int(r['control_generated']): raise ValueError('control cohort')
        if len(bulk)!=int(r['bulk_generated']): raise ValueError('bulk cohort')
        for flow,cohort in (('control',control),('bulk',bulk)):
            values=[float(p['latency_T']) for p in cohort if p['status']=='delivered']
            if len(values)!=int(r[flow+'_delivered']) or abs(p99(values)-float(r[flow+'_p99_T']))>1e-8: raise ValueError('delivery/P99 summary')
        miss=sum(p['status']!='delivered' or float(p['latency_T'])>=1 for p in control)/len(control)
        if abs(miss-float(r['control_miss_ratio']))>1e-12: raise ValueError('miss summary')
        if sum(p['source_drop']=='1' for p in bulk)!=int(r['bulk_source_drop']): raise ValueError('bulk source loss')
        generated=sum(sizes[int(p['flow'])]*8 for p in packets if p['measured']=='1')/((end-begin)*nominal)
        if abs(generated-float(r['generated_rho']))>1e-10 or abs(generated-float(r['rho']))>1e-5: raise ValueError('generated load')
        if abs(actual/((end-begin)*nominal)-float(r['admitted_rho']))>1e-10: raise ValueError('admitted load')
        source_replay(r,[p for p in packets if p['flow']=='3'])
        r['arrival_digest']=arrival_digest.hexdigest();r['bulk_delivery_ratio']=int(r['bulk_delivered'])/len(bulk)
        r['bulk_loss_ratio']=1-r['bulk_delivery_ratio'];r['bulk_goodput_bps']=int(r['bulk_delivered'])*1500*8/(end-begin)
        r['joint_pass']=float(r['control_p99_T'])<1 and miss<.01
        rows.append(r);pairs[(r['rho'],r['R'],r['tauB'],r['run'])].append(r)
        groups[tuple(r[k] for k in ('rho','R','tauB','shape','queue','bias','lag','capacity'))].append(r)
        count+=len(packets)
        if (i+1)%10==0: print(f'ns3 audited {i+1}/{len(grid)}',flush=True)
    for cohort in pairs.values():
        for field in ('arrival_digest','generated_rho','service_phase_fraction','bulk_phase_fraction','lattice_fraction'):
            if len({r[field] for r in cohort})!=1: raise ValueError('unpaired input '+field)
    points=[]
    for key,cohort in groups.items():
        point=dict(zip(('rho','R','tauB','shape','queue','bias','lag','capacity'),key),n=len(cohort),
                   joint_pass_fraction=sum(r['joint_pass'] for r in cohort)/len(cohort))
        for field in ('control_p99_T','control_miss_ratio','bulk_p99_T','bulk_delivery_ratio','bulk_goodput_bps','admitted_rho'):
            v=[float(r[field]) for r in cohort]
            for suffix,value in (('median',statistics.median(v)),('min',min(v)),('max',max(v))): point[field+'_'+suffix]=value
        points.append(point)
    out.mkdir(parents=True)
    for name,records in (('runs',rows),('points',points)):
        with (out/f'{name}.csv').open('w',newline='') as h:
            w=csv.DictWriter(h,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    result=dict(status='PASS',runs=len(rows),raw_all_flow_packets=count,points=len(points),
                scope='all-flow endpoint replay, paired-source digests, load and cross-language source-release replay',
                source_clock_tolerance_T=2e-5,analysis_sha256=digest(__file__),gate_replay_sha256=digest(Path(__file__).with_name('quantized_gate.py')),
                manifest_sha256=digest(source/'manifest.json'))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('sweep');p.add_argument('--config',required=True);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=4)
    p=sub.add_parser('audit');p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    a=parser.parse_args();print(sweep(a.config,a.out,a.workers) if a.command=='sweep' else audit(a.input,a.out),flush=True)
