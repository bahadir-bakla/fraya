Narrow-v3 offline Modal adapter. Parent is the only launch/cancel owner.

Protocol: modal_narrow_runner.prepare(train,packet,reviews,parent_review_authorization,
model_manifest,dev,source_manifest,lineage_overlay) -> exact TRAIN-only JSON bytes.
No annotation or source data is rewritten. The old81-row packet stays immutable.
R2 source view uses actual targets[].index and nested pending components. It
does not embed target indices, product IDs/labels, revisions, canonical pending
values or oracle spans. Relative current-question/sibling relationships retain
which typed statuses belong together; target renaming/permutation tested.
Review rows must include privacy_review.whole_turn_and_question_nonsecurity_value_free
and no_account_identifiers true plus parent_evidence_sha256. This is an explicit
independently checked dataset exclusion gate, not a deployed redactor. Security
turns or unknown secret isolation are excluded before text hashing/encoding.
Lexical digits are delexed BEFORE typed context serialization; original Unicode
source segments remain provenance metadata. Presence features are explicitly
present_unqualified, never asserted freshness or caller-source authentication.
Checkpoint05 canonical closure needs82rows including CSv2-E-0073. Every closure
member needs two independently verified blind non-author annotations and final
parent adjudication or a reviewed ambiguity mask. A partly exposed original
audit is not a second blind annotation. The overlay must contain complete train
AND dev group maps, transitive canonical roots, source hashes and axes version.
Parent authorization pins exact packet/reviews/source-manifest/overlay hashes
and reviewer identity/exposure evidence. Disagreements require a third independent
adjudicator. Adapter uses the user's strict >20 positive groups (=21) and >=20
additional negative groups; designer engineering floor20 is not weakened to
make current18 pass. Union counts and train/dev intersection are checked first.

prepare CLI (local only; rejects current insufficient review/gates):
python -B integrations/learned-dialogue/modal_narrow_runner.py --prepare
  --train <frozen-train.json> --dev <frozen-dev.json>
  --source-manifest <frozen-manifest.json> --lineage-overlay <parent-overlay.json>
  --packet <unchanged-review-packet.json> --reviews <closure-reviewed.json>
  --review-authorization <parent-review-authorization.json>
  --payload <NEW-narrow-payload.json>

Default dry-run:
python -B integrations/learned-dialogue/modal_narrow_runner.py
  --payload <narrow-payload.json> --budget <parent-global-budget.json>
  --grant <parent-launch-grant.json>

The grant must bind payload_sha256 and canonical budget_snapshot_sha256; profile
businessforever2338; reservation_id for a parent-authorized >=$10 active global
reservation; mode smoke|primary, compute_seconds<=120|1800; startup_seconds240;
shutdown_seconds60; automatic_retries0; gpuH100; invocation_ordinal1..3;
cloud_stop_utc2026-10-11T06:13:01Z; verified effective resource rate at least the
extra-conservative posted H200+2CPU+16GiB envelope; build/storage/egress reserve>=1.
Required true flags: parent_authorized_launch, reviewed_data_gate,
independent_annotations_verified, parent_adjudication_verified,
effective_rates_verified, sdk_and_stop_capabilities_verified,
independent_watchdog_armed, dependency_image_reviewed,
gpu_benefit_over_cpu_verified, canonical_lineage_closure_verified,
reviewed_dev_frozen, sparse_cpu_and_phase_controls_complete,
v3_source_reference_controls_passed, actual_detector_false_candidate_audit_passed.
JSON is parent evidence, not cryptographic authentication. Parent must serialize
the ledger transaction and independently verify these assertions. This utility
never writes the global ledger or profile. Current grant/gates are absent.

