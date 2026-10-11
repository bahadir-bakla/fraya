"""New fictional TRAIN acquisition; no runtime imports or legacy example reads."""
import hashlib
import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CONTRACT = ROOT / 'analysis/night-learned-dialogue.v5.next-data-interface.json'
ORIGINAL = ROOT / 'research/customer-benchmark/learned-dialogue-data.schema.json'
TEST = ROOT / 'integrations/customer-datasets/test_semantic_v6_peer_extension.py'
REPORT = ROOT / 'analysis/night-semantic-v6-peer-extension.json'
REPORT_TEXT = ROOT / 'analysis/night-semantic-v6-peer-extension.txt'

def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def sha(x):
    return hashlib.sha256(x).hexdigest()

def dump(path, x):
    path.write_bytes((json.dumps(x, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8'))

def span(text, start, end, field):
    assert 0 <= start < end <= len(text)
    return dict(raw_field_path=field, offset_unit='python_unicode_codepoints', char_start=start, char_end=end,
                text=text[start:end], utf8_byte_start=len(text[:start].encode('utf-8')),
                utf8_byte_end=len(text[:end].encode('utf-8')))

# Recipes and nominations are parent-only. No copied source exemplars.
# skeleton, ancestors, targets, question role, explanation, three utterances, author nomination
ADMIN = [
 ('ask composition of displayed balance', ['amount-composition-inquiry'], [0], 'payment',
  'The customer has heard a generic card figure and asks what its components mean.', [
  'That figure has made my stomach drop. What is included in the card balance you just mentioned?',
  'I’m trying to keep calm; when you say the card balance, are you describing the whole balance or only the part being discussed?',
  "Before I answer, could you unpack what the card figure is made up of? I can't tell which part you are asking about."], 'question_about_account'),
 ('request separate repetition of two figures', ['repeat-spoken-information', 'multi-target-administration'], [0,1], 'amount',
  'Two known generic product figures were spoken together; the customer asks for a slower repetition.', [
  'Both figures arrived at once and I lost the thread. Could you repeat the card figure, then the instalment figure?',
  'Please say those two amounts again with a breath between them; I only caught the second one.',
  "Would you rewind just the figures for each product? I'm flustered and don't want to answer the wrong question."], 'request_repetition'),
 ('ask why one product is discussed first', ['request-procedural-reason', 'multi-target-administration'], [0,1], 'payment',
  'The customer challenges discussion order without supplying a new account fact.', [
  'Why are we starting with the card when the instalment plan is also on the table? The order matters to me.',
  'It feels as though the instalment plan disappeared from the conversation. Could you explain why you moved to the card?',
  'Before we put either figure in a box, what is the reason for dealing with one product first?'], 'request_reason'),
 ('request pause before recording response', ['pause-before-recording', 'scope-of-permission'], [0], 'payment',
  'The customer asks for thinking time while the card discussion is pending.', [
  'I need a moment to stop feeling cornered. Please pause before recording a response for the card.',
  'Yes, I heard the question. Could you give me a quiet minute before asking me to settle on anything?',
  "Can we leave that box untouched while I think? I'm not ready for you to write down a decision."], 'request_pause'),
 ('ask meaning of quoted handling expression', ['quoted-administrative-idiom', 'meaning-of-action-verb'], [0], 'payment',
  'A quoted phrase has multiple ordinary administrative senses.', [
  "When you say 'take care of the card', do you mean explain it to me or enter something about it?",
  "I keep hearing 'sort it out'. Could you tell me what action that phrase refers to in this conversation?",
  "Does 'clear the card' mean clear up my confusion, or are you talking about a transaction? That wording is making me uneasy."], 'question_about_wording'),
 ('ask how conditional quoted answer is recorded', ['hypothetical-quoted-response', 'scope-of-permission'], [0], 'date',
  'The customer uses an invented answer to ask about recording procedure; no event anchor is dated.', [
  "Suppose I said 'the Tuesday after the statement arrives'; would you first check what I meant, or put those words straight into a record?",
  "If I used the words 'once the statement arrives', what would you ask me next? I'm asking how the conversation works.",
  "Could you explain what happens to an answer like 'after the statement arrives' before I give you my own answer?"], 'hypothetical_procedure_question'),
 ('ask how revisiting discussion works', ['request-procedural-reason', 'hypothetical-administration'], [1], 'payment',
  'The customer worries about revision; the source supplies no bank policy or consequences.', [
  "If I need to revisit the instalment discussion later, what would the process be? I don't want to guess and make things worse.",
  'Could you explain what changing my mind would involve here? The uncertainty is getting louder than the question.',
  'Before I choose words for the plan, can you walk me through how a correction would be handled?'], 'request_procedure_explanation'),
 ('ask navigation to administrative help', ['administrative-navigation', 'request-procedure-help'], [0,1], 'support',
  'The customer asks how to navigate help for two generic products.', [
  "I'm getting tangled in both products. Could we move to the part of the conversation where someone explains the options?",
  'Can you help me find the right discussion for the card and the plan? I keep answering one while thinking about the other.',
  'I need someone to lay out the two threads. How do we get to that kind of help from here?'], 'request_administrative_help'),
 ('ask which question belongs to which product', ['multi-target-administration', 'target-scope-inquiry'], [0,1], 'payment',
  'Both products are known; the customer asks about scope rather than supplying a new amount or date.', [
  'Which part of that question belongs to the card, and which belongs to the instalment plan? I need the two threads kept apart.',
  'Are you asking the same thing about both products, or only the card? The plural wording has thrown me.',
  "Could you point each question at its own product before I reply? 'Both' is doing too much work for me."], 'question_about_target_scope'),
 ('ask referent of quoted sending instruction', ['quoted-administrative-idiom', 'meaning-of-action-verb'], [0], 'recipient',
  'An administrative verb is questioned; no contact details, destination or recipient identity is supplied.', [
  "When you say 'send it over', are you asking me to send an explanation or to move an amount? I'm not sure what 'it' points to.",
  'Could you say what you want sent before I answer? I can hear two different instructions in that phrase.',
  "I feel rushed by 'send it'. Please explain the object of that instruction in ordinary words."], 'question_about_wording'),
 ('request note of difficulty following discussion', ['administrative-note-request', 'pause-before-recording'], [1], 'support',
  'The customer requests a conversation note without asserting an account fact or agreed arrangement.', [
  "Please note that I'm finding this conversation hard to follow. Could we slow down before returning to the instalment question?",
  'Can you put down that I need the plan explained in smaller pieces? The figures are blurring together for me.',
  "I'd like a note about the confusion, then a chance to hear the plan again. Could you do that in that order?"], 'request_note_and_help'),
 ('ask listening versus entry permission scope', ['scope-of-permission', 'target-scope-inquiry'], [0,1], 'payment',
  'The customer asks about the scope of listening; no authorization is manufactured.', [
  "I'm agreeing to hear you out about both products. Can you keep that separate from permission to enter an arrangement?",
  "Does my saying 'go ahead' mean go ahead with the explanation, or go ahead with an entry? I meant the explanation.",
  "Please check what my 'okay' is attached to. I'm following the card and the plan, but those are two different conversations in my head."], 'request_permission_scope_check'),
]

# skeleton, source-neutral ancestors, targets, explanation, three (text, span, author opinion) tuples
DATES = [
 ('number of days after event clause', ['temporal-offset-event'], [0], 'An offset refers to undated statement arrival.', [
  ('For the card, I could discuss two days after the statement arrives.', 'two days after the statement arrives', 'complete'),
  ('For the card, I could discuss two days after', 'two days after', 'unfinished'),
  ('For the card, I could discuss two days after that.', 'two days after that', 'complete_reference_unresolved')]),
 ('day before closing event clause', ['temporal-predecessor-event'], [1], 'A preceding day refers to an undated window-closing event.', [
  ('For the plan, the day before the payment window closes might be workable.', 'the day before the payment window closes', 'complete'),
  ('For the plan, the day before', 'the day before', 'unfinished'),
  ('For the plan, the day before it closes might be workable.', 'the day before it closes', 'complete_reference_unresolved')]),
 ('from event until event interval', ['temporal-event-interval'], [0,1], 'Two event boundaries define a discussion interval for both products.', [
  ('For both products, could we consider from the statement arriving until the direct debit is posted?', 'from the statement arriving until the direct debit is posted', 'complete'),
  ('For both products, could we consider from the statement arriving until', 'from the statement arriving until', 'unfinished'),
  ('For both products, could we consider from the statement arriving until that happens?', 'from the statement arriving until that happens', 'complete_reference_unresolved')]),
 ('ordinal working day of week in which event', ['temporal-nested-week-relative'], [1], 'A working-day ordinal is nested in an event-defined week.', [
  ('For the plan, I was thinking of the second working day of the week in which the plan resumes.', 'the second working day of the week in which the plan resumes', 'complete'),
  ('For the plan, I was thinking of the second working day of the week in which', 'the second working day of the week in which', 'unfinished'),
  ('For the plan, I was thinking of the second working day of that week.', 'the second working day of that week', 'complete_reference_unresolved')]),
 ('either temporal operand or temporal operand', ['temporal-alternative-operands'], [0], 'Two event days are alternatives; neither is dated or selected by prior state.', [
  ('For the card, perhaps either the day the plan restarts or the day the refund clears.', 'either the day the plan restarts or the day the refund clears', 'complete'),
  ('For the card, perhaps either the day the plan restarts or', 'either the day the plan restarts or', 'unfinished'),
  ('For the card, perhaps either that day or the day the refund clears.', 'either that day or the day the refund clears', 'complete_reference_unresolved')]),
 ('weekday nearest to nominal event', ['temporal-nearest-event'], [1], 'Proximity selects a weekday; no event date or tie resolution is invented.', [
  ('For the plan, I’m wondering about the Friday nearest to the statement being issued.', 'the Friday nearest to the statement being issued', 'complete'),
  ('For the plan, could we talk about the Friday nearest to', 'the Friday nearest to', 'unfinished'),
  ('For the plan, could we talk about the Friday nearest to that?', 'the Friday nearest to that', 'complete_reference_unresolved')]),
 ('last weekday of month after event', ['temporal-nested-month-relative', 'temporal-offset-event'], [0], 'An ordinal weekday is nested in an event-relative month.', [
  ('For the card, I have in mind the last Friday of the month after the instalment plan resumes.', 'the last Friday of the month after the instalment plan resumes', 'complete'),
  ('For the card, I have in mind the last Friday of the month after', 'the last Friday of the month after', 'unfinished'),
  ('For the card, I have in mind the last Friday of the following month.', 'the last Friday of the following month', 'complete_reference_unresolved')]),
 ('by whichever is later event or event', ['temporal-event-order-selector', 'temporal-alternative-operands'], [1], 'A deadline depends on ordering two undated events.', [
  ('For the plan, could it be by whichever is later, the statement arriving or the plan restarting?', 'by whichever is later, the statement arriving or the plan restarting', 'complete'),
  ('For the plan, could it be by whichever is later, the statement arriving or', 'by whichever is later, the statement arriving or', 'unfinished'),
  ('For the plan, could it be by whichever is later, those two events?', 'by whichever is later, those two events', 'complete_reference_unresolved')]),
]

def backbone(text):
    text = text.casefold().replace('’', "'")
    text = re.sub(r'\b(?:instalment plan|instalment|card balance|card|plan)\b', '<product>', text)
    text = re.sub(r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', '<weekday>', text)
    text = re.sub(r'\b(?:one|two|three|first|second|last)\b', '<ordinal>', text)
    text = re.sub(r'\b\d+(?:\.\d+)?\b', '<number>', text)
    return ' '.join(re.sub(r"[^\w<>']+", ' ', text).split())

def generate():
    contract_bytes = CONTRACT.read_bytes()
    contract = json.loads(contract_bytes)
    meta_path = OUT / 'author-metadata.parent-only.json'
    nonce = json.loads(meta_path.read_text(encoding='utf-8'))['author_root_nonce'] if meta_path.exists() else uuid.uuid4().hex
    oid = lambda p, value: p + '-' + sha((nonce + '|' + value).encode())[:24]
    source_name, blind_name = 'source-' + nonce[:12] + '.json', 'blind-source-' + nonce[:12] + '.json'
    author = oid('a','author')
    packet = dict(schema_version='label_free_train_supplement.v5', collection_id=oid('c','collection'), author_id=author,
                  split='train', license='fictional_internal_research_source; no third-party corpus copied', records=[])
    roots, lineage, nominations = [], [], []
    policy_text = 'fictional generic session wording: two products discussed, no dates or consequences stated'
    api_text = 'fictional local input shape; no endpoint, operator policy or external service'
    targets = [dict(index=0,type='credit_card',label='card balance',product_id='generic-card'),
               dict(index=1,type='personal_loan',label='instalment plan',product_id='generic-plan')]
    families = [('administrative', a) for a in ADMIN] + [('date', d) for d in DATES]
    for f, (kind, family) in enumerate(families):
        skeleton, ancestors, selected = family[:3]
        if kind == 'administrative':
            role, explanation, texts, nomination = family[3:]
            variants = [(t,None,nomination) for t in texts]
        else:
            explanation, variants = family[3:]
            role = 'date'
        root = oid('r',str(f))
        source_neutral = dict(skeleton=skeleton, ancestor_aliases=sorted(ancestors), target_arity=len(selected),
                              prior_state_recipe='generic discussion amounts; dates absent; event dates unknown')
        members = []
        for v,(text, nominal_span, nomination) in enumerate(variants):
            i = len(packet['records'])
            ex, turn = oid('e',str(f)+':'+str(v)), oid('t','utterance:'+str(f)+':'+str(v))
            prior = 'The amount I want to discuss for the card balance is 120 units, and for the instalment plan it is 80 units. I have not supplied any dates.'
            pending = []
            for target, amount in ((0,120),(1,80)):
                fragment = str(amount)+' units'
                start = prior.index(fragment)
                ref = span(prior,start,start+len(fragment),f'/records/{i}/input/pending/{target}/components/amount/evidence_refs/0/source_text')
                ref.update(source='authored_fixture',source_turn_id=oid('t','prior:'+root),source_text=prior)
                pending.append(dict(target_index=target,components={
                    'amount': dict(status='complete',revision=oid('v','prior:'+root+str(target)),value=amount,evidence_refs=[ref]),
                    'date': dict(status='absent',revision=oid('v','absent:'+root+str(target)),value=None,evidence_refs=[])},unresolved_components=['date']))
            target_text = 'both products' if len(selected)==2 else targets[selected[0]]['label']
            prompts = {'date':'What date or period would you like to discuss for ', 'amount':'Which amount would you like to discuss for ',
                       'support':'What help would you like with the discussion of ', 'recipient':'What do you want to discuss about sending something for the ',
                       'payment':'What would you like to do next in the discussion of '}
            question_text = prompts[role]+target_text+'?'
            if kind == 'administrative' and f == 4:
                question_text = [
                    'What would you like to do next to take care of the card?',
                    'What would you like to do next to sort it out?',
                    'What would you like to do next to clear the card?'][v]
            if kind == 'administrative' and f == 9:
                question_text = [
                    'What do you want to discuss about the phrase send it over for the card?',
                    'What do you want to discuss about what to send for the card?',
                    'What do you want to discuss about the phrase send it for the card?'][v]
            question_text = 'We are discussing 120 units for the card balance and 80 units for the instalment plan. ' + question_text
            inp = dict(schema_version='semantic_input.v1',call_local_id=oid('s',root),turn_id=turn,state_revision=2,
                       policy_hash=sha(policy_text.encode()),api_hash=sha(api_text.encode()),phase='post_verified_account',
                       utterance=dict(text=text,source='authored_fixture',source_turn_id=turn,complete_transport=True,offset_unit='python_unicode_codepoints'),
                       question=dict(question_id=oid('q',root),role=role,spoken_turn_id=oid('t','question:'+root),
                                     target_indices=selected,text=question_text),
                       targets=targets,pending=pending,spoken_offers=[],active_readback=None)
            record = dict(example_id=ex,declared_lineage_id=root,collection_axis='primary_other_act' if kind=='administrative' else 'date_open_complement',
                          author_provenance=dict(author_id=author,fictional_origin=True,recipe_id=oid('g',str(f)),
                            template_skeleton_id=oid('k',str(f)),scenario_family_id=oid('f',str(f)),source_family_id=oid('u',str(f)),
                            contrast_parent_id=root if kind=='date' else None),input=inp)
            packet['records'].append(record)
            members.append(ex)
            norm = backbone(text)
            lineage.append(dict(example_id=ex,root_id=root,source_record_path=f'/records/{i}',normalized_backbone=norm,
                normalized_backbone_sha256=sha(norm.encode()),utterance_raw_utf8_sha256=sha(text.encode()),
                source_neutral_template_sha256=sha(canonical(source_neutral)),source_neutral_ancestor_aliases=sorted(ancestors),
                source_neutral_semantic_input_sha256=sha(canonical(dict(phase=inp['phase'],question_role=role,
                    question_target_indices=selected,targets=targets,prior_source_text=prior,utterance_backbone=norm)))))
            nom = dict(example_id=ex,root_id=root,author_nomination_only=nomination,not_ground_truth=True,reviewer_access='exclude')
            if nominal_span:
                start = text.index(nominal_span)
                nom.update(author_span_nomination=span(text,start,start+len(nominal_span),f'/records/{i}/input/utterance/text'),
                           author_target_nomination=selected,reference_and_normalization='unassessed; no dated anchor supplied; no normalized value')
            nominations.append(nom)
        roots.append(dict(root_id=root,members=members,source_neutral_template=source_neutral,
                          source_neutral_template_sha256=sha(canonical(source_neutral)),scenario_explanation=explanation,
                          requested_family_kind=kind,member_relationship='sibling alternatives from one scenario recipe; retain every member'))
    dump(OUT/source_name,packet)
    blind = dict(schema_version='blind_source_train_packet.peer.v1',collection_id=packet['collection_id'],split='train',
                 records=[dict(example_id=r['example_id'],input=r['input']) for r in packet['records']])
    dump(OUT/blind_name,blind)
    schema = contract['collection_json_schema']
    dump(OUT/'collection.schema.json',schema)
    dump(OUT/'independent-review.schema.json',contract['independent_review_json_schema'])
    blind_schema = dict(schema)
    blind_schema.pop('$id',None)
    blind_schema['title']='Source-only blind projection of exact v5 inputs'
    blind_schema['properties']={k:schema['properties'][k] for k in ('collection_id','split')}
    blind_schema['properties']['schema_version']={'const':blind['schema_version']}
    item_schema = schema['properties']['records']['items']
    blind_schema['properties']['records']={'type':'array','minItems':1,'items':{'type':'object','additionalProperties':False,
        'required':['example_id','input'],'properties':{k:item_schema['properties'][k] for k in ('example_id','input')}}}
    blind_schema['required']=['schema_version','collection_id','split','records']
    dump(OUT/'blind-source.schema.json',blind_schema)
    source_hash, blind_hash = sha((OUT/source_name).read_bytes()), sha((OUT/blind_name).read_bytes())
    mapping = []
    for i,(raw,view) in enumerate(zip(packet['records'],blind['records'])):
        text=view['input']['utterance']['text']
        mapping.append(dict(example_id=raw['example_id'],root_id=raw['declared_lineage_id'],source_record_path=f'/records/{i}',
            source_record_json_sha256=sha(canonical(view)),source_input_json_sha256=sha(canonical(view['input'])),
            canonical_record_json_sha256=sha(canonical(raw)),whole_utterance_source_span=span(text,0,len(text),f'/records/{i}/input/utterance/text')))
    reviewer_files=[blind_name,'blind-source.schema.json','review-closure.json','independent-review.schema.json','REVIEW_INSTRUCTIONS.txt']
    closure = dict(schema_version='peer_source_review_closure.v1',split='train',source_packet_path=blind_name,
        source_packet_raw_sha256=blind_hash,canonical_packet_path=source_name,canonical_packet_raw_sha256=source_hash,
        canonicalization="json.dumps(ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')",
        projection='remove acquisition routing and author provenance; preserve exact inputs, IDs, order and source pointers',
        roots=[dict(root_id=r['root_id'],members=r['members']) for r in roots],records=mapping,
        closure_rule='Every supplied root member retained; external transitive closure unknown pending parent reconciliation',
        reviewer_files_only=reviewer_files,private_means='handoff segregation, not filesystem access control; parent isolates reviewers')
    dump(OUT/'review-closure.json',closure)
    duplicates=[]
    for key in ('utterance_raw_utf8_sha256','normalized_backbone_sha256','source_neutral_semantic_input_sha256'):
        groups=defaultdict(list)
        for row in lineage: groups[row[key]].append(row['example_id'])
        duplicates.extend(dict(key=key,digest=k,members=v) for k,v in groups.items() if len(v)>1)
    potential=[]
    for i,left in enumerate(roots):
        lrows=[r for r in lineage if r['root_id']==left['root_id']]
        for right in roots[i+1:]:
            rrows=[r for r in lineage if r['root_id']==right['root_id']]
            shared=sorted(set(left['source_neutral_template']['ancestor_aliases']) & set(right['source_neutral_template']['ancestor_aliases']))
            ratio=max(SequenceMatcher(None,a['normalized_backbone'],b['normalized_backbone']).ratio() for a in lrows for b in rrows)
            if shared or ratio>=0.72:
                potential.append(dict(left_root_id=left['root_id'],right_root_id=right['root_id'],shared_source_neutral_ancestor_aliases=shared,
                    max_lexical_backbone_similarity=round(ratio,6),status='potential_alias_for_parent_reconciliation_not_independent_support'))
    audit=dict(schema_version='source_neutral_lineage_audit.peer.v1',roots=roots,records=lineage,
        exact_duplicate_checks_before_union=duplicates,potential_cross_root_aliases=potential,
        within_root_alias_edges=[dict(left_example_id=r['members'][0],right_example_id=m,evidence='shared explicit authored scenario and template recipe')
            for r in roots for m in r['members'][1:]],
        union_state='not externally reconciled; declared roots are not IID or admitted canonical support',
        cross_author_rule='Compare source-neutral skeletons, ancestor aliases, normalized backbones and context recipes before union; different nonce/author/path never establishes independence',
        cross_source_checks='unknown; no older TRAIN, DEV, holdout, sibling source or annotations read',normalization_is_audit_only=True)
    dump(OUT/'lineage-audit.parent-only.json',audit)
    dump(OUT/'author-nominations.parent-only.json',dict(schema_version='author_nominations_not_review.peer.v1',
        status='author opinions only; no ground truth or admission evidence',access='parent only; exclude from both blind reviews',
        source_packet_raw_sha256=source_hash,blind_packet_raw_sha256=blind_hash,records=nominations))
    counts=dict(administrative_scenario_families=len(ADMIN),administrative_turn_variants=len(ADMIN)*3,
                date_contrast_roots=len(DATES),date_members=len(DATES)*3,total_records=len(packet['records']),declared_roots=len(roots))
    metadata=dict(schema_version='fictional_peer_author_metadata.v1',author_id=author,author_root_nonce=nonce,nonce_is_secret=False,
        nonce_purpose='public author/root namespace only; distinct nonce never implies independent support',
        authorship='independent second source author; inherited workhorse fallback; no separate model identity asserted',
        utc=datetime.now(timezone.utc).isoformat(),author_started_utc='2026-10-11T03:42:09+00:00',
        source_language='English',source_interface='finite authored text candidate interface',
        scope='fictional TRAIN engineering acquisition',scenario_context='generic already-verified product discussion; no identity content',
        prior_fact_semantics='120 and 80 units previously discussed, exact earlier-source evidence; dates absent before each sibling response',
        sibling_turn_semantics='alternative turns sharing a preexisting state, not sequential dialogue or independent rows',
        policy_hash_fictional_preimage=policy_text,api_hash_fictional_preimage=api_text,
        hash_semantics='fictional context hashes, not operator policy, external API, secrets or authorization grants',
        contract_file=str(CONTRACT.relative_to(ROOT)).replace('\\','/'),contract_raw_sha256=sha(contract_bytes),
        original_input_schema_file=str(ORIGINAL.relative_to(ROOT)).replace('\\','/'),original_input_schema_raw_sha256=sha(ORIGINAL.read_bytes()),
        content_origin='new fictional language and local scenario recipes; no copied third-party corpus or customer source',
        read_scope=['v5 next-data-interface schema/instructions','original input schema descriptions'],forbidden_source_contents_read=False,
        detector_or_predictions_run=False,new_dev_or_holdout_read=False,admission_review_adjudication_or_fit_performed=False,
        scenario_content_sha256=sha(canonical(dict(administrative=ADMIN,date=DATES))),
        nomination_manifest_sha256=sha((OUT/'author-nominations.parent-only.json').read_bytes()),
        source_packet=source_name,blind_packet=blind_name,authored_counts=counts,
        counts_are='inventory diagnostics only; no eligible class support or floor satisfaction claim')
    dump(meta_path,metadata)
    (OUT/'REVIEW_INSTRUCTIONS.txt').write_text(
        'Independent source-only review of fictional TRAIN utterances.\n'
        'Use only review-closure.json reviewer_files_only. Do not open parent-only files, generator, sibling sources, old examples, predictions or another review.\n'
        'Review every listed member of every root. Input/order/IDs are exact projections of the canonical source. Bind the blind-source raw hash and its canonical JSON record/input hashes in your separate review.\n'
        'Use independent-review.schema.json, copied exactly from v5. Do not alter source files. /records/N pointers refer to the blind-source packet.\n'
        'Spans use original half-open Python Unicode codepoints and UTF8 byte bounds; reproduce exact source text. Whole-utterance inventory spans are locations, not candidate annotations.\n'
        'Independently assess primary act, maximal temporal boundaries, candidate role, target scope, polarity, reference and normalization. Include dependent operands and open tails.\n'
        'Undated events do not establish a calendar value. Unsupported or ambiguous judgments remain unassessed or masked. Pending facts are earlier local state, not current-utterance labels.\n'
        'Use exact known target indices and retain multi-target readings. Do not force a reading to fit an extractor. Privacy is independently assessed; eventual source masks remain authoritative.\n'
        'The parent obtains two isolated reviews and a distinct source adjudicator. No author opinion or class-count target is review evidence.\n',encoding='utf-8',newline='\n')
    (OUT/'PARENT_HANDOFF.txt').write_text(
        'Pass only the five reviewer_files_only entries to fresh blind reviewers. The strict v5 packet has mandated acquisition routing; the blind projection removes it and author provenance without changing any inputs. Parent-only segregation is a handoff rule, not an ACL.\n'
        'Each reviewer labels every member independently. A distinct source adjudicator uses the untouched reviews and exact source. All members may be masked. No reviews are supplied here.\n'
        'Use the source-neutral lineage audit before union. Similar construction across two authors is a potential alias, regardless of nonce, author or filename. Reconcile evidence before transitive closure; never split roots to improve counts.\n'
        'Cross-author, older TRAIN and global lineage checks remain unknown because those reads were prohibited. Bind identifier-only split declarations before admission. Cross-split conflicts block admission.\n'
        'Maximal boundary/exact targets and unchanged detector/privacy/window requirements still apply. No detector or feature eligibility test was run. Multi-target or long expressions may be masked. No normalization values are supplied.\n'
        'Author nominations are parent-only opinions, not ground truth. Inventory counts do not satisfy support floors. No relabeling, padding, fit or previous grant reuse.\n',encoding='utf-8',newline='\n')
    inventory=[dict(path=str(p.relative_to(ROOT)).replace('\\','/'),bytes=p.stat().st_size,raw_sha256=sha(p.read_bytes()),reviewer_access=p.name in reviewer_files)
               for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='build-manifest.json']
    inventory_hash=sha(canonical(inventory))
    manifest=dict(schema_version='peer_artifact_manifest.v1',files=inventory,inventory_canonical_sha256=inventory_hash,
        manifest_self_hash='external report only to avoid circular digest',split='train',canonical_packet_raw_sha256=source_hash,
        blind_packet_raw_sha256=blind_hash,test_file_path=str(TEST.relative_to(ROOT)).replace('\\','/'),test_file_raw_sha256=sha(TEST.read_bytes()))
    dump(OUT/'build-manifest.json',manifest)
    report=dict(schema_version='semantic_v6_peer_acquisition_report.v1',status='source_acquired_pending_independent_review_and_alias_reconciliation',
        author_root_nonce=nonce,counts=counts,reviewed_records=0,adjudicated_records=0,eligible_canonical_class_support='unknown; no labels, detector, features, union or admission',
        duplicate_diagnostics=dict(exact_duplicate_groups=len(duplicates),potential_cross_root_alias_pairs=len(potential),external_comparison='unknown; prohibited reads not performed'),
        source_path=str((OUT/source_name).relative_to(ROOT)).replace('\\','/'),source_packet_raw_sha256=source_hash,
        blind_source_path=str((OUT/blind_name).relative_to(ROOT)).replace('\\','/'),blind_packet_raw_sha256=blind_hash,
        review_closure_path=str((OUT/'review-closure.json').relative_to(ROOT)).replace('\\','/'),review_closure_raw_sha256=sha((OUT/'review-closure.json').read_bytes()),
        inventory_canonical_sha256=inventory_hash,build_manifest_raw_sha256=sha((OUT/'build-manifest.json').read_bytes()),test_file_raw_sha256=manifest['test_file_raw_sha256'],
        verification=dict(status='pending local source/lineage/privacy/provenance tests'),
        constraints=dict(train_only=True,fictional_no_customer_pii=True,labels_absent_from_source_packets=True,blind_review_has_no_author_nomination=True,
                         no_asr_or_accent_claim=True,no_model_identity_claim=True,no_fit_weights_cloud_platform_api_credentials_git_or_source_changes=True),
        new_namespace=str(OUT.relative_to(ROOT)).replace('\\','/'),owned_paths=[str(OUT.relative_to(ROOT)).replace('\\','/')+'/',
            str(TEST.relative_to(ROOT)).replace('\\','/'),str(REPORT.relative_to(ROOT)).replace('\\','/'),str(REPORT_TEXT.relative_to(ROOT)).replace('\\','/')])
    dump(REPORT,report)
    REPORT_TEXT.write_text('Independent second-author fictional TRAIN acquisition; review/adjudication/union/admission pending.\n'
        +json.dumps(counts,sort_keys=True)+'\nInventory diagnostics only; eligible canonical support unknown; no floor, relabeling or padding claim.\n'
        +'Canonical source: '+report['source_path']+'\nSHA256: '+source_hash+'\nBlind source: '+report['blind_source_path']+'\nSHA256: '+blind_hash
        +'\nInventory canonical SHA256: '+inventory_hash+'\nExact duplicate groups: '+str(len(duplicates))+'; potential local cross-root aliases: '+str(len(potential))
        +'\nExternal closure unknown. Explicit reviewer allowlist excludes author opinions and provenance hints. Local test verification pending.\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(records=counts['total_records'],declared_roots=counts['declared_roots'],source=report['source_path'],source_sha256=source_hash,
                         blind_sha256=blind_hash,inventory_sha256=inventory_hash)))

if __name__=='__main__':
    generate()
