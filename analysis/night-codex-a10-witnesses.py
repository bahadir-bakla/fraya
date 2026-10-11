import ast,copy,datetime,hashlib,json,pathlib,re,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
PATH=ROOT/'competition/runs/20261011-090256-a12ce9/codex-stress-a.workflow.json'
RECEIPT='2026-10-11T06:09:20+00:00'
STATUS='CLOSED_FROZEN_CODEX_A10_SOURCE_CPU_REVIEW'
H=lambda b:hashlib.sha256(b).hexdigest()
export=json.loads(PATH.read_text(encoding='utf-8-sig')); W=export['workflow']; N=W['nodes']
runstatus=json.loads((PATH.parent/'status.json').read_text(encoding='utf-8-sig'))
candidate={'path':str(PATH.relative_to(ROOT)).replace('\\','/'),'sha256':H(PATH.read_bytes()),'publication_version':10,'agent_id':export['agent_id'],'workflow_id':export['workflow_id'],'updated_at':export['updated_at']}
assert candidate['sha256']=='6b73ea7c11e7ac412f66f17dfba42dda3c72128919b5bc758681473d0181f2f7'
assert candidate['agent_id']=='37b17600-df9a-4934-854e-a3de8f2e7987'
assert runstatus['phase']=='completed' and runstatus['freya']['version']==10 and runstatus['freya']['agent_id']==candidate['agent_id'] and runstatus['evaluation']=='not_evaluated' and runstatus['tests']==[]
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


# Eight focused new controls: 52 A5 CPU contract replays + 8 = 60 maximum.
v={'customer_id':'CPU-NEUTRAL-001','first_name':'Morgan','last_name':'Reed','title':'Mx','now':'2026-10-11T10:00:00','state':None}; execute('dispatch',v)
observe('A10/opening-recording-and-digital-notice',v,'recorded' in v['dialogue_line'].lower() and 'digital assistant' in v['dialogue_line'].lower(),'Mandatory recorded-call and transparent digital assistant notice')
v=init()
for left in (2,1):
 submit(v,'8 January 1991','My date of birth is 8 January 1991, thanks for checking.'); api(v,'verify_identity',{'ok':True,'verified':False,'all_verified':False,'wrong_answers_left':left})
inp=submit(v,'8 January 1991','My date of birth is 8 January 1991, thanks for checking.')
observe('A10/third-wrong-DOB-neutral-aside-before-bank',v,v['state']['wrong']==2 and v['route']=='verify_identity' and not v['state']['dob_passed'],'Complete third DOB answer plus neutral aside reaches bank without fabricated wrong comparison','target',inp)
api(v,'verify_identity',{'ok':True,'verified':False,'all_verified':False,'wrong_answers_left':0})
observe('A10/third-fresh-negative-fixture-close',v,v['state']['wrong']==3 and v['route']=='farewell' and v['outcome']=='not_verified' and v['reason']=='failed','Close only after third actual documented-shape synthetic negative comparison receipt','target')
for name,raw,answer,c in [('grouped-exact-four','Fifteen zero two','1502','1'),('grouped-incomplete','Fifteen zero','150','0'),('grouped-mismatch','Fifteen one two','1502','1'),('grouped-wrong-subject','My invoice number is fifteen zero two.','1502','1')]:
 v=phone(); inp=turn(v,'security',raw,fields={'v':answer} if c=='1' else {},c=c)
 ok=(v['route']=='verify_identity' and v['security_answer']=='1502' and not v['state']['verified']) if name=='grouped-exact-four' else v['route'] not in ('verify_identity','security_admin','get_account') and not v['state']['verified']
 observe('A10/'+name,v,ok,'Fifteen zero two is exactly 1502; no guessed padding, mismatches or wrong subject acceptance','target',inp)
v=init(); inp=turn(v,'security','My birthday is ninth January nineteen...; you a robot?','ai',c='0')
observe('A10/incomplete-question-transparent',v,v['route'] not in ('verify_identity','security_admin','get_account') and v['state']['wrong']==0 and 'digital assistant' in v['dialogue_line'].lower(),'Incomplete answer still answers AI question transparently without fake bank failure','target',inp)

