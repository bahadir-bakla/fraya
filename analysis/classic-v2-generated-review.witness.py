"""Independent literal-source CPU witnesses; no API, network or candidate writes."""
import copy, hashlib, json, datetime
from pathlib import Path
R=Path(__file__).resolve().parents[1]; P=R/'competition/runs/20261011-160237-d82126/work/workflow.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(P)=='aa25bf73f4a1a2fff8d5d9812be86adcf85a8ebbe32974eb2f9183574609ed46'
w=json.loads(P.read_bytes()); code=w['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default']; results=[]; executions=0
class Store:
 def __init__(self):
  self.v=dict(customer_id='cpu-neutral',first_name='Riley',last_name='Vale',title='Mx',now='2026-10-14T11:00:00',state='{}');self.trace=[];self.step()
 def state(self):return json.loads(self.v['state'])
 def step(self):
  global executions
  executions+=1
  work=copy.deepcopy(self.v);exec(compile(code,'literal-pinned-controller','exec'),{'vars':work});self.v.update(work)
  self.trace.append(dict(route=self.v.get('route'),phase=self.state().get('phase'),line=self.v.get('line'),body=json.loads(self.v.get('request_body','{}')),buffer=self.state().get('buffer'),format=self.state().get('format'),verified=self.state().get('verified')))
 def turn(self,raw,**kw):
  self.v.update(dict(raw_speech=raw,recipient_act='',security_answer='',security_part='',security_act='',admin='',event=''));self.v.update(kw);self.step();return self
 def receipt(self,data,stale=False):
  s=self.state();self.v.update(receipt_op=s['pending'],receipt_seq=str(s['op_seq']-1 if stale else s['op_seq']),receipt=json.dumps(dict(status='success',data=data)));self.step();return self
def record(id,store,expected,passed,kind='advertised-contract conditional CPU'):
 results.append(dict(id=id,expected=expected,met=bool(passed),classification=kind,trace=store.trace))
def security():return Store().turn('Yes, speaking.',recipient_act='self')
def dob():return security().turn('My phone ends in 2718.',security_answer='2718').receipt(dict(ok=True,verified=True))
def ready():
 x=dob().turn('4 May 1987',security_answer='1987-05-04').receipt(dict(ok=True,verified=True,all_verified=True))
 return x.receipt(dict(ok=True,products=[dict(product_id='cpu-p1',type='credit_card',card_last4='9012',past_due='2125.10',days_late=20,minimum_payment='300.00')]))
for raw in ['Riley','Mx Vale speaking.','Vale, Riley speaking.']:
 x=Store().turn(raw,recipient_act='self');record('recipient-positive-'+raw,x,'security only; no verified identity',x.state()['phase']=='security' and not x.state()['verified'])
x=Store().turn("Riley isn't here right now.",recipient_act='other');record('recipient-other-precedence',x,'callback; no security question',x.state()['phase']=='callback')
x=Store().turn('Riley is at work, can I take a message?',recipient_act='other');record('recipient-other-at-work',x,'callback; no security question',x.state()['phase']=='callback')
x=security().turn("My cousin's phone ends in 2718.");record('thirdparty-phone-empty-extractor',x,'no verify_identity operand borrowed from third party',x.v['route']!='verify_identity')
x=security().turn("My sister's phone ends in 2718.");record('thirdparty-listed-negative-control',x,'no verify_identity',x.v['route']!='verify_identity')
x=security().turn('Two seven',security_part='27').turn('One eight',security_part='18');record('phone-fragments',x,'one current phone comparison, not verified yet',x.v['route']=='verify_identity' and json.loads(x.v['request_body'])['answer']=='2718' and not x.state()['verified'])
x=dob().turn('1987',security_part='1987').turn('4 May',security_part='4 May').turn('4 May 1987',security_answer='1987-05-04');record('year-first-recovery',x,'later complete DOB recovers to verify_identity',x.v['route']=='verify_identity')
x=dob().turn('4 May',security_part='4 May').turn('1987',security_part='1987');record('day-month-first-positive',x,'DOB comparison after completing year',x.v['route']=='verify_identity' and json.loads(x.v['request_body'])['answer']=='1987-05-04')
x=ready();record('exact-floor-positive',x,'50 percent rounded up to whole euro',x.state()['floor']==106300)
x=ready().turn('The full amount is too much for me.',event='k=too_much|c=1;END');record('floor-no-customer-date',x,'ask for date when customer has proposed/agreed none',x.state().get('date')!='2026-10-14' or 'which date' in x.v['line'].lower())
def confirmed():return ready().turn('I can pay 1100 euros on 19 October.',event='k=propose|c=1|a=1100|d=2026-10-19;END')
x=confirmed();record('fresh-readback-before-write',x,'confirm speech with no create_promise',x.state()['phase']=='confirm' and x.v['route']=='dialogue')
x.turn('Yes, that is correct.',event='k=confirm|c=1;END');record('later-confirm-dispatch',x,'exact body after fresh readback',x.v['route']=='create_promise' and json.loads(x.v['request_body'])['amount']==1100 and json.loads(x.v['request_body'])['date']=='2026-10-19')
x.receipt(dict(ok=False));record('promise-false-no-retry',x,'service_error note, no retry or success acknowledgement',x.v['route']=='add_note' and json.loads(x.v['request_body'])['reason']=='service_error' and not x.state().get('recorded'))
x=confirmed().turn('Yes, correct.',event='k=confirm|c=1;END').receipt(dict(ok=True),stale=True);record('stale-receipt-failclosed',x,'no recorded arrangement on stale receipt',not x.state().get('recorded') and x.v['route']=='add_note')
x=confirmed().turn('Yes, correct.',event='k=confirm|c=1;END').receipt(dict(ok=True));record('current-success-email',x,'recorded only after current ok receipt; email acknowledgement',x.state().get('recorded') and 'email you a confirmation' in x.v['farewell'])
x=confirmed().turn('I withdraw permission.',event='k=confirm|c=1;END');record('withdrawal-forced-confirm-control',x,'forced financial confirm cannot override withdrawal',x.v['route']!='create_promise','inconsistent typed-confirm robustness conditional')
x=confirmed().turn('I want to stop.',event='k=stop|c=1;END').turn('Yes.',event='k=confirm|c=1;END');record('stop-question-scoped-yes',x,'yes to stop question must not use old financial readback',x.v['route']!='create_promise','inconsistent typed-confirm robustness conditional')
report=dict(status='CLOSED_LITERAL_CPU_WITNESSES',controller_sha256=hashlib.sha256(code.encode()).hexdigest(),export_sha256=sha(P),store_semantics='deepcopy each execution; merge variable patches so omitted keys do not imply persistent deletion',checks=len(results),met=sum(r['met'] for r in results),unmet=[r['id'] for r in results if not r['met']],literal_executions=executions,results=results,limits=['All receipts synthetic CPU inputs, not actual bank verification or hosted observations.','No external API or platform calls.','No candidate edits.'])
out=R/'analysis/classic-v2-generated-review.witnesses.json';out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:report[k] for k in ('checks','met','unmet','export_sha256')}))
