"""Paired whole-curve bootstrap for the factorial tail-latency experiment.

One bootstrap unit is a seed's complete factorial curve: every load, PMR arm,
and service-variability regime is selected together.  Boundaries are recomputed
on the observed load grid in every resample.  Censored replicates are counted
explicitly and are never converted to artificial numeric thresholds.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .analysis import contiguous_boundary, has_nonmonotonic_recovery
from .factorial_analysis import REGIMES, _check_regimes, _load_regime


REPLICATE_COLUMNS = (
    "replicate", "draw_digest", "regime", "pmr", "boundary", "censoring",
    "nonmonotonic_recovery", "erosion_vs_pmr1", "interaction_vs_constant",
)
DRAW_COLUMNS = ("replicate", "slot", "seed")
SUMMARY_COLUMNS = (
    "regime", "pmr", "observed_boundary", "observed_censoring",
    "observed_nonmonotonic_recovery", "replicates",
    "boundary_uncensored_count", "boundary_lower_censored_count",
    "boundary_upper_censored_count", "boundary_nonmonotonic_count",
    "boundary_uncensored_frequency", "boundary_lower_censored_frequency",
    "boundary_upper_censored_frequency", "boundary_nonmonotonic_frequency",
    "boundary_interval_low_conditional_uncensored",
    "boundary_interval_high_conditional_uncensored",
    "observed_erosion_vs_pmr1", "erosion_estimable_count",
    "erosion_estimable_frequency", "erosion_interval_low_conditional_estimable",
    "erosion_interval_high_conditional_estimable",
    "observed_interaction_vs_constant", "interaction_estimable_count",
    "interaction_estimable_frequency",
    "interaction_interval_low_conditional_estimable",
    "interaction_interval_high_conditional_estimable",
)


def _p99(row: Mapping[str, object]) -> float | None:
    raw = row.get("p99")
    if raw in (None, ""):
        return None
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid P99 in run row")
    return value


def _censoring(boundary: float | None, upper_censored: bool) -> str:
    if boundary is None:
        return "lower"
    if upper_censored:
        return "upper"
    return "none"


def _grid_interval(values: Iterable[float], confidence: float) -> tuple[float | None, float | None]:
    """Return nearest-rank endpoints selected from observed grid values.

    This intentionally performs no linear interpolation between load-grid
    thresholds.  The interval is conditional on the caller's estimable subset.
    """
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None, None
    if not 0 < confidence < 1:
        raise ValueError("confidence must lie strictly between zero and one")
    tail = (1.0 - confidence) / 2.0

    def nearest_rank(probability: float) -> float:
        rank = max(1, math.ceil(probability * len(ordered)))
        return ordered[min(rank - 1, len(ordered) - 1)]

    return nearest_rank(tail), nearest_rank(1.0 - tail)


def _index_rows(rows: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[
    dict[str, dict[int, dict[tuple[float, float], Mapping[str, object]]]],
    list[float], list[float], list[int],
]:
    index: dict[str, dict[int, dict[tuple[float, float], Mapping[str, object]]]] = {}
    keys_by_regime: dict[str, set[tuple[float, float, int]]] = {}
    for regime in REGIMES:
        regime_index: dict[int, dict[tuple[float, float], Mapping[str, object]]] = defaultdict(dict)
        keys: set[tuple[float, float, int]] = set()
        for row in rows[regime]:
            rho, pmr, seed = float(row["rho"]), float(row["pmr"]), int(row["seed"])
            key = (rho, pmr, seed)
            if key in keys:
                raise ValueError(f"duplicate run in {regime}: {key}")
            keys.add(key)
            regime_index[seed][(rho, pmr)] = row
        index[regime] = dict(regime_index)
        keys_by_regime[regime] = keys
    reference = keys_by_regime[REGIMES[0]]
    if any(keys_by_regime[regime] != reference for regime in REGIMES[1:]):
        raise ValueError("regimes do not share a complete load/PMR/seed grid")
    loads = sorted({key[0] for key in reference})
    pmrs = sorted({key[1] for key in reference})
    seeds = sorted({key[2] for key in reference})
    expected = {(rho, pmr, seed) for rho in loads for pmr in pmrs for seed in seeds}
    if reference != expected:
        raise ValueError("factorial grid is incomplete")
    if 1.0 not in pmrs:
        raise ValueError("PMR=1 reference arm is required")
    return index, loads, pmrs, seeds


def _evaluate_draw(
    index: Mapping[str, Mapping[int, Mapping[tuple[float, float], Mapping[str, object]]]],
    loads: Sequence[float], pmrs: Sequence[float], drawn_seeds: Sequence[int],
    deadline: float, miss_limit: float,
) -> dict[tuple[str, float], dict[str, object]]:
    """Recompute every factorial boundary for one paired seed resample."""
    outcomes: dict[tuple[str, float], dict[str, object]] = {}
    for regime in REGIMES:
        for pmr in pmrs:
            points: list[dict[str, object]] = []
            for rho in loads:
                selected = [index[regime][seed][(rho, pmr)] for seed in drawn_seeds]
                p99s = [_p99(row) for row in selected]
                median_p99 = None if any(value is None for value in p99s) else median(
                    value for value in p99s if value is not None
                )
                median_miss = median(float(row["miss_ratio"]) for row in selected)
                points.append({
                    "rho": rho,
                    "pass": median_p99 is not None and median_p99 < deadline and median_miss < miss_limit,
                })
            boundary, upper_censored = contiguous_boundary(points)
            outcomes[(regime, pmr)] = {
                "boundary": boundary,
                "censoring": _censoring(boundary, upper_censored),
                "nonmonotonic_recovery": has_nonmonotonic_recovery(points),
            }

    constant_reference = outcomes[("constant", 1.0)]
    for regime in REGIMES:
        reference = outcomes[(regime, 1.0)]
        for pmr in pmrs:
            arm = outcomes[(regime, pmr)]
            constant_arm = outcomes[("constant", pmr)]
            arm["erosion_vs_pmr1"] = _contrast(reference, arm)
            constant_erosion = _contrast(constant_reference, constant_arm)
            erosion = arm["erosion_vs_pmr1"]
            arm["interaction_vs_constant"] = (
                None if erosion is None or constant_erosion is None
                else round(float(erosion) - float(constant_erosion), 10)
            )
    return outcomes


def _contrast(reference: Mapping[str, object], arm: Mapping[str, object]) -> float | None:
    """Return reference-minus-arm only when both grid boundaries are uncensored."""
    if reference["censoring"] != "none" or arm["censoring"] != "none":
        return None
    return round(float(reference["boundary"]) - float(arm["boundary"]), 10)


def _draw_digest(seeds: Sequence[int]) -> str:
    payload = ",".join(str(seed) for seed in seeds).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _replicate_rows(
    index: Mapping[str, Mapping[int, Mapping[tuple[float, float], Mapping[str, object]]]],
    loads: Sequence[float], pmrs: Sequence[float], seeds: Sequence[int], deadline: float,
    miss_limit: float, replicates: int, bootstrap_seed: int,
) -> tuple[list[dict[str, object]], list[dict[str, int]]]:
    if replicates <= 0:
        raise ValueError("replicates must be positive")
    rng = random.Random(bootstrap_seed)
    replicate_rows: list[dict[str, object]] = []
    draw_rows: list[dict[str, int]] = []
    for replicate in range(replicates):
        draw = [rng.choice(seeds) for _ in seeds]
        digest = _draw_digest(draw)
        draw_rows.extend({"replicate": replicate, "slot": slot, "seed": seed}
                         for slot, seed in enumerate(draw))
        outcomes = _evaluate_draw(index, loads, pmrs, draw, deadline, miss_limit)
        for regime in REGIMES:
            for pmr in pmrs:
                replicate_rows.append({
                    "replicate": replicate,
                    "draw_digest": digest,
                    "regime": regime,
                    "pmr": pmr,
                    **outcomes[(regime, pmr)],
                })
    return replicate_rows, draw_rows


def _summaries(
    observed: Mapping[tuple[str, float], Mapping[str, object]],
    replicate_rows: Sequence[Mapping[str, object]], pmrs: Sequence[float],
    replicates: int, confidence: float,
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, float], list[Mapping[str, object]]] = defaultdict(list)
    for row in replicate_rows:
        grouped[(str(row["regime"]), float(row["pmr"]))].append(row)
    out: list[dict[str, object]] = []
    for regime in REGIMES:
        for pmr in pmrs:
            rows = grouped[(regime, pmr)]
            if len(rows) != replicates:
                raise ValueError("internal error: incomplete bootstrap output")
            censor_counts = {name: sum(row["censoring"] == name for row in rows)
                             for name in ("none", "lower", "upper")}
            boundary_values = [float(row["boundary"]) for row in rows if row["censoring"] == "none"]
            erosion_values = [float(row["erosion_vs_pmr1"]) for row in rows
                              if row["erosion_vs_pmr1"] is not None]
            interaction_values = [float(row["interaction_vs_constant"]) for row in rows
                                  if row["interaction_vs_constant"] is not None]
            boundary_low, boundary_high = _grid_interval(boundary_values, confidence)
            erosion_low, erosion_high = _grid_interval(erosion_values, confidence)
            interaction_low, interaction_high = _grid_interval(interaction_values, confidence)
            source = observed[(regime, pmr)]
            nonmonotonic = sum(bool(row["nonmonotonic_recovery"]) for row in rows)
            out.append({
                "regime": regime,
                "pmr": pmr,
                "observed_boundary": source["boundary"],
                "observed_censoring": source["censoring"],
                "observed_nonmonotonic_recovery": source["nonmonotonic_recovery"],
                "replicates": replicates,
                "boundary_uncensored_count": censor_counts["none"],
                "boundary_lower_censored_count": censor_counts["lower"],
                "boundary_upper_censored_count": censor_counts["upper"],
                "boundary_nonmonotonic_count": nonmonotonic,
                "boundary_uncensored_frequency": censor_counts["none"] / replicates,
                "boundary_lower_censored_frequency": censor_counts["lower"] / replicates,
                "boundary_upper_censored_frequency": censor_counts["upper"] / replicates,
                "boundary_nonmonotonic_frequency": nonmonotonic / replicates,
                "boundary_interval_low_conditional_uncensored": boundary_low,
                "boundary_interval_high_conditional_uncensored": boundary_high,
                "observed_erosion_vs_pmr1": source["erosion_vs_pmr1"],
                "erosion_estimable_count": len(erosion_values),
                "erosion_estimable_frequency": len(erosion_values) / replicates,
                "erosion_interval_low_conditional_estimable": erosion_low,
                "erosion_interval_high_conditional_estimable": erosion_high,
                "observed_interaction_vs_constant": source["interaction_vs_constant"],
                "interaction_estimable_count": len(interaction_values),
                "interaction_estimable_frequency": len(interaction_values) / replicates,
                "interaction_interval_low_conditional_estimable": interaction_low,
                "interaction_interval_high_conditional_estimable": interaction_high,
            })
    return out


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze(
    constant: Path, moderate: Path, strong: Path, out: Path, *,
    replicates: int, bootstrap_seed: int, confidence: float = 0.95,
    miss_limit: float = 0.01,
) -> dict[str, Any]:
    """Validate the factorial data, bootstrap paired curves, and write results."""
    if not 0 < confidence < 1:
        raise ValueError("confidence must lie strictly between zero and one")
    if not 0 <= miss_limit <= 1:
        raise ValueError("miss_limit must lie between zero and one")
    paths = {"constant": constant, "moderate": moderate, "strong": strong}
    if len({path.resolve() for path in paths.values()}) != len(REGIMES):
        raise ValueError("regime input directories must be distinct")
    manifests: dict[str, dict[str, Any]] = {}
    rows: dict[str, list[dict[str, str]]] = {}
    for regime, path in paths.items():
        manifests[regime], rows[regime] = _load_regime(path)
    pairing = _check_regimes(manifests, rows)
    index, loads, pmrs, seeds = _index_rows(rows)
    deadline = float(manifests["constant"]["deadline"])
    observed = _evaluate_draw(index, loads, pmrs, seeds, deadline, miss_limit)
    replicate_rows, draw_rows = _replicate_rows(
        index, loads, pmrs, seeds, deadline, miss_limit, replicates, bootstrap_seed,
    )
    summaries = _summaries(observed, replicate_rows, pmrs, replicates, confidence)
    audit: dict[str, Any] = {
        "status": "PASS",
        "method": "paired nonparametric bootstrap over complete seed-level factorial curves",
        "bootstrap_seed": bootstrap_seed,
        "replicates": replicates,
        "confidence": confidence,
        "deadline": deadline,
        "miss_limit": miss_limit,
        "sampling_unit": "one seed across every load, PMR, and service-rate regime",
        "boundary_rule": "highest scanned load in the contiguous passing prefix; median P99 < deadline and median miss ratio < miss_limit",
        "interval_rule": "nearest-rank percentile endpoints among uncensored/estimable replicates; endpoints are observed grid values or their exact grid contrasts; no interpolation",
        "censoring_rule": "lower=no safe scanned load; upper=all scanned loads pass; censored replicates are excluded from conditional intervals and reported by frequency",
        "scope": "synthetic finite-FIFO factorial experiment; bootstrap uncertainty reflects the sampled seeds, not physical-link population validity",
        "inputs": {regime: str(path.resolve()) for regime, path in paths.items()},
        "pairing": pairing,
        "loads": loads,
        "pmrs": pmrs,
        "seeds": seeds,
        "summary_rows": summaries,
    }
    out.mkdir(parents=True, exist_ok=False)
    _write_csv(out / "bootstrap_draws.csv", DRAW_COLUMNS, draw_rows)
    _write_csv(out / "bootstrap_replicates.csv", REPLICATE_COLUMNS, replicate_rows)
    _write_csv(out / "bootstrap_summary.csv", SUMMARY_COLUMNS, summaries)
    (out / "bootstrap_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paired whole-curve bootstrap for the three-regime factorial study"
    )
    parser.add_argument("--constant", type=Path, required=True)
    parser.add_argument("--moderate", type=Path, required=True)
    parser.add_argument("--strong", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=5000)
    parser.add_argument("--bootstrap-seed", type=int, required=True)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--miss-limit", type=float, default=0.01)
    args = parser.parse_args(argv)
    audit = analyze(
        args.constant, args.moderate, args.strong, args.out,
        replicates=args.replicates, bootstrap_seed=args.bootstrap_seed,
        confidence=args.confidence, miss_limit=args.miss_limit,
    )
    print(json.dumps({
        "status": audit["status"], "replicates": audit["replicates"],
        "bootstrap_seed": audit["bootstrap_seed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
