"""Keep actual call events useful to the repair model without repeated snapshots/code."""
import hashlib,json,re

def loop_signals(messages,ended_reason=None):
    """Objective loop evidence from one call: repeated agent lines, a caller repeating the same answer, a timeout,
    or a verified call closed as not verified. Empty when the call shows none of these."""
    norm=lambda text:re.sub(r'\W+',' ',str(text or '').lower()).strip()
    said=[norm(m.get('message')) for m in messages if m.get('role')=='assistant' and m.get('message')]
    heard=[norm(m.get('message')) for m in messages if m.get('role')=='user' and m.get('message')]
    signals=[]
    counts={}
    for line in said:counts[line]=counts.get(line,0)+1
    repeated=sorted(((n,line) for line,n in counts.items() if n>=3 and len(line)>15),reverse=True)
    if repeated:signals.append({'kind':'agent_repeats_line','times':repeated[0][0],'line':repeated[0][1][:160]})
    run=best=1
    for previous,current in zip(heard,heard[1:]):
        run=run+1 if current and current==previous else 1;best=max(best,run)
    if best>=3:signals.append({'kind':'caller_repeats_answer','times':best})
    if ended_reason=='exceeded-max-duration':signals.append({'kind':'call_timed_out'})
    events=[]
    for m in messages:
        if m.get('role')!='system':continue
        try:event=json.loads(m.get('message',''))
        except (TypeError,ValueError):continue
        if isinstance(event,dict):events.append(event)
    verified=any(e.get('event')=='function_call_complete' and isinstance(e.get('result'),dict) and str((e['result'].get('data') or {}).get('all_verified')).lower()=='true' for e in events)
    closed_unverified=any(e.get('event')=='function_call_start' and e.get('function')=='api_call' and str(e.get('args',{}).get('url','')).endswith('/close_call') and (e.get('args',{}).get('body') or {}).get('outcome')=='not_verified' for e in events)
    if verified and closed_unverified:signals.append({'kind':'verified_call_closed_not_verified'})
    return signals

def compact_messages(messages):
    output=[];previous={}
    for message in messages:
        entry={key:message[key] for key in ('role','nodeId','secondsFromStart','message') if key in message}
        if message.get('role')=='system':
            try:event=json.loads(message.get('message',''))
            except (TypeError,ValueError):output.append(entry);continue
            if not isinstance(event,dict):output.append(entry);continue
            kind=event.get('event');function=event.get('function')
            if kind=='function_call_start' and function=='code_exec':
                code=event.get('args',{}).get('code','');event={'event':kind,'function':function,'code_sha256':hashlib.sha256(code.encode()).hexdigest()}
            table=event.pop('variable_table',None)
            if isinstance(table,dict):
                current={key:(value['value'] if isinstance(value,dict) and 'value' in value and 'source' in value else value) for key,value in table.items() if not key.startswith(('system.','call.')) and not key.endswith(('.current_turns','.total_turns'))}
                changed={key:value for key,value in current.items() if previous.get(key)!=value}
                if changed:event['variable_updates']=changed
                previous.update(current)
            event.pop('raw_response',None)
            entry['event']=event;entry.pop('message',None)
        output.append(entry)
    return output
