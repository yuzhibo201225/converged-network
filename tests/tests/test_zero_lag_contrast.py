"""Synthetic regression fixtures, separate from scientific results."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from converged_sim.zero_lag_contrast import compare


class ZeroLagContrastTests(unittest.TestCase):
    def maps(self):
        left={};right={}
        for mode in ('lowfirst','highfirst','coinflip'):
            for run in range(1,11):
                for bias in (0,.06):
                    r={k:'fixed' for k in ('rho','R','tauB','tauS','seed','T','warm','measured','shape','queue','capacity','arrival_digest','service_trace_digest','bulk_phase_fraction','lattice_fraction')}
                    r.update(run=str(run),bias=str(bias),lag='.5',control_p99_T='.8',control_miss_ratio='0',bulk_p99_T='8',bulk_delivery_ratio='1',admitted_rho='.95',joint_pass='True')
                    left[(mode,run,bias)]=r
                    right[(mode,run,bias)]=dict(r,lag='0',control_p99_T='.6')
        m=dict(source_sha256={'engine':'same'},executable_sha256='same');return left,right,m

    def test_paired_delta_not_independent_trial_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'audit.json').write_text('{}');left,right,m=self.maps()
            with patch('converged_sim.zero_lag_contrast.checked',side_effect=[(left,m,{}),(right,m,{})]):
                result=compare('unused',root,'unused',root,root/'out')
            self.assertEqual(result['pairs'],60)
            self.assertAlmostEqual(result['points'][0]['delta_control_p99_T_median'],-.2)
            self.assertIn('not independent',result['scope'])

    def test_unpaired_trace_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);left,right,m=self.maps();right[('coinflip',1,.06)]['service_trace_digest']='changed'
            with patch('converged_sim.zero_lag_contrast.checked',side_effect=[(left,m,{}),(right,m,{})]):
                with self.assertRaises(ValueError):compare('unused',root,'unused',root,root/'out')
            self.assertFalse((root/'out').exists())

    def test_wrong_lag_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);left,right,m=self.maps();right[('lowfirst',1,0)]['lag']='.5'
            with patch('converged_sim.zero_lag_contrast.checked',side_effect=[(left,m,{}),(right,m,{})]):
                with self.assertRaises(ValueError):compare('unused',root,'unused',root,root/'out')


if __name__=='__main__':unittest.main()
