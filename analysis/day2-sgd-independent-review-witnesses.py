"""Read-only SGD TRAIN interface audit. No heldout rows, fitting or real index writes."""
import copy,hashlib,importlib.util,json,math,re,sqlite3,sys,time
from collections import Counter,defaultdict
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];B=ROOT/'research/customer-benchmark/day2-training-data/sgd';OUT=ROOT/'analysis/day2-sgd-independent-review-witnesses.json'
def digest(b):return hashlib.sha256(b).hexdigest()
def sha(p):return digest(p.read_bytes())
def read(p):return json.loads(p.read_text(encoding='utf8'))
def module(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
    if OUT.exists():raise RuntimeError('Existing frozen witnesses; no repeat')
    start=time.monotonic();proc=module('sgd_proc_readonly',B/'process.py');batch=module('sgd_batch_readonly',B/'batches.py');collector=module('sgd_collect_readonly',B/'collect.py')
    manifest=read(B/'full-v1/manifest.json');plan=read(B/'full-v1/split-plan.json');schemas_list=read(B/'service-schema.json');schemas={s['service_name']:s for s in schemas_list};inventory=read(B/'source-inventory.json')
    codepaths=[B/p for p in ('process.py','batches.py','collect.py','sources.json','source-inventory.json','service-schema.json','design-contract.json','NOTICE.txt','LICENSE.txt','PUBLISHER-README.md','README.txt')]+[B/'full-v1'/p for p in ('manifest.json','split-plan.json','validation.json','ready-handoff.json')]+[ROOT/'analysis/day2-multisource-gnn-design.json',ROOT/'analysis/day2-opus-training-engine-review.json']
    before={p.relative_to(ROOT).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in codepaths};checks=[];sourceproof=[]
    def check(name,ok,actual=None):checks.append({'id':name,'pass':bool(ok),'actual':actual})
    for field in ('processor','collector','source_inventory','service_schema','split_plan'):
        spec=manifest[field];check('pin/'+field,sha(ROOT/spec['path'])==spec['sha256'])
    for name,spec in manifest['license_files'].items():check('license/'+name,sha(ROOT/spec['path'])==spec['sha256'])
    check('schema/actualdimensions',len(schemas)==26 and sum(len(x['slots']) for x in schemas_list)==215 and sum(len(x['intents']) for x in schemas_list)==53)
    # Verify bytes/blob ancestry, never traverse CAL/EVAL source annotations.
    for spec in manifest['source_files']:
        p=B/'.cache'/spec['path'].replace('/','__');raw=p.read_bytes();blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest();okay=len(raw)==spec['bytes'] and digest(raw)==spec['sha256'] and blob==spec['publisher_blob_sha1'];sourceproof.append({'path':spec['path'],'sha256':digest(raw),'bytes':len(raw),'publisher_blob_match':blob==spec['publisher_blob_sha1']});check('officialTRAIN-source/'+spec['path'],okay)
    check('inventory/split-allowlist',all(x['path'] in ('README.md','LICENSE.txt','train/schema.json') or x['path'].startswith('train/dialogues_') and x['path'].endswith('.json') for x in inventory['files']))
    counts=Counter();groups=defaultdict(list);splitgroups=defaultdict(set)
    for ident,d in plan['dialogues'].items():counts[d['split']]+=d['user_turns'];groups[d['group_id']].append(ident);splitgroups[d['split']].add(d['group_id'])
    overlaps={a+'/'+b:len(splitgroups[a]&splitgroups[b]) for a,b in [('TRAIN','CAL'),('TRAIN','EVAL'),('CAL','EVAL')]}
    check('closure/metadata-zero-overlap',not any(overlaps.values()),overlaps)
    check('closure/group-contenthash',all(k=='sgd:'+proc.sha(proc.line(sorted(ids))) for k,ids in groups.items()))
    check('closure/counts',len(groups)==13161 and len(plan['dialogues'])==16142 and dict(counts)=={'TRAIN':132615,'CAL':16072,'EVAL':16295},{'components':len(groups),'dialogues':len(plan['dialogues']),'USER_examples':dict(counts),'largest_component':max(map(len,groups.values()))})
    train_specs=[s for s in manifest['outputs'] if s['split']=='TRAIN'];train_hashes={};samples=[]
    # TRAIN shard byte pins only. Heldout files are never opened, even for hashing.
    for i,spec in enumerate(train_specs):
        p=ROOT/spec['path'];train_hashes[spec['path']]=sha(p);check('TRAIN-shard-pin/'+spec['path'],train_hashes[spec['path']]==spec['sha256'] and p.stat().st_size==spec['bytes'])
        if i==0:
            with p.open(encoding='utf8') as f:
                for line in f:samples.append(json.loads(line))
    rowcounts=Counter();recoverability=[];schema_dims={s:{'active_intent_classes':1+len(v['intents']),'requested_slots':len(v['slots']),'slot_presence':len(v['slots'])} for s,v in schemas.items()}
    for r in samples:
        inp=r['input'];rowcounts['rows']+=1;rowcounts['frames']+=len(r['targets']['frames']);check('TRAIN-row/input-isolation/'+r['record_id'],set(inp)=={'speaker','utterance','earlier_context'} and inp['speaker']=='USER' and len(inp['earlier_context'])<=8 and all(set(t)=={'speaker','text'} and t['speaker'] in ('USER','SYSTEM') for t in inp['earlier_context']))
        check('TRAIN-row/no-bankgold/'+r['record_id'],r['ancestry']['split']=='TRAIN' and r['bank_policy_target_mask'] is False and r['ledger_target_mask'] is False and all(not f['head_masks'][h] for f in r['targets']['frames'] for h in ('bank_policy','bank_permission','ledger')))
        present={f['service'] for f in r['targets']['frames']};check('TRAIN-row/absentservice-mask/'+r['record_id'],len(r['service_supervision_masks'])==26 and all(r['service_supervision_masks'][s]==(s in present) for s in schemas))
        visible='\n'.join(t['text'] for t in inp['earlier_context'])+'\n'+inp['utterance']
        for f in r['targets']['frames']:
            slots=schemas[f['service']]['slots'];intents=['NONE']+[x['name'] for x in schemas[f['service']]['intents']]
            check('TRAIN-frame/dimensions/'+r['record_id']+'/'+f['service'],f['active_intent_id']==intents.index(f['active_intent']) if f['head_masks']['active_intent'] else f['active_intent'] is None)
            check('TRAIN-frame/masks/'+r['record_id']+'/'+f['service'],f['DELETE_mask'] is False and len(f['belief_updates'])==len(slots) and (f['requested_slots'] is None or len(f['requested_slots'])==len(slots)) and (f['published_slot_map_presence'] is None or len(f['published_slot_map_presence'])==len(slots)))
            for vals in f['slot_values'].values():
                for v in vals:
                    rowcounts['value_targets']+=1;rowcounts['recoverable']+=v['value_recoverability_mask']
                    check('TRAIN-value/mask-null/'+r['record_id'],v['value_recoverability_mask']==(v['text'] is not None))
                    if v['value_recoverability_mask'] and re.fullmatch(r'\w+',v['text']) and re.search(r'(?<!\w)'+re.escape(v['text'])+r'(?!\w)',visible,re.I) is None:
                        recoverability.append({'record_id':r['record_id'],'service':f['service'],'value_sha256':digest(v['text'].encode()),'value_chars':len(v['text']),'mask':True,'whole_token_visibility':False})
            for u in f['belief_updates']:rowcounts['update_total']+=1;rowcounts['update_observed']+=u['update_mask']
    # Independently compare 128 actualTRAIN examples to exact observed source prefixes.
    cached={};causal=0
    for r in samples[::max(1,len(samples)//128)][:128]:
        ancestry=r['ancestry'];sf=ancestry['source_file']
        if sf not in cached:cached[sf]={d['dialogue_id']:d for d in json.loads((B/'.cache'/sf.replace('/','__')).read_bytes()) if plan['dialogues'][d['dialogue_id']]['split']=='TRAIN'}
        dialog=cached[sf][ancestry['dialogue_id']];turns,_=proc.observed(dialog);i=ancestry['source_turn_index'];actual=proc.input_for(turns,i);check('causal/source-reconstruction/'+r['record_id'],0<=i<len(turns) and actual==r['input']);causal+=1
        mutant=copy.deepcopy(dialog)
        for j,t in enumerate(mutant['turns']):
            t['frames']=[{'service':'MUTATED_GOLD','state':{'active_intent':'LEAK_CANARY'}}]
            if j>i:t['utterance']='future marker should never be visible'
        transformed,_=proc.observed(mutant);check('causal/gold-future-mutation/'+r['record_id'],proc.input_for(transformed,i)==r['input'])
    # Tiny hand-authored schema tests masks, not new gold or retraining.
    schema={'S':{'slots':[{'name':'x'}],'intents':[{'name':'Act'}]}};stats=Counter();cases=[]
    for label,frame,previous in [('missing-state',{'service':'S','actions':[]},{'slot_values':{'x':['safe']}}),('missing-requested',{'service':'S','state':{'active_intent':'NONE','slot_values':{}},'actions':[]},None),('empty-known',{'service':'S','state':{'active_intent':'NONE','requested_slots':[],'slot_values':{}},'actions':[]},None),('removed-value',{'service':'S','state':{'active_intent':'NONE','requested_slots':[],'slot_values':{}},'actions':[]},{'slot_values':{'x':['safe']}}),('recoverable-SET',{'service':'S','state':{'active_intent':'Act','requested_slots':[],'slot_values':{'x':['safe']}},'actions':[]},{'slot_values':{}})]:
        target=proc.frame_targets(frame,schema,previous,'safe',stats);cases.append({'case':label,'target':target});check('synthetic/DELETE-mask/'+label,target['DELETE_mask'] is False)
    check('missing-state-stays-unknown',cases[0]['target']['active_intent'] is None and cases[0]['target']['requested_slots'] is None and cases[0]['target']['published_slot_map_presence'] is None and not any(cases[0]['target']['head_masks'][x] for x in ('active_intent','requested_slots','published_slot_map_presence')))
    check('missing-requested-not-zero',cases[1]['target']['requested_slots'] is None and not cases[1]['target']['head_masks']['requested_slots'])
    check('known-empty-is-zero',cases[2]['target']['requested_slots']==[0] and cases[2]['target']['head_masks']['requested_slots'])
    check('removed-value-not-DELETE',cases[3]['target']['belief_updates'][0]['publisher_map_update']=='UNKNOWN' and not cases[3]['target']['belief_updates'][0]['update_mask'])
    check('real-visible-SET',cases[4]['target']['belief_updates'][0]['publisher_map_update']=='SET' and cases[4]['target']['belief_updates'][0]['update_mask'])
    substring=[]
    for value,visible in [('one','someone'),('car','card'),('no','known'),('safe','safe')]:
        result=proc.value_targets([value],visible)[0];substring.append({'authored_value':value,'authored_visible':visible,'actual':result,'expected_recoverability':value==visible});check('recoverability/whole-value/'+value,result['value_recoverability_mask']==(value==visible),result)
    # Exact batch implementation with in-memory SQLite index. No real .sqlite files.
    memory=sqlite3.connect(':memory:');memory.execute('CREATE TABLE records (group_id TEXT,dialogue_id TEXT,turn_index INTEGER,path TEXT,offset INTEGER,length INTEGER)');offset=0;indexrows=[]
    selected=[]
    with (ROOT/train_specs[0]['path']).open('rb') as handle:
        for _ in range(256):
            offset=handle.tell();data=handle.readline();r=json.loads(data);z=r['ancestry'];indexrows.append((z['group_id'],z['dialogue_id'],z['source_turn_index'],train_specs[0]['path'],offset,len(data)));selected.append(r)
    memory.executemany('INSERT INTO records VALUES(?,?,?,?,?,?)',indexrows);memory.commit()
    class MemoryDB:
        def execute(self,*args):return memory.execute(*args)
        def close(self):pass
    emitted=[]
    with patch.object(batch,'index_for',lambda path,split:(MemoryDB(),manifest)):
        stream=batch.iter_batches(B/'full-v1/manifest.json',batch_size=17)
        try:
            for b in stream:emitted.append(b)
        finally:stream.close()
    flat=[x for b in emitted for x in b];check('batch/rowbounds',len(flat)==256 and max(map(len,emitted))<=17,{'rows':len(flat),'batches':len(emitted),'sizes':list(map(len,emitted))})
    last={};weights=defaultdict(float)
    for r in flat:
        z=r['ancestry'];d=z['dialogue_id'];check('batch/causal-order/'+r['record_id'],d not in last or z['source_turn_index']>last[d]);last[d]=z['source_turn_index'];weights[z['group_id']]+=r['sampling']['row_group_loss_weight']
    check('batch/equal-group-weight',all(abs(v-1)<1e-12 for v in weights.values()));check('batch/sampling-outside-input',all('sampling' not in r['input'] and set(r['input'])=={'speaker','utterance','earlier_context'} for r in flat))
    with patch.object(batch,'index_for',lambda path,split:(MemoryDB(),manifest)):
        stream=batch.iter_batches(B/'full-v1/manifest.json',batch_size=17.5);fractional=list(stream);check('batch/reject-noninteger',False,{'given':17.5,'actual_batch_sizes':list(map(len,fractional)),'boundedness_violation':max(map(len,fractional))>17.5})
    for label,kwargs in [('zero',{'batch_size':0}),('too-large',{'batch_size':513}),('CAL-default-denied',{'split':'CAL'}),('EVAL-default-denied',{'split':'EVAL'})]:
        accessed=[]
        def forbidden(*args):accessed.append(True);raise AssertionError('Should not access data')
        with patch.object(batch,'index_for',forbidden):
            try:next(batch.iter_batches(B/'full-v1/manifest.json',**kwargs));rejected=False
            except ValueError:rejected=True
        check('batch/'+label,rejected and not accessed)
    # Execute cache-hit branch without source opening; memory index only.
    cache=sqlite3.connect(':memory:');cache.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT)');cache.executemany('INSERT INTO metadata VALUES(?,?)',[('complete','1'),('manifest_sha256',sha(B/'full-v1/manifest.json')),('split','TRAIN')]);cache.commit();opened=[];real_open=Path.open
    def tracked(path,*args,**kwargs):opened.append(str(path));return real_open(path,*args,**kwargs)
    with patch.object(batch.sqlite3,'connect',lambda *args,**kwargs:cache),patch.object(Path,'open',tracked):db,_=batch.index_for(B/'full-v1/manifest.json','TRAIN')
    check('batch/cache-rechecks-shards',bool(opened),{'source_Path_open_calls':len(opened),'cache_hit_skipped_shard_rehash':not opened,'classification':'immutable-artifact assumption; no real mutation'})
    cache.close();memory.close()
    scrub=[]
    for text in ['My PIN is required to unlock the card.','I am not paying.','The museum is called Garden Grove.','I paid 100 today.','I paid 900 today.']:
        clean,c=proc.scrub(text);scrub.append({'authored_text':text,'scrubbed':clean,'redaction_counts':dict(c)})
    # Invalid negative index is caller-hardening; normal emission uses enumerate.
    turns=[{'speaker':'USER','text':'earlier'}]*12
    try:bad=proc.input_for(turns,-1);negative_accepted=True
    except (ValueError,IndexError):negative_accepted=False;bad={}
    check('serializer/negative-index-reject',not negative_accepted,{'accepted':negative_accepted,'context_length':len(bad.get('earlier_context',[])),'classification':'caller contract violation; actual source indices validated separately'})
    final={p:sha(ROOT/p) for p in before};stable=all(final[p]==d['sha256'] for p,d in before.items());check('protected-code-metadata-stability',stable)
    result={'status':'CLOSED_FROZEN_SGD_TRAIN_SOURCE_CPU_WITNESSES','task_started_utc':'2026-10-11T09:41:33Z','closed_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-start,3),'checks':checks,'checks_total':len(checks),'passed':sum(x['pass'] for x in checks),'failed':sum(not x['pass'] for x in checks),'source_manifest':before,'source_hashes_after':final,'all_protected_code_metadata_unchanged':stable,'official_source_bytes_verified':sum(x['bytes'] for x in sourceproof),'official_source_dialogue_files_verified':len(sourceproof),'source_blob_pins':sourceproof,'TRAIN_shard_hashes':train_hashes,'TRAIN_sample_stats':dict(rowcounts),'actual_causal_source_samples':causal,'schema_head_dimensions':schema_dims,'metadata_group_overlaps':overlaps,'component_split_counts':{s:len(g) for s,g in splitgroups.items()},'actual_TRAIN_recoverability_partialword_examples':recoverability[:20],'actual_TRAIN_recoverability_partialword_count':len(recoverability),'synthetic_target_mask_cases':cases,'synthetic_recoverability_cases':substring,'authored_scrub_cases':scrub,'batch_iterator_real_code_in_memory_index':{'rows':256,'all_state_detach_flags':all(x['sampling']['detach_state_on_dialogue_change'] for x in flat),'caller_detaches_state':'Metadata flag only; caller enforcement not provided.'},'heldout_data_files_opened':0,'heldout_gold_or_model_outcomes_read':False,'internal_split_metadata_only':True,'exact_cross_partition_text_overlap':'Producer-reported0; not independently reconstructed because heldout examples not opened. Independentgroup/ancestry overlap checked.','fits':0,'native_calls':0,'platform_calls':0,'GPU':0,'credentials_read':False,'realSQLite_files_written':0,'raw_corpus_text_logged':False}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');OUT.with_suffix('.txt').write_text('SGD independentTRAIN source/data-interface CPU witnesses.\n'+json.dumps({k:v for k,v in result.items() if k not in ('checks','source_blob_pins','source_manifest','source_hashes_after','TRAIN_shard_hashes','synthetic_target_mask_cases','schema_head_dimensions')},ensure_ascii=False,indent=2)+'\nFAILURES\n'+json.dumps([x for x in checks if not x['pass']],indent=2),encoding='utf8')
    print(json.dumps({'checks':result['checks_total'],'passed':result['passed'],'failed':result['failed'],'failures':[x for x in checks if not x['pass']],'TRAIN_stats':dict(rowcounts),'actual_partialword_count':len(recoverability),'causal_source_samples':causal,'wall_seconds':result['elapsed_seconds'],'protected_stable':stable},ensure_ascii=True))
if __name__=='__main__':main()
