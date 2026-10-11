"""Disposable packaging fixtures; all heads synthetic, no inference or network."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import finetuned_assist as assist
import package_submission as package
import test_finetuned_context_audit as fixtures


class ContextPackageProvenanceTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ContextAuditTests(methodName='runTest')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.repo=fixture.root;self.run=self.repo/'competition/runs/synthetic'
        (self.run/'work').mkdir(parents=True)
        model=self.repo/'integrations/learned-dialogue/minilm_ft_v2/model'
        shutil.copytree(fixture.model,model)
        runtime=self.run/'builder-source/finetuned-runtime'
        shutil.copytree(fixture.runtime,runtime)
        calls=self.run/'work/previous-failed-calls.json';shutil.copyfile(fixture.calls,calls)
        fixture.request.update(calls=str(calls),model_directory=str(model),runtime_directory=str(runtime))
        release=model.parent/'release.json'
        release.write_text(json.dumps({'manifest_sha256':fixture.request['manifest_sha256'],
                                      'runtime_sha256':fixture.request['runtime_sha256']}),encoding='utf8')
        self.full,self.audit,_,_,_=fixture.make_audit()
        self.fullpath=self.run/'work/finetuned-evidence.json'
        self.auditpath=self.run/'work/finetuned-context-evidence.json'
        self.requestpath=self.run/'finetuned-request.json'
        self.write(self.requestpath,fixture.request);self.write(self.fullpath,self.full);self.write(self.auditpath,self.audit)
        self.events=[{'kind':'finetuned_assist','status':'ready','version':'v2','bank_authority':False,
                      'artifact_sha256':assist.sha(self.fullpath)},
                     {'kind':'finetuned_context_audit','status':'AVAILABLE','bank_authority':False,
                      'artifact_sha256':assist.sha(self.auditpath)}]
        self.trace()

    def write(self,path,value):
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')

    def trace(self):
        (self.run/'trace.jsonl').write_text('\n'.join(json.dumps(e) for e in self.events)+'\n',encoding='utf8')

    def validate(self):
        return package.validate_run_evidence(self.run,self.repo)

    def test_valid_original_bindings_and_request_bytes_preserved(self):
        before=self.requestpath.read_bytes()
        result=self.validate()
        self.assertEqual(result['context'],'AVAILABLE')
        self.assertEqual(self.requestpath.read_bytes(),before)
        files=[(p,p.relative_to(self.repo).as_posix()) for p in result['bindings']]
        payload=package.archive_payload(files,result['bindings'])
        output=self.repo/'test.zip';package.write_verified_archive(output,payload,{'ancestry':['synthetic']})
        with zipfile.ZipFile(output) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(set(archive.namelist()),{v['path'] for v in manifest['files']}|{'manifest.json'})
            for item in manifest['files']:
                self.assertNotIn('\\',item['path'])
                self.assertEqual(archive.namelist().count(item['path']),1)
                self.assertEqual(__import__('hashlib').sha256(archive.read(item['path'])).hexdigest(),item['sha256'])

    def test_invalid_authority_rejected_even_with_fresh_trace_hash(self):
        self.audit['bank_authority']=True;self.audit['financial_authorization']='APPROVED'
        self.write(self.auditpath,self.audit);self.events[1]['artifact_sha256']=assist.sha(self.auditpath);self.trace()
        with self.assertRaises(ValueError):self.validate()

    def test_foreign_binding_rejected_even_with_fresh_trace_hash(self):
        self.audit['rows'][0]['call_index']=999
        self.write(self.auditpath,self.audit);self.events[1]['artifact_sha256']=assist.sha(self.auditpath);self.trace()
        with self.assertRaises(ValueError):self.validate()

    def test_trace_missing_and_conflicting_hashes_are_rejected(self):
        original=copy.deepcopy(self.events)
        for events in ([],original[:1],[dict(original[0],artifact_sha256='0'*64),original[1]],
                       original+[dict(original[1],artifact_sha256='0'*64)]):
            self.events=events;self.trace()
            with self.assertRaises(ValueError):self.validate()

    def test_older_round_hashes_and_versions_are_history_not_current_binding(self):
        self.events=[dict(self.events[0],artifact_sha256='0'*64,version='v1'),
                     dict(self.events[1],artifact_sha256='0'*64)]+self.events
        self.trace()
        self.assertEqual(self.validate()['context'],'AVAILABLE')
        self.events[-1]['artifact_sha256']='0'*64;self.trace()
        with self.assertRaises(ValueError):self.validate()

    def test_missing_request_or_full_companions_rejected(self):
        for path in (self.requestpath,self.fullpath):
            raw=path.read_bytes();path.unlink()
            try:
                with self.assertRaises((ValueError,OSError)):self.validate()
            finally:path.write_bytes(raw)

    def test_source_and_runtime_tampering_rejected(self):
        for path in (Path(self.fixture.request['calls']),Path(self.fixture.request['runtime_directory'])/'minilm_ft_core.py'):
            raw=path.read_bytes();path.write_bytes(b'changed')
            try:
                with self.assertRaises(ValueError):self.validate()
            finally:path.write_bytes(raw)

    def test_valid_unavailable_envelope_is_not_agreement(self):
        observations,skipped=assist._source(self.fixture.request)
        envelope=fixtures.audit.assemble_audit(self.fixture.request,self.full,observations,skipped,None,
                                               status='UNAVAILABLE',reason='DEADLINE')
        self.write(self.auditpath,envelope)
        self.events[1].update(status='UNAVAILABLE',artifact_sha256=assist.sha(self.auditpath));self.trace()
        self.assertEqual(self.validate()['context'],'UNAVAILABLE')

    def test_absent_audit_requires_explicit_unavailable_or_legacy_status(self):
        self.auditpath.unlink()
        with self.assertRaises(ValueError):self.validate()
        self.events[1]={'kind':'finetuned_context_audit','status':'UNAVAILABLE'};self.trace()
        self.assertEqual(self.validate()['context'],'UNAVAILABLE')
        self.events=self.events[:1];self.trace()
        self.assertEqual(self.validate()['context'],'ABSENT_LEGACY_V2')

    def test_classic_without_evidence_is_explicit_absence(self):
        self.fullpath.unlink();self.auditpath.unlink();self.events=[];self.trace()
        result=self.validate()
        self.assertEqual((result['full'],result['context']),('ABSENT','ABSENT'))
        self.assertIn(self.run/'trace.jsonl',result['bindings'])

    def test_v1_full_without_context_retains_legacy_validation(self):
        model=self.repo/'integrations/learned-dialogue/minilm_ft_v1/model'
        shutil.copytree(Path(self.fixture.request['model_directory']),model)
        manifest=assist.read_json(model/'manifest.json')
        del manifest['files']['architecture.json'];(model/'architecture.json').unlink()
        self.write(model/'manifest.json',manifest)
        self.fixture.request.update(model_directory=str(model),manifest_sha256=assist.sha(model/'manifest.json'))
        self.write(model.parent/'release.json',{'manifest_sha256':self.fixture.request['manifest_sha256'],
                                               'runtime_sha256':self.fixture.request['runtime_sha256']})
        full,_,_,_,_=self.fixture.make_audit()
        self.write(self.fullpath,full);self.write(self.requestpath,self.fixture.request);self.auditpath.unlink()
        self.events=[dict(self.events[0],version='v1',artifact_sha256=assist.sha(self.fullpath))];self.trace()
        self.assertEqual(self.validate()['context'],'ABSENT')

    def test_changed_bound_bytes_or_missing_archived_sources_rejected(self):
        bindings=self.validate()['bindings']
        files=[(p,p.relative_to(self.repo).as_posix()) for p in bindings]
        with self.assertRaises(ValueError):package.archive_payload(files[:-1],bindings)
        self.requestpath.write_bytes(b'changed after validation')
        with self.assertRaises(ValueError):package.archive_payload(files,bindings)

    def test_duplicate_names_source_collisions_and_windows_paths_rejected(self):
        cases=[[(self.fullpath,'a'),(self.auditpath,'a')],
               [(self.fullpath,'a'),(self.fullpath,'b')],[(self.fullpath,'work\\full.json')],
               [(self.fullpath,'../full.json')],[(self.fullpath,'manifest.json')]]
        for files in cases:
            with self.subTest(files=files):
                with self.assertRaises(ValueError):package.archive_payload(files,{})

    def test_relocated_original_paths_fail_closed_without_request_rewrite(self):
        self.fixture.request['calls']=str(self.repo/'missing-original.json')
        self.write(self.requestpath,self.fixture.request);before=self.requestpath.read_bytes()
        with self.assertRaises((ValueError,OSError)):self.validate()
        self.assertEqual(before,self.requestpath.read_bytes())


if __name__=='__main__':unittest.main()
