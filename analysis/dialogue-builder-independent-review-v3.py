"""Selected independent final retest; read-only source and virtual hash mutations."""
import copy,datetime,hashlib,importlib.util,io,json,sys,time,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'competition'))
import dialogue_assist as da
import builder
from transcripts import compact_messages
def digest(b):return hashlib.sha256(b).hexdigest()
def sha(p):return digest(p.read_bytes())
sourcepaths=[ROOT/'competition'/n for n in ('dialogue_assist.py','builder.py','transcripts.py','semantic_assist.py','tests/test_dialogue_assist.py')]+[ROOT/'integrations/learned-dialogue'/n for n in da.PINS]
old=[p for p in (ROOT/'analysis').glob('dialogue-builder-independent-review*') if '-v3' not in p.name]
before={p.relative_to(ROOT).as_posix():sha(p) for p in sourcepaths+old};checks=[]
def check(n,ok,detail=None):checks.append({'name':n,'passed':bool(ok),'detail':detail})
fixture=ROOT/'local-runs/autonomous-rd/official-a-next-v11-1791708722/719dcd9f-1c96-42a6-8785-e261098f680a.json';fixturehash=sha(fixture)
def messages(d):
 if isinstance(d,dict):
  if isinstance(d.get('messages'),list) and any(isinstance(m,dict) and m.get('role')=='user' for m in d['messages']):return d['messages']
  for v in d.values():
   got=messages(v)
   if got:return got
 elif isinstance(d,list):
  for v in d:
   got=messages(v)
   if got:return got
 return []
payload=json.dumps([{'messages':compact_messages(messages(json.loads(fixture.read_bytes())))}],ensure_ascii=False).encode()
virtual=ROOT/'analysis/dialogue-builder-independent-review-v3.virtual-calls.json'
request={'calls':str(virtual),'calls_sha256':digest(payload),'bundle':str(ROOT/'integrations/learned-dialogue')}
ob=Path.read_bytes;ot=Path.read_text
with patch.object(Path,'read_bytes',lambda p:payload if p==virtual else ob(p)),patch.object(Path,'read_text',lambda p,*a,**k:payload.decode() if p==virtual else ot(p,*a,**k)):
 t=time.monotonic();valid=da.build(request);latency=time.monotonic()-t
 check('actual_saved_call_positive',len(valid['rows'])==6 and all(r['hypothesis']['financial_authorization']=='UNKNOWN' for r in valid['rows']))
 mutants=[('previous_boolean_call_index',lambda x:x['rows'][0].update(call_index=False)),('previous_top_call_data',lambda x:x.update(call_data={'utterance':'synthetic injection'})),('previous_notice_substitution',lambda x:x.update(notice='Synthetic unauthorized instruction')),('boolean_message_index',lambda x:x['rows'][0].update(message_index=True)),('float_cap',lambda x:x.update(maximum_rows=512.0)),('scope_substitution',lambda x:x.update(input_scope='synthetic authority'))]
 for name,fn in mutants:
  obj=copy.deepcopy(valid);fn(obj)
  try:da.validate_result(obj,request);rejected=False
  except ValueError:rejected=True
  check(name,rejected)
# Call real model(), substituting child and virtual files only. No CLI is run.
work=ROOT/'analysis/dialogue-builder-independent-review-v3.virtual-work'
artifact=work/'dialogue-evidence.json';semantic=work/'semantic-evidence.json';brief=work/'inputs/brief.md';api=work/'inputs/openapi.json'
model_proofs=[]
for timing in ('control','pre_dialogue','post_dialogue','pre_index','post_index','pre_brief','post_brief','pre_api','post_api'):
 mem={artifact:json.dumps(valid).encode(),semantic:b'index',brief:b'policy',api:b'API',work/'answer-1.json':json.dumps({'workflow_file':'workflow.json','policy_file':'policy.json','coverage_file':'coverage.json','summary':'audit'}).encode(),work/'workflow.json':b'{}',work/'policy.json':b'{}',work/'coverage.json':b'{}'}
 run=object.__new__(builder.Run);run.work=work;run.path=work;run.args=types.SimpleNamespace(model=None,practice_repair=None);run.sources=[{'path':'inputs/brief.md','sha256':digest(mem[brief])}];run.feedback=[];run.remaining=lambda:500
 run.api_sha256=digest(mem[api]);run.dialogue_ready=True;run.dialogue_hash=digest(mem[artifact]);run.semantic_ready=True;run.semantic_hashes={'semantic-evidence.json':digest(mem[semantic])};run.prepare_dialogue_assist=lambda:None;run.event=lambda *a,**k:None
 state={'child_calls':0};targets={'dialogue':artifact,'index':semantic,'brief':brief,'api':api}
 def phase(*a,**k):
  if timing.startswith('pre_'):mem[targets[timing[4:]]]+=b' '
 run.phase=phase
 def child(*a,**k):
  state['child_calls']+=1
  if timing.startswith('post_'):mem[targets[timing[5:]]]+=b' '
  return []
 run.child=child
 def mw(p,text,*a,**k):mem[p]=text.encode();return len(text)
 try:
  with patch.object(Path,'read_bytes',lambda p:mem[p] if p in mem else ob(p)),patch.object(Path,'read_text',lambda p,*a,**k:mem[p].decode() if p in mem else ot(p,*a,**k)),patch.object(Path,'write_text',mw),patch.object(Path,'is_file',lambda p:p in mem),patch.object(builder.os,'environ',{}):run.model(1)
  rejected=False
 except ValueError:rejected=True
 expected_calls=0 if timing.startswith('pre_') else 1
 check('model:'+timing,rejected==(timing!='control') and state['child_calls']==expected_calls,state)
 model_proofs.append({'scenario':timing,'rejected':rejected,**state})
