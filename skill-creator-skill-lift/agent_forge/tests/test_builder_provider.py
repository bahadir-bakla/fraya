"""Offline compiler-process boundary tests; never launch a CLI/model."""

import io
import json
from pathlib import Path
import subprocess

import pytest

from agent_forge import builder_provider
from agent_forge.builder_provider import CodexProvider, ProviderError


SCHEMA = {"type": "object", "properties": {"decision": {"type": "string", "enum": ["ready"]}},
          "required": ["decision"], "additionalProperties": False}


class CapturedInput(io.StringIO):
    def close(self):
        self.submitted = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, args, *, response, events=(), stderr="", exit_code=0, timeout=False, broken_input=False):
        self.args = args
        self.stdin = CapturedInput()
        if broken_input:
            self.stdin.write = lambda _: (_ for _ in ()).throw(BrokenPipeError("closed compiler input"))
        self.stdout = io.StringIO("\n".join(json.dumps(e) for e in events) + "\n")
        self.stderr = io.StringIO(stderr)
        self.returncode = exit_code
        self.timeout = timeout
        self.killed = False
        self.wait_timeouts = []
        if response is not None:
            path = Path(args[args.index("--output-last-message") + 1])
            path.write_text(response, encoding="utf-8")

    def wait(self, timeout):
        self.wait_timeouts.append(timeout)
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Replacing the environment prevents real credentials appearing in test captures.
    monkeypatch.setattr(builder_provider.os, "environ", {
        "PATH": "fixture-path", "CODEX_HOME": "fixture-login-home", "LANG": "en_US.UTF-8",
        "FREYA_API_KEY": "fixture-bank-key", "FREYA_BASE_URL": "fixture-bank-url",
        "FREYA_WRITE_TOKEN": "fixture-write-token", "FREYA_MCP_CONFIG": "fixture-mcp-config",
    })
    monkeypatch.setattr(builder_provider.shutil, "which", lambda _: "fixture-codex.exe")

    def prohibit_process(*args, **kwargs):
        pytest.fail("A provider test attempted to launch an external process")

    monkeypatch.setattr(builder_provider.subprocess, "Popen", prohibit_process)


@pytest.fixture
def fake_process(monkeypatch):
    captures = []

    def configure(**options):
        def launch(args, **kwargs):
            process = FakeProcess(args, **options)
            captures.append((process, kwargs))
            return process
        monkeypatch.setattr(builder_provider.subprocess, "Popen", launch)
        return captures

    return configure


def provider(tmp_path):
    events = []
    instance = CodexProvider(tmp_path / "compiler", model="fixture-compiler-model",
                             event=lambda name, **details: events.append((name, details)))
    return instance, events


def test_valid_compiler_response_and_usage_are_returned_from_bounded_process(tmp_path, fake_process):
    captures = fake_process(response='\ufeff{"decision":"ready"}', events=[
        {"type": "item.completed", "item": {"type": "agent_message", "text": "compiled"}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}},
    ])
    instance, events = provider(tmp_path)
    assert instance.generate("policy", "Compile the fixture policy", SCHEMA, 37) == {"decision": "ready"}
    process, kwargs = captures[0]
    assert process.wait_timeouts == [37]
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
    assert kwargs["cwd"] == instance.directory
    assert json.loads(Path(process.args[process.args.index("--output-schema") + 1]).read_text(encoding="utf-8")) == SCHEMA
    finished = [details for name, details in events if name == "model_call_finished"]
    assert finished and finished[0]["usage"] == [{"input_tokens": 10, "output_tokens": 3}]
    assert finished[0]["tool_events"] == 0 and finished[0]["exit_code"] == 0
    assert "Compile the fixture policy" in process.stdin.submitted


def test_bank_credentials_and_mcp_env_are_excluded_without_losing_login_home(tmp_path, fake_process):
    captures = fake_process(response='{"decision":"ready"}')
    instance, _ = provider(tmp_path)
    instance.generate("policy", "No secret material", SCHEMA, 5)
    process, options = captures[0]
    assert not any(key.startswith("FREYA_") for key in options["env"])
    assert options["env"]["CODEX_HOME"] == "fixture-login-home"
    assert options["env"]["PATH"] == "fixture-path"
    assert all(value not in process.stdin.submitted for value in ("fixture-bank-key", "fixture-write-token", "fixture-mcp-config"))
    assert "--ignore-user-config" in process.args and "--ignore-rules" in process.args
    assert process.args[process.args.index("--sandbox") + 1] == "read-only"
    disabled = {process.args[i + 1] for i, arg in enumerate(process.args[:-1]) if arg == "--disable"}
    assert {"shell_tool", "multi_agent", "apps", "plugins", "browser_use", "computer_use"} <= disabled


