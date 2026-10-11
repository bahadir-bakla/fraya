"""Selected operation-scope followup, reusing unchanged literal CPU machinery."""
import ast,datetime,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
s=(ROOT/'analysis/classic-v2-opus.witness.py').read_text(encoding='utf-8');ns={'__file__':str(ROOT/'analysis/classic-v2-opus.witness.py')}
exec(compile(s.split('# Permissive recipient')[0],'<read-only-literal-harness>','exec'),ns)
t=ast.parse(s);fn=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='account')
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<literal-account-helper>','exec'),ns)
Store=ns['Store'];base=ns['account']().v;observations=[]
def record(label,store,expected):
 observations.append({'id':label,'expected':expected,'actual':store.facts(),'trace':store.trace})
plain=Store(base);plain.turn('I already paid my credit card overdue amount.','paid',target='cpu-card')
record('paid_claim_control',plain,'Current card paid disposition retained; no payment promise authorization.')
mixed=Store(base);mixed.turn("Do not record a new payment promise. I already paid my credit card overdue amount.",'withdraw',target='cpu-card',span='Do not record a new payment promise.',extra=[{'k':'paid','c':'1','p':'cpu-card','s':'I already paid my credit card overdue amount.'}])
record('withdraw_promise_does_not_erase_paid_note_basis',mixed,'Policy-required paid note basis retained; withdrawal removes payment permission only; no create_promise.')
ready=Store(base);ready.turn('Yes','accept',target='all');ready.turn('Yes, add a note.','confirm',target='all')
record('note_assent_is_not_payment_confirmation',ready,'Deliberately wrong financial producer row must not turn note assent into promise authorization.')
# Model claim adjudication for nonanswer handling, directly from immutable source.
source_a=(ROOT/'competition-v3/build-the-builder/briefs/brief-a.md').read_text(encoding='utf-8')
assert 'A flat refusal or a non-answer uses one persuasion attempt.' in source_a
report={'status':'CLOSED_SELECTED_OPERATION_SCOPE_CPU_PROOFS','finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate_sha256':ns['sha'](ns['PATH']),'observations':observations,'conclusions':{'paid_control_retained':plain.state()['products'][0]['status']=='paid','mixed_loses_paid_basis':mixed.state()['products'][0]['status']!='paid','mixed_no_promise_write':mixed.v['route']!='api_create_promise','wrong_note_confirm_dispatches_promise':ready.v['route']=='api_create_promise'},'adjudication':'Earlier unknown/no-attempt assertion is not established as a Brief A policy failure: rule30 permits a genuine non-answer attempt. Preserve the literal observed counter but do not count it as proven bank-policy failure. Note-assent forced-confirm fault is already covered by current guide different-operation consent. Mixed promise withdrawal versus paid-note basis warrants explicit operation-scope guidance.','limits':['Authored semantic rows and synthetic receipts against unchanged failed unpublished source, not hosted evidence.','Paid claim establishes customer assertion and required note basis, not confirmed bank payment.','No customer confirmation added as a requirement for mandatory notes; the input policy decides every effect.']}
out=ROOT/'analysis/classic-v2-opus.scope-witnesses.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'conclusions':report['conclusions'],'literal_executions':ns['calls'],'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
