"""Freeze identical-source scheduling follow-up before new policy outcomes."""
import argparse
import json
from pathlib import Path
from ns3_validation.renewal_cli import digest,dump


def freeze(configs,baselines,audits,out):
    out=Path(out)
    if out.exists():raise FileExistsError(out)
    if not(len(configs)==len(baselines)==len(audits)==2):raise ValueError('two complete paired profiles')
    profiles=[];root=Path(__file__).parents[1]
    for config,raw,checked in zip(map(Path,configs),map(Path,baselines),map(Path,audits)):
        s=json.loads(config.read_text());m=json.loads((raw/'manifest.json').read_text());a=json.loads((checked/'audit.json').read_text())
        if m['status']!='COMPLETE' or a['status']!='PASS' or digest(raw/'manifest.json')!=a['manifest_sha256']:
            raise ValueError('checked baseline required')
        original=m['spec']
        for k,v in original.items():
            if k not in ('purpose','settings') and s.get(k)!=v:raise ValueError('only scheduling intervention allowed')
        if s['settings']!=[dict(shape='feedback',queue='priority',bias=.06,lag=.5,capacity=16)]:raise ValueError('identical shaped priority required')
        if dict(shape='feedback',queue='fifo',bias=.06,lag=.5,capacity=16) not in original['settings']:raise ValueError('matching source baseline absent')
        if any(digest(root/p)!=v for p,v in m['source_sha256'].items()):raise ValueError('native source drift')
        profiles.append(dict(tauS=s['tauS'],new_config_sha256=digest(config),baseline_manifest_sha256=digest(raw/'manifest.json'),
                             baseline_audit_sha256=digest(checked/'audit.json'),source_sha256=m['source_sha256'],
                             executable_sha256=m['executable_sha256']))
    if {p['tauS'] for p in profiles}!={4,12}:raise ValueError('both service profiles required')
    result=dict(status='FROZEN',scope='post-V15 paired source-buffer/shaping-matched scheduling intervention; not new independent draws',
                profiles=profiles,code_sha256=digest(__file__))
    dump(out,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--configs',nargs='+',required=True);p.add_argument('--baselines',nargs='+',required=True)
    p.add_argument('--audits',nargs='+',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(freeze(a.configs,a.baselines,a.audits,a.out))
