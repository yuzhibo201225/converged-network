import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from converged_sim.q2_sweep import sweep
from converged_sim.q2_analysis import analyze


class Q2SweepTests(unittest.TestCase):
    def test_pairing_raw_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = {"base_config": {"warmup_control_packets": 8,
                "measured_control_packets": 24}, "loads": [0.6],
                "pmrs": [1, 3], "tau_bs": [2], "tau_ss": [2],
                "policies": ["fifo"], "seeds": [8]}
            config = root / "config.json"
            config.write_text(json.dumps(spec))
            sweep(config, root / "a")
            sweep(config, root / "b")
            self.assertEqual((root / "a/runs.csv").read_bytes(),
                             (root / "b/runs.csv").read_bytes())
            audit = analyze(root / "a", root / "analysis")
            self.assertEqual(audit["raw_control_rows"], 48)
            self.assertTrue((root / "analysis/p99_timescales.svg").exists())
            with (root / "a/runs.csv").open() as handle:
                runs = list(csv.DictReader(handle))
            self.assertEqual(runs[0]["service_trace_digest"], runs[1]["service_trace_digest"])
            self.assertEqual(runs[0]["offered_bulk_work_measured"], runs[1]["offered_bulk_work_measured"])
            with gzip.open(root / "a/control_packets.csv.gz", "rt") as handle:
                packets = list(csv.DictReader(handle))
            for index, run in enumerate(runs):
                cohort = [row for row in packets if int(row["run_id"]) == index]
                self.assertEqual(len(cohort), 24)
                misses = sum(row["deadline_miss"] == "True" for row in cohort)
                self.assertEqual(misses / 24, float(run["miss_ratio"]))
                delivered = sorted(float(row["latency"]) for row in cohort if row["status"] == "delivered")
                position = (len(delivered) - 1) * .99
                lower = int(position)
                p99 = delivered[lower] * (1 - position + lower) + delivered[min(lower + 1, len(delivered)-1)] * (position - lower)
                self.assertAlmostEqual(p99, float(run["p99"]))
            with self.assertRaises(FileExistsError):
                sweep(config, root / "a")

    def test_duplicate_grid_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"loads": [0.6, 0.6]}))
            with self.assertRaises(ValueError):
                sweep(config, root / "out")
            self.assertFalse((root / "out").exists())

    def test_raw_miss_flags_are_independently_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"base_config": {
                "warmup_control_packets": 8, "measured_control_packets": 24},
                "loads": [.6], "pmrs": [1], "tau_bs": [2], "tau_ss": [2],
                "policies": ["fifo"], "seeds": [8]}))
            sweep(config, root / "data")
            raw_path = root / "data/control_packets.csv.gz"
            with gzip.open(raw_path, "rt") as handle:
                reader = csv.DictReader(handle)
                fields, packets = reader.fieldnames, list(reader)
            # Keep the aggregate miss count unchanged while corrupting its
            # packet-level meaning. Source hashes are receipts, not truth.
            packets[0]["status"] = "dropped"
            with gzip.open(raw_path, "wt", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(packets)
            manifest_path = root / "data/manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["outputs_sha256"][raw_path.name] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "wrong raw miss flag"):
                analyze(root / "data", root / "analysis")
