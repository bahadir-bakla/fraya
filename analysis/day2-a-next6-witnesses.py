import ast,copy,datetime,hashlib,json,pathlib,re,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
RUN=ROOT/'competition/runs/20261011-120033-ec0e86'
EXPORT=RUN/'codex-stress-a-next.workflow.json'
START='2026-10-11T09:06:12Z'
DEADLINE='2026-10-11T09:16:12Z'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
existing=ROOT/'analysis/day2-a-next6-witnesses.json'
if existing.exists() and json.loads(existing.read_text(encoding='utf-8')).get('status','').startswith('CLOSED_FROZEN'):
 raise SystemExit('Frozen report exists; copy the owned helper to a newly authorized output prefix before rerunning.')
status=json.loads((RUN/'status.json').read_text(encoding='utf-8'))
assert status['id']==RUN.name and status['phase']=='completed' and status['freya']['version']==6
frozen=[EXPORT,RUN/'status.json',*sorted((RUN/'work').glob('*.py')),*sorted((RUN/'work/inputs').glob('*')),RUN/'work/policy.json',RUN/'work/coverage.json',RUN/'work/workflow.json',RUN/'work/day2-repair-feedback.json']
frozen=[p for p in frozen if p.is_file()]
before={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in frozen}
assert sha(EXPORT)=='ae31ec476820bd965c63598c524108b472ea340475fc2e2b01a299042a1e9351'
export=json.loads(EXPORT.read_text(encoding='utf-8'));assert export['agent_id']=='aa3d05ae-e605-4973-9c9f-dfabc3b995f6'
N=export['workflow']['nodes']; SOURCE=N['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
assert SOURCE==(RUN/'work/dispatch.py').read_text(encoding='utf-8')
blocks={'dispatch':SOURCE}
for node in ['verify_identity','get_account','create_promise']:
 for h in ['pre_process_code','post_process_code']:blocks[node+'/'+h]=N[node]['pre_actions'][0][h]
for source in blocks.values():
 tree=ast.parse(source)
 assert all(a.name in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names)
 assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('open','eval','exec','__import__') for n in ast.walk(tree))
codes={k:compile(s,'literal_export:'+k,'exec') for k,s in blocks.items()};codehash={k:hashlib.sha256(s.encode()).hexdigest() for k,s in blocks.items()}
executions=[];observations=[];wirechecks=[];receipts=[]
def view(v):
 s=v.get('state') or {};return {'route':v.get('route'),'phase':s.get('phase'),'speech':v.get('dialogue_line'),'verified':s.get('verified'),'dob_passed':s.get('dob_passed'),'wrong':s.get('wrong'),'declines':s.get('declines'),'pending':copy.deepcopy(s.get('pending')),'readback':copy.deepcopy(s.get('readback')),'offer':copy.deepcopy(s.get('offer')),'floor_offered':s.get('floor_offered'),'attempts':s.get('attempts'),'recorded':s.get('recorded'),'write_tries':s.get('write_tries'),'outcome':v.get('outcome'),'reason':v.get('reason'),'security_field':v.get('security_field'),'security_answer':v.get('security_answer'),'authorized_promise':copy.deepcopy(s.get('authorized_promise')),'promise_dispatch':copy.deepcopy(s.get('promise_dispatch'))}
class Store:
 def __init__(self,first='Avery',last='Stone',title='Dr'):
  self.values={'now':'2026-10-14T11:00:00','customer_id':'CPU-NEUTRAL-001','first_name':first,'last_name':last,'title':title,'state':None,'mode':'event','event':'','raw':'','admin':'none'};self.label='init';self.call('dispatch')
 def call(self,block,**extras):
  previous=copy.deepcopy(self.values);v=copy.deepcopy(previous);env={'vars':v,**copy.deepcopy(extras)};t=time.perf_counter();exec(codes[block],env,env)
  # Merge changed/new keys only. Deletion is not assumed to erase persisted variables.
  patch={k:copy.deepcopy(x) for k,x in v.items() if k not in previous or x!=previous[k]};self.values.update(patch)
  executions.append({'id':len(executions)+1,'label':self.label,'block':block,'source_sha256':codehash[block],'changed_keys':sorted(patch),'deleted_keys_not_persisted':[k for k in previous if k not in v],'elapsed_ms':round((time.perf_counter()-t)*1000,3),'actual':view(self.values)})
  return env
 def turn(self,kind,raw='',c='1',fields=None,wire=None,admin='none',label=None):
  self.label=label or kind;event=wire if wire is not None else 'k='+kind+';c='+c+';'+''.join(k+'='+str(v)+';' for k,v in (fields or {}).items())+'END';self.values.update(mode='event',event=event,raw=raw,admin=admin);self.call('dispatch');return {'event':event,'raw':raw,'admin':admin}
 def receipt(self,node,data,status_code=200,post=True,counter=True,body_change=None,token_stale=False):
  props=N[node]['pre_actions'][0]['function']['parameters']['properties']
  def render(x):
   if isinstance(x,dict) and x.get('type')=='object':return {k:render(v) for k,v in x.get('properties',{}).items()}
   value=x.get('default');m=re.fullmatch(r'\{\{([a-z_]+)\}\}',str(value));return self.values.get(m[1],'') if m else value
  config={k:render(v) for k,v in props.items() if k in ('url','method','body')}
  if body_change:config['body'].update(body_change)
  self.label='conditional/'+node+'/pre';self.call(node+'/pre_process_code',config=config)
  if token_stale:self.values['read_started']='STALE'
  if counter:
   key=node+('_success_count' if status_code==200 else '_failure_count');self.values[key]=int(self.values.get(key,0))+1
  if node=='create_promise':self.values.update({'create_promise_response.status':'success' if status_code==200 else 'error','create_promise_response.status_code':str(status_code),'create_promise_status_code':str(status_code),'create_promise_response.error':'' if status_code==200 else 'HTTP '+str(status_code)})
  if post:self.label='conditional/'+node+'/post';self.call(node+'/post_process_code',result={'status_code':status_code,'data':data})
  receipts.append({'node':node,'body':copy.deepcopy(config['body']),'conditional_result':copy.deepcopy(data),'status':status_code,'post_hook_executed':post,'counter_advanced':counter,'stale_token':token_stale})
  self.label='conditional/'+node+'/dispatch';self.call('dispatch');return config['body']
