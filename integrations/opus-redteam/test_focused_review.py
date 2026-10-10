"""Offline focused review contracts and prompt provenance; no external calls."""
from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run


def snapshot(*, count=3, focus="competition"):
    sources = {key: {"path": path, "sha256": hashlib.sha256(key.encode()).hexdigest(),
                     "line_count": 2, "text": f"{key} complete first line\n{key} complete last line\n"}
               for key, path in run.SOURCES.items()}
    body = "def exact_body():\n    return 'complete'\n" * 300
    value = {"metadata": {"extra": body}, "workflow": {"initial_node": "a/b~c",
             "nodes": {"a/b~c": {"code": body}, "end": {"code": body + "# final\n"}}}}
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode()
    candidate = {"path": "competition/runs/published/workflow.json", "kind": "workflow",
                 "sha256": hashlib.sha256(raw).hexdigest(), "text": raw.decode(),
                 "review_view": run.make_review_view(raw)}
    return {**run.review_options(count, "low" if focus == "competition" else "medium", focus),
            "sources": sources, "qualified_source_ids": ["brief-a:R1", "brief-b:R1"],
            "canonical_source_clauses": [{"qualified_id": "brief-a:R1", "text": "canonical A"},
                                         {"qualified_id": "brief-b:R1", "text": "canonical B"}],
            "tool_names": ["close_call"], "candidates": [candidate],
            "candidate_status": "complete_workflow_supplied"}


def review(data, *, count=None):
    attack = {"title": "Synthetic attack", "priority": "P1", "assessment": "source_derived_attack",
              "scenario": {"brief": "A", "call_variables": {}, "identity_fixture": {}, "products": [],
                           "customer_turns": ["synthetic correction"], "fault_plan": []},
              "expected_ledger": {key: [] for key in ("outcome", "reason", "promises", "notes", "callbacks", "transfers", "oracle_scope")},
              "expected_speech": ["goodbye before close"],
              "forbidden_bank_calls": [{"tool": "close_call", "when": "before goodbye", "reason": "order"}],
              "qualified_source_ids": ["brief-a:R1", "brief-b:R1", "openapi:L1", "competition-host:L2"],
              "failure_path": "source review proposal for supplied workflow",
              "fix_target": {"file": data["candidates"][0]["path"], "function_or_node": "a/b~c", "suggested_change": "harden"}}
    count = data.get("requested_attack_count", 15) if count is None else count
    attacks = [{**deepcopy(attack), "id": f"O55-{number:02d}"} for number in range(1, count + 1)]
    return {"review_type": "source_review_not_executed", "candidate_reviewed": True,
            "limitations": list(data.get("prompt_scope_limitations", [])), "attacks": attacks}


