import json,re,copy,datetime,hashlib
from pathlib import Path
w=json.load(open('workflow.json')); code=w['nodes']['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default']
ns={'vars':{}};exec(code,ns)
results=[]
def check(name,fn):
 try: fn();results.append({'test':name,'status':'passed'})
 except Exception as e: results.append({'test':name,'status':'failed','error':repr(e)});print('FAIL',name,repr(e))
def need(value): assert value
class Call:
 def __init__(self):
  self.v={'customer_id':'local_customer','first_name':'Aylin','last_name':'Demir','title':'Ms','now':'2026-10-14T11:00'};self.step()
 def step(self,**values):
  self.v.update(values); patch=copy.deepcopy(self.v);scope={'vars':patch};exec(code,scope);self.v.update(patch);return self
 def say(self,raw,event='k=unknown;c=1;END',**values): return self.step(raw=raw,event=event,**values)
 def receipt(self,node,data,http=200,post=True):
  tool=w['nodes'][node]['pre_actions'][0];prop=tool['function']['parameters']['properties']; config={'body':{k:self.v.get(v['default'][2:-2],v['default']) for k,v in prop['body']['properties'].items()},'method':prop['method']['default'],'url':prop['url']['default']}
  # Actual hooks and current automatic counters, merged exactly as persistent patches.
  env={'vars':self.v,'config':config};exec(tool.get('pre_process_code',''),env)
  self.v[node+('_success_count' if http==200 else '_failure_count')]=int(self.v.get(node+('_success_count' if http==200 else '_failure_count'),0))+1
  self.v.update({node+'_response.status':'success' if http==200 else 'error',node+'_response.status_code':http,node+'_status_code':http,node+'_response.error':'' if http==200 else 'HTTP '+str(http)})
  if post:
   env={'vars':self.v,'result':{'status':'success' if http==200 else 'error','data':data,'status_code':http}};exec(tool.get('post_process_code',''),env)
  self.step();return self
 def ready(self):
  self.say('Speaking.',recipient_act='recipient');need(self.v['state']['phase']=='dob')
  self.say('Ninth April one nine eight two.',security_value='1982-04-09');need(self.v['route']=='verify_identity')
  self.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':False,'wrong_answers_left':3});need(self.v['state']['phase']=='phone')
  self.say('Six two zero five.',security_value='6205');need(self.v['route']=='verify_identity')
  self.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':True,'wrong_answers_left':3});need(self.v['route']=='get_account')
  self.receipt('get_account',{'ok':True,'products':[{'product_id':'local_product','type':'credit_card','card_last4':'8136','past_due':800.25,'minimum_payment':240.05,'days_late':12}]});need(self.v['route']=='talk');return self
 def consent(self): self.say('Yes, I confirm.','k=confirm;c=1;END');need(self.v['route']=='create_promise');return self

def commitment():
 c=Call().ready().say('I can pay the full amount today.','k=agree;c=1;END');need(c.v['state']['phase']=='readback');need(c.v['route']=='talk');c.consent();c.receipt('create_promise',{'ok':True,'promise_id':'local_receipt'});need(c.v['outcome']=='promise');need('text message' in c.v['dialogue_line'])
check('present commitment -> readback -> later consent -> current receipt',commitment)
def condition():
 c=Call().ready();c.say("Are you a robot? I'll take that date if",'k=proposal;c=0;u=amount;d=today;END')
 need(c.v['state']['pending']['missing']=='condition');need('condition' in c.v['dialogue_line']);need('digital assistant' in c.v['dialogue_line']);need(c.v['route']=='talk')
 c.say('Today.','k=proposal;c=1;d=today;END');need(c.v['state']['pending']['incomplete']);need(c.v['route']=='talk')
 c.say('I will pay today.','k=proposal;c=1;d=today;END');need(c.v['state']['phase']=='readback');need(not c.v['state']['pending'].get('incomplete'));c.consent()
check('mislabelled condition distinct; date alone blocked; new commitment supersedes',condition)
def amount():
 c=Call().ready().say('I can pay four hundred and... on Friday.','k=proposal;c=0;u=amount;d=this Friday;END');need(c.v['state']['pending']['missing']=='amount');need('Do you accept that amount?' in c.v['dialogue_line']);need('continue when' not in c.v['dialogue_line'])
 c.say('Friday.','k=proposal;c=1;d=this Friday;END');need(c.v['state']['pending']['incomplete']);need('amount' not in c.v['state']['pending'])
 c.say('Yes, I accept that amount.','k=agree;c=1;END');need(c.v['state']['phase']=='readback');need(c.v['route']=='talk');c.consent()
