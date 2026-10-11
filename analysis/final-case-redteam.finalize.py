"""Consolidate bounded native evidence, independent source audit and local mock audit."""
import ast, datetime, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'analysis/final-case-redteam'
read=lambda suffix:json.loads(Path(str(BASE)+suffix).read_text(encoding='utf-8'))
source=read('.source.json');native=read('.native.json');mock=read('.mock.json');flow=read('.flow.json')
assert len(source['attacks'])==34
assert native['attempts']==1 and native['actual_opus_inference_verified']
assert set(native['model_usage'])=={'claude-opus-5-5'}
assert all(m=='claude-opus-5-5' for m in native['assistant_response_models'])
assert not mock['functional_failures'] and not mock['negative_failures']
assert mock['fixture_snapshot_exact'] and mock['real_delay_check']['body_exact']
assert mock['real_delay_check']['wall_ms']>=12000
for c in source['attacks']:
 for ref in c['source_refs']:
  p,n=ref.rsplit(':L',1);assert (ROOT/p).is_file() and 0<int(n)<=len((ROOT/p).read_text(encoding='utf-8-sig').splitlines())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
builder=ROOT/'competition/builder.py';ast.parse(builder.read_bytes())
adjudications=[
 {'claim':'Opus A07 requires 00.00 opening first','decision':'Refined: preferred opening, not exclusive pass/fail obligation. Meeting explicitly accepts due-date-first opening; totalDebt field choice is mandatory.','source_case':'FC-21'},
 {'claim':'Opus gap says past-due amount field unspecified','decision':'Rejected: analysis4.10 explicitly requires total debt after due date. Exact sentence remains flexible.','source_case':'FC-22'},
 {'claim':'Opus gap treats email lookup failure after reading as routing conflict','decision':'Rejected: analysis6/8.3 explicitly makes email service failure an agent transfer even after successful debt reading.','source_case':'FC-15/FC-29'},
 {'claim':'Opus A11 broadly says any404 goes to agent','decision':'Refined: cards.list FB_IVR_CHANNEL_102 is no-eligible-card main-menu outcome; missing PDF and other service failures go to agent.','source_case':'FC-29'},
 {'claim':'Opus A09 payment timing phrase always implies payment-channel transfer','decision':'Refined: asking only the due date is explicitly supported. Only clear pay/how/where or dispute intent triggers immediate agent; classify whole utterance.','source_case':'FC-22/FC-33'},
 {'claim':'Opus generic fix blocks calendar arithmetic globally','decision':'Refined: date comparisons against supplied Istanbul now are required. Forbid fabricating/shifting bank-issued due or preview dates, not legitimate calendar comparison.','source_case':'FC-22/FC-23'},
 {'claim':'Opus A10 annual-limit scenario omits clear known-used no-write condition','decision':'Refined: established used right must not be offered or changed again. No eligibility endpoint exists; conservative unknown-history behavior is a source gap, not an invented service.','source_case':'FC-03/FC-25'},
 {'claim':'Opus suggests instruction-pattern detector for service productName','decision':'Recommendation qualified: security obligation is settled, specific detector algorithm is not mandated. Treat free text as data; use safe display fallback without relying on keyword detection alone.','source_case':'FC-07'}
]
pdf=ROOT/'final-case-20261011/Build the Builder - Final Case/statement-debt-call-flow.pdf'
report={'status':'SOURCE_AND_LOCAL_MOCK_AUDIT_COMPLETE_CANDIDATE_PENDING','finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'candidate_reviewed':False,'candidate_json_edited':False,'source_audit_completed_utc':source['created_utc'],
 'source_attack_count':34,'resolved_conflict_count':len(source['source_conflicts']),'documented_gap_count':len(source['specification_gaps']),
 'generic_builder_recommendations':source['generic_builder_recommendations'],
 'native_evidence':{k:native[k] for k in ('status','attempts','timeout_seconds','seconds','actual_opus_inference_verified','assistant_response_models','model_usage','tool_calls','raw_stdout_saved','thinking_saved','auth_commands')},
 'native_review_adjudication':adjudications,
 'mock_evidence':{'fixture_checks':len(mock['fixture_checks']),'fixture_mismatches':0,'lookup_error_and_equivalence_checks':len(mock['negative_checks']),
  'lookup_error_and_equivalence_failures':0,'schema_failures':len(mock['schema_failures']),'exact_embedded_fixtures':mock['fixture_snapshot_exact'],
  'real_delay_check':mock['real_delay_check'],'source_stability':mock['source_stability'],'public_origin_verified':False,'openapi_origin':mock['openapi_origin'],
  'mock_bank_authority_warning':'Local PDF service intentionally accepts any address/card/date for fixture lookup by customer. Correct contract behavior; agent must enforce registered recipient, exact owned card, issued date and scoped consent.'},
 'flow_pdf_review':{'path':pdf.relative_to(ROOT).as_posix(),'sha256':sha(pdf),'pages':flow['pages'],'text_extracted':True,'visually_checked':True,
  'observations':['Second-factor box is obsolete by bank kickoff confirmation.','Drawing lacks full-number disambiguation after last-six collision.','Drawing labels USD/EUR but latest policy requires GBP and full currency names.','Drawing offers email before contact lookup; consolidated analysis requires lookup before eligible offer.','Debt branch drawing omits another-card question before offer; Oct10 meeting corrects this.']},
 'builder_current_snapshot':{'path':'competition/builder.py','sha256':sha(builder),'syntax':'pass','merge_markers_present':False,
  'qualification':'Earlier source snapshot had markers and failed parsing; concurrently resolved by owner. This audit made no builder changes.'},
 'handoff_actions':['Parent must deploy/verify public Worker and bind actual origin in HOSTCONFIG before builder execution; source OpenAPI still deliberately contains .invalid placeholder.',
                    'Repair generic builder behavior and regenerate, never edit generated candidate JSON.',
                    'Later supplied automatic candidate path must be byte-pinned and audited for executable tool paths, consent state, source policy and mock origin. No candidate failure/pass is asserted yet.'],
 'artifacts':{suffix:Path(str(BASE)+suffix).relative_to(ROOT).as_posix() for suffix in ('.source.json','.source.txt','.native.json','.mock.json','.mock.txt','.flow.json')},
 'limits':['All model content is proposed source review, independently adjudicated here; no candidate/platform/ASR outcome implied.',
           'Only one native exact Opus call; no rate-limit substitution or repeated attempt. CLI handled existing OAuth internally; no authentication commands or credential-file reads.',
           'All writes stayed in analysis/final-case-redteam.* or integrations/opus-redteam/runtime/final-case-20261011/**. No Git/Freya/publication/auth or candidate edits.']}
