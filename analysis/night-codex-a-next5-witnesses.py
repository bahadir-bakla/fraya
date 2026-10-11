import ast,copy,datetime,hashlib,json,pathlib,re,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
PATH=ROOT/'competition/runs/20261011-084902-0be1a0/codex-stress-a-next.workflow.json'
RECEIPT='2026-10-11T05:54:11+00:00'
STATUS='CLOSED_FROZEN_CODEX_A_NEXT5_SOURCE_CPU_REVIEW'
H=lambda b:hashlib.sha256(b).hexdigest()
export=json.loads(PATH.read_text(encoding='utf-8-sig')); W=export['workflow']; N=W['nodes']
runstatus=json.loads((PATH.parent/'status.json').read_text(encoding='utf-8-sig'))
candidate={'path':str(PATH.relative_to(ROOT)).replace('\\','/'),'sha256':H(PATH.read_bytes()),'publication_version':5,'agent_id':export['agent_id'],'workflow_id':export['workflow_id'],'updated_at':export['updated_at']}
assert candidate['sha256']=='5e4142262a89d37fd67b3a918657d2da0f99722675b28142975b34dd53cbd631'
assert candidate['agent_id']=='aa3d05ae-e605-4973-9c9f-dfabc3b995f6'
assert runstatus['phase']=='completed' and runstatus['freya']['version']==5 and runstatus['freya']['agent_id']==candidate['agent_id'] and runstatus['evaluation']=='not_evaluated' and runstatus['tests']==[]
DOC=ROOT/'competition-v3/build-the-builder/tools/openapi.json'; api_schema=json.loads(DOC.read_text(encoding='utf-8-sig'))
def response_properties(node):return api_schema['paths']['/'+node]['post']['responses']['200']['content']['application/json']['schema']['properties']
fixture_dob={'ok':True,'verified':True,'wrong_answers_left':3,'all_verified':False}
fixture_phone={'ok':True,'verified':True,'wrong_answers_left':3,'all_verified':True}
fixture_wrong={'ok':True,'verified':False,'wrong_answers_left':2,'all_verified':False}
product={'product_id':'CPU-CARD-001','type':'credit_card','card_last4':'8841','minimum_payment':90,'past_due':540,'days_late':5}
fixture_account={'ok':True,'products':[product]}
for data,node in [(fixture_dob,'verify_identity'),(fixture_phone,'verify_identity'),(fixture_wrong,'verify_identity'),(fixture_account,'get_account')]:assert set(data)<=set(response_properties(node))
protected=[PATH,PATH.parent/'status.json',DOC,ROOT/'competition-v3/build-the-builder/docs/tools-and-code.md',ROOT/'analysis/night-codex-a9-review.json',ROOT/'analysis/night-codex-a9-review.txt',ROOT/'analysis/night-codex-a9-witnesses.json',ROOT/'analysis/night-codex-a9-witnesses.txt',ROOT/'analysis/night-codex-a9-witnesses.py']
protected += [p for p in (ROOT/'analysis').glob('night-codex-a-next4-*') if p.is_file()]
before={str(p.relative_to(ROOT)).replace('\\','/'):H(p.read_bytes()) for p in protected}
old=json.loads((ROOT/'analysis/night-codex-a9-witnesses.json').read_text())
assert old['candidate']['sha256']=='471494ad17cab933aa56658e4a5d02d9c99a23bfc165386bf46a352b4585495c'
blocks={'dispatch':N['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default']}
for node in ('verify_identity','get_account','create_promise'):
 for hook in ('pre_process_code','post_process_code'):blocks[node+'/'+hook]=N[node]['pre_actions'][0][hook]
for block,source in blocks.items():
 tree=ast.parse(source); assert all(a.name in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names)
 assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('open','eval','exec','__import__') for n in ast.walk(tree))
