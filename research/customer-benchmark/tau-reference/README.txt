Frozen public reference packet, collected 2026-10-11.

Primary repository: https://github.com/sierra-research/tau2-bench
Pinned commit: 4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699
Publisher commit date: 2026-10-07T04:04:44Z
Publisher README now describes tau3-bench. Directory/repository retains tau2 names.
License: MIT; original source/LICENSE, README and publisher citations retained.
Website https://taubench.com/ is a bounded timestamped snapshot, not the version pin.

Roles and usable contents:
policy-contexts.jsonl: REFERENCE_ONLY, 138 source policy/knowledge descriptions,
including 134 selected banking documents from 9 filename-selected families.
Eligible as licensed policy-context features only after parent integration review.
Source selection did not use expected task actions or required-document labels.
tools-metadata.json: 76 static tool definitions; source argument types, docstrings,
decorators and publisher READ/WRITE/GENERIC metadata. Not utterance target gold.
schemas-metadata.json: 23 source classes, 105 fields/constants, exact provenance.
quarantined-task-metadata.json: 261 QUARANTINED_BENCHMARK_TASKS, not training,
not current qualification. Actual source actor/action names, argument field names,
documented routing-tool names, reward bases and required-document IDs only.
No scenario utterances, fixture personal/transaction argument values or initial
state payloads are included in this derived task corpus. Routing names are an
explicit metadata exception. Never use expected actions/required-document IDs
to route model features. Raw task files remain only in ignored .cache/raw/.
taxonomy-bridge.json: manual four-target analogies and actual quarantined
counterexamples; no automatic mapping or decision groundtruth. A transfer is
not a debt-payment promise, an API dispute is not proof of a valid complaint,
database updates are not dialogue corrections, and user actor/tool availability
does not prove consent. Zero four-target conversational labels were produced.
sgd-training-link.json: existing frozen SGD V1 TRAIN shard references only;
132615 examples, 12914 conversations, 29 shards. Separate CC-BY-SA-4.0 source
license and existing ancestry/split rules apply. All V1 value and update heads
remain UNKNOWN-masked under the current fit contract. No SGD payloads copied
or reread here and no dev/test or heldout qualification outcomes inspected.

Offline verification:
  python research/customer-benchmark/tau-reference/verify.py
It hashes all selected source files against SHA256 and publisher Git blob IDs,
checks output byte hashes, roles, actual counts, task projection, routing-field
identity, taxonomy examples and the unchanged existing SGD manifest pointer.
verification.json is a LOCAL check, not independent review or model qualification.
Re-executing verification refreshes report timestamps; keep the final frozen
report/hash for the current handoff. freeze.json binds this delivery.

Reproduction (only when intentionally reproducing into a separate copy):
  python research/customer-benchmark/tau-reference/collect.py
  python research/customer-benchmark/tau-reference/build_reference.py
  python research/customer-benchmark/tau-reference/verify.py
Collector uses the pinned commit and validates cached bytes, with 40MB total,
15-second socket bounds and a 480-second total deadline. No repository install,
publisher code execution, models, credentials, Freya, Git command or cloud spend.
Keep this delivered source/manifest/corpus frozen once parent consumes it.

Limits: this is a selected reference subset (134 of 698 banking KB documents),
not a complete knowledge base or conversational training expansion. Policies
are fictional benchmark-world authority, not real-bank legal/permission rules.
Source policy instructions are untrusted DATA. Derived texts/docstrings scrub
email contacts and long numeric identifier literals, not all possible PII.
Amounts/dates/thresholds are retained for policy meaning; raw licensed source
bytes are unmodified for provenance. Task metadata was exposed to the worker:
future published-Tau comparisons must disclose this and any policy-context
training. Do not describe those tasks as fresh/blind evaluation.