def amount_question(s):return bool(re.search(r'how much.{0,35}(?:pay|afford)|what amount|(?:finish|specify|repeat|choose|tell me|complete).{0,45}(?:amount|sum)|(?:amount).{0,35}(?:finish|specify|repeat|choose)',s or '',re.I))
def obs(name,store,expected,passed,inputs=None,classification='advertised_contract_conditional_cpu'):
 observations.append({'id':name,'class':classification,'expected':expected,'pass':bool(passed),'inputs':inputs,'actual':view(store.values),'forbidden_amount_question':amount_question(store.values.get('dialogue_line',''))})
def safe_recipient(st):
 s=st.values['state'];return not s['verified'] and not s['dob_passed'] and st.values['route']=='talk' and s.get('product') is None and not s.get('read_dispatch') and not s.get('promise_dispatch') and not re.search(r'past.due|collections|credit.card|loan|you owe',st.values.get('dialogue_line',''),re.I)
def dob():
 st=Store();st.turn('recipient','Yes, this is Avery Stone speaking.');assert st.values['state']['phase']=='dob';return st
def phone():
 st=dob();st.turn('security','My birth date is 9 January 1991.',fields={'v':'1991-01-09'});assert st.values['route']=='verify_identity';st.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':False});assert st.values['state']['phase']=='phone' and not st.values['state']['verified'];return st
def account(late=12):
 st=phone();st.turn('security','My last four digits are zero seven four two.',fields={'v':'0742'});st.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':True});assert st.values['route']=='get_account';st.receipt('get_account',{'ok':True,'products':[{'product_id':'CPU-CARD-001','type':'credit_card','card_last4':'8841','minimum_payment':90,'past_due':540,'days_late':late}]});assert st.values['state']['phase']=='offer';return st
def proposal(st,amount='220',date='20 October 2026'):
 return st.turn('proposal','I can pay '+amount+' on '+date+'.',fields={'a':amount,'d':date})
def ready():
 st=account();proposal(st);assert st.values['state']['phase']=='readback';return st
# Neutral fixture names are independent of public identities.
positives=['Yes.','That is me.','Speaking.','Avery Stone.','Dr Stone.','This is Dr Stone, Avery.','Stone, Avery.','This is Stone, Avery speaking.','Yes, this is Dr Avery Stone speaking.','Hello, this is Avery Stone.','Yes, that is me.','This is Avery Stone; are you a robot?','This is Dr Stone, Avery. Why are you calling?']
for text in positives:
 st=Store();inp=st.turn('recipient',text,admin='ai' if 'robot' in text else 'purpose' if 'calling' in text else 'none');obs('recipient/positive/'+text,st,'Advance only to DOB; no bank verification, disclosure or comparison.',st.values['state']['phase']=='dob' and safe_recipient(st),inp)
for first,last,title,text in [('Léa',"O’Neil",'Ms',"This is Ms O'Neil, Léa."),('Anne-Marie','Quinn','Dr','Yes, this is Dr Anne-Marie Quinn speaking.'),('Ji','Park','Mx','Park, Ji.'),('Avery','Stone','Dr','Dr. Stone, Avery!')]:
 st=Store(first,last,title);inp=st.turn('recipient',text);obs('recipient/unicode-title/'+text,st,'Symmetric supplied-name punctuation/Unicode normalization; recipient only.',st.values['state']['phase']=='dob' and safe_recipient(st),inp)
