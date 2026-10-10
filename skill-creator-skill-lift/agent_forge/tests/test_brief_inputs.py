from pathlib import Path

import pytest

from agent_forge.brief_inputs import load_brief_bundle, markdown_tables
from agent_forge.sop import parse_sop


KIT = Path(__file__).resolve().parents[3] / "competition-v3" / "build-the-builder"


def test_flat_and_dotted_rule_numbers_preserve_multiline_provenance():
    text = "# Policy\n## Identity\n1. Ask one question.\n   Wait for the answer.\n2) Never disclose the balance.\n3.2 Call verify_identity.\n2026 is an example year.\n"
    _, clauses = parse_sop(text, source_file="policy.md")
    assert [c.id for c in clauses] == ["1", "2", "3.2"]
    assert (clauses[0].start_line, clauses[0].end_line) == (3, 4)
    assert clauses[0].source_file == "policy.md"
    assert "2026 is an example year" in clauses[-1].text


@pytest.mark.parametrize("name,count", [("brief-a", 47), ("brief-b", 11)])
def test_official_briefs_retain_every_numbered_rule(name, count):
    if not KIT.exists():
        pytest.skip("Official kit is a separate local reference input")
    bundle = load_brief_bundle([KIT / "briefs" / f"{name}.md"])
    rules = {c["id"]: c for c in bundle["documents"][0]["clauses"] if c["id"].isdigit()}
    assert set(rules) == {str(i) for i in range(1, count + 1)}
    source_lines = (KIT / "briefs" / f"{name}.md").read_text(encoding="utf-8").splitlines()
    for rid, rule in rules.items():
        assert source_lines[rule["start_line"] - 1].startswith(rid + ". ")
        assert rule["end_line"] >= rule["start_line"]
    assert not bundle["semantic_policy_compiled"]


def test_same_rule_ids_in_separate_documents_stay_distinct(tmp_path):
    a, b = tmp_path / "base.md", tmp_path / "memo.md"
    a.write_text("# Base\n1. Ask for one field.\n", encoding="utf-8")
    b.write_text("# Memo\n1. Replace that question with another.\n", encoding="utf-8")
    bundle = load_brief_bundle([a, b])
    assert [d["clauses"][0]["qualified_id"] for d in bundle["documents"]] == ["base:1", "memo:1"]
    assert bundle["precedence_status"].startswith("unresolved")


def test_raw_memo_text_is_retained_without_markdown_headings(tmp_path):
    path = tmp_path / "memo.txt"
    path.write_text("Subject: revised verification\n\nUse the supplied fields only.\n", encoding="utf-8")
    doc = load_brief_bundle([path])["documents"][0]
    assert [c["text"] for c in doc["clauses"]] == ["Subject: revised verification", "Use the supplied fields only."]
    assert [c["start_line"] for c in doc["clauses"]] == [1, 3]


def test_tables_keep_rows_and_escaped_pipe():
    tables = markdown_tables("# Limits\n| Band | Days |\n|---|---|\n| early | 1-7 |\n| late | 8\\|45 |\n")
    assert len(tables) == 1
    assert tables[0]["headers"] == ["Band", "Days"]
    assert tables[0]["rows"] == [{"line": 4, "cells": ["early", "1-7"]}, {"line": 5, "cells": ["late", "8|45"]}]


def test_duplicate_rule_ids_are_rejected(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Policy\n1. First rule.\n1. Conflicting second rule.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate rule IDs"):
        load_brief_bundle([path])


def test_same_filename_labels_and_unsupported_format_are_rejected(tmp_path):
    a, b = tmp_path / "x", tmp_path / "y"
    a.mkdir(); b.mkdir()
    for parent in (a, b):
        (parent / "brief.md").write_text("# Policy\n1. Ask a question.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate document label"):
        load_brief_bundle([a / "brief.md", b / "brief.md"])
    with pytest.raises(ValueError, match="Unsupported brief format"):
        load_brief_bundle([tmp_path / "source.docx"])
