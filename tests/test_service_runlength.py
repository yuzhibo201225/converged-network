import unittest
from converged_sim.service_runlength_audit import low_durations


class ServiceRunlengthTests(unittest.TestCase):
    def test_equal_rates_are_merged_and_window_clipped(self):
        rows=[(1.,.7),(2.,.7),(3.,1.3),(4.,.7),(5.,1.3)]
        self.assertEqual(low_durations(rows,1.,5.,1.),[2.,1.])
        self.assertEqual(low_durations(rows,1.5,4.5,1.),[1.5,.5])

    def test_missing_initial_service_is_rejected(self):
        with self.assertRaises(ValueError): low_durations([(2.,.7)],1.,3.)


if __name__=='__main__':unittest.main()
