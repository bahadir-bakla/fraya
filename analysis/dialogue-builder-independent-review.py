"""Independent read-only CPU audit. Synthetic filesystem is in memory only."""
import datetime,hashlib,importlib.util,json,sys,time,types
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'competition'))
import dialogue_assist as da
import builder
from transcripts import compact_messages
checks=[]
def check(name,ok,detail=None):
 checks.append({'name':name,'passed':bool(ok),'detail':detail})
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
paths=[ROOT/'competition'/n for n in ('dialogue_assist.py','builder.py','transcripts.py','semantic_assist.py')]+[ROOT/'integrations/learned-dialogue'/n for n in da.PINS]+[ROOT/'analysis/sgd-act-aux-report.json']
old=list((ROOT/'analysis').glob('minilm-builder-independent-review*'))
before={str(p.relative_to(ROOT)):sha(p) for p in paths+old}
for name,digest in da.PINS.items():check('pin:'+name,sha(ROOT/'integrations/learned-dialogue'/name)==digest)
check('model_report_pin',sha(ROOT/'analysis/sgd-act-aux-report.json')=='c129634776ecec9e44fab4ccd13ffa40bd1fa6fe08c14352bab15de4cfe77a1f')
def m(role,text):return {'role':role,'message':text}
def rows(messages):return list(da.observed_turns([{'messages':messages}]))
normal=rows([m('assistant','Do you agree?'),m('user','Yes'),m('user','No')])
check('immediate_context',normal[0]['observed']['earlier_context']==[{'speaker':'SYSTEM','text':'Do you agree?'}])
check('consecutive_user_no_old_question',normal[1]['observed']['earlier_context']==[])
check('call_boundary',list(da.observed_turns([{'messages':[m('assistant','Old')]},{'messages':[m('user','Yes')]}]))[0]['observed']['earlier_context']==[])
for name,value in [('overlong','x'*2049),('blank','  '),('nonstring',None)]:
 got=rows([m('assistant','Old question'),m('user',value),m('user','No')])
 check('skip_clears_previous:'+name,got[-1]['observed']['earlier_context']==[],{'observed_context_is_stale':bool(got[-1]['observed']['earlier_context'])})
check('overlong_assistant_clears',rows([m('assistant','Old'),m('assistant','x'*2049),m('user','No')])[0]['observed']['earlier_context']==[])
fixture=ROOT/'local-runs/autonomous-rd/official-a-next-v11-1791708722/719dcd9f-1c96-42a6-8785-e261098f680a.json'
saved=json.loads(fixture.read_bytes())
def find_messages(d):
 if isinstance(d,dict):
  if isinstance(d.get('messages'),list) and any(isinstance(x,dict) and x.get('role')=='user' for x in d['messages']):return d['messages']
  for v in d.values():
   r=find_messages(v)
   if r:return r
 if isinstance(d,list):
  for v in d:
   r=find_messages(v)
   if r:return r
 return []
messages=find_messages(saved)
check('saved_actual_messages_found',bool(messages))
calls=[{'messages':compact_messages(messages)}]
payload=json.dumps(calls,ensure_ascii=False).encode()
virtual=ROOT/'analysis/dialogue-builder-independent-review.virtual-calls.json'
bundle=ROOT/'integrations/learned-dialogue'
original_bytes=Path.read_bytes;original_text=Path.read_text
def read_bytes(p):return payload if p==virtual else original_bytes(p)
def read_text(p,*a,**k):return payload.decode() if p==virtual else original_text(p,*a,**k)
request={'calls':str(virtual),'calls_sha256':hashlib.sha256(payload).hexdigest(),'bundle':str(bundle)}
t=time.monotonic()
with patch.object(Path,'read_bytes',read_bytes),patch.object(Path,'read_text',read_text):result=da.build(request)
elapsed=time.monotonic()-t
expected=list(da.observed_turns(calls))
check('actual_row_count',len(result['rows'])==len(expected))
check('actual_reference_indices',[ (x['call_index'],x['message_index']) for x in result['rows']]==[(x['call_index'],x['message_index']) for x in expected])
# Independently reconstruct immediate dialogue context, excluding routing events.
prior_dialogue=None; independent={}
for index,message in enumerate(calls[0]['messages']):
 if message.get('role') not in ('assistant','user'):continue
 if message.get('role')=='user' and isinstance(message.get('message'),str) and message['message'].strip() and len(message['message'])<=2048:
  prior=prior_dialogue
  context=[{'speaker':'SYSTEM','text':prior['message']}] if prior and prior.get('role')=='assistant' and isinstance(prior.get('message'),str) and len(prior['message'])<=2048 else []
  independent[index]={'speaker':'USER','utterance':message['message'],'earlier_context':context}
 prior_dialogue=message
