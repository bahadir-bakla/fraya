import json,re,datetime
HOLIDAYS=set(['2026-10-26','2026-11-11','2026-11-26','2026-12-25','2027-01-01'])
KINDS=set('recipient third_party wrong_number deceased security decline purpose agree confirm proposal refuse too_much vague paid dispute hardship plan human stop callback unknown question change'.split())
def decode(text):
    if not isinstance(text,str) or not text or len(text)>1800: raise ValueError('event')
    rows=[]
    for row in text.split('\n'):
        parts=row.split(';')
        if parts[-1]!='END': raise ValueError('terminal')
        d={}
        for p in parts[:-1]:
            if p.count('=')!=1: raise ValueError('separator')
            k,v=p.split('=')
            if k not in ('k','c','p','a','d','v','t','u') or k in d or not v or not re.fullmatch(r'[A-Za-z0-9 ,_./:-]+',v): raise ValueError('field')
            d[k]=v
        if d.get('k') not in KINDS or d.get('c') not in ('0','1'): raise ValueError('required')
        if 'u' in d and d['u'] not in ('amount','date','both','unknown'): raise ValueError('unresolved component')
        if 'u' in d and d['c']!='0': raise ValueError('unfinished marker')
        if 'a' in d and not re.fullmatch(r'\d+(\.\d{1,2})?',d['a']): raise ValueError('amount')
        if 'a' in d and not (0<=float(d['a'])<float('inf')): raise ValueError('finite amount')
        if 't' in d and not re.fullmatch(r'\d{2}:\d{2}',d['t']): raise ValueError('time')
        rows.append(d)
    return rows

def business(d): return d.weekday()<5 and d.isoformat() not in HOLIDAYS
def advance(d,n):
    while n:
        d+=datetime.timedelta(days=1)
        if business(d): n-=1
    return d

def number_words(s):
    units=dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),range(20)))
    tens=dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(),range(20,100,10)))
    words=s.replace('-',' ').split(); total=0; current=0
    for word in words:
        if word=='and': continue
        if word in units: current+=units[word]
        elif word in tens: current+=tens[word]
        elif word=='hundred': current*=100
        elif word=='thousand': total+=current*1000; current=0
        else: raise ValueError('number word')
    return total+current

def parse_date(s,today,dob=False):
    s=s.lower().strip()
    if not re.fullmatch(r'[a-z0-9 ,./-]+',s) or '..' in s or '--' in s: raise ValueError('date grammar')
    s=s.rstrip('.').replace(',',''); s=re.sub(r'\s+',' ',s)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',s): return datetime.date.fromisoformat(s)
    if re.fullmatch(r'\d{1,2}[/.-]\d{1,2}[/.-]\d{4}',s):
        a,b,c=re.split(r'[/.-]',s); return datetime.date(int(c),int(b),int(a))
    ordinal={'first':'one','second':'two','third':'three','fourth':'four','fifth':'five','sixth':'six','seventh':'seven','eighth':'eight','ninth':'nine','tenth':'ten','eleventh':'eleven','twelfth':'twelve','thirteenth':'thirteen','fourteenth':'fourteen','fifteenth':'fifteen','sixteenth':'sixteen','seventeenth':'seventeen','eighteenth':'eighteen','nineteenth':'nineteen','twentieth':'twenty','thirtieth':'thirty'}
    s=' '.join(ordinal.get(w,w) for w in s.replace('-',' ').split())
    s=re.sub(r'\b(the|of)\b',' ',s); s=re.sub(r'\s+',' ',s).strip()
    months='january february march april may june july august september october november december'.split()
    weekdays='monday tuesday wednesday thursday friday saturday sunday'.split()
    expected=None
    for wd in weekdays:
        if s.startswith(wd+' ') and s.split()[1] not in ('this','next'):
            expected=weekdays.index(wd); s=s[len(wd)+1:]; break
    found=[m for m in months if re.search(r'\b'+m+r'\b',s)]
    if len(found)==1:
        month=found[0]; before,after=s.split(month); before=before.strip(); after=after.strip()
        def num(v):
            v=re.sub(r'(\d)(st|nd|rd|th)\b',r'\1',v)
            return int(v) if v.isdigit() else number_words(v)
        if before: day=num(before); yeartext=after
        else:
            m=re.fullmatch(r'(\d{1,2})(?:st|nd|rd|th)?(?: (.+))?',after)
            if m: day=int(m[1]); yeartext=m[2] or ''
            else:
                tokens=after.split(); candidates=[]
                for count in range(1,min(3,len(tokens))+1):
                    try:
                        value=number_words(' '.join(tokens[:count]))
                        tail=' '.join(tokens[count:])
                        if 1<=value<=31 and (not tail or tail[:1].isdigit() or tail.startswith(('nineteen ','twenty ','two thousand'))): candidates.append((value,tail))
                    except ValueError: pass
                if len(candidates)!=1: raise ValueError('month first')
                day,yeartext=candidates[0]
        if not yeartext:
            if dob: raise ValueError('DOB year')
            year=today.year
        elif yeartext.startswith(('nineteen ','twenty ')) and not 'hundred' in yeartext and len(yeartext.split())>=2:
            head,tail=yeartext.split(' ',1); year=number_words(head)*100+number_words(tail)
        else: year=num(yeartext)
        d=datetime.date(year,months.index(month)+1,day)
        if expected is not None and d.weekday()!=expected: raise ValueError('weekday contradiction')
        return d
    if expected is not None:
        day=int(re.sub(r'(st|nd|rd|th)$','',s)) if re.fullmatch(r'\d{1,2}(st|nd|rd|th)?',s) else number_words(s)
        candidates=[]
        for shift in (0,1):
            month=(today.month-1+shift)%12+1; year=today.year+(today.month-1+shift)//12
            try:
                d=datetime.date(year,month,day)
                if d>=today and d.weekday()==expected: candidates.append(d)
            except ValueError: pass
        if len(candidates)!=1: raise ValueError('weekday ordinal ambiguity')
        return candidates[0]
    if dob: raise ValueError('DOB')
    if s=='today': return today
    if s=='tomorrow': return today+datetime.timedelta(days=1)
    m=re.fullmatch(r'(?:(next|this) )?('+ '|'.join(weekdays)+')',s)
    if m:
        idx=weekdays.index(m[2]); base=today-datetime.timedelta(days=today.weekday())
        if m[1]=='next': base+=datetime.timedelta(days=7)
        elif not m[1] and idx<today.weekday(): base+=datetime.timedelta(days=7)
        return base+datetime.timedelta(days=idx)
    raise ValueError('exact day')


def recipient_reply(raw,vars):
    r=str(raw or '').casefold().replace(chr(8217),"'").replace(chr(8216),"'")
    r,_=security_acts(r)
    if re.search(r'wrong (?:number|person)|not (?:me|here|available)|(?:he|she).*not here|(?:has |have )?died|deceased|(?:this is|i am|i\'m) (?:his|her|their|the) |(?:get|fetch|ask for).*speaking',r): return False
    if re.search(r'["\[\]{}]|\b(?:if|suppose|said|says|would be|not me|not speaking)\b',r) and not re.search(r"i just said[,]? that'?s me",r): return False
    def norm(v): return re.sub(r'\s+',' ',re.sub(r'[,!.:;]+',' ',str(v).casefold().replace(chr(8217),"'").replace(chr(8216),"'")).strip())
    first,last,title=[norm(vars.get(k,'')) for k in ('first_name','last_name','title')]
    if not first or not last: return False
    r=norm(r)
    r=re.sub(r'^(?:hello|hi|good morning|good afternoon) +','',r)
    if re.match(r"^(?:yes|speaking|that'?s me|that is me|it'?s me|i just said that'?s me)(?: |$)",r):
        m=re.search(r"(?:this is|i am|i'm) ([\w'-]+)",r)
        if m and m[1] not in (first,last,title): return False
        return True
    names=[first,last,first+' '+last,last+' '+first]
    if title: names += [title+' '+last,title+' '+first+' '+last,title+' '+last+' '+first]
    for n in names:
        if re.fullmatch(r"(?:(?:this is|i am|i'm|ben) )?"+re.escape(n)+r"(?: here| speaking| benim| konuşuyor)?(?: (?:what is this about|busy.*|sorry.*))?",r): return True
    return False

