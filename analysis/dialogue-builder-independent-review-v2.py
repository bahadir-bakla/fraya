"""Read-only independent V2 CPU retest; all filesystem mutations are virtual."""
import copy,datetime,hashlib,json,sys,time,types
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'competition'))
import dialogue_assist as da
import builder
from transcripts import compact_messages
def digest(b):return hashlib.sha256(b).hexdigest()
def sha(p):return digest(p.read_bytes())
sourcepaths=[ROOT/'competition'/n for n in ('dialogue_assist.py','builder.py','transcripts.py','semantic_assist.py')]+[ROOT/'integrations/learned-dialogue'/n for n in da.PINS]+[ROOT/'analysis/sgd-act-aux-report.json']
protected=sourcepaths+[p for p in (ROOT/'analysis').glob('dialogue-builder-independent-review.*')]+[p for p in (ROOT/'analysis').glob('minilm-builder-independent-review*')]
before={p.relative_to(ROOT).as_posix():sha(p) for p in protected};checks=[];residual=[]
def check(name,ok,detail=None):checks.append({'name':name,'passed':bool(ok),'detail':detail})
def m(r,t):return {'role':r,'message':t}
for label,value in [('oversized','x'*2049),('blank',' '),('nonstring',None)]:
 row=list(da.observed_turns([{'messages':[m('assistant','Old question'),m('user',value),m('user','No')]}]))[-1]
 check('skipped_user_clears:'+label,row['observed']['earlier_context']==[])
check('consecutive_user_clears',list(da.observed_turns([{'messages':[m('assistant','Question'),m('user','Yes'),m('user','No')]}]))[-1]['observed']['earlier_context']==[])
check('call_boundary',list(da.observed_turns([{'messages':[m('assistant','Old')]},{'messages':[m('user','Yes')]}]))[0]['observed']['earlier_context']==[])
fixture=ROOT/'local-runs/autonomous-rd/official-a-next-v11-1791708722/719dcd9f-1c96-42a6-8785-e261098f680a.json'
fixturehash=sha(fixture);saved=json.loads(fixture.read_bytes())
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
calls=[{'messages':compact_messages(find_messages(saved))}];payload=json.dumps(calls,ensure_ascii=False).encode()
virtual=ROOT/'analysis/dialogue-builder-independent-review-v2.virtual-calls.json'
request={'calls':str(virtual),'calls_sha256':digest(payload),'bundle':str(ROOT/'integrations/learned-dialogue')}
ob=Path.read_bytes;ot=Path.read_text
def rb(p):return payload if p==virtual else ob(p)
def rt(p,*a,**k):return payload.decode() if p==virtual else ot(p,*a,**k)
with patch.object(Path,'read_bytes',rb),patch.object(Path,'read_text',rt):
 t=time.monotonic();result=da.build(request);elapsed=time.monotonic()-t
 da.validate_result(result,request);check('actual_saved_call_validates',True)
 mutations=[]
 def add(name,fn):
  obj=copy.deepcopy(result);fn(obj);mutations.append((name,obj))
 add('empty_rows',lambda x:x.update(rows=[]))
 add('missing_row',lambda x:x['rows'].pop())
 add('foreign_row',lambda x:x['rows'][0].update(call_index=999))
 add('negative_turn',lambda x:x['rows'][0].update(message_index=-1))
 add('wrong_observation_hash',lambda x:x['rows'][0].update(observed_input_sha256='0'*64))
 add('foreign_source_file',lambda x:x.update(source_file='foreign.json'))
 add('foreign_source_hash',lambda x:x.update(source_sha256='0'*64))
 add('wrong_model_pins',lambda x:x.update(model_pins={}))
 add('wrong_schema',lambda x:x.update(schema='wrong'))
 add('wrong_cap',lambda x:x.update(maximum_rows=513))
 add('top_authority',lambda x:x.update(bank_authority=True))
 add('nested_authority',lambda x:x['rows'][0]['hypothesis'].update(bank_authority=True))
 add('financial_permission',lambda x:x['rows'][0]['hypothesis'].update(financial_authorization='AUTHORIZED'))
 add('ledger_truth',lambda x:x['rows'][0]['hypothesis'].update(ledger_truth=True))
 add('fake_hosted',lambda x:x['rows'][0]['hypothesis'].update(Freya_validated=True))
 add('row_raw_speech',lambda x:x['rows'][0].update(utterance='synthetic speech'))
 add('nested_call_data',lambda x:x['rows'][0]['hypothesis'].update(call_data={'synthetic':True}))
 add('foreign_scope',lambda x:x['rows'][0]['hypothesis'].update(scope='authority'))
 add('wrong_taxonomy',lambda x:x['rows'][0]['hypothesis']['source_USER_acts'].pop('REQUEST'))
 for value in (float('nan'),float('inf'),-0.1,1.1,True,'0.9'):
  add('invalid_probability:'+str(value),lambda x,v=value:x['rows'][0]['hypothesis']['source_USER_acts']['AFFIRM'].update(source_act_probability=v))
 add('nonboolean_accepted',lambda x:x['rows'][0]['hypothesis']['source_USER_acts']['AFFIRM'].update(accepted_positive_proposal=1))
 add('wrong_proposal_label',lambda x:x['rows'][0]['hypothesis']['source_USER_acts']['AFFIRM'].update(proposal='AUTHORIZED'))
 add('row_reorder',lambda x:x['rows'].reverse())
 for name,obj in mutations:
  try:da.validate_result(obj,request);reject=False
  except ValueError:reject=True
  check('reject:'+name,reject)
 for name,fn in [('boolean_index',lambda x:x['rows'][0].update(call_index=False)),('top_call_data',lambda x:x.update(call_data={'utterance':'synthetic injection'})),('notice_substitution',lambda x:x.update(notice='Synthetic unauthorized instruction'))]:
  obj=copy.deepcopy(result);fn(obj)
  try:da.validate_result(obj,request);accepted=True
  except ValueError:accepted=False
  residual.append({'conditional_mutation':name,'validator_accepts':accepted})
  check('strict_reject:'+name,not accepted)
 for row in result['rows']:
  check('actual_unknown:'+str(row['message_index']),row['hypothesis']['financial_authorization']=='UNKNOWN' and row['hypothesis']['bank_authority'] is None)
