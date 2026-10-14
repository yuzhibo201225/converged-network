import unittest
from converged_sim.deadline_sensitivity import contiguous


class PrefixTests(unittest.TestCase):
    def test_recovery_not_admitted(self):
        rows=[dict(rho=.4,ok=True),dict(rho=.2,ok=True),dict(rho=.3,ok=False)]
        self.assertEqual(contiguous(rows,lambda r:r["ok"]),dict(boundary=.2,first_failing=.3,censoring="interval"))

    def test_censoring(self):
        row=[dict(rho=.2)]
        self.assertEqual(contiguous(row,lambda r:False)["censoring"],"left")
        self.assertEqual(contiguous(row,lambda r:True)["censoring"],"right")
