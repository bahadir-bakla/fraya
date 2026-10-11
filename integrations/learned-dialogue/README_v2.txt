Context sparse CPU prototype v2

Runtime interface:
  predict_v2(input_snapshot, model_bundle, binding_context) -> semantic_proposal.v1
  BindingContext(authoritative_binding, model_id)
  authoritative_binding = {turn_id, state_revision, policy_hash, api_hash}
  model_bundle = {model_id: SHA256 of exact saved model bytes, model: decoded JSON}

Only a separately verified caller adapter may bind authenticated raw current-turn
text and current kernel state. Constructing BindingContext or setting source to
trusted_turn does not authenticate anything. Authored fixtures and saved structured
replays are offline evidence. Freya documents conversation template placeholders,
but an authenticated code ingress is unqualified. No transcript API is introduced.

Generated export interface:
  predict_context_embedded(input_snapshot, authoritative_binding)
It uses json/re plus builtins only and is capped at 500000 actual UTF-8 bytes and
100000 coefficients. Export source and model hashes are verified offline by the
wrapper; the generated runtime does not import hashlib. Pure inference emits no
tools, permissions, bank state patches, canonical amount/date, or policy values.

Current wire is frozen designer semantic_proposal.v1 (contract_v2.json). All heads
are uncalibrated/unqualified and every output abstains. Primary and secondary
scores are raw marginal diagnostics, never joint probabilities. Component score
is a placeholder, not joint confidence. Component evidence uses exact half-open
Python Unicode codepoint offsets into the supplied raw turn. Missing input,
stale revisions, malformed models and candidate/qualifier overflow fail closed.
No binding means InputRejected, never fabricated policy/API/model hashes.

CPU trainable heads: primary multiclass, secondary multilabel binary, independent
component completion/polarity, correction kind, target scope. Completion/polarity
are shared across components with a component feature. Missing reviewed masks,
absent/no-evidence components, discontinuous spans and multi-clause target scope
are masked. Clause segmentation, target identity ranking, offer ranking, consent,
recipient/allocation and span detection are not trained; dependent frames stay
unqualified. Lexical candidates are English-only hints, not absence detection.
Qualifiers do not mechanically replace primary intent with unknown. Multiple
candidates retain all raw spans with ambiguous completion and unknown polarity.

Offer acceptance can reference only the exact unsuperseded spoken_offer_id.
Readback affirmation can reference only active_readback.readback_id with its
revision and completed-speech validity checked. This is descriptive; deterministic
guards retain authority. Deferred refusal revision checking never patches state.

Worker data is read-only. The loader projects literal labels/frame values and
explicit masks; frame scores/status are never training targets. Single-author
proposals use weight .2; independently adjudicated evidence is not inferred from
another task authoring the files. All source bytes are pinned and checked before
and after fit; changes refuse to save results. No calibration/risk/qualification
files or v1 holdout are loaded by v2. Train/dev metrics are exploratory. Declared
lineage/template/source/scenario checks cannot prove IID or latent sibling freedom.

Commands from repository root (existing local Python; no installation):
  .\skill-creator-skill-lift\.venv\Scripts\python.exe -B integrations/learned-dialogue/train_v2.py
  .\skill-creator-skill-lift\.venv\Scripts\python.exe -B integrations/learned-dialogue/export_v2.py
  .\skill-creator-skill-lift\.venv\Scripts\python.exe -B integrations/learned-dialogue/controls_v2.py
  .\skill-creator-skill-lift\.venv\Scripts\python.exe -B integrations/learned-dialogue/checkpoint_v2.py

V1 archive, labels, model and metrics remain byte-for-byte frozen. Separate v2
artifacts never turn exposed v1 results into fresh unseen evidence. No GAN.

Modal adapter is read-only planning only; there is no remote-launch implementation.
Automatic H100->H200 upgrades retain H100 GPU billing according to Modal GPU docs;
the maximum posted H100/H200 rate is an extra conservative reservation envelope.
Function timeout excludes scheduling and resets per attempt; parent must verify
the actual SDK/capabilities, reserve aggregate budget, authorize reviewed data and
independently bound total wall/remote cancellation. Zero automatic retries. The
current data/CPU-ceiling evidence does not open cloud gates.
