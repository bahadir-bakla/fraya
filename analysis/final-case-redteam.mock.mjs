// Independent local audit. Frozen module sources and outputs stay in owned scope.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL, fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runtime=path.join(root,'integrations/opus-redteam/runtime/final-case-20261011/mock-snapshot');
mkdirSync(runtime,{recursive:true});
const sourceFiles=['final-bank-mock/src/index.js','final-bank-mock/src/fixtures.js','final-bank-mock/openapi.json','final-bank-mock/scripts/prepare.mjs','final-bank-mock/wrangler.toml','final-case-20261011/Build the Builder - Final Case/test-environment/test-customers.json'];
const frozen=new Map(sourceFiles.map(p=>[p,readFileSync(path.join(root,p))]));
const hash=b=>createHash('sha256').update(b).digest('hex');
for(const p of ['final-bank-mock/src/index.js','final-bank-mock/src/fixtures.js'])writeFileSync(path.join(runtime,path.basename(p)),frozen.get(p));
writeFileSync(path.join(runtime,'package.json'),'{"type":"module"}\n');
const {createWorker,SERVICES}=await import(pathToFileURL(path.join(runtime,'index.js')).href);
const {default:fixtureCopy}=await import(pathToFileURL(path.join(runtime,'fixtures.js')).href);
const fixtures=JSON.parse(frozen.get(sourceFiles.at(-1)).toString('utf8'));
const openapi=JSON.parse(frozen.get('final-bank-mock/openapi.json').toString('utf8'));
const waits=[];const worker=createWorker({wait:async ms=>{waits.push(ms);}});
const report={review_type:'independent_local_mock_contract_execution',started_utc:new Date().toISOString(),
 mock_source_manifest:[...frozen].map(([p,b])=>({path:p,sha256:hash(b),bytes:b.length})),
 actual_public_http_verified:false,remote_calls:0,auth_calls:0,fixture_checks:[],negative_checks:[],schema_failures:[],findings:[]};
