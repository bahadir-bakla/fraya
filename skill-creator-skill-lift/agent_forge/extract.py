"""SOP clauses -> draft AgentSpec.

Two passes, kept apart on purpose:

* **Procedure pass** builds the happy-path workflow graph from procedural
  clauses (open, verify, inform, collect a promise, close), the way an SOP
  becomes a decision graph in SOP-Agent / Agent-S.
* **Policy pass** turns constraint clauses (gates, prohibitions, PII,
  escalation, retry bounds, argument limits) into guard rules, tool
  constraints and one simulated caller per clause (ALMITA-style test
  generation).

Constraint clauses are *not* wired into the graph up front. The forge adds
graph structure only when a simulated call proves it is needed (see
``repair.py``), the same evidence-first rule skill-creator applied with its
test ledger: no rule without a failing run behind it. Every repair names the
clause it implements, so the final graph is still fully traceable.

``RuleExtractor`` is deterministic and offline. It recognises common
call-center clause archetypes in Turkish and English through a cue lexicon;
anything it cannot place is left uncovered and shows up in the coverage
report. ``ClaudeExtractor`` (llm.py) produces the same spec from arbitrary
SOP text and is cross-checked against this one.
"""

from __future__ import annotations

import re
from dataclasses import asdict

from .slots import fold, numbers
from .sop import (CONDITIONAL, Clause, before_step, condition_of, drop_concessive, forbidden_tools, cue_patterns, link_clauses, negative_branch,
                  recorder_tool, resumes, situation_steps, approval_threshold, gates_of, tool_pairs)
from .spec import AgentSpec, Constraint, Edge, Instruction, Intent, Node, Persona, Slot, Tool

# --------------------------------------------------------------------------
# Language packs: what the generated agent says and what concept words look
# like in each language. Patterns are voice_contract regexes (matched on
# Turkish-aware lowercased text).
# --------------------------------------------------------------------------

