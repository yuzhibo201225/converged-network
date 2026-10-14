import unittest
from converged_sim.service_curve_headroom import ceiling


class HeadroomTests(unittest.TestCase):
    def test_ambiguous_worlds_do_not_create_headroom(self):
        rows=[dict(mode='budget',rho='.4',queue='fifo',seed='1',profile=p,
                   qualified='False',observed_joint_pass='False' if p=='coarse' else 'True')
              for p in ('constant','fine','coarse')]
        g=ceiling(rows)[0]
        self.assertEqual(g['passing_worlds'],2)
        self.assertTrue(g['observed_ceiling_matches_budget'])
        self.assertTrue(g['unsafe_witness_blocks_universal_qualification'])

    def test_incomplete_and_inconsistent_rejected(self):
        rows=[dict(mode='budget',rho='.4',queue='fifo',seed='1',profile=p,
                   qualified='True',observed_joint_pass='True') for p in ('constant','fine','coarse')]
        with self.assertRaises(ValueError):ceiling(rows[:2])
        rows[0]['qualified']='False'
        with self.assertRaises(ValueError):ceiling(rows)


if __name__=='__main__':unittest.main()
