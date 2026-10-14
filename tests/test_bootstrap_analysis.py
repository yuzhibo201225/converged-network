import csv
import json
from pathlib import Path
import tempfile
import unittest

from converged_sim.bootstrap_analysis import (
    _censoring,
    _evaluate_draw,
    _grid_interval,
    _index_rows,
    analyze,
    main,
)
from converged_sim.factorial_analysis import _check_regimes, _load_regime


LOADS = (0.2, 0.4, 0.6, 0.8)
PMRS = (1.0, 2.0)
SEEDS = (10, 11, 12, 13)
RATES = {"constant": (1.0, 1.0), "moderate": (0.85, 1.15), "strong": (0.7, 1.3)}
LAST_PASS = {
    "constant": {
        1.0: {10: 0.8, 11: 0.6, 12: 0.4, 13: None},
        2.0: {10: 0.6, 11: 0.4, 12: 0.2, 13: None},
    },
    "moderate": {
        1.0: {10: 0.6, 11: 0.4, 12: 0.2, 13: None},
        2.0: {10: 0.4, 11: 0.2, 12: None, 13: None},
    },
    "strong": {
        1.0: {10: 0.4, 11: 0.2, 12: None, 13: None},
        2.0: {10: 0.2, 11: None, 12: None, 13: None},
    },
}


def fixture(root: Path) -> dict[str, Path]:
    paths = {}
    for regime, (low, high) in RATES.items():
        path = root / regime
        path.mkdir()
        paths[regime] = path
        manifest = {
            "simulation": {
                "control_period": 1.0,
                "measured_control_packets": 1000,
                "trace_low_rate": low,
                "trace_high_rate": high,
                "trace_normalize_mean": True,
            },
            "sweep": {
                "loads": list(LOADS), "pmrs": list(PMRS),
                "seeds": list(SEEDS), "refine_step": 0.1,
            },
            "deadline": 1.0,
        }
        (path / "config.json").write_text(json.dumps(manifest), encoding="utf-8")
        rows = []
        for rho in LOADS:
            for pmr in PMRS:
                for seed in SEEDS:
                    last_pass = LAST_PASS[regime][pmr][seed]
                    passed = last_pass is not None and rho <= last_pass
                    total_work = 1000 * rho
                    bulk_work = total_work - 30
                    rows.append({
                        "rho": rho, "pmr": pmr, "seed": seed,
                        "generated": 1000, "completed": 1000, "dropped": 0,
                        "unfinished": 0, "p99": 0.5 if passed else 1.5,
                        "miss_count": 0 if passed else 20,
                        "miss_ratio": 0 if passed else 0.02,
                        "trace_mean_rate": 1.0,
                        "trace_mean_rate_measured": 1 + (high - low) * 0.001,
                        "offered_load_measured_actual": rho / (1 + (high - low) * 0.001),
                        "trace_pattern_digest": f"pattern-seed-{seed}",
                        "offered_control_work": 10,
                        "offered_sensor_work": 20,
                        "offered_bulk_work": bulk_work,
                        "offered_total_work": total_work,
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


def loaded(paths: dict[str, Path]):
    manifests = {}
    rows = {}
    for regime, path in paths.items():
        manifests[regime], rows[regime] = _load_regime(path)
    _check_regimes(manifests, rows)
    return manifests, rows


class BootstrapAnalysisTests(unittest.TestCase):
    def test_whole_curve_draw_recomputes_and_keeps_censoring(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fixture(Path(temp))
            manifests, rows = loaded(paths)
            index, loads, pmrs, seeds = _index_rows(rows)
            deadline = float(manifests["constant"]["deadline"])

            upper = _evaluate_draw(index, loads, pmrs, [10] * len(seeds), deadline, 0.01)
            lower = _evaluate_draw(index, loads, pmrs, [13] * len(seeds), deadline, 0.01)
            self.assertEqual(upper[("constant", 1.0)]["boundary"], 0.8)
            self.assertEqual(upper[("constant", 1.0)]["censoring"], "upper")
            self.assertIsNone(lower[("constant", 1.0)]["boundary"])
            self.assertEqual(lower[("constant", 1.0)]["censoring"], "lower")
            self.assertIsNone(upper[("constant", 1.0)]["erosion_vs_pmr1"])
            self.assertIsNone(lower[("strong", 2.0)]["interaction_vs_constant"])

    def test_cli_is_deterministic_and_intervals_stay_on_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = fixture(root)
            args = [
                "--constant", str(paths["constant"]),
                "--moderate", str(paths["moderate"]),
                "--strong", str(paths["strong"]),
                "--replicates", "200", "--bootstrap-seed", "20260930",
            ]
            out_a, out_b = root / "bootstrap-a", root / "bootstrap-b"
            self.assertEqual(main([*args, "--out", str(out_a)]), 0)
            self.assertEqual(main([*args, "--out", str(out_b)]), 0)
            for filename in (
                "bootstrap_draws.csv", "bootstrap_replicates.csv",
                "bootstrap_summary.csv", "bootstrap_audit.json",
            ):
                self.assertEqual((out_a / filename).read_bytes(), (out_b / filename).read_bytes())

            with (out_a / "bootstrap_draws.csv").open(newline="", encoding="utf-8") as handle:
                draw_rows = list(csv.DictReader(handle))
            self.assertEqual(len(draw_rows), 200 * len(SEEDS))
            self.assertEqual(
                {int(row["slot"]) for row in draw_rows if int(row["replicate"]) == 0},
                set(range(len(SEEDS))),
            )
            with (out_a / "bootstrap_replicates.csv").open(newline="", encoding="utf-8") as handle:
                replicate_rows = list(csv.DictReader(handle))
            first_digests = {
                row["draw_digest"] for row in replicate_rows if int(row["replicate"]) == 0
            }
            self.assertEqual(len(first_digests), 1)
            self.assertEqual(len([row for row in replicate_rows if int(row["replicate"]) == 0]), 3 * len(PMRS))

            with (out_a / "bootstrap_summary.csv").open(newline="", encoding="utf-8") as handle:
                summaries = list(csv.DictReader(handle))
            self.assertEqual(len(summaries), 3 * len(PMRS))
            for row in summaries:
                frequencies = sum(float(row[key]) for key in (
                    "boundary_uncensored_frequency",
                    "boundary_lower_censored_frequency",
                    "boundary_upper_censored_frequency",
                ))
                self.assertAlmostEqual(frequencies, 1.0)
                for key in (
                    "boundary_interval_low_conditional_uncensored",
                    "boundary_interval_high_conditional_uncensored",
                ):
                    if row[key]:
                        self.assertIn(float(row[key]), LOADS)
            audit = json.loads((out_a / "bootstrap_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["bootstrap_seed"], 20260930)
            self.assertIn("no interpolation", audit["interval_rule"])
            self.assertEqual(audit["sampling_unit"], "one seed across every load, PMR, and service-rate regime")

    def test_order_statistic_interval_does_not_interpolate(self):
        low, high = _grid_interval([0.2, 0.4, 0.4, 0.8], 0.75)
        self.assertIn(low, LOADS)
        self.assertIn(high, LOADS)
        self.assertEqual(_censoring(None, False), "lower")
        self.assertEqual(_censoring(0.8, True), "upper")
        self.assertEqual(_censoring(0.4, False), "none")

    def test_rejects_incomplete_pairing_before_creating_output(self):
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
            out = root / "out"
            with self.assertRaisesRegex(ValueError, "incomplete"):
                analyze(
                    paths["constant"], paths["moderate"], paths["strong"], out,
                    replicates=10, bootstrap_seed=1,
                )
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
