"""Offline repair invariants: JSON pointers, finite data and atomic provenance."""

from copy import deepcopy
import json

import httpx
import pytest

from agent_forge.builder_repair import apply_repair


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Repair tests must not make HTTP requests")
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def previous(workflow=None):
    if workflow is None:
        workflow = {"initial_node": "ask", "nodes": {"ask": {
            "task_message": "Original prompt", "tools": [{"name": "first"}, {"name": "second"}]},
            "done": {"node_type": "end_call"}}, "metadata": {"keep": "untouched"}}
    return {"workflow_json": json.dumps(workflow, ensure_ascii=False, allow_nan=False),
            "coverage": [{"source_id": "brief::C1", "node_ids": ["ask"], "mechanism": "Original dialogue"},
                         {"source_id": "brief::C2", "node_ids": ["done"], "mechanism": "Original close"}],
            "limitations": ["Original limitation"]}


def patch(op, path, value=None):
    return {"op": op, "path": path,
            "value_json": "" if op == "remove" else json.dumps(value, ensure_ascii=False, allow_nan=False)}


def repair(*patches, coverage=(), limitations=()):
    return {"patches": list(patches), "coverage_updates": deepcopy(list(coverage)),
            "limitations": list(limitations)}


def decoded(result):
    return json.loads(result["workflow_json"])


def test_escaped_json_pointer_tokens_select_exact_keys_once():
    original = {"nodes": {"a/b": {"~flag": "old", "a~1b": "literal-tilde-one",
                                  "a/b": "literal-slash", "": "empty-key"}}, "": "root-empty-key"}
    candidate = previous(original)
    update = repair(
        patch("replace", "/nodes/a~1b/~0flag", "new"),
        patch("replace", "/nodes/a~1b/a~01b", "changed-tilde-one"),
        patch("replace", "/nodes/a~1b/", "changed-empty"),
        patch("replace", "/", "changed-root-empty"),
    )
    before, update_before = deepcopy(candidate), deepcopy(update)
    result = decoded(apply_repair(candidate, update))
    assert result == {"nodes": {"a/b": {"~flag": "new", "a~1b": "changed-tilde-one",
                                      "a/b": "literal-slash", "": "changed-empty"}}, "": "changed-root-empty"}
    assert candidate == before and update == update_before


@pytest.mark.parametrize("path", ["", "nodes/ask", "#/nodes/ask", "/nodes/~2bad", "/nodes/~", "/nodes/~~1bad"])
def test_root_non_pointer_and_invalid_escape_paths_are_rejected_atomically(path):
    candidate = previous()
    before = deepcopy(candidate)
    with pytest.raises(ValueError):
        apply_repair(candidate, repair(patch("add", path, "bad")))
    assert candidate == before


@pytest.mark.parametrize("op,index,value,expected", [
    ("add", "0", "x", ["x", "a", "b", "c"]),
    ("add", "1", "x", ["a", "x", "b", "c"]),
    ("add", "3", "x", ["a", "b", "c", "x"]),
    ("add", "-", "x", ["a", "b", "c", "x"]),
    ("replace", "1", "x", ["a", "x", "c"]),
    ("remove", "0", None, ["b", "c"]),
    ("remove", "2", None, ["a", "b"]),
])
def test_array_add_inserts_replace_overwrites_and_remove_shifts(op, index, value, expected):
    candidate = previous({"items": ["a", "b", "c"], "unrelated": {"sentinel": True}})
    before = deepcopy(candidate)
    result = decoded(apply_repair(candidate, repair(patch(op, f"/items/{index}", value))))
    assert result == {"items": expected, "unrelated": {"sentinel": True}}
    assert candidate == before


def test_array_patch_sequence_uses_indices_in_the_current_document():
    candidate = previous({"items": [{"name": "a"}, {"name": "b"}]})
    update = repair(patch("add", "/items/0", {"name": "new"}),
                    patch("replace", "/items/1/name", "renamed-a"),
                    patch("remove", "/items/2"))
    assert decoded(apply_repair(candidate, update)) == {"items": [{"name": "new"}, {"name": "renamed-a"}]}


@pytest.mark.parametrize("op,index", [
    ("add", "4"), ("replace", "3"), ("remove", "3"),
    ("replace", "-"), ("remove", "-"),
    ("add", "01"), ("replace", "00"), ("remove", "-1"),
    ("add", "+1"), ("replace", "1.0"), ("add", "999999999999999999999"),
    ("replace", "\u0660"), ("add", "\uff11"),
])
def test_out_of_bounds_or_noncanonical_array_indices_rejected(op, index):
    candidate = previous({"items": ["a", "b", "c"]})
    before = deepcopy(candidate)
    with pytest.raises(ValueError):
        apply_repair(candidate, repair(patch(op, f"/items/{index}", "x")))
    assert candidate == before


@pytest.mark.parametrize("path", ["/items/2/name", "/missing/child", "/scalar/child", "/items/01/name", "/items/\u0660/name"])
def test_invalid_intermediate_container_or_index_rejected_atomically(path):
    candidate = previous({"items": [{"name": "first"}], "scalar": 42})
    before = deepcopy(candidate)
    with pytest.raises((ValueError, KeyError, IndexError)):
        apply_repair(candidate, repair(patch("replace", path, "changed")))
    assert candidate == before


@pytest.mark.parametrize("op", ["replace", "remove"])
def test_missing_object_target_is_rejected(op):
    candidate = previous({"object": {"existing": 1}})
    with pytest.raises(ValueError):
        apply_repair(candidate, repair(patch(op, "/object/missing", 2)))
    assert decoded(candidate) == {"object": {"existing": 1}}


