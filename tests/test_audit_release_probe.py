import json
from pathlib import Path
import tempfile
import unittest
from converged_sim.audit_release_probe import audit


class ReleaseAuditTests(unittest.TestCase):
    def test_changed_receipt_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);raw=d/'unit-fixture';raw.mkdir()
            (raw/'manifest.json').write_text(json.dumps({'frozen_sha256':'invalid-test-hash'}))
            (raw/'frozen.json').write_text(json.dumps({'model_sha256':{}}))
            with self.assertRaisesRegex(ValueError,'receipts changed'):audit(raw,d/'rejected')
            self.assertFalse((d/'rejected').exists())


if __name__=='__main__':unittest.main()
