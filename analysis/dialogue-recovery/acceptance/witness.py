#!/usr/bin/env python3
"""Offline generated-dispatch witness. Executes candidate Python, no model/bank calls.
Seeds post-verification state to isolate conversation transitions; it does NOT
validate extractor or bank receipts. Default reports the immutable baseline bugs.
--require-fixed exits nonzero on any behavioral contract failure.
"""
import argparse, ast, copy, hashlib, json
from pathlib import Path

DEFAULT = '/tmp/fraya-rd-eval-f141ae8/competition/releases/minilm-v2-context-a-20261011/workflow.json'
REVIEW = '/home/yusuf/Masaüstü/fraya/local-runs/customer-benchmark-v2-context-20261011/public-a/failed-call-review.json'

def load_dispatch(path):
    candidates = []
    def walk(x):
        if isinstance(x, dict):
            for value in x.values(): walk(value)
        elif isinstance(x, list):
            for value in x: walk(value)
        elif isinstance(x, str) and 'def run(vars)' in x and 'def readback(s)' in x:
            candidates.append(x)
    walk(json.loads(Path(path).read_text()))
    if len(candidates) != 1:
        raise ValueError('Expected one generated Python dispatch with run(vars) and readback(s); adapt harness explicitly for different generated interfaces.')
    source = candidates[0]
    tree = ast.parse(source)
    # Load original imports/constants/functions without executing workflow entrypoint.
    tree.body = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef))]
    ns = {}
    exec(compile(tree, str(path), 'exec'), ns)
    return ns, source

def seed(ns, amount=420., deadline='2026-10-23'):
    v = {'now': '2026-10-14T10:00:00', 'title': 'Mr', 'last_name': 'Witness', 'customer_id': 'offline-witness'}
    ns['run'](v)
    p = {'product_id': 'p1', 'label': 'credit card ending 4821', 'type': 'credit_card', 'past_due': amount, 'floor': amount*.3, 'deadline': deadline, 'limit': 3}
    v['state'].update(verified=True, dob_passed=True, product=p, products=[p], phase='offer', pending={}, readback=None, offer_revision=0, offer=None)
    # Let each generated runtime initialize its own offer bindings (including
    # current product/revision fields); do not fabricate a stale offer shape.
    v['dialogue_line']=ns['offer'](v['state'],amount,ns['datetime'].date(2026,10,14))
    return v

