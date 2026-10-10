import pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import builder
class PracticeSeedTests(unittest.TestCase):
    def test_unseen_evidence_cannot_use_practice_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);(root/'kit/briefs').mkdir(parents=True);(root/'work/inputs').mkdir(parents=True)
            (root/'kit/briefs/brief-a.md').write_text('public practice');(root/'work/inputs/01-email.md').write_text('new final brief')
            with patch.object(builder,'KIT',root/'kit'):
                with self.assertRaisesRegex(ValueError,'unseen builds must start fresh'):builder.validate_practice_seed(root/'work',root/'seed',[{'path':'inputs/01-email.md'}])
    def test_omitting_a_prior_amendment_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            for path in ('kit/briefs','work/inputs','seed/work/inputs'):(root/path).mkdir(parents=True)
            for path,text in [('kit/briefs/brief-a.md','A'),('kit/briefs/brief-b.md','B'),('work/inputs/01-brief-a.md','A'),('seed/work/inputs/01-brief-a.md','A'),('seed/work/inputs/02-brief-b.md','B')]: (root/path).write_text(text)
            with patch.object(builder,'KIT',root/'kit'):
                with self.assertRaisesRegex(ValueError,'complete document set'):builder.validate_practice_seed(root/'work',root/'seed',[{'path':'inputs/01-brief-a.md'}])
if __name__=='__main__':unittest.main()
