import ast,copy,datetime,hashlib,json,pathlib,sys
sys.stdout.reconfigure(encoding='utf-8')
root=pathlib.Path.cwd(); base=root/'analysis/final-case-candidate-v1-review'
published='ce88e20b64fb25825016b9151f9819230d01006e4648e46b7886559baffb67e0'
pin=pathlib.Path(str(base)+'.candidate.json'); current=root/'competition/runs/20261011-223232-b788d1/work/workflow.json'
current_sha=hashlib.sha256(current.read_bytes()).hexdigest()
source=current if current_sha==published else pin
wf=json.loads(source.read_bytes()); sha=hashlib.sha256(source.read_bytes()).hexdigest()
code=wf['nodes']['controller']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
tree=ast.parse(code)
assert all(a.name in ('json','re','datetime') for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names)
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('eval','exec','open','compile') for n in ast.walk(tree))
compiled=compile(code,'IMMUTABLE_DOTTED_VARIABLE_CPU_WITNESS','exec')
fixture=json.loads((root/'final-case-20261011/Build the Builder - Final Case/test-environment/test-customers.json').read_bytes())
c=next(x for x in fixture['customers'] if x['customerNo']=='96158684'); response=c['services']['cards.list']
vars={'customerNumber':'96158684','now':'2026-10-11T22:45:00+03:00'}
exec(compiled,{'vars':vars}); start=copy.deepcopy(vars)
def flat(value,prefix,out):
 if isinstance(value,dict):
  for k,v in value.items(): flat(v,prefix+'.'+k,out)
 elif isinstance(value,list):
  for i,v in enumerate(value): flat(v,prefix+'.'+str(i),out)
 else:out[prefix]=value
flat({'status_code':response['http'],'data':response['response']},'cards_list_response',vars)
assert 'cards_list_response.data' not in vars
assert 'cards_list_response.data.data.cards.0.isMainCard' in vars
raw=copy.deepcopy(vars); exec(compiled,{'vars':vars})
bad=json.loads(vars['bank_state'])
# Reference-only reconstruction; never changes the controller or candidate.
def rebuild(leaves,prefix):
 paths=[(k[len(prefix)+1:].split('.'),v) for k,v in leaves.items() if k.startswith(prefix+'.')]
 def build(rows):
  direct=[v for path,v in rows if not path]
  if direct:return direct[-1]
  grouped={}
  for path,v in rows: grouped.setdefault(path[0],[]).append((path[1:],v))
  if grouped and all(k.isdigit() for k in grouped):
   out=[None]*(max(map(int,grouped))+1)
   for k,g in grouped.items():out[int(k)]=build(g)
   return out
  return {k:build(g) for k,g in grouped.items()}
 return build(paths)
rebuilt=rebuild(raw,'cards_list_response.data'); goodvars=copy.deepcopy(raw);goodvars['cards_list_response.data']=rebuilt
exec(compiled,{'vars':goodvars});good=json.loads(goodvars['bank_state'])
assert bad['route']=='finish' or bad.get('phase')=='end' or 'uygun bir kredi kartınız bulunmuyor' in bad.get('line','')
assert good['route']=='cards_balance'
report={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'published_failure_source_sha256':published,'executed_candidate_sha256':sha,'executed_candidate_is_published':sha==published,'source_path':str(source),'original_current_sha256_at_probe':current_sha,'hosted_evidence':'analysis/final-case-v1-hosted-failure.json; all five fail before substantive dialogue, HTTP success true; parent-provided platform dotted-leaf detail','cpu_witness':{'customerNumber':'96158684','nested_parent_absent':True,'dotted_leaf_example':'cards_list_response.data.data.cards.0.isMainCard','http':response['http'],'result_returnCode':response['response']['result']['returnCode'],'cards_count':len(response['response']['data']['cards']),'original_observed_route':bad['route'],'original_observed_line':bad.get('line'),'reference_reconstruction_route':good['route'],'reference_reconstruction_card':good.get('card'),'reference_array_type':type(rebuilt['data']['cards']).__name__},'repair_instruction':'Normalize only the currently pending operation response from this API completion: reconstruct nested dictionaries and numeric-index arrays from operation-prefixed dotted leaves before interpreting bank results. Preserve actual HTTP status and result.returnCode, validate reconstructed shape, and never classify missing or malformed payload as no eligible cards. Apply this generic boundary adapter to all seven API nodes, retaining receipt freshness and existing write-consent gates; prove dotted-only cards -> card selection/balance and dotted-only write receipts -> success only after valid fresh receipts.','bank_network_calls':0,'freya_calls':0,'candidate_modified':False,'native_call_added':False,'qualification':'If executed hash differs from published hash, CPU witness reproduces identical failure mode on earlier frozen candidate only; hosted outcomes bind ce88e20b, not the earlier hash.'}
pathlib.Path(str(base)+'.followup.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
text='BLOCKER: normalize fresh operation-scoped dotted API variables into nested dictionaries and numeric-index arrays before receipt validation and domain logic. Preserve HTTP/result checks; absent/malformed data must be an integration failure, not a no-card conclusion. Use the same adapter for all seven operations and verify valid fresh write receipts.\n\nPublished v1 SHA256: '+published+'; hosted 5/5 failures, API HTTP200 with eligible cards.\nCPU executed SHA256: '+sha+' (published match: '+str(sha==published)+'). cards_list_response.data absent; cards_list_response.data.data.cards.0.isMainCard present; unmodified controller falsely emits no-card. Reference-only reconstruction restores cards_balance.\n\nPrior Opus audit binds 5637dc7df1cef75b1a6d136a56ad76e63d2e9451aab0d806bc053af87fcf98f2, NOT published ce88e20b. Native call completed with verified claude-opus-5-5 and usage; no waiting on model metadata, no new native call.\nNew repair run 20261011-224723-9d9433 is pending; no claim about its output.\n'
pathlib.Path(str(base)+'.followup.txt').write_text(text,encoding='utf-8')
print(json.dumps({'followup':str(base)+'.followup.txt','executed_sha256':sha,'published_match':sha==published,'witness':report['cpu_witness']},ensure_ascii=False))
