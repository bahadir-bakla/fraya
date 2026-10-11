import ast, copy, datetime, hashlib, json, pathlib, re, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
P = ROOT / 'competition/runs/20261011-082830-a93659/codex-stress-a.workflow.json'
START = '2026-10-11T05:34:26.6516369Z'
STATUS = 'CLOSED_FROZEN_CODEX_A9_SOURCE_CPU_REVIEW'
sha = lambda b: hashlib.sha256(b).hexdigest()
raw_export = P.read_bytes()
export = json.loads(raw_export.decode('utf-8-sig'))
W = export['workflow']; N = W['nodes']
SOURCE = N['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
CANDIDATE = {'path':str(P.relative_to(ROOT)).replace('\\','/'),'sha256':sha(raw_export),'version':9,'agent_id':export['agent_id'],'updated_at':export['updated_at'],'publication_time_user_attested':'2026-10-11T05:33:07Z','hosted_tested':False}
assert CANDIDATE['agent_id']=='37b17600-df9a-4934-854e-a3de8f2e7987'
assert CANDIDATE['sha256']=='471494ad17cab933aa56658e4a5d02d9c99a23bfc165386bf46a352b4585495c'
protected = [P] + [p for p in (ROOT/'analysis').glob('night-*-*') if p.is_file() and ('review' in p.name or 'witnesses' in p.name) and 'a9' not in p.name and 'stage2' not in p.name.lower()]
before = {str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in protected}
tree = ast.parse(SOURCE)
assert all(n.module in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom))
assert all(a.name in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names)
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('open','eval','exec','__import__') for n in ast.walk(tree))
BLOCKS = {'dispatch':SOURCE}
for node in ('verify_identity','get_account','create_promise'):
 for hook in ('pre_process_code','post_process_code'): BLOCKS[node+'/'+hook] = N[node]['pre_actions'][0][hook]
codes={k:compile(v,'export:'+k,'exec') for k,v in BLOCKS.items()}
block_hashes={k:sha(v.encode()) for k,v in BLOCKS.items()}
observations=[]; executions=[]; codec=[]; api=[]

def view(v):
 s=v.get('state',{})
 return {'route':v.get('route'),'phase':s.get('phase'),'dialogue_line':v.get('dialogue_line'),'outcome':v.get('outcome'),'reason':v.get('reason'),'verified':s.get('verified'),'dob_passed':s.get('dob_passed'),'wrong':s.get('wrong'),'declines':s.get('declines'),'security_clarifications':s.get('security_clarifications'),'pending':copy.deepcopy(s.get('pending')),'readback':copy.deepcopy(s.get('readback')),'awaiting':s.get('awaiting'),'write_tries':s.get('write_tries'),'recorded':s.get('recorded'),'receipt':copy.deepcopy(s.get('receipt')),'promise_dispatch':copy.deepcopy(s.get('promise_dispatch')),'security_field':v.get('security_field'),'security_answer':v.get('security_answer')}

def execute(block,v,label,**extra):
 env={'vars':v,**extra}; t=time.perf_counter(); exec(codes[block],env,env)
 executions.append({'label':label,'block':block,'source_sha256':block_hashes[block],'elapsed_ms':round((time.perf_counter()-t)*1000,3),'output_sha256':sha(json.dumps(view(v),sort_keys=True).encode())})
 return env

def obs(label,v,expected,passed,category='control',inputs=None):
 observations.append({'id':label,'category':category,'expected':expected,'pass':bool(passed),'conditional_inputs':inputs,'actual':view(v)})

def init():
 v={'now':'2026-10-11T10:00:00','customer_id':'CPU-NEUTRAL-001','first_name':'Morgan','last_name':'Reed','title':'Mx','state':None,'mode':'event','event':'','raw':'','admin':'none'}
 execute('dispatch',v,'init')
 turn(v,'recipient','Yes, Morgan Reed speaking.')
 assert v['state']['phase']=='dob'
 return v

def turn(v,kind,raw='',admin='none',fields=None,wire=None,c='1',label='turn'):
 event=wire if wire is not None else 'k='+kind+';c='+c+';'+''.join(k+'='+str(x)+';' for k,x in (fields or {}).items())+'END'
 v.update(mode='event',event=event,raw=raw,admin=admin)
 execute('dispatch',v,label)
 return {'event':event,'raw':raw,'admin':admin}

