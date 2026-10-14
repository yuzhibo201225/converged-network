import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from converged_sim.source_receipts import generate


def fixture(root: Path) -> Path:
    results = root / "results"
    (results / "factorial_refined_analysis").mkdir(parents=True)
    for regime in ("constant", "moderate", "strong"):
        sources = {}
        for stage, folder in (("coarse", "factorial_coarse"),
                              ("refinement", "factorial_refinement")):
            source = results / folder / regime
            source.mkdir(parents=True)
            contents = {
                "config.json": b"{}\n",
                "runs.csv": f"rho,pmr,seed\n0.2,1,0\n{regime},{stage},x\n".encode(),
                "control_packets.csv.gz": f"raw {regime} {stage}".encode(),
            }
            for name, data in contents.items():
                (source / name).write_bytes(data)
            sources[stage] = {
                "path": str(source.resolve()),
                "config_sha256": hashlib.sha256(contents["config.json"]).hexdigest(),
                "runs_sha256": hashlib.sha256(contents["runs.csv"]).hexdigest(),
            }
        merged = results / "factorial_merged" / regime
        merged.mkdir(parents=True)
        (merged / "provenance.json").write_text(
            json.dumps({"sources": sources}), encoding="utf-8"
        )
    return results


class SourceReceiptTests(unittest.TestCase):
    def test_audits_all_six_and_records_raw_hashes_without_touching_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            results = fixture(Path(temp))
            with patch("converged_sim.source_receipts.audit", return_value={
                "status": "PASS", "runs": 2, "control_packets": 20004,
            }) as mocked:
                receipt = generate(results)
            self.assertEqual(mocked.call_count, 6)
            self.assertEqual(receipt["totals"], {
                "source_sweeps": 6, "runs": 12, "control_packets": 120024,
            })
            saved = json.loads((results / "factorial_refined_analysis" /
                                "source_audit_receipts.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "PASS")
            for entry in saved["sources"]:
                raw = Path(entry["source"]) / "control_packets.csv.gz"
                self.assertEqual(entry["sha256"]["control_packets.csv.gz"],
                                 hashlib.sha256(raw.read_bytes()).hexdigest())
                self.assertTrue(entry["merged_provenance_match"])
            with self.assertRaises(FileExistsError):
                generate(results)

    def test_mismatched_summary_provenance_writes_no_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            results = fixture(Path(temp))
            path = results / "factorial_merged" / "constant" / "provenance.json"
            provenance = json.loads(path.read_text(encoding="utf-8"))
            provenance["sources"]["coarse"]["runs_sha256"] = "invalid"
            path.write_text(json.dumps(provenance), encoding="utf-8")
            with patch("converged_sim.source_receipts.audit", return_value={
                "status": "PASS", "runs": 2, "control_packets": 20004,
            }), self.assertRaisesRegex(ValueError, "runs hash mismatch"):
                generate(results)
            self.assertFalse((results / "factorial_refined_analysis" /
                              "source_audit_receipts.json").exists())

    def test_rejects_output_outside_analysis_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            results = fixture(Path(temp))
            with self.assertRaisesRegex(ValueError, "output must be directly inside"):
                generate(results, results / "other.json")


if __name__ == "__main__":
    unittest.main()
