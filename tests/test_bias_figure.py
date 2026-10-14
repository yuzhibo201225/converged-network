import csv
import json
import tempfile
import unittest
from pathlib import Path
from converged_sim.bias_figure import plot


class BiasFigureTests(unittest.TestCase):
    def fixture(self, root):
        endpoint=root/"endpoint";source=root/"source"
        endpoint.mkdir();source.mkdir()
        receipt={"status":"PASS","source_receipt":{"packets.csv.gz":"fixture"}}
        for d in (endpoint,source): (d/"audit.json").write_text(json.dumps(receipt))
        rows=[]
        for pmr in (1,3):
            for bias in (0,.02,.03,.04,.05,.06,.08,.1):
                r=dict(rho=.95,lag=.5,capacity=16,pmr=pmr,bias=bias,bulk_delivery_ratio_min=1,
                       link_offered_rho_min=.94973,link_offered_rho_max=.95018)
                for field,value in (("control_p99_latency",.5+bias*20),("control_deadline_miss_ratio",bias*2)):
                    for suffix in ("median","min","max"): r[field+"_"+suffix]=value
                rows.append(r)
        with (endpoint/"points.csv").open("w",newline="") as h:
            w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        return endpoint,source

    def test_deterministic_replot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);endpoint,source=self.fixture(root)
            plot(endpoint,source,root/"first.svg");plot(endpoint,source,root/"second.svg")
            self.assertEqual((root/"first.svg").read_bytes(),(root/"second.svg").read_bytes())
            self.assertIn(".94973-0.95018",(root/"first.svg").read_text())

    def test_mismatched_receipts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);endpoint,source=self.fixture(root)
            (source/"audit.json").write_text(json.dumps(dict(status="PASS",source_receipt={})))
            with self.assertRaises(ValueError): plot(endpoint,source,root/"bad.svg")
