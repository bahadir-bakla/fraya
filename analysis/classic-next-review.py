"""Literal local classic-source witnesses; writes only classic-next-review.json/.txt.

No candidate patch, imports of builder/test modules, HTTP, platform, or score execution.
Run: python -B analysis/classic-next-review.py
"""
import ast
import copy
import datetime
import hashlib
import json
import pathlib
import re
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
START = time.monotonic()
OUT = ROOT / 'analysis/classic-next-review'
B_RUN = ROOT / 'competition/runs/20261011-141710-d6397a'
A_RUN = ROOT / 'competition/runs/20261011-123411-65d0e4'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def embedded(run, node):
    w = load(run / 'work/workflow.json')
    code = w['nodes'][node]['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    tree = ast.parse(code)
    assert all(a.name in ('json', 're', 'datetime') for n in ast.walk(tree)
               if isinstance(n, ast.Import) for a in n.names)
    assert not any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree))
    return code


B_CODE = embedded(B_RUN, 'controller')
A_CODE = embedded(A_RUN, 'dispatch')
B_COMPILED = compile(B_CODE, 'literal-local-classic-B-embedded-controller', 'exec')
A_TREE = ast.parse(A_CODE)
A_TREE.body = [n for n in A_TREE.body if isinstance(n, (ast.Import, ast.FunctionDef, ast.Assign))]
A_NS = {}
exec(compile(A_TREE, 'literal-local-classic-A-definitions', 'exec'), A_NS)
protected = list((ROOT / 'competition/releases/classic-baseline').glob('*'))
protected += list((ROOT / 'analysis').glob('official-*.json'))
protected += list((ROOT / 'analysis').glob('official-*.txt'))
protected += [ROOT / 'analysis/day2-official-a-v11.json', ROOT / 'analysis/day2-official-a-v11.txt',
              ROOT / 'competition/builder.py', ROOT / 'competition/skills/build-phone-agent.md']
for run in (A_RUN, B_RUN):
    protected += [run / 'status.json', run / 'work/workflow.json', run / 'work/controller.py',
                  run / 'work/policy.json']
for name in ('briefs/brief-a.md', 'briefs/brief-b.md', 'public-test-set.json',
             'tools/openapi.json', 'tools/score.py'):
    protected.append(ROOT / 'competition-v3/build-the-builder' / name)
before = {p.relative_to(ROOT).as_posix(): digest(p) for p in protected if p.is_file()}
observations = []
literal_executions = 0


class Store:
    def __init__(self, snapshot=None, first='Avery', last='Stone', title='Dr'):
        self.v = copy.deepcopy(snapshot) if snapshot is not None else {
            'customer_id': 'CPU-NEUTRAL-001', 'first_name': first, 'last_name': last,
            'title': title, 'now': '2026-10-14T11:00'}
        self.trace = []
        if snapshot is None:
            self.execute()

    def execute(self):
        global literal_executions
        # All mutation stays in the synthetic persistent variable store.
        exec(B_COMPILED, {'vars': self.v})
        literal_executions += 1
        st = self.state()
        self.trace.append({'route': self.v.get('route'), 'phase': st.get('phase'),
                           'speech': self.v.get('dialogue_line'),
                           'op': copy.deepcopy(st.get('op', {})),
                           'readback': copy.deepcopy(st.get('readback', [])),
                           'products': [{'id': p['product_id'], 'status': p['status'],
                                         'noted': p.get('noted', False), 'needs': p.get('needs', [])}
                                        for p in st.get('products', [])]})

    def state(self):
        return json.loads(self.v.get('state', '{}'))

    def turn(self, raw, kind=None, target='current', complete='1', source=None, rows=None, **fields):
        if rows is None:
            rows = [] if kind is None else [dict(k=kind, c=complete, p=target,
                                                s=raw if source is None else source, **fields)]
        def escape(x):
            return str(x).replace('%', '%25').replace('|', '%7C').replace('\n', '%0A')
        wire = '\n'.join('|'.join(k + '=' + escape(val) for k, val in row.items()) for row in rows) + '\nEND' if rows else ''
        self.v.update(speech=raw, event=wire, admin='')
        self.execute()
        return {'raw': raw, 'wire': wire}

    def receipt(self, data):
        op = self.state()['op']['name']
        counter = 'api_' + op + ('_success_count' if data.get('ok') else '_failure_count')
        self.v[counter] = int(self.v.get(counter, 0)) + 1
        self.v.update(receipt=json.dumps(data), receipt_op=op, event='', speech='', admin='')
        self.execute()


