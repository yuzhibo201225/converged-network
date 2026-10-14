"""Audited five-phase evidence plot and course result note; no inferred CIs."""
import argparse
import csv
import json
from pathlib import Path
from .coarse_observation import sha
from .scientific_figures import start, text, line, save


def run(input_path, raw_path, out):
    p, raw, out = Path(input_path), Path(raw_path), Path(out)
    if out.exists():
        raise FileExistsError(out)
    audit = json.loads((p / 'audit.json').read_text())
    assert audit['status'] == 'PASS_SAVED_RAW_AND_NATIVE_RELEASE_RECONSTRUCTION'
    assert audit['source_manifest_sha256'] == sha(raw / 'manifest.json')
    for name, expected in audit['outputs'].items():
        assert sha(p / name) == expected
    with (p / 'five_phase_summary.csv').open(newline='') as h:
        table = list(csv.DictReader(h))
    with (raw / 'runs.csv').open(newline='') as h:
        runs = list(csv.DictReader(h))
    manifest = json.loads((raw / 'manifest.json').read_text())
    assert sha(raw / 'runs.csv') == manifest['runs_sha256']
    variants = [('fifo', 'original', 'O', '#333333'),
                ('fifo', 'accepted', 'F', '#0072B2'),
                ('priority', 'accepted', 'P', '#D55E00'),
                ('pushout', 'accepted', 'X', '#009E73')]
    ordered = []
    for group, pmr in [('tmobile/weak-signal', '1'), ('tmobile/weak-signal', '3'),
                       ('verizon/stationary-good', '3')]:
        for policy, accounting, label, color in variants:
            found = [r for r in table if (r['group'], r['pmr'], r['policy'], r['accounting']) ==
                     (group, pmr, policy, accounting)]
            if not found:
                continue
            assert len(found) == 1
            ordered.append((found[0], label, color))
    assert len(ordered) == 10
    panels = [('control_p99_ms', 'Delivered control P99 (ms)', 0, 60, [0, 20, 40, 60], [20, 40]),
              ('control_miss_20ms', 'Control deadline misses at 20 ms (%)', 0, 100,
               [0, 25, 50, 75, 100], []),
              ('control_miss_40ms', 'Control deadline misses at 40 ms (%)', 0, 40,
               [0, 10, 20, 30, 40], [1])]
    svg = start(1500,570, 'Five paired bulk phases at offered load 0.60')
    for panel, (field, title, lo, hi, ticks, refs) in enumerate(panels):
        x0, y0, w, h = 60 + panel * 500, 88, 415, 305
        def xx(i):
            return x0 + (i + .5) * w / 10
        def yy(value):
            return y0 + h - (value - lo) * h / (hi - lo)
        def value(r, suffix=''):
            v = float(r[field + suffix])
            return v if field == 'control_p99_ms' else 100 * v
        text(svg, x0, y0 - 28, f'({chr(97 + panel)}) {title}', 14)
        for tick in ticks:
            line(svg, x0, yy(tick), x0 + w, yy(tick), '#ddd')
            text(svg, x0 - 6, yy(tick) + 4, str(tick), 12, 'end')
        line(svg, x0, y0, x0, y0 + h)
        line(svg, x0, y0 + h, x0 + w, y0 + h)
        for ref in refs:
            line(svg, x0, yy(ref), x0 + w, yy(ref), '#777', True)
        for i, (r, label, color) in enumerate(ordered):
            bottom, top = value(r, '_min'), value(r, '_max')
            assert lo <= bottom <= top <= hi, (field, bottom, top)
            line(svg, xx(i), yy(bottom), xx(i), yy(top), color)
            for v in (bottom, top):
                line(svg, xx(i)-5, yy(v), xx(i)+5, yy(v), color)
            matched = [a for a in runs if all(a[k] == r[k] for k in
                       ('group', 'pmr', 'policy', 'accounting'))]
            assert len(matched) == 5
            for j, a in enumerate(sorted(matched, key=lambda a: int(a['seed']))):
                svg.append(f'<circle cx="{xx(i)+(j-2)*2}" cy="{yy(value(a))}" r="2" fill="white" stroke="{color}"/>')
            med = yy(value(r, '_median'))
            line(svg, xx(i)-7, med, xx(i)+7, med, color)
            text(svg, xx(i), y0+h+17, label, 12, 'middle')
        for begin, end, label in [(0, 3, 'T-Mobile PMR 1'), (4, 7, 'T-Mobile PMR 3'),
                                  (8, 9, 'Verizon PMR 3')]:
            text(svg, (xx(begin)+xx(end))/2, y0+h+39, label, 11, 'middle')
    labels = ['O: original FIFO', 'F: accepted-only FIFO', 'P: accepted-only priority',
              'X: accepted-only priority + push-out']
    for i, ((_, _, _, color), label) in enumerate(zip(variants, labels)):
        x = 65 + i*355
        line(svg, x, 469, x+22, 469, color)
        text(svg, x+30, 474, label, 12)
    text(svg, 60, 508, 'Dots: five phase runs; bars: full range; horizontal ticks: median. Not confidence intervals or independent radio sessions.', 13)
    text(svg, 60, 533, 'All primary 20-ms cases fail. The 40-ms deadline is sensitivity only. Loss and unfinished controls count as misses.', 13)
    out.mkdir(parents=True)
    save(svg, out / 'five_phase_evidence.svg')
    lines = ['# Five-phase course evidence V32', '', '## Material Passport', '',
             'ARS-Codex saved-data validation, 2026-10-13. Status: ANALYZED with raw',
             'metric reconstruction and source-native release parity. This does not',
             'claim a fresh independent simulation rerun, external reviewer approval,',
             'complete course compliance, global novelty, or JCR Q2 readiness.', '',
             '## Verified population', '',
             f"{audit['runs']} runs / {audit['configurations']} configurations / 5 paired bulk phases each;",
             f"{audit['all_flow_records']:,} all-flow raw records; {audit['measured_control_records']:,} measured controls;",
             f"{audit['native_release_records']:,} source release records compared against the native fixture.", '',
             'Each run has 10,000 measured controls after 8s warmup, over a fixed 208s',
             'horizon. Same service prefix and critical arrivals are reused. Five phase',
             'ranges do not estimate population uncertainty or independent radio days.', '',
             'Mean offered bytes and traffic mix are exactly paired over the whole 208s',
             'interval, including each 300ms cycle. Post-warmup bulk volumes can differ',
             'because the 8s warmup cuts a cycle; exact window bytes are disclosed in',
             '`volume_pairing.json`, rather than asserted equal.', '',
             '## Results (median [min, max], five runs)', '',
             '| Prefix / PMR / variant | P99 ms | Miss20 % | Miss40 % | Bulk delivered % | Pass40 runs |',
             '|---|---:|---:|---:|---:|---:|']
    def fmt(r, field, scale=1):
        vals = [float(r[field + s])*scale for s in ('_median', '_min', '_max')]
        return f'{vals[0]:.4g} [{vals[1]:.4g}, {vals[2]:.4g}]'
    for r, label, _ in ordered:
        prefix = 'T-Mobile' if r['group'].startswith('tmobile') else 'Verizon'
        lines.append(f"| {prefix} / {r['pmr']} / {label} | {fmt(r, 'control_p99_ms')} | {fmt(r, 'control_miss_20ms', 100)} | {fmt(r, 'control_miss_40ms', 100)} | {fmt(r, 'bulk_delivery', 100)} | {r['pass_40ms_runs']}/5 |")
    assert sum(int(r['pass_20ms_runs']) for r in table) == 0
    lines += ['', '## Interpretation boundary', '',
              'The entire primary 20ms population fails. An accounting correction does',
              'not establish SLO restoration. The tested grid is only rho0.60; it does',
              'not identify the maximum admissible load or a shifted collapse boundary.',
              'Priority and push-out are established component baselines, not a newly',
              'invented scheduler. The independently source-tested absorbing-counter',
              'mechanism is a candidate reliability contribution, not global priority.', '',
              '## Statistical fallacy scan: 11/11 checked', '',
              '1. Simpson: prefix/PMR/variant strata retained; no pooled causal summary.',
              '2. Ecological: phase outcomes are not inferred as per-device reliability.',
              '3. Berkson: two deliberately selected prefixes; external generalization cautioned.',
              '4. Collider: no fitted adjustment model; delivered-only P99 is conditional.',
              '5. Base rate: misses use all 10,000 controls, not completed controls.',
              '6. Regression to mean: matched phases retained, not favorable before/after selection.',
              '7. Survivorship: drops/unfinished counted as misses; P99 explicitly delivered-only.',
              '8. Look elsewhere: all 50 frozen cases and all failed primary outcomes retained.',
              '9. Forking paths: V32 is a prospective followup to exploratory V27-V31,',
              '   not a retrospectively preregistered discovery; protocol is byte-frozen.',
              '10. Causality: intervention contrasts apply within the replay model only.',
              '11. Reverse causality: source-code invariant plus timed intervention,',
              '    not an observational directional inference about real radio.', '',
              'No hypothesis tests, p-values, population confidence intervals or numerical',
              'publication-readiness score are computed from these five phase runs.', '',
              '## Reproduce', '',
              '```powershell',
              'python -m converged_sim.course_repeats --out results/course_repeats_v32_fresh',
              'python -m converged_sim.audit_course_repeats --input results/course_repeats_v32 --out results/course_repeats_audit_v32_fresh',
              'python -m converged_sim.plot_course_repeats --input results/course_repeats_audit_v32 --raw results/course_repeats_v32 --out results/course_repeats_figures_v32_fresh',
              '```', '',
              'Run from the repository root. Fresh output directories are required.',
              'Source/native prerequisites remain the saved V20/V23b/V25/V31 artifacts.',
              'The raw data are local and are not uploaded by these commands.', '']
    (out / 'RESULTS_V32.md').write_text('\n'.join(lines), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps(dict(
        status='AUDITED_FIVE_PHASE_FIGURE_AND_REPORT', input_audit_sha256=sha(p/'audit.json'),
        script_sha256=sha(Path(__file__)), outputs={name: sha(out/name) for name in
         ('five_phase_evidence.svg', 'RESULTS_V32.md')}), indent=2))
    print('generated ' + str(out), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--raw', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    run(a.input, a.raw, a.out)
