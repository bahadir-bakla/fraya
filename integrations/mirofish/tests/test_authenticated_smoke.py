"""Offline credential-redaction, bounded configuration and evidence checks."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import authenticated_runtime
from authenticated_runtime import RedactedStream, redact
from inspect_proxy_providers import aggregate
from run_authenticated_smoke import Smoke, bounded_config, completed_run


class AuthenticatedSmokeTests(unittest.TestCase):
    def test_only_literal_loopback_backend_no_remote_userinfo_route(self):
        for url in ['http://127.0.0.1:5001@remote.example', 'https://127.0.0.1:5001',
                    'http://remote.example:5001', 'http://127.0.0.1:5001/path']:
            with self.assertRaises(ValueError):
                Smoke(url, [], 2, 240)
    def test_cannot_expand_agent_or_time_budget(self):
        for agents,timeout in [(4,240),(2,601),(0,240)]:
            with self.assertRaisesRegex(ValueError, 'Smoke limits'):
                Smoke('http://127.0.0.1:5001', [], agents, timeout)
    def test_explicit_model_is_never_substituted(self):
        settings = {'keys': ['synthetic-key'], 'key': 'synthetic-key', 'base_url': 'http://127.0.0.1:8317/v1'}
        with mock.patch.object(authenticated_runtime, 'install_redaction'), mock.patch.object(
                authenticated_runtime, 'request_json', return_value=(200, {'data': [{'id': 'gpt-6-luna'}]})) as request:
            with self.assertRaisesRegex(ValueError, 'no substitution'):
                authenticated_runtime.probe_proxy(settings, 'claude-opus-5-5')
            self.assertEqual(request.call_count, 1)
    def test_exact_keys_redacted_in_bytes_and_strings(self):
        value = 'two simulated-private-values in a traceback'
        for input_value in (value, value.encode()):
            self.assertNotIn('simulated-private-values', redact(input_value, ['simulated-private-values']))

    def test_bearer_jwt_and_provider_key_patterns_redacted(self):
        value = 'Bearer sample-only-key eyJhbGciOiJ9.eyJ0ZXN0IjoxfQ.c2lnbmF0dXJl sk-testcredential000000000'
        output = redact(value)
        for secret in ('sample-only-key', 'eyJhbGciOiJ9', 'sk-testcredential000000000'):
            self.assertNotIn(secret, output)

    def test_stream_preserves_safe_text_and_redacts_key(self):
        sink = io.StringIO()
        stream = RedactedStream(sink, ['sample-secret'])
        stream.write('safe sample-secret\n')
        stream.flush()
        self.assertEqual(sink.getvalue(), 'safe [REDACTED]\n')

    def test_provider_aggregation_never_exposes_names_or_tokens(self):
        rows = aggregate([{'type': 'codex', 'disabled': False, 'access_token': 'sample-secret'},
                          {'type': 'claude', 'disabled': True, 'email': 'sample-account'},
                          {'type': 'untrusted-secret-label', 'disabled': False}])
        self.assertEqual(rows, [{'provider': 'claude', 'enablement': 'disabled', 'count': 1},
                                {'provider': 'codex', 'enablement': 'enabled', 'count': 1},
                                {'provider': 'unknown', 'enablement': 'enabled', 'count': 1}])
        self.assertNotIn('secret', json.dumps(rows))

    def fixture(self):
        return {'time_config': {'total_simulation_hours': 72, 'minutes_per_round': 30},
                'agent_configs': [{'agent_id': 0, 'entity_name': 'Noah Vale', 'active_hours': [20]},
                                  {'agent_id': 1, 'entity_name': 'Maya Reed', 'active_hours': [20]}],
                'event_config': {'initial_posts': [{'poster_agent_id': 0, 'content': 'synthetic opening discussion'}]}}

    def test_two_agents_activate_in_first_and_only_round_without_mutating_input(self):
        original = self.fixture()
        baseline = deepcopy(original)
        result = bounded_config(original, 2)
        self.assertEqual(original, baseline)
        self.assertEqual(result['time_config']['total_simulation_hours'], 1)
        self.assertEqual(result['time_config']['minutes_per_round'], 60)
        self.assertEqual(result['time_config']['agents_per_hour_max'], 2)
        for agent in result['agent_configs']:
            self.assertEqual(agent['active_hours'], [0])
            self.assertEqual(agent['activity_level'], 1.0)
        self.assertEqual(result['event_config']['initial_posts'][0]['poster_agent_id'], 1)

    def test_refuses_extra_agents_or_posts(self):
        config = self.fixture()
        config['agent_configs'].append({'agent_id': 2, 'entity_name': 'Extra'})
        with self.assertRaisesRegex(ValueError, 'agent budget'):
            bounded_config(config, 2)
        config = self.fixture()
        config['event_config']['initial_posts'].append({'content': 'extra'})
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            bounded_config(config, 2)

    def test_health_or_accepted_start_never_proves_completed_simulation(self):
        for state in ({'status': 'healthy'}, {'runner_status': 'running', 'total_rounds': 1}):
            self.assertFalse(completed_run(state, [{'action': 'create_post'}]))

    def engine_fixture(self):
        return {'completed_rounds': 1, 'active_agents': 2, 'initialization_verified': True,
                'actions_after_seed': [{'action': 'like_post'}], 'agent_errors': []}

    def test_api_counter_gap_requires_independent_actual_engine_and_social_action(self):
        state = {'runner_status': 'completed', 'total_rounds': 1, 'current_round': 0}
        self.assertFalse(completed_run(state, []))
        self.assertTrue(completed_run(state, [], self.engine_fixture()))

    def test_initial_seed_refresh_inactive_round_or_llm_error_not_success(self):
        state = {'runner_status': 'completed', 'total_rounds': 1, 'current_round': 0}
        for change in ({'completed_rounds': 0}, {'active_agents': 0}, {'actions_after_seed': []},
                       {'initialization_verified': False}, {'actions_after_seed': [{'action': 'refresh'}]},
                       {'agent_errors': ['Agent 0 error: synthetic failure']}):
            engine = self.engine_fixture()
            engine.update(change)
            self.assertFalse(completed_run(state, [], engine), change)

    def test_extra_round_or_failed_runner_not_success(self):
        for change in ({'total_rounds': 2}, {'runner_status': 'failed'}, {'runner_status': 'stopped'}):
            state = {'runner_status': 'completed', 'total_rounds': 1}
            state.update(change)
            self.assertFalse(completed_run(state, [], self.engine_fixture()))


if __name__ == '__main__':
    unittest.main()
