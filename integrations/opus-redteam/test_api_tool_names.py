"""Actual supplied API coverage; no provider or secret access."""
import json
from pathlib import Path
import unittest
import run


class ApiToolNamesTests(unittest.TestCase):
    def test_supplied_api_without_operation_ids_has_all_seven_tools(self):
        api = json.loads((run.ROOT / run.SOURCES['openapi']).read_text(encoding='utf-8'))
        self.assertEqual(run.api_tool_names(api), sorted([
            'verify_identity', 'get_account', 'create_promise', 'add_note',
            'schedule_callback', 'transfer_to_agent', 'close_call']))

    def test_explicit_operation_id_and_path_fallback_skip_path_metadata(self):
        api = {'paths': {'/v1/read/': {'parameters': [], 'post': {'operationId': 'read_record'}},
                         '/v1/close_call': {'description': 'not an operation', 'post': {}}}}
        self.assertEqual(run.api_tool_names(api), ['close_call', 'read_record'])

    def test_empty_operation_registry_is_rejected(self):
        with self.assertRaises(ValueError):
            run.api_tool_names({'paths': {'/nothing': {'parameters': []}}})


if __name__ == '__main__':
    unittest.main()
