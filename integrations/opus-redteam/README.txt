Exact external Claude Opus 5.5 red-team launcher

This launcher is a different model's orchestration code. It never claims to be
Opus, creates substitute attacks, uses a different model, or performs bank/Freya
calls. A source review is not a reproduced attack or an executed workflow test.

Current verified state (2026-10-10):
- Official Anthropic API ID is claude-opus-5-5.
- Native official Claude Code 2.1.296 exists. Its checksum matched the official
  win32-x64 release manifest; native auth status was loggedIn=false/authMethod=none.
  The direct exact-model invocation could not authenticate.
- The designated loopback CLIProxy accepted its DPAPI key and returned 11 model
  IDs, with no Claude/Opus IDs. Auth on this route works; model routing is the gap.
- ONE explicitly authorized tools-disabled tiny completion used the exact ID,
  max_tokens=32, prompt="Reply ready", a 30-second whole-process deadline, and
  no fallback despite the inventory omission. HTTP 502, server_error,
  internal_server_error; sanitized classification unknown_provider_for_requested_model.
  No actual Opus inference or red-team attacks were obtained.
- A read-only check of documented config key names and designated auth-directory
  filename metadata found no claude-api-key/OpenAI-compatible section, no OAuth
  alias/exclusion section, and two Codex-named JSON files. No auth file was opened,
  token contents inspected, login started, service restarted, or proxy config edited.
  This describes only the designated provider; it is not a claim that the user's
  Claude authentication is absent elsewhere. Further auth checks are stopped
  pending the user's async configuration reply.

Commands from fraya root:
  python -B integrations/opus-redteam/run.py prepare
  python -B integrations/opus-redteam/run.py run --provider auto --timeout-seconds 420
  python -B integrations/opus-redteam/run.py run --provider local-proxy --timeout-seconds 420
  python -B integrations/opus-redteam/run.py run --provider claude-cli --timeout-seconds 420
  python -B -m unittest discover -s integrations/opus-redteam/tests -v

The optional explicit tiny probe is separate from automatic red-team launches:
  python -B integrations/opus-redteam/run.py probe --timeout-seconds 30
Do not repeat it automatically. The requested single probe has already completed.

Candidate discovery prefers builder-rd-a-v4, then v3, v2, then builder-rd-a.
Complete workflow JSON files (including workflow-N.json) and schema-valid policy.json
are snapshotted. Partial model streams, traces and gap reviews are not candidates.
Policy IR alone permits rule-level review; it never establishes an executable
workflow. Discovery is refreshed before every full run; the parent owns live
workflow generation/testing. This launcher does not modify candidate files.

Every full launch snapshots original briefs A/B, official runtime docs, OpenAPI,
13 official cases, builder_prompts.py, policy_runtime.py, and available complete
candidates. It records hashes, exact canonical clause IDs, and numbered source
lines. The model must produce 15 distinct attacks with synthetic scenarios,
ordered turns, expected ledger and speech, forbidden operations from OpenAPI,
qualified source IDs, plausible failure paths and precise fix targets. Required
focus covers corrections, stale fields, late transfer/no notes, identity,
dishonesty/injection, SMS/goodbye ordering and partial commitments.

Native CLI safeguards: no built-in tools, strict empty MCP, denied permissions,
safe/restricted mode, no hooks/slash commands/session persistence, no fallback.
Actual assistant message model and exclusive modelUsage must both match the exact
ID. An initialization model label does not count as inference.

Proxy safeguards: only the designated nonsecret metadata and DPAPI file are used.
The existing scripts/freya_dpapi_server.py unprotect function is imported, but its
Freya credential injection/main functions are never called. Decryption occurs
only inside the short-lived request process; no plaintext key is saved or printed.
CPython strings do not guarantee secure memory erasure. The child process ends
after its result. Ambient proxies and redirects are disabled. Tools=[] and
tool_choice=none; parent termination bounds the entire request to 300–480 seconds.
Raw error bodies, authorization headers and stderr are not published.

Full proxy review requires live inventory advertising the exact ID plus independently
inspected upstream route provenance. CLIProxyAPI can rewrite response model fields,
so a response label alone cannot establish actual upstream identity. The designated
nonsecret metadata may supply provenance.exact_model_route:
  requested_model: claude-opus-5-5
  upstream_model: claude-opus-5-5
  provider: claude (or anthropic)
  mapping_verified: true
  fallback_disabled: true
  evidence: nonempty list of nonsecret supported configuration/provider evidence
The provider owner must establish this evidence; do not fabricate it to pass a gate.
The response model must also be exact, finish normally, and contain no tool calls.

Reports: analysis/opus-redteam.json and analysis/opus-redteam.txt.
Source manifest: integrations/opus-redteam/source-manifest.json.
Input/source snapshots, model streams and verified raw review are in ignored runtime/.
The preexisting official-install.ps1 was not modified or executed by this task.

Primary documentation:
https://platform.claude.com/docs/en/models/opus-5-5/overview
https://code.claude.com/docs/en/cli-reference
https://code.claude.com/docs/en/authentication
https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/transport/subprocess_cli.py
https://github.com/router-for-me/CLIProxyAPI
https://github.com/router-for-me/CLIProxyAPI/blob/main/sdk/cliproxy/auth/response_model_rewriter.go

Validation: 17 synthetic transport/security tests pass. They verify exact identity,
no initialization-only inference, no mixed-model usage, no tools/MCP, no unverified
alias or fallback, no truncated response, no raw provider-error credential leakage,
inventory preflight isolation, the explicit one-call probe, redirect rejection,
and whole-process timeout termination. These are launcher tests, not Opus reviews.
