import csv
import json
from pathlib import Path
import tempfile
import unittest

from converged_sim.main_figure import generate, main, render_svg, summarize_points
from test_factorial_analysis import fixture


class MainFigureTests(unittest.TestCase):
    def test_seed_level_median_iqr_and_joint_qualification(self):
        rows = {}
        for regime in ("constant", "moderate", "strong"):
            rows[regime] = [
                {"rho": "0.2", "pmr": "1", "p99": "0.8", "miss_ratio": "0"},
                {"rho": "0.2", "pmr": "1", "p99": "1.0", "miss_ratio": "0.02"},
                {"rho": "0.4", "pmr": "1", "p99": "2.0", "miss_ratio": "0.02"},
                {"rho": "0.4", "pmr": "1", "p99": "2.2", "miss_ratio": "0.04"},
            ]
        points = summarize_points(rows, control_period=2.0, deadline=2.0)
        first = points[0]
        self.assertAlmostEqual(first["p99_median_T"], 0.45)
        self.assertAlmostEqual(first["p99_q25_T"], 0.425)
        self.assertAlmostEqual(first["p99_q75_T"], 0.475)
        self.assertAlmostEqual(first["miss_median"], 0.01)
        self.assertFalse(first["qualifies"])  # Strictly less than 1%.
        missing = {regime: [{"rho": "0.2", "pmr": "1", "p99": "", "miss_ratio": "1"}]
                   for regime in rows}
        self.assertIsNone(summarize_points(missing, 1, 1)[0]["p99_median_T"])

    def test_cli_reproducibility_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = fixture(root)
            out = root / "figure" / "p99_main.svg"
            arguments = [
                "--constant", str(paths["constant"]),
                "--moderate", str(paths["moderate"]),
                "--strong", str(paths["strong"]),
                "--out", str(out),
            ]
            self.assertEqual(main(arguments), 0)
            svg = out.read_text(encoding="utf-8")
            self.assertIn("Constant service", svg)
            self.assertIn("Moderate service variation", svg)
            self.assertIn("Strong service variation", svg)
            self.assertIn("Seed IQR", svg)
            self.assertIn("Hollow diamond", svg)
            point_csv = out.with_name("p99_main_points.csv")
            with point_csv.open(newline="", encoding="utf-8") as handle:
                points = list(csv.DictReader(handle))
            self.assertEqual(len(points), 3 * 4 * 2)
            self.assertEqual(points[0]["seeds"], "2")
            self.assertEqual(points[0]["p99_available"], "2")
            audit = json.loads(out.with_name("p99_main_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["point_count"], len(points))
            self.assertEqual(audit["pairing"]["paired_grid_points"], 16)
            with self.assertRaises(FileExistsError):
                main(arguments)

    def test_figure_rejects_incomplete_cell_and_invalid_cap(self):
        points = [
            {"regime": regime, "rho": rho, "pmr": pmr, "p99_median_T": 0.5,
             "p99_q25_T": 0.4, "p99_q75_T": 0.6, "miss_median": 0.0}
            for regime in ("constant", "moderate", "strong")
            for rho in (0.2, 0.4) for pmr in (1.0, 1.5, 2.0, 3.0)
        ]
        self.assertIn("<svg", render_svg(points, 1.0))
        points[0]["miss_median"] = 0.02
        self.assertIn('fill="white" stroke="#0072B2"', render_svg(points, 1.0))
        with self.assertRaises(ValueError):
            render_svg(points, 1.0, ymax=1.0)
        points[0]["p99_median_T"] = None
        with self.assertRaisesRegex(ValueError, "incomplete"):
            render_svg(points, 1.0)


if __name__ == "__main__":
    unittest.main()
