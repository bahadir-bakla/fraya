"""Independent bounded TRAIN/source-only V2 QA. No fitting, bank or network calls."""
from collections import Counter
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import unicodedata
from unittest.mock import patch
from datetime import datetime, timezone
import time

ROOT=Path(__file__).resolve().parents[1]
B=ROOT/'research/customer-benchmark/day2-training-data/sgd'
P=ROOT/'analysis/day2-sgd-v2-independent-review'
START=time.monotonic()
def load(path):return json.loads(path.read_bytes())
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load(B/'full-v2/manifest.json');v1=load(B/'full-v1/manifest.json');old=load(ROOT/'analysis/day2-sgd-independent-review.json');w=load(ROOT/'analysis/day2-sgd-independent-review-witnesses.json')
proc=module('independent_sgd_v2_process',B/'process-v2.py');batch=module('independent_sgd_v2_batches',B/'batches-v2.py')
checks=[];witnesses=[]
def ck(name,condition,detail=None):checks.append({'id':name,'pass':bool(condition),'detail':detail})
def rejects(fn):
    try:fn()
    except (ValueError,TypeError,IndexError):return True
    return False
protected=[B/'full-v2/manifest.json',B/'full-v2/split-plan.json',B/'full-v1/manifest.json',B/'full-v1/split-plan.json',B/'process.py',B/'process-v2.py',B/'batches.py',B/'batches-v2.py',ROOT/'analysis/day2-sgd-independent-review.json',ROOT/'analysis/day2-sgd-independent-review.txt',ROOT/'analysis/day2-sgd-independent-review-witnesses.json',ROOT/'analysis/day2-sgd-v2-handoff.json']
for key in ['collector','source_inventory','service_schema']:
    protected.append(ROOT/m[key]['path'])
for entry in m['license_files'].values():protected.append(ROOT/entry['path'])
protected=list(dict.fromkeys(protected));before={p.relative_to(ROOT).as_posix():digest(p) for p in protected}
ck('exact_V2_manifest_pin',digest(B/'full-v2/manifest.json')=='d0eda9a9cb3e88420cedcc919643d8ecd92123b94f39e29e78ac8b3b12efca23')
for key in ['processor','base_processor','batcher','collector','source_inventory','service_schema']:
    ck('source_pin:'+key,digest(ROOT/m[key]['path'])==m[key]['sha256'])
for entry in m['license_files'].values():ck('license_pin:'+entry['path'],digest(ROOT/entry['path'])==entry['sha256'])
ck('split_plan_byte_invariance',(B/'full-v2/split-plan.json').read_bytes()==(B/'full-v1/split-plan.json').read_bytes())
ck('split_plan_hash',digest(B/'full-v2/split-plan.json')==m['split_plan']['sha256'])
for key in ['counts','source_files','feature_protocol','target_protocol','service_schema','source_inventory','license_files']:
    ck('unchanged_V1_protocol:'+key,m[key]==v1[key])
plan=load(B/'full-v2/split-plan.json')['dialogues'];owners={};badgroups=0
for ident,meta in plan.items():
    if meta['group_id'] in owners and owners[meta['group_id']]!=meta['split']:badgroups+=1
    owners[meta['group_id']]=meta['split']
ck('metadata_closure_disjoint',badgroups==0,{'groups':len(owners),'dialogues':len(plan),'split_groups':dict(Counter(owners.values()))})
shardproof=[]
# CAL/EVAL bytes are opaque hash input only: never JSON-decoded or labels inspected.
for spec in m['outputs']:
    h=hashlib.sha256();size=rows=0
    with (ROOT/spec['path']).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block);size+=len(block);rows+=block.count(b'\n')
    result={**spec,'actual_sha256':h.hexdigest(),'actual_bytes':size,'actual_rows':rows,'payload_decode':False if spec['split']!='TRAIN' else 'separate TRAIN sample only'}
    shardproof.append(result);ck('shard:'+spec['path'],h.hexdigest()==spec['sha256'] and size==spec['bytes'] and rows==spec['rows'] and size<=19500000)
