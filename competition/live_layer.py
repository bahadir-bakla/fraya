"""Compile portable per-turn helpers as generation inputs, never patch a workflow.

The encoder stays outside the phone agent. A separately trained V2 student can
be embedded in a documented code node. Its outputs have no bank authority.
"""
import ast
import hashlib
import json
from pathlib import Path

BROKER = '''
def live_layer_apply(v):
    v['live_layer_status']='NO_CURRENT_RAW'
    v['live_semantic_hint']=''
    v['live_semantic_diagnostic']=''
    v['live_recipient_decision']='UNKNOWN'
    v['live_recipient_span']='[]'
    v['live_bank_authority']='false'
    v['live_financial_authorization']='UNKNOWN'
    v['live_input_kind']='extractor_copy'
    raw=v.get('raw')
    if v.get('mode','event')!='event' or not isinstance(raw,str) or not raw.strip():
        return
    v['live_layer_status']='SOURCE_ONLY'
    try:
        assertion=recipient_assertion(raw,str(v.get('first_name') or ''),str(v.get('last_name') or ''),str(v.get('title') or ''))
        if assertion.get('bank_authority') is False and assertion.get('decision') in ('SELF','OTHER','UNKNOWN'):
            v['live_recipient_decision']=assertion['decision']
            v['live_recipient_span']=json.dumps(assertion.get('source_span',[]))
    except Exception:
        v['live_recipient_decision']='UNKNOWN'
    prior=v.get('live_observed_prior',[])
    if not isinstance(prior,list): prior=[]
    prior=[p for p in prior if isinstance(p,dict) and p.get('speaker')=='USER' and isinstance(p.get('text'),str)][-2:]
    state=v.get('state',{})
    phase=state.get('phase','recipient') if isinstance(state,dict) else 'recipient'
    if phase not in ('decision','readback','proposal','offer','multi','after_partial','payment','confirmation','payment_terms','product'):
        v['live_layer_status']='SOURCE_ONLY_SECURITY_BYPASS'
        return
    if state.get('verified') is not True or state.get('dob_passed') is not True:
        v['live_layer_status']='SOURCE_ONLY_UNVERIFIED_BYPASS'
        return
    if LIVE_STUDENT_MODEL:
        try:
            result=student_predict(raw,prior,LIVE_STUDENT_MODEL)
            allowed=('proposal','dispute','correction','uncertain','reported_third_party')
            labels=result.get('labels',[])
            if result.get('bank_authority') is not False or not isinstance(labels,list): raise ValueError('authority')
            v['live_layer_status']='STUDENT_'+str(result.get('status','INVALID'))
            diagnostic=','.join(label for label in allowed if label in labels)
            v['live_semantic_diagnostic']=diagnostic
            if LIVE_STUDENT_ENABLED:
                v['live_semantic_hint']=diagnostic
        except Exception:
            v['live_layer_status']='STUDENT_UNAVAILABLE'
            v['live_semantic_hint']=''
    v['live_observed_prior']=(prior+[dict(speaker='USER',text=raw)])[-2:]
    count=v.get('live_layer_turns',0)
    v['live_layer_turns']=(count if isinstance(count,int) and not isinstance(count,bool) and count>=0 else 0)+1

def live_recipient_reply(raw,v):
    try:
        result=recipient_assertion(raw,str(v.get('first_name') or ''),str(v.get('last_name') or ''),str(v.get('title') or ''))
        return result.get('bank_authority') is False and result.get('decision')=='SELF'
    except Exception:
        return False
'''

