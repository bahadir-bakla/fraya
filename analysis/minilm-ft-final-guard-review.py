"""Guard-only synthetic audit. Never opens EVAL, models, credentials or cloud."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / 'integrations/learned-dialogue/minilm_ft_eval.py'
EXPECTED_DEFAULT = 'a563bca8e6f4a43680cef5ef881bfd8c15c2488392b04e191bb7880dd5da3aff'
FIXTURE = b'synthetic EVAL fixture; never real holdout data'
MATCH = hashlib.sha256(FIXTURE).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


old = load('preserved_final_audit', ROOT / 'new.py')
with mock.patch.dict(sys.modules, {'minilm_ft_core': old.core}):
    evaluation = load('independent_fixed_eval_guard', EVAL)


class Guard(unittest.TestCase):
    def test_matching_reviewed_hash_accepts_synthetic_EVAL(self):
        with mock.patch.object(Path, 'read_bytes', return_value=FIXTURE) as opened:
            self.assertEqual(evaluation.admit_eval('synthetic-only.jsonl', [{'split': 'EVAL'}], MATCH), MATCH)
            opened.assert_called_once_with()

    def test_wrong_reviewed_hash_rejects_synthetic_EVAL(self):
        with mock.patch.object(Path, 'read_bytes', return_value=FIXTURE):
            with self.assertRaisesRegex(ValueError, 'source pin mismatch'):
                evaluation.admit_eval('synthetic-only.jsonl', [{'split': 'EVAL'}], '0' * 64)

    def test_bad_tags_and_empty_input_reject_before_hash_read(self):
        for rows in [[], [{'split': 'TRAIN'}], [{'split': 'CAL'}], [{}], [{'split': 'EVAL'}, {'split': 'TRAIN'}]]:
            with self.subTest(rows=rows), mock.patch.object(Path, 'read_bytes') as opened:
                with self.assertRaisesRegex(ValueError, 'nonempty EVAL-tagged'):
                    evaluation.admit_eval('synthetic-only.jsonl', rows, MATCH)
                opened.assert_not_called()

    def test_default_matches_frozen_pin_and_malformed_digest_rejected(self):
        self.assertEqual(evaluation.DEFAULT_EVAL_SHA256, EXPECTED_DEFAULT)
        for invalid in [None, True, '0' * 63, 'G' * 64]:
            with self.subTest(digest=invalid), mock.patch.object(Path, 'read_bytes') as opened:
                with self.assertRaisesRegex(ValueError, 'Reviewed EVAL digest'):
                    evaluation.admit_eval('synthetic-only.jsonl', [{'split': 'EVAL'}], invalid)
                opened.assert_not_called()

    def test_main_wrong_hash_rejects_before_model_or_output(self):
        import numpy as np
        import torch
        args = ['eval', '--models', 'synthetic-models', '--eval', 'synthetic-only.jsonl',
                '--output', 'synthetic-no-output.json', '--expected-eval-sha256', '0' * 64]
        with mock.patch.object(sys, 'argv', args), \
             mock.patch.object(evaluation, 'read_rows', return_value=[{'split': 'EVAL'}]), \
             mock.patch.object(Path, 'exists', return_value=False), \
             mock.patch.object(Path, 'read_bytes', return_value=FIXTURE), \
             mock.patch.object(evaluation, 'load_model') as model, \
             mock.patch.object(Path, 'write_text') as output, \
             mock.patch.object(np, 'savez_compressed') as logits:
            with self.assertRaisesRegex(ValueError, 'source pin mismatch'):
                evaluation.main()
            model.assert_not_called(); output.assert_not_called(); logits.assert_not_called()


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.records = []
    def addSuccess(self, test):
        super().addSuccess(test); self.records.append({'test': test.id(), 'status': 'PASS'})
    def addFailure(self, test, err):
        super().addFailure(test, err); self.records.append({'test': test.id(), 'status': 'FAIL', 'reason': str(err[1])})
    def addError(self, test, err):
        super().addError(test, err); self.records.append({'test': test.id(), 'status': 'ERROR', 'reason': str(err[1])})


if __name__ == '__main__':
    preserved = [ROOT / 'new.py'] + sorted((ROOT / 'analysis').glob('minilm-ft-final-review.*'))
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in preserved}
    source_before = hashlib.sha256(EVAL.read_bytes()).hexdigest()
    suite = unittest.TestSuite([old.Witness('test_07_evaluation_rejects_non_EVAL_split_without_reading_holdout')])
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(Guard))
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    source_after = hashlib.sha256(EVAL.read_bytes()).hexdigest()
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in preserved}
    report = {'auditor': 'Codex', 'status': 'P2_FIXED_VERIFIED' if result.wasSuccessful() else 'GUARD_TEST_FAILURE',
              'eval_runtime_source': str(EVAL.relative_to(ROOT)), 'eval_runtime_sha256': source_after,
              'eval_runtime_sha256_before': source_before, 'source_stable': source_before == source_after,
              'default_EVAL_digest': evaluation.DEFAULT_EVAL_SHA256, 'synthetic_matching_digest': MATCH,
              'tests_run': result.testsRun, 'tests': result.records,
              'old_reports_and_new_py_unchanged': before == after,
              'preserved_files_sha256': before, 'old_test07_details': old.DETAILS.get('eval_admission'),
              'real_EVAL_file_opened': False, 'real_EVAL_metrics_read': False, 'actual_evaluation_rerun': False,
              'cloud_platform_calls': 0, 'model_or_core_changed': False,
              'scope': 'Only original test07 and synthetic evaluator-admission tests; no other old tests run.'}
    path = ROOT / 'analysis/minilm-ft-final-guard-review.json'
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    lines = ['Fixed evaluation admission guard: ' + report['status'],
             'Original test07 plus five synthetic guard tests: ' + str(result.testsRun) + ' run, ' +
             str(len(result.failures)) + ' failures, ' + str(len(result.errors)) + ' errors.',
             'Nonempty EVAL tags, matching reviewed digest, wrong digest, malformed digest,',
             'default frozen digest, and reject-before-model/output checks exercised.',
             'Old reports/new.py unchanged: ' + str(before == after),
             'Evaluator source stable during tests: ' + str(source_before == source_after),
             'Exact evaluator runtime SHA256: ' + source_after,
             'Default EVAL SHA256: ' + evaluation.DEFAULT_EVAL_SHA256,
             'Real EVAL text/result not opened; no actual evaluation rerun; no cloud calls.',
             'No core/model/fit changes. Only new minilm-ft-final-guard-review.* files written.']
    path.with_suffix('.txt').write_text('\n'.join(lines) + '\n', encoding='utf8')
    print(json.dumps({'report': str(path), 'status': report['status'], 'tests_run': result.testsRun,
                      'eval_runtime_sha256': source_after, 'preserved': before == after}))
    sys.exit(0 if result.wasSuccessful() else 1)
