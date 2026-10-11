"""Independent neutral CPU contracts; no APIs, data labels, training or platform."""
import ast,copy,datetime,hashlib,importlib.util,json,sys,tempfile,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];B=R/'analysis/final-sprint-live-redteam-20261011';rows=[]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def load(path,name):
 s=importlib.util.spec_from_file_location(name,R/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
names=['competition/live_layer.py','competition/recipient_assertion.py','competition/builder.py','integrations/learned-dialogue/live_v2_student_runtime.py','integrations/learned-dialogue/live_v2_student_train.py'];pins={p:sha(R/p) for p in names}
layer=load(names[0],'redteam_live_layer');recipient=load(names[1],'redteam_recipient');runtime=load(names[3],'redteam_student')
def check(id,expected,met,observed,kind='neutral conditional CPU'):
 rows.append(dict(id=id,expected=expected,met=bool(met),observed=observed,kind=kind))
fixtures=[
 ('Riley','Vale','Mx','Riley','SELF'),('Riley','Vale','Mx','Mx. Vale speaking.','SELF'),('Riley','Vale','Mx','Vale, Riley speaking.','SELF'),
 ('Oğuz',"D'Arcy",'Dr',"This is Dr. Oğuz D’Arcy.",'SELF'),('José','Nuñez','Prof','Jose\u0301 Nun\u0303ez speaking.','SELF'),
 ('Riley','Vale','Mx','This is Jordan Vale.','OTHER'),('Riley','Vale','Mx','I am not Riley Vale.','OTHER'),
 ('Riley','Vale','Mx','My sister said "Riley Vale speaking".','UNKNOWN'),('Riley','Vale','Mx','If I were Riley Vale, yes.','UNKNOWN'),
 ('Riley','Vale','Mx','This is Riley Vale. I am his brother.','UNKNOWN'),('Riley','Vale','Mx','Riley is unavailable.','OTHER'),
 ('Riley','Vale','Mx','Yes. Riley is not here.','UNKNOWN'),('Riley','Vale','Mx','Yes. Riley is not me.','UNKNOWN'),
 ('Riley','Vale','Mx','Yes. I am Riley Vale’s cousin.','UNKNOWN'),('Riley','Vale','Mx','Yes. Riley said to answer for him.','UNKNOWN'),
 ('Riley','Vale','Mx','This is Riley Vale, but only in a play.','UNKNOWN'),('Riley','Vale','Mx','This is Riley Vale, but I am pretending.','UNKNOWN'),
 ('Riley','Vale','Mx','Yes, this is Riley Vale speaking.','SELF'),('Riley','Vale','Mx','Riley Vale speaking, thank you.','SELF'),
 ('Riley','Vale','Mx','This is Riley Vale; I will not give my date of birth.','SELF'),('Riley','Vale','Mx','Dr Vale speaking.','OTHER')]
for i,(g,f,t,raw,want) in enumerate(fixtures):
 result=recipient.recipient_assertion(raw,g,f,t);check('recipient-'+str(i),want,result['decision']==want,dict(raw=raw,decision=result['decision'],reason=result['reason'],span=result['source_span'],bank_authority=result['bank_authority']))
 check('recipient-authority-'+str(i),'False always; span bounded',result['bank_authority'] is False and (not result['source_span'] or 0<=result['source_span'][0]<result['source_span'][1]<=len(raw)),dict(bank_authority=result['bank_authority'],span=result['source_span']))
model=dict(schema='live_v2_student.v1',labels=list(runtime.LABELS),feature_dim=768,quantization='int8_per_head',weights=[[0]*768 for _ in range(11)],scales=[.01]*11,bias=[0.0]*11,thresholds=list(runtime.MIN_THRESHOLDS),disabled_heads=['current_affirm','current_withdraw'],context_mode='current_only',bank_authority=False,financial_authorization='UNKNOWN',logit_cutoffs=[0.0]*11,quant_logit_margins=[0.0]*11)
for key,value in [('bank_authority',True),('financial_authorization','YES'),('feature_dim',True),('thresholds',[float('nan')]*11),('scales',[0.0]*11),('bias',[float('inf')]*11),('quant_logit_margins',[-1.0]*11),('disabled_heads',[]),('context_mode','state_authority'),('logit_cutoffs',[float('nan')]*11)]:
 bad=copy.deepcopy(model);bad[key]=value;out=runtime.student_predict('I would like a clarification.',[],bad);check('invalid-model-'+key,'INVALID with no authority',out['status']=='INVALID' and not out['labels'] and out['bank_authority'] is False and out['financial_authorization']=='UNKNOWN',out)
bad=copy.deepcopy(model);bad['weights'][0][0]=True;out=runtime.student_predict('Hello',[],bad);check('bool-weight','INVALID',out['status']=='INVALID',out)
out=runtime.student_predict('Yes, I withdraw permission.',[],model);check('disabled-financial-heads','no current_affirm/current_withdraw or aux labels; UNKNOWN',not set(out['labels']).intersection(runtime.LABELS[3:5]+runtime.LABELS[7:]) and out['financial_authorization']=='UNKNOWN',out)
for current,prior in [(None,[]),('',[]),('hello',[dict(speaker='USER',text='yes',authorization=True)]),('hello',[dict(speaker='USER',text='x')]*3)]:
 out=runtime.student_predict(current,prior,model);check('invalid-input-'+str(len(rows)),'INVALID',out['status']=='INVALID',out)
with tempfile.TemporaryDirectory(prefix='final-sprint-live-redteam-20261011.',dir=R/'analysis') as temp:
 work=Path(temp);assert work.resolve().is_relative_to((R/'analysis').resolve())
 contract=layer.prepare(work,R/names[1]);exact=(work/'live-layer-code.py').read_text(encoding='utf-8');ns={};exec(exact,ns)
 def broker(id,state,raw='2718',mode='event'):
  v=dict(state=state,raw=raw,mode=mode,first_name='Riley',last_name='Vale',title='Mx',verified=False,consent=False,live_observed_prior=[],live_semantic_hint='old',live_financial_authorization='YES');before=copy.deepcopy(v);ns['live_layer_apply'](v)
  check(id,'security raw not retained in learned history; financial UNKNOWN and authority untouched',not v.get('live_observed_prior') and v.get('verified')==before['verified'] and v.get('consent')==before['consent'] and v['live_financial_authorization']=='UNKNOWN',dict(state=state,status=v.get('live_layer_status'),history=v.get('live_observed_prior'),hint=v.get('live_semantic_hint'),verified=v['verified'],consent=v['consent']))
 for phase in ('recipient','dob','phone','security','phone_last4','date_of_birth'):broker('broker-phase-'+phase,dict(phase=phase))
 broker('broker-bank-response',dict(phase='financial'),mode='receipt');broker('broker-empty-current',dict(phase='financial'),raw='')
 v=dict(state=json.dumps(dict(phase='financial')),raw='A current proposal.',first_name='Riley',last_name='Vale');ns['live_layer_apply'](v);check('json-state-activity','financial JSON state should not be silently mistaken for recipient',v['live_layer_status']!='SOURCE_ONLY_SECURITY_BYPASS',dict(status=v['live_layer_status'],history=v.get('live_observed_prior')))
 for label,tail,node_type in [('dead-branch','\nif False:\n live_layer_apply(vars)\n live_recipient_reply("Riley", vars)\n','code'),('conversation-preaction','\nlive_layer_apply(vars)\nlive_recipient_reply("Riley", vars)\n','conversation')]:
  workflow={'nodes':{'dispatch':{'node_type':node_type,'pre_actions':[{'function':{'handler':'__function__:code_exec','parameters':{'properties':{'code':{'default':exact+tail}}}}}]}}}
  try:accepted=layer.validate_embedding(workflow,work,contract)
  except ValueError:accepted=None
  check('embedding-'+label,'reject non-executed or engine-dropped invocation',accepted is None,accepted,'synthetic workflow validator mutation; not a generated candidate')
 # The matching source with real calls is a positive structural control only.
 valid={'nodes':{'dispatch':{'node_type':'code','pre_actions':[{'function':{'handler':'__function__:code_exec','parameters':{'properties':{'code':{'default':exact+'\nlive_layer_apply(vars)\nlive_recipient_reply("Riley", vars)\n'}}}}}]}}}
 check('embedding-positive','accept exact reachable code calls',bool(layer.validate_embedding(valid,work,contract)),True)
 modeldir=work/'bundle';modeldir.mkdir();(modeldir/'runtime.py').write_bytes((R/names[3]).read_bytes());(modeldir/'model.json').write_text(json.dumps(model));manifest=dict(bank_authority=False,files={p.name:sha(p) for p in modeldir.iterdir()});(modeldir/'manifest.json').write_text(json.dumps(manifest));outdir=work/'student-work';outdir.mkdir();result=layer.prepare(outdir,R/names[1],modeldir,sha(modeldir/'manifest.json'));check('portable-student-prepare','confined pinned runtime/model accepted',result['mode']=='v2-student' and result['bank_authority'] is False,dict(bytes=result['component_bytes'],mode=result['mode']))
 broken=copy.deepcopy(model);broken['thresholds']=[0.0]*11;(modeldir/'model.json').write_text(json.dumps(broken));manifest['files']['model.json']=sha(modeldir/'model.json');(modeldir/'manifest.json').write_text(json.dumps(manifest));badwork=work/'bad-student';badwork.mkdir()
 accepted=layer.prepare(badwork,R/names[1],modeldir,sha(modeldir/'manifest.json'));check('prepare-invalid-model','reject pinned but invalid model before generation',False,dict(accepted_mode=accepted['mode'],model_valid=runtime._valid_model(broken)))
 # Execute only the literal Builder.child method, with a minimal owned harness.
 builder_code=(R/names[2]).read_text(encoding='utf-8');tree=ast.parse(builder_code);method=next(n for c in tree.body if isinstance(c,ast.ClassDef) for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='child');imports='import codecs,os,queue,signal,subprocess,threading,time\n';klass=ast.ClassDef(name='OwnedChildHarness',bases=[],keywords=[],body=[method],decorator_list=[]);nschild={};exec(imports+ast.unparse(ast.fix_missing_locations(ast.Module(body=[klass],type_ignores=[]))),nschild)
 h=nschild['OwnedChildHarness']();h.work=work;h.path=work;h.remaining=lambda:5;h.event=lambda *a,**kw:None;h.clean=lambda x:x
 out=h.child([sys.executable,'-I','-c','import sys,json; s=sys.stdin.buffer.read().decode("utf-8"); print(json.dumps({"n":len(s),"last":s[-1]}))'],timeout=2,stdin='é'*70000,log_name='owned-unicode.jsonl');data=json.loads(out[-1]);check('child-deferred-stdin','full UTF-8 stdin delivered before JSON read',data==dict(n=70000,last='é'),data)
 tick=time.monotonic()
 try:h.child([sys.executable,'-I','-c','import time; time.sleep(5)'],timeout=.2,stdin='x'*70000,log_name='owned-timeout.jsonl');bounded=False
 except TimeoutError:bounded=True
 check('child-timeout','bounded stop with blocked stdin; no native/network',bounded and time.monotonic()-tick<2,dict(bounded=bounded,seconds=time.monotonic()-tick))
modelpath=R/'integrations/learned-dialogue/live_v2_student/current_only_run/model.json'
actual=None
if modelpath.exists():
 actual=json.loads(modelpath.read_bytes());pins[modelpath.relative_to(R).as_posix()]=sha(modelpath);tick=time.perf_counter();out=runtime.student_predict('Please clarify my current proposal.',[],actual);elapsed=(time.perf_counter()-tick)*1000
 check('actual-model-interface','valid pinned actual model; financial UNKNOWN',out['status']!='INVALID' and out['financial_authorization']=='UNKNOWN' and out['bank_authority'] is False,dict(status=out['status'],financial_authorization=out['financial_authorization'],labels_count=len(out['labels']),cpu_ms=elapsed,context_mode=actual.get('context_mode')))
 oldruntime=modelpath.parent/'runtime.py'
 if oldruntime.exists():
  pins[oldruntime.relative_to(R).as_posix()]=sha(oldruntime);bundled=load(oldruntime.relative_to(R),'redteam_actual_bundled_runtime');out=bundled.student_predict('Please clarify my current proposal.',[],actual);check('actual-bundled-pair','matching actual bundled runtime/model can differ from current runtime',out['status']!='INVALID' and out['bank_authority'] is False,dict(status=out['status'],labels_count=len(out['labels']),runtime_sha256=sha(oldruntime)))
report=dict(status='CLOSED_SOURCE_CPU_WITNESSES',finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_hashes=pins,source_stability={p:sha(R/p)==h for p,h in pins.items()},checks=len(rows),met=sum(r['met'] for r in rows),unmet=[r['id'] for r in rows if not r['met']],results=rows,limits=['Synthetic neutral source fixtures only; no hosted semantics, frequency or bank verification claims.','No fresh64/EVAL96 examples, predictions, labels or old case outputs read.','Actual model interface test uses one independent new neutral input, not a benchmark.','Temporary prepared bundles confined to owned analysis prefix; no candidate edits.'])
Path(str(B)+'.witnesses.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(checks=report['checks'],met=report['met'],unmet=report['unmet'],stable=all(report['source_stability'].values()))))
