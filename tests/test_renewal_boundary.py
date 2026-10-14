import csv
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from converged_sim.renewal_boundary import sweep,analyze
from converged_sim.reliability_boundary import clopper_pearson_lower
from converged_sim.scientific_figures import boundary


class RenewalBoundaryTests(unittest.TestCase):
    def test_global_all_success_lower_bound_is_feasible(self):
        lower=clopper_pearson_lower(70,70,.05/48)
        self.assertGreater(lower,.9)
        self.assertAlmostEqual(lower,(.05/48)**(1/70),places=12)

    def test_raw_audit_and_contiguous_censoring(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=dict(measured=100,warmup=16,loads=[.2,.3],arms=[dict(pmr=1,tau_b=2),dict(pmr=3,tau_b=8)],
                tau_s=2,q=.9,alpha=.05,seeds=[13,14])
            (root/"config.json").write_text(json.dumps(config))
            manifest=sweep(root/"config.json",root/"data",2)
            self.assertEqual(manifest["completed_runs"],8)
            result=analyze(root/"data",root/"analysis")
            self.assertEqual(result["raw_control_packets"],800)
            self.assertEqual(result["familywise_points"],4)
            with (root/"analysis/boundaries.csv").open() as handle: boundaries=list(csv.DictReader(handle))
            certified=[r for r in boundaries if r["estimator"]=="familywise_lower"]
            self.assertTrue(all(r["censoring"]=="left" for r in certified))
            boundary(root/"analysis",root/"figure.svg")
            ET.parse(root/"figure.svg")
            with self.assertRaises(FileExistsError): sweep(root/"config.json",root/"data",2)