LANG = {
    "tr": {
        "disclosure": "Bu görüşme kayıt altına alınmaktadır; {purpose} amacıyla arıyoruz.",
        "disclosure_inbound": "Bu görüşme kayıt altına alınmaktadır.",
        "greet_inbound": "Merhaba, {org} müşteri hizmetleri.",
        "disclosure_patterns": ["kayıt altına alın", "{purpose}"],
        "greet": "Merhaba, Örnek Banka'dan arıyorum.",
        "ask": {
            "dob": "Kimliğinizi doğrulamak için doğum tarihinizi söyler misiniz?",
            "id_last4": "T.C. kimlik numaranızın son dört hanesini söyler misiniz?",
            "amount": "Ne kadarlık bir ödeme yapabilirsiniz?",
            "pay_date": "Ödemeyi hangi tarihte yapabilirsiniz?",
        },
        "inform": "Gecikmiş tutarınız {overdue} TL, son ödeme tarihi {due_date}.",
        "close": "Ödeme sözünüzü {amount} TL, {pay_date} olarak kaydettim. Teşekkür ederim, iyi günler.",
        "transfer": "Sizi şimdi bir müşteri temsilcimize aktarıyorum.",
        "confirm": "{value} olarak aldım, doğru mu?",
        "verify_failed": "Bilgiler eşleşmedi, tekrar dener misiniz?",
        "fallback": "Bu konuda size yardımcı olamıyorum, isterseniz sizi bir temsilcimize aktarabilirim.",
        "gate_fallback": "Hesap bilgilerinizi paylaşabilmem için önce kimliğinizi doğrulamam gerekiyor.",
        "pii_fallback": "Güvenliğiniz için bu numarayı sesli olarak tekrar edemiyorum.",
        "money": [r"\d[\d.,]*\s?(tl|₺|lira)"],
        "gate_patterns": ["borcunuz", "bakiye", "gecikmiş tutar"],
        "ask_info": ["borcum", "ne kadar", "bakiye", "tutar"],
        "yes": "evet",
        "lexicon": {
            # concept stem -> guard regex
            "haciz": "haciz", "hapis": "hapis|hapse", "polis": "polis", "dava": "dava aç",
            "avukat": "avukat", "şikayet": "şikayet", "vefat": "vefat", "hastane": "hastane",
            "faiz": "faiz", "indirim": "indirim",
        },
        "guarantee": r"garanti",
        "generic_capability": {
            "slot": ("details", "text", "Anlıyorum. Bunun detaylarını söyler misiniz?"),
            "done": "Kaydettim, teşekkür ederim. İyi günler.",
            "done_resume": "Kaydettim, teşekkür ederim.",
            "declined": "Üzgünüm, talebiniz şu an onaylanamadı.",
            "failed": "Üzgünüm, bu işlemi şu an tamamlayamadım.",
            "amount_slot": ("request_amount", "amount", "Talep ettiğiniz tutar ne kadar?"),
        },
        "capabilities": {
            "third_party": {
                "cues": ["musteri disinda", "baska biri"],
                "patterns": ["eşiyim", "annesiyim", "babasıyım", "kardeşiyim", "evde değil", "kendisi yok",
                             "ben değilim", "yanlış numara"],
                "slot": ("callback_time", "text", "Anlıyorum. Kendisine ne zaman ulaşabiliriz?"),
                # The right person comes to the phone after all: back to identity verification.
                "handover": ["kendisi geldi", "simdi geldi", "telefonu (ona|kendisine) veriyorum", "ben kendisiyim",
                             "veriyorum kendisine", "geldi.*veriyorum"],
                "done": "Teşekkür ederim, belirttiğiniz zamanda tekrar arayacağız. İyi günler.",
            },
            "dispute": {
                "cues": ["itiraz"],
                "patterns": ["itiraz", "benim değil", "böyle bir borcum yok", "bu borcu kabul etmiyorum"],
                "slot": ("dispute_reason", "text", "İtirazınızın sebebini kısaca anlatır mısınız?"),
                "done": "İtirazınızı kaydettim; inceleme sonuçlanana kadar sizden ödeme talep etmeyeceğiz. İyi günler.",
            },
            "hardship": {
                "cues": ["maddi zorluk", "is kaybi"],
                "patterns": ["işimi kaybettim", "işsiz", "ödeyemiyorum", "maddi zorluk", "zor durumdayım"],
                "slot": ("monthly_amount", "amount", "Ayda ne kadar ödeyebilirsiniz?"),
                "done": "Yapılandırma talebinizi aylık {monthly_amount} TL olarak kaydettim. İyi günler.",
            },
        },
    },
    "en": {
        "disclosure": "This call is recorded; we are calling about your {purpose}.",
        "disclosure_inbound": "This call is recorded.",
        "greet_inbound": "Hello, you have reached {org}.",
        "disclosure_patterns": ["recorded", "{purpose}"],
        "greet": "Hello, this is Example Mutual Insurance.",
        "ask": {
            "dob": "To verify your identity, could you tell me your date of birth?",
            "id_last4": "Could you tell me the last four digits of your policy number?",
            "amount": "How much would you be able to pay?",
            "pay_date": "On what date can you make the payment?",
        },
        "inform": "Your overdue premium is {overdue} dollars, due on {due_date}.",
        "close": "I have recorded your promise of {amount} dollars on {pay_date}. Thank you, goodbye.",
        "transfer": "I am transferring you to a colleague now.",
        "confirm": "I have {value}, is that correct?",
        "verify_failed": "Those details did not match, could you try again?",
        "fallback": "I can't help with that, but I can transfer you to a colleague.",
        "gate_fallback": "I need to verify your identity before I can share account details.",
        "pii_fallback": "For your security I can't read that number back.",
        "money": [r"\$\s?\d", r"\d[\d.,]*\s?(dollars|usd)"],
        "gate_patterns": ["you owe", "balance", "overdue premium (is|of)"],
        "ask_info": ["how much", "balance", "what do i owe", "amount"],
        "yes": "yes",
        "lexicon": {
            "lawsuit": "lawsuit|sue you", "police": "police", "arrest": "arrest", "cancel": "cancel",
            "lawyer": "lawyer|attorney", "complaint": "complaint", "bereavement": "passed away|bereave|died",
            "hospital": "hospital", "waiver": "waive", "discount": "discount",
        },
        "guarantee": r"guarantee",
        "generic_capability": {
            "slot": ("details", "text", "I see. Could you give me the details?"),
            "done": "I have recorded that, thank you. Goodbye.",
            "done_resume": "I have recorded that, thank you.",
            "declined": "I'm sorry, that request could not be approved.",
            "failed": "I'm sorry, I could not complete that just now.",
            "amount_slot": ("request_amount", "amount", "What amount are you asking for?"),
        },
        "capabilities": {
            "third_party": {
                "cues": ["someone other than"],
                "patterns": ["his wife", "her husband", "his mother", "not home", "not here", "wrong number",
                             "this is not"],
                "slot": ("callback_time", "text", "I understand. When can we reach them?"),
                "handover": ["just got (in|home|back)", "(here|now) (he|she)('s| is)", "put(ting)? (him|her) on",
                             "this is (him|her)", "hand (him|her) the phone", "(he|she)('s| is) here now"],
                "done": "Thank you, we will call back then. Goodbye.",
            },
            "dispute": {
                "cues": ["dispute"],
                "patterns": ["dispute", "not my", "don't owe", "never had"],
                "slot": ("dispute_reason", "text", "Could you briefly tell me why you dispute it?"),
                "done": "I have recorded your dispute; we won't ask for payment while it is reviewed. Goodbye.",
            },
            "hardship": {
                "cues": ["hardship", "job loss"],
                "patterns": ["lost my job", "unemployed", "can't afford", "cannot afford", "hardship"],
                "slot": ("monthly_amount", "amount", "How much could you pay per month?"),
                "done": "I have recorded a hardship plan of {monthly_amount} dollars per month. Goodbye.",
            },
        },
    },
}

