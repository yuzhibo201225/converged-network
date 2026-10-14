import csv
import json
from pathlib import Path
import tempfile
import unittest
from converged_sim.coarse_observation import CONFIG
from converged_sim.service_curve_baseline import predict,compare


class BaselineTests(unittest.TestCase):
    def test_contract_only_prediction_and_null_serialization(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);contract=d/'contract.json';contract.write_text(json.dumps({'config':CONFIG}))
            predict(contract,d/'prediction')
            with (d/'prediction/predictions.csv').open() as h:rows=list(csv.DictReader(h))
            self.assertEqual(len(rows),48)
            self.assertNotIn('profile',rows[0])
            self.assertNotIn('seed',rows[0])
            overloaded=next(r for r in rows if r['mode']=='minimum' and r['rho']=='0.8' and r['queue']=='fifo')
            self.assertEqual(overloaded['tail_cutoff_T'],'')
            self.assertEqual(overloaded['qualified'],'False')
            with self.assertRaises(FileExistsError):predict(contract,d/'prediction')

    def test_failed_raw_audit_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);contract=d/'contract.json';contract.write_text(json.dumps({'config':CONFIG}))
            predict(contract,d/'prediction')
            raw=d/'synthetic_fixture';raw.mkdir()
            (raw/'manifest.json').write_text(json.dumps({'runs_sha256':'invalid-test-fixture'}))
            (raw/'runs.csv').write_text('UNIT TEST FIXTURE ONLY\n')
            (d/'failed_audit.json').write_text(json.dumps({'status':'FAIL'}))
            with self.assertRaisesRegex(ValueError,'verified raw input'):
                compare(d/'prediction',raw/'runs.csv',d/'failed_audit.json',d/'rejected')
            self.assertFalse((d/'rejected').exists())


if __name__=='__main__':unittest.main()
