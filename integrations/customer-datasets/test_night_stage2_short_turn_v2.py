"""Pre-hosted source clarification QA; never runs a bank agent or a benchmark.

Independent v2 tests do not import or modify the frozen v1 tests. The genuine
unchanged speech adapter is imported normally under offline/default-env guards;
catalog and verify_pack receive the explicit v2 path. No adapter global, parser,
catalog function, source rule, actor or expectation is patched.
"""
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import unittest
from unittest.mock import patch
import urllib.request

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "competition-v3/build-the-builder"
OLD = ROOT / "research/customer-benchmark/night-stage2-short-turn-cases.json"
OLD_MANIFEST = OLD.with_suffix(".manifest.json")
PACK = ROOT / "research/customer-benchmark/night-stage2-short-turn-cases.v2.json"
MANIFEST = PACK.with_suffix(".manifest.json")
REVIEW = ROOT / "analysis/night-stage2-independent-source-review.json"
REPORT = ROOT / "analysis/night-stage2-short-turn-v2-clarification.json"
FROZEN = {
    "research/customer-benchmark/night-stage2-short-turn-cases.json": "88d5e668af1a77f7d0940135f5d21dea2f25017952f219aeeb111751524c1508",
    "research/customer-benchmark/night-stage2-short-turn-cases.manifest.json": "ee1bb8bef816d4a39efc5c98af5c73b9df9ddffcd850e109877497fa29d6334f",
    "integrations/customer-datasets/test_night_stage2_short_turn.py": "3d0b4aab88f7764ea52c99e795616256090f1311e87d973885112fe56a5b67bf",
    "analysis/night-stage2-short-turn-pack.json": "3c051c34a2a898fef32fc48a4f1caa9ae37a332f4868334aa0e3b11f7d71164e",
    "analysis/night-stage2-short-turn-pack.txt": "43ad8e65b555993116c53616695bd8e3f18767719d0c60ba627f09f2ce2d05ed",
    "analysis/night-stage2-independent-source-review.json": "9f17c3265513996e564d3fdf0bab6aac0ac023e0d0d57d9b8ffe2dbb010107a2",
    "analysis/night-stage2-independent-source-review.txt": "cd0f6972ee1f757038affff08ec4a05d891a5bdd5caf8dfb41f39c7c38a37e72",
    "competition-v3/build-the-builder/briefs/brief-a.md": "d57c049c89aec4615f5b939c5a96ee9bd194142d17045bc4036615cfbdf0f1c7",
    "competition-v3/build-the-builder/briefs/brief-b.md": "c59c70099148b91c13e9c5e40246a63b58638f09469d735f8eb65771bb63d550",
    "competition-v3/build-the-builder/tools/openapi.json": "9a8410b12e5c82b6c6a30e9ed7030574d6f919cafdb1e035cef7bd876b0badb8",
    "competition-v3/build-the-builder/public-test-set.json": "fb7f4c0082eecb724a6faab771b4339bc62655627e49251e6bb2a0cf59a72fcb",
    "competition-v3/build-the-builder/tools/score.py": "daf55989d47915d9a4f0387c2a4f6748580fcdf66b7d3ec61356925efb0d17d7",
    "competition-v3/build-the-builder/tools/run_cases.py": "c96da9f9189d82850e46bfc551603ff5a62847025b5c50a77b923ad999f3767c",
    "competition-v3/build-the-builder/freya.py": "881c5c86c784e16fe3b53d40a7e9a9d9318f45b6ce6fe4be992c27e522c7732b",
    "integrations/customer-datasets/speech_stress_adapter.py": "ac3b0a19fc57fe54e90b7fd84ffee505eefaf6c0934b7ecc830e5705ff916b28",
}
IMMUTABLE_ROW_FIELDS = ("id", "variant_id", "brief", "variables", "identity", "products", "faults", "expected")
JOINT_CHECK = (
    "[dialogue] B uses a JOINT readback and one JOINT confirmation for EACH CURRENT proposal revision; this is not a limit of one readback for the whole call. "
    "A35 requires another complete joint readback after a correction. An explicitly scripted pause/restoration request also permits its requested fresh readback; "
    "do not penalize these readbacks or seek separate consent per product. If a floor is offered, state the remaining balance stays overdue. "
    "On transfer add no notes. Recorded promises cannot be changed in this call; use the mobile app for such requests."
)
TRANSFER_CUE = (
    "At the next legitimate car-date clarification, response to the quotation, provisional current car readback, or confirmation question following the 75 proposal, "
    "BEFORE any clear customer consent or promise write. Give the actual new-plan request even if the provisional readback uses the previously offered 16 October date; "
    "a confirmation question is not customer consent. This reply must be spoken; never infer a restructuring request from silence."
)
ORDINAL_CUE = (
    "Only after the current individual card persuasion offer explicitly gives 66 on 23 October 2026. "
    "'Second card offer' is the authored referent to those current terms, not an official rule for counting the aggregate today question. "
    "A legitimate question about the ordinal or selected amount/date is allowed; use the following optional explicit-scope reply if asked."
)
ORDINAL_CLARIFY_CUE = (
    "Optional: if the agent asks what 'second card offer' means, whether the aggregate today question counts, which card terms were selected, "
    "or requests the amount/date scope before a complete current grouped readback. Clarification is legitimate and must not be penalized; "
    "it does not reset or consume a source persuasion attempt and supplies no final recording consent."
)
# Zero-based row/check indices. No lexical customer response is changed.
CUE_EDITS = {(8, "S06"): ORDINAL_CUE, (8, "S07"): ORDINAL_CLARIFY_CUE, (11, "S07"): TRANSFER_CUE}
CHECK_EDIT_LOCATIONS = {(6, 8), (9, 8), (10, 8), (8, 12), (11, 12)}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def raw_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def frozen_ok():
    for name, wanted in FROZEN.items():
        if raw_hash(ROOT / name) != wanted:
            raise ValueError("frozen original changed: " + name)


