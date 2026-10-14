"""Reliability-indexed SLO boundaries from paired run summaries.

The original analysis asks whether the median run-level P99 and miss ratio pass
at a load.  That is a typical-environment estimand.  This module instead treats
each independent seed/service trace as the inferential unit and estimates the
probability that a run jointly satisfies both SLOs.

For a requested reliability target q, the empirical boundary is the highest
load in the contiguous prefix whose joint pass fraction is at least q.  Two
conservative variants replace the empirical fraction with a one-sided exact
Clopper--Pearson lower confidence bound: pointwise, and Bonferroni-simultaneous
over every load in that PMR/regime arm.  No interpolation is performed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping


REGIMES = ("constant", "moderate", "strong")
POINT_COLUMNS = (
    "regime", "pmr", "rho", "successes", "trials", "pass_fraction",
    "pointwise_lower_95", "simultaneous_lower_95", "deadline",
    "miss_threshold",
)
BOUNDARY_COLUMNS = (
    "regime", "pmr", "reliability_target", "estimator", "boundary_rho",
    "censoring", "first_failing_rho", "recovery_after_failure",
    "successes_at_boundary", "trials_at_boundary", "value_at_boundary",
    "familywise_alpha", "loads_in_arm",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _binomial_upper_tail(successes: int, trials: int, probability: float) -> float:
    """Return P[X >= successes] for X ~ Binomial(trials, probability)."""

    if successes <= 0:
        return 1.0
    if successes > trials:
        return 0.0
    return math.fsum(
        math.comb(trials, observed)
        * probability ** observed
        * (1.0 - probability) ** (trials - observed)
        for observed in range(successes, trials + 1)
    )


def clopper_pearson_lower(successes: int, trials: int, alpha: float = 0.05) -> float:
    """One-sided exact lower confidence bound for a binomial proportion.

    The returned value solves ``P_p[X >= successes] = alpha``.  In particular,
    when every trial succeeds it is exactly ``alpha ** (1 / trials)``.
    """

    if isinstance(successes, bool) or isinstance(trials, bool):
        raise ValueError("success and trial counts must be integers")
    if not isinstance(successes, int) or not isinstance(trials, int):
        raise ValueError("success and trial counts must be integers")
    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError("require 0 <= successes <= trials and trials > 0")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie strictly between zero and one")
    if successes == 0:
        return 0.0
    low, high = 0.0, 1.0
    for _ in range(80):
        midpoint = (low + high) / 2.0
        if _binomial_upper_tail(successes, trials, midpoint) < alpha:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


def _read_manifest(directory: Path) -> tuple[dict[str, object], list[dict[str, str]]]:
    config_path = directory / "config.json"
    runs_path = directory / "runs.csv"
    manifest = json.loads(config_path.read_text(encoding="utf-8"))
    with runs_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty runs file: {runs_path}")
    return manifest, rows


def _joint_pass(row: Mapping[str, str], deadline: float, miss_threshold: float) -> bool:
    p99 = row.get("p99", "")
    miss = row.get("miss_ratio", "")
    return bool(p99) and float(p99) < deadline and float(miss) < miss_threshold


def arm_points(
    rows: Iterable[Mapping[str, str]], *, regime: str, deadline: float,
    miss_threshold: float, alpha: float,
) -> list[dict[str, object]]:
    """Aggregate independent run-level joint SLO outcomes by PMR and load."""

    grouped: dict[tuple[float, float], list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(float(row["pmr"]), float(row["rho"]))].append(row)
    loads_per_pmr: dict[float, int] = defaultdict(int)
    for pmr, _ in grouped:
        loads_per_pmr[pmr] += 1

    points: list[dict[str, object]] = []
    for (pmr, rho), cohort in sorted(grouped.items()):
        seeds = [int(row["seed"]) for row in cohort]
        if len(seeds) != len(set(seeds)):
            raise ValueError(f"duplicate seed in {regime}, PMR={pmr}, rho={rho}")
        trials = len(cohort)
        successes = sum(_joint_pass(row, deadline, miss_threshold) for row in cohort)
        family_alpha = alpha / loads_per_pmr[pmr]
        points.append({
            "regime": regime,
            "pmr": pmr,
            "rho": rho,
            "successes": successes,
            "trials": trials,
            "pass_fraction": successes / trials,
            "pointwise_lower_95": clopper_pearson_lower(successes, trials, alpha),
            "simultaneous_lower_95": clopper_pearson_lower(
                successes, trials, family_alpha
            ),
            "deadline": deadline,
            "miss_threshold": miss_threshold,
        })
    return points


def contiguous_boundary(
    points: list[Mapping[str, object]], value_field: str, target: float,
) -> dict[str, object]:
    """Return a no-interpolation boundary from a low-load contiguous prefix."""

    if not points:
        raise ValueError("cannot calculate a boundary from no points")
    ordered = sorted(points, key=lambda point: float(point["rho"]))
    passes = [float(point[value_field]) >= target for point in ordered]
    first_failure = next((index for index, passed in enumerate(passes) if not passed), None)
    recovery = False
    if first_failure is None:
        boundary_point = ordered[-1]
        censoring = "right"
        first_failing_rho: float | None = None
    elif first_failure == 0:
        boundary_point = None
        censoring = "left"
        first_failing_rho = float(ordered[0]["rho"])
        recovery = any(passes[1:])
    else:
        boundary_point = ordered[first_failure - 1]
        censoring = "none"
        first_failing_rho = float(ordered[first_failure]["rho"])
        recovery = any(passes[first_failure + 1 :])
    return {
        "boundary_rho": None if boundary_point is None else float(boundary_point["rho"]),
        "censoring": censoring,
        "first_failing_rho": first_failing_rho,
        "recovery_after_failure": recovery,
        "successes_at_boundary": None if boundary_point is None else int(boundary_point["successes"]),
        "trials_at_boundary": None if boundary_point is None else int(boundary_point["trials"]),
        "value_at_boundary": None if boundary_point is None else float(boundary_point[value_field]),
    }


def boundaries(
    points: list[Mapping[str, object]], targets: Iterable[float], alpha: float,
) -> list[dict[str, object]]:
    """Calculate empirical and confidence-qualified reliability boundaries."""

    grouped: dict[tuple[str, float], list[Mapping[str, object]]] = defaultdict(list)
    for point in points:
        grouped[(str(point["regime"]), float(point["pmr"]))].append(point)
    estimators = (
        ("empirical", "pass_fraction"),
        ("pointwise_lcb", "pointwise_lower_95"),
        ("simultaneous_lcb", "simultaneous_lower_95"),
    )
    output: list[dict[str, object]] = []
    for (regime, pmr), arm in sorted(grouped.items()):
        family_size = len(arm)
        for target in targets:
            for estimator, field in estimators:
                output.append({
                    "regime": regime,
                    "pmr": pmr,
                    "reliability_target": target,
                    "estimator": estimator,
                    **contiguous_boundary(arm, field, target),
                    "familywise_alpha": alpha,
                    "loads_in_arm": family_size,
                })
    return output


def _write_csv(path: Path, columns: tuple[str, ...], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def analyze(
    inputs: Mapping[str, Path], output_dir: Path, targets: list[float],
    alpha: float = 0.05, miss_threshold: float = 0.01,
) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    if not targets or any(not 0.0 < target <= 1.0 for target in targets):
        raise ValueError("reliability targets must lie in (0, 1]")
    all_points: list[dict[str, object]] = []
    receipts: dict[str, object] = {}
    reference_grid: tuple[list[float], list[float], list[int]] | None = None
    for regime in REGIMES:
        directory = inputs[regime]
        manifest, rows = _read_manifest(directory)
        sweep = manifest["sweep"]
        assert isinstance(sweep, dict)
        grid = (
            [float(value) for value in sweep["loads"]],
            [float(value) for value in sweep["pmrs"]],
            [int(value) for value in sweep["seeds"]],
        )
        if reference_grid is None:
            reference_grid = grid
        elif grid != reference_grid:
            raise ValueError("regimes do not share an identical load/PMR/seed grid")
        deadline = float(manifest["deadline"])
        all_points.extend(arm_points(
            rows, regime=regime, deadline=deadline,
            miss_threshold=miss_threshold, alpha=alpha,
        ))
        receipts[regime] = {
            "directory": str(directory.resolve()),
            "config_sha256": _sha256(directory / "config.json"),
            "runs_sha256": _sha256(directory / "runs.csv"),
            "rows": len(rows),
            "deadline": deadline,
        }

    boundary_rows = boundaries(all_points, targets, alpha)
    output_dir.mkdir(parents=True)
    _write_csv(output_dir / "reliability_points.csv", POINT_COLUMNS, all_points)
    _write_csv(output_dir / "reliability_boundaries.csv", BOUNDARY_COLUMNS, boundary_rows)
    audit = {
        "status": "PASS",
        "definition": {
            "run_pass": "p99 < deadline AND miss_ratio < miss_threshold",
            "boundary": "highest load in the contiguous passing prefix; no interpolation",
            "empirical": "joint run-pass fraction >= q",
            "pointwise_lcb": "one-sided exact Clopper-Pearson lower bound >= q",
            "simultaneous_lcb": (
                "one-sided exact lower bound with Bonferroni alpha/loads within each "
                "regime-by-PMR arm >= q"
            ),
            "alpha": alpha,
            "miss_threshold": miss_threshold,
            "targets": targets,
        },
        "inputs": receipts,
        "point_rows": len(all_points),
        "boundary_rows": len(boundary_rows),
    }
    (output_dir / "reliability_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for regime in REGIMES:
        parser.add_argument(f"--{regime}", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--q", type=float, nargs="+", default=[0.5, 0.9, 0.95])
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--miss-threshold", type=float, default=0.01)
    args = parser.parse_args(argv)
    result = analyze(
        {regime: getattr(args, regime) for regime in REGIMES},
        args.out,
        sorted(set(args.q)),
        alpha=args.alpha,
        miss_threshold=args.miss_threshold,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
