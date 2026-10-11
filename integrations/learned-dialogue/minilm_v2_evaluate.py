"""Once-only frozen-model comparison and labelled diagnostic ablations."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--output',required=True)
    p.add_argument('--worker',choices=['v1','v2']);a=p.parse_args();out=Path(a.output)
    if out.exists():raise ValueError('Do not overwrite evaluation evidence')
    plan=json.loads((ROOT/'analysis/minilm-v2-plan.json').read_text(encoding='utf8'))
    freshpath=ROOT/plan['fresh_EVAL_path']
    if sha(freshpath)!=plan['fresh_EVAL_sha256']:raise ValueError('Completed independent EVAL seal changed')
    if sha(HERE/'minilm_ft_v1/model/manifest.json')!=plan['base_manifest_sha256']:raise ValueError('V1 comparison anchor changed')
    modelpath=Path(a.model).resolve(strict=True)
    if not a.worker:
        fit=json.loads((modelpath/'training.json').read_text(encoding='utf8'))
        if fit['status']!='COMPLETED' or fit['completed_epochs']!=2 or fit['TRAIN_rows']!=168821:raise ValueError('Full frozen fit required before opening independent EVAL')
        out.mkdir(parents=True)
        paths={'v1':HERE/'minilm_ft_v1/model','v2':modelpath}
        env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN','SECRET','PASSWORD','API_KEY','TEAM_KEY'))}
        started=time.monotonic()
        for version,path in paths.items():
            subprocess.run([sys.executable,'-X','utf8','-B',str(__file__),'--worker',version,'--model',str(path),'--output',str(out/(version+'.json'))],env=env,check=True,timeout=900)
        arms={v:json.loads((out/(v+'.json')).read_text(encoding='utf8')) for v in paths}
        gains={'fresh_macro_F1':arms['v2']['fresh']['raw']['domain_macro_F1']-arms['v1']['fresh']['raw']['domain_macro_F1'],
               'fresh_joint_correct_rows':arms['v2']['fresh']['joint_raw']['correct']-arms['v1']['fresh']['joint_raw']['correct'],
               'reused384_macro_change':arms['v2']['reused384']['raw']['domain_macro_F1']-arms['v1']['reused384']['raw']['domain_macro_F1']}
        gate=plan['default_release_gate']
        enabled=gains['fresh_macro_F1']>=gate['fresh_macro_F1_gain_min'] and gains['fresh_joint_correct_rows']>=gate['fresh_joint_known_correct_gain_min_rows'] and gains['reused384_macro_change']>=-gate['reused384_domain_macro_regression_max']
        result={'status':'ACTUAL_FROZEN_ONCE_COMPARISON_COMPLETE','arms':arms,'gains':gains,'predefined_gate':gate,'default_enabled':enabled,'seconds':time.monotonic()-started,
                'fresh_EVAL_sha256':sha(freshpath),'v2_manifest_sha256':sha(modelpath/'manifest.json'),
                'scope':'Independent authored synthetic cohort; reused32/384 are regression diagnostics. Not IID/human policy gold, financial authority, Freya or ASR qualification.',
                'bank_authority':False,'thresholds_chosen_on':'CAL only before EVAL','cloud_launches':0}
        (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(json.dumps({'status':result['status'],'gains':gains,'default_enabled':enabled}),flush=True)
        return
    runtime=HERE if a.worker=='v1' else HERE/'minilm_ft_v2/runtime'
    sys.path.insert(0,str(runtime))
    import numpy as np
    import torch
    from minilm_ft_eval import load_model
    from minilm_ft_core import read_rows,metrics,targets,DOMAIN
    torch.set_num_threads(4);device='cuda' if torch.cuda.is_available() else 'cpu';started=time.monotonic();deadline=started+840
    fresh=json.loads(freshpath.read_text(encoding='utf8'))
    if not isinstance(fresh,list):raise ValueError('Expected sealed flat independent probe list')
    if len(fresh)!=96 or any(r['split']!='EVAL' for r in fresh):raise ValueError('Independent cohort schema/count')
    for r in fresh:targets(r)
    reused=read_rows(ROOT/'research/customer-benchmark/minilm-finetune-v1/eval.jsonl');reused=[r for r in reused if r['source']=='new-authored']
    old=json.loads((ROOT/'analysis/minilm-ft-adversarial-probes.json').read_text(encoding='utf8'))
    if len(reused)!=384 or len(old)!=32:raise ValueError('Frozen diagnostic cohorts')
    model,manifest=load_model(modelpath,device)
    def measure(rows,values):
        known=np.asarray([targets(r)[1][:7] for r in rows],dtype=bool);y=np.asarray([targets(r)[0][:7] for r in rows])
        def joint(th):
            pred=(1/(1+np.exp(-np.clip(values[:,:7],-50,50))))>=np.asarray(th)
            keep=known.any(1);correct=((pred==y)|~known).all(1)&keep
            return {'correct':int(correct.sum()),'denominator':int(keep.sum())}
        return {'raw':metrics(values,rows),'selected':metrics(values,rows,manifest['thresholds']),
                'joint_raw':joint([.5]*7),'joint_selected':joint(manifest['thresholds'][:7])}
    combined=fresh+reused+old
    logits=model.predict(combined,16,deadline=deadline)
    result={'version':a.worker,'manifest_sha256':sha(modelpath/'manifest.json'),'thresholds':manifest['thresholds'],'device':device,
            'fresh':measure(fresh,logits[:96]),'reused384':measure(reused,logits[96:480]),'reused32':measure(old,logits[480:]),
            'fresh_groups':len({r['group'] for r in fresh}),'bank_authority':False,'fresh_EVAL_sha256':sha(freshpath)}
    subsets={'long_over350words':[i for i,r in enumerate(fresh) if len(r['input']['current_utterance'].split())>350],
             'prior_own_turn':[i for i,r in enumerate(fresh) if any(t['speaker']=='USER' for t in r['input']['previous_utterances'])]}
    for label in ['tr','en']:
        ids=[i for i,r in enumerate(fresh) if r.get('language')==label]
        if ids:subsets[label]=ids
    result['fresh_subsets']={key:measure([fresh[i] for i in ids],logits[ids]) for key,ids in subsets.items() if ids}
    probabilities=1/(1+np.exp(-np.clip(logits[:96],-50,50)))
    result['fresh_predictions']=[{'id':r['id'],'group':r['group'],'probabilities':[float(v) for v in probabilities[i]],
       'raw_wrong_heads':[name for j,name in enumerate(DOMAIN) if r['domain_mask'][j] and bool(probabilities[i,j]>=.5)!=bool(r['domain_labels'][j])]} for i,r in enumerate(fresh)]
    if a.worker=='v2':
        for name,kwargs in [('no_tail',{'no_tail':True}),('no_context',{'no_context':True})]:
            vals=model.predict(fresh,16,deadline=deadline,**kwargs);result['fresh_'+name+'_ablation']=measure(fresh,vals)
    result['seconds']=time.monotonic()-started
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'version':a.worker,'fresh_macro_F1':result['fresh']['raw']['domain_macro_F1'],'joint':result['fresh']['joint_raw'],'seconds':result['seconds']}),flush=True)

if __name__=='__main__':main()
