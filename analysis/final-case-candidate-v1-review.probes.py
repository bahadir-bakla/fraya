"""Bounded CPU witnesses on unmodified pinned controller/hooks, synthetic speech events."""
import ast,copy,datetime,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'analysis/final-case-candidate-v1-review'
wf=json.loads(Path(str(BASE)+'.candidate.json').read_bytes())
code=wf['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
tree=ast.parse(code)
assert all(n.module in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom))
assert all(a.name in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names)
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('eval','exec','open','compile') for n in ast.walk(tree))
fixtures=json.loads((ROOT/'final-case-20261011/Build the Builder - Final Case/test-environment/test-customers.json').read_bytes())
customers={c['customerNo']:c for c in fixtures['customers']}
controller=compile(code,'PINNED_CANDIDATE_CONTROLLER','exec')
EVENT_FIELDS=('act','completion','raw','card_reference','card_digits','week','currency','consent','detail','followup','admin')
class Harness:
 def __init__(self,customer,now):
  self.vars={'customerNumber':customer,'now':now};self.requests=[];self.lines=[];self.run()
 def run(self):
  env={'vars':self.vars};exec(controller,env,env)
  self.lines.append(self.vars.get('dialogue_line',''));return self.state
 @property
 def state(self):return json.loads(self.vars['bank_state'])
 def event(self,act,raw='',**kw):
  self.vars.update({k:'' for k in EVENT_FIELDS});self.vars.update(act=act,completion='complete',raw=raw,**kw);return self.run()
 def bank(self):
  op=self.vars['route'];entry=wf['nodes'][op]['pre_actions'][0]
  config={};env={'vars':self.vars,'config':config};exec(entry['pre_process_code'],env,env)
  d=config['body']['data'];self.requests.append({'operation':op,'data':copy.deepcopy(d)})
  service=op.replace('_','.') if op.startswith('cards_') else {'statement_week_get':'statement.week.get','statement_week_decide':'statement.week.decide','statement_week_change':'statement.week.change','contact_email_get':'contact.email.get','statement_pdf_send':'statement.pdf.send'}[op]
  customer=customers.get(str(d.get('customerNo',self.vars['customerNumber'])))
  if service in ('cards.list','contact.email.get','statement.pdf.send'):answer=customer['services'][service]
  else:
   answer=next(c['services'][service][d['cardNumber']] for c in fixtures['customers'] if d['cardNumber'] in c['services'].get(service,{}))
   if service in ('statement.week.decide','statement.week.change'):answer=answer[str(d['newStatementWeek'])]
  result={'status_code':answer['http'],'data':copy.deepcopy(answer['response'])}
  env={'vars':self.vars,'result':result};exec(entry['post_process_code'],env,env)
  for mapping in wf['nodes'][op]['response_mapping']:
   value=result
   for key in mapping['path'].split('.'):value=value[key]
   self.vars[mapping['variable']]=copy.deepcopy(value)
  return self.run()
 def reads(self):
  for _ in range(12):
   route=self.vars['route']
   if route not in ('cards_list','cards_balance','contact_email_get','statement_week_get','statement_week_decide'):break
   self.bank()
  return self.state

rows=[]
def add(id,contract,h,expected,observed,match):
 rows.append({'id':id,'contract':contract,'expected':expected,'observed':observed,'observation_matches_expected':match,
              'requests':h.requests,'source_execution':'Unchanged controller and hooks from pinned JSON; Python dict persistence emulates vars. Typed speech is authored, not observed model extraction.'})

# Cut date represented by the coming statement field; last issued statement remains older.
h=Harness('96158684','2026-11-09T10:30:00+03:00');h.reads();line=h.vars['dialogue_line']
add('CPU-CUT-NEXT','Cut day uses upcoming statement date and totalDebt',h,'Recognize nextStatementDate 09.11.2026 as today; cut-day announcement; TL totalDebt 5000.',
 {'line':line,'phase':h.vars['phase'],'statementDate':'09.10.2026','nextStatementDate':'09.11.2026','totalDebt':5000,'statementDebt':10000},'00.00' in line and 'geçmiştir' not in line)
