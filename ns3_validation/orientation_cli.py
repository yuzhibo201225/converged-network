"""Elementary half-dwell orientation intervention using the frozen V10 engine."""
import argparse
import csv
import itertools
import json
import math
import os
import random
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .renewal_cli import ROOT, audit as raw_audit, cases, digest, dump
from .order_cli import trace_blocks, trace_signature

MODES = ('lowfirst', 'highfirst', 'coinflip')


def trace_rows(spec, run, mode):
    if mode not in MODES:
        raise ValueError('unknown orientation')
    rng = random.Random(f"orientation-v12:{spec['trace_seed_base'] + run - 1}")
    rows = []
    now = 1_000_000_000
    for block in trace_blocks(spec, run):
        for dwell in block:
            high_first = mode == 'highfirst' or (mode == 'coinflip' and bool(rng.getrandbits(1)))
            rates = (1.3,.7) if high_first else (.7,1.3)
            for rate in rates:
                rows.append((now / 1e9, rate)); now += dwell
    return rows


def sweep(config, out, workers=4):
    config = Path(config); out = Path(out).resolve()
    if out.exists():
        raise FileExistsError(out)
    spec = json.loads(config.read_text())
    if len(set(spec['modes'])) != len(spec['modes']) or not set(spec['modes']) <= set(MODES):
        raise ValueError('invalid modes')
    exe = ROOT / 'ns3_validation/_build_mingw/bin/renewal-validation.exe'
    paths = [ROOT / 'ns3_validation' / name for name in
             ('orientation_cli.py', 'order_cli.py', 'renewal_cli.py', 'renewal_gate.py', 'renewal-validation.cc', 'burst-tail-validation.cc')]
    paths.append(ROOT / 'third_party/msys_extract/ns-3.47/src/core/model/time.cc')
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    exe_hash = digest(exe)
    env = dict(os.environ)
    env['PATH'] = str(ROOT / 'third_party/msys_extract/ns-3.47/build-mingw/lib') + ';C:/msys64/mingw64/bin;' + env['PATH']
    grid = list(cases(spec)); out.mkdir(parents=True)
    parent = dict(status='RUNNING', spec=spec, config_sha256=digest(config), source_sha256=hashes,
                  executable_sha256=exe_hash, completed_runs=0, planned_runs=len(grid)*len(spec['modes']))
    dump(out / 'manifest.json', parent)
    for mode in spec['modes']:
        folder = out / mode; folder.mkdir(); (folder / 'traces').mkdir()
        manifest = dict(status='RUNNING', spec=spec, planned_runs=len(grid), completed_runs=0,
                        ordering=mode, config_sha256=digest(config), source_sha256=hashes,
                        executable_sha256=exe_hash, receipts={}, trace_sha256={}, dwell_signatures={})
        for run in spec['runs']:
            path = folder / 'traces' / f'{run}.csv'
            with path.open('w', newline='') as handle:
                csv.writer(handle).writerows(trace_rows(spec, run, mode))
            manifest['trace_sha256'][str(run)] = digest(path)
            manifest['dwell_signatures'][str(run)] = trace_signature(spec, run)
        dump(folder / 'manifest.json', manifest)

        def one(i, case):
            args = [str(exe)] + [f'--{k}={v}' for k, v in case.items()]
            args += [f'--traceCsv={folder}/traces/{case["run"]}.csv',
                     f'--summaryCsv={folder}/{i}-summary.csv', f'--packetCsv={folder}/{i}-packets.csv']
            process = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            (folder / f'{i}-log.txt').write_text(process.stdout + process.stderr, encoding='utf-8')
            if process.returncode:
                raise RuntimeError(f'{mode} run{i} failed {process.returncode}: {process.stderr[-1000:]}')
            return i, {name: digest(folder / f'{i}-{name}.csv') for name in ('summary', 'packets')}
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(one, i, c) for i, c in enumerate(grid)]
                for future in as_completed(futures):
                    i, receipt = future.result(); manifest['receipts'][str(i)] = receipt
                    manifest['completed_runs'] += 1; parent['completed_runs'] += 1
                    dump(folder / 'manifest.json', manifest); dump(out / 'manifest.json', parent)
                    print(f"order {mode} {manifest['completed_runs']}/{len(grid)} total {parent['completed_runs']}", flush=True)
            if hashes != {str(p.relative_to(ROOT)): digest(p) for p in paths} or digest(exe) != exe_hash or digest(config) != parent['config_sha256']:
                raise RuntimeError('frozen code/config changed')
            manifest['status'] = 'COMPLETE'; dump(folder / 'manifest.json', manifest)
        except BaseException as error:
            manifest['status'] = parent['status'] = 'FAILED'
            manifest['error'] = parent['error'] = str(error)
            dump(folder / 'manifest.json', manifest); dump(out / 'manifest.json', parent)
            raise
    parent['status'] = 'COMPLETE'; dump(out / 'manifest.json', parent)
    return parent['completed_runs']