def body(node,v):
 props=N[node]['pre_actions'][0]['function']['parameters']['properties']['body']['properties']; out={}
 for k,p in props.items():
  value=p.get('default',''); match=re.fullmatch(r'\{\{([a-z_]+)\}\}',str(value)); out[k]=v.get(match[1],'') if match else value
 return out

def receipt(v,node,data,status=200,counter=True,post=True,body_override=None):
 request=body(node,v) if body_override is None else body_override
 execute(node+'/pre_process_code',v,'synthetic/'+node+'/pre',config={'body':copy.deepcopy(request)})
 if counter:
  key=node+('_success_count' if status==200 else '_failure_count'); v[key]=int(v.get(key,0))+1
 if node=='create_promise':
  v.update({'create_promise_response.status':'success' if status==200 else 'error','create_promise_response.status_code':str(status),'create_promise_status_code':str(status),'create_promise_response.error':'' if status==200 else 'HTTP '+str(status)})
 if post: execute(node+'/post_process_code',v,'synthetic/'+node+'/post',result={'status_code':status,'data':copy.deepcopy(data)})
 api.append({'node':node,'body':request,'synthetic_data':data,'status':status,'counter_advanced':counter,'post_executed':post})
 execute('dispatch',v,'synthetic/'+node+'/dispatch')

def submit(v,answer,raw=None,admin='none'):
 return turn(v,'security',raw or answer,admin,{'v':answer})

def phone():
 v=init(); submit(v,'9 January 1991','My date of birth is 9 January 1991.'); receipt(v,'verify_identity',{'ok':True,'verified':True,'all_verified':False})
 assert v['state']['phase']=='phone' and not v['state']['verified']; return v

def account(late=12):
 v=phone(); submit(v,'0742','My last four digits are zero seven four two.'); receipt(v,'verify_identity',{'ok':True,'verified':True,'all_verified':True})
 assert v['route']=='get_account'
 product={'product_id':'CPU-CARD-001','type':'credit_card','card_last4':'8841','minimum_payment':90,'past_due':540,'days_late':late}
 receipt(v,'get_account',{'ok':True,'products':[product]}); assert v['state']['phase']=='offer'; return v

def authorized():
 v=account(); turn(v,'proposal','I can pay 220 on 20 October 2026.',fields={'a':'220','d':'20 October 2026'}); turn(v,'confirm','Yes, I confirm.'); assert v['route']=='create_promise'; return v

# Actual normalized schema against the literal decoder. Never unescape either.
env=execute('dispatch',{'state':None,'now':'2026-10-11T10:00:00'},'load-codec')
decode=env['decode']; schema=N['talk']['extraction_schema']; pattern=schema[0]['validation_pattern']; description=schema[0]['description']
examples=[line for line in description.splitlines() if line.startswith('k=')]
assert len(examples)==28, 'Published producer literal example inventory changed'
for i,text in enumerate(examples):
 try: rows=decode(text); accepted=True; error=None
 except Exception as e: rows=[]; accepted=False; error=str(e)
 codec.append({'id':'literal-example-'+str(i+1),'wire':text,'regex':bool(re.fullmatch(pattern,text)),'decoder':accepted,'rows':rows,'error':error})
extra_codec={'aggregate-newline':'k=proposal;c=1;a=220;END\nk=proposal;c=1;d=20 October 2026;END','aggregate-literal-backslash-n':'k=proposal;c=1;a=220;END\\nk=proposal;c=1;d=20 October 2026;END','duplicate-key':'k=proposal;c=1;a=220;a=230;END','unknown-kind':'k=malicious;c=1;END','nonfinite':'k=proposal;c=1;a=NaN;END','exponent':'k=proposal;c=1;a=2e2;END','unfinished-missing-u':'k=change;c=0;END','complete-with-u':'k=proposal;c=1;u=date;a=220;END','trailing-newline':'k=confirm;c=1;END\n','invalid-time':'k=callback;c=1;d=tomorrow;t=99:99;END'}
for name,text in extra_codec.items():
 try: rows=decode(text); accepted=True; error=None
 except Exception as e: rows=[]; accepted=False; error=str(e)
 codec.append({'id':name,'wire':text,'regex':bool(re.fullmatch(pattern,text)),'decoder':accepted,'rows':rows,'error':error})

