import csv
import json
from pathlib import Path
import tempfile
import unittest

from converged_sim.factorial_analysis import analyze, main


LOADS = (0.2, 0.4, 0.6, 0.8)
PMRS = (1.0, 2.0)
SEEDS = (0, 1)
RATES = {"constant": (1.0, 1.0), "moderate": (0.85, 1.15), "strong": (0.7, 1.3)}
LAST_PASS = {
    "constant": {1.0: 0.8, 2.0: 0.4},
    "moderate": {1.0: 0.6, 2.0: 0.2},
    "strong": {1.0: 0.4, 2.0: 0.2},
}


def fixture(root: Path) -> dict[str, Path]:
    paths = {}
    for regime, (low, high) in RATES.items():
        path = root / regime
        path.mkdir()
        paths[regime] = path
        manifest = {
            "simulation": {
                "control_period": 1.0, "measured_control_packets": 1000,
                "trace_low_rate": low, "trace_high_rate": high,
                "trace_normalize_mean": True,
            },
            "sweep": {"loads": list(LOADS), "pmrs": list(PMRS),
                      "seeds": list(SEEDS), "refine_step": 0.1},
            "deadline": 1.0,
        }
        (path / "config.json").write_text(json.dumps(manifest), encoding="utf-8")
        rows = []
        for rho in LOADS:
            for pmr in PMRS:
                for seed in SEEDS:
                    passed = rho <= LAST_PASS[regime][pmr]
                    total_work = 1000 * rho
                    bulk_work = total_work - 30
                    rows.append({
                        "rho": rho, "pmr": pmr, "seed": seed,
                        "generated": 1000, "completed": 1000, "dropped": 0,
                        "unfinished": 0, "p99": 0.5 if passed else 1.2,
                        "miss_count": 0 if passed else 20,
                        "miss_ratio": 0 if passed else 0.02,
                        "trace_mean_rate": 1.0,
                        "trace_mean_rate_measured": 1 + (high - low) * 0.001,
                        "offered_load_measured_actual": rho / (1 + (high - low) * 0.001),
                        "trace_pattern_digest": f"pattern-seed-{seed}",
                        "offered_control_work": 10, "offered_sensor_work": 20,
                        "offered_bulk_work": bulk_work, "offered_total_work": total_work,
                        "offered_control_work_measured": 10,
                        "offered_sensor_work_measured": 20,
                        "offered_bulk_work_measured": bulk_work,
                        "offered_total_work_measured": total_work,
                        "bulk_packet_count": int(bulk_work * 10),
                        "bulk_packet_count_measured": int(bulk_work * 10),
                        "offered_load_actual": rho,
                    })
        with (path / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return paths


def modify_csv(path: Path, predicate, field: str, value):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if predicate(row):
            row[field] = str(value)
            break
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class FactorialAnalysisTests(unittest.TestCase):
    def test_contrasts_censoring_and_cli_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = fixture(root)
            out = root / "analysis"
            self.assertEqual(main([
                "--constant", str(paths["constant"]),
                "--moderate", str(paths["moderate"]),
                "--strong", str(paths["strong"]), "--out", str(out),
            ]), 0)
            summary = json.loads((out / "factorial_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["pairing"]["paired_grid_points"], 16)
            self.assertAlmostEqual(summary["pairing"]["max_cross_regime_trace_mean_rate_measured_spread"], 0.0006)
            self.assertAlmostEqual(summary["pairing"]["max_abs_trace_mean_rate_measured_error"], 0.0006)
            self.assertTrue(summary["interpretive_cautions"])
            with (out / "factorial_boundaries.csv").open(newline="", encoding="utf-8") as handle:
                rows = {(row["regime"], float(row["pmr"])): row for row in csv.DictReader(handle)}
            self.assertEqual(float(rows[("constant", 2.0)]["boundary"]), 0.4)
            self.assertEqual(float(rows[("constant", 2.0)]["grid_erosion_vs_pmr1"]), 0.4)
            self.assertEqual(rows[("constant", 2.0)]["erosion_if_uncensored"], "")
            self.assertEqual(float(rows[("moderate", 2.0)]["grid_interaction_vs_constant"]), 0)
            self.assertEqual(float(rows[("strong", 2.0)]["grid_interaction_vs_constant"]), -0.2)
            self.assertEqual(rows[("strong", 2.0)]["interaction_if_uncensored"], "")
            svg = (out / "erosion.svg").read_text(encoding="utf-8")
            self.assertIn("Exploratory coarse-grid contrasts", svg)
            self.assertIn("open circles", svg)

    def test_rejects_unpaired_pattern_grid_work_and_normalization(self):
        cases = (
            ("pattern", "trace_pattern_digest", "wrong", "trace_pattern_digest"),
            ("work", "offered_bulk_work", "999", "offered work differs"),
            ("normalization", "trace_mean_rate", "0.99", "trace_mean_rate"),
        )
        for case, field, value, error in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                paths = fixture(root)
                modify_csv(paths["moderate"] / "runs.csv", lambda row: True, field, value)
                with self.assertRaisesRegex(ValueError, error):
                    analyze(paths["constant"], paths["moderate"], paths["strong"], root / "out")
                self.assertFalse((root / "out").exists())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = fixture(root)
            csv_path = paths["strong"] / "runs.csv"
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            rows.pop()
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "incomplete"):
                analyze(paths["constant"], paths["moderate"], paths["strong"], root / "out")

    def test_rejects_changed_simulation_control(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = fixture(root)
            config = paths["strong"] / "config.json"
            manifest = json.loads(config.read_text(encoding="utf-8"))
            manifest["simulation"]["control_period"] = 2.0
            config.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "simulation controls"):
                analyze(paths["constant"], paths["moderate"], paths["strong"], root / "out")


if __name__ == "__main__":
    unittest.main()
