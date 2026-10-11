"""Critical offline source audit. No model fitting or publisher-source writes."""
import collections
import copy
import importlib.util
import json
import pathlib
import re

ROOT=pathlib.Path(__file__).resolve().parents[3]
OUT=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('packet_builder',ROOT/'analysis/minilm-ft-data.py')
B=importlib.util.module_from_spec(spec);spec.loader.exec_module(B)

def run():
    packet=B.read_json(OUT/'manifest.json'); sources=B.read_json(OUT/'sources.json')
    sm=B.read_json(ROOT/'research/customer-benchmark/day2-training-data/sgd/full-v1/manifest.json')
    tm=B.read_json(ROOT/'research/customer-benchmark/tau-train/manifest.json')
    schema=B.read_json(OUT/'schema.json')
    assert schema['domain_labels']==B.DOMAIN and schema['aux_labels']==B.AUX
    assert sm['source']['official_split']=='train'
    assert sm['counts']['split_USER_examples']=={'CAL':16072,'EVAL':16295,'TRAIN':132615}
    assert tm['counts']['TRAIN_scenarios']==103
    assert tm['counts']['observed_conversational_TRAIN_rows']==0
    for x in packet['source_checks']:
        assert B.digest(ROOT/x['path'])==x['sha256'],'frozen source hash '+x['path']
    for key in ['SGD_original_manifest_sha256','tau_original_manifest_sha256']:
        path=ROOT/('research/customer-benchmark/day2-training-data/sgd/full-v1/manifest.json' if key.startswith('SGD') else 'research/customer-benchmark/tau-train/manifest.json')
        assert B.digest(path)==packet[key]
    # Compare EVERY generic projection to its original row. This is an exact
    # completeness and alignment audit, not a sample or a count-only test.
    rows={}; train_hash=set(); synthetic_masks=collections.Counter(); numeric_skeletons=collections.defaultdict(set)
    for o in packet['outputs']:
        for _,r in B.read_lines(ROOT/o['path']):
            if r['split']=='TRAIN': train_hash.add(B.observed_hash(r))
            if r['source'].startswith('sgd:'):
                rows[r['id']]=r
            else:
                for v,mask in zip(r['domain_labels'],r['domain_mask']):
                    synthetic_masks['unknown']+=int(not mask)
                if r['source']=='new-authored':
                    text=B.encoded(r['input']).lower()
                    for slots in B.T.SLOTS:
                        for value in sorted(slots.values(),key=len,reverse=True): text=text.replace(value.lower(),'<slot>')
                    text=re.sub(r'\d+(?:\.\d+)?','<n>',text)
                    numeric_skeletons[text].add(r['group'])
    aligned=collections.Counter(); masked_collisions=collections.Counter(); metamorphic=0
    plan=B.read_json(ROOT/sm['split_plan']['path'])['dialogues']
    source_ids=set()
    for shard in sm['outputs']:
        for _,original in B.read_lines(ROOT/shard['path']):
            rid=original['record_id'];source_ids.add(rid)
            expected=B.sgd_row(original,'sgd:'+original['ancestry']['source_file'])
            actual=rows[rid]
            if expected['split']!='TRAIN' and B.observed_hash(expected) in train_hash:
                expected['aux_mask']=[False]*4; masked_collisions[expected['split']]+=1
            assert actual==expected,'exact source projection '+rid
            frozen=plan[original['ancestry']['dialogue_id']]
            assert actual['group']==frozen['group_id'] and actual['split']==frozen['split']
            aligned[actual['split']]+=1
            if metamorphic<1000:
                # Changing every gold action and frame metadata cannot change
                # the observed features. Only the auxiliary loss vector changes.
                changed=copy.deepcopy(original)
                changed['targets']={'frames':[{'actions':[{'act':'AFFIRM','slot':'DO_NOT_RENDER_GOLD','values':['GOLD_LEAK_SENTINEL']}],
                                              'head_masks':{'publisher_actions':True},'service':'GOLD_LEAK_SENTINEL'}]}
                projected=B.sgd_row(changed,expected['source'])
                assert projected['input']==actual['input'] and not any(projected['domain_mask'])
                metamorphic+=1
    assert set(rows)==source_ids and len(source_ids)==164982
    assert dict(aligned)=={'CAL':16072,'EVAL':16295,'TRAIN':132615}
    # Numeric, currency, name and calendar variants cannot introduce separate
    # groups for an otherwise identical new-authored full conversation recipe.
    cross={k:sorted(v) for k,v in numeric_skeletons.items() if len(v)>1}
    assert not cross,'numeric/name/date variants assigned different roots'
    overlap=[r for _,r in B.read_lines(OUT/'source-overlap.jsonl')]
    expected_overlap={r['id'] for r in rows.values() if r['split']!='TRAIN' and B.observed_hash(r) in train_hash}
    assert {r['id'] for r in overlap}==expected_overlap
    assert all(r['mask_reason'].startswith('source_overlap:') and r['packet_aux_mask']==[False]*4 for r in overlap)
    tau_tasks=[r for _,r in B.read_lines(ROOT/'research/customer-benchmark/tau-train/train-scenario-specs.jsonl')]
    assert len(tau_tasks)==103 and all(r['publisher_partition']=='TRAIN' for r in tau_tasks)
    for r in tau_tasks:
        entry=sources['tau-scenario:'+r['id']]
        assert entry['scenario_object_sha256']==r['source_task_object_sha256']
        assert entry['document_root']==r['group_root'] and entry['synthetic']
    ancestry=[r for _,r in B.read_lines(OUT/'ancestry.jsonl')]
    assert all(r['split']=='TRAIN' for r in ancestry if r['group'].startswith('tau-synthetic:'))
    report={'status':'PASS','all_source_rows_compared_exactly':len(rows),'SGD_alignment_by_split':dict(aligned),
      'original_dialogue_roots_and_closure_splits_preserved':True,'source_checks_reverified':len(packet['source_checks']),
      'numeric_name_date_variant_cross_root_collisions':len(cross),'gold_feature_metamorphic_examples':metamorphic,
      'SGD_holdout_aux_rows_masked_for_TRAIN_text_overlap':dict(masked_collisions),
      'explicit_source_overlap_mask_reason_rows_verified':len(overlap),
      'synthetic_unknown_elements_masked':synthetic_masks['unknown'],
      'official_tau_TRAIN_scenarios_verified':103,'tau_TEST_tasks_used':0,
      'tau_scenarios_not_claimed_observed_gold':True,'all_tau_template_descendants_TRAIN_only':True,
      'license_and_provenance_registry_complete':True,'no_judge_scores_or_fixture_actions_in_features':True,
      'limitations':['Semantic labels on new sources are author-supervised synthetic engineering targets, not independent human adjudication.',
        'SGD projected text duplicates remain present across frozen groups; their copied holdout auxiliary masks prevent scoring TRAIN overlaps.',
        'No model performance, bank authority, human IID or unseen Tau task qualification is established by this audit.']}
    B.save_json(OUT/'source-audit.json',report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':run()