negatives=[('wrong-first','This is Dr Stone, Blair.','unknown'),('wrong-last','This is Avery Slate.','unknown'),('wrong-title','This is Ms Avery Stone.','unknown'),('third-party','Avery Stone is my sister.','third_party'),('named-other','This is my colleague Avery Stone.','third_party'),('quoted','He said "This is Avery Stone".','unknown'),('single-quote',"'This is Avery Stone.'",'unknown'),('hypothetical','If I were Avery Stone, I would say yes.','unknown'),('negative','This is not Avery Stone.','wrong_number'),('bare-wrong-name','Blair Stone.','unknown'),('unrelated-clause','Avery Stone filed the invoice.','unknown'),('greeting','Hello.','unknown')]
for name,text,kind in negatives:
 for forced in [False,True]:
  st=Store();inp=st.turn('recipient' if forced else kind,text);obs('recipient/negative/'+name+('/forced-semantic-inconsistent' if forced else ''),st,'No advancement to DOB or bank disclosure for non-self/mismatched act.',st.values['state']['phase']!='dob' and not st.values['state']['verified'] and not st.values['state'].get('product') and st.values['route'] not in ['verify_identity','get_account','create_promise'],inp,'forced_semantic_inconsistent_event' if forced else 'advertised_contract_conditional_cpu')
# Whole-turn explicit contradiction cannot be reduced to a matching name prefix.
for raw in ['This is Avery Stone, but actually I am Blair Stone.', 'This is Dr Stone, Avery; I am his sister.']:
 for forced in [False,True]:
  st=Store();inp=st.turn('recipient' if forced else 'unknown',raw);obs('recipient/whole-turn-contradiction/'+raw+('/forced' if forced else ''),st,'Do not discard an explicit contradictory identity clause; recipient is not bank authority.',st.values['state']['phase']!='dob' and not st.values['state']['verified'] and st.values['route'] not in ['verify_identity','get_account','create_promise'],inp,'forced_semantic_inconsistent_event' if forced else 'advertised_contract_conditional_cpu')

# Literal scalar producer/regex/decoder compatibility.
env=Store().call('dispatch');decode=env['decode'];schema=N['talk']['extraction_schema'];primary=next(x for x in schema if x['name']=='event');pattern=primary.get('validation_pattern');examples=[x for x in primary['description'].splitlines() if x.startswith('k=')]
for name,text in [(f'example-{i+1}',s) for i,s in enumerate(examples)]+[('aggregate-actual-newline','k=proposal;c=1;a=220;END\nk=proposal;c=1;d=20 October 2026;END'),('aggregate-literal-backslash-n','k=proposal;c=1;a=220;END\\nk=proposal;c=1;d=20 October 2026;END'),('unknown-key','k=proposal;c=1;a=220;x=bad;END'),('nonfinite','k=proposal;c=1;a=NaN;END')]:
 try:rows=decode(text);accepted=True;error=None
 except Exception as e:rows=[];accepted=False;error=str(e)
 wirechecks.append({'id':name,'wire':text,'pattern_matches':bool(re.fullmatch(pattern,text)) if pattern else None,'decoder_accepts':accepted,'rows':rows,'error':error})
# Source operands may prepare a comparison, never confer verified status.
for phase in ['dob','phone']:
 for name,raw in [('third-party','My sister was born on 9 January 1991.' if phase=='dob' else 'Her phone ends in 0742.'),('named-subject','Jordan was born on 9 January 1991.' if phase=='dob' else "Jordan's phone ends in 0742."),('quoted','The note says "9 January 1991".' if phase=='dob' else 'The note says "0742".'),('conditional','If my birthday were 9 January 1991.' if phase=='dob' else 'If my phone ended in 0742.'),('unfinished','My birthday is 9 January nineteen...' if phase=='dob' else 'My last four digits are zero seven...')]:
  st=dob() if phase=='dob' else phone();inp=st.turn('unknown',raw,wire='');obs('security/missing-event/'+phase+'/'+name,st,'No bank comparison from non-self/quoted/conditional/incomplete raw.',st.values['route'] not in ['verify_identity','security_admin','get_account','create_promise'] and not st.values['state']['verified'],inp,'caller_contract_violation_missing_primary')
  st=dob() if phase=='dob' else phone();inp=st.turn('security',raw,fields={'v':'1991-01-09' if phase=='dob' else '0742'});obs('security/polluted-event/'+phase+'/'+name,st,'Typed security candidate still requires current matching self-source.',st.values['route'] not in ['verify_identity','security_admin','get_account','create_promise'] and not st.values['state']['verified'],inp,'forced_semantic_inconsistent_event')
