import csv
import json
import tempfile
import unittest
from pathlib import Path
from converged_sim.audit_law_admission import audit
from converged_sim.scenario_predictor import model_hashes
from ns3_validation.renewal_cli import digest,dump


class LawAuditTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source';source.mkdir();(source/'traces').mkdir()
        trace=source/'traces'/'4-1.csv';trace.write_text('1,0.7\n')
        spec=dict(loads=[.9],tauS_values=[4],R=3,tauB=8,lag=.5,bias=.06,capacity=16,
                  warm=8,measured=24,draws=1,forecast_phase_seed=20261018,forecast_trace_seed_base=200000,q=.9,alpha=.05)
        row=dict(rho=.9,tauS=4,draw=1,control_p99_T=.4,control_miss_ratio=0,control_pass=True,bulk_delivery=1,trace_sha256=digest(trace))
        point=dict(rho=.9,tauS=4,successes=1,lower=.05,qualified=False)
        for name,r in (('draws.csv',row),('decisions.csv',point)):
            with (source/name).open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(r));w.writeheader();w.writerow(r)
        hashes=model_hashes();project=Path(__file__).parents[1]
        for p in ('converged_sim/law_admission.py','converged_sim/traffic_contract.py','converged_sim/reliability_boundary.py',
                  'ns3_validation/orientation_cli.py','ns3_validation/order_cli.py'):hashes[p]=digest(project/p)
        manifest=dict(status='COMPLETE',spec=spec,completed=1,planned=1,source_sha256=hashes,
                      outputs_sha256={n:digest(source/n) for n in ('draws.csv','decisions.csv')})
        dump(source/'manifest.json',manifest);return source,manifest

    def test_checked_counts_do_not_promote_one_draw_to_qualification(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source,_=self.fixture(root)
            self.assertEqual(audit(source,root/'check')['cells'],1)

    def test_changed_decision_export_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source,_=self.fixture(root)
            with (source/'decisions.csv').open('a') as h:h.write('\n')
            with self.assertRaises(ValueError):audit(source,root/'check')

    def test_missing_model_hashes_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source,m=self.fixture(root);m['source_sha256']={};dump(source/'manifest.json',m)
            with self.assertRaises(ValueError):audit(source,root/'check')
