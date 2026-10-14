"""Audit discovery raw rows and draw a dependency-free scientific SVG."""
import argparse
import csv
import gzip
import hashlib
import itertools
import json
import statistics
from collections import defaultdict
from pathlib import Path


def analyze(source, output):
    source, output = Path(source), Path(output)
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest["status"] != "COMPLETE":
        raise ValueError("sweep is not complete")
    deadline = manifest["spec"]["base_config"].get("deadline_periods", 1) * manifest["spec"]["base_config"].get("control_period", 1)
    if output.exists():
        raise FileExistsError(output)
    with (source / "runs.csv").open() as handle:
        runs = list(csv.DictReader(handle))
    if len(runs) != manifest["planned_runs"]:
        raise ValueError("incomplete run grid")
    dimensions = ("loads", "pmrs", "tau_bs", "tau_ss", "policies", "seeds")
    expected = set(itertools.product(*(manifest["spec"][key] for key in dimensions)))
    actual = [tuple(float(row[key]) for key in ("rho", "pmr", "tau_b", "tau_s"))
              + (row["policy"], int(row["seed"])) for row in runs]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("duplicate or missing configuration in run grid")
    for name, expected in manifest["outputs_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"changed source {name}")
    # Raw rows are written in run order, so retain only one cohort at a time.
    def check(index, cohort):
        row = runs[index]
        if len(cohort) != int(row["control_generated"]):
            raise ValueError(f"wrong raw count, run {index}")
        if len({packet["packet_id"] for packet in cohort}) != len(cohort):
            raise ValueError(f"duplicate raw packet IDs, run {index}")
        for packet in cohort:
            if packet["class"] != "control":
                raise ValueError(f"non-control raw record, run {index}")
            if packet["status"] not in ("delivered", "dropped", "unfinished"):
                raise ValueError(f"unknown packet status, run {index}")
            if packet["status"] == "delivered":
                latency = float(packet["completion"]) - float(packet["arrival"])
                if latency < -1e-10 or abs(latency - float(packet["latency"])) > 1e-10:
                    raise ValueError(f"wrong raw timestamp/latency, run {index}")
            expected_miss = packet["status"] != "delivered" or float(packet["latency"]) >= deadline
            if (packet["deadline_miss"] == "True") != expected_miss:
                raise ValueError(f"wrong raw miss flag, run {index}")
        if sum(packet["status"] == "dropped" for packet in cohort) != int(row["control_dropped"]):
            raise ValueError(f"wrong drop count, run {index}")
        misses = sum(packet["deadline_miss"] == "True" for packet in cohort)
        if abs(misses / len(cohort) - float(row["miss_ratio"])) > 1e-12:
            raise ValueError(f"wrong miss ratio, run {index}")
        values = sorted(float(packet["latency"]) for packet in cohort if packet["status"] == "delivered")
        if values:
            position = (len(values) - 1) * .99
            lower = int(position)
            p99 = values[lower] * (1 - position + lower) + values[min(lower+1, len(values)-1)] * (position-lower)
            if abs(p99 - float(row["p99"])) > 1e-10:
                raise ValueError(f"wrong P99, run {index}")
        elif row["p99"]:
            raise ValueError("P99 without deliveries")
    current, cohort, raw_count = 0, [], 0
    with gzip.open(source / "control_packets.csv.gz", "rt") as handle:
        for packet in csv.DictReader(handle):
            index = int(packet["run_id"])
            if index != current:
                if index != current + 1:
                    raise ValueError("non-contiguous raw run order")
                check(current, cohort)
                current, cohort = index, []
            cohort.append(packet)
            raw_count += 1
    check(current, cohort)
    if current != len(runs)-1:
        raise ValueError("missing final raw cohorts")
    pairing = defaultdict(list)
    grouped = defaultdict(list)
    for row in runs:
        pairing[(row["rho"], row["tau_s"], row["seed"])].append(row)
        grouped[tuple(row[key] for key in ("rho", "pmr", "tau_b", "tau_s", "policy"))].append(row)
    for key, rows in pairing.items():
        for field in ("service_trace_digest", "offered_bulk_work_measured", "offered_load_measured_actual"):
            if len({row[field] for row in rows}) != 1:
                raise ValueError(f"pairing failure {key}: {field}")
    points = []
    for key, rows in grouped.items():
        values = [float(row["p99"]) for row in rows if row["p99"]]
        successes = sum(bool(row["p99"]) and float(row["p99"]) < deadline and float(row["miss_ratio"]) < .01 for row in rows)
        points.append(dict(zip(("rho", "pmr", "tau_b", "tau_s", "policy"), key),
            n=len(rows), p99_median=statistics.median(values) if values else None,
            p99_min=min(values) if values else None, p99_max=max(values) if values else None,
            miss_median=statistics.median(float(row["miss_ratio"]) for row in rows),
            pass_fraction=successes/len(rows), bulk_goodput_median=statistics.median(float(row["bulk_goodput"]) for row in rows)))
    output.mkdir(parents=True)
    with (output / "points.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="900" viewBox="0 0 1080 900">',
           '<rect width="1080" height="900" fill="white"/>',
           '<text x="540" y="25" text-anchor="middle" font-family="Arial" font-size="18">Timescale discovery: control P99 / deadline (median and seed range)</text>']
    colors = {0.5: "#0072B2", 2.0: "#D55E00", 8.0: "#009E73"}
    policies = manifest["spec"]["policies"]
    for ri, tau_s in enumerate(manifest["spec"]["tau_ss"]):
        for ci, policy in enumerate(policies):
            x0, y0, w, h = 60 + ci*350, 85 + ri*250, 280, 180
            subset = [p for p in points if float(p["tau_s"]) == tau_s and p["policy"] == policy]
            cap = max(1.2, max(p["p99_max"] / deadline for p in subset if p["p99_max"] is not None)*1.05)
            def xy(p, field="p99_median"):
                return x0+(float(p["rho"])-.4)/.4*w, y0+h-p[field]/deadline/cap*h
            svg.append(f'<text x="{x0}" y="{y0-12}" font-family="Arial" font-size="13">{policy}; service dwell={tau_s}T</text>')
            svg.append(f'<path d="M{x0},{y0} V{y0+h} H{x0+w}" fill="none" stroke="black"/>')
            dy = y0+h-h/cap
            svg.append(f'<path d="M{x0},{dy} H{x0+w}" stroke="#777" stroke-dasharray="5 4"/>')
            svg.append(f'<text x="{x0-8}" y="{dy+4}" text-anchor="end" font-family="Arial" font-size="11">1</text>')
            for load in (.4, .6, .8):
                tick = x0+(load-.4)/.4*w
                svg.append(f'<path d="M{tick},{y0+h} v4" stroke="black"/><text x="{tick}" y="{y0+h+16}" text-anchor="middle" font-family="Arial" font-size="11">{load:.1f}</text>')
            for pmr, tau_b, color in [(1, .5, "#333333")] + [(3, tb, col) for tb,col in colors.items()]:
                curve = sorted([p for p in subset if float(p["pmr"]) == pmr and float(p["tau_b"]) == tau_b], key=lambda p: float(p["rho"]))
                coords = " ".join(f"{xy(p)[0]},{xy(p)[1]}" for p in curve if p["p99_median"] is not None)
                svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
                for p in curve:
                    if p["p99_median"] is None: continue
                    x,y=xy(p); _,lo=xy(p,"p99_min"); _,hi=xy(p,"p99_max")
                    svg.append(f'<path d="M{x},{lo} V{hi}" stroke="{color}" opacity=".5"/><circle cx="{x}" cy="{y}" r="3" fill="{color}"/>')
            svg.append(f'<text x="{x0+w/2}" y="{y0+h+32}" text-anchor="middle" font-family="Arial" font-size="12">Offered load / capacity (0.4, 0.6, 0.8)</text>')
            svg.append(f'<text x="{x0-8}" y="{y0+5}" text-anchor="end" font-family="Arial" font-size="11">{cap:.1f}</text>')
            svg.append(f'<text x="{x0-8}" y="{y0+h}" text-anchor="end" font-family="Arial" font-size="11">0</text>')
    svg.append('<text x="60" y="865" font-family="Arial" font-size="13">Black: PMR 1; blue/orange/green: PMR 3 with bulk cycle 0.5/2/8T. Dashed: deadline.</text>')
    svg.append('<text x="60" y="885" font-family="Arial" font-size="12">Five paired phase seeds; panel y-scales differ. Exploratory screen, not certified admission bounds.</text></svg>')
    (output / "p99_timescales.svg").write_text("\n".join(svg), encoding="utf-8")
    audit = {"status": "PASS", "runs": len(runs), "raw_control_rows": raw_count,
             "pairing_groups": len(pairing), "source_receipt": manifest["outputs_sha256"]}
    (output / "audit.json").write_text(json.dumps(audit, indent=2))
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.input, args.out)))
