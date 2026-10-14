import unittest
from ns3_validation.order_cli import trace_blocks, trace_rows


class ServiceOrderTests(unittest.TestCase):
    spec = dict(warm=256, measured=10000, tauS=8, trace_seed_base=100000)

    def test_window_balance_and_pair_multiset(self):
        windows = (256,10000,301)
        blocks = trace_blocks(self.spec,1)
        for block, periods in zip(blocks,windows):
            self.assertEqual(2*sum(block),round(periods*.02*1e9))
            self.assertGreater(min(block),0)
        for mode in ('random','ascending','descending'):
            rows = trace_rows(self.spec,1,mode)
            at = 0
            for block in blocks:
                durations = []
                for _ in block:
                    low,high = rows[at:at+2]
                    durations.append(round((high[0]-low[0])*1e9))
                    self.assertEqual((low[1],high[1]),(.7,1.3)); at += 2
                self.assertEqual(sorted(durations),sorted(block))
            self.assertTrue(all(a[0]<b[0] for a,b in zip(rows,rows[1:])))

    def test_reproduction_and_actual_order_change(self):
        a = trace_rows(self.spec,1,'random')
        self.assertEqual(a,trace_rows(self.spec,1,'random'))
        self.assertNotEqual(a,trace_rows(self.spec,2,'random'))
        self.assertNotEqual(a,trace_rows(self.spec,1,'ascending'))
        self.assertNotEqual(a,trace_rows(self.spec,1,'descending'))

    def test_invalid_order_rejected(self):
        with self.assertRaises(ValueError): trace_rows(self.spec,1,'unknown')


if __name__ == '__main__': unittest.main()