# Source-known repair tests and independently composed challenges are labeled separately.
questions=[('purpose','why are you calling?','purpose'),('balance','how much do I owe?','balance'),('ai','are you a digital assistant?','ai'),('scam','is this a legitimate call?','scam'),('security','why do you need this?','security_purpose')]
for phase in ('dob','phone'):
 for name,q,flag in questions:
  for separator in (', ','; ',' and '):
   v=init() if phase=='dob' else phone(); ans='9 January 1991' if phase=='dob' else '0742'; own='My birthday is '+ans if phase=='dob' else 'My last four digits are '+ans
   inp=submit(v,ans,own+separator+q,flag)
   passed=v['route']=='security_admin' and not v['state']['verified'] and v['state']['wrong']==0 and v['state']['declines']==0
   obs('repair/'+phase+'/'+name+'/'+repr(separator),v,'Preserve complete own answer, speak question response, then bank verify; no bank receipt yet',passed,'source_known_repair',inp)

new_questions=[('call-paraphrase','could you explain the reason for this call?','purpose'),('balance-paraphrase','can you tell me what I owe?','balance'),('security-paraphrase','why is my birthday required?','security_purpose'),('person-paraphrase','am I talking to a machine?','ai'),('authenticity-paraphrase','how can I establish that this call is authentic?','scam'),('prefix','How much do I owe? ','balance')]
for phase in ('dob','phone'):
 for name,q,flag in new_questions:
  v=init() if phase=='dob' else phone(); ans='9 January 1991' if phase=='dob' else '0742'; own='My birth date is '+ans if phase=='dob' else 'The last four digits are '+ans
  raw=q+own+'.' if name=='prefix' else own+'; '+q
  inp=submit(v,ans,raw,flag)
  obs('challenge/'+phase+'/'+name,v,'Conforming complete self answer plus independent admin question reaches bank after admin speech',v['route']=='security_admin' and not v['state']['verified'] and v['state']['declines']==0,'independent_challenge',inp)

for phase in ('dob','phone'):
 for name,q,flag in questions:
  v=init() if phase=='dob' else phone(); inp=turn(v,'purpose' if name in ('purpose','balance') else 'question',q,flag)
  obs('question-only/'+phase+'/'+name,v,'No comparison or verification from a question alone',v['route'] not in ('verify_identity','security_admin','get_account') and not v['state']['verified'],'control',inp)
 negatives=[('unfinished','My birthday is 9 January nineteen...' if phase=='dob' else 'My last four digits are zero seven...','security','0'),('quoted','He said "9 January 1991".' if phase=='dob' else 'She said "0742".','unknown','1'),('third-party','My sister was born on 9 January 1991.' if phase=='dob' else 'Her phone ends in 0742.','unknown','1'),('wrong-subject','The card expires on 9 January 1991.' if phase=='dob' else 'My card ends in 0742.','unknown','1'),('negated','I was not born on 9 January 1991.' if phase=='dob' else 'My last four digits are not 0742.','unknown','1'),('refusal','I refuse to answer; why are you calling?','decline','1')]
 for name,raw,kind,c in negatives:
  v=init() if phase=='dob' else phone(); inp=turn(v,kind,raw,'purpose' if name=='refusal' else 'none',c=c)
  obs('negative/'+phase+'/'+name,v,'No bank comparison for incomplete/non-self/non-asserted/refused answer',v['route'] not in ('verify_identity','security_admin','get_account') and not v['state']['verified'],'control',inp)
 # Malformed but syntactically complete security event cannot override contradictory raw.
 for name,raw in [('false-positive-third-party','My sister was born on 9 January 1991.' if phase=='dob' else 'Her last four digits are 0742.'),('false-positive-negated','I was not born on 9 January 1991.' if phase=='dob' else 'My last four digits are not 0742.')]:
  v=init() if phase=='dob' else phone(); inp=submit(v,'9 January 1991' if phase=='dob' else '0742',raw)
  obs('decoder-pollution/'+phase+'/'+name,v,'Reject wrong-subject/negative raw even with security v',v['route'] not in ('verify_identity','security_admin','get_account'),'control',inp)
 for name,kind,raw in [('human','human','I want to speak to a representative; why are you calling?'),('restructure','plan','I need lower instalments; how much do I owe?')]:
  v=init() if phase=='dob' else phone(); inp=turn(v,kind,raw,'purpose')
  obs('priority/'+phase+'/'+name,v,'Human/plan request outranks purpose; no identity verification',not v['state']['verified'] and v['state']['declines']==0 and v['route'] not in ('verify_identity','security_admin','get_account'),'control',inp)

