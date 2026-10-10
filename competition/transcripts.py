"""Keep actual call events useful to the repair model without repeated snapshots/code."""
import hashlib,json

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