def test_object_add_can_insert_or_replace_without_erasing_siblings():
    candidate = previous({"object": {"existing": 1, "keep": 3}})
    result = decoded(apply_repair(candidate, repair(patch("add", "/object/existing", 2),
                                                   patch("add", "/object/new", {"nested": True}))))
    assert result == {"object": {"existing": 2, "keep": 3, "new": {"nested": True}}}


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e309", '{"nested":[NaN]}', '{"nested":{"x":1e309}}'])
def test_non_finite_patch_json_cannot_be_committed(literal):
    candidate = previous()
    update = repair(patch("replace", "/nodes/ask/task_message", "would-have-changed"),
                    {"op": "add", "path": "/metadata/value", "value_json": literal})
    before, update_before = deepcopy(candidate), deepcopy(update)
    with pytest.raises(ValueError):
        apply_repair(candidate, update)
    assert candidate == before and update == update_before


@pytest.mark.parametrize("literal", ["", "{", "undefined", '{"broken":}', "[1,]"])
def test_malformed_patch_value_json_is_rejected_atomically(literal):
    candidate = previous()
    before = deepcopy(candidate)
    update = repair({"op": "add", "path": "/metadata/value", "value_json": literal})
    with pytest.raises(ValueError):
        apply_repair(candidate, update)
    assert candidate == before


def test_finite_json_values_unicode_and_literal_nan_text_are_preserved():
    candidate = previous({"metadata": {}})
    values = {"none": None, "flag": False, "zero": 0, "amount": 125.5,
              "text": "NaN — değişiklik", "nested": [{"value": 3}]}
    result = apply_repair(candidate, repair(patch("add", "/metadata/value", values)))
    assert decoded(result) == {"metadata": {"value": values}}
    json.dumps(decoded(result), allow_nan=False)
    assert "değişiklik" in result["workflow_json"]


@pytest.mark.parametrize("literal", ['{"metadata":{"value":NaN}}', '{"metadata":{"value":Infinity}}'])
def test_non_finite_values_already_in_previous_candidate_cannot_escape_output(literal):
    candidate = previous()
    candidate["workflow_json"] = literal
    before = deepcopy(candidate)
    with pytest.raises(ValueError):
        apply_repair(candidate, repair())
    assert candidate == before


@pytest.mark.parametrize("failure", ["later-patch", "unknown-source", "duplicate-source"])
def test_failed_repair_is_atomic_after_an_earlier_valid_edit(failure):
    candidate = previous()
    update = repair(patch("replace", "/nodes/ask/task_message", "new prompt"))
    changed_coverage = {"source_id": "brief::C1", "node_ids": ["ask", "done"], "mechanism": "Updated path"}
    if failure == "later-patch":
        update["patches"].append(patch("remove", "/nodes/ask/tools/99"))
    elif failure == "unknown-source":
        update["coverage_updates"] = [{**changed_coverage, "source_id": "foreign-brief::C9"}]
    else:
        update["coverage_updates"] = [changed_coverage, deepcopy(changed_coverage)]
    before, update_before = deepcopy(candidate), deepcopy(update)
    with pytest.raises(ValueError):
        apply_repair(candidate, update)
    assert candidate == before and update == update_before
    assert decoded(candidate)["nodes"]["ask"]["task_message"] == "Original prompt"
    assert candidate["coverage"][0]["node_ids"] == ["ask"]


def test_coverage_update_retains_unrelated_source_ids_and_input_ownership():
    candidate = previous()
    update_row = {"source_id": "brief::C1", "node_ids": ["ask", "done"], "mechanism": "Repaired dialogue"}
    update = repair(patch("replace", "/nodes/ask/task_message", "new prompt"),
                    coverage=[update_row], limitations=["Remaining limitation"])
    before, update_before = deepcopy(candidate), deepcopy(update)
    result = apply_repair(candidate, update)
    assert result["coverage"] == [update_row, before["coverage"][1]]
    assert result["limitations"] == ["Remaining limitation"]
    assert decoded(result)["nodes"]["done"] == decoded(before)["nodes"]["done"]
    assert candidate == before and update == update_before
    result["coverage"][0]["node_ids"].append("changed-output")
    assert candidate == before and update == update_before


def test_patch_count_bound_accepts_64_and_rejects_65_before_any_commit():
    candidate = previous({"metadata": {}})
    before = deepcopy(candidate)
    edits = [patch("add", f"/metadata/k{i}", i) for i in range(65)]
    assert decoded(apply_repair(candidate, repair(*edits[:64])))["metadata"] == {f"k{i}": i for i in range(64)}
    with pytest.raises(ValueError):
        apply_repair(candidate, repair(*edits))
    assert candidate == before


def test_pointer_length_bound_rejects_oversized_path_atomically():
    candidate = previous({})
    key = "x" * 999
    assert decoded(apply_repair(candidate, repair(patch("add", "/" + key, 1)))) == {key: 1}
    with pytest.raises(ValueError):
        apply_repair(candidate, repair(patch("add", "/" + key + "x", 1)))
    assert decoded(candidate) == {}


@pytest.mark.parametrize("change", ["unknown-op", "extra-field", "non-string-json", "missing-coverage"])
def test_invalid_patch_response_schema_is_rejected_before_editing(change):
    candidate = previous()
    update = repair(patch("replace", "/nodes/ask/task_message", "changed"))
    if change == "unknown-op":
        update["patches"][0]["op"] = "move"
    elif change == "extra-field":
        update["patches"][0]["extra"] = True
    elif change == "non-string-json":
        update["patches"][0]["value_json"] = {"wrong": "type"}
    else:
        del update["coverage_updates"]
    before = deepcopy(candidate)
    with pytest.raises(ValueError):
        apply_repair(candidate, update)
    assert candidate == before