# Wrong-answer accounting: only an explicit bank comparison changes wrong count.
v=init(); submit(v,'8 January 1991','My birthday is 8 January 1991; why are you calling?','purpose')
obs('wrong/pre-comparison-question',v,'No wrong answer or pass before bank comparison',v['state']['wrong']==0 and not v['state']['dob_passed'],'control')
receipt(v,'verify_identity',{'ok':True,'verified':False,'all_verified':False,'wrong_answers_left':2})
obs('wrong/first-bank-false',v,'Exactly one bank reported wrong answer',v['state']['wrong']==1 and not v['state']['verified'],'control')
submit(v,'9 January 1991','My birthday is 9 January 1991; how much do I owe?','balance')
obs('wrong/complete-repair-answer-question',v,'New answer reaches bank and preserves wrong count without false receipt',v['route']=='security_admin' and v['state']['wrong']==1 and not v['state']['dob_passed'],'source_known_repair')
receipt(v,'verify_identity',{'ok':True,'verified':True,'all_verified':False})
obs('wrong/fresh-DOB-pass',v,'Bank DOB pass advances to phone but does not verify identity',v['state']['phase']=='phone' and not v['state']['verified'] and v['state']['wrong']==1,'control')
submit(v,'0742','My last four digits are 0742; are you a robot?','ai')
obs('wrong/phone-answer-question-no-false-pass',v,'Bank still sole authority',v['route']=='security_admin' and not v['state']['verified'],'control')
receipt(v,'verify_identity',{'ok':True,'verified':False,'all_verified':False,'wrong_answers_left':1})
obs('wrong/second-bank-false',v,'Exactly two wrong answers',v['state']['wrong']==2 and not v['state']['verified'],'control')
submit(v,'0742'); receipt(v,'verify_identity',{'ok':True,'verified':False,'wrong_answers_left':0})
obs('wrong/third-bank-false-close',v,'Close after third wrong bank answer',v['route']=='farewell' and v['state']['wrong']==3 and not v['state']['verified'],'control')

# Freshness/operation/body challenges use actual hooks with synthetic receipts, never HTTP.
for phase in ('dob','phone'):
 for defect in ('stale-counter','wrong-operation','wrong-body'):
  v=init() if phase=='dob' else phone(); submit(v,'9 January 1991' if phase=='dob' else '0742')
  fake={'ok':True,'verified':True,'all_verified':True,'operation':'get_account' if defect=='wrong-operation' else 'verify_identity','customer_id':'OTHER-CUSTOMER' if defect=='wrong-body' else v['customer_id'],'field':'phone_last4' if phase=='dob' else 'date_of_birth','answer':'STALE-OTHER-ANSWER'}
  receipt(v,'verify_identity',fake,counter=defect!='stale-counter',body_override={'customer_id':'OTHER-CUSTOMER','field':'date_of_birth','answer':'1970-01-01'} if defect=='wrong-body' else None)
  obs('identity-guard/'+phase+'/'+defect,v,'Unfresh or mismatched comparison receipt cannot advance security',not v['state']['dob_passed'] if phase=='dob' else not v['state']['verified'],'receipt_guard_challenge',{'synthetic':True,'operation_or_body_mismatch':fake,'counter_advanced':defect!='stale-counter'})
v=phone(); submit(v,'0742'); v.update(mode='account',bank_result={'ok':True,'verified':True,'all_verified':True}); execute('dispatch',v,'wrong-mode')
obs('identity-guard/wrong-awaiting-mode',v,'Wrong mode cannot verify',not v['state']['verified'],'control')
v=phone(); submit(v,'0742'); receipt(v,'verify_identity',{'ok':True,'verified':True,'all_verified':True}); receipt(v,'get_account',{'ok':True,'products':[{'product_id':'CPU-CARD-001','type':'credit_card','card_last4':'8841','minimum_payment':90,'past_due':540,'days_late':12}]},counter=False,body_override={'customer_id':'OTHER-CUSTOMER'})
obs('account-guard/stale-counter-wrong-customer',v,'Reject stale or wrong-customer account receipt',v['state'].get('product') is None,'receipt_guard_challenge')
v=init(); submit(v,'8 January 1991'); receipt(v,'verify_identity',{'ok':True,'verified':False,'wrong_answers_left':2}); submit(v,'9 January 1991','My birthday is 9 January 1991; why are you calling?','purpose'); receipt(v,'verify_identity',{'ok':True,'verified':True,'all_verified':False,'answer':'1980-10-14','operation':'OLD_VERIFY'},counter=False)
obs('identity-guard/after-wrong-stale-counter-operation-answer',v,'New complete answer/question cannot advance from stale prior comparison',v['state']['wrong']==1 and not v['state']['dob_passed'],'receipt_guard_challenge')
for phase in ('dob','phone'):
 v=init() if phase=='dob' else phone(); ans='9 January 1991' if phase=='dob' else '0742'; submit(v,ans,'My birthday is 8 January 1991.' if phase=='dob' else 'My last four digits are 1742.')
 obs('schema/stale-security-v/'+phase,v,'Stale v conflicting with current raw cannot prepare bank comparison',v['route'] not in ('verify_identity','security_admin'),'control')
 v=init() if phase=='dob' else phone(); inp=turn(v,'security','My birthday is 9 January nineteen...; is 1991 in your records?' if phase=='dob' else 'My last four digits are zero seven...; is 0742 your number?','security_purpose',c='0')
 obs('schema/question-numbers-no-completion/'+phase,v,'Question numbers cannot finish incomplete year/digit group',v['route'] not in ('verify_identity','security_admin') and not v['state']['verified'],'control',inp)
