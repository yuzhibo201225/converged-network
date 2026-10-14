import unittest
from converged_sim.ns3_point_reliability import summarize


class PointReliabilityTests(unittest.TestCase):
    def fixture(self):
        settings=[dict(shape='feedback',queue='fifo',bias=b,lag=.5,capacity=16) for b in (0,.06)]
        settings.append(dict(shape='none',queue='priority',bias=0,lag=0,capacity=16))
        spec=dict(settings=settings,runs=list(range(1,71)),alpha=.05,reliability_target=.9)
        rows=[dict(s,run=i,control_p99_T=.4,control_miss_ratio=0,bulk_delivered=92000,
                   bulk_generated=92000,bulk_source_drop=0) for s in settings for i in spec['runs']]
        return rows,spec

    def test_all_pass_family_bound(self):
        rows,spec=self.fixture();p=summarize(rows,spec)
        self.assertEqual(len(p),3)
        self.assertAlmostEqual(p[0]['familywise_lower_95'],(.05/3)**(1/70))
        self.assertTrue(all(r['qualified'] for r in p))

    def test_failure_and_duplicate_guard(self):
        rows,spec=self.fixture()
        for r in rows[70:140]: r['control_p99_T']=2
        p=summarize(rows,spec);self.assertEqual(p[1]['successes'],0);self.assertFalse(p[1]['qualified'])
        rows.append(dict(rows[0]))
        with self.assertRaises(ValueError): summarize(rows,spec)

    def test_multiple_loads_not_mislabeled_as_one_point(self):
        rows,spec=self.fixture();spec['loads']=[.8,.95]
        with self.assertRaises(ValueError): summarize(rows,spec)
