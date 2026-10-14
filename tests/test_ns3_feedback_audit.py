import unittest
from ns3_validation.feedback_cli import p99, source_replay


class SourceReplayTests(unittest.TestCase):
    def fixture(self):
        r=dict(T='.02',rho='.8',lag='0',bias='0',tauS='8',service_phase_fraction='0',
               stop_s='7',shape='fixed',capacity='16',source_max_work='.2')
        # Fixed refill .77 work/T: first packet immediate, subsequent two wait.
        arrivals=[0,.01,.02];releases=[0,.1/.77,.2/.77]
        ps=[dict(generated_s=str(1+a*.02),released_s=str(1+t*.02),source_drop='0')
            for a,t in zip(arrivals,releases)]
        return r,ps

    def test_clock_replay_and_r7(self):
        r,ps=self.fixture();source_replay(r,ps)
        self.assertAlmostEqual(p99([0,1,2]),1.98)

    def test_corrupted_release_rejected(self):
        r,ps=self.fixture();ps[1]['released_s']=str(float(ps[1]['released_s'])+.001)
        with self.assertRaises(ValueError): source_replay(r,ps)

    def test_quantized_immediate_releases_have_zero_actual_occupancy(self):
        r,ps=self.fixture();r['source_max_work']='0'
        ps=[]
        for i in range(200):
            t=round((1+(i+.043)*.1/.77*.02)*1e9)/1e9
            ps.append(dict(generated_s=str(t),released_s=str(t),source_drop='0'))
        source_replay(r,ps)

    def test_wrong_reported_occupancy_rejected(self):
        r,ps=self.fixture();r['source_max_work']='.3'
        with self.assertRaises(ValueError): source_replay(r,ps)
