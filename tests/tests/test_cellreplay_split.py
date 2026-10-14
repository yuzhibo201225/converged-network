import unittest
from converged_sim.cellreplay_split import ROLES,COMPONENTS,assign


class CellReplaySplitTests(unittest.TestCase):
    def rows(self):
        return [dict(member_path=f'{g}/{c}',uncompressed_bytes='1',compressed_bytes='1') for g in ROLES for c in COMPONENTS]

    def test_complete_groups_and_operator_holdout(self):
        rows=assign(self.rows())
        self.assertEqual(sum(r['role']=='development' for r in rows),12)
        self.assertEqual(sum(r['role']=='calibration' for r in rows),6)
        self.assertEqual(sum(r['role']=='reserved' for r in rows),18)
        self.assertTrue(all(r['role']=='reserved' for r in rows if r['group'].startswith('verizon/')))

    def test_partial_duplicate_unknown_rejected(self):
        rows=self.rows()
        for bad in (rows[:-1],rows+[rows[0]],rows+[dict(member_path='unknown/a/b',uncompressed_bytes='1',compressed_bytes='1')]):
            with self.assertRaises(ValueError):assign(bad)


if __name__=='__main__':unittest.main()
