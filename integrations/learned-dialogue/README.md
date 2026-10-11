# Learned dialogue CPU prototype v1

This is an actual trained four-head sparse softmax classifier, fitted on 52
fictional English turns with word unigram/bigram and character trigram features.
It proposes primary/secondary intent, whole-utterance completion, and unresolved
component category. It has no permission kernel, bank adapter or tool executor.
No live workflow, guide, current candidate, platform simulation or existing kit
file was changed. No external inference, GPU rental, installation or commit.

From the repository root, using the existing interpreter:

```powershell
.\skill-creator-skill-lift\.venv\Scripts\python.exe -X utf8 -B integrations/learned-dialogue/cli.py "Please call me back later about this fictional account."
.\skill-creator-skill-lift\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s integrations/learned-dialogue -p "test_*.py" -v
```

`predict(input_snapshot, model_bundle)` is pure. Required snapshot fields are
utterance, turn_id, state_revision, policy_hash and raw_text_provenance. The
output binds the turn/state/policy and exact input SHA256, contains a four-field
candidate, raw-head scores, abstention reasons and conservative component spans.
`validation.validate_proposal` rejects stale bindings, text mismatch, malformed
spans and authority/tool fields. Caller rejection/exception must mean abstention;
it must never relax an external deterministic guard.

V1 only accepts local synthetic provenance for offline proposals. Every output
is research_only. An extracted text copy is untrusted; documentation does not
establish a trusted raw latest-user text binding. V1 has no learned target,
amount/date/security completeness, polarity, correction-scope or consent heads.
Detected value spans stay ambiguous/unfinished, targets stay unresolved and
consent stays unassessed. No canonical values are emitted. Scores refer to the
raw learned heads before conservative guard overrides, not correctness odds.

`authoring.py` declares all utterances and labels before fitting. `build_data.py`
freezes label-free records and a separate oracle, plus manifests/provenance.
It verifies the existing cached Banking77 bytes and official license notice.
Existing differing outputs are rejected. No augmentation is used. Shared
semantic-template, source and scenario-family keys, normalized duplicate text,
and augmentation ancestors cannot cross a split. Authoring is by the same Sol
process across all packs; renamed packs and related carrier phrases do not
establish independently authored or difficult OOD data. These are pre-fit
synthetic labels independent of predictions, not independently adjudicated gold.

Banking77: PolyAI; Casanueva et al. (2020), *Efficient Intent Detection with Dual
Sentence Encoders*, https://arxiv.org/abs/2003.04807. Four samples from the pinned
official test.csv supply linguistic inspiration in TRAIN ONLY. No raw source
utterance is saved in this pack. Fictional wording and facts replace originals.
Original license: CC BY 4.0,
https://github.com/PolyAI-LDN/task-specific-datasets/blob/57ec275d8078af65b7731c2a98be812d844a6d6b/LICENSE.
Terms/disclaimer: https://creativecommons.org/licenses/by/4.0/.
Source labels do not prove bank policy correctness. This is no BANKING77 score.

Original frozen evidence is in `analysis/night-learned-dialogue.train.json` and
`.eval.json`. Holdout: 22 turns, raw joint exact 10/22 (45.45%), accepted 4/22
(18.18%), accepted errors 0/4, uncertain abstentions 13/13. Two-sided row Wilson
95% upper error is 48.99%; these are exploratory rows, not a group qualification.
Train joint 52/52 is resubstitution. The same 22 calibration turns fit temperature
and select threshold 0.8; calibration results are optimistic. The training CLI
refuses to overwrite v1. Further versions require new datasets and manifests,
separate calibration-fit/risk/confirmation groups and independent annotations.

`diagnostics.py` writes separate observational controls and smoke evidence.
Guard-only uncertainty recall is 10/13; learned-only at the same threshold accepts
4/22 without error; shuffled TRAIN labels yield raw joint 2/22 and one accepted
error. These reuse the already inspected holdout and are not unseen results.

`export_runtime.py` emits a standalone research module using only json/re and
builtins. Shared feature indices and lossless binary64 storage reduce the source
to 357,336 bytes. Runtime receives a trusted upstream input_sha256; local wrapper
verification remains required. All 96 decisions match; numerical differences
are <=2.23e-16. Separate globals/locals execution passes locally. This establishes
no Freya sandbox support, competition eligibility, trusted input or live latency.
Kit README fixes AGENT_LLM and limits agent calls to bank API; code/hooks are
allowed, but supplementary learned inference needs its own eligibility review.

The designer's `analysis/learned-layer-design.*`, label spec and evaluation plan
define V2. Priorities: context-conditioned short replies and exact spoken-offer
identity; independent completion/polarity/correction dimensions; multilabel
administrative acts; masked unsupported heads; component/target evidence; separate
calibration roles. V1 negation/correction abstention is deliberately conservative
and semantically incomplete, including complete stop requests.