def observe(label, store, expected, passed, inputs=None, classification='conforming_source_CPU'):
    observations.append({'id': label, 'classification': classification, 'expected': expected,
                         'pass': bool(passed), 'inputs': inputs,
                         'actual': copy.deepcopy(store.trace[-1]), 'trace': copy.deepcopy(store.trace)})


def unit(label, actual, expected, passed, classification='literal_source_unit_CPU'):
    observations.append({'id': label, 'classification': classification, 'expected': expected,
                         'actual': actual, 'pass': bool(passed)})


def source_meta(run, code, node):
    status = load(run / 'status.json')
    helper = (run / 'work/controller.py').read_text(encoding='utf-8-sig')
    return {'run': run.relative_to(ROOT).as_posix(), 'slot': status['slot'],
            'status': status['phase'], 'error': status.get('error'),
            'published_version': None, 'version_note': 'Local failed build; no version or hosted qualification assigned.',
            'workflow_sha256': digest(run / 'work/workflow.json'),
            'embedded_node': node, 'embedded_code_sha256': hashlib.sha256(code.encode()).hexdigest(),
            'helper_file_sha256': digest(run / 'work/controller.py'),
            'helper_equals_embedded': helper.strip() == code.strip(),
            'functions': {n.name: [n.lineno, n.end_lineno] for n in ast.walk(ast.parse(code)) if isinstance(n, ast.FunctionDef)}}


for raw in ['Yes', 'Yes.', 'Speaking', 'Speaking.', "That's me.", 'Dr Stone.',
            'Stone, Avery.', 'This is Dr Stone, Avery.']:
    s = Store(); inp = s.turn(raw, 'recipient')
    observe('recipient/positive/' + raw, s, 'Advance only to DOB, without bank verification.',
            s.state()['phase'] == 'dob' and not s.state()['verified'], inp)
for first, last, title, raw in [('Léa', 'O’Neil', 'Ms', "This is Ms O'Neil, Léa."),
                               ('Anne-Marie', 'Quinn', 'Dr', 'This is Dr Anne-Marie Quinn.')]:
    s = Store(first=first, last=last, title=title); inp = s.turn(raw, 'recipient')
    observe('recipient/name-components/' + raw, s, 'Normalize supplied names symmetrically.', s.state()['phase'] == 'dob', inp)
for raw in ['Yes, this is Avery.', 'Avery here.', "I just said, that's me."]:
    s = Store(); inp = s.turn(raw, 'recipient')
    observe('recipient/friend-natural-self-answer/' + raw, s, 'Scoped configured first name or repeated present self-confirmation advances only to security.',
            s.state()['phase'] == 'dob' and not s.state()['verified'], inp, 'friend_proposed_low_risk_contract_CPU')
s = Store(); inp = s.turn('This is Dr Stone, Avery; could you tell me who employs you?', None)
observe('recipient/missing-event-independent-question', s, 'Complete self name survives an independent question.',
        s.state()['phase'] == 'dob', inp, 'missing_event_raw_recovery_CPU')
for raw, source in [('Yes, I am his sister.', 'Yes'), ('I am not Avery Stone.', 'Avery Stone'),
                    ('He said "Yes".', 'Yes')]:
    s = Store(); inp = s.turn(raw, 'recipient', source=source)
    observe('recipient/whole-turn-veto/' + raw, s, 'Nonself/negated/quoted current turn cannot advance.',
            s.state()['phase'] != 'dob', inp, 'forced_semantic_inconsistent_producer_CPU')
for raw in ['This is Blair Stone.', 'This is Ms Avery Stone.', 'If I were Avery Stone.']:
    s = Store(); inp = s.turn(raw, 'recipient')
    observe('recipient/negative/' + raw, s, 'Wrong name/title and hypothetical remain blocked.',
            s.state()['phase'] != 'dob', inp, 'forced_semantic_inconsistent_producer_CPU')


