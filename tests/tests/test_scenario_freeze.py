import json
import tempfile
import unittest
from pathlib import Path
from converged_sim.scenario_predictor import run
from converged_sim.freeze_scenario_amendment import amend


class ScenarioFreezeTests(unittest.TestCase):
    def test_heldout_label_requires_frozen_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=root/'raw';raw.mkdir();analysis=root/'analysis';analysis.mkdir()
            (raw/'manifest.json').write_text('{}');(analysis/'audit.json').write_text('{}')
            with self.assertRaises(ValueError):run(raw,analysis,root/'out','heldout')
            self.assertFalse((root/'out').exists())

    def test_model_hash_mismatch_rejected_before_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=root/'raw';raw.mkdir();analysis=root/'analysis';analysis.mkdir()
            (raw/'manifest.json').write_text('{}');(analysis/'audit.json').write_text('{}')
            freeze=root/'freeze.json';freeze.write_text(json.dumps({'model_hashes':{}}))
            with self.assertRaises(ValueError):run(raw,analysis,root/'out','heldout',freeze)

    def test_amendment_cannot_ignore_nonzero_outcomes(self):
        from converged_sim.scenario_predictor import model_hashes
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);failed=root/'failed';failed.mkdir()
            (failed/'manifest.json').write_text(json.dumps(dict(status='FAILED',completed_runs=1,error='non-whole measurement cycles')))
            (root/'freeze.json').write_text(json.dumps(dict(model_hashes=model_hashes())))
            for name in ('old.json','new.json'):(root/name).write_text('{}')
            with self.assertRaises(ValueError):amend(root/'freeze.json',failed,root/'old.json',root/'new.json',root/'out.json')
            self.assertFalse((root/'out.json').exists())


if __name__=='__main__':unittest.main()
