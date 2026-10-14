import unittest
from converged_sim.timescale_predictor import features,solve,fit_model,predict


class PredictorTests(unittest.TestCase):
    def test_linear_solver_and_singular_detection(self):
        result=solve([[2.,1.],[1.,3.]],[5.,7.])
        self.assertAlmostEqual(result[0],1.6)
        self.assertAlmostEqual(result[1],1.8)
        with self.assertRaises(ValueError): solve([[1.,1.],[1.,1.]],[1.,2.])

    def test_smooth_feature_does_not_depend_on_bulk_cycle(self):
        row=dict(rho=.6,pmr=1,tau_b=.5,tau_s=2)
        original=features(row,True)
        row["tau_b"]=8
        self.assertEqual(original,features(row,True))

    def test_fixed_fit_is_deterministic_and_positive(self):
        cells=[dict(rho=rho,pmr=pmr,tau_b=tb,tau_s=ts,p99=.1+rho*tb*pmr+ts*.01)
            for rho in (.4,.6) for pmr in (1,3) for tb in (.5,2) for ts in (.5,2)]
        for extended in (False,True):
            model=fit_model(cells,extended)
            self.assertEqual(model,fit_model(cells,extended))
            self.assertEqual(model["ridge"],.1)
            self.assertGreater(predict(model,cells[0]),0.)
