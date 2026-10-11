"""Single bounded exact native review; prompts/streams exist in memory only."""
import datetime,hashlib,importlib.util,json,re,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'competition/runs/20261011-160237-d82126'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def scrub(v):
 if isinstance(v,dict):return {k:('REDACTED_CREDENTIAL_FIELD' if re.search(r'(?i)headers|authorization|api.?key|token|secret|password',k) else scrub(x)) for k,x in v.items()}
 if isinstance(v,list):return [scrub(x) for x in v]
 if isinstance(v,str):return n.sanitize(v)[0]
 return v
spec=importlib.util.spec_from_file_location('generated_native_helpers',ROOT/'local-runs/autonomous-rd/night-opus-review.py');n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n);m=n.helper()
paths=[RUN/'work'/x for x in ('workflow.json','policy.json','coverage.json')]+[ROOT/'analysis/mock-final-20261011/briefs/brief-c.md',RUN/'work/inputs/openapi.json']
raw={p:p.read_bytes() for p in paths};pins={p.relative_to(ROOT).as_posix():hashlib.sha256(b).hexdigest() for p,b in raw.items()}
assert pins['competition/runs/20261011-160237-d82126/work/workflow.json']=='aa25bf73f4a1a2fff8d5d9812be86adcf85a8ebbe32974eb2f9183574609ed46'
status=json.loads((RUN/'status.json').read_bytes())
report={'status':'PREPARING_EXACT_NATIVE_GENERATED_C_REVIEW','started_utc':utc(),'requested_model':'claude-opus-5-5','actual_opus_inference_verified':False,'native_inference_attempts':0,'timeout_seconds':180,'run_status_at_capture':{'phase':status.get('phase'),'error':status.get('error'),'freya':status.get('freya')},'source_hashes':pins,'scope':'Automatically authored local artifacts from failed/expired original builder run, not completed or published qualification. Model-authored checks are not independent evidence.','raw_prompts_stdout_thinking_saved':False,'new_hosted_calls':0}
try:
 env={k:v for k,v in n.safe_env().items() if not k.upper().endswith('_PROXY')}
 auth=m.auth_status(n.CLI,env);safe={k:v for k,v in auth['status'].items() if k in ('loggedIn','authMethod','apiProvider','subscriptionType')};report['auth_status']=safe
 assert auth['exit_code']==0 and safe.get('loggedIn') is True and safe.get('authMethod') in ('oauth','claude.ai') and safe.get('apiProvider')=='firstParty','Native firstParty OAuth unavailable'
 report['cli_sha256']=sha(n.CLI)
 blocks=['Independently red-team NEW automatically generated classic C local artifacts. Return concise JSON {assessments:[{id,priority,title,source_pointer,concrete_contract,positive_control,producer_conformance,expected_source_observable,claim_limit}],recommendations:[...],limits:[...]}. Up to3 supported material assessments, do not invent quota. Prioritize supplied Brief C precision/rounding/calendar, recipient names/subjects and phone-before-DOB fragments, latest amount/date and operation scoped consent/withdrawal/coupled intentions, C no payment retry and current API receipt lifetime. Read original Brief C as authority, not A/B defaults. Check policy/coverage against actual literal workflow. Do not assume artifacts completed a builder run: current phase FAILED, no publication; own authored100checks do not establish independent quality. No network or tools. Do not claim source-only/CPU as hosted observation. Do not include thinking. Under1500words. Suggest source-general fixes only; no fixture hardcoding, no modified score/actor or candidate edits.']
 for p,b in raw.items():
  text=b.decode('utf-8-sig');value=scrub(json.loads(text)) if p.suffix=='.json' else n.sanitize(text)[0]
  blocks.append('SOURCE '+p.relative_to(ROOT).as_posix()+' ORIGINAL_SHA256 '+pins[p.relative_to(ROOT).as_posix()]+'\n'+(json.dumps(value,ensure_ascii=False,separators=(',',':')) if not isinstance(value,str) else value))
 prompt='\n\n'.join(blocks);report['prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest();report['prompt_bytes']=len(prompt.encode())
 assert all(sha(ROOT/p)==h for p,h in pins.items()),'Source changed before inference'
 start=time.monotonic();report['native_inference_attempts']=1
 process=subprocess.Popen(m.cli_arguments(n.CLI,effort='medium'),cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace')
 try:stdout,_=process.communicate(prompt,timeout=180)
 except subprocess.TimeoutExpired:
  process.kill();process.communicate(timeout=10);raise TimeoutError('Bounded exact inference timed out')
 finally:report['native_seconds']=round(time.monotonic()-start,3)
 report['exit_code']=process.returncode;events=[]
 for line in stdout.splitlines():
  try:events.append(json.loads(line))
  except ValueError:pass
 rates=[e for e in events if e.get('type')=='rate_limit_event']
 if rates:report['failure_tag']='RATE_LIMIT_BLOCKED'
 inference=m.verify_inference(events);assert process.returncode==0,'CLI unsuccessful'
 report['actual_opus_inference_verified']=True
 report['inference_evidence']={'assistant_response_models':inference['models'],'exclusive_model_usage_keys':list(inference['model_usage']),'model_usage':{model:{k:v for k,v in usage.items() if k in ('inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens','webSearchRequests','canonicalModel','provider','costUSD')} for model,usage in inference['model_usage'].items()},'tool_calls':inference['tool_calls']}
 answer=re.sub(r'^```(?:json)?\s*|\s*```$','',inference['text'].strip());report['model_claims']=json.loads(answer);report['final_answer_sha256']=hashlib.sha256(answer.encode()).hexdigest();report['status']='VERIFIED_NATIVE_GENERATED_C_SOURCE_REVIEW'
except Exception as error:
 report.update(status='UNVERIFIED_NATIVE_CODEX_FALLBACK_ONLY',failure_type=type(error).__name__,failure_reason=str(error) if isinstance(error,(AssertionError,ValueError,TimeoutError)) else type(error).__name__)
report['finished_utc']=utc();report['sources_unchanged']={p:sha(ROOT/p)==h for p,h in pins.items()}
report['run_status_at_finish']={'phase':json.loads((RUN/'status.json').read_bytes()).get('phase')}
out=ROOT/'analysis/classic-v2-generated-review.native.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':report['status'],'native_verified':report['actual_opus_inference_verified'],'seconds':report.get('native_seconds'),'sources_stable':all(report['sources_unchanged'].values()),'report_sha256':sha(out)}),flush=True)
