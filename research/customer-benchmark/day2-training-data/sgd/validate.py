"""Full shard/schema validation plus source-causality and real TRAIN reset tests.

No model fits, model outcomes, official dev/test reads or packet rewrites.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[3]
FULL=ROOT/'full-v1'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    processor=module('sgd_processor_validation',ROOT/'process.py')
    batches=module('sgd_validated_batch_reader',ROOT/'validated_batches.py')
    manifest=json.loads((FULL/'manifest.json').read_bytes())
    plan=json.loads((FULL/'split-plan.json').read_bytes())['dialogues']
    schema=json.loads((ROOT/'service-schema.json').read_bytes())
    schemas={s['service_name']:s for s in schema}
    # Every already-frozen shard is rechecked, including data identity, strict
    # observed-only input fields, closure and unknown/nonpermission masks.
    full=processor.verify_shards(manifest['outputs'],plan,manifest['counts']['source_counts']['USER_turns'])
    arity_count=0;known=0
    for shard in manifest['outputs']:
        with (REPO/shard['path']).open('rb') as handle:
            for data in handle:
                row=json.loads(data)
                assert set(row['service_supervision_masks'])==set(schemas)
                assert {s for s,v in row['service_supervision_masks'].items() if v}=={f['service'] for f in row['targets']['frames']}
                for frame in row['targets']['frames']:
                    service=schemas[frame['service']]
                    names=[s['name'] for s in service['slots']]
                    intents=['NONE']+[i['name'] for i in service['intents']]
                    if frame['head_masks']['active_intent']:
                        assert intents[frame['active_intent_id']]==frame['active_intent'];known+=1
                    for head,target in [('requested_slots','requested_slots'),('published_slot_map_presence','published_slot_map_presence')]:
                        assert not frame['head_masks'][head] or len(frame[target])==len(names)
                    assert len(frame['belief_updates'])==len(names)
                    assert all(x['slot_id']==i for i,x in enumerate(frame['belief_updates']))
                    arity_count+=1
    # Actual primary TRAIN conversations: current/earlier annotation mutations,
    # future-text changes and sibling gold-service changes cannot affect inputs.
    source=json.loads((ROOT/'.cache/train__dialogues_001.json').read_bytes())
    causal=0
    for original in source[:32]:
        for index,turn in enumerate(original['turns']):
            if turn['speaker']!='USER':continue
            if index+1>=len(original['turns']):continue
            baseline=processor.input_for(processor.observed(original)[0],index)
            mutated=copy.deepcopy(original)
            for j,t in enumerate(mutated['turns']):
                t['frames']=[{'service':'DO_NOT_LEAK_GOLD_SERVICE','state':{'active_intent':'DO_NOT_LEAK_GOLD_INTENT','slot_values':{'secret':['DO_NOT_LEAK_GOLD_VALUE']}},'slots':[{'start':0,'exclusive_end':len(t['utterance'])}],'actions':[{'act':'DO_NOT_LEAK_GOLD_ACTION'}]}]
                if j>index:t['utterance']='Changed future utterance with secret 999999.'
            assert processor.input_for(processor.observed(mutated)[0],index)==baseline
            causal+=1
            if causal>=128:break
        if causal>=128:break
    # Real TRAIN minibatches have explicit reset boundaries. A fresh iterator
    # resets on its first example even if the previous iterator used same dialog.
    manifest_path=FULL/'manifest.json'
    sample=[];state={};previous=None;resets=0
    stream=batches.iter_batches(manifest_path,batch_size=128,seed=20261011)
    try:
        for number,batch in enumerate(stream,1):
            for row in batch:
                ident=row['ancestry']['dialogue_id']
                reset=row['sampling']['state_reset_before_row']
                assert reset==(previous!=ident)
                if reset:state.clear();resets+=1
                assert not state or state['dialogue_id']==ident
                state['dialogue_id']=ident;previous=ident
                assert batches.input_view(row)==row['input']
                assert 'targets' not in batches.input_view(row) and 'service' not in batches.input_view(row)
                sample.append(row['record_id'])
            if number==2:break
    finally:stream.close()
    repeat=[];stream=batches.iter_batches(manifest_path,batch_size=128,seed=20261011)
    try:
        for number,batch in enumerate(stream,1):
            if number==1:assert batch[0]['sampling']['state_reset_before_row']
            repeat.extend(r['record_id'] for r in batch)
            if number==2:break
    finally:stream.close()
    assert repeat==sample
    # Refuse heldout fitting before opening its shards or creating its index.
    rejected=False;stream=batches.iter_batches(manifest_path,split='EVAL')
    try:next(stream)
    except ValueError:rejected=True
    finally:stream.close()
    assert rejected
    # Packet/source/processor identity is still exactly the handed-off identity.
    assert digest(FULL/'manifest.json')=='7176ce8bf20c7e6adce899a276f7de0c042e0e33eb63999462264ca6c1843513'
    assert digest(ROOT/'process.py')==manifest['processor']['sha256']
    assert digest(ROOT/'collect.py')==manifest['collector']['sha256']
    assert digest(ROOT/'service-schema.json')==manifest['service_schema']['sha256']
    report={'status':'passed','manifest_sha256':digest(FULL/'manifest.json'),'full_shard_checks':full,'schema_frame_arity_checks':arity_count,'published_active_intent_labels_checked':known,
            'source_only_causality':{'actual_primary_USER_cases':causal,'current_and_prior_gold_frames_mutation':'input unchanged','future_utterance_mutation':'input unchanged','gold_span_mutation':'input unchanged','current_service_selector':'targets only; all-schema input protocol'},
            'actual_TRAIN_batches':{'batch_size':128,'batches':2,'examples':len(sample),'conversation_resets':resets,'sample_order_sha256':hashlib.sha256(processor.line(sample)).hexdigest(),'same_seed_order_reproduced':True,'fresh_iterator_state_reset':True,'heldout_stream_without_opt_in_rejected':True},
            'frozen_packet_rewritten':False,'model_fits':0,'model_evaluation_outcomes_read':0,'official_dev_test_read':False,
            'limits':{'privacy':'text-only heuristic redaction loses information; not certified universal anonymity','value_recoverability':'only unchanged values directly visible in sanitized observed window are supervised; other values remain unknown','DELETE':'never supervised without independent completeness certificate','partial_preview':'shared TRAIN source ancestry; not independent qualification; not used for fitting by this data worker','other_source_overlap':'not audited against historical v1/v2 or pretrained corpora; no independent novelty claim'}}
    (FULL/'freeze-validation.json').write_bytes(processor.encode(report))
    print(json.dumps({'status':'passed','manifest_sha256':report['manifest_sha256'],'actual_TRAIN_batches':report['actual_TRAIN_batches'],'source_causality_cases':causal,'schema_frame_checks':arity_count},sort_keys=True))


if __name__=='__main__':main()
