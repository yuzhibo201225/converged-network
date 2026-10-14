import csv
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from converged_sim.analysis import (
    boundary_summaries, point_summaries, refinement_loads, validate_run_design,
)
from converged_sim.cli import (
    audit, plot, runs_from_raw, runs_from_raw_deadlines, sensitivity, sweep,
)


class AnalysisTests(unittest.TestCase):
    def test_pairing_rejects_missing_or_duplicate_seed(self):
        rows = [
            {"rho": 0.2, "pmr": 1, "seed": 0},
            {"rho": 0.2, "pmr": 2, "seed": 1},
        ]
        with self.assertRaisesRegex(ValueError, "incomplete seed pairing"):
            validate_run_design(rows)
        with self.assertRaisesRegex(ValueError, "duplicate run"):
            validate_run_design(rows[:1] * 2)

    def test_boundary_censor_and_nonmonotonic_recovery(self):
        rows = []
        for seed in (0, 1):
            for rho, p99 in ((0.2, 0.5), (0.3, 1.2), (0.4, 0.8)):
                rows.append({"rho": rho, "pmr": 1, "seed": seed,
                             "p99": p99, "miss_ratio": 0})
        boundary = boundary_summaries(rows, 1)[0]
        self.assertEqual(boundary["boundary"], 0.2)
        self.assertTrue(boundary["nonmonotonic_recovery"])
        self.assertFalse(boundary["lower_censored"])
        self.assertFalse(boundary["upper_censored"])
        self.assertEqual(refinement_loads(point_summaries(rows, 1), 0.05), [0.25])

    def test_sweep_and_plot_regenerate_from_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = {
                "simulation": {"warmup_control_packets": 6, "measured_control_packets": 12},
                "sweep": {"loads": [0.2], "pmrs": [1, 1.5, 2, 3],
                          "seeds": [0, 1], "refine_step": 0.01},
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            first, second = root / "first", root / "second"
            sweep(config_path, first)
            sweep(config_path, second)
            self.assertEqual((first / "control_packets.csv.gz").read_bytes(),
                             (second / "control_packets.csv.gz").read_bytes())
            self.assertEqual((first / "runs.csv").read_bytes(), (second / "runs.csv").read_bytes())
            raw_runs = runs_from_raw(first / "control_packets.csv.gz", 1.0)
            deadline_views = runs_from_raw_deadlines(
                first / "control_packets.csv.gz", [0.5, 1.0, 2.0], 12,
                recorded_deadline=1.0,
            )
            self.assertEqual(deadline_views[1.0], raw_runs)
            self.assertEqual(set(deadline_views), {0.5, 1.0, 2.0})
            with (first / "runs.csv").open(newline="", encoding="utf-8") as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(raw_runs), len(saved))
            saved_by_key = {(float(row["rho"]), float(row["pmr"]), int(row["seed"])): row
                            for row in saved}
            for raw in raw_runs:
                stored = saved_by_key[(raw["rho"], raw["pmr"], raw["seed"])]
                self.assertEqual(raw["generated"], int(stored["generated"]))
                self.assertAlmostEqual(raw["miss_ratio"], float(stored["miss_ratio"]))
                self.assertAlmostEqual(raw["p99"], float(stored["p99"]))
            svg = root / "figure.svg"
            plot(first, svg)
            first_bytes = svg.read_bytes()
            plot(first, svg)
            self.assertEqual(first_bytes, svg.read_bytes())
            self.assertEqual(audit(first)["status"], "PASS")
            sensitivity(first, root / "deadline_sensitivity.csv")
            with (root / "deadline_sensitivity.csv").open(newline="", encoding="utf-8") as handle:
                self.assertEqual({float(row["deadline_periods"]) for row in csv.DictReader(handle)},
                                 {0.5, 1.0, 2.0})
            self.assertIn(b"P99 latency / control period", first_bytes)
            with gzip.open(first / "control_packets.csv.gz", "rt", encoding="utf-8") as handle:
                self.assertEqual(sum(1 for _ in handle) - 1, 8 * 12)
            with (first / "runs.csv").open(newline="", encoding="utf-8") as handle:
                corrupted = list(csv.DictReader(handle))
            corrupted[0]["miss_count"] = "999"
            with (first / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(corrupted[0]))
                writer.writeheader()
                writer.writerows(corrupted)
            with self.assertRaisesRegex(ValueError, "raw/saved miss_count mismatch"):
                audit(first)

    def test_multi_deadline_reader_rejects_invalid_deadlines(self):
        with self.assertRaisesRegex(ValueError, "nonempty unique"):
            runs_from_raw_deadlines(Path("unused"), [])
        with self.assertRaisesRegex(ValueError, "nonempty unique"):
            runs_from_raw_deadlines(Path("unused"), [1.0, 1.0])
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            runs_from_raw_deadlines(Path("unused"), [0.0])


if __name__ == "__main__":
    unittest.main()