@pytest.mark.parametrize("tool_type", ["command_execution", "file_change", "mcp_tool_call", "web_search", "collab_agent_tool_call"])
def test_any_tool_receipt_rejects_an_otherwise_valid_response(tmp_path, fake_process, tool_type):
    fake_process(response='{"decision":"ready"}', events=[
        {"type": "item.completed", "item": {"type": tool_type, "status": "failed"}},
    ])
    instance, events = provider(tmp_path)
    with pytest.raises(ProviderError, match="unexpected tools=1"):
        instance.generate("policy", "Compile without tools", SCHEMA, 5)
    assert next(details for name, details in events if name == "model_call_finished")["tool_events"] == 1


def test_timeout_kills_process_drains_streams_and_reports_failure(tmp_path, fake_process):
    captures = fake_process(response=None, timeout=True, stderr="fixture-sensitive-host-information\n")
    instance, events = provider(tmp_path)
    with pytest.raises(ProviderError, match="time budget") as error:
        instance.generate("workflow", "Compile fixture", SCHEMA, 2)
    process, _ = captures[0]
    assert process.killed and process.wait_timeouts == [2, 10]
    assert process.stdout.closed and process.stderr.closed
    assert any(name == "model_call_failed" for name, _ in events)
    assert not any(name == "model_call_finished" for name, _ in events)
    assert "fixture-sensitive-host-information" not in str(error.value) + json.dumps(events)


def test_closed_input_is_reported_as_provider_failure(tmp_path, fake_process):
    captures = fake_process(response=None, broken_input=True)
    instance, events = provider(tmp_path)
    with pytest.raises(ProviderError, match="closed input"):
        instance.generate("policy", "Compile fixture", SCHEMA, 5)
    assert captures[0][0].killed
    assert any(name == "model_call_failed" for name, _ in events)


@pytest.mark.parametrize("response,exit_code", [(None, 0), ('{"decision":"ready"}', 7), ("not json", 0)])
def test_missing_failed_or_malformed_response_is_rejected_without_stderr_leak(tmp_path, fake_process, response, exit_code):
    fake_process(response=response, exit_code=exit_code, stderr="fixture-secret-path\n")
    instance, events = provider(tmp_path)
    with pytest.raises(ProviderError) as error:
        instance.generate("policy", "Compile fixture", SCHEMA, 5)
    assert "fixture-secret-path" not in str(error.value) + json.dumps(events)


def test_exhausted_budget_does_not_launch_or_write_schema(tmp_path):
    instance, _ = provider(tmp_path)
    with pytest.raises(ProviderError, match="budget exhausted"):
        instance.generate("policy", "Compile fixture", SCHEMA, 0.5)
    assert list(instance.directory.iterdir()) == [] and instance.calls == 0


def test_missing_cli_is_actionable_and_does_not_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(builder_provider.shutil, "which", lambda _: None)
    instance, _ = provider(tmp_path)
    with pytest.raises(ProviderError, match="not installed/on PATH"):
        instance.generate("policy", "Compile fixture", SCHEMA, 5)
    assert instance.calls == 0


def test_fresh_provider_cannot_accept_a_previous_runs_response(tmp_path, fake_process):
    fake_process(response='{"decision":"ready"}')
    first, _ = provider(tmp_path)
    assert first.generate("policy", "Compile the previous source", SCHEMA, 5) == {"decision": "ready"}

    # A resumed/repeated build reuses its output directory but produces no reply.
    # The old, schema-valid response must never count as a result for new sources.
    fake_process(response=None)
    repeated, _ = provider(tmp_path)
    with pytest.raises(ProviderError):
        repeated.generate("policy", "Compile different source rules", SCHEMA, 5)


@pytest.mark.parametrize("response", ["[]", "null", "NaN", '{"decision":NaN}', '{"decision":"not-in-schema"}', '{"decision":"ready","invented":true}'])
def test_provider_response_must_be_a_schema_valid_finite_json_object(tmp_path, fake_process, response):
    fake_process(response=response)
    instance, _ = provider(tmp_path)
    with pytest.raises(ProviderError):
        instance.generate("policy", "Compile fixture", SCHEMA, 5)
