"""Codex stdio entrypoint. Protocol only on stdout; never log credentials."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from typing import Any, Callable

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from freya_mcp.bridge import Bridge, BridgeError, Config, ROOT

INSTRUCTIONS = (
    "Freya bridge for the official competition kit. Check freya_health first; configured does not mean live-connected. "
    "Never expose credentials. Use stable workflow slots; updates publish before testing. "
    "Only one simulation per Freya workspace: start returns immediately; poll status every 10 seconds. "
    "No destructive tools or endpoint probing. Inputs stay in the local workspace; exports/state stay in this integration. "
    "Exported secrets are redacted. Public practice data is synthetic."
)


def build_server(bridge: Bridge) -> FastMCP:
    mcp = FastMCP("freya-mcp", instructions=INSTRUCTIONS, log_level="CRITICAL")

    def run(operation: Callable[..., Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return {"ok": True, "data": bridge.scrub(operation(*args, **kwargs))}
        except BridgeError as exc:
            return {"ok": False, "error": bridge.scrub(str(exc))}
        except Exception:
            # No raw exception repr or stack trace: API responses may contain keys.
            return {"ok": False, "error": "Bridge operation failed; details withheld to protect credentials."}

    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
    local = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=read)
    def freya_health(live: bool = False) -> dict[str, Any]:
        """Safe configured status. Default is offline; live=True verifies read-only workspace access."""
        return run(bridge.health, live)

    @mcp.tool(annotations=read)
    def freya_list_workspaces() -> dict[str, Any]:
        """List workspaces visible to the API key. Multiple workspaces require explicit FREYA_WORKSPACE_ID."""
        return run(bridge.workspaces)

    @mcp.tool(annotations=read)
    def freya_list_workflows(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List one page of workflows in the configured Freya workspace (limit 1..100)."""
        return run(bridge.list_workflows, limit, offset)

    @mcp.tool(annotations=read)
    def freya_get_workflow(workflow_id: str) -> dict[str, Any]:
        """Read the stored workflow. All credentials in returned definitions are redacted."""
        return run(bridge.get_workflow, workflow_id)

    @mcp.tool(annotations=read)
    def freya_validate_workflow(workflow_path: str, name: str = "mcp-dry-run", remote: bool = True) -> dict[str, Any]:
        """Platform dryRun without saving. remote=False checks local structure offline, not the full schema."""
        return run(bridge.validate, workflow_path, name, remote)

    @mcp.tool(annotations=write)
    def freya_save_workflow(slot: str, workflow_path: str, name: str = "") -> dict[str, Any]:
        """Create once per stable slot, otherwise update the same workflow, normalize kit model, and publish."""
        return run(bridge.save, slot, workflow_path, name)

    @mcp.tool(annotations=write)
    def freya_bind_workflow_slot(slot: str, workflow_id: str) -> dict[str, Any]:
        """Bind an existing remote workflow to a local stable slot; use after an uncertain create outcome."""
        return run(bridge.bind_slot, slot, workflow_id)

    @mcp.tool(annotations=write)
    def freya_update_workflow(workflow_id: str, workflow_path: str) -> dict[str, Any]:
        """Replace the entire workflow definition and publish its newest version, as in the official kit."""
        def operation():
            definition = bridge.workflow(workflow_path)
            with bridge.locked_state():
                return bridge.update(workflow_id, definition)
        return run(operation)

    @mcp.tool(annotations=write)
    def freya_publish_workflow(workflow_id: str) -> dict[str, Any]:
        """Publish the newest version of an existing workflow. No simulation starts."""
        def operation():
            with bridge.locked_state():
                return bridge.publish_latest(workflow_id)
        return run(operation)

    @mcp.tool(annotations=write)
    def freya_export_workflow(workflow_id: str, filename: str = "") -> dict[str, Any]:
        """Read and export a workflow under integration/exports. Redacts secrets and reports whether redaction occurred."""
        return run(bridge.export, workflow_id, filename)

    @mcp.tool(annotations=read)
    def freya_list_personas(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List one page of personas (documented workspaceId query)."""
        return run(bridge.list_personas, limit, offset)

    @mcp.tool(annotations=write)
    def freya_create_personas(personas_path: str) -> dict[str, Any]:
        """Create personas from a workspace JSON file: array or {personas: [...]}. Does not start tests."""
        return run(bridge.create_personas, personas_path)

    @mcp.tool(annotations=read)
    def freya_list_simulations(limit: int = 50, offset: int = 0, status: str = "") -> dict[str, Any]:
        """List simulations, including externally started runs; no polling loop."""
        return run(bridge.list_simulations, limit, offset, status)

    @mcp.tool(annotations=write)
    def freya_start_simulation(agent_id: str, name: str, variables_path: str,
                               max_seconds: int = 420, concurrency: int = 5) -> dict[str, Any]:
        """Start one chat simulation and return its id immediately. JSON maps persona ids to customer variables.

        Refuses overlap in the Freya workspace. Uses the fixed official kit's agent and judge models.
        Poll freya_simulation_status every 10 seconds; never retry an unknown mutation outcome.
        """
        def operation():
            values = bridge.read_json(variables_path)
            if isinstance(values, dict) and "variables_by_persona" in values:
                values = values["variables_by_persona"]
            if not isinstance(values, dict):
                raise BridgeError("Variables JSON must map persona ids to customer-variable objects.")
            return bridge.start(agent_id, name, values, max_seconds, concurrency)
        return run(operation)

    @mcp.tool(annotations=read)
    def freya_simulation_status(simulation_id: str, adopt: bool = False) -> dict[str, Any]:
        """Get status once. Terminal: completed, failed, paused. adopt=True recovers an uncertain start by known id."""
        return run(bridge.status, simulation_id, adopt)

    @mcp.tool(annotations=read)
    def freya_list_iterations(simulation_id: str) -> dict[str, Any]:
        """List iterations of a simulation after or during a run."""
        return run(bridge.iterations, simulation_id)

    @mcp.tool(annotations=read)
    def freya_get_iteration(simulation_id: str, iteration_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Get a single page of runs with call ids and judge verdicts. Follow pages until runsTotal is covered."""
        return run(bridge.iteration, simulation_id, iteration_id, limit, offset)

    @mcp.tool(annotations=read)
    def freya_get_call(call_id: str) -> dict[str, Any]:
        """Read a call's transcript, messages, tool calls, and workflow snapshots with secrets removed."""
        return run(bridge.call, call_id)

    @mcp.tool(annotations=local)
    def freya_practice_cases(brief: str = "", case_ids: list[str] | None = None) -> dict[str, Any]:
        """Read the official public test cases offline, optionally filtered by brief A/B and case ids."""
        return run(bridge.cases, brief, case_ids)

    @mcp.tool(annotations=write)
    def freya_create_practice_session(case_id: str) -> dict[str, Any]:
        """Create a synthetic bank practice session for a public case. Needs bank team key (16+ characters)."""
        return run(bridge.practice_session, case_id)

    @mcp.tool(annotations=read)
    def freya_practice_ledger(customer_id: str, case_id: str = "") -> dict[str, Any]:
        """Read the synthetic bank ledger. Optional case_id runs the official kit's ledger scorer; judge is separate."""
        return run(bridge.ledger, customer_id, case_id)

    @mcp.tool(annotations=write)
    def freya_prepare_practice(brief: str = "", case_ids: list[str] | None = None, style: str = "") -> dict[str, Any]:
        """Prepare up to five cases: reuse kit personas, create synthetic bank sessions, return variables; no simulation."""
        return run(bridge.prepare_practice, brief, case_ids, style)

    return mcp


def main() -> int:
    parser = argparse.ArgumentParser(description="Freya competition-kit MCP stdio bridge")
    parser.add_argument("--workspace", type=Path, default=ROOT.parents[2])
    parser.add_argument("--kit", type=Path)
    parser.add_argument("--env-file", type=Path, help="Explicit dotenv path only; no discovery")
    parser.add_argument("--health", action="store_true", help="Print offline health JSON and exit (not MCP mode)")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)  # SDK/library logs must never contain request headers.
    try:
        cfg = Config.load(args.workspace, args.kit or args.workspace / "competition-v3" / "build-the-builder", args.env_file)
        bridge = Bridge(cfg)
    except Exception:
        print("Freya MCP configuration failed (details withheld).", file=sys.stderr)
        return 2
    try:
        if args.health:
            import json
            print(json.dumps(bridge.health(), ensure_ascii=False))
        else:
            build_server(bridge).run(transport="stdio")
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