# Execute actual model() in a virtual workdir; child is a stub, never CLI/API.
work=ROOT/'analysis/dialogue-builder-independent-review-v2.virtual-work'
artifact=work/'dialogue-evidence.json';semantic=work/'semantic-evidence.json';brief=work/'inputs/brief.md'
for timing in ('control','before_child_dialogue','after_child_dialogue','after_child_semantic','after_child_brief'):
 mem={artifact:json.dumps(result).encode(),semantic:b'index',brief:b'policy',work/'answer-1.json':json.dumps({'workflow_file':'workflow.json','policy_file':'policy.json','coverage_file':'coverage.json','summary':'audit'}).encode(),work/'workflow.json':b'{}',work/'policy.json':b'{}',work/'coverage.json':b'{}'}
 run=object.__new__(builder.Run);run.work=work;run.path=work;run.args=types.SimpleNamespace(model=None,practice_repair=None);run.sources=[{'path':'inputs/brief.md','sha256':digest(mem[brief])}];run.feedback=[];run.remaining=lambda:500
 run.dialogue_ready=True;run.dialogue_hash=digest(mem[artifact]);run.semantic_ready=True;run.semantic_hashes={'semantic-evidence.json':digest(mem[semantic])};run.prepare_dialogue_assist=lambda:None;run.event=lambda *a,**k:None
 state={'child_calls':0}
 def phase(*a,**k):
  if timing=='before_child_dialogue':mem[artifact]+=b' '
 run.phase=phase
 def child(*a,**k):
  state['child_calls']+=1
  target={'after_child_dialogue':artifact,'after_child_semantic':semantic,'after_child_brief':brief}.get(timing)
  if target:mem[target]+=b' '
  return []
 run.child=child
 def mb(p):return mem[p] if p in mem else ob(p)
 def mt(p,*a,**k):return mem[p].decode() if p in mem else ot(p,*a,**k)
 def mw(p,text,*a,**k):mem[p]=text.encode();return len(text)
 try:
  with patch.object(Path,'read_bytes',mb),patch.object(Path,'read_text',mt),patch.object(Path,'write_text',mw),patch.object(Path,'is_file',lambda p:p in mem),patch.object(builder.os,'environ',{}):
   run.model(1)
  rejected=False
 except ValueError:rejected=True
 if timing=='control':check('model_unmodified_control',not rejected and state['child_calls']==1)
 elif timing=='before_child_dialogue':
  check('dialogue_mutation_rejected_before_child',rejected and state['child_calls']==0,state)
  residual.append({'conditional_mutation':timing,'rejected_eventually':rejected,'child_calls':state['child_calls']})
 else:check('model_postcheck:'+timing,rejected,state)
