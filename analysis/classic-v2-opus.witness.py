"""Independent unchanged literal-source CPU probes; no bank/platform calls."""
import ast,copy,datetime,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'competition/runs/20261011-141710-d6397a';PATH=RUN/'work/workflow.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
workflow=json.loads(PATH.read_bytes());source=workflow['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
assert sha(PATH)=='4db038772a5484a3915187b3c8514971cfe71020c8c63d23229eddd1515c55a3'
tree=ast.parse(source)
assert all(a.name in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names)
assert not any(isinstance(n,ast.ImportFrom) for n in ast.walk(tree))
compiled=compile(source,'unchanged-failed-classic-source','exec')
unit=copy.deepcopy(tree);unit.body=[n for n in unit.body if isinstance(n,(ast.Import,ast.Assign,ast.FunctionDef))];pure={};exec(compile(unit,'unchanged-classic-units','exec'),pure)
protected=[PATH,RUN/'status.json',ROOT/'analysis/classic-v2-opus.native.json',ROOT/'analysis/classic-merged-hardening.json',ROOT/'competition/builder.py',ROOT/'competition/semantic_assist.py',ROOT/'competition/dialogue_assist.py']
before={p.relative_to(ROOT).as_posix():sha(p) for p in protected};rows=[];calls=0
def observe(name,expected,actual,kind='literal_contract_cpu',detail=None):rows.append({'id':name,'passed':actual==expected,'expected':expected,'actual':actual,'classification':kind,'detail':detail})
class Store:
 def __init__(self,state=None):
  self.v=copy.deepcopy(state) if state is not None else {'customer_id':'CPU-INDEPENDENT','first_name':'Riley','last_name':'Vale','title':'Mx','now':'2026-10-14T11:00'};self.trace=[]
  if state is None:self.run()
 def state(self):return json.loads(self.v['state'])
 def run(self):
  global calls
  working=copy.deepcopy(self.v);exec(compiled,{'vars':working});self.v.update(working);calls+=1
  self.trace.append({'route':self.v['route'],'phase':self.v.get('phase'),'line':self.v['dialogue_line'],'op':copy.deepcopy(self.state().get('op',{})),'verified':self.state().get('verified')})
 def turn(self,raw,kind=None,target='current',complete='1',span=None,fields=None,extra=None):
  if kind is None:wire=''
  else:
   record={'k':kind,'c':complete,'p':target,'s':raw if span is None else span};record.update(fields or {})
   records=[record]+(extra or []);wire='\n'.join('|'.join(k+'='+str(v) for k,v in r.items()) for r in records)+'\nEND'
  self.v.update(speech=raw,event=wire,admin='');self.run()
 def receipt(self,data,current=True):
  op=self.state()['op']['name'];count='api_'+op+('_success_count' if data.get('ok') else '_failure_count')
  if current:self.v[count]=int(self.v.get(count,0))+1
  self.v.update(receipt_op=op,receipt=json.dumps(data),speech='',event='',admin='');self.run()
 def facts(self):
  return {'route':self.v['route'],'phase':self.state()['phase'],'verified':self.state()['verified'],'op':copy.deepcopy(self.state().get('op',{})),'products':[{'id':p['product_id'],'status':p['status'],'amount':p.get('a'),'date':p.get('d'),'attempts':p['attempts'],'needs':p['needs'],'noted':p.get('noted',False)} for p in self.state()['products']]}
# Permissive recipient vs true identity controls, with present and absent events.
recipient=[('Yes',True),('Speaking.',True),('Yes, this is Riley.',True),('Mx Vale speaking.',True),('Vale, Riley',True),("I just said, that's me.",True),('Yes, Riley Vale, are you a robot?',True),('No, this is his wife.',False),('I am Morgan Vale.',False),('My brother is Riley Vale.',False),('If I were Riley Vale, I would say yes.',False)]
for raw,expected in recipient:
 for present in (True,False):
  s=Store();s.turn(raw,'recipient' if present else None)
  observe('recipient/'+raw+'/'+str(present),expected,s.state()['phase']=='dob',detail=s.facts())
  observe('recipient-never-verifies/'+raw+'/'+str(present),False,s.state()['verified'],detail={'write_route':s.v['route'] in ('api_create_promise','api_add_note'),'account_route':s.v['route']=='api_get_account'})
# Independent security clauses test Opus claims rather than assuming them.
security=[('4 May 1987',True),('My date of birth is 4 May 1987.',True),('Her date of birth is 4 May 1987.',False),("My cousin's birthday is 4 May 1987.",False),('4 May 1987, but why would you need that?',True)]
for raw,expected in security:
 s=Store();s.turn('Yes','recipient');s.turn(raw,'security',fields={'d':'1987-05-04'})
 observe('security/'+raw,expected,s.v['route']=='api_verify_identity','conforming_or_negative_literal_source',s.facts())
 observe('security-no-local-verification/'+raw,False,s.state()['verified'])
s=Store();s.turn('Yes','recipient');s.turn("My sister's date of birth is 4 May 1987.",'security',span='4 May 1987',fields={'d':'1987-05-04'})
observe('security/truncated-source-subject',False,s.v['route']=='api_verify_identity','inconsistent_producer_source_span',s.facts())
s=Store();s.turn('Yes','recipient');s.turn('4 May...','security',complete='0',fields={'u':'date'});s.turn('nineteen eighty-seven','security',fields={'d':'1987-05-04'})
observe('security/proposed-cross-turn-fragment',True,s.v['route']=='api_verify_identity','proposed_fragment_contract_not_current_producer_observation',s.facts())
def account():
 s=Store();s.turn('Yes','recipient');s.turn('4 May 1987','security',fields={'d':'1987-05-04'})
 s.receipt({'ok':True,'verified':True,'all_verified':False,'wrong_answers_left':3})
 s.turn('2718','security',fields={'t':'2718'});s.receipt({'ok':True,'verified':True,'all_verified':True,'wrong_answers_left':3})
 s.receipt({'ok':True,'products':[{'product_id':'cpu-card','type':'credit_card','card_last4':'2718','past_due':400,'minimum_payment':100,'days_late':4},{'product_id':'cpu-loan','type':'personal_loan','past_due':600,'instalment_amount':200,'days_late':20}]})
 return s
base=account().v
s=Store(base);s.turn('"No, I refuse", said my brother.','unknown',target='cpu-card')
observe('unknown/nonasserted-row-no-refusal',0,s.state()['products'][0]['attempts'],'producer_conforming_unknown_kind',s.facts())
s=Store(base);s.turn('I will pay the card 200 on 20 October.','proposal',target='cpu-card',fields={'a':'200','d':'2026-10-20'})
s.turn('I withdraw permission for the card. I will pay the loan 300 on 21 October.','withdraw',target='cpu-card',extra=[{'k':'proposal','c':'1','p':'cpu-loan','s':'I will pay the loan 300 on 21 October.','a':'300','d':'2026-10-21'}])
observe('correction/scoped-withdraw-retains-sibling-proposal',30000,s.state()['products'][1].get('a'),'producer_conforming_mixed_rows',s.facts())
s=Store(base);s.turn('For the card, 200, sorry, 250 on 20 October.','proposal',target='cpu-card',span='For the card, 200',fields={'a':'200'},extra=[{'k':'proposal','c':'1','p':'cpu-card','s':'sorry, 250 on 20 October.','a':'250','d':'2026-10-20'}])
observe('correction/no-order-contract-clarifies',False,s.v['route']=='api_create_promise','unordered_producer_rows_control',s.facts())
for target in ('all','cpu-card,cpu-loan'):
 s=Store(base);s.turn('I will pay both bank products in full on 2 November.','proposal',target=target,fields={'d':'2026-11-02'})
 observe('shared-date/'+target,True,all(p.get('d')==p['deadline'] for p in s.state()['products']),'producer_conforming_equivalent_collective_scope',s.facts())
s=Store();s.turn('Yes','recipient');s.turn('4 May 1987','security',fields={'d':'1987-05-04'});s.receipt({'ok':False,'error':'unreadable_value'})
observe('identity/unreadable-not-retried-unchanged',False,s.v['route']=='api_verify_identity','synthetic_application_false_unreadable_receipt',s.facts())
for current in (False,True):
 s=Store(base);s.turn('Yes','accept',target='all');s.turn('Yes, I confirm.','confirm',target='all');s.receipt({'ok':True,'promise_id':'CPU-SYNTHETIC-RECEIPT'},current=current)
 observe('receipt/current='+str(current),current,any(p['status']=='recorded' for p in s.state()['products']),'synthetic_current_or_stale_receipt_control',s.facts())
s=Store(base);s.turn('I dispute both bank products.','dispute',target='all');body=s.state()['op']['body'];observe('note/no-security-copy',{'product_id':'cpu-card','reason':'dispute','text':'Customer disposition: dispute'},body,'note_body_control')
s.receipt({'ok':False,'error':'service_unavailable'});s.receipt({'ok':False,'error':'service_unavailable'})
attempts={t['op'].get('body',{}).get('product_id') for t in s.trace if t['op'].get('name')=='add_note'}
observe('note/failed-first-does-not-drop-sibling',{'cpu-card','cpu-loan'},attempts,'synthetic_note_retry_obligation',s.facts())
# Derive raw and adjusted mock totals without rescoring/revising anything.
mock=ROOT/'analysis/mock-final-20261011/results-v1';scores={};scorepaths=[]
for letter in ('C','D'):
 fs=sorted(mock.glob(letter+'-*.json'));scorepaths+=fs;values=[json.loads(p.read_bytes()) for p in fs]
 scores[letter]={'raw_passed':sum(sum(bool(x['pass']) for x in d['rows']) for d in values),'observed_calls':sum(len(d['rows']) for d in values),'reported_passed':sum(d['passed'] for d in values),'observed_styles':[p.stem for p in fs],'all_observed_styles_cases_passing':sum(all(next(x for x in d['rows'] if x['id']==row['id'])['pass'] for d in values) for row in values[0]['rows'])}
rescored=json.loads((mock/'rescored.json').read_bytes())
for letter in ('C','D'):
 scores[letter]['unofficial_adjusted_passed']=sum(bool(style['adj_pass']) for case in rescored[letter].values() for style in case.values())
after={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
report={'status':'CLOSED_UNCHANGED_PREMERGE_SOURCE_CPU_WITNESSES','finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate_path':PATH.relative_to(ROOT).as_posix(),'candidate_sha256':sha(PATH),'embedded_code_sha256':hashlib.sha256(source.encode()).hexdigest(),'candidate_status':'failed/unpublished pre-guide regeneration','counts':{'checks':len(rows),'passed_expected_controls':sum(x['passed'] for x in rows),'source_counterexamples':sum(not x['passed'] for x in rows),'literal_controller_executions':calls},'observations':rows,'mock_scores':scores,'mock_source_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in scorepaths+[mock/'rescored.json']},'protected_sources_unchanged':before==after,'source_hashes':before,'opus_claim_adjudication':['Her date of birth / cousin DOB literal rows did NOT dispatch identity: that specific Opus claim is refuted for tested inputs.','Truncated source-span forced extraction DID dispatch another subject operand; conditional producer-robustness counterexample, no bank verification or disclosure.','Unknown row consumes a persuasion attempt; mixed scoped withdrawal drops sibling proposal; shared date target-list differs from all; unreadable ok:false receipt retries unchanged.','Several old source faults already covered in the current guide; no post-guide generation claim.'],'limits':['Only immutable old controller is executed, with authored extraction and synthetic receipts in a store that merges patches and does not persist deletions.','No real extractor, API, audio, hosted calls or pass-frequency claim.','Raw mock scores are saved-run evidence with missing direct version/ledger proof; adjusted totals are separate unofficial derived records, not an official pass.']}
out=ROOT/'analysis/classic-v2-opus.witnesses.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda x:sorted(x))+'\n',encoding='utf-8')
print(json.dumps({'counts':report['counts'],'scores':scores,'protected_stable':before==after,'report_sha256':sha(out)}))
