import json
from pathlib import Path
import tempfile
import unittest
from converged_sim.plot_course_repeats import run


class PlotCourseRepeatsTests(unittest.TestCase):
    def test_reject_unaudited_without_output(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            source = p / 'input'
            source.mkdir()
            (source / 'audit.json').write_text(json.dumps({'status': 'FAIL'}))
            with self.assertRaises(AssertionError):
                run(source, p, p / 'out')
            self.assertFalse((p / 'out').exists())

    def test_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            with self.assertRaises(FileExistsError):
                run(p / 'missing', p, p)
