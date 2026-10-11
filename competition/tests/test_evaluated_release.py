"""Offline release/evaluation binding checks; no hosted calls or model work."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import repair_evaluated_release as repair

class EvaluatedReleaseTests(unittest.TestCase):
    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value))

    def mutate(self,path,operation):
        value=json.loads(path.read_text());operation(value);self.write(path,value)

    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.release=self.root/'candidate';self.evaluation=self.root/'evaluation'
        self.workflow={'nodes':{'talk':{'prompt':'Original prompt','transitions':[{'target_node':'end'}]}},'initial_node':'talk'}
        for name,value in [('workflow.json',self.workflow),('policy.json',{}),('coverage.json',{})]:self.write(self.release/name,value)
        self.repin()
        self.ids={'workflow_id':'workflow-1','agent_id':'agent-1','version':1}
        scopes={}
        for scope in ('public-a','stress-in-words'):
            folder=self.evaluation/scope
            self.write(folder/'published.json',self.ids)
            self.write(folder/'published-version.json',{'id':'version-1','entityId':'workflow-1','versionNumber':1,'isPublished':True})
            exported=copy.deepcopy(self.workflow);exported['nodes']['talk']['platform_default']=False
            self.write(folder/'platform-export.workflow.json',dict(self.ids,workflow=exported))
            call={'id':scope+'-call','assistantId':'agent-1','assistantWorkflowId':'workflow-1','entityVersionId':'version-1','entityVersionNumber':1,'messages':[]}
            call_path=folder/'calls'/f"{call['id']}.json";self.write(call_path,call)
            self.write(folder/'repetition-1.json',{'repetition':1,'published':self.ids,'version_id':'version-1','rows':[{'id':'PUB-01','call_id':call['id'],'pass':False,'failed':['Original failure']}]})
            self.write(folder/'direct-provenance.json',{'calls':[{'rep':1,'case':'PUB-01','call_id':call['id'],'call_sha256':repair.sha(call_path),'combined_pass':False,'agent_workflow_version_verified':True}]})
            scopes[scope]={'published':self.ids}
        self.write(self.evaluation/'results.json',{'candidate':self.release.name,'evaluation_completed':True,'scopes':scopes})
        self.pin_source()

    def repin(self):
        self.write(self.release/'release.json',{'files_sha256':{n:repair.sha(self.release/n) for n in ('workflow.json','policy.json','coverage.json')}})

    def pin_source(self):
        self.write(self.evaluation/'public-a/source-manifest.json',{f'competition/releases/{self.release.name}/{n}':repair.sha(self.release/n) for n in ('workflow.json','release.json')})

    def read(self):return repair.read_evaluation(self.evaluation,self.release)

    def test_valid_defaults_and_absent_stress_manifest(self):
        records,hashes,_=self.read()
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['original_failed_checks'],['Original failure'])
        self.assertIn(str(self.evaluation/'public-a/platform-export.workflow.json'),hashes)

    def test_rehashed_same_name_candidate_rejected(self):
        self.mutate(self.release/'workflow.json',lambda x:x['nodes']['talk'].update(prompt='Different runtime'))
        self.repin()
        with self.assertRaisesRegex(ValueError,'source manifest'):self.read()

    def test_missing_release_artifact_pin_rejected(self):
        self.mutate(self.release/'release.json',lambda x:x['files_sha256'].pop('coverage.json'))
        with self.assertRaisesRegex(ValueError,'incomplete'):self.read()

    def test_tampered_export_value_rejected(self):
        self.mutate(self.evaluation/'public-a/platform-export.workflow.json',lambda x:x['workflow']['nodes']['talk'].update(prompt='Different runtime'))
        with self.assertRaisesRegex(ValueError,'export source'):self.read()

    def test_tampered_export_list_rejected(self):
        self.mutate(self.evaluation/'public-a/platform-export.workflow.json',lambda x:x['workflow']['nodes']['talk']['transitions'].append({'target_node':'other'}))
        with self.assertRaisesRegex(ValueError,'export source'):self.read()

    def test_call_identity_cannot_hide_behind_refreshed_hash(self):
        folder=self.evaluation/'public-a';path=folder/'calls/public-a-call.json'
        self.mutate(path,lambda x:x.update(id='other-call'))
        self.mutate(folder/'direct-provenance.json',lambda x:x['calls'][0].update(call_sha256=repair.sha(path)))
        with self.assertRaisesRegex(ValueError,'Direct call provenance'):self.read()

    def test_modified_call_bytes_rejected(self):
        self.mutate(self.evaluation/'public-a/calls/public-a-call.json',lambda x:x.update(messages=[{'role':'user','content':'modified'}]))
        with self.assertRaisesRegex(ValueError,'call hash'):self.read()

    def test_score_flip_rejected_even_for_excluded_passing_row(self):
        folder=self.evaluation/'stress-in-words'
        self.mutate(folder/'repetition-1.json',lambda x:x['rows'][0].update({'pass':True}))
        with self.assertRaisesRegex(ValueError,'score verdict'):self.read()

    def test_repetition_version_mismatch_rejected(self):
        self.mutate(self.evaluation/'public-a/repetition-1.json',lambda x:x.update(version_id='different-version'))
        with self.assertRaisesRegex(ValueError,'Repetition'):self.read()

    def test_stress_cannot_use_other_published_version(self):
        self.mutate(self.evaluation/'stress-in-words/published-version.json',lambda x:x.update(id='version-2'))
        with self.assertRaisesRegex(ValueError,'Published workflow'):self.read()

    def test_missing_scored_row_rejected(self):
        self.mutate(self.evaluation/'stress-in-words/repetition-1.json',lambda x:x.update(rows=[]))
        with self.assertRaisesRegex(ValueError,'Incomplete scored'):self.read()

    def test_original_hosted_fixture_when_available(self):
        evaluation=Path('/home/yusuf/Masaüstü/fraya/local-runs/customer-benchmark-v2-context-20261011')
        release=ROOT/'competition/releases/minilm-v2-context-a-20261011'
        if not evaluation.exists():self.skipTest('Local original hosted evidence unavailable')
        records,hashes,result=repair.read_evaluation(evaluation,release)
        self.assertEqual(len(records),14)
        self.assertEqual(sum(r['original_pass'] for r in records),3)
        self.assertEqual(result['scopes']['public-a']['passed_calls'],24)
        self.assertEqual(len([p for p in hashes if '/calls/' in p]),39)

if __name__=='__main__':unittest.main()