def blocked_acceptance(raw):
    r=raw.replace(chr(8217),chr(39)).replace(chr(8216),chr(39)).lower().strip()
    r=re.sub(r'\bno problem\b','',r)
    return bool(re.search(r"\b(no|not|never|cannot|can't|won't|didn't|don't|haven't|unless|if|maybe|perhaps|but|actually|instead|withdraw|cancel|hold on|wait|said|says|told|he|she|they)\b|\.\.\.|--|[\[\]{}\"“”]",r)) or not bool(re.search(r"\b(yes|confirm|agree|certainly|sure|okay|ok|can do|will pay)\b",r))

def offered_date(value,s,raw):
    # Day-only inheritance is tied to the unique active spoken offer and its revision.
    offer_value=s.get('offer')
    if s['phase']!='offer' or not offer_value or s.get('pending',{}).get('incomplete') or blocked_acceptance(raw): raise ValueError('unbound offer')
    v=value.lower().strip().rstrip('.').replace(',','')
    if not re.fullmatch(r'[a-z0-9 -]+',v): raise ValueError('ordinal grammar')
    v=re.sub(r'^the ','',v)
    v=re.sub(r'(\d)(st|nd|rd|th)$',r'\1',v)
    ords=dict(zip('first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth'.split(),'one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty'.split()))
    v=' '.join(ords.get(x,x) for x in v.replace('-',' ').split())
    day=int(v) if re.fullmatch(r'\d{1,2}',v) else number_words(v)
    date=datetime.date.fromisoformat(offer_value['date'])
    if not 1<=day<=31 or day!=date.day: raise ValueError('offer day mismatch')
    return date

def vague_date(value):
    return bool(re.fullmatch(r'(?:the )?(?:next week|week after next|end of (?:the )?month|end of (?:this|next) month|when my salary comes|payday|sometime|later)',value.lower().strip().rstrip('.')))

def resolve(ref,products):
    if not ref and len(products)==1: return products[0]
    norm=lambda s: re.sub(r'\s+',' ',str(s).replace('_',' ').lower().strip())
    matches=[p for p in products if ref==p['product_id'] or norm(ref) in (norm(p['type']),norm(p['label']))]
    if len(matches)!=1: raise ValueError('target')
    return matches[0]

def finish(s,outcome,reason='',message=''):
    if s.get('recorded') and outcome not in ('transferred',): outcome,reason='promise',''
    if outcome=='not_verified' and 'mobile app or a branch' not in message: message=(message+' Please use the mobile app or a branch.').strip()
    s['outcome'],s['reason']=outcome,reason
    return 'farewell',(message+' Thank you. Goodbye.').strip()

def question(s):
    phase=s['phase']
    if phase=='recipient': return 'Am I speaking with '+s['address']+'?'
    if phase=='dob': return 'Please tell me your date of birth, with the month as a word.'
    if phase=='phone': return 'Please tell me the last four digits of the phone number on file.'
    if phase=='callback': return 'When can the customer be reached, today or the next business day between 10:00 and 19:00?'
    if phase=='support': return 'Would you like me to connect you with the customer support team?'
    if phase=='human': return 'May I help you first? If you still want a person, please say so.'
    p=s.get('product',{})
    pending=s.get('pending',{})
    if pending.get('missing') in ('unknown','both'): return 'Please continue when you are ready.'
    if pending.get('missing')=='date': return 'What exact day will you pay that amount?'
    if pending.get('missing')=='amount' or pending.get('amount') is None: return 'Please continue when you are ready.'
    if not pending.get('date'): return 'What exact day will you pay that amount?'
    return 'Please clarify your answer for '+p.get('label','this product')+'.'

def offer(s,a,d,prefix=''):
    p=s['product']; s['offer_revision']=s.get('offer_revision',0)+1; s['offer']={'amount':a,'date':d.isoformat(),'revision':s['offer_revision']}; s['phase']='offer'; s['readback']=None
    warning=' The rest stays overdue.' if a<p['past_due'] and s.get('warning_amount')!=a else ''
    if warning: s['warning_amount']=a
    return prefix+warning+' Can you pay '+str(a)+' for your '+p['label']+' on '+d.strftime('%d %B %Y')+'?'

def readback(s):
    p=s['product']; q=s['pending']; s['phase']='readback'; s['readback']=dict(q)
    warning='The rest stays overdue. ' if q['amount']<p['past_due'] and s.get('warning_amount')!=q['amount'] else ''
    if warning: s['warning_amount']=q['amount']
    s['warned']=str(bool(warning) or s.get('warning_amount')==q['amount']).lower()
    return warning+'For your '+p['label']+', you will pay '+str(q['amount'])+' on '+datetime.date.fromisoformat(q['date']).strftime('%d %B %Y')+'. Do you confirm?'

def security_acts(raw):
    # Structural current-turn clauses: questions never supply answer operands.
    value=str(raw or '').replace(chr(8217),"'").replace(chr(8216),"'")
    interrogative=r"(?:why|what|how|when|where|who|which|whose|are|is|am|do|does|did|can|could|would|will|should|have|has|you\s+(?:a|an|human|real|digital|robot)|(?:the\s+)?(?:branch|opening|office|business|customer service)\s+(?:hours|times|open))\b"
    boundary=r"(?:^|(?<=[,;?!])\s*|(?<=\.)\s+|\s+(?:and|but|also)\s+)"
    starts=list(re.finditer(boundary+r"(?=(?:please\s+)?"+interrogative+r")",value,re.I))
    # Any separately punctuated question is an act, including noun phrases and
    # missing auxiliary verbs. A date's internal comma is not a clause boundary.
    spans=[]; flags=set()
    for match in starts:
        a=match.end(); tail=value[a:]
        terminal=re.search(r'[?;!]|\.(?=\s|$)',tail)
        b=a+terminal.end() if terminal else len(value)
        q=value[a:b].lower()
        if re.search(r'robot|\bai\b|digital|automated|real person|human',q): flags.add('ai')
        elif re.search(r'scam|legitim|authentic|genuine|trust|really.*bank',q): flags.add('scam')
        elif re.search(r'balance|owe|owed|debt|amount|money',q): flags.add('balance')
        elif re.search(r'security|verif|birth|digits|phone|question|protect|need.*(?:date|number)|ask',q): flags.add('security_purpose')
        elif re.search(r'call|contact|reason|purpose|about|reach',q): flags.add('purpose')
        else: flags.add('other')
        spans.append((a,b))
    for match in re.finditer(r'(?:^|[;.!]|,(?!\s*\d{4}\b)|\b(?:and|also)\b)\s*([^,;.!?]*\?)',value,re.I):
        q=match[1].lower(); a=match.start(1); b=match.end(1)
        # A positive answer followed by a bare question mark is still an answer.
        if re.match(r'(?:my |i was born|\d|zero\b|one\b|two\b|three\b|four\b|five\b|six\b|seven\b|eight\b|nine\b|ten\b|eleven\b|twelve\b|thirteen\b|fourteen\b|fifteen\b|sixteen\b|seventeen\b|eighteen\b|nineteen\b|twenty\b|thirty\b|forty\b|fifty\b|sixty\b|seventy\b|eighty\b|ninety\b)',q): continue
        spans.append((a,b))
        if re.search(r'robot|\bai\b|digital|automated|human|real person|^you\s+(?:a|an)\b',q): flags.add('ai')
        elif re.search(r'balance|owe|owed|debt|amount|money',q): flags.add('balance')
        else: flags.add('other')
    # Merge overlapping question masks before removing them.
    merged=[]
    for a,b in sorted(spans):
        if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    spans=merged
    for a,b in sorted(spans,reverse=True): value=value[:a]+' '+value[b:]
    value=re.sub(r'(?:[,;.!?]\s*)?(?:and|but|also)\s*$', '',value.strip(),flags=re.I)
    return value.strip(' ,;.!?'),flags