def turn(ns, v, raw, event):
    v.update(raw=raw, event=event, mode='event', admin='none')
    ns['run'](v)
    return {'raw': raw, 'event': event, 'route': v['route'], 'line': v['dialogue_line'], 'phase': v['state']['phase'], 'pending': copy.deepcopy(v['state']['pending']), 'readback': copy.deepcopy(v['state']['readback'])}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workflow', default=DEFAULT)
    ap.add_argument('--review', default=REVIEW)
    ap.add_argument('--output')
    ap.add_argument('--require-fixed', action='store_true')
    args=ap.parse_args()
    ns,source=load_dispatch(args.workflow)
    checks=[]
    def record(name, ok, rows): checks.append({'contract': name, 'passed': bool(ok), 'turns': rows})
    # Complete payment ability accepting a uniquely spoken offer is not final write consent.
    v=seed(ns); rows=[turn(ns,v,'I can pay the full amount today.','k=agree;c=1;END')]
    record('complete_offer_acceptance_produces_readback_without_write', v['route']=='talk' and v['state']['phase']=='readback' and v['state']['pending'].get('amount')==420. and not v['state']['pending'].get('incomplete'), rows)
    rows.append(turn(ns,v,'Yes, I confirm.','k=confirm;c=1;END'))
    record('distinct_later_consent_can_dispatch_exact_promise',v['route']=='create_promise' and v.get('promise_amount')==420. and v.get('promise_date')=='2026-10-14',rows)
    # Readiness is not a financial authorization; answer with an actionable active offer.
    v=seed(ns); rows=[turn(ns,v,'I am ready.','k=agree;c=1;END')]
    record('readiness_never_writes_or_enters_vague_continuation',v['route']=='talk' and 'continue when you are ready' not in v['dialogue_line'].lower() and not v['state']['pending'].get('incomplete'),rows)
    # Exact observed conditional fragment and recovery utterance. First turn must not write.
    v=seed(ns,1250.); ns['offer'](v['state'],1250.,ns['datetime'].date(2026,10,23))
    rows=[turn(ns,v,"Are you a robot? I'll take that date if",'k=proposal;c=0;u=amount;d=23 October 2026;END')]
    record('unfinished_condition_preserves_terms_but_blocks_write',v['route']=='talk' and v['state']['readback'] is None and 'digital assistant' in v['dialogue_line'].lower(),copy.deepcopy(rows))
    rows.append(turn(ns,v,'I will pay on the twenty-third of October then','k=proposal;c=1;d=twenty-third of October;END'))
    rows.append(turn(ns,v,'Yes, I accept that date.','k=confirm;c=1;END'))
    record('unconditional_offer_restatement_recovers_without_missing_amount_lock',v['state']['phase']=='readback' and not v['state']['pending'].get('incomplete') and v['state']['pending'].get('amount')==1250.,copy.deepcopy(rows))
    # Real amount correction cannot be repaired with unrelated facts or generic yes.
    v=seed(ns); turn(ns,v,'Yes, I agree.','k=agree;c=1;END')
    rows=[turn(ns,v,'Actually, change the amount to one hundred and','k=change;c=0;u=amount;END')]
    before=copy.deepcopy(v['state']['pending'])
    rows.append(turn(ns,v,'My appointment is on 19 October at 2.','k=question;c=1;END'))
    record('unrelated_numbers_do_not_resolve_or_mutate_payment_fragment',v['route']=='talk' and v['state']['pending']==before,copy.deepcopy(rows))
    # If the agent actually spoke a fresh fixed amount question, assent may adopt
    # that offered component, but only as a proposal requiring a new readback.
    offered_line=rows[-1]['line'].lower()
    fresh_amount_offer=('420' in offered_line and ('accept' in offered_line or 'can you pay' in offered_line))
    rows.append(turn(ns,v,'Yes, I confirm.','k=confirm;c=1;END'))
    valid_resolution=(v['state']['phase']=='readback' and v['state']['pending'].get('amount')==420. and not v['state']['pending'].get('incomplete') and v['state']['readback']==v['state']['pending'])
    record('assent_only_resolves_amount_after_actual_fresh_fixed_offer_without_write',v['route']=='talk' and (valid_resolution if fresh_amount_offer else bool(v['state']['pending'].get('incomplete'))),copy.deepcopy(rows))
    consent_v=copy.deepcopy(v);consent_rows=copy.deepcopy(rows)
    consent_rows.append(turn(ns,consent_v,'Yes, I confirm.','k=confirm;c=1;END'))
    permitted_write=consent_v['route']=='create_promise' and consent_v.get('promise_amount')==420.
    record('recovery_offer_adoption_requires_distinct_later_consent',permitted_write if fresh_amount_offer else consent_v['route']!='create_promise',consent_rows)
    rows.append(turn(ns,v,'Two hundred.','k=proposal;c=1;a=200;END'))
    record('explicit_amount_completes_fragment_retaining_original_date',v['route']=='talk' and v['state']['phase']=='readback' and v['state']['pending'].get('amount')==200. and v['state']['pending'].get('date')=='2026-10-14',rows)
    # Boundary state: a real missing amount exists but no fresh amount question
    # was spoken. Old offer cache and generic yes must not silently complete it.
    v=seed(ns);v['state'].update(phase='readback',readback=None,pending={'date':'2026-10-14','incomplete':True,'missing':'amount','required_components':['amount'],'completed_components':[]})
    rows=[turn(ns,v,'Yes, I confirm.','k=confirm;c=1;END')]
    record('generic_yes_without_fresh_amount_offer_cannot_resolve_missing_amount',v['route']=='talk' and bool(v['state']['pending'].get('incomplete')) and v['state']['pending'].get('amount') is None,rows)
    # A recovery offer expires once the customer gives a different complete amount.
    # The following consent answers the latest readback, not an older offer question.
    v=seed(ns); rows=[turn(ns,v,'Yes, I agree.','k=agree;c=1;END')]
    rows.append(turn(ns,v,'Actually, change the amount to one hundred and','k=change;c=0;u=amount;END'))
    rows.append(turn(ns,v,'Two hundred.','k=proposal;c=1;a=200;END'))
    rows.append(turn(ns,v,'Yes, I confirm.','k=confirm;c=1;END'))
    record('completed_correction_consent_uses_latest_readback_not_stale_recovery_offer',v['route']=='create_promise' and v.get('promise_amount')==200. and v['state']['pending'].get('amount')==200.,rows)
    # Intentionally misleading producer affirmative labels must never bypass source guards.
    for raw in ['No, I cannot pay today.', 'I do not confirm.', 'She said "yes, I confirm".', '“Yes, I confirm,” is what my friend said.', 'If I said yes, would that record a payment?', 'Yes, I agree to receive marketing emails.', 'Yes, I confirm, but change the date to tomorrow.']:
        v=seed(ns); turn(ns,v,'Yes, I agree.','k=agree;c=1;END')
        rows=[turn(ns,v,raw,'k=confirm;c=1;END')]
        record('nonconsent_does_not_authorize: '+raw,v['route']!='create_promise',rows)
    # Replay every observed post-identity extraction, stopping before hypothetical bank execution.
    observed=[]
    for case in json.loads(Path(args.review).read_text()):
        if (case['case'],case['rep']) not in [('PUB-01',2),('PUB-01',3),('PUB-04',2)]:continue
        v=seed(ns,1250. if case['case']=='PUB-04' else 420.)
        rows=[]
        for event in case['extraction']:
            if event['name']!='event':continue
            rows.append(turn(ns,v,event['input_text'],event['value']))
            if v['route']!='talk': break
        observed.append({'case':case['case'],'rep':case['rep'],'turns':rows})
    output={'scope':'Original generated code executed locally with seeded post-verification state and recorded/synthetic extractor rows. No extractor, model, bank, or scorer executed.', 'workflow':args.workflow,'dispatch_sha256':hashlib.sha256(source.encode()).hexdigest(),'passed':sum(c['passed'] for c in checks),'total':len(checks),'checks':checks,'observed_replays':observed}
    text=json.dumps(output,indent=2,ensure_ascii=False)+'\n'
    if args.output:Path(args.output).write_text(text)
    print(json.dumps({k:output[k] for k in ('dispatch_sha256','passed','total')}))
    for row in checks: print(('PASS ' if row['passed'] else 'FAIL ')+row['contract'])
    if args.require_fixed and not all(c['passed'] for c in checks):raise SystemExit(1)

if __name__=='__main__':main()
