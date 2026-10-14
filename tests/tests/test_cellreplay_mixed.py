import unittest
from converged_sim.cellreplay_mixed import arrivals,simulate,summarize

def plan(time,size,flow,bypass=False):
    return dict(arrival_ms=time,release_ms=time,content_bytes=size,flow=flow,planned_light_bypass=bypass)

class MixedReplayTests(unittest.TestCase):
    def test_per_cycle_volume_pairing(self):
        cfg=dict(end_ms=208000,cycle_ms=300)
        a,ac=arrivals(35111,1,cfg);b,bc=arrivals(35111,3,cfg)
        self.assertEqual(ac,bc)
        self.assertEqual([e for e in a if e[1]!=3],[e for e in b if e[1]!=3])
        self.assertEqual(sum(e[3] for e in a),sum(e[3] for e in b))
        self.assertNotEqual([e for e in a if e[1]==3],[e for e in b if e[1]==3])
    def test_stale_counter_timing(self):
        p=[plan(0,1400,3),plan(0,1400,3),plan(201,150,1,True)]
        pdos=[(100,1),(200,1),(300,1),(400,1)]
        original,diag=simulate(p,pdos,'fifo','original',1,400)
        corrected,_=simulate(p,pdos,'fifo','accepted',1,400)
        self.assertEqual(original[2]['delay_ms'],99)
        self.assertEqual(corrected[2]['delay_ms'],0)
        self.assertEqual(diag['final_counter'],1)
    def test_same_time_output_hold(self):
        p=[plan(0,1400,3),plan(100,150,1,True)]
        rows,_=simulate(p,[(100,1),(200,1)],'fifo','accepted',16,200)
        self.assertFalse(rows[1]['actual_bypass'])
        self.assertEqual(rows[1]['finish_ms'],200)
    def test_idle_credit_expires(self):
        rows,_=simulate([plan(50,1400,3)],[(0,10),(100,1)],'fifo','accepted',16,100)
        self.assertEqual(rows[0]['finish_ms'],100)
    def test_priority_only_waiting_selection(self):
        p=[plan(0,150,1),plan(0,1400,3),plan(2,1400,3),plan(2,150,1)]
        fifo,_=simulate(p,[(1,1),(10,1),(20,1)],'fifo','accepted',16,20)
        priority,_=simulate(p,[(1,1),(10,1),(20,1)],'priority','accepted',16,20)
        self.assertEqual(fifo[3]['finish_ms'],20)
        self.assertEqual(priority[3]['finish_ms'],10)
        self.assertEqual(priority[1]['finish_ms'],10)
    def test_missing_and_dropped_are_misses_not_p99(self):
        p=[plan(0,150,1),plan(0,150,1),plan(1000,150,1)]
        rows,_=simulate(p,[(10,1)],'fifo','accepted',1,500)
        s=summarize(rows,0,[20])
        self.assertEqual(s['control_p99_ms'],10)
        self.assertAlmostEqual(s['control_miss_20ms'],2/3)
        self.assertFalse(s['control_pass_20ms'])