def security_fallback(raw,phase,today):
    # Project explicit source operands, rather than fullmatching a sentence list.
    # The result is only a comparison candidate; the bank establishes validity.
    if phase not in ('dob','phone'): return None
    value,flags=security_acts(raw)
    if not value: return None
    value=value.lower().strip()
    if phase=='phone':
        # Width words in the requested-field label describe the question, not
        # spoken answer operands. Preserve subject/polarity around the label.
        value=re.sub(r'\blast (?:four|4) (?:phone )?digits\b','requested suffix digits',value)
        value=re.sub(r'\bphone(?: number)? last (?:four|4)\b','phone number suffix',value)
    units='zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
    tens='twenty thirty forty fifty sixty seventy eighty ninety'.split()
    ordinals='first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth'.split()
    months='january february march april may june july august september october november december'.split()
    vocabulary=units+tens+ordinals+(months+['hundred','thousand','and','the','of'] if phase=='dob' else [])
    atom=r'(?:\d+(?:st|nd|rd|th)?|'+ '|'.join(vocabulary)+r')'
    pattern=r'(?<![a-z0-9])'+atom+r'(?:(?:[ ,./-]+)'+atom+r')*(?![a-z0-9])'
    operands=[]
    for m in re.finditer(pattern,value):
        operand=m[0].strip(' ,./-')
        if operand in ('and','the','of'): continue
        prefix=value[:m.start()]
        local=re.split(r'[;.!?]|,(?!\s*\d{4}\b)|\b(?:and|but)\b',prefix)[-1]
        suffix=value[m.end():]
        # Unsupported subject/polarity/quoted/hypothetical answer spans never
        # become self answers; an independently masked question cannot lend digits.
        if re.search(r'["\[\]{}]',value) or re.search(r"\b(?:not|never|no|isn't|wasn't|if|suppose|hypothetically|maybe|either|or|his|her|their|he|she|they|wife|husband|mother|father|friend|daughter|son|cousin|diary|note|invoice|parcel|record|quoted)\b",local): return None
        # An answer may be bare or refer to self/current requested value. An
        # arbitrary named subject cannot borrow the current security question.
        context=local.strip(' ,:-')
        if re.search(r"\bmy\s+(?!date\b|birth\b|phone\b|number\b|last\b|requested\b)[a-z]+(?:'s|\s+(?:date|birth|phone|number))",context): return None
        if re.search(r"\b[a-z]+(?:'s|s')\s+(?:date|birth|phone|number)",context): return None
        if context and not re.search(r"\b(?:my|i|i'm|it is|it's|that is|that's|date of birth|birth date|requested suffix digits|phone number)\b",context) and not re.fullmatch(r'(?:yes|okay|ok|sure|well|actually|sorry|instead|correction|born on)(?:[ ,]+(?:yes|okay|ok|sure|well|actually|sorry))*',context): return None
        if re.search(r'\bor\b',suffix): return None
        if re.match(r'\s*(?:\.\.|--|…|—)',suffix): return None
        # A lexical neutral aside may follow; explicit correction must supply a
        # complete replacement, not silently keep the old operand.
        if re.search(r'\b(?:actually|instead|i mean|correction|sorry)\b',suffix) and not re.search(pattern,suffix): return None
        try:
            if phase=='dob':
                if operand.endswith(' and'):
                    if not re.match(r'\s*(?:i\b|my\b|thanks\b)',suffix): return None
                    operand=operand[:-4].strip()
                operand=re.sub(r'\s+(?:and|the|of)$','',operand)
                parsed=parse_date(operand,today,True)
                if not 1000<=parsed.year<=today.year or parsed>today: return None
                normalized=parsed.isoformat()
            else:
                tokens=re.findall(r'\d+|[a-z]+',operand)
                groups=[]; i=0
                while i<len(tokens):
                    token=tokens[i]
                    if token.isdigit(): groups.append(token)
                    elif token in units: groups.append(str(units.index(token)))
                    elif token in tens:
                        n=(tens.index(token)+2)*10
                        if i+1<len(tokens) and tokens[i+1] in units[1:10]: i+=1; n+=units.index(tokens[i])
                        groups.append(str(n))
                    else: return None
                    i+=1
                normalized=''.join(groups)
                if not re.fullmatch(r'\d{4}',normalized): return None
            if operands and normalized!=operands[-1]:
                if not re.search(r'\b(?:actually|instead|i mean|correction|sorry)\b',local): return None
                operands=[]
            operands.append(normalized)
        except Exception: return None
    if not operands: return None
    return dict(k='security',c='1',v=operands[-1])

def security_cue(s,raw):
    if s['phase']=='phone': return 'Please finish all four digits of the phone number on file.'
    value=str(raw or '').lower()
    if any(m in value for m in 'january february march april may june july august september october november december'.split()) and not re.search(r'\b\d{4}\b',value): return 'Please finish the year of birth.'
    return 'Please finish your complete date of birth, including the year.'

def primary_raw(raw,s,today):
    r=raw.lower().strip()
    if not r or re.search(r'[\"\[\]{}]|\.\.\.|--|\b(?:hypothetically|suppose|if|maybe)\b',r): return None
    if s['phase']=='recipient' and re.search(r"\b(?:i am|i'm|this is|her|his)\s+(?:her |his |the )?(?:husband|wife|mother|father|sister|brother|son|daughter|partner)\b",r): return {'k':'third_party','c':'1'}
    if s['phase']=='support' and re.search(r"^no(?:[,.! ]|$)(?! problem)|do not want to be transferred|don't want.*transfer|decline",r): return {'k':'decline','c':'1'}
    if re.search(r'lower instalments|lower installments|new payment plan|smaller (?:amount|payment).*each month|instalments to be lower|installments to be lower',r) and not re.search(r'illness|ill|lost my job|job loss|death in|died',r): return {'k':'plan','c':'1'}
    if re.search(r'(?:want|speak|talk|connect|transfer).*\b(?:human|person|agent|representative)\b',r) and not re.search(r'robot|\bai\b',r): return {'k':'human','c':'1'}
    if s['phase'] in ('dob','phone'):
        ans=security_fallback(raw,s['phase'],today)
        if ans: return ans
        answer_text,flags=security_acts(raw)
        if re.search(r"^(?:no[, ]+)?(?:i (?:refuse|decline|will not|won't|do not want to|don't want to)|not (?:answering|giving|sharing))\b",answer_text,re.I): return {'k':'decline','c':'1'}
        if not answer_text and 'purpose' in flags: return {'k':'purpose','c':'1'}
    return None
