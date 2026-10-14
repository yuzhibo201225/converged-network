"""Reproducible main P99 figure for the paired factorial FIFO experiment.

The scientific unit is a simulation seed: medians and interquartile ranges are
computed across run-level P99s, never by pooling packets across seeds. The SVG
uses a common capped display scale; accompanying CSV retains uncapped values.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from .analysis import percentile
from .factorial_analysis import REGIMES, _check_regimes, _load_regime


POINT_COLUMNS = (
    "regime", "rho", "pmr", "seeds", "p99_available", "p99_median_T",
    "p99_q25_T", "p99_q75_T", "miss_median", "qualifies",
)
COLORS = {1.0: "#0072B2", 1.5: "#E69F00", 2.0: "#009E73", 3.0: "#CC79A7"}
DASHES = {1.0: "", 1.5: "7,3", 2.0: "3,3", 3.0: "10,3,2,3"}


def summarize_points(
    rows: dict[str, list[dict[str, str]]], control_period: float,
    deadline: float, miss_limit: float = 0.01,
) -> list[dict[str, object]]:
    """Summarize complete paired cells without silently omitting missing P99s."""
    if not math.isfinite(control_period) or control_period <= 0:
        raise ValueError("control_period must be positive and finite")
    points: list[dict[str, object]] = []
    for regime in REGIMES:
        grouped: dict[tuple[float, float], list[dict[str, str]]] = defaultdict(list)
        for row in rows[regime]:
            grouped[(float(row["rho"]), float(row["pmr"]))].append(row)
        for (rho, pmr), runs in sorted(grouped.items()):
            p99s = [float(row["p99"]) / control_period for row in runs if row["p99"] != ""]
            misses = [float(row["miss_ratio"]) for row in runs]
            if any(not math.isfinite(value) or value < 0 for value in p99s + misses):
                raise ValueError("non-finite or negative P99/miss ratio")
            complete = len(p99s) == len(runs)
            p99_median = median(p99s) if complete else None
            points.append({
                "regime": regime, "rho": rho, "pmr": pmr,
                "seeds": len(runs), "p99_available": len(p99s),
                "p99_median_T": p99_median,
                "p99_q25_T": percentile(p99s, 0.25) if complete else None,
                "p99_q75_T": percentile(p99s, 0.75) if complete else None,
                "miss_median": median(misses),
                "qualifies": p99_median is not None and p99_median < deadline / control_period
                and median(misses) < miss_limit,
            })
    return points


def _fmt(value: object) -> str:
    return "" if value is None else f"{float(value):.10g}"


def render_svg(points: list[dict[str, object]], deadline_T: float, ymax: float = 2.0) -> str:
    """Make a fixed, manuscript-friendly three-facet SVG with an explicit cap."""
    if not math.isfinite(ymax) or ymax <= deadline_T or deadline_T <= 0:
        raise ValueError("ymax must exceed the positive normalized deadline")
    if not points:
        raise ValueError("no points to plot")
    loads = sorted({float(point["rho"]) for point in points})
    pmrs = sorted({float(point["pmr"]) for point in points})
    if len(loads) < 2 or not pmrs or not set(pmrs).issubset(COLORS):
        raise ValueError("figure requires at least two loads and supported PMR arms")
    if any(point["p99_median_T"] is None for point in points):
        raise ValueError("figure has an incomplete delivered-P99 cell")
    xlo, xhi = min(loads), max(loads)
    width, height = 1320, 530
    left, panel_w, gap, top, plot_h = 82, 368, 30, 110, 288
    right = left + 3 * panel_w + 2 * gap
    x = lambda rho, panel: left + panel * (panel_w + gap) + (rho - xlo) / (xhi - xlo) * panel_w
    y = lambda value: top + plot_h * (1 - min(max(value, 0.0), ymax) / ymax)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Control-flow P99 versus offered load across bulk burstiness and service variability</title>',
        '<desc id="desc">Three service-regime panels share a capped vertical scale. Four PMR lines show median run-level P99 normalized by the control period; translucent ribbons show seed interquartile ranges. Upward triangles mark medians above the display cap. Hollow diamonds mark cells that meet the P99 deadline but fail the separate one-percent deadline-miss criterion.</desc>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#20252c}.grid{stroke:#e2e6e9;stroke-width:1}.axis{stroke:#59636e;stroke-width:1}</style>',
        '<text x="82" y="32" font-size="19" font-weight="600">Control-flow tail latency under heterogeneous contention</text>',
        '<text x="82" y="53" font-size="12">Run-level P99 medians and seed IQR; all regimes use the same paired load, PMR, and seed grid</text>',
    ]
    for panel, regime in enumerate(REGIMES):
        x0 = left + panel * (panel_w + gap)
        panel_points = [point for point in points if point["regime"] == regime]
        clipped = sum(float(point["p99_median_T"]) > ymax for point in panel_points)
        title = {"constant": "Constant service", "moderate": "Moderate service variation", "strong": "Strong service variation"}[regime]
        parts.append(f'<text x="{x0}" y="79" font-size="15" font-weight="600">{title}</text>')
        parts.append(f'<text x="{x0}" y="97" font-size="11">{clipped} / {len(panel_points)} medians above {ymax:g}T display cap</text>')
        parts.append(f'<clipPath id="panel-{panel}"><rect x="{x0}" y="{top}" width="{panel_w}" height="{plot_h}"/></clipPath>')
        for tick in (0.0, 0.5, 1.0, 1.5, 2.0):
            if tick > ymax + 1e-12:
                continue
            yy = y(tick)
            parts.append(f'<line class="grid" x1="{x0}" y1="{yy:.2f}" x2="{x0+panel_w}" y2="{yy:.2f}"/>')
            if panel == 0:
                parts.append(f'<text x="{x0-10}" y="{yy+4:.2f}" text-anchor="end" font-size="11">{tick:g}</text>')
        for tick in (0.2, 0.4, 0.6, 0.8, 0.95):
            if not xlo - 1e-12 <= tick <= xhi + 1e-12:
                continue
            xx = x(tick, panel)
            parts.append(f'<line class="grid" x1="{xx:.2f}" y1="{top}" x2="{xx:.2f}" y2="{top+plot_h}"/>')
            parts.append(f'<text x="{xx:.2f}" y="{top+plot_h+19}" text-anchor="middle" font-size="11">{tick:g}</text>')
        parts.append(f'<rect x="{x0}" y="{top}" width="{panel_w}" height="{plot_h}" fill="none" class="axis"/>')
        for pmr in pmrs:
            arm = sorted((point for point in panel_points if float(point["pmr"]) == pmr),
                         key=lambda point: float(point["rho"]))
            color = COLORS[pmr]
            upper = [(x(float(point["rho"]), panel), y(float(point["p99_q75_T"]))) for point in arm]
            lower = [(x(float(point["rho"]), panel), y(float(point["p99_q25_T"]))) for point in reversed(arm)]
            polygon = " ".join(f"{xx:.2f},{yy:.2f}" for xx, yy in upper + lower)
            parts.append(f'<polygon points="{polygon}" fill="{color}" fill-opacity="0.12" clip-path="url(#panel-{panel})"/>')
        yy = y(deadline_T)
        parts.append(f'<line x1="{x0}" y1="{yy:.2f}" x2="{x0+panel_w}" y2="{yy:.2f}" stroke="#333333" stroke-width="1.3" stroke-dasharray="5,4"/>')
        for pmr in pmrs:
            arm = sorted((point for point in panel_points if float(point["pmr"]) == pmr),
                         key=lambda point: float(point["rho"]))
            color = COLORS[pmr]
            coords = " ".join(f'{x(float(point["rho"]),panel):.2f},{y(float(point["p99_median_T"])):.2f}' for point in arm)
            dash = f' stroke-dasharray="{DASHES[pmr]}"' if DASHES[pmr] else ""
            parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.1"{dash} clip-path="url(#panel-{panel})"/>')
            for point in arm:
                if float(point["p99_median_T"]) > ymax:
                    xx = x(float(point["rho"]), panel)
                    parts.append(f'<path d="M {xx-3:.2f},{top+10} L {xx:.2f},{top+3} L {xx+3:.2f},{top+10}" fill="none" stroke="{color}" stroke-width="1.4" clip-path="url(#panel-{panel})"/>')
                elif float(point["p99_median_T"]) < deadline_T and float(point["miss_median"]) >= 0.01:
                    xx, yy = x(float(point["rho"]), panel), y(float(point["p99_median_T"]))
                    diamond = f"{xx:.2f},{yy-5:.2f} {xx+5:.2f},{yy:.2f} {xx:.2f},{yy+5:.2f} {xx-5:.2f},{yy:.2f}"
                    parts.append(f'<polygon points="{diamond}" fill="white" stroke="{color}" stroke-width="1.8" clip-path="url(#panel-{panel})"/>')
    parts.extend([
        f'<text x="{(left+right)/2:.2f}" y="440" text-anchor="middle" font-size="13">Target offered load ρ (mean work / mean service capacity)</text>',
        '<text x="23" y="254" transform="rotate(-90 23 254)" text-anchor="middle" font-size="13">Control P99 / control period (T)</text>',
    ])
    for index, pmr in enumerate(pmrs):
        xx = left + index * 135
        dash = f' stroke-dasharray="{DASHES[pmr]}"' if DASHES[pmr] else ""
        parts.append(f'<line x1="{xx}" y1="468" x2="{xx+24}" y2="468" stroke="{COLORS[pmr]}" stroke-width="2.5"{dash}/>')
        parts.append(f'<text x="{xx+30}" y="472" font-size="11">PMR {pmr:g}</text>')
    parts.extend([
        '<line x1="635" y1="468" x2="659" y2="468" stroke="#333333" stroke-dasharray="5,4"/>',
        f'<text x="665" y="472" font-size="11">Deadline = {deadline_T:g}T</text>',
        '<rect x="830" y="461" width="22" height="12" fill="#0072B2" fill-opacity="0.12"/>',
        '<text x="858" y="472" font-size="11">Seed IQR (25th–75th percentile)</text>',
        '<text x="82" y="497" font-size="10">Hollow diamond: P99 &lt; deadline but median miss fraction ≥1%; qualification requires both criteria.</text>',
        '<text x="82" y="514" font-size="10">Display cap affects drawing only; untruncated estimates and qualification flags are in the companion points CSV.</text>',
        '</svg>',
    ])
    return "\n".join(parts) + "\n"


def generate(constant: Path, moderate: Path, strong: Path, out: Path, ymax: float = 2.0) -> dict[str, Any]:
    """Read validated merged views and create a figure plus source-point table."""
    paths = dict(zip(REGIMES, (constant, moderate, strong)))
    if len({path.resolve() for path in paths.values()}) != 3:
        raise ValueError("regime input directories must be distinct")
    manifests: dict[str, dict[str, Any]] = {}
    rows: dict[str, list[dict[str, str]]] = {}
    for regime, path in paths.items():
        manifests[regime], rows[regime] = _load_regime(path)
    pairing = _check_regimes(manifests, rows)
    control_period = float(manifests["constant"]["simulation"]["control_period"])
    deadline = float(manifests["constant"]["deadline"])
    points = summarize_points(rows, control_period, deadline)
    figure = render_svg(points, deadline / control_period, ymax)
    output = out.resolve()
    if output.suffix.lower() != ".svg":
        raise ValueError("--out must be an .svg filename")
    point_csv = output.with_name(output.stem + "_points.csv")
    audit_json = output.with_name(output.stem + "_audit.json")
    for target in (output, point_csv, audit_json):
        if target.exists():
            raise FileExistsError(f"will not overwrite existing artifact: {target}")
    seed_count = len(pairing["seeds"])
    audit: dict[str, Any] = {
        "status": "PASS", "source": "validated runs.csv summaries, not raw packet re-audit",
        "scope": f"synthetic finite-FIFO model; {seed_count}-seed paired display",
        "inputs": {regime: {
            "directory": str(path.resolve()),
            "runs_sha256": hashlib.sha256((path / "runs.csv").read_bytes()).hexdigest(),
            "config_sha256": hashlib.sha256((path / "config.json").read_bytes()).hexdigest(),
        } for regime, path in paths.items()},
        "pairing": pairing, "control_period": control_period, "deadline": deadline,
        "display_ymax_T": ymax, "point_count": len(points),
        "p99_missing_cells": sum(point["p99_median_T"] is None for point in points),
        "median_above_display_cap_by_regime": {
            regime: sum(point["regime"] == regime and float(point["p99_median_T"]) > ymax for point in points)
            for regime in REGIMES
        },
        "spread_definition": "25th–75th percentile of run-level delivered-control P99 across paired seeds; type-7 interpolation",
        "qualification_rule": "cell median P99 < deadline AND cell median deadline-miss fraction < 0.01",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with point_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=POINT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for point in points:
            writer.writerow({key: _fmt(point[key]) if key in (
                "rho", "pmr", "p99_median_T", "p99_q25_T", "p99_q75_T", "miss_median"
            ) else point[key] for key in POINT_COLUMNS})
    output.write_text(figure, encoding="utf-8")
    audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the factorial control-P99 main figure from paired summaries")
    parser.add_argument("--constant", type=Path, required=True)
    parser.add_argument("--moderate", type=Path, required=True)
    parser.add_argument("--strong", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New .svg output filename")
    parser.add_argument("--ymax", type=float, default=2.0, help="Visible P99 cap in control periods; full values remain in CSV")
    args = parser.parse_args(argv)
    audit = generate(args.constant, args.moderate, args.strong, args.out, args.ymax)
    print(json.dumps({"status": audit["status"], "point_count": audit["point_count"],
                      "display_cap_T": audit["display_ymax_T"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
