import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from validation import validate_coverage


class CoverageCompatibilityTests(unittest.TestCase):
    def test_explicit_rule_id_inventory_is_supported(self):
        self.assertEqual(validate_coverage({'coverage':[{'rule_id':'R1','status':'implemented','implementation':'security gate'}]}),[])

    def test_blank_identifier_is_not_substantive_rule_coverage(self):
        self.assertTrue(validate_coverage({'coverage':[{'rule_id':' ','status':'implemented'}]}))
