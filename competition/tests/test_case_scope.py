import pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import builder
class CaseScopeTests(unittest.TestCase):
    def test_copy_of_public_cases_cannot_evaluate_an_unseen_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);brief=root/'new.md';brief.write_text('A different bank policy')
            copied=root/'alias.json';copied.write_text((builder.KIT/'public-test-set.json').read_text())
            with self.assertRaisesRegex(ValueError,'Unseen briefs'):builder.validate_case_scope([brief],copied,False)
    def test_a_and_its_amendment_have_distinct_test_cohorts(self):
        a=builder.KIT/'briefs/brief-a.md';b=builder.KIT/'briefs/brief-b.md'
        self.assertEqual(builder.infer_practice_group([a]),'A')
        self.assertEqual(builder.infer_practice_group([a,b]),'B')
        with tempfile.TemporaryDirectory() as directory:
            combined=pathlib.Path(directory)/'console.md';combined.write_text(a.read_text()+'\n\n'+b.read_text())
            self.assertEqual(builder.infer_practice_group([combined]),'B')
            combined.write_text(a.read_text()+'\nNew bank amendment that changes the policy.')
            self.assertIsNone(builder.infer_practice_group([combined]))
            with self.assertRaisesRegex(ValueError,'Unseen briefs'):
                builder.validate_case_scope([combined],builder.KIT/'public-test-set.json',False)
            builder.validate_case_scope([combined],builder.KIT/'public-test-set.json',True)
            builder.validate_case_scope([combined],pathlib.Path(directory)/'new-cases.json',False)
if __name__=='__main__':unittest.main()
