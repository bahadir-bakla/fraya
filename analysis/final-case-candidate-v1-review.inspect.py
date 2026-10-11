"""Static inventory and exact-code extraction from the pinned candidate only."""
import ast,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'analysis/final-case-candidate-v1-review'
candidate=Path(str(BASE)+'.candidate.json')
if not candidate.exists():
 print(json.dumps({'status':'WAITING_FOR_PINNED_CANDIDATE'}));raise SystemExit(0)
raw=candidate.read_bytes();v=json.loads(raw);codes=[];tools=[];prompts=[]
def esc(s):return str(s).replace('~','~0').replace('/','~1')
def walk(x,p=''):
 if isinstance(x,dict):
  function=x.get('function')
  if isinstance(function,dict):tools.append({'pointer':p,'name':function.get('name'),'handler':function.get('handler'),'config':x.get('config'),'parameters':function.get('parameters'),'pre_process_code':x.get('pre_process_code'),'post_process_code':x.get('post_process_code')})
  for k,y in x.items():
   cp=p+'/'+esc(k)
   if isinstance(y,str) and (k in ('code','pre_process_code','post_process_code') or k=='default' and p.endswith('/code')):
    if y.strip():codes.append({'pointer':cp,'text':y})
   if k in ('system_prompt','task_message','loop_prompt','role_message','routing_prompt') and isinstance(y,str):prompts.append({'pointer':cp,'text':y})
   walk(y,cp)
 elif isinstance(x,list):
  for i,y in enumerate(x):walk(y,p+'/'+str(i))
walk(v)
for i,c in enumerate(codes):
 source=c['text'];p=Path(str(BASE)+f'.code{i}.py');p.write_text(source,encoding='utf-8')
 c.update(path=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(source.encode()).hexdigest(),line_count=len(source.splitlines()))
 try:
  tree=ast.parse(source);c['syntax']='pass'
  c['functions']=[{'name':n.name,'line':n.lineno,'end':n.end_lineno} for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
  c['imports']=[ast.unparse(n) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
 except SyntaxError as e:c.update(syntax='fail',syntax_line=e.lineno,syntax_message=e.msg)
 c.pop('text')
nodes=v.get('nodes',{})
report={'candidate_sha256':hashlib.sha256(raw).hexdigest(),'initial_node':v.get('initial_node'),
 'nodes':[{k:n.get(k) for k in ('name','node_type','on_enter','on_enter_first_entry_only','transitions')}|{'key':key,'extraction_schema':n.get('extraction_schema')} for key,n in nodes.items()],
 'code_entries':codes,'tools':tools,'prompts':prompts,'scope':'Static pinned source inventory only; no platform/model execution.'}
Path(str(BASE)+'.structure.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'candidate_sha256':report['candidate_sha256'],'initial_node':report['initial_node'],'nodes':[{'key':n['key'],'type':n['node_type']} for n in report['nodes']],
 'codes':codes,'tools':[{'pointer':t['pointer'],'name':t['name'],'handler':t['handler'],'config':t['config']} for t in tools]},ensure_ascii=False))