h=Harness('96158684','2026-10-09T10:30:00+03:00');h.reads();line=h.vars['dialogue_line']
add('CPU-CUT-ISSUED-CONTROL','Existing issued-date cut comparison control',h,'Candidate recognizes statementDate==today',{'line':line},'00.00' in line)

# A declared currency in the producer's supported PDF field is lost by the consumer.
h=Harness('92460108','2026-10-12T10:30:00+03:00');h.reads()
h.event('email','Euro ekstresini kayıtlı e-posta adresime gönder.',currency='EUR')
readback=copy.deepcopy(h.state.get('readback'))
h.event('yes','Evet, onaylıyorum.',consent='explicit')
route=h.vars['route'];h.bank();payload=copy.deepcopy(h.requests[-1]['data'])
add('CPU-PDF-EUR','Supported explicit PDF currency must survive to scoped readback and dispatch',h,'Explicit extracted EUR request -> readback.currency EUR -> currencyType EUR.',
 {'readback':readback,'route_after_confirmation':route,'request_data':payload,'final_line':h.vars['dialogue_line']},payload.get('currencyType')=='EUR')

# Positive consent safety control, including required current statementDay.
h=Harness('96158684','2026-10-12T10:30:00+03:00');h.reads();h.event('week','Hesap kesim haftamı değiştirmek istiyorum.');h.reads()
h.event('yes','Evet.');h.event('week','Üçüncü hafta.',week='3');h.reads()
preview_line=h.vars['dialogue_line'];h.event('yes','Olur herhalde.',consent='vague');vague_route=h.vars['route']
h.event('yes','Evet, onaylıyorum.',consent='explicit');h.bank()
day_requests=[r for r in h.requests if r['operation'] in ('statement_week_decide','statement_week_change')]
add('CPU-WEEK-CONTROL','Preview, later explicit consent, current day, success receipt',h,'Vague -> no write; clear later yes -> one change, current statementDay9 in decide/change, preview dates in completion.',
 {'preview_line':preview_line,'vague_route':vague_route,'day_requests':day_requests,'final_line':h.vars['dialogue_line']},vague_route=='listen' and len([r for r in day_requests if r['operation']=='statement_week_change'])==1 and all(r['data']['statementDay']==9 for r in day_requests))

# Native F1 is qualified by the explicit narrow-reading exception in analysis8.5.
h=Harness('92220795','2026-10-12T10:30:00+03:00');h.reads();h.event('select','Yıldız Premium kartımın son ödeme tarihi?',card_reference='Yıldız Premium',detail='due');h.reads()
add('CPU-SINGLE-FIGURE-QUALIFICATION','Analysis8.5 explicitly sends single-figure answers to offer',h,'Source permits single-figure -> offer, so native F1 is not an established blocker.',{'phase':h.vars['phase'],'line':h.vars['dialogue_line']},h.vars['phase']=='offer')

report={'review_type':'exact_candidate_local_CPU_witnesses','candidate_sha256':hashlib.sha256(Path(str(BASE)+'.candidate.json').read_bytes()).hexdigest(),
 'controller_sha256':hashlib.sha256(code.encode()).hexdigest(),'rows':rows,'remote_bank_calls':0,'freya_calls':0,'extractor_calls':0,
 'limitations':['No hosted/ASR/extraction frequency measured. Typed events are faithful authored inputs to the advertised schema.',
                'Local persistence is a Python dict; platform timing, update-store behavior and transitions are not executed.',
                'Current formal run may have newer artifacts; witnesses bind only the immutable pinned first candidate.']}
Path(str(BASE)+'.probes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'candidate_sha256':report['candidate_sha256'],'rows':[{'id':r['id'],'match':r['observation_matches_expected'],'observed':r['observed']} for r in rows]},ensure_ascii=False))