try{assert.deepEqual(fixtureCopy,fixtures);report.fixture_snapshot_exact=true;}catch{report.fixture_snapshot_exact=false;report.findings.push({priority:'P0',title:'Embedded fixtures differ from original source JSON'});}
const request=(service,data,extra={})=>new Request('https://local-audit.invalid/voice/v1/'+service,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data,...extra})});
async function call(service,data,extra){const r=await worker.fetch(request(service,data,extra));return {status:r.status,body:await r.json()};}
function leaves(obj,prefix=[],out=[]){if(obj && Number.isInteger(obj.http))out.push({entry:obj,keys:prefix});else for(const[k,v]of Object.entries(obj||{}))leaves(v,[...prefix,k],out);return out;}
function schemaErrors(schema,value,pointer='$',out=[]){
 if(schema.$ref)return schemaErrors(openapi.components.schemas[schema.$ref.split('/').at(-1)],value,pointer,out);
 if(value===null && schema.nullable)return out;
 if(schema.oneOf){if(!schema.oneOf.some(s=>schemaErrors(s,value,pointer,[]).length===0))out.push({pointer,rule:'oneOf',value});return out;}
 const type=schema.type;
 const good=!type || (type==='object'?value!==null&&typeof value==='object'&&!Array.isArray(value):type==='array'?Array.isArray(value):type==='integer'?Number.isInteger(value):typeof value===type);
 if(!good){out.push({pointer,rule:'type '+type,value});return out;}
 if(schema.enum && !schema.enum.includes(value))out.push({pointer,rule:'enum',value});
 if(schema.pattern && typeof value==='string' && !new RegExp(schema.pattern).test(value))out.push({pointer,rule:'pattern '+schema.pattern,value});
 if(schema.minLength!==undefined && value.length<schema.minLength)out.push({pointer,rule:'minLength',value});
 if(schema.minimum!==undefined && value<schema.minimum)out.push({pointer,rule:'minimum',value});
 if(schema.maximum!==undefined && value>schema.maximum)out.push({pointer,rule:'maximum',value});
 if(type==='object'){
  for(const k of schema.required||[])if(!(k in value))out.push({pointer:pointer+'.'+k,rule:'required'});
  for(const[k,v]of Object.entries(value))if(schema.properties?.[k])schemaErrors(schema.properties[k],v,pointer+'.'+k,out);
  if(schema.additionalProperties===false)for(const k of Object.keys(value))if(!schema.properties?.[k])out.push({pointer:pointer+'.'+k,rule:'additionalProperties'});
 }
 if(type==='array')value.forEach((v,i)=>schemaErrors(schema.items,v,pointer+'['+i+']',out));
 return out;
}
for(const c of fixtures.customers){
 const list=c.services['cards.list']?.response?.data?.cards||[];
 for(const[service,value]of Object.entries(c.services))for(const{entry,keys}of leaves(value)){
  const card=keys[0]||list[0]?.cardNumber||'540000******0000';
  const get=c.services['statement.week.get']?.[card]?.response?.data;
  const balance=c.services['cards.balance']?.[card]?.response?.data;
  const day=get?.statementDay||1;
  const week=keys[1];
  const data=service==='cards.list'?{customerNo:c.customerNo,aiFlow:'CardOps'}:
   service==='contact.email.get'?{customerNo:c.customerNo,intAddressInfoType:'E'}:
   service==='statement.pdf.send'?{customerNo:c.customerNo,cardNumber:card,currencyType:'TL',statementDate:balance?.statementDate||'05.10.2026',emailAddress:c.services['contact.email.get']?.response?.data?.ibanEmail||'synthetic@local.invalid'}:
   {cardNumber:card,...(week?{newStatementWeek:week,statementDay:day}:{})};
  const result=await call(service,data,{call:{ani:'synthetic',lang:'tr'}});
  let exact=true;try{assert.equal(result.status,entry.http);assert.deepEqual(result.body,entry.response);}catch{exact=false;}
  const pointer=`customer=${c.customerNo} service=${service} keys=${keys.join('/')}`;
  report.fixture_checks.push({pointer,expected_http:entry.http,actual_http:result.status,exact});
  const schema=openapi.paths['/voice/v1/'+service]?.post?.responses[String(entry.http)]?.content?.['application/json']?.schema;
  if(schema)for(const error of schemaErrors(schema,entry.response))report.schema_failures.push({fixture:pointer,...error});
  else report.schema_failures.push({fixture:pointer,rule:'Missing response schema'});
  if(['cards.list','contact.email.get','statement.pdf.send'].includes(service)){
   const numeric=await call(service,{...data,customerNo:Number(c.customerNo)},{call:'ignored',aiFlow:'ignored'});
   report.negative_checks.push({name:'customerNo number/string '+pointer,pass:numeric.status===entry.http&&JSON.stringify(numeric.body)===JSON.stringify(entry.response)});
  }
  if(week){const numeric=await call(service,{...data,newStatementWeek:Number(week)});report.negative_checks.push({name:'week number/string '+pointer,pass:numeric.status===entry.http&&JSON.stringify(numeric.body)===JSON.stringify(entry.response)});}
 }
}
const unknowns={
 'cards.list':[{customerNo:'99999999'},404,'FB_IVR_CHANNEL_102'],
 'cards.balance':[{cardNumber:'not-owned'},404,'FB_IVR_CHANNEL_120'],
 'statement.week.get':[{cardNumber:'not-owned'},404,'FB_IVR_CHANNEL_121'],
 'statement.week.decide':[{cardNumber:'not-owned',newStatementWeek:2,statementDay:5},400,'INVALID_ARGUMENTS_ERROR'],
 'statement.week.change':[{cardNumber:'not-owned',newStatementWeek:2,statementDay:5},400,'INVALID_ARGUMENTS_ERROR'],
 'contact.email.get':[{customerNo:'99999999',intAddressInfoType:'E'},400,'INVALID_ARGUMENTS_ERROR'],
 'statement.pdf.send':[{customerNo:'99999999',cardNumber:'not-owned',currencyType:'TL',statementDate:'05.10.2026',emailAddress:'synthetic@local.invalid'},404,'FB_IVR_CHANNEL_107']};
