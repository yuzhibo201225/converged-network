import unittest
from converged_sim.audit_course_repeats import JsonListHash, histogram_quantile, independent_metrics
from converged_sim.coarse_observation import digest


class AuditCourseRepeatsTests(unittest.TestCase):
    def test_stream_canonical_hash(self):
        for items in ([], [(1, 2, 3, 4), (7, 8, 9, 10)], [{'b': True, 'a': 2}]):
            h = JsonListHash()
            for item in items:
                h.add(item)
            self.assertEqual(h.finish(), digest(items))

    def test_nearest_rank(self):
        self.assertEqual(histogram_quantile({1: 99, 40: 1}, .99), 1)
        self.assertEqual(histogram_quantile({1: 98, 40: 2}, .99), 40)
        self.assertIsNone(histogram_quantile({}, .99))

    def test_loss_censoring_and_deadline_equality(self):
        rows = [dict(flow=1, arrival_ms=8000, status='completed', delay_ms=20),
                dict(flow=1, arrival_ms=8020, status='dropped', delay_ms=''),
                dict(flow=1, arrival_ms=8040, status='unfinished', delay_ms=''),
                dict(flow=1, arrival_ms=0, status='completed', delay_ms=1)]
        m, hist = independent_metrics(rows, 8000, [20, 40])
        self.assertEqual(m['control_count'], 3)
        self.assertEqual(m['control_p99_ms'], 20)
        self.assertEqual(m['control_miss_20ms'], 1)
        self.assertEqual(m['control_miss_40ms'], 2 / 3)
        self.assertFalse(m['control_pass_40ms'])
        self.assertEqual(hist[1], {20: 1})