class FocusedContractTests(unittest.TestCase):
    def test_three_unique_grounded_attacks_pass(self):
        data = snapshot()
        run.validate_review(review(data), data)

    def test_fifteen_rejected_for_three_attack_request(self):
        data = snapshot()
        with self.assertRaisesRegex(ValueError, "Exactly 3"):
            run.validate_review(review(data, count=15), data)

    def test_duplicate_missing_out_of_range_and_malformed_ids_rejected(self):
        data = snapshot()
        for ids in (("O55-01", "O55-01", "O55-03"), ("O55-01", "O55-02", "O55-04"),
                    ("O55-01", "O55-02", None), ("O55-01", "O55-02", [])):
            value = review(data)
            for attack, attack_id in zip(value["attacks"], ids):
                attack["id"] = attack_id
            with self.assertRaisesRegex(ValueError, "Exactly 3"):
                run.validate_review(value, data)

    def test_unknown_lines_clauses_and_omitted_sources_rejected(self):
        data = snapshot()
        for source in ("unknown:L1", "brief-a:made-up", "openapi:L3", "openapi:L0",
                       "builder-prompts:L1", "policy-runtime:L2", "runtime-api:L1",
                       "runtime-workflow:L1", "runtime-tools:L1"):
            with self.subTest(source=source):
                value = review(data)
                value["attacks"][0]["qualified_source_ids"] = [source]
                with self.assertRaisesRegex(ValueError, "source ID|omitted"):
                    run.validate_review(value, data)

    def test_registry_entry_cannot_authorize_an_omitted_source(self):
        data = snapshot()
        data["qualified_source_ids"].append("policy-runtime:R1")
        value = review(data)
        value["attacks"][0]["qualified_source_ids"] = ["policy-runtime:R1"]
        with self.assertRaisesRegex(ValueError, "omitted"):
            run.validate_review(value, data)

    def test_omitted_implementation_fix_targets_rejected(self):
        data = snapshot()
        for source in ("builder-prompts", "policy-runtime"):
            value = review(data)
            value["attacks"][0]["fix_target"]["file"] = run.SOURCES[source]
            with self.assertRaisesRegex(ValueError, "outside supplied"):
                run.validate_review(value, data)

    def test_current_competition_fix_targets_allowed(self):
        data = snapshot()
        for source in ("competition-guidance", "competition-host"):
            value = review(data)
            value["attacks"][0]["fix_target"]["file"] = run.SOURCES[source]
            run.validate_review(value, data)

    def test_scope_acknowledgement_required(self):
        data = snapshot()
        value = review(data)
        value["limitations"] = []
        with self.assertRaisesRegex(ValueError, "scope limitations"):
            run.validate_review(value, data)

    def test_default_legacy_snapshot_still_requires_fifteen(self):
        data = snapshot(count=15, focus="full")
        for key in run.review_options():
            data.pop(key)
        run.validate_review(review(data), data)
        with self.assertRaisesRegex(ValueError, "Exactly 15"):
            run.validate_review(review(data, count=3), data)
        value = review(data)
        value["attacks"][-1]["id"] = "O55-01"
        with self.assertRaisesRegex(ValueError, "Exactly 15"):
            run.validate_review(value, data)


