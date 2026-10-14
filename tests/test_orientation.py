import unittest
from ns3_validation.orientation_cli import trace_rows
from ns3_validation.order_cli import trace_blocks
from converged_sim.service_runlength_audit import low_durations


class OrientationTests(unittest.TestCase):
    spec=dict(warm=256,measured=10000,tauS=8,trace_seed_base=110000)

    def test_boundaries_and_elementary_dwells_are_paired(self):
        variants=[trace_rows(self.spec,1,mode) for mode in ('lowfirst','highfirst','coinflip')]
        for rows in variants[1:]:
            self.assertEqual([t for t,_ in rows],[t for t,_ in variants[0]])
        expected=sum(trace_blocks(self.spec,1),[])
        for rows in variants:
            for i,dwell in enumerate(expected):
                self.assertEqual(set(rate for _,rate in rows[2*i:2*i+2]),{.7,1.3})
                self.assertEqual(round((rows[2*i+1][0]-rows[2*i][0])*1e9),dwell)

    def test_random_orientation_reproducible_and_merges_runs(self):
        a=trace_rows(self.spec,1,'coinflip')
        self.assertEqual(a,trace_rows(self.spec,1,'coinflip'))
        self.assertNotEqual(a,trace_rows(self.spec,2,'coinflip'))
        low=trace_rows(self.spec,1,'lowfirst')
        begin=1+.02*self.spec['warm'];end=begin+.02*self.spec['measured']
        self.assertGreater(max(low_durations(a,begin,end)),max(low_durations(low,begin,end)))
        self.assertAlmostEqual(sum(low_durations(a,begin,end)),self.spec['measured']/2,places=7)

    def test_invalid_orientation(self):
        with self.assertRaises(ValueError): trace_rows(self.spec,1,'unknown')


if __name__=='__main__':unittest.main()
