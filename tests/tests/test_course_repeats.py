from collections import Counter
import unittest
from converged_sim.course_repeats import rotated_events,PHASES,SETTINGS
from converged_sim.cellreplay_mixed import arrivals

class CourseRepeatTests(unittest.TestCase):
    def test_seed_zero_exact_previous_arrivals(self):
        self.assertEqual(rotated_events(1234,3,0,SETTINGS),arrivals(1234,3,SETTINGS))
    def test_all_phase_volume_pairing_and_bounds(self):
        for phase in PHASES.values():
            a,ac=rotated_events(12341,1,phase,SETTINGS)
            b,bc=rotated_events(12341,3,phase,SETTINGS)
            self.assertEqual(ac,bc)
            self.assertEqual([e for e in a if e[1]<3],[e for e in b if e[1]<3])
            self.assertEqual(Counter(t//300 for t,f,i,n in a if f==3),Counter(t//300 for t,f,i,n in b if f==3))
            self.assertTrue(all(0<=e[0]<208000 for e in a+b))
            self.assertEqual(sum(e[3] for e in a),sum(e[3] for e in b))
    def test_seed_map_and_determinism(self):
        self.assertEqual(len(PHASES),5)
        self.assertEqual(rotated_events(35000,3,PHASES[2],SETTINGS),rotated_events(35000,3,PHASES[2],SETTINGS))
