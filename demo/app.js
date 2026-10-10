import {compile} from './compiler.js';
import {PhoneDemo, simulate, checkCase} from './engine.js';
import {DEFAULT_BRIEF,STRICT_BRIEF,SCENARIOS} from './presets.js';
const $ = id=>document.getElementById(id);
let api,build,machine,activeScenario,suiteResults=[];
const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function download(name,value) {const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function policyView(policy) {
  $('policy').innerHTML=[['Kimlik limiti',`${policy.maxWrong} yanlış cevap`],['İkna limiti',`${policy.maxPersuasion} teklif`],['Son tarih',policy.deadline],['Tekrar deneme',`${policy.retries} kez`]].map(([key,value])=>`<div class="policy-item"><span>${key}</span><strong>${esc(value)}</strong></div>`).join('');
}
function showNode(key) {if(!build)return;$('json-preview').textContent=JSON.stringify(build.workflow.nodes[key],null,2);$('node-detail').open=true;}
function render() {
  if(!machine)return;
  $('messages').innerHTML=machine.messages.map(m=>`<div class="message ${m.role}"><span class="avatar">${m.role==='agent'?'A':'M'}</span><div class="message-body"><strong>${m.role==='agent'?'Ajan':'Müşteri'}</strong><div class="bubble">${esc(m.text)}</div></div></div>`).join('');
  $('messages').scrollTop=$('messages').scrollHeight;
  $('tool-trace').innerHTML=machine.bank.calls.length?machine.bank.calls.map(c=>`<div class="tool-row ${c.result.ok?'':'failed'}"><div class="tool-heading"><span>[${String(c.index).padStart(2,'0')}]</span><strong>${esc(c.name)}</strong><span class="${c.result.ok?'tool-ok':'tool-error'}">${c.result.ok?'ok':'error'}</span></div><div class="tool-data">params: ${esc(JSON.stringify(c.args))}</div><div class="tool-result">result: ${esc(JSON.stringify(c.result))}</div></div>`).join(''):'<div class="placeholder">Henüz bir banka aracı çağrılmadı.<span>Doğru kişiyle konuştuğunuzu doğrulayarak başlayın.</span></div>';
  $('tool-trace').scrollTop=$('tool-trace').scrollHeight;
  const ledger=machine.bank.closeRecord;
  $('ledger').innerHTML=ledger?`<strong>Banka kaydı</strong> · ${esc(ledger.outcome)}${ledger.reason?' / '+esc(ledger.reason):''}<br>${machine.bank.promises.length?machine.bank.promises.map(p=>`${esc(p.product_id)} · $${p.amount} · ${esc(p.date)}`).join('<br>'):'Ödeme sözü kaydedilmedi.'}`:'<strong>Banka kaydı</strong> · Görüşme sürüyor. Henüz bir ödeme sözü yok.';
  $('suggestions').replaceChildren(...machine.suggestions.map(text=>{const button=document.createElement('button');button.textContent=text;button.addEventListener('click',()=>send(text));return button;}));
  const closed=machine.state==='closed';$('chat-input').disabled=closed;$('send').disabled=closed;
  const current={greeting:'greeting',third_party:'greeting',date_of_birth:'identity',phone_last4:'identity',collection:'collection',confirm:'collection',hardship:'collection',closed:'closing'}[machine.state];
  document.querySelectorAll('.node').forEach(node=>node.classList.toggle('active',node.dataset.node===current));
  if(activeScenario && closed){const check=checkCase(machine,activeScenario);$('result').textContent=check.pass?'✓ Yerel kontrol geçti':'✕ Yerel kontrol başarısız';$('result').className='result'+(check.pass?'':' fail');$('checks').innerHTML=check.checks.map(c=>`<span class="check ${c.pass?'':'failed'}">${c.pass?'✓':'✕'} ${esc(c.label)}</span>`).join('');}
  else {$('result').textContent=closed?'Görüşme tamamlandı':'Canlı yerel deneme';$('checks').replaceChildren();}
  $('trace-download').disabled=false;$('reset').disabled=false;
}
function send(text) {machine.send(text);$('chat-input').value='';render();}
function selectScenario(id) {if(!build)return;activeScenario=id;const scenario=SCENARIOS.find(s=>s.id===id);$('scenario-detail').textContent=scenario.detail;machine=simulate(build.policy,id);document.querySelectorAll('[data-scenario]').forEach(button=>{const selected=button.dataset.scenario===id;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',selected);});render();}
function createAgent() {
  try {
    const candidate=compile($('brief').value,api);
    // Validate calendar for the synthetic customer's fixed date before replacing state.
    new PhoneDemo(candidate.policy);
    build=candidate;suiteResults=[];$('suite').hidden=true;$('workflow').classList.remove('empty');
    policyView(build.policy);$('json-preview').textContent=JSON.stringify(build.workflow,null,2);
    $('workflow-description').textContent=`${build.policy.bank} · 5 düğüm · Bankanın API şemasından üretilen araçlar`;
    $('build-status').className='status';$('build-status').textContent='✓ Workflow oluşturuldu. Şimdi senaryoları deneyin.';
    $('download').disabled=false;$('run-all').disabled=false;document.querySelectorAll('[data-scenario]').forEach(b=>b.disabled=false);selectScenario('promise');
  } catch(error){$('build-status').className='status error';$('build-status').textContent=error.message;}
}
function invalidate() {
  build=undefined;machine=undefined;activeScenario=undefined;suiteResults=[];
  ['download','run-all','trace-download','reset','chat-input','send'].forEach(id=>$(id).disabled=true);
  document.querySelectorAll('[data-scenario]').forEach(b=>b.disabled=true);
  document.querySelectorAll('.node').forEach(b=>b.classList.remove('active'));
  $('workflow').classList.add('empty');$('policy').innerHTML='<p>Yeni brief için <strong>Ajanı oluştur</strong> düğmesine basın.</p>';
  $('workflow-description').textContent='Brief değişti. Yeni kuralları uygulamak için ajanı yeniden oluşturun.';
  $('json-preview').textContent='Brief değişti. Workflow’u yeniden oluşturun.';
  $('messages').innerHTML='<div class="placeholder">Yeni brief hazır.<span>Ajanı yeniden oluşturup senaryoları deneyin.</span></div>';
  $('tool-trace').innerHTML='<div class="placeholder">Yeni çalıştırma bekleniyor.</div>';
  $('result').textContent='';$('checks').replaceChildren();$('suggestions').replaceChildren();$('ledger').textContent='Banka kaydı henüz oluşmadı.';$('suite').hidden=true;
  $('build-status').textContent='Brief değişti; önceki sonuçlar temizlendi.';$('build-status').className='status';
}
$('brief').value=DEFAULT_BRIEF;
for(const [id,text]of [['default-preset',DEFAULT_BRIEF],['strict-preset',STRICT_BRIEF]])$(id).addEventListener('click',()=>{ $('brief').value=text;for(const buttonId of ['default-preset','strict-preset']){$(buttonId).classList.toggle('selected',buttonId===id);$(buttonId).setAttribute('aria-pressed',buttonId===id);}invalidate();});
$('brief').addEventListener('input',invalidate);
for(const scenario of SCENARIOS){const button=document.createElement('button');button.textContent=scenario.label;button.dataset.scenario=scenario.id;button.disabled=true;button.setAttribute('aria-pressed','false');button.addEventListener('click',()=>selectScenario(scenario.id));$('scenarios').append(button);}
$('build').disabled=true;
fetch('./assets/bank-api.json').then(r=>{if(!r.ok)throw new Error('API şeması yüklenemedi.');return r.json();}).then(value=>{api=value;$('build').disabled=false;}).catch(error=>{$('build-status').className='status error';$('build-status').textContent=error.message;});
$('build').addEventListener('click',createAgent);
$('download').addEventListener('click',()=>download('freya-demo.workflow.json',build.workflow));
$('trace-download').addEventListener('click',()=>download('freya-demo.trace.json',{...build.trace,downloaded:new Date().toISOString(),policy:build.policy,simulation_type:'local deterministic policy simulation, not Freya workflow execution',cases:suiteResults,conversation:machine.messages,tool_calls:machine.bank.calls,ledger:{promises:machine.bank.promises,close:machine.bank.closeRecord}}));
$('run-all').addEventListener('click',()=>{suiteResults=SCENARIOS.map(s=>checkCase(simulate(build.policy,s.id),s.id));build.trace.tests=suiteResults.map(r=>({case:r.id,pass:r.pass,environment:'local-policy-simulator'}));$('suite').hidden=false;$('suite').innerHTML=`<h3>${suiteResults.filter(r=>r.pass).length}/${suiteResults.length} yerel senaryo kontrolü geçti</h3><div class="suite-grid">${suiteResults.map(r=>`<button class="${r.pass?'':'failed'}" data-result="${r.id}">${r.pass?'✓':'✕'} ${esc(SCENARIOS.find(s=>s.id===r.id).label)}<span>${esc(r.ledger.close?.outcome||'Kapanış yok')}</span></button>`).join('')}</div>`;$('suite').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>selectScenario(b.dataset.result)));});
$('reset').addEventListener('click',()=>{activeScenario=undefined;machine=new PhoneDemo(build.policy);$('scenario-detail').textContent='Kendiniz deneyin. Tarihler YYYY-AA-GG, tutarlar “tutar: 200” biçiminde. Hızlı cevapları da kullanabilirsiniz.';document.querySelectorAll('[data-scenario]').forEach(b=>{b.classList.remove('selected');b.setAttribute('aria-pressed','false');});render();});
$('chat-form').addEventListener('submit',event=>{event.preventDefault();if(machine&&machine.state!=='closed')send($('chat-input').value);});
document.querySelectorAll('.node').forEach(node=>node.addEventListener('click',()=>showNode(node.dataset.node)));
