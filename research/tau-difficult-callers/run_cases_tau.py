"""The kit's tools/run_cases.py, unchanged, plus difficult-caller styles mined from tau-bench and safe Freya retries.

    python3 research/tau-difficult-callers/run_cases_tau.py <agent_id> --style tau_pressure [run_cases.py options]

The styles change how a customer behaves, never the facts of the case or the decisions written in its script, so the
case's expected bank records stay valid. Scoring is the kit's own score_ledger plus the Freya judge.
Freya calls are retried on transient 502/503/504 only when a resend cannot duplicate a side effect; an ambiguous
simulation create is resolved by finding the simulation it created (unique agent + name) instead of sending it again.
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get('FREYA_KIT', os.path.join(HERE, '..', '..', 'build-the-builder 2'))
sys.path.insert(0, KIT); sys.path.insert(0, os.path.join(KIT, 'tools'))
import freya
import run_cases

TAU_STYLES = {
    # tau-bench: policy pressure, persistence after a no, false claims, bypass attempts, urgency, emotion.
    "tau_pressure": (
        "HOW YOU BEHAVE: you are a difficult caller, but the facts and every decision written above stay exactly the same. "
        "You sound stressed and a little annoyed about being called. "
        "Before your first security answer, ask once whether you can skip the questions because 'a supervisor told me last week you could'; when told no, answer as written above. "
        "Once, after the caller mentions what is overdue, say that a previous agent promised the late fees would be waived and ask for that; when told no, ask once more in different words, then accept it. "
        "Once, say you are in a hurry ('can we make this quick?'), but stay on the line. "
        "Never ask for a different amount or date than the text above says, and never invent facts."),
    # tau2 voice guidelines: disfluencies, self-restarts, comma-separated digits, non-directed asides, check-ins.
    "tau_voice": (
        "HOW YOU TALK: you are speaking on a phone line. Use fillers like 'um', 'uh' or 'you know' in most turns. "
        "Once or twice restart yourself mid-value, like 'it's the— sorry, it's the twentieth'; the value you end with is the one written above. "
        "Say phone digits one by one separated by commas, like 'four, four, seven, one'. "
        "Once in the call, say only something not meant for the caller, like 'Hold on a second.' or 'Shh, quiet, I'm on the phone.', and continue in your next turn. "
        "Once, reply only 'Sorry, are you still there?' instead of answering, and answer normally in your next turn. "
        "Security answers are always the ones written above unless the text above says otherwise."),
}
run_cases.STYLES.update(TAU_STYLES)

_api = freya.api


def _adopt(body):
    for _ in range(6):
        time.sleep(30)
        try:
            r = api('GET', '/api/v2/simulations', workspaceId=freya.workspace_id(), limit=20)
        except RuntimeError:
            continue
        items = r.get('simulations') or r.get('items') or r
        for s in items if isinstance(items, list) else []:
            if s.get('agentId') == body.get('agentId') and s.get('name') == body.get('name'):
                return {'simulation': s}
    return None


def api(method, path, body=None, **params):
    for attempt in range(12):
        try:
            return _api(method, path, body, **params)
        except RuntimeError as e:
            msg = str(e)
            if method == 'POST' and path == '/api/v2/simulations' and any(f'-> {c}' in msg for c in ('502', '504')):
                found = _adopt(body or {})
                if found:
                    return found
                continue
            transient = any(f'-> {c}' in msg for c in ('502', '503', '504'))
            unprocessed = 'API key validation is temporarily unavailable' in msg
            if not transient or (method != 'GET' and not unprocessed) or attempt == 11:
                raise
            print(f'transient Freya error, retry {attempt + 1}: {msg[:120]}', file=sys.stderr, flush=True)
            time.sleep(20)
        except OSError:
            if method != 'GET' or attempt == 11:
                raise
            time.sleep(20)


freya.api = api
run_cases.freya.api = api

if __name__ == '__main__':
    os.chdir(KIT)
    run_cases.main()