for phase in ['dob','phone']:
 st=dob() if phase=='dob' else phone();ans='1991-01-09' if phase=='dob' else '0742';raw='My birthday is 9 January 1991; why are you calling?' if phase=='dob' else 'My last four digits are zero seven four two; are you a robot?';inp=st.turn('security',raw,fields={'v':ans},admin='purpose' if phase=='dob' else 'ai');obs('security/concurrent-answer-question/'+phase,st,'Complete self answer survives administrative question; no pass before receipt.',st.values['route'] in ['security_admin','verify_identity'] and not st.values['state']['verified'],inp)
 for defect in ['stale-counter','wrong-body','stale-token']:
  x=dob() if phase=='dob' else phone();x.turn('security','9 January 1991' if phase=='dob' else '0742',fields={'v':ans});x.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':True},counter=defect!='stale-counter',body_change={'customer_id':'OTHER'} if defect=='wrong-body' else None,token_stale=defect=='stale-token');obs('security/receipt/'+phase+'/'+defect,x,'Only current operation/body/token/counter-bound bank receipt advances.',not x.values['state']['dob_passed'] if phase=='dob' else not x.values['state']['verified'])
st=dob();st.turn('security','9 January 1991',fields={'v':'1991-01-09'});st.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':True});obs('security/DOB-only-allverified',st,'DOB comparison alone cannot authorize account read/disclosure.',not st.values['state']['verified'] and st.values['state']['phase']=='phone' and st.values['route']=='talk')
# Corrections invalidate consent and only independently completed components resolve.
for missing in ['amount','date','both','unknown']:
 st=ready();fields={'u':missing};raw='Actually the '+missing+' is...';
 if missing=='amount':fields['d']='21 October 2026'
 if missing=='date':fields['a']='230'
 inp=st.turn('change',raw,c='0',fields=fields);obs('partial/'+missing+'/begin',st,'Invalidate readback, retain only unaffected independently completed component; neutral amount pause.',st.values['route']!='create_promise' and st.values['state']['readback'] is None and st.values['state']['pending'].get('incomplete') and not amount_question(st.values['dialogue_line']),inp)
 inp=st.turn('confirm','Yes, no problem.');obs('partial/'+missing+'/stale-yes',st,'No borrowing an earlier offer or consent while component unfinished.',st.values['route']!='create_promise' and st.values['state']['readback'] is None and not amount_question(st.values['dialogue_line']),inp)
 if missing in ['amount','both','unknown']:
  inp=st.turn('proposal','21 October 2026.',fields={'d':'21 October 2026'});obs('partial/'+missing+'/date-only',st,'Date alone cannot finish unresolved amount or restore readback.',st.values['route']!='create_promise' and (st.values['state']['pending'].get('amount') is None or (missing=='unknown' and st.values['state']['pending'].get('incomplete') and 'amount' not in st.values['state']['pending'].get('completed_components',[]))) and st.values['state']['readback'] is None and not amount_question(st.values['dialogue_line']),inp)
  inp=st.turn('proposal','230.',fields={'a':'230'})
 else:inp=st.turn('proposal','21 October 2026.',fields={'d':'21 October 2026'})
 obs('partial/'+missing+'/completed-pair',st,'Fresh full product/amount/date readback, no write until later yes.',st.values['route']=='talk' and st.values['state']['phase']=='readback' and st.values['state']['pending'].get('amount')==230 and st.values['state']['pending'].get('date')=='2026-10-21',inp)
 inp=st.turn('confirm','Yes, I confirm.');obs('partial/'+missing+'/fresh-later-yes',st,'Only corrected exact pair is authorized.',st.values['route']=='create_promise' and st.values['state']['authorized_promise']['amount']==230 and st.values['state']['authorized_promise']['date']=='2026-10-21',inp)
# All financial recovery speeches: malformed/missing inputs are never raw financial authority.
for name,wire,raw in [('missing','','I can pay 230 on 21 October 2026.'),('malformed','BROKEN','Actually, the amount is...'),('unknown','k=unknown;c=1;END','Please clarify.'),('bad-target','k=proposal;c=1;p=OTHER;a=230;d=21 October 2026;END','230 on 21 October 2026.'),('bad-codec','k=proposal;c=1;a=NaN;END','Actually the amount is...')]:
 st=ready();st.turn('change','Actually the amount is...',c='0',fields={'u':'amount'});inp=st.turn('unknown',raw,wire=wire);obs('speech/recovery/'+name,st,'No forbidden amount question, no raw financial salvage, no stale write.',not amount_question(st.values['dialogue_line']) and st.values['route']!='create_promise' and st.values['state']['readback'] is None and st.values['state']['pending'].get('amount') is None,inp,'caller_contract_violation' if name in ['malformed','bad-codec','bad-target'] else 'advertised_contract_conditional_cpu')
for name,amount,date in [('above-full','600','20 October 2026'),('below-floor','20','20 October 2026'),('past-date','220','13 October 2026'),('holiday','220','26 October 2026'),('after-deadline','220','2 November 2026'),('invalid-date','220','31 February 2026')]:
 st=account();inp=proposal(st,amount,date);obs('speech/amount-date/'+name,st,'Policy amount/date recovery never asks customer to supply/finish an amount; no write.',not amount_question(st.values['dialogue_line']) and st.values['route']!='create_promise',inp)