codes={k:compile(v,'published-export:'+k,'exec') for k,v in blocks.items()}; hashes={k:H(v.encode()) for k,v in blocks.items()}
observations=[]; executions=[]; receipts=[]; codecs=[]
def snapshot(v):
 s=v.get('state',{}); return {'route':v.get('route'),'line':v.get('dialogue_line'),'phase':s.get('phase'),'verified':s.get('verified'),'dob_passed':s.get('dob_passed'),'wrong':s.get('wrong'),'declines':s.get('declines'),'clarifications':s.get('security_clarifications'),'pending':copy.deepcopy(s.get('pending')),'readback':copy.deepcopy(s.get('readback')),'recorded':s.get('recorded'),'receipt':copy.deepcopy(s.get('receipt')),'read_dispatch':copy.deepcopy(s.get('read_dispatch')),'promise_dispatch':copy.deepcopy(s.get('promise_dispatch')),'write_tries':s.get('write_tries'),'outcome':v.get('outcome'),'reason':v.get('reason'),'security_field':v.get('security_field'),'security_answer':v.get('security_answer'),'read_started':v.get('read_started'),'read_completed':v.get('read_completed')}
def execute(block,v,**args):
 env={'vars':v,**args}; exec(codes[block],env,env); executions.append({'block':block,'source_sha256':hashes[block],'result_sha256':H(json.dumps(snapshot(v),sort_keys=True).encode())}); return env
def observe(name,v,ok,contract,category='control',inputs=None):observations.append({'id':name,'pass':bool(ok),'contract':contract,'category':category,'inputs':inputs,'actual':snapshot(v)})
def turn(v,k,raw='',admin='none',fields=None,c='1',wire=None):
 event=wire if wire is not None else 'k='+k+';c='+c+';'+''.join(a+'='+str(b)+';' for a,b in (fields or {}).items())+'END'; v.update(mode='event',event=event,raw=raw,admin=admin); execute('dispatch',v); return {'event':event,'raw':raw,'admin':admin}
def init():
 v={'customer_id':'CPU-NEUTRAL-001','first_name':'Morgan','last_name':'Reed','title':'Mx','now':'2026-10-11T10:00:00','state':None,'mode':'event','raw':'','admin':'none','event':''}; execute('dispatch',v); turn(v,'recipient','Yes, Morgan Reed speaking.'); assert v['state']['phase']=='dob'; return v
def submit(v,answer,raw=None,admin='none'):return turn(v,'security',raw or answer,admin,{'v':answer})
def config(node,v):
 props=N[node]['pre_actions'][0]['function']['parameters']['properties']; b={}
 for k,p in props['body']['properties'].items():
  d=p['default']; m=re.fullmatch(r'\{\{([a-z_]+)\}\}',str(d)); b[k]=v.get(m[1],'') if m else d
 return {'url':props['url']['default'],'method':props['method']['default'],'body':b}
def api(v,node,data,counter=True,post=True,mutation=None,status=200):
 cfg=config(node,v)
 if mutation:mutation(cfg)
 execute(node+'/pre_process_code',v,config=copy.deepcopy(cfg))
 if counter:
  key=node+('_success_count' if status==200 else '_failure_count'); v[key]=int(v.get(key,0))+1
 if node=='create_promise':v.update({'create_promise_response.status':'success' if status==200 else 'error','create_promise_response.status_code':str(status),'create_promise_status_code':str(status),'create_promise_response.error':'' if status==200 else 'HTTP '+str(status)})
 if post:execute(node+'/post_process_code',v,result={'status':'success' if status==200 else 'error','status_code':status,'data':copy.deepcopy(data),'message':'synthetic documented envelope'})
 receipts.append({'node':node,'body':cfg['body'],'method_matches_fixed':cfg['method']==N[node]['pre_actions'][0]['function']['parameters']['properties']['method']['default'],'url_matches_fixed':cfg['url']==N[node]['pre_actions'][0]['function']['parameters']['properties']['url']['default'],'data':copy.deepcopy(data),'counter_advanced':counter,'post_executed':post,'status':status,'synthetic_only':True}); execute('dispatch',v)
def phone():
 v=init(); submit(v,'9 January 1991','My date of birth is 9 January 1991.'); api(v,'verify_identity',fixture_dob); assert v['state']['phase']=='phone' and v['state']['dob_passed'] and not v['state']['verified']; return v