Parent only, after all gates: add --parent-launch --ids <NEW-id.json>
--result <NEW-result.json> to the default command. The supervisor bounds total
wall before image building/scheduling, starts one child, and cancels by deadline.
Child saves exact ap-ID before spawn and fc-ID immediately after. It never
detaches, resubmits, retries, deploys, or schedules. Independent external parent
watchdog remains mandatory: no local process can guarantee cloud cancellation
during machine/network loss. If app ID was not recovered during image startup,
NO verified stop is claimed and reservation remains held for parent recovery.

Parent recovery only:
python -B integrations/learned-dialogue/modal_narrow_runner.py
  --parent-cancel --app-id ap-EXACTID --call-id fc-EXACTID
Uses installed SDK FunctionCall.cancel(terminate_containers=True), then documented
python -m modal app stop --yes ap-EXACTID, then independent CLI app-list JSON
observation state=stopped/tasks=0. Missing/unknown/stopping or timeout means no
verified stop. Reservation release requires parent billing reconciliation.
SDK1.5.1 has no App.stop method. Authenticated remote cancel not tested here.

TRAIN payload <=1MB/512rows, exact field and row-hash allowlist; no dev, holdout,
oracle spans, qualification, real-customer rows or whole local directory upload.
Remote repeats byte/hash/contract checks BEFORE importing Torch/downloading E5.
Minimal phase/question/target-scoped pending context, IDs excluded as features;
numbers delexicalized. Security turns require a separately reviewed value-redaction
overlay and are rejected currently. Caller metadata never authenticates Freya raw.

Image explicitly adds only core.py,teacher.py,app.py and public model manifest.
Automatic source discovery false, no secrets/volumes/network filesystem/endpoints.
Pins Torch2.11.0,Transformers5.3.0,safetensors0.8.0rc0,huggingface-hub1.7.1;
published versions checked on official PyPI, cloud image build not exercised.
One H100 with automatic H200 upgrade billed at SAME H100 GPU price (official
https://modal.com/docs/guide/gpu). Higher H200 reservation is contingency only.
CPU hard2, memory hard16GiB, process VRAM24GiB, ephemeral disk2GiB. Compute
120smoke/1800primary, startup240, shutdown60; zero retries; single-use container;
function timeout excludes scheduling and resets per attempt, hence total-wall
supervisor/external watchdog mandatory (https://modal.com/docs/guide/timeouts).

Pinned E5 revision614241f622f53c4eeff9890bdc4f31cfecc418b3. Official model card
declares MIT, origin intfloat initialized from Microsoft's Multilingual-MiniLM;
no separate LICENSE file in this revision. Manifest pins actual metadata hashes
and official LFS weight/tokenizer SHA256. No weights downloaded here. Frozen
encoder produces384-dim mean-pooled normalized embeddings; logistic binary head
uses equal canonical-group weight with members sharing group mass. Token cap256
rejects overflow; no suffix truncation. Current hypothesis disallows fine-tuning.
TRAIN-only finite LOGITS carry exact row/group/payload bindings, never replace gold;
probabilities are diagnostic only and may saturate, hence not inverted for KD.
Student (1-alpha)CE+alpha*T^2*KL, T2/alpha.25 fixed, alpha0 gold-only comparator.
No dev-driven alpha sweep. Optional export uses json/re+builtins and remains an
abstaining diagnostic sidecar; no new wire fields, values, consent or permission.

CPU first: modal_narrow_cpu_trial.py --cache <already-pinned-public-cache>
only inspects readiness by default. Parent may --parent-measure with admitted
--payload and new --result, maximum300seconds, no weight download. Full-corpus
encoding+head fit under300s recommends CPU/skip GPU. Pinned weights currently
absent; no speed/accuracy/cost advantage is claimed. Model-card benchmarks do
not prove these dialogue labels or bank policy correctness.

Tests: python -B integrations/learned-dialogue/modal_narrow_tests.py
Freeze handoff: system Python -B integrations/learned-dialogue/modal_narrow_checkpoint.py
Tests use in-memory invented protocol fixtures, not independently reviewed gold.
No actual teacher or student trained on the research dataset in this checkpoint.
