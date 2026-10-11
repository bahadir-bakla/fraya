import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'build_case_folder.py'
spec = importlib.util.spec_from_file_location('case_folder_adapter', SOURCE)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class CaseFolder(unittest.TestCase):
    def test_local_refs_preserve_nested_schema_and_reject_cycles(self):
        original = {'components': {'schemas': {'Envelope': {'type': 'object', 'required': ['data'],
                      'properties': {'data': {'type': 'object', 'required': ['key'],
                      'properties': {'key': {'type': 'string', 'enum': ['one', 'two']}}}}}}}}
        resolved = adapter.expand_references({'$ref': '#/components/schemas/Envelope'}, original)
        self.assertEqual(resolved, original['components']['schemas']['Envelope'])
        for document in ({'x': {'$ref': '#/x'}}, {'x': {'$ref': 'https://example.com'}}):
            with self.assertRaises(ValueError):
                adapter.expand_references(document['x'], document)

    def test_config_only_change_and_source_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case = base / 'case'
            (case / 'sources').mkdir(parents=True)
            (case / 'BRIEF.md').write_text('injected call variables', encoding='utf-8')
            (case / 'sources/2026-01-02-change.txt').write_text('later accepted decision', encoding='utf-8')
            (case / 'sources/2025-01-01-old.md').write_text('old draft', encoding='utf-8')
            api = base / 'api.json'
            original = {'servers': [{'url': 'https://example.invalid'}], 'paths': {'/query': {'post': {}}}}
            api.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(adapter, 'urlopen') as request:
                request.return_value.__enter__.return_value.status = 200
                docs, prepared = adapter.prepare(case, api, 'https://mock.example', base / 'prepared')
            self.assertEqual(json.loads(api.read_text()), original)
            actual = json.loads(prepared.read_text())
            self.assertEqual(actual['paths'], original['paths'])
            self.assertEqual(actual['servers'], [{'url': 'https://mock.example'}])
            manifest = json.loads((prepared.parent / 'source-manifest.json').read_text())
            self.assertEqual([Path(r['source']).name for r in manifest['documents']],
                             ['BRIEF.md', '2025-01-01-old.md', '2026-01-02-change.txt'])
            for record, path in zip(manifest['documents'], docs):
                self.assertEqual(adapter.digest((case / record['source']).read_bytes()), record['sha256'])
                self.assertEqual(adapter.digest(Path(path).read_bytes()), record['prepared_sha256'])

    def test_rejects_credentials_and_non_https_before_network(self):
        for value in ('http://mock.example', 'https://user:password@mock.example', 'https://mock.example?token=x'):
            with patch.object(adapter, 'urlopen') as request:
                with self.assertRaises(ValueError):
                    adapter.prepare('.', SOURCE, value, Path('unused'))
                request.assert_not_called()

    def test_health_failure_prevents_input_preparation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(adapter, 'urlopen') as request:
            request.return_value.__enter__.return_value.status = 503
            output = Path(directory) / 'prepared'
            with self.assertRaises(ValueError):
                adapter.prepare('.', SOURCE, 'https://mock.example', output)
            self.assertFalse(output.exists())