def callback_fallback(raw,today):
    r=raw.lower()
    dates=re.findall(r'\b(today|tomorrow|(?:next|this) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|\d{4}-\d{2}-\d{2})\b',r)
    if len(dates)!=1: return None
    tm=re.search(r'\b(\d{1,2}):(\d{2})\b',r)
    if tm: hour=int(tm[1]); minute=int(tm[2])
    else:
        tm=re.search(r'\b(?:at|around|about) (\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b',r)
        if not tm: return None
        hour=int(tm[1]) if tm[1].isdigit() else number_words(tm[1]); minute=0
    if ('afternoon' in r or 'pm' in r) and hour<12: hour+=12
    if 'morning' in r and hour==12: hour=0
    if not 0<=hour<24 or not 0<=minute<60: return None
    return {'k':'callback','c':'1','d':dates[0],'t':('%02d:%02d'%(hour,minute))}

def disposition_source(raw,kind):
    text=str(raw or '').lower().replace(chr(8217),"'").replace(chr(8216),"'")
    if not text or re.search(r'["“”\[\]{}]|\b(?:hypothetically|suppose|diary|invoice|parcel|quoted|note says)\b|\.\.\.',text): return False
    if kind=='paid':
        if re.search(r"\b(?:haven't|hadn't|didn't|not paid|never paid|not sure|bounced|reversed|years ago|last year|paid off|closed|rent|shopping|purchase|will pay|scheduled|going to pay)\b",text): return False
        positive=False
        for clause in re.split(r'[;.!?]|\bbut\b',text):
            if re.search(r"\b(?:if|maybe|he|she|they|his|her|their)\b",clause): continue
            if re.search(r"\bi(?:'ve| have)?\s+(?:(?:already|just|actually|successfully)\s+)*(?:paid(?: it| this| the| my)?|made (?:the|my|this) payment|processed (?:the|my|this) payment)\b",clause): positive=True
        return positive
    return bool(re.search(r"(?:\b(?:this|the|my) (?:debt|product|account|card|loan).*(?:not mine|closed|paid off)|\bi (?:never had|never took|didn't take|did not take|paid off|closed)\b)",text))


def raw_date(raw,today):
    # Extract only a uniquely asserted complete date in payment speech. Never a fragment or negated date.
    r=raw.lower()
    if re.search(r'\.\.\.|--|not sure|hold on|no wait',r): return None
    month='january|february|march|april|may|june|july|august|september|october|november|december'
    ordinal='(?:\d{1,2}(?:st|nd|rd|th)?|(?:twenty[ -]|thirty[ -])?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|thirtieth))'
    weekday='monday|tuesday|wednesday|thursday|friday|saturday|sunday'
    pattern=r'\b(?:\d{4}-\d{2}-\d{2}|(?:the )?'+ordinal+r' (?:of )?(?:'+month+r')(?: \d{4})?|(?:'+weekday+r') (?:the )?'+ordinal+r'|(?:this|next) (?:'+weekday+r')|today|tomorrow)\b'
    values=[]
    for m in re.finditer(pattern,r):
        prefix=r[max(0,m.start()-30):m.start()]
        if re.search(r"(?:cannot|can't|can not|not|won't|will not)(?: pay)?(?: (?:that|it))?\s*$",prefix): continue
        try: parse_date(m[0],today)
        except Exception: continue
        values.append(m[0])
    return values[0] if len(values)==1 else None


def correction_component(raw,e):
    if e.get('u'): return e['u']
    text=raw.lower()
    # Compatibility for older events: identify the fragment, not a completed sibling.
    amount_fragment=bool(re.search(r'\b(amount|dollars|pounds|euros)\b',text) or re.search(r'\b(?:pay|make it)\s+(?:[a-z ]*hundred|[a-z ]*thousand|\d+)[a-z ]*and\s*(?:\.\.\.|--|$)',text))
    date_fragment=bool(re.search(r'\b(date|day)\b',text) or re.search(r'\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*(?:\.\.\.|--|$)',text) or re.search(r'\b(on|until)\s*[. -]*$',text))
    if amount_fragment and 'd' in e and 'a' not in e: return 'amount'
    if date_fragment and 'a' in e and 'd' not in e: return 'date'
    if amount_fragment and date_fragment: return 'both'
    if amount_fragment: return 'amount'
    if date_fragment: return 'date'
    if 'd' in e and 'a' not in e: return 'amount'
    if 'a' in e and 'd' not in e: return 'date'
    return 'unknown'

def invalidate_component(q,component,e,today):
    q['incomplete']=True; q['missing']=component
    q['required_components']=['amount','date'] if component in ('both','unknown') else [component]
    q['completed_components']=[]
    if component in ('amount','both'): q.pop('amount',None)
    if component in ('date','both'): q.pop('date',None)
    # Typed complete facts can update only the unaffected sibling.
    if 'a' in e and component=='date': q['amount']=float(e['a'])
    if 'd' in e and component=='amount':
        try: q['date']=parse_date(e['d'],today).isoformat()
        except Exception: q.pop('date',None)

def recover(s,raw,e=None):
    s['readback']=None
    if s['verified'] and s.get('pending'):
        q=s['pending']
        if re.search(r'\b(actually|instead|change|but|no wait|i mean|cannot|can not)\b',raw.lower()):
            component=correction_component(raw,e or {})
            invalidate_component(q,component,e or {},datetime.datetime.fromisoformat(s['now']).date())
            return question(s)
        if q.get('incomplete'): return question(s)
        if q.get('amount') is not None and q.get('date'): return readback(s)
    return 'Please repeat that clearly. '+question(s)

