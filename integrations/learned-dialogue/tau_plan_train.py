"""One source-bound Tau official-TRAIN planning fit, max600s, no retries."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from safetensors.numpy import save_file
from threadpoolctl import threadpool_limits
from tau_plan_data import ROOT, PACKET, sha, encoded, write_new, verify, load_packet
from tau_plan_runtime import FEATURE_VERSION, source_text, windows, load_encoder, encode_specs, decode_head, stdlib_logits
from tau_plan_model import sigmoid,loss_gradient,metrics

HERE=Path(__file__).parent;PLAN=HERE/'tau_plan_plan.json';REPORT=ROOT/'analysis/tau-plan-model-experiment.json';MARKER=ROOT/'analysis/tau-plan-model-execution-once.json'
SEED=20261011


def checks():
    results=[]
    def ok(name,value):
        if not value:raise AssertionError(name)
        results.append(name)
    def reject(name,fn):
        try:fn()
        except (ValueError,TypeError):results.append(name);return
        raise AssertionError(name)
    spec={'instructions':{'reason_for_call':'Cancel the order, please.','known_info':'[REDACTED]'},'persona':None}
    ok('only_source_fields_enter_serializer','Cancel' in source_text(spec))
    reject('oracle_fields_rejected',lambda:source_text(dict(spec,reference_actions=['cancel_pending_order'])))
    reject('no_dict_stringification',lambda:source_text({'instructions':{'reason_for_call':{'labels':True}},'persona':None}))
    reject('no_empty_input',lambda:source_text({'instructions':{},'persona':None}))
    t='0123456789'*250;parts=windows(t);ok('windows_cover_every_source_character',all(any(start<=i<start+len(s) for start,s in zip(range(0,len(t),480),parts)) for i in range(len(t))))
    rng=np.random.default_rng(SEED);x=rng.normal(size=(5,384));w=rng.normal(0,.02,(384,2));b=np.zeros(2);y=np.array([[1,0],[0,1],[0,0],[1,0],[0,0]],float);m=np.ones_like(y);m[4]=0;gw=np.ones(5);q=np.array([1.4,2.]);den=(m*np.where(y>.5,q,1)).sum(0)
    loss,g,gb,stats=loss_gradient(w,b,x,y,m,gw,q,den);ok('finite_loss_gradient',np.isfinite(loss) and np.isfinite(g).all())
    for name,array,gradient,idx in [('W',w,g,(0,0)),('bias',b,gb,(0,))]:
        v=array[idx];epsilon=1e-5;array[idx]=v+epsilon;plus=loss_gradient(w,b,x,y,m,gw,q,den)[0];array[idx]=v-epsilon;minus=loss_gradient(w,b,x,y,m,gw,q,den)[0];array[idx]=v
        ok('finite_difference_'+name,abs((plus-minus)/(2*epsilon)-gradient[idx])<1e-7)
    changed=y.copy();changed[4]=1;ok('unknown_target_exact_zero_data_gradient',abs(loss_gradient(w,b,x,changed,m,gw,q,den)[0]-loss)<1e-12)
    s=metrics(np.array([[3,-3],[-3,3]]),np.array([[1,0],[0,1]]),np.ones((2,2)),['a','b']);ok('scorer_exact_reference_tp_fp',s['micro_F1']==1 and s['known_elements']==4)
    return {'passed':len(results),'checks':results,'optimizer_steps':0}


def prepare():
    if PLAN.exists():raise ValueError('Write-once plan already exists')
    rows,labels,y,m,ix,pins,integrity=load_packet()
    oldhead=ROOT/'integrations/learned-dialogue/day2_pretrained_head.json';loader=ROOT/'integrations/learned-dialogue/day2_pretrained_runtime.py'
    if sha(oldhead)!='fb3d2758994ea47c2d7e88bafc2deab552a506dd09a39780fda85f2c6036cd5e' or sha(loader)!='355e946677aa0a08b35d3714802b4ba645a0405f7d2f1910d6b5b6f26f37e2db':raise ValueError('Encoder provenance changed')
    record=json.loads(oldhead.read_text(encoding='utf-8'))['encoder'];directory=ROOT/record['local_directory']
    ep={str((directory/name).relative_to(ROOT)).replace('\\','/'):v['sha256'] for name,v in record['files'].items()};ep[str(loader.relative_to(ROOT)).replace('\\','/')]=sha(loader);verify(ep)
    freeze=ROOT/'integrations/learned-dialogue/repayment_freeze.json'
    if sha(freeze)!='7624f5808db12624adc75b6a688d14975ed051d8ce863cd7e965326621157804':raise ValueError('Repayment freeze changed')
    f=json.loads(freeze.read_text(encoding='utf-8'));old=dict(f['source_sha256']);old.update(f['artifacts_sha256']);old['integrations/learned-dialogue/repayment_freeze.json']=sha(freeze);verify(old)
    with threadpool_limits(limits=2):test=checks()
    plan={'status':'READY_EXACT_SOURCE_AUTHORIZED_CPU_FIT','code_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [HERE/('tau_plan_'+n+'.py') for n in ['runtime','data','model','train']]},'input_sha256':pins,'encoder_sha256':ep,'encoder_directory':record['local_directory'],'encoder_loader_sha256':sha(loader),'encoder_revision':record['revision'],'old_artifact_sha256':old,'labels':labels,'integrity':integrity,'FIT_record_ids':[rows[i]['id'] for i in ix['FIT']],'CAL_record_ids':[rows[i]['id'] for i in ix['CAL']],'DIAG_record_ids':[rows[i]['id'] for i in ix['DIAG']],'partition_method':'SHA256(tau-plan-group-split-v1:+group_root)%10:0..6FIT,7..8CAL,9DIAG, before vocabulary/support selection','features':FEATURE_VERSION,'objective':'literal operation inclusion in complete nonempty serialized publisher annotation;7 empty/absent rows allUNKNOWN; not all possible valid tools','fit':{'epochs':200,'Adam_lr':.01,'batch':32,'seed':SEED,'class_weights':'FIT-only min(5,max(1,sqrt(group-negative/group-positive)))','untrained':'no FIT known positive or negative','mean_parameter_L2':.01},'calibration':'CAL only threshold grid[.5,.6,.7,.8,.9], empirical>=.90 precision and>=3 accepted with both directions; else unavailable. No independent risk claim.','diagnostic':'DIAG consists solely of officialTRAIN internal groups. Once after head/calibrator freeze, not officialTEST or new qualification.','wall_seconds':600,'CPU_threads':2,'GPU_USD':0,'encoder_gradient_updates':0,'tests':test,'authority':'NONE; all financial masksUNKNOWN; source specs NOT observed conversation','license':{'corpus':'MIT','MiniLM':'Apache-2.0'},'source_commit':'4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699'}
    write_new(PLAN,plan);write_new(ROOT/'analysis/tau-plan-model-plan.json',dict(plan,plan_sha256=sha(PLAN),command='"'+sys.executable+'" -B integrations/learned-dialogue/tau_plan_train.py --run --approved-plan-sha '+sha(PLAN)))
    print(json.dumps({'status':plan['status'],'plan_sha256':sha(PLAN),'classes_FIT_only':len(labels),'integrity':integrity,'tests':test},ensure_ascii=True),flush=True)


def verified_plan(digest):
    if sha(PLAN)!=digest:raise ValueError('Approved plan digest mismatch')
    p=json.loads(PLAN.read_text(encoding='utf-8'))
    for key in ['code_sha256','input_sha256','encoder_sha256','old_artifact_sha256']:verify(p[key])
    return p


def worker(digest):
    start=time.monotonic();plan=verified_plan(digest);rows,labels,y,m,ix,pins,integrity=load_packet();deadline=start+570
    with threadpool_limits(limits=2):
        encoder=load_encoder(ROOT/plan['encoder_directory'],plan['encoder_loader_sha256']);emb,windows_report=encode_specs(encoder,[r['generator_spec'] for r in rows],deadline)
        cache=HERE/'tau_plan_embeddings.safetensors';save_file({'embeddings':emb},str(cache),metadata={'specs_sha256':pins['research/customer-benchmark/tau-train/train-scenario-specs.jsonl'],'features':FEATURE_VERSION,'encoder_frozen':'true'})
        fi=ix['FIT'];counts=Counter(rows[i]['group_root'] for i in fi);gw=np.asarray([len(fi)/(len(counts)*counts[rows[i]['group_root']]) for i in fi],np.float32)
        fy,fm=y[fi],m[fi];positive=(fy*fm*gw[:,None]).sum(0);negative=((1-fy)*fm*gw[:,None]).sum(0);trained=(positive>0)&(negative>0);q=np.minimum(5,np.maximum(1,np.sqrt(negative/np.maximum(positive,1e-12))));den=(fm*gw[:,None]*np.where(fy>.5,q,1)).sum(0);den[~trained]=0
        w=np.zeros((384,len(labels)),np.float32);b=np.zeros(len(labels),np.float32);mw=np.zeros_like(w);vw=np.zeros_like(w);mb=np.zeros_like(b);vb=np.zeros_like(b);step=0;rng=np.random.default_rng(SEED);history=[];fit_start=time.monotonic()
        initial=metrics(emb[fi]@w+b,fy,fm,labels)
        for epoch in range(200):
            order=rng.permutation(len(fi))
            for off in range(0,len(fi),32):
                if time.monotonic()>deadline:raise TimeoutError('Bounded CPU cap, no retry')
                bi=order[off:off+32];ratio=len(bi)/len(fi);loss,g,gb,stats=loss_gradient(w,b,emb[fi[bi]],fy[bi],fm[bi],gw[bi],q,den*ratio);step+=1
                for param,grad,mean,var in [(w,g,mw,vw),(b,gb,mb,vb)]:
                    mean*=.9;mean+=.1*grad;var*=.999;var+=.001*grad**2;param-=.01*(mean/(1-.9**step))/(np.sqrt(var/(1-.999**step))+1e-8)
                if not np.isfinite(w).all() or not np.isfinite(b).all():raise ValueError('Nonfinite fit')
            if epoch in [0,99,199]:
                loss,_,_,stats=loss_gradient(w,b,emb[fi],fy,fm,gw,q,den);history.append({'epoch':epoch+1,'objective':loss,**stats});print(json.dumps(history[-1]),flush=True)
        fit_seconds=time.monotonic()-fit_start
        head={'schema':'tau_plan_reference_inclusion.v1','features':FEATURE_VERSION,'labels':labels,'trained_head_mask':trained.tolist(),'parameters':{n:base64.b64encode(v.astype('<f4').tobytes()).decode() for n,v in [('W',w),('b',b)]},'bank_authority':False,'observed_utterance':False,'qualified':False,'plan_sha256':digest}
        blob=encoded(head);headpath=HERE/'tau_plan_head.json'
        with headpath.open('xb') as out:out.write(blob)
        state=HERE/'tau_plan_state.safetensors';save_file({'W':w,'b':b},str(state),metadata={'FIT_only':'true','objective':'publisher_reference_list_inclusion'})
        write_new(HERE/'tau_plan_weights.freeze.json',{'head_sha256':sha(headpath),'state_sha256':sha(state),'status':'FROZEN_BEFORE_CAL'})
        decoded=decode_head(blob,sha(headpath));native=emb@w+b;export=np.asarray([stdlib_logits(decoded,v) for v in emb]);error=float(np.abs(native-export).max());flips=int(((native>=0)!=(export>=0)).sum())
        if error>1e-4 or flips:raise ValueError('Full native/export parity failed')
        threshold=np.full(len(labels),1.000001);records={};ci=ix['CAL']
        for j,label in enumerate(labels):
            known=m[ci,j]>0;yy=y[ci,j][known];pp=sigmoid(export[ci,j][known]);available=bool(trained[j] and (yy>.5).any() and (yy<.5).any());grid=[]
            for t in [.5,.6,.7,.8,.9]:
                accepted=pp>=t;n=int(accepted.sum());precision=float(yy[accepted].mean()) if n else None;grid.append({'threshold':t,'accepted':n,'precision':precision})
            valid=[r for r in grid if available and r['accepted']>=3 and r['precision']>=.90]
            if valid:threshold[j]=max(valid,key=lambda r:(r['accepted'],-r['threshold']))['threshold']
            records[label]={'FIT_positive':float(positive[j]),'FIT_negative':float(negative[j]),'CAL_positive':int(yy.sum()),'CAL_known':len(yy),'selective_available':available,'grid':grid}
        calpath=HERE/'tau_plan_calibrator.json';write_new(calpath,{'threshold':threshold.tolist(),'records':records,'bank_authority':False,'qualified':False})
        freeze=HERE/'tau_plan_freeze.json';write_new(freeze,{'plan_sha256':digest,'head_sha256':sha(headpath),'state_sha256':sha(state),'calibrator_sha256':sha(calpath),'source_sha256':plan['code_sha256'],'status':'FROZEN_BEFORE_ONCE_INTERNAL_TRAIN_DIAG'})
        di=ix['DIAG'];raw=metrics(export[di],y[di],m[di],labels);selective=metrics(export[di],y[di],m[di],labels,threshold)
        result={'status':'COMPLETED_ACTUAL_OFFICIAL_TRAIN_SOURCE_PLANNING_FIT','plan_sha256':digest,'freeze_sha256':sha(freeze),'head_sha256':sha(headpath),'head_bytes':len(blob),'head_plus_runtime_bytes':len(blob)+(HERE/'tau_plan_runtime.py').stat().st_size,'FIT_initial':initial,'FIT_final':metrics(export[fi],fy,fm,labels),'CAL_raw':metrics(export[ci],y[ci],m[ci],labels),'DIAG_raw':raw,'DIAG_selective':selective,'support_and_calibration':records,'integrity':integrity,'features':windows_report,'fit_seconds':fit_seconds,'wall_seconds':time.monotonic()-start,'epochs':200,'optimizer_steps':step,'loss_trajectory':history,'full_native_stdlib_parity':{'rows':len(rows),'head_elements':int(export.size),'max_logit_error':error,'decision_flips':flips},'encoder_gradient_updates':0,'official_TEST_loaded':False,'bank_authority':False,'financial_masks':'UNKNOWN','source_OOD':'UNKNOWN; internal officialTRAIN groups only, no conversation or OOD labels','limitations':['Reference annotations are one publisher-listed plan, not exhaustive valid tool or permissions gold.','Seven empty/missing-indistinguishable rows masked, not negatives.','Only103 source specifications; no observed user speech, generated traces, ASR/Freya or fresh risk qualification.','Group closure heuristic and previous Tau reference exposure disclosed; no independent semantic/OOD proof.','701documents/716policychunks not used in this task fit.'],'license':'MIT','source_commit':plan['source_commit'],'tests':plan['tests']}
        if result['head_plus_runtime_bytes']>500000:raise ValueError('Head size limit')
        for key in ['code_sha256','input_sha256','encoder_sha256','old_artifact_sha256']:verify(plan[key])
        write_new(REPORT,result);(ROOT/'analysis/tau-plan-model-experiment.txt').write_text(json.dumps(result,indent=2,ensure_ascii=True)+'\n',encoding='utf-8');print(json.dumps({'status':result['status'],'DIAG_macro_F1':raw['macro_F1'],'wall_seconds':result['wall_seconds'],'head_bytes':len(blob)}),flush=True)


def launch(digest):
    verified_plan(digest);write_new(MARKER,{'approved_plan_sha256':digest,'basis':'User explicitly authorizes actual targeted CPU sourceplanning fit','retries':0});start=time.monotonic()
    try:
        proc=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--approved-plan-sha',digest],cwd=str(ROOT),timeout=600);status={'exit_code':proc.returncode,'wall_seconds':time.monotonic()-start}
    except subprocess.TimeoutExpired:status={'status':'child_killed_waited_timeout','wall_seconds':time.monotonic()-start}
    write_new(ROOT/'analysis/tau-plan-model-watchdog.json',status)
    if status.get('exit_code')!=0:
        if not REPORT.exists():write_new(REPORT,{'status':'FAILED_NO_RETRY','watchdog':status,'plan_sha256':digest})
        raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--run',action='store_true');g.add_argument('--worker',action='store_true');parser.add_argument('--approved-plan-sha');args=parser.parse_args()
    if args.prepare:prepare()
    elif not args.approved_plan_sha:parser.error('Exact plan hash required')
    elif args.worker:worker(args.approved_plan_sha)
    else:launch(args.approved_plan_sha)