ck('37_shards_total',len(shardproof)==37 and sum(x['actual_rows'] for x in shardproof)==164982,{'bytes':sum(x['actual_bytes'] for x in shardproof),'splits':dict(Counter({s:sum(x['actual_rows'] for x in shardproof if x['split']==s) for s in ['TRAIN','CAL','EVAL']}))})
first2=next(x for x in m['outputs'] if x['split']=='TRAIN');first1=next(x for x in v1['outputs'] if x['split']=='TRAIN')
old_cases={(x['record_id'],x['service'],x['value_sha256']) for x in w['actual_TRAIN_recoverability_partialword_examples']}
repaired=[];sample_rows=[];source_offsets=[];input_drift=other_drift=0
schemas={x['service_name']:x for x in load(B/'service-schema.json')}
def maskless(row):
    r=copy.deepcopy(row);r.pop('schema_version',None)
    for frame in r['targets']['frames']:
        for vals in frame['slot_values'].values():
            for v in vals:v.pop('text',None);v.pop('value_recoverability_mask',None)
        for action in frame['actions']:
            for v in action['values']:v.pop('text',None);v.pop('value_recoverability_mask',None)
        for update in frame['belief_updates']:update.pop('update_mask',None);update.pop('reason',None)
    return r
with (ROOT/first1['path']).open('rb') as f1,(ROOT/first2['path']).open('rb') as f2:
    number=0
    while True:
        offset=f2.tell();a=f1.readline();b=f2.readline()
        if not a or not b:ck('TRAIN_sample_equal_length',a==b);break
        r1=json.loads(a);r2=json.loads(b);number+=1
        input_drift+=int(r1['input']!=r2['input']);other_drift+=int(maskless(r1)!=maskless(r2))
        ck('TRAIN_input_fields:'+r2['record_id'],set(r2['input'])=={'speaker','utterance','earlier_context'} and len(r2['input']['earlier_context'])<=8 and all(set(t)=={'speaker','text'} for t in r2['input']['earlier_context']))
        ck('TRAIN_no_bank_DELETE_gold:'+r2['record_id'],not r2['bank_policy_target_mask'] and not r2['ledger_target_mask'] and all(not f['DELETE_mask'] and not any(f['head_masks'][k] for k in ['bank_policy','bank_permission','ledger']) for f in r2['targets']['frames']))
        for oldf,newf in zip(r1['targets']['frames'],r2['targets']['frames']):
            slotnames=[s['name'] for s in schemas[newf['service']]['slots']]
            for slot,values in oldf['slot_values'].items():
                for i,val in enumerate(values):
                    if val['text'] is None:continue
                    key=(r1['record_id'],oldf['service'],hashlib.sha256(val['text'].encode()).hexdigest())
                    if key in old_cases:
                        newval=newf['slot_values'][slot][i];update=newf['belief_updates'][slotnames.index(slot)]
                        proof={'record_id':key[0],'service':key[1],'old_value_sha256':key[2],'new_source_value_sha256':newval['source_value_sha256'],'new_value_mask':newval['value_recoverability_mask'],'new_text_is_null':newval['text'] is None,'update_mask':update['update_mask'],'publisher_map_update':update['publisher_map_update']}
                        repaired.append(proof);ck('known_partialword_repaired:'+key[0],not newval['value_recoverability_mask'] and newval['text'] is None and not update['update_mask'],proof)
        if number<=256:
            sample_rows.append(r2);source_offsets.append((r2,offset,len(b)))
ck('5038_TRAIN_input_and_unrelated_label_invariance',number==5038 and input_drift==0 and other_drift==0,{'rows':number,'input_drift':input_drift,'unrelated_label_drift':other_drift})
ck('all_15_known_TRAIN_witnesses_found',len(repaired)==15 and {(x['record_id'],x['service'],x['old_value_sha256']) for x in repaired}==old_cases,{'found':len(repaired)})

boundary_cases=[('one','someone',False),('car','card',False),('no','known',False),('car',"car's",False),('car','car-like',False),('car','car‐like',False),('car','car‑like',False),('car','car_like',False),('car','carpet',False),('safe','safe\u0301',False),('car','a car.',True),('car','card then car',True),('san francisco','san\nfrancisco',False),('san  francisco','san francisco',True),('cafe\u0301','café',True),('ｃａｒ','car',True),('car','Car',False),('car','car’pet',False),('car','car\tpet',True)]
for value,visible,expected in boundary_cases:
    v=proc.value_targets([value],visible)[0];ck('boundary:'+repr((value,visible)),v['value_recoverability_mask']==expected,{'mask':v['value_recoverability_mask'],'expected':expected})
