import unittest
from converged_sim.traffic_contract import emissions,fractions
from converged_sim.law_admission import validate


class ContractTests(unittest.TestCase):
    def test_phases_repeat_and_change(self):
        self.assertEqual(fractions(20261018,1),fractions(20261018,1))
        self.assertNotEqual(fractions(20261018,1),fractions(20261018,2))
        self.assertTrue(all(0<x<1 for x in fractions(20261018,1)))

    def test_complete_cycles_have_expected_work_and_control_arrivals(self):
        a=emissions(.95,3,8,264,10008,20261018,1)
        ctrl=[e for e in a if e.flow==1];bulk=[e for e in a if e.flow==3]
        self.assertEqual(len(ctrl),10272)
        n=sum(6.28<=e.generated_s<206.44 for e in bulk)
        self.assertLessEqual(abs(n*.1/10008-.92),.1/10008)
        self.assertEqual(len({e.packet_id for e in bulk}),len(bulk))

    def test_actual_future_or_outcome_not_in_admission_interface(self):
        s=dict(loads=[.9],tauS_values=[4],R=3,tauB=8,lag=.5,bias=.06,capacity=16,warm=8,measured=24,
               draws=1,forecast_phase_seed=20261018,forecast_trace_seed_base=200000,q=.9,alpha=.05)
        validate(s)
        for extra in ('actual_future_trace','observed_p99','validation_seed'):
            with self.assertRaises(ValueError):validate(dict(s,**{extra:'forbidden'}))
