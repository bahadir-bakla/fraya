"""Pinned offline MiniLM task proposals on observed failed-call dialogue only.

Host helpers are stdlib-only. ML imports occur only in the explicitly invoked
child. Request hashes must come from the parent's reviewed source/model pins.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PureWindowsPath
import shutil
import sys
import time

DOMAIN = ('proposal', 'dispute', 'correction', 'current_affirm',
          'current_withdraw', 'uncertain', 'reported_third_party')
AUX = ('AFFIRM', 'NEGATE', 'INFORM', 'REQUEST')
LABELS = DOMAIN + AUX
RUNTIME_NAMES = ('minilm_ft_core.py', 'minilm_ft_eval.py')
SCHEMA = 'builder.finetuned_proposals.v1'
MAX_ROWS = 512
MAX_TEXT = 16384
MAX_MESSAGES = 20000
NOTICE = ('Experimental observed-language proposals only. Scores and selected '
          'flags never establish identity, consent, ledger truth, policy, '
          'permission or an authorized bank action. Financial authorization '
          'remains UNKNOWN; deterministic guards retain authority. Check each '
          'hypothesis against the original current utterance and relevant '
          'conversation. Combined intents, long speech with late corrections, '
          'quoted agreement and Turkish language produced actual diagnostic '
          'errors; preserve conflicting or unresolved acts for clarification '
          'instead of treating these heads as a complete parse.')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('Unexpected fields')


def _hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid SHA256')


def _number(value, lo, hi):
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError('Invalid finite numeric value')


def _sigmoid(value):
    _number(value, -1e30, 1e30)
    return 1 / (1 + math.exp(-value)) if value >= 0 else math.exp(value) / (1 + math.exp(value))


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError('Nonfinite JSON constant')
    return json.loads(Path(path).read_text(encoding='utf8'), object_pairs_hook=unique,
                      parse_constant=invalid_constant)


def observed_turns(calls, *, context_turns=1):
    """Literal message adjacency; intervening system/tool/invalid turns reset it.

    Gold/scorer/case metadata is never passed to the encoder. Oversized or blank
    USER turns are explicitly skipped and reset context; nothing is truncated.
    """
    if type(calls) is not list or len(calls) > 512:
        raise ValueError('Invalid call collection')
    if context_turns not in (1,2):raise ValueError('Unsupported observed context length')
    rows, skipped, count, total = [], [], 0, 0
    for ci, call in enumerate(calls):
        if type(call) is not dict or type(call.get('messages')) is not list:
            raise ValueError('Invalid message collection')
        previous = None
        history = []
        for mi, message in enumerate(call['messages']):
            count += 1
            if count > MAX_MESSAGES:
                raise ValueError('Message overflow')
            old_previous, previous = previous, None
            if type(message) is not dict:
                history=[]
                continue
            role, text = message.get('role'), message.get('message')
            if type(role) is not str:
                history=[]
                continue
            role = role.lower()
            valid = type(text) is str and bool(text.strip()) and len(text) <= MAX_TEXT
            if role == 'assistant':
                if valid:
                    previous = text
                    history=(history+[{'speaker':'ASSISTANT','text':text}])[-2:]
                else:history=[]
                continue
            if role != 'user':
                history=[]
                continue
            if not valid:
                reason = 'malformed' if type(text) is not str else 'oversized' if len(text) > MAX_TEXT else 'blank'
                skipped.append({'call_index': ci, 'message_index': mi, 'reason': reason})
                history=[]
                continue
            context=history[-2:] if context_turns==2 else ([{'speaker': 'ASSISTANT', 'text': old_previous}] if old_previous is not None else [])
            inp = {'current_utterance': text, 'previous_utterances':context}
            history=(history+[{'speaker':'USER','text':text}])[-2:]
            total += len(text) + sum(len(turn['text']) for turn in context)
            if len(rows) >= MAX_ROWS or total > 2_000_000:
                raise ValueError('Observed input overflow; no partial result')
            rows.append({'call_index': ci, 'message_index': mi,
                         'input_sha256': _digest(inp), 'input': inp})
    return rows, skipped


def validate_request(request):
    _keys(request, ('schema', 'calls', 'calls_sha256', 'model_directory',
                    'manifest_sha256', 'runtime_directory', 'runtime_sha256', 'seconds'))
    if request['schema'] != SCHEMA:
        raise ValueError('Request schema')
    for key in ('calls', 'model_directory', 'runtime_directory'):
        if type(request[key]) is not str or not Path(request[key]).is_absolute():
            raise ValueError('Absolute path required')
    for key in ('calls_sha256', 'manifest_sha256'):
        _hash(request[key])
    _keys(request['runtime_sha256'], RUNTIME_NAMES)
    for digest in request['runtime_sha256'].values():
        _hash(digest)
    _number(request['seconds'], 0.01, 600)
    return request


def verify_manifest(request):
    validate_request(request)
    root = Path(request['model_directory']).resolve(strict=True)
    manifest_path = root / 'manifest.json'
    if manifest_path.is_symlink() or sha(manifest_path) != request['manifest_sha256']:
        raise ValueError('Model manifest pin mismatch')
    manifest = read_json(manifest_path)
    _keys(manifest, ('files', 'labels', 'thresholds', 'bank_authority'))
    if manifest['labels'] != list(LABELS) or manifest['bank_authority'] is not False:
        raise ValueError('Model taxonomy/authority mismatch')
    if type(manifest['thresholds']) is not list or len(manifest['thresholds']) != 11:
        raise ValueError('Missing CAL thresholds')
    for threshold in manifest['thresholds']:
        _number(threshold, 0, 1.01)  # Parent CAL uses 1.01 for disabled heads.
    files = manifest['files']
    if type(files) is not dict or not 3 <= len(files) <= 64:
        raise ValueError('Invalid manifest files')
    required = {'head.safetensors', 'encoder/model.safetensors', 'encoder/config.json'}
    if not required <= set(files):
        raise ValueError('Missing fine-tuned safetensors/config pins')
    for name, digest in files.items():
        if type(name) is not str or '\\' in name or ':' in name:
            raise ValueError('Invalid manifest path')
        relative = Path(name)
        if relative.is_absolute() or PureWindowsPath(name).is_absolute() or '..' in relative.parts or relative.as_posix() != name:
            raise ValueError('Invalid manifest path')
        if relative.suffix not in ('.json', '.safetensors', '.txt'):
            raise ValueError('Unsupported model artifact')
        _hash(digest)
        path = root / relative
        if any(p.is_symlink() for p in [path] + list(path.parents)[:len(relative.parts)-1]):
            raise ValueError('Model link rejected')
        if not path.resolve(strict=True).is_relative_to(root) or sha(path) != digest:
            raise ValueError('Model artifact pin mismatch')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(files) | {'manifest.json'}:
        raise ValueError('Unlisted model file')
    return manifest


def _source(request):
    if sha(request['calls']) != request['calls_sha256']:
        raise ValueError('Changed call source')
    manifest=verify_manifest(request)
    return observed_turns(read_json(request['calls']),context_turns=2 if 'architecture.json' in manifest['files'] else 1)


def copy_runtime(source_directory, destination, expected_sha256):
    """Copy only the two reviewed runtime modules into a fresh builder snapshot."""
    _keys(expected_sha256, RUNTIME_NAMES)
    source, dest = Path(source_directory).resolve(), Path(destination).resolve()
    for name in RUNTIME_NAMES:
        _hash(expected_sha256[name])
        if sha(source / name) != expected_sha256[name]:
            raise ValueError('Runtime source changed')
    dest.mkdir(parents=True, exist_ok=False)
    for name in RUNTIME_NAMES:
        shutil.copyfile(source / name, dest / name)
        if sha(dest / name) != expected_sha256[name]:
            raise ValueError('Runtime copy changed')
    return str(dest)


def prepare_request(*, calls, model_directory, manifest_sha256,
                    runtime_directory, runtime_sha256, seconds=60, mode='auto'):
    """Parent supplies reviewed pins. Off returns None without touching files.

    Auto returns None only for unavailable model/pin. Pin mismatches raise in all
    modes so the parent records the failure; required never silently falls back.
    """
    if mode not in ('auto', 'off', 'required'):
        raise ValueError('Invalid assist mode')
    if mode == 'off':
        return None
    if not manifest_sha256 or not (Path(model_directory) / 'manifest.json').is_file():
        if mode == 'auto':
            return None
        raise ValueError('Required pinned fine-tuned model unavailable')
    request = {'schema': SCHEMA, 'calls': str(Path(calls).resolve()),
               'calls_sha256': sha(calls), 'model_directory': str(Path(model_directory).resolve()),
               'manifest_sha256': manifest_sha256,
               'runtime_directory': str(Path(runtime_directory).resolve()),
               'runtime_sha256': dict(runtime_sha256), 'seconds': seconds}
    verify_manifest(request)
    _source(request)
    _verify_runtime(request)
    return request


def _verify_runtime(request):
    root = Path(request['runtime_directory']).resolve(strict=True)
    if {p.name for p in root.iterdir()} != set(RUNTIME_NAMES):
        raise ValueError('Runtime snapshot must contain exactly two modules')
    for name in RUNTIME_NAMES:
        path = root / name
        if path.is_symlink() or sha(path) != request['runtime_sha256'][name]:
            raise ValueError('Runtime pin mismatch')
    return root


def _load_runtime(request):
    root = _verify_runtime(request)
    if 'minilm_ft_core' in sys.modules:
        raise ValueError('Foreign/preloaded core module rejected')
    # No caller-controlled sys.path insertion; resolve both source modules exactly.
    def load(name, file):
        spec = importlib.util.spec_from_file_location(name, file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module
    load('minilm_ft_core', root / RUNTIME_NAMES[0])
    runtime = load('_builder_pinned_minilm_eval', root / RUNTIME_NAMES[1])
    import torch
    torch.set_num_threads(2)
    return runtime.load_model(request['model_directory'], device='cpu')


class FinetunedModel:
    """Child-only pinned loader; initialization never trains or chooses thresholds.

    predict accepts exact observed input snapshots, not rows containing gold,
    state, permissions or expected actions. Use build for source-bound evidence.
    """
    def __init__(self, request):
        validate_request(request)
        self.manifest = verify_manifest(request)
        self.deadline = time.monotonic() + request['seconds']
        self.model, loaded_manifest = _load_runtime(request)
        if loaded_manifest != self.manifest:
            raise ValueError('Loaded manifest substitution')
        if time.monotonic() >= self.deadline:
            raise TimeoutError('Model startup exceeded child budget')

    def predict(self, inputs):
        if type(inputs) is not list or len(inputs) > MAX_ROWS:
            raise ValueError('Invalid inference inputs')
        for inp in inputs:
            _keys(inp, ('current_utterance', 'previous_utterances'))
            current, previous = inp['current_utterance'], inp['previous_utterances']
            if type(current) is not str or not current.strip() or len(current) > MAX_TEXT:
                raise ValueError('Invalid observed USER speech')
            v2='architecture.json' in self.manifest['files']
            if type(previous) is not list or len(previous) > (2 if v2 else 1):
                raise ValueError('Observed context exceeds the pinned model contract')
            for turn in previous:
                _keys(turn, ('speaker', 'text'))
                if turn['speaker'] not in (('ASSISTANT','USER') if v2 else ('ASSISTANT',)) or type(turn['text']) is not str or not turn['text'].strip() or len(turn['text']) > MAX_TEXT:
                    raise ValueError('Invalid assistant context')
        logits = self.model.predict([{'input': inp} for inp in inputs], batch_size=16, deadline=self.deadline)
        if hasattr(logits, 'tolist'):
            logits = logits.tolist()
        if type(logits) is not list or len(logits) != len(inputs):
            raise ValueError('Invalid logit rows')
        output = []
        for values in logits:
            if type(values) is not list or len(values) != 11:
                raise ValueError('Invalid logit head dimensions')
            heads = {}
            for label, value, threshold in zip(LABELS, values, self.manifest['thresholds']):
                probability = _sigmoid(value)
                heads[label] = {'logit': value, 'probability': probability,
                                'selected': probability >= threshold}
            output.append(heads)
        if time.monotonic() >= self.deadline:
            raise TimeoutError('Child budget exceeded')
        return output


def build(request):
    validate_request(request)
    observations, skipped = _source(request)
    engine = FinetunedModel(request)
    manifest = engine.manifest
    proposals = engine.predict([item['input'] for item in observations])
    rows = []
    for observed, heads in zip(observations, proposals):
        rows.append({key: observed[key] for key in ('call_index', 'message_index', 'input_sha256')} |
                    {'heads': heads, 'bank_authority': False, 'financial_authorization': 'UNKNOWN'})
    # Recheck sources/weights after inference; parent independently bounds wall time.
    if verify_manifest(request) != manifest:
        raise ValueError('Model changed during inference')
    _verify_runtime(request)
    result = {'schema': SCHEMA, 'bank_authority': False, 'financial_authorization': 'UNKNOWN',
              'source_sha256': request['calls_sha256'], 'manifest_sha256': request['manifest_sha256'],
              'runtime_sha256': request['runtime_sha256'], 'request_sha256': _digest(request),
              'labels': list(LABELS), 'thresholds': manifest['thresholds'],
              'rows': rows, 'skipped': skipped, 'notice': NOTICE}
    validate_result(result, request)
    return result


def validate_result(result, request):
    validate_request(request)
    _keys(result, ('schema', 'bank_authority', 'financial_authorization', 'source_sha256',
                   'manifest_sha256', 'runtime_sha256', 'request_sha256', 'labels',
                   'thresholds', 'rows', 'skipped', 'notice'))
    for key in ('schema', 'manifest_sha256', 'runtime_sha256'):
        if result[key] != request[key]:
            raise ValueError('Result binding mismatch')
    if result['source_sha256'] != request['calls_sha256'] or result['request_sha256'] != _digest(request):
        raise ValueError('Result source/request mismatch')
    if result['bank_authority'] is not False or result['financial_authorization'] != 'UNKNOWN' or result['notice'] != NOTICE or result['labels'] != list(LABELS):
        raise ValueError('Result authority/taxonomy mismatch')
    manifest = verify_manifest(request)
    _verify_runtime(request)
    if result['thresholds'] != manifest['thresholds']:
        raise ValueError('CAL threshold substitution')
    if type(result['thresholds']) is not list:
        raise ValueError('Invalid threshold types')
    for threshold in result['thresholds']:
        _number(threshold, 0, 1.01)
    expected, skipped = _source(request)
    if type(result['rows']) is not list or len(result['rows']) != len(expected) or result['skipped'] != skipped:
        raise ValueError('Missing/foreign rows or skip diagnostics')
    if type(result['skipped']) is not list:
        raise ValueError('Invalid skipped records')
    for item in result['skipped']:
        _keys(item, ('call_index', 'message_index', 'reason'))
        if type(item['call_index']) is not int or type(item['message_index']) is not int or type(item['reason']) is not str:
            raise ValueError('Invalid skipped-record types')
    for actual, item in zip(result['rows'], expected):
        _keys(actual, ('call_index', 'message_index', 'input_sha256', 'heads', 'bank_authority', 'financial_authorization'))
        for key in ('call_index', 'message_index'):
            if type(actual[key]) is not int or actual[key] != item[key]:
                raise ValueError('Invalid source index')
        if actual['input_sha256'] != item['input_sha256'] or actual['bank_authority'] is not False or actual['financial_authorization'] != 'UNKNOWN':
            raise ValueError('Invalid input binding/authority')
        _keys(actual['heads'], LABELS)
        for label, threshold in zip(LABELS, manifest['thresholds']):
            head = actual['heads'][label]
            _keys(head, ('logit', 'probability', 'selected'))
            _number(head['probability'], 0, 1)
            if head['probability'] != _sigmoid(head['logit']):
                raise ValueError('Logit/sigmoid mismatch')
            if type(head['selected']) is not bool or head['selected'] != (head['probability'] >= threshold):
                raise ValueError('Selection/threshold mismatch')
    return result


def child_environment(environment):
    keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR',
            'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'LANG', 'LC_ALL',
            'USERNAME', 'USER', 'LOGNAME'}
    out = {k: v for k, v in environment.items() if k.upper() in keep}
    out.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
               TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2',
               PYTHONIOENCODING='utf8', PYTHONDONTWRITEBYTECODE='1')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Refuse stale/overwritten proposal output')
    result = build(read_json(args.request))
    temporary = output.with_name(output.name + '.pending')
    with temporary.open('x', encoding='utf8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(output)
    print(json.dumps({'status': 'ready', 'rows': len(result['rows']),
                      'skipped': len(result['skipped']), 'bank_authority': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'unavailable', 'error_type': type(error).__name__}))
        sys.exit(1)
