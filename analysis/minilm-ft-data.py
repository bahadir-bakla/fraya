"""Offline replayable MiniLM packet builder. Writes only its owned new directory.

Run from repository root: python analysis/minilm-ft-data.py
No external models, APIs, GPU, Git, or publisher-source mutations.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'research/customer-benchmark/minilm-finetune-v1'
BASE = ROOT / 'research/customer-benchmark'
DOMAIN = ['proposal','dispute','correction','current_affirm','current_withdraw','uncertain','reported_third_party']
AUX = ['AFFIRM','NEGATE','INFORM','REQUEST']
KEYS = {'id','group','split','source','input','domain_labels','domain_mask','aux_labels','aux_mask'}

def digest(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def read_json(path): return json.loads(pathlib.Path(path).read_text(encoding='utf-8-sig'))
def read_lines(path):
    with pathlib.Path(path).open(encoding='utf-8-sig') as f:
        for n,line in enumerate(f,1):
            if line.strip(): yield n,json.loads(line)
def encoded(x): return json.dumps(x,ensure_ascii=False,separators=(',',':'),sort_keys=True)
def observed_hash(row):
    # Runtime projection: current text plus the last two observed prior turns.
    # SGD has exactly zero/one prior SYSTEM turn, so its source projection is
    # unchanged. Role names are input fields, not source/target metadata.
    observed={'current_utterance':row['input']['current_utterance'],
              'previous_utterances':row['input']['previous_utterances'][-2:]}
    return hashlib.sha256(encoded(observed).encode()).hexdigest()
def relative(path): return pathlib.Path(path).relative_to(ROOT).as_posix()
def save_json(path,x): pathlib.Path(path).write_text(json.dumps(x,indent=2,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf8')

spec=importlib.util.spec_from_file_location('minilm_authored_templates',OUT/'templates.py')
T=importlib.util.module_from_spec(spec); spec.loader.exec_module(T)

def synthetic_row(rid,group,split,source,previous,current,positive,unknown=()):
    labels,masks=T.vectors(positive,unknown)
    return {'id':rid,'group':group,'split':split,'source':source,
      'input':{'current_utterance':current,'previous_utterances':previous},
      'domain_labels':labels,'domain_mask':masks,'aux_labels':[0]*4,'aux_mask':[False]*4}

def system(text): return [{'speaker':'ASSISTANT','text':text}]

def sgd_row(r,source):
    # This projection deliberately reads only observed fields. Current gold
    # actions are consulted below for loss targets and never rendered as text.
    prev=next((c for c in reversed(r['input']['earlier_context']) if c['speaker']=='SYSTEM'),None)
    acts=set(); frames=r['targets'].get('frames',[])
    complete=bool(frames) and all(bool(f.get('head_masks',{}).get('publisher_actions',False)) for f in frames)
    for frame in frames:
        acts.update(a['act'] for a in frame.get('actions',[]))
    return {'id':r['record_id'],'group':r['ancestry']['group_id'],'split':r['ancestry']['split'],
      'source':source,'input':{'current_utterance':r['input']['utterance'],
      'previous_utterances':system(prev['text']) if prev else []},
      'domain_labels':[0]*7,'domain_mask':[False]*7,
      'aux_labels':[int(a in acts) for a in AUX],
      # Positive action membership is known; absence requires the publisher
      # annotation-presence mask. Missing frames remain unknown, not negatives.
      'aux_mask':[bool(a in acts or complete) for a in AUX]}

def policy_topic(text):
    candidates=[('overdraft','overdraft fee'),('dispute','disputed transaction'),
      ('rebate','missing rebate'),('atm','ATM transaction'),('debit card','debit card charge'),
      ('wire','wire transfer'),('interest','account interest'),('saving','savings account'),
      ('checking','checking account'),('refund','refund payment'),('insurance','insurance payment'),
      ('flight','flight reservation payment'),('return','order refund'),('fee','account fee'),
      ('payment','account payment'),('transfer','account transfer'),('account','account balance')]
    lower=text.lower()
    return next((topic for needle,topic in candidates if needle in lower),'account service')

def policy_excerpt(text):
    # Licensed publisher policy is reference context, not fixture state. Never
    # include IDs, tool placeholders, task instructions, or expected actions.
    text=re.sub(r'\[[A-Z_]+\]','the referenced item',text)
    text=re.sub(r'\s+',' ',text).strip()
    return text[:320].rsplit(' ',1)[0]

POLICY_CASES=[
 ('own-offer','What payment, if any, do you personally propose?', 'I will pay {amount} toward the balance on {date}.',['proposal']),
 ('liability','What do you contest on the account?', 'That {topic} is not mine; I dispute responsibility for it.',['dispute']),
 ('term-repair','You mentioned {old_amount}. Was that the figure you meant?', 'I meant {amount}, not {old_amount}; correct that figure.',['correction']),
 ('admin-yes','Would you like an explanation of this account topic?', 'yes',['current_affirm']),
 ('readback-right','I have recorded only your request for an explanation. Is that correct?', 'right',['current_affirm']),
 ('revoke-yes','You previously allowed an automatic payment. Do you now revoke that permission?', 'yes',['current_affirm','current_withdraw']),
 ('revoke-no','You previously allowed an automatic payment. Should that permission stay active?', 'no',['current_withdraw']),
 ('first-no','This is my first request for permission to make a debit. Do you give permission?', 'no',[]),
 ('correct-short','I wrote that you meant savings, although we were discussing checking. Is that what you meant?', 'not that',['correction']),
 ('maybe-pay','Do you have a definite payment commitment?', 'If my wages arrive, I might pay {amount} on {date}; I am not sure.',['proposal','uncertain']),
 ('report','What did the other account holder say?', 'My sister said she would pay {amount} on {date}; I am only reporting her.',['reported_third_party']),
 ('hypothetical','Are you discussing an actual plan or an imagined example?', 'Suppose I paid {amount} on {date}; what would happen? It is only hypothetical.',['uncertain']),
 ('mixed','What is your own plan for the disputed balance?', 'I dispute that charge, but I will pay {amount} toward the other balance on {date}.',['dispute','proposal']),
 ('withdraw-manual','You previously approved automatic payment and discussed a manual alternative.', 'Withdraw my earlier debit permission. I will pay {amount} manually on {date}.',['current_withdraw','proposal']),
]

SCENARIO_CASES=[
 ('admin','Would you like an explanation before making any decision?', 'yes',['current_affirm']),
 ('hypothetical','Are you discussing an example rather than making a commitment?', 'yes',['current_affirm','uncertain']),
 ('report','Are you reporting someone else\'s request, without adopting it?', 'yes',['current_affirm','reported_third_party']),
 ('revoke','You earlier allowed us to proceed. Should that earlier permission remain active?', 'no',['current_withdraw']),
 ('initial','You have not granted permission. May I proceed?', 'no',[]),
 ('repair','I recorded cancellation, although you mentioned a modification. Is that what you meant?', 'not that',['correction']),
 ('offer','What payment do you personally offer for the remaining balance?', 'I will pay {amount} on {date}.',['proposal']),
 ('contest','What do you contest about the payment record?', 'That claimed payment did not happen. I dispute the record.',['dispute']),
 ('uncertain','Is your decision definite?', 'I might proceed if the refund is available, but I have not decided.',['uncertain']),
 ('relative','Whose decision are you describing?', 'My colleague said they would proceed. I am only passing on their words.',['reported_third_party']),
 ('replace','You proposed a payment on {old_date}.', 'I meant {date}; I will pay then instead.',['proposal','correction']),
 ('mixed','You discussed a disputed fee and a remaining balance.', 'I contest the fee, but I personally offer {amount} for the other balance.',['proposal','dispute']),
]

def scenario_topic(r):
    # Only scenario prose informs authoring. No publisher action-annotation file,
    # expected trajectory, DB fixture, or evaluator criteria is ever opened.
    instructions=r.get('generator_spec',{}).get('instructions',{})
    text=str(instructions.get('reason_for_call','')).lower()
    choices=[('exchange','an item exchange'),('cancel','a cancellation'),('return','an order return'),
      ('modify','a reservation modification'),('book','a booking'),('refund','a refund'),('baggage','baggage')]
    return next((topic for key,topic in choices if key in text),'an account service request')

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    sources={}; ancestry={}; counts=collections.defaultdict(collections.Counter)
    positive=collections.defaultdict(collections.Counter); masks=collections.defaultdict(collections.Counter)
    ids=set(); group_splits={}; input_splits=collections.defaultdict(set)
    inputs=collections.Counter(); source_inputs=collections.defaultdict(set)
    manifest=read_json(BASE/'day2-training-data/sgd/full-v1/manifest.json')
    tau_manifest=read_json(BASE/'tau-train/manifest.json')
    source_checks=[]; train_input_hashes=set(); excluded_holdout_aux=collections.Counter(); overlap_rows=[]
    def check(path,expected):
        actual=digest(path)
        if actual!=expected: raise ValueError(f'Source hash mismatch: {path}')
        source_checks.append({'path':relative(path),'sha256':actual})
    # Read and verify source manifests before payload use. Publish their pins.
    for output in tau_manifest['outputs']:
        if pathlib.Path(output['path']).name in {'train-scenario-specs.jsonl','train-policy-contexts.jsonl'}:
            check(ROOT/output['path'],output['sha256'])
    for license_file in manifest['license_files'].values():
        check(ROOT/license_file['path'],license_file['sha256'])
    split_plan=read_json(ROOT/manifest['split_plan']['path'])
    check(ROOT/manifest['split_plan']['path'],manifest['split_plan']['sha256'])
    sgd_sources={s['path']:s for s in manifest['source_files']}
    files={s:(OUT/f'{s.lower()}.jsonl').open('w',encoding='utf8',newline='\n') for s in ['TRAIN','CAL','EVAL']}
    def emit(row,kind,anc):
        if set(row)!=KEYS: raise ValueError('row schema keys')
        if row['id'] in ids: raise ValueError('duplicate id '+row['id'])
        ids.add(row['id']); split=row['split']; group=row['group']
        if group in group_splits and group_splits[group]!=split: raise ValueError('cross split group '+group)
        group_splits[group]=split
        if group not in ancestry: ancestry[group]={'group':group,'split':split,'kind':kind,'rows':0,**anc}
        ancestry[group]['rows']+=1
        ih=observed_hash(row); input_splits[ih].add(split); inputs[ih]+=1; source_inputs[kind].add(ih)
        counts[split][kind]+=1
        for label,value,mask in zip(DOMAIN,row['domain_labels'],row['domain_mask']):
            positive[split][label]+=int(value and mask); masks[split][label]+=int(mask)
        files[split].write(encoded(row)+'\n')
    try:
        # TRAIN first lets holdout collision masks be assigned without changing
        # a single frozen dialogue/source split or dropping a TRAIN example.
        for shard in sorted(manifest['outputs'],key=lambda s:(s['split']!='TRAIN',s['path'])):
            path=ROOT/shard['path']; check(path,shard['sha256'])
            n=0
            for _,r in read_lines(path):
                spath=r['ancestry']['source_file']; key='sgd:'+spath
                assert spath.startswith('train/')
                frozen=split_plan['dialogues'][r['ancestry']['dialogue_id']]
                assert frozen['split']==r['ancestry']['split'] and frozen['group_id']==r['ancestry']['group_id']
                if key not in sources:
                    original=sgd_sources[spath]
                    sources[key]={'publisher':'Google Research','dataset':'Schema-Guided Dialogue','license':manifest['source']['license'],
                      'publisher_partition':'TRAIN','original_local_partition_is_internal':True,'source_path':spath,
                      'source_url':original['url'],'source_sha256':original['sha256'],
                      'revision':manifest['source']['revision'],'synthetic':False,'observed_dataset_conversation':True,
                      'license_url':'https://creativecommons.org/licenses/by-sa/4.0/',
                      'local_license':relative(BASE/'day2-training-data/sgd/LICENSE.txt'),
                      'source_manifest':relative(BASE/'day2-training-data/sgd/full-v1/manifest.json'),
                      'record_locator':'id = original record_id; dialogue and turn are encoded in id; shard map in manifest.json'}
                row=sgd_row(r,key)
                ih=observed_hash(row)
                if row['split']=='TRAIN': train_input_hashes.add(ih)
                elif ih in train_input_hashes:
                    # Annotation remains in aux_labels; only holdout metric
                    # eligibility is masked for text already seen in TRAIN.
                    original_mask=row['aux_mask'][:]
                    row['aux_mask']=[False]*4
                    excluded_holdout_aux[row['split']]+=1
                    overlap_rows.append({'id':row['id'],'group':row['group'],'split':row['split'],
                      'source':row['source'],'runtime_observed_input_sha256':ih,
                      'mask_reason':'source_overlap: current text plus last two previous observed turns equals a TRAIN input',
                      'original_publisher_aux_mask':original_mask,'packet_aux_mask':[False]*4,
                      'publisher_aux_labels_retained':row['aux_labels']})
                emit(row,'sgd_aux',{'ancestry_policy':'original frozen closure group and split unchanged',
                    'dialogue_roots':[],'publisher_partition':'TRAIN'})
                d=r['ancestry']['dialogue_id']
                if d not in ancestry[row['group']]['dialogue_roots']: ancestry[row['group']]['dialogue_roots'].append(d)
                n+=1
            if n!=shard['rows']: raise ValueError('SGD shard count')
            print(f"SGD {path.name}: {n}",flush=True)
        if counts['TRAIN']['sgd_aux']!=132615: raise ValueError('full TRAIN required')
        # Existing authored engineering data, preserving its frozen groups and
        # splits and all original unknown masks. No remapping to model authority.
        rep=BASE/'repayment-semantic'; rep_manifest=read_json(rep/'manifest.json')
        sources['existing-authored']={'publisher':'workspace synthetic author','license':T.AUTHOR_LICENSE,
          'publisher_partition':'AUTHORED_INTERNAL','synthetic':True,'independently_adjudicated':False,
          'source_manifest':relative(rep/'manifest.json'),'source_manifest_sha256':digest(rep/'manifest.json'),
          'lineage_file':relative(rep/'ancestry.json'),'frozen_source_splits_preserved':True}
        for fname,split in [('train.jsonl','TRAIN'),('cal.jsonl','CAL'),('heldout.jsonl','EVAL')]:
            check(rep/fname,rep_manifest['outputs'][fname]['sha256'])
            for line,r in read_lines(rep/fname):
                row={'id':'existing:'+r['record_id'],'group':'existing:'+r['group_id'],'split':split,'source':'existing-authored',
                  'input':{'current_utterance':r['input']['current_utterance']['text'],
                    'previous_utterances':[{'speaker':'ASSISTANT' if u['speaker']=='SYSTEM' else u['speaker'],'text':u['text']} for u in r['input']['previous_utterances']]},
                  'domain_labels':[r['labels'][k] for k in DOMAIN],'domain_mask':[r['known_mask'][k] for k in DOMAIN],
                  'aux_labels':[0]*4,'aux_mask':[False]*4}
                emit(row,'existing_authored',{'source_file':relative(rep/fname),'template_root':r['group_id'],
                    'family_ids':[],'independence':'shared prior author; regression partition, not fresh gold'})
                fam=r['family_id']
                if fam not in ancestry[row['group']]['family_ids']: ancestry[row['group']]['family_ids'].append(fam)
        sources['new-authored']={'publisher':'user-authorized workspace author','license':T.AUTHOR_LICENSE,
          'publisher_partition':'AUTHORED_INTERNAL','synthetic':True,'source_path':relative(OUT/'templates.py'),
          'source_sha256':digest(OUT/'templates.py'),'independently_adjudicated':False,
          'independence':'engineering families; one shared author and label ontology, not human IID'}
        for split,families in [('TRAIN',T.TRAIN),('CAL',T.CAL),('EVAL',T.EVAL)]:
            for name,context,utterances,labels in families:
                group='new-authored:'+split.lower()+':'+name
                for si,slots in enumerate(T.SLOTS):
                    for ui,utterance in enumerate(utterances):
                        ambiguous={'unfinished-correction':['proposal'],
                          'unclear-referent':['proposal','correction','current_affirm','current_withdraw'],
                          'partial-unknown':['proposal','correction','current_affirm','current_withdraw'],
                          'cal-unknown-short':['proposal','dispute','correction','current_affirm','current_withdraw','reported_third_party'],
                          'ood-ambiguous-target':['proposal','dispute','correction','current_affirm','current_withdraw','reported_third_party'],
                          'ood-incomplete-switch':['proposal']}
                        row=synthetic_row(f'{group}:slot{si}:text{ui}',group,split,'new-authored',
                          system(context.format(**slots)),utterance.format(**slots),labels,ambiguous.get(name,()))
                        emit(row,'fresh_authored',{'template_root':name,'family':name,
                          'ancestry_policy':'all paraphrases, currency, date, amount and fictional name variants stay together',
                          'heldout_difficult_text':split=='EVAL','source_path':relative(OUT/'templates.py')})
        group='new-authored:train:short-context-contrasts'
        for ci,(context,current,labels) in enumerate(T.SHORT):
            for si,slots in enumerate(T.SLOTS):
                row=synthetic_row(f'{group}:case{ci}:slot{si}',group,'TRAIN','new-authored',system(context.format(**slots)),current,labels)
                emit(row,'fresh_authored',{'template_root':'short-context-contrasts','family':'short-context-contrasts',
                  'ancestry_policy':'all assistant-scope contrast descendants and synonymous short replies share one root',
                  'source_path':relative(OUT/'templates.py')})
        # Tau policies and scenarios are synthetic generation sources only. All
        # common recipe descendants are conservatively unioned into TRAIN roots.
        # Document count is reported separately from the single recipe family.
        tau=BASE/'tau-train'; tau_pin=tau_manifest['source_pin']; policy_count=0
        for line,r in read_lines(tau/'train-policy-contexts.jsonl'):
            text=r['input']['reference_text']; topic=policy_topic(text); key='tau-policy:'+r['id']; policy_count+=1
            sources[key]={'publisher':'Sierra Research','license':'MIT','publisher_partition':'TRAIN_SOURCE_TEXT_CONTEXT',
              'synthetic':True,'source_path':r['source_path'],'source_sha256':r['source_sha256'],
              'source_url':f"https://github.com/{tau_pin['repo']}/blob/{tau_pin['commit']}/{r['source_path']}",
              'revision':tau_pin['commit'],'packet_path':relative(tau/'train-policy-contexts.jsonl'),'packet_line':line,
              'context_id':r['id'],'document_root':r['group_root'],'context_sha256':r['text_sha256'],
              'template_root':'tau-policy-finance-semantics','instructions_are_not_observed_dialogue':True}
            group='tau-synthetic:policy-recipe-closure'
            for ci,(name,question,current,labels) in enumerate(POLICY_CASES):
                for si,slots in enumerate(T.SLOTS[:2]):
                    fmt={**slots,'topic':topic}
                    # The quote is public policy reference text; the subsequent
                    # question and current reply are newly authored synthetic.
                    ctx=f'We are discussing {topic}. The account guide says: "{policy_excerpt(text)}" '+question.format(**fmt)
                    row=synthetic_row(f'tau-policy:{line}:case{ci}:slot{si}',group,'TRAIN',key,system(ctx),current.format(**fmt),labels)
                    emit(row,'tau_policy_synthetic',{'template_root':'tau-policy-finance-semantics',
                      'ancestry_policy':'all shared template descendants and policy documents unioned into one TRAIN embargo family',
                      'independent_source_roots_claimed':0,'source_document_roots':[]})
            if r['group_root'] not in ancestry[group]['source_document_roots']: ancestry[group]['source_document_roots'].append(r['group_root'])
        scenario_count=0
        for line,r in read_lines(tau/'train-scenario-specs.jsonl'):
            if r['publisher_partition']!='TRAIN': raise ValueError('tau official TEST forbidden')
            scenario_count+=1; key='tau-scenario:'+r['id']; topic=scenario_topic(r)
            sources[key]={'publisher':'Sierra Research','license':'MIT','publisher_partition':'TRAIN','synthetic':True,
              'source_path':r['source_path'],'source_sha256':r['source_sha256'],'revision':r['source_commit'],
              'source_url':f"https://github.com/{tau_pin['repo']}/blob/{r['source_commit']}/{r['source_path']}",
              'packet_path':relative(tau/'train-scenario-specs.jsonl'),'packet_line':line,'scenario_id':r['id'],
              'scenario_object_sha256':r['source_task_object_sha256'],'document_root':r['group_root'],
              'template_root':'tau-scenario-scope-contrasts','instructions_are_not_observed_dialogue':True,
              'no_oracle_actions_used':True}
            group='tau-synthetic:scenario-recipe-closure'
            for ci,(name,question,current,labels) in enumerate(SCENARIO_CASES):
                for si,slots in enumerate(T.SLOTS[:2]):
                    ctx=f'We are discussing {topic} in {r["domain"]} customer service. '+question.format(**slots)
                    row=synthetic_row(f'tau-scenario:{r["id"]}:case{ci}:slot{si}',group,'TRAIN',key,system(ctx),current.format(**slots),labels)
                    emit(row,'tau_scenario_synthetic',{'template_root':'tau-scenario-scope-contrasts',
                      'ancestry_policy':'all common authoring recipes and official TRAIN scenario descendants unioned into one TRAIN embargo family',
                      'scenario_roots':[],'independent_source_roots_claimed':0})
            ancestry[group]['scenario_roots'].append(r['group_root'])
        if scenario_count!=103 or policy_count!=716: raise ValueError('tau source counts changed')
    finally:
        for f in files.values(): f.close()
    sources['new-authored']['generator_path']=relative(pathlib.Path(__file__))
    sources['new-authored']['generator_sha256']=digest(__file__)
    save_json(OUT/'sources.json',sources)
    with (OUT/'source-overlap.jsonl').open('w',encoding='utf8',newline='\n') as f:
        for r in overlap_rows: f.write(encoded(r)+'\n')
    with (OUT/'ancestry.jsonl').open('w',encoding='utf8',newline='\n') as f:
        for group,a in sorted(ancestry.items()): f.write(encoded(a)+'\n')
    cross_split={k:sorted(v) for k,v in input_splits.items() if len(v)>1}
    save_json(OUT/'observed-collision-audit.json',{'cross_split_unique_inputs':len(cross_split),
      'reason':'current USER plus previous SYSTEM projection may collide after shortening frozen 8-turn source windows; original groups/splits remain unchanged',
      'input_sha256_and_splits':cross_split,'no_independence_claim_for_projected_collisions':True})
    source_breakdown={s:dict(c) for s,c in counts.items()}
    outputs=[{'path':relative(OUT/f'{s.lower()}.jsonl'),'split':s,'rows':sum(counts[s].values()),
       'bytes':(OUT/f'{s.lower()}.jsonl').stat().st_size,'sha256':digest(OUT/f'{s.lower()}.jsonl')} for s in ['TRAIN','CAL','EVAL']]
    packet_bytes=sum(o['bytes'] for o in outputs)
    if packet_bytes>=120_000_000: raise ValueError(f'JSONL exceeds original 120MB cap: {packet_bytes}')
    m={'schema_version':'minilm-finetune-v1','schema':relative(OUT/'schema.json'),'domain_label_order':DOMAIN,'aux_label_order':AUX,
      'outputs':outputs,'jsonl_bytes':packet_bytes,'counts':source_breakdown,
      'domain_positive_rows':{s:dict(c) for s,c in positive.items()},'domain_known_elements':{s:dict(c) for s,c in masks.items()},
      'group_counts':dict(collections.Counter(group_splits.values())),
      'unique_observed_inputs_by_kind':{k:len(v) for k,v in source_inputs.items()},
      'duplicate_observed_rows':sum(v-1 for v in inputs.values()),'cross_split_projected_inputs':len(cross_split),
      'SGD_holdout_aux_masked_for_TRAIN_projection_collision':dict(excluded_holdout_aux),
      'source_overlap_mask_reasons':{'path':relative(OUT/'source-overlap.jsonl'),
        'rows':len(overlap_rows),'sha256':digest(OUT/'source-overlap.jsonl')},
      'report_strata':{'existing_authored':'DIAGNOSTIC: all 134 prior exposed source rows, preserving old TRAIN/CAL/EVAL',
        'fresh_authored_CAL':'NEW_SYNTHETIC_CAL: source=new-authored, split=CAL; 320 rows / 20 authored families',
        'fresh_authored_EVAL':'NEW_SYNTHETIC_OOD_EVAL: source=new-authored, split=EVAL; 384 rows / 24 authored families',
        'fresh_macro_grouping':'compute label and macro metrics separately on fresh authored EVAL groups; author-defined synthetic families, not human IID'},
      'fresh_authored_template_families':{'TRAIN':len(T.TRAIN)+1,'CAL':len(T.CAL),'EVAL':len(T.EVAL)},
      'tau_source_contexts':{'official_TRAIN_scenarios':scenario_count,'TRAIN_policy_chunks':policy_count,
        'policy_document_roots':len(ancestry['tau-synthetic:policy-recipe-closure']['source_document_roots']),
        'tau_synthetic_embargo_families':2,'independent_IID_roots_claimed':0},
      'source_checks':source_checks,'SGD_original_manifest_sha256':digest(BASE/'day2-training-data/sgd/full-v1/manifest.json'),
      'tau_original_manifest_sha256':digest(tau/'manifest.json'),
      'generator':{'path':relative(pathlib.Path(__file__)),'sha256':digest(__file__),
        'templates':relative(OUT/'templates.py'),'templates_sha256':digest(OUT/'templates.py'),'external_spend':0},
      'training_contract':{'all_SGD_TRAIN_rows_required_per_aux_epoch':132615,
        'input_allowlist':['input.current_utterance','input.previous_utterances[].speaker','input.previous_utterances[].text'],
        'never_encode':['id','source','group','split','domain_labels','domain_mask','aux_labels','aux_mask','sources.json','ancestry.jsonl'],
        'generic_AFFIRM_is_not_domain_authority':True,'false_mask_means_unknown':True,
        'tau_scenario_generation_is_synthetic':True,'official_TEST_tasks_used':0},
      'limitations':['Synthetic engineering labels are not independently adjudicated human gold.',
        'Families share an author, ontology and broad semantic patterns; family-disjoint is not human IID.',
        'Tau synthetic families are TRAIN-only; no task-blind Tau qualification claim.',
        'SGD CAL/EVAL are frozen internal partitions of publisher TRAIN, not publisher official dev/test.',
        'Short projected SGD inputs collide across frozen partitions; copied CAL/EVAL aux masks exclude inputs also present in TRAIN. Originals are unchanged.',
        '3000 genuinely diverse independent domain templates not achieved; source contexts, templates and variants are counted separately.',
        'current_affirm is semantic/admin agreement and never authentication or payment authority.']}
    save_json(OUT/'manifest.json',m)
    print(json.dumps({'outputs':outputs,'counts':source_breakdown,'bytes':packet_bytes,'families':m['fresh_authored_template_families']},indent=2),flush=True)
    return m

def validate():
    m=read_json(OUT/'manifest.json'); sources=read_json(OUT/'sources.json')
    groups={}; ids=set(); kind_counts=collections.defaultdict(collections.Counter); label_masks=collections.Counter()
    all_inputs=collections.defaultdict(set); domain_inputs=collections.defaultdict(set)
    contrast=collections.defaultdict(lambda:collections.defaultdict(set)); unexpected=[]
    for output in m['outputs']:
        path=ROOT/output['path']
        assert digest(path)==output['sha256'],'output hash'
        count=0
        for _,r in read_lines(path):
            assert set(r)==KEYS,'exact row schema'
            assert r['id'] not in ids,'unique id'; ids.add(r['id'])
            assert r['split']==output['split'],'row file split'
            assert groups.setdefault(r['group'],r['split'])==r['split'],'group disjoint'
            assert r['source'] in sources,'resolved provenance'
            assert set(r['input'])=={'current_utterance','previous_utterances'},'feature allowlist'
            assert isinstance(r['input']['current_utterance'],str)
            for u in r['input']['previous_utterances']:
                assert set(u)=={'speaker','text'} and u['speaker'] in {'ASSISTANT','USER'} and isinstance(u['text'],str)
            for name,n in [('domain_labels',7),('domain_mask',7),('aux_labels',4),('aux_mask',4)]:
                assert isinstance(r[name],list) and len(r[name])==n
                assert all(type(v) is bool if name.endswith('mask') else type(v) is int and v in (0,1) for v in r[name])
            if r['source'].startswith('sgd:'):
                assert not any(r['domain_mask']) and not any(r['domain_labels']),'generic semantic leakage'
                assert len(r['input']['previous_utterances'])<=1,'previous SYSTEM projection'
                kind_counts[r['split']]['sgd_aux']+=1
            else:
                assert not any(r['aux_mask']),'synthetic aux labels not fabricated'
                domain_inputs[observed_hash(r)].add(r['split'])
            for label,v,mask in zip(DOMAIN,r['domain_labels'],r['domain_mask']):
                label_masks['known_'+label]+=int(mask); label_masks['unknown_'+label]+=int(not mask)
            inp=encoded(r['input'])
            # Structural isolation plus clean lexical sentinels: no training
            # metadata wrappers, publisher frames or oracle instructions.
            for sentinel in ['domain_labels','domain_mask','aux_labels','head_masks','generator_spec','evaluation_criteria','source_task_object_sha256']:
                assert sentinel not in inp,'metadata in observed input'
            all_inputs[observed_hash(r)].add(r['split'])
            token=r['input']['current_utterance'].strip().lower()
            if token in {'yes','no','right','not that'} and any(r['domain_mask']):
                contrast[r['split']][token].add(tuple(r['domain_labels']))
            count+=1
        assert count==output['rows'],'output count'
    assert kind_counts['TRAIN']['sgd_aux']==132615
    assert kind_counts['CAL']['sgd_aux']==16072 and kind_counts['EVAL']['sgd_aux']==16295
    # No domain content is copied across the packet's training/holdout splits.
    domain_collisions={k:sorted(v) for k,v in domain_inputs.items() if len(v)>1}
    assert not domain_collisions,'cross split synthetic content collision'
    assert all(len(contrast['TRAIN'][token])>=3 for token in ['yes','no','right','not that'])
    for key,s in sources.items():
        if key.startswith('tau-scenario:'): assert s['publisher_partition']=='TRAIN'
    report={'status':'PASS','rows':len(ids),'hashes_verified':len(m['outputs']),
      'group_counts':dict(collections.Counter(groups.values())), 'schema_exact':True,
      'SGD_TRAIN_complete':kind_counts['TRAIN']['sgd_aux'],'SGD_original_splits_preserved':True,
      'all_generic_domain_masks_false':True,'masked_unknowns_retained':dict(label_masks),
      'domain_cross_split_exact_input_collisions':len(domain_collisions),
      'source_hashes_verified':len(m['source_checks']),
      'observed_input_allowlist_enforced':True,'labels_and_gold_metadata_absent_from_features':True,
      'short_token_distinct_label_vectors':{s:{k:len(v) for k,v in c.items()} for s,c in contrast.items()},
      'aux_projected_collision_caveat_count':sum(len(v)>1 for v in all_inputs.values()),
      'no_external_calls':True,'no_publisher_TEST_tasks':True,
      'scope':'packet structural and replay validation; not independent semantic adjudication or model qualification'}
    save_json(OUT/'validation.json',report)
    print(json.dumps(report,indent=2),flush=True)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--validate-only',action='store_true'); args=ap.parse_args()
    if not args.validate_only: build()
    validate()
