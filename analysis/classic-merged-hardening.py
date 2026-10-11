"""Read-only literal-source probes; only writes classic-merged-hardening.json/.txt.

The guide edit is an instruction change, not a regenerated workflow. These probes
retain pre-existing source failures and receipt controls without patching it.
Run with python -B analysis/classic-merged-hardening.py.
"""
import ast
import copy
import datetime
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFIX = ROOT / 'analysis/classic-merged-hardening'
GUIDE = ROOT / 'competition/skills/build-phone-agent.md'
RUN = ROOT / 'competition/runs/20261011-141710-d6397a'
BASE = json.loads(PREFIX.with_name('classic-merged-hardening.baseline.json').read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


workflow = json.loads((RUN / 'work/workflow.json').read_text(encoding='utf-8-sig'))
source = workflow['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
source_sha = hashlib.sha256(source.encode()).hexdigest()
assert source_sha == 'fc6b7b9845041766b5881893032271b37a3dc696e997f2d04b27b22d1d63a846'
tree = ast.parse(source)
assert all(a.name in ('json', 're', 'datetime') for n in ast.walk(tree)
           if isinstance(n, ast.Import) for a in n.names)
assert not any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree))
compiled = compile(source, 'unchanged-local-classic-embedded-controller', 'exec')
pure_tree = ast.parse(source)
pure_tree.body = [n for n in pure_tree.body if isinstance(n, (ast.Import, ast.Assign, ast.FunctionDef))]
pure = {}
exec(compile(pure_tree, 'unchanged-local-classic-source-units', 'exec'), pure)
executions = 0
observations = []


class Store:
    def __init__(self, snapshot=None):
        self.v = copy.deepcopy(snapshot) if snapshot is not None else {
            'customer_id': 'CPU-SYNTHETIC-REVIEW', 'first_name': 'Riley', 'last_name': 'Vale',
            'title': 'Mx', 'now': '2026-10-14T11:00'}
        self.trace = []
        if snapshot is None:
            self.execute()

    def state(self):
        return json.loads(self.v['state'])

    def execute(self):
        global executions
        exec(compiled, {'vars': self.v})
        executions += 1
        s = self.state()
        self.trace.append({'route': self.v['route'], 'phase': s['phase'],
                           'line': self.v['dialogue_line'], 'op': copy.deepcopy(s.get('op', {})),
                           'readback': copy.deepcopy(s.get('readback', [])),
                           'products': [{'id': p['product_id'], 'status': p['status'],
                                         'noted': p.get('noted', False)} for p in s['products']]})

    def turn(self, raw, kind, target='current', complete='1', **fields):
        row = dict(k=kind, c=complete, p=target, s=raw, **fields)
        wire = '|'.join(k + '=' + str(v) for k, v in row.items()) + '\nEND'
        self.v.update(speech=raw, event=wire, admin='')
        self.execute()

    def receipt(self, data, advance_counter=True):
        name = self.state()['op']['name']
        counter = 'api_' + name + ('_success_count' if data.get('ok') else '_failure_count')
        if advance_counter:
            self.v[counter] = int(self.v.get(counter, 0)) + 1
        self.v.update(receipt_op=name, receipt=json.dumps(data), speech='', event='', admin='')
        self.execute()


def observe(label, expected, passed, store=None, actual=None, classification='literal-source-control'):
    observations.append({'id': label, 'expected': expected, 'pass': bool(passed),
                         'classification': classification,
                         'actual': copy.deepcopy(store.trace[-1]) if store else actual,
                         'trace': copy.deepcopy(store.trace) if store else None})


products = [{'product_id': 'cpu-card', 'type': 'credit_card', 'label': 'credit card ending 2718'},
            {'product_id': 'cpu-loan', 'type': 'personal_loan', 'label': 'personal loan'}]
for kind, raw, expected in [
    ('paid', 'I paid my credit card overdue amount.', True),
    ('paid', 'I paid my credit card overdue amount, but I still owe that same overdue amount.', False),
    ('dispute', 'I never had the personal loan.', True),
    ('dispute', 'This personal loan is not mine.', True),
    ('dispute', 'I dispute the personal loan.', True),
    ('dispute', 'I do not dispute the personal loan.', False)]:
    p = products[0 if kind == 'paid' else 1]
    span = raw.split(', but')[0]
    row = {'k': kind, 'p': p['product_id'], 's': span}
    actual = pure['claim_source'](row, p, raw, products)
    observe('claim/' + raw, expected, actual == expected, actual=actual,
            classification='inconsistent-producer-robustness' if ', but' in raw else 'conforming-source-unit')

