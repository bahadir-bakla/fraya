import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_layer


RECIPIENT = '''
def recipient_assertion(raw, given_name, last_name, title=''):
    return dict(decision='SELF' if raw==given_name+' '+last_name else 'UNKNOWN', source_span=[0,len(raw)], bank_authority=False)
'''


class LiveLayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.recipient = self.work / 'source.py'
        self.recipient.write_text(RECIPIENT, encoding='utf-8')

    def compile(self):
        contract = live_layer.prepare(self.work, self.recipient)
        code = (self.work / 'live-layer-code.py').read_text(encoding='utf-8')
        namespace = {}
        exec(code, namespace)
        return contract, code, namespace

    def test_bank_state_is_never_modified_by_live_proposal(self):
        _, _, ns = self.compile()
        state = {'verified': False, 'readback': {'amount': '530'}, 'consent': 'UNKNOWN', 'recorded': False}
        v = {'raw': 'Ava Martin', 'first_name': 'Ava', 'last_name': 'Martin', 'state': copy.deepcopy(state), 'route': 'talk'}
        ns['live_layer_apply'](v)
        self.assertEqual(v['live_recipient_decision'], 'SELF')
        self.assertEqual(v['state'], state)
        self.assertEqual(v['route'], 'talk')
        self.assertEqual(v['raw'], 'Ava Martin')
        self.assertEqual(v['live_bank_authority'], 'false')
        self.assertEqual(v['live_financial_authorization'], 'UNKNOWN')

    def test_bank_response_never_enters_observed_history(self):
        _, _, ns = self.compile()
        v = dict(raw='Ava Martin', mode='account', live_semantic_hint='proposal')
        ns['live_layer_apply'](v)
        self.assertEqual(v['live_layer_status'], 'NO_CURRENT_RAW')
        self.assertEqual(v['live_semantic_hint'], '')
        self.assertNotIn('live_observed_prior', v)

    def test_nonstring_current_does_not_reuse_previous_proposal(self):
        _, _, ns = self.compile()
        v = dict(raw={'text': 'offer'}, live_semantic_hint='proposal', live_recipient_decision='SELF')
        ns['live_layer_apply'](v)
        self.assertEqual(v['live_recipient_decision'], 'UNKNOWN')
        self.assertEqual(v['live_semantic_hint'], '')

    def test_previous_history_has_only_bounded_actual_user_turns(self):
        _, _, ns = self.compile()
        v = dict(raw='one', state={'phase':'proposal','verified':True,'dob_passed':True})
        for utterance in ('one', 'two', 'three'):
            v['raw'] = utterance
            ns['live_layer_apply'](v)
        self.assertEqual(v['live_observed_prior'], [dict(speaker='USER', text='two'), dict(speaker='USER', text='three')])
        self.assertEqual(v['live_layer_turns'], 3)

    def test_security_answers_do_not_enter_student_history(self):
        _, _, ns = self.compile()
        for phase in ('recipient','dob','phone','security_answer','new_unknown_phase'):
            v = dict(raw='private operand', state={'phase':phase})
            ns['live_layer_apply'](v)
            self.assertEqual(v['live_layer_status'], 'SOURCE_ONLY_SECURITY_BYPASS')
            self.assertEqual(v['live_input_kind'], 'extractor_copy')
            self.assertNotIn('live_observed_prior', v)

    def test_source_changed_after_prepare_rejected(self):
        contract, _, _ = self.compile()
        path = self.work / 'recipient_assertion.py'
        path.write_text(RECIPIENT + '# changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            live_layer.verify_inputs(self.work, contract)

    def test_embedding_definition_without_invocation_rejected(self):
        contract, code, _ = self.compile()
        workflow = {'nodes': {'controller': {'node_type':'code', 'pre_actions': [{'function': {'handler': '__function__:code_exec', 'parameters': {'properties': {'code': {'default': code}}}}}]}}}
        with self.assertRaisesRegex(ValueError, 'no exact invoked'):
            live_layer.validate_embedding(workflow, self.work, contract)

    def test_dead_live_invocation_is_rejected(self):
        contract,code,_=self.compile()
        snippet=code+'\nif False:\n    live_layer_apply(vars)\nmatched=live_recipient_reply("someone",vars)\n'
        workflow={'nodes':{'controller':{'node_type':'code','pre_actions':[{'function':{'handler':'__function__:code_exec','parameters':{'properties':{'code':{'default':snippet}}}}}]}}}
        with self.assertRaises(ValueError):live_layer.validate_embedding(workflow,self.work,contract)

    def test_embedding_is_exact_and_requires_recipient_use(self):
        contract, code, _ = self.compile()
        snippet = code + '\nlive_layer_apply(vars)\nmatched=live_recipient_reply(vars.get("raw",""),vars)\n'
        workflow = {'nodes': {'controller': {'node_type':'code', 'pre_actions': [{'function': {'handler': '__function__:code_exec', 'parameters': {'properties': {'code': {'default': snippet}}}}}]}}}
        self.assertEqual(live_layer.validate_embedding(workflow, self.work, contract)['nodes'], ['controller'])
        workflow['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default'] = snippet.replace("NO_CURRENT_RAW", "OK")
        with self.assertRaises(ValueError):
            live_layer.validate_embedding(workflow, self.work, contract)

    def test_external_runtime_dependencies_rejected(self):
        for source in ('import torch', 'from hashlib import sha256', 'open("model.json")', 'exec("pass")'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                live_layer.portable(source)

    def test_student_requires_explicit_digest(self):
        directory = self.work / 'student'
        directory.mkdir()
        (directory / 'manifest.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'explicit frozen'):
            live_layer.prepare(self.work, self.recipient, directory, '0'*64)

    def test_financial_phase_requires_both_actual_boolean_identity_guards(self):
        _, _, ns = self.compile()
        for phase in ('proposal','readback','confirmation','payment_terms'):
            for verified,dob in ((False,False),(True,False),(False,True),('true',True),(True,'true')):
                v=dict(raw='private operand',state=dict(phase=phase,verified=verified,dob_passed=dob))
                ns['live_layer_apply'](v)
                self.assertEqual(v['live_layer_status'],'SOURCE_ONLY_UNVERIFIED_BYPASS')
                self.assertNotIn('live_observed_prior',v)
                self.assertEqual(v['live_semantic_diagnostic'],'')

    def test_conversation_preaction_and_prior_controller_execution_rejected(self):
        contract,code,_=self.compile()
        tail='\nlive_layer_apply(vars)\nmatched=live_recipient_reply(vars.get("raw",""),vars)\n'
        for kind,extra in [('conversation',''),('code',"\nvars['raw']=''\n"),
                           ('code','\nlive_layer_apply=lambda v:None\n'),
                           ('code','\ndef live_layer_apply(v):pass\n'),
                           ('code','\nvars={}\n'),
                           ('code','\nimport re as live_layer_apply\n'),
                           ('code','\ncontroller(vars)\n')]:
            snippet=code+extra+tail
            wf={'nodes':{'dispatch':{'node_type':kind,'pre_actions':[{'function':{'handler':'__function__:code_exec','parameters':{'properties':{'code':{'default':snippet}}}}}]}}}
            with self.subTest(kind=kind,extra=extra),self.assertRaises(ValueError):
                live_layer.validate_embedding(wf,self.work,contract)

    def test_unqualified_student_runs_only_as_non_authoritative_diagnostic(self):
        _,_,ns=self.compile()
        ns['LIVE_STUDENT_MODEL']={'dummy':True}
        ns['student_predict']=lambda *a:dict(status='OK',labels=['proposal'],bank_authority=False)
        v=dict(raw='proposal source',state=dict(phase='proposal',verified=True,dob_passed=True))
        ns['live_layer_apply'](v)
        self.assertEqual(v['live_semantic_diagnostic'],'proposal')
        self.assertEqual(v['live_semantic_hint'],'')
        self.assertEqual(v['live_bank_authority'],'false')

    def test_experimental_clarify_is_explicit_and_cannot_enable_without_a_student(self):
        with self.assertRaisesRegex(ValueError,'pinned student'):
            live_layer.prepare(self.work,self.recipient,student_use='clarify')


if __name__ == '__main__':
    unittest.main()