def run(vars):
    s=vars.get('state'); s=json.loads(json.dumps(s)) if isinstance(s,dict) else s; mode=vars.get('mode','event'); vars['mode']='event'; route='talk'; line=''
    if not isinstance(s,dict):
        now=datetime.datetime.fromisoformat(str(vars['now']))
        s={'phase':'recipient','address':str(vars.get('title',''))+' '+str(vars.get('last_name','')),'now':now.isoformat(),'verified':False,'recipient_asks':1,'wrong':0,'security_clarifications':0,'dob_passed':False,'declines':0,'stops':0,'formats':0,'attempts':0,'callback_tries':0,'human_asked':False,'recorded':False,'pending':{},'readback':None,'offer':None,'vague':0,'floor_offered':False,'too_much':False,'hardship':False,'outcome':'not_reached','reason':'unclear','write_tries':0,'admin':'','steps':0,'no_progress':0}
        line='Hello, I am a digital assistant calling from Freya Bank, and this call is recorded. '+question(s)
    else:
        today=datetime.datetime.fromisoformat(s['now']).date()
        s['steps']=s.get('steps',0)+1
        if s['steps']>65:
            route,line=finish(s,'no_promise' if s['verified'] else 'not_verified','service_error' if s['verified'] else 'failed','I cannot continue safely. Please use the mobile app or a branch.')
            vars.update(state=s,route=route,dialogue_line=line,outcome=s['outcome'],reason=s['reason'],mode='event',bank_result={},event='',raw='',admin='none')
            return
        result=vars.get('bank_result',{}); vars['bank_result']={}
        if mode!='event':
            if mode!=s.get('awaiting'): mode='event'; result={}
            if mode in ('verify','account'):
                dispatch=s.get('read_dispatch',{})
                node='verify_identity' if mode=='verify' else 'get_account'
                expected={'customer_id':str(vars.get('customer_id',''))}
                if mode=='verify': expected.update(field=vars.get('security_field'),answer=vars.get('security_answer'))
                matching=(dispatch.get('node')==node and dispatch.get('request')==expected and
                    dispatch.get('phase')==s.get('phase') and
                    vars.get('read_started')==dispatch.get('token') and
                    vars.get('read_completed')==dispatch.get('token') and
                    int(vars.get(node+'_success_count',0) or 0)==dispatch.get('success_base',-1)+1 and
                    int(vars.get(node+'_failure_count',0) or 0)==dispatch.get('failure_base',-1) and
                    str(vars.get('bank_status',''))=='200')
                if not matching: result={}; vars['bank_status']=''
                s['read_dispatch']={}; vars['read_started']=''; vars['read_completed']=''
                for suffix in ('_ok','_response.data.ok','_response.data.verified','_response.data.all_verified','_response.data.products','_response.status_code','_status_code'):
                    vars[node+suffix]=''
                vars['products']=[]
            if mode=='promise':
                # Automatic metadata is authoritative only for this dispatched request.
                dispatch=s.get('promise_dispatch',{})
                request=dispatch.get('request',{})
                matching=(dispatch.get('node')=='create_promise' and
                    dispatch.get('attempt')==s.get('write_tries') and
                    vars.get('promise_started')==dispatch.get('token') and
                    request==s.get('authorized_promise') and
                    request.get('customer_id')==str(vars.get('customer_id','')) and
                    request.get('product_id')==s.get('product',{}).get('product_id') and
                    request.get('amount')==s.get('pending',{}).get('amount') and
                    request.get('date')==s.get('pending',{}).get('date') and
                    not s.get('recorded') and s.get('verified'))
                failures=int(vars.get('create_promise_failure_count',0) or 0)
                successes=int(vars.get('create_promise_success_count',0) or 0)
                fresh_failure=(failures==dispatch.get('failure_base',-1)+1 and
                    successes==dispatch.get('success_base',-1))
                fresh_success=(successes==dispatch.get('success_base',-1)+1 and
                    failures==dispatch.get('failure_base',-1))
                status=str(vars.get('create_promise_response.status','')).lower()
                status_code=str(vars.get('create_promise_response.status_code',''))
                http_error=str(vars.get('create_promise_response.error',''))
                # Only the source's documented HTTP 500 guarantees no recording.
                documented_failure=(matching and fresh_failure and status=='error' and
                    status_code=='500' and
                    str(vars.get('create_promise_status_code',''))=='500' and
                    re.fullmatch(r'HTTP\s*500',http_error,re.I) is not None)
                if not matching or not (fresh_success or fresh_failure):
                    result={}; vars['bank_status']=''
                elif documented_failure:
                    result={'ok':False,'error':'documented_http_500_no_record'}
                    vars['bank_status']='500'
                elif not fresh_success:
                    # Timeout, sandbox failure, and unrecognized HTTP errors stay unknown.
                    result={}; vars['bank_status']=''
                s['promise_dispatch']={}
                vars['promise_started']=''
                for key in ('create_promise_response.status','create_promise_response.error',
                    'create_promise_response.status_code','create_promise_status_code',
                    'create_promise_response.data.ok','create_promise_ok'):
                    vars[key]=''
            s['awaiting']=''
        ok=isinstance(result,dict) and str(result.get('ok','')).lower()=='true'
        if mode=='verify':
            if result.get('hint')=='day_month_swapped': line='Please say the month as a word. '+question(s)
            elif not ok: line='I could not read that answer. '+question(s)
            elif s['phase']=='phone' and s.get('dob_passed') and str(result.get('verified','')).lower()=='true' and str(result.get('all_verified','')).lower()=='true': s['verified']=True; route='get_account'
            elif s['phase']=='dob' and str(result.get('verified','')).lower()=='true': s['dob_passed']=True; s['phase']='phone'; s['security_clarifications']=0; line=question(s)
            elif str(result.get('verified','')).lower() not in ('false',): line='I could not complete the security comparison. '+question(s)
            else:
                s['wrong']+=1
                if s['wrong']>=3 or str(result.get('wrong_answers_left'))=='0': route,line=finish(s,'not_verified','failed','Please use the mobile app or a branch.')
                else: line='That answer did not match. '+question(s)
        elif mode=='account':
            products=result.get('products',[]) if isinstance(result,dict) else []
            if isinstance(products,str): products=json.loads(products)
            if not ok or not s['verified'] or not isinstance(products,list) or len(products)!=1: route,line=finish(s,'no_promise','service_error','I cannot access the account information.')
            else:
                p=dict(products[0]); typ=p['type']; assert typ in ('credit_card','personal_loan','car_loan')
                p['label']=typ.replace('_',' ')+(' ending '+p['card_last4'] if typ=='credit_card' else '')
                p['floor']=float(p['minimum_payment'] if typ=='credit_card' else p['instalment_amount']); p['past_due']=float(p['past_due']); late=int(p['days_late']); assert 1<=late<=45 and 0<p['floor']<=p['past_due'] and p['product_id']
                p['deadline']=advance(today,12 if late<=7 else 7).isoformat(); p['limit']=1 if late<=7 else 2
                s['product']=p; s['products']=[p]; s['phase']='offer'; s['offer_revision']=1; s['offer']={'amount':p['past_due'],'date':today.isoformat(),'revision':1}; s['pending']={}
                line='I am calling from the collections team about a late payment on your '+p['label']+'. The past-due amount is '+str(p['past_due'])+', and it is '+str(late)+' days late. Can you make this payment today?'
        elif mode=='promise':
            if ok:
                s['recorded']=True; s['receipt']={'promise_id':str(result.get('promise_id','')),'product_id':s['product']['product_id'],'amount':s['pending']['amount'],'date':s['pending']['date']}; s['phase']='recorded'; route,line=finish(s,'promise','','Your promise is recorded. You will receive a text message confirming this promise.')
            elif s['write_tries']<2 and (str(vars.get('bank_status',''))=='500' or (isinstance(result,dict) and 'ok' in result and str(result['ok']).lower()=='false')): s['write_tries']+=1; route='create_promise'
            else: route,line=finish(s,'no_promise','service_error','I could not record your promise.')
        elif mode=='transfer':
            if ok: route,line=finish(s,'transferred',s['transfer_reason'],'I am connecting you with the team.')
            else: route,line=finish(s,'no_promise' if s['verified'] else 'not_verified','service_error' if s['verified'] else 'failed','I could not connect you. Please contact the bank directly.')
        elif mode=='callback_result': route,line=finish(s,'not_reached','callback' if ok else 'no_callback','Your callback is scheduled.' if ok else 'I could not schedule a callback.')
        else:
            text=vars.get('event',''); raw=str(vars.get('raw') or ''); admin=str(vars.get('admin') or '')
            if s['phase']=='recipient' and vars.get('recipient_act') in ('recipient','third_party','wrong_number','deceased','unknown'): text='k='+vars['recipient_act']+';c=1;END'
            if s['phase'] in ('dob','phone') and vars.get('security_value'): text='k=security;c=1;v='+str(vars['security_value'])+';END'
            if re.search(r'robot|\bai\b|digital assistant',raw.lower()) or (s['phase']=='recipient' and recipient_reply(raw,vars) and re.search(r'\bare you(?: a| an)?[ .…?!]*$',raw.lower())): admin+=' ai'
            if re.search(r'scam|legitimate',raw.lower()): admin+=' scam'
            if re.search(r'what.*call.*about|how much.*owe|why.*calling',raw.lower()): admin+=' purpose'
            if re.search(r'why.*(?:asking|need)|what.*questions?.*(?:for|protect)|security.*(?:for|why)',raw.lower()): admin+=' security_purpose'
            if re.search(r'(?:if|could|can).*\b(?:relative|wife|husband|family member)\b.*(?:answer|pay)',raw.lower()): admin+=' relative_policy'
            _,question_flags=security_acts(raw)
            allowed_admin=set('ai scam purpose balance security_purpose relative_policy other'.split())
            admin_flags=set(admin.split()).intersection(allowed_admin) | question_flags
            if admin_flags: s['admin']=' '.join(sorted(admin_flags))
            if s['phase'] in ('dob','phone'):
                span,_=security_acts(raw)
                if s.get('security_buffer_phase')!=s['phase']: s['security_buffer']=''; s['security_buffer_phase']=s['phase']
                if span and not security_fallback(raw,s['phase'],today) and re.fullmatch(r'[0-9a-zA-Z ,./-]+',span) and not re.search(r'\b(my|his|her|their|he|she|they|if|not|no|or)\b',span.lower()):
                    buffer=s.get('security_buffer','')
                    combined=(buffer+' '+span).strip()
                    candidate=security_fallback(combined,s['phase'],today)
                    if candidate: raw=combined; s['security_buffer']=''
                    elif len(combined)<90: s['security_buffer']=combined
                elif security_fallback(raw,s['phase'],today): s['security_buffer']=''
            primary=primary_raw(raw,s,today)
            if s['phase']=='recipient' and recipient_reply(raw,vars): primary={'k':'recipient','c':'1'}
            if s['phase']=='callback': primary=callback_fallback(raw,today) or primary
            try:
                try:
                    rows=decode(text) if text else []
                    complete_security=[r for r in rows if r['k']=='security' and r['c']=='1' and r.get('v')]
                    if primary and not (s['phase'] in ('dob','phone') and primary['k'] in ('purpose','security') and complete_security): rows=[primary]
                    if not rows: raise ValueError('missing event')
                except Exception:
                    fallback=primary if s['phase']=='recipient' and primary else security_fallback(raw,s['phase'],today) if s['phase'] in ('dob','phone') else None
                    if not fallback: raise
                    rows=[fallback]
                if len(rows)==1 and rows[0]['k']=='security' and not rows[0].get('v') and rows[0]['c']=='1':
                    fallback=security_fallback(raw,s['phase'],today)
                    if fallback: rows=[fallback]
                # All rows validated before state mutation. Brief A has one returned product.
                if s['verified']:
                    for row in rows:
                        if row.get('p'): resolve(row['p'],s['products'])
                if len(rows)>1:
                    rows=[r for r in rows if r['k'] not in ('question','purpose')] or rows
                if len(rows)>1 and s['verified'] and all(r['k'] in ('proposal','change') and r['c']=='1' for r in rows):
                    combined={'k':'proposal','c':'1'}
                    for row in rows:
                        if row.get('p'): resolve(row['p'],s['products'])
                        for component in ('a','d'):
                            if component in row:
                                if component in combined and combined[component]!=row[component]: raise ValueError('conflicting components')
                                combined[component]=row[component]
                    rows=[combined]
                if len(rows)>1:
                    if all(r['k'] in ('agree','confirm') and r['c']=='1' and not any(key in r for key in ('a','d')) for r in rows): e=rows[0]
                    elif len([r for r in rows if r['k']=='proposal'])==1 and all(r['k'] in ('proposal','too_much') and r['c']=='1' for r in rows): e=next(r for r in rows if r['k']=='proposal'); s['too_much']=True
                    elif any(r['k']=='human' and r['c']=='1' for r in rows): e=next(r for r in rows if r['k']=='human')
                    elif any(r['k']=='hardship' and r['c']=='1' for r in rows): e=next(r for r in rows if r['k']=='hardship')
                    elif any(r['k']=='plan' and r['c']=='1' for r in rows): e=next(r for r in rows if r['k']=='plan')
                    else: raise ValueError('multiple decisions require clarification')
                else: e=rows[0]
                if s['verified'] and e['k'] in ('paid','dispute') and not disposition_source(raw,e['k']):
                    raise ValueError('unsupported current bank disposition')
                if e['k']=='human' and re.search(r'robot|\bai\b',raw.lower()) and not re.search(r'(?:want|speak|talk|transfer).*\b(?:human|person|representative)\b',raw.lower()):
                    e={'k':'question','c':'1'}
                if e['k']!='unknown': s['formats']=0
            except Exception:
                s['formats']+=1; s['readback']=None
                if s['formats']>=3: route,line=finish(s,'no_promise' if s['verified'] else 'not_verified' if s['phase']!='recipient' else 'not_reached','service_error' if s['verified'] else 'failed' if s['phase']!='recipient' else 'unclear','I could not understand the answer clearly. Please use the mobile app or a branch.')
                else: line=recover(s,raw)
                e=None
            if e:
                k=e['k']; phase=s['phase']
                if phase!='recipient' and k in ('agree','confirm') and blocked_acceptance(raw):
                    e=dict(e); e['c']='0'; e['u']=correction_component(raw,e)
                # Completion guard precedes all phase-specific consent and actions.
                unfinished=e['c']=='0' or (k in ('agree','confirm') and not ('a' in e or 'd' in e) and bool(re.search(r'\b(actually|instead|change|but|no wait|i mean|cannot|can not)\b',raw.lower()))) or bool(re.search(r'(?:actually|change|instead|no wait|i mean).*(?:\.\.\.|â€”|--|not sure|hold on|wait)\s*$',raw.lower()))
                if unfinished:
                    s['readback']=None
                    if s['verified']:
                        q=s.setdefault('pending',{}); invalidate_component(q,correction_component(raw,e),e,today)
                    if phase in ('dob','phone'):
                        s['security_clarifications']=s.get('security_clarifications',0)+1
                        line=security_cue(s,raw)
                        if s['security_clarifications']>=3: route,line=finish(s,'not_verified','failed','I could not complete the security check. Please use the mobile app or a branch.')
                    else: line=question(s)
                elif k=='human':
                    s['readback']=None
                    if s['human_asked'] or phase=='human': s['queue']='general'; s['transfer_reason']='human'; route='transfer_to_agent'
                    else: s['human_asked']=True; s['resume']=phase; s['phase']='human'; line=question(s)
                elif k=='stop':
                    s['readback']=None; s['stops']+=1
                    if s['stops']>=2: route,line=finish(s,'no_promise' if s['verified'] else 'not_verified','refused' if s['verified'] else 'declined')
                    else: s['resume']=phase; s['phase']='paused'; line='I understand. May we continue briefly?'
                elif k in ('wrong_number','deceased') and not s['verified']: route,line=finish(s,'not_reached',k,'I am sorry for your loss.' if k=='deceased' else '')
                elif phase=='recipient':
                    if k in ('recipient','agree','confirm') and recipient_reply(raw,vars): s['phase']='dob'; line=question(s)
                    elif k=='third_party': s['phase']='callback'; s['third_party']=True; line=question(s)
                    else:
                        s['recipient_asks']+=1
                        if s['recipient_asks']>2: route,line=finish(s,'not_reached','unclear')
                        else: line=question(s)
                elif phase=='callback':
                    try:
                        d=parse_date(e.get('d',''),today); t=datetime.time.fromisoformat(e.get('t','')); dt=datetime.datetime.combine(d,t); now=datetime.datetime.fromisoformat(s['now'])
                        assert k=='callback' and d in (today,advance(today,1)) and datetime.time(10)<=t<=datetime.time(19) and dt>now
                        vars['callback_date']=d.isoformat(); vars['callback_time']=t.strftime('%H:%M'); route='schedule_callback'
                    except Exception:
                        s['callback_tries']+=1
                        if s['callback_tries']>=2: route,line=finish(s,'not_reached','no_callback')
                        else: line=question(s)
                elif phase in ('dob','phone'):
                    if k in ('question','unknown') and set(s.get('admin','').split()).intersection(('security_purpose','relative_policy','ai','scam')) and not set(s.get('admin','').split()).intersection(('purpose','balance')): line=question(s)
                    elif k in ('decline','purpose'):
                        s['declines']+=1
                        if s['declines']>=2: route,line=finish(s,'not_verified','declined','Please use the mobile app or a branch.')
                        else: line='These questions protect your account. I can explain the purpose after verification. '+question(s)
                    else:
                        try:
                            assert k=='security'
                            answer=e.get('v','')
                            if not raw.strip(): raise ValueError('missing mandatory current source')
                            if raw:
                                candidate=security_fallback(raw,phase,today)
                                if not candidate: raise ValueError('not a complete current security answer')
                                if answer:
                                    canonical=parse_date(answer,today,True).isoformat() if phase=='dob' else answer
                                    if canonical!=candidate['v']: raise ValueError('conflicting security evidence')
                                answer=candidate['v']
                            s['security_clarifications']=0
                            # The whole-answer fallback already rejects unresolved corrections and unrelated clauses.
                            if phase=='dob': answer=parse_date(answer,today,True).isoformat()
                            else: assert re.fullmatch(r'\d{4}',answer)
                            s['security_buffer']=''; s['security_buffer_phase']=''
                            vars['security_field']='date_of_birth' if phase=='dob' else 'phone_last4'; vars['security_answer']=answer; route='verify_identity'
                        except Exception:
                            s['security_clarifications']=s.get('security_clarifications',0)+1
                            line=security_cue(s,raw)
                            if s['security_clarifications']>=3: route,line=finish(s,'not_verified','failed','I could not complete the security check. Please use the mobile app or a branch.')
                elif phase=='paused':
                    s['phase']=s.get('resume','offer'); s['readback']=None
                    line=readback(s) if s.get('pending',{}).get('amount') is not None and s.get('pending',{}).get('date') and not s['pending'].get('incomplete') else question(s)
                elif phase=='human':
                    if k in ('refuse','decline'): s['queue']='general'; s['transfer_reason']='human'; route='transfer_to_agent'
                    else: s['phase']=s['resume']; line=question(s)
                elif s['verified']:
                    p=s['product']; deadline=datetime.date.fromisoformat(p['deadline'])
                    if k=='hardship':
                        s['hardship']=True; s['readback']=None
                        if 'a' in e or 'd' in e: k='proposal'; line='I am sorry you are going through this. '
                        else: s['phase']='support'; line='I am sorry you are going through this. '+question(s)
                    if k=='plan': s['readback']=None; s['queue']='restructuring'; s['transfer_reason']='restructuring'; route='transfer_to_agent'
                    elif k=='paid': route,line=finish(s,'paid','','Payments can take one business day to appear.')
                    elif k=='dispute': route,line=finish(s,'no_promise','dispute')
                    elif phase=='support' and k in ('agree','confirm'): s['queue']='support'; s['transfer_reason']='support'; route='transfer_to_agent'
                    elif phase=='support' and k in ('refuse','decline'): route,line=finish(s,'no_promise','hardship','I cannot offer a discount.' if re.search(r'discount|waiver',raw.lower()) else '')
                    elif k=='change' and s['recorded']: line='You can change the recorded promise in the mobile app.'
                    elif k in ('proposal','change') or (k in ('agree','confirm') and ('a' in e or 'd' in e)):
                        s['readback']=None; q=s.setdefault('pending',{}); missing=q.get('missing'); unresolved=q.get('incomplete',False)
                        if 'a' in e: q['amount']=float(e['a'])
                        elif not q.get('amount') and s.get('offer') and not missing and not unresolved: q['amount']=s['offer']['amount']
                        if 'd' in e:
                            try:
                                try: date_value=parse_date(e['d'],today)
                                except ValueError:
                                    date_value=offered_date(e['d'],s,raw)
                                q['date']=date_value.isoformat()
                            except Exception:
                                q.pop('date',None)
                                if vague_date(e['d']):
                                    s['vague']+=1
                                    if s['vague']>=2 and not q.get('incomplete'):
                                        q['date']=deadline.isoformat(); s['date_fallback']=True
                        # Count only explicit completed facts since this correction began.
                        # Retained cache and spoken counteroffers cannot complete a requirement.
                        required=q.get('required_components')
                        if unresolved and not required:
                            required=['amount','date'] if missing in ('both','unknown') else [missing]
                            q['required_components']=required
                        completed=list(q.get('completed_components',[]))
                        if unresolved:
                            if 'a' in e and 'amount' in required and 'amount' not in completed: completed.append('amount')
                            if 'd' in e and q.get('date') and 'date' in required and 'date' not in completed: completed.append('date')
                            # An invalid replacement invalidates its earlier completion too.
                            if 'd' in e and not q.get('date') and 'date' in completed: completed.remove('date')
                            q['completed_components']=completed
                            remaining=[part for part in required if part not in completed]
                            resolved=not remaining
                            if remaining: q['missing']=remaining[0] if len(remaining)==1 else missing
                        else: resolved=True
                        if resolved:
                            q.pop('incomplete',None); q.pop('missing',None)
                            q.pop('required_components',None); q.pop('completed_components',None)
                        if q.get('incomplete'):
                            line+=question(s)
                        elif q.get('amount') is None or not q.get('date'):
                            q['missing']='amount' if q.get('amount') is None else 'date'; line+=question(s)
                        else:
                            a=q['amount']; d=datetime.date.fromisoformat(q['date'])
                            if a<p['floor']:
                                s['too_much']=True
                                if s['floor_offered']: k='refuse'
                                else: s['floor_offered']=True; line=offer(s,p['floor'],d if today<=d<=deadline and business(d) else deadline,'That amount cannot be recorded. The minimum amount is '+str(p['floor'])+'.'); q.clear(); q['missing']='amount'
                            elif a>p['past_due']: q.pop('amount'); q['missing']='amount'; line='The full past-due amount is '+str(p['past_due'])+'. '+question(s)
                            elif d<today: q.pop('date'); line='The date must be today or later. '+question(s)
                            elif d>deadline: line=offer(s,a,deadline,'The latest date I can record is '+deadline.strftime('%d %B %Y')+'.'); q.clear()
                            elif not business(d):
                                nextday=advance(d,1); line=offer(s,a,min(nextday,deadline),'That is not a business day.'); q.clear()
                            elif s.pop('date_fallback',False): line=offer(s,a,deadline,'The latest date I can record is '+deadline.strftime('%d %B %Y')+'.'); q.clear()
                            else: line+=readback(s)
                    elif k in ('agree','confirm'):
                        if phase=='readback' and s.get('readback')==s.get('pending') and not s['pending'].get('incomplete'):
                            q=s['pending']; d=datetime.date.fromisoformat(q['date']); assert s['verified'] and not s['recorded'] and p['floor']<=q['amount']<=p['past_due'] and today<=d<=deadline and business(d)
                            assert q['amount']==p['past_due'] or s['warned']=='true'
                            vars['promise_product_id']=p['product_id']; vars['promise_amount']=q['amount']; vars['promise_date']=q['date']; s['write_tries']=1; route='create_promise'
                        elif s['pending'].get('incomplete'): line=question(s)
                        elif phase=='readback' and s['pending'].get('amount') is not None and s['pending'].get('date'): line=readback(s)
                        elif phase=='offer' and s.get('offer'): s['pending']=dict(s['offer']); line=readback(s)
                        else: line=question(s)
                    elif k=='vague':
                        s['readback']=None; s['vague']+=1
                        if s['pending'].get('incomplete'): line=question(s)
                        elif s['vague']>=2: line=offer(s,s['pending'].get('amount',p['past_due']),deadline)
                        else: line='What exact day do you mean?'
                    if k=='too_much':
                        s['readback']=None; s['too_much']=True
                        if s['floor_offered']: k='refuse'
                        else: s['floor_offered']=True; s['pending']={}; line=offer(s,p['floor'],today if business(today) else advance(today,1),'The minimum amount is '+str(p['floor'])+'.')
                    if k in ('refuse','decline') and route=='talk':
                        s['readback']=None; s['pending']={}
                        if s['hardship']: route,line=finish(s,'no_promise','hardship','I cannot offer a discount.' if re.search(r'discount|waiver',raw.lower()) else '')
                        elif s['attempts']>=p['limit']: route,line=finish(s,'no_promise','refused')
                        else:
                            s['attempts']+=1
                            if s['attempts']==2: d=deadline; a=p['floor']
                            else:
                                d=today+datetime.timedelta(days=4-today.weekday())
                                while not business(d): d-=datetime.timedelta(days=1)
                                if d<=today:
                                    d=today-datetime.timedelta(days=today.weekday())+datetime.timedelta(days=11)
                                    while not business(d): d-=datetime.timedelta(days=1)
                                d=min(d,deadline); a=p['floor'] if s['too_much'] else p['past_due']
                            line=offer(s,a,d)
                    elif k=='unknown':
                        s['formats']+=1; line=recover(s,raw)
                        if s['formats']>=3: route,line=finish(s,'no_promise','service_error','I could not understand the answer clearly.')
                    elif k in ('question','purpose'): line='I do not have that information. '+question(s)
    progress={key:s.get(key) for key in ('phase','verified','wrong','declines','stops','attempts','callback_tries','recorded','pending','offer','vague','floor_offered')}
    signature=json.dumps(progress,sort_keys=True)
    if signature==s.get('progress_signature') and route=='talk': s['no_progress']=s.get('no_progress',0)+1
    else: s['no_progress']=0
    s['progress_signature']=signature
    if s['no_progress']>=4:
        route,line=finish(s,'no_promise' if s['verified'] else 'not_reached' if s['phase'] in ('recipient','callback') else 'not_verified','service_error' if s['verified'] else 'unclear' if s['phase']=='recipient' else 'no_callback' if s['phase']=='callback' else 'failed','I could not complete the information. Please use the mobile app or a branch.')
    # Administrative answers survive API hops and precede next permitted speech.
    if route=='verify_identity' and s.get('admin'):
        route='security_admin'
        line='Thank you.'
    if line and s.get('admin'):
        prefixes=[]
        if 'other' in s['admin'].split(): prefixes.append('I do not have that information.'+(' I can discuss account details after the security check.' if not s['verified'] else ''))
        if 'security_purpose' in s['admin'].split(): prefixes.append('These questions protect your account.')
        if 'relative_policy' in s['admin'].split(): prefixes.append('A relative cannot answer your security questions or receive account information.')
        if 'balance' in s['admin'].split(): prefixes.append('For your privacy, I cannot discuss account balances until the security check is complete.' if not s['verified'] else 'Your past-due amount is '+str(s.get('product',{}).get('past_due','unavailable'))+'.')
        if 'ai' in s['admin'].split(): prefixes.append("I am Freya Bank's digital assistant.")
        if 'scam' in s['admin'].split(): prefixes.append("You can verify this call by phoning Freya Bank's customer service number.")
        if 'purpose' in s['admin'].split() and not s.get('third_party') and s['phase'] not in ('callback',) and s.get('reason') not in ('callback','no_callback','wrong_number','deceased'): prefixes.append('I can explain after the security check.' if not s['verified'] else 'This call is about your late payment.')
        line=' '.join(prefixes)+' '+line; s['admin']=''
    if route=='talk' and not line: line=question(s)
    vars['bank_status']=''; vars['recipient_act']=''; vars['security_value']=''; vars['event']=''; vars['raw']=''; vars['admin']='none'; vars['bank_result']={}; vars['mode']='event'
    if route=='create_promise':
        request={'customer_id':str(vars.get('customer_id','')),
            'product_id':vars['promise_product_id'],'amount':vars['promise_amount'],
            'date':vars['promise_date']}
        if s['write_tries']==1: s['authorized_promise']=dict(request)
        assert s.get('verified') and not s.get('recorded') and s['write_tries'] in (1,2)
        assert request==s.get('authorized_promise')
        assert request['product_id']==s['product']['product_id']
        assert s.get('readback')==s.get('pending') and not s['pending'].get('incomplete')
        assert request['amount']==s['pending']['amount'] and request['date']==s['pending']['date']
        s['promise_sequence']=s.get('promise_sequence',0)+1
        s['promise_dispatch']={'node':'create_promise','attempt':s['write_tries'],
            'token':str(s['promise_sequence']),'request':dict(request),
            'failure_base':int(vars.get('create_promise_failure_count',0) or 0),
            'success_base':int(vars.get('create_promise_success_count',0) or 0)}
        vars['promise_started']=''
        for key in ('create_promise_response.status','create_promise_response.error',
            'create_promise_response.status_code','create_promise_status_code',
            'create_promise_response.data.ok','create_promise_ok'):
            vars[key]=''
    if route in ('verify_identity','security_admin','get_account'):
        node='get_account' if route=='get_account' else 'verify_identity'
        request={'customer_id':str(vars.get('customer_id',''))}
        if node=='verify_identity': request.update(field=vars['security_field'],answer=vars['security_answer'])
        else: assert s.get('verified') and s.get('dob_passed')
        s['read_sequence']=s.get('read_sequence',0)+1
        s['read_dispatch']={'node':node,'phase':s['phase'],'token':str(s['read_sequence']),
            'request':dict(request),'success_base':int(vars.get(node+'_success_count',0) or 0),
            'failure_base':int(vars.get(node+'_failure_count',0) or 0)}
        vars['read_started']=''; vars['read_completed']=''
        vars['bank_result']={}; vars['bank_status']=''; vars['products']=[]
        for suffix in ('_ok','_response.data.ok','_response.data.verified','_response.data.all_verified','_response.data.products','_response.status_code','_status_code'):
            vars[node+suffix]=''
    s['awaiting']={'verify_identity':'verify','security_admin':'verify','get_account':'account','create_promise':'promise','transfer_to_agent':'transfer','schedule_callback':'callback_result'}.get(route,'')
    vars['state']=s; vars['phase']=s['phase']; vars['route']=route; vars['dialogue_line']=line; vars['outcome']=s['outcome']; vars['reason']=s['reason']; vars['queue']=s.get('queue','general')
try:
    run(vars)
except Exception:
    s=vars.get('state',{})
    vars['route']='safe_failure'; vars['dialogue_line']='I cannot continue safely. Please contact Freya Bank directly. Thank you. Goodbye.'
    vars['outcome']='promise' if s.get('recorded') else 'no_promise' if s.get('verified') else 'not_verified'
    vars['reason']='' if s.get('recorded') else 'service_error' if s.get('verified') else 'failed'

