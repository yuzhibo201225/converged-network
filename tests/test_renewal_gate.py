import csv
import tempfile
import unittest
from pathlib import Path
from ns3_validation.renewal_gate import replay


class RenewalGateTests(unittest.TestCase):
    def test_prefix_causality_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.csv';trace=[(1,.7),(1.003,1.3),(1.01,.7),(1.2,1.3)]
            with path.open('w',newline='') as h: csv.writer(h).writerows(trace)
            row=dict(T='.02',rho='.95',lag='.5',tauS='8',service_phase_fraction='0',
                     bias='0',capacity='16',shape='feedback',nominal_bps='6000000',traceCsv=str(path))
            packets=[dict(generated_s=str(1+i*.000001)) for i in range(40)]
            full=replay(row,packets)
            self.assertEqual(full[:10],replay(row,packets[:10]))
            for i,t in enumerate(full):
                breaks=[1]+[a+.01 for a,_ in trace[1:] if a+.01<t]+[t]
                integral=0
                for a,b in zip(breaks,breaks[1:]):
                    probe=(a+b)/2-.01;factor=trace[0][1]
                    for start,value in trace:
                        if start<=probe: factor=value
                    integral+=(b-a)*(.95*factor-.03)*6000000
                self.assertLessEqual((i+1)*12000,12000+integral+.01)
            trace[-1]=(1.2,.7)
            with path.open('w',newline='') as h: csv.writer(h).writerows(trace)
            self.assertEqual(full,replay(row,packets))

    def test_finite_source_drops_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.csv';path.write_text('1,0.7\n')
            row=dict(T='.02',rho='.95',lag='.5',tauS='8',service_phase_fraction='0',
                     bias='0',capacity='.1',shape='feedback',traceCsv=str(path))
            packets=[dict(generated_s=str(1+i*.000001)) for i in range(20)]
            released=replay(row,packets)
            self.assertEqual(sum(r is None for r in released),18)
