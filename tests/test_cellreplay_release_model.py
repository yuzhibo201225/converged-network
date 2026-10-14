import unittest
from converged_sim.cellreplay_release_model import ReleasePlanner,cpp_round


class ReleaseTests(unittest.TestCase):
    def records(self):return [(0,20,[0,3,5]),(100,30,[0,4,8]),(200,20,[0,2,4])]

    def test_interpolation_and_rounding(self):
        p=ReleasePlanner(self.records(),[-4.9,-4.3],0)
        r=p.plan(50,150)
        self.assertEqual(r['base_delay_ms'],25)
        self.assertEqual(r['planned_delay_ms'],20)
        self.assertEqual(cpp_round(-.5),-1)
        self.assertEqual(cpp_round(.5),1)

    def test_active_light_and_heavy_handoff(self):
        p=ReleasePlanner(self.records(),[],25)
        self.assertEqual(p.plan(0,1400)['release_ms'],20)
        self.assertEqual(p.plan(1,1400)['release_ms'],23)
        self.assertEqual(p.plan(2,1400)['release_ms'],25)
        r=p.plan(3,1400)
        self.assertFalse(r['planned_light_bypass'])
        self.assertEqual(r['release_ms'],25)
        self.assertTrue(r['release_clamped'])

    def test_bounds_and_no_wrap(self):
        p=ReleasePlanner(self.records(),[],0)
        for t,size in ((0,1500),(200,150)):
            with self.assertRaises(ValueError):p.plan(t,size)


if __name__=='__main__':unittest.main()