# Once-floor and mandatory warning are separate from repetition judged by old transcripts.
st=account();st.turn('too_much','That full amount is too much.');first=copy.deepcopy(st.values['state']);obs('floor/first-offer',st,'Offer floor once and warn rest overdue.',first['floor_offered'] and first['offer']['amount']==90 and 'rest stays overdue' in st.values['dialogue_line'])
st.turn('confirm','Yes, no problem.');obs('floor/readback-warning',st,'Rule34 fresh full readback; warning may appear again, brief has no global once-warning ban.',st.values['route']=='talk' and st.values['state']['phase']=='readback' and st.values['state']['readback']['amount']==90 and 'rest stays overdue' in st.values['dialogue_line'])
st=account();st.turn('too_much','That is too much.');st.turn('too_much','The minimum is too much too.');obs('floor/no-repeat-normal-offer',st,'A second too-much consumes persuasion rather than another ordinary floor offer.',st.values['state']['floor_offered'] and st.values['state']['attempts']==1 and st.values['state']['offer']['amount']==90)
st.turn('refuse','No.');obs('floor/late-attempt2',st,'Late band attempt2 may name floor on deadline under rule26/30.',st.values['state']['attempts']==2 and st.values['state']['offer']['amount']==90 and st.values['state']['offer']['date']==st.values['state']['product']['deadline']);st.turn('refuse','No.');obs('floor/exhausted',st,'Close after allowed persuasion without another offer.',st.values['route']=='farewell' and st.values['outcome']=='no_promise' and st.values['reason']=='refused')
for late in [5,12]:
 st=account(late);st.turn('refuse','No.');st.turn('refuse','No.');
 if late==12:st.turn('refuse','No.')
 obs('preservation/persuasion/'+str(late),st,'Early one attempt, late two attempts, then refused close.',st.values['route']=='farewell' and st.values['state']['attempts']==(1 if late==5 else 2))
st=account();st.turn('hardship','I lost my job.');obs('preservation/hardship',st,'Sympathy/support before persuasion.',st.values['state']['phase']=='support' and st.values['state']['attempts']==0);st.turn('decline','No, thank you.');obs('preservation/hardship-decline',st,'Close hardship without persuasion.',st.values['route']=='farewell' and st.values['reason']=='hardship')
for raw in ['Yes, but wait, I withdraw that.','Yes, if I get paid.','He said "yes".','Yes, actually the amount is...']:
 st=ready();inp=st.turn('confirm',raw);obs('consent/qualified-or-quoted/'+raw,st,'No write from withdrawn/conditional/quoted/unfinished yes.',st.values['route']!='create_promise' and not st.values['state']['recorded'],inp,'forced_semantic_inconsistent_event')
st=account(5);proposal(st,'220','26 October 2026');obs('preservation/holiday-offer',st,'Holiday advances to27 October and requires acceptance/readback.',st.values['state']['offer']['date']=='2026-10-27' and st.values['route']=='talk');st.turn('proposal','The twenty seventh.',fields={'d':'twenty seventh'});obs('preservation/ordinal-inheritance',st,'Current ordinal bound to offered27October, no direct write.',st.values['state']['phase']=='readback' and st.values['state']['pending']['date']=='2026-10-27' and st.values['route']=='talk')
st=account();inp=st.turn('proposal','220 on20 October2026.',wire='k=proposal;c=1;a=220;END\nk=proposal;c=1;d=20 October 2026;END');obs('preservation/aggregate-decoder',st,'Literal decoder merges actual newline completed rows; regex compatibility reported separately.',st.values['state']['phase']=='readback' and st.values['state']['pending']=={'amount':220.0,'date':'2026-10-20'},inp)
# No-posthook documented500 is distinct from application false and unknown timeout.
for condition in ['documented500','application-false','stale500','unknown504']:
 st=ready();st.turn('confirm','Yes, I confirm.');firstbody=st.receipt('create_promise',{'ok':False,'error':'service unavailable; nothing recorded'} if condition!='application-false' else {'ok':False},status_code=500 if condition in ['documented500','stale500'] else 504 if condition=='unknown504' else 200,post=condition=='application-false',counter=condition!='stale500');retry=st.values['route']=='create_promise';obs('receipt/'+condition+'/retry',st,'Exactly one retry only for fresh documented500 or applicationfalse; no premature recorded/SMS.',retry==(condition in ['documented500','application-false']) and not st.values['state']['recorded'] and 'Your promise is recorded' not in st.values['dialogue_line'])
 if retry:
  secondbody=st.receipt('create_promise',{'ok':True,'promise_id':'CPU-PROMISE-001'});obs('receipt/'+condition+'/identical-retry-success',st,'Exact body identical on retry; acknowledge/SMS only after current oktrue receipt.',firstbody==secondbody and st.values['state']['recorded'] and st.values['outcome']=='promise' and 'You will receive a text message confirming this promise.' in st.values['dialogue_line'])
