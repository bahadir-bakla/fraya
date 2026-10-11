"""Offline validation of the twelve-row night delivery pack.

Uses the unchanged speech adapter, source pins and OpenAPI contracts. No
reference replay, customer execution or transcript verdict is manufactured.
Imports receive environment defaults because the official Freya module reads
an API-key setting at import time; no actual environment values are read.
"""
from contextlib import ExitStack
from copy import deepcopy
from collections import Counter
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import unittest
from unittest.mock import patch
import urllib.request


def import_defaults(key, default=None):
    return default


with patch.object(os.environ, "get", side_effect=import_defaults), \
     patch.object(os, "getenv", side_effect=import_defaults), \
     patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
     patch.object(urllib.request, "urlopen", side_effect=AssertionError("HTTP forbidden")):
    import benchmark_adapter as b
    import benchmark_runner as runner
    import speech_stress_adapter as speech
    import speech_stress_live as live


PACK = b.OUT / "night-stress-cases.json"
REQUIRED_TAGS = {
    "mixed_multiintent", "correction_reversal", "ordinal_dates",
    "vague_then_precise", "negated_payment", "consent_withdrawn_reissued",
    "security_purpose", "unrelated_fragments", "grouped_product_terms",
}


def no_environment_values(key, default=None):
    if any(token in str(key).upper() for token in ("KEY", "TOKEN", "SECRET", "CREDENTIAL")):
        raise AssertionError("credential lookup forbidden")
    return default


def offline_guards():
    guards = ExitStack()
    guards.enter_context(patch.object(os.environ, "get", side_effect=no_environment_values))
    guards.enter_context(patch.object(os, "getenv", side_effect=no_environment_values))
    guards.enter_context(patch.object(socket, "socket", side_effect=AssertionError("network forbidden")))
    guards.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")))
    guards.enter_context(patch.object(urllib.request, "urlopen", side_effect=AssertionError("HTTP forbidden")))
    guards.enter_context(patch.object(runner, "OfficialClient", side_effect=AssertionError("client forbidden")))
    guards.enter_context(patch.object(runner, "execute", side_effect=AssertionError("execution forbidden")))
    return guards


def validate_rows(rows):
    """Extra pack invariants; adapter validation and schema are unmodified."""
    speech.validate_hosted(rows)
    if len(rows) != 12 or Counter(row["brief"] for row in rows) != {"A": 6, "B": 6}:
        raise ValueError("night pack must contain exactly six A and six B rows")
    if {row["id"] for row in rows} != {"PUB-01", "PUB-11"}:
        raise ValueError("night pack uses unsupported registered fixtures")
    tags = set()
    for row in rows:
        base = b.PUBLIC[row["id"]]
        if runner.digest(row["expected"]) != runner.digest(base["expected"]):
            raise ValueError("official expected ledger changed")
        if row["checks"][:len(base["checks"])] != base["checks"]:
            raise ValueError("official dialogue expectations removed or rewritten")
        if row["family"] != base["family"] or row["third_party"] is not False:
            raise ValueError("official recipient role changed")
        if not row["variant_id"].startswith(row["id"] + "__speech_night_"):
            raise ValueError("night variant namespace missing")
        if row["script"] == base["script"] or row["level"] != "hard":
            raise ValueError("authored hard delivery script missing")
        if len(row["stress"]["tags"]) < 3:
            raise ValueError("compound delivery challenge missing")
        if not any(check.startswith("[ledger]") for check in row["checks"]):
            raise ValueError("explicit ledger assertion missing")
        if not any(check.startswith("[dialogue]") for check in row["checks"]):
            raise ValueError("explicit dialogue assertion missing")
        if not any(check.startswith("[actor]") for check in row["checks"]):
            raise ValueError("delivery fidelity assertion missing")
        if len(set(row["oracle_rule_refs"])) != len(row["oracle_rule_refs"]):
            raise ValueError("duplicate source rule reference")
        if re.search(r"https?://|customer_id|product_id|\bp[123]\b", row["script"]):
            raise ValueError("transport or backend identifier leaked into actor script")
        tags.update(row["stress"]["tags"])
    if not REQUIRED_TAGS <= tags:
        raise ValueError("required delivery coverage missing")
    return rows


