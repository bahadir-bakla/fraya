"""Local structural checks. These complement, never replace, Freya dry-run/scoring."""
import ast
from urllib.parse import urlparse

def validate_coverage(coverage):
    errors=[]
    def walk(value,path='coverage'):
        if isinstance(value,dict):
            status=str(value.get('status','')).lower().replace('_',' ')
            if any(marker in status for marker in ('degraded enforcement','weakened enforcement','not implemented','not enforced','prompt only')):
                errors.append(f'{path}: required policy enforcement is incomplete: {value.get("rule",value.get("id",status))}')
            for key,item in value.items():walk(item,path+'.'+key)
        elif isinstance(value,list):
            for index,item in enumerate(value):walk(item,f'{path}[{index}]')
    walk(coverage)
    return errors

def validate(workflow, api):
    errors = []
    def fail(message): errors.append(message)
    def walk(value, location='workflow'):
        if value is None: fail(f'{location}: null is forbidden')
        elif isinstance(value,dict):
            for key,item in value.items(): walk(item,f'{location}.{key}')
        elif isinstance(value,list):
            for i,item in enumerate(value): walk(item,f'{location}[{i}]')
    walk(workflow)
    nodes={**workflow.get('nodes',{}),**workflow.get('global_nodes',{})}
    if workflow.get('initial_node') not in workflow.get('nodes',{}): fail('initial_node does not name a normal node')
    if 'agent_config' in workflow: fail('builder must not set agent_config')
    allowed_urls={server['url'].rstrip('/')+endpoint for server in api['servers'] for endpoint in api['paths']}
    def check_code(code,where):
        if '{{' in code or '}}' in code: fail(f'{where}: forbidden double-curly markers')
        try: tree=ast.parse(code)
        except SyntaxError as error: fail(f'{where}: Python syntax: {error}');return
        for item in ast.walk(tree):
            if isinstance(item,ast.Global):fail(f'{where}: global control writes are not a reliable sandbox state contract; use vars or explicit returned values for {item.names}')
            if isinstance(item,(ast.Import,ast.ImportFrom)):
                modules=[alias.name for alias in item.names] if isinstance(item,ast.Import) else [item.module or '']
                if any(module.split('.')[0] not in {'json','re','datetime'} for module in modules):fail(f'{where}: unsupported module {modules}')
            if isinstance(item,ast.Call) and isinstance(item.func,ast.Name) and item.func.id in {'open','eval','exec','__import__','compile'}:fail(f'{where}: forbidden call {item.func.id}')
    def check_tool(tool,where):
        fn=tool.get('function',{});handler=fn.get('handler');name=fn.get('name');props=fn.get('parameters',{}).get('properties',{})
        for hook in ('pre_process_code','post_process_code'):
            if tool.get(hook):check_code(tool[hook],f'{where}.{hook}')
        if handler=='__function__:code_exec':check_code(props.get('code',{}).get('default',''),where);return
        if handler=='__function__:end_call':return
        if handler!='__function__:api_call':fail(f'{where}: unsupported handler {handler}');return
        url=props.get('url',{}).get('default','')
        if url not in allowed_urls:fail(f'{where}: endpoint outside supplied bank API: {url}')
        endpoint='/'+name if '/'+str(name) in api['paths'] else urlparse(url).path.removeprefix(urlparse(api['servers'][0]['url']).path)
        operation=api['paths'].get(endpoint,{}).get('post',{})
        expected=operation.get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema',{})
        body=props.get('body',{})
        if body.get('type')!='object':fail(f'{where}: body must be an object schema')
        if set(body.get('required',[])) != set(expected.get('required',[])):fail(f'{where}: required body fields differ from OpenAPI')
        if set(body.get('properties',{})) != set(expected.get('properties',{})):fail(f'{where}: body fields differ from OpenAPI')
        for field,schema in expected.get('properties',{}).items():
            actual=body.get('properties',{}).get(field,{})
            if actual.get('type')!=schema.get('type'):fail(f'{where}.{field}: incorrect type')
            if actual.get('enum')!=schema.get('enum'):fail(f'{where}.{field}: incorrect enum')
        if name in {'create_promise','add_note','close_call','transfer_to_agent','schedule_callback'} and tool.get('config',{}).get('maxRetries',0)!=0:fail(f'{where}: automatic write retries must be zero')
        for mapping in tool.get('response_mapping',[]):
            if not mapping.get('path','').startswith('data.'):fail(f'{where}: response path must start with data.')
    for key,node in nodes.items():
        kind=node.get('node_type')
        entry=node.get('on_enter',{})
        if entry.get('type')=='tts' and not str(entry.get('text','')).strip():fail(f'{key}: empty TTS entry can terminate the call; use silent for action nodes')
        if kind=='conversation' and node.get('pre_actions'):fail(f'{key}: pre_actions dropped on conversation node')
        if kind in {'code','api_request'} and node.get('tools'):fail(f'{key}: tools dropped on action node')
        for transition in node.get('transitions',[]):
            target=transition.get('target_node')
            if target not in nodes and target!='__previous__':fail(f'{key}: missing transition target {target}')
        if node.get('passthrough') and not any(t.get('condition',{}).get('operator')=='always' for t in node.get('transitions',[])):fail(f'{key}: passthrough needs always fallback')
        for var in node.get('extraction_schema',[]):
            if 'min_confidence' not in var:fail(f'{key}.{var.get("name")}: missing min_confidence')
        for mapping in node.get('response_mapping',[]):
            if not mapping.get('path','').startswith('data.'):fail(f'{key}: mapping must start with data.')
        for i,tool in enumerate(node.get('tools',[])+node.get('pre_actions',[])):check_tool(tool,f'{key}.tool[{i}]')
    for i,tool in enumerate(workflow.get('tools',[])):check_tool(tool,f'workflow.tool[{i}]')
    return errors