for invisible in ['\u00ad','\u200d','\u200c','\u2060']:
    raw='car'+invisible+'pet';visible=proc.base.scrub(raw)[0];target=proc.value_targets(['car'],visible)[0]
    witnesses.append({'id':'format-character-token-continuation','character':'U+'+format(ord(invisible),'04X'),'source_visible_unchanged':raw==visible,'actual_mask':target['value_recoverability_mask'],'scope':'authored Unicode segmentation challenge; outside the explicitly enumerated LMN/Pc/apostrophe/hyphen boundary policy; not observed TRAIN corruption'})
schema={'S':{'slots':[{'name':'x'}],'intents':[{'name':'Act'}]}}
for prior in [None,{}, {'slot_values':{}},{'slot_values':{'x':['car']}}]:
    frame={'service':'S','state':{'active_intent':'Act','requested_slots':[],'slot_values':{'x':['car']}},'actions':[]}
    t=proc.base.frame_targets(frame,schema,prior,'card',Counter());ck('SET_KEEP_partialword_mask:'+repr(prior),not t['belief_updates'][0]['update_mask'])
for state in [None,{}, {'active_intent':'Act'},{'slot_values':None}]:
    frame={'service':'S','actions':[]}
    if state is not None:frame['state']=state
    t=proc.base.frame_targets(frame,schema,{'slot_values':{'x':['car']}},'car',Counter())
    ck('missing_state_unknown:'+repr(state),t['published_slot_map_presence'] is None and not t['head_masks']['published_slot_map_presence'] and t['requested_slots'] is None and not t['head_masks']['requested_slots'] and not t['belief_updates'][0]['update_mask'] and not t['DELETE_mask'])
t=proc.base.frame_targets({'service':'S','state':{'slot_values':{},'requested_slots':[]},'actions':[]},schema,{'slot_values':{'x':['car']}},'car',Counter())
ck('named_DELETE_unknown',t['belief_updates'][0]['publisher_map_update']=='UNKNOWN' and not t['belief_updates'][0]['update_mask'] and not t['DELETE_mask'],t['belief_updates'])
turns=[{'speaker':'USER' if i%2==0 else 'SYSTEM','text':'observed '+str(i)} for i in range(31)]
for index in [-1,31,True,False,0.5,'0',None]:ck('index_reject:'+repr(index),rejects(lambda i=index:proc.input_for(turns,i)))
for index in range(0,31,2):
    original=proc.input_for(turns,index);changed=copy.deepcopy(turns)
    for j,t in enumerate(changed):
        t.update(frames=[{'state':{'private_gold':'sentinel'}}],service='hidden',state={'x':'target'})
        if j>index:t['text']='future sentinel'
    actual=proc.input_for(changed,index)
    # Caller annotations in already observed objects are not safe inputs: serialization takes
    # pre-scrubbed observed turns, not raw source objects. The actual source observed() strips them.
    source={'turns':[{'speaker':t['speaker'],'utterance':t['text'],'frames':t.get('frames',[]),'service':t.get('service')} for t in changed]}
    cleaned,_=proc.base.observed(source)
    clean_original,_=proc.base.observed({'turns':[{'speaker':t['speaker'],'utterance':t['text']} for t in turns]})
    ck('observed_serializer_causal:'+str(index),proc.input_for(cleaned,index)==proc.input_for(clean_original,index) and len(original['earlier_context'])<=8)
for size in [17.5,True,False,0,513,'17',None]:ck('batch_reject_before_index:'+repr(size),rejects(lambda s=size:next(batch.iter_batches(B/'full-v2/manifest.json',s))))
for split in ['CAL','EVAL','BAD']:ck('heldout_default_reject:'+split,rejects(lambda s=split:next(batch.iter_batches(B/'full-v2/manifest.json',17,split=s))))

# Exercise real iterator/cache code with an in-memory derived SQLite cache only.
fixture_manifest=copy.deepcopy(m);fixture_manifest['outputs']=[first2]
fixture_bytes=json.dumps(fixture_manifest,sort_keys=True).encode();fp=P.with_name(P.name+'-witnesses-memory-manifest.json')
read_orig=Path.read_bytes;open_orig=Path.open;cache_proofs=[]
def fixture_read(path):return fixture_bytes if path==fp else read_orig(path)
def db_for(records):
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)');db.executemany('INSERT INTO metadata VALUES (?,?)',[('complete','1'),('manifest_sha256',batch.sha(fixture_bytes)),('split','TRAIN')]);db.execute('CREATE TABLE records(group_id TEXT,dialogue_id TEXT,turn_index INTEGER,path TEXT,offset INTEGER,length INTEGER)')
    for row,path,offset,length in records:
        a=row['ancestry'];db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(a['group_id'],a['dialogue_id'],a['source_turn_index'],path,offset,length))
    db.commit();return db
