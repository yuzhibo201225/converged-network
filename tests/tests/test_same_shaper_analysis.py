import csv
import tempfile
import unittest
from pathlib import Path
from converged_sim.same_shaper_analysis import SOURCE_FIELDS,source_pair,summarize


class SameShaperTests(unittest.TestCase):
    def write(self,path,rows):
        with path.open('w',newline='') as h:
            w=csv.DictWriter(h,fieldnames=SOURCE_FIELDS);w.writeheader();w.writerows(rows)

    def test_actual_release_and_not_just_generated_time_is_checked(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);row=dict(zip(SOURCE_FIELDS,('3','0','1','1.2','1.3','0','1','5')))
            self.write(root/'a.csv',[row]);self.write(root/'b.csv',[row])
            self.assertEqual(source_pair(root/'a.csv',root/'b.csv')[0],1)
            self.write(root/'b.csv',[dict(row,released_s='1.300000001')])
            with self.assertRaises(ValueError):source_pair(root/'a.csv',root/'b.csv')

    def test_missing_source_packet_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);row=dict(zip(SOURCE_FIELDS,('1','0','1','1','1','0','1','0')))
            self.write(root/'a.csv',[row]);self.write(root/'b.csv',[])
            with self.assertRaises(ValueError):source_pair(root/'a.csv',root/'b.csv')

    def test_pairs_not_independent_runs_and_median_of_differences(self):
        rows=[]
        for run in range(1,71):
            r=dict(rho=.95,tauS=4,run=run,control_delta=-.1,bulk_delta=.02)
            for policy in ('fifo','priority'):
                r[policy+'_control_pass']=True;r[policy+'_joint_pass']=True
                for name,v in (('control_p99_T',.5),('bulk_p99_T',7),('control_miss_ratio',0),('bulk_delivery',1),('source_max_work',8)):
                    r[policy+'_'+name]=v
            rows.append(r)
        p=summarize(rows)[0]
        self.assertEqual(p['n'],70);self.assertEqual(p['control_delta_negative_pairs'],70)
        self.assertEqual(p['bulk_delta_median'],.02)
        with self.assertRaises(ValueError):summarize(rows+[rows[0]])
