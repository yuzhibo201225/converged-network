import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from converged_sim.robustness_cli import sweep,analyze


@unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("pandas"),"use bundled Python for C-parser audit crosscheck")
class IndependentAuditTests(unittest.TestCase):
    def test_adaptive_raw_audit(self):
        from converged_sim.fast_robustness_audit import audit
        from converged_sim.adaptive_cli import sweep as adaptive_sweep
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            spec=dict(model="delayed_capacity_feedback",measured=200,warmup=16,
                loads=[.8],arms=[dict(pmr=3,tau_b=8)],tau_ss=[8],
                lags=[0,.5,2],bucket=.1,seeds=[23])
            (root/"config.json").write_text(json.dumps(spec))
            adaptive_sweep(root/"config.json",root/"data",2)
            result=audit(root/"data",root/"audited")
            self.assertEqual(result["status"],"PASS")
            self.assertEqual(result["runs"],3)

    def test_independent_parsers_agree(self):
        from converged_sim.fast_robustness_audit import audit
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            spec=dict(measured=200,warmup=16,loads=[.6],arms=[dict(pmr=3,tau_b=8)],tau_ss=[2],
                profiles=[dict(jitter_bulk=True,jitter_service=True)],
                policies=[dict(policy="fifo"),dict(policy="fifo",bucket=.1)],seeds=[23])
            (root/"config.json").write_text(json.dumps(spec))
            sweep(root/"config.json",root/"data",2)
            standard=analyze(root/"data",root/"standard")
            independent=audit(root/"data",root/"independent")
            self.assertEqual(standard["raw_packets"],independent["raw_packets"])
            self.assertEqual((root/"standard/points.csv").read_text(),(root/"independent/points.csv").read_text())
