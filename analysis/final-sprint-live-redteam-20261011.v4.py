"""Independent v4 source/CPU retest; no native/platform/model/data operations."""
import copy,datetime,hashlib,importlib.util,json,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];B=R/'analysis/final-sprint-live-redteam-20261011.v4';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();rows=[]
names=['competition/recipient_assertion.py','competition/live_layer.py'];pins={p:sha(R/p) for p in names};old=[p for p in (R/'analysis').glob('final-sprint-live-redteam-20261011*.json') if '.v4.' not in p.name];oldpins={p.relative_to(R).as_posix():sha(p) for p in old}
def module(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
p=module(R/names[0],'v4_recipient');l=module(R/names[1],'v4_layer')
def check(id,expected,met,observed,kind='new neutral conditional CPU'):
 rows.append(dict(id=id,expected=expected,met=bool(met),observed=observed,kind=kind))
def identify(id,g,f,title,raw,want,kind='new neutral conditional CPU'):
 result=p.recipient_assertion(raw,g,f,title);met=result['decision']!='SELF' if want=='NON_SELF' else result['decision']==want
 check(id,want,met,dict(raw=raw,given=g,family=f,title=title,decision=result['decision'],reason=result['reason'],span=result['source_span'],bank_authority=result['bank_authority']),kind)
 check(id+'-invariant','no bank authority; source span bounded',result['bank_authority'] is False and (not result['source_span'] or 0<=result['source_span'][0]<result['source_span'][1]<=len(raw)),dict(bank_authority=result['bank_authority'],span=result['source_span']))
for id,raw in [('recipient-17','This is Riley Vale, but I’m only pretending.'),('recipient-18','This is Riley Vale, but I am pretending to be them.'),('recipient-19','Yes. Riley Vale said to answer for him.')]:identify(id,'Riley','Vale','Mx',raw,'NON_SELF','prior10 residual replay')
cases=[('Renée',"O'Neill",'Dr',"Speaking, Dr. Renée O’Neill.",'SELF'),('Renée',"O'Neill",'Dr',"Yes, this is Renée O’Neill speaking.",'SELF'),('Renée',"O'Neill",'Dr',"O’Neill, Renée speaking.",'SELF'),('Renée',"O'Neill",'Dr',"This is Daniel O’Neill.",'NON_SELF'),('Renée',"O'Neill",'Dr',"Yes. Renée O’Neill is not me.",'NON_SELF'),('Renée',"O'Neill",'Dr',"Yes. I am Renée O’Neill’s attorney.",'NON_SELF'),('Renée',"O'Neill",'Dr',"Yes. I’m her caregiver.",'NON_SELF'),('Renée',"O'Neill",'Dr',"Yes. Renée O’Neill said to answer for her.",'NON_SELF'),('Renée',"O'Neill",'Dr',"Yes. If I were Renée O’Neill.",'NON_SELF'),('Renée',"O'Neill",'Dr','Yes. "Renée O’Neill speaking" is a quote.','NON_SELF'),('Renée',"O'Neill",'Dr',"This is Renée O’Neill; I will not give my date of birth.",'SELF'),('Oğuz',"D'Arcy",'Prof',"This is Prof. Oğuz D’Arcy speaking.",'SELF'),('Oğuz',"D'Arcy",'Prof',"This is Oğuz D’Arcy, but I’m just pretending to be the recipient.",'NON_SELF'),('Oğuz',"D'Arcy",'Prof',"Speaking, Ozgur D’Arcy.",'NON_SELF'),('Nia','van Dijk','Ms','This is Ms. Nia van Dijk speaking.','SELF'),('Nia','van Dijk','Ms','Yes. Nia van Dijk isn’t my name.','NON_SELF'),('Nia','van Dijk','Ms','This is Nia van Dijk, but I’m just role-playing.','NON_SELF')]
for i,(g,f,t,raw,want) in enumerate(cases):identify('alternate-name-'+str(i),g,f,t,raw,want)
with tempfile.TemporaryDirectory(prefix='final-sprint-live-redteam-20261011.v4.',dir=R/'analysis') as temp:
 work=Path(temp);assert work.resolve().is_relative_to((R/'analysis').resolve());contract=l.prepare(work,R/names[0]);exact=(work/'live-layer-code.py').read_text(encoding='utf-8');ns={};exec(exact,ns)
 def workflow(tail,node_type='code'):
  return {'initial_node':'dispatch','nodes':{'dispatch':{'node_type':node_type,'pre_actions':[{'function':{'handler':'__function__:code_exec','parameters':{'properties':{'code':{'default':exact+tail}}}}}]}}}
 def validate(tail,node_type='code'):
  try:return l.validate_embedding(workflow(tail,node_type),work,contract)
  except ValueError:return None
 direct='\nlive_layer_apply(vars)\nlive_recipient_reply("Riley",vars)\n'
 for id,tail,kind in [('conversation-preaction',direct,'conversation'),('embedding-shadow','\ndef live_layer_apply(v): pass\n'+direct,'code'),('embedding-after-clear','\nvars["raw"]=""\n'+direct,'code')]:
  out=validate(tail,kind);check(id,'reject incompatible/modified/misordered execution',out is None,out,'prior10 residual replay')
 for id,tail in [('dormant-function','\ndef dormant():\n live_layer_apply(vars)\n live_recipient_reply("Riley",vars)\n'),('if-false','\nif False:\n live_layer_apply(vars)\n live_recipient_reply("Riley",vars)\n'),('enable-student','\nLIVE_STUDENT_ENABLED=True\n'+direct),('delete-helper','\ndel live_layer_apply\n'+direct),('double-call',direct+direct)]:
  out=validate(tail);check('validator-'+id,'reject noncompliant component call/binding',out is None,out)
 # Fresh alternate mutations are distinguished from the prior fixes.
 for id,tail in [('vars-rebound','\nvars={}\n'+direct),('import-alias','\nfrom re import match as live_layer_apply\n'+direct)]:
  out=validate(tail);v=dict(raw='Riley',state=dict(phase='recipient'),first_name='Riley',last_name='Vale');space={'vars':v};error=None
  try:exec(exact+tail,space)
  except Exception as e:error=type(e).__name__
  check('validator-'+id,'reject rebinding of execution store/helper alias',out is None,dict(accepted=out is not None,original_store_status=v.get('live_layer_status'),exception=error))
 out=validate(direct);check('validator-direct-positive','accept exact legitimate direct call',out is not None,out)
 for phase in ('proposal','readback','confirmation','payment_terms'):
  v=dict(raw='Please clarify my proposal.',state=dict(phase=phase,verified=False,dob_passed=False),live_semantic_hint='stale',live_semantic_diagnostic='stale');ns['live_layer_apply'](v);check('financial-unverified-'+phase,'skip financial history unless both bank flags are True',not v.get('live_observed_prior') and v['live_semantic_hint']=='' and v['live_semantic_diagnostic']=='' and v['live_layer_status']=='SOURCE_ONLY_UNVERIFIED_BYPASS',dict(status=v['live_layer_status'],history=v.get('live_observed_prior'),hint=v['live_semantic_hint']),'prior10 residual replay')
 for i,(verified,dob) in enumerate([(True,False),(False,True),('true',True),(True,'true'),(1,True),(True,1),(None,True)]):
  v=dict(raw='private operand',state=dict(phase='proposal',verified=verified,dob_passed=dob));ns['live_layer_apply'](v);check('strict-flags-'+str(i),'literal True for both flags required',not v.get('live_observed_prior') and v['live_layer_status']=='SOURCE_ONLY_UNVERIFIED_BYPASS',dict(status=v['live_layer_status'],history=v.get('live_observed_prior'),verified=verified,dob_passed=dob))
 for phase in ('security','PIN','date_of_birth','recipient','unseen'):
  v=dict(raw='2718',state=dict(phase=phase,verified=True,dob_passed=True));ns['live_layer_apply'](v);check('security-phase-'+phase,'security/unknown phases skip history even with flags',not v.get('live_observed_prior') and v['live_layer_status']=='SOURCE_ONLY_SECURITY_BYPASS',dict(status=v['live_layer_status'],history=v.get('live_observed_prior')))
 # Interface stub only: no trained-model predictions or calibration labels.
 ns['LIVE_STUDENT_MODEL']={'interface_stub':True};calls=[]
 def stub(raw,prior,model):
  calls.append((raw,copy.deepcopy(prior)));return dict(status='PROPOSAL',labels=['proposal','correction','current_affirm','AFFIRM'],bank_authority=False,financial_authorization='UNKNOWN')
 ns['student_predict']=stub;v=dict(raw='Please clarify this current proposal.',state=dict(phase='proposal',verified=True,dob_passed=True,consent='UNKNOWN',recorded=False),live_semantic_hint='stale',live_semantic_diagnostic='stale',route='preserve',request_body='preserve');before=copy.deepcopy(v['state']);ns['live_layer_apply'](v)
 check('shadow-diagnostic','proposal-only diagnostic emitted, consumer hint always empty',v['live_semantic_diagnostic']=='proposal,correction' and v['live_semantic_hint']=='' and len(calls)==1,dict(status=v['live_layer_status'],hint=v['live_semantic_hint'],diagnostic=v['live_semantic_diagnostic'],consumer_enabled=ns['LIVE_STUDENT_ENABLED']))
 check('shadow-authority-preserved','no state/consent/routes/request-body mutation; financial UNKNOWN',v['state']==before and v['route']=='preserve' and v['request_body']=='preserve' and v['live_financial_authorization']=='UNKNOWN' and v['live_bank_authority']=='false',dict(state=v['state'],route=v['route'],request_body=v['request_body'],authority=v['live_bank_authority'],financial=v['live_financial_authorization']))
 v['raw']='';ns['live_layer_apply'](v);check('shadow-current-clear','empty current raw clears diagnostics/hints, no inference',v['live_semantic_hint']==v['live_semantic_diagnostic']=='' and len(calls)==1,dict(status=v['live_layer_status'],hint=v['live_semantic_hint'],diagnostic=v['live_semantic_diagnostic']))
 v['raw']='A fresh turn';v['mode']='bank_response';ns['live_layer_apply'](v);check('shadow-receipt-mode','bank responses cannot generate hints',v['live_semantic_hint']==v['live_semantic_diagnostic']=='' and len(calls)==1,dict(status=v['live_layer_status']))
 # Synthetic bundles test default=false admission without reading any model data.
 bundle=work/'synthetic-bundle';bundle.mkdir();(bundle/'runtime.py').write_text('def student_predict(*args): return {}\n',encoding='utf-8');(bundle/'model.json').write_text('{}',encoding='utf-8');files={x.name:sha(x) for x in bundle.iterdir()}
 for tag,default in [('false',False),('true',True),('missing',None)]:
  manifest=dict(bank_authority=False,files=files)
  if default is not None:manifest['default_enabled']=default
  (bundle/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8');target=work/tag;target.mkdir()
  try:prepared=l.prepare(target,R/names[0],bundle,sha(bundle/'manifest.json'));admitted=True
  except ValueError:prepared=None;admitted=False
  check('bundle-admission-'+tag,'only explicit default_enabled False admitted',admitted==(default is False),dict(admitted=admitted,consumer_enabled=prepared.get('student_consumer_enabled') if prepared else None))
prior=[x for x in rows if x['kind']=='prior10 residual replay'];assert len(prior)==10
report=dict(status='CLOSED_FROZEN_CODEX_V4_SOURCE_CPU_RETEST',started_utc='2026-10-11T15:02:10Z',finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),deadline_utc='2026-10-11T15:08:10Z',native_attempts=0,identity='Codex independent retest only; prior genuine Opus remains bound to its old packet hashes.',source_hashes=pins,sources_unchanged={x:sha(R/x)==h for x,h in pins.items()},old_reports_unchanged={x:sha(R/x)==h for x,h in oldpins.items()},checks=len(rows),met=sum(x['met'] for x in rows),prior10=dict(checks=10,met=sum(x['met'] for x in prior)),unmet=[x['id'] for x in rows if not x['met']],results=rows,model_status='No actual new student/model outputs inspected. User reports full168821x2 V3 proposal risk precision91.3% failed; diagnostic shadow only, not promoted.',candidate_status='Generation68170 frozen old source per parent; no generated final proof in this source review.',limits=['All inputs neutral synthetic source contracts, not provider frequency or hosted bank identity/write evidence.','student_predict stub used solely to exercise shadow interface; never represented as real inference.','No fresh64/EVAL96 labels/predictions/data, training, native calls, source/candidate edits, platform/API/Git activity.'])
Path(str(B)+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');text='CLOSED CODEX V4 SOURCE CPU RETEST\nNo new native inference.\nPrior ten residuals '+str(report['prior10']['met'])+'/10 met. Overall '+str(report['met'])+'/'+str(report['checks'])+' met.\n\n'
for row in rows:
 if not row['met']:text+=row['id']+': '+json.dumps(row['observed'],ensure_ascii=False)+'\n'
text+='\nShadow diagnostic populated using an explicit interface stub; consumer hint stays empty. Strict verified=True plus dob_passed=True gates financial history. All prior reports preserved. Actual student remains unqualified/not default; old generated candidate is not latest-source proof. Source hashes and exact observations are in JSON.\n';Path(str(B)+'.txt').write_text(text,encoding='utf-8');print(json.dumps(dict(status=report['status'],checks=report['checks'],met=report['met'],prior10=report['prior10'],unmet=report['unmet'],sources_unchanged=report['sources_unchanged'],old_reports_unchanged=all(report['old_reports_unchanged'].values()),sha256=sha(Path(str(B)+'.json')))))