def account():
    s = Store(); s.turn('Yes', 'recipient')
    s.turn('12 March 1984', 'security', d='1984-03-12')
    assert s.v['route'] == 'api_verify_identity'
    s.receipt({'ok': True, 'verified': True, 'all_verified': False, 'wrong_answers_left': 3})
    s.turn('0742', 'security', t='0742')
    assert s.v['route'] == 'api_verify_identity'
    s.receipt({'ok': True, 'verified': True, 'all_verified': True, 'wrong_answers_left': 3})
    assert s.v['route'] == 'api_get_account'
    s.receipt({'ok': True, 'products': [
        {'product_id': 'cpu-card', 'type': 'credit_card', 'card_last4': '8841', 'past_due': 400, 'minimum_payment': 100, 'days_late': 4},
        {'product_id': 'cpu-personal', 'type': 'personal_loan', 'past_due': 600, 'instalment_amount': 200, 'days_late': 20},
        {'product_id': 'cpu-car', 'type': 'car_loan', 'past_due': 800, 'instalment_amount': 250, 'days_late': 12}]})
    assert s.state()['verified'] and s.v['phase'] == 'collective'
    return s


base = account().v
def ready():
    s = Store(base); s.turn('Yes', 'accept', target='all')
    assert s.v['phase'] == 'confirm' and s.v['route'] == 'listen'
    return s

for raw, expected in [('Yes, no problem.', True), ('I agree to the current payment promise.', True),
                      ('Yes, I agree to the callback.', False), ('My assistant said yes.', False),
                      ('Yesterday I confirm.', False), ("Yes, I don't agree.", False), ('"Yes, I confirm."', False)]:
    s = ready(); inp = s.turn(raw, 'confirm', target='all')
    observe('consent/scope/' + raw, s, 'Promise request only for present self assent to the current payment readback.',
            (s.v['route'] == 'api_create_promise') == expected and not any(p['status'] == 'recorded' for p in s.state()['products']),
            inp, 'conforming_source_CPU' if expected else 'forced_semantic_inconsistent_producer_CPU')
s = ready(); s.turn('Please stop for a moment.', 'stop')
inp = s.turn('Yes', 'confirm', target='all')
observe('consent/pause-continuation-is-not-payment-consent', s, 'Yes to May we continue must not authorize the old payment readback.',
        s.v['route'] != 'api_create_promise', inp, 'forced_semantic_inconsistent_producer_CPU')
s = ready(); s.turn('Yes, I confirm.', 'confirm', target='all')
for i in range(3): s.receipt({'ok': True, 'promise_id': 'CPU-PROMISE-' + str(i)})
observe('consent/three-current-promise-receipts', s, 'Three bound successes precede recorded outcome and required SMS notice.',
        s.v['route'] == 'end' and s.state()['outcome'] == 'promise' and all(p['status'] == 'recorded' for p in s.state()['products'])
        and 'You will receive a text message confirming this promise.' in s.v['dialogue_line'])
s = Store(base); s.turn('I want a new payment plan.', 'restructure')
s.receipt({'ok': True})
observe('obligations/transfer-no-notes', s, 'Restructuring transfers with zero note dispatch and no unrecorded promises.',
        s.state()['outcome'] == 'transferred' and not any(t['op'].get('name') == 'add_note' for t in s.trace))

s = ready(); inp = s.turn('Actually, make the amount two hundred...', 'proposal', complete='0', u='amount', target='personal_loan')
observe('amount/fragment-recovery', s, 'No amount solicitation or bank write; unresolved amount blocks old consent.',
        s.v['route'] == 'listen' and not re.search(r'(?:how much|what amount|finish.*amount|complete.*amount)', s.v['dialogue_line'], re.I), inp)
inp = s.turn('On 21 October.', 'proposal', target='personal_loan', d='21 October 2026')
observe('amount/date-does-not-fill-fragment', s, 'Date alone cannot fill an unfinished amount.',
        s.v['route'] != 'api_create_promise' and 'amount' in s.state()['products'][1]['needs'], inp)

for raw, source in [('I already paid my credit card overdue amount.', 'I already paid my credit card overdue amount'),
                    ('I already paid my credit card overdue amount, but I still owe that same overdue amount.', 'I already paid my credit card overdue amount')]:
    s = Store(base); inp = s.turn(raw, 'paid', target='credit_card', source=source)
    expected = 'but' not in raw
    observe('paid/whole-turn/' + raw, s, 'Only a current uncontradicted bank-debt claim becomes paid.',
            (s.state()['products'][0]['status'] == 'paid') == expected, inp,
            'conforming_source_CPU' if expected else 'forced_semantic_inconsistent_producer_CPU')

for raw in ['I never had the personal loan.', 'This personal loan is not mine.']:
    s = Store(base); inp = s.turn(raw, 'dispute', target='personal_loan')
    observe('dispute/supported-negative-ownership/' + raw, s, 'A complete ownership denial is a positive dispute act.',
            s.state()['products'][1]['status'] == 'dispute', inp)