def check_edits(old):
    edits = {(i, 8): JOINT_CHECK for i in (6, 9, 10)}
    old_sentence = "The ordinal refers exclusively to those two explicitly spoken card offers, never to account position or a loan offer."
    replacement = ("The authored ordinal intends the currently offered card terms 66 on 23 October 2026. Official rules define persuasion attempts, not spoken ordinal numbering including the aggregate today question. "
                   "Permit legitimate clarification and the exact explicit 66/23 October reply; do not penalize clarification, reset attempts, or infer a different acceptance from the ambiguous phrase.")
    if old_sentence not in old[8]["checks"][12]:
        raise ValueError("frozen ordinal wording differs")
    edits[(8, 12)] = old[8]["checks"][12].replace(old_sentence, replacement)
    old_sentence = ("The same quotation turn also proposes 75 for the car, without a date or consent, so a required date clarification remains legitimate before the new-plan request. That provisional proposal is never recorded.")
    replacement = ("The same quotation turn proposes 75 without clear consent. The previous actual car offer already supplies 16 October, so either a legitimate date clarification or a provisional current readback/confirmation question may follow. "
                   "S07 must then actually speak the new-plan request before any clear consent or write; only that spoken request triggers restructuring. Never invent a transfer from an unspoken request. The provisional proposal is not recorded.")
    if old_sentence not in old[11]["checks"][12]:
        raise ValueError("frozen transfer wording differs")
    edits[(11, 12)] = old[11]["checks"][12].replace(old_sentence, replacement)
    return edits


