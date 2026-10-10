"""Lossless input inventory for the builder; semantic policy compilation follows it.

Keep documents and rule IDs separate. Input order is recorded, but order alone
does not prove that a later document overrides an earlier rule.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .sop import parse_sop


def _cells(line: str) -> list[str]:
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def markdown_tables(text: str) -> list[dict]:
    """Retain table headers, rows and physical source lines for later compilers."""
    lines = text.splitlines()
    tables = []
    i = 0
    while i + 1 < len(lines):
        if "|" not in lines[i]:
            i += 1
            continue
        separator = _cells(lines[i + 1])
        if not separator or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            i += 1
            continue
        headers = _cells(lines[i])
        rows = []
        start = i + 1
        i += 2
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            cells = _cells(lines[i])
            rows.append({"line": i + 1, "cells": cells})
            i += 1
        tables.append({"start_line": start, "end_line": i, "headers": headers, "rows": rows})
    return tables


def load_brief_bundle(paths: list[str | Path]) -> dict:
    """Inventory text/Markdown sources, without silently resolving amendments."""
    if not paths:
        raise ValueError("At least one brief file is required")
    documents = []
    document_ids = set()
    for order, input_path in enumerate(paths):
        path = Path(input_path)
        if path.suffix.lower() not in {".md", ".txt"}:
            raise ValueError(f"Unsupported brief format {path.suffix!r}: supply extracted text or Markdown")
        document_id = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-") or "document"
        if document_id in document_ids:
            raise ValueError(f"Duplicate document label {document_id!r}; use distinct input filenames")
        document_ids.add(document_id)
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        title, clauses = parse_sop(text, source_file=str(path), include_preamble=True)
        counts = Counter(c.id for c in clauses)
        duplicate_ids = sorted(key for key, count in counts.items() if count > 1)
        if duplicate_ids:
            raise ValueError(f"Duplicate rule IDs in {path}: {', '.join(duplicate_ids)}")
        documents.append({
            "id": document_id,
            "input_order": order,
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "title": title or path.stem,
            "clauses": [asdict(c) | {"qualified_id": f"{document_id}:{c.id}"} for c in clauses],
            "tables": markdown_tables(text),
        })
    return {
        "schema_version": 1,
        "stage": "source_inventory",
        "documents": documents,
        "precedence_status": "unresolved; explicit source amendments must be compiled separately",
        "semantic_policy_compiled": False,
    }
