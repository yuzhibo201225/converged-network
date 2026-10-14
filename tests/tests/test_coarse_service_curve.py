import math
import random
import unittest
from converged_sim.coarse_service_curve import beta,inverse,bounds,arrival_right,qualify
from converged_sim.coarse_observation import CONFIG,trace
from converged_sim.traffic_contract import emissions


class ServiceCurveTests(unittest.TestCase):
    def test_partial_bin_optimization(self):
        D=50
        def g(z):return max(.7*z,D-1.3*(D-z))
        for length in (.1,20,49,50,63,75,80,100,120,150,170):
            candidates=[]
            for j in range(10001):
                start=j*D/10000;stop=start+length
                first=min(length,D-start)
                if start==D:first=0
                remaining=length-first;n=math.floor(remaining/D);last=remaining-n*D
                candidates.append(g(first)+n*D+g(last))
            self.assertAlmostEqual(beta(length),min(candidates),places=7)

    def test_inverse_and_tail_lower_bound(self):
        for mode in ('budget','minimum','mean'):
            for t in (0,.1,25,49.9,50,50.1,75,100,125,999.3):
                self.assertAlmostEqual(inverse(beta(t,mode=mode),mode=mode),t,places=9)
                if mode=='budget':self.assertGreaterEqual(beta(t)+1e-10,t-15)

    def test_prescribed_paths_dominate_beta(self):
        rng=random.Random(1234)
        for p in CONFIG['profiles']:
            s=trace(p,2,CONFIG)
            for _ in range(200):
                left=rng.uniform(0,1000);length=rng.uniform(.01,160)
                self.assertGreaterEqual(s.integrate(left,left+length)+1e-8,beta(length))

    def test_suprema_dense_diagnostic(self):
        for rho in (.2,.4,.7,.9,.95):
            b=bounds(rho)
            for i in range(5001):
                t=i*b['tail_cutoff_T']/5000;a=arrival_right(t,rho)
                self.assertLessEqual(a-beta(t),b['backlog_work']+1e-8)
                self.assertLessEqual(inverse(a)-t,b['delay_T']+1e-8)
            for k in range(500):
                t=b['tail_cutoff_T']+k/10;a=arrival_right(t,rho)
                self.assertLessEqual(a-beta(t),b['backlog_work']+1e-8)
                self.assertLessEqual(inverse(a)-t,b['delay_T']+1e-8)

    def test_arrival_envelope_coverage(self):
        es=emissions(.9,3,8,0,800,20261020,1)
        events=[((e.generated_s-1)/.02,{1:.01,2:.04,3:.1}[e.flow]) for e in es]
        rng=random.Random(42)
        for _ in range(100):
            left=rng.uniform(0,500);width=rng.uniform(.01,70)
            work=sum(w for t,w in events if left<t<=left+width)
            self.assertLessEqual(work,arrival_right(width,.9)+1e-8)

    def test_minimum_rate_overload(self):
        self.assertTrue(math.isinf(bounds(.8,mode='minimum')['backlog_work']))
        self.assertTrue(math.isinf(bounds(.7+5e-13,mode='minimum')['backlog_work']))
        self.assertTrue(math.isfinite(bounds(.7,mode='minimum')['backlog_work']))

    def test_reject_outcomes(self):
        x=dict(rho=.4,queue='fifo',capacity=16,guard=400,pmr=3,bulk_cycle=8,deadline_T=1,observation_bin_T=50)
        with self.assertRaisesRegex(ValueError,'declared contract'):qualify({**x,'observed_p99':.1})
        self.assertFalse(qualify(x)['qualified'])
        self.assertTrue(qualify({**x,'queue':'priority'})['qualified'])


if __name__=='__main__':unittest.main()
