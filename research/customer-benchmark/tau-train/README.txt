Tau official TRAIN bridge, commit 4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699
dated 2026-10-07T04:04:44Z. MIT License; see source/LICENSE and NOTICE.txt.
Source repository: https://github.com/sierra-research/tau2-bench

The earlier tau-reference delivery did not inspect official train/test partition
files and therefore packaged every task as quarantined reference metadata.
This NEW delivery inspects the actual pinned partition files and gym code.
Airline has 30 official TRAIN / 20 TEST tasks; retail has 74 TRAIN / 40 TEST.
base is their union, not a training split. Banking has no official TRAIN task
partition; its loader documents that task_split_name is unused, and its registry
registration has no split loader. No banking task split has been invented.
Its licensed full knowledge corpus is available for policy-source pretraining.
Prior tau-reference files remain unchanged, including all261 task metadata.

Ready files:
train-policy-contexts.jsonl: 716 actual source-text pretraining chunks from all
698 banking knowledge documents plus airline/retail/banking policy headers.
Source-domain auxiliary target is a publisher document domain, with mask true.
All promise/dispute/correction/permission labels are UNKNOWN (value null, mask
false). This corpus is source-policy text, not human conversation or permission
gold. All chunks of a document retain one group_root; no invented IID split.
policy-contexts.jsonl: 701 complete redacted source-context records with hashes.
train-scenario-specs.jsonl: 103 retained official TRAIN simulator specifications
(30 airline,73 retail). Includes original instruction structure after declared
privacy transformations, provenance and exact source task hashes. Instructions
are generation conditioning, never an observed utterance/runtime dialogue input.
No observed conversation history or generated trace exists in this delivery.
Scenario variants/generated traces must inherit the same source group root.
train-publisher-action-annotations.jsonl: 103 offline annotation records,448
publisher reference-action name/actor/argument-field metadata. No argument values.
These are annotation-only, never runtime features or independent human act gold.
partition-and-closure.json: official IDs and exact/delexicalized core closure
metadata across TRAIN/TEST. One retail TRAIN scenario (93) was excluded because
its component overlaps TEST. Test instructions/action labels are not exported.
Template closure is a declared heuristic, not proof of all semantic duplicates.
schema-and-feature-contract.json: financial and independent semantic masks,
explicit runtime allowlist, and exclusion of simulator/gym oracle metadata.
Gym code returns actual observations but its info also includes full task and
simulation state. Project only public policy/tools; never encode info.task or
info.simulation_run. Golden retrieval/required-document or expected-action fields
cannot be used for model feature routing.

CPU consumer:
  python research/customer-benchmark/tau-train/batches.py
  from batches import iter_policy_batches, iter_train_scenario_specs
Default batches yield716 policy rows in12 batches of64, final batch12. Only source
reference_text enters policy features. Typed bounds reject bool/floats/nonpositive
batch sizes and sizes above512. File bytes and row counts are rechecked against
the pinned manifest on every stream, with no cached index reuse.

Reproduction/verification in this repository layout:
  python research/customer-benchmark/tau-train/collect.py
  python research/customer-benchmark/tau-train/process.py
  python research/customer-benchmark/tau-train/verify.py
Requires the preserved tau-reference pin/tree inventory and frozen metadata
pointers. Collector verifies/restores selected pinned official files (10MB byte
budget,15-second sockets,240-second deadline), preserving an existing matching
source manifest's provenance bytes. It installs/executes no publisher code.
Only our processor/consumer are imported for local checks. Mixed official raw
task aggregate files are kept in ignored .cache/; derived TRAIN excludes TEST.
Verification replays the processor byte-for-byte, checks source blobs, partitions,
closure, UNKNOWN masks, batches and current-oracle mutations. Report timestamp
updates on a new verification run; preserve this handoff's freeze/report hashes.

Existing SGD132615 TRAIN examples remain linked and unchanged, with V1 value and
update heads UNKNOWN-masked. These supply actual observed multi-turn publisher
training; Tau adds policy contexts and official TRAIN synthetic scenario seeds.
No model fit, rollouts, Freya, Git, auth/key access, cloud or spend occurred here.
Gym DB/install/simulator dependencies were not collected; these scenario specs
are generation seeds, not a self-contained executable Gym environment. Identity
fields are suppressed and obvious contacts/IDs scrubbed, requiring explicit mock
fixture binding for any future simulator. This is not universal PII clearance.
Financial decisions still require independent semantic supervision. Published
task metadata was exposed earlier: future Tau results must disclose training and
exposure; do not call the benchmark fresh/blind. No qualification rows produced.
