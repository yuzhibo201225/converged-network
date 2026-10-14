"""Outcome-neutral queue-mechanism follow-up for the frozen FIFO experiment."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from .analysis import packet_metrics, percentile, validate_run_design
from .cli import RUN_COLUMNS, _check_paired, _deadline, _grid, _load_config, _write_csv
from .config import normalize_config
from .factorial_analysis import REGIMES, _check_regimes, _load_regime
from .model import run_one


MECHANISM_FIELDS = (
    "queue_work_ahead", "service_start", "waiting_time", "service_time",
    "bulk_on_at_arrival", "low_service_at_arrival", "bulk_on_low_at_arrival",
    "bulk_on_fraction_preceding_T", "low_service_fraction_preceding_T",
    "bulk_on_low_fraction_preceding_T",
)
RAW_COLUMNS = (
    "rho", "pmr", "seed", "packet_id", "arrival", "completion", "status",
    "latency", "deadline_miss",
) + MECHANISM_FIELDS
MECHANISM_RUN_COLUMNS = (
    "queue_p50", "queue_p90", "queue_p99", "waiting_p50", "waiting_p90",
    "waiting_p99", "service_p50", "service_p90", "service_p99",
    "bulk_on_low_at_arrival_fraction", "bulk_on_fraction_preceding_T_mean",
    "low_service_fraction_preceding_T_mean",
    "bulk_on_low_fraction_preceding_T_mean", "overlap_positive_count",
    "overlap_zero_count", "queue_p99_overlap_positive", "queue_p99_overlap_zero",
)
MECHANISM_RUN_FILE_COLUMNS = RUN_COLUMNS + MECHANISM_RUN_COLUMNS
SUMMARY_METRICS = (
    "p99", "miss_ratio", "queue_p99", "waiting_p99", "service_p99",
    "bulk_on_low_fraction_preceding_T_mean", "queue_p99_overlap_positive",
    "queue_p99_overlap_zero",
)
SUMMARY_COLUMNS = ("regime", "pmr", "seeds") + tuple(
    f"{metric}_median" for metric in SUMMARY_METRICS
) + tuple(f"{metric}_available" for metric in SUMMARY_METRICS)
CONTRAST_COLUMNS = (
    "regime", "metric", "reference_pmr", "comparison_pmr", "seeds_available",
    "median_paired_difference", "q25_paired_difference", "q75_paired_difference",
    "min_paired_difference", "max_paired_difference",
)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite mechanism value")
    return number


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError("invalid boolean mechanism value")


def _pct(values: Iterable[float], fraction: float) -> float | None:
    return percentile(list(values), fraction)


def _mechanism_metrics(rows: list[Mapping[str, object]]) -> dict[str, object]:
    if not rows:
        raise ValueError("empty mechanism cohort")
    queues = [float(row["queue_work_ahead"]) for row in rows]
    waiting = [float(row["waiting_time"]) for row in rows if row.get("waiting_time") not in (None, "")]
    service = [float(row["service_time"]) for row in rows if row.get("service_time") not in (None, "")]
    on = [float(row["bulk_on_fraction_preceding_T"]) for row in rows]
    low = [float(row["low_service_fraction_preceding_T"]) for row in rows]
    overlap = [float(row["bulk_on_low_fraction_preceding_T"]) for row in rows]
    overlap_positive = [queue for queue, exposure in zip(queues, overlap) if exposure > 1e-12]
    overlap_zero = [queue for queue, exposure in zip(queues, overlap) if exposure <= 1e-12]
    return {
        "queue_p50": _pct(queues, 0.50), "queue_p90": _pct(queues, 0.90),
        "queue_p99": _pct(queues, 0.99), "waiting_p50": _pct(waiting, 0.50),
        "waiting_p90": _pct(waiting, 0.90), "waiting_p99": _pct(waiting, 0.99),
        "service_p50": _pct(service, 0.50), "service_p90": _pct(service, 0.90),
        "service_p99": _pct(service, 0.99),
        "bulk_on_low_at_arrival_fraction": sum(
            _bool(row["bulk_on_low_at_arrival"]) for row in rows
        ) / len(rows),
        "bulk_on_fraction_preceding_T_mean": sum(on) / len(on),
        "low_service_fraction_preceding_T_mean": sum(low) / len(low),
        "bulk_on_low_fraction_preceding_T_mean": sum(overlap) / len(overlap),
        "overlap_positive_count": len(overlap_positive),
        "overlap_zero_count": len(overlap_zero),
        "queue_p99_overlap_positive": _pct(overlap_positive, 0.99),
        "queue_p99_overlap_zero": _pct(overlap_zero, 0.99),
    }


def _combined_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    packets = result["packets"]
    mechanism = result["mechanism_rows"]
    if not isinstance(packets, list) or not isinstance(mechanism, list) or len(packets) != len(mechanism):
        raise ValueError("packet and mechanism cohorts differ")
    rows: list[dict[str, object]] = []
    for packet, detail in zip(packets, mechanism):
        if packet["packet_id"] != detail["packet_id"] or packet["arrival"] != detail["arrival"]:
            raise ValueError("packet and mechanism row mismatch")
        rows.append({**packet, **detail})
    return rows


def run(config_path: Path, output_dir: Path) -> None:
    simulation, sweep_spec = _load_config(config_path)
    loads, pmrs, seeds, refine_step = _grid(sweep_spec)
    if len(loads) != 1 or pmrs != [1.0, 3.0] or refine_step < 0.05:
        raise ValueError("mechanism_v1 requires one load, PMR 1/3, and no adaptive refinement")
    simulation = normalize_config(simulation)
    deadline = _deadline(simulation)
    for pmr in pmrs:
        for key in ("warmup_control_packets", "measured_control_packets"):
            if not math.isclose(int(simulation[key]) / pmr, round(int(simulation[key]) / pmr),
                                rel_tol=0, abs_tol=1e-8):
                raise ValueError(f"{key} must contain whole PMR {pmr:g} cycles")
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "simulation": simulation,
        "sweep": {"loads": loads, "pmrs": pmrs, "seeds": seeds, "refine_step": refine_step},
        "deadline": deadline,
        "instrumentation": "mechanism_v1",
    }
    (output_dir / "config.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run_rows: list[dict[str, object]] = []
    with (output_dir / "control_mechanism.csv.gz").open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text_handle:
                writer = csv.DictWriter(text_handle, fieldnames=RAW_COLUMNS,
                                        extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for rho in loads:
                    for seed in seeds:
                        results = [run_one(simulation, rho, pmr, seed, collect_mechanism=True)
                                   for pmr in pmrs]
                        _check_paired(results)
                        for result in results:
                            combined = _combined_rows(result)
                            metrics = packet_metrics(result["packets"], deadline)
                            row: dict[str, object] = {
                                "rho": rho, "pmr": result["pmr"], "seed": seed,
                                **metrics, **_mechanism_metrics(combined),
                            }
                            row.update({key: result[key] for key in RUN_COLUMNS if key in result})
                            run_rows.append(row)
                            for packet in combined:
                                writer.writerow({"rho": rho, "pmr": result["pmr"],
                                                 "seed": seed, **packet})
    run_rows.sort(key=lambda row: (float(row["rho"]), float(row["pmr"]), int(row["seed"])))
    validate_run_design(run_rows, seeds, pmrs, loads)
    _write_csv(output_dir / "runs.csv", MECHANISM_RUN_FILE_COLUMNS, run_rows)


def _raw_runs(raw_path: Path, deadline: float, expected_packets: int) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    with gzip.open(raw_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for (rho, pmr, seed), grouped in groupby(
            reader, key=lambda row: (float(row["rho"]), float(row["pmr"]), int(row["seed"]))
        ):
            rows = list(grouped)
            if [int(row["packet_id"]) for row in rows] != list(range(expected_packets)):
                raise ValueError("incomplete mechanism control cohort")
            for row in rows:
                if row["completion"] == "":
                    row["completion"] = None
            runs.append({"rho": rho, "pmr": pmr, "seed": seed,
                         **packet_metrics(rows, deadline), **_mechanism_metrics(rows)})
    return runs


def audit(input_dir: Path) -> dict[str, object]:
    manifest = json.loads((input_dir / "config.json").read_text(encoding="utf-8"))
    sweep = manifest["sweep"]
    expected = int(manifest["simulation"]["measured_control_packets"])
    raw = _raw_runs(input_dir / "control_mechanism.csv.gz", float(manifest["deadline"]), expected)
    validate_run_design(raw, sweep["seeds"], sweep["pmrs"], sweep["loads"])
    with (input_dir / "runs.csv").open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))
    validate_run_design(saved, sweep["seeds"], sweep["pmrs"], sweep["loads"])
    index = {(float(row["rho"]), float(row["pmr"]), int(row["seed"])): row for row in saved}
    if len(index) != len(raw):
        raise ValueError("raw and saved mechanism run counts differ")
    fields = ("generated", "completed", "dropped", "unfinished", "miss_count")
    numeric = ("p99", "miss_ratio") + MECHANISM_RUN_COLUMNS
    for row in raw:
        key = (float(row["rho"]), float(row["pmr"]), int(row["seed"]))
        saved_row = index[key]
        if any(int(row[field]) != int(saved_row[field]) for field in fields):
            raise ValueError(f"raw/saved mechanism count mismatch at {key}")
        for field in numeric:
            left, right = _optional_float(row.get(field)), _optional_float(saved_row.get(field))
            if left is None and right is None:
                continue
            if left is None or right is None or not math.isclose(left, right, rel_tol=0, abs_tol=1e-10):
                raise ValueError(f"raw/saved mechanism {field} mismatch at {key}")
    return {"status": "PASS", "runs": len(raw),
            "control_packets": len(raw) * expected}


def _median_available(rows: list[Mapping[str, object]], metric: str) -> tuple[float | None, int]:
    values = [_optional_float(row.get(metric)) for row in rows]
    present = [value for value in values if value is not None]
    return (median(present) if present else None), len(present)


def analyze(constant: Path, moderate: Path, strong: Path, out: Path) -> dict[str, object]:
    paths = dict(zip(REGIMES, (constant, moderate, strong)))
    manifests: dict[str, dict[str, Any]] = {}
    rows: dict[str, list[dict[str, str]]] = {}
    for regime, path in paths.items():
        manifests[regime], rows[regime] = _load_regime(path)
        if manifests[regime].get("instrumentation") != "mechanism_v1":
            raise ValueError("mechanism_v1 instrumentation manifest required")
    pairing = _check_regimes(manifests, rows)
    summary_rows: list[dict[str, object]] = []
    contrast_rows: list[dict[str, object]] = []
    for regime in REGIMES:
        by_pmr: dict[float, list[dict[str, str]]] = defaultdict(list)
        for row in rows[regime]:
            by_pmr[float(row["pmr"])].append(row)
        for pmr, arm in sorted(by_pmr.items()):
            summary: dict[str, object] = {"regime": regime, "pmr": pmr, "seeds": len(arm)}
            for metric in SUMMARY_METRICS:
                value, available = _median_available(arm, metric)
                summary[f"{metric}_median"] = value
                summary[f"{metric}_available"] = available
            summary_rows.append(summary)
        reference = {int(row["seed"]): row for row in by_pmr[1.0]}
        comparison = {int(row["seed"]): row for row in by_pmr[3.0]}
        if set(reference) != set(comparison):
            raise ValueError("mechanism PMR arms are not seed-paired")
        for metric in SUMMARY_METRICS:
            differences = []
            for seed in sorted(reference):
                low = _optional_float(reference[seed].get(metric))
                high = _optional_float(comparison[seed].get(metric))
                if low is not None and high is not None:
                    differences.append(high - low)
            contrast_rows.append({
                "regime": regime, "metric": metric, "reference_pmr": 1.0,
                "comparison_pmr": 3.0, "seeds_available": len(differences),
                "median_paired_difference": median(differences) if differences else None,
                "q25_paired_difference": _pct(differences, 0.25),
                "q75_paired_difference": _pct(differences, 0.75),
                "min_paired_difference": min(differences) if differences else None,
                "max_paired_difference": max(differences) if differences else None,
            })
    audit_record: dict[str, object] = {
        "status": "PASS", "instrumentation": "mechanism_v1",
        "scope": "post-confirmatory synthetic-FIFO mechanism follow-up at one fixed load",
        "inputs": {regime: str(path.resolve()) for regime, path in paths.items()},
        "pairing": pairing, "summary_rows": summary_rows, "contrast_rows": contrast_rows,
    }
    out.mkdir(parents=True, exist_ok=False)
    _write_csv(out / "mechanism_summary.csv", SUMMARY_COLUMNS, summary_rows)
    _write_csv(out / "mechanism_paired_contrasts.csv", CONTRAST_COLUMNS, contrast_rows)
    (out / "mechanism_audit.json").write_text(
        json.dumps(audit_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--config", type=Path, required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    audit_parser = commands.add_parser("audit")
    audit_parser.add_argument("--input", type=Path, required=True)
    analyze_parser = commands.add_parser("analyze")
    for regime in REGIMES:
        analyze_parser.add_argument(f"--{regime}", type=Path, required=True)
    analyze_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.config, args.out)
        return 0
    if args.command == "audit":
        print(json.dumps(audit(args.input), sort_keys=True))
        return 0
    result = analyze(args.constant, args.moderate, args.strong, args.out)
    print(json.dumps({"status": result["status"], "pairing": result["pairing"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
