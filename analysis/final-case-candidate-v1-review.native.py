"""Readiness pin and at most one native exact-model candidate audit; no raw streams saved."""
from __future__ import annotations
import argparse, datetime, hashlib, importlib.util, json, os, re, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'competition/runs/20261011-223232-b788d1'
BASE=ROOT/'analysis/final-case-candidate-v1-review'
MODEL='claude-opus-5-5';CLI=Path(r'C:\Users\9bakl\.local\bin\claude.exe')
sha=lambda b:hashlib.sha256(b).hexdigest()
utc=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
def out(s,v):Path(str(BASE)+s).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def readiness():
    status=read(RUN/'status.json')
    paths={k:RUN/'work'/name for k,name in [('candidate','workflow.json'),('policy','policy.json'),('coverage','coverage.json'),('api','inputs/openapi.json')]}
    row={'checked_utc':utc(),'run_id':RUN.name,'phase':status.get('phase'),'ready':False,'artifacts':{}}
    priorpath=Path(str(BASE)+'.readiness.json');prior=read(priorpath) if priorpath.exists() else {}
    captured={}
    for key,p in paths.items():
        if not p.exists():row['artifacts'][key]={'exists':False};continue
        b=p.read_bytes();stat=p.stat();valid=True
        try:v=json.loads(b)
        except (ValueError,UnicodeError):valid=False;v=None
        captured[key]=(p,b,v)
        row['artifacts'][key]={'exists':True,'bytes':len(b),'sha256':sha(b),'json_valid':valid,'age_seconds':round(time.time()-stat.st_mtime,2)}
    complete=len(captured)==4 and all(v['json_valid'] for v in row['artifacts'].values())
    if complete:
        workflow=captured['candidate'][2]
        complete=isinstance(workflow,dict) and isinstance(workflow.get('nodes'),dict) and bool(workflow['nodes']) and workflow.get('initial_node') in workflow['nodes']
    identical=complete and all(prior.get('artifacts',{}).get(k,{}).get('sha256')==d['sha256'] for k,d in row['artifacts'].items())
    previous_at=prior.get('checked_utc')
    observation_seconds=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(previous_at)).total_seconds() if previous_at else 0
    model_finished=(RUN/'answer-1.json').exists() or status.get('phase') in ('local_validation','validating','completed','published','exporting','publishing')
    stable=identical and observation_seconds>=20 and all(d['age_seconds']>=45 for k,d in row['artifacts'].items() if k!='api')
    row.update(ready=complete and (model_finished or stable),model_finished_evidence=model_finished,
               stable_observation_seconds=round(observation_seconds,2),stable_artifacts=stable)
    out('.readiness.json',row)
    return row,captured

def pin():
    receiptpath=Path(str(BASE)+'.pin.json')
    if receiptpath.exists():return read(receiptpath)
    row,captured=readiness()
    if not row['ready']:return row
    manifest=[]
    for key,(p,b,v) in captured.items():
        target=Path(str(BASE)+'.'+key+'.json');target.write_bytes(b)
        manifest.append({'kind':key,'source':p.relative_to(ROOT).as_posix(),'snapshot':target.relative_to(ROOT).as_posix(),'sha256':sha(b),'bytes':len(b)})
    assert all(sha((ROOT/m['source']).read_bytes())==m['sha256'] for m in manifest),'Artifacts changed during pin'
    record={'status':'PINNED_CANDIDATE','pinned_utc':utc(),'readiness':row,'manifest':manifest}
    out('.pin.json',record);return record

