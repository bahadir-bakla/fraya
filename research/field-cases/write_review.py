"""Write the two assigned review files from observed local validation, no network."""
from collections import Counter
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
catalog = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))
manifest = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
validation = json.loads((HERE / "validation.json").read_text(encoding="utf-8"))
mapping = json.loads((HERE / "hosted-style-mapping.json").read_text(encoding="utf-8"))
cases, sources = catalog["scenarios"], manifest["sources"]
used_refs = sorted({r for c in cases for r in c["oracle"]["rule_refs"]})
rows = [{
    "id": c["id"], "brief": c["brief"], "title": c["title"],
    "source_ids": [s["id"] for s in c["provenance"]["sources"]],
    "expected": c["expected"], "scenario_constraints": c["oracle"]["scenario_constraints"],
    "related_existing_catalog_ids": c["provenance"]["related_existing_catalog_ids"],
    "classification": "source_supported_complaint_motif_with_explicit_synthetic_extensions; oracle_from_official_kit",
} for c in cases]

review = {
    "version": "1.0.0", "reviewed_on": "2026-10-10", "timezone": "Europe/Istanbul", "kit_version": 3,
    "objective": "Complaint-inspired independent synthetic edge fixtures and expected outputs, with public evidence separated from policy and architectural inventions.",
    "ownership": {"allowed": ["research/field-cases/**", "analysis/field-scenario-review.json", "analysis/field-scenario-review.txt"], "no_changes_elsewhere_by_this_task": True},
    "summary": {
        "scenarios": len(cases), "briefs": dict(Counter(c["brief"] for c in cases)),
        "sources": len(sources), "platforms": dict(Counter(s["platform"] for s in sources)),
        "reddit_communities": sorted({s["community"] for s in sources if s["platform"] == "Reddit"}),
        "sikayetvar_financial_service_names": sorted({s["community"] for s in sources if s["platform"] == "Sikayetvar"}),
        "known_absolute_publication_dates": sum(s["published_on"] is not None for s in sources),
        "unknown_exact_publication_dates": sum(s["published_on"] is None for s in sources),
        "covered_rule_refs": used_refs, "all_official_rules_covered": False,
    },
    "evidence_method": {
        "source_selection": "Directly readable original public posts/complaints, balanced between platforms and varied by motif. Not a representative sample or prevalence estimate.",
        "source_date_policy": manifest["publication_policy"],
        "source_claim_status": manifest["claim_status"],
        "privacy": "Only URLs, neutral titles, publication/access metadata and short paraphrased motifs retained. No usernames, real names, contact details, addresses, account/customer/file identifiers, attachments, screenshots or raw complaint bodies copied into fixtures.",
        "fact_style_boundary": "facts holds synthetic inputs and semantic event/revision sequences; speaking_style holds delivery. The oracle and sources are not supplied to the agent/customer simulator.",
        "expectation_independence": "Read kit README, both briefs and OpenAPI, plus existing catalog, runner/scorer and benchmark analysis first. Expected ledger and constraints were authored directly from them, not from generated workflow/policy output, hosted results, forum advice or complaint demands.",
    },
    "decision_notes": [
        {"topic": "Current payment vs historical closure", "rule_refs": ["A39", "A40"], "decision": "Current past-due payment -> paid; historical payoff/closed-product claim -> dispute. Do not replace verification with a complaint's refusal of security."},
        {"topic": "Deceased borrower vs living bereaved borrower", "rule_refs": ["A9", "A10", "A32"], "decision": "Relative reporting customer death ends deceased with no further question; living customer's family loss invokes hardship/support, never deceased."},
        {"topic": "Hardship precedence", "rule_refs": ["A32", "A30", "A41"], "decision": "Job loss/illness/family death stops persuasion and precedes a lower-instalment request; support requires acceptance. A voluntarily offered valid promise can still be recorded."},
        {"topic": "Consent and corrections", "rule_refs": ["A34", "A35", "A36", "A37", "A38", "B7"], "decision": "Before write, revalidate changed values and read back again for clear consent; after successful write, do not edit or cancel in-call. Never claim a failed promise recorded."},
        {"topic": "B notes and terminal outcome", "rule_refs": ["B8", "B9", "B10", "B11", "B-close"], "decision": "Per-product paid/dispute continues. Defer final note writes so a later transfer can leave no notes anywhere. Retain successful promises on partial failure; closure otherwise follows account order, with promise/transfer precedence."},
        {"topic": "Scam concerns", "rule_refs": ["A3", "A4", "A15", "A42", "A43", "A44"], "decision": "Answer legitimate authenticity questions without inventing a telephone number; they do not verify identity. Repeated security refusal ends declined; an insisted human request can transfer even before verification."},
        {"topic": "Architectural combinations", "rule_refs": ["R-styles", "A18", "B3", "B6", "B11"], "decision": "Speech pieces, self-corrections, unrelated numbers, holiday boundaries, multi-product mixes, delayed transfer and deterministic API faults are labeled authored extensions, not attributed to a complaint."},
    ],
    "schema_proposal": {
        "file": "research/field-cases/scenario.schema.json",
        "small_envelope": ["id", "title", "brief", "facts", "speaking_style", "provenance", "expected", "oracle", "execution"],
        "local_runner_input": "research/field-cases/runner-cases.json is a flat kit-compatible list with synthetic FIELD ids. Local mock reads fixtures from scenarios.json. Expected ledger has the exact six official scorer fields; reference tool calls have supplied OpenAPI body shapes.",
        "execution_limits": "Executable local replay/mock plus actual-trace ledger/selected tool-guard check. Natural-language scenario constraints still require an independent judge. This is not a generated-agent pass or general compiler.",
    },
    "hosted_mapping": mapping,
    "existing_catalog_review": {"file": "analysis/synthetic-cases.json", "count": 50, "role": "Planning-only; links in case provenance acknowledge related rule coverage. Kept unchanged. No SYN ids are treated as registered hosted fixtures.", "public_suite_role": "13 existing PUB ids used only to bound proposed style mappings; field scenarios have their own synthetic inputs and source-derived oracles."},
    "validation": validation,
    "limitations": [
        "No live Freya, hosted bank, simulation, persona or workflow mutations; no credentials were used.",
        "No actual agent transcript or workflow was run. Empathy, opening, read-back, confirmation, persuasion limits and honesty remain explicit expected constraints requiring transcript evidence.",
        "The positive reference trace is not an oracle generated from an agent and is not evidence of behavioral generalization; its purpose is checking fixture/tool/ledger consistency.",
        "Sources are allegations and only inspiration. Jurisdiction-specific legal advice and commenters' proposed remedies were not incorporated.",
        "Exact publication dates are unknown for seven sources; nulls and observed labels make the uncertainty explicit.",
        "Fresh local sessions and mock failure schedules are harness design choices; arbitrary hosted fixture registration remains undocumented in the inspected kit.",
        "The 28 cases emphasize requested complaint motifs, not exhaustive coverage of the 47 A rules, 11 B amendments, source parsing, raw memo trust or future changed tool APIs.",
        "Transfer/callback service-failure recovery is not specified here; no guessed terminal outcome is asserted for those faults.",
    ],
    "sources": sources,
    "excluded_candidates": manifest["excluded_candidates"],
    "scenarios": rows,
    "files": [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted(HERE.iterdir()) if p.is_file()],
}
out_json = ROOT / "analysis/field-scenario-review.json"
out_txt = ROOT / "analysis/field-scenario-review.txt"
review["files"] += [out_json.relative_to(ROOT).as_posix(), out_txt.relative_to(ROOT).as_posix()]
out_json.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    "FRAYA — PUBLIC COMPLAINT-INSPIRED SYNTHETIC FIELD SCENARIO REVIEW",
    "Reviewed/accessed 2026-10-10, Europe/Istanbul. Official kit v3.",
    "28 cases (22 A, 6 B); 16 directly read public sources (8 Reddit, 8 Sikayetvar).",
    f"{len(review['summary']['reddit_communities'])} subreddits; {len(review['summary']['sikayetvar_financial_service_names'])} financial-service names. 9 absolute publication dates, 7 exact dates unknown.",
    "", "RESULT AND SCOPE",
    "Observed local validation: " + validation["status"].upper() + ". Schema, request contracts, source anchors/hashes and all 28 reference ledgers passed.",
    f"Negative controls: {sum(x['rejected'] for x in validation['negative_controls'])}/{len(validation['negative_controls'])} rejected.",
    "No generated agent, real transcript, hosted simulation or MCP mutation was run.",
    "Reference replay checks authored fixture consistency. It is not an agent-policy pass.",
    "", "SOURCE VS ARCHITECTURE VS EXPECTATION",
    "Each source contributes only its short paraphrased original complaint motif. Allegations are unverified and not legal guidance.",
    "All customer identities, amounts, account ids and fixture dates are authored. No real customer data, raw post bodies or attachments were retained.",
    "Every scenario separates source-supported pattern from authored architectural extensions and official rule-linked expectations.",
    "Spoken corrections/pieces, mock faults, holiday boundaries, multi-product combinations and delayed transfer are extensions; sources do not establish them.",
    "Unknown publication dates remain null with the original observed label. Event dates and crawl ages are not publication dates.",
    "", "OFFICIAL DERIVATIONS",
]
for item in review["decision_notes"]:
    lines.append(item["topic"] + " [" + ", ".join(item["rule_refs"]) + "]: " + item["decision"])
