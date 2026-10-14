import unittest
from converged_sim.coarse_observation import CONFIG,trace,simulate
from converged_sim.coarse_fifo_shadow import shadow


class ShadowTests(unittest.TestCase):
    def test_separate_cumulative_integrator(self):
        for profile in ('constant','coarse','fine'):
            s=trace(profile,1,CONFIG)
            events=[(0,3,0,20),(1,1,0,.1),(1,3,1,.3),(25,1,1,.1),(50,3,2,3)]
            rows,_=simulate(events,s,'fifo',.4,0,51,100)
            alt=shadow(events,s.starts,s.ends,s.rates,.4,0,51)
            for r in rows:
                status,at=alt[(r['flow'],r['id'])]
                self.assertEqual(r['status'],status)
                if status=='completed':self.assertAlmostEqual(r['finish_T'],at,places=9)


if __name__=='__main__':unittest.main()