check('real amount fragment cannot borrow amount from later date; recovery acceptance',amount)
def malformed():
 c=Call().ready().say('I can pay the full amount today.','k=agree;c=1;END');c.say('Yes','k=confirm;c=1;');need(c.v['route']=='talk');need('Do you confirm?' in c.v['dialogue_line']);c.consent()
check('malformed confirmation retains terms and requires fresh spoken readback',malformed)
for utterance in ['Yes, I agree to marketing.','Yes, I consent to receiving promotional calls.','She said "yes".','Yes, but I do not agree.','I never agreed.','Yes, I agree to stop contact.','Yes, I confirm the address change.','Yes, if my salary arrives.']:
 def negative(u=utterance):
  c=Call().ready().say('I can pay the full amount today.','k=agree;c=1;END');c.say(u,'k=confirm;c=1;END');need(c.v['route']!='create_promise');need(not c.v['state']['recorded'])
 check('inconsistent confirm blocked: '+utterance,negative)
for raw in ['Ninth April one nine eight two.','My date of birth is ninth April one nine eight two.','Ninth April one nine eight two. Why are you calling?','Ninth April one nine eight two. How much do I owe?']:
 def sec(u=raw):
  c=Call().say('Speaking.',recipient_act='recipient');c.say(u,security_value='1982-04-09');need(c.v['route'] in ('verify_identity','security_admin'));need(c.v['security_answer']=='1982-04-09');need(not c.v['state']['verified']);need(c.v['state']['wrong']==0)
 check('digit year canonical compared: '+raw,sec)
for raw in ['My cousin was born ninth April one nine eight two.','He said "ninth April one nine eight two".','Not ninth April one nine eight two.','Ninth April one nine eight...','My partner date of birth is ninth April one nine eight two.']:
 def secneg(u=raw):
  c=Call().say('Speaking.',recipient_act='recipient');c.say(u,security_value='1982-04-09');need(c.v['route'] not in ('verify_identity','security_admin'));need(c.v['state']['wrong']==0)
 check('security subject/completion veto: '+raw,secneg)
def split():
 c=Call().say('Speaking.',recipient_act='recipient');c.say('Ninth April');need(c.v['route']=='talk');c.say('one nine eight two',security_value='1982-04-09');need(c.v['route']=='verify_identity');c.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':False});c.say('six two');need(c.v['route']=='talk');c.say('zero five',security_value='6205');need(c.v['route']=='verify_identity')
check('persistent split DOB and phone',split)
def wrong():
 c=Call().say('Speaking.',recipient_act='recipient');c.say('Ninth April one nine eight two',security_value='1982-04-09');c.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':False})
 c.say('6204',security_value='6204');c.receipt('verify_identity',{'ok':True,'verified':False,'all_verified':False,'wrong_answers_left':2});need(c.v['state']['wrong']==1)
 c.say('6205',security_value='6205');need(c.v['route']=='verify_identity');c.receipt('verify_identity',{'ok':True,'verified':True,'all_verified':True});need(c.v['route']=='get_account')
check('DOB pass, wrong phone, corrected phone uses separate bank receipts',wrong)
def retry():
 c=Call().ready().say('I can pay the full amount today.','k=agree;c=1;END').consent();c.receipt('create_promise',{},500,False);need(c.v['route']=='create_promise');need(c.v['state']['write_tries']==2);c.receipt('create_promise',{'ok':True,'promise_id':'retry_receipt'});need(c.v['outcome']=='promise')
check('HTTP500 no post-hook -> exactly one retry -> success',retry)
for present in (True,False):
 for raw in ['Yes.','Speaking.','Yes, this is Aylin.','Aylin here.','Ms Demir speaking.',"Yes, it's me. Busy day today, the traffic was awful.","I just said, that's me.","That's me, what is this about?",'Yes, Aylin Demir, are you a robot?']:
  def opening(u=raw,p=present):
   c=Call().say(u,recipient_act='recipient' if p else 'unknown');need(c.v['state']['phase']=='dob');need(not c.v['state']['verified'])
  check('recipient '+str(present)+' '+raw,opening)
 for raw in ['No, this is his wife.','Wrong number.',"She's not here right now.","I'm his son, he's at work."]:
  def openingneg(u=raw,p=present):
   c=Call().say(u,recipient_act='third_party' if p else 'unknown');need(c.v['state']['phase']!='dob');need(not c.v['state']['verified'])
  check('recipient exclusion '+str(present)+' '+raw,openingneg)
