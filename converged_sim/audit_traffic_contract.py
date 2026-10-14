"""Check generated contracts against preserved native arrivals, not outcomes."""
import argparse
import csv
import json
from pathlib import Path
from .traffic_contract import emissions,fractions
from ns3_validation.renewal_cli import digest,dump


def audit(sources,out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    rows=[]
    for folder in map(Path,sources):
        m=json.loads((folder/'manifest.json').read_text())
        if m['status']!='COMPLETE':raise ValueError('complete native input required')
        for i in (0,len(m['receipts'])-1):
            paths={name:folder/f'{i}-{name}.csv' for name in ('summary','packets')}
            if any(digest(path)!=m['receipts'][str(i)][name] for name,path in paths.items()):raise ValueError('native receipt changed')
            with paths['summary'].open() as h:r=list(csv.DictReader(h))[0]
            generated=emissions(float(r['rho']),float(r['R']),float(r['tauB']),int(r['warm']),int(r['measured']),int(r['seed']),int(r['run']))
            expected={(e.flow,e.packet_id):e.generated_s for e in generated}
            with paths['packets'].open() as h:
                observed={(int(p['flow']),int(p['id'])):float(p['generated_s']) for p in csv.DictReader(h)}
            if set(expected)!=set(observed):raise ValueError('native generated cohort/ID mismatch')
            error=max(abs(expected[k]-observed[k]) for k in expected)
            phase=fractions(int(r['seed']),int(r['run']))
            if error>1e-9 or any(abs(v-float(r[k]))>1e-15 for v,k in zip(phase,('bulk_phase_fraction','lattice_fraction','service_phase_fraction'))):
                raise ValueError('native generation/phase mismatch')
            rows.append(dict(folder=str(folder),case=i,packets=len(expected),max_generated_error_s=error,
                             packets_sha256=digest(paths['packets']),summary_sha256=digest(paths['summary'])))
    out.mkdir(parents=True)
    result=dict(status='PASS',scope='input-generation agreement on selected preserved native cases; no outcome fitting',
                checks=rows,code_sha256=digest(__file__),generator_sha256=digest(Path(__file__).with_name('traffic_contract.py')))
    dump(out/'audit.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',nargs='+',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(audit(a.input,a.out))
