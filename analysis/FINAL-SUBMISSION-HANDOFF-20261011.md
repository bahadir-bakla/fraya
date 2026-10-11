# Final case handoff — 11 October 2026

Deadline: **20:00 UTC / 23:00 Istanbul**. This is final-case preparation, not a claim that the final workflow has been generated or tested.

## Completed and verified

- Friend's `origin/blend-13` work was merged with the existing MiniLM/classic builder. Checkpoint `5f6f99486e5c88c289305ae8a9f52f92f049b2e1` is on `origin/codex/builder-rd`.
- All 19 ZIP files were extracted without edits. The latest local comparison found 19/19 byte-identical; ZIP SHA256 `4c7d4c22db0daa1d90a39547fccf56aec768acd5b2052be78de9314fd49c5dce`.
- `final-bank-mock/` implements all seven bank service paths. Local tests passed 22/22, including all 617 fixture responses, HTTP statuses and the 12-second delayed balance response. Independent review exercised another 505 request/error cases.
- The current bank source audit contains 72 rules and 16 conflicts with provenance. The source pack, rather than prior payment-collection examples, controls the final domain and IVR entry boundary.
- Real native `claude-opus-5-5` ran an independent bounded review: 126.406 seconds, actual model and usage saved in `final-case-redteam.native.json`. It produced 34 adversarial source contracts. This was source/mock review, not an audit of a generated final candidate.
- Twelve source-grounded scenarios (six supplied examples and six new hard cases) passed 68 condition checks and 14 parser probes. Their personas have been created on Freya; actual returned IDs are bound in `final-case-persona-variables.json`.
- The merged builder and generic folder adapter passed 207 source tests, with two intentional skips. The independent packager passed another 32 tests (three successful packages and 29 rejection cases). The latest share snapshot passed 3357-file credential checks. Both ZIPs remain intact: final 19/19 and practice v3 16/16.

## Immediate blocker

Wrangler has no authenticated Cloudflare session. No final-case Worker has been deployed and no public mock URL is known. The final BRIEF explicitly requires deploying the mock **before** running the builder. Consequently no formal final builder run or final platform simulation has started. Previously exported practice workflow `98e91cbf-f611-4b3d-b18e-b667e9c65f68` is a reference only.

The user can approve a fresh bounded Cloudflare device login, or the teammate can provide the team's already deployed final mock URL. Do not substitute the organizer's practice mock. Temporary unclaimed deployments expire after 60 minutes and do not satisfy the requirement to keep the mock alive until results.

## Sequence once the team's mock is available

1. Authenticate Wrangler and deploy `final-bank-mock` to the team's Cloudflare account. Keep the Worker running until results are announced.
2. Run `node scripts/verify-http.mjs https://ACTUAL-WORKER.workers.dev` from `final-bank-mock`. Record the real URL and actual HTTP verification results.
3. Run the existing generic folder adapter against the immutable case folder. It checks mock health before launching, extracts all source documents with hashes and expands local OpenAPI references without changing request fields. The shared builder contains no case-specific customer, amount or policy constants.

```powershell
python -X utf8 -B competition/build_case_folder.py "{case_folder}" --tool-api final-bank-mock/openapi.json --mock-url https://ACTUAL-WORKER.workers.dev --slot final-case --minutes 25 --local-only --semantic-assist off --finetuned-assist off --live-layer off
```

This final domain differs from the earlier payment-promise classifier. The explicit switches preserve a reproducible classic run and prevent old financial classifier assumptions from silently entering the final agent. The classic and learned practice versions remain available for comparison.

4. Audit the automatically generated candidate, validate and publish to a stable final slot. Record source workflow SHA, actual agent/workflow/version, actual platform export SHA and public mock URL. Never hand-edit candidate JSON; repairs go through generic builder changes and a fresh bounded automatic run.
5. Test the bound final personas, with a single active workspace simulation and at most five calls at once. Local batches are 5+5+2. Judge verdicts, actual API bodies, receipts, transcripts and published version must support reported outcomes; offline scenario QA is not a platform pass.
6. Package the actual completed run, unmodified platform export and full coding-agent JSONL session logs. Team name and members' names/emails still require the user's actual values. Commit/push completed artifacts without forcing or replacing the teammate's history. Prepare `submission.json`, the exported workflow and the full builder trace for the user's email reply.

## Honest coverage limits

The source audit flags unresolved policy conflicts; expectations were not altered to pass. No hidden tests were accessed. Text simulation does not demonstrate real speech, ASR or accent performance. No final hosted score or trained-model improvement is claimed by this preparation checkpoint.
