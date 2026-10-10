import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import adapter as a


def dialog():
    return [{'conversation_id': 'dlg-test', 'vertical': 'synthetic-fixture', 'utterances': [
        {'index': 0, 'speaker': 'user', 'text': 'Wait, actually please change my request?'},
        {'index': 1, 'speaker': 'assistant', 'text': 'PRIVATE RESPONSE',
         'apis': [{'name': 'PRIVATE_POLICY_ACTION', 'response': {'secret': 'PRIVATE RESULT'}}]},
        {'index': 2, 'speaker': 'user', 'text': ''}]}]


class ParsingTests(unittest.TestCase):
    def test_csv_quoted_multiline_unicode(self):
        records = a.banking('text,category\n"Hello, café\nplease",intent\n'.encode())
        self.assertEqual(records[0]['turns'][0]['text'], 'Hello, café\nplease')

    def test_bad_csv(self):
        for data in [b'wrong,category\nx,y\n', b'text,category\nx\n',
                     b'text,category\nx,y,z\n', b'text,category\n', b'text,category\n,y\n', b'\xff']:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                a.banking(data)

    def test_multiturn_preserves_order_and_empty_turn(self):
        record = a.taskmaster(json.dumps(dialog()).encode())[0]
        self.assertEqual([t['index'] for t in record['turns']], [0, 1, 2])
        self.assertEqual(record['action_count'], 1)

    def test_bad_dialogs(self):
        for raw in [None, {}, [], [1], dialog() + dialog()]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                a.taskmaster(json.dumps(raw).encode())
        for field, value in [('index', 9), ('index', True), ('speaker', 'system'),
                             ('text', None), ('apis', {}), ('apis', [{}])]:
            raw = dialog()
            raw[0]['utterances'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                a.taskmaster(json.dumps(raw).encode())
        with self.assertRaises(ValueError):
            a.taskmaster(b'{bad json')

    def test_hash_mismatch_and_size(self):
        self.assertEqual(a.checked(b'x', {'sha256': a.digest(b'x')}), b'x')
        with self.assertRaises(ValueError):
            a.checked(b'x', {'sha256': a.digest(b'y')})
        with patch.object(a, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            a.checked(b'xx', {'sha256': a.digest(b'xx')})

    def test_pin_and_cached_hash_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            spec = {'id': 'test', 'url': 'https://example.com/main/data', 'sha256': a.digest(b'x')}
            with self.assertRaises(ValueError):
                a.download(spec, cache)
            (cache / 'test.data').write_bytes(b'corrupted')
            with self.assertRaises(ValueError):
                a.download(spec, cache)

    def test_network_hash_rejected_without_writing(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def geturl(self): return 'https://raw.githubusercontent.com/o/r/' + 'a' * 40 + '/data'
            def read(self, size): return b'corrupt'
        with tempfile.TemporaryDirectory() as tmp, patch.object(a.urllib.request, 'urlopen', return_value=Response()):
            spec = {'id': 'test', 'url': Response().geturl(), 'sha256': a.digest(b'expected')}
            with self.assertRaises(ValueError): a.download(spec, Path(tmp))
            self.assertFalse((Path(tmp) / 'test.data').exists())

    def test_cues_are_located_and_heuristic(self):
        record = a.taskmaster(json.dumps(dialog()).encode())[0]
        observations = a.observations(record)
        self.assertEqual({o['feature'] for o in observations}, set(a.PATTERNS))
        self.assertTrue(all(o['turn_index'] == 0 and o['method'] == 'lexical_heuristic_v1' for o in observations))
        record['turns'][0]['text'] = 'No, I meant another request.'
        self.assertIn('correction_cue', {o['feature'] for o in a.observations(record)})

    def test_sampling_deterministic_capped_taxonomy_coverage(self):
        records = a.banking(b'text,category\na,z\nb,a\nc,z\nd,b\n')
        chosen = a.sample(records, 3)
        self.assertEqual([r['source_label'] for r in chosen], ['a', 'b', 'z'])
        self.assertEqual(chosen, a.sample(records, 3))
        for limit in (0, 26, True):
            with self.assertRaises(ValueError): a.sample(records, limit)

    def test_no_policy_or_private_content_leakage(self):
        record = a.taskmaster(json.dumps(dialog()).encode())[0]
        spec = a.manifest()[1]
        output = a.scenario(record, spec)
        encoded = json.dumps(output)
        for secret in ('PRIVATE RESPONSE', 'PRIVATE_POLICY_ACTION', 'PRIVATE RESULT', 'Wait, actually please'):
            self.assertNotIn(secret, encoded)
        self.assertEqual(output['synthetic_plan']['expected_outputs'], [])
        self.assertIsNone(output['synthetic_plan']['policy_mapping'])
        self.assertNotIn(record['source_label'], json.dumps(output['synthetic_plan']))
        self.assertEqual(output['oracle_scope'], 'conversation_only')
        self.assertEqual(output['execution_status'], 'not_executed')
        self.assertEqual(output['provenance']['sha256'], spec['sha256'])


@unittest.skipUnless(all((a.ROOT / 'cache' / (s['id'] + '.data')).exists() for s in a.manifest()),
                     'Run adapter.py once to download pinned sources')
class DownloadedSampleTests(unittest.TestCase):
    def test_actual_sources_and_license_notice_hashes(self):
        for spec in a.manifest():
            data = a.checked((a.ROOT / 'cache' / (spec['id'] + '.data')).read_bytes(), spec)
            self.assertEqual(len(data), spec['bytes'])
            notice = (a.ROOT / 'cache' / (spec['id'] + '-license.data')).read_bytes()
            self.assertEqual(a.digest(notice), spec['license_notice_sha256'])

    def test_actual_scenario_provenance_and_separation(self):
        one, two = a.build(25, offline=True), a.build(25, offline=True)
        self.assertEqual(one, two)
        self.assertEqual(len(one['scenarios']), 50)
        self.assertEqual([s['source_records'] for s in one['stats']], [3080, 1188])
        self.assertEqual(one['stats'][0]['sampled_labels'], 25)
        self.assertGreater(one['stats'][1]['sampled_action_annotations'], 0)
        for s in one['scenarios']:
            self.assertEqual(s['synthetic_plan']['expected_outputs'], [])
            self.assertIsNone(s['synthetic_plan']['policy_mapping'])
            self.assertEqual(s['execution_status'], 'not_executed')
            self.assertEqual(s['oracle_scope'], 'conversation_only')
            self.assertTrue(all('text' not in t for t in s['source_facts']['turn_structure']))
        self.assertIn('wait_or_hold_cue', one['stats'][1]['sampled_feature_names'])


if __name__ == '__main__':
    unittest.main()
