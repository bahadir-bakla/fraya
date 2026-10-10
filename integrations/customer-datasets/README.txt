Customer dataset adapters — local conversation planning only
Verified 2026-10-10. Python 3.11+, standard library only.

From the canonical fraya repository:
  python integrations/customer-datasets/adapter.py
  python integrations/customer-datasets/adapter.py --offline
  python -m unittest discover -s integrations/customer-datasets -p test_adapter.py -v

The first command fetches only two pinned publisher data files and their
license notices. No authentication, package installation, dataset loader,
archive extraction or remote code execution. Each file has an immutable
40-character commit URL and SHA-256 in sources.json. Downloads are capped at
20 MB per file, checked before writing, and existing cache files are checked
again. The default is 25 scenarios per dataset; --limit accepts 1..25 (50 total).
Both actual-data tests skip on a clean checkout until downloads are present;
the other ten tests require no network. A changed publisher payload or corrupt
cache fails closed rather than silently updating the pin.

Inputs:
  Banking77 test.csv: 239,961 bytes; 3,080 single-turn queries; 77 intent labels.
  Taskmaster-3 data_00.json: 15,832,328 bytes; 1,188 multi-turn dialogs.
  License notices: PolyAI LICENSE and Google's TM-3-2020/README.md.
Exact URLs, revision, hashes, creator credits and license URLs: sources.json.
Both publishers explicitly release these datasets under CC-BY-4.0.

Output: cache/scenarios.json, ignored by this subtree's .gitignore.
The full raw datasets and notices remain in ignored cache/*.data. There is no
vendored raw dataset or consumer narrative in tracked files. validation.txt
contains reproducible aggregate results and the scenario artifact hash.

Schema boundaries:
  provenance: immutable download URL/hash, revision, attribution, license,
              license terms URL and adaptation notice.
  source_facts: record locator, SOURCE taxonomy label, original turn ordering
                and roles, annotation counts, empty-turn count, lexical cue
                names with source turn index and original utterance hash.
  synthetic_plan: generic local user-turn sketches, explicitly synthetic;
                  expected_outputs=[], policy_mapping=null.
  oracle_scope=conversation_only; execution_status=not_executed.

No utterance text, API arguments/responses, worker instructions, account
details or customer entities are exported. API counts are historical publisher
annotations, not evidence of an executed Freya action. Taxonomy labels remain
source facts only and never become bank policy, expected results or executable
instructions. No brief/API mapping was supplied; these files are independent
planning inputs, not the builder's native scenario schema or a bank oracle.
Applying these plans to bank tests requires a supplied brief/API, fixture
facts and a validated expected outcome; this adapter does not provide them.

Conversation features are conservative lexical heuristics: correction terms,
wait/hold terms, politeness terms and question marks in USER turns only.
Each observation includes its evidence turn and a hash, permitting local audit
without copying text. "Sorry" can be apology rather than correction; "wait"
can refer to service delay. These are candidate cues, not verified repairs,
emotions, audio interruptions or timing measurements. Synthetic sketches do
not replay original dialogue content, exact turn count or chronology.

Sampling is deterministic sorted taxonomy/feature-bucket round-robin, with
original row order inside a bucket. Banking77 buckets use only intent labels:
default selection covers the first 25 sorted labels out of 77, not all intents.
Taskmaster buckets use observed cue combinations within the movie-ticket
vertical. This gives linguistic variety, not a random or statistically
representative population sample. Only shard 00 is ingested, not all TM-3.
The shard contains three empty utterances; parser preserves their positions.
No timing or user barge-in evidence is inferred from turn adjacency.

Attribution and distribution:
  Banking77: PolyAI; Casanueva et al. (2020), Efficient Intent Detection with
  Dual Sentence Encoders: https://arxiv.org/abs/2003.04807
  Taskmaster-3 / TicketTalk: Bill Byrne, Karthik Krishnamoorthi, Saravanan
  Ganesh, Google LLC. Publisher copyright/license notice is pinned below:
  https://github.com/google-research-datasets/Taskmaster/blob/d92cb6af3005f1dc09c39e75e7daf4a04905e00b/TM-3-2020/README.md
  License terms: https://creativecommons.org/licenses/by/4.0/
  Original PolyAI license text (including warranty disclaimer):
  https://github.com/PolyAI-LDN/task-specific-datasets/blob/57ec275d8078af65b7731c2a98be812d844a6d6b/LICENSE

If distributing source material or adaptations, retain creator credits,
copyright/license notices, source links, disclaimer link and modification
notices. Generated provenance carries these references and the transformation
notice. CC-BY does not guarantee privacy or accuracy. Local ignored cache is
not a redistribution package; inspect any proposed export before shipping.
Neither historical movie availability nor source banking intents establishes
current Freya business rules. Banking77's official test split is used only
for this planning experiment; do not mix it into training and later claim
an uncontaminated BANKING77 test score.

Research covering six candidates: ../../research/customer-datasets.txt
No hosted simulation, git commit or push was performed.

The initial ingestion above remains conversation-only. A separate subsequent
benchmark compiler now supplies kit-v3 policy/fixture mapping without changing
this ingestion module or the official kit: benchmark_adapter.py. Its tracked
pack has 362 independent local fixtures and 117 immutable public delivery
variants. See ../../research/customer-benchmark/README.txt for exact boundaries,
reference checks, source hashes, negative controls and the explicit hosted runner.
