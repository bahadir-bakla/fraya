#!/usr/bin/env python3
"""Independent, offline security controller witnesses. No files are modified.

Supports the tagged-event/run(vars) workflow family. An incompatible regenerated
workflow is an explicit adapter failure, never a passing/skipped security check.
Inputs are synthetic and separate from the observed customer identities/dates.
This exercises literal extractor-shaped inputs and synthetic documented receipts;
it does NOT qualify live extraction, the hosted sandbox, or conversation judging.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workflow', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    payload = args.workflow.read_bytes()
    workflow = json.loads(payload.decode('utf-8-sig'))
    workflow = workflow.get('workflow', workflow)
    nodes = workflow['nodes']
    source = nodes['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
    tree = ast.parse(source)
    imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert set(imports) <= {'json', 're', 'datetime', 'decimal', 'math'}, 'Offline harness refuses unreviewed imports'
    assert not any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree)), 'Review imported dependency before adapting'
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'open', 'exec', 'eval', '__import__'} for node in ast.walk(tree))
    # Keep actual declarations and remove only the workflow's bottom-level call.
    declarations = ast.Module(body=[node for node in tree.body if isinstance(node, (ast.Import, ast.Assign, ast.FunctionDef))], type_ignores=[])
    env = {}
    exec(compile(declarations, str(args.workflow), 'exec'), env)
    assert callable(env.get('run')), 'Unsupported controller: adapt to its real producer/decoder contract'
    observations = []

    def step(v):
        env['run'](v)
        # Exercise persistent store serialization between every event.
        v.update(json.loads(json.dumps(v)))

    def fresh():
        v = dict(customer_id='OFFLINE-SECURITY', first_name='Jordan', last_name='Vale', title='Mx', now='2026-10-11T10:00:00', state=None, mode='event', raw='', admin='none', event='')
        step(v)
        v.update(mode='event', event='k=recipient;c=1;END', recipient_act='recipient', raw='Yes, this is Jordan Vale.', admin='none')
        step(v)
        assert v['state']['phase'] == 'dob', 'Workflow producer contract incompatible with fixture'
        return v

    def answer(v, raw, canonical):
        v.update(mode='event', security_value=canonical, event='k=security;c=1;v='+canonical+';END', raw=raw, admin='none')
        step(v)

    def observe(name, v, passed, expected):
        s = v['state']
        observations.append(dict(id=name, passed=bool(passed), expected=expected, actual={key:v.get(key) for key in ('route','security_field','security_answer','dialogue_line')}, state={key:s.get(key) for key in ('phase','verified','dob_passed','wrong','security_clarifications')}))

    positive = [
        ('digit_year', 'the fourth of September one nine nine two.', '1992-09-04'),
        ('digit_year_comma', 'My date of birth is the fourth of September, one nine nine two.', '1992-09-04'),
        ('cardinal_year', 'The fourth of September nineteen ninety-two.', '1992-09-04'),
        ('canonical', '1992-09-04', '1992-09-04'),
        ('digit_year_purpose', 'Fourth of September one nine nine two. Why do you need my birth date?', '1992-09-04'),
        ('digit_year_balance', 'Fourth of September one nine nine two; what is my balance?', '1992-09-04'),
        ('digit_year_other', 'Fourth of September one nine nine two; what are your opening hours?', '1992-09-04'),
        ('two_thousand', 'Fourth of September two thousand and two.', '2002-09-04'),
    ]
    for name, raw, value in positive:
        v = fresh(); answer(v,raw,value)
        dispatched = v['route'] in ('verify_identity','security_admin')
        observe(name,v,dispatched and v.get('security_answer')==value and not v['state']['verified'] and v['state']['wrong']==0,'Submit exact canonical candidate for bank comparison; do not locally verify')

    negative = [
        ('missing_year','Fourth of September.'),
        ('incomplete_year','Fourth of September one nine...'),
        ('negated','My date of birth is not fourth of September nineteen ninety-two.'),
        ('quoted','She said "fourth of September nineteen ninety-two".'),
        ('third_party','His date of birth is fourth of September nineteen ninety-two.'),
        ('hypothetical','If I was born fourth of September nineteen ninety-two.'),
        ('alternative','Fourth of September nineteen ninety-two or nineteen ninety-three.'),
        ('question_operand','Fourth of September. Is nineteen ninety-two the year you need?'),
        ('explicit_conflict','Fourth of September nineteen ninety-three.'),
        ('unfinished_correction','Fourth of September nineteen ninety-two, actually...'),
        ('missing_source',''),
    ]
    for name, raw in negative:
        v=fresh(); answer(v,raw,'1992-09-04')
        observe(name,v,v['route'] not in ('verify_identity','security_admin','get_account') and not v['state']['verified'] and v['state']['wrong']==0,'Reject unsafe/partial/conflicting canonical evidence without spending a bank wrong-answer attempt')

    # Run current node pre/post hooks, current counters and documented response
    # shape. No fabricated identity authority or prefilled verification flags.
    def bank_receipt(v, data):
        node=nodes['verify_identity']; action=node['pre_actions'][0]
        props=action['function']['parameters']['properties']
        body={}
        for key, schema in props['body']['properties'].items():
            default=schema['default']; match=re.fullmatch(r'\{\{([a-z_]+)\}\}',str(default))
            body[key]=v.get(match[1],'') if match else default
        config=dict(url=props['url']['default'],method=props['method']['default'],body=body)
        exec(action['pre_process_code'], {'vars':v,'config':copy.deepcopy(config)})
        v['verify_identity_success_count']=int(v.get('verify_identity_success_count',0))+1
        exec(action['post_process_code'], {'vars':v,'result':dict(status='success',status_code=200,data=data,message='offline fixture')})
        step(v)

    v=fresh(); answer(v,'Fourth of September nineteen ninety-two.','1992-09-04')
    assert v['route']=='verify_identity'
    bank_receipt(v,dict(ok=True,verified=False,wrong_answers_left=2,all_verified=False))
    observe('bank_wrong_answer',v,v['state']['wrong']==1 and not v['state']['verified'] and v['state']['phase']=='dob','Only current bank mismatch increments wrong-answer count')
    v=fresh(); answer(v,'Fourth of September nineteen ninety-two.','1992-09-04')
    bank_receipt(v,dict(ok=True,verified=True,wrong_answers_left=3,all_verified=False))
    observe('bank_dob_only',v,v['state']['dob_passed'] and not v['state']['verified'] and v['state']['phase']=='phone','Bank DOB pass alone still requires phone verification')
    answer(v,'Zero two seven four.','0274')
    observe('phone_leading_zero',v,v['route']=='verify_identity' and v.get('security_answer')=='0274' and not v['state']['verified'],'Preserve four explicit phone digits and bank gate')
    bank_receipt(v,dict(ok=True,verified=True,wrong_answers_left=3,all_verified=True))
    observe('bank_complete_identity',v,v['state']['verified'] and v['route']=='get_account','Account lookup only after both successful bank checks')

    v=fresh(); answer(v,'Fourth of September one nine nine two.','1992-09-04')
    digit_dispatched = v['route']=='verify_identity'
    if digit_dispatched:
        bank_receipt(v,dict(ok=True,verified=True,wrong_answers_left=3,all_verified=False))
    observe('digit_year_bank_dob',v,digit_dispatched and v['state']['dob_passed'] and not v['state']['verified'] and v['state']['phase']=='phone','Complete spoken-digit year advances only after current successful bank DOB comparison')
    digit_phone_dispatched=False
    if digit_dispatched and v['state']['phase']=='phone':
        answer(v,'Zero two seven four.','0274')
        digit_phone_dispatched=v['route']=='verify_identity'
        if digit_phone_dispatched:
            bank_receipt(v,dict(ok=True,verified=True,wrong_answers_left=3,all_verified=True))
    observe('digit_year_complete_identity',v,digit_phone_dispatched and v['state']['verified'] and v['route']=='get_account','Spoken-digit DOB plus phone requires both real hook receipt paths before account lookup')
    v=fresh(); answer(v,'Fourth of September one nine nine two.','1992-09-04')
    digit_dispatched = v['route']=='verify_identity'
    if digit_dispatched:
        bank_receipt(v,dict(ok=True,verified=False,wrong_answers_left=2,all_verified=False))
    observe('digit_year_bank_mismatch',v,digit_dispatched and v['state']['wrong']==1 and not v['state']['verified'] and v['state']['phase']=='dob','Wrong complete spoken-digit DOB remains a failed bank comparison, not local verification')
    v=fresh(); answer(v,'Fourth of September one nine nine two.','1992-09-04')
    digit_dispatched = v['route']=='verify_identity'
    if digit_dispatched:
        bank_receipt(v,dict(ok=False,verified=False,wrong_answers_left=3,all_verified=False))
    observe('digit_year_bank_unreadable',v,digit_dispatched and v['state']['wrong']==0 and not v['state']['verified'] and v['state']['phase']=='dob','Bank unreadable response is not a wrong-answer attempt or successful verification')

    result=dict(workflow=str(args.workflow),sha256=hashlib.sha256(payload).hexdigest(),evidence='offline literal producer inputs plus synthetic current API receipts; not hosted evaluation',passed=sum(row['passed'] for row in observations),total=len(observations),observations=observations)
    if args.output: args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:value for key,value in result.items() if key!='observations'},indent=2))
    return 0 if result['passed']==result['total'] else 1

if __name__=='__main__':
    raise SystemExit(main())