def analyze(source, out):
    source = Path(source).resolve(); out = Path(out).resolve()
    if out.exists(): raise FileExistsError(out)
    parent = json.loads((source / 'manifest.json').read_text()); spec = parent['spec']
    if parent['status'] != 'COMPLETE': raise ValueError('incomplete parent sweep')
    out.mkdir(parents=True)
    rows = []; audits = {}
    for mode in spec['modes']:
        audits[mode] = raw_audit(source / mode, out / mode)
        manifest = json.loads((source / mode / 'manifest.json').read_text())
        for run in spec['runs']:
            path = source / mode / 'traces' / f'{run}.csv'
            with path.open() as handle: observed = [(float(t), float(v)) for t, v in csv.reader(handle)]
            if observed != trace_rows(spec, run, mode) or manifest['dwell_signatures'][str(run)] != trace_signature(spec, run):
                raise ValueError('trace generation/dwell multiset mismatch')
        with (out / mode / 'runs.csv').open() as handle:
            rows.extend(dict(r, ordering=mode) for r in csv.DictReader(handle))
    fields = ('rho','R','tauB','shape','queue','bias','lag','capacity','seed','run')
    pairs = {}
    for r in rows: pairs.setdefault(tuple(r[k] for k in fields), {})[r['ordering']] = r
    contrasts = []
    for key, group in pairs.items():
        if set(group) != set(spec['modes']): raise ValueError('missing matched ordering')
        for field in ('arrival_digest','generated_rho','bulk_phase_fraction','lattice_fraction'):
            if len({r[field] for r in group.values()}) != 1: raise ValueError('source mismatch ' + field)
        for mode in spec['modes']:
            if mode == 'lowfirst': continue
            base = group['lowfirst']; other = group[mode]
            c = dict(zip(fields, key), ordering=mode,
                     control_p99_delta_T=float(other['control_p99_T'])-float(base['control_p99_T']),
                     bulk_p99_delta_T=float(other['bulk_p99_T'])-float(base['bulk_p99_T']),
                     lowfirst_pass=base['joint_pass'], intervention_pass=other['joint_pass'])
            contrasts.append(c)
    for name, records in (('runs', rows), ('contrasts', contrasts)):
        with (out / f'{name}.csv').open('w', newline='') as handle:
            w = csv.DictWriter(handle, fieldnames=list(records[0])); w.writeheader(); w.writerows(records)
    groups = {}
    for r in rows:
        key = (r['ordering'], r['shape'], r['queue'], r['bias'])
        groups.setdefault(key, []).append(r)
    points = []
    for key, records in groups.items():
        p = dict(zip(('ordering','shape','queue','bias'),key), n=len(records),
                 successes=sum(r['joint_pass']=='True' for r in records))
        for field in ('control_p99_T','control_miss_ratio','bulk_p99_T','bulk_delivery_ratio','admitted_rho'):
            values = [float(r[field]) for r in records]
            p[field+'_median'] = statistics.median(values); p[field+'_min'] = min(values); p[field+'_max'] = max(values)
        points.append(p)
    result = dict(status='PASS', runs=len(rows), pairs=len(pairs),
                  raw_all_flow_packets=sum(a['raw_all_flow_packets'] for a in audits.values()),
                  scope='exploratory matched elementary-half orientation; merged dwell lengths are NOT fixed; no reliability certification',
                  points=points, code_sha256=digest(__file__), manifest_sha256=digest(source/'manifest.json'),
                  contrasts_sha256=digest(out/'contrasts.csv'), runs_sha256=digest(out/'runs.csv'))
    dump(out/'audit.json', result); return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('sweep'); p.add_argument('--config', required=True); p.add_argument('--out', required=True); p.add_argument('--workers', type=int, default=4)
    p = sub.add_parser('audit'); p.add_argument('--input', required=True); p.add_argument('--out', required=True)
    a = parser.parse_args()
    print(sweep(a.config,a.out,a.workers) if a.command=='sweep' else analyze(a.input,a.out), flush=True)


