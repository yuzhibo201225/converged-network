"""Merge two disjoint sweep summaries without changing either raw-data source.

The result is a *summary view* for factorial_analysis, not a new raw-auditable
sweep: control_packets.csv.gz is deliberately not copied. Audit each source
with ``python -m converged_sim audit`` before using this command.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def _read_source(directory: Path) -> tuple[dict[str, Any], list[str], list[dict[str, str]], set[float]]:
    manifest = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("simulation"), dict):
        raise ValueError(f"invalid simulation manifest: {directory}")
    sweep = manifest.get("sweep")
    if not isinstance(sweep, dict):
        raise ValueError(f"invalid sweep manifest: {directory}")
    try:
        loads = [float(value) for value in sweep["loads"]]
        pmrs = [float(value) for value in sweep["pmrs"]]
        seeds = [int(value) for value in sweep["seeds"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid sweep grid: {directory}") from exc
    if (not loads or not pmrs or not seeds or
            len(set(loads)) != len(loads) or len(set(pmrs)) != len(pmrs) or
            len(set(seeds)) != len(seeds) or
            any(not math.isfinite(value) or not 0 < value < 1 for value in loads) or
            any(not math.isfinite(value) or value < 1 for value in pmrs)):
        raise ValueError(f"invalid or duplicate sweep coordinates: {directory}")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in sweep["seeds"]):
        raise ValueError(f"seeds must be integers: {directory}")
    csv_path = directory / "runs.csv"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        if not columns or len(columns) != len(set(columns)) or not {"rho", "pmr", "seed"}.issubset(columns):
            raise ValueError(f"invalid runs.csv header: {directory}")
        rows = list(reader)
    expected = {(rho, pmr, seed) for rho in loads for pmr in pmrs for seed in seeds}
    actual: set[tuple[float, float, int]] = set()
    for row in rows:
        if None in row:
            raise ValueError(f"malformed CSV row: {directory}")
        try:
            key = float(row["rho"]), float(row["pmr"]), int(row["seed"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid run coordinate: {directory}") from exc
        if key in actual:
            raise ValueError(f"duplicate rho/pmr/seed run {key}: {directory}")
        actual.add(key)
    if actual != expected:
        missing = len(expected - actual)
        extra = len(actual - expected)
        raise ValueError(f"incomplete or extra sweep grid in {directory}: {missing} missing, {extra} extra")
    return manifest, columns, rows, set(loads)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def merge_sweeps(coarse: Path, refinement: Path, out: Path) -> dict[str, Any]:
    """Validate complete, disjoint grids and write one derived summary view."""
    coarse, refinement, out = coarse.resolve(), refinement.resolve(), out.resolve()
    if coarse == refinement or out == coarse or out == refinement:
        raise ValueError("source and output directories must be distinct")
    if out.is_relative_to(coarse) or out.is_relative_to(refinement):
        raise ValueError("output cannot be inside a source sweep directory")
    if out.exists():
        raise FileExistsError(f"output already exists: {out}")

    base, base_columns, base_rows, base_loads = _read_source(coarse)
    extra, extra_columns, extra_rows, extra_loads = _read_source(refinement)
    if base["simulation"] != extra["simulation"] or base.get("deadline") != extra.get("deadline"):
        raise ValueError("simulation settings or deadline differ between sweeps")
    base_grid = {key: value for key, value in base["sweep"].items() if key != "loads"}
    extra_grid = {key: value for key, value in extra["sweep"].items() if key != "loads"}
    if base_grid != extra_grid:
        raise ValueError("PMRs, seeds, refinement rule, or other sweep controls differ")
    if base_columns != extra_columns:
        raise ValueError("runs.csv columns differ between sweeps")
    if base_loads & extra_loads:
        raise ValueError(f"overlapping load points: {sorted(base_loads & extra_loads)}")

    rows = sorted(base_rows + extra_rows,
                  key=lambda row: (float(row["rho"]), float(row["pmr"]), int(row["seed"])))
    manifest = copy.deepcopy(base)
    manifest["sweep"]["loads"] = sorted(base_loads | extra_loads)
    provenance = {
        "kind": "derived_runs_summary_view",
        "raw_packet_data_copied": False,
        "raw_audit_note": "Audit each source sweep separately; this view has no control_packets.csv.gz.",
        "sources": {
            "coarse": {
                "path": str(coarse), "loads": sorted(base_loads), "runs": len(base_rows),
                "config_sha256": _sha256(coarse / "config.json"),
                "runs_sha256": _sha256(coarse / "runs.csv"),
            },
            "refinement": {
                "path": str(refinement), "loads": sorted(extra_loads), "runs": len(extra_rows),
                "config_sha256": _sha256(refinement / "config.json"),
                "runs_sha256": _sha256(refinement / "runs.csv"),
            },
        },
        "merged_loads": manifest["sweep"]["loads"],
        "merged_runs": len(rows),
    }
    out.mkdir(parents=True, exist_ok=False)
    (out / "config.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (out / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=base_columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge audited coarse and refinement run summaries")
    parser.add_argument("--coarse", type=Path, required=True)
    parser.add_argument("--refinement", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    provenance = merge_sweeps(args.coarse, args.refinement, args.out)
    print(json.dumps({"status": "PASS", "merged_loads": len(provenance["merged_loads"]),
                      "merged_runs": provenance["merged_runs"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