async function check(name,service,data,http,code){const r=await call(service,data);report.negative_checks.push({name,pass:r.status===http&&r.body.result?.returnCode===code&&!('data'in r.body)&&r.body.result?.code===code&&r.body.result?.messageText===r.body.result?.message});}
for(const[s,[d,h,c]]of Object.entries(unknowns))await check('Unknown lookup '+s,s,d,h,c);
for(const s of SERVICES)await check('Missing required fields '+s,s,{},400,'INVALID_ARGUMENTS_ERROR');
await check('Current week preview no fixture','statement.week.decide',{cardNumber:'540000******1234',newStatementWeek:1,statementDay:5},400,'INVALID_ARGUMENTS_ERROR');
await check('Balance masking is not list key','cards.balance',{cardNumber:'5400********1234'},404,'FB_IVR_CHANNEL_120');
// The fixture mock is intentionally permissive: authorization belongs to the agent.
const permissive=await call('statement.pdf.send',{customerNo:'90000001',cardNumber:'arbitrary',currencyType:'TL',statementDate:'01.01.2025',emailAddress:'unregistered@local.invalid'});
report.negative_checks.push({name:'PDF fixture lookup by customer only; no added business authorization',pass:permissive.status===200&&permissive.body.data?.exitState==='DONE'});
const inconsistentContact=await call('contact.email.get',{customerNo:90000001,intAddressInfoType:'X'});
report.negative_checks.push({name:'Contact fixture ignores nonempty requested type',pass:inconsistentContact.status===200});
report.delay_checks={expected_12000_ms:waits.filter(ms=>ms===12000).length,unexpected_delays:waits.filter(ms=>ms!==12000),scope:'Stubbed wait records exact requested delay; real timer checked separately below.'};
const realWorker=createWorker();const realStart=performance.now();const slow=await realWorker.fetch(request('cards.balance',{cardNumber:'540000******7211'}));
report.real_delay_check={wall_ms:Math.round(performance.now()-realStart),http:slow.status,body_exact:JSON.stringify(await slow.json())===JSON.stringify(fixtures.customers.find(c=>c.customerNo==='94907600').services['cards.balance']['540000******7211'].response)};
report.functional_failures=report.fixture_checks.filter(c=>!c.exact);
report.negative_failures=report.negative_checks.filter(c=>!c.pass);
if(report.schema_failures.length)report.findings.push({priority:'P1',title:'OpenAPI response date pattern excludes official empty issued/due dates',evidence:report.schema_failures,fix:'Permit documented empty issued statementDate/lastPayDate in response schemas; keep PDF request date validation separate. Fix generic schema generation and regenerate, do not change official fixtures.'});
if(report.functional_failures.length||report.negative_failures.length)report.findings.push({priority:'P0',title:'Local mock contract mismatch',fixture_failures:report.functional_failures,negative_failures:report.negative_failures});
report.hosting_limit='Local frozen-module execution only. Public origin, deployment availability, Cloudflare behavior and candidate routing not verified.';
report.openapi_origin=openapi.servers?.[0]?.url;
report.source_stability=Object.fromEntries([...frozen].map(([p,b])=>[p,hash(readFileSync(path.join(root,p)))===hash(b)]));
report.finished_utc=new Date().toISOString();
writeFileSync(path.join(root,'analysis/final-case-redteam.mock.json'),JSON.stringify(report,null,2)+'\n');
const summary={status:report.functional_failures.length||report.negative_failures.length?'LOCAL_MOCK_MISMATCH':'LOCAL_FIXTURE_BEHAVIOR_MATCHES',fixture_checks:report.fixture_checks.length,fixture_failures:report.functional_failures.length,negative_checks:report.negative_checks.length,negative_failures:report.negative_failures.length,schema_failures:report.schema_failures.length,real_delay_check:report.real_delay_check,source_stability:report.source_stability};
writeFileSync(path.join(root,'analysis/final-case-redteam.mock.txt'),JSON.stringify(summary,null,2)+'\n\n'+report.findings.map(f=>f.priority+' '+f.title+'\n'+f.fix).join('\n')+'\n'+report.hosting_limit+'\n');
console.log(JSON.stringify(summary));