assert len(observations)==60
schema=N['talk']['extraction_schema']; pattern=schema[0]['validation_pattern']; examples=[x for x in schema[0]['description'].splitlines() if x.startswith('k=')]; assert len(examples)==28
E=execute('dispatch',{'state':None,'now':'2026-10-11T10:00:00'}); decoder=E['decode']
for label,wire in [(f'literal-{i+1}',x) for i,x in enumerate(examples)]+[('actual-newline','k=proposal;c=1;a=220;END\nk=proposal;c=1;d=20 October 2026;END'),('literal-backslash-n','k=proposal;c=1;a=220;END\\nk=proposal;c=1;d=20 October 2026;END')]:
 try:rows=decoder(wire); accepted=True; error=None
 except Exception as e:accepted=False; error=str(e)
 regex=bool(re.fullmatch(pattern,wire)); expected=label!='literal-backslash-n'; codecs.append({'id':label,'wire':wire,'regex':regex,'decoder':accepted,'pass':regex==accepted==expected,'error':error})
oldp=ROOT/'competition/runs/20261011-084902-0be1a0/codex-stress-a-next.workflow.json'; oldw=json.loads(oldp.read_text(encoding='utf-8-sig'))['workflow']; olds=oldw['nodes']['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default']; oldtree=ast.parse(olds)
changes={'changed_functions':[n.name for n in ast.parse(blocks['dispatch']).body if isinstance(n,ast.FunctionDef) and not any(isinstance(m,ast.FunctionDef) and m.name==n.name and ast.dump(m)==ast.dump(n) for m in oldtree.body)],'hooks_identical_to_A5':{n:all(N[n]['pre_actions'][0][k]==oldw['nodes'][n]['pre_actions'][0][k] for k in ('pre_process_code','post_process_code')) for n in ('verify_identity','get_account','create_promise')},'old_export_sha256':H(oldp.read_bytes()),'old_dispatch_sha256':H(olds.encode())}
assert changes['old_export_sha256']=='5e4142262a89d37fd67b3a918657d2da0f99722675b28142975b34dd53cbd631'
assert H((ROOT/'analysis/night-codex-a-next5-witnesses.py').read_bytes())=='d6a33f7fe56fae50c8a6c9c0f13cf7b910b52416a561f2d67ce3e60d243cdd38'
assert all(H(p.read_bytes())==before[str(p.relative_to(ROOT)).replace('\\','/')] for p in protected)
for p in (ROOT/'analysis').glob('night-codex-a-next5-*'):before[str(p.relative_to(ROOT)).replace('\\','/')]=H(p.read_bytes())
before[str(oldp.relative_to(ROOT)).replace('\\','/')]=H(oldp.read_bytes())
fail=[o for o in observations if not o['pass']]
within_case_reproduction=[]
if any(o['id']=='negative/dob/third-party' for o in fail):
 v=init(); inp=turn(v,'unknown','My sister was born on 9 January 1991.')
 within_case_reproduction.append({'parent_case':'negative/dob/third-party','contract':'Conforming unknown producer event must not borrow third-party DOB from raw','inputs':inp,'actual':snapshot(v),'pass':v['route'] not in ('verify_identity','security_admin')})
