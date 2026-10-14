import unittest
from converged_sim.ucc_split_screen import role,timestamp


class UccSplitTests(unittest.TestCase):
    def test_same_date_sessions_are_never_split_across_roles(self):
        a=role('Download/Static/B_2020.02.27_18.39.27.csv')
        b=role('Download/Car/X_2020.02.27_20.00.00.csv')
        self.assertEqual(a,b)

    def test_rate_values_do_not_enter_role_assignment(self):
        self.assertEqual(role('B_2019.12.16_13.40.04.csv'),role('B_2019.12.16_13.40.04.csv'))
        with self.assertRaises(ValueError):role('missing-date.csv')

    def test_unknown_time_format_not_silently_interpolated(self):
        self.assertIsNone(timestamp('unknown'))
        self.assertEqual(timestamp('2020.02.27_18:39:27').second,27)
