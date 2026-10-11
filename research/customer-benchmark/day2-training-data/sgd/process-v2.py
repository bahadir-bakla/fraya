"""Isolated SGD mask repair; publisher labels/inputs/groups stay unchanged.

V2 needs independent review before affected-head fitting. V1 is never rewritten.
"""
from collections import Counter
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unicodedata

HERE = Path(__file__).resolve().parent
PARENT = HERE
FULL = HERE / "full-v2"
REPO = PARENT.parents[3]
V1_SHA = '7176ce8bf20c7e6adce899a276f7de0c042e0e33eb63999462264ca6c1843513'
BASE_PROCESSOR_SHA = '3cc4fbdc7cc3757b7ab80998f3a3e585b97cb6c3d28e11b33ff46b618224b032'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert digest(PARENT / 'process.py') == BASE_PROCESSOR_SHA
spec = importlib.util.spec_from_file_location('sgd_v1_frozen_base', PARENT / 'process.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
original_input_for = base.input_for


def input_for(turns, index):
    if type(index) is not int or not 0 <= index < len(turns):
        raise ValueError('Turn index must be an integer within the observed conversation.')
    return original_input_for(turns, index)


def word_part(char):
    return bool(char) and (unicodedata.category(char)[0] in 'LMN' or unicodedata.category(char) == 'Pc' or char in "'’‐‑-")


def whole_source_span(value, visible):
    """Case-sensitive normalized source identity, no cross-turn/partial-token match.

    Observed inputs retain the frozen NFKC/whitespace/privacy transform. Source
    values use the same NFKC/whitespace fold, with no additional case fold.
    Unicode letters/marks/numbers/connector punctuation and apostrophe/hyphen
    continuations count as word parts. Normalized multiword internal spacing is exact.
    """
    if not value or value != value.strip() or any(c in value for c in '\r\n\t'):
        return False
    start = 0
    while True:
        start = visible.find(value, start)
        if start < 0:
            return False
        end = start + len(value)
        before = visible[start - 1] if start else ''
        after = visible[end] if end < len(visible) else ''
        if not word_part(before) and not word_part(after):
            return True
        start += 1


def value_targets(values, visible):
    base.require(isinstance(values, list) and all(isinstance(v, str) for v in values), 'Invalid slot/action values')
    result = []
    for value in values:
        cleaned, _ = base.scrub(value)
        normalized = ' '.join(unicodedata.normalize('NFKC', value).split())
        recoverable = cleaned == normalized and not any(c in value for c in '\r\n\t') and whole_source_span(normalized, visible)
        result.append({'text': cleaned if recoverable else None, 'value_recoverability_mask': recoverable, 'source_value_sha256': base.sha(value.encode())})
    return result


base.input_for = input_for
base.value_targets = value_targets
OriginalShards = base.Shards


class V2Shards(OriginalShards):
    def add(self, split, row):
        row['schema_version'] = 'sgd.observed-user-input.publisher-targets.v2'
        super().add(split, row)


base.Shards = V2Shards


def self_test():
    bad = [('one', 'someone'), ('one', 'phone'), ('car', 'card'), ('no', 'known'), ('car', "car's"), ('car', 'car-like'), ('é', 'café'), ('la', 'call'), ('safe', 'safe\u0301'), ('car', 'Car'), ('san francisco', 'san  francisco')]
    for value, visible in bad:
        assert not whole_source_span(value, visible), (value, visible)
        assert not value_targets([value], visible)[0]['value_recoverability_mask']
    for value, visible in [('car', 'a car.'), ('san francisco', 'in san francisco today'), ('café', 'a café.'), ('car', 'card then car')]:
        assert whole_source_span(value, visible)
    turns = [{'speaker': 'USER', 'text': 'Hi'}]
    for index in [-1, 1, 0.5, True, '0']:
        try: input_for(turns, index)
        except ValueError: pass
        else: raise AssertionError('Invalid index accepted')
    schema = {'S': {'slots': [{'name': 'x'}], 'intents': [{'name': 'Act'}]}}
    current = {'service': 'S', 'state': {'active_intent': 'Act', 'requested_slots': [], 'slot_values': {'x': ['car']}}, 'actions': []}
    for previous in [{'slot_values': {}}, {'slot_values': {'x': ['car']}}]:
        target = base.frame_targets(current, schema, previous, 'card', Counter())
        assert not target['slot_values']['x'][0]['value_recoverability_mask']
        assert not target['belief_updates'][0]['update_mask']
    assert value_targets(['san  francisco'], 'san francisco')[0]['value_recoverability_mask']
    assert value_targets(['cafe\u0301'], 'café')[0]['value_recoverability_mask']
    assert base.self_test()['status'] == 'passed'
    return {'status': 'passed', 'partial_word_and_identity_negatives': len(bad), 'whole_span_positives': 4, 'invalid_indexes_rejected': 5, 'partial_word_SET_and_KEEP_masks_false': True}


def main():
    assert digest(PARENT / 'full-v1/manifest.json') == V1_SHA
    report = self_test()
    v1 = json.loads((PARENT / 'full-v1/manifest.json').read_bytes())
    plan_bytes = (PARENT / 'full-v1/split-plan.json').read_bytes()
    assert hashlib.sha256(plan_bytes).hexdigest() == v1['split_plan']['sha256']
    plan = json.loads(plan_bytes)['dialogues']
    items = base.source_files(None)
    schema = json.loads((PARENT / 'service-schema.json').read_bytes())
    destination = base.LOCAL / 'full-v2'
    if destination.exists() or (FULL / 'manifest.json').exists():
        raise RuntimeError('V2 output namespace already exists; never overwrite a frozen packet.')
    outputs, targets = base.emit(items, plan, {s['service_name']: s for s in schema}, destination)
    validation = base.verify_shards(outputs, plan, v1['counts']['source_counts']['USER_turns'])
    validation['repair_self_tests'] = report
    manifest = copy.deepcopy(v1)
    manifest.update(schema_version='sgd.training-packet.v2', status='prepared_awaiting_independent_review_not_fit_authorized', outputs=outputs, target_counts=targets, validation=validation)
    manifest['parent_v1'] = {'path': base.rel(PARENT / 'full-v1/manifest.json'), 'sha256': V1_SHA}
    manifest['base_processor'] = v1['processor']
    manifest['processor'] = {'path': base.rel(Path(__file__)), 'sha256': digest(Path(__file__))}
    manifest['batcher'] = {'path': base.rel(HERE / 'batches-v2.py'), 'sha256': digest(HERE / 'batches-v2.py')}
    manifest['split_plan'] = {'path': base.rel(FULL / 'split-plan.json'), 'sha256': hashlib.sha256(plan_bytes).hexdigest()}
    manifest['repair_protocol'] = {'only_changes': 'value recovery/null masks, dependent KEEP/SET masks and schema-version marker; same observed inputs/publisher labels/ancestry', 'identity': 'cleaned value equals NFKC/whitespace-normalized original source value; case-sensitive aligned whole literal span; source-value hash preserved', 'token_boundaries': 'Unicode letters/marks/numbers/connector punctuation, apostrophe and hyphen are word continuations', 'multiword': 'source NFKC and whitespace normalization equals frozen observed normalization; no across-turn newline matches', 'privacy': 'frozen text-only scrub unchanged; no relaxation', 'review_gate': 'Independent review required before value/update head fit; producer tests are not independent qualification.'}
    manifest['V1_loss_admission'] = 'ALL value and KEEP/SET heads masked in V1; unrelated publisher-head baselines may continue.'
    manifest['independent_review'] = {'status': 'pending', 'review_not_performed_by_data_owner': True}
    FULL.mkdir(exist_ok=True)
    (FULL / 'split-plan.json').write_bytes(plan_bytes)
    (FULL / 'manifest.json').write_bytes(base.encode(manifest))
    (FULL / 'producer-validation.json').write_bytes(base.encode(validation))
    assert digest(PARENT / 'full-v1/manifest.json') == V1_SHA
    print(json.dumps({'status': manifest['status'], 'manifest': base.rel(FULL / 'manifest.json'), 'sha256': digest(FULL / 'manifest.json'), 'target_counts': {k: targets[k] for k in ['value_targets', 'value_recoverable_targets', 'belief_update_KEEP', 'belief_update_SET', 'belief_update_masked']}, 'shards': len(outputs)}, sort_keys=True))


if __name__ == '__main__':
    main()
