import csv
import json
from pathlib import Path
import tempfile
import unittest
from converged_sim.coarse_observation import CONFIG,run
from converged_sim.audit_coarse_observation import audit


class AuditTests(unittest.TestCase):
    def test_raw_reconstruction_and_summary_tamper(self):
        cfg={**CONFIG,'loads':[.2],'seeds':[1],'profiles':['constant'],'queues':['fifo'],
             'measured':1000,'horizon':2000}
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);raw=d/'raw';run(raw,cfg);audit(raw,d/'verified')
            report=json.loads((d/'verified/audit.json').read_text())
            self.assertEqual(report['control_records'],1000)
            self.assertEqual(report['fifo_shadow_runs'],1)
            with (raw/'runs.csv').open('a') as h:h.write('\n')
            with self.assertRaisesRegex(ValueError,'summary changed'):audit(raw,d/'bad')
            self.assertFalse((d/'bad').exists())


if __name__=='__main__':unittest.main()