NOTICE = """Read live-layer-contract.json and live-layer-code.py. The latter is a
frozen portable component, not a phone workflow: include its EXACT complete
text in the controller code_exec and call live_layer_apply(vars) BEFORE the
controller consumes/clears the CURRENT raw utterance on each dispatch. Do not
The invocation MUST be the standalone unconditional module statement
live_layer_apply(vars), outside every function, try, if or loop. Definitions may
precede it, followed by this call and then the controller entry call. Preserve
the exact component's line endings and complete text, not an adapted copy.
run any controller statements before this call except definitions, imports and
literal constants. The component belongs in a CODE node, never conversation
pre_actions. Do not redefine or rebind its helpers or model constants.
For the currently supplied shadow-only bundles LIVE_STUDENT_ENABLED is False:
record live_semantic_diagnostic internally, leave live_semantic_hint empty, and
do not let diagnostic labels change routing, dialogue or tools. This is a
per-turn runtime integration experiment, not an enabled learned decision layer.
Do not
call it on bank response mode or replace observed current text with model text.
Use live_recipient_reply(raw, vars) as the source-backed recipient assertion
check instead of substring matching: SELF only opens the existing DOB prompt,
never establishes verified identity. OTHER/UNKNOWN retain classic safe routing.
The optional V2 student is a DISTINCT compact distilled model, not the full
MiniLM encoder. It executes locally inside code_exec, never via a tool/server.
live_semantic_hint is a proposal for conversational agenda only. For a verified
customer with an UNKNOWN/unresolved language extraction, consult that hint to
ask ONE source-grounded clarification of the currently supplied proposal,
dispute or correction; preserve the current target and already stored slots.
Do not treat uncertainty or an absent/negative label as a refusal. Current raw
speech, source scope, classical policy guards, explicit readback confirmation
and bank receipts remain authoritative. A model hint must NEVER set identity,
consent, amounts, dates, product targets, backend receipts or close outcomes.
Extraction happened BEFORE this code: do not pretend the hint repaired that
already-run extraction. Keep AGENT_LLM and all bank-only tools unchanged.
The supplied raw field is an extractor copy, not an attested engine transcript;
declare this provenance and validate literal source patterns conservatively.
Do not apply the student to recipient or security-answer phases. The runtime
skips those phases and does not store their copied text in learned history.
Fail closed to classic behavior on malformed/unavailable student input. Declare
all live_* vars you use; counters/labels are internal and never read verbatim.
No post-generation/manual phone JSON edits are permitted.
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def portable(source):
    if '{{' in source or '}}' in source:
        raise ValueError('Portable source contains template markers')
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(m not in ('json', 're', 'datetime') for m in modules):
                raise ValueError('Unverified sandbox dependency')
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise ValueError('State must use vars/returns')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('open', 'exec', 'eval', 'compile', '__import__'):
            raise ValueError('Nonportable runtime call')
    return tree


def prepare(work, recipient_path, student_directory=None, student_manifest_sha256=None, student_use='shadow'):
    """Freeze sources and produce explicit reviewed generator inputs."""
    work = Path(work)
    recipient = Path(recipient_path).read_bytes()
    source = 'import json\n' + recipient.decode('utf-8') + '\n'
    files = {'recipient_assertion.py': recipient}
    model = {}
    if student_use not in ('shadow','clarify') or (student_use=='clarify' and student_directory is None):
        raise ValueError('Clarification mode requires an explicitly pinned student')
    enabled = student_use=='clarify'
    student_kind = None
    mode = 'recipient'
    if student_directory is not None:
        directory = Path(student_directory).resolve(strict=True)
        manifest_raw = (directory / 'manifest.json').read_bytes()
        if not student_manifest_sha256 or sha(manifest_raw) != student_manifest_sha256:
            raise ValueError('An explicit frozen student manifest pin is required')
        manifest = json.loads(manifest_raw)
        if manifest.get('bank_authority') is not False:
            raise ValueError('Student must not have bank authority')
        # No current bundle has qualified for consumer activation. Preserve its
        # training and runtime for shadow diagnostics without influencing speech.
        if manifest.get('default_enabled') is not False:
            raise ValueError('This integration accepts diagnostic shadow bundles only')
        student_kind = manifest.get('model_kind', 'PORTABLE_STUDENT_NOT_MINILM')
        for name, digest in manifest['files'].items():
            path = (directory / name).resolve(strict=True)
            if not path.is_relative_to(directory) or path.name != name:
                raise ValueError('Student payload path must be a flat confined name')
            raw = path.read_bytes()
            if sha(raw) != digest:
                raise ValueError('Student payload digest mismatch')
            if name in ('model.json','runtime.py'):
                files['student-' + name] = raw
        if 'student-model.json' not in files or 'student-runtime.py' not in files:
            raise ValueError('Student requires model.json and runtime.py')
        model = json.loads(files['student-model.json'])
        source += files['student-runtime.py'].decode('utf-8') + '\n'
        files['student-manifest.json'] = manifest_raw
        mode = 'v2-student'
    # Whitespace is legal JSON; avoid even accidental double-curly templates.
    payload = json.dumps(model, ensure_ascii=False, separators=(',', ':')).replace('{{', '{ {').replace('}}', '} }')
    source += 'LIVE_STUDENT_MODEL=json.loads(' + repr(payload) + ')\nLIVE_STUDENT_ENABLED='+repr(enabled)+'\n' + BROKER
    portable(source)
    if len(source.encode('utf-8')) > 85000:
        raise ValueError('Inline runtime exceeds the explicit component budget')
    files['live-layer-code.py'] = source.encode('utf-8')
    for name, raw in files.items():
        (work / name).write_bytes(raw)
    contract = {'schema': 'portable-live-layer-v1', 'mode': mode,
                'bank_authority': False, 'financial_authorization': 'UNKNOWN',
                'full_MiniLM_encoder_in_phone_agent': False,
                'hosted_runtime_verified': False,
                'student_kind': student_kind, 'student_consumer_enabled': enabled,
                'student_use': student_use,
                'risk_qualified': False,
                'activation_scope': 'Explicit experimental clarification only; below the CAL target' if enabled else 'Shadow diagnostics only',
                'files': {name: sha(raw) for name, raw in files.items()},
                'component_bytes': len(source.encode('utf-8')),
                'call': 'live_layer_apply(vars)', 'recipient_check': 'live_recipient_reply(raw, vars)',
                'notice': NOTICE + ('\nThis run explicitly uses student_use=clarify: LIVE_STUDENT_ENABLED=True. Below-target CAL is disclosed. A hint may only request ONE source-grounded clarification when verified and canonical extraction is UNKNOWN/unresolved. Never invent slots, targets or consent; no complete valid canonical event may be changed.\n' if enabled else '')}
    raw = (json.dumps(contract, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    (work / 'live-layer-contract.json').write_bytes(raw)
    contract['contract_sha256'] = sha(raw)
    return contract


def verify_inputs(work, contract):
    work = Path(work)
    for name, digest in {**contract['files'], 'live-layer-contract.json': contract['contract_sha256']}.items():
        if sha((work / name).read_bytes()) != digest:
            raise ValueError('Live component changed during generation: ' + name)


def validate_embedding(workflow, work, contract):
    """Reject unused/mutated helpers, leaving policy tests to actual replay."""
    verify_inputs(work, contract)
    exact = (Path(work) / 'live-layer-code.py').read_text(encoding='utf-8')
    matches = []
    for name, node in {**workflow.get('nodes', {}), **workflow.get('global_nodes', {})}.items():
        for action in node.get('pre_actions', []):
            fn = action.get('function', {})
            code = fn.get('parameters', {}).get('properties', {}).get('code', {}).get('default', '')
            if exact in code:
                tree = portable(code)
                if node.get('node_type') != 'code':
                    continue
                # Frozen helper names cannot be rebound by the controller. Only
                # the exact source owns their definitions and model constants.
                begin = code.index(exact)
                first = code[:begin].count('\n') + 1
                last = first + len(exact.splitlines()) - 1
                helper_names = {n.name for n in ast.parse(exact).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
                for statement in ast.parse(exact).body:
                    if isinstance(statement,ast.Assign):
                        helper_names.update(n.id for target in statement.targets for n in ast.walk(target) if isinstance(n,ast.Name))
                helper_names.update(('LIVE_STUDENT_MODEL','LIVE_STUDENT_ENABLED','vars'))
                external = [n for n in ast.walk(tree) if not first <= getattr(n,'lineno',first) <= last]
                if any((isinstance(n,ast.Name) and isinstance(n.ctx,(ast.Store,ast.Del)) and n.id in helper_names)
                       or (isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in helper_names)
                       or (isinstance(n,ast.alias) and (n.asname or n.name.split('.')[0]) in helper_names)
                       for n in external):
                    continue
                calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
                # Require an unconditional module-level call, outside dormant
                # functions/if False. Functional replay proves actual effects.
                direct = [n.value for n in tree.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)]
                applied = [n for n in direct if isinstance(n.func,ast.Name) and n.func.id == 'live_layer_apply' and len(n.args) == 1 and isinstance(n.args[0], ast.Name) and n.args[0].id == 'vars']
                if len(applied) != 1:
                    continue
                call_line = applied[0].lineno
                if call_line <= last:
                    continue
                # Before invocation, allow definitions/imports and literal
                # constants only. Reject raw clearing, controller execution,
                # hidden helper rebinding and other runtime preparation.
                safe = True
                for statement in tree.body:
                    if statement.lineno >= call_line or first <= statement.lineno <= last:
                        continue
                    if isinstance(statement,(ast.Import,ast.ImportFrom,ast.FunctionDef)):
                        continue
                    if isinstance(statement,ast.Assign) and all(isinstance(t,ast.Name) for t in statement.targets):
                        try: ast.literal_eval(statement.value); continue
                        except (ValueError,TypeError): pass
                    if isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Constant):
                        continue
                    safe=False; break
                if not safe:
                    continue
                checked = sum(n.func.id == 'live_recipient_reply' for n in calls) > 0
                if applied and checked and fn.get('handler') == '__function__:code_exec':
                    matches.append(name)
    if not matches:
        raise ValueError('Generated workflow has no exact invoked portable live component')
    return {'nodes': matches, 'mode': contract['mode'], 'bank_authority': False,
            'scope': 'Exact embedding and call sites; runtime/guard behavior requires separate replay and Freya validation'}