class FocusedPromptTests(unittest.TestCase):
    def test_complete_sources_registry_and_lossless_candidate_retained(self):
        data = snapshot()
        prompt, raw_prompt = run.build_review_prompt(data)
        text = prompt.decode()
        self.assertIn("exactly 3 objects", text)
        self.assertIn("O55-01 through O55-03", text)
        self.assertNotIn("exactly 15", text)
        self.assertNotIn("across 15", text)
        self.assertNotIn("Fifteen attack", text)
        for source_id, source in data["sources"].items():
            if source_id in data["included_source_ids"]:
                self.assertIn(f"SOURCE {source_id} PATH {source['path']} SHA256 {source['sha256']}", text)
                for number, line in enumerate(source["text"].splitlines(), 1):
                    self.assertIn(f"L{number} {line}", text)
            else:
                self.assertNotIn(f"SOURCE {source_id} PATH", text)
                self.assertNotIn(source["text"].splitlines()[0], text)
        for clause in data["canonical_source_clauses"]:
            self.assertIn(json.dumps(clause), text)
        candidate = data["candidates"][0]
        encoded = json.dumps(candidate["review_view"], ensure_ascii=True, separators=(",", ":"))
        self.assertIn(encoded, text)
        self.assertIn(candidate["text"], raw_prompt.decode())
        run.verify_review_view(json.loads(encoded), candidate["text"].encode())
        self.assertIn("/workflow/nodes/a~1b~0c/code", text)
        self.assertIn("Never claim to have read omitted", text)
        for limitation in data["prompt_scope_limitations"]:
            self.assertIn(limitation, text)

    def test_default_prompt_keeps_full_fifteen_attack_instructions(self):
        data = snapshot(count=15, focus="full")
        text = run.build_review_prompt(data)[0].decode()
        self.assertIn("exactly 15 objects", text)
        self.assertIn("O55-01 through O55-15", text)
        self.assertIn("Cover all of these, across 15 concrete attacks:", text)
        for source_id in data["sources"]:
            self.assertIn(f"SOURCE {source_id} PATH", text)

    def test_read_only_prepare_never_writes_and_retains_full_snapshot(self):
        data = snapshot()
        candidate = run.ROOT / data["candidates"][0]["path"]
        contract = types.ModuleType("agent_forge.input_contract")
        contract.inspect_inputs = lambda *args: {"documents": [{"clauses": data["canonical_source_clauses"]}]}
        policy = types.ModuleType("agent_forge.builder_policy")
        policy.POLICY_SCHEMA = {}
        api = types.ModuleType("agent_forge.tool_api")
        api.validate_json = lambda *args: []
        original_read_bytes = Path.read_bytes
        original_read_text = Path.read_text

        def read_bytes(path):
            if path == candidate:
                return data["candidates"][0]["text"].encode()
            for key, relative in run.SOURCES.items():
                if path == run.ROOT / relative:
                    return (b'{"paths": {"/get_account": {"post": {}}}}' if key == "openapi" else data["sources"][key]["text"].encode())
            return original_read_bytes(path)

        def read_text(path, *args, **kwargs):
            return data["candidates"][0]["text"] if path == candidate else original_read_text(path, *args, **kwargs)

        with patch.dict(sys.modules, {"agent_forge.input_contract": contract, "agent_forge.builder_policy": policy,
                                     "agent_forge.tool_api": api}), \
             patch.object(run, "latest_published_candidate", return_value=candidate), \
             patch.object(Path, "read_bytes", read_bytes), patch.object(Path, "read_text", read_text), \
             patch.object(Path, "mkdir") as mkdir, patch.object(Path, "write_bytes") as write_bytes, \
             patch.object(Path, "write_text") as write_text:
            prepared = run.prepare(attack_count=3, effort="low", focus="competition", write_outputs=False)
            # A selected export that becomes invalid must not degrade to a source-only focused review.
            with patch.object(Path, "read_text", lambda path, *args, **kwargs:
                              "{}" if path == candidate else original_read_text(path, *args, **kwargs)):
                with self.assertRaisesRegex(ValueError, "complete latest published"):
                    run.prepare(attack_count=3, effort="low", focus="competition", write_outputs=False)
        mkdir.assert_not_called()
        write_bytes.assert_not_called()
        write_text.assert_not_called()
        self.assertEqual(set(prepared["sources"]), set(run.SOURCES))
        self.assertEqual(prepared["canonical_source_clauses"], data["canonical_source_clauses"])
        self.assertEqual(prepared["requested_attack_count"], 3)
        self.assertEqual(prepared["effort"], "low")
        self.assertEqual(prepared["focus"], "competition")
        prompt = run.build_review_prompt(prepared)[0]
        self.assertEqual(prepared["prompt_bytes"], len(prompt))
        self.assertEqual(prepared["prompt_sha256"], hashlib.sha256(prompt).hexdigest())
        run.verify_review_view(prepared["candidates"][0]["review_view"], data["candidates"][0]["text"].encode())


