"""Self-practice: the builder writes and audits its own practice customers from the run's evidence.

Unseen final briefs come without test customers, so the test-and-repair loop that lifts practice scores has nothing
to run. Here a separate model reads only the evidence, the API and the hosted mock's registered customer facts, and
writes cases in the kit's public-test-set format; an independent model re-derives every expected ledger; only cases
both agree on, and that pass structural checks, are used. Nothing from a brief is written into builder code: the
cases live in the run directory. Train cases drive repairs; holdout cases only measure the chosen candidate.
"""
import datetime,json,os,pathlib,shutil

GROUP='S'
CASE_KEYS=('id','brief','family','level','title','variables','identity','products','script','expected','checks')

def public_facts(kit):
    """Facts the hosted mock fixes per registered customer; a case may change only the script and the expectations."""
    keep=('variables','identity','products','faults','third_party')
    return [{'id':c['id'],**{k:c[k] for k in keep if k in c}} for c in json.load(open(kit/'public-test-set.json'))]

def enums(api):
    """Allowed values for scored ledger fields, read from this run's OpenAPI."""
    found={}
    for path,item in api.get('paths',{}).items():
        props=(((item.get('post') or {}).get('requestBody') or {}).get('content',{}).get('application/json',{}).get('schema',{}) or {}).get('properties',{})
        for field,spec in props.items():
            if 'enum' in spec:found[(path.strip('/'),field)]=set(spec['enum'])
    return found

def ledger_key(expected):
    """The fields the official scorer compares."""
    e=expected or {}
    return (e.get('outcome'),e.get('reason'),
            sorted((p.get('product_id'),round(float(p.get('amount',0)),2),p.get('date')) for p in e.get('promises',[])),
            sorted((n.get('product_id'),n.get('reason')) for n in e.get('notes',[])),
            sorted((c.get('date'),c.get('time')) for c in e.get('callbacks',[])),
            sorted(t.get('queue') for t in e.get('transfers',[])))

def validate_cases(cases,facts,api):
    """Structural checks; returns (kept, problems). A case that breaks one is dropped, never repaired by guessing."""
    by_id={f['id']:f for f in facts};allowed=enums(api);kept=[];problems=[];seen=set()
    def bad(case,why):problems.append({'case':case.get('case_label') or case.get('id'),'problem':why})
    for case in cases if isinstance(cases,list) else []:
        if not isinstance(case,dict) or any(k not in case for k in CASE_KEYS):bad(case if isinstance(case,dict) else {},'missing fields');continue
        fact=by_id.get(case['id'])
        if not fact:bad(case,'unknown registered customer');continue
        if case['id'] in seen:bad(case,'registered customer used twice in one file');continue
        if any(case.get(k)!=fact.get(k) for k in ('variables','identity','products')):bad(case,'facts differ from the registered customer');continue
        e=case['expected'];ids={f'p{i+1}' for i in range(len(fact['products']))}
        outcomes=allowed.get(('close_call','outcome'));notes=allowed.get(('add_note','reason'));queues=allowed.get(('transfer_to_agent','queue'))
        if outcomes and e.get('outcome') not in outcomes:bad(case,'outcome not in the API enum');continue
        if any(n.get('product_id') not in ids or (notes and n.get('reason') not in notes) for n in e.get('notes',[])):bad(case,'invalid note');continue
        if queues and any(t.get('queue') not in queues for t in e.get('transfers',[])):bad(case,'invalid queue');continue
        try:
            for p in e.get('promises',[]):
                if p.get('product_id') not in ids or float(p['amount'])<=0:raise ValueError
                datetime.date.fromisoformat(p['date'])
            for c in e.get('callbacks',[]):
                datetime.date.fromisoformat(c['date']);datetime.time.fromisoformat(c['time'])
        except (KeyError,TypeError,ValueError):bad(case,'invalid promise or callback');continue
        if not isinstance(case['checks'],list) or not 1<=len(case['checks'])<=5:bad(case,'checks must be a list of 1-5');continue
        if 'faults' in fact:case['faults']=fact['faults']
        case['brief']=GROUP;seen.add(case['id']);kept.append(case)
    return kept,problems

