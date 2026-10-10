"""Run one small seeded graph/simulation through the pinned official MiroFish API.

Every completed stage is recorded separately. A healthy server or accepted
start request is never treated as a completed simulation. State is resumable;
only this run's fresh, labelled graph/project are accessed or mutated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from authenticated_runtime import HERE, RUNTIME, ROOT, VENDOR, install_redaction, proxy_settings, redact, zep_key

SEED = HERE / "scenarios" / "authenticated-smoke-seed.txt"
REQUIREMENT = (
    "Run a tiny synthetic Twitter-style discussion for exactly one round. "
    "Only two fictional people can act: Maya Reed and Noah Vale. "
    "Maya supports opening their workshop thirty minutes earlier next Saturday; "
    "Noah prefers usual opening because the bus timetable is fixed. "
    "Observe one respectful exchange. Do not invent extra actors, organizations, "
    "events, accounts, financial actions, or real-world predictions. "
    "Use a single Participant entity type for both people and a DISCUSSES_WITH relation. "
    "Use at most two active agents, one short initial post from Maya, and one round."
)


def completed_run(state, actions, engine=None):
    """Require an actual finished bounded round and observed agent actions."""
    if state.get("runner_status") != "completed" or int(state.get("total_rounds", 0)) != 1:
        return False
    if engine is not None:
        # The pinned single-platform script has no actions.jsonl writer, so
        # API counters stay zero. Preserve that fact; use independent engine
        # output and persisted platform actions, never fabricated counters.
        return (engine.get("completed_rounds") == 1 and engine.get("active_agents", 0) > 0
                and engine.get("initialization_verified") is True
                and any(action.get("action") in {"create_post", "like_post", "repost", "follow", "do_nothing", "quote_post"}
                        for action in engine.get("actions_after_seed", []))
                and not engine.get("agent_errors"))
    return int(state.get("current_round", 0)) == 1 and bool(actions)


def bounded_config(config, max_agents):
    """Bound this generated test configuration and activate the first round."""
    config = json.loads(json.dumps(config))
    agents = config.get("agent_configs", [])
    if not 1 <= len(agents) <= max_agents:
        raise ValueError("Generated configuration exceeds the agent budget")
    config["time_config"].update(total_simulation_hours=1, minutes_per_round=60,
                                 agents_per_hour_min=len(agents), agents_per_hour_max=len(agents),
                                 peak_hours=[], off_peak_hours=[], peak_activity_multiplier=1,
                                 off_peak_activity_multiplier=1)
    for agent in agents:
        agent.update(active_hours=[0], activity_level=1.0)
    posts = config.get("event_config", {}).get("initial_posts", [])
    if len(posts) != 1:
        raise ValueError("The smoke configuration must contain exactly one seeded post")
    maya = next((agent for agent in agents if agent.get("entity_name") == "Maya Reed"), None)
    if maya is None:
        raise ValueError("Synthetic participant Maya Reed is missing")
    posts[0]["poster_agent_id"] = maya["agent_id"]
    return config


class Smoke:
    def __init__(self, base_url, secrets, max_agents=3, phase_timeout=600):
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("The smoke harness accepts only the local MiroFish server")
        if not 1 <= max_agents <= 3 or not 1 <= phase_timeout <= 600:
            raise ValueError("Smoke limits are one to three agents and at most 600 seconds per phase")
        self.secrets, self.max_agents, self.phase_timeout = secrets, max_agents, phase_timeout
        self.path = RUNTIME / "authenticated-simulation.json"
        if self.path.is_file():
            self.evidence = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            label = "fraya-rd_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.evidence = {
                "schema_version": 1, "label": label, "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "backend_base_url": self.base_url, "seed_file": str(SEED), "synthetic_data_only": True,
                "budget": {"maximum_agents": max_agents, "maximum_rounds": 1, "platforms": ["twitter"],
                           "llm_persona_generation": False, "graph_memory_updates": False},
                "stages": {}, "simulation_completed": False, "freya_calls": 0, "bank_calls": 0,
                "existing_graph_mutations": 0, "credential_values_logged": False,
            }

    def save(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.evidence["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        serialized = redact(json.dumps(self.evidence, indent=2, ensure_ascii=False), self.secrets)
        self.path.write_text(serialized + "\n", encoding="utf-8")

    def stage(self, name, data):
        self.evidence["stages"][name] = data
        self.evidence["last_stage"] = name
        self.save()
        summary = {k: v for k, v in data.items() if k in {
            "status", "status_code", "task_id", "project_id", "graph_id", "simulation_id", "node_count", "edge_count",
            "profiles_count", "runner_status", "current_round", "total_rounds", "total_actions_count", "agent_count", "message",
        }}
        print(redact(json.dumps({"stage": name, **summary}, ensure_ascii=True), self.secrets), flush=True)

    def call(self, path, payload=None, *, multipart=None, timeout=180):
        headers = {"Accept": "application/json", "Accept-Language": "en"}
        data = None
        if multipart is not None:
            boundary = "mirofish_smoke_" + uuid.uuid4().hex
            fields = {
                "project_name": self.evidence["label"], "simulation_requirement": REQUIREMENT,
                "additional_context": "Synthetic bounded integration verification. Exactly two human participants; no additional actors.",
            }
            chunks = []
            for name, value in fields.items():
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="authenticated-smoke-seed.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode())
            chunks.extend([multipart, f"\r\n--{boundary}--\r\n".encode()])
            data = b"".join(chunks)
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(self.base_url + path, data=data, headers=headers), timeout=timeout) as response:
                code, body = response.status, json.load(response)
        except HTTPError as error:
            code = error.code
            try:
                body = json.loads(error.read().decode("utf-8", "replace"))
            except (ValueError, UnicodeError):
                body = {"error": "HTTP error with a non-JSON response"}
        if code != 200 or body.get("success") is False:
            safe = json.loads(redact(json.dumps(body), self.secrets))
            self.stage("last_api_error", {"status_code": code, "path": path, "response": safe})
            raise RuntimeError(f"Official MiroFish API failed at {path}, status {code}: {redact(str(body.get('error')), self.secrets)}")
        return code, body

    def wait_task(self, task_id, stage):
        deadline = time.monotonic() + self.phase_timeout
        last = None
        while time.monotonic() < deadline:
            _, response = self.call("/api/graph/task/" + task_id, timeout=30)
            data = response["data"]
            state = (data.get("status"), data.get("progress"), data.get("message"))
            if state != last:
                self.stage(stage, data)
                last = state
            if data.get("status") == "completed":
                return data
            if data.get("status") == "failed":
                raise RuntimeError(f"{stage} failed: {redact(str(data.get('message')), self.secrets)}")
            time.sleep(4)
        raise TimeoutError(f"{stage} did not complete within {self.phase_timeout} seconds")

    def simulation_directory(self):
        simulation_id = self.evidence["simulation_id"]
        if not re.fullmatch(r"sim_[a-f0-9]+", simulation_id):
            raise ValueError("Invalid owned simulation identifier")
        return VENDOR / "backend" / "uploads" / "simulations" / simulation_id

    def configure_run(self):
        path = self.simulation_directory() / "simulation_config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        if config.get("graph_id") != self.evidence["graph_id"] or config.get("project_id") != self.evidence["project_id"]:
            raise ValueError("Refusing to edit configuration outside this test's project/graph")
        modified = bounded_config(config, self.max_agents)
        path.write_text(json.dumps(modified, indent=2) + "\n", encoding="utf-8")
        self.stage("bounded_run_config", {"status": "configured", "agent_count": len(modified["agent_configs"]),
                   "maximum_rounds": 1, "active_hour": 0, "seed_posts": 1,
                   "source": "owned generated simulation_config.json; upstream source unchanged",
                   "reason": "Generated evening-only activation would skip the midnight first round"})

    def observe_engine(self):
        directory = self.simulation_directory()
        log = redact((directory / "simulation.log").read_text(encoding="utf-8", errors="replace"), self.secrets)
        rounds = re.findall(r"Round (\d+)/(\d+).*?- (\d+) agents active", log)
        evidence = {"source": "pinned single-platform engine output and read-only OASIS SQLite trace",
                    "completed_rounds": max((int(r[0]) for r in rounds), default=0),
                    "active_agents": max((int(r[2]) for r in rounds), default=0),
                    "agent_errors": re.findall(r"Agent \d+ error:.*", log),
                    "initialization_verified": False, "actions_after_seed": [],
                    "official_api_action_counters_available": False}
        path = directory / "twitter_simulation.db"
        if not path.is_file():
            return evidence
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            traces = [{"rowid": row[0], "agent_id": row[1], "action": row[2], "info": row[3]}
                      for row in connection.execute("SELECT rowid,user_id,action,info FROM trace ORDER BY rowid")]
            agents = connection.execute('SELECT count(*) FROM "user"').fetchone()[0]
        initial = traces[:agents + 1]
        evidence.update(agent_count=agents, trace_count=len(traces),
                        initialization_verified=(len(initial) == agents + 1
                           and all(row["action"] == "sign_up" for row in initial[:agents])
                           and initial[-1]["action"] == "create_post"),
                        actions_after_seed=traces[agents + 1:])
        return evidence

    def run(self):
        # Normal launcher validation must have passed; this is not the offline app-factory bypass.
        deadline = time.monotonic() + 120
        while True:
            try:
                code, health = self.call("/health", timeout=5)
                break
            except (URLError, TimeoutError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
        self.stage("normal_backend_health", {"status": "healthy", "status_code": code, "body": health,
                                            "normal_launcher": "backend/run.py", "credential_validation_bypassed": False})
        if "project_id" not in self.evidence:
            code, response = self.call("/api/graph/ontology/generate", multipart=SEED.read_bytes(), timeout=240)
            data = response["data"]
            self.evidence["project_id"] = data["project_id"]
            self.evidence["ontology"] = data["ontology"]
            self.stage("ontology", {"status": "completed", "status_code": code, **data})
        if "graph_id" not in self.evidence:
            task = self.evidence.get("graph_task_id")
            if not task:
                _, response = self.call("/api/graph/build", {
                    "project_id": self.evidence["project_id"], "graph_name": self.evidence["label"],
                    "chunk_size": 3000, "chunk_overlap": 0,
                })
                task = self.evidence["graph_task_id"] = response["data"]["task_id"]
                self.stage("graph_requested", response["data"])
            result = self.wait_task(task, "graph_build")
            self.evidence["graph_id"] = result["result"]["graph_id"]
            self.save()
        _, graph = self.call("/api/graph/data/" + self.evidence["graph_id"])
        self.stage("graph_observed", {"status": "completed", **graph["data"]})
        _, entities = self.call("/api/simulation/entities/" + self.evidence["graph_id"] + "?enrich=false")
        entity_data = entities["data"]
        self.stage("entities_observed", {"status": "completed", **entity_data})
        actual_count = entity_data.get("filtered_count", len(entity_data.get("entities", [])))
        if not 1 <= actual_count <= self.max_agents:
            raise ValueError(f"Refusing unbounded preparation: observed {actual_count} candidate agents (cap {self.max_agents})")
        if "simulation_id" not in self.evidence:
            _, response = self.call("/api/simulation/create", {
                "project_id": self.evidence["project_id"], "graph_id": self.evidence["graph_id"],
                "enable_twitter": True, "enable_reddit": False,
            })
            self.evidence["simulation_id"] = response["data"]["simulation_id"]
            self.stage("simulation_created", response["data"])
        simulation_id = self.evidence["simulation_id"]
        if not self.evidence.get("prepared"):
            task = self.evidence.get("prepare_task_id")
            if not task:
                _, response = self.call("/api/simulation/prepare", {
                    "simulation_id": simulation_id, "use_llm_for_profiles": False, "parallel_profile_count": 1,
                    "force_regenerate": False,
                })
                task = self.evidence["prepare_task_id"] = response["data"].get("task_id")
                self.stage("prepare_requested", response["data"])
            if task:
                self.wait_task(task, "simulation_prepare")
            _, response = self.call("/api/simulation/" + simulation_id)
            state = response["data"]
            profiles = int(state.get("profiles_count", 0))
            if state.get("status") != "ready" or not 1 <= profiles <= self.max_agents:
                raise ValueError("The official preparation did not produce a ready simulation within the agent cap")
            self.evidence["prepared"] = True
            self.stage("simulation_ready", {"status": "ready", "agent_count": profiles, **state})
        if not self.evidence.get("run_started"):
            self.configure_run()
            _, response = self.call("/api/simulation/start", {
                "simulation_id": simulation_id, "platform": "twitter", "max_rounds": 1,
                "enable_graph_memory_update": False, "force": False,
            })
            self.evidence["run_started"] = True
            self.stage("run_started", response["data"])
        deadline = time.monotonic() + self.phase_timeout
        last = None
        close_requested = False
        while time.monotonic() < deadline:
            _, response = self.call("/api/simulation/" + simulation_id + "/run-status", timeout=30)
            state = response["data"]
            snapshot = (state.get("runner_status"), state.get("current_round"), state.get("total_actions_count"))
            if snapshot != last:
                self.stage("run_observed", state)
                last = snapshot
            if state.get("runner_status") == "running" and not close_requested:
                # Upstream waits for interviews after its loop. Close only our
                # environment so the official monitor sees terminal process status.
                _, environment = self.call("/api/simulation/env-status", {"simulation_id": simulation_id}, timeout=15)
                if environment["data"].get("env_alive"):
                    _, response = self.call("/api/simulation/close-env", {"simulation_id": simulation_id}, timeout=45)
                    self.stage("environment_closed", {"status": "closed", **response["data"]})
                    close_requested = True
            if state.get("runner_status") in {"completed", "failed", "stopped"}:
                _, response = self.call("/api/simulation/" + simulation_id + "/actions?limit=30")
                actions = response["data"]["actions"]
                self.stage("actions_observed", {"status": "observed", "count": len(actions), "actions": actions})
                engine = self.observe_engine()
                self.stage("engine_observed", {"status": "observed", **engine})
                self.evidence["simulation_completed"] = completed_run(state, actions, engine)
                self.save()
                if not self.evidence["simulation_completed"]:
                    raise RuntimeError("The engine did not complete an observed one-round simulation with agent actions")
                # Stop only our run's post-simulation environment, after preserving evidence.
                if not close_requested and self.evidence["stages"].get("environment_closed", {}).get("status") != "closed":
                    _, response = self.call("/api/simulation/close-env", {"simulation_id": simulation_id})
                    self.stage("environment_closed", {"status": "closed", **response.get("data", {})})
                self.evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
                self.save()
                return self.evidence
            time.sleep(4)
        # Bound any still-running engine before returning a truthful timeout.
        self.call("/api/simulation/stop", {"simulation_id": simulation_id})
        raise TimeoutError("The one-round simulation exceeded the bounded wait and was stopped")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--proxy-config", required=True)
    parser.add_argument("--max-agents", type=int, default=3)
    parser.add_argument("--phase-timeout", type=int, default=600)
    parser.add_argument("--retry-incomplete", action="store_true")
    args = parser.parse_args()
    settings = proxy_settings(args.proxy_config)
    secrets = [*settings["keys"], zep_key(ROOT / ".local-secrets" / "zep-key.dpapi")]
    install_redaction(secrets)
    smoke = Smoke(args.backend_base_url, secrets, args.max_agents, args.phase_timeout)
    try:
        if args.retry_incomplete:
            if smoke.evidence.get("simulation_completed") or not smoke.evidence.get("run_started"):
                raise ValueError("Retry requires this test's incomplete prior run")
            if smoke.evidence.get("attempt_history"):
                raise ValueError("The smoke budget permits only one correction attempt")
            _, previous = smoke.call("/api/simulation/" + smoke.evidence["simulation_id"] + "/run-status", timeout=15)
            if previous["data"].get("runner_status") not in {"completed", "failed", "stopped"}:
                raise ValueError("The previous owned engine must finish or stop before a correction attempt")
            directory = smoke.simulation_directory()
            prior = {"run": smoke.evidence["stages"].get("run_observed"),
                     "actions": smoke.evidence["stages"].get("actions_observed"),
                     "engine": smoke.observe_engine(),
                     "reason": "No first-round activation in generated evening-only schedule"}
            smoke.evidence["attempt_history"] = [prior]
            shutil.copy2(directory / "simulation.log", RUNTIME / "first-inactive-attempt.log")
            smoke.evidence.update(run_started=False, simulation_completed=False,
                                  first_simulation_id=smoke.evidence["simulation_id"])
            # Pinned restart validation insists on a Reddit profile even for
            # Twitter-only runs. Create/prepare one new bounded simulation on
            # the same owned graph through the official API instead.
            for key in ("simulation_id", "prepare_task_id", "prepared", "last_error"):
                smoke.evidence.pop(key, None)
            smoke.save()
        evidence = smoke.run()
        print(json.dumps({"status": "simulation_completed", "project_id": evidence["project_id"],
                          "graph_id": evidence["graph_id"], "simulation_id": evidence["simulation_id"]}), flush=True)
        return 0
    except Exception as error:
        if smoke.evidence.get("run_started") and not smoke.evidence.get("simulation_completed"):
            try:
                _, response = smoke.call("/api/simulation/stop", {"simulation_id": smoke.evidence["simulation_id"]}, timeout=45)
                smoke.stage("incomplete_run_stopped", response.get("data", {}))
            except Exception as stop_error:
                smoke.evidence["stop_error"] = {"type": type(stop_error).__name__, "message": redact(str(stop_error), secrets)}
        smoke.evidence["last_error"] = {"type": type(error).__name__, "message": redact(str(error), secrets)}
        smoke.save()
        print(json.dumps({"status": "incomplete", "last_stage": smoke.evidence.get("last_stage"),
                          "error_type": type(error).__name__, "message": redact(str(error), secrets)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
