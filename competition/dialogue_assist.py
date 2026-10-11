"""Source-act diagnostics for actual failed-call turns, never bank permission."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

PINS = {
    'sgd_act_aux_runtime.py': 'a284bd9f482fc369cdc9fe207a337997f41c94d174cb6c6bb3da745c449778a9',
    'sgd_act_aux_weights.json': '0c0f1b11d2e66dfeb06edc5ac57001c51616e685b5679d014f1892392e1edf46',
    'sgd_act_aux_calibration.json': 'e4dbde277bd13377c60e7d09785e65e5c93baccd16705ff311b1193f573c1d49',
}
NOTICE = '''Read dialogue-evidence.json for optional source-act hypotheses on failed
call turns. Every row references the original call/turn and retains UNKNOWN
financial authorization. These are generic SGD USER acts, not payment intent,
identity, consent, policy, ledger truth or conversation-judge decisions. Read
the original transcript and all rules; resolve corrections and withdrawal from
actual speech and deterministic guards. No classifier score authorizes a tool.
'''
INPUT_SCOPE='Only observed USER speech and immediately preceding assistant speech; no current bank/state labels.'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed_turns(calls):
    for call_number, call in enumerate(calls):
        previous = ''
        for turn, message in enumerate(call.get('messages', [])):
            role = message.get('role', '').lower()
            text = message.get('message')
            if role == 'assistant' and type(text) is str:
                previous = text if len(text) <= 2048 else ''
            elif role == 'user':
                if type(text) is str and text.strip() and len(text) <= 2048:
                    yield {'call_index': call_number, 'message_index': turn,
                           'observed': {'speaker': 'USER', 'utterance': text,
                                        'earlier_context': [{'speaker': 'SYSTEM', 'text': previous}] if previous else []}}
                # Context means the previous dialogue turn, not an old question.
                previous = ''


def validate_result(result, request):
    if type(result) is not dict or result.get('schema')!='builder.dialogue_evidence.v1' or result.get('bank_authority') is not False or result.get('financial_authorization')!='UNKNOWN':
        raise ValueError('Invalid dialogue contract')
    if set(result)!={'schema','bank_authority','financial_authorization','source_file','source_sha256','model_pins','input_scope','rows','maximum_rows','notice'} or result.get('notice')!=NOTICE or result.get('input_scope')!=INPUT_SCOPE or type(result.get('maximum_rows')) is not int:
        raise ValueError('Unexpected dialogue metadata')
    source=Path(request['calls'])
    if sha(source)!=request['calls_sha256'] or result.get('source_sha256')!=request['calls_sha256'] or result.get('source_file')!=source.name or result.get('model_pins')!=PINS:
        raise ValueError('Dialogue evidence/model binding mismatch')
    expected=list(observed_turns(json.loads(source.read_text(encoding='utf-8'))))[:512]
    rows=result.get('rows')
    if type(rows) is not list or len(rows)!=len(expected) or result.get('maximum_rows')!=512:
        raise ValueError('Missing or foreign dialogue rows')
    for actual,item in zip(rows,expected):
        digest=hashlib.sha256(json.dumps(item['observed'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if type(actual) is not dict or set(actual)!={'call_index','message_index','observed_input_sha256','hypothesis'} or type(actual.get('call_index')) is not int or type(actual.get('message_index')) is not int or actual.get('call_index')!=item['call_index'] or actual.get('message_index')!=item['message_index'] or actual.get('observed_input_sha256')!=digest:
            raise ValueError('Invalid observed-turn reference')
        hypothesis=actual['hypothesis']
        if type(hypothesis) is not dict or set(hypothesis)!={'source_USER_acts','bank_authority','financial_authorization','ledger_truth','Freya_validated','scope'} or hypothesis['bank_authority'] is not None or hypothesis['financial_authorization']!='UNKNOWN' or hypothesis['ledger_truth'] is not None or hypothesis['Freya_validated'] is not False:
            raise ValueError('Forbidden hypothesis authority')
        if hypothesis['scope']!='SGD source acts only; AFFIRM conveys no financial authorization' or type(hypothesis['source_USER_acts']) is not dict or set(hypothesis['source_USER_acts'])!={'AFFIRM','NEGATE','INFORM','REQUEST'}:
            raise ValueError('Invalid source act taxonomy/scope')
        for name,act in hypothesis['source_USER_acts'].items():
            if type(act) is not dict or set(act)!={'source_act_probability','accepted_positive_proposal','proposal'}:
                raise ValueError('Invalid source act fields')
            p=act['source_act_probability'];accepted=act['accepted_positive_proposal']
            if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1 or type(accepted) is not bool or act['proposal']!=(name if accepted else 'UNKNOWN'):
                raise ValueError('Invalid source act probability/proposal')


def build(request):
    directory = Path(request['bundle'])
    for name, digest in PINS.items():
        if sha(directory / name) != digest: raise ValueError('Unpinned source-act artifact')
    source = Path(request['calls'])
    if sha(source) != request['calls_sha256']: raise ValueError('Changed call evidence')
    spec = importlib.util.spec_from_file_location('pinned_builder_source_acts', directory / 'sgd_act_aux_runtime.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    proposer = module.ActProposer(directory / 'sgd_act_aux_weights.json', directory / 'sgd_act_aux_calibration.json',
                                 PINS['sgd_act_aux_weights.json'], PINS['sgd_act_aux_calibration.json'])
    rows = []
    for item in observed_turns(json.loads(source.read_text(encoding='utf-8'))):
        if len(rows) >= 512: break
        observation = item.pop('observed')
        item['observed_input_sha256'] = hashlib.sha256(json.dumps(observation, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        item['hypothesis'] = proposer.propose(observation)
        rows.append(item)
    result={'schema': 'builder.dialogue_evidence.v1', 'bank_authority': False,
            'financial_authorization': 'UNKNOWN', 'source_file': source.name,
            'source_sha256': request['calls_sha256'], 'model_pins': PINS,
            'input_scope': INPUT_SCOPE,
            'rows': rows, 'maximum_rows': 512, 'notice': NOTICE}
    validate_result(result,request)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--request', required=True)
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.request).read_text(encoding='utf-8'))
        result = build(request)
        Path(request['output']).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'status': 'ready', 'turns': len(result['rows']), 'bank_authority': False}))
    except Exception as error:
        print(json.dumps({'status': 'unavailable', 'error_type': type(error).__name__})); sys.exit(1)