def author_v2():
    frozen_ok()
    old, prior = read_json(OLD), read_json(OLD_MANIFEST)
    rows, manifest = deepcopy(old), deepcopy(prior)
    changes = []
    for (index, number), check in check_edits(old).items():
        rows[index]["checks"][number] = check
        changes.append({"pack_pointer": f"/{index}/checks/{number}", "finding": "U1" if number == 8 else "U3" if index == 8 else "U2"})
        if number == 12:
            manifest["cases"][index]["derivation"] = check.removeprefix("[dialogue] ")
    for (index, step_id), cue in CUE_EDITS.items():
        step = next(s for s in manifest["cases"][index]["steps"] if s["step_id"] == step_id)
        old_cue = step["cue"]
        needle = f"{step_id} | Phase: {step['phase']}. Cue: {old_cue} Reply exactly:"
        replacement = f"{step_id} | Phase: {step['phase']}. Cue: {cue} Reply exactly:"
        if rows[index]["script"].count(needle) != 1:
            raise ValueError("frozen script step differs")
        rows[index]["script"] = rows[index]["script"].replace(needle, replacement)
        step["cue"] = cue
        changes.append({"pack_pointer": f"/{index}/script#{step_id}/cue", "manifest_pointer": f"/cases/{index}/steps/{int(step_id[1:])-1}/cue", "finding": "U3" if index == 8 else "U2"})
    for index, row in enumerate(rows):
        manifest["cases"][index]["script_sha256"] = hashlib.sha256(row["script"].encode()).hexdigest()
    manifest.update(pack=PACK.name, pack_version="2", revision_kind="pre_hosted_source_cue_check_clarification",
                    normalized_pack_sha256=digest(rows), parent_pack=OLD.name,
                    parent_normalized_pack_sha256=digest(old), frozen_original_raw_sha256=FROZEN,
                    clarification_changes=changes)
    manifest["diagnostic_source_review_provenance"] = {
        "path": REVIEW.relative_to(ROOT).as_posix(), "raw_sha256": raw_hash(REVIEW),
        "review_kind": "independent_source_based_static_QA", "original_counts": {"pass": 7, "unresolved": 5, "block": 0},
        "original_intended_ledgers_valid": 12, "findings_addressed": ["U1", "U2", "U3"],
        "review_frozen_not_reclassified": True, "independent_benchmark_qualification": False,
        "basis": "User-authorized clarification of source review; no hosted result, candidate, model output or judge verdict used"}
    manifest["catalog_binding"] = {
        "pack_path": PACK.relative_to(ROOT).as_posix(), "manifest_path": MANIFEST.relative_to(ROOT).as_posix(),
        "canonical_pack_sha256": digest(rows), "adapter_call": "speech_stress_adapter.catalog(explicit_v2_path)",
        "native_adapter_manifest_support": False,
        "parent_wrapper_note": "Native catalog takes a path; native verify_pack returns its digest. Parent wrapper must bind this version-specific manifest path and exact raw/canonical hashes; no global OUT/catalog patch."}
    manifest["clarification_branch_spec"] = {
        "U1": {"rows": [7, 10, 11], "unit": "joint_per_current_proposal_revision", "fresh_revision_readback_required": True},
        "U2": {"row": 12, "step_id": "S07", "events": ["car-date clarification", "response to the quotation", "provisional current car readback", "confirmation question"],
               "guard": "before_clear_customer_consent_and_before_promise_write", "actual_spoken_request_required": True},
        "U3": {"row": 9, "steps": ["S06", "S07", "S10"], "clarification_optional_legitimate": True,
               "accepted_scope": {"product_id": "p1", "amount": 66, "date": "2026-10-23"}, "official_attempt_budget_unchanged": True}}
    manifest["freshness"]["v2_status"] = "pre-hosted clarification; diagnostic source review informed these explicit cue/check edits"
    manifest["read_scope"]["v2_revision"] = "V1 pack/manifest, diagnostic source review, original briefs/API/fixtures and adapter source only. Frozen v1 tests/reports and original runner/scorer/actor hashes checked; no v1 tests executed."
    manifest["metadata_history_scope"] = "Inherited authoring/QA limitations describe v1. V2 validation additionally imports the genuine unmodified adapter normally and passes the explicit v2 path to catalog/verify_pack; this does not erase v1 exposure or establish benchmark qualification."
    manifest["limitations"].extend([
        "V2 branch tests are static cue/reachability checks, not an empirical customer-actor run or independent benchmark qualification",
        "Genuine adapter import loads its existing field-cases/scenarios.json dependency; the validator uses its rule registry, not old scenario expectations",
        "Diagnostic review remains frozen at 7 pass/5 unresolved; v2 does not manufacture a new independent review verdict"])
    PACK.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["raw_pack_sha256"] = raw_hash(PACK)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frozen_ok()


