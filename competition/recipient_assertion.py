"""Current opening-answer source assertions, never verified identity.

Portable inline source: re and builtins only; no IO, model, bank variables or
test subjects. Call recipient_assertion(raw, given_name, last_name, title='').
SELF supplies only eligibility for the next security question. The caller must
keep verification and disclosure authority independent. Offsets are Python
codepoint offsets into the exact original raw string, with end exclusive.
"""
import re

_RA_WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|[\u0300-\u036f])*(?:['’‘ʼ\-‐‑–−][^\W\d_](?:[^\W\d_]|[\u0300-\u036f])*)*", re.UNICODE)
_RA_TITLES = (
    ('dr', 'doctor', 'doktor'),
    ('prof', 'professor', 'profesör', 'profesor'),
    ('mr', 'mister', 'bay', 'bey'),
    ('ms', 'miss', 'bayan', 'hanım', 'hanim'),
    ('mrs', 'madam', 'hanım', 'hanim'),
    ('sir',), ('mx',), ('dame',),
)
_RA_COURTESY = re.compile(r"^(?:[,.:\s]*)(?:please|thanks|thank you|hello|hi|good morning|good afternoon|buyurun|efendim|merhaba|teşekkürler|tesekkurler|evet|yes)(?:[.!\s]*)$", re.I)
_RA_RELATION = re.compile(
    r"\b(?:i\s+am|i['’]m|this\s+is)\s+(?:(?:his|her|their|the)\s+|[^;.!?]+?['’]s\s+)"
    r"(?:assistant|mother|father|sister|brother|wife|husband|son|daughter|neighbou?r|colleague|friend|partner)\b"
    r"|\b(?:ben\s+)?(?:annesiyim|babas(?:ı|i)y(?:ı|i)m|kardeşiyim|kardesiyim|komşusuyum|komsusuyum|asistan(?:ı|i)y(?:ı|i)m|eşiyim|esiyim|oğluyum|ogluyum|k(?:ı|i)z(?:ı|i)y(?:ı|i)m)\b", re.I)
_RA_DOB_REFUSAL = re.compile(
    r"\b(?:i\s+(?:will\s+not|won['’]t|refuse\s+to|do\s+not\s+want\s+to)|i['’]m\s+not\s+going\s+to)"
    r"[^;.!?]{0,100}\b(?:birthday|birth\s*date|date\s+of\s+birth|dob)\b"
    r"|\b(?:doğum|dogum)\s+(?:tarihimi|günümü|gunumu)[^;.!?]{0,100}\b(?:söylemem|soylemem|vermeyeceğim|vermeyecegim|paylaşmam|paylasmam|söylemeyeceğim|soylemeyecegim)\b", re.I)
_RA_PREFIX = re.compile(
    r"^(?:(?:i\s+am|i['’]m|this\s+is|my\s+name\s+is|the\s+name\s+is|benim\s+ad(?:ı|i)m|ad(?:ı|i)m|ismim|ben)\s+|speaking\s*[,.:]\s*)(.+)$", re.I)
_RA_EN_DENIAL = re.compile(
    r"^(?:(?:i\s+am|i['’]m|this\s+is)\s+(?:not|never)|my\s+name\s+(?:is\s+not|isn['’]t))\s+(.+)$", re.I)
_RA_TR_DENIAL = re.compile(r"^(?:ben\s+)?(.+?)\s+(?:ben\s+)?(?:değilim|degilim)\s*$", re.I)
_RA_SUFFIX = re.compile(r"^(.+?)\s+(?:speaking|here|benim|konuşuyor|konusuyor|konuşuyorum|konusuyorum)(.*)$", re.I)
_RA_REPORT = re.compile(r"\b(?:said|says|told|quoting|quoted|according\s+to|read\s+aloud|dedi|diyor|söyledi|soyledi|söylemiş|soylemis|alıntı|alinti)\b", re.I)
_RA_HYPOTHETICAL = re.compile(r"\b(?:if|suppose|imagine|pretend|hypothetically|eğer|eger|varsay|diyelim)\b", re.I)
_RA_NO_ANSWER = re.compile(r"\b(?:no\s+answer|voicemail|silence|unanswered|caller\s+(?:repeats|prompt)|cevap\s+yok|sessizlik|sesli\s+mesaj)\b", re.I)
_RA_WRONG_RECIPIENT = re.compile(
    r"^(?:not\s+me|it['’]s\s+not\s+me|wrong\s+(?:number|person)|you\s+(?:have|have\s+got|are\s+calling)\s+(?:the\s+)?wrong\s+(?:number|person)"
    r"|yanlış\s+numara|yanlis\s+numara|ben\s+değilim|ben\s+degilim|aradığınız\s+kişi\s+değilim|aradiginiz\s+kisi\s+degilim)$", re.I)
_RA_ABSENCE = re.compile(r"^(.+?)\s+(?:is\s+(?:away|not\s+here|unavailable|deceased|dead)|burada\s+(?:değil|degil)|yok)\s*$", re.I)


def _ra_fold(text):
    text = text.casefold().replace('\u0307', '').replace('ı', 'i')
    for source, target in (("’", "'"), ("‘", "'"), ("ʼ", "'"), ('‐', '-'), ('‑', '-'), ('–', '-'), ('−', '-')):
        text = text.replace(source, target)
    # Common Latin decomposed spelling, without importing an undocumented module.
    for source, target in (('s\u0327', 'ş'), ('c\u0327', 'ç'), ('g\u0306', 'ğ'),
                           ('o\u0308', 'ö'), ('u\u0308', 'ü'), ('a\u0308', 'ä'),
                           ('e\u0301', 'é'), ('a\u0301', 'á'), ('i\u0301', 'í'),
                           ('o\u0301', 'ó'), ('u\u0301', 'ú'), ('n\u0303', 'ñ')):
        text = text.replace(source, target)
    return text


def _ra_tokens(text):
    return [_ra_fold(match.group()) for match in _RA_WORD.finditer(text)]


def _ra_aliases(title):
    value = _ra_fold(title.strip().rstrip('.'))
    aliases = [value] if value else []
    for group in _RA_TITLES:
        folded = [_ra_fold(item) for item in group]
        if value in folded:
            aliases.extend(folded)
    return [_ra_tokens(item) for item in aliases if item]


def _ra_name(candidate, given, family, aliases, *, strong=False):
    """Match the complete asserted name phrase, never an utterance substring."""
    tokens = _ra_tokens(candidate)
    if not tokens:
        return 'UNKNOWN', [], 'NO_NAME'
    # Reject arbitrary punctuation/numeric payload embedded in a name phrase.
    rest = _RA_WORD.sub('', candidate)
    if re.search(r"[^\s,.'’‘ʼ\-‐‑–−]", rest):
        return 'UNKNOWN', [], 'NOT_A_NAME_PHRASE'
    for alias in sorted(aliases, key=len, reverse=True):
        if tokens[:len(alias)] == alias:
            tokens = tokens[len(alias):]; break
        if tokens[-len(alias):] == alias:
            tokens = tokens[:-len(alias)]; break
    allowed = []
    if given: allowed.append((given, ['given']))
    if family: allowed.append((family, ['family']))
    if given and family:
        allowed.extend(((given + family, ['given', 'family']), (family + given, ['family', 'given'])))
    for name, parts in allowed:
        if tokens == name:
            return 'SELF', parts, 'CURRENT_NAME_ASSERTION'
    if not tokens:
        return 'UNKNOWN', [], 'TITLE_ONLY'
    # A matching family name cannot discard an explicitly different given name.
    overlaps = [part for part, name in (('given', given), ('family', family)) if name and
                any(tokens[i:i+len(name)] == name for i in range(len(tokens)-len(name)+1))]
    words = [match.group() for match in _RA_WORD.finditer(candidate)]
    proper = bool(words) and all(word[0].isupper() or _ra_fold(word) in ('de', 'van', 'von', 'da', 'di') for word in words)
    # Ordinary copular descriptions such as "I'm busy" are not different names.
    if strong or proper:
        return 'OTHER', overlaps, 'EXPLICIT_DIFFERENT_NAME'
    return 'UNKNOWN', [], 'UNSUPPORTED_NAME_PHRASE'


def _ra_quotes(raw):
    ranges = []; active = None; begin = None
    for index, char in enumerate(raw):
        if char not in "'\"‘’“”":
            continue
        left = raw[index-1] if index else ''
        right = raw[index+1] if index+1 < len(raw) else ''
        if char in "'‘’" and left and right and (left.isalnum() or '\u0300' <= left <= '\u036f') and right.isalnum():
            continue  # Contraction, name apostrophe, or Turkish possessive.
        kind = 'single' if char in "'‘’" else 'double'
        if active is not None:
            if kind == active:
                ranges.append((begin, index+1)); active = None; begin = None
        elif char in "'\"‘“":
            # A trailing possessive apostrophe is punctuation, not a quotation.
            if char == "'" and left.isalnum() and (not right or right.isspace()):
                continue
            active = kind; begin = index
    if active is not None:
        ranges.append((begin, len(raw)))
    return ranges


def _ra_segments(raw, masked, quote_ranges):
    bounds = [0, len(raw)]
    for start, end in quote_ranges:
        bounds.extend((start, end))
    for index, char in enumerate(masked):
        if char in ';!?':
            bounds.append(index+1)
        elif char == '.':
            preceding = re.search(r"([^\W\d_]+)$", masked[max(0, index-32):index])
            abbreviation = preceding and _ra_fold(preceding.group()) in ('dr', 'prof', 'mr', 'mrs', 'ms', 'mx')
            if not abbreviation: bounds.append(index+1)
    # Commas within inverted names stay in the candidate; speech-act connectors
    # and courtesy/question suffixes form separate clauses.
    for match in re.finditer(r",\s*(?=(?:but|and|ama|fakat|ancak|i\b|i['’]m|ben\b|buyurun|please|thanks|thank\s+you|what\b|who\b|why\b|which\b|how\b|merhaba|efendim)\b)|\s+(?=(?:but|ama|fakat|ancak)\s+)", masked, re.I):
        bounds.append(match.end())
    ordered = sorted(set(bounds))
    for start, end in zip(ordered, ordered[1:]):
        while start < end and (raw[start].isspace() or raw[start] in ',;.!'):
            start += 1
        while end > start and raw[end-1].isspace():
            end -= 1
        if start < end and masked[start:end].strip():
            yield start, end


def recipient_assertion(raw, given_name, last_name, title=''):
    """Parse one current recipient-opening answer. No extractor output needed.

    Name-only answers and short affirmatives are scoped to this opening API.
    Input contains only current speech and dynamic recipient name/title strings.
    Unclear attribution, unsupported grammar and conflicting identities remain
    UNKNOWN. Independent DOB refusal does not negate recipient identification.
    """
    result = {'decision': 'UNKNOWN', 'recipient_self': None, 'source_span': [],
              'assertions': [], 'reason': 'NO_CURRENT_ASSERTION', 'bank_authority': False}
    if any(type(value) is not str for value in (raw, given_name, last_name, title)):
        result['reason'] = 'INVALID_INPUT'; return result
    if not raw.strip() or len(raw) > 16384 or max(len(given_name), len(last_name)) > 256 or len(title) > 64:
        result['reason'] = 'INVALID_INPUT'; return result
    given, family = _ra_tokens(given_name), _ra_tokens(last_name)
    if not given and not family:
        result['reason'] = 'MISSING_RECIPIENT_NAME'; return result
    aliases = _ra_aliases(title)
    assertions = result['assertions']
    def add(act, start, end, subject, polarity, decision='UNKNOWN', parts=None, reason=''):
        assertions.append({'act': act, 'source_span': [start, end], 'text': raw[start:end],
                           'subject': subject, 'polarity': polarity, 'decision': decision,
                           'matched_name_parts': parts or [], 'reason': reason})
    quote_ranges = _ra_quotes(raw)
    masked = list(raw)
    for start, end in quote_ranges:
        prefix = raw[max(0, start-100):start]
        subject = 'reported' if _RA_REPORT.search(prefix) else 'unknown'
        add('quotation', start, end, subject, 'unknown', reason='QUOTED_NOT_CURRENT_SELF')
        masked[start:end] = [' '] * (end-start)
    for match in re.finditer(r"\[[^\]]*\]", raw):
        if _RA_NO_ANSWER.search(match.group()):
            add('no_answer', match.start(), match.end(), 'no_current_speaker', 'negative', 'OTHER', reason='NO_LIVE_ANSWER')
            masked[match.start():match.end()] = [' '] * (match.end()-match.start())
    masked = ''.join(masked)
    for start, end in _ra_segments(raw, masked, quote_ranges):
        segment = masked[start:end]
        text = segment.rstrip(' .;!?,').strip()
        if not text: continue
        # Discourse prefixes express courtesy or repair, not a name component.
        prefix = re.match(r"^(?:(?:yes|no|evet|hayır|hayir|hello|merhaba|actually|aslında|aslinda)\s*[,.:]\s*)+", text, re.I)
        offset = prefix.end() if prefix else 0
        core = text[offset:]
        connector = re.match(r"^(?:but|and|ama|fakat|ancak)\s+", core, re.I)
        if connector: offset += connector.end(); core = core[connector.end():]
        core_start = start + offset
        reverse_denial = re.fullmatch(r"(.+?)\s+(?:is\s+not\s+me|isn['’]t\s+me|is\s+not\s+my\s+name|isn['’]t\s+my\s+name)", core, re.I)
        if reverse_denial and _ra_name(reverse_denial.group(1), given, family, aliases)[0]=='SELF':
            add('identity_denial', core_start, end, 'speaker', 'negative', 'OTHER', reason='CURRENT_RECIPIENT_DENIAL')
            continue
        possessive = re.fullmatch(r"(?:i\s+am|i['’]m|this\s+is)\s+(.+?)['’]s\s+([^;.!?]+)", core, re.I)
        generic_relation = re.fullmatch(r"(?:i\s+am|i['’]m|this\s+is)\s+(?:his|her|their)\s+(?:cousin|relative|attorney|representative|carer|caregiver|aunt|uncle|niece|nephew|grandchild|grandparent)", core, re.I)
        if (possessive and _ra_name(possessive.group(1),given,family,aliases)[0]=='SELF') or generic_relation:
            add('other_person',core_start,end,'speaker','positive','OTHER',reason='CURRENT_THIRD_PARTY_POSSESSIVE_RELATION')
            continue
        if re.fullmatch(r"(?:i\s+am|i['’]m|ben)\s+(?:(?:just|only)\s+)?(?:pretending|roleplaying|acting|imitating|şaka\s+yapıyorum|saka\s+yapiyorum)(?:\s+to\s+be\s+[^;.!?]+)?",core,re.I):
            add('identity_qualification',core_start,end,'speaker','unknown',reason='CURRENT_IDENTITY_NOT_ASSERTED_LITERALLY')
            continue
        refusal = _RA_DOB_REFUSAL.search(segment)
        if refusal:
            add('dob_refusal', start+refusal.start(), start+refusal.end(), 'speaker', 'negative', reason='INDEPENDENT_DISCLOSURE_REFUSAL')
        relation = _RA_RELATION.search(segment)
        if relation:
            if re.match(r"(?:i\s+am|i['’]m|this\s+is)\s+(?:not|never)\b", relation.group(), re.I):
                add('other_person', start+relation.start(), start+relation.end(), 'speaker', 'negative', reason='DENIED_RELATION_NOT_RECIPIENT_DENIAL')
                continue
            add('other_person', start+relation.start(), start+relation.end(), 'speaker', 'positive', 'OTHER', reason='CURRENT_THIRD_PARTY_RELATION')
            continue
        if _RA_NO_ANSWER.fullmatch(text) or re.match(r"^(?:caller\s*:|voicemail\s*:|no\s+answer\b|silence\b)", text, re.I):
            add('no_answer', start, end, 'no_current_speaker', 'negative', 'OTHER', reason='NO_LIVE_ANSWER'); continue
        # A question cannot become an assertion by stripping its question mark.
        if segment.rstrip().endswith('?'):
            add('identity_question', start, end, 'unknown', 'unknown', reason='QUESTION_NOT_ASSERTION'); continue
        if _RA_WRONG_RECIPIENT.fullmatch(core):
            add('wrong_recipient', core_start, end, 'speaker', 'negative', 'OTHER', reason='CURRENT_WRONG_RECIPIENT_ASSERTION'); continue
        absent = _RA_ABSENCE.fullmatch(core)
        if absent and _ra_name(absent.group(1), given, family, aliases)[0] == 'SELF':
            add('recipient_absent', core_start, end, 'recipient', 'negative', 'OTHER', reason='CURRENT_RECIPIENT_ABSENCE'); continue
        # Unquoted reported/hypothetical introductions apply to this clause too.
        sentence_start = max(raw.rfind('.', 0, start), raw.rfind(';', 0, start), raw.rfind('?', 0, start), raw.rfind('!', 0, start)) + 1
        context_prefix = raw[sentence_start:core_start]
        for qstart, qend in quote_ranges:
            if qend <= start and qend > sentence_start:
                context_prefix = raw[qend:core_start]
        # A word such as Said may itself be the supplied name. In an exact
        # current naming frame it is a name, not an attribution verb/condition.
        naming = _RA_PREFIX.match(core) or _RA_SUFFIX.match(core)
        named = naming.group(1) if naming else ''
        nested_suffix = _RA_SUFFIX.match(named) if _RA_PREFIX.match(core) else None
        if nested_suffix and (not nested_suffix.group(2).strip() or _RA_COURTESY.fullmatch(nested_suffix.group(2))):
            named = nested_suffix.group(1)
        exact_name = naming and _ra_name(named, given, family, aliases)[0] == 'SELF'
        if (_RA_REPORT.search(core) and not exact_name) or _RA_REPORT.search(context_prefix):
            add('reported_identity', start, end, 'reported', 'unknown', reason='ATTRIBUTED_NOT_CURRENT_SELF'); continue
        if (_RA_HYPOTHETICAL.search(core) and not exact_name) or _RA_HYPOTHETICAL.search(context_prefix):
            add('hypothetical_identity', start, end, 'unknown', 'unknown', reason='HYPOTHETICAL_NOT_CURRENT_SELF'); continue
        denial = _RA_EN_DENIAL.match(core) or _RA_TR_DENIAL.match(core)
        if denial:
            decision, parts, reason = _ra_name(denial.group(1), given, family, aliases)
            decision = 'OTHER' if decision == 'SELF' else 'UNKNOWN'
            add('identity_denial', core_start, end, 'speaker', 'negative', decision, parts,
                'CURRENT_RECIPIENT_DENIAL' if decision == 'OTHER' else 'DENIAL_OF_UNBOUND_IDENTITY')
            continue
        if re.fullmatch(r"(?:yes|evet|speaking|it's\s+me|it['’]s\s+me|that['’]s\s+me|that's\s+me|(?:that|this)\s+is\s+me|benim|ben\s+konuşuyorum)[.!\s]*", core, re.I):
            add('opening_confirmation', core_start, end, 'speaker', 'positive', 'SELF', reason='SHORT_CURRENT_OPENING_ANSWER')
            continue
        identified = _RA_PREFIX.match(core)
        suffix = _RA_SUFFIX.match(identified.group(1) if identified else core)
        candidate = suffix.group(1) if suffix else identified.group(1) if identified else core
        if suffix and suffix.group(2).strip() and not _RA_COURTESY.fullmatch(suffix.group(2)):
            add('unresolved_identity', core_start, end, 'unknown', 'unknown', reason='UNRESOLVED_SUFFIX_SCOPE'); continue
        if identified:
            # Remove a conventional courtesy tail; never arbitrary extra words.
            courtesy = re.search(r"(?:,\s*|\s+)(?:please|thanks|thank you|buyurun|efendim|merhaba)\b.*$", candidate, re.I)
            if courtesy and _RA_COURTESY.fullmatch(candidate[courtesy.start():]):
                candidate = candidate[:courtesy.start()]
        decision, parts, reason = _ra_name(candidate, given, family, aliases,
                                          strong=bool(re.match(r"^(?:my\s+name|benim\s+ad|ad[ıi]m|ismim)\b", core, re.I)))
        if decision == 'SELF' and not identified and not suffix and quote_ranges:
            # A bare subject adjoining quoted speech may be its attribution.
            # Require an explicit unquoted self frame when quotation is present.
            decision, reason = 'UNKNOWN', 'BARE_NAME_WITH_QUOTATION_ATTRIBUTION_UNCLEAR'
        if identified or suffix or decision == 'SELF':
            add('self_identification', core_start, end, 'speaker', 'positive', decision, parts, reason)
        elif re.fullmatch(r"(?:yes|evet|speaking|it's\s+me|it['’]s\s+me|that['’]s\s+me|that's\s+me|(?:that|this)\s+is\s+me|benim|ben\s+konuşuyorum)[.!\s]*", core, re.I):
            add('opening_confirmation', core_start, end, 'speaker', 'positive', 'SELF', reason='SHORT_CURRENT_OPENING_ANSWER')
    decisive = [item for item in assertions if item['decision'] in ('SELF', 'OTHER')]
    # Generic opening yes cannot override a more specific current identity act.
    specific = [item for item in decisive if item['act']!='opening_confirmation']
    if specific: decisive=specific
    elif any(item['act'] in ('reported_identity','hypothetical_identity','quotation') for item in assertions):
        # An opening yes alongside attributed/delegated speech is not a literal
        # current naming assertion. An explicit unquoted self frame is separate.
        decisive=[]
    if any(item['act']=='identity_qualification' for item in assertions):
        result['reason']='QUALIFIED_CURRENT_IDENTITY'; return result
    choices = set(item['decision'] for item in decisive)
    if len(choices) == 1:
        result['decision'] = decisive[-1]['decision']
        result['recipient_self'] = result['decision'] == 'SELF'
        result['source_span'] = decisive[-1]['source_span']
        result['reason'] = decisive[-1]['reason']
    elif len(choices) > 1:
        result['reason'] = 'CONFLICTING_CURRENT_IDENTITIES'
    return result
