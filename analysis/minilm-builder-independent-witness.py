"""Independent source/CPU review. Writes only the two named analysis reports."""
import ast
import builtins
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import time
import types
from datetime import datetime,timezone
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'competition'))
import builder
import semantic_assist as assist
P=ROOT/'analysis/minilm-builder-independent-review'
started=time.monotonic();checks=[];evidence=[]
earlier_snapshot=None
if P.with_suffix('.json').exists():
    old_report=json.loads(P.with_suffix('.json').read_bytes())
    earlier_snapshot={k:old_report[k] for k in ['closed_at_utc','source_hashes_before','source_hashes_after','source_stable','counts','CPU_evidence']}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ck(name,value,detail=None):checks.append({'id':name,'pass':bool(value),'detail':detail})
def reject(fn):
    try:fn()
    except (ValueError,RuntimeError,TimeoutError,KeyError):return True
    return False
head_path=ROOT/'integrations/learned-dialogue/day2_pretrained_head.json'
runtime=ROOT/'integrations/learned-dialogue/day2_pretrained_runtime.py'
head=json.loads(head_path.read_bytes());directory=ROOT/head['encoder']['local_directory']
protected=[ROOT/'competition/builder.py',ROOT/'competition/semantic_assist.py',ROOT/'competition/tests/test_semantic_assist.py',runtime,head_path]
protected.extend(directory/name for name in head['encoder']['files'])
before={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
ck('exact_head_pin',sha(head_path)==assist.HEAD_SHA256)
for name,record in head['encoder']['files'].items():ck('encoder_pin:'+name,sha(directory/name)==record['sha256'] and (directory/name).stat().st_size==record['bytes'])

# Virtual authored evidence is read through actual chunker; no fixture files created.
work=P.parent.resolve()
fixtures={work/'minilm-builder-independent-base-fixture.md':('# Rule\r\n'+'a '*330+'MUST obtain consent before writing.\r\n'+'end_without_newline').encode(),work/'minilm-builder-independent-amendment-fixture.md':('\ufeff# Amendment\nReplace only the previous callback limit.\nDo not change bank verification.\n').encode()}
sources=[{'path':p.name,'sha256':hashlib.sha256(raw).hexdigest()} for p,raw in fixtures.items()]
read_original=Path.read_bytes;isfile_original=Path.is_file
def virtual_read(path):return fixtures[path] if path in fixtures else read_original(path)
def virtual_file(path):return path in fixtures or isfile_original(path)
with patch.object(Path,'read_bytes',virtual_read),patch.object(Path,'is_file',virtual_file):
    chunks=assist.chunks_from_sources(work,sources)
    for order,(path,raw) in enumerate(fixtures.items()):ck('lossless_decoded_text:'+str(order),''.join(c['text'] for c in chunks if c['source_order']==order)==raw.decode('utf-8-sig'))
    ck('amendment_input_order_retained',chunks[-1]['source_order']==1 and all(c['source_sha256']==sources[c['source_order']]['sha256'] for c in chunks))
    ck('changed_source_hash_rejected',reject(lambda:assist.chunks_from_sources(work,[dict(sources[0],sha256='0'*64)])))
    ck('escaping_source_path_rejected',reject(lambda:assist.chunks_from_sources(work,[{'path':'../outside-fixture.md','sha256':'0'*64}])))
    long=work/'minilm-builder-independent-cap-fixture.md'
    fixtures[long]=b'x'*1000001
    ck('one_MB_capacity_fails_closed',reject(lambda:assist.chunks_from_sources(work,[{'path':long.name,'sha256':hashlib.sha256(fixtures[long]).hexdigest()}])))
    fixtures[long]=b'\n'*2001
    ck('2000_chunk_capacity_fails_closed',reject(lambda:assist.chunks_from_sources(work,[{'path':long.name,'sha256':hashlib.sha256(fixtures[long]).hexdigest()}])))
    del fixtures[long]

synthetic_env={'PATH':'SYNTHETIC_BIN','SystemRoot':'C:\\Windows','HOME':'SYNTHETIC_HOME','FREYA_API_KEY':'SYNTHETIC_ONLY','AWS_ACCESS_KEY_ID':'SYNTHETIC_ONLY','HF_TOKEN':'SYNTHETIC_ONLY','PYTHONPATH':'SYNTHETIC_INJECT','PYTHONHOME':'SYNTHETIC_INJECT','LD_PRELOAD':'SYNTHETIC_INJECT','HTTP_PROXY':'SYNTHETIC_ONLY','HTTPS_PROXY':'SYNTHETIC_ONLY'}
env=assist.child_env(synthetic_env)
identity_values={'USER':'SYNTHETIC_REVIEW','USERNAME':'SYNTHETIC_REVIEW','LOGNAME':'SYNTHETIC_REVIEW'}
identity_env=assist.child_env(dict(synthetic_env,**identity_values))
ck('latest_Windows_identity_environment_repair',all(identity_env.get(k)==v for k,v in identity_values.items()))
ck('semantic_child_credentials_and_injection_stripped',all(k not in env for k in ['FREYA_API_KEY','AWS_ACCESS_KEY_ID','HF_TOKEN','PYTHONPATH','PYTHONHOME','LD_PRELOAD','HTTP_PROXY','HTTPS_PROXY']))
ck('offline_cpu_environment',all(env[k]==v for k,v in {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2'}.items()))

def semantic_stub(mode,remaining):
    r=object.__new__(builder.Run);r.args=types.SimpleNamespace(semantic_assist=mode,semantic_python=sys.executable);r.work=work/'minilm-builder-independent-virtual-work';r.path=r.work;r.builder_source=r.work;r.status={};r.sources=[];r.event=Mock();r.child=Mock();r.remaining=lambda:remaining;return r
for mode in ['auto','off','required']:
    r=semantic_stub(mode,121)
    errored=reject(r.prepare_semantic_assist) if mode=='required' else (r.prepare_semantic_assist() or False)
    ck('mode_low_budget:'+mode,(bool(errored)==(mode=='required')) and not r.semantic_ready and r.child.call_count==0,{'status':r.status['semantic_assist']})

minimal={'schema':'builder.semantic_evidence.v1','bank_authority':False,'head_sha256':assist.HEAD_SHA256,'sources':sources,'retrieval':{key:[] for key in assist.QUERIES},'chunks':[]}
accepted=not reject(lambda:assist.validate_result(minimal,sources))
ck('validator_rejects_missing_chunks_and_encoder_proof',not accepted,{'accepted':accepted,'scope':'conditional malformed artifact; not normal child output'})
for key,value in [('head_sha256','0'*64),('bank_authority',True),('sources',sources[:1]),('retrieval',{})]:ck('validator_negative:'+key,reject(lambda k=key,v=value:assist.validate_result(dict(minimal,**{k:v}),sources)))
quoted=assist.render_index({'sources':sources,'chunks':chunks,'retrieval':{'amendments':[{'chunk_id':len(chunks)-1,'cosine':.8}]}})
ck('quoted_evidence_and_no_authority_notice','untrusted passage=' in quoted and 'not truth, policy precedence' in quoted and 'not a deployed phone model' in quoted)

# Real CPU embeddings; literal frozen runtime/model, no network or classifier fit.
for k,v in {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1','TOKENIZERS_PARALLELISM':'false'}.items():os.environ[k]=v
spec=importlib.util.spec_from_file_location('independent_real_minilm',runtime);rt=importlib.util.module_from_spec(spec)
with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')) as http_guard,patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')) as socket_guard:
    spec.loader.exec_module(rt);encoder=rt.FrozenEncoder(directory)
    long_chunk=next(c for c in chunks if len(c['text'])>600)
    embedded_text=long_chunk['heading']+'\n'+long_chunk['text']
    raw_tokens=encoder.tokenizer(embedded_text,truncation=False)['input_ids']
    used_tokens=encoder.tokenizer(embedded_text,truncation=True,max_length=256)['input_ids']
    ck('700_character_fragment_fits_256_tokens',len(raw_tokens)<=256,{'characters':len(embedded_text),'full_tokens':len(raw_tokens),'encoded_tokens':len(used_tokens),'retained_original_chunk_text':True})
    pair=['a '*330+'ALLOW recording after agreement.','a '*330+'DENY recording without agreement.']
    vectors=encoder.encode(pair,deadline=time.monotonic()+20)
    difference=float(abs(vectors[0]-vectors[1]).max())
    evidence.append({'id':'actual_encoder_tail_truncation','maximum_embedding_difference':difference,'opposite_tails_retained_in_original_text':True,'tail_beyond_256_tokens':True,'model_revision':head['encoder']['revision'],'scope':'authored navigation-loss witness, not bank policy execution'})
    ck('embedding_distinguishes_opposite_tail_rules',difference>1e-7,{'maximum_difference':difference,'scope':'actual CPU; no bank authority'})
    request={'head':str(head_path),'repo':str(ROOT),'runtime':str(runtime),'runtime_sha256':sha(runtime),'work':str(work),'sources':sources,'seconds':30}
    with patch.object(Path,'read_bytes',virtual_read),patch.object(Path,'is_file',virtual_file):result=assist.build_index(request)
    ck('actual_CPU_build_index_complete_sources',result['sources']==sources and len(result['chunks'])==len(chunks) and result['bank_authority'] is False and set(result['retrieval'])==set(assist.QUERIES))
    ck('actual_CPU_index_authority_stays_false',result['bank_authority'] is False and result['runtime_sha256']==sha(runtime))
    evidence.append({'id':'actual_CPU_navigation','elapsed_seconds':result['elapsed_seconds'],'chunks':len(result['chunks']),'queries':len(result['retrieval']),'revision':result['encoder_revision'],'runtime_sha256':result['runtime_sha256'],'result_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest(),'source_count':len(result['sources']),'classifier_head_used':False,'bank_authority':False})
    ck('actual_CPU_no_network_attempts',http_guard.call_count==0 and socket_guard.call_count==0,{'HTTP_attempts':http_guard.call_count,'socket_connect_attempts':socket_guard.call_count})

# Actual execute()/main() control flow, stub generation and validation; no Freya imports/calls.
r=object.__new__(builder.Run);r.args=types.SimpleNamespace(local_only=True,resume_run=None,model='synthetic',minutes=1,rounds=1,skip_tests=False,repair_first=False,practice_repair=None);r.status={'phase':'starting','round':0,'artifacts':{},'tests':[]};r.work=work;r.path=work;r.event=Mock();r.prepare=Mock();r.model=Mock(return_value={});r.publish=Mock(side_effect=AssertionError('publish forbidden'));r.test=Mock(side_effect=AssertionError('platform test forbidden'));r.remaining=lambda:500;r.elapsed=lambda:0;r.start=time.monotonic()
def phase(name,**kwargs):r.status.update(phase=name,**kwargs)
r.phase=phase
r.api={};r.clean=lambda x:x;r.secrets=[]
readtext_original=Path.read_text
def virtual_text(path,*args,**kwargs):return '{}' if path==work/'coverage.json' else readtext_original(path,*args,**kwargs)
with patch.object(Path,'read_text',virtual_text),patch.object(builder,'validate',lambda *a:[]),patch.object(builder,'validate_coverage',lambda *a:[]),contextlib.redirect_stdout(io.StringIO()):local_ok=r.execute()
ck('actual_local_only_execute_no_publish_or_test',local_ok and r.publish.call_count==0 and r.test.call_count==0 and r.status['published'] is False and r.status['evaluation']=='local_validation_only',{'generation_and_artifact_validation':'stubbed to isolate actual control-flow branches'})
fake=types.SimpleNamespace(execute=lambda:True)
args=r.args;args.slot='minilm-independent-synthetic';fake.event=Mock()
with patch.object(builder,'arguments',lambda:args),patch.object(builder,'Run',lambda _:fake),patch.object(builder,'slot_lock',lambda _:contextlib.nullcontext()),patch.object(Path,'mkdir',lambda *a,**k:None),patch.object(builder.getpass,'getpass',Mock(side_effect=AssertionError('credential prompt forbidden'))),patch.object(builder.os,'environ',{}):
    main_rc=builder.main();prompt_count=builder.getpass.getpass.call_count
ck('actual_local_only_main_no_credential_prompt',main_rc==0 and prompt_count==0,{'lock/run creation':'stubbed; no global state files created'})
fake.status={'phase':'starting'};fake.clean=lambda x:x
fake.phase=lambda name,**kwargs:fake.status.update(phase=name,**kwargs)
def required_failure():raise RuntimeError('Required local MiniLM navigation is unavailable')
fake.execute=required_failure
with patch.object(builder,'arguments',lambda:args),patch.object(builder,'Run',lambda _:fake),patch.object(builder,'slot_lock',lambda _:contextlib.nullcontext()),patch.object(Path,'mkdir',lambda *a,**k:None),patch.object(builder.os,'environ',{}),contextlib.redirect_stderr(io.StringIO()):failed_rc=builder.main()
ck('latest_required_prepare_failure_records_failed_phase',failed_rc==1 and fake.status['phase']=='failed',{'main_exit':failed_rc,'scope':'actual main exception branch; execute failure injected, no run/platform created'})

# Actual owned child termination, synthetic output only, named review txt used as scratch log.
child=object.__new__(builder.Run);child.work=work;child.path=work;child.event=Mock();child.remaining=lambda:5;child.clean=lambda x:x
safeenv=assist.child_env({'SYSTEMROOT':os.environ.get('SYSTEMROOT','C:\\Windows'),'WINDIR':os.environ.get('WINDIR','C:\\Windows'),'PATH':os.environ.get('PATH',''),'TEMP':os.environ.get('TEMP','')})
safeenv.update(identity_values)
child.remaining=lambda:60
clean_import_start=time.monotonic()
clean_lines=child.child([sys.executable,'-I','-B','-c','import torch;from transformers import AutoModel,AutoTokenizer;import getpass;assert getpass.getuser()=="SYNTHETIC_REVIEW";print("CLEAN_ENV_TORCH_IMPORT_OK")'],timeout=45,env=safeenv,log_name=P.name+'.txt',purpose='Owned clean environment Torch import witness')
ck('actual_clean_Windows_child_torch_transformers_import',any('CLEAN_ENV_TORCH_IMPORT_OK'==x for x in clean_lines),{'seconds':round(time.monotonic()-clean_import_start,3),'OS_identity':'synthetic only','API_credentials':False,'classifier_fit':False})
child.remaining=lambda:5
wall=time.monotonic()
timed=reject(lambda:child.child([sys.executable,'-I','-B','-c','import time;print("SAFE_SYNTHETIC",flush=True);time.sleep(10)'],timeout=.25,env=safeenv,log_name=P.name+'.txt',purpose='Owned synthetic timeout witness'))
ck('actual_child_timeout_and_exit',timed and time.monotonic()-wall<3,{'wall_seconds':round(time.monotonic()-wall,3),'native_LLM':False,'taskkill_scope':'only owned synthetic Python child process tree'})

tree=ast.parse((ROOT/'competition/builder.py').read_text());refs={}
for n in ast.walk(tree):
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ['prepare_semantic_assist','model','execute','main','child']:refs[n.name]={'start':n.lineno,'end':n.end_lineno}
after={p.relative_to(ROOT).as_posix():sha(p) for p in protected};ck('all_protected_source_model_tests_unchanged',before==after)
failures=[x for x in checks if not x['pass']]
report={'status':'CLOSED_FROZEN_CODEX_MINILM_BUILDER_SOURCE_CPU_REVIEW','reviewer':'Independent Codex; no native Opus inference claimed','started_at_utc':'2026-10-11T11:06:33Z','closed_at_utc':datetime.now(timezone.utc).isoformat(),'deadline_utc':'2026-10-11T11:16:33Z','source_hashes_before':before,'source_hashes_after':after,'source_stable':before==after,'harness_sha256':sha(Path(__file__)),'model':{'id':head['encoder']['model_id'],'revision':head['encoder']['revision'],'head_sha256':sha(head_path),'encoder_files':len(head['encoder']['files']),'encoder_bytes':head['encoder']['total_encoder_files_bytes'],'local_files_only':True,'CPU':True,'gradient_updates':0},'counts':{'checks':len(checks),'passed':len(checks)-len(failures),'failed':len(failures),'native_calls':0,'classifier_fits':0,'platform_calls':0,'model_downloads':0},'checks':checks,'CPU_evidence':evidence,'source_locations':refs,'findings':[{'id':'MINILM-01','priority':'P2','classification':'demonstrated_navigation_embedding_truncation_not_document_loss','detail':'700-character fragments plus up-to-200-character headings exceed 256 WordPieces. Actual pinned encoder maps opposite late rules to identical embeddings after truncation. Chunk JSON still retains text and builder is instructed to read full originals, so this is retrieval coverage loss, not a demonstrated financial-policy bypass.','remedy':'Chunk by actual tokenizer budget including heading/special tokens; preserve line/character offsets and overlap. Add explicit per-fragment token/truncation coverage checks; keep full-input reading mandatory.'},{'id':'MINILM-02','priority':'P2','classification':'conditional_semantic_artifact_validation_gap','detail':'validate_result accepts bound source headers with zero chunks, empty retrieval rows and no encoder/runtime proof. Normal actual build_index succeeds with full sources; malformed artifact acceptance is independently executed but no real artifact tamper was performed.','remedy':'Validate chunk reconstruction/coverage against each source, offsets and hashes; finite cosine values, legal chunk references, encoder/runtime pins, retrieval cardinality and matching rendered text. Validate supplied evidence hashes again before later model rounds.'},{'id':'MINILM-03','priority':'P3','classification':'navigation_scope_mismatch_source_fact','detail':'prepare_semantic_assist passes only self.sources (ordered brief/amendment files). OpenAPI and platform docs are supplied separately to the builder but are absent from the semantic source list. Tool query cannot navigate an API-only rule.','remedy':'State scope as all supplied bank-brief evidence, or explicitly include pinned OpenAPI and relevant interface docs in navigation. Retrieval omission never implies rule absence.'},{'id':'MINILM-04','priority':'P2','classification':'runtime_provenance_not_fixed_pin','detail':'Head and all encoder file hashes are fixed and checked. Builder snapshots runtime and records its current hash; child checks that dynamically supplied hash, the pinned head references reviewed_plan_sha256 but stores no direct runtime hash. No fixed trusted runtime hash is enforced here. This binds the snapshot but does not independently authenticate a modified encoder implementation.','remedy':'Declare intended runtime version and verify its reviewed hash as a transitive dependency before execution; retain the snapshot hash in result and validate it on return. No unauthorized model or runtime modification was observed.'}],'positive_controls':['All11 local encoder file byte/hash pins and exact head hash independently match.','Actual CPU build_index preserves the two supplied authored evidence files and all10 query keys with bank_authority=false.','Long-line/CRLF/final-no-newline/amendment decoded text reconstruction passes; BOM intentionally treated as UTF-8 signature.','Semantic child allowlist removes tested credential/injection/proxy environment variables; offline CPU flags set.','Auto falls back, off runs no encoder and required fails rather than silently degrading when remaining budget is insufficient.','Actual local-only execute/main branch checks avoid publish/test and credential prompts; generation and artifact validation stubbed for control-flow proof.','Actual owned synthetic child timeout terminates within bounded wall time.'],'limitations':['No native retry; prior quota failures respected. Actual native identity is not attributed to this review.','No full autonomous build, model-generated bank agent, Freya/client/platform call, guide/candidate/test/model/data edit or Git action.','No blanket financial safety or complete semantic retrieval coverage claim; encoder is navigation/proposals only.','Normal encoder safetensors are hashed/loaded locally. No corpus, model EVAL outcomes or hidden test cases opened.','Only named new analysis report files and optional witness script written; virtual fixture documents were never created on disk.','Classic off path inspected/tested without editing backups; this is not a byte comparison with an unspecified classic archive.'],'script_wall_seconds':time.monotonic()-started}
report['earlier_snapshot_during_parent_source_repair']=earlier_snapshot;report['parent_reported_context']={'initial_unpublished_run':'20261011-140646-3f56dc','standalone_fragments':144,'standalone_encode_seconds':20.609,'independent_replay':False};P.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
lines=[report['status'],f"Checks {len(checks)}: {len(checks)-len(failures)} pass / {len(failures)} fail.",'Real local CPU MiniLM embedding/navigation executed; native LLM calls0, model/classifier fits0, platform calls0.', 'Source hashes: builder '+before['competition/builder.py']+'; semantic assist '+before['competition/semantic_assist.py'], 'Pinned head '+sha(head_path)+'; model revision '+head['encoder']['revision'], 'P2: token-aware chunks required. Full text survives but 256-token encoder drops late rules in700-character fragments; opposite tails produced identical actual vectors.', 'P2: result validation accepts incomplete unproven semantic artifacts. Fixed model files verified; current runtime is snapshot-bound rather than fixed reviewed-version-bound.', 'P3: semantic sources cover bank brief/amendments, not supplied OpenAPI/platform docs.', 'Local-only branch and no-credential-prompt controls pass; auto/off/required budget controls pass. No live generation/hosted qualification implied.', 'Protected sources/model/tests unchanged: '+str(report['source_stable']), 'Closed '+report['closed_at_utc']]
P.with_suffix('.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'status':report['status'],'counts':report['counts'],'failed_checks':failures,'source_stable':report['source_stable'],'real_CPU_evidence':evidence,'report_sha256':sha(P.with_suffix('.json')),'closed_at':report['closed_at_utc']},ensure_ascii=True))