normal=[(r,first2['path'],off,n) for r,off,n in source_offsets]
db=db_for(normal);opens=[]
def tracked_open(path,*a,**kw):
    if path==ROOT/first2['path']:opens.append(str(path))
    return open_orig(path,*a,**kw)
with patch.object(Path,'read_bytes',fixture_read),patch.object(Path,'open',tracked_open),patch.object(batch.sqlite3,'connect',lambda _:db):
    outputs=list(batch.iter_batches(fp,17,seed=20261011))
ck('real_iterator_integer_17',len(outputs)==16 and sum(map(len,outputs))==256 and max(map(len,outputs))<=17)
ck('cache_hit_rehashes_requested_shard',len(opens)>=2,{'TRAIN_shard_open_calls':len(opens),'scope':'first actual V2 TRAIN shard; completed memory cache'})
emitted=[r for bs in outputs for r in bs];previous=None;ordered={};weights=Counter()
for row in emitted:
    a=row['ancestry'];s=row['sampling'];boundary=a['dialogue_id'];ck('state_reset:'+row['record_id'],s['state_reset_before_row']==(boundary!=previous));previous=boundary
    ck('sequence_order:'+row['record_id'],a['source_turn_index']>ordered.get(boundary,-1));ordered[boundary]=a['source_turn_index'];weights[a['group_id']]+=s['row_group_loss_weight']
ck('equal_group_total_weight',all(abs(v-1)<1e-10 for v in weights.values()))
with (ROOT/first1['path']).open('rb') as f:data=f.readline()
stale_row=json.loads(data);stale_db=db_for([(stale_row,first1['path'],0,len(data))])
with patch.object(Path,'read_bytes',fixture_read),patch.object(batch.sqlite3,'connect',lambda _:stale_db):
    out=list(batch.iter_batches(fp,17))
accepted=out[0][0]['schema_version']=='sgd.observed-user-input.publisher-targets.v1'
ck('cache_rejects_unpinned_record_path',not accepted,{'actual_schema_version':out[0][0]['schema_version'],'advertised_version':m['schema_version'],'scope':'conditional stale/corrupt memory index; actual V2 source shards unchanged'})
witnesses.append({'id':'completed-cache-unpinned-path','actual_V1_row_yielded_under_V2_manifest':accepted,'actual_code_executed':True,'real_index_files_written':0,'protected_files_modified':0,'scope':'conditional derivative-cache provenance defect, not observed frozen-data contamination'})

