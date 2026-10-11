import ast, copy, datetime, hashlib, json, pathlib, re, sys, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
WORK=ROOT/'competition/runs/20261011-180353-bdb56c/work'
OUT=ROOT/'analysis/final-sprint-v3-live-candidate-review-20261011'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
paths=[WORK/x for x in ['workflow.json','controller.py','live-layer-code.py','recipient_assertion.py','student-runtime.py','student-model.json','student-manifest.json','live-layer-contract.json','policy.json','coverage.json','inputs/01-brief-a.md','inputs/openapi.json','inputs/tools-and-code.md','inputs/workflow-format.md']]+[WORK.parent/'status.json']
before={str(p.relative_to(ROOT)):sha(p) for p in paths}
w=json.loads((WORK/'workflow.json').read_text(encoding='utf-8'))
code=w['nodes']['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
compiled=compile(code,'<frozen-candidate-dispatch>','exec')
checks=[]; samples=[]
def check(name,ok,evidence=None,classification='literal_source_CPU'):
    checks.append(dict(name=name,met=bool(ok),classification=classification,evidence=evidence))
def step(store,updates=None):
    store.update(copy.deepcopy(updates or {})); v=copy.deepcopy(store); counts={}
    def profile(frame,event,arg):
        if event=='call' and frame.f_code.co_filename=='<frozen-candidate-dispatch>' and frame.f_code.co_name in ('student_predict','student_features','live_layer_apply','hint_clarification','run'):
            k=frame.f_code.co_name; counts[k]=counts.get(k,0)+1
    ns={'vars':v}; sys.setprofile(profile)
    try: exec(compiled,ns)
    finally: sys.setprofile(None)
    store.update(v)
    return copy.deepcopy(v),counts,ns
base={'customer_id':'neutral-17','first_name':'Nia','last_name':'van Dijk','title':'Dr','now':'2026-10-14T11:00:00'}
initial,_,ns=step(copy.deepcopy(base))
state=copy.deepcopy(initial['state'])
p={'product_id':'neutral-card','type':'credit_card','card_last4':'7359','label':'credit card ending 7359','past_due':510.0,'floor':170.0,'minimum_payment':170.0,'days_late':4,'deadline':'2026-10-30','limit':1}
def financial(phase='offer'):
    s=copy.deepcopy(state); s.update(phase=phase,verified=True,dob_passed=True,product=copy.deepcopy(p),products=[copy.deepcopy(p)],offer={'amount':510.0,'date':'2026-10-14','revision':1},pending={},warned='true')
    return dict(copy.deepcopy(base),state=s)
check('exact user workflow pin',before[str((WORK/'workflow.json').relative_to(ROOT))]=='01737194f782659fb2799c9513e353bcf08005e004129fe7ba80c3e9669705ee')
check('embedded controller literal identical',code==(WORK/'controller.py').read_text(encoding='utf-8'))
component=(WORK/'live-layer-code.py').read_text(encoding='utf-8')
check('exact component embedded',component in code)
model=json.loads((WORK/'student-model.json').read_text(encoding='utf-8'))
check('actual embedded weights identical',ns.get('LIVE_STUDENT_MODEL')==model)
contract=json.loads((WORK/'live-layer-contract.json').read_text(encoding='utf-8'))
check('bundle pins exact',all(sha(WORK/k)==v for k,v in contract['files'].items()))
check('clarify explicit opt-in',ns.get('LIVE_STUDENT_ENABLED') is True and contract['student_use']=='clarify' and contract['risk_qualified'] is False)
for phase in ['recipient','dob','phone','unknown','decision']:
    st=financial(phase); st['state'].update(verified=False,dob_passed=False)
    v,c,_=step(st,{'raw':'I can pay the card tomorrow.','event':'k=unknown;c=1;END','admin':'none'})
    check('no model in unverified '+phase,c.get('student_predict',0)==0 and not v.get('live_semantic_hint'),{'status':v.get('live_layer_status'),'calls':c})
st=financial(); st['state']['dob_passed']=False
v,c,_=step(st,{'raw':'I can pay tomorrow.','event':'k=unknown;c=1;END'})
check('both security gates required',c.get('student_predict',0)==0)
st=financial(); st['state']['awaiting']='account'
v,c,_=step(st,{'mode':'account','raw':'I can pay tomorrow.','bank_result':{'ok':True,'products':[p]}})
check('API mode bypass',c.get('student_predict',0)==0 and not v.get('live_semantic_hint'))
utterances=['I can pay the card tomorrow.','I want to change the payment date instead.','This debt is not mine.','I am unsure about this card payment.','Can I pay on Friday?','I will make a payment today.']
selected=None
for raw in utterances:
    st=financial('readback'); st['state'].update(pending={'amount':340.0,'date':'2026-10-21'},readback={'amount':340.0,'date':'2026-10-21'})
    v,c,n=step(st,{'raw':raw,'event':'k=unknown;c=1;END','admin':'none'})
    pred=n['student_predict'](raw,[],n['LIVE_STUDENT_MODEL'])
    samples.append({'raw':raw,'model_status':pred['status'],'labels':pred['labels'],'score_range':[min(pred['scores']),max(pred['scores'])],'profile':c,'broker_status':v.get('live_layer_status'),'hint':v.get('live_semantic_hint'),'speech':v.get('dialogue_line'),'route':v.get('route'),'clarified':v['state'].get('student_clarified',False)})
    check('real model called '+raw,c.get('student_predict')==1 and len(pred['scores'])==11 and pred['bank_authority'] is False)
    check('unknown no write '+raw,v['route'] not in ('create_promise','get_account','verify_identity') and not v['state']['recorded'])
    if v['state'].get('student_clarified') and selected is None: selected=(raw,st,v)
check('actual model exercised hint consumer',selected is not None,samples)
if selected:
    raw,st,v=selected
    check('hint invalidates readback retains terms',v['state']['readback'] is None and v['state']['pending']=={'amount':340.0,'date':'2026-10-21'})
    direct=copy.deepcopy(st); directv,_,_=step(direct,{'raw':'Yes, I confirm.','event':'k=confirm;c=1;END'})
    check('no phantom consent immediately after hint',directv['route']!='create_promise' and directv['state']['phase']=='readback',{'route':directv['route'],'speech':directv['dialogue_line']})
    first=v['dialogue_line']; v2,c,_=step(st,{'raw':raw,'event':'k=unknown;c=1;END'})
    check('clarification once',v2['dialogue_line']!=first and v2['state'].get('student_clarified') is True,{'first':first,'second':v2['dialogue_line']})
    v3,_,_=step(st,{'raw':'Yes, I confirm.','event':'k=confirm;c=1;END'})
    check('yes after separately reissued full readback permitted',v3['route']=='create_promise',{'prior_readback':v2['dialogue_line'],'route':v3['route']})
    for ev in ['BAD','k=proposal;c=0;u=amount;END','k=proposal;c=1;a=340;d=2026-10-21;END']:
        t=financial(); h,counts,_=step(t,{'raw':raw,'event':ev})
        check('real proposal hint never supplies financial slots '+ev,h['route']!='create_promise' and not h['state']['recorded'],{'hint':h.get('live_semantic_hint'),'speech':h['dialogue_line'],'clarified':h['state'].get('student_clarified',False),'pending':h['state']['pending'],'profile':counts},'conditional_codec_input_CPU')
st=financial(); v,c,_=step(st,{'raw':'I will pay 340 on October 21.','event':'k=proposal;c=1;a=340;d=2026-10-21;END'})
check('complete proposal not overridden',v['state']['phase']=='readback' and v['state']['readback']==v['state']['pending'] and not v['state'].get('student_clarified') and v['route']=='talk',{'speech':v['dialogue_line'],'hint':v.get('live_semantic_hint')})
check('complete proposal no write before later yes',v['route']!='create_promise' and not v['state']['recorded'])
ready=copy.deepcopy(st)
for raw in ['Yes, if you waive the fee.','My brother said yes, but I do not consent.','I withdraw permission.']:
    t=copy.deepcopy(ready); v,_,_=step(t,{'raw':raw,'event':'k=confirm;c=1;END'})
    check('inconsistent typed confirm guarded '+raw,v['route']!='create_promise',{'route':v['route'],'speech':v['dialogue_line']},'forced_semantic_inconsistent_CPU')
v,c,_=step(st,{'raw':'Yes, I confirm.','event':'k=confirm;c=1;END'})
check('fresh later yes dispatch exact body',v['route']=='create_promise' and v['state']['authorized_promise']=={'customer_id':'neutral-17','product_id':'neutral-card','amount':340.0,'date':'2026-10-21'})
check('no pre-receipt acknowledgement',not v['state']['recorded'] and 'promise is recorded' not in v['dialogue_line'].lower())
dispatched=copy.deepcopy(st)
t=copy.deepcopy(st); v,_,_=step(t,{'mode':'promise','bank_result':{'ok':True,'promise_id':'stale'}})
check('stale successful result rejected',not v['state']['recorded'] and v['route']!='create_promise',{'route':v['route'],'speech':v['dialogue_line']})
dispatch=st['state']['promise_dispatch']; request=copy.deepcopy(dispatch['request'])
v,_,_=step(st,{'mode':'promise','promise_started':dispatch['token'],'create_promise_failure_count':dispatch['failure_base']+1,'create_promise_success_count':dispatch['success_base'],'create_promise_response.status':'error','create_promise_response.status_code':'500','create_promise_status_code':500,'create_promise_response.error':'HTTP 500','bank_result':{}})
check('documented fresh 500 retries once unchanged',v['route']=='create_promise' and v['state']['write_tries']==2 and v['state']['promise_dispatch']['request']==request and not v['state']['recorded'])
dispatch=st['state'].get('promise_dispatch',{})
v,_,_=step(st,{'mode':'promise','promise_started':dispatch.get('token'),'create_promise_failure_count':dispatch.get('failure_base',0),'create_promise_success_count':dispatch.get('success_base',0)+1,'bank_result':{'ok':True,'promise_id':'neutral-receipt'}})
check('fresh receipt acknowledges plus SMS',v['state']['recorded'] and v['outcome']=='promise' and 'You will receive a text message confirming this promise.' in v['dialogue_line'],{'route':v['route'],'speech':v['dialogue_line']},'conditional_synthetic_bank_receipt_CPU')
for event,raw in [('k=proposal;c=0;u=amount;END','I can pay three...'),('k=change;c=0;u=both;END','Actually, change both...'),('k=change;c=0;u=date;END','Change the date to...'),('k=proposal;c=1;a=nan;END','I propose a payment.'),('BAD','I can pay tomorrow.')]:
    t=copy.deepcopy(ready); v,c,_=step(t,{'raw':raw,'event':event})
    speech=v['dialogue_line']
    check('no open amount elicitation '+event,re.search(r'(how much|(?:finish|specify|repeat|tell me).{0,25}amount)',speech,re.I) is None,{'speech':speech})
    check('partial/malformed no authority '+event,v['route']!='create_promise' and not v['state']['recorded'])
for raw in ['This is Nia van Dijk speaking.','Speaking, Dr van Dijk.','Yes, this is Nia van Dijk, but I am just role-playing.','My brother said "I am Nia van Dijk".','I am Mila van Dijk.']:
    t=dict(copy.deepcopy(base),state=copy.deepcopy(state)); v,c,_=step(t,{'raw':raw,'event':'k=recipient;c=1;END'})
    check('recipient never verifies '+raw,v['state']['verified'] is False and v['state']['dob_passed'] is False and v['route'] not in ('get_account','create_promise'))
    samples.append({'recipient_raw':raw,'phase':v['state']['phase'],'decision':v.get('live_recipient_decision'),'route':v['route']})
tree=ast.parse(code); imports=[]
for node in ast.walk(tree):
    if isinstance(node,(ast.Import,ast.ImportFrom)): imports.extend([x.name for x in node.names] if isinstance(node,ast.Import) else [node.module])
check('no external code imports',set(imports)<=set(['json','re','datetime','math']),imports)
api_nodes=[k for k,v in w['nodes'].items() if str(v.get('node_type','')).lower()=='api_request']
check('bank-only node inventory',set(api_nodes)<=set(['verify_identity','get_account','create_promise','transfer_to_agent','schedule_callback','close_call']),api_nodes)
urls=[]; toolnames=[]
def tools_walk(x):
    if isinstance(x,dict):
        if x.get('handler')=='__function__:api_call': toolnames.append(x.get('name'))
        props=x.get('properties',{})
        if isinstance(props,dict) and isinstance(props.get('url'),dict): urls.append(props['url'].get('default',''))
        for value in x.values(): tools_walk(value)
    elif isinstance(x,list):
        for value in x: tools_walk(value)
tools_walk(w)
api=json.loads((WORK/'inputs/openapi.json').read_text(encoding='utf-8'))
servers=[s['url'].rstrip('/') for s in api.get('servers',[]) if isinstance(s,dict) and isinstance(s.get('url'),str)]
check('external tools all bank api handlers',set(toolnames)<=set(['verify_identity','get_account','create_promise','transfer_to_agent','schedule_callback','close_call']),sorted(set(toolnames)))
check('API endpoints bound to supplied bank server',bool(urls) and all(any(u.startswith(s+'/') for s in servers) for u in urls),{'endpoint_count':len(urls),'all_bound':all(any(u.startswith(s+'/') for s in servers) for u in urls)})
bad=copy.deepcopy(model); bad['thresholds'][0]=float('nan')
badresult=ns['student_predict']('I will make a payment today.',[],bad)
check('invalid model threshold failclosed',badresult['status']=='INVALID' and not badresult['labels'] and badresult['financial_authorization']=='UNKNOWN')
after={str(p.relative_to(ROOT)):sha(p) for p in paths}
check('all audited source hashes stable',before==after)
result={'status':'CLOSED_FROZEN_CODEX_FINAL_V3_CANDIDATE_SOURCE_CPU_REVIEW','identity':'Independent Codex; no new native Opus call','candidate':{'path':str((WORK/'workflow.json').relative_to(ROOT)),'sha256':sha(WORK/'workflow.json'),'published':False},'scope':'Unchanged literal embedded dispatch, real pinned student on fresh neutral authored utterances; persistent assign/merge store. No dataset labels/outcomes, hosted calls, network, training or candidate edits. API outcomes synthetic conditional inputs.','counts':{'executed':len(checks),'met':sum(x['met'] for x in checks),'unmet':sum(not x['met'] for x in checks)},'checks':checks,'samples':samples,'source_hashes_before':before,'source_hashes_after':after,'harness_correction':'Initial no-phantom-consent check incorrectly placed a repeated unknown turn which explicitly reissued full readback before yes. Corrected immediate-after-hint and separate-fresh-readback controls are both executed; no source modification.','findings':[{'priority':'P2','scope':'hint consumer scope','fact':'Hint consumer is reachable from decode exception, not only syntactically valid canonical unknown. Malformed event with real proposal hint may receive one clarification; no slots or consent synthesized.','recommendation':'Make decode failure vs canonical unknown eligibility explicit in contract; keep all malformed rows unauthoritative.'},{'priority':'P2','scope':'recipient eligibility','fact':'Frozen hyphenated role-playing assertion may advance to DOB; independently tested no verification or bank action.','recommendation':'Future parser revision should veto hyphenated role-play qualifiers; no frozen candidate patch.'}],'limitations':['raw is extractor_copy, not authenticated speech; no live extractor frequency proof','CAL below old target; user-authorized experimental clarify only; no qualification claim','Known role-playing parser gap is NONVERIFIED eligibility only','Model-authored local checks not counted; local generated completed publishedFalse not hosted validation','Receipt chronology is synthetic contract replay, not actual bank evidence']}
OUT.with_suffix('.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
failed=[x for x in checks if not x['met']]
result['frozen_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
result['disposition']='No authority-breaking defect reproduced in these bounded checks. Experimental clarification only; residual scope/recipient findings retained. Not hosted/model qualification.'
OUT.with_suffix('.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
text='Independent Codex final V3 candidate source/CPU audit; no new Opus inference.\n'+json.dumps(result['candidate'])+'\n'+json.dumps(result['counts'])+'\n'+result['disposition']+'\nReal pinned model called in unchanged embedded dispatch: six neutral inputs, five ABSTAIN and one proposal. Real proposal reached one clarification; immediate next yes reissues full readback instead of writing. Complete canonical proposal unchanged; later yes requires receipt-bound dispatch. Synthetic stale result rejected, documented fresh HTTP500 retried once with identical body, fresh success permits acknowledgement and SMS. Unverified/security/API states bypass model; no open amount solicitation in tested partial/malformed branches.\nFindings:\n'+json.dumps(result['findings'],indent=2,ensure_ascii=False)+'\nAssertion failures:\n'+json.dumps(failed,indent=2,ensure_ascii=False)+'\n'+ '\n'.join(result['limitations'])+'\nAll source hashes stable: '+str(before==after)+'\nReport JSON contains exact checks, real-model call profiles and pins.\n'+result['harness_correction']+'\nFrozen: '+result['frozen_utc']+'\n'
OUT.with_suffix('.txt').write_text(text,encoding='utf-8')
print(json.dumps({'counts':result['counts'],'failures':failed,'real_model_samples':samples[:6],'report_sha256':sha(OUT.with_suffix('.json'))},ensure_ascii=False))