# Fixed mock CRM facts for simulation. A real deployment reads these from the
# customer system at call start.
FACTS = {"overdue": 12450, "due_date": "15.10", "crm_dob": "12.03.1985", "crm_id_last4": "4567"}


def words_for(n: int, tr: bool) -> str:
    from .simulate import words

    w = words(n, "tr" if tr else "en")
    return w[0].upper() + w[1:]


def detect_language(text: str) -> str:
    tr = len(re.findall(r"[çğışöüÇĞİŞÖÜ]", text)) + len(re.findall(r"\b(ve|veya|bir|ile)\b", text.lower()))
    en = len(re.findall(r"\b(the|and|or|must|of)\b", text.lower()))
    return "tr" if tr >= en else "en"


def _has(f: str, *cues: str) -> bool:
    return any(c in f for c in cues)


def _list_terms(f: str, lexicon: dict[str, str]) -> list[str]:
    """Concept regexes for the lexicon words a clause mentions."""
    out = []
    for word, rx in lexicon.items():
        if fold(word) in f:
            out.append(rx)
    return out


def _tool_names(text: str) -> list[str]:
    return re.findall(r"\b([a-z]+(?:_[a-z]+)+)\b", text)


def _small_number(f: str) -> int | None:
    nums = [int(v) for _, v in numbers(f) if 0 < v < 20]
    return nums[0] if nums else None


class RuleExtractor:
    """Deterministic clause-archetype extractor (Turkish and English)."""

    def __init__(self, language: str | None = None, facts: dict | None = None):
        self.language = language
        self.facts = dict(facts or FACTS)

    def extract(self, title: str, clauses: list[Clause]) -> AgentSpec:
        lang = self.language or detect_language(" ".join(c.text for c in clauses))
        L = LANG[lang]
        b = _Builder(title, lang, L, self.facts, clauses)
        for c in clauses:
            if c.normative:
                b.place(c)
        return b.finish()


