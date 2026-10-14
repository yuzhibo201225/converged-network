import unittest
from converged_sim.telemetry_budget import condition
from converged_sim.finite_source import run


class BudgetTests(unittest.TestCase):
    def test_boundary_algebra(self):
        a=condition(.8,.1,.5);self.assertTrue(a["sufficient"])
        self.assertAlmostEqual(a["maximum_load_from_error"],.875)
        self.assertFalse(condition(.95,.1,.5)["sufficient"])
        self.assertIsNone(condition(.95,.1,.5)["delay_bound"])
        self.assertAlmostEqual(condition(.95,.1,.5)["error_upper_budget"],.03684210526315793)
        self.assertFalse(condition(.875,.1,2)["sufficient"])

    def test_sufficient_cases_respect_maximum_delay(self):
        for rho,error in ((.8,.1),(.875,.1),(.95,.03)):
            for pmr in (1,6):
                for tb in (.5,20):
                    c=condition(rho,error,.5)
                    self.assertTrue(c["sufficient"])
                    r=run(rho,pmr,tb,8,877,mode="feedback",capacity=16,bias=error,lag=.5,measured=300,warmup=16)
                    control=[p for p in r["packets"] if p["class"]=="control"]
                    self.assertTrue(all(p["status"]=="delivered" for p in control))
                    self.assertLessEqual(max(p["latency"] for p in control),c["delay_bound"]+1e-8)
