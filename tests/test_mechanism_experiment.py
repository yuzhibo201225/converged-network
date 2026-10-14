import csv
import json
from pathlib import Path
import tempfile
import unittest

from converged_sim.mechanism_experiment import analyze, audit, run


class MechanismExperimentTests(unittest.TestCase):
    def _config(self, path: Path, low: float, high: float) -> None:
        path.write_text(json.dumps({
            "simulation": {
                "warmup_control_packets": 6,
                "measured_control_packets": 12,
                "trace_low_rate": low,
                "trace_high_rate": high,
                "trace_normalize_mean": True,
            },
            "sweep": {
                "loads": [0.6], "pmrs": [1.0, 3.0],
                "seeds": [101, 102], "refine_step": 0.1,
            },
        }), encoding="utf-8")

    def test_run_audit_replay_and_cross_regime_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = {}
            for regime, rates in {
                "constant": (1.0, 1.0),
                "moderate": (0.85, 1.15),
                "strong": (0.7, 1.3),
            }.items():
                config = root / f"{regime}.json"
                self._config(config, *rates)
                output = root / regime
                run(config, output)
                self.assertEqual(audit(output), {
                    "status": "PASS", "runs": 4, "control_packets": 48,
                })
                paths[regime] = output
            replay = root / "constant-replay"
            run(root / "constant.json", replay)
            self.assertEqual(
                (paths["constant"] / "control_mechanism.csv.gz").read_bytes(),
                (replay / "control_mechanism.csv.gz").read_bytes(),
            )
            self.assertEqual(
                (paths["constant"] / "runs.csv").read_bytes(),
                (replay / "runs.csv").read_bytes(),
            )
            result = analyze(paths["constant"], paths["moderate"], paths["strong"],
                             root / "analysis")
            self.assertEqual(result["status"], "PASS")
            with (root / "analysis" / "mechanism_summary.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                summary = list(csv.DictReader(handle))
            self.assertEqual(len(summary), 6)
            with (root / "analysis" / "mechanism_paired_contrasts.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                contrasts = list(csv.DictReader(handle))
            self.assertEqual(len(contrasts), 3 * 8)

    def test_rejects_wrong_mechanism_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "wrong.json"
            config.write_text(json.dumps({
                "simulation": {"warmup_control_packets": 6,
                               "measured_control_packets": 12},
                "sweep": {"loads": [0.5, 0.6], "pmrs": [1, 3],
                          "seeds": [1], "refine_step": 0.1},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mechanism_v1"):
                run(config, root / "out")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
