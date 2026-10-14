"""Read-only, paired three-regime analysis of the synthetic FIFO experiment.

The reported contrasts are descriptive properties of the scanned load grid.
They are not confidence intervals or estimates for physical wireless links.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .analysis import boundary_summaries, validate_run_design


REGIMES = ("constant", "moderate", "strong")
WORK_COLUMNS = (
    "offered_control_work", "offered_sensor_work", "offered_bulk_work",
    "offered_total_work", "offered_control_work_measured",
    "offered_sensor_work_measured", "offered_bulk_work_measured",
    "offered_total_work_measured", "bulk_packet_count",
    "bulk_packet_count_measured", "offered_load_actual",
)
BOUNDARY_COLUMNS = (
    "regime", "pmr", "boundary", "lower_censored", "upper_censored",
    "nonmonotonic_recovery", "seed_boundary_min", "seed_boundary_max",
    "seed_no_safe_point", "seed_upper_censored", "seed_nonmonotonic_recovery",
    "seeds", "grid_erosion_vs_pmr1", "grid_interaction_vs_constant",
    "erosion_if_uncensored", "interaction_if_uncensored",
)


def _number(row: dict[str, str], key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"missing or invalid {key}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite {key}")
    return value


def _equal(a: float, b: float, tolerance: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance)


def _load_regime(directory: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    with (directory / "config.json").open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("simulation"), dict):
        raise ValueError(f"invalid config.json in {directory}")
    if not isinstance(manifest.get("sweep"), dict):
        raise ValueError(f"invalid sweep manifest in {directory}")
    if manifest["simulation"].get("trace_normalize_mean") is not True:
        raise ValueError(f"trace_normalize_mean must be true: {directory}")
    with (directory / "runs.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "trace_pattern_digest" not in reader.fieldnames:
            raise ValueError(f"runs.csv lacks trace_pattern_digest: {directory}")
        rows = list(reader)
    sweep = manifest["sweep"]
    validate_run_design(rows, sweep["seeds"], sweep["pmrs"], sweep["loads"])
    expected = {
        (float(rho), float(pmr), int(seed))
        for rho in sweep["loads"] for pmr in sweep["pmrs"] for seed in sweep["seeds"]
    }
    actual = {(float(row["rho"]), float(row["pmr"]), int(row["seed"])) for row in rows}
    # Refined loads are permitted, but every refined point must be a full
    # PMR × seed crossing, rather than a sparse collection of favorable runs.
    loads = {key[0] for key in actual}
    full = {(rho, float(pmr), int(seed)) for rho in loads
            for pmr in sweep["pmrs"] for seed in sweep["seeds"]}
    if not expected.issubset(actual) or actual != full:
        raise ValueError(f"incomplete coarse or refined grid: {directory}")
    expected_packets = int(manifest["simulation"]["measured_control_packets"])
    for row in rows:
        if not row["trace_pattern_digest"]:
            raise ValueError("empty trace_pattern_digest")
        if not _equal(_number(row, "trace_mean_rate"), 1.0):
            raise ValueError("trace_mean_rate is not normalized to 1")
        generated = int(row["generated"])
        completed, dropped, unfinished = (int(row[key]) for key in ("completed", "dropped", "unfinished"))
        misses = int(row["miss_count"])
        if generated != expected_packets or completed + dropped + unfinished != generated:
            raise ValueError("invalid control-packet cohort counts")
        if not 0 <= misses <= generated or not _equal(_number(row, "miss_ratio"), misses / generated):
            raise ValueError("invalid miss count or miss ratio")
        if row["p99"] != "" and _number(row, "p99") < 0:
            raise ValueError("negative P99")
        for key in WORK_COLUMNS:
            _number(row, key)
    return manifest, rows


def _check_regimes(manifests: dict[str, dict[str, Any]], rows: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    baseline = manifests["constant"]
    baseline_sim = {key: value for key, value in baseline["simulation"].items()
                    if key not in ("trace_low_rate", "trace_high_rate")}
    for name in REGIMES:
        manifest = manifests[name]
        sim = manifest["simulation"]
        comparable = {key: value for key, value in sim.items()
                      if key not in ("trace_low_rate", "trace_high_rate")}
        if comparable != baseline_sim or manifest["sweep"] != baseline["sweep"] or not _equal(
            float(manifest["deadline"]), float(baseline["deadline"])
        ):
            raise ValueError(f"simulation controls, sweep design, or deadline differ in {name}")
    spreads: dict[str, float] = {}
    for name in REGIMES:
        sim = manifests[name]["simulation"]
        low, high = float(sim["trace_low_rate"]), float(sim["trace_high_rate"])
        if low <= 0 or high <= 0 or low > high:
            raise ValueError(f"invalid service-rate bounds in {name}")
        spreads[name] = high - low
    if not (_equal(spreads["constant"], 0.0) and
            spreads["constant"] < spreads["moderate"] < spreads["strong"]):
        raise ValueError("service regimes must have increasing rate spread")

    index = {name: {(float(row["rho"]), float(row["pmr"]), int(row["seed"])): row
                    for row in rows[name]} for name in REGIMES}
    keys = set(index["constant"])
    for name in REGIMES[1:]:
        if set(index[name]) != keys:
            raise ValueError("regimes do not share an identical load/PMR/seed grid")

    # This digest must encode the Bernoulli high/low pattern, not the numeric
    # rate amplitudes.  Every arm and load for one seed reuses that pattern.
    pattern_by_seed: dict[int, str] = {}
    max_measured_trace_spread = 0.0
    max_measured_trace_error = 0.0
    max_measured_load_spread = 0.0
    for key in sorted(keys):
        seed = key[2]
        anchor = index["constant"][key]
        pattern = anchor["trace_pattern_digest"]
        if seed in pattern_by_seed and pattern_by_seed[seed] != pattern:
            raise ValueError(f"trace_pattern_digest changed within seed {seed}")
        pattern_by_seed[seed] = pattern
        for name in REGIMES[1:]:
            row = index[name][key]
            if row["trace_pattern_digest"] != pattern:
                raise ValueError(f"trace_pattern_digest mismatch at {key}: {name}")
            for field in WORK_COLUMNS:
                if not _equal(_number(row, field), _number(anchor, field)):
                    raise ValueError(f"offered work differs across regimes at {key}: {field}")
        max_measured_trace_spread = max(
            max_measured_trace_spread,
            max(_number(index[name][key], "trace_mean_rate_measured") for name in REGIMES)
            - min(_number(index[name][key], "trace_mean_rate_measured") for name in REGIMES),
        )
        max_measured_trace_error = max(
            max_measured_trace_error,
            max(abs(_number(index[name][key], "trace_mean_rate_measured") - 1.0)
                for name in REGIMES),
        )
        max_measured_load_spread = max(
            max_measured_load_spread,
            max(_number(index[name][key], "offered_load_measured_actual") for name in REGIMES)
            - min(_number(index[name][key], "offered_load_measured_actual") for name in REGIMES),
        )

    return {
        "paired_grid_points": len(keys),
        "loads": sorted({key[0] for key in keys}),
        "pmrs": sorted({key[1] for key in keys}),
        "seeds": sorted({key[2] for key in keys}),
        "rate_spreads": spreads,
        "trace_mean_tolerance": 1e-9,
        "offered_work_tolerance": 1e-9,
        "max_cross_regime_trace_mean_rate_measured_spread": max_measured_trace_spread,
        "max_abs_trace_mean_rate_measured_error": max_measured_trace_error,
        "max_cross_regime_offered_load_measured_actual_spread": max_measured_load_spread,
    }


def _boundary_rows(
    manifests: dict[str, dict[str, Any]], rows: dict[str, list[dict[str, str]]]
) -> list[dict[str, object]]:
    by_regime: dict[str, dict[float, dict[str, object]]] = {}
    for name in REGIMES:
        boundary = boundary_summaries(rows[name], float(manifests[name]["deadline"]))
        by_regime[name] = {float(item["pmr"]): item for item in boundary}
    if 1.0 not in by_regime["constant"]:
        raise ValueError("PMR=1 reference arm is missing")

    out: list[dict[str, object]] = []
    for name in REGIMES:
        reference = by_regime[name][1.0]
        constant_reference = by_regime["constant"][1.0]
        for pmr, arm in sorted(by_regime[name].items()):
            constant_arm = by_regime["constant"][pmr]
            boundary = arm["boundary"]
            ref_boundary = reference["boundary"]
            const_boundary = constant_arm["boundary"]
            const_ref_boundary = constant_reference["boundary"]
            grid_erosion = None if boundary is None or ref_boundary is None else round(
                float(ref_boundary) - float(boundary), 10
            )
            constant_grid_erosion = None if const_boundary is None or const_ref_boundary is None else round(
                float(const_ref_boundary) - float(const_boundary), 10
            )
            grid_interaction = None if grid_erosion is None or constant_grid_erosion is None else round(
                grid_erosion - constant_grid_erosion, 10
            )
            own_uncensored = not any(bool(item[flag]) for item in (arm, reference)
                                     for flag in ("lower_censored", "upper_censored"))
            all_uncensored = own_uncensored and not any(
                bool(item[flag]) for item in (constant_arm, constant_reference)
                for flag in ("lower_censored", "upper_censored")
            )
            out.append({
                "regime": name, **arm,
                "grid_erosion_vs_pmr1": grid_erosion,
                "grid_interaction_vs_constant": grid_interaction,
                "erosion_if_uncensored": grid_erosion if own_uncensored else None,
                "interaction_if_uncensored": grid_interaction if all_uncensored else None,
            })
    return out


def _svg(boundaries: list[dict[str, object]]) -> str:
    """Small exploratory figure; missing or censored values remain explicit."""
    width, height = 810, 530
    left, right, top, bottom = 95, 185, 55, 95
    plot_w, plot_h = width - left - right, height - top - bottom
    plotted = [row for row in boundaries if row["grid_erosion_vs_pmr1"] is not None]
    if not plotted:
        raise ValueError("no observed boundary contrasts to plot")
    pmrs = sorted({float(row["pmr"]) for row in boundaries})
    lo, hi = min(pmrs), max(pmrs)
    if lo == hi:
        lo -= 0.5
        hi += 0.5
    values = [float(row["grid_erosion_vs_pmr1"]) for row in plotted]
    ylo, yhi = min(0.0, min(values)), max(0.0, max(values))
    padding = max(0.025, (yhi - ylo) * 0.12)
    ylo -= padding
    yhi += padding
    x = lambda value: left + (value - lo) / (hi - lo) * plot_w
    y = lambda value: top + (yhi - value) / (yhi - ylo) * plot_h
    colors = {"constant": "#4263a5", "moderate": "#d08027", "strong": "#b33b57"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#20252c}.grid{stroke:#e5e9ec;stroke-width:1}</style>',
        f'<text x="{left}" y="28" font-size="19">Observed boundary erosion versus bulk PMR</text>',
    ]
    for step in range(5):
        value = ylo + (yhi - ylo) * step / 4
        yy = y(value)
        parts.append(f'<line class="grid" x1="{left}" y1="{yy:.2f}" x2="{left+plot_w}" y2="{yy:.2f}"/>')
        parts.append(f'<text x="{left-10}" y="{yy+4:.2f}" text-anchor="end" font-size="12">{value:.2f}</text>')
    for pmr in pmrs:
        xx = x(pmr)
        parts.append(f'<line class="grid" x1="{xx:.2f}" y1="{top}" x2="{xx:.2f}" y2="{top+plot_h}"/>')
        parts.append(f'<text x="{xx:.2f}" y="{top+plot_h+22}" text-anchor="middle" font-size="12">{pmr:g}</text>')
    for name in REGIMES:
        arm = sorted((row for row in plotted if row["regime"] == name), key=lambda row: float(row["pmr"]))
        if not arm:
            continue
        color = colors[name]
        coords = " ".join(f'{x(float(row["pmr"])):.2f},{y(float(row["grid_erosion_vs_pmr1"])):.2f}' for row in arm)
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for row in arm:
            cx, cy = x(float(row["pmr"])), y(float(row["grid_erosion_vs_pmr1"]))
            censored = row["erosion_if_uncensored"] is None
            parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="5" fill="{"white" if censored else color}" stroke="{color}" stroke-width="2"/>')
        legend_y = top + 20 + REGIMES.index(name) * 27
        parts.append(f'<line x1="{width-right+20}" y1="{legend_y-4}" x2="{width-right+45}" y2="{legend_y-4}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{width-right+52}" y="{legend_y}" font-size="13">{escape(name)}</text>')
    parts.extend([
        f'<text x="{left+plot_w/2:.2f}" y="{height-50}" text-anchor="middle" font-size="14">Bulk peak-to-mean rate ratio (PMR)</text>',
        f'<text x="25" y="{top+plot_h/2:.2f}" transform="rotate(-90 25 {top+plot_h/2:.2f})" text-anchor="middle" font-size="14">Grid boundary erosion (rho units)</text>',
        f'<text x="{left}" y="{height-20}" font-size="11">Exploratory coarse-grid contrasts; open circles involve a censored boundary.</text>',
        '</svg>',
    ])
    return "\n".join(parts) + "\n"


def analyze(constant: Path, moderate: Path, strong: Path, out: Path) -> dict[str, Any]:
    """Validate pairings before writing a CSV, JSON audit, and exploratory SVG."""
    paths = {"constant": constant, "moderate": moderate, "strong": strong}
    if len({path.resolve() for path in paths.values()}) != 3:
        raise ValueError("regime input directories must be distinct")
    manifests: dict[str, dict[str, Any]] = {}
    rows: dict[str, list[dict[str, str]]] = {}
    for name, path in paths.items():
        manifests[name], rows[name] = _load_regime(path)
    checks = _check_regimes(manifests, rows)
    boundaries = _boundary_rows(manifests, rows)
    loads = checks["loads"]
    grid_step = min((b - a for a, b in zip(loads, loads[1:])), default=None)
    nontrivial_interactions = [
        abs(float(row["grid_interaction_vs_constant"]))
        for row in boundaries
        if row["regime"] != "constant" and float(row["pmr"]) != 1.0
        and row["grid_interaction_vs_constant"] is not None
    ]
    trace_spread = checks["max_cross_regime_trace_mean_rate_measured_spread"]
    trace_error = checks["max_abs_trace_mean_rate_measured_error"]
    cautions = [
        (
            "Measured-window service means match exactly across regimes under the frozen balanced-window design."
            if trace_spread <= 1e-12 and trace_error <= 1e-12
            else "Measured-window service means need not match exactly even though full-trace means are normalized to one."
        ),
        "Any contrast involving a censored boundary is a within-grid descriptor, not a point estimate of the true boundary difference.",
    ]
    if grid_step is not None and any(value <= grid_step + 1e-10 for value in nontrivial_interactions):
        cautions.append("At least one non-reference grid interaction is no larger than one load-grid step.")
    if any(value <= checks["max_cross_regime_offered_load_measured_actual_spread"] + 1e-10
           for value in nontrivial_interactions):
        cautions.append("At least one non-reference grid interaction is no larger than the maximum measured-window offered-load spread.")
    summary: dict[str, Any] = {
        "status": "PASS",
        "data_source": "runs.csv summaries; raw packet records are not re-audited here",
        "scope": "synthetic finite-FIFO model; descriptive scanned-grid analysis only",
        "inputs": {name: str(path.resolve()) for name, path in paths.items()},
        "runs_per_regime": {name: len(rows[name]) for name in REGIMES},
        "pairing": checks,
        "deadline": float(manifests["constant"]["deadline"]),
        "miss_limit": 0.01,
        "boundary_rows": boundaries,
        "minimum_load_grid_step": grid_step,
        "interpretive_cautions": cautions,
        "censoring_note": "grid erosion/interaction use observed passing-prefix endpoints; uncensored columns are blank if a required boundary is censored",
    }
    figure = _svg(boundaries)
    out.mkdir(parents=True, exist_ok=False)
    with (out / "factorial_boundaries.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOUNDARY_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(boundaries)
    (out / "factorial_audit.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "erosion.svg").write_text(figure, encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and compare three paired service-variability sweeps")
    parser.add_argument("--constant", type=Path, required=True)
    parser.add_argument("--moderate", type=Path, required=True)
    parser.add_argument("--strong", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = analyze(args.constant, args.moderate, args.strong, args.out)
    print(json.dumps({"status": summary["status"], "pairing": summary["pairing"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
