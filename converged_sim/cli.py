"""Command line sweep, raw-data aggregation, and dependency-free SVG plotting."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
from itertools import groupby
from pathlib import Path
from statistics import median
from typing import Any
from xml.sax.saxutils import escape

from .analysis import (
    boundary_summaries, packet_metrics, point_summaries, refinement_loads,
    validate_run_design,
)
from .config import normalize_config
from .model import run_one


PACKET_COLUMNS = ("rho", "pmr", "seed", "packet_id", "arrival", "completion", "status", "latency", "deadline_miss")
RUN_COLUMNS = (
    "rho", "pmr", "seed", "generated", "completed", "dropped", "unfinished", "p99", "miss_count", "miss_ratio",
    "trace_digest", "trace_pattern_digest", "trace_cv", "config_digest", "offered_control_work", "offered_sensor_work", "offered_bulk_work",
    "offered_total_work", "bulk_packet_count", "bulk_packet_count_measured",
    "offered_control_work_measured", "offered_sensor_work_measured", "offered_bulk_work_measured",
    "offered_total_work_measured", "offered_load_actual", "offered_load_measured_actual",
    "trace_mean_rate", "trace_mean_rate_measured", "observation_duration",
    "measurement_start", "measurement_duration", "drain_horizon", "bulk_phase",
)
POINT_COLUMNS = ("rho", "pmr", "runs", "p99_median", "p99_min", "p99_max", "miss_median", "pass")
BOUNDARY_COLUMNS = (
    "pmr", "boundary", "lower_censored", "upper_censored", "nonmonotonic_recovery",
    "seed_boundary_min", "seed_boundary_max", "seed_no_safe_point",
    "seed_upper_censored", "seed_nonmonotonic_recovery", "seeds",
)
SENSITIVITY_COLUMNS = ("deadline_periods",) + BOUNDARY_COLUMNS


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _load_config(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    simulation = data.get("simulation", {})
    sweep = data.get("sweep", {})
    if not isinstance(simulation, dict) or not isinstance(sweep, dict):
        raise ValueError("simulation and sweep must be JSON objects")
    return simulation, sweep


def _grid(sweep: dict[str, object]) -> tuple[list[float], list[float], list[int], float]:
    loads = [round(float(value), 10) for value in sweep.get("loads", [i / 100 for i in range(20, 96, 5)])]
    pmrs = [float(value) for value in sweep.get("pmrs", [1, 1.5, 2, 3])]
    raw_seeds = sweep.get("seeds", list(range(10)))
    if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_seeds):
        raise ValueError("seeds must be integers")
    seeds = list(raw_seeds)
    refine_step = float(sweep.get("refine_step", 0.01))
    if not loads or not pmrs or not seeds:
        raise ValueError("loads, pmrs, and seeds must be nonempty")
    if len(set(loads)) != len(loads) or len(set(pmrs)) != len(pmrs) or len(set(seeds)) != len(seeds):
        raise ValueError("loads, pmrs, and seeds must be unique")
    if any(not math.isfinite(value) or not 0 < value < 1 for value in loads) or any(value < 1 or not math.isfinite(value) for value in pmrs):
        raise ValueError("loads must lie in (0,1) and PMRs must be >= 1")
    if not 0 < refine_step < 1:
        raise ValueError("refine_step must lie in (0,1)")
    return sorted(loads), sorted(pmrs), sorted(seeds), refine_step


def _deadline(simulation: dict[str, object]) -> float:
    value = float(simulation.get("control_period", 1.0)) * float(simulation.get("deadline_periods", 1.0))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("deadline must be positive and finite")
    return value


def _check_paired(results: list[dict[str, object]]) -> None:
    if len(results) <= 1:
        return
    reference = results[0]
    for result in results[1:]:
        if result["trace_digest"] != reference["trace_digest"]:
            raise ValueError("paired arms did not use the same service trace")
        for key in (
            "offered_control_work", "offered_sensor_work", "offered_bulk_work",
            "offered_total_work", "bulk_packet_count", "bulk_packet_count_measured",
            "offered_control_work_measured", "offered_sensor_work_measured",
            "offered_bulk_work_measured", "offered_total_work_measured",
            "offered_load_measured_actual", "trace_mean_rate_measured",
        ):
            if not math.isclose(float(result[key]), float(reference[key]), rel_tol=0, abs_tol=1e-9):
                raise ValueError(f"paired arms differ in {key}")


def _run_load(
    simulation: dict[str, object], rho: float, pmrs: list[float], seeds: list[int],
    packet_writer: csv.DictWriter, run_rows: list[dict[str, object]],
) -> None:
    for seed in seeds:
        results = [run_one(simulation, rho, pmr, seed) for pmr in pmrs]
        _check_paired(results)
        for result in results:
            packets = result["packets"]
            metrics = packet_metrics(packets, _deadline(simulation))
            row: dict[str, object] = {"rho": rho, "pmr": result["pmr"], "seed": seed, **metrics}
            row.update({key: result[key] for key in RUN_COLUMNS if key in result})
            run_rows.append(row)
            for packet in packets:
                packet_writer.writerow({"rho": rho, "pmr": result["pmr"], "seed": seed, **packet})


def sweep(config_path: Path, output_dir: Path) -> None:
    simulation, sweep_spec = _load_config(config_path)
    loads, pmrs, seeds, refine_step = _grid(sweep_spec)
    simulation = normalize_config(simulation)
    deadline = _deadline(simulation)
    for pmr in pmrs:
        for key in ("warmup_control_packets", "measured_control_packets"):
            cycles = int(simulation[key])
            if not math.isclose(cycles / pmr, round(cycles / pmr), rel_tol=0, abs_tol=1e-8):
                raise ValueError(f"{key} must contain whole PMR {pmr:g} cycles")
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"simulation": simulation, "sweep": {"loads": loads, "pmrs": pmrs, "seeds": seeds, "refine_step": refine_step}, "deadline": deadline}
    (output_dir / "config.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run_rows: list[dict[str, object]] = []
    with (output_dir / "control_packets.csv.gz").open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text_handle:
                packet_writer = csv.DictWriter(text_handle, fieldnames=PACKET_COLUMNS, extrasaction="ignore", lineterminator="\n")
                packet_writer.writeheader()
                for rho in loads:
                    _run_load(simulation, rho, pmrs, seeds, packet_writer, run_rows)
                coarse_points = point_summaries(run_rows, deadline)
                for rho in refinement_loads(coarse_points, refine_step):
                    if rho not in loads:
                        _run_load(simulation, rho, pmrs, seeds, packet_writer, run_rows)
    run_rows.sort(key=lambda row: (float(row["rho"]), float(row["pmr"]), int(row["seed"])))
    validate_run_design(run_rows, seeds, pmrs, loads)
    _write_csv(output_dir / "runs.csv", RUN_COLUMNS, run_rows)
    points = point_summaries(run_rows, deadline)
    _write_csv(output_dir / "points.csv", POINT_COLUMNS, points)
    _write_csv(output_dir / "boundaries.csv", BOUNDARY_COLUMNS, boundary_summaries(run_rows, deadline))


def runs_from_raw(
    raw_path: Path, deadline: float, expected_packets: int | None = None,
    verify_recorded_deadline_miss: bool = True,
) -> list[dict[str, object]]:
    """Recompute run metrics directly from the saved packet cohort."""
    runs: list[dict[str, object]] = []
    with gzip.open(raw_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for (rho, pmr, seed), rows in groupby(reader, key=lambda row: (float(row["rho"]), float(row["pmr"]), int(row["seed"]))):
            packets = list(rows)
            if expected_packets is not None:
                ids = [int(packet["packet_id"]) for packet in packets]
                if ids != list(range(expected_packets)):
                    raise ValueError(f"incomplete control cohort for rho={rho}, pmr={pmr}, seed={seed}")
            metrics = packet_metrics(packets, deadline, verify_recorded_deadline_miss)
            runs.append({"rho": rho, "pmr": pmr, "seed": seed, **metrics})
    return runs


def runs_from_raw_deadlines(
    raw_path: Path, deadlines: list[float], expected_packets: int | None = None,
    recorded_deadline: float | None = None,
) -> dict[float, list[dict[str, object]]]:
    """Recompute multiple deadline views during one raw-file decompression pass."""
    normalized = [float(deadline) for deadline in deadlines]
    if not normalized or len(set(normalized)) != len(normalized):
        raise ValueError("deadlines must be a nonempty unique list")
    if any(not math.isfinite(deadline) or deadline <= 0 for deadline in normalized):
        raise ValueError("deadlines must be positive and finite")
    runs = {deadline: [] for deadline in normalized}
    with gzip.open(raw_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for (rho, pmr, seed), grouped in groupby(
            reader, key=lambda row: (float(row["rho"]), float(row["pmr"]), int(row["seed"]))
        ):
            packets = list(grouped)
            if expected_packets is not None:
                ids = [int(packet["packet_id"]) for packet in packets]
                if ids != list(range(expected_packets)):
                    raise ValueError(
                        f"incomplete control cohort for rho={rho}, pmr={pmr}, seed={seed}"
                    )
            for deadline in normalized:
                verify = recorded_deadline is not None and math.isclose(
                    deadline, recorded_deadline, rel_tol=0, abs_tol=1e-12
                )
                metrics = packet_metrics(packets, deadline, verify)
                runs[deadline].append({"rho": rho, "pmr": pmr, "seed": seed, **metrics})
    return runs


def audit(input_dir: Path) -> dict[str, Any]:
    """Compare saved summaries with raw packet records and paired-run metadata."""
    manifest = json.loads((input_dir / "config.json").read_text(encoding="utf-8"))
    sweep_spec = manifest["sweep"]
    expected_packets = int(manifest["simulation"]["measured_control_packets"])
    raw = runs_from_raw(
        input_dir / "control_packets.csv.gz", float(manifest["deadline"]), expected_packets
    )
    validate_run_design(raw, sweep_spec["seeds"], sweep_spec["pmrs"], sweep_spec["loads"])
    with (input_dir / "runs.csv").open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))
    validate_run_design(saved, sweep_spec["seeds"], sweep_spec["pmrs"], sweep_spec["loads"])
    by_key = {(float(row["rho"]), float(row["pmr"]), int(row["seed"])): row for row in saved}
    if len(raw) != len(saved):
        raise ValueError("raw and saved run counts differ")
    for row in raw:
        key = (float(row["rho"]), float(row["pmr"]), int(row["seed"]))
        saved_row = by_key[key]
        for field in ("generated", "completed", "dropped", "unfinished", "miss_count"):
            if int(row[field]) != int(saved_row[field]):
                raise ValueError(f"raw/saved {field} mismatch at {key}")
        for field in ("p99", "miss_ratio"):
            raw_value, saved_value = row[field], saved_row[field]
            if raw_value is None and saved_value == "":
                continue
            if raw_value is None or saved_value == "" or not math.isclose(
                float(raw_value), float(saved_value), rel_tol=0, abs_tol=1e-10
            ):
                raise ValueError(f"raw/saved {field} mismatch at {key}")
    paired: dict[tuple[float, int], list[dict[str, object]]] = {}
    for row in saved:
        paired.setdefault((float(row["rho"]), int(row["seed"])), []).append(row)
    for rows in paired.values():
        _check_paired(rows)
    return {"status": "PASS", "runs": len(raw), "control_packets": len(raw) * expected_packets}


def _svg(points: list[dict[str, object]], deadline_periods: float, period: float) -> str:
    width, height = 960, 620
    left, right, top, bottom = 100, 35, 45, 95
    plot_width, plot_height = width - left - right, height - top - bottom
    data = [point for point in points if point["p99_median"] is not None]
    if not data:
        raise ValueError("no delivered control packets to plot")
    xlo = min(float(point["rho"]) for point in data)
    xhi = max(float(point["rho"]) for point in data)
    if xlo == xhi:
        xlo -= 0.025
        xhi += 0.025
    ymax = max(deadline_periods, max(float(point["p99_max"]) / period for point in data if point["p99_max"] is not None))
    ymax = max(ymax * 1.1, 0.1)
    x = lambda rho: left + (rho - xlo) / (xhi - xlo) * plot_width
    y = lambda value: top + (1 - value / ymax) * plot_height
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#20252c}.grid{stroke:#e3e6ea;stroke-width:1}.axis{stroke:#303944;stroke-width:1.5}</style>',
        f'<text x="{left}" y="27" font-size="20">Control-flow P99 versus offered load</text>',
    ]
    for index in range(6):
        value = ymax * index / 5
        yy = y(value)
        parts.append(f'<line class="grid" x1="{left}" y1="{yy:.2f}" x2="{width-right}" y2="{yy:.2f}"/>')
        parts.append(f'<text x="{left-12}" y="{yy+4:.2f}" text-anchor="end" font-size="13">{value:.2f}</text>')
    for index in range(6):
        value = xlo + (xhi - xlo) * index / 5
        xx = x(value)
        parts.append(f'<line class="grid" x1="{xx:.2f}" y1="{top}" x2="{xx:.2f}" y2="{height-bottom}"/>')
        parts.append(f'<text x="{xx:.2f}" y="{height-bottom+23}" text-anchor="middle" font-size="13">{value:.2f}</text>')
    parts.append(f'<line class="axis" x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}"/>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}"/>')
    dy = y(deadline_periods)
    parts.append(f'<line x1="{left}" y1="{dy:.2f}" x2="{width-right}" y2="{dy:.2f}" stroke="#9c2828" stroke-dasharray="7,5" stroke-width="2"/>')
    parts.append(f'<text x="{width-right-4}" y="{dy-7:.2f}" text-anchor="end" fill="#9c2828" font-size="13">deadline</text>')
    palette = ["#087e8b", "#e18d00", "#7d4fbd", "#d44c55", "#427551", "#607d8b"]
    arms = sorted({float(point["pmr"]) for point in data})
    for arm_index, pmr in enumerate(arms):
        color = palette[arm_index % len(palette)]
        arm = sorted((point for point in data if float(point["pmr"]) == pmr), key=lambda point: float(point["rho"]))
        upper = " ".join(f'{x(float(point["rho"])):.2f},{y(float(point["p99_max"]) / period):.2f}' for point in arm)
        lower = " ".join(f'{x(float(point["rho"])):.2f},{y(float(point["p99_min"]) / period):.2f}' for point in reversed(arm))
        parts.append(f'<polygon points="{upper} {lower}" fill="{color}" opacity="0.13"/>')
        line = " ".join(f'{x(float(point["rho"])):.2f},{y(float(point["p99_median"]) / period):.2f}' for point in arm)
        parts.append(f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.4"/>')
        for point in arm:
            parts.append(f'<circle cx="{x(float(point["rho"])):.2f}" cy="{y(float(point["p99_median"]) / period):.2f}" r="2.5" fill="{color}"/>')
        legend_x = left + 15 + (arm_index % 3) * 220
        legend_y = height - 49 + (arm_index // 3) * 18
        parts.append(f'<line x1="{legend_x}" y1="{legend_y-4}" x2="{legend_x+24}" y2="{legend_y-4}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x+31}" y="{legend_y}" font-size="13">PMR {escape(f"{pmr:g}")}</text>')
    parts.append(f'<text x="{left + plot_width/2:.2f}" y="{height-65}" text-anchor="middle" font-size="15">Target offered load / trace mean capacity (ρ)</text>')
    parts.append(f'<text x="24" y="{top + plot_height/2:.2f}" transform="rotate(-90 24 {top + plot_height/2:.2f})" text-anchor="middle" font-size="15">P99 latency / control period</text>')
    parts.append('</svg>')
    return "\n".join(parts) + "\n"


def plot(input_dir: Path, output_path: Path) -> None:
    manifest = json.loads((input_dir / "config.json").read_text(encoding="utf-8"))
    simulation = manifest["simulation"]
    deadline = float(manifest["deadline"])
    period = float(simulation.get("control_period", 1.0))
    runs = runs_from_raw(
        input_dir / "control_packets.csv.gz", deadline,
        int(simulation["measured_control_packets"]),
    )
    sweep_spec = manifest["sweep"]
    validate_run_design(runs, sweep_spec["seeds"], sweep_spec["pmrs"], sweep_spec["loads"])
    points = point_summaries(runs, deadline)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_svg(points, deadline / period, period), encoding="utf-8")


def sensitivity(input_dir: Path, output_path: Path) -> None:
    """Recompute the three predeclared deadline boundaries from the same raw data."""
    manifest = json.loads((input_dir / "config.json").read_text(encoding="utf-8"))
    simulation, sweep_spec = manifest["simulation"], manifest["sweep"]
    period = float(simulation["control_period"])
    count = int(simulation["measured_control_packets"])
    multipliers = (0.5, 1.0, 2.0)
    deadlines = [multiplier * period for multiplier in multipliers]
    by_deadline = runs_from_raw_deadlines(
        input_dir / "control_packets.csv.gz", deadlines, count,
        recorded_deadline=float(manifest["deadline"]),
    )
    rows: list[dict[str, object]] = []
    for multiplier, deadline in zip(multipliers, deadlines):
        runs = by_deadline[deadline]
        validate_run_design(runs, sweep_spec["seeds"], sweep_spec["pmrs"], sweep_spec["loads"])
        rows.extend({"deadline_periods": multiplier, **row}
                    for row in boundary_summaries(runs, deadline))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output_path, SENSITIVITY_COLUMNS, rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paired burstiness versus control tail-latency study")
    commands = parser.add_subparsers(dest="command", required=True)
    sweep_parser = commands.add_parser("sweep", help="run coarse and first-crossing refined experiment")
    sweep_parser.add_argument("--config", type=Path, required=True)
    sweep_parser.add_argument("--out", type=Path, required=True)
    plot_parser = commands.add_parser("plot", help="regenerate the SVG figure directly from raw packets")
    plot_parser.add_argument("--input", type=Path, required=True)
    plot_parser.add_argument("--out", type=Path, required=True)
    audit_parser = commands.add_parser("audit", help="verify raw packets, summaries, and pairing")
    audit_parser.add_argument("--input", type=Path, required=True)
    sensitivity_parser = commands.add_parser(
        "sensitivity", help="recompute 0.5T, 1T, and 2T deadline boundaries from raw packets"
    )
    sensitivity_parser.add_argument("--input", type=Path, required=True)
    sensitivity_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "sweep":
        sweep(args.config, args.out)
    elif args.command == "plot":
        plot(args.input, args.out)
    elif args.command == "sensitivity":
        sensitivity(args.input, args.out)
    else:
        print(json.dumps(audit(args.input), sort_keys=True))
    return 0
