"""Offline contract tests only; hosted execution and all sockets are mocked."""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch, sentinel

import benchmark_runner as runner
import speech_stress_adapter as adapter
import speech_stress_live as live


def no_credentials(key, default=None):
    if key in {"FREYA_API_KEY", "FREYA_BANK_TEAM_KEY"}:
        raise AssertionError("credential read forbidden")
    # argparse consults locale and terminal settings. Return their defaults
    # without reading any environment values.
    return default


class LiveEntryPointTests(unittest.TestCase):
    def setUp(self):
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        self.guards.enter_context(patch("socket.socket", side_effect=AssertionError("network forbidden")))
        self.guards.enter_context(patch.object(runner, "OfficialClient", side_effect=AssertionError("client forbidden")))
        self.execute = self.guards.enter_context(patch.object(
            runner, "execute", side_effect=AssertionError("live execution forbidden")))
        self.guards.enter_context(patch.object(os.environ, "get", side_effect=no_credentials))
        self.guards.enter_context(patch.object(os, "getenv", side_effect=no_credentials))

    def invoke(self, argv, **kwargs):
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = live.main(argv, **kwargs)
        return code, json.loads(output.getvalue())

    def test_default_handoff_uses_exact_adapter_and_speech_catalog(self):
        with patch.object(adapter, "verify_pack", wraps=adapter.verify_pack) as verify, \
             patch.object(runner, "main", return_value=7) as entry:
            self.assertEqual(live.main([]), 7)
        self.assertEqual(live.DEFAULT_PACK, adapter.b.OUT / "speech-stress-cases.json")
        verify.assert_called_once_with(live.DEFAULT_PACK)
        entry.assert_called_once_with(
            ["--cases", str(live.DEFAULT_PACK)], adapter=adapter, client=None)
        self.execute.assert_not_called()

    def test_default_is_keyless_nonexecution_through_existing_runner(self):
        with patch.object(runner, "main", wraps=runner.main) as entry:
            code, result = self.invoke([])
        self.assertEqual(code, 0)
        entry.assert_called_once()
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(result["execution_status"], "not_executed")
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["scope"], adapter.SCOPE)
        self.assertEqual(result["repetitions"], 3)
        self.assertEqual(result["max_personas_per_batch"], 5)
        self.execute.assert_not_called()

    def test_all_missing_explicit_execution_selectors_refused_by_runner(self):
        fields = ["--agent-id", "agent_test", "--brief", "A", "--only",
                  adapter.catalog().to_rows()[0]["variant_id"]]
        # All seven combinations missing one or more required selectors.
        for mask in range(7):
            argv = ["--execute"]
            for index in range(3):
                if mask & (1 << index):
                    argv.extend(fields[index * 2:index * 2 + 2])
            with self.subTest(argv=argv), patch.object(runner, "main", wraps=runner.main) as entry:
                code, result = self.invoke(argv)
                self.assertEqual(code, 2)
                self.assertEqual(result["error_code"], "execution_requires_agent_brief_and_variants")
                entry.assert_called_once()
        self.execute.assert_not_called()

    def test_selectors_alone_do_not_opt_in_to_execution(self):
        row = adapter.catalog().to_rows()[0]
        code, result = self.invoke(["--agent-id", "agent_test", "--brief", row["brief"],
                                    "--only", row["variant_id"]])
        self.assertEqual(code, 0)
        self.assertEqual(result["execution_status"], "not_executed")
        self.assertEqual(result["sessions_required"], 3)
        self.execute.assert_not_called()

    def test_explicit_execution_options_reach_existing_runner_unchanged(self):
        row = adapter.catalog().to_rows()[0]
        argv = ["--execute", "--agent-id", "agent_test", "--brief", row["brief"],
                "--only", row["variant_id"], "--batch-size", "5", "--reps", "4",
                "--parallel-reps", "--fail-fast", "--budget-seconds", "600"]
        with patch.object(runner, "main", return_value=0) as entry:
            self.assertEqual(live.main(argv), 0)
        entry.assert_called_once_with(["--cases", str(live.DEFAULT_PACK), *argv],
                                      adapter=adapter, client=None)
        self.execute.assert_not_called()

    def test_existing_runner_owns_max_five_validation(self):
        for batch_size in (0, 6):
            with self.subTest(batch_size=batch_size), \
                 patch.object(runner, "settings", wraps=runner.settings) as settings:
                code, result = self.invoke(["--batch-size", str(batch_size)])
                self.assertEqual(code, 2)
                self.assertEqual(result["error_code"], "batch_size_must_be_one_to_five")
                settings.assert_called_once_with(3, batch_size)
        with patch.object(runner, "plan", wraps=runner.plan) as plan:
            code, result = self.invoke(["--batch-size", "5", "--parallel-reps"])
        self.assertEqual(code, 0)
        self.assertEqual(result["max_personas_per_batch"], 5)
        self.assertEqual(result["batches_required"], 6)
        self.assertIs(plan.call_args.args[1], adapter)
        self.execute.assert_not_called()

    def test_each_required_original_source_pin_checked_before_handoff(self):
        self.assertEqual(set(adapter.PINS), {
            "tools/score.py", "tools/openapi.json", "tools/run_cases.py",
            "public-test-set.json", "briefs/brief-a.md", "briefs/brief-b.md"})
        read_bytes = Path.read_bytes
        for name in adapter.PINS:
            target = adapter.KIT / name

            def changed(path, target=target):
                data = read_bytes(path)
                return data + b"\n# changed source\n" if path == target else data

            with self.subTest(source=name), patch.object(Path, "read_bytes", changed), \
                 patch.object(runner, "main") as entry:
                code, result = self.invoke([])
                self.assertEqual(code, 2)
                self.assertEqual(result["error_code"], "pack_integrity_failed")
                entry.assert_not_called()
        self.execute.assert_not_called()

    def test_custom_catalog_is_verified_and_forwarded(self):
        argv = ["--cases", str(adapter.OUT), "--brief", "B"]
        with patch.object(adapter, "verify_pack", wraps=adapter.verify_pack) as verify, \
             patch.object(runner, "main", return_value=0) as entry:
            self.assertEqual(live.main(argv), 0)
        verify.assert_called_once_with(adapter.OUT)
        entry.assert_called_once_with(["--cases", str(live.DEFAULT_PACK), *argv],
                                      adapter=adapter, client=None)

    def test_invalid_catalog_refused_before_handoff(self):
        read_text = Path.read_text

        def invalid(path, *args, **kwargs):
            return "[]" if path == adapter.OUT else read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", invalid), patch.object(runner, "main") as entry:
            code, result = self.invoke([])
        self.assertEqual(code, 2)
        self.assertEqual(result["error_code"], "pack_integrity_failed")
        entry.assert_not_called()

    def test_original_adapter_cli_still_refuses_execution(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(adapter.main(["--execute"]), 2)
        self.assertEqual(json.loads(output.getvalue())["error_code"], "speech_stress_offline_only")
        self.execute.assert_not_called()

    def test_client_test_seam_is_forwarded_without_another_transport(self):
        with patch.object(runner, "main", return_value=0) as entry:
            self.assertEqual(live.main([], client=sentinel.offline_client), 0)
        self.assertIs(entry.call_args.kwargs["client"], sentinel.offline_client)
        self.assertIs(entry.call_args.kwargs["adapter"], adapter)


if __name__ == "__main__":
    unittest.main()
