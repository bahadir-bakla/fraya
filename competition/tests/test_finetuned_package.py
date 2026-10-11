"""Submission copy must retain exact trained-model/runtime pins."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_submission import finetuned_files


class FinetunedPackageTests(unittest.TestCase):
    def make_release(self, root):
        base=root/'integrations/learned-dialogue'
        model=base/'minilm_ft_v1/model'
        files={}
        for name in ('head.safetensors','encoder/model.safetensors','encoder/config.json'):
            path=model/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'fixture');files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        runtime={}
        for name in ('minilm_ft_core.py','minilm_ft_eval.py'):
            path=base/name;path.write_bytes(b'fixture-runtime')
            runtime[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        labels=['proposal','dispute','correction','current_affirm','current_withdraw','uncertain','reported_third_party','AFFIRM','NEGATE','INFORM','REQUEST']
        manifest=model/'manifest.json'
        manifest.write_text(json.dumps({'files':files,'labels':labels,'thresholds':[1.01]*11,'bank_authority':False}),encoding='utf8')
        (base/'minilm_ft_v1/release.json').write_text(json.dumps({'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'runtime_sha256':runtime}),encoding='utf8')
        return base,model

    def test_classic_without_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(finetuned_files(Path(tmp)),[])

    def test_exact_model_and_runtime_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.make_release(root)
            entries=finetuned_files(root)
            self.assertEqual(len(entries),7)
            self.assertTrue(all(p.is_file() and name==p.relative_to(root).as_posix() for p,name in entries))

    def test_changed_encoder_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,model=self.make_release(root)
            (model/'encoder/model.safetensors').write_bytes(b'changed')
            with self.assertRaises(ValueError):finetuned_files(root)

    def test_changed_runtime_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base,_=self.make_release(root)
            (base/'minilm_ft_core.py').write_bytes(b'changed')
            with self.assertRaises(ValueError):finetuned_files(root)


if __name__=='__main__':unittest.main()
