"""Separate, source-bound frozen V2 context audit. Host API is stdlib-only.

One isolated CPU child loads one model and shares <=60 seconds across startup,
FULL, actual NO_CONTEXT, and validation. The parent must hard-bound that child:
the frozen predictor checks deadlines between batches, not within each forward.
Existing finetuned_assist.SCHEMA and validate_result remain unchanged.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

# -I child execution does not place the script directory on sys.path. Load the
# sibling by exact path, without importing caller-controlled search paths.
if 'finetuned_assist' in sys.modules:
    assist = sys.modules['finetuned_assist']
    if Path(getattr(assist, '__file__', '')).resolve() != Path(__file__).with_name('finetuned_assist.py').resolve():
        raise ValueError('Foreign/preloaded assist module rejected')
else:
    _spec = importlib.util.spec_from_file_location(
        'finetuned_assist', Path(__file__).with_name('finetuned_assist.py'))
    assist = importlib.util.module_from_spec(_spec)
    sys.modules['finetuned_assist'] = assist
    _spec.loader.exec_module(assist)

SCHEMA = 'minilm.context_disagreement.audit.v1'
V2_PIN_MANIFEST = '7eca3b016b47ec20f1b1fd9e207c71a0c72ece9bf91f4e2c28ecd411dcb59189'
V2_PIN_RUNTIME = {
    'minilm_ft_core.py': '3b90bfb29389732c730cde4035bb881880ab53e21d9c2ab6915ead51469e4423',
    'minilm_ft_eval.py': 'e13e4b2bc5262a436b092a38dd5df35cc4f99e29be1dbdd6fcce89948f318c94',
}
V2_PIN_ARCHITECTURE = '5a124a14f26ef960a5533f352b2d50f0078724aa5f5a4ddfdd090424465ef230'
THRESHOLDS = [.5, .5, .5, 1.01, 1.01, .99, .8, .5, .7, .5, .6]
ARCHITECTURE = {'version': 2, 'features': ['current_global_mean',
    'current_last_window', 'prior_observed_context'], 'width': 1152,
    'max_window_tokens': 256, 'stride': 32}
NOTICE = ('Read finetuned-context-evidence.json only alongside verified FULL '
          'finetuned-evidence.json and original observed call/message rows. '
          'Enabled-head context selection flips are UNRESOLVED; inspect the '
          'source utterance and prior for scope or clarification hypotheses. '
          'Do not choose either arm, average scores, or infer a voice outcome. '
          'AGREED_NOT_SELECTED is not semantic absence or denial. DISABLED '
          'heads provide no negative evidence. NOT_APPLICABLE is untested '
          'because no prior exists. UNAVAILABLE supplies no agreement. '
          'Agreement may still be wrong. Bank authority is false and financial '
          'authorization remains UNKNOWN.')
REASONS = ('DEADLINE', 'NO_CONTEXT_FAILED')
INTERVENTION = {'name': 'zero_prior_context_only', 'retain_current_and_tail': True,
                'no_label_access': True}


def verify_v2(request):
    assist.validate_request(request)
    assist._number(request['seconds'], .01, 60)
    if request['manifest_sha256'] != V2_PIN_MANIFEST or request['runtime_sha256'] != V2_PIN_RUNTIME:
        raise ValueError('Frozen V2 release pins required')
    manifest = assist.verify_manifest(request)
    assist._verify_runtime(request)
    if manifest['files'].get('architecture.json') != V2_PIN_ARCHITECTURE:
        raise ValueError('Frozen V2 architecture pin required')
    if manifest['thresholds'] != THRESHOLDS or assist.read_json(
            Path(request['model_directory']) / 'architecture.json') != ARCHITECTURE:
        raise ValueError('Frozen V2 architecture/threshold contract')
    return manifest


def _check_heads(heads, thresholds):
    assist._keys(heads, assist.LABELS)
    for label, threshold in zip(assist.LABELS, thresholds):
        head = heads[label]
        assist._keys(head, ('logit', 'probability', 'selected'))
        probability = assist._sigmoid(head['logit'])
        assist._number(head['probability'], 0, 1)
        if abs(head['probability'] - probability) > 1e-12:
            raise ValueError('Logit/probability mismatch')
        if type(head['selected']) is not bool or head['selected'] != (probability >= threshold):
            raise ValueError('Selection/threshold mismatch')


def head_state(full_head, no_context_head, threshold):
    if threshold > 1:
        return 'DISABLED'
    if no_context_head is None:
        return 'UNAVAILABLE'
    if full_head['selected'] != no_context_head['selected']:
        return 'UNRESOLVED'
    return 'AGREED_SELECTED_PROPOSAL' if full_head['selected'] else 'AGREED_NOT_SELECTED'


def assemble_audit(request, full_result, observations, skipped, no_context_heads,
                   *, status='AVAILABLE', reason=None):
    """Pure deterministic envelope assembly; validate_audit is the trust boundary."""
    if status not in ('AVAILABLE', 'UNAVAILABLE'):
        raise ValueError('Audit status')
    if (status == 'AVAILABLE' and reason is not None) or (status == 'UNAVAILABLE' and reason not in REASONS):
        raise ValueError('Audit reason')
    if status == 'UNAVAILABLE':
        if no_context_heads is not None:
            raise ValueError('Unavailable cannot retain partial second-arm scores')
        no_context_heads = [None] * len(observations)
    if type(no_context_heads) is not list or len(no_context_heads) != len(observations):
        raise ValueError('Incomplete second arm')
    if len(full_result['rows']) != len(observations):
        raise ValueError('Incomplete FULL artifact')
    rows = []
    effective = []
    for observation, original, other in zip(observations, full_result['rows'], no_context_heads):
        prior = bool(observation['input']['previous_utterances'])
        zero_digest = assist._digest({'current_utterance': observation['input']['current_utterance'],
                                     'previous_utterances': []}) if prior else None
        if not prior and other is not None:
            raise ValueError('No prior must not claim a second inference')
        if prior and status == 'AVAILABLE' and other is None:
            raise ValueError('Incomplete prior-present second arm')
        _check_heads(original['heads'], THRESHOLDS)
        if other is not None:
            _check_heads(other, THRESHOLDS)
        states = {label: ('DISABLED' if threshold > 1 else 'NOT_APPLICABLE') if not prior
                  else head_state(original['heads'][label], None if other is None else other[label], threshold)
                  for label, threshold in zip(assist.LABELS, THRESHOLDS)}
        domain = any(states[label] == 'UNRESOLVED' for label in assist.DOMAIN)
        auxiliary = any(states[label] == 'UNRESOLVED' for label in assist.AUX)
        row_status = ('NOT_APPLICABLE' if not prior else 'UNAVAILABLE' if status == 'UNAVAILABLE'
                      else 'UNRESOLVED' if domain or auxiliary else 'AGREED')
        rows.append({'call_index': observation['call_index'], 'message_index': observation['message_index'],
                     'original_input_sha256': observation['input_sha256'],
                     'effective_no_context_input_sha256': zero_digest, 'prior_present': prior,
                     'full_heads': original['heads'], 'no_context_heads': other,
                     'audit_heads': states, 'domain_disagreement': domain,
                     'aux_disagreement': auxiliary, 'status': row_status})
        effective.append({'call_index': observation['call_index'], 'message_index': observation['message_index'],
                          'input_sha256': zero_digest})
    return {'schema': SCHEMA, 'request_sha256': assist._digest(request),
            'source_calls_sha256': request['calls_sha256'],
            'base_full_evidence_sha256': assist._digest(full_result),
            'manifest_sha256': request['manifest_sha256'], 'runtime_sha256': dict(request['runtime_sha256']),
            'architecture_sha256': V2_PIN_ARCHITECTURE,
            'model_files_sha256': dict(assist.read_json(Path(request['model_directory']) / 'manifest.json')['files']),
            'observed_inputs_sha256': assist._digest(observations),
            'effective_no_context_inputs_sha256': assist._digest(effective),
            'labels': list(assist.LABELS), 'thresholds': list(THRESHOLDS),
            'intervention': dict(INTERVENTION),
            'limits': {'shared_child_seconds': request['seconds'], 'cpu_threads': 2,
                       'parent_hard_wall_required': True, 'max_observed_rows': 512,
                       'max_messages': 20000, 'max_text_codepoints': 16384,
                       'max_prior_turns': 2, 'aggregate_observed_codepoints': 2000000},
            'status': status, 'reason': reason, 'rows': rows, 'skipped': skipped,
            'bank_authority': False, 'financial_authorization': 'UNKNOWN', 'notice': NOTICE}


def validate_audit(audit, request, full_result):
    """Reconstruct exact rows/states and bind the complete validated FULL artifact.

    Hashes bind reviewed local artifacts; they are not authenticated raw speech
    or proof that someone could not fabricate a mutually consistent logit pair.
    """
    verify_v2(request)
    assist.validate_result(full_result, request)
    observations, skipped = assist._source(request)
    if type(audit) is not dict or audit.get('status') not in ('AVAILABLE', 'UNAVAILABLE'):
        raise ValueError('Audit envelope/status')
    if type(audit.get('rows')) is not list or len(audit['rows']) != len(observations):
        raise ValueError('Missing/duplicate/foreign audit rows')
    other = []
    for row in audit['rows']:
        if type(row) is not dict:
            raise ValueError('Audit row')
        if type(row.get('call_index')) is not int or type(row.get('message_index')) is not int:
            raise ValueError('Audit source indices')
        for key in ('prior_present', 'domain_disagreement', 'aux_disagreement'):
            if type(row.get(key)) is not bool:
                raise ValueError('Strict audit booleans')
        other.append(row.get('no_context_heads'))
    if audit['status'] == 'UNAVAILABLE':
        if any(heads is not None for heads in other):
            raise ValueError('Unavailable must discard all partial second-arm rows')
        other = None
    expected = assemble_audit(request, full_result, observations, skipped, other,
                              status=audit['status'], reason=audit.get('reason'))
    assist._keys(audit, expected)
    # Canonical JSON equality also distinguishes bool from int, extra row/head
    # keys, ordering, substitutions and inconsistent semantic state derivations.
    if assist._digest(audit) != assist._digest(expected):
        raise ValueError('Audit source/output/state binding mismatch')
    return audit


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('Shared context audit deadline')


def _predict(model, observations, deadline, *, no_context=False):
    _deadline(deadline)
    logits = model.predict([{'input': item['input']} for item in observations], batch_size=16,
                           no_context=no_context, no_tail=False, deadline=deadline)
    _deadline(deadline)
    if hasattr(logits, 'tolist'):
        logits = logits.tolist()
    if type(logits) is not list or len(logits) != len(observations):
        raise ValueError('Incomplete prediction rows')
    result = []
    for values in logits:
        if type(values) is not list or len(values) != 11:
            raise ValueError('Invalid prediction dimensions')
        heads = {label: {'logit': value, 'probability': assist._sigmoid(value),
                         'selected': assist._sigmoid(value) >= threshold}
                 for label, value, threshold in zip(assist.LABELS, values, THRESHOLDS)}
        _check_heads(heads, THRESHOLDS)
        result.append(heads)
    return result


def _full(request, observations, skipped, heads):
    return {'schema': assist.SCHEMA, 'bank_authority': False, 'financial_authorization': 'UNKNOWN',
            'source_sha256': request['calls_sha256'], 'manifest_sha256': request['manifest_sha256'],
            'runtime_sha256': dict(request['runtime_sha256']), 'request_sha256': assist._digest(request),
            'labels': list(assist.LABELS), 'thresholds': list(THRESHOLDS),
            'rows': [{key: row[key] for key in ('call_index', 'message_index', 'input_sha256')} |
                     {'heads': scores, 'bank_authority': False, 'financial_authorization': 'UNKNOWN'}
                     for row, scores in zip(observations, heads)],
            'skipped': skipped, 'notice': assist.NOTICE}


def _run(request, full_result=None):
    assist.validate_request(request)
    assist._number(request['seconds'], .01, 60)
    deadline = time.monotonic() + request['seconds']
    request_digest = assist._digest(request)
    manifest = verify_v2(request)
    observations, skipped = assist._source(request)
    if full_result is not None:
        assist.validate_result(full_result, request)
    _deadline(deadline)
    model = None
    # No-prior audit of an existing artifact loads nothing and claims no parity.
    needs_model = full_result is None or any(item['input']['previous_utterances'] for item in observations)
    if needs_model:
        model, loaded_manifest = assist._load_runtime(request)
        if loaded_manifest != manifest:
            raise ValueError('Loaded model substitution')
        _deadline(deadline)
    if full_result is None:
        heads = _predict(model, observations, deadline)
        full_result = _full(request, observations, skipped, heads)
    assist.validate_result(full_result, request)
    status, reason = 'AVAILABLE', None
    paired = [None] * len(observations)
    try:
        _deadline(deadline)
        positions = [i for i, item in enumerate(observations) if item['input']['previous_utterances']]
        if positions:
            no_context = _predict(model, [observations[i] for i in positions], deadline, no_context=True)
            for i, scores in zip(positions, no_context):
                paired[i] = scores
        _deadline(deadline)
    except (TimeoutError, OSError, RuntimeError, ValueError) as error:
        status, reason, paired = 'UNAVAILABLE', ('DEADLINE' if isinstance(error, TimeoutError) or time.monotonic() >= deadline else 'NO_CONTEXT_FAILED'), None
    # Every source, model and runtime is checked again after both arms.
    if verify_v2(request) != manifest or assist._digest(request) != request_digest:
        raise ValueError('Source/model/request changed during audit')
    audit = assemble_audit(request, full_result, observations, skipped, paired, status=status, reason=reason)
    validate_audit(audit, request, full_result)
    if time.monotonic() >= deadline and audit['status'] == 'AVAILABLE':
        audit = assemble_audit(request, full_result, observations, skipped, None,
                               status='UNAVAILABLE', reason='DEADLINE')
        validate_audit(audit, request, full_result)
    return full_result, audit


def build_pair(request):
    return _run(request)


def audit_existing(request, full_result):
    """Preserve a source-bound existing actual FULL artifact byte-for-byte."""
    return _run(request, full_result)[1]


def _write_new(path, result):
    path = Path(path)
    if path.exists():
        raise ValueError('Refuse stale/overwritten evidence output')
    pending = path.with_name(path.name + '.pending')
    created = False
    try:
        with pending.open('x', encoding='utf8') as stream:
            created = True
            stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        if path.exists():
            raise ValueError('Evidence output appeared during write')
        pending.rename(path)
    finally:
        if created:
            pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', help='New strict FULL artifact when computing both arms')
    parser.add_argument('--audit-output', required=True)
    parser.add_argument('--full-evidence', help='Validate an existing FULL artifact; infer only NO_CONTEXT')
    args = parser.parse_args()
    if bool(args.output) == bool(args.full_evidence):
        parser.error('Supply exactly one of --output or --full-evidence')
    for path in [args.audit_output] + ([args.output] if args.output else []):
        if Path(path).exists() or Path(path).with_name(Path(path).name + '.pending').exists():
            raise ValueError('Refuse existing evidence output')
    request_path = Path(args.request)
    request_file_digest = assist.sha(request_path)
    request = assist.read_json(request_path)
    source_full_digest = assist.sha(args.full_evidence) if args.full_evidence else None
    full, audit = _run(request, assist.read_json(args.full_evidence) if args.full_evidence else None)
    if assist.sha(request_path) != request_file_digest or (args.full_evidence and assist.sha(args.full_evidence) != source_full_digest):
        raise ValueError('Request/FULL file changed during inference')
    if args.output:
        _write_new(args.output, full)
    _write_new(args.audit_output, audit)
    print(json.dumps({'status': audit['status'], 'reason': audit['reason'], 'rows': len(audit['rows']),
                      'domain_disagreements': sum(row['domain_disagreement'] for row in audit['rows']),
                      'aux_disagreements': sum(row['aux_disagreement'] for row in audit['rows']),
                      'bank_authority': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'UNAVAILABLE', 'error_type': type(error).__name__}))
        sys.exit(1)