class FocusedCliTests(unittest.TestCase):
    def test_run_cli_records_scope_count_effort_and_validates_three(self):
        data = snapshot()
        prompt = run.build_review_prompt(data)[0]
        data.update(prompt_bytes=len(prompt), prompt_sha256=hashlib.sha256(prompt).hexdigest())
        value = review(data)
        events = [{"type": "system", "subtype": "init", "model": run.MODEL, "tools": [], "mcp_servers": []},
                  {"type": "assistant", "message": {"model": run.MODEL,
                   "content": [{"type": "text", "text": json.dumps(value)}]}},
                  {"type": "result", "subtype": "success", "is_error": False, "modelUsage": {run.MODEL: {"outputTokens": 1}}}]
        child = types.SimpleNamespace(stdout=io.StringIO("\n".join(json.dumps(e) for e in events)),
                                      stdin=io.StringIO(), returncode=0, wait=lambda **kwargs: 0)

        class SyntheticCLI:
            def __str__(self):
                return "synthetic-claude.exe"

            def read_bytes(self):
                return b"synthetic executable bytes"

        reports = []
        with TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            (runtime / "prompt.txt").write_bytes(prompt)
            with patch.object(run, "RUNTIME", runtime), patch.object(run, "prepare", return_value=data) as prepare, \
                 patch.object(run, "find_cli", return_value=SyntheticCLI()), \
                 patch.dict(run.os.environ, {}, clear=True), \
                 patch.object(run.subprocess, "check_output", return_value="synthetic version"), \
                 patch.object(run, "auth_status", return_value={"status": {"loggedIn": True}}), \
                 patch.object(run.subprocess, "Popen", return_value=child) as popen, \
                 patch.object(run, "write_reports", side_effect=lambda meta, *args: reports.append(deepcopy(meta))), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(run.run_cli(420, attack_count=3, effort="low", focus="competition"), 0)
            self.assertEqual(json.loads((runtime / "verified-review.json").read_text()), value)
        prepare.assert_called_once_with(attack_count=3, effort="low", focus="competition")
        arguments = popen.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--effort") + 1], "low")
        self.assertEqual(reports[-1]["status"], "completed_actual_opus_source_review")
        for key in ("requested_attack_count", "effort", "focus", "included_source_ids", "prompt_scope_limitations", "prompt_bytes"):
            self.assertEqual(reports[-1][key], data[key])

    def test_report_metadata_defaults_are_explicit(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "analysis").mkdir()
            metadata = {"status": "synthetic", "timeout_seconds": 420}
            with patch.object(run, "ROOT", root):
                run.write_reports(metadata)
            self.assertEqual(metadata["requested_attack_count"], 15)
            self.assertEqual(metadata["effort"], "medium")
            self.assertEqual(metadata["focus"], "full")
            self.assertEqual(metadata["included_source_ids"], list(run.SOURCES))

    def test_focused_report_retains_requested_count_and_rerun_flags(self):
        data = snapshot()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "analysis").mkdir()
            metadata = {**run.review_options(3, "low", "competition"), "status": "synthetic", "timeout_seconds": 420}
            with patch.object(run, "ROOT", root):
                run.write_reports(metadata, review(data))
            saved = json.loads((root / "analysis/opus-redteam.json").read_text())
            self.assertEqual(saved["attack_count"], 3)
            self.assertEqual(saved["requested_attack_count"], 3)
            self.assertEqual(saved["effort"], "low")
            self.assertEqual(saved["focus"], "competition")
            self.assertIn("--attack-count 3 --effort low --focus competition", (root / "analysis/opus-redteam.txt").read_text())

    def test_effort_low_and_medium_arguments(self):
        for effort in ("low", "medium"):
            arguments = run.cli_arguments(Path("synthetic-claude.exe"), effort=effort)
            self.assertEqual(arguments[arguments.index("--effort") + 1], effort)
            self.assertEqual(arguments[arguments.index("--model") + 1], run.MODEL)
        arguments = run.cli_arguments(Path("synthetic-claude.exe"))
        self.assertEqual(arguments[arguments.index("--effort") + 1], "medium")

    def test_main_nondefault_auto_uses_native_and_forwards_options(self):
        argv = ["run.py", "run", "--attack-count", "3", "--effort", "low", "--focus", "competition"]
        with patch.object(sys, "argv", argv), patch.object(run, "run_cli", return_value=0) as launch, \
             patch.object(Path, "is_file", side_effect=AssertionError("No credential metadata access needed")):
            self.assertEqual(run.main(), 0)
        launch.assert_called_once_with(420, attack_count=3, effort="low", focus="competition")

    def test_main_default_native_call_is_backwards_compatible(self):
        with patch.object(sys, "argv", ["run.py", "run", "--provider", "claude-cli"]), \
             patch.object(run, "run_cli", return_value=0) as launch:
            self.assertEqual(run.main(), 0)
        launch.assert_called_once_with(420)

    def test_proxy_nondefault_options_rejected_before_launch(self):
        with patch.object(sys, "argv", ["run.py", "run", "--provider", "local-proxy", "--attack-count", "3"]), \
             patch.object(run, "run_cli") as launch, patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                run.main()
        self.assertEqual(raised.exception.code, 2)
        launch.assert_not_called()

    def test_unsupported_counts_and_options_rejected(self):
        for kwargs in ({"attack_count": 2}, {"attack_count": True}, {"effort": "high"}, {"focus": "unknown"}):
            with self.assertRaises(ValueError):
                run.review_options(**kwargs)


if __name__ == "__main__":
    unittest.main()