s = Store(); s.turn('Yes', 'recipient')
s.turn('4 May...', 'security', complete='0', u='date')
observe('DOB/partial-no-comparison', 'No incomplete comparison or bank verification.',
        s.v['route'] != 'api_verify_identity' and not s.state()['verified'], store=s)
s.turn('nineteen eighty-seven', 'security', d='1987-05-04')
observe('DOB/same-answer-fragment-completion', 'Retained day/month plus explicit year prepares exactly 1987-05-04.',
        s.v['route'] == 'api_verify_identity' and s.v.get('request_answer') == '1987-05-04', store=s,
        classification='proposed-fragment-contract-source-probe')
s = Store(); s.turn('Yes', 'recipient'); s.turn('4 May 1987', 'security', d='1987-05-04')
observe('DOB/complete-control', 'Complete current self DOB prepares a comparison, not verification.',
        s.v['route'] == 'api_verify_identity' and not s.state()['verified'], store=s)


def account():
    s = Store(); s.turn('Yes', 'recipient'); s.turn('4 May 1987', 'security', d='1987-05-04')
    s.receipt({'ok': True, 'verified': True, 'all_verified': False, 'wrong_answers_left': 3})
    s.turn('2718', 'security', t='2718')
    s.receipt({'ok': True, 'verified': True, 'all_verified': True, 'wrong_answers_left': 3})
    s.receipt({'ok': True, 'products': [
        {'product_id': 'cpu-card', 'type': 'credit_card', 'card_last4': '2718', 'past_due': 400, 'minimum_payment': 100, 'days_late': 4},
        {'product_id': 'cpu-loan', 'type': 'personal_loan', 'past_due': 600, 'instalment_amount': 200, 'days_late': 20}]})
    return s


base = account().v
def ready():
    s = Store(base); s.turn('Yes', 'accept', target='all')
    assert s.v['phase'] == 'confirm' and s.v['route'] == 'listen'
    return s

s = ready(); s.turn('I withdraw my confirmation.', 'withdraw', target='all')
observe('consent/withdraw-no-write', 'Withdrawal retains terms and issues no promise request.',
        s.v['route'] != 'api_create_promise' and all(p['status'] == 'pending' for p in s.state()['products']), store=s)
s = ready(); s.turn('Please stop for a moment.', 'stop'); s.turn('Yes', 'confirm', target='all')
observe('consent/continue-is-not-payment-confirmation', 'Yes to continuation cannot reuse the old payment question.',
        s.v['route'] != 'api_create_promise', store=s, classification='inconsistent-producer-robustness')
s = ready(); s.turn('Yes', 'confirm', target='all')
s.receipt({'ok': True, 'promise_id': 'CPU-UNBOUND'}, advance_counter=False)
observe('receipt/stale-promise-does-not-record', 'Unbound receipt cannot set a recorded promise.',
        not any(p['status'] == 'recorded' for p in s.state()['products']), store=s,
        classification='synthetic-stale-receipt-control')
s = ready(); s.turn('Yes', 'confirm', target='all')
for i in range(2): s.receipt({'ok': True, 'promise_id': 'CPU-CURRENT-' + str(i)})
observe('receipt/current-promises-control', 'Current successes precede recorded outcome.',
        s.state()['outcome'] == 'promise' and all(p['status'] == 'recorded' for p in s.state()['products']), store=s,
        classification='synthetic-current-receipt-control')
s = Store(base); s.turn('I dispute all my bank products.', 'dispute', target='all')
assert s.v['route'] == 'api_add_note'
s.receipt({'ok': False, 'error': 'service_unavailable'})
s.receipt({'ok': False, 'error': 'service_unavailable'})
attempted = {t['op']['body']['product_id'] for t in s.trace if t['op'].get('name') == 'add_note'}
observe('notes/failed-first-note-retains-sibling', 'A failed first note does not skip the other required product note.',
        attempted == {'cpu-card', 'cpu-loan'} and not any(p.get('noted') for p in s.state()['products']), store=s,
        classification='synthetic-note-failure-obligation-probe')
