"""Replayable TRAIN/CAL engineering corpus. No models, eval files, GPU or Git.

python analysis/minilm-v2-data.py --fetch
python analysis/minilm-v2-data.py --validate-only
python analysis/minilm-v2-data.py                 # offline deterministic replay
Only the assigned v2 packet and the authorized raw-source cache are written.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import importlib.util
import json
import pathlib
import random
import re
import sys
import urllib.request

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'research/customer-benchmark/minilm-finetune-v2-data'
RAW = ROOT / 'ignoredlocal-runs/minilm-finetune-v2-sources'
OLD = ROOT / 'research/customer-benchmark/minilm-finetune-v1'
PARQUET_REV = 'ed58ac423a2f4121720918bf5301577edce4ffd3'
CARD_REV = 'ff6bd8e4b27c3543e4f8fe2108f32bb95a6f8740'
HUB = 'https://huggingface.co/datasets/AmazonScience/massive'
LIMIT = 30_000_000
SEED = 20261011
spec = importlib.util.spec_from_file_location('v2_families', OUT / 'families.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
KEYS = {'id','group','split','source','input','domain_labels','domain_mask','aux_labels','aux_mask'}

def enc(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def sha(x): return hashlib.sha256(x).hexdigest()
def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20), b''): h.update(b)
    return h.hexdigest()
def rel(p): return p.relative_to(ROOT).as_posix()
def save(name, x):
    (OUT/name).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf8')
def load(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def lines(p):
    with p.open(encoding='utf-8-sig') as f:
        for line in f:
            if line.strip(): yield json.loads(line)
def tokens(text): return re.findall(r"\w+|[^\w\s]",text,flags=re.UNICODE)

def fetch_sources():
    RAW.mkdir(parents=True,exist_ok=True)
    # The authorized cache is ignored without editing any shared root ignore file.
    (RAW/'.gitignore').write_text('*\n!.gitignore\n',encoding='utf8')
    entries=[]
    for name,url in [
        ('tr-TR-train.parquet',f'{HUB}/resolve/{PARQUET_REV}/tr-TR/train/0000.parquet'),
        ('publisher-README.md',f'{HUB}/resolve/{CARD_REV}/README.md')]:
        p=RAW/name
        if not p.exists():
            req=urllib.request.Request(url,headers={'User-Agent':'minilm-v2-source-research/1.0'})
            # No auth headers, cookies, credentials or redirected signed URLs are saved.
            with urllib.request.urlopen(req,timeout=25) as response:
                declared=int(response.headers.get('Content-Length','0'))
                used=sum(x.stat().st_size for x in RAW.iterdir() if x.is_file())
                if declared and declared+used>LIMIT: raise ValueError('30 MB source cap')
                data=response.read(LIMIT-used+1)
                if len(data)+used>LIMIT: raise ValueError('30 MB source cap')
            p.write_bytes(data)
        entries.append({'path':rel(p),'url':url,'bytes':p.stat().st_size,'sha256':digest(p)})
    card=(RAW/'publisher-README.md').read_text(encoding='utf8')
    start=card.find('Creative Commons Attribution 4.0 International Public License')
    if start<0: raise ValueError('publisher CC BY 4.0 text missing')
    license_text=card[start:].split('```',1)[0].strip()+'\n'
    (OUT/'LICENSE-MASSIVE.txt').write_text(license_text,encoding='utf8')
    lock={'dataset':'AmazonScience/MASSIVE','publisher':'Amazon.com Inc. or its affiliates',
      'publisher_partition':'train','locale':'tr-TR','license':'CC-BY-4.0',
      'license_url':'https://creativecommons.org/licenses/by/4.0/',
      'card_revision':CARD_REV,'parquet_conversion_revision':PARQUET_REV,
      'transport':'Hugging Face conversion branch in the official AmazonScience repository',
      'upstream':'https://github.com/alexa/massive',
      'downloaded_files':entries,'external_data_actually_available':True,
      'external_bytes':sum(x['bytes'] for x in entries),
      'maximum_source_cache_bytes':LIMIT,'only_TRAIN_corpus_downloaded':True}
    save('source-lock.json',lock)
    return lock

def external_data():
    lock_path=OUT/'source-lock.json'
    if not lock_path.exists(): return [], {'external_data_actually_available':False,'reason':'No successfully verified TRAIN source cache.'}
    lock=load(lock_path)
    if not lock.get('external_data_actually_available'): return [],lock
    for e in lock['downloaded_files']:
        p=ROOT/e['path']
        if not p.exists() or digest(p)!=e['sha256']: raise ValueError('source pin failed: '+e['path'])
    import pyarrow.parquet as pq
    # Publisher intents/scenarios retained as provenance only. No task-head mapping.
    rows=pq.read_table(RAW/'tr-TR-train.parquet',columns=['id','locale','partition','utt','intent','scenario']).to_pylist()
    assert len(rows)==11514, ('publisher TRAIN count',len(rows))
    assert all(r['partition']=='train' and r['locale']=='tr-TR' for r in rows)
    return rows,lock

LEXICAL_CANDIDATES=['hava','müzik','ışık','alarm','takvim','kahve','mutfak','kitap','yemek','radyo','film','park',
 'sabah','akşam','şarkı','haber','oda','saat','hafta','gün','şehir','yol','ses','pencere','telefon','ev','bugün','yarın',
 'liste','spor','oyun','tarif','otobüs','tren','deniz','yağmur','güneş','sıcak','soğuk','renk']

def lexical_dictionary(raw):
    result=[]
    for word in LEXICAL_CANDIDATES:
        witnesses=[{'publisher_id':str(r['id']),'utterance_sha256':sha(r['utt'].encode())}
            for r in raw if word in re.findall(r'\w+',r['utt'].lower())]
        if witnesses: result.append({'token':word,'source':'massive-tr-train','witnesses':witnesses,
            'use':'literal unrelated word-list in authored utterances; not a target label'})
    return result

CAL_CHATTER={
 'tr':[
  'Koridordaki duvar resmini incelerken resimdeki küçük teknenin gölgesini fark ettim ve hangi renkle boyandığını düşündüm.',
  'Eski bir haritaya bakıp vadinin etrafındaki tepelerin isimlerini okudum, ardından kâğıdı katlayıp dolabın üstüne bıraktım.',
  'Dikiş kutusundaki düğmeleri büyüklüklerine göre ayırdım, bir tanesi masanın altına yuvarlanınca sandalye çekip onu aradım.',
  'Küçük saksıyı balkonda farklı bir köşeye taşıdım, yaprakların ışığa dönmesini izleyip toprağın yüzeyine baktım.',
  'Çocukken öğrendiğim bir bilmecenin cevabını hatırlamaya çalıştım, aklıma gelmeyince başka bir hikâyenin sonunu düşündüm.',
  'Fotoğraf albümündeki sayfaları çevirdim, dağ yolundaki köprünün nasıl göründüğünü anlatan eski kareyi uzun süre inceledim.',
  'Bisikletin zilinin sesini denedim, ardından tekerleğin üstündeki tozu bezle silip arka kapının yanına yerleştirdim.',
  'Kumaşın desenindeki çizgileri sayarken kenarda farklı bir şekil olduğunu gördüm ve parçayı daha iyi ışıkta çevirdim.'
 ],
 'en':[
  'I studied a picture in the hallway, noticed the shadow of a small boat, and wondered which colors had been used.',
  'I looked at an old map, read the names of hills around a valley, folded the paper, and left it on a cupboard.',
  'I sorted buttons in a sewing box by size, and moved a chair to find one that had rolled under the table.',
  'I moved a flowerpot to another corner of the balcony, watched the leaves turn toward the light, and checked the soil.',
  'I tried to remember the answer to a childhood riddle, then thought about the ending of a different story.',
  'I turned the pages of a photo album and studied an old photograph showing a bridge along a mountain road.',
  'I tested a bicycle bell, wiped dust from the wheel with a cloth, and put the bicycle beside the back door.',
  'While counting the stripes in a fabric pattern I noticed another shape at the edge and turned it toward the light.'
 ]}

def slots(i):
    # Entirely fictional named entities; only their spoken occurrences are input.
    return {'name':['Deniz','Ece','Arda','Selin','Mert','Ada'][i%6],
      'product':['internet paketi','telefon hattı','kurs kaydı','kargo hizmeti','spor üyeliği','abonelik'][i%6],
      'amount':f'{135+37*i} TL','old_amount':f'{280+43*i} TL',
      'date':f'{1+i%27} Kasım 2026','old_date':f'{1+i%27} Ekim 2026'}

def previous_user(f,lang,s,i):
    k=f['family']
    if k in {'revoke-prior-contact'}:
        text='Bu numaramı arayabilirsiniz.' if lang=='tr' else 'You may call this number.'
    elif k in {'cancel-only-one-permission'}:
        text='Beni aramanıza ve otomatik tahsilata izin veriyorum.' if lang=='tr' else 'I allow both phone calls and automatic debits.'
    elif k in {'revoke-prior-debit','revoke-yes-answer','revoke-no-retention','switch-debit-to-manual',
        'maintain-permission-negated-stop','withdraw-and-dispute','revoke-with-undecided-replacement',
        'correction-withdraw-date-no-renewal','double-negation-revocation','self-quote-retracted','revoke-conditionally-not-yet'}:
        text='Otomatik tahsilata izin veriyorum.' if lang=='tr' else 'I give permission for the automatic debit.'
    elif k in {'repair-amount-commitment','repair-date-commitment','unfinished-term-repair',
        'ellipsis-amount-repair-offer','trailing-language-switch-repair'}:
        text=f"{s['old_date']} günü {s['old_amount']} ödeyeceğim." if lang=='tr' else f"I will pay {s['old_amount']} on {s['old_date']}."
    else:
        text=f"{s['name']} benim; {s['product']} hakkında konuşuyorum." if lang=='tr' else f"My name is {s['name']}; I am discussing {s['product']}."
    # A varying actual spoken detail increases dialogue uniqueness without hidden features.
    extra=(f" Konuşmaya saat 10:{i+8:02d} civarında başladım." if lang=='tr'
        else f" I began this conversation around 10:{i+8:02d}.")
    return text+extra

def chatter(split,lang,target,rng,lexical):
    parts=[]
    # CAL has no external source words or reused TRAIN chatter skeletons.
    if split=='TRAIN' and lang=='tr' and lexical:
        words=rng.sample([x['token'] for x in lexical],min(5,len(lexical)))
        parts.append('Konu dışında, bir ekranda '+', '.join(words)+' kelimelerini gördüm ve yazı tipine baktım.')
    bank=F.CHATTER[lang] if split=='TRAIN' else CAL_CHATTER[lang]
    while len(tokens(' '.join(parts)))<target:
        parts.append(rng.choice(bank))
    # Cut on whitespace; lower target is >=100, upper guard is <=700 lexical tokens.
    text=' '.join(parts)
    words=text.split()
    while len(tokens(' '.join(words)))>target: words.pop()
    return ' '.join(words).rstrip('.,;:')+'.'

def row_for(f,p,pi,i,lexical):
    s=slots(i); lang=p['language']; current=p['text'].format(**s)
    rid=f"v2:{f['split'].lower()}:{f['family']}:{pi}:{i}"
    rng=random.Random(int(sha(rid.encode())[:16],16))
    long=i%3==0
    prefix=''
    if long:
        target=[110,180,280,420,660][(i//3+pi)%5]
        prefix=chatter(f['split'],lang,target,rng,lexical)
        bridge=' Şimdi asıl söylediğim son kısma geleyim: ' if lang=='tr' else ' Now here is the final part about the actual issue: '
        prefix+=bridge
    elif i%4==1:
        prefix='Ya bir saniye, ' if lang=='tr' else 'Wait a moment, '
    elif i%4==2:
        prefix='Şöyle anlatayım: ' if lang=='tr' else 'Let me put it this way: '
    current=prefix+current
    # ASCII transcription is an explicit surface variant within the same family.
    ascii_variant=lang=='tr' and i%7==5
    previous=[{'speaker':'USER','text':previous_user(f,lang,s,i)},
      {'speaker':'ASSISTANT','text':f['contexts'][lang].format(**s)}]
    if ascii_variant:
        table=str.maketrans('çğıöşüÇĞİÖŞÜ','cgiosuCGIOSU')
        current=current.translate(table)
        previous=[{'speaker':x['speaker'],'text':x['text'].translate(table)} for x in previous]
    labels=[int(k in f['positive']) for k in F.DOMAIN]
    masks=[k not in f['unknown'] for k in F.DOMAIN]
    assert all(m or v==0 for v,m in zip(labels,masks))
    row={'id':rid,'group':'v2-family:'+f['closure_root'],'split':f['split'],'source':'v2-authored',
      'input':{'current_utterance':current,'previous_utterances':previous},
      'domain_labels':labels,'domain_mask':masks,
      'aux_labels':[int(k in f['aux']) for k in F.AUX],
      'aux_mask':[k in f['aux'] for k in F.AUX]}
    lineage={'id':rid,'group':row['group'],'rule_type':f['rule_type'],'recipe':f['family'],'pattern_index':pi,
      'slot_variant':i,'language':lang,'ascii_transcription':ascii_variant,
      'late_signal':long,'prefix_lexical_tokens':len(tokens(prefix)),'utterance_lexical_tokens':len(tokens(current)),
      'external_lexical_derivation':bool(long and f['split']=='TRAIN' and lang=='tr' and lexical),
      'targets':'explicit family recipe; not inferred from source intents'}
    return row,lineage

def parent_pin():
    # Only the preexisting TRAIN payload is read, solely to hash and count it.
    p=OLD/'train.jsonl'
    n=sum(1 for _ in lines(p))
    assert n==156341,('old parent TRAIN count',n)
    return {'path':rel(p),'sha256':digest(p),'rows':n,'purpose':'Separate full original TRAIN parent; do not replace or subsample.',
      'CAL_or_EVAL_payload_read':False}

def build(fetch=False):
    OUT.mkdir(parents=True,exist_ok=True)
    if fetch:
        try: fetch_sources()
        except Exception as e:
            if not (OUT/'source-lock.json').exists():
                save('source-lock.json',{'external_data_actually_available':False,'reason':type(e).__name__+': '+str(e)[:200],
                    'only_TRAIN_corpus_requested':True})
            print('External fetch could not complete; using verified cache or authored synthetic data.',flush=True)
    raw,lock=external_data()
    lexical=lexical_dictionary(raw)
    save('lexical-dictionary.json',{'source_partition':'publisher TRAIN only','entries':lexical,
      'payment_target_mapping':None,'targetlabels_are':'engineering labels in families.py; never publisher intent labels'})
    counts=collections.Counter(); ancestry={}
    handles={s:(OUT/(s.lower()+'.jsonl')).open('w',encoding='utf8',newline='\n') for s in ['TRAIN','CAL']}
    with (OUT/'row-provenance.jsonl').open('w',encoding='utf8',newline='\n') as prov:
        try:
            for f in F.FAMILIES:
                nvariants=48 if f['split']=='TRAIN' else 8
                for pi,p in enumerate(f['patterns']):
                    for i in range(nvariants):
                        row,meta=row_for(f,p,pi,i,lexical)
                        handles[f['split']].write(enc(row)+'\n'); prov.write(enc(meta)+'\n')
                        counts[f['split']]+=1
                group='v2-family:'+f['closure_root']
                if group not in ancestry:
                    ancestry[group]={'group':group,'split':f['split'],'rule_type':f['rule_type'],
                      'rows':0,'recipes':[],'closure':['all patterns','all languages',
                        'all amounts/dates/names/products','all long chatter variants','all ASCII transcription variants',
                        'resource/polarity/ellipsis/language-switch descendants from CLOSURE'],
                      'independence':'reserved engineering root, shared author and ontology; not IID or independently adjudicated'}
                ancestry[group]['rows']+=5*nvariants
                ancestry[group]['recipes'].append({'key':f['family'],'recipe_sha256':sha(enc(f).encode()),
                    'positive':f['positive'],'unknown':f['unknown']})
        finally:
            for h in handles.values(): h.close()
    (OUT/'ancestry.jsonl').write_text(''.join(enc(x)+'\n' for x in ancestry.values()),encoding='utf8')
    # An all-unknown reference bank is separate from supervised training. Deduplicate literal inputs.
    unique={}
    for r in raw:
        text=r['utt'].strip(); unique.setdefault(text,[]).append(r)
    with (OUT/'lexical-unknown.jsonl').open('w',encoding='utf8',newline='\n') as output, \
         (OUT/'publisher-train-lineage.jsonl').open('w',encoding='utf8',newline='\n') as prov:
        for text,originals in sorted(unique.items()):
            h=sha(text.encode()); group='massive-train-text:'+h
            row={'id':'massive-train:'+h,'group':group,'split':'TRAIN','source':'massive-tr-train',
              'input':{'current_utterance':text,'previous_utterances':[]},
              'domain_labels':[0]*7,'domain_mask':[False]*7,'aux_labels':[0]*4,'aux_mask':[False]*4}
            output.write(enc(row)+'\n')
            prov.write(enc({'id':row['id'],'group':group,'publisher_partition':'train','locale':'tr-TR',
              'publisher_records':[{'id':str(r['id']),'intent':r['intent'],'scenario':r['scenario']} for r in originals],
              'use':'provenance only; no finance permission or auxiliary mapping'})+'\n')
    sources={'v2-authored':{'publisher':'user-authorized engineering author','synthetic':True,
      'license':'LicenseRef-User-Authorized-Synthetic-RD','target_authority':'explicit recipe in families.py',
      'human_gold':False,'IID':False,'external_words_derived_only_from':'lexical-dictionary.json TRAIN witnesses'},
      'massive-tr-train':{**lock,'task_head_annotations':'none; all 7+4 task heads unknown',
        'publisher_intents_are_not_payment_labels':True,'synthetic':False}}
    save('sources.json',sources)
    (OUT/'NOTICE.txt').write_text(
      'MASSIVE public TRAIN source: Copyright Amazon.com Inc. or its affiliates.\n'
      'Dataset: https://huggingface.co/datasets/AmazonScience/massive\n'
      'Upstream publisher project: https://github.com/alexa/massive\n'
      'CC BY 4.0: https://creativecommons.org/licenses/by/4.0/\n'
      'Publisher licence text is retained in LICENSE-MASSIVE.txt and pinned publisher-README.md.\n'
      'FitzGerald, Jack, et al. 2023. MASSIVE: A 1M-Example Multilingual Natural Language\n'
      'Understanding Dataset with 51 Typologically-Diverse Languages. ACL 2023, pp. 4277-4302.\n'
      'https://aclanthology.org/2023.acl-long.235/ DOI: 10.18653/v1/2023.acl-long.235\n'
      'Modifications: publisher TRAIN parquet projected to current text and deduplicated by text;\n'
      'publisher id/intent/scenario retained only in separate provenance, with 7+4 unknown masks.\n'
      'A witnessed dictionary of literal Turkish words supports authored unrelated chatter.\n'
      'All finance-domain and selected auxiliary targets are engineered, not publisher labels.\n'
      'No publisher endorsement, repayment ground-truth claim, or natural-customer transcript claim.\n'
      'Authored contributions: LicenseRef-User-Authorized-Synthetic-RD; publisher components remain CC BY 4.0.\n',encoding='utf8')
    save('schema.json',{'schema_version':'minilm-finetune-v2-data','row_keys':sorted(KEYS),
      'domain_labels':F.DOMAIN,'aux_labels':F.AUX,'dimensions':{'domain_labels':7,'domain_mask':7,'aux_labels':4,'aux_mask':4},
      'input':{'current_utterance':'observed current USER text','previous_utterances':'zero to two observed turns, chronological order; role USER/ASSISTANT only'},
      'mask':'False = unknown, stored label must be zero; never treat unknown as a negative.',
      'semantic_scope':{'proposal':'own payment offer, including explicitly conditional proposals',
        'dispute':'own contest of liability, charge or payment record',
        'correction':'current explicit repair of earlier text/interpretation',
        'current_affirm':'own current affirmative response, including administrative assent; NEVER payment authority',
        'current_withdraw':'own current withdrawal of previously granted permission; first refusal is not withdrawal',
        'uncertain':'expressed uncertainty or explicitly hypothetical/counterfactual condition',
        'reported_third_party':'reports another speaker; a quotation does not automatically imply own assent'},
      'supervised_files':['train.jsonl','cal.jsonl'],'reference_only_files':['lexical-unknown.jsonl'],
      'all_unknown_row_policy':'Reference-only: exclude from supervised minibatches unless a separately specified unsupervised objective is introduced.',
      'runtime_projection':'input only; never id/group/source/labels/masks or row-provenance',
      'long_text':'Lexical token counts use Unicode words and punctuation, not MiniLM WordPiece. Tail preservation must be addressed by trainer; head truncation can erase the correction.'})
    parent=parent_pin()
    save('training-plan.json',{'parents':[parent],
      'domain_addition':{'path':rel(OUT/'train.jsonl'),'rows':counts['TRAIN']},
      'combined_TRAIN_rows':parent['rows']+counts['TRAIN'],
      'CAL':{'path':rel(OUT/'cal.jsonl'),'rows':counts['CAL'],'do_not_train':True},
      'publisher_unknown_bank_in_supervised_training':False,
      'no_model_changes_or_training_executed':True,'spend_usd':0,
      'long_sequence_caveat':'At short sequence limits, retain late current-utterance content plus both prior observed roles. This packet does not claim the current trainer does so.'})
    report=validate()
    save('manifest.json',{'schema_version':'minilm-finetune-v2-data','seed':SEED,'counts':dict(counts),
      'family_counts':dict(collections.Counter(x['split'] for x in ancestry.values())),
      'recipe_counts':dict(collections.Counter(f['split'] for f in F.FAMILIES)),
      'parent_TRAIN':parent,'public_raw_TRAIN_rows':len(raw),'public_unique_unknown_rows':len(unique),
      'external_data_actually_available':bool(raw),'external_corpus_bytes':lock.get('external_bytes',0),
      'source_lock_sha256':digest(OUT/'source-lock.json') if (OUT/'source-lock.json').exists() else None,
      'external_is_payment_gold':False,'human_gold':False,'IID':False,
      'known_corpus_limits':'Combinatorial authored rows; CAL rules share an author and ontology. No natural Turkish repayment transcript collection, tokenizer-length guarantee, or model-quality claim.',
      'never_opened':['new independent EVAL author corpus','model predictions','private customer data','official test/dev corpus payloads','old diagnostic failure pack'],
      'validation_status':report['status']})
    write_handoff(report,lock,parent,len(raw),len(unique),len(lexical))
    freeze()
    print(enc({'counts':dict(counts),'families':dict(collections.Counter(x['split'] for x in ancestry.values())),
      'raw_TRAIN':len(raw),'unique_unknown_reference':len(unique),'validation':report['status']}),flush=True)

def validate():
    ids=set(); input_hashes={}; groups={}; counters=collections.defaultdict(collections.Counter)
    positives=collections.defaultdict(collections.Counter); known=collections.defaultdict(collections.Counter)
    aux_known=collections.defaultdict(collections.Counter); family_counts=collections.defaultdict(set)
    metas={r['id']:r for r in lines(OUT/'row-provenance.jsonl')}; long_lengths=collections.defaultdict(list)
    late_corrections=collections.Counter({'TRAIN':0,'CAL':0})
    ancestry={r['group']:r for r in lines(OUT/'ancestry.jsonl')}
    actual_family_counts=collections.Counter()
    for fname,expected in [('train.jsonl','TRAIN'),('cal.jsonl','CAL'),('lexical-unknown.jsonl','TRAIN')]:
        for row in lines(OUT/fname):
            assert set(row)==KEYS and row['split']==expected
            assert row['id'] not in ids; ids.add(row['id'])
            assert set(row['input'])=={'current_utterance','previous_utterances'}
            inp=row['input']; assert isinstance(inp['current_utterance'],str) and inp['current_utterance'].strip()
            assert 0<=len(inp['previous_utterances'])<=2
            for turn in inp['previous_utterances']:
                assert set(turn)=={'speaker','text'} and turn['speaker'] in {'USER','ASSISTANT'}
                assert isinstance(turn['text'],str) and turn['text'].strip()
            for label,mask,n in [('domain_labels','domain_mask',7),('aux_labels','aux_mask',4)]:
                assert len(row[label])==len(row[mask])==n
                assert all(type(v)==int and v in [0,1] for v in row[label])
                assert all(type(m)==bool for m in row[mask])
                assert all(m or v==0 for v,m in zip(row[label],row[mask]))
            g=row['group']; assert g not in groups or groups[g]==expected; groups[g]=expected
            h=sha(enc(inp).encode()); assert h not in input_hashes,('duplicate observed input',row['id'],input_hashes.get(h))
            input_hashes[h]=row['id']; counters[fname]['rows']+=1
            if fname=='lexical-unknown.jsonl':
                assert not any(row['domain_mask']+row['aux_mask'])
                continue
            assert any(row['domain_mask']), 'unlabelled supervised row'
            assert len(inp['previous_utterances'])==2
            assert [t['speaker'] for t in inp['previous_utterances']]==['USER','ASSISTANT']
            assert g in ancestry and ancestry[g]['split']==expected
            actual_family_counts[g]+=1; family_counts[expected].add(g)
            meta=metas[row['id']]; assert meta['group']==g and meta['rule_type']==ancestry[g]['rule_type']
            family=next(f for f in F.FAMILIES if f['family']==meta['recipe'])
            assert 'v2-family:'+family['closure_root']==g
            expected_signal=family['patterns'][meta['pattern_index']]['text'].format(**slots(meta['slot_variant']))
            if meta['ascii_transcription']:
                expected_signal=expected_signal.translate(str.maketrans('çğıöşüÇĞİÖŞÜ','cgiosuCGIOSU'))
            assert inp['current_utterance'].endswith(expected_signal), 'final semantic signal changed or disappeared'
            assert row['domain_labels']==[int(k in family['positive']) for k in F.DOMAIN]
            assert row['domain_mask']==[k not in family['unknown'] for k in F.DOMAIN]
            for k,v,m in zip(F.DOMAIN,row['domain_labels'],row['domain_mask']):
                positives[expected][k]+=int(v and m); known[expected][k]+=int(m)
            for k,m in zip(F.AUX,row['aux_mask']): aux_known[expected][k]+=int(m)
            counters[fname][meta['language']]+=1
            counters[fname]['ascii_transcription']+=int(meta['ascii_transcription'])
            if meta['late_signal']:
                assert 100<=meta['prefix_lexical_tokens']<=700
                long_lengths[expected].append(meta['prefix_lexical_tokens'])
                late_corrections[expected]+=row['domain_labels'][2]
            if expected=='CAL': assert not meta['external_lexical_derivation']
    assert family_counts['TRAIN'].isdisjoint(family_counts['CAL'])
    assert len(family_counts['TRAIN'])>=40 and len(family_counts['CAL'])>=12
    assert 10000<=counters['train.jsonl']['rows']<=20000 and counters['cal.jsonl']['rows']>=400
    assert all(actual_family_counts[g]==a['rows'] for g,a in ancestry.items())
    assert len(metas)==counters['train.jsonl']['rows']+counters['cal.jsonl']['rows']
    # Compatibility and exact-observed-input independence against the full old TRAIN
    # parent only. No old/new holdout corpus is opened.
    old_schema=load(OLD/'schema.json')
    assert old_schema['domain_labels']==F.DOMAIN and old_schema['aux_labels']==F.AUX
    assert set(old_schema['row_keys'])==KEYS
    new_supervised={sha(enc(r['input']).encode()):(r['id'],r['split'])
      for fname in ['train.jsonl','cal.jsonl'] for r in lines(OUT/fname)}
    parent_overlap=collections.Counter({'TRAIN':0,'CAL':0})
    for row in lines(OLD/'train.jsonl'):
        inp={'current_utterance':row['input']['current_utterance'],
             'previous_utterances':row['input']['previous_utterances'][-2:]}
        h=sha(enc(inp).encode())
        if h in new_supervised: parent_overlap[new_supervised[h][1]]+=1
    assert not any(parent_overlap.values()),('old TRAIN observed projection collision',dict(parent_overlap))
    raw,source_lock=external_data()
    if raw:
        assert len({r['utt'].strip() for r in raw})==counters['lexical-unknown.jsonl']['rows']
    if RAW.exists(): assert sum(p.stat().st_size for p in RAW.iterdir() if p.is_file())<=LIMIT
    report={'status':'PASS','counts':{k:dict(v) for k,v in counters.items()},
      'domain_positive_rows':{k:dict(v) for k,v in positives.items()},
      'domain_known_elements':{k:dict(v) for k,v in known.items()},
      'aux_known_elements':{k:dict(v) for k,v in aux_known.items()},
      'families':{k:len(v) for k,v in family_counts.items()},
      'old_full_TRAIN_observed_projection_overlap':dict(parent_overlap),
      'late_correction_positive_rows':dict(late_corrections),
      'late_signal_prefix_lexical_tokens':{k:{'rows':len(v),'min':min(v),'max':max(v)} for k,v in long_lengths.items()},
      'checks':{'unique_ids':True,'unique_observed_inputs':True,'group_split_closure':True,
        'language_pattern_slot_closure':True,'recipe_target_consistency':True,'7_7_4_4_dimensions':True,
        'unknown_zero_placeholders':True,'all_unknown_excluded_from_supervised_rows':True,
        'only_two_observed_prior_turns':True,'CAL_no_external_source_derivatives':True,
        'old_core_schema_compatible':True,'old_TRAIN_exact_input_disjoint':True,
        'verified_public_source_pins':bool(raw),'source_download_under_30MB':True,
        'final_semantic_signal_preserved_in_every_current_utterance':True},
      'limits':'Automated schema/closure/recipe checks, not independent semantic adjudication or model evaluation.'}
    save('validation.json',report)
    return report

def write_handoff(report,lock,parent,raw_count,unique_count,terms):
    train_n=report['counts']['train.jsonl']['rows']; cal_n=report['counts']['cal.jsonl']['rows']
    analysis={'status':'PASS','dataset':rel(OUT),'supervised_TRAIN_rows':train_n,'CAL_rows':cal_n,
      'closure_families':report['families'],'language_counts':{
        'TRAIN':{k:report['counts']['train.jsonl'][k] for k in ['tr','en']},
        'CAL':{k:report['counts']['cal.jsonl'][k] for k in ['tr','en']}},
      'late_signal_prefix_lexical_tokens':report['late_signal_prefix_lexical_tokens'],
      'late_correction_positive_rows':report['late_correction_positive_rows'],
      'source':lock,'publisher_TRAIN_rows':raw_count,'deduplicated_unknown_reference_rows':unique_count,
      'witnessed_lexical_terms':terms,'parent_TRAIN':parent,'combined_TRAIN_rows':parent['rows']+train_n,
      'validation':report,'cost_usd':0,'model_training_executed':False,
      'inference_from_source':'Only literal word occurrence is inferred; finance labels come solely from explicit authored recipes.',
      'source_selection':[
        {'url':HUB,'role':'Official AmazonScience dataset and licence'},
        {'url':'https://github.com/alexa/massive','role':'Publisher corpus description; full mixed-partition tarball intentionally not downloaded'},
        {'url':'https://aclanthology.org/2023.acl-long.235/','role':'Primary dataset paper and attribution'}],
      'limitations':['Engineered combinatorial corpus, not human gold or IID.',
        'CAL is engineering-family-disjoint, with shared author and ontology.',
        'Counts of words/punctuation are lexical tokens, not measured MiniLM WordPiece tokens.',
        'Head-only truncation can remove late corrections; trainer must preserve current-utterance tail and prior roles.',
        'Public raw intent annotations supply no repayment/payment-permission labels.',
        'Unknown reference bank contributes no supervised loss and is excluded from the TRAIN parent/addition plan.']}
    (ROOT/'analysis/minilm-v2-data.json').write_text(json.dumps(analysis,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf8')
    text=(f'MiniLM v2 data: PASS\n'
      f'Addition: {train_n:,} labelled engineered TRAIN rows, {cal_n:,} CAL rows.\n'
      f'Conservative roots: {report["families"]["TRAIN"]} TRAIN / {report["families"]["CAL"]} CAL.\n'
      f'TRAIN language variants: {report["counts"]["train.jsonl"]["tr"]:,} Turkish and '
      f'{report["counts"]["train.jsonl"]["en"]:,} English (including explicit code-switch variants).\n'
      f'Late-signal rows: {report["late_signal_prefix_lexical_tokens"]["TRAIN"]["rows"]:,} TRAIN / '
      f'{report["late_signal_prefix_lexical_tokens"]["CAL"]["rows"]:,} CAL; Unicode word/punctuation counts are '
      '117-672 in TRAIN and 118-672 in CAL, not MiniLM WordPiece measurements.\n'
      f'Of the late-signal rows, explicit correction positives: {report["late_correction_positive_rows"]["TRAIN"]:,} TRAIN / '
      f'{report["late_correction_positive_rows"]["CAL"]:,} CAL.\n'
      f'Public source actually collected: {raw_count:,} Amazon MASSIVE tr-TR publisher TRAIN rows; '
      f'{lock.get("external_bytes",0):,} bytes including publisher README; CC BY 4.0.\n'
      f'Unknown reference bank: {unique_count:,} unique public utterances; all task masks false, excluded from supervised training.\n'
      f'Lexical derivation: {terms} witnessed Turkish terms, used literally in unrelated TRAIN chatter only.\n'
      f'Old full TRAIN parent: {parent["rows"]:,} rows, separately retained and hashed; combined plan '
      f'{parent["rows"]+train_n:,} rows. CAL is excluded from training.\n'
      'Exact 7/7/4/4 core schema; current text + previous USER and ASSISTANT turns only.\n'
      'PASS: input/id uniqueness, split closure, recipe consistency, masks/placeholders, all-unknown row policy.\n'
      'Resource, question-polarity, ellipsis and language-switch siblings are merged in CLOSURE; '
      'all descendants remain in the same split. Twelve CAL roots have separate rules and separate chatter.\n'
      'Targets distinguish own offers, contested debts and paid records, explicit corrections, current administrative assent, '
      'revocation of prior permission, uncertainty, and reports of others. Assent never grants payment authority.\n'
      'Short first refusals are not withdrawal; quoted yes is not personal assent; completed payment is not a future offer.\n'
      'Ambiguous referents/unfinished corrections have unknown masks. Auxiliary labels are sparse authored positive membership; '
      'unannotated auxiliary absence remains unknown. No fresh auxiliary CAL supervision is claimed.\n'
      'This corpus is authored engineering data. It is not independent human gold, an IID sample, '
      'or a natural Turkish repayment transcript corpus; no model-quality result is claimed.\n'
      'Do not head-truncate long examples: a late correction may otherwise disappear. '
      'Trainer input must preserve the current-utterance tail and both observed prior roles.\n'
      'Replay from repository root: python analysis/minilm-v2-data.py (offline cached source).\n'
      'Fetch on a new machine: python analysis/minilm-v2-data.py --fetch; only two pinned publisher files, 30 MB cap.\n'
      'Validation: python analysis/minilm-v2-data.py --validate-only. Freeze pins are in freeze.json.\n'
      'Pin verification: python analysis/minilm-v2-data.py --verify-freeze.\n'
      'Required replay dependency: Python 3.11+ and pyarrow; no model downloads or remote execution.\n'
      'No private customers, independent EVAL files, predictions, test/dev corpus, or old failure-pack wording were read.\n'
      'No GPU training, Modal/platform use, Git operation, model-source edits or spending. Cost: USD 0.\n'
      'Sources: https://huggingface.co/datasets/AmazonScience/massive ; https://github.com/alexa/massive ; '
      'https://aclanthology.org/2023.acl-long.235/\n')
    (OUT/'HANDOFF.txt').write_text(text,encoding='utf8')
    (ROOT/'analysis/minilm-v2-data.txt').write_text(text,encoding='utf8')

def freeze():
    names=['train.jsonl','cal.jsonl','lexical-unknown.jsonl','row-provenance.jsonl','ancestry.jsonl',
        'publisher-train-lineage.jsonl','schema.json','sources.json','source-lock.json','lexical-dictionary.json',
        'manifest.json','training-plan.json','validation.json','families.py','LICENSE-MASSIVE.txt','NOTICE.txt','HANDOFF.txt']
    files=[OUT/n for n in names if (OUT/n).exists()]+[pathlib.Path(__file__).resolve(),
        ROOT/'analysis/minilm-v2-data.json',ROOT/'analysis/minilm-v2-data.txt']
    save('freeze.json',{'schema_version':'minilm-finetune-v2-data','files':[{'path':rel(p),'bytes':p.stat().st_size,
        'sha256':digest(p)} for p in files],'purpose':'Immutable content pins; rerun offline and compare hashes.',
        'row_core_contract':'7 domain labels / 7 masks / 4 auxiliary labels / 4 masks'})

def verify_freeze():
    frozen=load(OUT/'freeze.json')
    for entry in frozen['files']:
        p=ROOT/entry['path']
        assert p.exists() and p.stat().st_size==entry['bytes'] and digest(p)==entry['sha256'],entry['path']
    for entry in load(OUT/'source-lock.json').get('downloaded_files',[]):
        assert digest(ROOT/entry['path'])==entry['sha256'],entry['path']
    return {'status':'PASS','packet_files_verified':len(frozen['files']),
        'raw_source_files_verified':len(load(OUT/'source-lock.json').get('downloaded_files',[]))}

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--fetch',action='store_true'); ap.add_argument('--validate-only',action='store_true')
    ap.add_argument('--verify-freeze',action='store_true')
    args=ap.parse_args()
    if args.verify_freeze: print(enc(verify_freeze()))
    elif args.validate_only: print(enc(validate()))
    else: build(args.fetch)
