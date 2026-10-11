Actual frozen MiniLM + fresh 77-way BANKING77 classifier (offline reference)

One parent-approved CPU fit completed on 7943 frozen publisher-TRAIN-derived
examples. The base sentence-transformers/all-MiniLM-L6-v2 encoder stayed frozen
at official revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41. The classifier
is fixed C=1 multinomial logistic regression, not a downloaded BANKING77 head.
Only the 993 CAL rows chose temperature and confidence threshold. Code, source,
input, exported head and calibration were frozen before the one 993-row EVAL.

From the repository root, run the usable exported runtime:
  py -3.11 -I -B integrations/learned-dialogue/day2_pretrained_runtime.py --head integrations/learned-dialogue/day2_pretrained_head.json --text "I did not make this card payment."

The runtime verifies all local encoder hashes, loads only safetensors on CPU,
uses trust_remote_code=False/token=False/local_files_only=True, and applies
attention-mask mean pooling followed by L2 normalization (384 dimensions,
maximum 256 wordpieces). It returns the original publisher intent hypothesis,
confidence and abstain flag. Bank permission and ledger truth are always null.
Consumers must respect abstain; even accepted labels supply no bank authority.

The compact JSON head is 178893 bytes and uses per-class symmetric int16
weights with float scales/intercepts. Its fitted temperature is
0.46613213827208083 and threshold is 0.64. Exported labels match the fitted
classifier on 100% of CAL and EVAL rows. The complete encoder files total
91578415 bytes under the existing ignored path:
  local-runs/customer-benchmark-day2-pretrained/encoder/1110a243fdf4706b3f48f1d95db1a4f5529b4d41
The head alone cannot encode text. This is an offline teacher/reference, with
no deployment or live Freya/tool integration. Model/card/tokenizer/config
hashes and the publisher's Apache-2.0 license declaration are recorded in the
plan and head. The corpus retains its separate CC-BY-4.0 publisher provenance.

Actual outcomes and full per-intent recall/confusion matrix:
  analysis/day2-pretrained-baseline.json
  analysis/day2-pretrained-baseline.txt
Freeze/hash chain:
  day2_pretrained_freeze.json
  analysis/day2-pretrained-baseline-eval-once.json
External 900-second watchdog / approved execution evidence:
  analysis/day2-pretrained-baseline-watchdog.json
  analysis/day2-pretrained-baseline-grant.json
Exported runtime smoke (new texts, no refit or EVAL reuse):
  analysis/day2-pretrained-baseline-runtime-smoke.json

The trainer --run rejects existing head/freeze/results. Do not rerun the fit
or evaluate this EVAL again to choose settings. The original plan, trainer,
runtime and corpus pins remain unchanged after execution approval.

Limits: this is internal English publisher-source intent evaluation. Known
two cross-split contraction aliases, redaction-related semantic loss,
single-label ambiguity/composite queries and answer-like publisher rows were
not relabeled or repartitioned. CAL precision/coverage are in-sample selection
estimates. All 16 predeclared authored OOD probes abstained, but they are not
independent/blind OOD or bank safety gold. No multilingual debt collection,
permission/ledger correctness, multi-turn, all-paraphrase or IID-gold claim.
