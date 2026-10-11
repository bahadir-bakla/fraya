"""Read-only authored expectation QA; no agent, model, bank or network execution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone, date
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations/customer-datasets'))
import speech_stress_adapter as stress
import bound_stress_catalog as bound
import benchmark_runner as runner

PACK = ROOT / 'research/customer-benchmark/day2-expanded-cases.json'
MANIFEST = PACK.with_suffix('.manifest.json')
PREFIX = ROOT / 'analysis/day2-expanded-cases-independent-review'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
rows = json.loads(PACK.read_text(encoding='utf-8'))
manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
inputs = [PACK, MANIFEST, Path(stress.__file__), Path(bound.__file__), Path(runner.__file__), Path(stress.b.__file__), Path(stress.b.local.__file__), stress.KIT/'briefs/brief-a.md', stress.KIT/'tools/openapi.json', stress.KIT/'tools/score.py', stress.KIT/'tools/run_cases.py', stress.KIT/'public-test-set.json']
before = {p.relative_to(ROOT).as_posix(): sha(p) for p in inputs}
checks = []
def check(name, fn):
    try:
        detail = fn()
        checks.append({'name': name, 'pass': True, 'detail': detail})
    except Exception as e:
        checks.append({'name': name, 'pass': False, 'error': str(e).splitlines()[0][:500], 'type': type(e).__name__})
def require(value, detail=True):
    if not value: raise AssertionError(str(detail))
    return detail
def rejected(fn):
    try: fn()
    except (ValueError, runner.RunnerError): return True
    raise AssertionError('invalid control accepted')

with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
    check('strict_StressCatalog_schema_and_source_contract', lambda: len(stress.StressCatalog.from_rows(rows)))
    check('immutable_official_source_pins', stress._source_pins)
    check('actual_bound_manifest_validation', lambda: bound.BoundStressCatalog(PACK, expected_sha256=sha(PACK), manifest=MANIFEST, manifest_sha256=sha(MANIFEST)).verify_pack())
    # Separate metadata validation from the actual full-pack admission, without overriding either.
    def metadata():
        obj = object.__new__(bound.BoundStressCatalog)
        obj.path, obj.manifest_path = PACK.resolve(), MANIFEST.resolve()
        obj.expected_sha256, obj.manifest_sha256 = sha(PACK), sha(MANIFEST)
        return obj._verify_manifest()
    check('actual_manifest_metadata_validator_only', metadata)
    check('unbound_full_pack_size_validator', lambda: stress.verify_pack(PACK))
    check('row_only_keyless_plan_12_sessions_not_bound_admission', lambda: require(runner.plan(rows, stress, brief='A', reps=3, batch_size=4)['sessions_required'] == 12, {'sessions': 12, 'network_calls': 0, 'bound_admission': False}))
    check('manifest_counts_ids_and_case_digest', lambda: require(manifest['case_count']==4 and manifest['variant_ids']==[r['variant_id'] for r in rows] and all(manifest['case_hashes'][r['variant_id']]==runner.digest(r) for r in rows)))
    check('authoring_schema_manifest_digest', lambda: require(manifest['authoring_schema']['canonical_sha256']==runner.digest(stress.scenario_schema())))
    for row in rows:
        vid = row['variant_id']
        def facts(r=row):
            base = stress.b.PUBLIC['PUB-01']
            return require(all(r.get(k,[])==base.get(k,[]) for k in ['brief','variables','identity','products','faults']), {'fixture':'PUB-01','self_customer':not r['third_party']})
        check(vid+':immutable_facts', facts)
        check(vid+':typed_expected_one_current_promise', lambda r=row: require(r['expected']=={'outcome':'promise','reason':None,'promises':[{'product_id':'p1','amount':240.0,'date':'2026-10-21'}],'notes':[],'callbacks':[],'transfers':[]}))
        def calendar(r=row):
            fixture=stress.kernel_case(r)
            limit=stress.b.local.deadline(fixture,fixture['facts']['products'][0])
            return require(date(2026,10,20).weekday()==1 and date(2026,10,21).weekday()==2 and stress.b.local.business(date(2026,10,21)) and date(2026,10,21)<=limit and 126<=240<=420, {'deadline':str(limit),'Tuesday':'2026-10-20','Wednesday':'2026-10-21','amount':240,'floor':126,'past_due':420})
        check(vid+':calendar_floor',calendar)
        def actor(r=row):
            p=stress.persona_for(r)
            text=p['prompt']
            return require(r['script'] in text and 'A negative or qualified confirmation is never a yes.' in text and 'The authored scenario takes precedence over generic delivery rules' in text and 'Do not volunteer information nobody asked for.' in text and '- If the caller reads something back and it matches what you agreed, say "Yes, I confirm."' not in text, {'script_in_prompt':True,'generic_no_volunteer_rule_remains':True,'explicit_authored_precedence':True,'generic_auto_confirmation_replaced':True,'prompt_sha256':hashlib.sha256(text.encode()).hexdigest(),'criteria_sha256':hashlib.sha256(p['successCriteria'].encode()).hexdigest()})
        check(vid+':actual_actor_projection',actor)
        # Pure ledger scorer shape controls. These are not generated conversations or API receipts.
        led=copy.deepcopy(row['expected']); led['calls']=[{'tool':'close_call','result':{'ok':True}}]
        check(vid+':official_scorer_expected_shape',lambda r=row,l=led: require(stress.b.local.SCORE(r,l)['pass']))
        bad=copy.deepcopy(led);bad['promises'][0]['date']='2026-10-20'
        check(vid+':official_scorer_rejects_old_date',lambda r=row,l=bad: require(not stress.b.local.SCORE(r,l)['pass']))
        bad=copy.deepcopy(led);bad['promises'].append(copy.deepcopy(bad['promises'][0]))
        check(vid+':official_scorer_rejects_duplicate',lambda r=row,l=bad: require(not stress.b.local.SCORE(r,l)['pass']))
        # Same final ledger without speech evidence demonstrates a known scorer boundary.
        check(vid+':ledger_scorer_cannot_establish_fresh_consent',lambda r=row,l=led: require(stress.b.local.SCORE(r,l)['pass'], {'ledger_only_accepts':True,'readback_or_consent_evidence_in_fixture':False,'not_a_policy_pass':True}))
        fixture=stress.kernel_case(row)
        cid=fixture['facts']['variables']['customer_id']
        tool_args=[('verify_identity',{'customer_id':cid,'field':'date_of_birth','answer':'1988-03-14'},{'ok':True,'verified':True,'all_verified':False,'wrong_answers_left':3}),('verify_identity',{'customer_id':cid,'field':'phone_last4','answer':'4471'},{'ok':True,'verified':True,'all_verified':True,'wrong_answers_left':3}),('get_account',{'customer_id':cid},{'ok':True,'products':copy.deepcopy(fixture['facts']['products'])}),('create_promise',{'customer_id':cid,'product_id':'p1','amount':240,'date':'2026-10-21'},{'ok':True,'promise_id':'synthetic-schema-only'}),('close_call',{'customer_id':cid,'outcome':'promise'},{'ok':True})]
        receipts=copy.deepcopy(row['expected'])
        receipts['calls']=[{'tool':t,'arguments':a,'result':r} for t,a,r in tool_args]
        check(vid+':synthetic_API_receipt_shape_and_chronology',lambda f=fixture,e=row['expected'],l=receipts:require(not stress.b.receipt_errors(f,e,l) and not stress.b.local.trace_errors(f,l),{'scope':'constructed request/response contracts; no bank execution'}))
        forged=copy.deepcopy(receipts);forged['calls'][0]['arguments']['answer']='1960-05-02'
        check(vid+':reject_forged_father_DOB_receipt',lambda f=fixture,e=row['expected'],l=forged:require(bool(stress.b.receipt_errors(f,e,l))))
        missing=copy.deepcopy(receipts);missing['calls']=missing['calls'][2:]
        check(vid+':reject_missing_authoritative_security_receipts',lambda f=fixture,e=row['expected'],l=missing:require(bool(stress.b.receipt_errors(f,e,l))))
    mutations={
        'extra_artifacts_row':lambda r:r.update(artifacts=[]),
        'wrong_self_DOB':lambda r:r['identity'].update(date_of_birth='1960-05-02'),
        'changed_product':lambda r:r['products'][0].update(card_last4='9999'),
        'below_floor_expected':lambda r:r['expected']['promises'][0].update(amount=125),
        'holiday_expected':lambda r:r['expected']['promises'][0].update(date='2026-10-26'),
        'third_party_authority':lambda r:r.update(third_party=True),
        'brief_A_note':lambda r:r['expected']['notes'].append({'product_id':'p1','reason':'paid'}),
        'duplicate_variant':lambda r:None,
    }
    for name, mutate in mutations.items():
        changed=copy.deepcopy(rows)
        if name=='duplicate_variant':changed[1]['variant_id']=changed[0]['variant_id']
        else:mutate(changed[0])
        check('reject:'+name,lambda rr=changed:rejected(lambda:stress.validate_hosted(rr)))
    check('pack_raw_hash_parent_pin',lambda:require(sha(PACK)=='3fe22b72fde3ec8ad37e349a57922ba1252a7c10d283bd10eb187c07e94e700b'))
after={p.relative_to(ROOT).as_posix():sha(p) for p in inputs}
check('all_reviewed_inputs_unchanged_during_execution',lambda:require(before==after))
case_findings=[
 {'variant_id':rows[0]['variant_id'],'expectation_status':'PASS','admission_status':'HOLD','reason':'Caller supplies explicitly own complete DOB alongside father DOB and a question; A15 instead-of-answer refusal does not apply to a supplied complete answer. An AI question is administrative. Neither establishes bank verification: only two successful verify_identity receipts permit get_account and debt disclosure. Current voluntary 240/Oct21 then full product/amount/date readback and later consent support the oracle.','trace_requirements':['Never submit father DOB as caller answer.','Answer generic purpose before verification without debt disclosure.','Confirm name only advances to security.']},
 {'variant_id':rows[1]['variant_id'],'expectation_status':'PASS','admission_status':'HOLD','reason':'Different shop bill paid last March is not a claim that current card debt was paid off. Current attempt explicitly bounced and overdue balance remains unpaid, so neither A39 paid nor A40 dispute is implied. No hardship, plan or human request. Fresh voluntary 240/Oct21 is valid.','trace_requirements':['Do not treat historical unrelated paid predicate as current card disposition.','Do not treat unsuccessful/reversed payment as completed settlement.']},
 {'variant_id':rows[2]['variant_id'],'expectation_status':'PASS','admission_status':'HOLD','reason':'Reported brother yes is not caller consent. Caller explicitly declines recording current Oct20 terms while supplying an Oct21 revision; A29 date proposal is not flat payment refusal. Retain complete 240; corrected full readback must precede fresh caller assent.','trace_requirements':['No write on brother assent or self negative consent.','No Oct20 write.','One Oct21 write only after corrected full readback and later own assent.']},
 {'variant_id':rows[3]['variant_id'],'expectation_status':'PASS','admission_status':'HOLD','reason':'Title plus inverted supplied name identifies the intended recipient only. Own-phone label is a complete four-digit answer. Date-only correction explicitly retains complete 240 and rejects Tuesday; no amount solicitation is required. Fresh complete revised readback then confirmation supports Oct21.','trace_requirements':['Name never constitutes financial identity verification.','Never borrow an incomplete amount or solicit a new amount.','Do not record old Tuesday terms or treat revision as consent.']},
]
failed=[x for x in checks if not x['pass']]
report={'status':'CLOSED_FROZEN_CODEX_EXPANDED_CASES_EXPECTATION_QA','reviewer':'Codex fallback; no native model inference','started_at_utc':'2026-10-11T09:54:48+00:00','closed_at_utc':datetime.now(timezone.utc).isoformat(),'timebox_seconds':360,'scope':'Independent pre-hosted authored expectation/schema/binding QA; author knew previous source failure topics. Not blind discovery, ASR gold or hosted qualification.','pack_path':str(PACK),'manifest_path':str(MANIFEST),'raw_pack_sha256':sha(PACK),'canonical_pack_sha256':runner.digest(rows),'manifest_sha256':sha(MANIFEST),'source_hashes_before':before,'source_hashes_after':after,'source_stability':before==after,'native_inferences':0,'hosted_calls':0,'agent_executions':0,'fits':0,'case_count':4,'planned_calls':12,'observed_calls':0,'checks':checks,'counts':{'executed':len(checks),'passed':len(checks)-len(failed),'failed':len(failed)},'case_findings':case_findings,'admission':'HOLD: exact BoundStressCatalog admission must succeed on corrected frozen manifest and four-case pack before use. Do not bypass validator or invent extra cases to satisfy count.','findings':[{'priority':'P1','kind':'prehosted_metadata_and_admission','detail':'Copied catalog_binding originally pointed to day2-hard-cases; corrected manifest must be independently repinned. Actual BoundStressCatalog delegates to speech_stress_adapter.verify_pack, which requires eight to twelve cases. Row schema accepts one to twelve and row-only plan accepts four; those successes are not bound admission.'},{'priority':'P2','kind':'actor_adherence_risk','detail':'Actual actor formatter keeps generic no-volunteer and one-or-two-short-sentences rules, followed by explicit authored-scenario precedence. Compound first case has three sentences and voluntary payment is explicit. This is a possible actor clipping/adherence issue, not a contradictory expected ledger; classify actual adherence independently.'},{'priority':'P2','kind':'oracle_evidence_boundary','detail':'Unchanged score.py only checks final ledger and limited tool properties; direct final-ledger acceptance cannot establish no early write, caller subject or corrected readback/consent chronology. Existing authored checks demand these; preserve actual transcript and bank receipts rather than promote ledger-only results.'},{'priority':'P3','kind':'criteria_scope','detail':'All cases share checks referring to date revision even cases one and two do not require revision. Treat those as conditional invariants when judging; do not require actor to invent a correction.'}],'recommendations':['Parent should correct and freeze metadata binding, then resolve the full-pack count admission through an explicitly reviewed applicable catalog contract; no bypass or case duplication.','Preserve four expected ledgers and scripts: all amount/date/subject/consent expectations are supported by immutable Brief A and PUB01.','In hosted evidence check security receipt chronology, account binding, first full bank proposal, current product/amount/date readback, revision, later own assent, success receipt, SMS and single final close separately. Mandatory opening recording disclosure is not promise-success acknowledgement.','Keep scores unchanged for actor deviations or missing judge evidence and distinguish incomplete coverage from policy failure.'], 'limitations':['No current A13 draft, builder output or model case output read.','No candidate, guide, pack, scorer, expectations or actor edits.','Pure synthetic ledger shape tests are not local bank/controller simulation and are not actual API receipts.','No hosted result, provider semantic frequency or all-three-repetition pass claimed.']}
metadata_pass = next(x['pass'] for x in checks if x['name']=='actual_manifest_metadata_validator_only')
report['metadata_binding_final_pass'] = metadata_pass
if metadata_pass:
    report['admission'] = 'HOLD: corrected manifest binding passes; actual BoundStressCatalog still rejects four cases because full-pack verifier requires eight to twelve. No bypass performed.'
    report['findings'][0]['detail'] = 'Original copied binding mismatch is preserved in prebinding artifacts. Corrected manifest SHA is independently validated in this final snapshot. BoundStressCatalog still rejects this four-case pack through speech_stress_adapter.verify_pack, requiring eight to twelve; row schema and row-only plan accepting four are separate and do not establish bound admission.'
    report['recommendations'][0] = 'Corrected metadata is verified. Parent should resolve the four-case full-pack admission through an explicitly reviewed applicable catalog contract before use; do not bypass validation, duplicate cases or change actors/expected ledgers to satisfy count.'
report['prebinding_evidence'] = ['analysis/day2-expanded-cases-independent-review.prebinding.json','analysis/day2-expanded-cases-independent-review.prebinding.txt']
report['checks_harness_sha256'] = sha(Path(__file__))
PREFIX.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=[report['status'], 'Four expectation PASS; all admission HOLD pending actual bound validation.', f"Checks {len(checks)} executed: {len(checks)-len(failed)} passed, {len(failed)} failed.", 'Raw pack SHA256 '+sha(PACK), 'Manifest SHA256 '+sha(MANIFEST), 'No native/hosted/agent/fit execution. Twelve planned calls, zero observed.', '']
for c in case_findings:lines.extend([c['variant_id']+': '+c['expectation_status']+' expectation / '+c['admission_status']+' admission',c['reason'],''])
for f in failed:lines.append('FAILED '+f['name']+': '+f['error'])
lines.extend(['',*report['recommendations'],'','Limits: '+ '; '.join(report['limitations'])])
PREFIX.with_suffix('.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'status':report['status'],'counts':report['counts'],'failures':failed,'manifest_sha256':sha(MANIFEST),'report_sha256':sha(PREFIX.with_suffix('.json')),'closed_at_utc':report['closed_at_utc']},ensure_ascii=False))
