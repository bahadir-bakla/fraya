"""Read-only export/source CPU audit. No fitting, platform, network or labels written."""
import ast,copy,hashlib,importlib.util,json,math,re,sys,time
from collections import Counter,defaultdict
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'integrations/learned-dialogue';sys.path.insert(0,str(BASE))
import day2_public_model_v2 as model,day2_public_train_v2 as train,day2_public_eval_v2 as ev
import numpy as np
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def wilson(k,n):
    z=1.959963984540054;p=k/n;a=1+z*z/n;b=p+z*z/(2*n);d=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n));return [(b-d)/a,(b+d)/a]
def main():
    start=time.monotonic();out=ROOT/'analysis/day2-opus-training-engine-review-witnesses.json'
    if out.exists():raise RuntimeError('Witness file exists; no rerun')
    metrics=read(BASE/'day2_public_metrics_v2.json');plan=read(BASE/'day2_public_plan_v2.json');freeze=read(BASE/'day2_public_freeze_v2.json');grant=read(ROOT/'analysis/day2-parent-public-cpu-authorization-v2.json')
    paths=set(metrics['source_sha256'])|set(metrics['input_sha256'])|set(freeze['models_sha256'])|set(freeze['artifacts_sha256'])|{str(p.relative_to(ROOT)).replace('\\','/') for p in [BASE/'day2_public_plan_v2.json',BASE/'day2_public_freeze_v2.json',BASE/'day2_public_pre_eval_freeze_v2.json',ROOT/'analysis/day2-parent-public-cpu-authorization-v2.json',ROOT/'analysis/day2-public-data-independent-review.json',ROOT/'analysis/day2-a-next6-source-review.json',ROOT/'analysis/day2-a-next6-witnesses.json',ROOT/'competition/runs/20261011-120033-ec0e86/codex-stress-a-next.workflow.json']}
    before={p:sha(ROOT/p) for p in paths};checks=[]
    def check(name,ok,actual=None):checks.append({'id':name,'pass':bool(ok),'actual':actual})
    for kind in ('source_sha256','input_sha256','models_sha256','artifacts_sha256'):
        for p,h in freeze.get(kind,{}).items():check('freeze/'+p,before[p]==h)
    ph=sha(BASE/'day2_public_plan_v2.json')
    check('grant/plan',ph==grant['plan_sha256']==metrics['approved_plan_sha256']==freeze['approved_plan_sha256'])
    check('grant/code-input',grant['source_sha256']==plan['source_sha256'] and grant['input_sha256']==plan['input_sha256'])
    rows,labels=train.load(plan['config'])
    check('row-mask-exact-reproduction',[{k:v for k,v in r.items() if k!='text'} for r in rows]==plan['row_mask_partitions'])
    groups=defaultdict(set)
    for r in rows:groups[r['canonical_group']].add(r['partition'])
    check('assigned-group-isolation',all(len(s)==1 for s in groups.values()),{'groups':len(groups),'rows':len(rows)})
    partitions={s:{'rows':sum(r['observed_mask'] and r['partition']==s for r in rows),'groups':len({r['canonical_group'] for r in rows if r['observed_mask'] and r['partition']==s}),'min_class_rows':min(Counter(r['publisher_label'] for r in rows if r['observed_mask'] and r['partition']==s).values())} for s in ('fit','calibration','internal_publisher_TRAIN_eval')}
    cal=[r for r in rows if r['partition']=='calibration' and r['observed_mask']]
    halves=[{r['canonical_group'] for r in cal if int(hashlib.sha256(r['canonical_group'].encode()).hexdigest()[:8],16)%2==i} for i in (0,1)]
    check('CAL-disjoint-parity',not halves[0]&halves[1] and [len(x) for x in halves]==[496,497],{'groups':[len(x) for x in halves]})
    # Independent wider contraction canonicalization; report record IDs, not raw corpus text.
    contraction={"isn't":"is not","doesn't":"does not","haven't":"have not","can't":"can not","don't":"do not","didn't":"did not","i'm":"i am","i've":"i have","it's":"it is"}
    aliases=defaultdict(list)
    for r in rows:
        t=r['text'].casefold().replace('’',"'")
        for a,b in contraction.items():t=re.sub(r'\b'+re.escape(a)+r'\b',b,t)
        t=' '.join(re.findall(r'\w+',t));aliases[t].append(r)
    links=[[{'id':r['id'],'partition':r['partition'],'publisher_label':r['publisher_label']} for r in v] for v in aliases.values() if len({r['partition'] for r in v})>1]
    check('known-contraction-links-reproduced',len(links)==2,links)
    source_tests=ev.source_tests();check('encoder-controls',source_tests['passed']==source_tests['executed'],source_tests)
    evaluation=[r for r in rows if r['partition']=='internal_publisher_TRAIN_eval' and r['observed_mask']]
    sample=sorted(rows,key=lambda r:r['id'])[::max(1,len(rows)//96)][:96]
    results={};decisions={};parity=0;max_error=0;authority=0
    canaries=['I paid it today.','I made the hotel payment yesterday.', 'My sister said yes.', 'He said “yes”.','I will make the payment tomorrow.',"I've already processed the payment through the app this morning.",'My phone ends in 0742.','My phone ends in 9876.','My password is working again.','Yes, but change the amount.']
    for name,info in metrics['models'].items():
        bundle=read(ROOT/info['path']);params={k:np.asarray(v,dtype=float) for k,v in bundle['parameters'].items()}
        if bundle['architecture']=='sparse_softmax':params['weights']=params['weights_q']*params['weight_scale']
        records=[];predicted=[]
        for r in evaluation:
            p=ev.native_scores(r['text'],bundle,params);guess=max(range(77),key=lambda i:p[i]);predicted.append(guess)
            records.append({'group':r['canonical_group'],'label_index':labels.index(r['publisher_label']),'probabilities':p})
        actual=ev.metrics(records,labels,bundle['calibration']['threshold']);reported=info['internal_publisher_TRAIN_eval']
        for k in actual:check(name+'/EVAL/'+k,actual[k]==reported[k] or isinstance(actual[k],float) and isinstance(reported[k],float) and abs(actual[k]-reported[k])<1e-12)
        proposed=actual['source_intent_proposed'];correct=round(actual['source_intent_proposal_precision']*proposed)
        results[name]={'recomputed_EVAL':actual,'correct_rows':round(actual['accuracy']*len(evaluation)),'proposal_correct_rows':correct,'proposal_precision_Wilson95_diagnostic_only':wilson(correct,proposed),'threshold':bundle['calibration']['threshold'],'temperature':bundle['calibration']['temperature'],'complete_runtime_bytes':(ROOT/info['path']).stat().st_size+(BASE/'day2_public_model_v2.py').stat().st_size,'canaries':[]}
        decisions[name]=predicted
        t=bundle['calibration'];min_temp=min(t['temperature_grid_results'],key=lambda a:(a['CAL_fit_CE'],a['temperature']))['temperature'];eligible=[(a['proposed'],a['threshold']) for a in t['threshold_select_results'] if a['proposed']>=30 and a['precision'] is not None and a['precision']>=.9]
        check(name+'/CAL-frozen-choice',t['temperature']==min_temp and t['threshold']==(max(eligible)[1] if eligible else 1.1))
        for r in sample:
            p=model.score(r['text'],bundle);n=ev.native_scores(r['text'],bundle,params);error=max(abs(a-b) for a,b in zip(p,n));max_error=max(max_error,error);parity+=1
            check(name+'/export-parity/'+r['id'],error<1e-10)
        for text in canaries+['', 'x'*2049, {'schema':'not text'}]:
            p=model.predict(text,bundle);authority+=1;check(name+'/authority/'+str(authority),p['status']=='bank_abstain' and p['qualified'] is False and p['acceptance'] is False and p['authority']=='none')
            if isinstance(text,str) and len(text)<100:results[name]['canaries'].append({'authored_text':text,'output':p})
        check(name+'/numeric-identity-collapse',model.score('My phone ends in 0742.',bundle)==model.score('My phone ends in 9876.',bundle))
        check(name+'/no-authoritative-bundle',all(model.predict(t,bundle)['acceptance'] is False for t in canaries))
    y=[labels.index(r['publisher_label']) for r in evaluation];gnn=decisions['gnn'];none=decisions['no_edges'];b=sum(a==z and c!=z for a,c,z in zip(gnn,none,y));c=sum(a!=z and d==z for a,d,z in zip(gnn,none,y));n=b+c
    paired={'gnn_only_correct':b,'no_edges_only_correct':c,'net_rows':b-c,'discordant':n,'exact_paired_binomial_p_diagnostic':min(1,2*sum(math.comb(n,j) for j in range(min(b,c)+1))/2**n) if n else 1,'qualification':False,'one_fit_and_known_paraphrase_links':True}
    procpath=ROOT/'research/customer-benchmark/day2-training-data/processor-v1.py';spec=importlib.util.spec_from_file_location('readonly_scrub',procpath);proc=importlib.util.module_from_spec(spec);spec.loader.exec_module(proc)
    scrub=[]
    for text in ['My password is working again.','My PIN is required to unlock my card.','I paid 100 yesterday.','I paid 900 yesterday.']:
        value,counts=proc.scrub(text);scrub.append({'authored_text':text,'scrubbed':value,'counts':counts})
    check('redaction-numeric-collapse',scrub[2]['scrubbed']==scrub[3]['scrubbed'])
    check('redaction-status-clause-loss-reproduced','required' not in scrub[1]['scrubbed'] and 'unlock' not in scrub[1]['scrubbed'])
    special=[{'id':r['id'],'publisher_label':r['publisher_label'],'partition':r['partition'],'observed_mask':r['observed_mask'],'word_count':len(r['text'].split()),'redaction_placeholder_count':r['text'].count('[REDACTED_'),'text_sha256':hashlib.sha256(r['text'].encode()).hexdigest()} for r in rows if r['id']=='banking77-train:01708']
    # Actual frozen A-next6 pure source predicates, no store/API execution claim.
    export=read(ROOT/'competition/runs/20261011-120033-ec0e86/codex-stress-a-next.workflow.json');source=export['workflow']['nodes']['dispatch']['pre_actions'][0]['function']['parameters']['properties']['code']['default'];tree=ast.parse(source);tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.FunctionDef)) or isinstance(n,ast.Assign) and all(isinstance(t,ast.Name) and t.id in ('HOLIDAYS','KINDS') for t in n.targets)];env={};exec(compile(tree,'frozen_A_next6_pure_predicates','exec'),env,env)
    predicate=[]
    state={'product':{'type':'credit_card','card_last4':'8841'}}
    for text,expected,classification in [('I have already processed the payment through the app this morning.',True,'conforming_positive'),("I've already processed the payment through the app this morning.",True,'conforming_positive'),('I made the payment in 2024.',False,'forced_inconsistent_paid_row'),('I processed the payment tomorrow.',False,'forced_inconsistent_paid_row'),('I made the hotel payment yesterday.',False,'forced_inconsistent_paid_row'),('I paid it today, but I did not actually pay this overdue amount.',False,'forced_inconsistent_paid_row'),('I paid my credit card ending 7736 today.',False,'forced_inconsistent_paid_row')]:
        observed=env['disposition_source'](text,'paid',state);predicate.append({'authored_text':text,'kind':'paid','expected':expected,'actual':observed,'expectation_met':observed==expected,'classification':classification})
    after={p:sha(ROOT/p) for p in paths};check('protected-source-stability',before==after)
    report={'status':'CLOSED_FROZEN_INDEPENDENT_CODEX_CPU_WITNESSES','started_task_utc':'2026-10-11T09:15:20Z','finished_utc':datetime.now(timezone.utc).isoformat(),'wall_seconds':round(time.monotonic()-start,3),'checks':checks,'check_count':len(checks),'passed':sum(c['pass'] for c in checks),'failed':sum(not c['pass'] for c in checks),'source_manifest_before':before,'source_manifest_after':after,'source_hashes_unchanged':before==after,'partitions':partitions,'models':results,'paired_ablation':paired,'contraction_cross_split_links':links,'independent_export_numpy_comparisons':parity,'independent_export_numpy_max_error':max_error,'full_precision_training_parity':'Producer-reported768comparisons; original full-precision arrays not retained; NOT independently reproduced and no refit','bank_abstention_canary_calls':authority,'scrub_semantic_loss_witnesses':scrub,'known_redaction_row_metadata':special,'A_next6_paid_predicates':predicate,'A_next6_paid_predicate_expectation_failures':sum(not x['expectation_met'] for x in predicate),'fits':0,'hosted_calls':0,'bank_calls':0,'GPU':0,'native_inference_claim':False,'mask_warning':'Observed mask tests type/length, not recoverable label semantics. Source-intent predictions have no bank authority.'}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8');out.with_suffix('.txt').write_text('Independent read-only CPU evidence. No fit/hosted calls.\n'+json.dumps({k:v for k,v in report.items() if k not in ('checks','source_manifest_before','source_manifest_after','models')},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'checks':report['check_count'],'passed':report['passed'],'failed':report['failed'],'parity':parity,'paired':paired,'paid_predicate_failures':report['A_next6_paid_predicate_expectation_failures'],'wall_seconds':report['wall_seconds']}))
if __name__=='__main__':main()
