"""Post-hoc decision accounting, NOT a new rule or native safety certificate."""
import argparse
import csv
import json
from pathlib import Path
from ns3_validation.renewal_cli import digest, dump


def decide(rho, epsilon, lag):
    """Known error envelope, not retrospectively estimated from observations.

    Qualification is only for TELEMETRY_BUDGET.md's continuous fluid scope;
    native PPP/access/propagation/packet-rate semantics are not certified.
    """
    if not (0<=rho<=1 and epsilon>=0 and lag>=0):raise ValueError('invalid declared inputs')
    return {
        'mean_load':rho<1,
        'fluid_sufficient_condition':rho<=.7/(.7+epsilon) and .1+.05+.6*rho*lag<.7,
    }


def run(inputs,out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    rows=[];sources={}
    for source in map(Path,inputs):
        a=json.loads((source/'audit.json').read_text())
        if a['status']!='PASS' or a['evaluation_scope']!='heldout' or digest(source/'runs.csv')!=a['outputs_sha256']['runs.csv']:
            raise ValueError('checked held-out endpoint table required')
        sources[str(source)]=digest(source/'audit.json')
        with (source/'runs.csv').open() as h:
            for r in csv.DictReader(h):
                # The experimental fixed bias is treated as an already-known
                # upper envelope. This is an assumption, not an error estimator.
                decisions=decide(float(r['rho']),float(r['bias']),float(r['lag']))
                for name,accept in decisions.items():
                    observed=r['observed_joint_pass']=='True'
                    rows.append(dict(profile=str(source),ordering=r['ordering'],run_index=r['run_index'],
                                     bias=r['bias'],lag=r['lag'],rule=name,qualified=accept,observed_pass=observed,
                                     false_safe_call=accept and not observed,unnecessary_abstention=not accept and observed))
    counts={}
    for name in ('mean_load','fluid_sufficient_condition'):
        group=[r for r in rows if r['rule']==name]
        counts[name]={field:sum(r[field] for r in group) for field in ('qualified','observed_pass','false_safe_call','unnecessary_abstention')}
        counts[name]['runs']=len(group)
    out.mkdir(parents=True)
    with (out/'decisions.csv').open('w',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    result=dict(status='PASS',scope='POST-HOC known-input baseline accounting; fluid qualification not native certification',
                information='rho, known lag and assumed known additive-error upper envelope only; no future trace',
                counts=counts,sources_sha256=sources,code_sha256=digest(__file__),decisions_sha256=digest(out/'decisions.csv'))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',nargs='+',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.input,a.out))