def offline_guards():
    stack = ExitStack()
    stack.enter_context(patch.object(os.environ, "get", side_effect=lambda key, default=None: default))
    stack.enter_context(patch.object(os, "getenv", side_effect=lambda key, default=None: default))
    stack.enter_context(patch.object(socket, "socket", side_effect=AssertionError("network forbidden")))
    stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")))
    stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=AssertionError("HTTP forbidden")))
    return stack


def genuine_adapter():
    sys.path.insert(0, str(ROOT / "integrations/customer-datasets"))
    return importlib.import_module("speech_stress_adapter")


def strict_diffs(old, rows, prior, manifest):
    expected = deepcopy(old)
    for (index, number), check in check_edits(old).items():
        expected[index]["checks"][number] = check
    for (index, step_id), cue in CUE_EDITS.items():
        step = next(s for s in prior["cases"][index]["steps"] if s["step_id"] == step_id)
        needle = f"{step_id} | Phase: {step['phase']}. Cue: {step['cue']} Reply exactly:"
        replacement = f"{step_id} | Phase: {step['phase']}. Cue: {cue} Reply exactly:"
        expected[index]["script"] = expected[index]["script"].replace(needle, replacement)
    if canonical(expected) != canonical(rows):
        raise ValueError("pack change outside exact allowlisted cue/check clarifications")
    expected_cases = deepcopy(prior["cases"])
    for (index, number), check in check_edits(old).items():
        if number == 12:
            expected_cases[index]["derivation"] = check.removeprefix("[dialogue] ")
    for (index, step_id), cue in CUE_EDITS.items():
        next(s for s in expected_cases[index]["steps"] if s["step_id"] == step_id)["cue"] = cue
    for index, row in enumerate(rows):
        expected_cases[index]["script_sha256"] = hashlib.sha256(row["script"].encode()).hexdigest()
    if canonical(expected_cases) != canonical(manifest["cases"]):
        raise ValueError("manifest case change outside corresponding cue/check metadata")


def actual_script_steps(row):
    """Parse delivered script, independently of manifest branch metadata."""
    result={}
    for line in row["script"].splitlines():
        match=re.fullmatch(r"(S\d+) \| Phase: (.*?)\. Cue: (.*?) Reply exactly: (.*)",line)
        if match:
            ident,phase,cue,reply=match.groups()
            result[ident]={"phase":phase,"cue":cue,"say":json.loads(reply)}
    return result


def current_grouped_readback_terms(consent_step, year=2026):
    """Read explicit scoped terms in a delivered conditional consent cue."""
    values=[]
    months={"October":10}
    for descriptor in (r"card ending \d{4}",r"personal loan",r"car loan"):
        match=re.search(descriptor+r": (\d+(?:\.\d+)?) on (\d+) (October)",consent_step["cue"],re.I)
        if not match:
            raise ValueError("consent cue lacks an explicit current product tuple")
        amount,day,month=match.groups()
        values.append((Decimal(amount),date(year,months[month],int(day)).isoformat()))
    return tuple(values)


def restructuring_reply_for_event(step,event,customer_consented=False,promise_written=False):
    """Static authored-cue applicability; not an actor or a tool simulator."""
    if customer_consented or promise_written:
        return None
    cue=step["cue"]
    if event=="confirmation question" and "before any confirmation." in cue:
        return None
    # Only positive trigger text before the consent boundary applies. The
    # later prohibition mentioning silence must never become a trigger.
    trigger_text=re.split(r"\bBEFORE\b|\bbefore any confirmation\b",cue)[0]
    if event not in trigger_text:
        return None
    return step["say"]


class ClarificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old, cls.prior = read_json(OLD), read_json(OLD_MANIFEST)
        cls.rows, cls.manifest = read_json(PACK), read_json(MANIFEST)

    def test_fifteen_frozen_original_raw_hashes(self):
        frozen_ok()
        self.assertEqual(self.manifest["frozen_original_raw_sha256"], FROZEN)

    def test_exact_allowlisted_cue_check_diffs_only(self):
        strict_diffs(self.old, self.rows, self.prior, self.manifest)
        self.assertEqual({i + 1 for i,(a,b) in enumerate(zip(self.old,self.rows)) if canonical(a)!=canonical(b)}, {7,9,10,11,12})

    def test_all_twelve_expected_and_fixture_fields_byte_canonical_unchanged(self):
        self.assertEqual(len(self.rows), 12)
        self.assertEqual(Counter(r["brief"] for r in self.rows), {"A":6,"B":6})
        for old, new in zip(self.old,self.rows):
            for field in IMMUTABLE_ROW_FIELDS:
                self.assertEqual(canonical(old[field]), canonical(new[field]), (new["variant_id"],field))

    def test_all_108_reply_strings_and_step_order_unchanged_at_most_80(self):
        count=0
        for old, new, row in zip(self.prior["cases"],self.manifest["cases"],self.rows):
            self.assertEqual([(s["step_id"],s["phase"],s["say"]) for s in old["steps"]],[(s["step_id"],s["phase"],s["say"]) for s in new["steps"]])
            for step in new["steps"]:
                count+=1
                self.assertLessEqual(len(step["say"]),80)
                line=f"{step['step_id']} | Phase: {step['phase']}. Cue: {step['cue']} Reply exactly: {json.dumps(step['say'],ensure_ascii=False)}"
                self.assertEqual(row["script"].count(line),1)
        self.assertEqual(count,108)

    def test_genuine_full_adapter_catalog_and_verify_bind_explicit_v2(self):
        with offline_guards():
            speech=genuine_adapter()
            original_out=speech.OUT
            original_default=speech.catalog.__defaults__
            catalog=speech.catalog(PACK)
            verified=speech.verify_pack(PACK)
            speech.validate_hosted(catalog)
            self.assertEqual(canonical(catalog.to_rows()),canonical(self.rows))
            self.assertEqual(verified["catalog_sha256"],self.manifest["normalized_pack_sha256"])
            self.assertEqual(speech.OUT,original_out)
            self.assertEqual(speech.catalog.__defaults__,original_default)
            self.assertTrue(str(original_out).endswith("speech-stress-cases.json"))
            self.assertEqual(Path(speech.__file__).resolve(),(ROOT/"integrations/customer-datasets/speech_stress_adapter.py").resolve())
        binding=self.manifest["catalog_binding"]
        self.assertEqual(ROOT/binding["pack_path"],PACK)
        self.assertEqual(ROOT/binding["manifest_path"],MANIFEST)
        self.assertEqual(binding["canonical_pack_sha256"],digest(self.rows))
        self.assertEqual(self.manifest["raw_pack_sha256"],raw_hash(PACK))
        self.assertNotEqual(digest(self.old),digest(self.rows))

    def test_strict_source_hashes_and_span_refs_preserved(self):
        self.assertEqual(canonical(self.prior["source_hashes"]),canonical(self.manifest["source_hashes"]))
        self.assertEqual(canonical(self.prior["source_refs"]),canonical(self.manifest["source_refs"]))
        for pin in self.manifest["source_hashes"]:
            data=(ROOT/pin["path"]).read_bytes().replace(b"\r\n",b"\n")
            self.assertEqual(hashlib.sha256(data).hexdigest(),pin["sha256"])
        for ref in self.manifest["source_refs"].values():
            data=(ROOT/ref["path"]).read_bytes().replace(b"\r\n",b"\n")
            lines=data.decode("utf-8").splitlines(keepends=True)
            start,end=ref["span"]["start_line"],ref["span"]["end_line"]
            self.assertEqual(hashlib.sha256(data).hexdigest(),ref["source_sha256"])
            self.assertEqual(hashlib.sha256("".join(lines[start-1:end]).encode()).hexdigest(),ref["span_sha256"])

    def test_u1_joint_current_revision_permits_required_fresh_consent_paths(self):
        a=(KIT/"briefs/brief-a.md").read_text(encoding="utf-8")
        b=(KIT/"briefs/brief-b.md").read_text(encoding="utf-8")
        self.assertIn('35. If the customer changes the date or the amount',a)
        self.assertIn('7. Read all promises back together and ask for one confirmation.',b)
        for index, correction, consent in ((6,"S08","S09"),(9,"S06","S09"),(10,"S06","S09")):
            check=self.rows[index]["checks"][8]
            self.assertIn("EACH CURRENT proposal revision",check)
            self.assertIn("not a limit of one readback",check)
            self.assertIn("another complete joint readback after a correction",check)
            steps={s["step_id"]:s for s in self.manifest["cases"][index]["steps"]}
            self.assertNotIn("Yes, I confirm",steps[correction]["say"])
            self.assertIn("readback",steps[consent]["cue"])
            self.assertIn("Yes, I confirm",steps[consent]["say"])
        steps={s["step_id"]:s for s in self.manifest["cases"][10]["steps"]}
        self.assertIn("even if that turn already contains a readback",steps["S08"]["cue"])
        self.assertIn("following the readiness request",steps["S09"]["cue"])

    def test_u2_all_lawful_preconsent_branches_have_actual_plan_reply(self):
        steps={s["step_id"]:s for s in self.manifest["cases"][11]["steps"]}
        cue=steps["S07"]["cue"]
        for event in ("car-date clarification","response to the quotation","provisional current car readback","confirmation question"):
            self.assertIn(event,cue)
        self.assertIn("BEFORE any clear customer consent or promise write",cue)
        self.assertIn("never infer a restructuring request from silence",cue)
        self.assertIn("I need a new plan for the car loan",steps["S07"]["say"])
        self.assertNotIn("Yes",steps["S06"]["say"])
        self.assertIn("75 on 16 October 2026",steps["S06"]["cue"])
        self.assertEqual(self.rows[11]["expected"]["transfers"],[{"queue":"restructuring"}])
        self.assertEqual(self.rows[11]["expected"]["notes"],[])
        self.assertEqual(self.rows[11]["expected"]["promises"],[])
        self.assertIn("only that spoken request triggers restructuring",self.rows[11]["checks"][12])

    def test_u3_ambiguous_ordinal_clarification_reaches_explicit_scope_and_consent(self):
        steps={s["step_id"]:s for s in self.manifest["cases"][8]["steps"]}
        self.assertEqual(steps["S06"]["say"],"The second card offer works for me.")
        self.assertEqual(steps["S07"]["say"],"I mean the card offer of 66 on 23 October 2026.")
        self.assertIn("aggregate today question",steps["S07"]["cue"])
        self.assertIn("must not be penalized",steps["S07"]["cue"])
        self.assertIn("does not reset or consume a source persuasion attempt",steps["S07"]["cue"])
        self.assertIn("card ending 2288: 66 on 23 October",steps["S10"]["cue"])
        self.assertEqual(steps["S10"]["say"],"Yes, I confirm those payments.")
        b=(KIT/"briefs/brief-b.md").read_text(encoding="utf-8")
        self.assertIn("5. Persuasion attempts are counted per product.",b)
        self.assertEqual(self.rows[8]["expected"]["promises"][0],{"product_id":"p1","amount":66,"date":"2026-10-23"})

    def test_delivered_script_current_revision_consent_and_request_branch_matrix(self):
        # Values below come from the frozen authored spoken corrections and
        # source full/floor fields, independently of expected ledger records.
        public={r["id"]:r for r in read_json(KIT/"public-test-set.json")}
        p=public["PUB-11"]["products"]
        full=[Decimal(str(v["past_due"])) for v in p]
        floor=Decimal(str(p[1]["instalment_amount"]))
        revised={
          6:((full[0],"2026-10-22"),(full[1],"2026-10-22"),(full[2],"2026-10-30")),
          9:((full[0],"2026-10-21"),(floor,"2026-10-22"),(full[2],"2026-10-21")),
          10:((full[0],"2026-10-22"),(full[1],"2026-10-20"),(full[2],"2026-10-20"))}
        stale={6:tuple((v,"2026-10-22") for v in full),9:tuple((v,"2026-10-21") for v in full),10:tuple((v,"2026-10-20") for v in full)}
        for index,terms in revised.items():
            steps=actual_script_steps(self.rows[index])
            consent=steps["S09"]
            self.assertEqual(current_grouped_readback_terms(consent),terms)
            self.assertNotEqual(current_grouped_readback_terms(consent),stale[index])
            self.assertIn("Yes, I confirm",consent["say"])
        current=actual_script_steps(self.rows[11])["S07"]
        old=actual_script_steps(self.old[11])["S07"]
        for event in ("car-date clarification","response to the quotation","provisional current car readback","confirmation question"):
            reply=restructuring_reply_for_event(current,event)
            self.assertEqual(reply,"Those are just quoted labels. I need a new plan for the car loan.")
            self.assertIsNone(restructuring_reply_for_event(current,event,customer_consented=True))
            self.assertIsNone(restructuring_reply_for_event(current,event,promise_written=True))
        self.assertIsNone(restructuring_reply_for_event(old,"confirmation question"))
        self.assertIsNone(restructuring_reply_for_event(old,"provisional current car readback"))
        self.assertIsNone(restructuring_reply_for_event(current,"silence"))
        ordinal=actual_script_steps(self.rows[8])
        self.assertIn("Optional",ordinal["S07"]["cue"])
        self.assertIn("amount/date scope",ordinal["S07"]["cue"])
        self.assertEqual(current_grouped_readback_terms(ordinal["S10"]),
          ((Decimal(str(p[0]["minimum_payment"])),"2026-10-23"),(full[1],"2026-10-16"),(full[2],"2026-10-16")))

    def test_source_amount_date_outcome_and_api_contracts_independently(self):
        a=(KIT/"briefs/brief-a.md").read_text(encoding="utf-8")
        line=next(s for s in a.splitlines() if s.startswith("Business days are"))
        holidays={date.fromisoformat(d) for d in re.findall(r"\d{4}-\d{2}-\d{2}",line)}
        api=read_json(KIT/"tools/openapi.json")
        public={r["id"]:r for r in read_json(KIT/"public-test-set.json")}
        def business(day): return day.weekday()<5 and day not in holidays
        for row in self.rows:
            base=public[row["id"]]
            for key in ("brief","variables","identity","products"):
                self.assertEqual(canonical(row[key]),canonical(base[key]))
            products={f"p{i+1}":p for i,p in enumerate(base["products"])}
            for promise in row["expected"]["promises"]:
                p=products[promise["product_id"]]
                floor=p.get("minimum_payment",p.get("instalment_amount"))
                self.assertLessEqual(Decimal(str(floor)),Decimal(str(promise["amount"])))
                self.assertLessEqual(Decimal(str(promise["amount"])),Decimal(str(p["past_due"])))
                today=date.fromisoformat(row["variables"]["now"][:10]); limit=today; remaining=12 if p["days_late"]<=7 else 7
                while remaining:
                    limit+=timedelta(days=1)
                    if business(limit): remaining-=1
                day=date.fromisoformat(promise["date"])
                self.assertTrue(business(day)); self.assertLessEqual(today,day); self.assertLessEqual(day,limit)
            for collection,tool in (("promises","create_promise"),("notes","add_note"),("transfers","transfer_to_agent")):
                schema=api["paths"]["/"+tool]["post"]["requestBody"]["content"]["application/json"]["schema"]
                for record in row["expected"][collection]:
                    jsonschema.Draft7Validator(schema,format_checker=jsonschema.FormatChecker()).validate({"customer_id":"reserved-synthetic-local",**record})
            if row["expected"]["outcome"]=="transferred": self.assertEqual(row["expected"]["notes"],[])
        notes=self.rows[7]["expected"]["notes"]
        self.assertEqual(next(n["reason"] for n in notes if n["reason"]!="paid"),self.rows[7]["expected"]["reason"])

    def test_negative_controls_for_unauthorized_ledger_reply_and_fixture_edits(self):
        for mutate in (
            lambda r:r[0]["expected"]["promises"][0].update(amount=201),
            lambda r:r[0]["products"][0].update(past_due=421),
            lambda r:r[8].update(script=r[8]["script"].replace("The second card offer works for me.","Yes, I confirm."))):
            rows=deepcopy(self.rows); mutate(rows)
            with self.assertRaisesRegex(ValueError,"allowlisted"):
                strict_diffs(self.old,rows,self.prior,self.manifest)

    def test_diagnostic_review_not_relabelled_or_qualification_claimed(self):
        review=read_json(REVIEW)
        self.assertEqual(review["summary"]["row_classification_counts"],{"pass":7,"unresolved":5,"block":0})
        self.assertEqual(review["summary"]["intended_ledger_passes"],12)
        self.assertFalse(self.manifest["diagnostic_source_review_provenance"]["independent_benchmark_qualification"])
        self.assertEqual(self.manifest["pack_version"],"2")


