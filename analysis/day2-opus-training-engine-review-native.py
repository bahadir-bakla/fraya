"""One bounded OAuth exact-model review. Never persist raw transport or thinking."""
import ast, hashlib, importlib.util, json, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
PREFIX=ROOT/'analysis/day2-opus-training-engine-review'
BASE='integrations/learned-dialogue/'
def sha(b): return hashlib.sha256(b).hexdigest()
def utc(): return datetime.now(timezone.utc).isoformat()
def read(p): return json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
def load(name,path):
    s=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def save(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
def summary(v):
    if isinstance(v,dict): return {k:summary(x) for k,x in v.items() if k not in ('text','probabilities','row_mask_partitions','loss_trajectory','source_segments','examples','digit_loss_examples','secret_or_contact_redaction_witnesses','broader_alias_examples')}
    if isinstance(v,list): return [summary(x) for x in v] if len(v)<=40 else {'list_count':len(v),'contents_omitted':True}
    return v
def main():
    output=PREFIX.with_name(PREFIX.name+'-native.json')
    preflight=None
    if output.exists():
        preflight=json.loads(output.read_text(encoding='utf8'))
        if preflight.get('status')!='NATIVE_BOUND_ATTEMPT_FAILED' or preflight.get('failure_tag')!='ValueError' or preflight.get('native_elapsed_seconds') is not None:
            raise RuntimeError('One-attempt output already exists; refusing another invocation')
        save(PREFIX.with_name(PREFIX.name+'-preflight.json'),preflight)
    start=time.monotonic();metrics=read(BASE+'day2_public_metrics_v2.json');plan=read(BASE+'day2_public_plan_v2.json');freeze=read(BASE+'day2_public_freeze_v2.json');kuhn=read('analysis/day2-public-data-independent-review.json')
    paths=set(metrics['source_sha256'])|set(metrics['input_sha256'])|set(freeze['models_sha256'])|set(freeze['artifacts_sha256'])
    paths.update([BASE+'day2_public_plan_v2.json',BASE+'day2_public_freeze_v2.json',BASE+'day2_public_pre_eval_freeze_v2.json','analysis/day2-public-data-independent-review.json','analysis/day2-parent-public-cpu-authorization-v2.json','analysis/day2-a-next6-source-review.json','analysis/day2-a-next6-witnesses.json','integrations/opus-redteam/run.py','local-runs/autonomous-rd/night-opus-review.py'])
    before={p:{'sha256':sha((ROOT/p).read_bytes()),'bytes':(ROOT/p).stat().st_size} for p in sorted(paths)}
    r={'status':'PREPARING','started_at_utc':utc(),'requested_model':'claude-opus-5-5','attempt_limit':1,'timeout_seconds':180,'actual_opus_inference_verified':False,'source_manifest':before,'raw_stdout_saved':False,'thinking_saved':False,'credential_files_read':False,'hosted_calls':0,'bank_calls':0,'fits':0,'GPU':0,'preflight_recovery':'Unsupported helper high effort rejected before process creation; use supported medium' if preflight else None}
    transport=load('training_safe_transport','local-runs/autonomous-rd/night-opus-review.py');helper=transport.helper()
    instructions='''HEAVY independent source-grounded architectural red-team of actual fitted public Banking77 source-intent head v2. NO bank attack-schema shoehorning. JSON only {review_type:"source_review_not_executed",findings:[up to7 objects {id,priority,title,source_references,claim,concrete_counterexample,safe_CPU_contract,conditional_assumptions,remedy}],assessment:{split_and_group_closure,calibration_and_selective_precision,quantization_and_parity,graph_ablation_effect_size,bank_authority_separation,source_quality_semantic_loss},recommendations:[prioritized concise source-compatible remedies],limitations:[...]}. <=2200words. Review three actual trainers/encoder/evaluator, hashes and reported metrics; full weights hashes provided but weights omitted. DO NOT assert execution. Actual3CPU fits completed, GNN78.45 vs NoEdges78.05 on993 (four rows), Sparse73.01; public publisher-TRAIN internal split, no publisherTEST/hidden/Freya benefit. Calibration disjoint CAL temperature-fit/threshold-select groups, adaptively selected threshold >=30proposal .90precision, no statistical guarantee. Two broader contraction alias cross-split links known from independent source review; exact skeleton closure does not prove independent ancestry/IID. Analyze raw vs group weighted accuracy, uncertain proposal precision vs authority, EVAL exposure, prefit grant/input/model freeze binding, exported quantization coverage/gaps and tie/low-margin stress. All bank deployment remains bank_abstain qualifiedFalse acceptanceFalse authoritynone. Diagnose interface tampering/untrusted artifact assumptions explicitly. Public77taxonomy supplies no consent/subject/current-payment/time/phone/promise/tool permission; digit delexicalization and semantic redaction can make authority distinctions unidentifiable. Need exact generic guards failclosed quotation/attributed subject/self phone/paid predicate/time/target, no direct tool authority or raw financial fallback. Prior exact A-next6 CPU222208pass14fail: two legitimate self-phone formulations reject; two contracted I've paid/processed current-payment paraphrases reject; six forced semantically-inconsistent paid positives include historical/future/unrelated/contradictory/carddigits; four forced quoted/thirdparty confirmations prepare write absent actualHTTP. Conforming unknown negatives failclosed; actualAPIreceipt essential. Conforming positives vs polluted-primary conditionals must be separate. New MiniLM public teacher worker owns fitting: no duplicate fit or recommendation disguised as executed model. Preserve all originalscores/candidates/reports; no raw data/secret examples sent, no execution/tools. Return precise source references and counterexamples, do not invent quota findings.'''
    blocks=[instructions,'METRICS '+json.dumps(summary(metrics),ensure_ascii=True),'PLAN '+json.dumps(summary({k:v for k,v in plan.items() if k not in ('worker_manifest_literal','row_mask_partitions')}),ensure_ascii=True),'KUHN '+json.dumps(summary({k:kuhn[k] for k in ('verdict','accounting','split_closure','redaction','policy_mapping','reproducibility') if k in kuhn}),ensure_ascii=True),'HASHES '+json.dumps(before)]
    for p in metrics['source_sha256']:
        source=(ROOT/p).read_text(encoding='utf-8-sig');blocks.append('SOURCE '+p+'\n'+'\n'.join('L%d %s'%(i,l) for i,l in enumerate(source.splitlines(),1)))
    cp=ROOT/'competition/runs/20261011-120033-ec0e86/codex-stress-a-next.workflow.json'
    candidate=json.loads(cp.read_bytes());workflow=candidate.get('workflow',candidate)
    for n in workflow['nodes'].values():
        if not isinstance(n,dict): continue
        def strings(v):
            if isinstance(v,str):yield v
            elif isinstance(v,dict):
                for x in v.values():yield from strings(x)
            elif isinstance(v,list):
                for x in v:yield from strings(x)
        for s in strings(n):
            if 'def disposition_source(' not in s:continue
            tree=ast.parse(s)
            for f in tree.body:
                if isinstance(f,ast.FunctionDef) and f.name in ('security_subject','disposition_source','blocked_acceptance'):
                    lines=s.splitlines();blocks.append('A-next6 exactguard '+f.name+' exportSHA '+sha(cp.read_bytes())+'\n'+'\n'.join('L%d %s'%(i+1,lines[i]) for i in range(f.lineno-1,f.end_lineno)))
    prompt,redactions=transport.sanitize('\n'.join(blocks));r.update(prompt_sha256=sha(prompt.encode()),prompt_bytes=len(prompt.encode()),redactions=redactions)
    save(output,r)
    try:
        env=transport.safe_env();auth=helper.auth_status(transport.CLI,env);r['auth_status']={k:v for k,v in auth['status'].items() if k in ('loggedIn','authMethod','apiProvider','subscriptionType')}
        assert auth['exit_code']==0 and r['auth_status'].get('loggedIn') is True and r['auth_status'].get('authMethod') in ('claude.ai','oauth') and r['auth_status'].get('apiProvider')=='firstParty'
        r['cli_sha256']=sha(transport.CLI.read_bytes());r['status']='RUNNING_NATIVE_ONCE';save(output,r)
        args=helper.cli_arguments(transport.CLI,effort='medium');r['native_process_started']=True;save(output,r)
        t=time.monotonic();proc=subprocess.Popen(args,cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',errors='replace')
        try:stdout,_=proc.communicate(prompt,timeout=180)
        except subprocess.TimeoutExpired:
            proc.kill();proc.communicate(timeout=10);r.update(status='NATIVE_TIMEOUT',native_elapsed_seconds=round(time.monotonic()-t,3));stdout=''
        else:
            r['native_elapsed_seconds']=round(time.monotonic()-t,3);r['exit_code']=proc.returncode
            events=[]
            for line in stdout.splitlines():
                try:events.append(json.loads(line))
                except ValueError:pass
            r['safe_event_types']=[{'type':e.get('type'),'subtype':e.get('subtype'),'error_tag':e.get('error') if isinstance(e.get('error'),str) and re.fullmatch('[a-z_]+',e['error']) else None} for e in events]
            try:v=helper.verify_inference(events)
            except Exception:
                rate=any(e.get('type')=='rate_limit_event' or 'rate_limit' in str(e.get('error','')) for e in events)
                r.update(status='NATIVE_RATE_LIMIT_BLOCKED' if rate else 'NATIVE_EXACT_MODEL_UNVERIFIED',failure_tag='NO_SUCCESSFUL_EXACT_MODEL_AND_USAGE_PROOF')
            else:
                usage={m:{k:x for k,x in u.items() if k in ('inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens','webSearchRequests','costUSD','canonicalModel','provider')} for m,u in v['model_usage'].items()}
                assert sum(u.get('outputTokens',0) for u in usage.values())>0
                r.update(actual_opus_inference_verified=True,inference_evidence={'assistant_response_models':v['models'],'model_usage':usage,'tool_calls':0})
                answer,_=transport.sanitize(v['text']);answer=re.sub(r'^```(?:json)?\s*|\s*```$','',answer.strip());value=json.loads(answer)
                assert value.get('review_type')=='source_review_not_executed'
                r.update(status='COMPLETED_VERIFIED_NATIVE_SOURCE_REVIEW',review=value,final_answer_sha256=sha(answer.encode()))
        stdout=None
    except Exception as e:r.update(status='NATIVE_BOUND_ATTEMPT_FAILED',failure_tag=type(e).__name__)
    r.update(finished_at_utc=utc(),wall_seconds=round(time.monotonic()-start,3),source_hashes_unchanged={p:sha((ROOT/p).read_bytes())==d['sha256'] for p,d in before.items()})
    save(output,r);print(json.dumps({k:r.get(k) for k in ('status','actual_opus_inference_verified','native_elapsed_seconds','failure_tag','prompt_bytes')}))
if __name__=='__main__':main()
