import unittest
from converged_sim.cellreplay_development_screen import parse_light,parse_offset


class ScreenTests(unittest.TestCase):
    def receipt(self):return {'sha256':'synthetic-fixture','bytes':0,'complete_member_read':True}
    def test_light_order_and_quantiles(self):
        r=parse_light(iter(['0 10 0 2 5','100 20 0 3 8','200 30 0 1 2',self.receipt()]))
        self.assertEqual(r['base_delay_p99_ms'],30)
        self.assertEqual(r['fraction_base_ge20ms'],2/3)
        with self.assertRaises(ValueError):parse_light(iter(['0 10 2 1',self.receipt()]))
        with self.assertRaises(ValueError):parse_light(iter(['0 10 0','-1 10 0',self.receipt()]))

    def test_offset_interpolation_and_reject_missing_receipt(self):
        r=parse_offset(iter(['100 -2','200 0','300 1',self.receipt()]))
        self.assertEqual(r['content_150_offset_ms'],-1)
        self.assertEqual(r['content_1200_offset_ms'],1)
        with self.assertRaises(ValueError):parse_offset(iter(['200 0',self.receipt()]))
        with self.assertRaises(ValueError):parse_offset(iter(['100 nan',self.receipt()]))
        with self.assertRaises(ValueError):parse_offset(iter(['100 0']))


if __name__=='__main__':unittest.main()
