import ast,copy,datetime,hashlib,json,pathlib,sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT=pathlib.Path.cwd();BASE=ROOT/'analysis/final-case-candidate-v1-review'; RUN=ROOT/'competition/runs/20261011-224723-9d9433'
raw=(RUN/'work/workflow.json').read_bytes();wf=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
previous=json.loads(pathlib.Path(str(BASE)+'.repair-readiness.json').read_bytes())
assert sha==previous['sha256'],'changed since readiness sample; re-sample required'
assert json.loads((RUN/'status.json').read_bytes())['phase']=='completed' or (datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(previous['sample_utc'])).total_seconds()>=15
pathlib.Path(str(BASE)+'.v2-candidate.json').write_bytes(raw)
manifest=[]
for kind,name in [('candidate','workflow.json'),('policy','policy.json'),('coverage','coverage.json'),('api','inputs/openapi.json')]:
 p=RUN/'work'/name;b=p.read_bytes();json.loads(b)
 dest=pathlib.Path(str(BASE)+('.v2-candidate.json' if kind=='candidate' else '.v2-'+kind+'.json'))
 if kind!='candidate':dest.write_bytes(b)
 manifest.append({'kind':kind,'source':str(p),'snapshot':str(dest),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)})
code=wf['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
pathlib.Path(str(BASE)+'.v2-controller.py').write_text(code,encoding='utf-8')
def safe(c):
 t=ast.parse(c)
 assert all(a.name in ('json','re','datetime') for n in ast.walk(t) if isinstance(n,ast.Import) for a in n.names)
 assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('eval','exec','open','compile','__import__') for n in ast.walk(t))
safe(code)
# Reuse the earlier authored harness definition, then bind all globals to the new immutable snapshot.
prefix=pathlib.Path(str(BASE)+'.probes.py').read_text(encoding='utf-8').split('rows=[]')[0]
env={'__file__':str(BASE)+'.probes.py'};exec(prefix,env)
env.update(wf=wf,code=code,controller=compile(code,'V2_EXACT_UNMODIFIED_CONTROLLER','exec'))
fixtures=env['fixtures']; customers=env['customers']
def flatten(v,prefix,out):
 if isinstance(v,dict):
  for k,x in v.items():flatten(x,prefix+'.'+k,out)
 elif isinstance(v,list):
  for i,x in enumerate(v):flatten(x,prefix+'.'+str(i),out)
 else:out[prefix]=v
class H(env['Harness']):
 def bank(self,override=None):
  op=self.vars['route'];entry=wf['nodes'][op]['pre_actions'][0]
  safe(entry['pre_process_code']);safe(entry['post_process_code'])
  config={};x={'vars':self.vars,'config':config};exec(entry['pre_process_code'],x,x)
  d=config['body']['data'];self.requests.append({'operation':op,'data':copy.deepcopy(d)})
  service=op.replace('_','.') if op.startswith('cards_') else {'statement_week_get':'statement.week.get','statement_week_decide':'statement.week.decide','statement_week_change':'statement.week.change','contact_email_get':'contact.email.get','statement_pdf_send':'statement.pdf.send'}[op]
  customer=customers.get(str(d.get('customerNo',self.vars['customerNumber'])))
  if service in ('cards.list','contact.email.get','statement.pdf.send'):answer=customer['services'][service]
  else:
   answer=next(c['services'][service][d['cardNumber']] for c in fixtures['customers'] if d['cardNumber'] in c['services'].get(service,{}))
   if service in ('statement.week.decide','statement.week.change'):answer=answer[str(d['newStatementWeek'])]
  result={'status_code':answer['http'],'data':copy.deepcopy(answer['response'])}
  if override is not None:result=copy.deepcopy(override)
  x={'vars':self.vars,'result':result};exec(entry['post_process_code'],x,x)
  # Match observed platform representation: only dotted response leaves, no object aggregation.
  self.vars['bank_receipt']='';self.vars['receipt_operation']='';self.vars[op+'_payload']=''
  flatten(result,op+'_response',self.vars)
  self.last_raw=copy.deepcopy(result)
  return self.run()
