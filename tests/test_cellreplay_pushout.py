import unittest
from converged_sim.cellreplay_pushout import simulate
from converged_sim.cellreplay_mixed import simulate as original

def p(t,size,flow):return dict(arrival_ms=t,release_ms=t,content_bytes=size,flow=flow,planned_light_bypass=False)

class PushoutTests(unittest.TestCase):
    def test_evict_lowest_tail_and_count_loss(self):
        rows,d=simulate([p(0,1400,3),p(0,150,1)],[(10,1)],1,10)
        self.assertEqual(rows[0]['status'],'dropped')
        self.assertEqual(rows[0]['evicted_by'],1)
        self.assertEqual(rows[1]['status'],'completed')
        self.assertEqual(d['evictions'],1);self.assertEqual(d['final_counter'],0)
    def test_no_equal_or_higher_eviction(self):
        rows,d=simulate([p(0,150,1),p(0,150,1),p(0,1400,3)],[(10,1)],1,10)
        self.assertEqual(rows[0]['status'],'completed')
        self.assertEqual(rows[1]['status'],'dropped');self.assertEqual(rows[2]['status'],'dropped')
        self.assertEqual(d['evictions'],0)
    def test_sensor_can_evict_bulk(self):
        rows,d=simulate([p(0,1400,3),p(0,256,2)],[(10,1)],1,10)
        self.assertEqual(rows[0]['evicted_by'],1);self.assertEqual(d['evictions'],1)
    def test_in_transit_not_evicted(self):
        plan=[p(0,150,1),p(0,1400,3),p(2,1400,3),p(2,1400,3),p(2,150,1)]
        rows,d=simulate(plan,[(1,1),(10,1)],2,10)
        self.assertEqual(rows[1]['finish_ms'],10)
        self.assertEqual(rows[3]['status'],'dropped')
        self.assertEqual(rows[4]['status'],'completed')
    def test_non_full_matches_priority_and_deterministic(self):
        plan=[p(0,150,1),p(0,1400,3),p(2,150,1)]
        pdos=[(1,1),(10,1),(20,1)]
        rows,diag=simulate(plan,pdos,16,20)
        reference,_=original(plan,pdos,'priority','accepted',16,20)
        for r in rows:r.pop('evicted_by')
        self.assertEqual(rows,reference)
        self.assertEqual(simulate(plan,pdos,16,20),simulate(plan,pdos,16,20))
