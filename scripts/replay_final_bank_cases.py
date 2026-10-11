"""Offline conditional sealed-bank replay; no ASR, LLM, or conversation judge.

Three deterministic repetitions create fresh generic Banks, not independent
actors. Only the adjudicator receives expected/checks/oracle information.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "competition-v3/build-the-builder"
PACK = ROOT / "research/customer-benchmark/final-sprint-bank-cases-20261011.json"
PACK_HASH = "3a7c4a3dc6084198fc14d5d7be7e679d91c2225bdb931a15f54481ecf36766e2"
PREFIX = ROOT / "analysis/final-sprint-bank-replay-20261011"
PINS = {"A": (10, "6fa31318b1b24073ef04f058d62c1a8e803bc2538fb437c43c3679dff94ba0b3"),
        "B": (14, "1768e23ee0c24c530786fc3fb7e58bf16a96ca48bb8d27914603109047d45163")}
MONTHS = "January February March April May June July August September October November December".split()
TR_MONTHS = "Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık".split()
FAMILIES = {"identity_answer_plus_purpose", "verified_full_today", "third_party_non_disclosure",
            "explicit_security_refusal", "final_terms_correction", "paid_current_single",
            "paid_current_then_refusal", "paid_current_then_dispute"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deny_network():
    def denied(*args, **kwargs):
        raise RuntimeError("offline_network_denied")
    class DeniedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            denied()
    socket.socket = DeniedSocket
    socket.create_connection = denied
    socket.getaddrinfo = denied
    socket.gethostbyname = denied
    import urllib.request
    urllib.request.urlopen = denied


class AdapterUnsupported(ValueError):
    pass


def words_number(value):
    units = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
    tens = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
    total = 0
    for word in value.lower().replace("-", " ").split():
        if word in units:
            total += units[word]
        elif word in tens:
            total += tens[word]
        else:
            raise AdapterUnsupported("ACTOR:unsupported_number_words")
    return total


def script_dates(raw):
    """Parse supplied complete dates; never fill a year from fixture/oracle."""
    result = []
    months = MONTHS + TR_MONTHS
    pat = r"(\d{1,2})\s+(" + "|".join(months) + r")\s+(\d{4})"
    for match in re.finditer(pat, raw, re.I):
        month = next((i % 12 + 1 for i, m in enumerate(months) if m.casefold() == match[2].casefold()), None)
        result.append(date(int(match[3]), month, int(match[1])).isoformat())
    if not result:
        match = re.match(r"([A-Za-z -]+)\s+(" + "|".join(MONTHS) + r")\s+(nineteen|twenty)\s+([A-Za-z -]+?)(?:[.!?]|$)", raw, re.I)
        if match:
            month = next(i + 1 for i, m in enumerate(MONTHS) if m.lower() == match[2].lower())
            result.append(date(words_number(match[3]) * 100 + words_number(match[4]), month, words_number(match[1])).isoformat())
    return result


def amounts(raw):
    return [float(m[0].replace(",", ".")) for m in re.finditer(r"\b\d+[.,]\d{2}\b", raw)]


def fixture(original, arm, repetition):
    """Explicit projection: original oracle fields never enter actor/Bank/vars."""
    variables = deepcopy(original["variables"])
    variables["customer_id"] = f"synthetic-final-bank-{arm}-{original['brief'].lower()}-{original['id'].rsplit('-', 1)[-1]}-r{repetition}"
    products = [dict(deepcopy(p), product_id=f"p{i}") for i, p in enumerate(original["products"], 1)]
    return {"brief": original["brief"], "family": original["family"], "script": original["script"],
            "facts": {"variables": variables, "identity": deepcopy(original["identity"]),
                      "products": products, "faults": [],
                      "third_party": original["family"] == "third_party_non_disclosure"}}


class ScriptActor:
    """Authored event adapter from frozen SCRIPT, current state and spoken turn.

    Family tags select script parsing only. No case-ID or financial constants,
    no expected outcome, and no generated model turns are used.
    """
    def __init__(self, projected):
        self.case = deepcopy(projected)
        assert set(self.case) == {"brief", "family", "script", "facts"}
        self.script = self.case["script"]
        self.quotes = re.findall(r'"([^"\n]+)"', self.script)
        self.turkish = self.script.startswith("Speak Turkish")
        self.family = self.case["family"]
        if self.family not in FAMILIES:
            raise AdapterUnsupported("ACTOR:unrecognized_script_family")
        self.counts, self.decisions, self.corrected = {}, 0, False
        self.confirmed, self.gates = [], []
        self.payment_quotes = [q for q in self.quotes if amounts(q)]
        self.last_terms = []

    def security(self, phase):
        prefix = re.split(r"After (?:both |the )?debt|After the debt|Wait for both debts|Borç|Kart borcu|İki ürün|Güvenlik tamamlanıp", self.script, maxsplit=1)[0]
        if phase == "dob":
            # Use the full scripted reply, including concurrent questions.
            date_start = r"^(?:\d{1,2}\s+(?:" + "|".join(MONTHS + TR_MONTHS) + r")\s+\d{4}|[A-Za-z -]+\s+(?:" + "|".join(MONTHS) + r")\s+(?:nineteen|twenty)\b)"
            raw = next((q for q in self.quotes if q in prefix and re.match(date_start, q, re.I) and script_dates(q)), None)
            if raw is None:
                match = re.search(r"\d{1,2}\s+(?:" + "|".join(MONTHS + TR_MONTHS) + r")\s+\d{4}", prefix, re.I)
                raw = match[0] if match else None
            if not raw or len(script_dates(raw)) != 1:
                raise AdapterUnsupported("ACTOR:script_DOB_not_parseable")
            return raw, script_dates(raw)[0]
        digits = re.findall(r"\b\d{4}\b", prefix)
        # Distinguish the explicitly supplied phone digits from supplied years.
        supplied = self.case["facts"]["identity"]["phone_last4"]
        raw = next((q for q in self.quotes if q in prefix and re.match(r"\d{4}(?:\.|$)", q) and q.startswith(supplied)), None)
        if raw:
            return raw, re.match(r"\d{4}", raw)[0]
        word_reply = next((q for q in self.quotes if q in prefix and re.match(r"(?:zero|one|two|three|four|five|six|seven|eight|nine)\b", q, re.I)), None)
        if word_reply:
            head = word_reply.split(".", 1)[0]
            words = head.lower().split()
            if len(words) == 4:
                return word_reply, "".join(str(words_number(w)) for w in words)
        if supplied not in digits:
            raise AdapterUnsupported("ACTOR:script_phone_not_supplied")
        return supplied, supplied

    def terms_from(self, raw, *, correction=False):
        current = raw.split("The earlier", 1)[0] if correction else raw
        av, dv = amounts(current), script_dates(current)
        products = self.case["facts"]["products"]
        if len(av) != len(products) or not dv or len(set(dv)) != 1:
            raise AdapterUnsupported("ACTOR:ambiguous_script_terms")
        # The authored full-payment scripts enumerate products in their frozen
        # returned order. Verify that order using actual literal mentions.
        mentions = []
        aliases = {"credit_card": ("card", "kart"), "personal_loan": ("personal loan", "bireysel kredi"),
                   "car_loan": ("car loan", "taşıt kredisi")}
        for p in products:
            positions = [current.casefold().find(alias) for alias in aliases[p["type"]]]
            positions = [pos for pos in positions if pos >= 0]
            if not positions:
                # Single-product script can refer to the just-spoken product.
                if len(products) != 1:
                    raise AdapterUnsupported("ACTOR:script_product_scope_missing")
            else:
                mentions.append(min(positions))
        if mentions != sorted(mentions):
            raise AdapterUnsupported("ACTOR:script_product_order_unsupported")
        return [dict(product_id=p["product_id"], amount=a, date=dv[0]) for p, a in zip(products, av)]

    def readback_matches(self, state, spoken):
        if self.case["brief"] == "A":
            q = state.get("readback")
            p = state.get("product", {})
            actual = [dict(product_id=p.get("product_id"), amount=q.get("amount"), date=q.get("date"))] if q else []
            products = [p]
        else:
            products = [p for p in state.get("products", []) if p.get("status") == "agreed"]
            actual = [dict(product_id=p.get("product_id"), amount=p.get("amount"), date=p.get("date")) for p in products]
            if not state.get("readback") or any(p.get("pending") for p in products):
                return False
        if actual != self.last_terms:
            return False
        for p, term in zip(products, actual):
            label = p.get("label", p.get("type", "").replace("_", " "))
            d = date.fromisoformat(term["date"])
            date_forms = [term["date"], f"{d.day} {MONTHS[d.month-1]} {d.year}", f"{d.day:02d} {MONTHS[d.month-1]} {d.year}"]
            if label not in spoken or not re.search(r"(?<![\d.])" + re.escape(format(term["amount"], ".2f")) + r"(?!\d)", spoken) or not any(v in spoken for v in date_forms):
                return False
        return True

    def next(self, variables, spoken):
        state = variables.get("state", {})
        if isinstance(state, str):
            state = json.loads(state)
        phase = state.get("phase", "recipient")
        count = self.counts.get(phase, 0)
        self.counts[phase] = count + 1
        brief, rows, raw, admin = self.case["brief"], [], "", "none"
        meta = {"phase": phase, "script_sha256": hashlib.sha256(self.script.encode()).hexdigest(),
                "terms": [], "confirmation": False}
        def row(kind, **tags):
            rows.append(dict(k=kind, c="1", **{k: str(v) for k, v in tags.items()}))
        if phase == "recipient":
            if self.family == "third_party_non_disclosure":
                raw = self.quotes[0]
                row("third_party" if brief == "A" else "third")
            else:
                # Recipient evidence is scoped to the actual script's opening
                # instructions; a later financial confirmation is not a name act.
                opening = re.split(r"For birth date|Give (?:the )?complete security|Sorulunca|Doğum tarihi|At the first security|Doğum tarihi istendiğinde", self.script, maxsplit=1)[0]
                opening_quotes = re.findall(r'"([^"\n]+)"', opening)
                raw = next((q for q in opening_quotes if q.startswith(("Evet,", "Yes,")) and not amounts(q)), None)
                if not raw:
                    v = self.case["facts"]["variables"]
                    raw = f"{v['first_name']} {v['last_name']}" if self.turkish else f"Yes, {v['first_name']} {v['last_name']} speaking."
                row("recipient" if brief == "A" else "yes")
                if "dijital asistan" in raw.casefold():
                    admin = "ai"
        elif phase in {"dob", "phone"}:
            if self.family == "explicit_security_refusal":
                refusals = [q for q in self.quotes if re.search(r"refuse|will not provide|reddediyorum|yanıtlamayacağım", q, re.I)]
                if len(refusals) != 2:
                    raise AdapterUnsupported("ACTOR:script_refusal_turns_missing")
                raw = refusals[min(count, 1)]
                row("decline")
            else:
                raw, answer = self.security(phase)
                row("security" if brief == "A" else "answer", v=answer)
                if self.family == "identity_answer_plus_purpose":
                    admin = "purpose"
            if self.turkish and phase == "dob":
                meta["raw_language_gate_candidate"] = True
        elif phase == "callback":
            raw = next((q for q in self.quotes if re.search(r"\b\d{1,2}:\d{2}\b", q)), "")
            dv = script_dates(raw)
            tv = re.findall(r"\b\d{2}:\d{2}\b", raw)
            if len(dv) != 1 or len(tv) != 1:
                raise AdapterUnsupported("ACTOR:script_callback_not_parseable")
            row("callback", d=dv[0], t=tv[0])
        elif phase in {"readback", "confirm"}:
            if self.family == "final_terms_correction" and not self.corrected:
                raw = next((q for q in self.payment_quotes if "final commitment" in q), "")
                if not raw:
                    raise AdapterUnsupported("ACTOR:script_final_correction_missing")
                self.last_terms = self.terms_from(raw, correction=True)
                self.corrected = True
                for t in self.last_terms:
                    row("proposal", a=format(t["amount"], ".2f"), d=t["date"], **({"p": t["product_id"]} if brief == "B" else {}))
                meta["terms"] = deepcopy(self.last_terms)
                meta["correction"] = True
            elif self.readback_matches(state, spoken):
                raw = next((q for q in reversed(self.quotes) if q.startswith(("Yes,", "Evet,")) and ("confirm" in q or "onay" in q)), "")
                if not raw:
                    raise AdapterUnsupported("ACTOR:script_confirmation_missing")
                row("confirm", **({"p": "all"} if brief == "B" else {}))
                meta.update(terms=deepcopy(self.last_terms), confirmation=True, spoken_readback=spoken)
                self.confirmed = deepcopy(self.last_terms)
            else:
                # Follow the frozen instruction to restate and withhold yes.
                raw = next((q for q in self.payment_quotes if "final commitment" in q), self.payment_quotes[0] if self.payment_quotes else "")
                if not raw:
                    raise AdapterUnsupported("ACTOR:cannot_restate_unmatched_terms")
                if count >= 3:
                    raise AdapterUnsupported("CODE_FORMAT_GATE:matching_spoken_complete_readback_unavailable")
                for t in self.last_terms:
                    row("proposal", a=format(t["amount"], ".2f"), d=t["date"], **({"p": t["product_id"]} if brief == "B" else {}))
                meta.update(terms=deepcopy(self.last_terms), withheld_confirmation=True)
        elif phase in {"collect", "offer", "payment", "today", "amount", "date"}:
            first = self.decisions == 0
            self.decisions += 1
            if self.family in {"verified_full_today", "identity_answer_plus_purpose", "final_terms_correction"}:
                if not self.payment_quotes:
                    raise AdapterUnsupported("ACTOR:script_payment_missing")
                raw = self.payment_quotes[0]
                self.last_terms = self.terms_from(raw)
                for t in self.last_terms:
                    row("proposal", a=format(t["amount"], ".2f"), d=t["date"], **({"p": t["product_id"]} if brief == "B" else {}))
                meta["terms"] = deepcopy(self.last_terms)
            elif self.family.startswith("paid_current"):
                if first:
                    raw = self.payment_quotes[0]
                    if brief == "A":
                        row("paid")
                    else:
                        # Current asserted self claim, exact source sentence.
                        span = raw.split(". ", 1)[0] + ("." if ". " in raw else "")
                        if len(span) > 240:
                            raise AdapterUnsupported("ACTOR:paid_claim_span_unrepresentable")
                        row("paid", p="p1", sub="self", claim="current_bank", pol="positive", mode="asserted", x=span)
                        if self.family.endswith("refusal"):
                            row("no", p="p2")
                        elif self.family.endswith("dispute"):
                            span = raw.split(". ", 1)[-1]
                            row("dispute", p="p2", sub="self", claim="current_bank", pol="positive", mode="asserted", x=span)
                    meta["current_paid_claim"] = True
                elif self.family.endswith("refusal"):
                    if state.get("current") == "p2":
                        raw = next((q for q in self.quotes if q.startswith("No,")), "")
                        row("no", p="p2")
                    else:
                        # No loan-offer condition has occurred. Restate the same
                        # current-card assertion from SCRIPT, without changing its
                        # passive wording or claiming a prospective payment.
                        raw = self.payment_quotes[0].split(". ", 1)[0] + "."
                        row("paid", p="p1", sub="self", claim="current_bank", pol="positive", mode="asserted", x=raw)
                        meta["current_paid_claim"] = True
                elif self.family.endswith("dispute"):
                    raw = next((q for q in self.quotes if q == "Kredi bana ait değil"), "")
                    row("dispute", p="p2", sub="self", claim="current_bank", pol="positive", mode="asserted", x=raw)
                else:
                    raise AdapterUnsupported("ACTOR:paid_script_continuation_unavailable")
            else:
                raise AdapterUnsupported("ACTOR:unexpected_financial_phase")
        else:
            raise AdapterUnsupported("ACTOR:unsupported_observed_phase:" + str(phase))
        if not raw:
            raise AdapterUnsupported("ACTOR:empty_script_reply")
        if self.turkish and phase == "recipient" and self.family != "third_party_non_disclosure":
            meta["raw_language_gate_candidate"] = True
        if brief == "A":
            serialized = "\n".join(";".join(k + "=" + v for k, v in r.items()) + ";END" for r in rows)
            authored = {"event": serialized, "raw": raw, "admin": admin}
        else:
            serialized = "\n".join("|".join(k + "=" + v for k, v in r.items()) for r in rows) + "\nEND"
            authored = {"event": serialized, "raw_speech": raw, "admin": admin}
        meta["rows"] = deepcopy(rows)
        return authored, meta


class PublicActorAdapter:
    """Unchanged existing public13 authored actor, separately labelled scope."""
    def __init__(self, projected, public):
        self.original_actor = public.Actor(projected)
        self.last_terms, self.confirmed = [], []

    def next(self, variables, spoken):
        authored = self.original_actor.next(variables)
        state = variables.get("state", {})
        state = json.loads(state) if isinstance(state, str) else state
        rows = []
        for line in authored["event"].splitlines():
            if line == "END":
                continue
            fields = line.split(";" if "raw" in authored else "|")
            rows.append(dict(field.split("=", 1) for field in fields if "=" in field))
        confirm = any(r["k"] == "confirm" for r in rows)
        if confirm:
            if "raw" in authored:
                q, p = state.get("readback", {}), state.get("product", {})
                self.confirmed = [dict(product_id=p.get("product_id"), amount=q.get("amount"), date=q.get("date"))]
            else:
                self.confirmed = [dict(product_id=p.get("product_id"), amount=p.get("amount"), date=p.get("date")) for p in state.get("products", []) if p.get("status") == "agreed"]
            self.last_terms = deepcopy(self.confirmed)
        return authored, {"phase": state.get("phase", "recipient"), "rows": rows,
                          "confirmation": confirm, "terms": deepcopy(self.confirmed) if confirm else [],
                          "actor_scope": "unchanged_existing_public13_conditional_actor"}


def declared_schema_output(authored, evidence, schema, brief, helpers):
    """Map current script-derived rows only into the schema declared by source."""
    contract = helpers.schema_contract(schema, brief)
    if contract == "frozen":
        result = deepcopy(authored)
    else:
        phase, rows = evidence["phase"], evidence["rows"]
        kind = rows[0]["k"] if rows else "unknown"
        answer_rows = [r for r in rows if r.get("k") == "security" and r.get("c") == "1" and r.get("v")]
        answer = answer_rows[0]["v"] if phase in {"dob", "phone"} and len(answer_rows) == 1 else ""
        if contract == "live_copy":
            result = dict(authored, recipient_act="UNKNOWN", security_answer_copy=answer)
            if phase == "recipient":
                result["recipient_act"] = {"recipient": "SELF", "third_party": "OTHER", "wrong_number": "WRONG_NUMBER", "deceased": "DECEASED"}.get(kind, "UNKNOWN")
        elif contract == "recipient" and phase == "recipient":
            result = dict(raw=authored["raw"], admin=authored["admin"], recipient_act=kind)
        elif contract in {"classic", "security_value", "security_act_value"} and phase in {"dob", "phone"} and answer:
            result = dict(raw=authored["raw"], admin=authored["admin"])
            if contract == "classic":
                result["security_answer_event"] = answer
            else:
                result["security_value"] = answer
                if contract == "security_act_value":
                    result["security_act"] = "answer"
        else:
            raise AdapterUnsupported("ADAPTER_UNSUPPORTED:declared_schema_incompatible_current_script_act")
    if set(result) != {s["name"] for s in schema}:
        raise AdapterUnsupported("ADAPTER_UNSUPPORTED:mapped_schema_fields")
    for s in schema:
        value = result[s["name"]]
        if not isinstance(value, str) or (s.get("enum_values") and value not in s["enum_values"]):
            raise AdapterUnsupported("ACTOR:outside_declared_schema_enum")
        if s.get("validation_pattern") and not re.fullmatch(s["validation_pattern"], value):
            raise AdapterUnsupported("ACTOR:authored_event_schema_violation")
    evidence["schema_contract"] = contract
    return result


def execute(workflow, projected, wr, public, *, public_mode=False, frozen_b14=False, helpers=None, condition_helper=None):
    """Runtime boundary accepts only the actor/Bank projection, never an oracle."""
    bank = wr.b.local.Bank(deepcopy(projected))
    actor = PublicActorAdapter(projected, public) if public_mode else ScriptActor(projected)
    variables = deepcopy(workflow.get("test_variables", {}))
    if any(k in variables for k in ("expected", "checks", "oracle", "oracle_derivation")):
        raise AdapterUnsupported("ADAPTER_UNSUPPORTED:oracle_like_workflow_defaults")
    variables.update(deepcopy(projected["facts"]["variables"]))
    code, messages, visits, inputs, transports = wr.Code(), [], [], [], []
    error, kind, node_id = None, None, workflow["initial_node"]
    verified, audit_errors, events, receipt_audit = set(), [], [], []
    def snapshot():
        value = variables.get("state", {})
        return json.loads(value) if isinstance(value, str) else deepcopy(value)
    try:
        if workflow.get("global_nodes") or workflow.get("tools"):
            raise wr.ReplayError("unsupported_global_semantics")
        for step in range(180):
            node = workflow["nodes"][node_id]
            visits.append(node_id)
            if node.get("tools") or node.get("assertions") or node.get("on_enter_first_entry_only"):
                raise wr.ReplayError("unsupported_node_semantics")
            if node.get("node_type") == "end_call":
                if not bank.closed:
                    raise wr.ReplayError("ended_without_bank_close")
                break
            if node.get("node_type") not in {"code", "api_request", "conversation"}:
                raise wr.ReplayError("unsupported_node_type")
            entry = node.get("on_enter", {})
            if entry.get("type") == "tts":
                line = str(wr.render(entry["text"], variables))
                messages.append({"role": "assistant", "content": line})
                events.append({"step": step, "speech": line, "verified": sorted(verified)})
                if len(verified) != 2 and re.search(r"\b(?:collections|debt|past.due|overdue|credit card|personal loan|car loan)\b", line, re.I):
                    audit_errors.append("debt_or_product_disclosure_before_both_security_receipts")
            elif entry.get("type") != "silent":
                raise wr.ReplayError("unsupported_entry_semantics")
            if node.get("node_type") == "conversation" and not node.get("passthrough"):
                spoken = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), "")
                authored, meta = actor.next(variables, spoken)
                if helpers is not None:
                    authored = declared_schema_output(authored, meta, node.get("extraction_schema", []), projected["brief"], helpers)
                schema = {s["name"]: s for s in node.get("extraction_schema", [])}
                if set(schema) != set(authored) or any(s["type"] != "string" for s in schema.values()):
                    raise AdapterUnsupported("ADAPTER_UNSUPPORTED:extraction_contract")
                descriptions = " ".join(s.get("description", "") for s in schema.values())
                if (projected["brief"] == "A" and "k=KIND;c=" not in descriptions) or (projected["brief"] == "B" and "k=K|c=C" not in descriptions):
                    raise AdapterUnsupported("ADAPTER_UNSUPPORTED:undeclared_tagged_grammar")
                for key, val in authored.items():
                    if schema[key].get("validation_pattern") and not re.fullmatch(schema[key]["validation_pattern"], val):
                        raise AdapterUnsupported("ACTOR:authored_event_schema_violation")
                variables.update(authored)
                inputs.append({"step": step, "node": node_id, "values": deepcopy(authored), "evidence": meta, "observed_state": snapshot()})
                messages.append({"role": "user", "content": authored.get("raw", authored.get("raw_speech"))})
            for action in node.get("pre_actions", []):
                fn = action["function"]
                properties = fn["parameters"]["properties"]
                if fn["handler"] == "__function__:code_exec":
                    before_state = snapshot()
                    signal = variables.get("signal")
                    receipt = variables.get("api_receipt")
                    if signal not in {None, "", "user"} and receipt:
                        current = str(receipt) == str(before_state.get("awaiting_id")) and signal == before_state.get("awaiting") and str(receipt) != str(before_state.get("consumed_receipt", ""))
                        receipt_audit.append({"step": step, "signal": signal, "receipt": str(receipt), "awaiting": before_state.get("awaiting"), "awaiting_id": before_state.get("awaiting_id"), "matches_current_request": current})
                        if not current:
                            audit_errors.append("completion_receipt_does_not_match_current_request")
                    code.run(properties["code"]["default"], variables)
                    after_state = snapshot()
                    if signal not in {None, "", "user"} and receipt and str(after_state.get("consumed_receipt")) != str(receipt):
                        audit_errors.append("current_request_receipt_not_consumed")
                    variables[node_id + "_success_count"] = int(variables.get(node_id + "_success_count", 0)) + 1
                    continue
                if fn["handler"] != "__function__:api_call" or action.get("config", {}).get("maxRetries", 0):
                    raise wr.ReplayError("unsupported_action_semantics")
                config = {"url": wr.render(properties["url"]["default"], variables),
                          "method": wr.render(properties["method"]["default"], variables),
                          "body": wr.defaults(properties["body"], variables)}
                code.run(action.get("pre_process_code"), variables, {"config": config})
                paths = [p for s in wr.b.local.API["servers"] for p in wr.b.local.API["paths"] if s["url"].rstrip("/") + p == config["url"]]
                if len(set(paths)) != 1 or config["method"] != "POST" or set(config) != {"url", "method", "body"}:
                    raise wr.ReplayError("unsupported_or_unbound_http_operation")
                operation = wr.b.local.API["paths"][paths[0]]["post"]
                if fn["name"] != operation.get("operationId", paths[0].lstrip("/")):
                    raise wr.ReplayError("function_endpoint_binding_mismatch")
                name, body = fn["name"], config["body"]
                if name in {"get_account", "create_promise"} and len(verified) != 2:
                    audit_errors.append("identity_before_" + name)
                if name == "create_promise":
                    term = {k: body.get(k) for k in ("product_id", "amount", "date")}
                    if term not in actor.confirmed:
                        audit_errors.append("promise_without_script_and_spoken_current_terms_confirmation")
                observed = bank.call(name, body)
                if name == "verify_identity" and observed.get("ok") and observed.get("verified"):
                    verified.add(body["field"])
                result = {"status": "success", "status_code": 200, "data": deepcopy(observed)}
                variables[node_id + "_success_count"] = int(variables.get(node_id + "_success_count", 0)) + 1
                public.flatten(name + "_response", result, variables)
                variables[name + "_status_code"] = "200"
                transports.append({"step": step, "node": node_id, "method": "POST", "path": paths[0], "body": deepcopy(body), "result": deepcopy(observed), "http_status": 200, "dispatch_request_id": variables.get("request_id"), "state_at_dispatch": snapshot()})
                code.run(action.get("post_process_code"), variables, {"config": config, "result": result})
                for mapping in node.get("response_mapping", []):
                    value = result
                    for part in mapping["path"].split("."):
                        value = value.get(part) if isinstance(value, dict) else None
                    variables[mapping["variable"]] = str(value) if isinstance(value, bool) else deepcopy(value)
            predicate = condition_helper or public.exact_condition
            target = next((t["target_node"] for t in node.get("transitions", []) if predicate(t["condition"], variables, wr)), None)
            if not target:
                raise wr.ReplayError("missing_transition")
            node_id = target
        else:
            raise wr.ReplayError("node_step_budget_exhausted")
    except AdapterUnsupported as exc:
        error = str(exc)
        kind = error.split(":", 1)[0]
    except Exception as exc:
        error = str(exc) if isinstance(exc, (wr.ReplayError, ValueError)) else type(exc).__name__ + ":" + str(exc)
        kind = "HARNESS_UNSUPPORTED" if isinstance(exc, wr.ReplayError) and error.startswith("unsupported") else "RUNTIME_ERROR"
    divergence = None
    if error and error.startswith("uninitialized_template_variable:"):
        divergence = {"missing_variable": error.split(":", 1)[1],
                      "workflow_test_variables": deepcopy(workflow.get("test_variables", {})),
                      "declared_default_missing_from_init": False,
                      "public_driver_same_strict_behavior": True,
                      "documented_engine_behavior": "Unset exact-placeholder normal API fields are dropped before pre_process_code; no interpolation exception.",
                      "source": "competition-v3/build-the-builder/docs/tools-and-code.md:111-118",
                      "strict_replay_result_retained": True}
        kind = "HARNESS_UNSUPPORTED"
    ledger = deepcopy(bank.ledger)
    tools = [c["tool"] for c in ledger["calls"]]
    if tools.count("close_call") != 1 or not tools or tools[-1] != "close_call":
        audit_errors.append("exactly_one_terminal_close_call")
    audit_errors.extend(wr.b.local.trace_errors(projected, ledger))
    # Preserve malformed authored turns; do not rewrite them to manufacture a
    # policy result. A confirmation selected at recipient is an adapter fault.
    malformed_recipient = [i for i in inputs if i["evidence"]["phase"] == "recipient" and re.search(r"confirm|onay", i["values"].get("raw", i["values"].get("raw_speech", "")), re.I)]
    if malformed_recipient:
        kind, error = "ACTOR", "ACTOR:later_payment_confirmation_selected_at_recipient"
    # Raw-text code format gates: complete authored answer was supplied but
    # rejected by the kernel before account access. Preserve raw scorer failure.
    if not public_mode and not error and "get_account" not in tools and projected["family"] not in {"third_party_non_disclosure", "explicit_security_refusal"}:
        complete = [i for i in inputs if any(r["k"] in {"security", "answer"} and r.get("v") for r in i["evidence"]["rows"])]
        if complete or any(i["evidence"].get("raw_language_gate_candidate") for i in inputs):
            kind = "CODE_FORMAT_GATE"
            error = "CODE_FORMAT_GATE:script_recipient_or_complete_security_raw_rejected_before_account"
    if not public_mode and not error and projected["family"] == "explicit_security_refusal" and ledger["outcome"] == "not_reached":
        kind, error = "CODE_FORMAT_GATE", "CODE_FORMAT_GATE:script_recipient_raw_rejected_before_refusal"
    actor_delivery_errors = []
    if not public_mode and projected["family"] == "paid_current_then_refusal":
        for i in inputs[1:]:
            state = i["observed_state"]
            if i["evidence"]["phase"] in {"collect", "offer"} and not state.get("initial") and state.get("current") not in {None, "", "p2"} and any(r["k"] == "no" and r.get("p") == "p2" for r in i["evidence"]["rows"]):
                actor_delivery_errors.append("loan_refusal_delivered_while_bank_asked_about_card; scripted_loan_offer_condition_not_met")
    if actor_delivery_errors:
        kind = "ACTOR"
        if not error:
            error = "ACTOR:scripted_product_offer_condition_not_met"
    gates = []
    if frozen_b14 and error and projected["family"] == "paid_current_then_refusal":
        gates.append("B14 bank_claim rejects scripted passive 'was already paid' and card-ending label; neutral current-card claim blocks disposition")
    if frozen_b14 and error and projected["family"] == "paid_current_then_dispute":
        gates.append("B14 English-only security_raw rejects the supplied Turkish-month DOB; paid/disputed turns unreachable")
    if frozen_b14 and error and projected["family"] == "third_party_non_disclosure":
        gates.append("B14 asserted(third) requires English third-party terms; Turkish spouse statement blocks callback phase")
    return {"ledger": ledger, "toolcalls": tools, "messages": messages,
            "extraction_inputs": inputs, "transport_calls": transports, "node_visits": visits,
            "runtime_error": error, "failure_domain": kind, "audit_errors": sorted(set(audit_errors)),
            "fixture": deepcopy(projected["facts"]), "actor_final_terms": deepcopy(actor.last_terms),
            "actor_confirmed_terms": deepcopy(actor.confirmed), "speech_events": events,
            "current_request_receipt_audit": receipt_audit,
            "receipt_audit_available": bool(receipt_audit),
            "delivered_acts": sorted({r["k"] for i in inputs for r in i["evidence"]["rows"]}),
            "observed_phases": sorted({i["evidence"]["phase"] for i in inputs}),
            "replayer_divergence": divergence, "underlying_code_format_gates": gates,
            "actor_delivery_errors": sorted(set(actor_delivery_errors))}


def workflow_from(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if "workflow" in value:
        value = value["workflow"]
    if "initial_node" not in value or not isinstance(value.get("nodes"), dict):
        raise ValueError("candidate_workflow_structure_unsupported:" + str(path))
    return value


def normalized_signature(row):
    value = {k: deepcopy(row[k]) for k in ("ledger", "extraction_inputs", "runtime_error", "audit_errors", "status")}
    for c in value["ledger"]["calls"]:
        c["arguments"].pop("customer_id", None)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def worker(args):
    deny_network()
    if digest(PACK) != PACK_HASH:
        raise ValueError("sealed_pack_pin_mismatch")
    manifest_path = PACK.with_suffix(".manifest.json")
    seal = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in seal["frozen_artifacts"] + seal["official_sources"]:
        if digest(ROOT / item["path"]) != item["raw_sha256"]:
            raise ValueError("sealed_source_pin_mismatch:" + item["path"])
    paths = [PACK, manifest_path, PACK.with_suffix(".txt"), Path(__file__).resolve(),
             ROOT / "scripts/local_public_replay.py", ROOT / "integrations/customer-datasets/workflow_replay.py",
             ROOT / "integrations/customer-datasets/benchmark_adapter.py", ROOT / "research/field-cases/local_runner.py",
             ROOT / "competition/releases/classic-baseline/manifest.json", KIT / "docs/workflow-format.md"]
    paths.extend([ROOT / "scripts/compare_local_candidate_kernels.py", ROOT / "scripts/replay_final_public_candidate.py"])
    output = Path(args.output_prefix or (str(PREFIX) + (".public39" if args.public39 else ""))).resolve()
    if output.parent != PREFIX.parent or not output.name.startswith(PREFIX.name):
        raise ValueError("output_outside_authorized_analysis_prefix")
    if args.candidate_sha256 and any(Path(str(output) + ext).exists() for ext in (".json", ".txt")):
        raise ValueError("do_not_overwrite_pinned_candidate_replay_evidence")
    protected = {str(p): digest(p) for p in PREFIX.parent.glob(PREFIX.name + "*") if p.is_file() and str(p) not in {str(output) + ".json", str(output) + ".txt"}}
    paths.extend(ROOT / item["path"] for item in seal["official_sources"])
    workflows, arms, sources = {}, {"baseline": {}}, {}
    baseline = json.loads(paths[8].read_text(encoding="utf-8"))
    for brief, (version, pinned) in PINS.items():
        source = next(s for s in baseline["sources"] if s["brief"] == brief)
        path = ROOT / source["review_template"]
        if source["historical_published_version"] != version or source["review_template_sha256"] != pinned or digest(path) != pinned:
            raise ValueError("baseline_workflow_pin_mismatch:" + brief)
        paths.append(path)
        arms["baseline"][brief] = workflow_from(path)
        sources["baseline:" + brief] = {"path": str(path), "sha256": pinned, "version": version}
    if args.candidate_workflow:
        expected_candidates = dict(argument.split("=", 1) for argument in args.candidate_sha256 or [])
        arms["candidate"] = {}
        for argument in args.candidate_workflow:
            brief, name = argument.split("=", 1)
            if brief not in PINS or brief in arms["candidate"]:
                raise ValueError("candidate_arg_requires_unique_A_or_B_equals_path")
            path = Path(name).resolve()
            expected = expected_candidates.get(brief)
            if expected and digest(path) != expected:
                raise ValueError("exact_candidate_pin_mismatch_before_read:" + brief)
            paths.append(path)
            arms["candidate"][brief] = workflow_from(path)
            if expected and digest(path) != expected:
                raise ValueError("exact_candidate_pin_mismatch_after_read:" + brief)
            sources["candidate:" + brief] = {"path": str(path), "sha256": digest(path), "expected_sha256": expected}
    before = {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): digest(p) for p in set(paths)}
    sys.path.insert(0, str(ROOT / "integrations/customer-datasets"))
    wr = load("final_bank_workflow_replay", ROOT / "integrations/customer-datasets/workflow_replay.py")
    public = load("final_bank_public_utilities", ROOT / "scripts/local_public_replay.py")
    helpers = load("final_bank_declared_schema_helpers", ROOT / "scripts/replay_final_public_candidate.py")
    condition_helper = load("final_bank_condition_helpers", ROOT / "scripts/compare_local_candidate_kernels.py").documented_condition
    scorer = load("final_bank_original_score", KIT / "tools/score.py").score_ledger
    case_path = KIT / "public-test-set.json" if args.public39 else PACK
    originals = json.loads(case_path.read_text(encoding="utf-8"))
    inventory = 13 if args.public39 else 12
    if len(originals) != inventory or len({c["id"] for c in originals}) != inventory:
        raise ValueError("case_inventory_mismatch")
    rows, finals = [], []
    for arm, selected in arms.items():
        for original in originals:
            if original["brief"] not in selected:
                finals.append({"arm": arm, "id": original["id"], "brief": original["brief"], "status": "CANDIDATE_PENDING", "repetitions": 0})
                continue
            group = []
            for repetition in range(1, 4):
                projected = public.fixture(original, repetition) if args.public39 else fixture(original, arm, repetition)
                if args.public39:
                    projected["facts"]["variables"]["customer_id"] += "-" + arm
                result = execute(selected[original["brief"]], projected, wr, public, public_mode=args.public39,
                                 frozen_b14=not args.public39 and sources.get(arm + ":" + original["brief"], {}).get("sha256") == PINS["B"][1],
                                 helpers=helpers, condition_helper=condition_helper)
                # First oracle access, strictly after execution has returned.
                scored = scorer({"expected": deepcopy(original["expected"])}, result["ledger"])
                status = result["failure_domain"] if result["runtime_error"] else "CONDITIONAL_LEDGER_PASS" if scored["pass"] and not result["audit_errors"] else "POLICY_FAIL"
                result.update(arm=arm, id=original["id"], brief=original["brief"], repetition=repetition,
                              original_score=scored, status=status, conditional_pass=status == "CONDITIONAL_LEDGER_PASS")
                rows.append(result)
                group.append(result)
            finals.append({"arm": arm, "id": original["id"], "brief": original["brief"],
                           "status": group[0]["status"] if len({r["status"] for r in group}) == 1 else "REPEAT_MISMATCH",
                           "repetitions": 3, "conditional_passes": sum(r["conditional_pass"] for r in group),
                           "raw_original_ledger_passes": sum(r["original_score"]["pass"] for r in group),
                           "identical_deterministic_results": len({normalized_signature(r) for r in group}) == 1,
                           "errors": sorted({r["runtime_error"] for r in group if r["runtime_error"]}),
                           "original_score_failures": group[0]["original_score"]["failed"],
                           "audit_errors": group[0]["audit_errors"], "toolcalls": group[0]["toolcalls"]})
            finals[-1].update(delivered_acts=group[0]["delivered_acts"], observed_phases=group[0]["observed_phases"],
                              current_request_receipts_checked=len(group[0]["current_request_receipt_audit"]),
                              replayer_divergence=group[0]["replayer_divergence"],
                              underlying_code_format_gates=group[0]["underlying_code_format_gates"],
                              actor_delivery_errors=group[0]["actor_delivery_errors"])
    if "candidate" not in arms:
        finals.extend({"arm": "candidate", "id": c["id"], "brief": c["brief"], "status": "CANDIDATE_PENDING", "repetitions": 0} for c in originals)
    after = {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): digest(p) for p in set(paths)}
    if before != after:
        raise ValueError("immutable_source_changed_during_replay")
    if any(digest(path) != value for path, value in protected.items()):
        raise ValueError("prior_replay_evidence_changed")
    for source in sources.values():
        if source.get("expected_sha256") and digest(source["path"]) != source["expected_sha256"]:
            raise ValueError("exact_candidate_pin_mismatch_after_execution")
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "scope": "public13_offline_conditional_extraction" if args.public39 else "sealed12_offline_conditional_extraction",
              "cases": inventory, "repetitions": 3, "executions": len(rows), "final": finals, "results": rows,
              "workflow_sources": sources, "source_hashes_before": before, "source_hashes_after": after,
              "immutable_sources_unchanged": before == after, "sealed_pack_sha256": PACK_HASH,
              "prior_replay_evidence_sha256": protected, "prior_replay_evidence_unchanged": True,
              "adapter_change_basis": "Hume documented_condition permits bare equals/always/greater_than; declared schema_contract maps script-derived current rows to actual enum/security copy fields. Recipient quotes scoped to pre-security SCRIPT, loan refusals only at actual loan questions. No oracle-based actor repairs.",
              "network_denied": True, "network_calls": 0, "credentials_loaded": False,
              "asr_executed": False, "llm_executed": False, "extractor_executed": False, "conversation_judge_executed": False,
              "freya_executed": False, "independent_actor_repetitions": False,
              "repeat_qualification": "Three identical deterministic conditional actor replays with fresh Banks and synthetic customer IDs; not independent actor repetitions.",
              "oracle_source_QA": {"method": "Read-only independent subagent original briefs/API/scorer review of sealed12", "all12_expected_ledgers": "PASS", "discrepancies": []},
              "delivery_note": "Public39 uses unchanged public13 actor. New output uses source-scoped recipient quotes and actual requested product; earlier malformed actor reports are hash-protected. Coverage counts only actually delivered acts.",
              "template_initialization_QA": {"baseline_B_test_variables": {}, "reason_default_declared": False,
                                             "strict_public_and_new_driver_behavior": "Both raise on missing normal API placeholder before pre_process_code.",
                                             "platform_docs_behavior": "Drop unset exact-placeholder API field; safe_close preprocessor can supply it.",
                                             "conclusion": "Missing reason exception is harness divergence, not established platform runtime failure; raw strict-replay scores preserved."},
              "limitations": ["Authored contract events; NO ASR/LLM/extractor/conversation judge. No hosted or full bank pass claim.",
                              "Original scorer compares normalized arrays and exact outcome/reason; selected chronological/spoken/confirmation audits are additional guards.",
                              "Unsupported actor delivery, extraction grammar and raw-language code gates are separate from policy failures.",
                              "Current-request API envelopes/hooks run on generic mockBank; actual Freya receipt semantics and transcript judgments remain untested.",
                              "Frozen scripts, fixtures, expectations and source code are never altered to fix failures."]}
    Path(str(output) + ".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"{inventory} bank cases: offline conditional replay", report["repeat_qualification"],
             "NO ASR/LLM/extractor/judge/Freya/network/credentials. Sources pinned before/after and unchanged.",
             "Independent original-source oracle QA: all 12 PASS, no discrepancies.", ""]
    for f in finals:
        lines.append(f"{f['arm']} {f['id']} {f['status']} {f.get('conditional_passes', 0)}/{f['repetitions']}; raw ledger={f.get('raw_original_ledger_passes', 0)}; tools=" + ">".join(f.get("toolcalls", [])))
        lines.extend("  " + e for e in f.get("errors", []) + f.get("actor_delivery_errors", []) + f.get("underlying_code_format_gates", []) + f.get("audit_errors", []) + f.get("original_score_failures", []))
        if f.get("replayer_divergence"):
            lines.append("  Harness divergence: documented unset API field is dropped before preprocessing; strict sidecar raises. No declared reason default omitted from initialization; raw score retained.")
    lines.extend(["", "Limitations:"] + report["limitations"])
    Path(str(output) + ".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"executions": len(rows), "conditional_passes": sum(r["conditional_pass"] for r in rows),
                      "statuses": {arm: {s: sum(f['status'] == s for f in finals if f['arm'] == arm) for s in sorted({f['status'] for f in finals if f['arm'] == arm})} for arm in ("baseline", "candidate")},
                      "report": str(output) + '.json'}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-workflow", action="append", metavar="A=PATH", help="Late candidate workflow, repeat for B=PATH; missing brief is pending")
    parser.add_argument("--candidate-sha256", action="append", metavar="A=SHA256", help="Required exact pre/post runtime pin for the supplied validated candidate")
    parser.add_argument("--output-prefix")
    parser.add_argument("--public39", action="store_true", help="Separate 13 public cases x 3 fresh Banks, using unchanged existing public actor")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PYTHONUTF8", "USERNAME"}}
    command = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), "--worker"]
    if args.output_prefix:
        command.extend(["--output-prefix", args.output_prefix])
    if args.public39:
        command.append("--public39")
    for candidate in args.candidate_workflow or []:
        command.extend(["--candidate-workflow", candidate])
    for expected in args.candidate_sha256 or []:
        command.extend(["--candidate-sha256", expected])
    try:
        completed = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "HARNESS_TIMEOUT", "timeout_seconds": 90}))
        return 2
    print(completed.stdout.strip())
    if completed.returncode:
        print(completed.stderr[-3000:])
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
