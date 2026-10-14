"""Record reproducible raw-audit receipts for the six factorial source sweeps.

Inputs are read-only.  The sole output is a new JSON file inside
``results/factorial_refined_analysis``; merged summary views are not treated as
raw-auditable sweeps.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .cli import audit


REGIMES = ("constant", "moderate", "strong")
STAGES = (("coarse", "factorial_coarse"), ("refinement", "factorial_refinement"))
SOURCE_FILES = ("config.json", "runs.csv", "control_packets.csv.gz")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(directory: Path) -> dict[str, str]:
    return {name: _sha256(directory / name) for name in SOURCE_FILES}


def _check_merged_provenance(
    results_root: Path, regime: str, stage: str, source: Path, hashes: dict[str, str]
) -> None:
    provenance_path = results_root / "factorial_merged" / regime / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    entry = provenance["sources"][stage]
    if Path(entry["path"]).resolve() != source:
        raise ValueError(f"merged provenance source path mismatch: {regime}/{stage}")
    if entry["config_sha256"] != hashes["config.json"]:
        raise ValueError(f"merged provenance config hash mismatch: {regime}/{stage}")
    if entry["runs_sha256"] != hashes["runs.csv"]:
        raise ValueError(f"merged provenance runs hash mismatch: {regime}/{stage}")


def generate(results_root: Path, output: Path | None = None) -> dict[str, Any]:
    """Audit sources, verify summary provenance, then write one new receipt."""
    root = results_root.resolve()
    allowed_dir = root / "factorial_refined_analysis"
    out = output.resolve() if output else allowed_dir / "source_audit_receipts.json"
    if out.parent != allowed_dir:
        raise ValueError("output must be directly inside factorial_refined_analysis")
    if not allowed_dir.is_dir():
        raise FileNotFoundError(f"analysis directory does not exist: {allowed_dir}")
    if out.exists():
        raise FileExistsError(f"receipt already exists: {out}")

    receipts: list[dict[str, Any]] = []
    for regime in REGIMES:
        for stage, folder in STAGES:
            source = (root / folder / regime).resolve()
            before = _source_hashes(source)
            result = audit(source)
            if result.get("status") != "PASS":
                raise ValueError(f"raw audit did not pass: {regime}/{stage}")
            after = _source_hashes(source)
            if before != after:
                raise ValueError(f"source changed during raw audit: {regime}/{stage}")
            _check_merged_provenance(root, regime, stage, source, after)
            receipt = {
                "regime": regime,
                "stage": stage,
                "source": str(source),
                "raw_audit": result,
                "sha256": after,
                "merged_provenance_match": True,
            }
            receipts.append(receipt)
            print(f"PASS {regime}/{stage}: {result['runs']} runs, {result['control_packets']} control packets", flush=True)

    manifest: dict[str, Any] = {
        "kind": "factorial_source_raw_audit_receipts_v1",
        "status": "PASS",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "audit_scope": "six immutable source sweeps; derived merged views not raw-audited",
        "sources": receipts,
        "totals": {
            "source_sweeps": len(receipts),
            "runs": sum(item["raw_audit"]["runs"] for item in receipts),
            "control_packets": sum(item["raw_audit"]["control_packets"] for item in receipts),
        },
    }
    with out.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="new JSON file under factorial_refined_analysis")
    args = parser.parse_args(argv)
    manifest = generate(args.results_root, args.out)
    print(json.dumps({"status": manifest["status"], "totals": manifest["totals"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
