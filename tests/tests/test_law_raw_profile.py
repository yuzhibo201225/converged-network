import tempfile
import unittest
from pathlib import Path
from converged_sim.law_raw_profile import verify
from ns3_validation.renewal_cli import dump


class LawProfileTests(unittest.TestCase):
    def test_multimode_input_does_not_use_single_mode_adapter(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'raw';source.mkdir()
            dump(source/'manifest.json',dict(status='COMPLETE',spec=dict(modes=['lowfirst','coinflip'])))
            with self.assertRaises(ValueError):verify(source,root/'partial',root/'out')
            self.assertFalse((root/'out').exists())

    def test_completed_parent_audit_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'raw';source.mkdir();partial=root/'partial';partial.mkdir()
            dump(source/'manifest.json',dict(status='COMPLETE',spec=dict(modes=['coinflip'])))
            dump(partial/'audit.json',dict(status='PASS'))
            with self.assertRaises(ValueError):verify(source,partial,root/'out')
            self.assertFalse((root/'out').exists())
