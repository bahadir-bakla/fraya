"""Independent real CPU retest; virtual authored inputs; no native/platform calls."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import time
from datetime import datetime,timezone
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'competition'))
import semantic_assist as assist
P=ROOT/'analysis/minilm-builder-independent-review-v2';checks=[];cases=[]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ck(name,value,detail=None):checks.append({'id':name,'pass':bool(value),'detail':detail})
def rejected(fn):
    try:fn()
    except ValueError as e:return True,type(e).__name__,str(e)
    except Exception as e:return True,type(e).__name__,'non-normalized malformed-artifact exception'
    return False,None,None
head_path=ROOT/'integrations/learned-dialogue/day2_pretrained_head.json';runtime=ROOT/'integrations/learned-dialogue/day2_pretrained_runtime.py'
head=json.loads(head_path.read_bytes());directory=ROOT/head['encoder']['local_directory']
old_paths=[ROOT/'analysis/minilm-builder-independent-review.json',ROOT/'analysis/minilm-builder-independent-review.txt',ROOT/'analysis/minilm-builder-independent-witness.py']
protected=[ROOT/'competition/builder.py',ROOT/'competition/semantic_assist.py',head_path,runtime]+old_paths+[directory/name for name in head['encoder']['files']]
before={p.relative_to(ROOT).as_posix():sha(p) for p in protected};old=json.loads(old_paths[0].read_bytes())
ck('same_exact_head_pin',sha(head_path)==assist.HEAD_SHA256)
for name,record in head['encoder']['files'].items():ck('same_encoder_pin:'+name,sha(directory/name)==record['sha256'])
work=P.parent.resolve()
texts=[('# Long source heading\r\n'+'a '*330+'ALLOW recording after agreement.\r\n'),('# Amendment\n'+'a '*330+'DENY recording without agreement.\n'),('# Unicode\n'+'漢字かな '*190+'Consent remains required.\n'),('# Combining\n'+('cafe\u0301 👩\u200d💻 ñ ﬁ ß ')*130+'END-COMBINING'),('\ufeff# Mixed separators\r\nfirst\u2028second\u2029third\r\nfourth\n'),('# Metadata-only long heading '+'漢'*400+'\n'+'Rule stays deterministic.\n')]
fixtures={work/('minilm-builder-independent-review-v2-fixture-'+str(i)+'.md'):text.encode('utf-8') for i,text in enumerate(texts)}
sources=[{'path':p.name,'sha256':hashlib.sha256(raw).hexdigest()} for p,raw in fixtures.items()]
read_original=Path.read_bytes;file_original=Path.is_file
def virtual_read(p):return fixtures[p] if p in fixtures else read_original(p)
def virtual_file(p):return p in fixtures or file_original(p)
for k,v in {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1','TOKENIZERS_PARALLELISM':'false'}.items():os.environ[k]=v
spec=importlib.util.spec_from_file_location('independent_minilm_v2_runtime',runtime);rt=importlib.util.module_from_spec(spec)
with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')) as http_guard,patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')) as socket_guard:
    spec.loader.exec_module(rt);encoder=rt.FrozenEncoder(directory)
    with patch.object(Path,'read_bytes',virtual_read),patch.object(Path,'is_file',virtual_file):
        initial=assist.chunks_from_sources(work,sources)
        safe=assist.token_safe_chunks(initial,encoder.tokenizer,encoder.max_length,time.monotonic()+30)
        request={'head':str(head_path),'repo':str(ROOT),'runtime':str(runtime),'runtime_sha256':sha(runtime),'work':str(work),'sources':sources,'seconds':40}
        result=assist.build_index(request)
        validate=lambda obj:assist.validate_result(obj,sources,work=work,runtime_sha256=sha(runtime),encoder_files=head['encoder']['files'])
        validate(result);ck('actual_CPU_deep_valid_result',True,{'queries':len(result['retrieval']),'chunks':len(result['chunks']),'sources':len(sources),'seconds':result['elapsed_seconds']})
        for order,(path,raw) in enumerate(fixtures.items()):
            selected=[c for c in result['chunks'] if c['source_order']==order]
            ck('complete_Unicode_text_reconstruction:'+str(order),''.join(c['text'] for c in selected)==raw.decode('utf-8-sig'))
            lines=raw.decode('utf-8-sig').splitlines(keepends=True)
            for number,line in enumerate(lines,1):
                offset=0
                for c in [x for x in selected if x['line']==number]:
                    ck('coordinates:'+str((order,number,offset)),c['character_start']==offset and c['text']==line[offset:c['character_end']]);offset=c['character_end']
                ck('full_line_coverage:'+str((order,number)),offset==len(line))
        for c in result['chunks']:
            count=len(encoder.tokenizer(c['text'],truncation=False)['input_ids'])
            ck('actual_token_proof:'+str(c['id']),count==c['wordpieces'] and count<=256 and count==len(encoder.tokenizer(c['text'],truncation=True,max_length=256)['input_ids']))
        ck('headings_not_added_to_model_input',"texts = [c['text'] for c in chunks]" in (ROOT/'competition/semantic_assist.py').read_text())
        tails=[next(c['text'] for c in result['chunks'] if c['source_order']==o and ('ALLOW' if o==0 else 'DENY') in c['text']) for o in [0,1]]
        vectors=encoder.encode(tails,deadline=time.monotonic()+20);difference=float(abs(vectors[0]-vectors[1]).max())
        ck('previous_opposite_late_rule_witness_resolved',difference>1e-7,{'maximum_embedding_difference':difference,'tail_chunks_tokens':[len(encoder.tokenizer(t,truncation=False)['input_ids']) for t in tails],'all_source_text_retained':True,'scope':'actual CPU navigation; not policy truth'})
        minimal={'schema':'builder.semantic_evidence.v1','bank_authority':False,'head_sha256':assist.HEAD_SHA256,'sources':sources,'retrieval':{key:[] for key in assist.QUERIES},'chunks':[]}
        outcome=rejected(lambda:validate(minimal));ck('previous_head_only_malformed_witness_rejected',outcome[0] and outcome[1]=='ValueError',{'error':outcome[2]})
        mutations={
          'empty_chunks':lambda x:x.update(chunks=[]),
          'missing_runtime':lambda x:x.pop('runtime_sha256'),
          'wrong_runtime':lambda x:x.update(runtime_sha256='0'*64),
          'missing_encoder':lambda x:x.pop('encoder_files'),
          'wrong_encoder':lambda x:x.update(encoder_files={'wrong':{}}),
          'head_mismatch':lambda x:x.update(head_sha256='0'*64),
          'bank_authority_true':lambda x:x.update(bank_authority=True),
          'missing_query':lambda x:x['retrieval'].pop('identity'),
          'empty_query':lambda x:x['retrieval'].update(identity=[]),
          'nan_cosine':lambda x:x['retrieval']['identity'][0].update(cosine=float('nan')),
          'inf_cosine':lambda x:x['retrieval']['identity'][0].update(cosine=float('inf')),
          'cosine_out_of_range':lambda x:x['retrieval']['identity'][0].update(cosine=1.1),
          'bool_cosine':lambda x:x['retrieval']['identity'][0].update(cosine=True),
          'out_of_range_chunk':lambda x:x['retrieval']['identity'][0].update(chunk_id=len(x['chunks'])),
          'duplicate_retrieval':lambda x:x['retrieval']['identity'].append(copy.deepcopy(x['retrieval']['identity'][0])),
          'chunk_id':lambda x:x['chunks'][0].update(id=8),
          'bool_coordinates':lambda x:x['chunks'][0].update(line=True),
          'oversized_token_count':lambda x:x['chunks'][0].update(wordpieces=257),
          'missing_token_count':lambda x:x['chunks'][0].pop('wordpieces'),
          'wrong_chunk_source':lambda x:x['chunks'][0].update(source_sha256='0'*64),
          'text_substitution':lambda x:x['chunks'][0].update(text='X'+x['chunks'][0]['text'][1:]),
          'offset_gap':lambda x:x['chunks'][0].update(character_start=1,character_end=x['chunks'][0]['character_end']+1),
          'reconstructed_source_omission':lambda x:x['chunks'].pop(),
        }
        for name,mutate in mutations.items():
            changed=copy.deepcopy(result);mutate(changed);outcome=rejected(lambda:validate(changed));ck('deep_guard:'+name,outcome[0] and outcome[1]=='ValueError',{'exception':outcome[1],'reason':outcome[2]})
        # Token counts are trusted child measurements: independently demonstrate the host boundary.
        forged=copy.deepcopy(result)
        for c in forged['chunks']:c['wordpieces']=1
        outcome=rejected(lambda:validate(forged))
        cases.append({'id':'token_count_measurement_trust_boundary','forged_counts_accepted':not outcome[0],'source_characters_unchanged':True,'scope':'conditional artifact mutation; current child generated and independently measured all true counts','recommendation':'Treat wordpieces as trusted child measurement, or validate/tokenize again if artifacts are considered untrusted. Not a regression of actual token-safe build_index.'})
        for name,mutate in [('chunk_nonmapping',lambda x:x['chunks'].__setitem__(0,0)),('row_nonmapping',lambda x:x['retrieval']['identity'].__setitem__(0,0))]:
            changed=copy.deepcopy(result);mutate(changed);outcome=rejected(lambda:validate(changed));cases.append({'id':name,'rejected':outcome[0],'exception':outcome[1],'scope':'malformed-artifact error normalization; no normal child emits these'} )
        originals={p:raw for p,raw in fixtures.items()}
        first_path=next(iter(fixtures));fixtures[first_path]=fixtures[first_path]+b'changed'
        outcome=rejected(lambda:validate(result));ck('changed_actual_work_evidence_rejected',outcome[0] and outcome[1]=='ValueError');fixtures.update(originals)
        ck('expired_token_split_fails_closed',rejected(lambda:assist.token_safe_chunks(initial,encoder.tokenizer,256,time.monotonic()-1))[0])
    ck('no_network_attempts',http_guard.call_count==0 and socket_guard.call_count==0)
after={p.relative_to(ROOT).as_posix():sha(p) for p in protected};ck('all_reviewed_code_encoder_and_old_reports_unchanged',before==after)
fail=[x for x in checks if not x['pass']]
report={'status':'CLOSED_FROZEN_CODEX_MINILM_BUILDER_V2_SOURCE_CPU_RETEST','started_at_utc':'2026-10-11T11:14:20Z','closed_at_utc':datetime.now(timezone.utc).isoformat(),'deadline_utc':'2026-10-11T11:20:20Z','reviewer':'Independent Codex; zero native calls','source_hashes_before':before,'source_hashes_after':after,'all_protected_unchanged':before==after,'harness_sha256':sha(Path(__file__)),'counts':{'checks':len(checks),'passed':len(checks)-len(fail),'failed':len(fail),'authored_sources':len(sources),'initial_char_chunks':len(initial),'actual_token_safe_chunks':len(result['chunks']),'queries':len(result['retrieval']),'native_calls':0,'fits':0,'platform_calls':0},'checks':checks,'CPU_evidence':{'local_model_id':head['encoder']['model_id'],'revision':head['encoder']['revision'],'head_sha256':sha(head_path),'runtime_sha256':sha(runtime),'real_index_seconds':result['elapsed_seconds'],'all_original_characters_retained':True,'maximum_actual_fragment_tokens':max(c['wordpieces'] for c in result['chunks']),'late_rule_embedding_difference':difference,'GPU':False,'classifier_head_used':False,'bank_authority':False},'prior_findings':{'MINILM_01_token_truncation':'Resolved on current actual token-safe path: all fragments independently counted <=256, originals reconstruct, opposite tails now yield different embeddings.','MINILM_02_head_only_validation':'Original minimal malformed artifact rejected; 23 deep artifact mutations and actual-work mutation rejected with ValueError.','runtime_fixed_reviewed_version':'Current runtime remains dynamically snapshot-bound; trusted snapshot hashes match. No runtime change observed.','navigation_input_scope':'Still bank briefs/amendments only; OpenAPI/platform docs supplied separately. Not silently expanded by this retest.'},'conditional_hardening':cases,'source_scope':'Exact current competition/builder.py and semantic_assist.py plus pinned encoder/runtime. All fixtures are authored virtual input, including CJK, combining accents, ligature, emoji joiner, Unicode line separators, UTF8 BOM and CRLF.','old_frozen_review':{'sha256':before['analysis/minilm-builder-independent-review.json'],'previous_counts':old['counts'],'unchanged':after['analysis/minilm-builder-independent-review.json']==before['analysis/minilm-builder-independent-review.json']},'active_run':'20261011-141102-3e5d3f not opened, altered, resumed or tested; parent reports it uses earlier copied144-chunk source. Current-source repairs are not attributed to that active run.','limits':['No native retry, model fitting, Freya/client/platform/Git/credentials access or original-source/model/test edits.','Actual CPU embeddings and navigation are source witnesses, not bank safety/hosted qualification or policy authority.','No old frozen review overwrite; only named new v2 report/script files written.','Token count range checking trusts child measurements; malformed non-mapping objects are rejected but may surface AttributeError rather than normalized ValueError.','Parent test updates not invoked; no hidden data/model EVAL or active candidate outputs read.']}
P.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
lines=[report['status'],f"{len(checks)-len(fail)}/{len(checks)} executed checks pass.",'Both prior witnesses resolved on current source; exact source/old review/encoder pins unchanged during retest.',f"Actual CPU index: {len(sources)} authored Unicode sources, {len(result['chunks'])} token-safe chunks, {len(result['retrieval'])} queries; max tokens {report['CPU_evidence']['maximum_actual_fragment_tokens']}.",f"Opposite late-rule embeddings now differ by {difference}; full source characters/contiguous offsets retained.",'Head-only malformed artifact and23 mutations rejected. Actual-work amendment/source changes rejected.', 'Remaining conditional hardening: token measurement is trusted, not re-tokenized by host; nonmapping malformed objects may raise AttributeError. No observed normal-output failure.', 'Active144-chunk run untouched; current-source result is not its qualification. Native/fits/platform0; bank_authority=false.', 'Builder SHA256 '+before['competition/builder.py'],'Semantic SHA256 '+before['competition/semantic_assist.py'],'Closed '+report['closed_at_utc']]
P.with_suffix('.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'status':report['status'],'counts':report['counts'],'failures':fail,'CPU_evidence':report['CPU_evidence'],'conditional_hardening':cases,'source_stable':before==after,'report_sha256':sha(P.with_suffix('.json')),'closed_at':report['closed_at_utc']},ensure_ascii=True))
