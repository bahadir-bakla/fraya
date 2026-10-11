"""Offline synthetic packaging fixtures, never an actual final candidate."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('final_package', ROOT / 'scripts/package_final_case.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class FinalPackageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='final-package-test-', dir=ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        root_patch = patch.object(package, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.run = self.root / 'runs/synthetic-final'
        (self.run / 'work/inputs').mkdir(parents=True)
        self.status = {'id': self.run.name, 'phase': 'completed'}
        self.source = {'nodes': {'start': {'node_type': 'talk'}}}
        self.export = self.root / 'platform-export.json'
        # Matches the reference bridge's envelope keys, with synthetic content.
        self.envelope = {'workflow_id': 'synthetic-workflow', 'agent_id': 'synthetic-agent',
                         'updated_at': '2026-10-11T19:12:00Z', 'workflow': self.source}
        self.proof_path = self.root / 'proof.json'
        self.write(self.run / 'status.json', self.status)
        self.write(self.run / 'work/workflow.json', self.source)
        self.write(self.run / 'work/inputs/openapi.json', {'servers': [{'url': 'https://synthetic.workers.dev'}]})
        self.write(self.export, self.envelope)
        self.proof = {'run_id': self.run.name,
                      'source_workflow_sha256': package.sha256((self.run / 'work/workflow.json').read_bytes()),
                      'workflow_id': self.envelope['workflow_id'], 'agent_id': self.envelope['agent_id'],
                      'version': 3, 'export_sha256': package.sha256(self.export.read_bytes()),
                      'mock_url': 'https://synthetic.workers.dev',
                      'published_version': {'entityType': 'workflow', 'entityId': self.envelope['workflow_id'],
                                            'versionNumber': 3, 'isPublished': True}}
        self.write(self.proof_path, self.proof)
        self.events = [{'kind': 'run_start'}, {'kind': 'model_call', 'round': 1},
                       {'kind': 'command_end', 'log': 'model-1.jsonl', 'returncode': 0, 'timed_out': False},
                       {'kind': 'phase', 'phase': 'completed'},
                       {'kind': 'run_end', 'phase': 'completed'}]
        self.model = [{'type': 'thread.started'}, {'type': 'turn.started'},
                      {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Türkçe synthetic'}},
                      {'type': 'turn.completed'}]
        self.write_logs()
        self.args = argparse.Namespace(run=str(self.run), export_file=str(self.export),
                                       publication_proof=str(self.proof_path), mock_url=self.proof['mock_url'],
                                       team='Synthetic test team', member=['Synthetic=synthetic@example.invalid'],
                                       repo='https://example.invalid/synthetic/builder', commit='a' * 40,
                                       run_command='synthetic builder {case_folder}', output=str(self.root / 'submission'))

    def write(self, path, value):
        path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\r\n').encode('utf-8'))

    def write_logs(self):
        for name, rows in [('trace.jsonl', self.events), ('model-1.jsonl', self.model)]:
            (self.run / name).write_bytes('\r\n'.join(json.dumps(row, ensure_ascii=False) for row in rows).encode('utf-8'))

    def reject(self, message):
        with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
            package.package(self.args)
        self.assertFalse(Path(self.args.output).exists())

    def test_success_exact_schema_repo_paths_and_original_bytes(self):
        before = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        result = package.package(self.args)
        output = Path(self.args.output)
        submission = json.loads((output / 'submission.json').read_bytes())
        self.assertEqual(set(submission), {'team', 'members', 'repo', 'commit', 'run_command', 'workflow', 'trace', 'mock_url'})
        self.assertEqual(submission['team'], self.args.team)
        self.assertEqual(submission['repo'], self.args.repo)
        self.assertEqual(submission['members'], [{'name': 'Synthetic', 'email': 'synthetic@example.invalid'}])
        self.assertEqual(submission['workflow'], 'submission/final.workflow.json')
        self.assertEqual((output / 'final.workflow.json').read_bytes(), self.export.read_bytes())
        self.assertEqual((output / 'publication-proof.json').read_bytes(), self.proof_path.read_bytes())
        combined = (output / 'final.trace.jsonl').read_bytes()
        package.jsonl(combined, 'combined')
        for name in ('trace.jsonl', 'model-1.jsonl'):
            raw = (self.run / name).read_bytes()
            self.assertEqual((output / 'raw-logs' / name).read_bytes(), raw)
            self.assertIn(raw, combined)
            self.assertIn('raw-logs/' + name, result['files'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_success_multiple_rounds_and_publication_crosschecks(self):
        ids = {k: self.proof[k] for k in ('workflow_id', 'agent_id', 'version')}
        self.status['freya'] = ids
        self.write(self.run / 'status.json', self.status)
        self.events.insert(-2, {'kind': 'freya_published', **ids})
        self.events[1:1] = [{'kind': 'model_call', 'round': 2},
                            {'kind': 'command_end', 'log': 'model-2.jsonl', 'returncode': 0, 'timed_out': False}]
        self.write_logs()
        (self.run / 'model-2.jsonl').write_bytes((self.run / 'model-1.jsonl').read_bytes())
        package.package(self.args)
        self.assertEqual((Path(self.args.output) / 'raw-logs/model-2.jsonl').read_bytes(),
                         (self.run / 'model-2.jsonl').read_bytes())

    def test_reject_incomplete_run(self):
        self.status['phase'] = 'needs_attention'
        self.write(self.run / 'status.json', self.status)
        self.reject('completed run')

    def test_reject_missing_publication_proof(self):
        self.proof_path.unlink()
        self.reject('proof.json')

    def test_reject_unrelated_run(self):
        self.proof['run_id'] = 'another-run'
        self.write(self.proof_path, self.proof)
        self.reject('unrelated run')

    def test_reject_source_hash_mismatch(self):
        self.write(self.run / 'work/workflow.json', {'nodes': {'changed': {}}})
        self.reject('source_workflow_sha256')

    def test_reject_export_hash_mismatch(self):
        self.export.write_bytes(self.export.read_bytes() + b' ')
        self.reject('export_sha256')

    def test_reject_unrelated_export_even_with_matching_hash(self):
        self.envelope['workflow_id'] = 'another-workflow'
        self.write(self.export, self.envelope)
        self.proof['export_sha256'] = package.sha256(self.export.read_bytes())
        self.write(self.proof_path, self.proof)
        self.reject('workflow_id')

    def test_reject_source_workflow_as_export(self):
        self.write(self.export, self.source)
        self.reject('actual platform export')

    def test_reject_mock_url_mismatch(self):
        self.args.mock_url = 'https://unrelated.workers.dev'
        self.reject('mock_url mismatch')

    def test_reject_run_api_mock_url_mismatch(self):
        self.write(self.run / 'work/inputs/openapi.json', {'servers': [{'url': 'https://unrelated.workers.dev'}]})
        self.reject('tool API mock_url mismatch')

    def test_reject_unpublished_version(self):
        self.proof['published_version']['isPublished'] = False
        self.write(self.proof_path, self.proof)
        self.reject('readback')

    def test_reject_wrong_version_readback(self):
        self.proof['published_version']['versionNumber'] = 4
        self.write(self.proof_path, self.proof)
        self.reject('readback')

    def test_reject_status_publication_mismatch(self):
        self.status['freya'] = {'workflow_id': 'another', 'agent_id': 'synthetic-agent', 'version': 3}
        self.write(self.run / 'status.json', self.status)
        self.reject('Run publication')

    def test_reject_missing_host_trace(self):
        (self.run / 'trace.jsonl').unlink()
        self.reject('trace.jsonl')

    def test_reject_incomplete_host_trace(self):
        self.events[-1]['phase'] = 'model_build'
        self.write_logs()
        self.reject('host trace')

    def test_reject_missing_model_round(self):
        self.events.insert(1, {'kind': 'model_call', 'round': 2})
        self.write_logs()
        self.reject('inventory')

    def test_reject_empty_model_log(self):
        (self.run / 'model-1.jsonl').write_bytes(b'')
        self.reject('nonempty')

    def test_reject_truncated_session(self):
        self.model.pop()
        self.write_logs()
        self.reject('Truncated')

    def test_reject_summary_instead_of_full_session(self):
        self.model = [{'type': 'turn.completed'}]
        self.write_logs()
        self.reject('Full coding-session')

    def test_reject_failed_final_command(self):
        self.events[2]['returncode'] = 1
        self.write_logs()
        self.reject('Final model command')

    def test_reject_malformed_model_jsonl(self):
        (self.run / 'model-1.jsonl').write_bytes(b'{broken')
        self.reject('Expecting')

    def test_reject_missing_proof_field(self):
        del self.proof['export_sha256']
        self.write(self.proof_path, self.proof)
        self.reject('missing required')

    def test_reject_boolean_version(self):
        self.proof['version'] = True
        self.write(self.proof_path, self.proof)
        self.reject('positive integer')

    def test_reject_duplicate_proof_keys(self):
        raw = self.proof_path.read_bytes().rstrip()
        self.proof_path.write_bytes(raw[:-1] + b', "version": 3}')
        self.reject('Duplicate JSON key')

    def test_reject_original_run_output(self):
        self.args.output = str(self.run / 'submission')
        self.reject('outside the original run')

    def test_success_cli_warning_bytes_preserved(self):
        log = self.run / 'model-1.jsonl'
        raw = b'2026-10-11T15:03:55.748104Z  WARN codex_core::shell_snapshot: unsupported shell\r\n' + log.read_bytes()
        log.write_bytes(raw)
        package.package(self.args)
        output = Path(self.args.output)
        self.assertEqual((output / 'raw-logs/model-1.jsonl').read_bytes(), raw)
        self.assertIn(raw, (output / 'final.trace.jsonl').read_bytes())

    def test_reject_trimmed_host_trace(self):
        self.events.pop(0)
        self.write_logs()
        self.reject('Full host trace')

    def test_reject_duplicate_model_round(self):
        self.events.insert(1, {'kind': 'model_call', 'round': 1})
        self.write_logs()
        self.reject('inventory')

    def test_reject_agent_identity_mismatch(self):
        self.proof['agent_id'] = 'another-agent'
        self.write(self.proof_path, self.proof)
        self.reject('agent_id')

    def test_reject_wrong_publication_entity(self):
        self.proof['published_version']['entityId'] = 'another-workflow'
        self.write(self.proof_path, self.proof)
        self.reject('readback')

    def test_reject_malformed_export_nodes(self):
        self.envelope['workflow'] = {'nodes': 'not a graph'}
        self.write(self.export, self.envelope)
        self.reject('actual platform export')


if __name__ == '__main__':
    unittest.main()