def launch():
    if datetime.datetime.now(datetime.timezone.utc)>=datetime.datetime(2026,10,11,19,47,tzinfo=datetime.timezone.utc):
        return {'status':'NATIVE_LAUNCH_CUTOFF_REACHED_NO_ATTEMPT'}
    nativepath=Path(str(BASE)+'.native.json')
    if nativepath.exists():return {'status':'NATIVE_ATTEMPT_ALREADY_RECORDED_NO_RETRY'}
    pinned=pin()
    if pinned.get('status')!='PINNED_CANDIDATE':return {'status':'WAITING_FOR_STABLE_CANDIDATE',**pinned}
    report={'status':'PREPARING','started_utc':utc(),'requested_model':MODEL,'attempts':0,'attempt_limit':1,
            'timeout_seconds':145,'maximum_inference_and_cleanup_seconds':150,'actual_opus_inference_verified':False,
            'candidate_reviewed':True,'candidate_manifest':pinned['manifest'],'raw_stdout_saved':False,'thinking_saved':False,
            'auth_commands':0,'credential_files_read':False,'network_bank_calls':0,'freya_calls':0,'git_commands':0}
    out('.native.json',report)
    prompt=['''Independent adversarial audit of this EXACT generated FINAL CASE candidate, current OpenAPI and policy. Source review only: no hosted/platform/ASR frequency or execution claims. Return JSON only {review_type:"exact_candidate_source_review_not_executed",candidate_sha256,findings:[{id,priority,title,candidate_refs:["JSON-pointer or code function+line"],source_refs,concrete_counterexample,observed_source_path,expected,highest_impact_generic_builder_repair,local_CPU_probe}],verified_controls:[],limitations:[]}. At most TWO actual material findings; fewer if evidence is insufficient. Under 650 words. Cite exact executable guards/tool paths, not generic hypothetical risks. Prioritize actual defects with bounded local CPU witnesses. Read all candidate code, hooks, transitions and tool parameters. Check IVR identity immutable customerNumber, no customer/PIN/DOB requests or PAN disclosure; now-based cut-day/past-due/no-debt/negative/missing-currency amounts; collisions without guesses; statement.week current statementDay for preview AND change, complete preview+joint impact+fresh affirmative+actual success receipt; email only registered recipient and issued date with same-turn corrections invalidating consent; source amendments; seven bank operations only. A pre_action default may bake at node entry; response updates must use runtime update store. Don't invent platform behavior. Do not edit candidate. Open annual-eligibility and masked-last-six gaps are already acknowledged: don't fill your two findings with repetitions of them. Highest-impact repair must change generic builder behavior and regenerate, never patch this candidate JSON. Full currency names, other-card-before-offer and no unissued dates are required. The October10 meeting explicitly accepts due-date-first opening as an alternative on cut day: mandatory amount is totalDebt, not one exact opening sentence. A missing GBP block is not zero. No raw thinking.''']
    for m in pinned['manifest']:
        b=(ROOT/m['snapshot']).read_bytes();assert sha(b)==m['sha256']
        # Whitespace-only JSON compaction preserves every source value. Raw
        # byte snapshots and their hashes remain the review identity.
        value=json.loads(b)
        compact=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        assert json.loads(compact)==value
        prompt.append('EXACT '+m['kind'].upper()+' '+m['source']+' RAW_SHA256 '+m['sha256']+' LOSSLESS_JSON_COMPACTION\n'+compact)
    # Prior source review supplied as concise adjudicated authority, not as candidate findings.
    audit=read(ROOT/'analysis/final-case-redteam.source.json')
    summary={k:audit[k] for k in ('source_conflicts','specification_gaps')}
    prompt.append('ADJUDICATED DOMAIN SUMMARY\n'+json.dumps(summary,ensure_ascii=False))
    pack=ROOT/'final-case-20261011/Build the Builder - Final Case'
    names=['sources/documents/2026-10-01-service-contract.md','sources/emails/attachments/2026-10-08-statement-debt-analysis.md',
           'sources/emails/2026-10-09-decisions-recap.txt','sources/meetings/2026-10-10-follow-up-session-transcript.txt']
    report['source_manifest']=[]
    for name in names:
        p=pack/name;b=p.read_bytes();report['source_manifest'].append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha(b)})
        prompt.append('SOURCE '+p.relative_to(ROOT).as_posix()+' SHA256 '+sha(b)+'\n'+'\n'.join(f'L{i} {line}' for i,line in enumerate(b.decode('utf-8-sig').splitlines(),1)))
    platform=RUN/'work/inputs/tools-and-code.md';b=platform.read_bytes()
    prompt.append('EXACT PLATFORM TOOL CONTRACT '+platform.relative_to(ROOT).as_posix()+'\n'+b.decode('utf-8-sig'))
    report['source_manifest'].append({'path':platform.relative_to(ROOT).as_posix(),'sha256':sha(b)})
    packet='\n\n'.join(prompt);report.update(prompt_sha256=sha(packet.encode()),prompt_bytes=len(packet.encode()))
    allowed={'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','USERPROFILE','HOMEDRIVE','HOMEPATH','APPDATA','LOCALAPPDATA','TEMP','TMP','PROGRAMDATA','OS','PROCESSOR_ARCHITECTURE','PROCESSOR_IDENTIFIER','NUMBER_OF_PROCESSORS'}
    env={k:v for k,v in os.environ.items() if k.upper() in allowed}
    env.update(DISABLE_AUTOUPDATER='1',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',PYTHONUTF8='1')
    try:
        spec=importlib.util.spec_from_file_location('candidate_exact_safe_launcher',ROOT/'integrations/opus-redteam/run.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        args=helper.cli_arguments(CLI,effort='low')
        assert args[args.index('--tools')+1]=='' and not any('dangerously' in a for a in args)
        report.update(status='RUNNING',attempts=1);out('.native.json',report)
        start=time.monotonic()
        proc=subprocess.Popen(args,cwd=ROOT/'analysis',env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace')
        try:stdout,_=proc.communicate(packet,timeout=145)
        except subprocess.TimeoutExpired:
            proc.kill();proc.communicate(timeout=5);report.update(status='TIMEOUT_CODEX_FALLBACK',seconds=round(time.monotonic()-start,3));return report
        report.update(seconds=round(time.monotonic()-start,3),exit_code=proc.returncode)
        events=[]
        for line in stdout.splitlines():
            try:
                e=json.loads(line)
                if isinstance(e,dict):events.append(e)
            except ValueError:pass
        blocked=any(e.get('type')=='rate_limit_event' and isinstance(e.get('rate_limit_info'),dict) and e['rate_limit_info'].get('status')=='rejected' for e in events)
        failed_text=' '.join(str(e.get('error',''))+' '+str(e.get('result','')) for e in events if e.get('is_error') or e.get('error'))
        blocked=blocked or bool(re.search(r'rate.?limit|usage.?limit|too many requests|limit reached',failed_text,re.I))
        report['rate_limit_blocked']=blocked
        if blocked:report['status']='RATE_LIMIT_CODEX_FALLBACK';return report
        verified=helper.verify_inference(events);assert proc.returncode==0
        report.update(actual_opus_inference_verified=True,assistant_response_models=verified['models'],tool_calls=verified['tool_calls'],
          model_usage={m:{k:v for k,v in u.items() if k in ('inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens','webSearchRequests','canonicalModel','provider','costUSD')} for m,u in verified['model_usage'].items()})
        answer=re.sub(r'^```(?:json)?\s*|\s*```$','',verified['text'].strip());review=json.loads(answer)
        assert review.get('review_type')=='exact_candidate_source_review_not_executed' and len(review.get('findings',[]))<=2
        report.update(status='VERIFIED_NATIVE_OPUS_CANDIDATE_REVIEW',review=review,final_answer_sha256=sha(answer.encode()))
    except Exception as exc:report.update(status='NATIVE_UNVERIFIED_CODEX_FALLBACK',failure_type=type(exc).__name__)
    finally:
        report['finished_utc']=utc()
        report['candidate_source_stability']={m['source']:sha((ROOT/m['source']).read_bytes())==m['sha256'] for m in pinned['manifest']}
        report['snapshot_stability']={m['snapshot']:sha((ROOT/m['snapshot']).read_bytes())==m['sha256'] for m in pinned['manifest']}
        out('.native.json',report)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('check','pin','launch'));a=p.parse_args()
    r=readiness()[0] if a.mode=='check' else pin() if a.mode=='pin' else launch()
    print(json.dumps({k:r.get(k) for k in ('status','phase','ready','artifacts','attempts','seconds','actual_opus_inference_verified','rate_limit_blocked') if k in r}),flush=True)