s = Store(base)
raw = 'I paid my credit card overdue amount; I dispute the personal loan; I dispute the car loan.'
inp = s.turn(raw, rows=[{'k': 'paid', 'c': '1', 'p': 'credit_card', 's': 'I paid my credit card overdue amount'},
                        {'k': 'dispute', 'c': '1', 'p': 'personal_loan', 's': 'I dispute the personal loan'},
                        {'k': 'dispute', 'c': '1', 'p': 'car_loan', 's': 'I dispute the car loan'}])
assert s.v['route'] == 'api_add_note'
s.receipt({'ok': False, 'error': 'service_unavailable'})
s.receipt({'ok': False, 'error': 'service_unavailable'})
attempted = {t['op'].get('body', {}).get('product_id') for t in s.trace if t['op'].get('name') == 'add_note'}
observe('obligations/note-failure-keeps-sibling-obligations', s,
        'After bounded failure of one note, attempt other mandatory product notes before closure.',
        attempted == {'cpu-card', 'cpu-personal', 'cpu-car'}, inp, 'synthetic_documented_failure_receipts_CPU')
s = Store(base); s.turn(raw, rows=[{'k': 'paid', 'c': '1', 'p': 'credit_card', 's': 'I paid my credit card overdue amount'},
                                 {'k': 'dispute', 'c': '1', 'p': 'personal_loan', 's': 'I dispute the personal loan'},
                                 {'k': 'dispute', 'c': '1', 'p': 'car_loan', 's': 'I dispute the car loan'}])
for _ in range(3): s.receipt({'ok': True})
observe('obligations/three-current-note-receipts', s, 'All three successful note receipts precede no-promise/dispute closure.',
        s.v['route'] == 'end' and all(p.get('noted') for p in s.state()['products']) and s.state()['outcome'] == 'no_promise')

for raw, canonical in [('04/05/1987', '1987-05-04'), ('April the seventeenth, in the year 1987', '1987-04-17'),
                       ('The seventeenth of April of nineteen eighty-seven', '1987-04-17')]:
    s = Store(); s.turn('Yes', 'recipient'); inp = s.turn(raw, 'security', d=canonical)
    observe('date/DOB-complete/' + raw, s, 'Complete self DOB projects exact DMY/word date without establishing identity.',
            s.v['route'] == 'api_verify_identity' and s.v.get('request_answer') == canonical and not s.state()['verified'], inp)
for raw in ['My sister was born on 12 March 1984.', '12 March nineteen...', '"12 March 1984"']:
    s = Store(); s.turn('Yes', 'recipient'); inp = s.turn(raw, 'security', d='1984-03-12')
    observe('date/DOB-negative/' + raw, s, 'Nonself/incomplete/quoted DOB cannot dispatch.',
            s.v['route'] != 'api_verify_identity', inp, 'forced_semantic_inconsistent_producer_CPU')
s = Store(); s.turn('Yes', 'recipient')
inp = s.turn('I will not share my birth date.', 'security', source='12 March 1984', d='1984-03-12')
observe('date/DOB-source-absent-from-turn', s, 'An invented source span cannot initiate a comparison.',
        s.v['route'] != 'api_verify_identity', inp, 'forced_semantic_inconsistent_producer_CPU')
s = Store(); s.turn('Yes', 'recipient'); s.turn('04/05/1987', 'security', d='1987-05-04')
s.receipt({'ok': True, 'verified': False, 'all_verified': False, 'hint': 'day_month_swapped', 'wrong_answers_left': 3})
observe('date/DOB-bank-swap-hint', s, 'Ask for the month as a word; do not silently swap or verify.',
        s.v['phase'] == 'dob' and 'month as a word' in s.v['dialogue_line'] and not s.state()['verified'])
s = Store(); s.turn('Yes', 'recipient'); s.turn('12 March 1984', 'security', d='1984-03-12')
s.receipt({'ok': True, 'verified': True, 'all_verified': False, 'wrong_answers_left': 3})
inp = s.turn('44...', None)
observe('date/security-fragment-no-premature-comparison', s, 'Two unfinished self-phone digits prepare no comparison.',
        s.v['route'] != 'api_verify_identity', inp, 'missing_event_raw_recovery_CPU')
