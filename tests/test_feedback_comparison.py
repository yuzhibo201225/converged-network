import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from converged_sim.feedback_comparison import compare


class PairingTests(unittest.TestCase):
    def test_digest_mismatch_fails_closed(self):
        common=dict(rho=".8",pmr="3",tau_b="8",tau_s="8",seed="1",
            service_digest="a",bulk_digest="b",bulk_offered_work="77",service_mean="1",
            control_p99_latency=".2",bulk_p99_latency="8",control_deadline_miss_ratio="0")
        candidate=dict(common,lag=".5")
        refs=[dict(common,policy="fifo",bucket=""),dict(common,policy="strict_priority",bucket=""),dict(common,policy="fifo",bucket=".1")]
        receipt=dict(status="PASS",source_receipt={})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch("converged_sim.feedback_comparison.read_source",side_effect=[([candidate],receipt),(refs,receipt)]),patch("converged_sim.feedback_comparison.figure"):
                result=compare("c","ca","r","ra",root/"ok")
            self.assertEqual(result["paired_contrasts"],3)
            refs[0]["service_digest"]="changed"
            with patch("converged_sim.feedback_comparison.read_source",side_effect=[([candidate],receipt),(refs,receipt)]):
                with self.assertRaisesRegex(ValueError,"unpaired service_digest"):
                    compare("c","ca","r","ra",root/"bad")
            self.assertFalse((root/"bad").exists())
