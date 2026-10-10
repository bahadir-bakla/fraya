"""Bounded, credential-safe wrapper around documented Freya kit API routes.

No arbitrary HTTP, destructive endpoints, credential-store discovery, or wait loops.
The original competition client and artifacts are never modified.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"completed", "failed", "paused"}
AGENT_LLM = {"provider": "experimental-5", "model": "experimental-5"}
SIM_LLM = {"provider": "google", "model": "gemini-3-flash-preview"}
SECRET_FIELDS = {"authorization", "x-team-key", "api_key", "apikey", "api-key",
                 "freya_api_key", "freya_bank_team_key", "team_key", "token",
                 "access_token", "password", "secret"}


class BridgeError(Exception):
    """Already sanitized error, suitable for an MCP result."""


@dataclass
class Config:
    workspace: Path
    kit: Path
    state_dir: Path = ROOT / "state"
    api_key: str = field(default="", repr=False)
    bank_key: str = field(default="", repr=False)
    workspace_id: str = ""
    api_url: str = "https://staging-app.freyavoice.ai"
    bank_url: str = "https://freya-bank-mock.freyavoice.workers.dev"
    env_file_configured: bool = False

    @classmethod
    def load(cls, workspace: Path, kit: Path, env_file: Path | None = None) -> "Config":
        # dotenv_values is only called for the explicit path; never find_dotenv.
        values: dict[str, Any] = {}
        if env_file is not None:
            if not env_file.is_file():
                raise BridgeError("Explicit credential file is not readable.")
            values = dict(dotenv_values(env_file, interpolate=False))
        values.update(os.environ)  # The invoking launcher's env takes precedence.
        cfg = cls(workspace.resolve(), kit.resolve(),
                  api_key=values.get("FREYA_API_KEY", "") or "",
                  bank_key=values.get("FREYA_BANK_TEAM_KEY", "") or "",
                  workspace_id=values.get("FREYA_WORKSPACE_ID", "") or "",
                  api_url=values.get("FREYA_API_URL", cls.api_url) or cls.api_url,
                  bank_url=values.get("FREYA_BANK_HOST", cls.bank_url) or cls.bank_url,
                  env_file_configured=env_file is not None)
        for address in (cfg.api_url, cfg.bank_url):
            u = urlsplit(address)
            if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise BridgeError("API hosts must be HTTPS origins without credentials, query, or fragment.")
            if u.path not in ("", "/"):
                raise BridgeError("Set API hosts to an origin, without /api/v2.")
        cfg.api_url = cfg.api_url.rstrip("/")
        cfg.bank_url = cfg.bank_url.rstrip("/")
        return cfg


class Bridge:
    def __init__(self, config: Config, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.http = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0),
                                 follow_redirects=False, transport=transport, trust_env=False)
        self._workspace_id = ""

    def close(self) -> None:
        self.http.close()

    def scrub(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): "[REDACTED]" if str(k).lower() in SECRET_FIELDS else self.scrub(v)
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(v) for v in value]
        if isinstance(value, str):
            if value.lstrip().startswith(("{", "[")):
                try:
                    nested = json.loads(value)
                    if isinstance(nested, (dict, list)):
                        return json.dumps(self.scrub(nested), ensure_ascii=False)
                except ValueError:
                    pass
            for secret in (self.config.api_key, self.config.bank_key):
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            # Transcripts sometimes contain serialized request headers.
            value = re.sub(r"fak_[A-Za-z0-9_-]+", "[REDACTED]", value)
            value = re.sub(r"(?i)(Bearer\s+)[^\s\"'\\,}]+", r"\1[REDACTED]", value)
            value = re.sub(r'(?i)(["\']?(?:x-team-key|authorization|FREYA_BANK_TEAM_KEY)["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+',
                           r"\1[REDACTED]", value)
        return value

    def inject_bank_placeholder(self, value: Any) -> Any:
        """Replace the explicit bank-key placeholder only in the outgoing payload."""
        if isinstance(value, dict):
            return {k: self.inject_bank_placeholder(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.inject_bank_placeholder(v) for v in value]
        if isinstance(value, str) and "${FREYA_BANK_TEAM_KEY}" in value:
            self.require(bank=True)
            return value.replace("${FREYA_BANK_TEAM_KEY}", self.config.bank_key)
        return value

    def require(self, bank: bool = False) -> None:
        if bank:
            if len(self.config.bank_key) < 16:
                raise BridgeError("Bank practice is unconfigured: set FREYA_BANK_TEAM_KEY (16+ characters).")
        elif not self.config.api_key:
            raise BridgeError("Freya is unconfigured: inject FREYA_API_KEY through the launcher or an explicit --env-file.")

    def request(self, method: str, path: str, body: Any = None, *, bank: bool = False,
                params: dict[str, Any] | None = None) -> Any:
        self.require(bank)
        headers = {"User-Agent": "Mozilla/5.0 (build-the-builder-freya-mcp/0.1.0)",
                   "Content-Type": "application/json"}
        if bank:
            headers["x-team-key"] = self.config.bank_key
        else:
            headers["Authorization"] = "Bearer " + self.config.api_key
        origin = self.config.bank_url if bank else self.config.api_url
        try:
            response = self.http.request(method, origin + path, json=body, params=params, headers=headers)
        except httpx.HTTPError:
            # Never include request/response repr, URLs, bodies, or library exceptions.
            raise BridgeError("HTTP transport failed; mutation outcome may be unknown. Do not automatically retry writes.") from None
        if response.status_code >= 300:
            if response.status_code in (400, 422) and path == "/api/v2/workflow" and params == {"dryRun": "true"}:
                try:
                    diagnostics = self.scrub(response.json())
                except ValueError:
                    diagnostics = {"message": "non-JSON schema rejection"}
                # Only workflow dry-run feedback is exposed, always credential-redacted and bounded.
                raise BridgeError(f"HTTP {response.status_code} validation: " + json.dumps(diagnostics, ensure_ascii=False)[:6000])
            if response.status_code in (409, 429):
                raise BridgeError(f"HTTP {response.status_code}: conflict or capacity limit; check simulation status before retrying.")
            raise BridgeError(f"HTTP {response.status_code}: Freya request rejected (response body withheld).")
        try:
            result = response.json()
        except (ValueError, UnicodeError):
            raise BridgeError("API returned non-JSON data (body withheld).") from None
        if isinstance(result, dict):
            if result.get("success") is False or result.get("error"):
                raise BridgeError("API reported failure (response details withheld).")
            data = result.get("data")
            if isinstance(data, dict) and "result" in data:
                return data["result"]
        return result

    @staticmethod
    def identifier(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", value):
            raise BridgeError("Invalid resource identifier.")
        return value

    @staticmethod
    def page(limit: int, offset: int) -> dict[str, int]:
        if not 1 <= limit <= 100 or offset < 0:
            raise BridgeError("Pagination requires limit 1..100 and offset >= 0.")
        return {"limit": limit, "offset": offset}

    @staticmethod
    def items(result: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for candidate in (key, "items"):
                if isinstance(result.get(candidate), list):
                    return result[candidate]
        raise BridgeError("Unexpected API list response.")

    @staticmethod
    def unwrap(result: Any, key: str) -> dict[str, Any]:
        if isinstance(result, dict):
            inner = result.get(key, result)
            if isinstance(inner, dict):
                return inner
        raise BridgeError("Unexpected API object response.")

    def workspaces(self) -> list[dict[str, Any]]:
        return self.items(self.request("GET", "/api/v2/workspaces"), "workspaces")

    def workspace_id(self) -> str:
        if self._workspace_id:
            return self._workspace_id
        ids = [w["id"] for w in self.workspaces()]
        selected = self.config.workspace_id
        if selected and selected not in ids:
            raise BridgeError("FREYA_WORKSPACE_ID is not visible to this key.")
        if not selected:
            if len(ids) != 1:
                raise BridgeError("Set FREYA_WORKSPACE_ID explicitly when the API key sees multiple workspaces.")
            selected = ids[0]
        self._workspace_id = self.identifier(selected)
        return self._workspace_id

    def health(self, live: bool = False) -> dict[str, Any]:
        out = {"server": "freya-mcp", "version": "0.1.0", "transport": "stdio",
               "status": "configured" if self.config.api_key else "unconfigured",
               "api_key_present": bool(self.config.api_key), "bank_team_key_present": bool(self.config.bank_key),
               "bank_practice_configured": len(self.config.bank_key) >= 16,
               "env_file_configured": self.config.env_file_configured,
               "workspace_id_configured": bool(self.config.workspace_id),
               "kit_available": (self.config.kit / "freya.py").is_file(),
               "live_checked": False, "live_connected": False}
        if live:
            self.require()
            out["workspace_id"] = self.workspace_id()
            out.update(status="connected", live_checked=True, live_connected=True)
        return out

    def read_json(self, path: str) -> Any:
        p = Path(path)
        if not p.is_absolute():
            p = self.config.workspace / p
        p = p.resolve()
        if not p.is_relative_to(self.config.workspace) or not p.is_file():
            raise BridgeError("Input JSON must be a file inside the configured local workspace.")
        if p.suffix.lower() != ".json" or p.stat().st_size > 8_000_000:
            raise BridgeError("Input must be a JSON file no larger than 8 MB.")
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise BridgeError("Input JSON could not be read (contents withheld).") from None

    def workflow(self, path: str) -> dict[str, Any]:
        raw = self.read_json(path)
        if isinstance(raw, dict) and "workflow" in raw and "nodes" not in raw:
            raw = raw["workflow"]
        if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), dict) or not raw["nodes"]:
            raise BridgeError("Workflow must contain a nonempty nodes object.")
        if raw.get("initial_node") not in raw["nodes"]:
            raise BridgeError("Workflow initial_node must name a node in nodes.")
        if "global_nodes" in raw and not isinstance(raw["global_nodes"], dict):
            raise BridgeError("Workflow global_nodes must be an object.")
        return raw

    def validate(self, path: str, name: str = "mcp-dry-run", remote: bool = True) -> dict[str, Any]:
        workflow = self.workflow(path)
        out: dict[str, Any] = {"local_structure_valid": True, "remote_checked": False,
                               "node_count": len(workflow["nodes"]),
                               "note": "Local structural check only; the platform dry run validates the schema."}
        if remote:
            out["result"] = self.request("POST", "/api/v2/workflow", {"name": name, "workflow": workflow},
                                         params={"dryRun": "true"})
            out["remote_checked"] = True
        return out

    def list_workflows(self, limit: int = 50, offset: int = 0) -> Any:
        return self.request("GET", "/api/v2/workflow", params={"workspaceId": self.workspace_id(), **self.page(limit, offset)})

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.unwrap(self.request("GET", "/api/v2/workflow/" + self.identifier(workflow_id),
                                        params={"workspaceId": self.workspace_id()}), "workflow")

    def state_path(self) -> Path:
        digest = hashlib.sha256((self.config.api_url + "|" + self.workspace_id()).encode()).hexdigest()[:24]
        return self.config.state_dir / (digest + ".json")

    @contextmanager
    def locked_state(self):
        p = self.state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Nonblocking OS lock shared by processes; OS releases it after a crash.
        with open(p.with_suffix(".lock"), "a+b") as f:
            f.seek(0, 2)
            if f.tell() == 0:
                f.write(b"0")
                f.flush()
            f.seek(0)
            acquired = False
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                raise BridgeError("Another bridge operation owns this workspace lock; retry later.") from None
            try:
                state = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                yield state
            finally:
                if acquired:
                    if os.name == "nt":
                        import msvcrt
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f, fcntl.LOCK_UN)

    def persist(self, state: dict[str, Any]) -> None:
        p = self.state_path()
        temp = p.with_suffix(".tmp")
        temp.write_text(json.dumps(self.scrub(state), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, p)

    def publish_latest(self, workflow_id: str) -> dict[str, Any]:
        wid = self.identifier(workflow_id)
        rows = self.items(self.request("GET", f"/api/v2/versions/workflow/{wid}",
                                      params={"workspaceId": self.workspace_id()}), "versions")
        if not rows:
            raise BridgeError("Workflow has no versions to publish.")
        newest = max(rows, key=lambda v: v["versionNumber"])
        if not newest.get("isPublished"):
            self.request("POST", f"/api/v2/versions/workflow/{wid}/publish", {"versionId": newest["id"]})
        return {"workflow_id": wid, "version_id": newest["id"], "version": newest["versionNumber"], "published": True}

    def update(self, workflow_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
        wid = self.identifier(workflow_id)
        self.request("PUT", f"/api/v2/workflow/{wid}", {"workflow": self.inject_bank_placeholder(workflow)})
        stored = self.get_workflow(wid)
        definition = stored.get("workflow")
        if not isinstance(definition, dict):
            raise BridgeError("Updated workflow could not be read back.")
        ac = definition.get("agent_config") or {}
        llm = ac.get("llmConfig") or {}
        if (llm.get("provider"), llm.get("model")) != (AGENT_LLM["provider"], AGENT_LLM["model"]):
            ac = {**ac, "llmConfig": {**llm, **AGENT_LLM}}
            self.request("PUT", f"/api/v2/workflow/{wid}", {"workflow": {**definition, "agent_config": ac}})
        return {**self.publish_latest(wid), "agent_id": stored.get("agentId")}

    def save(self, slot: str, path: str, name: str = "") -> dict[str, Any]:
        if not slot or len(slot) > 150:
            raise BridgeError("Give a stable slot label of 1..150 characters.")
        workflow = self.workflow(path)
        outbound = self.inject_bank_placeholder(workflow)
        with self.locked_state() as state:
            slots = state.setdefault("workflows", {})
            existing = slots.get(slot)
            if existing and existing.get("outcome_unknown"):
                raise BridgeError("Previous create outcome is unknown; list workflows and bind the slot before retrying.")
            if existing:
                result = self.update(existing["workflow_id"], workflow)
                action = "updated"
            else:
                # Record unknown outcomes before POST; no automatic repeated creates.
                slots[slot] = {"outcome_unknown": True}
                self.persist(state)
                made = self.unwrap(self.request("POST", "/api/v2/workflow", {"name": name or slot, "workflow": outbound}), "workflow")
                slots[slot] = {"workflow_id": made["id"], "agent_id": made["agentId"]}
                self.persist(state)  # Remember id even if publishing subsequently fails.
                # Use the same model normalization as the official kit's update path.
                result = self.update(made["id"], workflow)
                action = "created"
            slots[slot] = {"workflow_id": result["workflow_id"], "agent_id": result.get("agent_id") or slots[slot].get("agent_id"),
                           "version": result["version"]}
            self.persist(state)
            return {**slots[slot], "action": action, "published": True}

    def bind_slot(self, slot: str, workflow_id: str) -> dict[str, Any]:
        if not slot or len(slot) > 150:
            raise BridgeError("Give a stable slot label of 1..150 characters.")
        row = self.get_workflow(workflow_id)
        with self.locked_state() as state:
            state.setdefault("workflows", {})[slot] = {"workflow_id": workflow_id, "agent_id": row.get("agentId")}
            self.persist(state)
        return {"slot": slot, "workflow_id": workflow_id, "bound": True}

    def export(self, workflow_id: str, filename: str = "") -> dict[str, Any]:
        row = self.get_workflow(workflow_id)
        filename = filename or self.identifier(workflow_id) + ".workflow.json"
        if Path(filename).name != filename or not filename.endswith(".json") or filename in {".json", ".."}:
            raise BridgeError("Export filename must be a plain .json filename.")
        target = (ROOT / "exports" / filename).resolve()
        if not target.is_relative_to((ROOT / "exports").resolve()):
            raise BridgeError("Export must stay inside the integration exports directory.")
        data = {"workflow_id": row.get("id", workflow_id), "agent_id": row.get("agentId"),
                "updated_at": row.get("updatedAt"), "workflow": row.get("workflow")}
        clean = self.scrub(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"path": str(target), "workflow_id": workflow_id, "secrets_redacted": clean != data,
                "note": "If redacted, restore credentials through an authorized launcher before use; exported files contain no secrets."}

    def list_personas(self, limit: int = 50, offset: int = 0) -> Any:
        return self.request("GET", "/api/v2/personas", params={"workspaceId": self.workspace_id(), **self.page(limit, offset)})

    def create_personas(self, path: str) -> Any:
        rows = self.read_json(path)
        rows = rows.get("personas") if isinstance(rows, dict) else rows
        if not isinstance(rows, list) or not rows or len(rows) > 100:
            raise BridgeError("Persona JSON must be a nonempty array (maximum 100), or a personas envelope.")
        if any(not isinstance(p, dict) or not p.get("name") or not p.get("prompt") for p in rows):
            raise BridgeError("Every persona needs name and prompt.")
        return self.request("POST", "/api/v2/personas", {"personas": rows})

    def list_simulations(self, limit: int = 50, offset: int = 0, status: str = "") -> Any:
        params: dict[str, Any] = {"workspaceId": self.workspace_id(), **self.page(limit, offset)}
        if status:
            if status not in {"draft", "running", "paused", "completed"}:
                raise BridgeError("Invalid list status.")
            params["status"] = status
        return self.request("GET", "/api/v2/simulations", params=params)

    def simulation(self, simulation_id: str) -> dict[str, Any]:
        return self.unwrap(self.request("GET", "/api/v2/simulations/" + self.identifier(simulation_id)), "simulation")

    def assert_idle(self, state: dict[str, Any]) -> None:
        active = state.get("active_simulation")
        if active:
            if not active.get("id"):
                raise BridgeError("Previous simulation start outcome is unknown. List simulations and adopt its id before retrying.")
            if self.simulation(active["id"]).get("status") not in TERMINAL:
                raise BridgeError("A simulation is already active in this workspace. Poll it before starting another.")
        # Check external starts too; the platform also enforces its own workspace cap.
        rows = self.items(self.list_simulations(limit=100, status="running"), "simulations")
        if rows:
            raise BridgeError("A simulation is already running in this workspace. Poll its status before starting another.")

    def start(self, agent_id: str, name: str, variables_by_persona: dict[str, Any],
              max_seconds: int = 420, concurrency: int = 5) -> dict[str, Any]:
        aid = self.identifier(agent_id)
        if not name or len(name) > 200 or not variables_by_persona or len(variables_by_persona) > 100:
            raise BridgeError("Start requires a name and 1..100 personas.")
        for pid, values in variables_by_persona.items():
            self.identifier(pid)
            if not isinstance(values, dict):
                raise BridgeError("Each persona must map to a customer-variable object.")
        if not 60 <= max_seconds <= 3600 or not 1 <= concurrency <= 100:
            raise BridgeError("Duration must be 60..3600 seconds; concurrency 1..100.")
        outbound_variables = self.inject_bank_placeholder(variables_by_persona)
        with self.locked_state() as state:
            self.assert_idle(state)
            state["active_simulation"] = {"outcome_unknown": True, "started_at": time.time()}
            self.persist(state)
            body = {"agentId": aid, "name": name, "mode": "chat", "selectedPersonaIds": list(variables_by_persona),
                    "customerVariablesMap": outbound_variables, "maxConcurrentCalls": concurrency,
                    "runsPerPersona": 1, "maxCallDurationSeconds": max_seconds,
                    "assistantLlmOverride": AGENT_LLM, "routingLlmOverride": AGENT_LLM,
                    "extractionLlmOverride": AGENT_LLM, "personaLlmOverride": SIM_LLM, "analysisLlmOverride": SIM_LLM}
            sim = self.unwrap(self.request("POST", "/api/v2/simulations", body), "simulation")
            sid = self.identifier(sim["id"])
            state["active_simulation"] = {"id": sid, "started_at": time.time()}
            self.persist(state)
        return {"simulation_id": sid, "status": sim.get("status", "started"), "poll_after_seconds": 10,
                "note": "Start returned without waiting. Call freya_simulation_status to poll."}

    def status(self, simulation_id: str, adopt: bool = False) -> dict[str, Any]:
        sim = self.simulation(simulation_id)
        with self.locked_state() as state:
            active = state.get("active_simulation")
            matches = active and active.get("id") == simulation_id
            if adopt and active and active.get("id") and not matches:
                raise BridgeError("Cannot adopt another id while a tracked simulation is active.")
            if matches or adopt:
                state["active_simulation"] = None if sim.get("status") in TERMINAL else {"id": simulation_id}
                self.persist(state)
        return {"simulation_id": simulation_id, "terminal": sim.get("status") in TERMINAL,
                "poll_after_seconds": 10, "simulation": sim}

    def iterations(self, simulation_id: str) -> Any:
        return self.request("GET", f"/api/v2/simulations/{self.identifier(simulation_id)}/iterations")

    def iteration(self, simulation_id: str, iteration_id: str, limit: int = 100, offset: int = 0) -> Any:
        # One page per MCP call so a large simulation cannot monopolize the tool.
        return self.request("GET", f"/api/v2/simulations/{self.identifier(simulation_id)}/iterations/{self.identifier(iteration_id)}",
                            params=self.page(limit, offset))

    def call(self, call_id: str) -> Any:
        return self.unwrap(self.request("GET", "/api/v2/call/" + self.identifier(call_id)), "call")

    def cases(self, brief: str = "", case_ids: list[str] | None = None) -> list[dict[str, Any]]:
        path = self.config.kit / "public-test-set.json"
        rows = self.read_json(str(path))
        return [c for c in rows if (not brief or c["brief"] == brief) and (not case_ids or c["id"] in case_ids)]

    def practice_session(self, case_id: str) -> Any:
        if not self.cases(case_ids=[case_id]):
            raise BridgeError("Case id is not in the official public practice set.")
        return self.request("POST", "/v1/practice/sessions", {"case": case_id}, bank=True)

    def ledger(self, customer_id: str, case_id: str = "") -> dict[str, Any]:
        led = self.request("GET", "/v1/practice/ledger/" + self.identifier(customer_id), bank=True)
        out = {"customer_id": customer_id, "ledger": led}
        if case_id:
            rows = self.cases(case_ids=[case_id])
            if not rows:
                raise BridgeError("Unknown practice case id.")
            spec = importlib.util.spec_from_file_location("freya_mcp_kit_score", self.config.kit / "tools" / "score.py")
            if spec is None or spec.loader is None:
                raise BridgeError("Kit scoring helper unavailable.")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            out["ledger_score"] = module.score_ledger(rows[0], led)
            out["note"] = "Ledger score only; combine with the simulation judge outcome for full practice scoring."
        return out

    def prepare_practice(self, brief: str = "", case_ids: list[str] | None = None,
                         style: str = "") -> dict[str, Any]:
        self.require()
        self.require(bank=True)
        cases = self.cases(brief, case_ids)
        if not cases:
            raise BridgeError("No practice cases matched.")
        if len(cases) > 5:
            raise BridgeError("Prepare at most five practice cases per tool call; pass case_ids in batches.")
        # Load only the kit's persona constants/function; do not invoke run_cases.py
        # (which blocks for minutes and writes shared kit files).
        tree = ast.parse((self.config.kit / "tools" / "run_cases.py").read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"PERSONA", "STYLES"} for t in n.targets))
                 or (isinstance(n, ast.FunctionDef) and n.name == "persona_for")]
        namespace: dict[str, Any] = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "kit_persona_for", "exec"), namespace)
        if style and style not in namespace["STYLES"]:
            raise BridgeError("Unknown practice speaking style.")
        variables: dict[str, Any] = {}
        bindings: list[dict[str, Any]] = []
        with self.locked_state() as state:
            cached = state.setdefault("practice_personas", {})
            for case in cases:
                persona = namespace["persona_for"](case, {"identity": case["identity"]}, style or None)
                digest = hashlib.sha256(json.dumps(persona, sort_keys=True).encode()).hexdigest()
                if digest not in cached:
                    made = self.items(self.request("POST", "/api/v2/personas", {"personas": [persona]}), "personas")
                    cached[digest] = made[0]["id"]
                    self.persist(state)
                pid = cached[digest]
                session = self.practice_session(case["id"])
                values = session.get("variables")
                if not isinstance(values, dict):
                    raise BridgeError("Practice session did not return variables.")
                variables[pid] = values
                bindings.append({"case_id": case["id"], "persona_id": pid, "customer_id": values.get("customer_id")})
        return {"variables_by_persona": variables, "cases": bindings, "simulation_started": False}