rows=[]
def add(id,h,observed,passed):rows.append({'id':id,'passed':bool(passed),'observed':observed,'requests':h.requests})
# Lossless provider adapter shape compared to actual official three-card fixture.
h=H('92220795','2026-10-11T22:49:00+03:00');h.bank(); got=h.state['cards'];expected=customers['92220795']['services']['cards.list']['response']['data']['cards']
add('DOTTED-CARDS-ARRAY',h,{'phase':h.vars['phase'],'card_count':len(got),'exact_array_equal':got==expected,'line':h.vars['dialogue_line']},got==expected and h.vars['route']=='listen')
# Single card auto-selection and full nested multi-currency balance survives.
h=H('96158684','2026-10-12T10:30:00+03:00');h.reads(); card=h.state['card'];expected=customers['96158684']['services']['cards.balance'][card]['response']['data'];got=h.state['balance']
add('DOTTED-BALANCE-LOSSLESS',h,{'phase':h.vars['phase'],'exact_balance_equal':got==expected,'line':h.vars['dialogue_line']},got==expected and h.vars['phase']=='offer')
# Correct write gate: no write at preview, vague consent no write, later fresh explicit -> one change.
h.event('week','Hesap kesim haftamı değiştirmek istiyorum.');h.reads();h.event('yes','Evet.');h.event('week','Üçüncü hafta.',week='3');h.reads();preview=h.vars['dialogue_line']
readback=copy.deepcopy(h.state.get('readback'));h.event('yes','Olur herhalde.',consent='vague');vague=h.vars['route'];h.event('yes','Evet, onaylıyorum.',consent='explicit');before=h.vars['route'];h.bank()
wr=[r for r in h.requests if r['operation']=='statement_week_change'];days=[r['data']['statementDay'] for r in h.requests if r['operation'] in ('statement_week_decide','statement_week_change')]
add('DOTTED-WEEK-FRESH-CONSENT-RECEIPT',h,{'preview':preview,'readback':readback,'vague_route':vague,'explicit_route':before,'write_count':len(wr),'current_days':days,'completion':h.vars['dialogue_line'],'route':h.vars['route']},vague=='listen' and before=='statement_week_change' and len(wr)==1 and days==[9,9] and h.vars['route']=='finish' and 'değiş' in h.vars['dialogue_line'])
# Failed fresh write receipt cannot announce success.
h=H('96158684','2026-10-12T10:30:00+03:00');h.reads();h.event('week','Hafta değiştirmek');h.reads();h.event('yes','Evet.');h.event('week','Üçüncü hafta.',week='3');h.reads();h.event('yes','Evet, onaylıyorum.',consent='explicit');h.bank({'status_code':500,'data':{'result':{'returnCode':'1'},'data':{'responseCode':0,'exitState':'OK'}}})
add('DOTTED-FAILED-WRITE-NO-SUCCESS',h,{'route':h.vars['route'],'destination':h.state.get('destination'),'line':h.vars['dialogue_line']},h.state.get('destination')=='AGENT' and 'değiştiremiyorum' in h.vars['dialogue_line'])
# Fresh incomplete response with old dotted data retained: dispatch must neutralize stale keys.
h=H('92460108','2026-10-12T10:30:00+03:00');h.reads();h.event('email','Ekstremi kayıtlı adrese gönder.');h.event('yes','Evet, onaylıyorum.',consent='explicit');h.bank()
# Execute the exact authored dispatch/clear_response functions to neutralize old provider leaves.
module=ast.parse(code);module.body=[n for n in module.body if not isinstance(n,ast.Try)]
x={'vars':h.vars};exec(compile(module,'V2_EXACT_HELPER_DEFINITIONS','exec'),x,x)
s=x['dispatch'](h.state,'statement_pdf_send')
h.vars['bank_state']=json.dumps(s);h.vars['route']=s['route']
h.bank({'status_code':200,'data':{'result':{'returnCode':'1'}}})
add('DOTTED-MISSING-FRESH-WRITE-DATA',h,{'route':h.vars['route'],'destination':h.state.get('destination'),'line':h.vars['dialogue_line'],'note':'Exact candidate dispatch neutralizes old same-operation DONE leaves; fresh incomplete receipt must fail.'},h.state.get('destination')=='AGENT' and 'gönderildi' not in h.vars['dialogue_line'])
# Prior independent source findings re-evaluated on v2, not asserted as repaired by the boundary work.
h=H('92460108','2026-10-12T10:30:00+03:00');h.reads();h.event('email','Euro ekstresini kayıtlı e-posta adresime gönder.',currency='EUR');rb=copy.deepcopy(h.state.get('readback'));h.event('yes','Evet, onaylıyorum.',consent='explicit');h.bank();payload=h.requests[-1]['data']
add('EXPLICIT-PDF-EUR',h,{'readback':rb,'request_data':payload,'line':h.vars['dialogue_line']},payload.get('currencyType')=='EUR')
h=H('96158684','2026-11-09T10:30:00+03:00');h.reads();line=h.vars['dialogue_line']
add('UPCOMING-CUT-DAY',h,{'nextStatementDate':'09.11.2026','statementDate':'09.10.2026','line':line},'00.00' in line and 'geçmiştir' not in line)
report={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run':'20261011-224723-9d9433','candidate_sha256':sha,'manifest':manifest,'controller_sha256':hashlib.sha256(code.encode()).hexdigest(),'source_stable_after_cpu':hashlib.sha256((RUN/'work/workflow.json').read_bytes()).hexdigest()==sha,'api_byte_equal_prior_pin':(RUN/'work/inputs/openapi.json').read_bytes()==pathlib.Path(str(BASE)+'.api.json').read_bytes(),'rows':rows,'passed':sum(r['passed'] for r in rows),'total':len(rows),'native_calls_added':0,'bank_network_calls':0,'freya_calls':0,'limits':['Exact unchanged new controller and API pre/post hooks executed on official fixtures; vars is a Python dict with dotted leaves.','Speech events authored to advertised extraction schema; no hosted frequency, ASR, model extraction, or platform-store semantics measured.','Run status completed at snapshot; claims bind this SHA256 only.']}
pathlib.Path(str(BASE)+'.v2-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'candidate_sha256':sha,'stable_after':report['source_stable_after_cpu'],'api_equal':report['api_byte_equal_prior_pin'],'passed':report['passed'],'total':report['total'],'rows':[{'id':r['id'],'passed':r['passed'],'observed':r['observed']} for r in rows]},ensure_ascii=False))
