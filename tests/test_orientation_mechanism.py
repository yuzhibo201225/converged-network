"""Synthetic fixtures only, never used as scientific experiment results."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from converged_sim.orientation_mechanism import analyze
from ns3_validation.renewal_cli import digest


class OrientationMechanismTests(unittest.TestCase):
    def fixture(self,root,missing=False):
        raw=root/'raw';raw.mkdir();(raw/'manifest.json').write_text('{}')
        analysis=root/'analysis';analysis.mkdir();rows=[]
        for mode in ('lowfirst','highfirst','coinflip'):
            for seed in range(1,11):
                for bias in (0,.06):
                    if missing and mode=='coinflip' and seed==10 and bias==.06:continue
                    value=.5+ (bias>0)*.2+(mode=='coinflip')*(.4 if bias else -.01)
                    rows.append(dict(ordering=mode,run=seed,bias=bias,shape='feedback',control_p99_T=value))
        with (analysis/'runs.csv').open('w',newline='') as handle:
            w=csv.DictWriter(handle,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        receipt=dict(status='PASS',manifest_sha256=digest(raw/'manifest.json'),runs_sha256=digest(analysis/'runs.csv'))
        (analysis/'audit.json').write_text(json.dumps(receipt));return raw,analysis

    def test_paired_difference_in_differences_and_posthoc_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw,analysis=self.fixture(root)
            with patch('converged_sim.orientation_mechanism.describe',return_value=([{'run':1}],{'traces':10},'unused')):
                result=analyze(raw,analysis,root/'out')
            self.assertAlmostEqual(result['paired_contrasts']['interaction_T']['median'],.41)
            self.assertIn('post-hoc',result['scope'])

    def test_missing_pair_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw,analysis=self.fixture(root,True)
            with self.assertRaises(ValueError):analyze(raw,analysis,root/'out')
            self.assertFalse((root/'out').exists())

    def test_changed_run_table_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw,analysis=self.fixture(root)
            with (analysis/'runs.csv').open('a') as handle:handle.write('\n')
            with self.assertRaises(ValueError):analyze(raw,analysis,root/'out')
            self.assertFalse((root/'out').exists())


if __name__=='__main__':unittest.main()