def validation_report():
    with offline_guards():
        rows = validate_rows(speech.catalog(PACK).to_rows())
        manifest = speech.verify_pack(PACK)
        planned = speech.plan(rows)
    return {
        "validation": "pass", "cases": len(rows),
        "brief_counts": dict(Counter(row["brief"] for row in rows)),
        "registered_fixture_ids": sorted({row["id"] for row in rows}),
        "official_expected_ledgers_unchanged": len(rows),
        "catalog_sha256": manifest["catalog_sha256"],
        "adapter_sha256": manifest["adapter_sha256"],
        "source_pins": manifest["sources"],
        "hash_method": manifest["hash_method"],
        "network_calls": planned["network_calls"],
        "execution_status": planned["execution_status"],
        "voice_asr_certified": planned["voice_asr_certified"],
        "transcript_verdict": "not_assessed",
        "planned_sessions_only": planned["sessions_required"],
        "planned_batches_only": planned["batches_required"],
    }


class NightPackTests(unittest.TestCase):
    def setUp(self):
        self.guards = offline_guards()
        self.addCleanup(self.guards.close)
        self.rows = json.loads(PACK.read_text(encoding="utf-8"))

    def test_current_schema_typed_catalog_and_verify_pack_accept_all_twelve(self):
        b.jsonschema.Draft202012Validator.check_schema(speech.scenario_schema())
        b.jsonschema.Draft202012Validator(
            speech.scenario_schema(), format_checker=b.jsonschema.FormatChecker()).validate(self.rows)
        typed = speech.catalog(PACK)
        self.assertEqual(typed.to_rows(), self.rows)
        validate_rows(self.rows)
        self.assertEqual(speech.verify_pack(PACK)["catalog_sha256"], runner.digest(self.rows))

    def test_registered_facts_roles_faults_and_official_expectations_are_exact(self):
        for row in self.rows:
            with self.subTest(variant=row["variant_id"]):
                base = b.PUBLIC[row["id"]]
                for field in ("brief", "variables", "identity", "products", "faults", "expected"):
                    self.assertEqual(runner.digest(row[field]), runner.digest(base.get(field, [])))
                self.assertEqual(row["checks"][:len(base["checks"])], base["checks"])
                self.assertFalse(row["third_party"])

    def test_rule_registry_anchors_resolve_to_unchanged_official_sources(self):
        self.assertEqual(speech._source_pins(), speech.PINS)
        registry = b.local.CATALOG["rule_registry"]
        for ref in sorted({ref for row in self.rows for ref in row["oracle_rule_refs"]}):
            with self.subTest(ref=ref):
                source = registry[ref]
                path = b.ROOT / source["path"]
                self.assertTrue(path.is_file())
                if "line" in source:
                    text = path.read_text(encoding="utf-8").splitlines()[source["line"] - 1]
                    self.assertTrue(text.strip())
                    if re.fullmatch(r"[AB]\d+", ref):
                        self.assertTrue(text.startswith(ref[1:] + ". "))
                if "json_pointer" in source:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    for part in source["json_pointer"].strip("/").split("/"):
                        value = value[part.replace("~1", "/").replace("~0", "~")]
                    self.assertTrue(value)

    def test_expected_ledger_records_obey_original_openapi(self):
        for row in self.rows:
            for collection, tool in (("promises", "create_promise"), ("notes", "add_note"),
                                     ("callbacks", "schedule_callback"), ("transfers", "transfer_to_agent")):
                schema = speech._request_schema(tool)
                for record in row["expected"][collection]:
                    with self.subTest(variant=row["variant_id"], tool=tool):
                        b.jsonschema.Draft7Validator(schema, format_checker=b.jsonschema.FormatChecker()).validate(
                            {"customer_id": "offline-contract-only", **record})
            close = {"customer_id": "offline-contract-only", "outcome": row["expected"]["outcome"]}
            if row["expected"]["reason"] is not None:
                close["reason"] = row["expected"]["reason"]
            b.jsonschema.Draft7Validator(speech._request_schema("close_call")).validate(close)

    def test_actual_actor_formatter_keeps_oracle_and_backend_fields_out(self):
        for row in self.rows:
            with self.subTest(variant=row["variant_id"]):
                actor = speech.persona_for(row)
                self.assertEqual(actor["name"], row["variant_id"])
                self.assertIn(row["script"], actor["prompt"])
                self.assertIn("negative or qualified confirmation is never a yes", actor["prompt"])
                for forbidden in ("[ledger]", "[dialogue]", "[actor]", "oracle_rule_refs", "product_id", "customer_id"):
                    self.assertNotIn(forbidden, actor["prompt"])
                self.assertNotIn('"promises":', actor["prompt"])
                for check in row["checks"]:
                    self.assertIn(check, actor["successCriteria"])

    def test_unchanged_offline_cli_accepts_custom_pack_and_both_brief_selections(self):
        for brief in (None, "A", "B"):
            output = io.StringIO()
            argv = ["--cases", str(PACK)] + (["--brief", brief] if brief else [])
            with self.subTest(brief=brief), patch("sys.stdout", output):
                self.assertEqual(speech.main(argv), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["network_calls"], 0)
            self.assertEqual(result["execution_status"], "not_executed")
            self.assertEqual(len(result["variants"]), 6 if brief else 12)
            self.assertFalse(result["voice_asr_certified"])
            self.assertFalse(result["execution_supported"])

    def test_live_entrypoint_also_accepts_pack_as_a_keyless_nonexecuting_plan(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(live.main(["--cases", str(PACK), "--brief", "B"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["sessions_required"], 18)

    def test_exact_variant_selection_maps_back_to_real_bank_ids(self):
        for brief in ("A", "B"):
            chosen = [row["variant_id"] for row in self.rows if row["brief"] == brief][:2]
            planned = speech.plan(self.rows, brief=brief, only=chosen, reps=3, batch_size=5)
            self.assertEqual([row["variant_id"] for row in planned["variants"]], chosen)
            self.assertEqual({row["id"] for row in planned["variants"]}, {"PUB-01" if brief == "A" else "PUB-11"})
            self.assertEqual(planned["sessions_required"], 6)

    def test_negative_controls_reject_source_drift_and_unreviewed_rows(self):
        controls = []
        rows = deepcopy(self.rows); rows[0]["variables"]["now"] = "2026-10-15T11:00"; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["identity"]["phone_last4"] = "0000"; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["products"][0]["past_due"] = 421; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["faults"] = [{"tool": "create_promise", "fail_first_n": 1}]; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["id"] = "PUB-99"; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["delivery_profile"] = "unregistered_night"; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["oracle_rule_refs"].append("A999"); controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["expected"]["promises"][0]["amount"] = 126; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["expected"]["promises"][0]["date"] = "2026-10-15"; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["checks"].pop(0); controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["third_party"] = True; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["stress"]["tags"] = ["one"]; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["script"] += " Use product_id p1."; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["hosted_registered"] = False; controls.append(rows)
        rows = deepcopy(self.rows); rows[0]["variant_id"] = rows[1]["variant_id"]; controls.append(rows)
        controls.extend([deepcopy(self.rows[:-1]), deepcopy(self.rows) + [deepcopy(self.rows[0])]])
        for index, rows in enumerate(controls):
            with self.subTest(control=index), self.assertRaises(ValueError):
                validate_rows(rows)

    def test_original_offline_execute_guard_stays_closed(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(speech.main(["--cases", str(PACK), "--execute"]), 2)
        self.assertEqual(json.loads(output.getvalue())["error_code"], "speech_stress_offline_only")


if __name__ == "__main__":
    if sys.argv[1:] == ["--report"]:
        print(json.dumps(validation_report(), ensure_ascii=False, indent=2))
    else:
        unittest.main()