def agree(cases,audit):
    """Keep only cases whose expected ledger the independent auditor re-derived identically and judged unambiguous."""
    verdicts={(a.get('file'),a.get('case_label')):a for a in audit if isinstance(a,dict)}
    kept=[];dropped=[]
    for name,group in cases.items():
        for case in group:
            a=verdicts.get((name,case.get('case_label')))
            if a and a.get('verdict')=='ok' and ledger_key(a.get('expected'))==ledger_key(case['expected']):kept.append((name,case))
            else:dropped.append({'file':name,'case':case.get('case_label'),'verdict':(a or {}).get('verdict','missing'),'reason':(a or {}).get('reason','')})
    return kept,dropped

AUTHOR_PROMPT='''You write practice customers for a bank collections phone agent that another process is building from the same evidence.
Read every file in inputs/ completely: the bank evidence (precedence order: {briefs}; a later explicit amendment overrides earlier rules), the tool API (openapi.json), the hosted mock's registered customers (facts.json) and how a case becomes a simulated customer and a judge (persona.md).
Write two JSON files in this directory, each a JSON array in the format described in persona.md:
- train.json: up to {train} cases; holdout.json: up to {holdout} different cases.
- Each case uses one registered customer id and copies its variables, identity and products exactly. Within one file each id appears at most once. If the evidence covers only one product per customer, use only customers with exactly one product.
- Spread the cases over the situations the evidence defines: verified promise inside the rules, date outside the allowed window or on a non-business day, amount below the floor, refusal with the evidence's persuasion steps, hardship, dispute, already paid, failed identity, declined identity, third party or wrong number with callback, a transfer the evidence requires, a write tool failure (the customer whose facts list faults), and several products with mixed decisions when the evidence covers them.
- script: third person, only facts from the case, and every expected value must follow from the evidence plus these facts. Write the customer's behaviour so the persona rules in persona.md can follow it (the customer confirms a matching read-back unless the script says otherwise; give exact dates and amounts).
- expected: outcome, reason (the evidence's own code; null for a promise or paid outcome unless the evidence says otherwise), promises, notes, callbacks, transfers, exactly as the evidence requires.
- checks: 2 to 4 short statements a judge can verify from the transcript, each required by the evidence.
- Add case_label (T-01, T-02, H-01, ...) and rationale (rule references and the derivation).
If a rule could be read two ways, do not write a case that depends on it. Do not read or write anything outside this directory. Return the file names and a one-line summary.'''

AUDIT_PROMPT='''Audit practice cases for a bank collections phone agent. Read inputs/ (bank evidence in precedence order {briefs}, openapi.json, facts.json, persona.md), then train.json and holdout.json.
For every case, derive the expected ledger yourself from the evidence and the case facts and script, without trusting the case's own expected or rationale: outcome, reason, promises (product_id, amount, date), notes (product_id, reason), callbacks (date, time), transfers (queue).
Write audit.json: a JSON array with one object per case: {{"file": "train.json" or "holdout.json", "case_label": ..., "verdict": "ok" | "ambiguous" | "wrong", "expected": {{your derived ledger}}, "reason": "one line"}}.
verdict is ok only when the evidence determines one ledger and the script lets the simulated customer produce it; ambiguous when the evidence allows more than one; wrong when the case's expected ledger contradicts the evidence. Do not edit the case files. Return the file name and a one-line summary.'''

def prepare_workspace(run,kit,persona_text):
    root=run.path/'self-practice';inputs=root/'inputs';inputs.mkdir(parents=True,exist_ok=True)
    names=[]
    for entry in run.sources:
        source=run.work/entry['path'];shutil.copyfile(source,inputs/source.name);names.append('inputs/'+source.name)
    shutil.copyfile(run.work/'inputs/openapi.json',inputs/'openapi.json')
    (inputs/'facts.json').write_text(json.dumps(public_facts(kit),indent=1))
    (inputs/'persona.md').write_text(persona_text)
    return root,names