inp = s.turn('71.', None)
observe('date/security-fragment-completion', s, 'Current question-bound explicit fragments 44 then 71 can project 4471 without guessing.',
        s.v['route'] == 'api_verify_identity' and s.v.get('request_answer') == '4471', inp, 'friend_proposed_fragment_contract_CPU')
ns = {}; tree = ast.parse(B_CODE); tree.body = [n for n in tree.body if isinstance(n, (ast.Import, ast.Assign, ast.FunctionDef))]
exec(compile(tree, 'literal-classic-B-date-unit', 'exec'), ns)
for raw, expected in [('next Friday', '2026-10-23'), ('Friday 23 October 2026', '2026-10-23'), ('Thursday 23 October 2026', None)]:
    try: actual = ns['datevalue'](raw, datetime.date(2026, 10, 14)).isoformat()
    except ValueError: actual = None
    unit('date/payment/' + raw, actual, expected, actual == expected)

state_a = {'product': {'type': 'credit_card', 'card_last4': '8841', 'label': 'credit card ending 8841'},
           'phase': 'readback', 'verified': True, 'pending': {'amount': 220, 'date': '2026-10-20'},
           'readback': {'amount': 220, 'date': '2026-10-20'}}
for raw, expected in [("I've already processed the payment through the app this morning.", True),
                      ('I actually paid it in the app.', True), ('I made the payment through the app.', True),
                      ('Last March I paid it.', False), ('I paid it today, but I did not actually pay this overdue amount.', False)]:
    actual = A_NS['disposition_source'](raw, 'paid', state_a)
    unit('A-latest-local/paid/' + raw, actual, expected, actual == expected)
for component in ('amount', 'both', 'unknown'):
    st = copy.deepcopy(state_a); st['pending'].update(incomplete=True, missing=component)
    actual = A_NS['question'](st)
    unit('A-latest-local/amount-recovery/' + component, actual, 'Neutral continuation; no amount elicitation.', actual == 'Please go on.')

after = {p: digest(ROOT / p) for p in before}
findings = [
    {'slice': 1, 'title': 'Recipient punctuation, whole-turn source binding and raw-recovery question split',
     'source': 'B embedded recipient/selfsubject/run',
     'observed': 'Title/surname/inverted/Unicode positives pass. Yes./Speaking./That\'s me. reject, as do configured-first-name and repeated present self-confirmation probes suggested by the friend guide. Quoted/negated/third-party raw with inconsistent short positive rows advances only to DOB; no identity verification.'},
    {'slice': 2, 'title': 'Financial source predicates and policy-compliant incomplete amount recovery',
     'source': 'B embedded claim_source/payments; A embedded disposition_source/question',
     'observed': 'B rejects complete not-mine/never-had disputes and accepts a paid span despite a later unpaid clause. A accepts the three saved paid paraphrases but still accepts I paid it today, but I did not actually pay this overdue amount. Tested neutral A amount recovery and B unfinished amount/date isolation pass.'},
    {'slice': 3, 'title': 'Consent question scope, pause lifetime and outstanding product notes',
     'source': 'B embedded consent_source/payments/finalize/run',
     'observed': 'Inconsistent confirm rows for callback, reported yes, historical confirmation or yes to continuation prepare a synthetic promise request. Two synthetic failures of the first note end the call before sibling notes are attempted. Three successful note receipts preserve expected closure.'},
    {'slice': 4, 'title': 'Complete DOB grammar, current-source binding and separate payment dates',
     'source': 'B embedded datevalue/security_operand/run',
     'observed': 'Two complete spoken-year DOB forms reject; a non-current invented security source prepares a comparison. A friend-proposed two-turn phone-fragment completion is not assembled. Prescribed DMY, bank swap-hint clarification, self/quote/incomplete controls and tested payment weekday conflict guards pass.'}]
