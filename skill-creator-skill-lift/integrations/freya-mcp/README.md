# Local Freya MCP for Build the Builder

This is a locally authored Windows stdio adapter for the Freya API and the
competition kit. **Treat the integration as unconfigured until the parent
supplies credentials to the launched process, applies configuration, reloads
Codex, and verifies tool discovery.** Packaging or successful dependency
installation alone does not expose Freya tools in an existing chat.

As of 2026-10-10, the server owner's official-domain searches and review of
the [Freya documentation index](https://docs.freyavoice.ai/llms.txt) and
[OpenAPI definition](https://docs.freyavoice.ai/api-reference/openapi.json)
did not discover an official Freya MCP endpoint. This package bridges the
documented API; it is not an official Freya MCP distribution. Route evidence
is recorded in `references/official-api-routes.json`; kit guidance is in
`competition-v3/build-the-builder/docs/api.md` under the workspace.

The runtime is installed in this integration's isolated `.venv`. All server,
launcher, packaging, and test sources are included below. Project registration
and authenticated live checks remain for the parent integration.

## Files and paths

```text
skill-creator-skill-lift/integrations/freya-mcp/
  README.md
  install.ps1
  run.ps1
  codex-mcp.toml                         # Parent-applied project snippet
  plugin/
    .agents/plugins/marketplace.json    # Optional, root is plugin/
    freya-mcp/
      plugin.json                      # Agent Plugins 1.0 manifest
      mcp.json                         # Portable stdio configuration
  requirements.txt                     # Server owner
  requirements-lock.txt                # Server owner; used when present
  freya_mcp/server.py                   # Server owner
  references/official-api-routes.json   # Server owner
  .venv/                               # Runtime installed separately
```

All commands below use these PowerShell variables:

```powershell
$freyaWorkspace = 'C:\Users\9bakl\OneDrive\Belgeler\ChatGPT\BUILD THE BUILDER'
$freyaIntegration = Join-Path $freyaWorkspace 'skill-creator-skill-lift\integrations\freya-mcp'
$freyaKit = Join-Path $freyaWorkspace 'competition-v3\build-the-builder'
```

The plugin intentionally references this checkout's absolute launcher path. It
requires the checkout and its integration `.venv`; copying the plugin alone
does not deploy the Python server. Update paths in both `codex-mcp.toml` and
`plugin/freya-mcp/mcp.json` if the checkout moves.

## Install the integration runtime

Python 3.11 or newer and Windows PowerShell are required. The agreed direct pins
in the server-owned `requirements.txt` are:

```text
mcp==1.27.1
httpx==0.28.1
python-dotenv==1.0.1
```

The exact parent runtime-install command is:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$freyaIntegration\install.ps1"
```

For a different base interpreter, append `-PythonExecutable` followed by its
absolute `python.exe` path. `install.ps1` creates or reuses only the integration's
`.venv`, checks the direct pins, and prefers `requirements-lock.txt` when it
exists. UTF-8 lock files with a BOM are supported. The script installs through
`.venv\Scripts\python.exe`, disables pip's package cache, and runs `pip check`.
It does not edit either dependency file, upgrade global packages, activate the
environment, or register anything in Codex.

If installation is blocked by network policy, the parent may retry that local
installation with permitted network access. Do not substitute global SDK
packages for this isolated environment. A partially created `.venv` is reported
for explicit repair; the installer does not delete it.

## Credentials and launcher

Authentication uses only `FREYA_API_KEY` and `FREYA_BANK_TEAM_KEY`, supplied as
process environment variables or in a caller-selected env file. The bank team
key is needed for synthetic bank practice. `FREYA_WORKSPACE_ID` is an optional,
non-secret workspace selector; set it explicitly if the API key can see several
Freya workspaces. The local filesystem workspace argument does not select a
remote Freya workspace.

Workflow and simulation JSON may contain the explicit string
`${FREYA_BANK_TEAM_KEY}`. Remote dry-run validation permits this placeholder
without a bank key because schema validation stores nothing. Saving or starting
with that placeholder requires the supplied bank key; the bridge replaces it
only in outgoing payloads, keeping source files credential-free. Exported
workflows scrub the key and report redaction. If an
export reports redaction, reinject the required credentials or restore the
explicit placeholder binding before using that export again.

`run.ps1` preserves the inherited process environment. The parent's private
DPAPI wrapper can inject credentials before launching it; this package neither
implements nor reads that private credential store. Restarting or reloading
Codex must also make those variables available to the process that actually
launches MCP. Setting variables in an unrelated PowerShell window does not
change a running desktop process's environment.

Launch stdio with:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$freyaIntegration\run.ps1" -Workspace $freyaWorkspace -Kit $freyaKit
```

For an explicit env file, append `-EnvFile` and its existing absolute path.
For example, if the parent has set `$freyaExplicitEnvPath` privately:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$freyaIntegration\run.ps1" -Workspace $freyaWorkspace -Kit $freyaKit -EnvFile $freyaExplicitEnvPath
```

Relative env-file paths are rejected. There is no `.env` discovery, secret
generation, credential persistence, or example env file. The launcher passes
the path to Python without reading the file's contents. It sets the process
working directory to the integration and invokes:

```text
.venv/Scripts/python.exe -B -m freya_mcp.server --workspace <absolute-workspace> --kit <absolute-kit> [--env-file <explicit-absolute-path>]
```

`-B` prevents Python bytecode writes to the source tree. Normal stdio mode has
no launcher banners; diagnostics go to stderr and the Python exit code is
preserved. Starting it in a terminal waits for MCP requests; it is not a health
check. For one offline JSON health result and process exit, use:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$freyaIntegration\run.ps1" -Workspace $freyaWorkspace -Kit $freyaKit -Health
```

`-Health` forwards Python's `--health`. It is a diagnostic mode, so **do not put
`-Health` or `--health` in MCP transport configuration**. Offline health does
not validate remote credentials or prove that Codex discovered the tools.

The server also supports a direct absolute `freya_mcp/server.py` entrypoint.
To use that transport instead, set `command` to the integration's absolute
`.venv/Scripts/python.exe`, set `args` to `['-B', '<absolute-server.py>',
'--workspace', '<absolute-workspace>', '--kit', '<absolute-kit>']`, and retain
the integration `cwd`. Optional `--env-file` remains explicit.

## Parent-applied project MCP configuration

Use `codex-mcp.toml` for the primary setup. The parent must merge its
`[mcp_servers.freya]` table into this trusted workspace's `.codex/config.toml`,
preserving existing settings and updating an existing `freya` table rather
than duplicating it. The snippet itself is not loaded automatically.
Codex documents project configuration and stdio `command`, `args`, `cwd`, and
`env_vars` in its [MCP guide](https://developers.openai.com/codex/mcp#stdio-servers);
project configuration loads only for trusted projects, as described in
[configuration precedence](https://developers.openai.com/codex/config-basic#configuration-precedence).

The supplied table runs `run.ps1`, sets integration `cwd`, forwards both
credential variable names and the optional workspace selector, and uses
`startup_timeout_sec = 30` and `tool_timeout_sec = 120`. For file-based auth,
append `'-EnvFile', '<explicit-absolute-path>'` to the launcher `args`; do not
put credential values in TOML. Existing parent credential-injection wrappers
may replace `command`/`args` while preserving those arguments and the working
directory.

Do not run a plain `codex mcp add` for this project setup: it writes the user
configuration and the checked CLI has no project-scope flag on that command.
After the parent merges the project table, a read-only registration check is:

```powershell
codex -C $freyaWorkspace mcp list
```

Reload or restart the target client, open a fresh chat for this workspace, and
verify that `freya_health` appears. The CLI's `/mcp` view can inspect active
servers. First call `freya_health(live=false)`. Only after credentials have been
injected, `freya_health(live=true)` can verify read-only remote workspace access.
Seeing a configured entry in `mcp list` is not an MCP handshake or API check.

## Optional local plugin and marketplace

Choose the plugin route as an alternative to the standalone
`[mcp_servers.freya]` route; enabling both launches duplicate servers.
The portable package uses root `plugin.json` and `mcp.json` with Agent Plugins
schemas, following OpenAI's
[plugin packaging guide](https://developers.openai.com/plugins/build/plugins#plugin-structure).
It contains no account connector ID, remote MCP endpoint, lifecycle hook, or
auto-install script.

The portable MCP schema has no `env_vars` or timeout fields, and restricts
`cwd` to the plugin root or another contained location. Accordingly, this
package sets `cwd = "${PLUGIN_ROOT}"`; `run.ps1` changes Python's working
directory to the integration. Ambient credential inheritance depends on the
host. For reliable auth, the parent should append `"-EnvFile"` and an explicit
absolute path to `mcp.json`'s `args`, or use its credential-injection wrapper.
The launcher supports inherited credentials unchanged. Do not insert
`${FREYA_API_KEY}` strings in portable `env`: portable expansion only recognizes
plugin path variables. See the
[Agent Plugins environment contract](https://agent-plugins.org/specification#9-environment-variables-and-placeholder-expansion).
The standalone project table is the supplied route with explicit env forwarding
and the 120-second tool timeout.

The optional catalog is `plugin/.agents/plugins/marketplace.json`. Register the
**`plugin/` directory**, not the catalog file or the `freya-mcp/` package. Its
`source.path = "./freya-mcp"` resolves from that marketplace root. OpenAI
documents this resolution in
[local plugin installation](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually).
The `ON_USE` catalog policy is install metadata; it does not obtain credentials
for this local process.

For parent-side CLI registration and installation without changing the normal
user Codex home, run this exact block only after reviewing the local package:

```powershell
$freyaMarketplaceRoot = Join-Path $freyaIntegration 'plugin'
$freyaLocalCliHome = Join-Path $freyaMarketplaceRoot '.codex-local'
$freyaPreviousCliHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
try {
    New-Item -ItemType Directory -Path $freyaLocalCliHome -Force | Out-Null
    [Environment]::SetEnvironmentVariable('CODEX_HOME', $freyaLocalCliHome, 'Process')
    codex plugin marketplace add $freyaMarketplaceRoot
    if ($LASTEXITCODE -ne 0) { throw 'Local marketplace registration failed.' }
    codex plugin add 'freya-mcp@freya-local'
    if ($LASTEXITCODE -ne 0) { throw 'Local plugin installation failed.' }
} finally {
    [Environment]::SetEnvironmentVariable('CODEX_HOME', $freyaPreviousCliHome, 'Process')
}
```

This optional block writes only the isolated CLI's config/cache under
`plugin/.codex-local`; it has not been executed by this packaging task. That
isolated installation does not install the plugin into the already-running
desktop app. Subsequent isolated CLI use needs the same `CODEX_HOME` selection.
Codex documents that state location in
[advanced configuration](https://developers.openai.com/codex/config-advanced#config-and-state-locations).

For discovery by the existing client through trusted project configuration,
the parent may instead merge these optional tables into the project config,
using this route in place of the standalone MCP table:

```toml
[marketplaces.freya-local]
source_type = 'local'
source = 'C:/Users/9bakl/OneDrive/Belgeler/ChatGPT/BUILD THE BUILDER/skill-creator-skill-lift/integrations/freya-mcp/plugin'

[plugins."freya-mcp@freya-local"]
enabled = true
```

The keys are documented in the
[Codex configuration reference](https://developers.openai.com/codex/config-reference).
Project discovery does not prove installation, authentication, or live tool
availability; verify those in the target client after reload. Keep edits in the
source package and use the host's refresh/reinstall flow for updates, followed
by tool discovery verification. Do not edit Codex's cached plugin copy.

## Implemented tool surface

The following names and defaults were read from `freya_mcp/server.py` on
2026-10-10. Tool discovery after reload remains the authoritative runtime list.

| Tool and arguments | Behavior |
| --- | --- |
| `freya_health(live=False)` | Offline configuration status; `live=True` verifies read-only workspace access. |
| `freya_list_workspaces()` | List workspaces visible to the API key; several require an explicit workspace selector. |
| `freya_list_workflows(limit=50, offset=0)` | Read one page; limit is 1..100. |
| `freya_get_workflow(workflow_id)` | Read a definition with credentials redacted. |
| `freya_validate_workflow(workflow_path, name="mcp-dry-run", remote=True)` | Remote dry run without saving; `remote=False` checks local structure, not the full platform schema. |
| `freya_save_workflow(slot, workflow_path, name="")` | Create once per stable slot or update its existing workflow; normalize the kit model and publish. |
| `freya_bind_workflow_slot(slot, workflow_id)` | Bind an existing remote workflow to a local slot, including recovery after an uncertain create. |
| `freya_update_workflow(workflow_id, workflow_path)` | Replace the entire definition and publish the newest version. |
| `freya_publish_workflow(workflow_id)` | Publish the newest version; no simulation starts. |
| `freya_export_workflow(workflow_id, filename="")` | Export under this integration's fixed `exports/` directory with secrets redacted. |
| `freya_list_personas(limit=50, offset=0)` | Read one page of personas. |
| `freya_create_personas(personas_path)` | Create personas from an array or a JSON object containing `personas`; no simulation starts. |
| `freya_list_simulations(limit=50, offset=0, status="")` | Read one page, including externally started simulations; no polling loop. |
| `freya_start_simulation(agent_id, name, variables_path, max_seconds=420, concurrency=5)` | Start one chat simulation and return its ID; refuses overlap and uses the official kit's agent/judge models. |
| `freya_simulation_status(simulation_id, adopt=False)` | Read status once; terminal states are `completed`, `failed`, `paused`. `adopt=True` recovers a known run after an uncertain start. |
| `freya_list_iterations(simulation_id)` | List a simulation's iterations. |
| `freya_get_iteration(simulation_id, iteration_id, limit=100, offset=0)` | Read one page of runs, call IDs, and judge verdicts; follow pages until `runsTotal` is covered. |
| `freya_get_call(call_id)` | Read transcripts, messages, tool calls, and workflow snapshots with secrets removed. |
| `freya_practice_cases(brief="", case_ids=None)` | Read public kit test cases offline, optionally filtered by brief A/B and case IDs. |
| `freya_create_practice_session(case_id)` | Create a synthetic bank session; requires a bank team key of at least 16 characters. |
| `freya_practice_ledger(customer_id, case_id="")` | Read the synthetic bank ledger; optional case ID runs the kit ledger scorer, separately from the judge. |
| `freya_prepare_practice(brief="", case_ids=None, style="")` | Prepare at most five cases by reusing kit personas and creating bank sessions; return variables without starting a simulation. |

Workflow save/update/publish, persona creation, bank-session preparation, and
simulation start change remote state. Verification exercised these only through
mocked HTTP, with no live publication or simulation.
Do not automatically retry a mutation whose outcome is unknown: reconcile the
workflow slot or known simulation ID first. Simulation status calls return
once; if separately authorized, space later status checks by about ten seconds.
There is no blocking simulation polling in this setup.

## Verification and current limits

Packaging checks cover PowerShell syntax, JSON/TOML structure, portable schema
constraints, matching launcher paths/arguments, and catalog containment. They
do not establish a real Codex MCP connection.

Verification completed with **all 18 tests passing: 17 mocked/config
checks and one real SDK initialize/list/offline-call smoke check**, plus a
passing `pip check` and the original kit untouched. The real smoke ran outside
the restricted Windows sandbox:
protocol `2025-11-25`, all 22 tools discovered, offline health showing
unconfigured status, public practice cases, and local workflow validation.
That smoke result establishes local SDK transport behavior, not a live Freya
connection or discovery in this chat. The API key is currently absent from the
bridge process; the parent holds it privately for later injection. The packaged
PowerShell `run.ps1` launcher also passed the real initialize/list/offline-call
smoke, recorded in `tests/smoke-result.json`. No authenticated remote check,
publication, or simulation ran during verification.
Parent credential delivery, target-client reload, and discovery of
`freya_health` are still required before calling the integration configured.

The owner traced the restricted-sandbox startup hang to Python asyncio's
Windows proactor creating a local socket pair and blocking in `socket.accept`.
The same smoke check passed with approved execution outside that sandbox.
If that specific startup issue recurs, the parent may need permission for the
Python event loop's local socket operation; this is separate from Freya API
network access. Do not interpret that hang as evidence of missing credentials
or retry workflow/simulation mutations to diagnose it.

Read-only CLI help checked on 2026-10-10: `codex --help`, `codex plugin --help`,
`codex plugin add --help`, `codex plugin marketplace add --help`, and
`codex mcp add --help`. The installed version was `codex-cli 0.162.0-alpha.2`.
That help supports `plugin marketplace add <SOURCE>` and
`plugin add PLUGIN@MARKETPLACE`; no install/register commands were executed.