counts={'runtime_cases':len(observations),'runtime_pass':len(observations)-len(fail),'runtime_fail':len(fail),'A5_contract_replays':52,'A10_new_target_cases':8,'literal_code_executions':len(executions),'synthetic_hook_sequences':len(receipts),'codec_checks':len(codecs),'codec_pass':sum(c['pass'] for c in codecs),'producer_literal_examples':28,'categories':{c:{'count':sum(o['category']==c for o in observations),'fail':sum(o['category']==c and not o['pass'] for o in observations)} for c in sorted({o['category'] for o in observations})}}
findings=[]
for o in fail:findings.append({'id':o['id'],'severity':'critical' if o['category'] in ('target','documented_fixture','independent_challenge','known_A9_repair') or any(not x['pass'] and x['parent_case']==o['id'] for x in within_case_reproduction) else 'high','conditional':True,'contract':o['contract'],'observed':o['actual'],'inputs':o['inputs'],'source_note':'security_fallback blocks many third-party words but omits sister; local my context then permits sister DOB. Conforming unknown-frame within-case reproduction also checked. No actual backend incident or verified identity claimed.','source_lines':[276,280,332,641]})
finish=datetime.datetime.now(datetime.timezone.utc).isoformat(); elapsed=(datetime.datetime.fromisoformat(finish)-datetime.datetime.fromisoformat(RECEIPT)).total_seconds()
publication={'phase':runstatus['phase'],'version':runstatus['freya']['version'],'agent_id':runstatus['freya']['agent_id'],'elapsed_generation_seconds':runstatus['elapsed_s'],'evaluation':runstatus['evaluation'],'tests':runstatus['tests'],'ended':runstatus['ended'],'status_sha256':H((PATH.parent/'status.json').read_bytes()),'verification':'Local completed auto-export/status; no live platform read'}
limits='Exact local newly published auto A10 source and persistent hooks; 60 runtime cases, plus 28 literal codec examples and two separator checks. Documented API successful/wrong fixtures contain no invented operation/body echoes. All receipts/counters are synthetic CPU inputs. Conditional stale/misbinding controls are not actual hosted incidents. No model, platform, native, Git, network, keys, candidate/source edits, parser followup, or model training. Only owned A10 review/witness files written. Known source exposures are not qualification; original judge, actors and expected results untouched. Parent alone owns workspace queue; original30 not run by this reviewer.'
payload={'status':STATUS,'candidate':candidate,'publication':publication,'receipt_utc':RECEIPT,'finished_utc':finish,'elapsed_seconds':elapsed,'within_3_minutes':elapsed<=180,'counts':counts,'source_hashes':hashes,'changed_source_review':changes,'limits':limits,'documented_api_path':str(DOC.relative_to(ROOT)).replace('\\','/'),'documented_api_sha256':H(DOC.read_bytes()),'documented_response_fields':{n:list(response_properties(n)) for n in ('verify_identity','get_account')},'documented_success_fixtures':{'DOB':fixture_dob,'phone':fixture_phone,'account':fixture_account},'observations':observations,'executions':executions,'synthetic_receipts':receipts,'codec_checks':codecs,'findings':findings,'protected_inputs_sha256':before,'protected_inputs_unchanged':True,'qualification':'Hosted not evaluated in frozen local status; independent source review not deployment qualification.'}
payload['within_case_conforming_reproduction']=within_case_reproduction
wp=ROOT/'analysis/night-codex-a10-witnesses.json'; wp.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8'); runhash=H(wp.read_bytes()); harnesshash=H(pathlib.Path(__file__).read_bytes())
review={k:payload[k] for k in ('status','candidate','publication','receipt_utc','finished_utc','elapsed_seconds','within_3_minutes','counts','source_hashes','changed_source_review','limits','documented_api_path','documented_api_sha256','documented_response_fields','findings','protected_inputs_sha256','protected_inputs_unchanged','qualification','within_case_conforming_reproduction')}; review.update(source_cpu_run_sha256=runhash,harness_sha256=harnesshash,witness_path='analysis/night-codex-a10-witnesses.json')
(ROOT/'analysis/night-codex-a10-review.json').write_text(json.dumps(review,indent=2)+'\n',encoding='utf-8')
lines=[STATUS,'Candidate '+candidate['path'],'Candidate SHA256 '+candidate['sha256'],'Publication v10 agent '+candidate['agent_id'],'Completed auto generation322s; local status not_evaluated tests=[]','Elapsed '+str(round(elapsed,3))+'s; within3min '+str(elapsed<=180),'Actual persistent CPU counts '+json.dumps(counts),'CPU run SHA256 '+runhash,'Harness SHA256 '+harnesshash,'Dispatch source SHA256 '+hashes['dispatch'],'Changed source '+json.dumps(changes),'Protected export and frozen inputs unchanged.','All receipts synthetic; negative guard controls explicitly conditional.','Independent source review is not qualification; original judge/actors/expected immutable.']
for f in findings:lines+=['',f['id']+' '+f['severity'],f['contract'],json.dumps(f['observed'])]
(ROOT/'analysis/night-codex-a10-review.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(ROOT/'analysis/night-codex-a10-witnesses.txt').write_text('\n'.join(lines[:14]+['']+[o['id']+' '+('PASS' if o['pass'] else 'FAIL')+' route='+str(o['actual']['route'])+' phase='+str(o['actual']['phase'])+' wrong='+str(o['actual']['wrong']) for o in observations])+'\n',encoding='utf-8')
print(json.dumps({'status':STATUS,'candidate':candidate,'elapsed_seconds':elapsed,'counts':counts,'findings':findings,'run_sha256':runhash,'harness_sha256':harnesshash,'dispatch_sha256':hashes['dispatch']},indent=2))
