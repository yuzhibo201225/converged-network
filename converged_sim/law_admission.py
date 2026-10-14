"""Known-law Monte Carlo admission baseline; no realized future validation inputs.

This is not a newly invented algorithm or a deployment forecast. Confidence
qualifies run-SLO probability under the declared synthetic law/model only.
"""
import argparse
import csv
import itertools
import json
import time
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from .traffic_contract import emissions,fractions
from .scenario_predictor import predict,model_hashes
from .reliability_boundary import clopper_pearson_lower
from .scenario_admission_baselines import decide
from ns3_validation.orientation_cli import trace_rows
from ns3_validation.renewal_cli import digest,dump,p99

FIELDS={'loads','tauS_values','R','tauB','lag','bias','capacity','warm','measured','draws',
        'forecast_phase_seed','forecast_trace_seed_base','q','alpha'}


def validate(s):
    if set(s)!=FIELDS:raise ValueError('declared law/traffic only; no validation trace, outcome, or seed features')
    if s['draws']<1 or not(0<s['q']<1 and 0<s['alpha']<1):raise ValueError('invalid probability design')
    if len(set(s['loads']))!=len(s['loads']) or len(set(s['tauS_values']))!=len(s['tauS_values']):raise ValueError('duplicate cell')
    for ts in s['tauS_values']:
        for periods in (s['warm'],s['measured']):
            if periods%(2*ts) or periods%s['tauB']:raise ValueError('whole-cycle windows required')


def one(s,rho,ts,draw,folder):
    started=time.perf_counter();folder=Path(folder)
    law=dict(warm=s['warm'],measured=s['measured'],tauS=ts,trace_seed_base=s['forecast_trace_seed_base'])
    trace=folder/'traces'/f'{ts}-{draw}.csv'
    rows=trace_rows(law,draw,'coinflip')
    # Different loads intentionally share each forecast service/phase draw.
    # Parent writes each trace once, before workers run.
    with trace.open() as h:
        if [(float(t),float(v)) for t,v in csv.reader(h)]!=rows:raise ValueError('forecast generator mismatch')
    traffic=emissions(rho,s['R'],s['tauB'],s['warm'],s['measured'],s['forecast_phase_seed'],draw)
    parameters=dict(rho=rho,shape='feedback',queue='fifo',bias=s['bias'],lag=s['lag'],capacity=s['capacity'],
                    T=.02,tauS=ts,nominal_bps=6000000,traceCsv=str(trace),warm=s['warm'],measured=s['measured'],
                    begin_s=1+s['warm']*.02,end_s=1+(s['warm']+s['measured'])*.02,
                    stop_s=7+(s['warm']+s['measured'])*.02,service_phase_fraction=fractions(s['forecast_phase_seed'],draw)[2])
    prediction=predict(parameters,traffic);delay=prediction['delays']['packet']
    control=list(delay[1].values());bulk=list(delay[3].values())
    if len(control)!=s['measured']:raise ValueError('forecast full control cohort')
    nbulk=sum(e.flow==3 and parameters['begin_s']<=e.generated_s<parameters['end_s'] for e in traffic)
    miss=sum(v>=1 for v in control)/len(control);tail=p99(control)
    return dict(rho=rho,tauS=ts,draw=draw,control_p99_T=tail,control_miss_ratio=miss,
                control_pass=tail<1 and miss<.01,bulk_delivery=len(bulk)/nbulk,bulk_p99_T=p99(bulk),
                source_drops=prediction['source_drop_count'],input_records=len(traffic),trace_sha256=digest(trace),
                runtime_s=time.perf_counter()-started)


def run(config,out,workers=4):
    config=Path(config);out=Path(out).resolve();s=json.loads(config.read_text());validate(s)
    if out.exists():raise FileExistsError(out)
    hashes=model_hashes()
    for path in ('converged_sim/law_admission.py','converged_sim/traffic_contract.py','converged_sim/reliability_boundary.py',
                 'ns3_validation/orientation_cli.py','ns3_validation/order_cli.py'):
        hashes[path]=digest(Path(__file__).parents[1]/path)
    cells=list(itertools.product(s['loads'],s['tauS_values']))
    out.mkdir(parents=True);(out/'traces').mkdir()
    m=dict(status='RUNNING',spec=s,config_sha256=digest(config),source_sha256=hashes,
           planned=len(cells)*s['draws'],completed=0,information='known synthetic law, not realized validation futures')
    dump(out/'manifest.json',m)
    try:
        for ts,draw in itertools.product(s['tauS_values'],range(1,s['draws']+1)):
            law=dict(warm=s['warm'],measured=s['measured'],tauS=ts,trace_seed_base=s['forecast_trace_seed_base'])
            with (out/'traces'/f'{ts}-{draw}.csv').open('w',newline='') as h:csv.writer(h).writerows(trace_rows(law,draw,'coinflip'))
        rows=[]
        with (out/'draws.csv').open('w',newline='') as h,ProcessPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(one,s,rho,ts,draw,str(out)) for (rho,ts),draw in itertools.product(cells,range(1,s['draws']+1))]
            writer=None
            for future in as_completed(futures):
                r=future.result();rows.append(r)
                if writer is None:writer=csv.DictWriter(h,fieldnames=list(r));writer.writeheader()
                writer.writerow(r);h.flush();m['completed']+=1;dump(out/'manifest.json',m)
                if m['completed']%10==0:print(f"law draws {m['completed']}/{m['planned']}",flush=True)
        points=[]
        for rho,ts in cells:
            cohort=[r for r in rows if r['rho']==rho and r['tauS']==ts]
            if len(cohort)!=s['draws']:raise ValueError('complete forecast cohort')
            successes=sum(r['control_pass'] and r['bulk_delivery']==1 for r in cohort)
            lower=clopper_pearson_lower(successes,s['draws'],s['alpha']/len(cells))
            points.append(dict(rho=rho,tauS=ts,successes=successes,draws=s['draws'],lower=lower,
                               qualified=lower>=s['q'],min_bulk_delivery=min(r['bulk_delivery'] for r in cohort),
                               **decide(rho,s['bias'],s['lag'])))
        with (out/'decisions.csv').open('w',newline='') as h:
            w=csv.DictWriter(h,fieldnames=list(points[0]));w.writeheader();w.writerows(points)
        if digest(config)!=m['config_sha256'] or any(digest(Path(__file__).parents[1]/p)!=sha for p,sha in hashes.items()):raise ValueError('frozen input changed')
        m.update(status='COMPLETE',outputs_sha256={p:digest(out/p) for p in ('draws.csv','decisions.csv')})
        dump(out/'manifest.json',m);return m
    except BaseException as error:
        m.update(status='FAILED',error=str(error));dump(out/'manifest.json',m);raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();run(a.config,a.out,a.workers)