after={p.relative_to(ROOT).as_posix():digest(p) for p in protected};ck('protected_inputs_before_after',before==after)
shards_after={x['path']:digest(ROOT/x['path']) for x in m['outputs']};ck('37_shards_stable_after',all(shards_after[x['path']]==x['sha256'] for x in m['outputs']))
fail=[x for x in checks if not x['pass']]
wp=P.with_name(P.name+'-witnesses.json')
proof={'checks':checks,'full_37_shard_hashes':shardproof,'all_15_known_TRAIN_repairs':repaired,'conditional_witnesses':witnesses,'protected_before':before,'protected_after':after,'shard_hashes_after':shards_after,'raw_source_text_logged':False,'heldout_payload_JSON_decoded':False,'real_index_files_written':0}
wp.write_text(json.dumps(proof,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
report={'status':'CLOSED_FROZEN_CODEX_SGD_V2_TRAIN_SOURCE_CPU_REVIEW','reviewer':'Independent Codex; no native inference','started_at_utc':'2026-10-11T10:01:10Z','closed_at_utc':datetime.now(timezone.utc).isoformat(),'deadline_utc':'2026-10-11T10:09:10Z','manifest':{'path':str(B/'full-v2/manifest.json'),'sha256':digest(B/'full-v2/manifest.json')},'counts':{'checks':len(checks),'passed':len(checks)-len(fail),'failed':len(fail),'shards_hashed':37,'TRAIN_sample_rows':number,'known_partialword_witnesses_repaired':len(repaired),'batch_rows':256},'source_hashes':before,'all_protected_unchanged':before==after and all(shards_after[x['path']]==x['sha256'] for x in m['outputs']),'split_plan_byte_invariant':True,'split_metadata_group_disjoint':badgroups==0,'data_version_repair':'15/15 known actual TRAIN partial-word values are null/masked; their dependent updates are masked. First5038 TRAIN inputs/ancestry/unrelated publisher labels equal V1. Integer/index bounds and actual requested-shard cache rehash controls pass.','findings':[{'id':'V2-CACHE-01','priority':'P2','classification':'actual_code_conditional_completed_cache_provenance','evidence':'Actual V2 iterator hashes pinned V2 TRAIN shard, then trusts completed SQLite record paths/offsets. A memory-only corrupted cache pointed to unchanged V1 TRAIN data and yielded a V1 row under the V2 manifest without rejection. No actual disk cache or corpus was altered.','recommendation':'Bind derivative cache contents to allowed V2 shard paths; validate path/offset/length plus row schema, split/group/dialogue/turn identity on read, or rebuild/verify a content-addressed derived index. Fresh shard hashes alone do not authenticate cached pointers.'},{'id':'V2-UNICODE-01','priority':'P3','classification':'authored_uncovered_segmentation_controls_not_observed_TRAIN_defect','evidence':witnesses[:4],'recommendation':'Specify format-character treatment for soft hyphen, joiner/nonjoiner and word joiner before any span qualification. Current declared LMN/Pc/apostrophe/hyphen policy matches code but does not define these linguistic continuations; do not call this an actual TRAIN defect without corpus evidence.'},{'id':'V2-AUTHORITY-01','priority':'P2','classification':'retained_protocol_limits','evidence':'Missing state/requested slots are unknown/masked; named removals are UNKNOWN with DELETE_mask false. All bank policy/permission/ledger masks remain false. Source privacy transform unchanged and can erase semantics. Publisher KEEP/SET map deltas are not current-turn corrections, bank consent or human gold.','recommendation':'Use strict input-only projection with all service schemas; loss masks and current frames cannot route graph/features. Keep proposal/abstention and deterministic bank authority separate; no bank deployment or span qualification follows from this data repair.'}],'head_admission':{'previous_15_partialword_blocker':'Reproduced repaired in actual V2 TRAIN sample; this specific blocker resolved.','value_KEEP_SET_publisher_baseline':'Data mask repair supported within tested scope; secure consumer must bind derived cache or bypass corrupted cache safely through a reviewed reader. No fit authorized or performed by this review.','unrelated_V1_pilot':'Untouched; this review does not stop or modify it.','DELETE_bankpolicy_permission_ledger':'No new gold; unknown/unqualified.'},'failures':fail,'witnesses':{'path':str(wp),'sha256':digest(wp)},'source_causality':'16 direct observed() -> input_for() annotation/future mutations pass; 5038 actual V2 input equality to frozen V1; previous V1 128 actual source reconstructions remain separate preserved evidence, not newly replayed here.','heldout_access':{'CAL_EVAL_shards':8,'operation':'opaque SHA256/byte/newline accounting only','payload_JSON_decoded':False,'labels_or_model_outcomes_inspected':False},'limits':['No training/model/teacher/metric outcomes read, fits, native calls, platform/Git/budget/credentials actions.','Full37 byte hashes independently verified; label/feature checks restricted to first5038 TRAIN rows.','Full cross-partition exact feature closure remains producer-reported; metadata split closure and split-plan byte identity independently verified.','Only named new review/witness files written; no real SQLite cache writes.'], 'new_fits':0,'native_calls':0,'platform_calls':0,'elapsed_script_seconds':time.monotonic()-START}
P.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
lines=[report['status'],'Manifest SHA256 '+report['manifest']['sha256'],report['data_version_repair'],f"Checks {len(checks)}: {len(checks)-len(fail)} pass, {len(fail)} fail. Full37hashes verified; CAL/EVAL opaque hash only.",'P2: completed cache trusts unpinned record pointers; actual iterator conditionally yielded V1 row under V2 manifest. No actual cache tamper. Bind cache record provenance before relying on reusable indexes.','P3: format-character continuation remains an authored segmentation gap, not observed TRAIN contamination.','No human/bank-policy gold or DELETE qualification; all bank masks false. Zero fits/native/platform/Git/budget operations.','Protected code, both manifests, split plans, earlier reviews and all37 shards unchanged: '+str(report['all_protected_unchanged']),'Closed '+report['closed_at_utc']]
P.with_suffix('.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'status':report['status'],'counts':report['counts'],'failures':fail,'all15_repaired':len(repaired)==15,'all_protected_stable':report['all_protected_unchanged'],'report_sha256':digest(P.with_suffix('.json')),'closed_at':report['closed_at_utc']},ensure_ascii=True))
