import pathlib,sys,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import builder
class RoundsDefaultTests(unittest.TestCase):
    def parse(self,*extra):
        with patch.object(sys,'argv',['builder.py',str(builder.KIT/'briefs/brief-a.md'),'--model','test',*extra]):return builder.arguments()
    def test_skip_tests_uses_the_whole_budget_with_six_rounds(self):self.assertEqual(self.parse('--skip-tests').rounds,6)
    def test_tested_runs_keep_three_rounds_to_bound_test_count(self):self.assertEqual(self.parse().rounds,3)
    def test_explicit_rounds_win(self):self.assertEqual(self.parse('--skip-tests','--rounds','2').rounds,2)
if __name__=='__main__':unittest.main()