for flags in ('paid','purpose paid','balance ai polluted','unknown-token'):
 v=init(); inp=turn(v,'question','Please clarify.',flags)
 obs('admin/exact-token/'+flags,v,'Unknown scalar tokens do not create AI answer by substring and cannot verify',not v['state']['verified'] and ('digital assistant' not in v['dialogue_line'] if flags=='paid' else True),'control',inp)

# Grouped readback, later consent, corrections and stop. No financial raw salvage.
v=account(); inp=turn(v,'proposal','I can pay 220 on 20 October 2026.',wire=extra_codec['aggregate-newline'])
obs('payment/group-newline-readback',v,'Completed independent rows combine into one readback without writing',v['state']['phase']=='readback' and v['route']=='talk' and v['state']['pending']=={'amount':220.0,'date':'2026-10-20'},'control',inp)
turn(v,'question','Is this a robot?','ai'); obs('payment/question-no-consent',v,'Question cannot create promise',v['route']!='create_promise','control')
turn(v,'confirm','Yes, I confirm.'); obs('payment/later-consent',v,'Fresh yes permits exactly readback terms',v['route']=='create_promise','control')
for name,kind,raw,fields,c in [('amount-correction','proposal','Actually, 230 on 20 October 2026.',{'a':'230','d':'20 October 2026'},'1'),('unfinished-date','change','Actually 230, but the date is...',{'u':'date','a':'230'},'0'),('withdrawn','confirm','Yes, but wait, I withdraw that.',{},'1'),('stop','stop','Stop calling me.',{},'1'),('quoted-consent','confirm','He said "yes".',{},'1')]:
 v=account(); turn(v,'proposal','220 on 20 October 2026.',fields={'a':'220','d':'20 October 2026'}); turn(v,kind,raw,fields=fields,c=c)
 obs('payment/'+name,v,'Changed/unfinished/withdrawn/stopped/quoted terms require fresh current readback and later consent',v['route']!='create_promise' and not v['state']['recorded'],'control')
for name,event,raw in [('missing-event','','I can pay 220 on 20 October 2026.'),('invalid-event','INVALID','I can pay 220 on 20 October 2026.'),('unknown-event','k=unknown;c=1;END','I can pay 220 on 20 October 2026.'),('literal-backslash-n',extra_codec['aggregate-literal-backslash-n'],'220 on 20 October 2026.'),('wrong-target','k=proposal;c=1;p=OTHER;a=220;d=20 October 2026;END','220 on 20 October 2026.')]:
 v=account(); turn(v,'unknown',raw,wire=event)
 obs('payment/no-salvage/'+name,v,'Raw financial numbers/date never authorize readback or write when event missing/invalid/unknown',v['route']!='create_promise' and not v['state'].get('pending',{}).get('amount') and v['state']['phase']!='readback','control')
for first,second in [('amount','date'),('date','amount')]:
 v=account(); turn(v,'proposal','220 on 20 October 2026.',fields={'a':'220','d':'20 October 2026'}); turn(v,'change','Actually I am changing both...',fields={'u':'both'},c='0')
 for component in (first,second):
  fields={'a':'230'} if component=='amount' else {'d':'19 October 2026'}; turn(v,'proposal','230' if component=='amount' else '19 October 2026',fields=fields)
  obs('payment/components/'+first+'-first/'+component,v,'Readback snapshot exists only after both changed components complete; never write yet',v['route']=='talk' and bool(v['state']['readback'])==(component==second),'control')
 turn(v,'confirm','Yes, no problem.'); obs('payment/components/'+first+'-first/consent',v,'Fresh later consent uses corrected pair',v['route']=='create_promise' and v['state']['pending']=={'amount':230.0,'date':'2026-10-19'},'control')