s = Store(base); s.turn('I dispute all my bank products.', 'dispute', target='all')
for _ in range(2): s.receipt({'ok': True})
observe('notes/current-receipts-control', 'Both successful receipts precede note-based closure.',
        s.v['route'] == 'end' and all(p.get('noted') for p in s.state()['products']), store=s,
        classification='synthetic-current-receipt-control')

guide_bytes = GUIDE.read_bytes()
current_lines = guide_bytes.decode('utf-8').splitlines()
changed = [i + 1 for i, line in enumerate(current_lines)
           if hashlib.sha256(line.encode()).hexdigest() != BASE['guide_line_sha256_before'][i]]
assert changed == BASE['changed_line_numbers'] == [134, 172, 179, 185]
assert len(current_lines) == len(BASE['guide_line_sha256_before'])
assert guide_bytes.count(b'\r\n') == BASE['before_CRLF'] == guide_bytes.count(b'\n')
assert sha(GUIDE) == BASE['guide_sha256_after']
protected_after = {p: sha(ROOT / p) for p in BASE['protected_hashes']}
status = json.loads((RUN / 'status.json').read_text(encoding='utf-8'))
report = {
    'scope': 'Four localized merged-guide paragraph edits; unchanged candidate literal CPU witnesses.',
    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'guide_before_sha256': BASE['guide_sha256_before'], 'guide_after_sha256': sha(GUIDE),
    'edited_paragraph_lines': changed, 'all_other_guide_lines_unchanged': True, 'CRLF_preserved': True,
    'recipient_policy_and_prior_financial_blocks_preserved': True,
    'source': {'path': str((RUN / 'work/workflow.json').relative_to(ROOT)),
               'workflow_sha256': sha(RUN / 'work/workflow.json'), 'embedded_code_sha256': source_sha,
               'node': 'controller', 'run_status': status['phase'], 'published_version': None,
               'limitation': 'Pre-merge failed local classic candidate, not regenerated from the new guide.'},
    'counts': {'CPU_checks': len(observations), 'passed_controls': sum(x['pass'] for x in observations),
               'remaining_source_counterexamples': sum(not x['pass'] for x in observations),
               'literal_controller_executions': executions},
    'observations': observations,
    'protected_hashes_before': BASE['protected_hashes'], 'protected_hashes_after': protected_after,
    'protected_unchanged': protected_after == BASE['protected_hashes'],
    'limits': ['No Git, HTTP, platform, credentials, model fit, official score or candidate modification.',
               'Synthetic receipt controls do not demonstrate hosted behavior or financial success.',
               'Unit-source and proposed cross-turn fragment probes are distinct from actual extractor observations.',
               'Guide edits require a future automatic generation and behavioral validation; old-source failures are retained.',
               'Parent owns the merged builder checks; they are not run or claimed by this reviewer.']}
PREFIX.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
summary = ['MERGED CLASSIC GUIDE HARDENING',
           'Edited existing paragraphs 134,172,179,185 only; all other guide lines and CRLF preserved.',
           '1. Act/operand scope: positive ownership-denial disputes; per-target corrected paid claims; same-question DOB fragment provenance and explicit buffer clearing.',
           '2. Authorization/effect lifetime: suspend payment permission on pause/other question; fresh later confirmation; retain sibling note obligations after bounded failure; policy-derived transfer/terminal handling.',
           'Permissive first/surname/bare-yes recipient gate, mandatory bank security, current successful receipt gates and all other financial safety paragraphs preserved.',
           json.dumps(report['counts']), 'Protected files unchanged: ' + str(report['protected_unchanged']),
           'CPU source is the unchanged failed/unpublished local comparison, not a regenerated or hosted workflow.',
           'Remaining source counterexamples:']
summary += [x['id'] + ' | ' + x['classification'] for x in observations if not x['pass']]
summary += report['limits']
PREFIX.with_suffix('.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
print(json.dumps({'counts': report['counts'], 'edited_lines': changed,
                  'protected_unchanged': report['protected_unchanged'],
                  'failure_ids': [x['id'] for x in observations if not x['pass']]}))
