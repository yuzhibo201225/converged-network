import unittest
from converged_sim.adaptive_shaper import refill_trace,shape,run
from converged_sim.robustness_model import service_trace,shape as fixed_shape


class AdaptiveTests(unittest.TestCase):
    def test_constant_capacity_agrees_with_fixed_bucket(self):
        trace=service_trace(16.,116.,700.,2.,13,True)
        trace.rates=[1.]*len(trace.rates)
        refill=refill_trace(trace,.8,.5)
        arrivals=[0.]*8+[2.,3.,4.]
        expected=fixed_shape(arrivals,.77,.1)
        actual=shape(arrivals,refill,.1)
        for a,b in zip(actual,expected): self.assertAlmostEqual(a,b,places=9)

    def test_token_envelope_for_varying_refill(self):
        trace=service_trace(16.,116.,700.,2.,5,True)
        refill=refill_trace(trace,.8,1.)
        releases=shape([0.]*10+[2.]*10,refill,.2)
        for i in range(len(releases)):
            for j in range(i,len(releases)):
                self.assertLessEqual((j-i+1)*.1,.2+refill.integrate(releases[i],releases[j])+1e-9)

    def test_fifo_sufficient_bound_and_source_cost(self):
        for lag in (0.,.5,1.,2.):
            result=run(.95,3,8,8,51,lag=lag,measured=500)
            control=[p for p in result["packets"] if p["class"]=="control"]
            self.assertTrue(all(p["status"]=="delivered" for p in control))
            self.assertLessEqual(max(p["latency"] for p in control),result["control_delay_sufficient_bound"]+1e-8)
            self.assertGreater(result["shaper_max_delay"],0.)
            if lag<=.5: self.assertEqual(result["summaries"]["control"]["deadline_miss_ratio"],0.)

    def test_future_changes_do_not_change_past_releases(self):
        original=service_trace(16.,116.,700.,2.,4,True)
        changed=service_trace(16.,116.,700.,2.,4,True)
        changed.rates=[rate if a<10 else .9 for a,rate in zip(changed.starts,changed.rates)]
        first=shape([0.]*100,refill_trace(original,.8,1.),.1)
        second=shape([0.]*100,refill_trace(changed,.8,1.),.1)
        self.assertEqual([r for r in first if r<10],[r for r in second if r<10])

    def test_bound_across_off_grid_extreme_envelopes(self):
        import itertools
        # Implementation stress check, not additional paper replications.
        for rho,pmr,tb,ts,lag in itertools.product((.2,.95),(1,6),(.5,20),(.5,20),(0,5)):
            with self.subTest(rho=rho,pmr=pmr,tb=tb,ts=ts,lag=lag):
                result=run(rho,pmr,tb,ts,719,lag=lag,measured=120,warmup=16)
                controls=[p for p in result["packets"] if p["class"]=="control"]
                self.assertTrue(all(p["status"]=="delivered" for p in controls))
                self.assertLessEqual(max(p["latency"] for p in controls),result["control_delay_sufficient_bound"]+1e-8)
