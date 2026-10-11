"""Fresh fictional source authoring; no detector, review, model, or DEV access.

Only label-free-train-packet.json and packet.schema.json are reviewer material.
This file and manifest.json contain private recruitment intentions, never labels.
Run with python -B authoring.py. All writes are restricted to this author's scope.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
AUTHOR = "fresh-workhorse-fallback-source-author-v6"
LICENSE = "fictional_internal_research_source; no third-party corpus copied"
INTERFACE = "analysis/night-learned-dialogue.v5.next-data-interface.json"
OLD_MANIFESTS = (
    "research/customer-benchmark/semantic-v3-collection/manifest.json",
    "research/customer-benchmark/context-semantic-v2-manifest.json",
    "research/customer-benchmark/learned-dialogue-data.manifest.json",
)
SOURCE_GOAL = {
    "split": "train", "modality": "English synthetic text only",
    "primary": "12 other-primary-act recruitment families; 2-3 paraphrase/role/context contrasts",
    "date": "12 temporal expression families; 3 closed/open/context contrast members",
    "labels": "source-blind independent review and adjudication later",
    "lineage": "source-neutral carrier/template/scenario union; arbitrary authors/IDs do not prove independence",
}
# Declared raw-file hashes from an allowed source manifest, not policy statements.
# Parent must verify compatibility with the current runtime binding before admission.
POLICY_HASH = "d57c049c89aec4615f5b939c5a96ee9bd194142d17045bc4036615cfbdf0f1c7"
API_HASH = "9a8410b12e5c82b6c6a30e9ed7030574d6f919cafdb1e035cef7bd876b0badb8"


def sha(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(obj):
    return sha(canonical(obj))


def opaque(namespace, number):
    return sha(f"fraya-v6-own-author-20261011/{namespace}/{number}")[:24]


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def backbone(text):
    text = normalized(text)
    text = re.sub(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|november|december)\b", "<calendar>", text)
    text = re.sub(r"\b(?:first|second|third|last|one|two|nineteenth|seventeenth)\b", "<slot>", text)
    text = re.sub(r"\d+(?:[./-]\d+)*", "<value>", text)
    return " ".join(re.findall(r"<[^>]+>|\w+", text))


def variant(text, role="payment", targets=(0,), question=None, spans=(), mask=()):
    return {"text": text, "role": role, "targets": list(targets), "question": question,
            "span_specs": list(spans), "mask_reasons": list(mask)}


def span(text, targets=(0,), construction="unspecified", role="current", mask=()):
    return {"text": text, "target_indices": list(targets), "construction_nomination": construction,
            "candidate_role_nomination": role, "mask_reasons": list(mask)}


# Twelve separately devised conversational situations, not twelve gold classes.
# Every member is retained even if a future reviewer finds a different primary act.
PRIMARY = [
    ("distinguish two displayed totals", "explanation request with a numerical contrast", [
        variant("What is the difference between the scheduled 184 pounds and the remaining 263 pounds? I need the distinction explained.", "amount"),
        variant("You asked about 184 pounds. Does that figure include the separate 79 pounds, or are those different totals?", "payment"),
        variant("Before choosing anything, explain which total your question refers to: 184 pounds or 263 pounds.", "support"),
    ]),
    ("ask about a hypothetical timetable", "conditional information question without an undertaking", [
        variant("If a fictional payment arrived a day early, would the schedule display change? I am asking how the display works.", "date"),
        variant("Suppose the transfer reached the plan before its listed date. What would the screen show then?", "payment"),
        variant("Would the same explanation apply to plan two if its scheduled amount arrived early?", "support", (1,)),
    ]),
    ("pause a decision while allowing explanation", "scope-limited conversational pause", [
        variant("Please pause the decision step. You can explain the options while I think, but I am not choosing one yet."),
        variant("Wait before asking me to agree. I only want the explanation at this point.", "support"),
        variant("For plan two, hold that question for a moment; first explain what the two choices mean.", "amount", (1,)),
    ]),
    ("request accessible presentation", "nonfinancial format service request", [
        variant("Could you present the explanation in shorter sentences? The long paragraph is hard to follow.", "support"),
        variant("I need the explanation read one line at a time before I answer the amount question.", "amount"),
        variant("Please use plain text instead of a table for the two plans. I am asking for a format change.", "payment", (0, 1)),
    ]),
    ("distinguish a rehearsal quotation from speaker intent", "quoted training dialogue attribution", [
        variant("The rehearsal script says, ‘I will send 208 pounds on November 16.’ I am asking why the script uses that wording.", "support", spans=(span("November 16", construction="closed_calendar", role="uncertain"),)),
        variant("When I read ‘I will send 208 pounds on November 16’, I am quoting the sample dialogue, not making that statement myself.", "payment", spans=(span("November 16", construction="closed_calendar", role="uncertain"),)),
        variant("Is the sentence ‘I will send 208 pounds on November 16’ meant as an example for plan two?", "date", (1,), spans=(span("November 16", (1,), "closed_calendar", "uncertain"),)),
    ]),
    ("correct a displayed numeral", "correction of supplied information rather than choosing terms", [
        variant("The display you described reads 246 pounds, not 264 pounds. Please correct the description.", "amount"),
        variant("I am correcting what was read aloud: the amount shown for plan one is 246 pounds."),
        variant("For plan two you reversed the digits. The displayed figure is 246 pounds; please say it again accurately.", "support", (1,)),
    ]),
    ("ask an independent glossary question", "new question interrupts an unrelated date question", [
        variant("Before I answer the date question, what does ‘scheduled’ mean in that heading?", "date"),
        variant("Your question is about timing; mine is about the word ‘scheduled’. Could you define it?", "payment"),
        variant("What is the meaning of ‘scheduled’ beside plan two? That is the question I need answered first.", "none", (1,)),
    ]),
    ("request a human explanation", "request for a different explainer", [
        variant("Please let a human explain the next step. I have a question that I cannot phrase in the menu.", "support"),
        variant("Could I speak with a person who can explain these two options? I have not selected either."),
        variant("For the question about plan two, I would like a human to explain what you are asking.", "date", (1,)),
    ]),
    ("find a navigation instruction", "help locating an explanatory guide", [
        variant("Where is the guide that explains the headings on this page? I cannot find the help link.", "support"),
        variant("Please tell me how to open the explanation panel before I respond to your question."),
        variant("Which menu leads to the guide for plan two? I want to read that guide first.", "amount", (1,)),
    ]),
    ("check which object is being discussed", "target identity clarification without commitment", [
        variant("Are you asking about plan one or plan two? Their headings are similar.", "payment", (0, 1)),
        variant("Before answering, can you specify which plan your amount question is about?", "amount", (0, 1)),
        variant("You mentioned plan one, but my question concerns plan two. Which one are we discussing now?", "support", (0,)),
    ]),
    ("separate history from a new choice", "historical explanation with explicit current question", [
        variant("The practice record shows 172 pounds sent on November 3. Why does the history still show two separate entries?", "payment", spans=(span("November 3", construction="closed_calendar", role="uncertain"),)),
        variant("I am asking about the old sample entry dated November 3, not setting a new date. Why is it listed twice?", "date", spans=(span("November 3", construction="closed_calendar", role="uncertain"),)),
        variant("For plan two, explain the two history lines for November 3. They describe the same fictional transfer.", "support", (1,), spans=(span("November 3", (1,), "closed_calendar", "uncertain"),)),
    ]),
    ("repair turn-taking and repetition", "request to repeat a question rather than answer it", [
        variant("We spoke at the same time. Please repeat the question slowly so I can hear all of it.", "date"),
        variant("I caught the amount but missed the question itself. Could you ask it again?", "amount"),
        variant("Please repeat just the question about plan two; I have not answered it yet.", "payment", (1,)),
    ]),
]


DATE = [
    ("ordinal followed by a month complement", "ordinal-of construction in a scheduling reply", [
        variant("For plan one, use the seventeenth of November.", "date", spans=(span("the seventeenth of November", construction="closed_operand"),)),
        variant("For plan one, use the seventeenth of", "date", spans=(span("the seventeenth of", construction="open_complement"),)),
        variant("The practice line is ‘the seventeenth of’. Can you explain what is missing from that line?", "support", spans=(span("the seventeenth of", construction="open_complement", role="uncertain"),)),
    ]),
    ("named month awaiting its ordinal", "month-the construction with a scoped self-correction", [
        variant("Plan two can be scheduled for November the nineteenth.", "date", (1,), spans=(span("November the nineteenth", (1,), "closed_operand"),)),
        variant("Plan two can be scheduled for November the", "date", (1,), spans=(span("November the", (1,), "open_complement"),)),
        variant("For plan two, not November the nineteenth; I meant November the", "date", (1,), spans=(span("November the nineteenth", (1,), "closed_operand", "superseded"), span("November the", (1,), "open_complement"))),
    ]),
    ("offset requiring an after operand", "relative-day offset with a dependent anchor", [
        variant("My date for plan one is three days after Friday.", "date", spans=(span("three days after Friday", construction="closed_operand"),)),
        variant("My date for plan one is three days after", "payment", spans=(span("three days after", construction="open_complement"),)),
        variant("Would three days after work for plan one? I have not specified the anchor yet.", "date", spans=(span("three days after", construction="open_complement", role="uncertain", mask=("boundary_requires_independent_review",)),)),
    ]),
    ("range requiring a to endpoint", "from-to range with shared multi-target scope", [
        variant("For plan one, the window is from November 6 to November 9.", "date", spans=(span("from November 6 to November 9", construction="closed_range"),)),
        variant("For plan one, the window is from November 6 to", "date", spans=(span("from November 6 to", construction="open_endpoint"),)),
        variant("Both plan one and plan two use the window from November 6 to", "date", (0, 1), spans=(span("from November 6 to", (0, 1), "open_endpoint", mask=("multi_target_binding_unsupported",)),)),
    ]),
    ("weekday alternatives awaiting an operand", "or-coordination with a quoted question contrast", [
        variant("For plan two, I can choose Friday or Saturday.", "date", (1,), spans=(span("Friday or Saturday", (1,), "closed_alternative"),)),
        variant("For plan two, I can choose Friday or", "date", (1,), spans=(span("Friday or", (1,), "open_operand"),)),
        variant("Does ‘Friday or’ leave the example for plan two incomplete?", "support", (1,), spans=(span("Friday or", (1,), "open_operand", "uncertain"),)),
    ]),
    ("day-before dependency", "before-anchor phrase and an unsupported double dependency", [
        variant("For plan one, the day before November 21 is the date I mean.", "date", spans=(span("the day before November 21", construction="closed_operand"),)),
        variant("For plan one, the date I mean is the day before", "date", spans=(span("the day before", construction="open_complement"),)),
        variant("For plan one, the date I mean is the day before, after", "date", spans=(span("the day before, after", construction="malformed_dependency", mask=("malformed_temporal_dependency", "unsupported_expression")),)),
    ]),
    ("ordinal weekday awaiting its month", "second-weekday-of phrase with a clause interruption", [
        variant("Plan two should use the second Monday of November.", "date", (1,), spans=(span("the second Monday of November", (1,), "closed_operand"),)),
        variant("Plan two should use the second Monday of", "payment", (1,), spans=(span("the second Monday of", (1,), "open_complement"),)),
        variant("Plan two should use the second Monday of, while the explanation on the other page has several unrelated steps, November.", "date", (1,), spans=(span("the second Monday of, while the explanation on the other page has several unrelated steps, November", (1,), "interrupted_dependency", mask=("cross_clause_dependency_unsupported", "fixed_window_alignment_unknown")),)),
    ]),
    ("last weekday awaiting a container", "last-weekday-in phrase with explicit utterance subject shift", [
        variant("The last Friday in November would suit plan one.", "date", spans=(span("The last Friday in November", construction="closed_operand"),)),
        variant("For plan one, I was thinking of the last Friday in", "date", spans=(span("the last Friday in", construction="open_complement"),)),
        variant("You asked about plan one; for plan two I was thinking of the last Friday in", "date", (0,), spans=(span("the last Friday in", (1,), "open_complement", mask=("utterance_question_target_mismatch",)),)),
    ]),
    ("between awaiting its second endpoint", "between-and range with two separately scoped subjects", [
        variant("Plan one can use between November 12 and November 14.", "date", spans=(span("between November 12 and November 14", construction="closed_range"),)),
        variant("Plan one can use between November 12 and", "date", spans=(span("between November 12 and", construction="open_endpoint"),)),
        variant("Plan one can use between November 12 and; plan two can use November 20.", "date", (0, 1), spans=(span("between November 12 and", construction="open_endpoint", mask=("multi_target_question_binding_unsupported",)), span("November 20", (1,), "closed_calendar", mask=("multi_target_question_binding_unsupported",)))),
    ]),
    ("until awaiting an articulated date", "until-the phrase with invalid-calendar control", [
        variant("For plan two, I would wait until the twenty-third of November.", "date", (1,), spans=(span("until the twenty-third of November", (1,), "closed_operand"),)),
        variant("For plan two, I would wait until the", "date", (1,), spans=(span("until the", (1,), "open_complement"),)),
        variant("For plan two, the sample displays November 31. Is that a valid calendar entry?", "support", (1,), spans=(span("November 31", (1,), "closed_but_invalid_calendar", "uncertain", mask=("invalid_calendar_normalization",)),)),
    ]),
    ("weekday following an anchor", "following-anchor construction with a negated contrast", [
        variant("For plan one, I mean the Monday following November 8.", "date", spans=(span("the Monday following November 8", construction="closed_operand"),)),
        variant("For plan one, I mean the Monday following", "date", spans=(span("the Monday following", construction="open_complement"),)),
        variant("Not the Monday following November 8; for plan one I mean the Monday following", "date", spans=(span("the Monday following November 8", construction="closed_operand", role="superseded"), span("the Monday following", construction="open_complement"))),
    ]),
    ("numeric calendar token with an incomplete endpoint", "ISO-looking date token and invalid-field control", [
        variant("For plan two, the date in the practice record is 2026-11-18.", "date", (1,), spans=(span("2026-11-18", (1,), "closed_numeric_calendar"),)),
        variant("For plan two, the date in the practice record is 2026-11-", "date", (1,), spans=(span("2026-11-", (1,), "open_numeric_field", mask=("numeric_open_expression_support_unknown",)),)),
        variant("For plan two, the practice record prints 2026-13-18. Can that token be interpreted?", "support", (1,), spans=(span("2026-13-18", (1,), "closed_but_invalid_calendar", "uncertain", mask=("invalid_calendar_normalization", "unsupported_expression")),)),
    ]),
]


def make_input(fi, vi, v):
    turn = opaque("turn", fi * 3 + vi)
    question_texts = {
        "payment": "What would you like to discuss next for {subject}?",
        "date": "Which date do you mean for {subject}?",
        "amount": "What is your question about the amount for {subject}?",
        "support": "What explanation would help with {subject}?",
        "none": "What would you like explained about {subject}?",
    }
    subject = " and ".join("plan one" if i == 0 else "plan two" for i in v["targets"])
    pending = []
    for i in range(2):
        pending.append({"target_index": i, "components": {
            "amount": {"status": "complete", "revision": opaque("amount-revision", fi * 2 + i),
                       "value": str(131 + fi * 7 + i * 43), "evidence_refs": []},
            "date": {"status": "complete", "revision": opaque("date-revision", fi * 2 + i),
                     "value": f"2026-11-{6 + i:02d}", "evidence_refs": []}},
            "unresolved_components": []})
    return {"schema_version": "semantic_input.v1", "call_local_id": opaque("call", fi * 3 + vi),
            "turn_id": turn, "state_revision": 3 + fi,
            "policy_hash": POLICY_HASH, "api_hash": API_HASH,
            "phase": "payment", "utterance": {"text": v["text"], "source": "authored_fixture",
            "source_turn_id": turn, "complete_transport": True, "offset_unit": "python_unicode_codepoints"},
            "question": {"question_id": opaque("question", fi * 3 + vi), "role": v["role"],
            "spoken_turn_id": opaque("previous-turn", fi * 3 + vi), "target_indices": v["targets"],
            "text": v["question"] or question_texts[v["role"]].format(subject=subject), "security_field": None},
            "targets": [{"index": i, "type": "loan", "label": "plan one" if i == 0 else "plan two",
                         "product_id": f"fictional-plan-{i + 1}"} for i in range(2)],
            "pending": pending, "spoken_offers": [], "active_readback": None}


def source_span(record_index, text, phrase, start=None):
    if start is None:
        start = text.index(phrase)
    end = start + len(phrase)
    assert text[start:end] == phrase
    return {"raw_field_path": f"/records/{record_index}/input/utterance/text",
            "offset_unit": "python_unicode_codepoints", "char_start": start, "char_end": end,
            "text": phrase, "utf8_byte_start": len(text[:start].encode("utf-8")),
            "utf8_byte_end": len(text[:end].encode("utf-8"))}


def safe_old_metadata():
    """Only declared manifests; never open referenced TRAIN/DEV/source/model files."""
    manifests = {p: json.loads((REPO / p).read_text(encoding="utf-8-sig")) for p in OLD_MANIFESTS}
    v3 = manifests[OLD_MANIFESTS[0]]
    v2 = manifests[OLD_MANIFESTS[1]]
    old = []
    for root in v3["lineage"]["roots"]:
        old.append({"root_id": root["lineage_group_id"], "split": "train_or_dev_unknown_from_this_root_metadata",
                    "scene_digest": sha(normalized(root.get("scene", ""))),
                    "scene_backbone_digest": sha(backbone(root.get("scene", ""))),
                    "declared_carrier_id": root.get("state_carrier_id"),
                    "declared_source_id": root.get("source_episode_id")})
    for group in v2["grouping"]["groups"]:
        for seed in group.get("seed_roots", []):
            old.append({"root_id": group["lineage_group_id"], "split": group["split"],
                        "declared_seed_id": seed, "seed_name_backbone_digest": sha(backbone(seed))})
    bindings = [{"example_id": k, "input_snapshot_sha256": v["input_snapshot_sha256"],
                 "lineage_group_id": v["lineage_group_id"]}
                for k, v in v3.get("review_input_bindings", {}).items()]
    return manifests, old, bindings


def build():
    interface = json.loads((REPO / INTERFACE).read_text(encoding="utf-8-sig"))
    input_schema = copy.deepcopy(interface["collection_json_schema"]["properties"]["records"]["items"]["properties"]["input"])
    packet_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:fraya:label-free-source-review-packet:v6-own",
        "type": "object", "additionalProperties": False,
        "properties": {"schema_version": {"const": "label_free_source_review_packet.v6"},
                       "collection_id": {"type": "string", "minLength": 1}, "split": {"const": "train"},
                       "records": {"type": "array", "minItems": 1, "items": {"type": "object",
                         "additionalProperties": False, "properties": {
                           "example_id": {"type": "string", "pattern": "^[0-9a-f]{24}$"},
                           "input": input_schema}, "required": ["example_id", "input"]}}},
        "required": ["schema_version", "collection_id", "split", "records"]}
    families = PRIMARY + DATE
    records, private = [], {}
    roots = []
    for fi, (scene, carrier, variants) in enumerate(families):
        root = opaque("root", fi)
        ids = []
        for vi, v in enumerate(variants):
            eid = opaque("example", fi * 3 + vi)
            records.append({"example_id": eid, "input": make_input(fi, vi, v)})
            ids.append(eid)
            private[eid] = {"declared_lineage_id": root, "author_id": AUTHOR,
                "fictional_origin": True, "source_family_id": opaque("source-family", fi),
                "scenario_family_id": opaque("scenario-family", fi), "recipe_id": opaque("recipe", fi),
                "template_skeleton_id": opaque("skeleton", fi),
                "contrast_parent_id": ids[0] if vi else None,
                "collection_axis": "primary_other_act" if fi < 12 else "date_open_complement",
                "recruitment_intention": "other_known_primary_act_candidate" if fi < 12 else "linguistic_open_closed_contrast_candidate",
                "assigned_training_labels": None, "review_status": "unreviewed",
                "variant_index": vi, "candidate_specs": v["span_specs"],
                "mandatory_mask_reasons": v["mask_reasons"]}
        roots.append({"root_id": root, "members": ids, "scene": scene, "carrier_recipe": carrier,
            "scene_normalized_sha256": sha(normalized(scene)), "scene_backbone_sha256": sha(backbone(scene)),
            "carrier_recipe_sha256": sha(normalized(carrier)),
            "independence": "provisional construction lineage; shared author/prompt; IID not established",
            "source_neutral_alias_keys": {"source": opaque("source-family", fi), "scenario": opaque("scenario-family", fi),
                                         "recipe": opaque("recipe", fi), "skeleton": opaque("skeleton", fi)}})
    # Deterministic neutral ordering hides axis, family sequence, and variant order.
    records.sort(key=lambda r: sha("packet-order/" + r["example_id"]))
    packet = {"schema_version": "label_free_source_review_packet.v6", "collection_id": opaque("collection", 0),
              "split": "train", "records": records}
    for ri, record in enumerate(records):
        entry = private[record["example_id"]]
        text = record["input"]["utterance"]["text"]
        entry.update({"source_record_path": f"/records/{ri}", "source_record_json_sha256": digest(record),
                      "source_input_json_sha256": digest(record["input"]), "raw_utterance_sha256": sha(text),
                      "normalized_utterance_sha256": sha(normalized(text)), "utterance_backbone_sha256": sha(backbone(text)),
                      "source_evidence": [source_span(ri, text, text)]})
        candidates = []
        for ci, spec in enumerate(entry.pop("candidate_specs")):
            # Later short corrective phrase may be a prefix of an earlier full phrase.
            # For a current phrase after a superseded phrase, bind to the last exact occurrence.
            start = text.rfind(spec["text"]) if spec["candidate_role_nomination"] == "current" else text.index(spec["text"])
            candidates.append({**spec, "source_span": source_span(ri, text, spec["text"], start),
                               "nomination_id": opaque("nomination", ri * 4 + ci),
                               "is_detector_candidate": False, "is_review_annotation": False,
                               "completion_supervision": None, "normalization_status": "not_assessed",
                               "reference_status": "unassessed", "normalized_value": None,
                               "training_mask_required": bool(spec["mask_reasons"]),
                               "eligibility": "masked_by_construction" if spec["mask_reasons"] else "unknown_pending_independent_review_and_actual_alignment"})
        entry["private_candidate_nominations"] = candidates
        # Source-only carrier fingerprint: replace privately authored temporal
        # extents in a separate copy. Never change source text or offsets.
        carrier_text = text
        extents = sorted({(c["source_span"]["char_start"], c["source_span"]["char_end"]) for c in candidates}, reverse=True)
        for start, end in extents:
            carrier_text = carrier_text[:start] + "<temporal>" + carrier_text[end:]
        entry["carrier_phrase_sha256"] = sha(backbone(carrier_text))
        entry["template_skeleton_sha256"] = digest({"carrier": backbone(carrier_text),
            "question_role": record["input"]["question"]["role"],
            "question_target_cardinality": len(record["input"]["question"]["target_indices"])})
    manifests, old_metadata, old_bindings = safe_old_metadata()
    known_input_hashes = {x["input_snapshot_sha256"] for x in old_bindings}
    known_scene_hashes = {x["scene_digest"] for x in old_metadata if "scene_digest" in x}
    known_backbones = {x["scene_backbone_digest"] for x in old_metadata if "scene_backbone_digest" in x}
    fingerprint_fields = ("normalized_utterance_sha256", "utterance_backbone_sha256",
                          "carrier_phrase_sha256", "template_skeleton_sha256")
    compatible_old_fingerprints = {k: set() for k in fingerprint_fields}
    # Traverse only the approved metadata projections, never old nominations/labels.
    def collect_fingerprints(value):
        if isinstance(value, dict):
            for k, item in value.items():
                if k in compatible_old_fingerprints and isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item):
                    compatible_old_fingerprints[k].add(item)
                elif isinstance(item, (dict, list)):
                    collect_fingerprints(item)
        elif isinstance(value, list):
            for item in value:
                collect_fingerprints(item)
    for path, old_manifest in manifests.items():
        for key in ("lineage", "grouping", "review_input_bindings", "identity_repack"):
            collect_fingerprints(old_manifest.get(key, {}))
    # Existing manifests provide raw input bindings and scene/identifier metadata,
    # but no compatible utterance/carrier-normalization fingerprints. Do not infer closure.
    audit = {"source": "declared source-collection metadata/hashes only",
        "old_manifest_paths": list(OLD_MANIFESTS), "declared_old_input_hashes_compared": len(known_input_hashes),
        "exact_input_hash_collisions": [eid for eid, x in private.items() if x["source_input_json_sha256"] in known_input_hashes],
        "declared_scene_metadata_rows_compared": sum("scene_digest" in x for x in old_metadata),
        "scene_metadata_hash_collisions": [r["root_id"] for r in roots if r["scene_normalized_sha256"] in known_scene_hashes],
        "scene_backbone_hash_collisions": [r["root_id"] for r in roots if r["scene_backbone_sha256"] in known_backbones],
        "compatible_old_fingerprint_counts": {k: len(v) for k, v in compatible_old_fingerprints.items()},
        "known_normalized_utterance_collisions": [eid for eid, x in private.items() if x["normalized_utterance_sha256"] in compatible_old_fingerprints["normalized_utterance_sha256"]],
        "known_utterance_backbone_collisions": [eid for eid, x in private.items() if x["utterance_backbone_sha256"] in compatible_old_fingerprints["utterance_backbone_sha256"]],
        "known_carrier_phrase_collisions": [eid for eid, x in private.items() if x["carrier_phrase_sha256"] in compatible_old_fingerprints["carrier_phrase_sha256"]],
        "known_template_skeleton_collisions": [eid for eid, x in private.items() if x["template_skeleton_sha256"] in compatible_old_fingerprints["template_skeleton_sha256"]],
        "old_normalized_utterance_hashes_available": len(compatible_old_fingerprints["normalized_utterance_sha256"]),
        "old_carrier_phrase_hashes_available": len(compatible_old_fingerprints["carrier_phrase_sha256"]),
        "normalized_duplicate_cross_old_status": "unknown; no compatible declared fingerprints; old texts unopened",
        "carrier_phrase_cross_old_status": "unknown; declared opaque carrier IDs are not comparable natural-language hashes",
        "backbone_cross_old_status": "metadata-hash comparison performed; semantic equivalence unresolved",
        "raw_input_hash_limitation": "Identity and revision fields differ; noncollision does not establish new wording or independence.",
        "peer_status": "unread; common initial source goal may create cross-author backbone ancestry",
        "global_closure": "unknown", "split_closure": "not asserted; TRAIN only; known metadata insufficient",
        "parent_action": "Conservatively union both authors and known old lineages by actual carrier/template/scenario evidence before counting. Obtain identifier/fingerprint-only external DEV declarations; never expose DEV wording."}
    alias_edges = []
    for r in roots:
        for eid in r["members"]:
            alias_edges.append({"a": eid, "b": r["root_id"], "reason": "same declared scenario/recipe; all three contrasts retained"})
    internal_fingerprints = {}
    for field in ("normalized_utterance_sha256", "utterance_backbone_sha256", "carrier_phrase_sha256", "template_skeleton_sha256"):
        buckets = defaultdict(list)
        for eid, entry in private.items():
            buckets[entry[field]].append(eid)
        internal_fingerprints[field] = [ids for ids in buckets.values() if len(ids) > 1]
        for ids in internal_fingerprints[field]:
            for other in ids[1:]:
                alias_edges.append({"a": ids[0], "b": other, "reason": field + " equality; source-neutral conservative union"})
    read_paths = [INTERFACE, "analysis/night-learned-dialogue.v5.next-data-interface.txt", *OLD_MANIFESTS,
                  "research/customer-benchmark/learned-dialogue-data.schema.json",
                  "research/customer-benchmark/manifest.json"]
    checkpoint = "analysis/learned-layer-design.checkpoint11-primary-evaluation.json"
    # This checkpoint was read only through instruction/collection fields during author intake.
    if (REPO / checkpoint).exists():
        read_paths.append(checkpoint)
    manifest = {"schema_version": "semantic_v6_extension_parent_manifest.v1",
        "audience": "PARENT ONLY: never supply this manifest or authoring.py to source-blind reviewers",
        "author_id": AUTHOR, "author_runtime": "inherited workhorse fallback; requested GPT5.6 web unavailable; no GPT5.6 identity claim",
        "license": LICENSE, "source_freshness": True, "modality": "English synthetic text only",
        "sampling": "24 freshly devised provisional author roots; 3 related members each; one author; no production sampling",
        "shared_prompt_ancestry": "Both authors have the same initial structural goals; arbitrary different IDs do not prove independence.",
        "cross_author_comparison_invariants": {"input_schema_canonical_sha256": digest(input_schema),
            "declared_source_goal": SOURCE_GOAL, "declared_source_goal_canonical_sha256": digest(SOURCE_GOAL),
            "fingerprint_rules": {"normalized": "NFKC, Unicode casefold, collapse whitespace; source offsets never normalized",
                "backbone": "normalized text; calendar, number and selected ordinal slots abstracted; word tokens retained",
                "carrier": "replace private authored temporal source extents in a copy by <temporal>, then backbone; never a reviewer/model feature",
                "skeleton": "canonical JSON of carrier backbone, question role, question-target cardinality",
                "scope": "same rules must be used by parent for comparison; independently named hash fields do not establish algorithm parity"},
            "peer_schema_or_source_goal_hash_equal": "unknown; peer output unread",
            "parent_union_required_before_support_count": True},
        "read_policy": "No old source wording, weak/review labels, model predictions, DEV contents, peer outputs, secrets, logs, environment, or platform data read.",
        "schema_binding": {"input_contract": "semantic_input.v1 copied from the permitted v5.1 collection interface",
            "policy_hash_origin": "allowed v3 manifest declared briefs/brief-a.md raw file hash",
            "api_hash_origin": "allowed v3 manifest declared tools/openapi.json raw file hash",
            "current_runtime_binding_compatibility": "unverified; parent must verify; no policy truth asserted",
            "pending_state": "fictional previously supplied complete amount/date snapshots; no new-turn annotations; empty evidence refs mean no documentary verification",
            "candidate_contract": "maximal original half-open Unicode and UTF8 spans; private author nominations are never detector candidates or review guidance"},
        "counts": {"packet_rows": len(records), "unique_examples": len(private), "provisional_author_roots": len(roots),
            "primary_scenario_families": len(PRIMARY), "primary_source_rows": len(PRIMARY) * 3,
            "date_expression_families": len(DATE), "date_source_rows": len(DATE) * 3,
            "members_per_root": 3, "private_temporal_nominations": sum(len(x["private_candidate_nominations"]) for x in private.values()),
            "explicitly_masked_nominations": sum(c["training_mask_required"] for x in private.values() for c in x["private_candidate_nominations"]),
            "reviewed_rows": 0, "adjudicated_rows": 0, "assigned_training_labels": 0,
            "actual_eligible_primary_negative_groups": None, "actual_eligible_unfinished_date_groups": None,
            "additional_eligible_support": "unknown; 1 primary and 4 DATE deficits are diagnostics only"},
        "status": {"source_packet_ready": True, "input_schema_compatible": True,
            "independent_reviews": "pending_parent_two_fresh_source_blind_reviewers",
            "adjudication": "pending_parent_distinct_fresh_adjudicator", "actual_detector_alignment": "unrun",
            "admission": "not_granted", "fit_ready": False, "qualified": False, "human_gold": False,
            "IID_gold": False, "payment_authority": False, "current_weights": "untouched"},
        "reviewer_allowlist": [str((HERE / "label-free-train-packet.json").relative_to(REPO)).replace("\\", "/"),
                              str((HERE / "packet.schema.json").relative_to(REPO)).replace("\\", "/")],
        "review_requirements": interface["independent_review_requirements"],
        "source_neutral_lineage": {"roots": roots, "alias_edges": alias_edges,
            "internal_fingerprint_collisions": internal_fingerprints, "old_identifier_only_metadata": old_metadata,
            "old_raw_input_bindings": old_bindings, "audit": audit,
            "root_count_is_support_count": False, "label_dependent_grouping": False},
        "private_author_nominations": private,
        "provenance": [{"path": p, "raw_sha256": sha((REPO / p).read_bytes()),
                        "use": "schema/instructions or declared lineage/hash metadata only"} for p in read_paths],
        "actions": {"model_fits": 0, "detector_runs": 0, "cloud_calls": 0, "platform_calls": 0,
                    "other_agents": 0, "git_calls": 0, "new_DEV_reads": 0, "peer_reads": 0},
        "artifacts": []}
    return packet_schema, packet, manifest


def write_json(path, obj):
    path.write_bytes((json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def main():
    schema, packet, manifest = build()
    import jsonschema
    jsonschema.Draft202012Validator(schema).validate(packet)
    write_json(HERE / "packet.schema.json", schema)
    write_json(HERE / "label-free-train-packet.json", packet)
    for name in ("authoring.py", "packet.schema.json", "label-free-train-packet.json"):
        p = HERE / name
        manifest["artifacts"].append({"path": p.relative_to(REPO).as_posix(), "bytes": p.stat().st_size,
                                      "sha256": sha(p.read_bytes())})
    manifest["source_packet_raw_sha256"] = sha((HERE / "label-free-train-packet.json").read_bytes())
    write_json(HERE / "manifest.json", manifest)
    print(json.dumps({"packet": str(HERE / "label-free-train-packet.json"),
                      "sha256": manifest["source_packet_raw_sha256"], "counts": manifest["counts"]}, indent=2))


if __name__ == "__main__":
    main()