Path(str(BASE)+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
summary=['Final-case redteam handoff','Status: source + local mock complete; candidate audit pending path.',
 'Source audit completed '+source['created_utc']+' (within ten minutes of 18:42:20 UTC start).',
 '34 independent attacks; 9 resolved source conflicts; 7 gaps. Full contracts: analysis/final-case-redteam.source.{json,txt}.',
 'One verified native claude-opus-5-5 call, 126.406 seconds (300 second bound), tools empty, no raw stdout/thinking saved.',
 'Actual usage: '+json.dumps(native['model_usage']),
 'Local frozen mock: 617 exact status/body pairs, 505 lookup/error/equivalence checks; zero mismatches, zero response-schema failures.',
 'Real delayed answer: 12011ms, HTTP200 and exact fixture JSON. Public deployment/candidate wiring not verified.',
 'Current builder parses; earlier concurrently resolved markers were not edited by this audit.',
 '\nPriority generic builder fixes']
summary.extend(r['priority']+' '+r['target']+': '+r['fix'] for r in source['generic_builder_recommendations'])
summary.append('\nMaterial integration gaps: annual entitlement flag missing; hidden last-six digits; third-party IVR-login versus main-menu target; final timeout unspecified; PDF currency choice; future foreign totals; transferred-currency line wording.')
summary.append('\nParent actions: deploy and verify public Worker; bind actual origin in HOSTCONFIG (OpenAPI placeholder is .invalid); regenerate through builder. No candidate JSON edits.')
summary.append('\nOpus review qualifications')
summary.extend(a['claim']+' -> '+a['decision'] for a in adjudications)
Path(str(BASE)+'.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
print(json.dumps({'status':report['status'],'source_attacks':34,'native_model':'claude-opus-5-5','native_attempts':1,'mock_fixture_checks':617,'mock_other_checks':505,'candidate_reviewed':False}))