st=ready();st.turn('confirm','Yes, I confirm.');st.receipt('create_promise',{},status_code=500,post=False);st.receipt('create_promise',{},status_code=500,post=False);obs('receipt/two500-close',st,'Stop after second documented failure, no acknowledgement.',st.values['route']=='farewell' and st.values['reason']=='service_error' and st.values['state']['write_tries']==2 and not st.values['state']['recorded'])
# Follow-up on concrete subject failures: valid unknown rows vs missing primary channel.
for phase in ['dob','phone']:
 for subject in ['sister','brother','partner','neighbour']:
  raw='My '+subject+' was born on 9 January 1991.' if phase=='dob' else 'My '+subject+' has last four digits 0742.'
  st=dob() if phase=='dob' else phone();inp=st.turn('unknown',raw);obs('security/conforming-unknown/'+phase+'/'+subject,st,'Current non-self assertion cannot become a self comparison through raw fallback.',st.values['route'] not in ['verify_identity','security_admin','get_account','create_promise'] and not st.values['state']['verified'],inp)
# Cache-preservation is not cache-consumption: unresolved unknown corrections retain
# old scalar cache but completed_components still gates authority.
st=ready();st.turn('change','Actually the terms are...',c='0',fields={'u':'unknown'});st.turn('proposal','21 October 2026.',fields={'d':'21 October 2026'});st.turn('confirm','Yes, I confirm.');obs('partial/unknown/cached-amount-not-authority',st,'A cached amount does not finish the required amount; no readback or write.',st.values['route']=='talk' and st.values['state']['readback'] is None and st.values['state']['pending'].get('incomplete') and 'amount' not in st.values['state']['pending'].get('completed_components',[]))
# A newly spoken permitted amount offer, explicitly accepted, may replace unfinished terms.
st=ready();st.turn('change','Actually the amount is...',c='0',fields={'u':'amount'});old=copy.deepcopy(st.values['state']['offer']);st.turn('too_much','The full amount is too much.');new=copy.deepcopy(st.values['state']['offer']);obs('partial/new-floor-offer',st,'Fresh permitted floor offer clears unfinished proposal, warns, changes offer revision.',new['amount']==90 and new['revision']>old['revision'] and not st.values['state']['pending'] and 'rest stays overdue' in st.values['dialogue_line']);st.turn('agree','Yes, no problem.');obs('partial/new-floor-acceptance',st,'Acceptance of new agent terms reaches readback only.',st.values['route']=='talk' and st.values['state']['readback']['amount']==90 and st.values['state']['readback']['date']==new['date']);st.turn('confirm','Yes, I confirm.');obs('partial/new-floor-later-consent',st,'Subsequent clear yes authorizes exactly new offered terms, never old amount.',st.values['route']=='create_promise' and st.values['state']['authorized_promise']['amount']==90 and st.values['state']['authorized_promise']['date']==new['date'])
# Account stale/cross-customer receipt never grants product disclosure.
for defect in ['stale-counter','wrong-body']:
 st=phone();st.turn('security','0742',fields={'v':'0742'});st.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':True});st.receipt('get_account',{'ok':True,'products':[{'product_id':'CPU-CARD-001','type':'credit_card','card_last4':'8841','minimum_payment':90,'past_due':540,'days_late':12}]},counter=defect!='stale-counter',body_change={'customer_id':'OTHER'} if defect=='wrong-body' else None);obs('account/receipt/'+defect,st,'Reject non-current account results and disclose no financial product.',st.values['state'].get('product') is None and 'past-due amount' not in st.values['dialogue_line'])
# API body mismatch and stale success cannot manufacture successful acknowledgement.
for defect in ['wrong-body','stale-counter']:
 st=ready();st.turn('confirm','Yes, I confirm.');st.receipt('create_promise',{'ok':True,'promise_id':'CPU-UNTRUSTED'},counter=defect!='stale-counter',body_change={'amount':230} if defect=='wrong-body' else None);obs('promise/receipt/'+defect,st,'No recorded/SMS acknowledgement from mismatched body or unfresh success.',not st.values['state']['recorded'] and 'Your promise is recorded' not in st.values['dialogue_line'] and st.values['route']=='farewell')

# Independently challenge legitimate requested-field surfaces and comma isolation.
security_good={'dob':[('bare','9 January 1991','1991-01-09'),('self','My date of birth is 9 January 1991.','1991-01-09'),('born','I was born on9 January1991.','1991-01-09'),('yearwords','My birthday is ninth January nineteen ninety one.','1991-01-09')], 'phone':[('bare','0742','0742'),('self','My last four digits are zero seven four two.','0742'),('phone-number','My phone number ends in0742.','0742'),('phone-short','My phone ends in0742.','0742'),('field-with-of','The last four digits of my phone number are0742.','0742'),('grouped','Fifteen zero two.','1502')]}
for phase,items in security_good.items():
 for name,raw,answer in items:
  raw=raw.replace('on9','on 9').replace('January1991','January 1991').replace('in0742','in 0742').replace('are0742','are 0742')
  st=dob() if phase=='dob' else phone();inp=st.turn('security',raw,fields={'v':answer});obs('security/legitimate-surface/'+phase+'/'+name,st,'Complete current self/bare requested-field answer prepares comparison only.',st.values['route']=='verify_identity' and not st.values['state']['verified'] and st.values.get('security_answer')==answer,inp)
