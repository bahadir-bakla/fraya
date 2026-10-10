"""Bounded execution facts for repair, without customer speech or request values.

The full transcript and ledger remain separate evidence. These counts describe
observed events; they do not certify policy compliance or successful API writes.
Only names supplied by the compiled workflow/API can appear in the summary.
"""
from collections import Counter
import hashlib
import json

_EVENTS = {
    "node_enter", "route_evaluated", "variable_extracted", "function_call_start",
    "function_call_complete", "function_call_error", "error",
}
_END_REASONS = {
    "customer-ended-call", "assistant-ended-call", "workflow-ended-call",
    "max-duration", "max-duration-exceeded", "silence-timed-out",
}


def summarize_execution(call, *, node_names=(), function_names=()):
    """Ignore arbitrary metadata, snapshots, arguments, results and error text.

    At most 20,000 messages and 16 KiB per event are inspected. Truncated input
    is labelled; absence of an event is never described as proof of absence.
    Assistant text is used only for repetition counts and is never returned.
    """
    nodes = set(node_names)
    functions = set(function_names)
    if not isinstance(call, dict):
        call = {}
    messages = call.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    roles, events, entries, starts, completes, errors, edges, speech = (
        Counter() for _ in range(8)
    )
    unknown_events = 0
    for message in messages[:20000]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if not isinstance(role, str) or role not in {"user", "assistant", "system"}:
            continue
        roles[role] += 1
        value = message.get("message")
        if role == "assistant" and isinstance(value, str) and len(value) <= 16384:
            # Keep no spoken content in the resulting model feedback.
            normalized = " ".join(value.split()).casefold()
            if normalized:
                speech[hashlib.sha256(normalized.encode("utf-8", errors="replace")).digest()] += 1
        if role != "system" or not isinstance(value, str) or len(value) > 16384:
            continue
        try:
            event = json.loads(value)
        except (ValueError, RecursionError):
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("event")
        if not isinstance(kind, str) or kind not in _EVENTS:
            unknown_events += 1
            continue
        events[kind] += 1
        node = event.get("node")
        if kind == "node_enter" and isinstance(node, str) and node in nodes:
            entries[node] += 1
        if kind == "route_evaluated" and event.get("matched") is True:
            source, target = event.get("from_node"), event.get("target")
            if isinstance(source, str) and isinstance(target, str) and source in nodes and target in nodes:
                edges[(source, target)] += 1
        function = event.get("function")
        if isinstance(function, str) and function in functions:
            counts = {"function_call_start": starts, "function_call_complete": completes,
                      "function_call_error": errors}.get(kind)
            if counts is not None:
                counts[function] += 1
    reason = call.get("endedReason")
    return {
        "scope": "observed_counts_only_no_policy_verdict",
        "messages_truncated": len(messages) > 20000,
        "message_counts": dict(roles), "event_counts": dict(events),
        "unknown_event_count": unknown_events,
        "node_entry_counts": dict(entries),
        "matched_edges": [{"from": a, "to": b, "count": n}
                          for (a, b), n in edges.items()],
        "function_start_counts": dict(starts),
        "function_complete_counts": dict(completes),
        "function_error_counts": dict(errors),
        "largest_identical_assistant_count": max(speech.values(), default=0),
        "ended_reason": reason if isinstance(reason, str) and reason in _END_REASONS else "other_or_unavailable",
    }
