"""Pinned, stdlib-only dataset ingestion; exports conversation planning, never policy."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 20_000_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest():
    return json.loads((ROOT / 'sources.json').read_text(encoding='utf-8'))


def checked(data, spec):
    if len(data) > MAX_BYTES or digest(data) != spec['sha256']:
        raise ValueError('Source size/hash mismatch')
    return data


def download(spec, cache):
    target = cache / (spec['id'] + '.data')
    if target.exists():
        return checked(target.read_bytes(), spec)
    # No user URL, credentials, archive extraction, or remote execution.
    if not re.fullmatch(r'https://raw\.githubusercontent\.com/[\w-]+/[\w-]+/[a-f0-9]{40}/[\w./-]+', spec['url']):
        raise ValueError('Expected immutable GitHub raw URL')
    req = urllib.request.Request(spec['url'], headers={'User-Agent': 'fraya-customer-datasets/1'})
    with urllib.request.urlopen(req, timeout=60) as response:
        if not response.geturl().startswith('https://raw.githubusercontent.com/'):
            raise ValueError('Unexpected redirect')
        data = checked(response.read(MAX_BYTES + 1), spec)
    cache.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 20000:
        raise ValueError('Expected bounded nonempty text')
    return value


def banking(data):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline=''))
    if reader.fieldnames != ['text', 'category']:
        raise ValueError('Unexpected Banking77 columns')
    records = []
    for i, row in enumerate(reader):
        if None in row or any(v is None for v in row.values()):
            raise ValueError('Malformed CSV row')
        utterance, label = text(row['text']), text(row['category'])
        records.append({'record_id': str(i), 'source_label': label,
                        'turns': [{'index': 0, 'speaker': 'user', 'text': utterance}],
                        'action_count': 0})
    if not records:
        raise ValueError('Empty dataset')
    return records


def taskmaster(data):
    raw = json.loads(data.decode('utf-8'))
    if not isinstance(raw, list) or not raw:
        raise ValueError('Expected nonempty dialog list')
    records, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('Expected dialog object')
        ident = text(item.get('conversation_id'))
        if ident in seen:
            raise ValueError('Duplicate conversation ID')
        seen.add(ident)
        turns = item.get('utterances')
        if not isinstance(turns, list) or len(turns) < 2:
            raise ValueError('Expected multi-turn conversation')
        actions = 0
        for i, turn in enumerate(turns):
            if not isinstance(turn, dict) or type(turn.get('index')) is not int or turn['index'] != i:
                raise ValueError('Invalid turn index')
            if turn.get('speaker') not in ('user', 'assistant'):
                raise ValueError('Invalid speaker')
            # Publisher shard contains three empty turns; preserve their position.
            if not isinstance(turn.get('text'), str) or len(turn['text']) > 20000:
                raise ValueError('Invalid turn text')
            apis = turn.get('apis', [])
            if not isinstance(apis, list) or any(not isinstance(a, dict) or not isinstance(a.get('name'), str) for a in apis):
                raise ValueError('Invalid API annotations')
            actions += len(apis)
        records.append({'record_id': ident, 'source_label': text(item.get('vertical')),
                        'turns': turns, 'action_count': actions})
    return records


PATTERNS = {
    'correction_cue': re.compile(r'\b(actually|instead|i meant|change my|no(?=,)|sorry)\b', re.I),
    'wait_or_hold_cue': re.compile(r'\b(wait|hold on|one moment|hang on)\b', re.I),
    'polite_cue': re.compile(r'\b(please|thank you|thanks)\b', re.I),
    'question_cue': re.compile(r'\?'),
}


def observations(record):
    result = []
    for turn in record['turns']:
        if turn['speaker'] != 'user':
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(turn['text']):
                result.append({'feature': name, 'turn_index': turn['index'],
                               'utterance_sha256': digest(turn['text'].encode('utf-8')),
                               'method': 'lexical_heuristic_v1'})
    return result


def sample(records, limit):
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError('Sample limit must be 1..25 per dataset (50 total)')
    # Round-robin across intent labels / observed conversation feature combinations.
    buckets = {}
    for record in records:
        key = (record['source_label'], () if len(record['turns']) == 1 else
               tuple(sorted({o['feature'] for o in observations(record)})))
        buckets.setdefault(key, []).append(record)
    selected = []
    for offset in range(len(records)):
        for key in sorted(buckets):
            if offset < len(buckets[key]):
                selected.append(buckets[key][offset])
                if len(selected) == limit:
                    return selected
        if len(selected) == len(records):
            break
    return selected


def scenario(record, spec):
    obs = observations(record)
    features = {o['feature'] for o in obs}
    user_plan = ['I need help with my request.']
    if 'question_cue' in features:
        user_plan.append('Could you explain the next step?')
    if 'wait_or_hold_cue' in features:
        user_plan.append('Wait, let me finish explaining my request.')
    if 'correction_cue' in features:
        user_plan.append('Actually, let me correct part of my request.')
    if 'polite_cue' in features:
        user_plan.append('Thank you for helping me.')
    provenance = {k: spec[k] for k in ('id', 'url', 'revision', 'sha256', 'license', 'license_url', 'license_terms_url', 'attribution')}
    provenance['adaptation_notice'] = 'Modified: selected records reduced to taxonomy, turn structure, counts and hashed lexical cues; generic synthetic planning templates added.'
    return {
        'schema_version': 1,
        'scenario_id': spec['id'] + ':' + record['record_id'],
        'provenance': provenance,
        'source_facts': {'record_id': record['record_id'], 'source_taxonomy_label': record['source_label'],
                         'source_turn_count': len(record['turns']), 'source_action_annotation_count': record['action_count'],
                         'source_empty_turn_count': sum(not t['text'].strip() for t in record['turns']),
                         'turn_structure': [{'index': t['index'], 'speaker': t['speaker']} for t in record['turns']],
                         'observations': obs},
        'synthetic_plan': {'origin': 'local_generic_templates_v1', 'user_utterances': user_plan,
                           'expected_outputs': [], 'policy_mapping': None,
                           'note': 'Templates are synthetic; source cues are heuristic, not verified interruptions or emotions.'},
        'oracle_scope': 'conversation_only', 'execution_status': 'not_executed',
    }


def build(limit=25, offline=False):
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError('Sample limit must be 1..25 per dataset (50 total)')
    result, stats = [], []
    for spec in manifest():
        notice_spec = {'id': spec['id'] + '-license', 'url': spec['license_url'],
                       'sha256': spec['license_notice_sha256']}
        notice_path = ROOT / 'cache' / (notice_spec['id'] + '.data')
        if offline:
            checked(notice_path.read_bytes(), notice_spec)
        else:
            download(notice_spec, ROOT / 'cache')
        target = ROOT / 'cache' / (spec['id'] + '.data')
        data = checked(target.read_bytes(), spec) if offline else download(spec, ROOT / 'cache')
        records = banking(data) if spec['format'] == 'banking77_csv' else taskmaster(data)
        chosen = sample(records, limit)
        result.extend(scenario(r, spec) for r in chosen)
        stats.append({'dataset': spec['id'], 'source_records': len(records), 'sampled': len(chosen),
                      'source_labels': len({r['source_label'] for r in records}),
                      'sampled_labels': len({r['source_label'] for r in chosen}),
                      'sampled_feature_names': sorted({o['feature'] for r in chosen for o in observations(r)}),
                      'sampled_action_annotations': sum(r['action_count'] for r in chosen)})
    return {'selection_method': 'sorted_label_feature_round_robin_v1', 'scenarios': result, 'stats': stats}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=25, help='Per dataset, hard cap 25 (50 total)')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    output = build(args.limit, args.offline)
    destination = ROOT / 'cache' / 'scenarios.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(destination), 'stats': output['stats']}))
