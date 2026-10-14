import math
import unittest

from converged_sim.reliability_boundary import (
    arm_points,
    clopper_pearson_lower,
    contiguous_boundary,
)


class ReliabilityBoundaryTests(unittest.TestCase):
    def test_exact_lower_bound_edges(self):
        self.assertEqual(clopper_pearson_lower(0, 30), 0.0)
        self.assertAlmostEqual(
            clopper_pearson_lower(30, 30), 0.05 ** (1.0 / 30.0), places=12
        )

    def test_lower_bound_has_declared_binomial_tail(self):
        lower = clopper_pearson_lower(18, 30)
        tail = math.fsum(
            math.comb(30, observed)
            * lower ** observed
            * (1.0 - lower) ** (30 - observed)
            for observed in range(18, 31)
        )
        self.assertAlmostEqual(tail, 0.05, places=12)

    def test_joint_endpoint_and_simultaneous_bound(self):
        rows = []
        for seed in range(4):
            rows.extend([
                {"pmr": "3", "rho": "0.2", "seed": str(seed),
                 "p99": "0.5", "miss_ratio": "0"},
                {"pmr": "3", "rho": "0.3", "seed": str(seed),
                 "p99": "0.9" if seed < 3 else "1.1", "miss_ratio": "0"},
            ])
        points = arm_points(
            rows, regime="strong", deadline=1.0, miss_threshold=0.01, alpha=0.05
        )
        self.assertEqual([point["successes"] for point in points], [4, 3])
        self.assertLess(
            float(points[0]["simultaneous_lower_95"]),
            float(points[0]["pointwise_lower_95"]),
        )

    def test_contiguous_boundary_flags_recovery(self):
        points = [
            {"rho": 0.2, "pass_fraction": 1.0, "successes": 10, "trials": 10},
            {"rho": 0.3, "pass_fraction": 0.8, "successes": 8, "trials": 10},
            {"rho": 0.4, "pass_fraction": 1.0, "successes": 10, "trials": 10},
        ]
        result = contiguous_boundary(points, "pass_fraction", 0.9)
        self.assertEqual(result["boundary_rho"], 0.2)
        self.assertEqual(result["first_failing_rho"], 0.3)
        self.assertTrue(result["recovery_after_failure"])


if __name__ == "__main__":
    unittest.main()