v=account(late=5); turn(v,'proposal','220 on 26 October 2026.',fields={'a':'220','d':'26 October 2026'}); obs('payment/holiday-counteroffer',v,'Holiday counteroffer requires later agreement',v['state']['offer']['date']=='2026-10-27' and v['route']=='talk','control'); turn(v,'proposal','The twenty seventh.',fields={'a':'220','d':'twenty seventh'}); obs('payment/offer-ordinal-readback',v,'Offer ordinal binds current offer with readback only',v['state']['phase']=='readback' and v['route']=='talk' and v['state']['pending']['date']=='2026-10-27','control')
v=account(late=5); turn(v,'proposal','220 on 26 October 2026.',fields={'a':'220','d':'26 October 2026'}); turn(v,'proposal','Yes, the twenty seventh.',fields={'a':'220','d':'twenty seventh'}); obs('payment/offer-ordinal-with-yes-readback',v,'Ordinal with explicit yes binds offered date but still requires later consent',v['state']['phase']=='readback' and v['route']=='talk' and v['state']['pending']['date']=='2026-10-27','control')
for vraw in ('Yes.','"Yes."','Yes, but wait.'):
 v=account(); turn(v,'proposal','220 on 20 October 2026.',fields={'a':'220','d':'20 October 2026'}); turn(v,'unknown',vraw,wire='')
 obs('payment/no-consent-raw-salvage/'+vraw,v,'Raw consent never authorizes promise when event missing',v['route']!='create_promise','control')

for name,status,counter,post,data,bad_body in [('fresh500',500,True,False,{},False),('stale500',500,False,False,{},False),('unknown503',503,True,False,{},False),('fresh-success',200,True,True,{'ok':True,'promise_id':'CPU-PROMISE-001'},False),('stale-success',200,False,True,{'ok':True,'promise_id':'CPU-OLD'},False),('wrong-body-success',200,True,True,{'ok':True},True),('empty-success',200,True,True,{},False),('explicit-false',200,True,True,{'ok':False},False)]:
 v=authorized(); original=copy.deepcopy(v['state']['authorized_promise']); request=body('create_promise',v); request['amount']=999 if bad_body else request['amount']; receipt(v,'create_promise',data,status,counter,post,request)
 passed=(v['route']=='create_promise' and v['state']['write_tries']==2 and v['state']['authorized_promise']==original) if name in ('fresh500','explicit-false') else (v['state']['recorded'] and v['route']=='farewell') if name=='fresh-success' else not v['state']['recorded'] and v['route']=='farewell'
 obs('promise-guard/'+name,v,'Fresh bound success records; documented fresh500 retries same body once; stale/missing/unknown/mismatched receipts fail closed',passed,'control')
 if name=='fresh500':
  retry_request=body('create_promise',v); obs('promise-guard/identical-retry-body',v,'Retry body is identical',retry_request==original,'control'); receipt(v,'create_promise',{},500,True,False); obs('promise-guard/second500-stops',v,'Second 500 cannot retry or claim receipt',v['route']=='farewell' and not v['state']['recorded'] and v['state']['write_tries']==2,'control')

# Missing raw is a conditional schema-contract challenge, not a producer benchmark.
for phase in ('dob','phone'):
 v=init() if phase=='dob' else phone(); v.pop('raw',None); v.update(mode='event',event='k=security;c=1;v='+('9 January 1991' if phase=='dob' else '0742')+';END',admin='none'); execute('dispatch',v,'missing-raw')
 obs('schema/missing-raw/'+phase,v,'Missing mandatory raw prevents comparison',v['route'] not in ('verify_identity','security_admin'),'schema_contract_challenge')