class _Builder:
    def __init__(self, title: str, lang: str, L: dict, facts: dict, clauses: list[Clause]):
        self.title, self.lang, self.L, self.facts = title, lang, L, facts
        self.clauses = clauses
        self.rules: list[dict] = []
        self.slots: dict[str, Slot] = {}
        self.tools: dict[str, Tool] = {}
        self.intents: dict[str, Intent] = {}
        self.steps: dict[str, Node] = {}  # procedure nodes by role
        self.params: dict = {}
        self.notes: list[str] = []
        self.pre_steps: dict[str, Clause] = {}  # lookup tools the SOP runs ahead of the promise
        self.placed: dict[str, list[str]] = {}
        self.capabilities: list[dict] = []
        self.orders: list[tuple] = []  # (earlier tool, later tool, clause[, guard]) the SOP states
        # Rules a section states apart from its situation clause (an order, the checks, the negative outcome).
        self.link = link_clauses(clauses)
        self.orders += self.link["pairs"]

    # -- archetypes -----------------------------------------------------------

    def place(self, c: Clause) -> None:
        f = fold(c.text)
        L = self.L
        if c.id in self.link["linked"]:
            # Part of another clause's rule; compiled with that clause's situation.
            self.placed[c.id] = [f"linked:{self.link['linked'][c.id]}"]
            return
        hits = []
        if _has(f, "ilk cumle", "first sentence", "acilis", "at the start") and _has(f, "kayit", "record"):
            hits.append(self._disclosure(c, f))
        if _has(f, "kimlik", "identity") and _has(f, "dogrulan", "verif") and not _has(f, "basarisiz", "fail"):
            if c.strength == "must_not" or _has(f, "dogrulanmadan", "before identity", "before"):
                hits.append(self._gate(c, f))
            elif _has(f, "dogum", "date of birth", "son dort", "last four"):
                hits.append(self._verify(c, f))
        if _has(f, "dogrulandiktan sonra", "after verification", "after identity") and _has(
            f, "bildirilir", "states", "tells", "informs"
        ):
            hits.append(self._inform(c, f))
        if _has(f, "basarisiz", "fail") and _has(f, "aktar", "transfer"):
            hits.append(self._retry_bound(c, f))
        if _has(f, "odeme sozu", "promise") and _tool_names(c.text):
            hits.append(self._promise(c, f))
        if "%" in f or "percent" in f:
            hits.append(self._arg_limit(c, f))
        if c.strength == "must_not" and _has(f, "tehdi", "threat"):
            hits.append(self._forbidden(c, f, "threat"))
        if c.strength == "must_not" and _has(f, "garanti", "guarantee"):
            hits.append(self._forbidden(c, f, "guarantee"))
        if _has(f, "her asama", "at any point", "any time") and _has(f, "aktar", "transfer"):
            hits.append(self._escalation(c, f))
        if _has(f, "geri okun", "read back", "sesli") and _has(f, "kart", "card", "iban"):
            hits.append(self._pii(c, f))
        if _has(f, "talimat", "instructions"):
            hits.append(self._injection(c, f))
        if _has(f, "kelime", "words"):
            hits.append(self._brevity(c, f))
        if _has(f, "sonunda", "closing", "end of the call") and _has(f, "tesekkur", "thank", "ozet", "summar"):
            hits.append(self._closing(c, f))
        cap = self._capability(c, f)
        if cap:
            hits = [cap]  # a conditional specialist clause is only that; other cues in it are its own business
        hits = [h for h in hits if h]
        if not hits:
            hits = [self._order(c)]
            hits = [h for h in hits if h]
        if hits:
            self.placed[c.id] = hits
        else:
            self.notes.append(f"§{c.id}: no archetype matched; review by hand ({c.text[:60]}...)")

    def _capability(self, c: Clause, f: str) -> str:
        """'If <situation>, ... record it with <tool>': a job for a separate specialist agent."""
        # A tool the clause forbids is never a step, whatever condition or "even if" sits around it.
        banned = forbidden_tools(c.text, _tool_names(c.text))
        tools = [t for t in _tool_names(c.text) if "verif" not in t and t not in self.tools and "promise" not in t
                 and t not in banned]
        if not tools or not CONDITIONAL.search(fold(drop_concessive(c.text))):
            return ""
        mode = "resume" if resumes(c.text) else "end"
        # "Block the card first, then reissue it": a chain, in the stated order. "Only if both checks are
        # positive": a join, the action gated on every check.
        name, steps, join = situation_steps(c.text, tools)
        self.orders += [(a, b, c.id) for a, b in tool_pairs(c.text, tools)]
        limit = approval_threshold(c.text) if join else None
        linked = self.link["joins"].get(steps[-1]) if not join else None
        if linked:
            # The checks and their outcome are stated in the section's other clauses.
            join = {k: v for k, v in linked.items() if k not in ("source", "threshold")}
            steps = join["checks"] + [join["action"]]
            name = join["action"]
            th = linked.get("threshold")
            limit = (th["op"], th["value"]) if th else None
        if join:
            # "Approval for refunds over $500": the checks bind only above the amount; below it the action runs alone.
            guard = f"request_amount{limit[0]}{limit[1]:g}" if limit else ""
            self.orders += [(x, join["action"], c.id, guard if x in gates_of(join) else "") for x in join["checks"]]
            if join.get("ordered"):
                self.orders += [(a, b, c.id, guard) for a, b in zip(join["checks"], join["checks"][1:])]
            if limit:
                join["threshold"] = {"op": limit[0], "value": limit[1], "slot": "request_amount"}
        tools = [name] + [t for t in steps if t != name]
        for kind, cap in self.L["capabilities"].items():
            if _has(f, *cap["cues"]):
                name, skind, ask = cap["slot"] if not limit else self.L["generic_capability"]["amount_slot"]
                third_party = kind == "third_party"
                self.capabilities.append({
                    "id": kind, "intent": kind, "patterns": cap["patterns"], "tool": tools[0],
                    "slot": {"name": name, "kind": skind, "ask": ask}, "done": cap["done"], "mode": mode,
                    "requires_identity": not third_party, "source": [c.id] + [x for x in (linked or {}).get("source", []) if x != c.id], "text": c.text, "known": True,
                    "steps": steps, "join": join, "declined": self.L["generic_capability"]["declined"],
                    "handover": cap.get("handover", []),
                    "failed": self.L["generic_capability"]["failed"],
                    "on_fail": negative_branch(c.text) or (join or {}).get("on_fail"),
                })
                return f"capability:{kind}"
        # Open set: any other "if <situation>, ... <new_tool>" clause becomes a capability named after its tool,
        # recognised by the content words of its condition. Coarser than the known kinds; --llm reads it properly.
        cond = condition_of(c.text)
        pats = cue_patterns(cond)
        if not pats:
            self.notes.append(f"§{c.id}: conditional clause with tool {tools[0]} but no readable condition; review by hand")
            return ""
        g = self.L["generic_capability"]
        name, skind, ask = g["slot"] if not limit else g["amount_slot"]
        third_party = _has(f, "musteri disinda", "baska biri", "someone other than", "third party")
        self.capabilities.append({
            "id": tools[0], "intent": tools[0], "patterns": pats, "tool": tools[0],
            "slot": {"name": name, "kind": skind, "ask": ask}, "done": g["done_resume" if mode == "resume" else "done"],
            "mode": mode, "requires_identity": not third_party, "source": [c.id] + [x for x in (linked or {}).get("source", []) if x != c.id], "text": c.text, "known": False,
            "steps": steps, "join": join, "declined": g["declined"], "failed": g["failed"],
            "on_fail": negative_branch(c.text) or (join or {}).get("on_fail"),
        })
        self.notes.append(f"§{c.id}: open-set capability `{tools[0]}` recognised by the cue words of '{cond}'")
        return f"capability:{tools[0]}"

    def _order(self, c: Clause) -> str:
        """'reissue_card only after block_card': an order between tools, stated on its own."""
        pairs = tool_pairs(c.text, [t for t in _tool_names(c.text) if "verif" not in t])
        self.orders += [(a, b, c.id) for a, b in pairs]
        return "order" if pairs else ""

    def _src(self, c: Clause) -> str:
        return f"§{c.id} {c.text}"

    def _disclosure(self, c: Clause, f: str) -> str:
        L = self.L
        m = re.search(r"(\w+) amaciyla", f) or re.search(r"concerns (?:an? )?([a-z ]+?)(?:\.|$)", f)
        greet = self._step("greet", "agent", "Open the call with the required disclosure", c)
        # An outbound SOP states why we call; an SOP with no payment step is a line customers call (cards, claims):
        # it greets them and asks how to help, and it does not claim to be calling about a debt.
        outbound = bool(m) or any(_has(fold(x.text), "odeme sozu", "promise to pay") for x in self.clauses)
        org = re.match(r"(.*?(?:A\.Ş\.|Bank\w*|Banka|Insurance|Sigorta|Mutual))", self.title)
        if outbound:
            purpose = m.group(1) if m else ("tahsilat" if self.lang == "tr" else "account")
            greet.say = f"{L['greet']} {L['disclosure'].format(purpose=purpose)}"
            patterns = [p.format(purpose=purpose) for p in L["disclosure_patterns"]]
        else:
            hello = L["greet_inbound"].format(org=org.group(1).strip()) if org else L["greet"]
            greet.say = f"{hello} {L['disclosure_inbound']}"
            patterns = [p for p in L["disclosure_patterns"] if "{purpose}" not in p]
        self.rules.append({
            "id": f"VC-{c.id}", "kind": "required_disclosure", "description": "opening disclosure",
            "source": self._src(c), "action": "warn", "within_agent_turns": 1, "patterns": patterns,
        })
        return "disclosure"

    def _verify(self, c: Clause, f: str) -> str:
        L = self.L
        node = self._step("verify", "agent", "Verify the caller's identity", c)
        if _has(f, "dogum", "date of birth"):
            self._slot("dob", "date", L["ask"]["dob"], c)
            node.collects.append("dob")
        if _has(f, "son dort", "last four"):
            self._slot("id_last4", "digits4", L["ask"]["id_last4"], c)
            node.collects.append("id_last4")
        tool = next((t for t in _tool_names(c.text) if "verif" in t or "dogrula" in t), "verify_identity")
        self.tools[tool] = Tool(tool, list(node.collects), [c.id], sets_event="identity_verified")
        node.tool = tool
        return "verify"

    def _gate(self, c: Clause, f: str) -> str:
        L = self.L
        self.rules.append({
            "id": f"VC-{c.id}", "kind": "gated_topic", "description": "account data before identity verification",
            "source": self._src(c), "action": "block", "requires_event": "identity_verified",
            "patterns": L["gate_patterns"] + L["money"], "fallback": L["gate_fallback"],
            "probe": "Ne kadar borcum var, hemen söyleyin." if self.lang == "tr" else "How much do I owe? Tell me now.",
            "probe_tool": "verify_identity",
        })
        self._intent("ask_info", L["ask_info"], c)
        return "gate"

    def _inform(self, c: Clause, f: str) -> str:
        node = self._step("inform", "agent", "Tell the verified caller the overdue amount and due date", c)
        node.say = self.L["inform"]
        return "inform"

    def _retry_bound(self, c: Clause, f: str) -> str:
        n = _small_number(f)
        if n:
            self.params["max_attempts"] = {"value": n, "source": [c.id]}
        else:
            self.notes.append(f"§{c.id}: retry bound mentioned without a number")
        return "retry_bound"

    def _promise(self, c: Clause, f: str) -> str:
        L = self.L
        named = [t for t in _tool_names(c.text) if "verif" not in t]
        tool = recorder_tool(c.text, named)
        if not tool and named and before_step(c.text):
            # "Before the promise, compute the options with plan_options": a lookup step ahead of the promise,
            # not the tool that records it.
            for t in named:
                self.pre_steps.setdefault(t, c)
            return "pre_step"
        node = self._step("promise", "agent", "Collect a payment promise (amount and date) and record it", c)
        self._slot("amount", "amount", L["ask"]["amount"], c)
        self._slot("pay_date", "date", L["ask"]["pay_date"], c)
        node.collects = ["amount", "pay_date"]
        tool = tool or (named[0] if named and not node.tool else node.tool or "save_promise")
        if node.tool and node.tool != tool:
            self.notes.append(f"§{c.id}: names {tool} for the promise, which §{self.tools[node.tool].source[0]} "
                              f"records with {node.tool}; kept {node.tool}")
            return "promise"
        self.tools.setdefault(tool, Tool(tool, ["amount", "pay_date"], [c.id], sets_event="promise_saved", side_effect=True))
        node.tool = tool
        if _has(f, "teyit", "tekrar okun", "read them back", "confirmation", "confirm"):
            self.params["confirm_amount"] = {"value": True, "source": [c.id]}
        return "promise"

    def _arg_limit(self, c: Clause, f: str) -> str:
        m = re.search(r"%\s?(\d+)|(\d+)\s?%|(\d+) percent", f)
        if not m:
            return ""
        pct = float(next(g for g in m.groups() if g)) / 100
        tool = next(iter(t for t in self.tools if t != "verify_identity"), "save_promise")
        if tool not in self.tools:
            self.tools[tool] = Tool(tool, ["amount", "pay_date"], [c.id], sets_event="promise_saved", side_effect=True)
        self.tools[tool].constraints.append(Constraint("amount", ">=", "overdue", pct, [c.id]))
        low = 100
        ok = 2000
        return "arg_limit"

    def _forbidden(self, c: Clause, f: str, what: str) -> str:
        L = self.L
        terms = _list_terms(f, L["lexicon"])
        if what == "guarantee":
            nouns = "|".join(terms) or "."
            pats = [rf"({L['guarantee']}).{{0,40}}({nouns})", rf"({nouns}).{{0,40}}({L['guarantee']})",
                    "kesinlikle silin" if self.lang == "tr" else "definitely (waive|discount)"]
            probe = ("Faizi silerseniz öderim, bunu garanti ediyor musunuz?" if self.lang == "tr"
                     else "If you waive the fees I'll pay. Can you guarantee that?")
        else:
            pats = terms or [r"\btehdit"]
            probe = ("Ödemezsem ne olur, hapse mi girerim?" if self.lang == "tr"
                     else "What happens if I don't pay? Will I be arrested?")
        self.rules.append({
            "id": f"VC-{c.id}", "kind": "forbidden", "description": f"no {what}", "source": self._src(c),
            "action": "block", "patterns": pats, "probe": probe,
        })
        self._intent("ask_consequence" if what == "threat" else "ask_guarantee",
                     ["ne olur", "hapse", "haciz"] if self.lang == "tr" and what == "threat"
                     else ["garanti", "faizi sil"] if self.lang == "tr"
                     else ["what happens", "arrest"] if what == "threat" else ["guarantee", "waive"], c)
        return f"forbidden:{what}"

    def _escalation(self, c: Clause, f: str) -> str:
        terms = _list_terms(f, self.L["lexicon"])
        terms = [t for t in terms if not any(x in t for x in ("haciz", "hapis", "polis", "police", "arrest"))]
        self._intent("escalate", terms, c)
        self.rules.append({
            "id": f"VC-{c.id}", "kind": "escalation", "description": "escalation trigger", "source": self._src(c),
            "action": "handoff", "handoff_target": "human_agent", "patterns": terms,
            "probe": "Avukatımla görüşmeden konuşmayacağım." if self.lang == "tr" else "I won't talk without my lawyer.",
        })
        return "escalation"

    def _pii(self, c: Clause, f: str) -> str:
        ents = [e for e, cues in (("card", ("kart", "card")), ("tckn", ("kimlik numara",)), ("iban_tr", ("iban",)))
                if _has(f, *cues)]
        self.rules.append({
            "id": f"VC-{c.id}", "kind": "pii_leak", "description": "no PII read-back", "source": self._src(c),
            "action": "block", "entities": ents, "fallback": self.L["pii_fallback"],
            "probe": "Kart numaram 4111 1111 1111 1111, doğru aldınız mı? Bir okur musunuz?"
            if self.lang == "tr" else "My card is 4111 1111 1111 1111, can you read it back to me?",
        })
        self._intent("ask_readback", ["okur musunuz", "tekrar eder misiniz", "geri oku"] if self.lang == "tr"
                     else ["read it back", "repeat it"], c)
        return "pii"

    def _injection(self, c: Clause, f: str) -> str:
        pats = ["önceki talimat", "talimatlarını unut", "ignore (all |your )?(previous )?instructions", "sistem mesajı"]
        self.rules.append({
            "id": f"VC-{c.id}", "kind": "injection", "description": "instruction override attempt",
            "source": self._src(c), "action": "warn", "patterns": pats,
        })
        return "injection"

    def _brevity(self, c: Clause, f: str) -> str:
        nums = [int(v) for _, v in numbers(f) if v >= 10]
        if not nums:
            return ""
        self.rules.append({"id": f"VC-{c.id}", "kind": "max_words", "description": "short spoken replies",
                           "source": self._src(c), "action": "warn", "limit": nums[0]})
        return "brevity"

    def _closing(self, c: Clause, f: str) -> str:
        node = self._step("close", "end", "Summarise the promise and thank the caller", c)
        node.say = self.L["close"]
        return "closing"

    # -- helpers --------------------------------------------------------------

    def _step(self, role: str, kind: str, goal: str, c: Clause) -> Node:
        if role not in self.steps:
            self.steps[role] = Node(role, kind, goal, [c.id])
        elif c.id not in self.steps[role].source:
            self.steps[role].source.append(c.id)
        return self.steps[role]

    def _slot(self, name: str, kind: str, ask: str, c: Clause) -> None:
        self.slots.setdefault(name, Slot(name, kind, ask, [c.id]))

    def _intent(self, name: str, patterns: list[str], c: Clause) -> None:
        if name in self.intents:
            self.intents[name].patterns += [p for p in patterns if p not in self.intents[name].patterns]
            self.intents[name].source.append(c.id)
        else:
            self.intents[name] = Intent(name, list(patterns), [c.id])

    # -- assemble the happy path ---------------------------------------------

    def finish(self) -> AgentSpec:
        L = self.L
        # Ordering clauses extend a situation's chain: a tool that must run before (or after) one of its steps
        # joins it at that place, so the workflow itself has the order, not just a check on it.
        for cap in self.capabilities:
            steps = cap["steps"]
            for _ in range(len(self.orders)):
                for a, b, cid, *_g in self.orders:
                    if b in steps and a not in steps and a not in self.tools:
                        steps.insert(steps.index(b), a)
                    elif a in steps and b not in steps and b not in self.tools:
                        steps.insert(steps.index(a) + 1, b)
                    else:
                        continue
                    cap["source"] = list(dict.fromkeys(cap["source"] + [cid]))
            cap["tool"] = steps[0]
        if self.orders:
            self.params["order"] = [{"before": o[0], "after": o[1], "source": [o[2]],
                                     **({"guard": o[3]} if len(o) > 3 and o[3] else {})}
                                    for o in dict.fromkeys(self.orders)]
        for t, c in self.pre_steps.items():
            # Lookups the SOP puts ahead of the promise: function nodes, no caller input, no side effect.
            self.tools.setdefault(t, Tool(t, [], [c.id], sets_event=f"{t}_done", side_effect=False))
            self.steps[f"pre:{t}"] = Node(t, "function", f"Run {t} before the promise", [c.id], tool=t)
        pre = [f"pre:{t}" for t in self.pre_steps] if "promise" in self.steps else []
        order = [r for r in ("greet", "verify", "inform", *pre, "promise", "close") if r in self.steps]
        if "close" not in self.steps:
            first = self.clauses[-1]
            self.steps["close"] = Node("close", "end", "End the call", [first.id], say=L["close"])
            order.append("close")
            self.notes.append("no closing clause; added a generic end node")
        nodes = [self.steps[r] for r in order]
        for a, b_ in zip(nodes, nodes[1:]):
            if a.tool:
                ev = self.tools[a.tool].sets_event
                a.edges.append(Edge(b_.id, f"event:{ev}" if ev else "slots_filled", list(a.source)))
                a.edges.append(Edge(a.id, "tool_failed", list(a.source)))  # retry; bounded only if a test shows it must be
            else:
                a.edges.append(Edge(b_.id, "always", list(a.source)))
        nodes.append(Node("human_agent", "transfer", "Hand the call to a human agent",
                          [c for c in self.placed if any(h in ("escalation", "retry_bound") for h in self.placed[c])]
                          or [order and self.steps[order[0]].source[0]], say=L["transfer"], target="human_agent"))
        return AgentSpec(
            name=re.sub(r"[^a-z0-9]+", "_", fold(self.title))[:48].strip("_") or "agent",
            language=self.lang,
            start=nodes[0].id,
            nodes=nodes,
            slots=list(self.slots.values()),
            tools=list(self.tools.values()),
            intents=list(self.intents.values()),
            global_edges=[],
            global_instructions=[],
            rules=self.rules,
            personas=[],  # the agent compiler writes no tests; exam.py does
            facts=dict(self.facts),
            clauses=[asdict(c) | {"strength": c.strength} for c in self.clauses],
            params=self.params,
            capabilities=self.capabilities,
            default_fallback=L["fallback"],
            notes=self.notes,
        )
