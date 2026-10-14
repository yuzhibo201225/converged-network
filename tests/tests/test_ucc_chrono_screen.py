import unittest
from converged_sim.ucc_chrono_screen import chronology


class ChronologyTests(unittest.TestCase):
    def test_latest_dates_sealed_and_same_date_not_split(self):
        paths=['A_2019.12.14_x.csv','B_2019.12.14_y.csv','C_2020.02.14_x.csv','D_2020.02.27_x.csv']
        r=chronology(paths)
        self.assertEqual(r[paths[0]][1],'development');self.assertEqual(r[paths[1]],r[paths[0]])
        self.assertEqual(r[paths[2]][1],'calibration');self.assertEqual(r[paths[3]][1],'validation')

    def test_insufficient_dates_fail_before_reading_values(self):
        with self.assertRaises(ValueError):chronology(['A_2020.02.27_x.csv'])
