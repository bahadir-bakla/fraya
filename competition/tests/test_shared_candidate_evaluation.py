"""Offline provenance and mutation-retry regression checks for hosted evaluation."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

PATH = Path(__file__).resolve().parents[2] / 'scripts/evaluate_shared_candidate.py'
SPEC = importlib.util.spec_from_file_location('shared_candidate_evaluation', PATH)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


class SharedCandidateEvaluationTests(unittest.TestCase):
    def fixture(self):
        publication = dict(agent_id='agent', workflow_id='workflow', version_id='version', version=2, workspace_id='workspace')
        row = dict(id='case', call_id='call', customer_id='customer')
        run = dict(callId='call', personaId='persona', agentId='agent', agentWorkflowId='workflow', agentVersionId='version', agentVersionNumber=2)
        call = dict(id='call', assistantId='agent', assistantWorkflowId='workflow', entityVersionId='version', entityVersionNumber=2, workspaceId='workspace',
                    messages=[dict(role='system', message=json.dumps(dict(event='function_call_start', function='api_call', args=dict(body=dict(customer_id='customer')))))])
        return row, call, run, publication

    def test_real_direct_call_field_names_bind_all_evidence(self):
        result = evaluation.call_binding(*self.fixture(), 'persona', 'customer')
        self.assertTrue(result['verified'], result)

    def test_wrong_or_missing_call_customer_version_and_agent_are_rejected(self):
        for field in ('id', 'assistantId', 'assistantWorkflowId', 'entityVersionId', 'entityVersionNumber', 'workspaceId'):
            with self.subTest(field=field):
                row, call, run, publication = self.fixture()
                call[field] = 'different'
                self.assertFalse(evaluation.call_binding(row, call, run, publication, 'persona', 'customer')['verified'])
        row, call, run, publication = self.fixture()
        call['messages'] = [dict(role='system', message=json.dumps(dict(event='function_call_start', function='api_call', args=dict(body=dict(customer_id='other')))))]
        result = evaluation.call_binding(row, call, run, publication, 'persona', 'customer')
        self.assertFalse(result['verified'])
        self.assertEqual(result['bank_customer_observation'], 'mismatch')
        row, call, run, publication = self.fixture()
        self.assertFalse(evaluation.call_binding(row, call, run, publication, 'wrong-persona', 'customer')['verified'])
        self.assertFalse(evaluation.call_binding(row, call, run, publication, 'persona', 'other-session')['verified'])

    def test_call_without_bank_tools_preserves_session_binding_as_unobserved(self):
        row, call, run, publication = self.fixture()
        call['messages'] = []
        result = evaluation.call_binding(row, call, run, publication, 'persona', 'customer')
        self.assertTrue(result['verified'], result)
        self.assertEqual(result['observed_customer_ids'], [])
        self.assertEqual(result['bank_customer_observation'], 'unobserved')
        self.assertFalse(evaluation.call_binding(row, call, run, publication, 'persona', 'different-session')['verified'])
        self.assertFalse(evaluation.call_binding(row, call, run, publication, 'different-persona', 'customer')['verified'])

    def test_workspace_requires_unambiguous_authorized_choice(self):
        self.assertEqual(evaluation.select_workspace([{'id': 'one'}]), 'one')
        choices = {'workspaces': [{'id': 'one'}, {'id': 'two'}]}
        self.assertEqual(evaluation.select_workspace(choices, 'two'), 'two')
        for configured in (None, 'absent'):
            with self.assertRaises(ValueError):
                evaluation.select_workspace(choices, configured)

    def test_uncertain_mutations_are_not_repeated(self):
        with tempfile.TemporaryDirectory() as root:
            harness = evaluation.Evaluation(argparse.Namespace(out=str(Path(root) / 'new')))
            for method in ('POST', 'PUT'):
                with self.subTest(method=method), patch.object(evaluation.urllib.request, 'urlopen', side_effect=urllib.error.URLError('interrupted')) as request:
                    with self.assertRaises(RuntimeError):
                        harness.request('https://example.invalid', method, {})
                    self.assertEqual(request.call_count, 1)

    def test_readback_may_add_defaults_but_not_change_authored_values(self):
        original = {'nodes': [{'id': 'one', 'text': 'Original'}]}
        returned = copy.deepcopy(original)
        returned['agent_config'] = {'default': True}
        evaluation.authored_equal(original, returned)
        returned['nodes'][0]['text'] = 'Changed'
        with self.assertRaises(ValueError):
            evaluation.authored_equal(original, returned)

    def test_new_slot_reuses_published_version_or_publishes_without_put(self):
        with tempfile.TemporaryDirectory() as root:
            harness = evaluation.Evaluation(argparse.Namespace(out=str(Path(root) / 'new')))
            workflow = {'nodes': []}
            record = {'workflow': {'id': 'workflow', 'agentId': 'agent', 'workflow': {
                **workflow, 'agent_config': {'llmConfig': dict(evaluation.freya.AGENT_LLM)}}}}
            for published in (True, False):
                versions = {'versions': [{'id': 'version', 'versionNumber': 1, 'isPublished': published}]}
                with self.subTest(published=published), patch.object(harness, 'api', side_effect=[record, versions, {}]) as api, patch.object(evaluation.freya, 'workspace_id', return_value='workspace'), patch.object(evaluation.freya, 'update_workflow') as update:
                    version = harness.publish_created({'workflow_id': 'workflow', 'agent_id': 'agent'}, workflow)
                    self.assertEqual(version, 1)
                    update.assert_not_called()
                    self.assertEqual([call.args[0] for call in api.call_args_list], ['GET', 'GET'] if published else ['GET', 'GET', 'POST'])


if __name__ == '__main__':
    unittest.main()
