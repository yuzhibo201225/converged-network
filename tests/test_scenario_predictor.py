import tempfile
import unittest
from pathlib import Path
from converged_sim.scenario_predictor import Emission,predict


class ScenarioPredictorTests(unittest.TestCase):
    def inputs(self,path):
        return dict(rho='.95',shape='feedback',queue='fifo',bias='0',lag='0',capacity='16',T='.02',tauS='8',nominal_bps='6000000',
                    traceCsv=str(path),warm='0',measured='100',begin_s='1',end_s='3',stop_s='4',service_phase_fraction='0')

    def test_constant_service_packet_and_fluid_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.csv';path.write_text('1,1\n')
            r=predict(self.inputs(path),[Emission(3,0,1.),Emission(1,0,1.0002)])
            a=r['delays']['packet'][1][0];b=r['delays']['fluid'][1][0]
            self.assertAlmostEqual(a,b,places=6)
            self.assertGreater(a,.05)

    def test_outcome_fields_rejected_and_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.csv';path.write_text('1,1\n');parameters=self.inputs(path)
            with self.assertRaises(ValueError):predict(dict(parameters,received_s='2'),[Emission(1,0,1.)])
            with self.assertRaises(ValueError):predict(parameters,[dict(flow=1,id=0,generated_s=1.,received_s=2.)])
            with self.assertRaises(ValueError):predict(parameters,[Emission(1,0,1.),Emission(1,0,1.)])

    def test_unsupported_access_overflow_rejected_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trace.csv';path.write_text('1,1\n')
            with self.assertRaises(ValueError):predict(self.inputs(path),[Emission(1,i,1.) for i in range(22)])


if __name__=='__main__':unittest.main()