def persona_document(kit):
    """How a case turns into the simulated customer and the judge: the kit's own runner text, plus the case format."""
    runner=(kit/'tools/run_cases.py').read_text()
    start=runner.find('PERSONA = """');end=runner.find('"""',start+13)
    template=runner[start:end+3] if start>=0 and end>start else ''
    example=json.load(open(kit/'public-test-set.json'))[0]
    example={k:example[k] for k in example if k!='faults'}
    return ('# How a case is simulated\n\nThe runner fills this persona template with the case (who + script) and gives the '
            'case checks to a judge model as success criteria. The bank ledger is scored against expected.\n\n```python\n'
            +template+'\n```\n\n# Case format (one public example; your cases use the same keys)\n\n```json\n'
            +json.dumps(example,indent=1)+'\n```\n')

def run_model(run,root,prompt,schema_name,schema,log_name,seconds,purpose):
    (root/schema_name).write_text(json.dumps(schema))
    from builder import model_permissions
    command=['codex','exec','--ignore-user-config','--skip-git-repo-check','--ephemeral','--config','default_permissions='+model_permissions(os.environ),
             '--config','approval_policy=never','--json','--color','never','--output-schema',str(root/schema_name),'--output-last-message',str(root/(log_name+'.answer.json'))]
    if run.args.model:command+=['--model',run.args.model]
    command+=['-']
    env={key:value for key,value in os.environ.items() if not any(word in key.upper() for word in ('API_KEY','TEAM_KEY','TOKEN','SECRET','PASSWORD'))}
    run.child(command,timeout=seconds,env=env,stdin=prompt,log_name=f'self-practice-{log_name}.jsonl',purpose=purpose,cwd=root)

def build_cases(run,kit,train=8,holdout=5):
    """Author, audit and validate. Returns {'train': path or None, 'holdout': path or None, 'report': {...}}."""
    root,names=prepare_workspace(run,kit,persona_document(kit));briefs=json.dumps(names)
    schema={'type':'object','properties':{'files':{'type':'string'},'summary':{'type':'string'}},'required':['files','summary'],'additionalProperties':False}
    run_model(run,root,AUTHOR_PROMPT.format(briefs=briefs,train=train,holdout=holdout),'author.schema.json',schema,'author',min(420,max(60,run.remaining()-600)),'Self-practice: write practice customers from the evidence')
    run_model(run,root,AUDIT_PROMPT.format(briefs=briefs),'audit.schema.json',schema,'audit',min(300,max(60,run.remaining()-480)),'Self-practice: independently re-derive expected ledgers')
    facts=public_facts(kit);report={'problems':[],'dropped':[]};cases={}
    for name in ('train.json','holdout.json'):
        try:raw=json.loads((root/name).read_text())
        except (OSError,ValueError):raw=[];report['problems'].append({'file':name,'problem':'missing or invalid JSON'})
        kept,problems=validate_cases(raw,facts,run.api);cases[name]=kept;report['problems']+=[{**p,'file':name} for p in problems]
    try:audit=json.loads((root/'audit.json').read_text())
    except (OSError,ValueError):audit=[];report['problems'].append({'file':'audit.json','problem':'missing or invalid JSON'})
    agreed,dropped=agree(cases,audit);report['dropped']=dropped
    paths={}
    for name in ('train.json','holdout.json'):
        final=[case for file,case in agreed if file==name]
        report[name]=len(final)
        if final:
            path=root/name.replace('.json','-final.json');path.write_text(json.dumps(final,indent=1,ensure_ascii=False));paths[name.split('.')[0]]=path
    return {'train':paths.get('train'),'holdout':paths.get('holdout'),'report':report}