for phase in ['dob','phone']:
 for subject in ['My sister,','My brother,','My partner,','Jordan,']:
  raw=subject+' 9 January 1991.' if phase=='dob' else subject+' 0742.'
  for typed in [False,True]:
   st=dob() if phase=='dob' else phone();inp=st.turn('security' if typed else 'unknown',raw,fields={'v':'1991-01-09' if phase=='dob' else '0742'} if typed else None);obs('security/comma-nonself/'+phase+'/'+subject+('/typed' if typed else ''),st,'Comma cannot erase non-self prefix or lend identity operands.',st.values['route'] not in ['verify_identity','security_admin','get_account','create_promise'] and not st.values['state']['verified'],inp,'forced_semantic_inconsistent_event' if typed else 'advertised_contract_conditional_cpu')
# Exact saved A11 payment paraphrases; this is conditional replay on the new source.
paid_positives=[('actual-paid-adverb','I actually paid it in the app this morning.'),('actual-made-payment','I already made the payment through the app today.'),('actual-processed-contraction',"I've already processed the payment through the app this morning."),('processed-expanded','I have already processed the payment through the app this morning.'),('made-simple','I made the payment today.'),('completed','I completed the payment through the app today.'),('paid-bare','I already paid.'),('paid-current-product','I paid the credit card this morning.'),('paid-same-target-canonical',"I paid the credit card ending8841 through the app today.")]
for name,raw in paid_positives:
 raw=raw.replace('ending8841','ending 8841');st=account();inp=st.turn('paid',raw);obs('paid/current-positive/'+name,st,'Typed current completed self-paid claim closes paid, no promise.',st.values['route']=='farewell' and st.values['outcome']=='paid' and not st.values['state']['recorded'] and not st.values['state'].get('promise_dispatch'),inp,'saved_A11_raw_new_source_conditional_cpu' if name.startswith('actual-') else 'advertised_contract_conditional_cpu')
paid_negatives=[('negated','I have not paid it in the app today.'),('future','I will make the payment tomorrow.'),('hypothetical','If I made the payment today, would that help?'),('quoted','He said "I paid the credit card today".'),('single-quoted',"'I paid it this morning.'"),('third-party','My sister made the payment this morning.'),('historical-payoff','I paid off the credit card years ago.'),('historical-payment','I made the payment in2024.'),('future-dated-completed','I processed the payment tomorrow.'),('unrelated-shopping','I paid for shopping this morning.'),('unrelated-hotel','I made the payment for the hotel this morning.'),('unrelated-tuition','I processed the payment for tuition this morning.'),('different-bank-product','I paid the personal loan this morning.'),('unfinished','I actually paid the...'),('withdrawn-current-assertion','I paid it today, but I did not actually pay this overdue amount.')]
for name,raw in paid_negatives:
 raw=raw.replace('in2024','in 2024')
 for forced in [False,True]:
  st=account();inp=st.turn('paid' if forced else 'unknown',raw);obs('paid/non-current-negative/'+name+('/forced-paid' if forced else ''),st,'Non-current/non-self/unfinished/negated/unrelated claim cannot close paid or create promise.',st.values['outcome']!='paid' and st.values['route']!='create_promise' and not st.values['state']['recorded'],inp,'forced_semantic_inconsistent_event' if forced else 'advertised_contract_conditional_cpu')
# An actually incomplete primary is different from a complete malformed row.
st=account();inp=st.turn('paid','I actually paid the...',c='0');obs('paid/c0-unfinished',st,'Unfinished paid primary cannot decide paid outcome.',st.values['outcome']!='paid' and st.values['route']!='create_promise',inp)
# A stale readback receipt snapshot cannot authorize corrected terms.
st=ready();old=copy.deepcopy(st.values['state']['readback']);st.turn('proposal','230 on21 October2026.',fields={'a':'230','d':'21 October 2026'});obs('consent/corrected-terms-readback',st,'Changed valid terms read back in full before any write.',st.values['route']=='talk' and st.values['state']['readback']['amount']==230 and st.values['state']['readback']['date']=='2026-10-21' and st.values['state']['readback']!=old)
st.turn('confirm','Yes, no problem.');obs('consent/corrected-terms-later-yes',st,'Later yes binds revised pair only.',st.values['route']=='create_promise' and st.values['state']['authorized_promise']['amount']==230 and st.values['state']['authorized_promise']['date']=='2026-10-21')

# Explicit identifier scope and Unicode quotation cannot borrow current authority.
for name,raw,expected in [('matching-card-digits','I paid the credit card ending8841 this morning.',True),('other-card-digits','I paid the credit card ending7736 this morning.',False),('already-paid-contraction',"I've already paid it in the app this morning.",True)]:
 raw=raw.replace('ending8841','ending 8841').replace('ending7736','ending 7736');st=account();inp=st.turn('paid',raw);obs('paid/identifier-or-contraction/'+name,st,'Completed self claim must match explicit current product identifier; first-person contraction preserves assertion.',(st.values['outcome']=='paid')==expected and st.values['route']!='create_promise',inp,'forced_semantic_inconsistent_event' if not expected else 'advertised_contract_conditional_cpu')