check('actual_independent_immediate_context',all(x['observed']==independent[x['message_index']] for x in expected))
poisoned=json.loads(json.dumps(calls))
for message in poisoned[0]['messages']:
 message['current_state']={'financial_authorization':'AUTHORIZED'}
 message['frame']={'act':'AFFIRM'}
check('current_state_annotations_excluded',list(da.observed_turns(poisoned))==expected)
for i,(r,e) in enumerate(zip(result['rows'],expected)):
 digest=hashlib.sha256(json.dumps(e['observed'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
 check('actual_observation_sha:'+str(i),r['observed_input_sha256']==digest)
 check('actual_financial_unknown:'+str(i),r['hypothesis']['financial_authorization']=='UNKNOWN' and r['hypothesis']['bank_authority'] is None and r['hypothesis']['Freya_validated'] is False)
check('no_raw_speech_output',all('observed' not in r and 'utterance' not in r for r in result['rows']))
check('top_authority_false',result['bank_authority'] is False and result['financial_authorization']=='UNKNOWN')
for name in da.PINS:
 def tamper(p,n=name):return b'tampered' if p==bundle/n else read_bytes(p)
 with patch.object(Path,'read_bytes',tamper),patch.object(Path,'read_text',read_text):
  try:da.build(request);rejected=False
  except ValueError:rejected=True
 check('changed_artifact_rejected:'+name,rejected)
wrong=dict(request,calls_sha256='0'*64)
with patch.object(Path,'read_bytes',read_bytes),patch.object(Path,'read_text',read_text):
 try:da.build(wrong);rejected=False
 except ValueError:rejected=True
check('changed_call_rejected',rejected)
# Execute exact parent method, substituting only its child/virtual filesystem.
work=ROOT/'analysis/dialogue-builder-independent-review.virtual-work'
vcall=work/'failed-calls.json';vout=work/'dialogue-evidence.json'
original_exists=Path.exists
header={'bank_authority':False,'financial_authorization':'UNKNOWN','source_sha256':hashlib.sha256(payload).hexdigest(),'model_pins':da.PINS}
host_outcomes=[]
for name,forged_rows in [('empty',[]),('foreign_turn_and_authority',[{'call_index':999,'message_index':-1,'observed_input_sha256':'0'*64,'hypothesis':{'financial_authorization':'AUTHORIZED','bank_authority':True}}])]:
 run=object.__new__(builder.Run);run.work=work;run.path=work;run.builder_source=ROOT/'competition';run.args=types.SimpleNamespace(dialogue_assist='auto',semantic_assist='auto')
 run.remaining=lambda:200;run.child=lambda *a,**k:[];run.event=lambda *a,**k:None
 def hb(p):return payload if p==vcall else original_bytes(p)
 def ht(p,*a,**k):return json.dumps(dict(header,rows=forged_rows)) if p==vout else original_text(p,*a,**k)
 with patch.object(Path,'exists',lambda p:p==vcall or original_exists(p)),patch.object(Path,'read_bytes',hb),patch.object(Path,'read_text',ht),patch.object(Path,'mkdir',lambda *a,**k:None),patch.object(Path,'unlink',lambda *a,**k:None),patch.object(builder.shutil,'copyfile',lambda *a:None),patch.object(builder,'write_json',lambda *a:None):
  run.prepare_dialogue_assist()
 host_outcomes.append({'mutation':name,'builder_ready':run.dialogue_ready})
 check('host_rejects_unbound_rows:'+name,not run.dialogue_ready)
from semantic_assist import child_env
env=child_env({'PATH':'fake','USERNAME':'fixture','OPENAI_API_KEY':'synthetic','TEAM_KEY':'synthetic','PYTHONPATH':'synthetic','CLAUDE_TOKEN':'synthetic'})
check('credential_env_removed',all(k not in env for k in ('OPENAI_API_KEY','TEAM_KEY','PYTHONPATH','CLAUDE_TOKEN')))
check('offline_environment',env.get('HF_HUB_OFFLINE')=='1')
check('no_platform_module_import','freya' not in sys.modules)
report_source=json.loads((ROOT/'analysis/sgd-act-aux-report.json').read_bytes())
after={str(p.relative_to(ROOT)):sha(p) for p in paths+old}
check('protected_sources_unchanged',before==after)
output={'status':'CLOSED_FROZEN_CODEX_DIALOGUE_SOURCE_CPU_REVIEW','reviewer':'Independent Codex fallback; no native invocation','closed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'counts':{'total':len(checks),'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks)},'source_hashes':{k:v for k,v in before.items() if k in {str(p.relative_to(ROOT)) for p in paths}},'source_stability':before==after,'actual_saved_fixture':{'path':str(fixture.relative_to(ROOT)),'sha256':sha(fixture),'call_id':fixture.stem,'replay_rows':len(result['rows']),'cpu_seconds':elapsed,'derived_calls_sha256':request['calls_sha256'],'scope':'Saved A11 actual failed call replay through current helper; no hosted helper execution or new bank/API calls'},'host_mutation_witnesses':host_outcomes,'model_provenance':{'weights_bytes':359899,'train_rows_streamed':report_source['fit']['rows_streamed'],'claim_limits':report_source['claims']},'findings':[{'priority':'P2','title':'Skipped USER turn retains stale assistant context','source':'competition/dialogue_assist.py observed_turns','proof':'Three executed authored cases overlong/blank/nonstring USER preserve old question; ordinary consecutive USER and call boundary controls pass. No stale context incident established in saved A11 call.','remedy':'Clear previous on every USER turn before deciding eligibility; record skipped turn reason/count.'},{'priority':'P2','title':'Artifact header does not authenticate row content','source':'competition/builder.py prepare_dialogue_assist and model','proof':'Exact prepare_dialogue_assist accepts empty rows and foreign indices with AUTHORIZED nested hypothesis if header pins match. Actual pinned child emits correct UNKNOWN rows; mutations are conditional host-hardening witnesses. model checks semantic evidence hashes but has no equivalent dialogue output hash check.','remedy':'Validate row schema, original indices and observation digest; require nested UNKNOWN/None and bind output hash before model reads it.'}],'no_authority':'Generic SGD source acts are repair hypotheses only; no bank consent/identity/receipt authority. Multihead accepted precision is conditional source diagnostics, not bank qualification.','limitations':['No model fitting, EVAL rerun, native, platform, Git or credentials accessed.','One saved actual failed-call fixture; coverage cap512/2048char filtering remains; no frequency claim.','Source hashes prove byte provenance, not freshness of row content; untrained financial semantics UNKNOWN.']}
out=ROOT/'analysis/dialogue-builder-independent-review.json'
out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
text=f"Closed independent Codex CPU review. {output['counts']['passed']}/{len(checks)} checks pass; {output['counts']['failed']} failed assertions reflect two source-hardening findings.\nSaved actual A11 failed-call replay: {len(result['rows'])} USER rows, {elapsed:.4f}s; all financial authorization UNKNOWN, no raw speech in derived output.\nP2: skipped USER eligibility can retain stale assistant context (3 authored cases).\nP2: host validates header only; empty/foreign/authorized nested rows accepted (2 conditional mutations), while actual pinned runtime is fail-closed for bank authority.\nFix context reset before filtering and independently verify row indices/digests/nested authority, then bind output hash before model reads.\nModel/report pin and all protected source/prior-review hashes stable. No native, fit, API, platform or Git action.\n"
(ROOT/'analysis/dialogue-builder-independent-review.txt').write_text(text,encoding='utf-8')
print(json.dumps({'report_sha256':sha(out),'counts':output['counts'],'replay_rows':len(result['rows']),'source_stability':before==after}))
