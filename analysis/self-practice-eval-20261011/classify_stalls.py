"""Classify each scored call in result files as a platform stall or an agent outcome.

A platform stall: the engine produced no event (no extraction, code, route or speech) after the caller's first reply,
and the call ended by the simulated customer. Such calls say nothing about the agent and are rerun.
    python3 classify_stalls.py results-cmp/*.json
"""
import json,sys,os,pathlib
sys.path[:0]=[str(pathlib.Path(__file__).parent/'builder-wt'/'build-the-builder 2'),str(pathlib.Path(__file__).parent/'builder-wt'/'build-the-builder 2'/'tools')]
import freya

def stalled(call):
    messages=call.get('messages',[])
    first_user=next((i for i,m in enumerate(messages) if m.get('role')=='user'),None)
    if first_user is None:return False
    after=[m for m in messages[first_user+1:] if m.get('role') in ('assistant','system')]
    return call.get('endedReason')=='customer-ended-call' and not after

def main(paths):
    summary={}
    for path in paths:
        report=json.loads(open(path).read());rows=report.get('rows',[]);stalls=[]
        for row in rows:
            if row.get('pass') or not row.get('call_id'):continue
            try:
                if stalled(freya.get_call(row['call_id'])):stalls.append(row['id'])
            except Exception as error:print('call read failed',row['id'],error,file=sys.stderr)
        summary[os.path.basename(path)]={'passed':report.get('passed'),'total':report.get('total'),'stalled':stalls}
        print(os.path.basename(path),report.get('passed'),'/',report.get('total'),'stalled:',stalls)
    return summary

if __name__=='__main__':main(sys.argv[1:])
