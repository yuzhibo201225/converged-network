import unittest
from dataclasses import replace
from converged_sim.coarse_observation import CONFIG,trace,simulate,summarize
from converged_sim.traffic_contract import emissions


class CoarseObservationTests(unittest.TestCase):
    def test_bin_totals(self):
        for p in CONFIG['profiles']:
            s=trace(p,3,CONFIG)
            for t in range(0,10800,50):self.assertAlmostEqual(s.integrate(t,t+50),50,places=8)

    def test_rate_change_integration(self):
        s=trace('coarse',1,CONFIG)
        self.assertAlmostEqual(s.finish_time(0,50),50)
        self.assertAlmostEqual(s.integrate(0,s.finish_time(0,30)),30)

    def test_departure_before_arrival(self):
        s=trace('constant',1,CONFIG)
        rows,_=simulate([(0,3,0,1),(1,3,1,1)],s,'fifo',.5,0,2,10)
        self.assertEqual([r['finish_T'] for r in rows],[1,2])

    def test_priority_nonpreemptive(self):
        s=trace('constant',1,CONFIG)
        rows,_=simulate([(0,3,0,1),(.1,3,1,1),(.2,1,0,.1)],s,'priority',2,0,3,10)
        self.assertAlmostEqual(next(r for r in rows if r['flow']==1)['finish_T'],1.1)
        self.assertAlmostEqual(next(r for r in rows if r['flow']==3 and r['id']==1)['finish_T'],2.1)

    def test_drop_is_miss(self):
        s=trace('constant',1,CONFIG)
        rows,_=simulate([(0,3,0,1),(.1,3,1,.5),(.2,1,0,.1)],s,'fifo',.5,0,2,10)
        d=summarize(rows,1)
        self.assertEqual(d['control_drop_count'],1)
        self.assertEqual(d['control_miss_ratio'],1)

    def test_repeat_exact(self):
        self.assertEqual(trace('fine',2,CONFIG).digest,trace('fine',2,CONFIG).digest)

    def test_unresolved_is_miss(self):
        s=replace(trace('constant',1,CONFIG),starts=[0.],ends=[.2],rates=[1.],drain_horizon=.2)
        rows,_=simulate([(0,1,0,1)],s,'fifo',1,0,1,.2)
        self.assertEqual(rows[0]['status'],'unresolved')
        self.assertEqual(summarize(rows,1)['control_miss_ratio'],1)

    def test_exact_measured_offered_work(self):
        for rho in CONFIG['loads']:
            for seed in CONFIG['seeds']:
                es=emissions(rho,3,8,400,10400,CONFIG['phase_seed'],seed)
                work=sum({1:.01,2:.04,3:.1}[e.flow] for e in es if 400<=round((e.generated_s-1)/.02,10)<10400)
                self.assertAlmostEqual(work,rho*10000,places=6)


if __name__=='__main__':unittest.main()