report = {'scope': 'Local exact embedded classic source, synthetic CPU stores/receipts only.',
          'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'sources': [source_meta(B_RUN, B_CODE, 'controller'), source_meta(A_RUN, A_CODE, 'dispatch')],
          'counts': {'checks': len(observations), 'passed': sum(x['pass'] for x in observations),
                     'failed': sum(not x['pass'] for x in observations), 'literal_B_controller_executions': literal_executions},
          'protected_hashes_before': before, 'protected_hashes_after': after, 'protected_unchanged': before == after,
          'observations': observations,
          'findings': findings,
          'historical_evidence': {
              'A10': {'file': 'analysis/official-a-v10.json', 'version': 10, 'passed_calls': 29, 'total_calls': 30,
                       'remaining_failure': 'PUB-06 repetition 3, call 95f18c2e-006d-448d-853f-72450d6d4efe: amount solicitation; original bank checks passed.'},
              'A11': {'file': 'analysis/day2-official-a-v11.json', 'version': 11, 'passed_calls': 27, 'total_calls': 30,
                       'remaining_failures': 'PUB-08 repetition 2 paid paraphrase, plus PUB-10 repetitions 1 and 3 conversation judgments about mandatory opening recording notice. PUB-06 passes all three.'},
              'B6_name': {'file': 'analysis/night-b-next6-selected-stress-triage.json', 'version': 6,
                          'finding': 'All three pause/restore authored calls stop at title/surname/given-name recipient recognition, so pause/consent behavior was unexercised.'},
              'limit': 'Historical reports retain their exact version/scope and original verdicts; these CPU probes add no hosted evidence.'},
          'harness_correction': 'Initial note setup exposed candidate rejection of never-had disputes. Used explicit I dispute for isolated note lifecycle and retained ownership-denial failures separately. Corrected A source-unit argument order (raw, kind, state); superseded counts are preserved in classic-next-review.first-pass.json and are not current findings.',
          'limits': ['Typed inconsistent-producer probes are robustness controls, not measured extractor failures.',
                     'Local failed candidate builds have no assigned published version; source-unit A tests are not a persisted A replay.',
                     'No HTTP, bank, hosted, model, score/judge, fetch, push, publication or queue actions.',
                     'Only embedded Python and synthetic variables are executed. Candidate JSON and helper source remain unchanged.'],
          'elapsed_seconds': round(time.monotonic() - START, 3)}
friend_path = OUT.with_name('classic-next-review.friend.json')
if friend_path.exists():
    report['friend_branch_review'] = load(friend_path)
    report['friend_branch_review_sha256'] = digest(friend_path)
OUT.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
summary = ['CLASSIC NEXT LOCAL SOURCE REVIEW', json.dumps(report['counts']),
           'Protected source hashes unchanged: ' + str(report['protected_unchanged']),
           'No hosted or published-candidate qualification.',
           'B: latest available local classic comparison 20261011-141710-d6397a, failed/unpublished; embedded SHA256 fc6b7b9845041766b5881893032271b37a3dc696e997f2d04b27b22d1d63a846. Helper differs materially from embedded candidate.',
           'A: latest available local classic A 20261011-123411-65d0e4, failed/unpublished; embedded SHA256 bbb19d883152bb1a2bd220c54a3d27de23bfbf061cdbca12713e57bb1268cbc7.',
           'The later 20261011-142322-f58d75 candidate belongs to the MiniLM lane and is excluded from classic CPU findings.',
           'Historical A10 PUB06 amount question remains failed; A11 fixes that case but has a paid-paraphrase failure and two recording-notice judge conflicts. Preserve mandatory notice and every original verdict. B6 name gate blocked all pause/restore calls before security.',
           'FOUR ACTIONABLE SLICES']
summary += [str(x['slice']) + '. ' + x['title'] + ': ' + x['observed'] for x in findings]
summary += ['Minimal future automatic-build delta: competition/skills/classic-hardening-next.txt',
            'CPU failures below include deliberately inconsistent producer controls and synthetic receipts; they are not provider failure frequencies.']
if friend_path.exists():
    summary += ['Friend branch pinned: ' + report['friend_branch_review']['pinned_commit'],
                'Committed pre-hardening mock: C raw5/30, adjusted8/30, all-observed-style cases0/10; D raw0/26, cases0/13 over two styles. Missing D pieces/plain controls unobserved. Scorer Git blob hash pinned; no per-call ledger hashes or published-version proof bundled. No post-fix pass claim.',
                'Friend failures: natural recipient cues/missing multipurpose extraction, split security digits, C05 forbidden hardship transfer, C09 wrong general/support queue, C06 pieces wrong date. New delta retains simple phase extraction and every policy-specific action/calendar/notification rule.']
summary += [x['id'] + ' | ' + x['classification'] + ' | ' + str(x['expected']) for x in observations if not x['pass']]
OUT.with_suffix('.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
print(json.dumps({'counts': report['counts'], 'protected_unchanged': before == after,
                  'failed_ids': [x['id'] for x in observations if not x['pass']]}, ensure_ascii=True))
