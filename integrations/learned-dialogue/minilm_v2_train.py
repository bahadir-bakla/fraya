"""Local bounded V2 continuation, full retained TRAIN plus targeted augmentation."""
import argparse
import hashlib
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'minilm_ft_v2/runtime'))
from minilm_ft_core import Model,read_rows,targets,observed_parts,metrics,DOMAIN,AUX


def main():
    import numpy as np
    import torch
    from safetensors.torch import load_file,save_file
    p=argparse.ArgumentParser();p.add_argument('--augmentation',required=True);p.add_argument('--base',required=True);p.add_argument('--output',required=True);p.add_argument('--epochs',type=int,default=2);p.add_argument('--seconds',type=int,default=2400);p.add_argument('--batch-size',type=int,default=32);a=p.parse_args()
    if not 1<=a.epochs<=3 or not 1<=a.seconds<=2400 or not 1<=a.batch_size<=32:raise ValueError('Bounded training arguments')
    out=Path(a.output)
    if out.exists():raise ValueError('Refuse overwrite of training/model evidence')
    out.mkdir(parents=True);started=time.monotonic();deadline=started+a.seconds;torch.set_num_threads(4)
    if not torch.cuda.is_available():raise ValueError('Local CUDA GPU required; no implicit cloud or CPU launch')
    device='cuda';torch.manual_seed(20261012);random.seed(20261012);np.random.seed(20261012)
    legacy=HERE.parents[1]/'research/customer-benchmark/minilm-finetune-v1';augment=Path(a.augmentation).resolve(strict=True)
    files=[legacy/'train.jsonl',legacy/'cal.jsonl',augment/'train.jsonl',augment/'cal.jsonl']
    expected={}
    for packet in (legacy,augment):
        for item in json.loads((packet/'freeze.json').read_text(encoding='utf8'))['files']:
            path=HERE.parents[1]/item['path']
            if path in files:expected[path]=item['sha256']
    if set(expected)!=set(files):raise ValueError('Every TRAIN/CAL input requires a frozen source pin')
    for path,digest in expected.items():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Frozen input changed')
    legacytrain=read_rows(files[0]);newtrain=read_rows(files[2]);train=legacytrain+newtrain;cal=read_rows(files[1])+read_rows(files[3])
    if len(legacytrain)!=156341:raise ValueError('All old training rows required')
    groups={r['group'] for r in train}
    if groups&{r['group'] for r in cal}:raise ValueError('TRAIN/CAL group collision')
    if len({r['id'] for r in train+cal})!=len(train)+len(cal):raise ValueError('Duplicate example IDs')
    for part,tag in [(train,'TRAIN'),(cal,'CAL')]:
        for row in part:
            if row['split']!=tag:raise ValueError('Split admission')
            targets(row);observed_parts(row)
    base=Path(a.base);manifest=json.loads((base/'manifest.json').read_text())
    for name,digest in manifest['files'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest()!=digest:raise ValueError('Warm-start source pin '+name)
    model=Model(base/'encoder',device,True);oldhead=load_file(str(base/'head.safetensors'))
    if not torch.cuda.is_bf16_supported():raise ValueError('This bounded local trainer requires BF16 CUDA support')
    costs=[]
    for start in range(0,len(train),256):
        if time.monotonic()>=deadline:raise TimeoutError('Token-cost preparation deadline')
        parts=[observed_parts(row) for row in train[start:start+256]]
        texts=[text for current,prior in parts for text in (current,prior) if text]
        lengths=iter(len(ids) for ids in model.tokenizer(texts,add_special_tokens=False,truncation=False)['input_ids'])
        for current,prior in parts:
            count=lambda n:1 if n<=254 else 1+(n-254+221)//222
            cost=count(next(lengths))
            if prior:cost+=count(next(lengths))
            costs.append(cost)
    with torch.no_grad():
        model.head.weight[:,:384].copy_(oldhead['weight'].to(device)*.5)
        model.head.weight[:,384:768].copy_(oldhead['weight'].to(device)*.5)
        model.head.weight[:,768:].zero_();model.head.bias.copy_(oldhead['bias'].to(device))
    original={k:v.detach().float().cpu().clone() for k,v in model.encoder.state_dict().items()}
    optimizer=torch.optim.AdamW([{'params':model.encoder.parameters(),'lr':1e-5},{'params':model.head.parameters(),'lr':.001}],weight_decay=.01)
    values=np.asarray([targets(r)[0] for r in train],dtype='float32');maskarray=np.asarray([targets(r)[1] for r in train],dtype='float32')
    pos=(values*maskarray).sum(0);neg=((1-values)*maskarray).sum(0)
    posweight=torch.tensor(np.clip(np.sqrt(neg/np.maximum(1,pos)),1,5),device=device)
    order=list(range(len(train)));seen=set();steps=0;curve=[];max_micro_windows=0
    total_steps=a.epochs*((len(train)+a.batch_size-1)//a.batch_size)
    warmup=max(1,int(total_steps*.05));base_lrs=[g['lr'] for g in optimizer.param_groups]
    def receipt(status):
        return {'status':status,'TRAIN_rows':len(train),'legacy_TRAIN_rows':len(legacytrain),'augmented_TRAIN_rows':len(newtrain),'CAL_rows':len(cal),'unique_TRAIN_rows_seen':len(seen),'optimizer_steps':steps,'epochs_requested':a.epochs,'completed_epochs':len(curve),'curve':curve,'local_GPU':torch.cuda.get_device_name(0),'peak_GPU_bytes':torch.cuda.max_memory_allocated(),'seconds':time.monotonic()-started,'bank_authority':False,'cloud_launches':0,'logical_batch_rows':a.batch_size,'window_budget_per_microbatch':48,'max_observed_microbatch_windows':max_micro_windows,'single_row_large_window_policy':'chunked encoder with gradient checkpointing, no text dropped','objective':'mean_known_domain_BCE + .25 * mean_known_aux_BCE; .25 does not cancel on auxiliary-only batches','input_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in files},'warm_start_manifest_sha256':hashlib.sha256((base/'manifest.json').read_bytes()).hexdigest()}
    try:
        for epoch in range(a.epochs):
            random.Random(20261012+epoch).shuffle(order);model.encoder.train();model.head.train();losses=[]
            for start in range(0,len(order),a.batch_size):
                if time.monotonic()>=deadline:raise TimeoutError('Local fit deadline; no incomplete model promoted')
                indices=order[start:start+a.batch_size]
                known=torch.tensor(maskarray[indices].sum(0),device=device);eligible=(known>0).float()
                if not bool(eligible.any()):continue
                microbatches=[];pending=[];cost=0
                for i in indices:
                    if pending and cost+costs[i]>48:microbatches.append(pending);pending=[];cost=0
                    pending.append(i);cost+=costs[i]
                if pending:microbatches.append(pending)
                optimizer.zero_grad(set_to_none=True)
                for g,lr in zip(optimizer.param_groups,base_lrs):g['lr']=lr*min(1,(steps+1)/warmup)
                batchloss=0.
                for micro in microbatches:
                    part=[train[i] for i in micro];y=torch.tensor(values[micro],device=device);mask=torch.tensor(maskarray[micro],device=device)
                    max_micro_windows=max(max_micro_windows,sum(costs[i] for i in micro))
                    with torch.autocast(device_type='cuda',dtype=torch.bfloat16):
                        logits=model.head(model.encode(part))
                        elements=torch.nn.functional.binary_cross_entropy_with_logits(logits,y,reduction='none',pos_weight=posweight)
                        normalized=(elements*mask).sum(0)/known.clamp(min=1)
                        loss=normalized[:7].sum()/eligible[:7].sum().clamp(min=1)+.25*normalized[7:].sum()/eligible[7:].sum().clamp(min=1)
                    if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
                    loss.backward();batchloss+=float(loss.detach())
                torch.nn.utils.clip_grad_norm_(list(model.encoder.parameters())+list(model.head.parameters()),1);optimizer.step()
                steps+=1;seen.update(indices);losses.append(batchloss)
                if steps%250==0:print(json.dumps({'epoch':epoch,'step':steps,'rows_seen':len(seen),'loss':sum(losses[-250:])/len(losses[-250:]),'seconds':time.monotonic()-started}),flush=True)
            if not losses:raise ValueError('No training supervision')
            curve.append({'epoch':epoch,'mean_loss':sum(losses)/len(losses),'logical_batches':len(losses),'rows_consumed':len(order)})
        if len(seen)!=len(train):raise ValueError('Some training rows never consumed')
        cal_logits=model.predict(cal,16,deadline=deadline);thresholds=[]
        for j,label in enumerate(DOMAIN+AUX):
            candidates=[]
            for th in [.5,.6,.7,.8,.9,.95,.99]:
                h=metrics(cal_logits,cal,[th]*11)['heads'][label]
                if h['TP']+h['FP']>=10 and h['precision'] is not None and h['precision']>=.95:candidates.append((h['recall'] or 0,th))
            thresholds.append(max(candidates)[1] if candidates else 1.01)
        current=model.encoder.state_dict();changed=sum(not torch.equal(v.detach().float().cpu(),original[k]) for k,v in current.items());delta=sum(float((v.detach().float().cpu()-original[k]).square().sum()) for k,v in current.items())**.5
        if not changed or not delta:raise ValueError('Encoder not updated')
        for path,digest in expected.items():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('TRAIN/CAL source changed during fit')
        report=receipt('COMPLETED');report.update(encoder_changed_tensors=changed,encoder_delta_L2=delta,thresholds=thresholds,CAL_raw=metrics(cal_logits,cal),CAL_selected=metrics(cal_logits,cal,thresholds),source_sha256={str(path.relative_to(HERE)):hashlib.sha256(path.read_bytes()).hexdigest() for path in [Path(__file__),HERE/'minilm_ft_v2/runtime/minilm_ft_core.py',HERE/'minilm_ft_v2/runtime/minilm_ft_eval.py']})
        modeldir=out/'model';modeldir.mkdir();model.encoder.to(dtype=torch.float16).save_pretrained(modeldir/'encoder',safe_serialization=True);model.tokenizer.save_pretrained(modeldir/'encoder')
        save_file({k:v.detach().float().cpu().contiguous() for k,v in model.head.state_dict().items()},str(modeldir/'head.safetensors'))
        (modeldir/'training.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
        architecture={'version':2,'features':['current_global_mean','current_last_window','prior_observed_context'],'width':1152,'max_window_tokens':256,'stride':32}
        (modeldir/'architecture.json').write_text(json.dumps(architecture,indent=2)+'\n',encoding='utf8')
        pins={path.relative_to(modeldir).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in modeldir.rglob('*') if path.is_file()}
        (modeldir/'manifest.json').write_text(json.dumps({'files':pins,'labels':DOMAIN+AUX,'thresholds':thresholds,'bank_authority':False},indent=2)+'\n',encoding='utf8')
        (out/'training.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps({'status':'COMPLETED','steps':steps,'rows':len(train),'changed':changed,'seconds':report['seconds']}),flush=True)
    except BaseException as error:
        r=receipt('FAILED');r['error_class']=type(error).__name__;(out/'training.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf8');raise


if __name__=='__main__':main()