protected_ok=all(p.exists() and sha(p.read_bytes())==before[str(p.relative_to(ROOT))] for p in protected)
assert protected_ok
fail=[o for o in observations if not o['pass']]
findings=[]
if any(o['id'].startswith('challenge/') for o in fail): findings.append({'id':'A9-C01','severity':'critical','classification':'conforming_complete_security_plus_independent_question_source_counterexample','observed':'Question paraphrases outside security_acts are left inside answer text. The consumer then rejects complete conforming security v, although admin scalar flags correctly identify the independent question. Known repair wording passes; new challenge paraphrases fail to reach bank.','source_lines':[208,230,548,550],'witness_ids':[o['id'] for o in fail if o['id'].startswith('challenge/')],'qualification':'Conditional CPU evidence with manually supplied schema-conforming event/raw/admin; no actual producer model execution.'})
if any(o['id'].startswith(('identity-guard/','account-guard/')) for o in fail): findings.append({'id':'A9-C02','severity':'critical','classification':'identity_and_account_receipts_lack_fresh_counter_operation_body_binding','observed':'Literal verify_identity/get_account pre/post hooks and dispatcher consume ok/verified/all_verified or products while awaiting mode matches. They do not bind identity/account success to a fresh counter, requested operation, customer, field or answer. Synthetic stale/mismatched receipts advance security and expose synthetic account data. Promise receipts have separate binding guards.','source_lines':[361,407,410,411,417],'witness_ids':[o['id'] for o in fail if o['id'].startswith(('identity-guard/','account-guard/'))],'qualification':'Requires stale/misbound data reaching exported hooks; actual platform correlation is untested. This is a missing source guard, not a claimed observed backend incident.'})
if any(o['id'].startswith('schema/missing-raw') for o in fail): findings.append({'id':'A9-C03','severity':'high','classification':'mandatory_raw_missing_not_failclosed','observed':'A syntactically complete security v reaches comparison when mandatory raw is absent; exported consumer only applies current-self/raw checks if raw is truthy.','source_lines':[548,559],'witness_ids':[o['id'] for o in fail if o['id'].startswith('schema/missing-raw')],'qualification':'Conditional missing extraction control, not conforming producer emission.'})
if any(o['id']=='payment/offer-ordinal-readback' for o in fail): findings.append({'id':'A9-C04','severity':'medium','classification':'advertised_offer_ordinal_without_yes_rejected','observed':'Producer advertises day-only ordinal referring to current offer. After 26 October holiday counteroffer moves to 27 October, proposal d=twenty seventh with raw The twenty seventh cannot bind the offer; adding Yes to the same proposal succeeds. Consumer line587 restricts offered_date to agree/confirm or explicit yes/sure/okay/ok.','source_lines':[150,583,587,588],'witness_ids':['payment/offer-ordinal-readback'],'qualification':'Conditional conforming producer frame, actual CPU result; no bank write or false receipt.'})
schema_info={'event_type':schema[0]['type'],'raw_type':schema[1]['type'],'admin_type':schema[2]['type'],'admin_validation_pattern_present':'validation_pattern' in schema[2],'literal_examples':len(examples),'normalized_pattern':pattern,'decoder_split_codepoints':[ord(x) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='split' for a in n.args if isinstance(a,ast.Constant) and a.value=='\n' for x in a.value],'regex_separator_codepoints':[ord(x) for x in pattern[pattern.index('(?:',pattern.index('END'))+3:pattern.index('k=',pattern.index('END'))]],'literal_examples_all_match':all(c['regex'] and c['decoder'] for c in codec[:len(examples)]),'actual_newline_regex_decoder_match':next(c for c in codec if c['id']=='aggregate-newline'),'literal_backslash_n_rejected':next(c for c in codec if c['id']=='aggregate-literal-backslash-n'),'admin_allowed_tokens':'none ai scam purpose balance security_purpose relative_policy'.split(),'security_admin_tts':N['security_admin']['on_enter'],'security_admin_transitions':N['security_admin']['transitions']}
counts={'cpu_observations':len(observations),'cpu_pass':len(observations)-len(fail),'cpu_fail':len(fail),'literal_source_executions':len(executions),'codec_checks':len(codec),'producer_literal_examples':len(examples),'synthetic_api_hook_sequences':len(api),'critical_remaining_defects':sum(f['severity']=='critical' for f in findings),'high_remaining_defects':sum(f['severity']=='high' for f in findings),'medium_remaining_defects':sum(f['severity']=='medium' for f in findings),'by_category':{c:{'count':sum(o['category']==c for o in observations),'pass':sum(o['category']==c and o['pass'] for o in observations),'fail':sum(o['category']==c and not o['pass'] for o in observations)} for c in sorted({o['category'] for o in observations})}}
finished=datetime.datetime.now(datetime.timezone.utc).isoformat(); elapsed=(datetime.datetime.fromisoformat(finished)-datetime.datetime.fromisoformat(START.replace('Z','+00:00'))).total_seconds()
payload={'status':STATUS,'candidate':CANDIDATE,'receipt_utc':START,'finished_utc':finished,'elapsed_seconds':elapsed,'source_cpu':True,'actual_platform_client_http_git_native_dev_model_secret_reads':False,'queue_mutated':False,'candidate_patched':False,'parent_only_workspace_queue_owner':True,'qualification':'Parent R&D only; source CPU controls with synthetic bank receipts. Hosted candidate untested; deployment not qualified.','counts':counts,'source_hashes':block_hashes,'schema_inspection':schema_info,'observations':observations,'codec_checks':codec,'executions':executions,'synthetic_api_receipts':api,'protected_files_unchanged':protected_ok,'protected_file_count':len(protected),'new_independent_challenge_wording':True,'no_new_stage2_pack_read':True}
wp=ROOT/'analysis/night-codex-a9-witnesses.json'; wp.write_text(json.dumps(payload,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
runhash=sha(wp.read_bytes()); harnesshash=sha(pathlib.Path(__file__).read_bytes())
review={'status':STATUS,'candidate':CANDIDATE,'receipt_utc':START,'finished_utc':finished,'elapsed_seconds':elapsed,'within_7_minutes':elapsed<=420,'counts':counts,'findings':findings,'source_hashes':block_hashes,'source_cpu_run_sha256':runhash,'harness_sha256':harnesshash,'schema_inspection':schema_info,'protected_files_unchanged':protected_ok,'protected_file_count':len(protected),'scope':'Exact local published-normalized export; actual persistent vars and exact exported code/hooks. Manual conforming producer frames and explicit pollution controls; synthetic bank receipts only. No platform, client, HTTP, Git, native, DEV, model or secret reads. Parent owns workspace queue. No candidate patch. No stage2 pack wording.','qualification':'CLOSED source CPU review, parent R&D not qualified deployment; HOSTED UNTESTED','failed_observation_ids':[o['id'] for o in fail],'artifacts':['analysis/night-codex-a9-review.json','analysis/night-codex-a9-review.txt','analysis/night-codex-a9-witnesses.json','analysis/night-codex-a9-witnesses.txt','analysis/night-codex-a9-witnesses.py']}
(ROOT/'analysis/night-codex-a9-review.json').write_text(json.dumps(review,indent=2)+'\n',encoding='utf-8')
lines=[STATUS,'Candidate '+CANDIDATE['path'],'Candidate SHA256 '+CANDIDATE['sha256'],'Version 9 agent '+CANDIDATE['agent_id'],'Export updated_at '+CANDIDATE['updated_at']+'; publication user-attested 05:33:07 UTC','Elapsed '+str(round(elapsed,3))+' seconds; within 7 min '+str(elapsed<=420),'Actual persistent source CPU run SHA256 '+runhash,'Harness SHA256 '+harnesshash,'Counts '+json.dumps(counts),'Parent R&D only; HOSTED UNTESTED; deployment not qualified.','Protected candidate/frozen reports unchanged: '+str(protected_ok), 'Codec: '+str(len(examples))+' literal examples tested; actual newline accepted by regex and decoder; literal backslash-n rejected by both.','Schema event/raw/admin are strings; admin has no lexical validation pattern, but consumer intersects exact allowed tokens.','Bank verify_identity is sole positive authority in normal complete-answer/question runs; no speech alone sets verified. Source does not bind identity/account receipt freshness/operation/body.']
for f in findings: lines.extend(['',f['id']+' '+f['severity']+' '+f['classification'],f['observed'],f['qualification'],'Witnesses: '+', '.join(f['witness_ids'])])
(ROOT/'analysis/night-codex-a9-review.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(ROOT/'analysis/night-codex-a9-witnesses.txt').write_text('\n'.join(lines[:14]+['']+[o['id']+' '+('PASS' if o['pass'] else 'FAIL')+' route='+str(o['actual']['route'])+' phase='+str(o['actual']['phase'])+' wrong='+str(o['actual']['wrong'])+' verified='+str(o['actual']['verified']) for o in observations])+'\n',encoding='utf-8')
print(json.dumps({'status':STATUS,'candidate':CANDIDATE,'counts':counts,'source_cpu_run_sha256':runhash,'harness_sha256':harnesshash,'elapsed_seconds':elapsed,'findings':findings,'unclassified_failures':[o['id'] for o in fail if not any(o['id'] in f['witness_ids'] for f in findings)]},indent=2))
