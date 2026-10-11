"""Rescore mock-final results. Raw = official score_ledger on the hosted ledger.
Adjusted = same, except a close_call rejected by the hosted mock ONLY because its reason is not in Brief A/B's
reason list counts as recorded with the agent's own outcome/reason (the final's mock would know the new table).
The judge verdict is reused unchanged."""
import json, sys, os, glob, copy
KIT = os.path.join(os.path.dirname(__file__), 'builder-wt', 'build-the-builder 2')
sys.path.insert(0, os.path.join(KIT, 'tools')); from score import http, score_ledger
REJ = 'this outcome needs one of these reasons'
def effective(led):
    led = copy.deepcopy(led); fixed = False
    if led.get('outcome') is None:
        for c in reversed(led['calls']):
            if c['tool'] == 'close_call' and REJ in str(c['result'].get('error', '')):
                led['outcome'], led['reason'] = c['args'].get('outcome'), c['args'].get('reason'); fixed = True; break
    return led, fixed
cases = {}
for f in ('cases-c.json', 'cases-d.json'):
    for c in json.load(open(os.path.join(os.path.dirname(__file__), 'mockfinal', f))): cases[(c['brief'], c['id'])] = c
out = {}
RES = sys.argv[1] if len(sys.argv) > 1 else 'results'
for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), RES, '*-*.json'))):
    label, style = os.path.basename(path)[:-5].split('-', 1); d = json.load(open(path))
    for r in d['rows']:
        case = cases[(label[0], r['id'])]; led = http('/v1/practice/ledger/' + r['customer_id'])
        conv = [x for x in r['failed'] if x.startswith('conversation:')]
        raw = score_ledger(case, led)['failed']; eled, fixed = effective(led); adj = score_ledger(case, eled)['failed']
        out.setdefault(label, {}).setdefault(r['id'], {})[style] = {'raw_pass': not raw and not conv, 'adj_pass': not adj and not conv, 'reason_fixed': fixed, 'ledger_fail': adj, 'conversation_fail': conv, 'tools': r['tools'], 'call_id': r['call_id']}
for label, rows in out.items():
    styles = sorted({s for v in rows.values() for s in v})
    print(f'== Brief {label}: styles {styles}')
    for cid, v in rows.items():
        lab = cases[(label[0], cid)].get('case_label', cid)
        print(f"  {lab:<5} {cid}  raw {''.join('P' if v[s]['raw_pass'] else '.' for s in styles if s in v)}  adj {''.join('P' if v[s]['adj_pass'] else '.' for s in styles if s in v)}")
    for k in ('raw_pass', 'adj_pass'):
        calls = sum(x[k] for v in rows.values() for x in v.values()); n = sum(len(v) for v in rows.values())
        all3 = sum(all(x[k] for x in v.values()) and len(v) == len(styles) for v in rows.values())
        print(f'  {k}: calls {calls}/{n}, cases passing every run {all3}/{len(rows)}')
json.dump(out, open(os.path.join(os.path.dirname(__file__), RES, 'rescored.json'), 'w'), indent=1)
