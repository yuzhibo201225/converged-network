import unittest
from converged_sim.scenario_admission_baselines import decide


class AdmissionBaselineTests(unittest.TestCase):
    def test_known_envelope_qualifies_only_smaller_bias(self):
        for lag in (0,.5):
            self.assertTrue(decide(.95,.03,lag)['fluid_sufficient_condition'])
            self.assertFalse(decide(.95,.06,lag)['fluid_sufficient_condition'])

    def test_mean_load_is_not_a_deadline_criterion(self):
        self.assertTrue(decide(.95,.5,9)['mean_load'])
        self.assertFalse(decide(1,0,0)['mean_load'])

    def test_invalid_inputs_fail_closed(self):
        for args in ((-.1,0,0),(.95,-.1,0),(.95,0,-1),(1.1,0,0)):
            with self.assertRaises(ValueError):decide(*args)