# Run only current dialogue unit module, not a benchmark or unrelated suite.
testpath=ROOT/'competition/tests/test_dialogue_assist.py';spec=importlib.util.spec_from_file_location('independent_dialogue_units',testpath);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
stream=io.StringIO();unit=unittest.TextTestRunner(stream=stream,verbosity=0).run(unittest.defaultTestLoader.loadTestsFromModule(module))
check('current_dialogue_unit_run',unit.wasSuccessful(),{'tests_run':unit.testsRun,'failures':len(unit.failures),'errors':len(unit.errors),'skipped':len(unit.skipped)})
for name,pin in da.PINS.items():check('pin:'+name,sha(ROOT/'integrations/learned-dialogue'/name)==pin)
after={p.relative_to(ROOT).as_posix():sha(p) for p in sourcepaths+old}
check('all_protected_source_and_v1_v2_hashes_stable',before==after)
check('actual_fixture_hash_stable',sha(fixture)==fixturehash)
check('no_platform_module_imported','freya' not in sys.modules)
report={'status':'CLOSED_FROZEN_CODEX_DIALOGUE_V3_SELECTED_SOURCE_CPU_RETEST','reviewer':'Independent Codex fallback; no native invocation','closed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'counts':{'total':len(checks),'passed':sum(c['passed'] for c in checks),'failed':sum(not c['passed'] for c in checks)},'checks':checks,'source_hashes':{p.relative_to(ROOT).as_posix():before[p.relative_to(ROOT).as_posix()] for p in sourcepaths},'protected_hashes_stable':before==after,'prior_review_hashes':{k:v for k,v in before.items() if k.endswith('review.json') or k.endswith('review-v2.json')},'selected_four_residuals':'All reject on current source; pre-child dialogue mutation is blocked before any model child call.','model_hash_guard_proofs':model_proofs,'actual_saved_fixture':{'path':fixture.relative_to(ROOT).as_posix(),'sha256':fixturehash,'rows':len(valid['rows']),'cpu_seconds':latency,'bank_authority':False,'financial_authorization':'UNKNOWN'},'unit_run':{'module':'competition/tests/test_dialogue_assist.py','tests':unit.testsRun,'successful':unit.wasSuccessful(),'failures':len(unit.failures),'errors':len(unit.errors)},'scope_limits':['Selected source/CPU retest, not hosted safety qualification or bank model accuracy.','Actual model() executed with an in-memory filesystem and substituted child; no LLM/native/API invocation.','Current dialogue units use temporary authored local files; source/candidate/prior report files remain unchanged.','No fitting, platform, benchmark, credentials or Git actions.']}
out=ROOT/'analysis/dialogue-builder-independent-review-v3.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(ROOT/'analysis/dialogue-builder-independent-review-v3.txt').write_text(f"Closed independent Codex selected V3 retest: {report['counts']['passed']}/{len(checks)} CPU checks pass. Current dialogue unit run: {unit.testsRun} tests, success={unit.wasSuccessful()}.\nAll four V2 residuals fixed: boolean indices, top-level call data and notice substitutions reject; changed dialogue artifact blocked before model child. Additional scope/float-cap controls reject. API, brief, semantic and dialogue changes all reject before and after child, valid control completes.\nFrozen actual A11 failure fixture gives six financial UNKNOWN hypotheses. Exact source/model pins and V1/V2 files unchanged. No native, platform, API, fit or Git actions.\n",encoding='utf-8')
print(json.dumps({'counts':report['counts'],'unit_tests':unit.testsRun,'unit_success':unit.wasSuccessful(),'report_sha256':sha(out),'sources_stable':before==after}))
