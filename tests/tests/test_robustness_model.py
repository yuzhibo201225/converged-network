import math
import json
import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from converged_sim.robustness_model import run, shape, service_trace, bulk_arrivals
from converged_sim.robustness_cli import sweep, analyze
from converged_sim.shaper_accounting import account
from converged_sim.scientific_figures import robustness


class RobustnessTests(unittest.TestCase):
    def test_balanced_jittered_service(self):
        trace = service_trace(256.,10256.,10800.,8.,22,True)
        self.assertAlmostEqual(trace.integrate(0.,256.),256.,places=8)
        self.assertAlmostEqual(trace.integrate(256.,10256.),10000.,places=8)
        widths = [trace.ends[i]-trace.starts[i] for i in range(0,len(trace.ends),2)]
        self.assertGreater(len(set(round(w,6) for w in widths)),10)

    def test_work_matches_all_traffic_arms(self):
        counts = []
        for jitter in (False,True):
            for pmr,tau in ((1,2),(3,.5),(3,8)):
                arrivals = bulk_arrivals(256.,10256.,10768.,.57,pmr,tau,32,jitter)
                counts.append(sum(256 <= a < 10256 for a in arrivals))
                self.assertEqual(arrivals,sorted(arrivals))
        self.assertEqual(len(set(counts)),1)

    def test_token_bucket_envelope_and_source_causality(self):
        arrivals = [0.]*10+[2.]*3
        releases = shape(arrivals,.5,.2)
        self.assertEqual(releases,sorted(releases))
        self.assertTrue(all(r>=a for a,r in zip(arrivals,releases)))
        for i in range(len(releases)):
            for j in range(i,len(releases)):
                self.assertLessEqual((j-i+1)*.1,.2+.5*(releases[j]-releases[i])+1e-10)
        self.assertAlmostEqual(releases[0],0.)
        self.assertAlmostEqual(releases[1],0.)
        with self.assertRaises(ValueError): shape(arrivals,1.,.05)

    def test_end_to_end_shaper_delay_and_pairing(self):
        common = dict(rho=.6,pmr=3,tau_b=8,tau_s=2,seed=30,measured=1000)
        plain = run(**common)
        shaped = run(**common,bucket=.1)
        self.assertEqual(plain["bulk_offered_work"],shaped["bulk_offered_work"])
        self.assertEqual(plain["bulk_digest"],shaped["bulk_digest"])
        self.assertEqual(plain["service_digest"],shaped["service_digest"])
        self.assertGreater(shaped["shaper_max_delay"],0.)
        for packet in shaped["packets"]:
            if packet["status"]=="delivered":
                self.assertAlmostEqual(packet["completion"]-packet["arrival"],packet["latency"])
                self.assertGreaterEqual(packet["latency"]+1e-10,packet["shaper_delay"])
        self.assertEqual(shaped,run(**common,bucket=.1))

    def test_all_policies_and_control_cohort(self):
        for policy in ("fifo","strict_priority","drr"):
            result = run(.8,3,8,8,43,policy=policy,measured=200)
            control = result["summaries"]["control"]
            self.assertEqual(control["generated"],200)
            self.assertEqual(control["unfinished"],0)
            self.assertTrue(math.isclose(result["service_mean"],1.))

    def test_parallel_sweep_and_all_class_raw_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cfg=dict(measured=100,warmup=16,loads=[.6],arms=[dict(pmr=1,tau_b=2),dict(pmr=3,tau_b=8)],
                tau_ss=[2],profiles=[dict(jitter_bulk=True,jitter_service=True)],
                policies=[dict(policy="fifo"),dict(policy="fifo",bucket=.1)],seeds=[3])
            (root/"config.json").write_text(json.dumps(cfg))
            manifest=sweep(root/"config.json",root/"data",2)
            self.assertEqual(manifest["completed_runs"],4)
            receipt=analyze(root/"data",root/"analysis")
            self.assertEqual(receipt["status"],"PASS")
            self.assertGreater(receipt["raw_packets"],400)
            replay=account(root/"data",root/"analysis",root/"source_replay")
            self.assertEqual(replay["status"],"PASS")
            self.assertEqual(replay["unique_envelopes"],4)
            robustness(root/"analysis",root/"figure.svg")
            ET.parse(root/"figure.svg")