def account():
 v=phone(); submit(v,'0742','My last four digits are zero seven four two.'); api(v,'verify_identity',fixture_phone); assert v['route']=='get_account' and v['state']['verified']; api(v,'get_account',fixture_account); assert v['state']['phase']=='offer'; return v

# Documented response fields only; no invented response echo contracts.
v=init(); submit(v,'9 January 1991'); api(v,'verify_identity',fixture_dob); observe('documented/DOB-success',v,v['state']['phase']=='phone' and not v['state']['verified'],'Documented ok/verified/wrong_answers_left/all_verified body passes without echoes','documented_fixture')
submit(v,'0742'); api(v,'verify_identity',fixture_phone); observe('documented/phone-success',v,v['route']=='get_account' and v['state']['verified'],'Documented phone body is sole positive identity authority','documented_fixture')
api(v,'get_account',fixture_account); observe('documented/get-account-success',v,v['state']['phase']=='offer' and v['state']['product']['product_id']==product['product_id'],'Documented products body loads account without customer/operation echoes','documented_fixture')
v=init(); submit(v,'8 January 1991'); api(v,'verify_identity',fixture_wrong); observe('documented/wrong-DOB',v,v['state']['wrong']==1 and not v['state']['dob_passed'],'One fresh documented wrong answer increments wrong once','documented_fixture')
submit(v,'9 January 1991','My birthday is 9 January 1991; can you tell me what I owe?','balance'); observe('documented/after-wrong-complete-question',v,v['route']=='security_admin' and v['state']['wrong']==1 and not v['state']['dob_passed'],'Complete answer and independent question have no false bank receipt','known_A9_repair'); api(v,'verify_identity',fixture_dob); observe('documented/after-wrong-fresh-pass',v,v['state']['phase']=='phone' and v['state']['wrong']==1,'Fresh successful response recovers after wrong DOB','documented_fixture')

# Reuse bounded A9 challenge frames, preserving their expected contracts.
challenge=[o for o in old['observations'] if o['category']=='independent_challenge' and not o['id'].endswith('/prefix')]
for o in challenge:
 v=init() if '/dob/' in o['id'] else phone(); inp=o['conditional_inputs']; turn(v,'security',inp['raw'],inp['admin'],wire=inp['event']); observe('A9-replay/'+o['id'],v,v['route']=='security_admin' and not v['state']['verified'] and v['state']['declines']==0,o['expected'],'known_A9_repair',inp)
for phase in ('dob','phone'):
 for q in ('Do you have branch parking?','Any weekend branch opening hours?'):
  v=init() if phase=='dob' else phone(); ans='9 January 1991' if phase=='dob' else '0742'; raw=('My birth date is ' if phase=='dob' else 'My last four digits are ')+ans+'; '+q; inp=submit(v,ans,raw,'none'); observe('arbitrary-question/'+phase+'/'+q,v,v['route']=='security_admin' and not v['state']['verified'],'Complete current self-answer plus arbitrary independent question preserves bank comparison','independent_challenge',inp)
 for name,raw,event,c in [('missing-raw','',None,'1'),('disagreement','My birthday is 8 January 1991.' if phase=='dob' else 'My last four digits are 1742.',None,'1'),('quoted','He said "9 January 1991".' if phase=='dob' else 'She said "0742".',None,'1'),('third-party','My sister was born on 9 January 1991.' if phase=='dob' else 'Her last four digits are 0742.',None,'1'),('negated','I was not born on 9 January 1991.' if phase=='dob' else 'My last four digits are not 0742.',None,'1'),('incomplete','My birthday is 9 January nineteen...; is 1991 on file?' if phase=='dob' else 'My digits are zero seven...; is 0742 your number?',None,'0')]:
  v=init() if phase=='dob' else phone(); ans='9 January 1991' if phase=='dob' else '0742'; inp=turn(v,'security',raw,fields={'v':ans} if c=='1' else {},c=c); observe('negative/'+phase+'/'+name,v,v['route'] not in ('verify_identity','security_admin','get_account') and not v['state']['verified'],'Missing/contradictory/non-self/non-asserted/incomplete raw cannot initiate comparison','known_negative',inp)

