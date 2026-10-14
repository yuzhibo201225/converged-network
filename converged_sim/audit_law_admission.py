"""Recompute forecast admission from checked draw endpoints, then freeze."""
import argparse
import csv
import json
from pathlib import Path
from .law_admission import validate
from .scenario_predictor import model_hashes
from .reliability_boundary import clopper_pearson_lower
from ns3_validation.renewal_cli import digest,dump


def audit(source,out):
    source=Path(source);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text());s=m['spec'];validate(s)
    if m['status']!='COMPLETE' or m['completed']!=m['planned']:raise ValueError('completed forecast required')
    required=set(model_hashes())|{'converged_sim/law_admission.py','converged_sim/traffic_contract.py',
                                'converged_sim/reliability_boundary.py','ns3_validation/orientation_cli.py','ns3_validation/order_cli.py'}
    if set(m['source_sha256'])!=required:raise ValueError('complete model/generator hash set required')
    if any(digest(Path(__file__).parents[1]/p)!=v for p,v in m['source_sha256'].items()):raise ValueError('forecast implementation changed')
    if any(digest(source/p)!=v for p,v in m['outputs_sha256'].items()):raise ValueError('forecast export changed')
    with (source/'draws.csv').open() as h:rows=list(csv.DictReader(h))
    with (source/'decisions.csv').open() as h:points=list(csv.DictReader(h))
    expected={(float(rho),float(ts),d) for rho in s['loads'] for ts in s['tauS_values'] for d in range(1,s['draws']+1)}
    observed={(float(r['rho']),float(r['tauS']),int(r['draw'])) for r in rows}
    if observed!=expected or len(rows)!=len(expected):raise ValueError('draw IDs/coverage')
    if len(points)!=len(s['loads'])*len(s['tauS_values']):raise ValueError('cell coverage')
    for r in rows:
        path=source/'traces'/f"{int(float(r['tauS']))}-{r['draw']}.csv"
        if digest(path)!=r['trace_sha256']:raise ValueError('forecast trace changed')
        passed=float(r['control_p99_T'])<1 and float(r['control_miss_ratio'])<.01
        if passed!=(r['control_pass']=='True'):raise ValueError('forecast control decision')
    for p in points:
        cohort=[r for r in rows if float(r['rho'])==float(p['rho']) and float(r['tauS'])==float(p['tauS'])]
        success=sum(r['control_pass']=='True' and float(r['bulk_delivery'])==1 for r in cohort)
        lower=clopper_pearson_lower(success,s['draws'],s['alpha']/len(points))
        if success!=int(p['successes']) or abs(lower-float(p['lower']))>1e-14 or (lower>=s['q'])!=(p['qualified']=='True'):
            raise ValueError('forecast probability decision')
    out.mkdir(parents=True)
    result=dict(status='PASS',scope='SHA-checked draws/trace coverage and admission recomputation; not independent proof/packet endpoint re-run',
                draws=len(rows),cells=len(points),source_manifest_sha256=digest(source/'manifest.json'),
                decisions_sha256=digest(source/'decisions.csv'),code_sha256=digest(__file__))
    dump(out/'audit.json',result);return result


def freeze(source,check,configs,out):
    source=Path(source);check=Path(check);out=Path(out)
    if out.exists():raise FileExistsError(out)
    m=json.loads((source/'manifest.json').read_text());a=json.loads((check/'audit.json').read_text());s=m['spec']
    if a['status']!='PASS' or digest(source/'manifest.json')!=a['source_manifest_sha256'] or digest(source/'decisions.csv')!=a['decisions_sha256']:
        raise ValueError('checked forecast required')
    profiles=set()
    for path in map(Path,configs):
        n=json.loads(path.read_text());profiles.add(n['tauS'])
        if n['loads']!=s['loads'] or n['warm']!=s['warm'] or n['measured']!=s['measured'] or n['arms']!=[dict(R=s['R'],tauB=s['tauB'])]:
            raise ValueError('validation contracts differ')
        if n['seed']==s['forecast_phase_seed'] or n['trace_seed_base']<=s['forecast_trace_seed_base']+s['draws'] or n['runs']!=list(range(1,71)):
            raise ValueError('forecast/validation draws not separated')
        if n['settings']!=[dict(shape='feedback',queue='fifo',bias=s['bias'],lag=s['lag'],capacity=s['capacity']),
                           dict(shape='none',queue='priority',bias=0,lag=0,capacity=s['capacity'])]:raise ValueError('validation policies differ')
        if n['modes']!=['coinflip']:raise ValueError('validation service law differs')
    if profiles!=set(s['tauS_values']):raise ValueError('complete validation profiles required')
    result=dict(status='FROZEN',forecast_manifest_sha256=digest(source/'manifest.json'),forecast_audit_sha256=digest(check/'audit.json'),
                decisions_sha256=digest(source/'decisions.csv'),model_sha256=m['source_sha256'],
                allowed_native_config_sha256=[digest(Path(p)) for p in configs],
                native_executable_sha256=digest(Path(__file__).parents[1]/'ns3_validation/_build_mingw/bin/renewal-validation.exe'),
                validation_family_size=8,alpha=s['alpha'],q=s['q'],
                information='before native validation; known synthetic law, no actual future realization')
    dump(out,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    x=sub.add_parser('audit');x.add_argument('--input',required=True);x.add_argument('--out',required=True)
    x=sub.add_parser('freeze');x.add_argument('--input',required=True);x.add_argument('--audit',required=True);x.add_argument('--configs',nargs='+',required=True);x.add_argument('--out',required=True)
    a=p.parse_args();print(audit(a.input,a.out) if a.command=='audit' else freeze(a.input,a.audit,a.configs,a.out))
