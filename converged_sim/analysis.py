"""Deterministic aggregation of control-packet simulation output.

The unit of replication is one simulation seed. A packet without a completion
counts as a deadline miss, but never enters the delivered-packet P99.
"""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from statistics import median
from typing import Iterable, Mapping


def percentile(values: Iterable[float], fraction: float) -> float | None:
    """Return the linearly interpolated empirical percentile (type 7)."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between zero and one")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight


def packet_metrics(
    packets: Iterable[Mapping[str, object]], deadline: float,
    verify_recorded_deadline_miss: bool = True,
) -> dict[str, float | int | None]:
    """Summarize a generated cohort of control packets, including unfinished ones."""
    if not isfinite(deadline) or deadline <= 0:
        raise ValueError("deadline must be positive and finite")
    generated = completed = dropped = unfinished = misses = 0
    latencies: list[float] = []
    for packet in packets:
        generated += 1
        status = str(packet["status"])
        arrival = float(packet["arrival"])
        completion = packet.get("completion")
        expected_miss: bool
        if status == "delivered":
            if completion is None:
                raise ValueError("delivered packet has no completion")
            latency = float(completion) - arrival
            if not isfinite(latency) or latency < 0:
                raise ValueError("invalid packet latency")
            completed += 1
            latencies.append(latency)
            expected_miss = latency >= deadline
        elif status == "dropped":
            dropped += 1
            expected_miss = True
        elif status == "unfinished":
            unfinished += 1
            expected_miss = True
        else:
            raise ValueError(f"unknown packet status: {status}")
        if verify_recorded_deadline_miss and "deadline_miss" in packet:
            recorded = packet["deadline_miss"]
            if isinstance(recorded, str):
                if recorded not in ("True", "False"):
                    raise ValueError("invalid recorded deadline miss value")
                recorded = recorded == "True"
            if recorded is not expected_miss:
                raise ValueError("recorded deadline miss disagrees with packet outcome")
        misses += expected_miss
    if generated == 0:
        raise ValueError("cannot summarize an empty control cohort")
    return {
        "generated": generated,
        "completed": completed,
        "dropped": dropped,
        "unfinished": unfinished,
        "p99": percentile(latencies, 0.99),
        "miss_count": misses,
        "miss_ratio": misses / generated,
    }


def validate_run_design(
    rows: Iterable[Mapping[str, object]],
    expected_seeds: Iterable[int] | None = None,
    expected_pmrs: Iterable[float] | None = None,
    expected_loads: Iterable[float] | None = None,
) -> None:
    """Reject incomplete or duplicated paired runs before drawing a boundary."""
    by_point: dict[tuple[float, float], set[int]] = defaultdict(set)
    pmr_loads: dict[float, set[float]] = defaultdict(set)
    for row in rows:
        rho, pmr, seed = float(row["rho"]), float(row["pmr"]), int(row["seed"])
        key = (rho, pmr)
        if seed in by_point[key]:
            raise ValueError(f"duplicate run for rho={rho}, pmr={pmr}, seed={seed}")
        by_point[key].add(seed)
        pmr_loads[pmr].add(rho)
    if not by_point:
        raise ValueError("no runs to analyze")
    seed_sets = list(by_point.values())
    reference_seeds = set(expected_seeds) if expected_seeds is not None else seed_sets[0]
    if any(seed_set != reference_seeds for seed_set in seed_sets):
        raise ValueError("incomplete seed pairing across load and PMR points")
    if expected_pmrs is not None and set(pmr_loads) != {float(value) for value in expected_pmrs}:
        raise ValueError("PMR arms do not match the configured arms")
    load_sets = list(pmr_loads.values())
    reference_loads = load_sets[0]
    if any(load_set != reference_loads for load_set in load_sets):
        raise ValueError("PMR arms do not share the same load grid")
    if expected_loads is not None and not {float(value) for value in expected_loads}.issubset(reference_loads):
        raise ValueError("configured coarse loads are missing")


def point_summaries(rows: Iterable[Mapping[str, object]], deadline: float, miss_limit: float = 0.01) -> list[dict[str, object]]:
    """Pool *run metrics*, not packets, for each paired load/PMR point."""
    runs = list(rows)
    validate_run_design(runs)
    grouped: dict[tuple[float, float], list[Mapping[str, object]]] = defaultdict(list)
    for row in runs:
        grouped[(float(row["rho"]), float(row["pmr"]))].append(row)
    points: list[dict[str, object]] = []
    for (rho, pmr), runs in sorted(grouped.items()):
        p99s = [float(row["p99"]) for row in runs if row.get("p99") not in (None, "")]
        misses = [float(row["miss_ratio"]) for row in runs]
        median_p99 = median(p99s) if len(p99s) == len(runs) else None
        median_miss = median(misses)
        points.append({
            "rho": rho,
            "pmr": pmr,
            "runs": len(runs),
            "p99_median": median_p99,
            "p99_min": min(p99s) if p99s else None,
            "p99_max": max(p99s) if p99s else None,
            "miss_median": median_miss,
            "pass": median_p99 is not None and median_p99 < deadline and median_miss < miss_limit,
        })
    return points


def contiguous_boundary(points: Iterable[Mapping[str, object]]) -> tuple[float | None, bool]:
    """Highest load in the passing prefix; censored if no failure is observed."""
    ordered = sorted(points, key=lambda row: float(row["rho"]))
    boundary = None
    failed = False
    for point in ordered:
        if not bool(point["pass"]):
            failed = True
            break
        boundary = float(point["rho"])
    return boundary, bool(ordered and not failed)


def has_nonmonotonic_recovery(points: Iterable[Mapping[str, object]]) -> bool:
    failed = False
    for point in sorted(points, key=lambda row: float(row["rho"])):
        if not bool(point["pass"]):
            failed = True
        elif failed:
            return True
    return False


def boundary_summaries(rows: Iterable[Mapping[str, object]], deadline: float, miss_limit: float = 0.01) -> list[dict[str, object]]:
    """Report median-rule boundary plus descriptive per-seed boundary range."""
    runs = list(rows)
    points = point_summaries(runs, deadline, miss_limit)
    by_pmr_points: dict[float, list[dict[str, object]]] = defaultdict(list)
    by_pmr_seed: dict[tuple[float, int], list[dict[str, object]]] = defaultdict(list)
    for point in points:
        by_pmr_points[float(point["pmr"])].append(point)
    for run in runs:
        p99_raw = run.get("p99")
        p99 = None if p99_raw in (None, "") else float(p99_raw)
        by_pmr_seed[(float(run["pmr"]), int(run["seed"]))].append({
            "rho": float(run["rho"]),
            "pass": p99 is not None and p99 < deadline and float(run["miss_ratio"]) < miss_limit,
        })
    out = []
    for pmr, point_rows in sorted(by_pmr_points.items()):
        boundary, censored = contiguous_boundary(point_rows)
        seed_rows_for_arm = [seed_rows for (seed_pmr, _), seed_rows in by_pmr_seed.items() if seed_pmr == pmr]
        seed_results = [contiguous_boundary(seed_rows) for seed_rows in seed_rows_for_arm]
        known = [value for value, _ in seed_results if value is not None]
        out.append({
            "pmr": pmr,
            "boundary": boundary,
            "lower_censored": boundary is None,
            "upper_censored": censored,
            "nonmonotonic_recovery": has_nonmonotonic_recovery(point_rows),
            "seed_boundary_min": min(known) if known else None,
            "seed_boundary_max": max(known) if known else None,
            "seed_no_safe_point": len(seed_results) - len(known),
            "seed_upper_censored": sum(censored for _, censored in seed_results),
            "seed_nonmonotonic_recovery": sum(has_nonmonotonic_recovery(rows)
                                                for rows in seed_rows_for_arm),
            "seeds": len(seed_results),
        })
    return out


def refinement_loads(points: Iterable[Mapping[str, object]], step: float = 0.01) -> list[float]:
    """Union of points between each PMR arm's first coarse pass/fail pair."""
    if step <= 0:
        raise ValueError("step must be positive")
    by_pmr: dict[float, list[Mapping[str, object]]] = defaultdict(list)
    for point in points:
        by_pmr[float(point["pmr"])].append(point)
    loads: set[float] = set()
    for arm in by_pmr.values():
        ordered = sorted(arm, key=lambda row: float(row["rho"]))
        for previous, current in zip(ordered, ordered[1:]):
            if bool(previous["pass"]) and not bool(current["pass"]):
                start = float(previous["rho"])
                end = float(current["rho"])
                n = int(round((end - start) / step))
                loads.update(round(start + index * step, 10) for index in range(1, n) if start + index * step < end - 1e-9)
                break
    return sorted(loads)