lines += ["", "SMALL GENERIC SCHEMA", ", ".join(review["schema_proposal"]["small_envelope"]), review["schema_proposal"]["local_runner_input"], review["schema_proposal"]["execution_limits"], "", "LOCAL VS HOSTED", mapping["registration_boundary"], mapping["style_boundary"], "Use only original registered PUB data for proposed style exercises. No such exercise was executed.", "", "REPRODUCE LOCALLY FROM FRAYA ROOT", "python -X utf8 -B research/field-cases/build_catalog.py", "python -X utf8 -B research/field-cases/local_runner.py validate --out research/field-cases/validation.json", "python -X utf8 -B research/field-cases/write_review.py", "", "SCENARIO INDEX (all also inherit branch-applicable shared constraints)"]
for c in rows:
    e = c["expected"]
    terminal = e["outcome"] + ("/" + e["reason"] if e["reason"] else "")
    lines += [f"{c['id']} [{c['brief']}] {c['title']} -> {terminal}; sources {', '.join(c['source_ids'])}", "  Expected ledger: " + json.dumps(e, ensure_ascii=False), "  Rules: " + ", ".join(sorted({r for x in c["scenario_constraints"] for r in x["rule_refs"]})), *["  Transcript/action constraint: " + x["description"] for x in c["scenario_constraints"]]]
lines += ["", "PUBLIC SOURCE MANIFEST (full metadata in sources.json)"]
for s in sources:
    lines += [s["id"] + " [" + s["platform"] + "] " + s["title"], "  URL: " + s["url"], "  Published: " + (s["published_on"] or "UNKNOWN exact date") + "; observed label: " + s["publication_label"] + "; accessed: " + s["accessed_on"], "  Basis: " + s["publication_basis"], "  Pattern (paraphrase): " + s["pattern"]]
lines += ["", "LIMITATIONS", *review["limitations"], "", "VALIDATION NEGATIVE CONTROLS"]
for m in validation["negative_controls"]:
    lines.append(("REJECTED " if m["rejected"] else "MISSED ") + m["name"])
lines += ["", "ASSIGNED OUTPUT PATHS", *review["files"]]
out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps({"written": [str(out_json), str(out_txt)], "validation": validation["status"], "scenarios": len(cases), "sources": len(sources)}))
