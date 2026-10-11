"""Bounded local production audit runner; labels are opened only after inference.

Never updates the parent runs, their state, or any existing analysis report.
"""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'competition'))
import finetuned_assist as assist
import finetuned_context_audit as audit

OUT = ROOT / 'analysis/minilm-v2-context-auditdata-20261011'
RECORDED = ROOT / 'competition/runs/20261011-165857-6ce127'


def save(path, value):
    with path.open('x', encoding='utf8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def run_child(arguments, name):
    command = [sys.executable, '-I', '-B', str(ROOT / 'competition/finetuned_context_audit.py')] + arguments
    source_hashes = {name: assist.sha(ROOT / 'competition' / name)
                     for name in ('finetuned_context_audit.py', 'finetuned_assist.py')}
    start = time.monotonic()
    try:
        completed = subprocess.run(command, env=assist.child_environment(os.environ),
                                   capture_output=True, text=True, encoding='utf8', timeout=60)
        result = {'command': command, 'returncode': completed.returncode,
                  'elapsed_seconds': round(time.monotonic() - start, 3),
                  'stdout': completed.stdout, 'stderr': completed.stderr, 'hard_wall_seconds': 60}
    except subprocess.TimeoutExpired as error:
        result = {'command': command, 'returncode': None, 'status': 'UNAVAILABLE',
                  'reason': 'PARENT_HARD_WALL', 'elapsed_seconds': round(time.monotonic() - start, 3),
                  'hard_wall_seconds': 60}
    result['source_sha256_before'] = source_hashes
    result['source_sha256_after'] = {name: assist.sha(ROOT / 'competition' / name) for name in source_hashes}
    result['source_unchanged_during_child'] = result['source_sha256_before'] == result['source_sha256_after']
    save(OUT / (name + '.invocation.json'), result)
    print(json.dumps({'name': name, 'returncode': result['returncode'],
                      'elapsed_seconds': result['elapsed_seconds']}), flush=True)
    return result


def recorded():
    request = RECORDED / 'finetuned-request.json'
    full = RECORDED / 'work/finetuned-evidence.json'
    destination = OUT / 'recorded13.audit.json'
    invocation = run_child(['--request', str(request), '--full-evidence', str(full),
                            '--audit-output', str(destination)], 'recorded13')
    if destination.exists():
        result = assist.read_json(destination)
        audit.validate_audit(result, assist.read_json(request), assist.read_json(full))
        summary = {'status': result['status'], 'rows': len(result['rows']),
                   'prior_present': sum(row['prior_present'] for row in result['rows']),
                   'domain_disagreement_rows': sum(row['domain_disagreement'] for row in result['rows']),
                   'aux_disagreement_rows': sum(row['aux_disagreement'] for row in result['rows']),
                   'row_statuses': {state: sum(row['status'] == state for row in result['rows'])
                                    for state in ('AGREED', 'UNRESOLVED', 'NOT_APPLICABLE', 'UNAVAILABLE')},
                   'request_file_sha256': assist.sha(request), 'full_file_sha256': assist.sha(full),
                   'audit_file_sha256': assist.sha(destination),
                   'actual_inference': True, 'labels_used': False, 'bank_score': None}
        save(OUT / 'recorded13.summary.json', summary)
        print(json.dumps(summary), flush=True)
    return invocation


def translate96():
    # Translation only: do not inspect label/mask/expected-action fields here.
    source = ROOT / 'analysis/minilm-v2-independent-probes.json'
    cases = assist.read_json(source)
    if len(cases) != 96:
        raise ValueError('Expected exposed96')
    calls, mapping = [], []
    for i, case in enumerate(cases):
        inp = case['input']
        messages = []
        translated = []
        for turn in inp['previous_utterances']:
            role = turn['role'].upper()
            if role not in ('USER', 'ASSISTANT'):
                raise ValueError('Cannot silently translate non-observed context')
            translated.append({'speaker': role, 'text': turn['text']})
            messages.append({'role': role.lower(), 'message': turn['text']})
        messages.append({'role': 'user', 'message': inp['current_utterance']})
        calls.append({'messages': messages})
        mapping.append({'case_index': i, 'call_index': i, 'message_index': len(messages) - 1,
                        'input_sha256': assist._digest({'current_utterance': inp['current_utterance'],
                                                     'previous_utterances': translated})})
    callpath = OUT / 'exposed96.observed-only.calls.json'
    save(callpath, calls)
    save(OUT / 'exposed96.current-row-map.json', {'source_sha256': assist.sha(source), 'mapping': mapping})
    rows, _ = assist.observed_turns(calls, context_turns=2)
    indexed = {(row['call_index'], row['message_index']): row for row in rows}
    for item in mapping:
        if indexed[(item['call_index'], item['message_index'])]['input_sha256'] != item['input_sha256']:
            raise ValueError('Current-row translation lost original prior')
    original = assist.read_json(RECORDED / 'finetuned-request.json')
    request = dict(original, calls=str(callpath.resolve()), calls_sha256=assist.sha(callpath), seconds=60)
    requestpath = OUT / 'exposed96.request.json'
    save(requestpath, request)
    return requestpath, mapping


def diagnostics96(mapping, full, envelope):
    # First label access for diagnosis occurs AFTER both production arms finish.
    cases = assist.read_json(ROOT / 'analysis/minilm-v2-independent-probes.json')
    indexed = {(row['call_index'], row['message_index']): row for row in envelope['rows']}
    current = [indexed[(item['call_index'], item['message_index'])] for item in mapping]
    paired = [i for i, row in enumerate(current) if row['prior_present'] and row['no_context_heads'] is not None]
    ratio = lambda a, b: a / b if b else None
    head_metrics = {}
    for j, label in enumerate(assist.LABELS):
        enabled = audit.THRESHOLDS[j] <= 1
        known = [i for i in paired if (cases[i]['domain_mask'] + cases[i]['aux_mask'])[j]] if enabled else []
        truth = lambda i: (cases[i]['domain_labels'] + cases[i]['aux_labels'])[j] == 1
        errors = [i for i in known if current[i]['full_heads'][label]['selected'] != truth(i)]
        flags = [i for i in known if current[i]['audit_heads'][label] == 'UNRESOLVED']
        caught = [i for i in flags if i in errors]
        positive = [i for i in known if current[i]['audit_heads'][label] == 'AGREED_SELECTED_PROPOSAL']
        correct_positive = [i for i in positive if truth(i)]
        head_metrics[label] = {'enabled': enabled, 'known_paired': len(known),
                              'flags': len(flags), 'full_errors': len(errors), 'flagged_full_errors': len(caught),
                              'error_capture_precision': ratio(len(caught), len(flags)),
                              'flag_error_recall': ratio(len(caught), len(errors)),
                              'positive_proposals': len(positive), 'correct_positive_proposals': len(correct_positive),
                              'positive_proposal_precision': ratio(len(correct_positive), len(positive)),
                              'positive_proposal_recall': ratio(len(correct_positive), sum(truth(i) for i in known)),
                              'positive_coverage': ratio(len(positive), len(known))}
    def active_error(i):
        return any(cases[i]['domain_mask'][j] and audit.THRESHOLDS[j] <= 1 and
                   current[i]['full_heads'][label]['selected'] != bool(cases[i]['domain_labels'][j])
                   for j, label in enumerate(assist.DOMAIN))
    known_rows = [i for i in paired if any(cases[i]['domain_mask'][j] and audit.THRESHOLDS[j] <= 1 for j in range(7))]
    retained = [i for i in known_rows if not current[i]['domain_disagreement']]
    joint_all7 = [i for i in range(96) if all(not cases[i]['domain_mask'][j] or
                 current[i]['full_heads'][label]['selected'] == bool(cases[i]['domain_labels'][j])
                 for j, label in enumerate(assist.DOMAIN))]
    groups = {}
    for i, case in enumerate(cases):
        group = groups.setdefault(case['group'], {'rows': 0, 'paired': 0, 'domain_flags': 0, 'active_full_errors': 0})
        group['rows'] += 1
        if i in paired:
            group['paired'] += 1
            group['domain_flags'] += current[i]['domain_disagreement']
            group['active_full_errors'] += active_error(i)
    return {'status': envelope['status'], 'exposed_cases': 96, 'authored_groups': len(groups),
            'total_inferred_observed_rows': len(envelope['rows']), 'current_rows': len(current),
            'prior_present': sum(row['prior_present'] for row in current), 'paired_prior_rows': len(paired),
            'no_prior_rows': sum(not row['prior_present'] for row in current),
            'unavailable_prior_rows': sum(row['prior_present'] and row['no_context_heads'] is None for row in current),
            'domain_flags': sum(current[i]['domain_disagreement'] for i in paired),
            'aux_flags': sum(current[i]['aux_disagreement'] for i in paired),
            'any_flags': sum(current[i]['status'] == 'UNRESOLVED' for i in paired),
            'domain_flag_coverage': ratio(sum(current[i]['domain_disagreement'] for i in paired), len(paired)),
            'active_known_domain_retained': len(retained), 'active_known_domain_rows': len(known_rows),
            'active_domain_retained_coverage': ratio(len(retained), len(known_rows)),
            'active_domain_retained_error_rows': sum(active_error(i) for i in retained),
            'active_domain_retained_error_rate': ratio(sum(active_error(i) for i in retained), len(retained)),
            'all7_known_joint_correct_including_disabled': len(joint_all7),
            'heads': head_metrics, 'groups': groups,
            'group_macro_domain_flag_fraction': sum(ratio(g['domain_flags'], g['paired']) or 0 for g in groups.values()) / len(groups),
            'repeat_count': 1, 'repeat_consistency': 'NOT_TESTED_IN_THIS_AUDIT',
            'scope': 'Same exposed96 /24 authored groups. Labels used only after inference. No independent qualification, promotion, bank or voice claim.'}


def finalize():
    request13 = assist.read_json(RECORDED / 'finetuned-request.json')
    full13 = assist.read_json(OUT / 'recorded13.shared-child.full.json')
    audit13 = assist.read_json(OUT / 'recorded13.shared-child.audit.json')
    audit.validate_audit(audit13, request13, full13)
    oldfull = assist.read_json(RECORDED / 'work/finetuned-evidence.json')
    request96 = assist.read_json(OUT / 'exposed96.request.json')
    full96 = assist.read_json(OUT / 'exposed96.reviewed.full.json')
    audit96 = assist.read_json(OUT / 'exposed96.reviewed.audit.json')
    audit.validate_audit(audit96, request96, full96)
    mapping = assist.read_json(OUT / 'exposed96.current-row-map.json')['mapping']
    diagnostics = diagnostics96(mapping, full96, audit96)
    cases = assist.read_json(ROOT / 'analysis/minilm-v2-independent-probes.json')
    indexed = {(row['call_index'], row['message_index']): row for row in audit96['rows']}
    current = [indexed[(item['call_index'], item['message_index'])] for item in mapping]
    diagnostics['disabled_head_missed_known_positives'] = {
        label: sum(cases[i]['domain_mask'][j] and cases[i]['domain_labels'][j] == 1 for i in range(96))
        for j, label in enumerate(assist.DOMAIN) if audit.THRESHOLDS[j] > 1}
    diagnostics['raw_point5_joint'] = {
        arm: {'correct': sum(all(not cases[i]['domain_mask'][j] or
            (current[i][arm][label]['probability'] >= .5) == bool(cases[i]['domain_labels'][j])
            for j, label in enumerate(assist.DOMAIN)) for i in range(96)), 'denominator': 96}
        for arm in ('full_heads', 'no_context_heads')}
    active = [value for value in diagnostics['heads'].values() if value['enabled'] and value['known_paired']]
    diagnostics['known_enabled_head_micro_flag_precision'] = sum(h['flagged_full_errors'] for h in active) / sum(h['flags'] for h in active)
    diagnostics['known_enabled_head_micro_error_capture_recall'] = sum(h['flagged_full_errors'] for h in active) / sum(h['full_errors'] for h in active)
    diagnostics['known_enabled_head_micro_positive_precision'] = sum(h['correct_positive_proposals'] for h in active) / sum(h['positive_proposals'] for h in active)
    previous = assist.read_json(OUT / 'exposed96.audit.json')
    diagnostics['repeat_pair_scores_exactly_equal'] = all(
        before['full_heads'] == after['full_heads'] and before['no_context_heads'] == after['no_context_heads']
        for before, after in zip(previous['rows'], audit96['rows']))
    diagnostics['repeat_count'] = 2
    diagnostics['repeat_consistency'] = 'EXACT_SCORES_ON_SAME_EXPOSED_INPUTS_NO_ADDED_SUPPORT'
    diagnostics['complete_task_coverage'] = None
    diagnostics['complete_task_coverage_reason'] = 'Audit is per-head evidence; two domain heads disabled. Retained active-head coverage is not complete-task success.'
    save(OUT / 'exposed96.reviewed.diagnostics.json', diagnostics)
    invocations = {name: assist.read_json(OUT / (name + '.invocation.json'))
                   for name in ('recorded13.shared-child', 'exposed96.reviewed')}
    for name, invocation in invocations.items():
        if invocation['returncode'] != 0 or not invocation['source_unchanged_during_child']:
            raise ValueError('Final production invocation not source-stable: ' + name)
    design = assist.read_json(ROOT / 'analysis/minilm-v2-context-design-20261011.json')
    preserved = {}
    for path, expected in design['source_sha256'].items():
        if path == 'competition/builder.py':
            continue
        actual = assist.sha(ROOT / path)
        preserved[path] = {'expected': expected, 'actual': actual, 'unchanged': expected == actual}
    v1pins = {
        'integrations/learned-dialogue/minilm_ft_v1/release.json': 'b373a20d1357d8a7d21594ab8906b55a87713712b18ad5b4d11c389ecf8343fb',
        'integrations/learned-dialogue/minilm_ft_v1/model/manifest.json': '0e8b19305d935c08ec0b25ff9ca42ac556d3474cf6c859a06683988f630350ea',
        'integrations/learned-dialogue/minilm_ft_core.py': '560deaa6344b88b893b0105b48204725e578a0a0fa3acab7fa2f4bdc7173f00f',
        'integrations/learned-dialogue/minilm_ft_eval.py': '7ba86a4b0a088051bb4bd03a329cfc6689aac177a6d57f112bfae0e5b59b37f0',
    }
    for path, expected in v1pins.items():
        actual = assist.sha(ROOT / path)
        preserved[path] = {'expected': expected, 'actual': actual, 'unchanged': expected == actual}
    if not all(value['unchanged'] for value in preserved.values()):
        raise ValueError('Protected source/model pin changed')
    from package_submission import finetuned_files
    packaged = finetuned_files(ROOT)
    changed = ['competition/finetuned_context_audit.py', 'competition/tests/test_finetuned_context_audit.py',
               'competition/builder.py', 'competition/package_submission.py',
               'analysis/minilm-v2-context-auditdata-20261011.py']
    report = {'schema': 'minilm-v2-context-implementation.20261011',
              'finished_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'status': 'IMPLEMENTED_TESTED_ACTUAL_CPU_AUDITS_NO_PROMOTION',
              'changed_source_sha256': {path: assist.sha(ROOT / path) for path in changed},
              'new_reports': ['analysis/minilm-v2-context-implementation-20261011.json',
                              'analysis/minilm-v2-context-implementation-20261011.txt'],
              'auditdata_files_sha256': {path.relative_to(ROOT).as_posix(): assist.sha(path)
                                        for path in OUT.iterdir() if path.is_file()},
              'preserved_source_sha256': preserved,
              'tests': {'invocation': 'python -B -m unittest discover -s competition/tests -p test_*.py',
                        'passed': 119, 'failed': 0, 'seconds': 9.385, 'new_context_tests': 28,
                        'fixture_inference_is_not_actual_evidence': True},
              'package_validation': {'verified_model_runtime_entries': len(packaged), 'versions': ['v1', 'v2'],
                                     'new_helper_in_source_list_and_hash_manifest': True, 'zip_created': False},
              'production_invocations': invocations,
              'recorded13': {'parent_run': RECORDED.name, 'status': audit13['status'], 'rows': len(audit13['rows']),
                             'FULL_exactly_equal_original': assist._digest(full13) == assist._digest(oldfull),
                             'domain_flips': sum(row['domain_disagreement'] for row in audit13['rows']),
                             'aux_flips': sum(row['aux_disagreement'] for row in audit13['rows']),
                             'agreed_rows': sum(row['status'] == 'AGREED' for row in audit13['rows']),
                             'labels_used': False, 'gold_precision': None,
                             'parent_builder_used_old_helper': True, 'new_builder_actual_generation': False},
              'exposed96': diagnostics,
              'integration': {'v2': 'One paired CPU child; FULL strictly verified before audit/prompt; separate artifact pinned before and after builder model.',
                              'v1': 'Original inference child and exact v1 schema preserved.',
                              'classic_off': 'No model child launched.',
                              'auto_v2_promotion': False, 'V2_default_enabled': False,
                              'failure': 'Explicit UNAVAILABLE; never partial agreement; required FULL failures still fail clearly.'},
              'digest_contract': 'base_full_evidence_sha256 binds canonical complete validated FULL JSON; raw request/FULL/audit file hashes also retained in actual data. Other pins bind calls, all model files, runtime, architecture, observed inputs and zero-prior effective inputs.',
              'limitations': ['Same exposed96/24 authored groups; repeats measure stability only, no IID or fresh qualification.',
                              'Auxiliary heads have zero known labels; precision/recall null. Disabled heads remain disabled.',
                              '31/55 domain-retained rows still have active known-domain errors; agreement is not semantic correctness.',
                              'No thresholds, weights, original schema, model release gate, or bank guards changed.',
                              'Parent completed V2 builder used old helper; actual new builder generation and voice/platform evaluation not executed here.',
                              'Source hashes bind local artifacts, not authenticated raw speech or attested inference.',
                              'Python predictor deadlines are between batches; parent must hard-kill at shared wall limit.',
                              'NO_CONTEXT failed before FULL availability produces explicit child/host UNAVAILABLE; no separate successful evidence exists.'],
              'network_calls': 0, 'Freya_calls': 0, 'Modal_calls': 0, 'nativeCLI_calls': 0,
              'bank_authority': False, 'financial_authorization': 'UNKNOWN'}
    save(ROOT / 'analysis/minilm-v2-context-implementation-20261011.json', report)
    text = ('Implemented separate frozen-V2 context audit; existing assist schema/validator unchanged.\n'
            'Changed sources: ' + ', '.join(changed) + '\n'
            'Tests: 119 passed /0 failed; 28 new context tests; 9.385 seconds.\n'
            'Final actual shared-child CPU13: FULL matches original exactly; 8 domain flips, 0 auxiliary flips, 5 agreed rows; no labels.\n'
            'Final actual CPU exposed96: 108 observed rows mapped to 96 current rows; 41 domain flips, 34 auxiliary flips, 63 any-head flips.\n'
            'Domain-retained coverage 55/96 (57.29%); 31/55 retained rows have active known-domain errors (56.36%).\n'
            'Known enabled flagged-head error precision 32/44 (72.73%); error capture 32/105 (30.48%).\n'
            'Known enabled positive consensus precision 50/61 (81.97%); per-head counts/coverage/recall in JSON.\n'
            'All7 known-domain pinned-threshold joint correctness 19/96 includes disabled misses; raw0.5 diagnostic reported separately.\n'
            'Aux known labels=0; disabled affirm/withdraw precision null. No complete-task coverage or financial authority claim.\n'
            'Both final child invocations bind unchanged helper source and share hard60s wall; exact commands/logs/hashes in auditdata and JSON.\n'
            'V2 consumes separate validated audit after FULL; V1/classic/off preserved; package includes new helper and verifies23 frozen model/runtime entries.\n'
            'Same exposed96/24 authored groups, two stability runs without added support. No promotion, retraining, new dataset, hosted, voice or bank score.\n'
            'Parent V2 completed with old helper; parent owns current builder execution/review. Existing parent reports/runs/state untouched.\n')
    with (ROOT / 'analysis/minilm-v2-context-implementation-20261011.txt').open('x', encoding='utf8') as stream:
        stream.write(text)
    print(json.dumps({'report': 'analysis/minilm-v2-context-implementation-20261011.json',
                      'preserved_pins': len(preserved), 'tests_passed': 119}), flush=True)


def main():
    OUT.mkdir(exist_ok=False)
    recorded()
    requestpath, mapping = translate96()
    fullpath, auditpath = OUT / 'exposed96.full.json', OUT / 'exposed96.audit.json'
    run_child(['--request', str(requestpath), '--output', str(fullpath), '--audit-output', str(auditpath)], 'exposed96')
    if fullpath.exists() and auditpath.exists():
        full, envelope = assist.read_json(fullpath), assist.read_json(auditpath)
        audit.validate_audit(envelope, assist.read_json(requestpath), full)
        summary = diagnostics96(mapping, full, envelope)
        save(OUT / 'exposed96.diagnostics.json', summary)
        print(json.dumps({key: summary[key] for key in ('status', 'exposed_cases', 'paired_prior_rows',
                        'domain_flags', 'aux_flags', 'active_domain_retained_coverage',
                        'active_domain_retained_error_rows', 'all7_known_joint_correct_including_disabled')}), flush=True)


if __name__ == '__main__':
    main()
