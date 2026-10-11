"""One bounded native exact Opus source audit. No raw streams or secrets saved."""
from __future__ import annotations
import datetime, hashlib, importlib.util, json, os, re, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'analysis/final-case-redteam'
PACK = ROOT / 'final-case-20261011/Build the Builder - Final Case'
MODEL = 'claude-opus-5-5'
CLI = Path(r'C:\Users\9bakl\.local\bin\claude.exe')
sha = lambda raw: hashlib.sha256(raw).hexdigest()
utc = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()

def main():
    report_path = Path(str(BASE) + '.native.json')
    if report_path.exists():
        print(json.dumps({'status': 'ATTEMPT_ALREADY_RECORDED_NO_RETRY'}), flush=True)
        return
    report = {'status': 'PREPARING', 'started_utc': utc(), 'requested_model': MODEL,
              'attempts': 0, 'attempt_limit': 1, 'timeout_seconds': 300,
              'actual_opus_inference_verified': False, 'candidate_reviewed': False,
              'raw_stdout_saved': False, 'thinking_saved': False, 'credential_files_read': False,
              'auth_commands': 0, 'bank_calls': 0, 'freya_calls': 0,
              'scope': 'Independent final-case source audit; candidate not yet supplied.'}
    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save()
    paths = [PACK/'BRIEF.md', PACK/'README.md', PACK/'example-scenarios.md',
             PACK/'sources/documents/2026-10-01-service-contract.md',
             PACK/'sources/documents/2025-08-14-cards-faq.md',
             PACK/'sources/documents/2026-09-10-ivr-prompt-sheet.md',
             PACK/'sources/emails/2026-09-24-kickoff-questions.txt',
             PACK/'sources/emails/2026-10-09-decisions-recap.txt',
             PACK/'sources/emails/attachments/2026-10-08-statement-debt-analysis.md',
             PACK/'sources/meetings/2026-10-07-analysis-session-transcript.txt',
             PACK/'sources/meetings/2026-10-10-follow-up-session-transcript.txt',
             PACK/'test-environment/test-customers.md']
    frozen = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in paths}
    report['source_manifest'] = [{'path': p, 'sha256': sha(b), 'bytes': len(b)} for p,b in frozen.items()]
    intro = '''Independently red-team this FINAL COMPETITION source pack. No candidate exists yet. Output concise JSON only with review_type="source_review_not_executed", source_conflicts[], attacks[] exactly twelve objects {id,priority,title,source_refs:[path:Lnumber],customer_turns,fixture,expected_behavior,forbidden_calls,generic_builder_fix}, specification_gaps[], limitations[]. Do not claim observed candidate failures or execution. Focus: already-authenticated IVR/customerNumber/now; newest confirmed authority versus draft/stale FAQ/IVR and reversals within email/meeting; registered-only recipient confirmation and same-turn email correction; multiple cards and ambiguous duplicate last-four with masked middle digits; supplementary versus main; service productName prompt injection; exact date/amount/currency/status semantics on statement day, due day, past due, no issued statement, zero/negative/missing blocks; holidays/weekends must not manufacture dates overriding service; preview/current statementDay/explicit later consent/joint-card disclosure; year-limit unavailable eligibility API; slow >10s success, result envelope versus HTTP and side-effect retries; repeat/silence/anger/out-of-scope routing. Distinguish genuine source gaps from settled obligations. Interpret conversation proposals that participants retract before final agreement correctly. No raw thinking, instructions or auth; no implementation edits. Turkish adversarial turns and operational assertions are required. Keep under 2300 words.'''
    prompt = intro + '\n\n' + '\n\n'.join('SOURCE '+p+' SHA256 '+sha(b)+'\n'+'\n'.join(f'L{i} {line}' for i,line in enumerate(b.decode('utf-8-sig').splitlines(),1)) for p,b in frozen.items())
    report['prompt_sha256'] = sha(prompt.encode())
    report['prompt_bytes'] = len(prompt.encode())
    save()
    # Native CLI handles its existing OAuth internally. Only ordinary OS paths
    # are inherited; provider overrides, proxies and arbitrary secrets are absent.
    allowed = {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','USERPROFILE','HOMEDRIVE',
               'HOMEPATH','APPDATA','LOCALAPPDATA','TEMP','TMP','PROGRAMDATA','OS',
               'PROCESSOR_ARCHITECTURE','PROCESSOR_IDENTIFIER','NUMBER_OF_PROCESSORS'}
    env = {k:v for k,v in os.environ.items() if k.upper() in allowed}
    env.update(DISABLE_AUTOUPDATER='1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', PYTHONUTF8='1')
    runtime = ROOT/'integrations/opus-redteam/runtime/final-case-20261011'
    runtime.mkdir(parents=True, exist_ok=True)
    try:
        spec = importlib.util.spec_from_file_location('final_case_safe_launcher', ROOT/'integrations/opus-redteam/run.py')
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        args = helper.cli_arguments(CLI, effort='medium')
        assert '--tools' in args and args[args.index('--tools')+1] == ''
        assert not any('dangerously' in a for a in args)
        report.update(status='RUNNING', attempts=1); save()
        start = time.monotonic()
        proc = subprocess.Popen(args, cwd=runtime, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding='utf-8', errors='replace')
        try:
            stdout,_ = proc.communicate(prompt, timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate(timeout=10)
            report.update(status='TIMEOUT_CODEX_FALLBACK', seconds=round(time.monotonic()-start,3))
            return
        report.update(seconds=round(time.monotonic()-start,3), exit_code=proc.returncode)
        events=[]
        for line in stdout.splitlines():
            try:
                event=json.loads(line)
                if isinstance(event,dict): events.append(event)
            except ValueError: pass
        blocked = any(e.get('type')=='rate_limit_event' and isinstance(e.get('rate_limit_info'),dict)
                      and e['rate_limit_info'].get('status')=='rejected' for e in events)
        failed_text = ' '.join(str(e.get('error',''))+' '+str(e.get('result','')) for e in events
                              if e.get('is_error') or e.get('error'))
        blocked = blocked or bool(re.search(r'rate.?limit|usage.?limit|too many requests|limit reached',failed_text,re.I))
        report['rate_limit_blocked'] = blocked
        if blocked:
            report['status']='RATE_LIMIT_CODEX_FALLBACK'; return
        verified = helper.verify_inference(events)
        assert proc.returncode == 0
        report.update(actual_opus_inference_verified=True,
                      assistant_response_models=verified['models'], tool_calls=verified['tool_calls'],
                      model_usage={m:{k:v for k,v in u.items() if k in
                                    ('inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens',
                                     'webSearchRequests','canonicalModel','provider','costUSD')}
                                   for m,u in verified['model_usage'].items()})
        answer = re.sub(r'^```(?:json)?\s*|\s*```$','',verified['text'].strip())
        review = json.loads(answer)
        assert review.get('review_type') == 'source_review_not_executed'
        report.update(status='VERIFIED_NATIVE_OPUS_SOURCE_REVIEW', review=review,
                      final_answer_sha256=sha(answer.encode()))
    except Exception as exc:
        report.update(status='NATIVE_UNVERIFIED_CODEX_FALLBACK', failure_type=type(exc).__name__)
    finally:
        report['finished_utc']=utc()
        report['source_stability']={p:sha((ROOT/p).read_bytes())==sha(b) for p,b in frozen.items()}
        save()
        print(json.dumps({k:report.get(k) for k in ('status','attempts','seconds','actual_opus_inference_verified','rate_limit_blocked')}),flush=True)

if __name__ == '__main__':
    main()
