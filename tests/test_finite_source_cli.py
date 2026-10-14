import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from converged_sim.finite_source_cli import sweep


@unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("pandas"),"bundled Python required for raw parser")
class FiniteAuditTests(unittest.TestCase):
    def test_endpoints_and_independent_occupancy_replay(self):
        from converged_sim.finite_source_cli import audit
        from converged_sim.finite_clock_audit import audit as clock
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            spec=dict(measured=200,warmup=16,bucket=.1,loads=[.95],tau_s=8,
                arms=[dict(pmr=3,tau_b=8)],seeds=[19],settings=[dict(mode="fifo"),dict(mode="priority"),
                dict(mode="fixed",capacity=2),dict(mode="feedback",capacity=2,bias=-.1,lag=.5),dict(mode="feedback",capacity=16,bias=.1,lag=2)])
            (root/"config.json").write_text(json.dumps(spec))
            sweep(root/"config.json",root/"data",2)
            self.assertEqual(audit(root/"data",root/"endpoint")["status"],"PASS")
            result=clock(root/"data",root/"endpoint",root/"clock")
            self.assertEqual(result["runs"],5)
            self.assertEqual(result["status"],"PASS")
