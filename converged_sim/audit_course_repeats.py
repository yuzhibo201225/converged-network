"""Stream raw V32 records and independently reconstruct measurement summaries.

This is a saved-data consistency check, not independent radio validation or a
second implementation of the queue. Never overwrite an earlier audit.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import statistics

from .audit_cellreplay_mixed import read_rows
from .coarse_observation import sha


class JsonListHash:
    """Same canonical list encoding as coarse_observation.digest, streaming."""
    def __init__(self):
        self.h = hashlib.sha256(b'[')
        self.first = True

    def add(self, item):
        if not self.first:
            self.h.update(b',')
        self.first = False
        self.h.update(json.dumps(item, sort_keys=True, separators=(',', ':')).encode())

    def finish(self):
        h = self.h.copy()
        h.update(b']')
        return h.hexdigest()


def histogram_quantile(hist, q):
    count = sum(hist.values())
    if not count:
        return None
    rank = math.ceil(q * count)
    seen = 0
    for delay, n in sorted(hist.items()):
        seen += n
        if seen >= rank:
            return delay
    raise AssertionError('quantile rank')


def independent_metrics(rows, warm, deadlines):
    """Do not call the simulation's summarize() function."""
    counts = Counter()
    statuses = Counter()
    hist = defaultdict(Counter)
    misses = Counter()
    for r in rows:
        if r['arrival_ms'] < warm:
            continue
        f = r['flow']
        counts[f] += 1
        statuses[f, r['status']] += 1
        if r['status'] == 'completed':
            hist[f][r['delay_ms']] += 1
        for d in deadlines:
            if r['status'] != 'completed' or r['delay_ms'] >= d:
                misses[f, d] += 1
    metrics = {}
    for f, label in ((1, 'control'), (2, 'sensor'), (3, 'bulk')):
        n = counts[f]
        metrics[label + '_count'] = n
        metrics[label + '_p99_ms'] = histogram_quantile(hist[f], .99)
        metrics[label + '_drops'] = statuses[f, 'dropped']
        metrics[label + '_unfinished'] = statuses[f, 'unfinished']
        metrics[label + '_delivery'] = statuses[f, 'completed'] / n if n else None
        for d in deadlines:
            metrics[f'{label}_miss_{d}ms'] = misses[f, d] / n if n else None
    for d in deadlines:
        p99 = metrics['control_p99_ms']
        metrics[f'control_pass_{d}ms'] = (
            p99 is not None and p99 < d and metrics[f'control_miss_{d}ms'] < .01)
    return metrics, hist


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run(input_path, out):
    p = Path(input_path)
    out = Path(out)
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    # Retain a STARTED receipt even if a later check fails.
    (out / 'progress.json').write_text(json.dumps({'status': 'STARTED'}))
    manifest = json.loads((p / 'manifest.json').read_text())
    freeze = json.loads((p / 'frozen.json').read_text())
    assert sha(p / 'frozen.json') == manifest['frozen_sha256']
    assert sha(p / 'runs.csv') == manifest['runs_sha256']
    root = Path(__file__).resolve().parents[1]
    for name, expected in freeze['model_sha256'].items():
        assert sha(root / name) == expected, name
    with (p / 'runs.csv').open(newline='') as h:
        summaries = list(csv.DictReader(h))
    assert len(summaries) == 50 and len(manifest['plans']) == 15
    receipts = {r['file']: r for r in manifest['receipts']}
    cfg = freeze['config']
    volumes = defaultdict(list)
    plan_rows = 0
    for plan in manifest['plans']:
        pp, np = p / plan['planned_file'], p / plan['native_file']
        assert sha(pp) == plan['planned_sha256']
        assert sha(np) == plan['native_sha256']
        source = JsonListHash()
        cycle_counts = Counter()
        flow_bytes = Counter()
        window_bytes = Counter()
        count = 0
        with np.open(newline='') as h:
            for row, native in zip_longest(read_rows(pp), csv.DictReader(h)):
                assert row is not None and native is not None
                assert row['packet_id'] == count == int(native['packet_id'])
                for field, value in row.items():
                    if field in native:
                        assert native[field] == str(value), (plan['key'], count, field)
                event = (row['arrival_ms'], row['flow'], row['flow_id'], row['content_bytes'])
                source.add(event)
                flow_bytes[row['flow']] += row['content_bytes']
                if row['arrival_ms'] >= cfg['warm_ms']:
                    window_bytes[row['flow']] += row['content_bytes']
                if row['flow'] == 3:
                    cycle_counts[row['arrival_ms'] // cfg['cycle_ms']] += 1
                assert 0 <= row['arrival_ms'] < cfg['end_ms']
                count += 1
        assert count == plan['rows']
        assert source.finish() == plan['source_sha256']
        assert [cycle_counts[i] for i in range(len(plan['cycles']))] == plan['cycles']
        volumes[plan['group']].append((tuple(sorted(flow_bytes.items())), plan['service_sha256']))
        plan_rows += count
        plan['full_bytes_by_flow'] = dict(flow_bytes)
        plan['measured_window_bytes_by_flow'] = dict(window_bytes)
    for group, paired in volumes.items():
        assert len(set(paired)) == 1, (group, 'full-interval mean/mix pairing')
    plans = {r['planned_file']: r for r in manifest['plans']}
    total = 0
    measured_controls = 0
    ecdf_rows = []
    groups = defaultdict(list)
    for s in summaries:
        receipt = receipts[s['packet_file']]
        path = p / s['packet_file']
        assert sha(path) == receipt['sha256']
        plan = plans[s['planned_file']]
        for key in ('source_sha256', 'service_sha256', 'planned_sha256'):
            assert s[key] == plan[key]
        drops = 0
        row_count = 0
        evictions = 0

        def checked_rows():
            nonlocal drops, row_count, evictions
            for row, planned in zip_longest(read_rows(path), read_rows(p / s['planned_file'])):
                assert row is not None and planned is not None
                assert row['packet_id'] == row_count
                for key, value in planned.items():
                    assert row[key] == value, (path.name, row_count, key)
                assert row['release_ms'] >= row['arrival_ms']
                assert row['planned_delay_ms'] == row['release_ms'] - row['arrival_ms']
                assert row['status'] in ('completed', 'dropped', 'unfinished')
                if row['status'] == 'completed':
                    assert row['release_ms'] <= row['finish_ms'] <= cfg['end_ms']
                    assert row['delay_ms'] == row['finish_ms'] - row['arrival_ms']
                    if row['actual_bypass']:
                        assert row['finish_ms'] == row['release_ms']
                else:
                    assert row['finish_ms'] == row['delay_ms'] == ''
                    assert not row['actual_bypass']
                drops += row['status'] == 'dropped'
                evictions += row.get('evicted_by', '') != ''
                row_count += 1
                yield row

        metrics, hist = independent_metrics(checked_rows(), cfg['warm_ms'], cfg['deadlines_ms'])
        assert row_count == receipt['rows'] == plan['rows']
        assert metrics['control_count'] == 10000
        for key, value in metrics.items():
            assert s[key] == (str(value) if value is not None else ''), (path.name, key)
        assert int(s['evictions']) == evictions
        assert int(s['final_counter']) - int(s['final_resident']) == (
            drops if s['accounting'] == 'original' else 0)
        total += row_count
        measured_controls += metrics['control_count']
        groups[s['group'], s['pmr'], s['policy'], s['accounting']].append(s)
        cumulative = 0
        denominator = sum(hist[1].values())
        for delay, n in sorted(hist[1].items()):
            cumulative += n
            ecdf_rows.append(dict(group=s['group'], pmr=s['pmr'], policy=s['policy'],
                                  accounting=s['accounting'], seed=s['seed'], delay_ms=delay,
                                  delivered_count=n, delivered_ecdf=cumulative / denominator,
                                  all_control_completed_by_time=cumulative / 10000))
        (out / 'progress.json').write_text(json.dumps(dict(status='AUDITING', checked_runs=len(sum(groups.values(), [])))))
        print('audited ' + path.name, flush=True)
    table = []
    fields = ('control_p99_ms', 'control_miss_20ms', 'control_miss_40ms',
              'control_drops', 'control_unfinished', 'bulk_delivery', 'evictions')
    for key, repeats in sorted(groups.items()):
        assert len(repeats) == 5 and {int(r['seed']) for r in repeats} == set(range(5))
        row = dict(zip(('group', 'pmr', 'policy', 'accounting'), key))
        row['runs'] = 5
        for field in fields:
            v = [float(r[field]) for r in repeats]
            row[field + '_median'] = statistics.median(v)
            row[field + '_min'] = min(v)
            row[field + '_max'] = max(v)
        for d in cfg['deadlines_ms']:
            row[f'pass_{d}ms_runs'] = sum(r[f'control_pass_{d}ms'] == 'True' for r in repeats)
        table.append(row)
    paired = []
    for key, repeats in groups.items():
        if key[2:] != ('fifo', 'original'):
            continue
        other = {r['seed']: r for r in groups[key[:2] + ('fifo', 'accepted')]}
        for a in repeats:
            b = other[a['seed']]
            paired.append(dict(group=key[0], pmr=key[1], seed=a['seed'],
                               p99_fixed_minus_original_ms=float(b['control_p99_ms']) - float(a['control_p99_ms']),
                               miss20_fixed_minus_original=float(b['control_miss_20ms']) - float(a['control_miss_20ms']),
                               miss40_fixed_minus_original=float(b['control_miss_40ms']) - float(a['control_miss_40ms']),
                               control_drops_fixed_minus_original=int(b['control_drops']) - int(a['control_drops'])))
    write_csv(out / 'five_phase_summary.csv', table)
    write_csv(out / 'paired_accounting_differences.csv', paired)
    write_csv(out / 'control_ecdf.csv', ecdf_rows)
    (out / 'volume_pairing.json').write_text(json.dumps(manifest['plans'], indent=2))
    report = dict(status='PASS_SAVED_RAW_AND_NATIVE_RELEASE_RECONSTRUCTION',
                  runs=len(summaries), phase_repeats_per_configuration=5,
                  configurations=len(table), all_flow_records=total,
                  measured_control_records=measured_controls, native_release_records=plan_rows,
                  source_manifest_sha256=sha(p / 'manifest.json'),
                  audit_script_sha256=sha(Path(__file__)),
                  outputs={name: sha(out / name) for name in ('five_phase_summary.csv',
                      'paired_accounting_differences.csv', 'control_ecdf.csv', 'volume_pairing.json')},
                  scope='raw reconstruction and source-native release parity; no independent full-queue/radio validation',
                  pairing_scope='mean/mix exact over full208s interval, not asserted over postwarm200s interval',
                  uncertainty_scope='five phase ranges, not confidence intervals or independent radio sessions')
    (out / 'audit.json').write_text(json.dumps(report, indent=2))
    (out / 'progress.json').write_text(json.dumps({'status': 'COMPLETED', 'checked_runs': 50}))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    run(a.input, a.out)