# Conditional engine corruption controls: request config and local receipt metadata, not API echoes.
for node in ('verify_identity','get_account'):
 for control in ('stale-counter','missing-posthook','wrong-body','wrong-operation-config'):
  if node=='verify_identity':v=init(); submit(v,'9 January 1991'); data=fixture_dob
  else:v=phone(); submit(v,'0742'); api(v,'verify_identity',fixture_phone); data=fixture_account
  mutation=(lambda cfg:cfg['body'].update(customer_id='OTHER-CUSTOMER')) if control=='wrong-body' else (lambda cfg:cfg.update(url='https://invalid.example/other-operation')) if control=='wrong-operation-config' else None
  api(v,node,data,counter=control!='stale-counter',post=control!='missing-posthook',mutation=mutation)
  safe=not v['state']['dob_passed'] if node=='verify_identity' else v['state'].get('product') is None
  observe('conditional/'+node+'/'+control,v,safe,'Non-current/missing-hook/wrong-config receipt cannot advance identity or reveal account','conditional_receipt_guard')
v=init(); submit(v,'8 January 1991'); api(v,'verify_identity',fixture_wrong); submit(v,'9 January 1991','My birthday is 9 January 1991; why are you calling?','purpose'); api(v,'verify_identity',fixture_dob,counter=False); observe('conditional/after-wrong-non-current',v,v['state']['wrong']==1 and not v['state']['dob_passed'],'Stale positive receipt after wrong DOB cannot pass current answer','conditional_receipt_guard')

v=account(); turn(v,'proposal','220 on 26 October 2026.',fields={'a':'220','d':'26 October 2026'}); observe('ordinal/holiday-current-offer',v,v['state']['offer']['date']=='2026-10-27' and v['route']=='talk','Holiday counteroffer is current spoken offer'); turn(v,'proposal','The twenty seventh.',fields={'a':'220','d':'twenty seventh'}); observe('ordinal/fresh-readback',v,v['state']['phase']=='readback' and v['state']['pending']=={'amount':220.0,'date':'2026-10-27'} and v['route']=='talk','Current offered ordinal must read back exact terms without writing','known_A9_repair'); turn(v,'question','Are you a digital assistant?','ai'); observe('ordinal/question-no-consent',v,v['route']!='create_promise','Question cannot supply financial consent'); turn(v,'confirm','Yes, I confirm.'); observe('ordinal/subsequent-consent',v,v['route']=='create_promise' and not v['state']['recorded'],'Subsequent fresh consent authorizes exactly current readback')
for name,raw,k,fields,c in [('withdrawn','Yes, but wait.','confirm',{},'1'),('correction','Actually 230, but the date is...','change',{'a':'230','u':'date'},'0'),('missing-event','Yes.','unknown',{},'1')]:
 v=account(); turn(v,'proposal','220 on 20 October 2026.',fields={'a':'220','d':'20 October 2026'}); turn(v,k,raw,fields=fields,c=c,wire='' if name=='missing-event' else None); observe('payment/'+name,v,v['route']!='create_promise','Withdrawal/incomplete correction/missing event never salvages raw consent')
v=account(); turn(v,'proposal','220 on 20 October 2026.',wire='k=proposal;c=1;a=220;END\nk=proposal;c=1;d=20 October 2026;END'); observe('payment/group-readback',v,v['state']['readback']=={'amount':220.0,'date':'2026-10-20'} and v['route']=='talk','Actual newline facts form one readback, not a write')
v=account(); turn(v,'unknown','I can pay 220 on 20 October 2026.',wire=''); observe('payment/no-numeric-date-raw-salvage',v,not v['state']['pending'] and v['route']!='create_promise','No financial date/numeric salvage from missing event')
v=account(); turn(v,'proposal','220 on 20 October 2026.',fields={'a':'220','d':'20 October 2026'}); turn(v,'confirm','Yes.'); request=copy.deepcopy(v['state']['authorized_promise']); api(v,'create_promise',{},status=500,post=False); observe('promise/fresh500-identical-retry',v,v['route']=='create_promise' and v['state']['write_tries']==2 and config('create_promise',v)['body']==request,'Fresh documented 500 retries identical authorized body once'); api(v,'create_promise',{},status=500,post=False); observe('promise/second500-stop',v,v['route']=='farewell' and not v['state']['recorded'] and v['state']['write_tries']==2,'Second 500 cannot retry or claim receipt')

