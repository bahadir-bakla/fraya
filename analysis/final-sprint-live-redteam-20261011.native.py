"""Single bounded native exact-model source-only audit; streams never persisted."""
import datetime,hashlib,importlib.util,json,re,subprocess,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];base=R/'analysis/final-sprint-live-redteam-20261011'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sp=importlib.util.spec_from_file_location('live_native_helper',R/'local-runs/autonomous-rd/night-opus-review.py');n=importlib.util.module_from_spec(sp);sp.loader.exec_module(n);helper=n.helper()
names=['competition/live_layer.py','competition/recipient_assertion.py','competition/builder.py','integrations/learned-dialogue/live_v2_student_runtime.py','integrations/learned-dialogue/live_v2_student_train.py','build-the-builder 2/README.md','build-the-builder 2/docs/workflow-format.md','build-the-builder 2/docs/tools-and-code.md']
captured={p:(R/p).read_bytes() for p in names};pins={p:hashlib.sha256(b).hexdigest() for p,b in captured.items()}
packet=['Independent source-only audit of live recipient/student layer. Return concise JSON {findings:[{id,priority,source_pointer,contract,counterexample,control,claim_limit}],recommendations:[...],limits:[...]}. At most four material findings. Sources are frozen in memory and may change concurrently later; no candidate exists in this audit. Focus official model/external-tool/code restrictions, extractor_copy provenance and extraction-before-code, exact executable embedding versus dead/misordered call sites, current/prior permission isolation, state type/phase bypass and security history, invalid threshold/logit cutoffs/quantization safety, dynamic Unicode names/titles/quotes/reported/hypothetical/contradictory speakers. Student is proposal-only financial UNKNOWN, not full MiniLM. Trainer source only: no fresh64/EVAL96 examples, labels, predictions or prior case outputs. No tools; do not supply thinking or claim platform tests. Source-bound actionable counterexamples and conservative generic repairs. Under1500words.']
for p,b in captured.items():packet.append('EXACT_SOURCE '+p+' SHA256 '+pins[p]+'\n'+n.sanitize(b.decode('utf-8-sig'))[0])
# Read only model interface and manifest, never dataset indices or prediction files.
modelp=R/'integrations/learned-dialogue/live_v2_student/current_only_run/model.json';manifestp=modelp.parent/'manifest.json'
if modelp.exists() and manifestp.exists():
 model=json.loads(modelp.read_bytes());manifest=json.loads(manifestp.read_bytes());pins[str(modelp.relative_to(R)).replace('\\','/')]=sha(modelp);pins[str(manifestp.relative_to(R)).replace('\\','/')]=sha(manifestp)
 summary={k:model.get(k) for k in ('schema','model_kind','labels','feature_dim','context_mode','mode','thresholds','logit_cutoffs','quant_logit_margins','disabled_heads','financial_authorization','bank_authority')};summary['weight_shape']=[len(model.get('weights',[])),len(model.get('weights',[[]])[0])]
 packet.append('PINNED_MODEL_INTERFACE_ONLY '+json.dumps(summary)+'\nMANIFEST '+json.dumps(manifest))
report=dict(status='PREPARING',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_hashes=pins,actual_opus_inference_verified=False,attempts=0,scope='Source-only; no generated candidate, heldout data/outcomes or platform evidence.',raw_streams_thinking_prompt_saved=False)
try:
 env={k:v for k,v in n.safe_env().items() if not k.upper().endswith('_PROXY')};auth=helper.auth_status(n.CLI,env);safe={k:v for k,v in auth['status'].items() if k in ('loggedIn','authMethod','apiProvider','subscriptionType')};report['auth_status']=safe
 assert auth['exit_code']==0 and safe.get('loggedIn') is True and safe.get('authMethod') in ('oauth','claude.ai') and safe.get('apiProvider')=='firstParty','Native OAuth unavailable'
 prompt='\n\n'.join(packet);report['packet_sha256']=hashlib.sha256(prompt.encode()).hexdigest();report['packet_bytes']=len(prompt.encode());report['attempts']=1;report['timeout_seconds']=300
 tick=time.monotonic();proc=subprocess.Popen(helper.cli_arguments(n.CLI,effort='medium'),cwd=R,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace')
 try:stdout,_=proc.communicate(prompt,timeout=300)
 except subprocess.TimeoutExpired:proc.kill();proc.communicate(timeout=10);raise TimeoutError('Bounded native inference timed out')
 finally:report['seconds']=round(time.monotonic()-tick,3)
 report['exit_code']=proc.returncode;events=[]
 for line in stdout.splitlines():
  try:events.append(json.loads(line))
  except ValueError:pass
 report['rate_notification_count']=sum(e.get('type')=='rate_limit_event' for e in events)
 verified=helper.verify_inference(events);assert proc.returncode==0,'CLI failure'
 report['actual_opus_inference_verified']=True;report['inference_evidence']=dict(assistant_response_models=verified['models'],exclusive_usage_models=list(verified['model_usage']),model_usage={m:{k:v for k,v in usage.items() if k in ('inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens','webSearchRequests','canonicalModel','provider','costUSD')} for m,usage in verified['model_usage'].items()},tool_calls=verified['tool_calls'])
 answer=re.sub(r'^```(?:json)?\s*|\s*```$','',verified['text'].strip());report['model_claims']=json.loads(answer);report['final_answer_sha256']=hashlib.sha256(answer.encode()).hexdigest();report['status']='VERIFIED_NATIVE_OPUS_SOURCE_REVIEW'
except Exception as e:report.update(status='NATIVE_UNVERIFIED_CODEX_FALLBACK_ONLY',failure_type=type(e).__name__,failure_reason=str(e) if isinstance(e,(ValueError,AssertionError,TimeoutError)) else type(e).__name__)
report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();report['source_stability']={p:sha(R/p)==h for p,h in pins.items()};out=Path(str(base)+'.native.json');out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:report.get(k) for k in ('status','actual_opus_inference_verified','attempts','seconds','source_stability')}),flush=True)