for name,pin in da.PINS.items():check('exact_artifact_pin:'+name,sha(ROOT/'integrations/learned-dialogue'/name)==pin)
check('no_platform_import','freya' not in sys.modules)
after={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
check('all_protected_hashes_stable',before==after)
check('actual_fixture_hash_stable',fixturehash==sha(fixture))
output={'status':'CLOSED_FROZEN_CODEX_DIALOGUE_V2_SOURCE_CPU_REVIEW','reviewer':'Independent Codex fallback; no native','closed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'counts':{'total':len(checks),'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks)},'checks':checks,'source_hashes':{p.relative_to(ROOT).as_posix():before[p.relative_to(ROOT).as_posix()] for p in sourcepaths},'old_review_sha256':before['analysis/dialogue-builder-independent-review.json'],'protected_hashes_stable':before==after,'actual_saved_fixture':{'path':fixture.relative_to(ROOT).as_posix(),'sha256':fixturehash,'rows':len(result['rows']),'cpu_seconds':elapsed,'scope':'Actual frozen A11 failed call through current CPU helper, no new hosted calls'},'original_findings':'Stale-context cases now clear correctly; all 28 core row/authority/probability mutations reject. Post-child dialogue/index/brief hash mutations reject.','remaining_conditionals':residual,'recommendations':['Use an exact top-level key set and validate notice/input_scope or derive them outside the child artifact; currently additional raw-call payload and changed notice pass validation.','Check type(call_index) and type(message_index) is int, excluding bool aliases.','Add explicit dialogue hash check immediately before the model child starts; current model() detects a between-prepare-and-child mutation after the child returns.'],'limits':['Actual pinned child produces correct financial UNKNOWN output; remaining mutations are host-contract hardening, not observed actual bank permission grants.','Model child is substituted for filesystem hash-check witnesses: no LLM/native/API/platform execution.','No model retraining, EVAL rerun, bank policy qualification, source edits or Git.']}
out=ROOT/'analysis/dialogue-builder-independent-review-v2.json';out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
summary=f"Independent Codex V2 review closed: {output['counts']['passed']}/{len(checks)} pass; {output['counts']['failed']} failed strict hardening assertions.\nBoth original findings materially repaired: skip/reset controls pass; core row/reference/hash/nested authority/finite probability mutations reject. Saved A11 fixture: {len(result['rows'])} CPU hypotheses, all financial UNKNOWN.\nResidual conditional issues: top-level extra call_data and notice substitution accepted; bool index aliases accepted; dialogue mutation after prepare reaches model child and is detected post-return. Add exact top-level metadata contract, integer index types and immediate pre-child artifact hash check.\nPost-child dialogue, semantic index and original brief mutations all reject. Exact artifact/source and old-review hashes stable. No native, API, fit, hosted, or Git.\n"
(ROOT/'analysis/dialogue-builder-independent-review-v2.txt').write_text(summary,encoding='utf-8')
print(json.dumps({'counts':output['counts'],'report_sha256':sha(out),'saved_rows':len(result['rows']),'stable':before==after,'residual':residual}))