schema=N['talk']['extraction_schema']; pattern=schema[0]['validation_pattern']; examples=[x for x in schema[0]['description'].splitlines() if x.startswith('k=')]; assert len(examples)==28
env=execute('dispatch',{'state':None,'now':'2026-10-11T10:00:00'}); decode=env['decode']
extra={'actual-newline':'k=proposal;c=1;a=220;END\nk=proposal;c=1;d=20 October 2026;END','literal-backslash-n':'k=proposal;c=1;a=220;END\\nk=proposal;c=1;d=20 October 2026;END','duplicate-key':'k=proposal;c=1;a=220;a=230;END','unknown-kind':'k=malicious;c=1;END','complete-with-u':'k=proposal;c=1;u=date;a=220;END'}
for name,text in [(f'literal-{i+1}',t) for i,t in enumerate(examples)]+list(extra.items()):
 try:rows=decode(text); accepted=True; error=None
 except Exception as e:rows=[]; accepted=False; error=str(e)
 expected=name.startswith('literal-') and name!='literal-backslash-n' or name=='actual-newline'
 regex=bool(re.fullmatch(pattern,text)); codecs.append({'id':name,'wire':text,'regex_accepts':regex,'decoder_accepts':accepted,'error':error,'pass':(regex and accepted) if expected else not accepted and (not regex if name=='literal-backslash-n' else True)})