def main():
    if sys.argv[1:]==["--build"]:
        author_v2()
        return
    with offline_guards():
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ClarificationTests))
    rows,manifest=read_json(PACK),read_json(MANIFEST)
    frozen_ok()
    report={"status":"pass" if result.wasSuccessful() else "fail", "revision_kind":"pre_hosted_source_clarification", "pack_version":"2",
      "cases":len(rows),"brief_counts":dict(Counter(r["brief"] for r in rows)),"unchanged_expected_ledgers":12,
      "unchanged_reply_strings":108,"max_reply_unicode_characters":max(len(s["say"]) for c in manifest["cases"] for s in c["steps"]),
      "canonical_pack_sha256":digest(rows),"raw_pack_sha256":raw_hash(PACK),"raw_manifest_sha256":raw_hash(MANIFEST),
      "frozen_original_hashes":FROZEN,"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
      "genuine_adapter_catalog_explicit_v2_path":result.wasSuccessful(),"old_global_adapter_monkeypatch":False,
      "catalog_binding":manifest["catalog_binding"],"clarification_changes":manifest["clarification_changes"],
      "source_hashes":manifest["source_hashes"],"source_review":manifest["diagnostic_source_review_provenance"],
      "read_scope":manifest["read_scope"],"limitations":manifest["limitations"],"repetition_plan":manifest["repetition_plan"],
      "hosted_calls":0,"agent_executed":False,"judge_executed":False,"independent_benchmark_qualification":False,
      "parent_queue_slots_state_touched":False,"test_raw_sha256":raw_hash(Path(__file__))}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    REPORT.with_suffix(".txt").write_text(
      f"V2 pre-hosted source clarification: {report['status']}\n12 variants (6 A + 6 B); all 12 expected ledgers and immutable fixture fields byte-canonical unchanged.\n"
      f"108 unchanged replies; maximum {report['max_reply_unicode_characters']} Unicode characters.\n"
      f"Local independent tests: {result.testsRun}; failures={len(result.failures)}; errors={len(result.errors)}.\n"
      "U1: joint confirmation per current proposal revision, allowing corrected/requested fresh grouped readbacks.\n"
      "U2: actual restructuring reply applicable on clarification, quotation response, provisional current readback or confirmation question before clear consent/write.\n"
      "U3: legitimate ordinal clarification resolves explicit card 66 / 23 October, without changing persuasion budget.\n"
      "Genuine unmodified adapter catalog and verify_pack called with explicit v2 path; no old global adapter patch.\n"
      "Canonical SHA-256: "+digest(rows)+"\n"
      "15 frozen original hashes verified, including v1 outputs/test, diagnostic reviews, kit source/scorer/runner/actor and adapter.\n"
      "Diagnostic source review remains 7 pass / 5 unresolved / 0 block with 12 valid intended ledgers; not independently rerun or relabelled.\n"
      "No hosted calls, benchmark, candidate/model/DEV reads, network/platform/Git actions or parent state changes.\n"
      "Static branch/source tests only; no empirical actor or independent benchmark qualification. Native adapter has no manifest parser; parent wrapper must bind the explicit v2 manifest path/hash.\n",
      encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=="__main__": main()