def ready_resume():
 c=Call().ready().say('I can pay the full amount today.','k=agree;c=1;END')
 c.say('I do not want to talk.','k=stop;c=1;END');need(c.v['state']['phase']=='paused')
 c.say('Yes, I am ready.','k=confirm;c=1;END');need(c.v['route']=='talk');need('Do you confirm?' in c.v['dialogue_line']);c.consent()
check('pause/readiness resumes complete readback without write',ready_resume)
def condition_misconfirm():
 c=Call().ready().say('I can pay the full amount today.','k=agree;c=1;END')
 c.say('Yes, if','k=confirm;c=1;END');need(c.v['state']['pending']['missing']=='condition')
 c.say('Yes.','k=confirm;c=1;END');need(c.v['route']=='talk');need(c.v['state']['pending']['incomplete']);need('condition' in c.v['dialogue_line'])
check('mislabelled complete confirm with actual condition blocks subsequent bare yes',condition_misconfirm)
def failure_budget():
 c=Call().ready().say('I can pay the full amount today.','k=agree;c=1;END').consent()
 c.receipt('create_promise',{'ok':False});need(c.v['route']=='create_promise');c.receipt('create_promise',{'ok':False});need(c.v['route']=='farewell');need(c.v['reason']=='service_error');need(not c.v['state']['recorded']);need('promise is recorded' not in c.v['dialogue_line'])
check('two application failures exhaust write retry without acknowledgement',failure_budget)
def stale():
 c=Call().ready();c.step(mode='verify',bank_status='200',bank_result={'ok':True,'verified':True,'all_verified':True});need(c.v['route'] not in ('get_account','verify_identity','create_promise'));need(c.v['mode']=='event');need(c.v['bank_result']=={})
check('stale completed identity signal cannot replay account dispatch',stale)
def ordinal():
 c=Call().ready();c.say('The fourteenth.','k=proposal;c=1;d=fourteenth;END');need(c.v['state']['phase']=='readback');need(c.v['route']=='talk');c.consent()
check('offered ordinal proposal without extra yes -> readback -> consent',ordinal)
def empty_recovery():
 c=Call().ready();c.say('I am ready.');need('Can you pay' in c.v['dialogue_line']);need('continue when' not in c.v['dialogue_line']);need(c.v['route']=='talk')
check('ready without terms restates actual active offer',empty_recovery)

# Literal producer examples, not synthetic hidden structures.
for line in w['nodes']['talk']['extraction_schema'][0]['description'].splitlines():
 if line.startswith('k='): check('literal '+line,lambda x=line: need(ns['decode'](x)))
for row in ['k=confirm;c=1;;END','k=confirm;c=1;END;','k=proposal;c=1;a=NaN;END','k=proposal;c=1;a=1e3;END','k=proposal;c=1;d=[Friday];END','k=confirm;c=1;c=1;END']:
 def invalid(x=row):
  try: ns['decode'](x)
  except ValueError: return
  assert False
 check('reject malformed '+row,invalid)
# OpenAPI and generated snippet checks.
api=json.load(open('inputs/openapi.json'))
for name,node in w['nodes'].items():
 for tool in node.get('pre_actions',[]):
  for key in ('pre_process_code','post_process_code'):
   if key in tool: compile(tool[key],name+key,'exec')
  if tool['function']['handler']=='__function__:api_call':
   prop=tool['function']['parameters']['properties'];schema=api['paths']['/'+name]['post']['requestBody']['content']['application/json']['schema'];body=prop['body'];assert set(schema['required'])<=set(body['required'])
   for key,val in body['properties'].items(): assert val['type']==schema['properties'][key]['type']
   assert tool['config']['maxRetries']==0
assert '{{' not in code and '}}' not in code
json.dump({'scope':'local generated graph, persistent state, actual hooks; no network or fresh hosted extractor','passed':sum(r['status']=='passed' for r in results),'failed':sum(r['status']=='failed' for r in results),'checks':results},open('local-check-results.json','w'),indent=2)
print('RESULT',len(results),sum(r['status']=='failed' for r in results),'failed')
