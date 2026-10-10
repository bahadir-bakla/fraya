"""Evidence integrity tests; no runner/scorer imports or external services."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import failure_triage as triage


class FailureTriageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def fixture(self, run="20261010T174349Z-test", call_id="call-1", rep=1,
                events=None, score=False, judge="fail", reason="Unspecified failure",
                completed=1, required=3, ledger_pass=False):
        directory = self.root / run
        binding = {"id": "PUB-11", "variant_id": "PUB-11__cent_floor", "rep": rep, "call_id": call_id}
        result = {"pass": score, "ledger_and_trace_pass": ledger_pass, "transcript_pass": judge == "pass", "failed": ["promises [], expected one"]}
        job = dict(binding, state="scored", result=result, evidence="evidence/0001.json")
        self.write(directory / "manifest.json", {"run_id": run, "status": "completed", "jobs": [job], "reps": required,
                                                  "tested_version": {"published_version_id": "version-3", "published_version_number": 3}})
        self.write(directory / "results.json", {"execution_status": "completed", "pass": score,
                 "final": [{"id": "PUB-11", "variant_id": binding["variant_id"], "pass": score,
                            "completed_repetitions": completed, "passes": int(score), "required_repetitions": required}]})
        if events is None:
            events = [{"event": "call_ended"}]
        evidence = {"binding": binding,
                    "call": {"id": call_id, "type": "simulationCall", "modality": "text",
                             "entityVersionId": "version-3", "entityVersionNumber": 3,
                             "messages": [{"role": "system", "message": json.dumps(event)} for event in events]},
                    "judge": {"callId": call_id, "outcome": judge, "reason": reason},
                    "ledger": {"ok": True, "outcome": "no_promise", "reason": "service_error", "promises": [],
                               "calls": [{"n": 1, "tool": "close_call", "args": {"outcome": "no_promise", "reason": "service_error"}, "status": 200, "result": {"ok": True}}]}}
        self.write(directory / "evidence/0001.json", evidence)
        return directory, evidence

    def groups(self, report, kind):
        return [g for g in report["backlog"] if g["failure_type"] == kind]

    def test_explicit_outer_parse_error_with_safe_exit_and_actual_close(self):
        directory, _ = self.fixture(events=[
            {"event": "extraction_error", "variables": ["event"], "error": "Unterminated string starting at: line 1 column 25 (char 24)"},
            {"event": "route_evaluated", "from_node": "process", "target": "safe_exit"},
            {"event": "call_ended"}])
        report = triage.collect(self.root)
        group = self.groups(report, "extraction_error")[0]
        self.assertEqual(group["mechanism"], "model_format_outer_json_parse_error")
        occurrence = group["occurrences"][0]
        self.assertFalse(occurrence["original_score_pass"])
        self.assertEqual(occurrence["original_judge_outcome"], "fail")
        self.assertEqual(occurrence["below_floor_kernel_outcome"], "unobserved")
        refs = occurrence["evidence"]
        self.assertTrue(any("safe_exit" in r["excerpt"] for r in refs))
        self.assertTrue(any("close_call" in r["excerpt"] for r in refs))
        source = next(s for s in report["sources"] if s["path"] == str(directory / "evidence/0001.json"))
        self.assertEqual(source["sha256"], hashlib.sha256((directory / "evidence/0001.json").read_bytes()).hexdigest())

    def test_truncated_json_is_infrastructure_not_agent_failure(self):
        directory, _ = self.fixture()
        (directory / "evidence/0001.json").write_text('{"call":', encoding="utf-8")
        report = triage.collect(self.root)
        self.assertEqual({g["failure_type"] for g in report["backlog"]}, {"infrastructure_incomplete"})
        self.assertTrue(any(s["status"] == "invalid_or_truncated_json" and s["sha256"] for s in report["sources"]))
        self.assertTrue(all(g["observed_failure_calls"] == 0 for g in report["backlog"]))

    def test_outer_success_with_malformed_inner_event_retains_exact_provenance(self):
        value = '  {"type":"note","text":"unterminated}'
        event = {"event": "variable_extracted", "name": "event", "value": value,
                 "raw_response": json.dumps({"extracted": {"event": value}})}
        directory, evidence = self.fixture(events=[event, {"event": "call_ended"}],
                                           score=True, judge="pass", ledger_pass=True, required=1)
        path = directory / "evidence/0001.json"
        before = path.read_bytes()
        report = triage.collect(self.root)
        group = self.groups(report, "inner_event_json_error")[0]
        self.assertFalse(self.groups(report, "extraction_error"))
        self.assertEqual(group["mechanism"], "extracted_event_string_json_parse_error")
        self.assertEqual(group["observed_failure_calls"], 1)
        occurrence = group["occurrences"][0]
        self.assertTrue(occurrence["original_score_pass"])
        self.assertTrue(occurrence["original_ledger_and_trace_pass"])
        self.assertEqual(occurrence["original_judge_outcome"], "pass")
        self.assertEqual(occurrence["below_floor_kernel_outcome"], "unobserved")
        ref = next(r for r in occurrence["evidence"] if r.get("decoded_json_pointer"))
        self.assertEqual(ref["json_pointer"], "/call/messages/0/message")
        self.assertEqual(ref["decoded_json_pointer"], "/value")
        self.assertEqual(ref["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(json.loads(evidence["call"]["messages"][0]["message"])["value"], value)
        # Every source pointer resolves against the actual stored artifact.
        for ref in occurrence["evidence"]:
            resolved = json.loads(Path(ref["path"]).read_bytes())
            for part in ref["json_pointer"].strip("/").split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                resolved = resolved[int(part)] if isinstance(resolved, list) else resolved[part]
        self.assertEqual(path.read_bytes(), before)

    def test_native_outer_envelope_cites_actual_value_pointer(self):
        directory, evidence = self.fixture(score=True, judge="pass", ledger_pass=True, required=1)
        evidence["call"]["messages"].insert(0, {"role": "system", "message": {
            "event": "variable_extracted", "name": "event", "value": '{"type":'}})
        self.write(directory / "evidence/0001.json", evidence)
        group = self.groups(triage.collect(self.root), "inner_event_json_error")[0]
        ref = group["occurrences"][0]["evidence"][0]
        self.assertEqual(ref["json_pointer"], "/call/messages/0/message/value")
        self.assertNotIn("decoded_json_pointer", ref)

    def test_valid_inner_native_values_and_text_formats_have_no_false_positives(self):
        values = [' {"type":"note"} ', '[{"type":"note"}]', {"type": "note"},
                  [{"type": "note"}], "free text with {braces}", "NOTE|text=hello",
                  'event=note; text="unfinished', "", None, 7, True]
        for index, value in enumerate(values):
            with self.subTest(value=value):
                self.fixture(run=f"passing-{index}", call_id=f"passing-call-{index}",
                             events=[{"event": "variable_extracted", "name": "event", "value": value},
                                     {"event": "call_ended"}],
                             score=True, judge="pass", ledger_pass=True, required=1)
        self.assertEqual(triage.collect(self.root)["backlog"], [])

    def test_inner_json_detection_requires_recorded_system_event_named_event(self):
        malformed = '{"type":'
        events = [{"event": "variable_extracted", "name": "other", "value": malformed},
                  {"event": "other", "name": "event", "value": malformed},
                  {"event": "variable_extracted", "name": "event",
                   "raw_response": json.dumps({"extracted": {"event": malformed}}),
                   "variable_table": {"event": {"value": malformed}}},
                  {"event": "call_ended"}]
        directory, evidence = self.fixture(events=events, score=True, judge="pass",
                                           ledger_pass=True, required=1)
        for role in ("user", "assistant"):
            evidence["call"]["messages"].insert(0, {"role": role, "message": json.dumps({
                "event": "variable_extracted", "name": "event", "value": malformed})})
        self.write(directory / "evidence/0001.json", evidence)
        self.assertEqual(triage.collect(self.root)["backlog"], [])

    def test_sensitive_malformed_inner_payload_never_leaks(self):
        secrets = ["embedded-private-value", "escaped-private-value", "late-private-value",
                   "fak_abcdef123456", "Bearer private-auth-value"]
        values = ['{"nested":{"headers":{"X-API-Key":"' + secrets[0] + '"}},',
                  '{"\\u0074oken":"' + secrets[1] + '",',
                  '{"text":"' + "benign " * 100 + '","secret":"' + secrets[2] + '",',
                  '{"text":"' + secrets[3] + '",', '{"text":"' + secrets[4] + '",']
        self.fixture(events=[{"event": "variable_extracted", "name": "event", "value": v}
                             for v in values] + [{"event": "call_ended"}], required=1)
        report = triage.collect(self.root)
        group = self.groups(report, "inner_event_json_error")[0]
        refs = [r for r in group["occurrences"][0]["evidence"] if r.get("decoded_json_pointer")]
        self.assertEqual(len(refs), len(values))
        self.assertEqual(group["observed_failure_calls"], 1)
        output = json.dumps(report) + triage.render_text(report)
        for secret in secrets:
            self.assertNotIn(secret, output)
        self.assertTrue(all("WITHHELD extracted event payload" in r["excerpt"] for r in refs))

    def test_inner_event_in_incomplete_or_bounded_evidence_is_not_agent_failure(self):
        for condition in ("cut_short", "missing", "binding", "messages", "bytes", "depth",
                          "integer_limit", "judge", "ledger", "malformed_outer"):
            with self.subTest(condition=condition):
                value = "[" * 1500 + "]" * 1500 if condition == "depth" else '{"type":'
                if condition == "integer_limit":
                    value = '{"n":' + "1" * 5000 + "}"
                events = [{"event": "variable_extracted", "name": "event", "value": value}]
                if condition != "cut_short":
                    events.append({"event": "call_ended"})
                directory, evidence = self.fixture(events=events, required=1)
                path = directory / "evidence/0001.json"
                if condition == "missing":
                    path.unlink()
                elif condition == "binding":
                    evidence["binding"]["call_id"] = "other-call"
                    self.write(path, evidence)
                elif condition in ("judge", "ledger", "malformed_outer"):
                    if condition == "judge":
                        evidence["judge"].pop("outcome")
                    elif condition == "ledger":
                        evidence["ledger"].pop("calls")
                    else:
                        evidence["call"]["messages"].insert(0, {"role": "system", "message": '{"event":'})
                    self.write(path, evidence)
                limits = triage.Limits(max_messages=1) if condition == "messages" else (
                    triage.Limits(max_file_bytes=50) if condition == "bytes" else None)
                report = triage.collect(self.root, limits)
                self.assertEqual({g["failure_type"] for g in report["backlog"]},
                                 {"infrastructure_incomplete"})
                self.assertTrue(all(g["observed_failure_calls"] == 0 for g in report["backlog"]))
                self.assertTrue(all(o["agent_failure_attribution"] == "unknown"
                                    for g in report["backlog"] for o in g["occurrences"]))

    def test_inner_detection_is_text_only(self):
        directory, evidence = self.fixture(events=[
            {"event": "variable_extracted", "name": "event", "value": '{"type":'},
            {"event": "call_ended"}], score=True, judge="pass", ledger_pass=True, required=1)
        for modality in ("voice", "audio", None):
            with self.subTest(modality=modality):
                evidence["call"]["modality"] = modality
                self.write(directory / "evidence/0001.json", evidence)
                self.assertEqual(triage.collect(self.root)["backlog"], [])

    def test_outer_and_inner_errors_remain_distinct_without_inflated_call_counts(self):
        events = [{"event": "variable_extracted", "name": "event", "value": '{"type":'},
                  {"event": "extraction_error", "error": "Unterminated string"},
                  {"event": "call_ended"}]
        self.fixture(events=events, required=1)
        report = triage.collect(self.root)
        group = self.groups(report, "extraction_error")[0]
        self.assertEqual(group["mechanism"], "model_format_outer_json_parse_error")
        self.assertIn("inner_event_json_error", group["occurrences"][0]["secondary_failure_types"])
        self.assertEqual(group["observed_failure_calls"], 1)

    def test_same_inner_error_call_in_two_runs_is_one_observation(self):
        events = [{"event": "variable_extracted", "name": "event", "value": '{"type":'},
                  {"event": "call_ended"}]
        self.fixture(run="inner-a", events=events, required=1)
        self.fixture(run="inner-b", events=events, required=1)
        group = self.groups(triage.collect(self.root), "inner_event_json_error")[0]
        self.assertEqual(len(group["occurrences"]), 2)
        self.assertEqual(group["observed_failure_calls"], 1)

    def test_valid_json_with_cut_short_events_is_infrastructure(self):
        self.fixture(events=[{"event": "node_enter", "node": "initialize"}])
        report = triage.collect(self.root)
        self.assertFalse(self.groups(report, "policy_receipt_ledger_failure"))
        self.assertTrue(self.groups(report, "infrastructure_incomplete"))

    def test_missing_evidence_does_not_promote_failed_score_or_count_agent_failure(self):
        directory, _ = self.fixture()
        (directory / "evidence/0001.json").unlink()
        report = triage.collect(self.root)
        group = self.groups(report, "infrastructure_incomplete")[0]
        self.assertEqual(group["observed_failure_calls"], 0)
        self.assertFalse(group["occurrences"][0]["original_score_pass"])
        self.assertEqual(group["occurrences"][0]["agent_failure_attribution"], "unknown")
        self.assertTrue(any(s["path"] == str(directory / "evidence/0001.json") and s["status"] == "missing" for s in report["sources"]))

    def test_repetitions_not_fabricated_from_summary(self):
        self.fixture(completed=3, required=3)
        report = triage.collect(self.root)
        row = report["runs"][0]["coverage"][0]
        self.assertEqual(row["reported_completed_repetitions"], 3)
        self.assertEqual(row["observed_scored_repetitions"], 1)
        self.assertEqual(row["unobserved_scored_repetitions"], 2)
        self.assertEqual(self.groups(report, "policy_receipt_ledger_failure")[0]["observed_failure_calls"], 1)

    def test_same_call_in_two_runs_is_one_observed_failure(self):
        self.fixture(run="20261010T174349Z-a")
        self.fixture(run="20261010T174350Z-b")
        group = self.groups(triage.collect(self.root), "policy_receipt_ledger_failure")[0]
        self.assertEqual(len(group["occurrences"]), 2)
        self.assertEqual(group["observed_failure_calls"], 1)
        self.assertEqual(group["repetition_status"], "single_observed")

    def test_distinct_calls_establish_observed_repetition(self):
        self.fixture(run="20261010T174349Z-a", call_id="call-1")
        self.fixture(run="20261010T174350Z-b", call_id="call-2")
        group = self.groups(triage.collect(self.root), "policy_receipt_ledger_failure")[0]
        self.assertEqual(group["observed_failure_calls"], 2)
        self.assertEqual(group["repetition_status"], "repeated_observed")

    def test_judged_actor_divergence_retains_failure(self):
        self.fixture(reason="Materially different simulated customer: the simulated customer did not follow the actor script.")
        group = self.groups(triage.collect(self.root), "judged_actor_divergence")[0]
        self.assertEqual(group["occurrences"][0]["original_judge_outcome"], "fail")
        self.assertFalse(group["occurrences"][0]["original_score_pass"])
        self.assertEqual(group["occurrences"][0]["agent_failure_attribution"], "unknown")

    def test_unknown_failure_stays_unknown_even_if_score_claims_pass(self):
        self.fixture(score=True, judge="fail", ledger_pass=True)
        group = self.groups(triage.collect(self.root), "unknown")[0]
        self.assertTrue(group["occurrences"][0]["original_score_pass"])
        self.assertEqual(group["occurrences"][0]["original_judge_outcome"], "fail")

    def test_pending_passing_repetition_is_only_coverage_gap(self):
        self.fixture(score=True, judge="pass", ledger_pass=True)
        report = triage.collect(self.root)
        self.assertEqual({g["failure_type"] for g in report["backlog"]}, {"infrastructure_incomplete"})
        self.assertEqual(report["runs"][0]["coverage"][0]["unobserved_scored_repetitions"], 2)

    def test_nested_sensitive_text_withheld_before_excerpt(self):
        secret = "very-private-value"
        nested = {"payload": json.dumps({"response": {"headers": {"X-API-Key": secret}, "token": "fak_abcdef123456"}})}
        for value in (nested, json.dumps(nested), 'prefix {\\"headers\\":{\\"x\\":\\"' + secret + '\\"}}',
                      "benign " * 100 + " token=" + secret, "fak_abcdef123456", {"private_key": secret}):
            output = json.dumps(triage.safe(value)) + triage.excerpt(value)
            self.assertNotIn(secret, output)
            self.assertNotIn("fak_abcdef123456", output)
        self.fixture(reason=json.dumps(nested))
        output = json.dumps(triage.collect(self.root))
        self.assertNotIn(secret, output)
        self.assertNotIn("fak_abcdef123456", output)

    def test_binding_mismatch_is_infrastructure(self):
        directory, evidence = self.fixture()
        evidence["call"]["id"] = "other-call"
        self.write(directory / "evidence/0001.json", evidence)
        report = triage.collect(self.root)
        self.assertFalse(self.groups(report, "policy_receipt_ledger_failure"))

    def test_byte_bound_is_visible_not_behavioral_failure(self):
        self.fixture()
        report = triage.collect(self.root, triage.Limits(max_file_bytes=50))
        self.assertFalse(report["collection_complete"])
        self.assertTrue(any(s["status"] == "byte_budget_exhausted" for s in report["sources"]))
        self.assertEqual({g["failure_type"] for g in report["backlog"]}, {"infrastructure_incomplete"})

    def test_input_files_unchanged_and_no_other_artifacts_read(self):
        self.fixture()
        ignored = self.root / "credentials.json"
        ignored.write_text("DO NOT READ", encoding="utf-8")
        before = {str(p): p.read_bytes() for p in self.root.rglob("*.json")}
        report = triage.collect(self.root)
        after = {str(p): p.read_bytes() for p in self.root.rglob("*.json")}
        self.assertEqual(before, after)
        self.assertNotIn(str(ignored), {s["path"] for s in report["sources"]})
        self.assertEqual(report["observed_call_modes"], {"hosted_text_simulation": 1})

    def test_offline_kernel_never_counted_as_voice(self):
        directory, evidence = self.fixture(score=True, judge="pass", ledger_pass=True)
        mp = directory / "manifest.json"
        manifest = json.loads(mp.read_text())
        manifest["scope"] = "offline_kernel_replay"
        self.write(mp, manifest)
        evidence["call"]["modality"] = "voice"
        self.write(directory / "evidence/0001.json", evidence)
        self.assertEqual(triage.collect(self.root)["observed_call_modes"], {"offline_or_kernel": 1})
        self.assertEqual(triage.mode({}, {"type": "offline_kernel", "modality": "voice"}), "offline_or_kernel")

    def test_recovered_receipt_failure_does_not_make_passing_call_fail(self):
        directory, evidence = self.fixture(score=True, judge="pass", ledger_pass=True, required=1)
        evidence["ledger"]["calls"].insert(0, {"tool": "get_account", "result": {"ok": False}})
        self.write(directory / "evidence/0001.json", evidence)
        self.assertEqual(triage.collect(self.root)["backlog"], [])

    def test_run_bound_prioritizes_newest_and_declares_omission(self):
        self.fixture(run="20261010T174349Z-a")
        self.fixture(run="20261010T174350Z-b")
        report = triage.collect(self.root, triage.Limits(max_runs=1))
        self.assertEqual([r["run_id"] for r in report["runs"]], ["20261010T174350Z-b"])
        self.assertTrue(any(i["status"] == "run_budget_exhausted" for i in report["collection_issues"]))

    def test_report_sources_are_not_silently_cut_at_one_hundred(self):
        value = {"sources": [{"path": str(i)} for i in range(101)]}
        self.assertEqual(len(triage.safe(value, max_items=None)["sources"]), 101)

    def test_evidence_path_cannot_escape_to_credentials(self):
        directory, _ = self.fixture()
        mp = directory / "manifest.json"
        manifest = json.loads(mp.read_text())
        manifest["jobs"][0]["evidence"] = "../../credentials.json"
        self.write(mp, manifest)
        credentials = self.root / "credentials.json"
        credentials.write_text("not valid json, must never read", encoding="utf-8")
        report = triage.collect(self.root)
        self.assertNotIn(str(credentials), {s["path"] for s in report["sources"]})


if __name__ == "__main__":
    unittest.main()
