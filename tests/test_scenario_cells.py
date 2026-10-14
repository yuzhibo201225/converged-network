import unittest
from converged_sim.scenario_cells import FIELDS,key


class ScenarioCellTests(unittest.TestCase):
    def row(self):return {f:('feedback' if f=='shape' else 'fifo' if f=='queue' else '1') for f in FIELDS}
    def test_lag_and_observation_window_are_distinct_cells(self):
        a=self.row()
        self.assertNotEqual(key(a),key(dict(a,lag='0')))
        self.assertNotEqual(key(a),key(dict(a,measured='10008')))
        self.assertNotEqual(key(a),key(dict(a,capacity='16')))
    def test_numeric_representation_does_not_split_cells(self):
        a=self.row();self.assertEqual(key(a),key(dict(a,rho='1.0000')))


if __name__=='__main__':unittest.main()
