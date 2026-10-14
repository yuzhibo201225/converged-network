import csv
import json
from pathlib import Path
import tempfile
import unittest

from converged_sim.merge_sweeps import main, merge_sweeps


PMRS = [1.0, 1.5]
SEEDS = [0, 1]
COLUMNS = ["rho", "pmr", "seed", "trace_pattern_digest", "p99"]


def make_sweep(path: Path, loads: list[float]) -> None:
    path.mkdir()
    manifest = {
        "simulation": {"control_period": 1.0, "trace_normalize_mean": True},
        "sweep": {"loads": loads, "pmrs": PMRS, "seeds": SEEDS, "refine_step": 0.1},
        "deadline": 1.0,
    }
    (path / "config.json").write_text(json.dumps(manifest), encoding="utf-8")
    with (path / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for rho in loads:
            for pmr in PMRS:
                for seed in SEEDS:
                    writer.writerow({"rho": rho, "pmr": pmr, "seed": seed,
                                     "trace_pattern_digest": f"seed-{seed}", "p99": 0.5})


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class MergeSweepsTests(unittest.TestCase):
    def test_merge_writes_summary_view_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coarse, refinement, out = root / "coarse", root / "refinement", root / "merged"
            make_sweep(coarse, [0.2, 0.4])
            make_sweep(refinement, [0.31, 0.32])
            before = [(path / name).read_bytes() for path in (coarse, refinement)
                      for name in ("config.json", "runs.csv")]
            self.assertEqual(main(["--coarse", str(coarse), "--refinement", str(refinement),
                                   "--out", str(out)]), 0)
            self.assertEqual(len(read_rows(out / "runs.csv")), 16)
            self.assertEqual(json.loads((out / "config.json").read_text())["sweep"]["loads"],
                             [0.2, 0.31, 0.32, 0.4])
            provenance = json.loads((out / "provenance.json").read_text())
            self.assertEqual(provenance["merged_runs"], 16)
            self.assertFalse(provenance["raw_packet_data_copied"])
            self.assertFalse((out / "control_packets.csv.gz").exists())
            after = [(path / name).read_bytes() for path in (coarse, refinement)
                     for name in ("config.json", "runs.csv")]
            self.assertEqual(before, after)

    def test_rejects_overlap_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coarse, refinement, out = root / "coarse", root / "refinement", root / "merged"
            make_sweep(coarse, [0.2, 0.4])
            make_sweep(refinement, [0.4, 0.6])
            with self.assertRaisesRegex(ValueError, "overlapping load"):
                merge_sweeps(coarse, refinement, out)
            self.assertFalse(out.exists())

    def test_rejects_changed_controls_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coarse, refinement, out = root / "coarse", root / "refinement", root / "merged"
            make_sweep(coarse, [0.2])
            make_sweep(refinement, [0.3])
            manifest_path = refinement / "config.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["simulation"]["control_period"] = 2.0
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "simulation settings"):
                merge_sweeps(coarse, refinement, out)
            self.assertFalse(out.exists())
            manifest["simulation"]["control_period"] = 1.0
            manifest_path.write_text(json.dumps(manifest))
            out.mkdir()
            with self.assertRaises(FileExistsError):
                merge_sweeps(coarse, refinement, out)

    def test_rejects_incomplete_and_duplicate_run_grid(self):
        for bad_kind in ("incomplete", "duplicate"):
            with self.subTest(bad_kind=bad_kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                coarse, refinement, out = root / "coarse", root / "refinement", root / "merged"
                make_sweep(coarse, [0.2])
                make_sweep(refinement, [0.3])
                rows = read_rows(refinement / "runs.csv")
                if bad_kind == "incomplete":
                    rows.pop()
                else:
                    rows.append(dict(rows[-1]))
                write_rows(refinement / "runs.csv", rows)
                with self.assertRaisesRegex(ValueError, "incomplete|duplicate"):
                    merge_sweeps(coarse, refinement, out)
                self.assertFalse(out.exists())

    def test_rejects_output_within_a_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coarse, refinement = root / "coarse", root / "refinement"
            make_sweep(coarse, [0.2])
            make_sweep(refinement, [0.3])
            with self.assertRaisesRegex(ValueError, "inside a source"):
                merge_sweeps(coarse, refinement, coarse / "derived")


if __name__ == "__main__":
    unittest.main()
