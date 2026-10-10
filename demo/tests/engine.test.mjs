import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {compile,parseBrief} from '../compiler.js';
import {MockBank,PhoneDemo,simulate,checkCase,nextBusiness} from '../engine.js';
import {DEFAULT_BRIEF,STRICT_BRIEF,SCENARIOS} from '../presets.js';
const api=JSON.parse(await readFile(new URL('../assets/bank-api.json',import.meta.url),'utf8'));
const policy=parseBrief(DEFAULT_BRIEF);
for(const brief of [DEFAULT_BRIEF,STRICT_BRIEF])test(`All synthetic scenarios: ${brief===DEFAULT_BRIEF?'default':'strict'} brief`,()=>{
  const policy=parseBrief(brief);
  for(const scenario of SCENARIOS){const result=checkCase(simulate(policy,scenario.id),scenario.id);assert.equal(result.pass,true,JSON.stringify(result));}
});
test('Changing the brief actually changes identity, persuasion and retry behavior',()=>{
  const strict=parseBrief(STRICT_BRIEF);
  assert.equal(simulate(strict,'wrong_identity').bank.calls.filter(c=>c.name==='verify_identity').length,2);
  assert.equal(simulate(policy,'wrong_identity').bank.calls.filter(c=>c.name==='verify_identity').length,3);
  assert.equal(simulate(strict,'refusal').attempts,1);
  assert.equal(simulate(policy,'refusal').attempts,2);
  assert.equal(simulate(strict,'retry').bank.closeRecord.outcome,'no_promise');
  assert.equal(simulate(policy,'retry').bank.closeRecord.outcome,'promise');
});
test('Neither a relative nor an injection can access account information',()=>{
  for(const id of ['third_party','injection','wrong_identity']){
    const machine=simulate(policy,id);assert.equal(machine.bank.promises.length,0);
    assert(!machine.bank.calls.some(c=>['get_account','create_promise'].includes(c.name)));
  }
});
test('Bank guard refuses unverified account reads and writes even if dialogue is bypassed',()=>{
  const bank=new MockBank(policy);
  assert.equal(bank.call('get_account',{}).error,'not_verified');
  assert.equal(bank.call('create_promise',{product_id:'p1',amount:420,date:'2026-10-14',confirmed:true}).error,'not_verified');
  bank.call('verify_identity',{field:'date_of_birth',answer:'1990-05-14'});
  assert.equal(bank.call('get_account',{}).error,'not_verified');
});
test('Bank rejects missing confirmation, low amounts, unknown products, expired dates and weekends',()=>{
  const bank=new MockBank(policy);bank.call('verify_identity',{field:'date_of_birth',answer:'1990-05-14'});bank.call('verify_identity',{field:'phone_last4',answer:'4821'});
  const good={product_id:'p1',amount:420,date:'2026-10-14',confirmed:true};
  for(const [patch,error]of [[{confirmed:false},'confirmation_required'],[{amount:125},'invalid_amount'],[{product_id:'invented'},'invalid_amount'],[{amount:NaN},'invalid_amount'],[{date:'2026-10-25'},'invalid_date'],[{date:'2026-10-17'},'invalid_date']])assert.equal(bank.call('create_promise',{...good,...patch}).error,error);
  assert.equal(bank.promises.length,0);
});
test('A promise is not recorded before explicit read-back confirmation',()=>{
  const machine=new PhoneDemo(policy);['Evet','1990-05-14','4821','Bugün ödeyebilirim.'].forEach(m=>machine.send(m));
  assert.equal(machine.state,'confirm');assert.equal(machine.bank.promises.length,0);assert(!machine.bank.calls.some(c=>c.name==='create_promise'));
  machine.send('Onaylıyorum.');assert.equal(machine.bank.promises.length,1);
});
test('Service errors never become a false success claim',()=>{
  const machine=simulate(policy,'service_error');assert.equal(machine.bank.promises.length,0);assert(!machine.messages.some(m=>m.role==='agent'&&m.text.includes('sözünüz kaydedildi')));
  assert.equal(machine.bank.closeRecord.reason,'service_error');
});
test('No tools may run after closing and no duplicate promise is recorded',()=>{
  const machine=simulate(policy,'promise');const count=machine.bank.calls.length;machine.send('Onaylıyorum');assert.equal(machine.bank.calls.length,count);
  assert.throws(()=>machine.bank.call('get_account',{}),/sonrasında/);
});
test('Weekend is proposed as a business day and requires acceptance plus read-back confirmation',()=>{
  const machine=new PhoneDemo(policy);['Evet','1990-05-14','4821','2026-10-17'].forEach(m=>machine.send(m));
  assert.equal(machine.proposal.date,'2026-10-19');assert.equal(machine.bank.promises.length,0);
  machine.send('Evet');assert.equal(machine.state,'confirm');machine.send('Onaylıyorum');assert.equal(machine.bank.promises[0].date,'2026-10-19');
  assert.equal(nextBusiness('2026-10-26',policy),'2026-10-27');
});
test('Changing a proposed amount clears prior pending confirmation and validates it again',()=>{
  const machine=new PhoneDemo(policy);['Evet','1990-05-14','4821','Bugün ödeyebilirim.','tutar: 200 bugün'].forEach(m=>machine.send(m));
  assert.equal(machine.pending.amount,200);assert.equal(machine.bank.promises.length,0);machine.send('Onaylıyorum');assert.equal(machine.bank.promises[0].amount,200);
});
test('Compiler gates account access on a bank response, never on extracted customer claims',()=>{
  const {workflow}=compile(DEFAULT_BRIEF,api);
  assert.equal(workflow.nodes.identity.tools.filter(t=>t.function.name==='get_account').length,0);
  const route=workflow.nodes.identity.transitions.find(t=>t.target_node==='account');
  assert(route.condition.conditions.every(c=>c.variable==='verify_identity_response.data.all_verified'));
  assert.equal(workflow.nodes.account.pre_actions[0].function.name,'get_account');
  assert.equal(workflow.nodes.collection.tools.find(t=>t.function.name==='create_promise').config.maxRetries,0);
});
test('Workflow output has resolved node references, no nulls, and only supported API endpoints',()=>{
  const {workflow}=compile(DEFAULT_BRIEF,api);
  const visit=value=>{assert.notEqual(value,null);if(typeof value==='object')Object.values(value).forEach(visit);};visit(workflow);
  assert(!('agent_config' in workflow));
  for(const node of Object.values(workflow.nodes)){
    for(const transition of node.transitions)assert(workflow.nodes[transition.target_node]);
    for(const tool of [...(node.tools||[]),...(node.pre_actions||[])]){
      assert(api.paths['/'+tool.function.name]);
      assert.deepEqual(tool.function.parameters.properties.body.required,api.paths['/'+tool.function.name].post.requestBody.content['application/json'].schema.required);
    }
  }
});
test('Unrecognized briefs and impossible calendar dates fail visibly instead of using hidden defaults',()=>{
  assert.throws(()=>parseBrief('Do something with a bank.'),/alanı bulunamadı/);
  assert.throws(()=>parseBrief(DEFAULT_BRIEF.replace('2026-10-23','2026-02-30')),/geçerli/);
  assert.throws(()=>new PhoneDemo({...policy,deadline:'2026-10-17'}),/iş günü/);
});
