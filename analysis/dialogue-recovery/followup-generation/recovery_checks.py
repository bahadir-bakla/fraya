"""Independent local lifecycle regression controls; no hosted evaluation claim."""
import copy
import json
import local_checks as original
Call, need = original.Call, original.need
results = []

def check(name, test):
    try:
        test()
        results.append({'test': name, 'status': 'passed'})
    except Exception as exc:
        results.append({'test': name, 'status': 'failed', 'error': repr(exc)})

def recovery():
    c = Call().ready().say('Yes, I agree.', 'k=agree;c=1;END')
    c.say('Actually, change the amount to one hundred and', 'k=change;c=0;u=amount;END')
    need(c.v['state']['recovery_offer'])
    need(c.v['state']['pending']['incomplete'])
    need(c.v['route'] == 'talk')
    return c

def replacement(amount, kind='proposal'):
    c = recovery()
    old = copy.deepcopy(c.v['state']['recovery_offer'])
    c.say(('Yes, I confirm ' if kind == 'confirm' else '') + str(amount) + '.', f'k={kind};c=1;a={amount};END')
    s = c.v['state']
    need(s['recovery_offer'] is None)
    need(s['readback']['amount'] == amount != old['amount'])
    need(c.v['route'] == 'talk')
    c.consent()
    need(c.v['promise_amount'] == amount)
    c.receipt('create_promise', {'ok': True, 'promise_id': 'replacement_receipt'})
    need(c.v['outcome'] == 'promise')

for amount in (310.75, 525.50, 700):
    for kind in ('proposal', 'change', 'confirm'):
        check(f'explicit {kind} {amount}, fresh readback and separate confirmation', lambda a=amount,k=kind: replacement(a,k))

def fresh():
    c = recovery()
    amount = c.v['state']['recovery_offer']['amount']
    c.say('Yes.', 'k=agree;c=1;END')
    need(c.v['route'] == 'talk')
    need(c.v['state']['readback']['amount'] == amount)
    need(c.v['state']['recovery_offer'] is None)
    c.consent()
    need(c.v['promise_amount'] == amount)
check('fresh recovery bare yes only reads back; later consent writes', fresh)

def stale(mutate):
    c = recovery()
    mutate(c)
    c.say('Yes.', 'k=confirm;c=1;END')
    need(c.v['route'] == 'talk')
    need(c.v['state']['pending'].get('amount') is None)
    need(c.v['state']['readback'] is None)

mutations = {
    'offer revision': lambda c: c.v['state'].__setitem__('offer_revision', 17),
    'terms revision': lambda c: c.v['state'].__setitem__('terms_revision', 17),
    'pending revision': lambda c: c.v['state']['pending'].__setitem__('revision', 17),
    'product': lambda c: c.v['state']['product'].__setitem__('product_id', 'replacement_product'),
    'unrelated current question': lambda c: c.v['state'].__setitem__('current_question', {'kind':'other','sequence':999}),
    'actual spoken question': lambda c: c.v.__setitem__('dialogue_line', 'May I update your mailing address?'),
    'changed retained date': lambda c: c.v['state']['pending'].__setitem__('date', '2026-10-16'),
    'offer payload': lambda c: c.v['state']['recovery_offer'].__setitem__('amount', 600),
}
for name, mutate in mutations.items():
    check('stale '+name+' cannot adopt', lambda m=mutate: stale(m))

def reoffer():
    c = recovery()
    c.v['state']['offer_revision'] += 1
    c.say('Yes.', 'k=agree;c=1;END')
    need(c.v['state']['pending'].get('amount') is None)
    need(c.v['state']['recovery_offer'])
    amount = c.v['state']['recovery_offer']['amount']
    c.say('Yes.', 'k=agree;c=1;END')
    need(c.v['route'] == 'talk')
    need(c.v['state']['readback']['amount'] == amount)
    c.consent()
check('invalid old offer then fresh reoffer acceptance and separate confirmation', reoffer)

def pause():
    c = recovery().say('Stop.', 'k=stop;c=1;END')
    need(c.v['state']['recovery_offer'] is None)
    c.say('Yes.', 'k=agree;c=1;END')
    need(c.v['route'] == 'talk')
    need(c.v['state']['pending'].get('amount') is None)
check('stop question supersedes recovery; yes does not adopt or write', pause)

for raw in ['Yes, if I can.', 'She said "yes".', 'Yes, I agree to marketing.', 'No, I do not agree.']:
    def negative(raw=raw):
        c = recovery().say(raw, 'k=confirm;c=1;END')
        need(c.v['route'] == 'talk')
        need(c.v['state']['pending'].get('amount') is None)
    check('unsupported recovery acceptance '+raw, negative)

need(original.code == open('dispatch.py').read())
report = {'scope':'Independent local persistent-state regression; synthetic bank receipts; no network or hosted evaluation',
          'passed':sum(x['status']=='passed' for x in results),
          'failed':sum(x['status']=='failed' for x in results), 'checks':results}
with open('recovery-check-results.json','w') as f: json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
assert not report['failed']
