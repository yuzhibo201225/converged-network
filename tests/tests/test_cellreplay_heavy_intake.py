import io
import unittest
from converged_sim.cellreplay_heavy_intake import parse

class HeavyIntakeTests(unittest.TestCase):
    def test_duplicate_budget_and_absolute_time(self):
        stats,prefix=parse(io.BytesIO(b'5\n5\n1001\n208001\n'))
        self.assertEqual(stats['duplicate_times'],1)
        self.assertEqual(stats['events'],4)
        self.assertEqual(dict(prefix),{5:2,1001:1})
        self.assertEqual(stats['bins_1000ms'],{0:2,1:1,208:1})
    def test_monotonicity(self):
        with self.assertRaises(ValueError): parse(io.BytesIO(b'3\n2\n'))
    def test_invalid_or_empty(self):
        for body in (b'',b'0\n',b'1.0\n',b'-1\n',b'\n',b'18446744073709551616\n'):
            with self.assertRaises(ValueError): parse(io.BytesIO(body))