assert len(observations)+len(codecs)<=100
assert all(H(p.read_bytes())==before[str(p.relative_to(ROOT)).replace('\\','/')] for p in protected)
fails=[o for o in observations if not o['pass']]; findings=[]
if any(o['id'].startswith('arbitrary-question/') for o in fails):findings.append({'id':'A5-I01','severity':'critical','classification':'complete_security_plus_fragment_question_still_blocked','observed':'A9 explicit interrogative paraphrases now pass. An independent fragment question beginning Any is not recognized by security_acts and remains in the primary answer. Complete conforming v is rejected by security_fallback, preventing bank comparison despite a complete neutral own DOB/phone answer.','witness_ids':[o['id'] for o in fails if o['id'].startswith('arbitrary-question/')],'conditional':True,'source_lines':[211,213,235,565,566]})
other=[o for o in fails if not o['id'].startswith('arbitrary-question/')]
if other:findings.append({'id':'A5-I02','severity':'critical','classification':'remaining_source_contract_failure','witness_ids':[o['id'] for o in other],'conditional':True})
counts={'cpu_observations':len(observations),'cpu_pass':len(observations)-len(fails),'cpu_fail':len(fails),'codec_checks':len(codecs),'codec_pass':sum(c['pass'] for c in codecs),'producer_literals':len(examples),'literal_source_executions':len(executions),'synthetic_hook_sequences':len(receipts),'critical_remaining_defects':sum(f['severity']=='critical' for f in findings),'categories':{c:{'count':sum(o['category']==c for o in observations),'fail':sum(o['category']==c and not o['pass'] for o in observations)} for c in sorted({o['category'] for o in observations})}}
finish=datetime.datetime.now(datetime.timezone.utc).isoformat(); elapsed=(datetime.datetime.fromisoformat(finish)-datetime.datetime.fromisoformat(RECEIPT)).total_seconds()
publication={'phase':runstatus['phase'],'version':runstatus['freya']['version'],'agent_id':runstatus['freya']['agent_id'],'workflow_id':runstatus['freya']['workflow_id'],'evaluation':runstatus['evaluation'],'tests':runstatus['tests'],'completed_utc':runstatus['ended'],'status_sha256':H((PATH.parent/'status.json').read_bytes()),'verification_scope':'Local completed auto-export/status evidence; no live platform check.'}
docs={'path':str(DOC.relative_to(ROOT)).replace('\\','/'),'sha256':H(DOC.read_bytes()),'response_fields':{n:list(response_properties(n)) for n in ('verify_identity','get_account')},'fixtures':{'dob_success':fixture_dob,'phone_success':fixture_phone,'wrong_dob':fixture_wrong,'get_account':fixture_account},'echo_operation_customer_body_fields_required':False,'hook_contract_path':'competition-v3/build-the-builder/docs/tools-and-code.md','fixed_llm_bank_tools':{n:len(N[n].get('tools',[])) for n in ('talk','verify_identity','get_account','create_promise')},'pre_actions_invoked_locally_without_model_or_http':True}
scope='Exact completed published v5 normalized export; bounded A9 contract replays and new independent fragment question challenge. Exact exported code/hooks executed against persistent vars. Documented API shape fixtures, synthetic local envelopes/counters only. No actual platform/native/Git/model/bank tools/keys or HTTP reads or calls; no candidate patch; parent owns queue. Conditional corruption controls are not observed backend incidents. Hosted evaluation not yet started at recorded status; independent source review is not deployment qualification.'
payload={'status':STATUS,'candidate':candidate,'publication':publication,'receipt_utc':RECEIPT,'finished_utc':finish,'elapsed_seconds':elapsed,'within_5_minutes':elapsed<=300,'scope':scope,'counts':counts,'source_hashes':hashes,'documented_api':docs,'observations':observations,'codec_checks':codecs,'executions':executions,'synthetic_receipts':receipts,'protected_inputs_sha256':before,'protected_inputs_unchanged':True,'findings':findings,'schema_types':{s['name']:s['type'] for s in schema},'normalized_pattern':pattern,'regex_separator_codepoints':[ord(x) for x in pattern[pattern.index('(?:',pattern.index('END'))+3:pattern.index('k=',pattern.index('END'))]]}
out=ROOT/'analysis/night-codex-a-next5-witnesses.json';out.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8'); runhash=H(out.read_bytes()); harnesshash=H(pathlib.Path(__file__).read_bytes())
review={k:payload[k] for k in ('status','candidate','publication','receipt_utc','finished_utc','elapsed_seconds','within_5_minutes','scope','counts','source_hashes','documented_api','findings','protected_inputs_sha256','protected_inputs_unchanged','schema_types','regex_separator_codepoints')};review.update(source_cpu_run_sha256=runhash,harness_sha256=harnesshash,witness_path='analysis/night-codex-a-next5-witnesses.json',qualification='Parent R&D only; independent source review is not qualification; hosted evaluation not started at frozen local status.')
(ROOT/'analysis/night-codex-a-next5-review.json').write_text(json.dumps(review,indent=2)+'\n',encoding='utf-8')
lines=[STATUS,'Candidate '+candidate['path'],'Candidate SHA256 '+candidate['sha256'],'Publication version5 agent '+candidate['agent_id'],'Local status completed, not_evaluated, tests=[]; no live platform read','Elapsed seconds '+str(round(elapsed,3)),'Counts '+json.dumps(counts),'CPU run SHA256 '+runhash,'Harness SHA256 '+harnesshash,'Dispatch SHA256 '+hashes['dispatch'],'Documented identity/get_account successful response fixtures pass without echo operation/body/customer fields.','Protected export and frozen inputs unchanged.','Conditional receipt controls are synthetic corruption tests, not actual backend incidents.','Hosted evaluation not yet started in local status; parent R&D review not qualification.']
for f in findings:lines+=['',f['id']+' '+f['severity']+' '+f['classification'],f.get('observed',''),', '.join(f['witness_ids'])]
(ROOT/'analysis/night-codex-a-next5-review.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(ROOT/'analysis/night-codex-a-next5-witnesses.txt').write_text('\n'.join(lines[:14]+['']+[o['id']+' '+('PASS' if o['pass'] else 'FAIL')+' route='+str(o['actual']['route'])+' phase='+str(o['actual']['phase'])+' wrong='+str(o['actual']['wrong']) for o in observations])+'\n',encoding='utf-8')
print(json.dumps({'status':STATUS,'candidate':candidate,'counts':counts,'findings':findings,'elapsed_seconds':elapsed,'run_sha256':runhash,'harness_sha256':harnesshash,'dispatch_sha256':hashes['dispatch']},indent=2))
