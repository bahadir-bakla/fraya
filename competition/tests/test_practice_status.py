import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from builder import practice_seed_stopped_or_untested


class PracticeStatusTests(unittest.TestCase):
    def test_explicit_untested_artifact_can_be_repaired_under_new_public_cycle(self):
        self.assertTrue(practice_seed_stopped_or_untested({'phase':'completed','evaluation':'not_evaluated'}))

    def test_unknown_or_successful_evaluation_is_not_an_untested_seed(self):
        for prior in [{'phase':'completed'},{'phase':'completed','evaluation':'official_practice'},{'phase':'model_build','evaluation':'not_evaluated'}]:
            self.assertFalse(practice_seed_stopped_or_untested(prior))
