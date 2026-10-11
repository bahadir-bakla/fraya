"""One bounded exact native OAuth review. No prompt/stream/thinking persistence."""
import ast,datetime,hashlib,importlib.util,json,re,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def main():
 n=load('local-runs/autonomous-rd/night-opus-review.py','classic_bounded_native_transport');m=n.helper()
 guide=ROOT/'competition/skills/build-phone-agent.md'
 run=ROOT/'competition/runs/20261011-141710-d6397a'
 candidate=run/'work/workflow.json';workflow=json.loads(candidate.read_bytes())
 code=workflow['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
 sourcepaths=[guide,candidate,run/'status.json',ROOT/'analysis/classic-merged-hardening.json',ROOT/'analysis/classic-next-review.friend.json']+[ROOT/'competition-v3/build-the-builder'/x for x in ('briefs/brief-a.md','briefs/brief-b.md','tools/openapi.json','docs/tools-and-code.md')]
 sourcepaths += list((ROOT/'analysis/mock-final-20261011/results-v1').glob('*.json'))+[ROOT/'analysis/mock-final-20261011/README.md',ROOT/'analysis/mock-final-20261011/audit.md']
 pins={p.relative_to(ROOT).as_posix():sha(p) for p in sourcepaths}
 report={'status':'PREPARING_ONE_NATIVE_EXACT_REVIEW','started_utc':utc(),'requested_model':n.MODEL,'actual_opus_inference_verified':False,'native_inference_attempts':0,'timeout_seconds':180,'source_hashes':pins,'scope':'Current classic guide plus unchanged failed unpublished pre-merge controller; historical friend mock evidence, no current hosted qualification','branch_provenance':'Parent says ca1565bd35ab4773ecd8afd13ee23a729c1b169d merged into HEAD6706017; no Git commands by this reviewer','raw_scores':{'C':{'pass':5,'calls':30},'D':{'pass':0,'calls':26}},'unofficial_adjusted_scores':{'C':{'pass':8,'calls':30},'D':{'pass':0,'calls':26}},'score_limits':'Friend mock cases; directly bound candidate version not verified. Adjusted scores are unofficial, not official passing evidence.','raw_prompt_stream_thinking_saved':False,'credential_files_read':False,'new_hosted_calls':0,'model_claims':None}
 try:
  env=n.safe_env();env={k:v for k,v in env.items() if not k.upper().endswith('_PROXY')}
  report['cli_sha256']=sha(n.CLI)
  report['cli_version']=subprocess.check_output([str(n.CLI),'--version'],env=env,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',timeout=20).strip()
  auth=m.auth_status(n.CLI,env)
  safe={k:v for k,v in auth['status'].items() if k in ('loggedIn','authMethod','apiProvider','subscriptionType')};report['auth_status']=safe
  assert auth['exit_code']==0 and safe.get('loggedIn') is True and safe.get('authMethod') in ('oauth','claude.ai') and safe.get('apiProvider')=='firstParty','Native first-party OAuth unavailable'
  blocks=['Independent classic engine R&D source audit. Return ONLY concise JSON: {assessments:[{id,priority,title,source_pointers,evidence,producer_conformance,conditional_cpu_plan,positive_control,generic_guide_fix}],architectural_recommendations:[...],already_covered:[...],limits:[...]}. Exactly THREE meaningful prioritized assessments; do not invent fault quotas. Review current guide for uncovered generic gaps/contradictions, not fixed fixtures. Guide hardening already covers dispute ownership denial, per-target payment corrections, security fragment provenance, pause/continuation consent and sibling note retry. Do not restate those as absent. Target recipient first/surname/title and self vs third-party security operands; latest scope/corrections across targets; note reason/scope/consent vs current receipts. Also check call-specific recipient grammar, failed-comparison fragment reset, and notes that copy unrelated security or caller speech. Code is a frozen failed unpublished PRE-guide-regeneration candidate, not a platform-tested implementation of current guide. Original bank brief/API alone defines policy. A semantic proposal is never tool authority. Keep voice AGENT_LLM and bank-only tools; no raw financial authority or successful write without current receipt. Do not add endpoints, LLMs or fixture-specific names/rules. No tools, no thinking, no transcript reconstruction. Under 1800 words. Include concrete test contracts and distinguish conforming source units from forced wrong producer rows and proposed fragment contract. Historical friend rawC5/30 D0/26; unofficial adjustedC8/30 distinct; no verified direct candidate version/official pass.']
  for p in sourcepaths[:9]:
   if p==candidate:
    data=json.dumps({'controller_literal':code,'listen':workflow['nodes'].get('listen'),'route_nodes':list(workflow['nodes'])},ensure_ascii=False)
   elif p.suffix=='.json' and 'hardening' in p.name:
    d=json.loads(p.read_bytes());data=json.dumps({'counts':d['counts'],'scope':d['scope'],'source':d['source'],'observations':[{'id':x['id'],'pass':x['pass'],'classification':x['classification']} for x in d['observations']]})
   elif p.name=='classic-next-review.friend.json':
    d=json.loads(p.read_bytes());data=json.dumps({k:d[k] for k in ('scope','derived_saved_summary_counts','concrete_failure_notes','provenance_limits')})
   elif p.name=='status.json':
    d=json.loads(p.read_bytes());data=json.dumps({'phase':d.get('phase'),'freya':d.get('freya'),'test_brief':d.get('test_brief')})
   else:data=p.read_text(encoding='utf-8-sig')
   data,_=n.sanitize(data);blocks.append('SOURCE '+p.relative_to(ROOT).as_posix()+' SHA256 '+pins[p.relative_to(ROOT).as_posix()]+'\n'+data)
  prompt='\n\n'.join(blocks);report['prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest();report['prompt_bytes']=len(prompt.encode())
  arguments=m.cli_arguments(n.CLI,effort='medium')
  start=time.monotonic();report['native_inference_attempts']=1
  process=subprocess.Popen(arguments,cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace')
  try:stdout,_=process.communicate(prompt,timeout=180)
  except subprocess.TimeoutExpired:
   process.kill();process.communicate(timeout=10);raise TimeoutError('Exact native inference exceeded180seconds')
  finally:report['elapsed_seconds']=round(time.monotonic()-start,3)
  report['exit_code']=process.returncode
  events=[]
  for line in stdout.splitlines():
   try:events.append(json.loads(line))
   except ValueError:pass
  rate=[e for e in events if e.get('type')=='rate_limit_event']
  if rate:report['rate_limit_status']=[{k:v for k,v in e.get('rate_limit_info',e.get('rateLimitInfo',{})).items() if k in ('status','resetsAt','rateLimitType','isUsingOverage')} for e in rate]
  inference=m.verify_inference(events)
  assert process.returncode==0,'Native nonzero exit'
  report['actual_opus_inference_verified']=True
  report['inference_evidence']={'assistant_response_models':inference['models'],'result_model_usage_keys':list(inference['model_usage']),'model_usage':{key:{k:v for k,v in usage.items() if k in ('inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens','webSearchRequests','canonicalModel','provider','costUSD')} for key,usage in inference['model_usage'].items()},'tool_calls':inference['tool_calls']}
  answer=re.sub(r'^```(?:json)?\s*|\s*```$','',inference['text'].strip());value=json.loads(answer)
  assert isinstance(value.get('assessments'),list) and len(value['assessments'])==3,'Review structure incomplete'
  report.update(status='COMPLETED_VERIFIED_NATIVE_OPUS_SOURCE_REVIEW',model_claims=value,final_answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
 except Exception as error:
  report.update(status='NATIVE_UNVERIFIED_CODEX_FALLBACK_REQUIRED',failure_type=type(error).__name__,failure_tag='RATE_LIMIT_BLOCKED' if report.get('rate_limit_status') else 'UNVERIFIED_OR_UNAVAILABLE',failure_reason=str(error) if isinstance(error,(AssertionError,TimeoutError,ValueError)) else type(error).__name__)
 report['finished_utc']=utc();report['protected_hashes_unchanged']={k:sha(ROOT/k)==v for k,v in pins.items()}
 out=ROOT/'analysis/classic-v2-opus.native.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'status':report['status'],'verified':report['actual_opus_inference_verified'],'seconds':report.get('elapsed_seconds'),'failure_tag':report.get('failure_tag'),'report_sha256':sha(out)}),flush=True)
if __name__=='__main__':main()
