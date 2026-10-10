import json

from agent_forge.__main__ import main


def test_inspect_cli_uses_supplied_operation_names_and_preserves_amendments(tmp_path, capsys):
    a, b = tmp_path / "base.md", tmp_path / "amendment.txt"
    a.write_text("# Base\n1. Call revised_verify with birth_date.\n2. no_promise is a reason, not an operation.\n", encoding="utf-8")
    b.write_text("1. Replace birth_date with account_suffix.\n", encoding="utf-8")
    api_path = tmp_path / "api.json"
    api_path.write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "Changed", "version": "1"},
        "servers": [{"url": "https://example.test"}],
        "paths": {"/verify": {"post": {"operationId": "revised_verify", "responses": {"200": {"description": "OK"}},
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "required": ["account_suffix"],
                "properties": {"account_suffix": {"type": "string"}},
            }}}}}}},
    }), encoding="utf-8")
    out = tmp_path / "run" / "contract.json"
    assert main(["inspect", str(a), str(b), "--tool-api", str(api_path), "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    rules = result["documents"][0]["clauses"]
    assert rules[0]["mentioned_tools"] == ["revised_verify"]
    assert rules[1]["mentioned_tools"] == []
    assert result["documents"][1]["clauses"][0]["qualified_id"] == "amendment:1"
    assert result["precedence_status"].startswith("unresolved")
    assert result["tool_api_source"]["sha256"]
    assert not result["readiness"]["freya_workflow_generated"]
    assert "remain pending" in capsys.readouterr().out


def test_inspect_cli_rejects_invalid_input_without_writing_success_artifact(tmp_path, capsys):
    brief = tmp_path / "brief.md"
    brief.write_text("1. Ask one question.\n", encoding="utf-8")
    api = tmp_path / "api.json"
    api.write_text('{"openapi":"2.0"}', encoding="utf-8")
    out = tmp_path / "contract.json"
    assert main(["inspect", str(brief), "--tool-api", str(api), "--out", str(out)]) == 2
    assert not out.exists()
    assert capsys.readouterr().err