for raw in ['“Yes, I confirm.”','‘Yes, I confirm.’','He said “yes”.','My sister said yes.']:
 st=ready();inp=st.turn('confirm',raw);obs('consent/non-self-or-Unicode-quotation/'+raw,st,'Quoted or attributed yes is not current self permission, even with polluted confirm row.',st.values['route']!='create_promise' and not st.values['state']['recorded'],inp,'forced_semantic_inconsistent_event')

# Correctly produced unknown rows for the same quoted/attributed utterances fail closed.
for raw in ['“Yes, I confirm.”','‘Yes, I confirm.’','He said “yes”.','My sister said yes.']:
 st=ready();inp=st.turn('unknown',raw);obs('consent/unknown-producer-control/'+raw,st,'Conforming unknown primary for quotation/attribution cannot authorize a promise.',st.values['route']!='create_promise' and not st.values['state']['recorded'],inp)

# Static literals plus every actual computed speech from all executed blocks.
literal_speech=[]
for name,node in N.items():
 text=node.get('on_enter',{}).get('text','')
 if text:literal_speech.append({'node':name,'text':text,'forbidden_amount_question':amount_question(text)})
for key,source in blocks.items():
 for x in ast.walk(ast.parse(source)):
  if isinstance(x,ast.Constant) and isinstance(x.value,str) and ('?' in x.value or 'Please ' in x.value) and amount_question(x.value):literal_speech.append({'source':key,'line':x.lineno,'text':x.value,'forbidden_amount_question':True})
failed=[o for o in observations if not o['pass']];forbidden=[e for e in executions if amount_question(e['actual']['speech'])];after={p:sha(ROOT/p) for p in before};assert before==after
payload={'status':'SOURCE_CPU_EXECUTED_PENDING_FINAL_REVIEW_FREEZE','reviewer':'Codex fallback; no native attempts or Opus claim','started_utc':START,'deadline_utc':DEADLINE,'executed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate':{'path':str(EXPORT),'sha256':sha(EXPORT),'version':6,'agent_id':export['agent_id'],'workflow_id':export['workflow_id'],'controller_sha256':codehash['dispatch'],'controller_equals_export':True,'publication_status_completed':True},'limits':'Literal candidate snippets and deterministic patch-store CPU execution only, with manually conditioned semantic event rows and synthetic API receipts. No actual extractor inference, HTTP requests, hosted calls or platform simulation. Bank truth never established by CPU fixtures. No hosted frequency/pass claim.','store_contract':'Copy persisted table into each block; merge changed/new returned variables; omitted/deleted keys persist; explicit empty resets must be written. The precise actual platform merge behavior remains a caller assumption.','counts':{'assertions':len(observations),'passed':len(observations)-len(failed),'failed':len(failed),'literal_block_executions':len(executions),'codec_checks':len(wirechecks),'computed_speech_forbidden_amount_questions':len(forbidden)},'failed_assertions':failed,'producer_schema':schema,'producer_pattern_repr':repr(pattern),'codec_checks':wirechecks,'static_speech_scan':literal_speech,'observations':observations,'executions':executions,'conditional_receipts':receipts,'source_hashes_before':before,'source_hashes_after':after,'protected_sources_unchanged':True,'neutral_fixtures':{'first_name':'Avery','last_name':'Stone','title':'Dr','additional_names':['Léa O’Neil','Anne-Marie Quinn','Ji Park']},'original_tests':'No original tests, expectations, actor, judge or scores modified. Selected preservation controls independently execute current source; old tests are not rerun or promoted.'}
(ROOT/'analysis/day2-a-next6-witnesses.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'analysis/day2-a-next6-witnesses.txt').write_text('Codex fallback literal-source CPU witnesses for published A-next6.\n'+json.dumps(payload['candidate'],indent=2)+'\n'+json.dumps(payload['counts'],indent=2)+'\nFailed assertions:\n'+ '\n'.join(o['id']+' :: '+json.dumps(o['actual'],ensure_ascii=False) for o in failed)+'\nCodec disagreements:\n'+'\n'.join(json.dumps(x,ensure_ascii=False) for x in wirechecks if x['pattern_matches']!=x['decoder_accepts'])+'\nNo hosted/extractor inference or API calls. Protected hashes unchanged. Full detail in JSON.\n',encoding='utf-8')
print(json.dumps({'candidate':payload['candidate'],'counts':payload['counts'],'failed_ids':[o['id'] for o in failed],'codec_disagreements':[x['id'] for x in wirechecks if x['pattern_matches']!=x['decoder_accepts']],'forbidden_literal_strings':[x for x in literal_speech if x['forbidden_amount_question']]}))
