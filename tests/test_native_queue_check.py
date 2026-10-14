import unittest
from converged_sim.native_queue_check import audit_rows

class QueueAuditTests(unittest.TestCase):
    def rows(self):
        return [dict(variant=v,event='drained',resident='0',counter=c,dropped=d,light_bypass=b)
                for v,c,d,b in [('original_drop','1','1','0'),
                                ('original_no_drop','0','0','1'),
                                ('corrected_drop','0','1','1')]]
    def test_expected_counterexample(self):
        self.assertEqual(len(audit_rows(self.rows())),3)
    def test_rejects_incorrect_bypass(self):
        rows=self.rows(); rows[0]['light_bypass']='1'
        with self.assertRaises(AssertionError): audit_rows(rows)
    def test_rejects_incorrect_accounting(self):
        rows=self.rows(); rows.append(dict(variant='original_drop',event='other',resident='0',counter='2',dropped='1'))
        with self.assertRaises(AssertionError): audit_rows(rows)
