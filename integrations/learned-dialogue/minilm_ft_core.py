"""Real MiniLM encoder fine-tuning. Public/synthetic input, no bank authority."""
import argparse, gzip, hashlib, json, math, random, time
from pathlib import Path

DOMAIN = ['proposal','dispute','correction','current_affirm','current_withdraw','uncertain','reported_third_party']
AUX = ['AFFIRM','NEGATE','INFORM','REQUEST']

def read_rows(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf8') as stream:
        return [json.loads(line) for line in stream if line.strip()]

def observed_text(row):
    """Only observed language enters the encoder; gold/provenance remain outside."""
    inp = row['input']; current = inp['current_utterance']
    if not isinstance(current,str) or not current.strip(): raise ValueError('current utterance required')
    previous = inp.get('previous_utterances', [])
    pieces=[]
    for turn in previous[-2:]:
        role=turn['speaker']; text=turn['text']
        if role not in ('ASSISTANT','USER','SYSTEM') or not isinstance(text,str): raise ValueError('invalid observed turn')
        pieces.append(('ASSISTANT' if role=='SYSTEM' else role)+': '+text)
    return '\n'.join(pieces+['USER: '+current])

def targets(row):
    if any(len(row[k])!=n for k,n in [('domain_labels',7),('domain_mask',7),('aux_labels',4),('aux_mask',4)]):raise ValueError('Separate7/7/4/4 dimensions required')
    values=row['domain_labels']+row['aux_labels']; mask=row['domain_mask']+row['aux_mask']
    if len(values)!=11 or len(mask)!=11 or any(type(x) not in (int,float) or x not in (0,1) for x in values): raise ValueError('label schema')
    if any(type(x) is not bool for x in mask): raise ValueError('mask schema')
    return values,mask

def metrics(logits, rows, thresholds=None):
    import numpy as np
    y=np.asarray([targets(r)[0] for r in rows]); known=np.asarray([targets(r)[1] for r in rows],dtype=bool)
    p=1/(1+np.exp(-np.clip(logits,-50,50))); thresholds=np.asarray(thresholds if thresholds is not None else [0.5]*11)
    pred=p>=thresholds; result={}; tp_total=fp_total=fn_total=0; f1=[]
    for j,name in enumerate(DOMAIN+AUX):
        k=known[:,j]; a=pred[:,j]&k; positive=(y[:,j]==1)&k
        tp=int((a&positive).sum());fp=int((a&~positive).sum());fn=int((~a&positive).sum())
        precision=tp/(tp+fp) if tp+fp else None; recall=tp/(tp+fn) if tp+fn else None
        score=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
        result[name]={'known':int(k.sum()),'positive':int(positive.sum()),'TP':tp,'FP':fp,'FN':fn,'precision':precision,'recall':recall,'F1':score,'positive_prediction_coverage':float(a.sum()/max(1,k.sum()))}
        if j<7 and score is not None:f1.append(score)
        if j<7:tp_total+=tp;fp_total+=fp;fn_total+=fn
    return {'heads':result,'domain_macro_F1':sum(f1)/len(f1) if f1 else None,'domain_micro_F1':2*tp_total/max(1,2*tp_total+fp_total+fn_total),'rows':len(rows)}

class Model:
    def __init__(self, directory, device='cpu', trainable=False):
        import torch
        from transformers import AutoTokenizer,AutoModel
        self.torch=torch; self.device=device
        self.tokenizer=AutoTokenizer.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False,token=False)
        self.encoder=AutoModel.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False,token=False,use_safetensors=True,attn_implementation='sdpa').to(device=device,dtype=torch.float32)
        if self.encoder.config.hidden_size!=384:raise ValueError('MiniLM384 required')
        self.head=torch.nn.Linear(384,11).to(device)
        for param in self.encoder.parameters():param.requires_grad_(trainable)
        self.trainable=trainable

    def encode(self,texts):
        t=self.torch
        # Overflow windows cover the complete observed input, including late corrections.
        batch=self.tokenizer(texts,return_tensors='pt',padding=True,truncation=True,max_length=256,stride=32,return_overflowing_tokens=True)
        mapping=batch.pop('overflow_to_sample_mapping').to(self.device)
        batch={k:v.to(self.device) for k,v in batch.items()}
        out=self.encoder(**batch).last_hidden_state
        mask=batch['attention_mask'].unsqueeze(-1).to(out.dtype)
        pooled=(out*mask).sum(1)/mask.sum(1).clamp(min=1)
        sums=t.zeros((len(texts),384),dtype=pooled.dtype,device=self.device).index_add(0,mapping,pooled)
        count=t.bincount(mapping,minlength=len(texts)).clamp(min=1).unsqueeze(1)
        return t.nn.functional.normalize(sums/count,p=2,dim=1)

    def predict(self,rows,batch_size=64,no_context=False,deadline=None):
        import numpy as np
        t=self.torch;self.encoder.eval();self.head.eval();chunks=[]
        with t.inference_mode():
            for start in range(0,len(rows),batch_size):
                if deadline and time.monotonic()>deadline:raise TimeoutError('eval deadline')
                part=rows[start:start+batch_size]
                text=[('USER: '+r['input']['current_utterance']) if no_context else observed_text(r) for r in part]
                with t.autocast(device_type='cuda',dtype=t.bfloat16,enabled=str(self.device).startswith('cuda')):
                    logits=self.head(self.encode(text))
                chunks.append(logits.float().cpu().numpy())
        return np.concatenate(chunks) if chunks else np.zeros((0,11),dtype='float32')

def train_arm(rows,cal,encoder,out,trainable,epochs=2,batch_size=128,seed=20261011,deadline=None):
    import torch,numpy as np
    from safetensors.torch import save_file
    torch.manual_seed(seed);random.seed(seed);np.random.seed(seed);device='cuda' if torch.cuda.is_available() else 'cpu'
    model=Model(encoder,device,trainable); original={k:v.detach().float().cpu().clone() for k,v in model.encoder.state_dict().items()}
    optimizer=torch.optim.AdamW([{'params':[p for p in model.encoder.parameters() if p.requires_grad],'lr':2e-5},{'params':model.head.parameters(),'lr':0.003}],weight_decay=0.01)
    values=np.asarray([targets(r)[0] for r in rows],dtype='float32'); masks=np.asarray([targets(r)[1] for r in rows],dtype='float32')
    positives=(values*masks).sum(0);negatives=((1-values)*masks).sum(0)
    posweight=torch.tensor(np.clip(np.sqrt(negatives/np.maximum(1,positives)),1,5),device=device)
    headweight=torch.tensor([1]*7+[0.25]*4,device=device)
    order=list(range(len(rows))); steps=0;seen=set();curve=[];started=time.monotonic();maxgrad=0.0
    # Domain and aux are distinct objectives, not permission conversions.
    for epoch in range(epochs):
        random.Random(seed+epoch).shuffle(order);model.head.train();model.encoder.train(trainable); losses=[]
        for start in range(0,len(order),batch_size):
            if deadline and time.monotonic()>deadline:raise TimeoutError('training deadline; incomplete fit is not exported as complete')
            indices=order[start:start+batch_size];part=[rows[i] for i in indices]
            y=torch.tensor(values[indices],device=device);mask=torch.tensor(masks[indices],device=device);optimizer.zero_grad(set_to_none=True)
            if not bool(mask.any()):continue
            with torch.autocast(device_type='cuda',dtype=torch.bfloat16,enabled=device=='cuda'):
                logits=model.head(model.encode([observed_text(r) for r in part]))
                elements=torch.nn.functional.binary_cross_entropy_with_logits(logits,y,reduction='none',pos_weight=posweight)
                known=mask.sum(0); valid=(known>0).float();loss=((elements*mask).sum(0)/known.clamp(min=1)*headweight*valid).sum()/(headweight*valid).sum().clamp(min=1)
            if not torch.isfinite(loss):raise ValueError('nonfinite loss')
            loss.backward();norm=float(torch.nn.utils.clip_grad_norm_(list(model.encoder.parameters())+list(model.head.parameters()),1));maxgrad=max(maxgrad,norm)
            optimizer.step();steps+=1;seen.update(indices);losses.append(float(loss.detach()))
            if steps%100==0:print(json.dumps({'arm':'finetuned' if trainable else 'frozen','epoch':epoch,'steps':steps,'seen':len(seen),'loss':sum(losses[-100:])/len(losses[-100:])}),flush=True)
        if not losses:raise ValueError('No known training supervision; no fit exported')
        curve.append({'epoch':epoch,'mean_loss':sum(losses)/len(losses)})
    current=model.encoder.state_dict(); changed=sum(not torch.equal(v.detach().float().cpu(),original[k]) for k,v in current.items()); delta=sum(float((v.detach().float().cpu()-original[k]).square().sum()) for k,v in current.items())**0.5
    if trainable and (changed==0 or delta==0):raise AssertionError('encoder was not actually fine-tuned')
    if not trainable and changed:raise AssertionError('frozen baseline changed')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    cal_logits=model.predict(cal,deadline=deadline);rawmetrics=metrics(cal_logits,cal)
    thresholds=[]
    for j in range(11):
        candidates=[]
        for th in [0.5,0.6,0.7,0.8,0.9,0.95,0.99]:
            hs=metrics(cal_logits,cal,[th]*11)['heads'][(DOMAIN+AUX)[j]]
            if hs['TP']+hs['FP']>=10 and hs['precision'] is not None and hs['precision']>=0.95:candidates.append((hs['recall'] or 0,th))
        thresholds.append(max(candidates)[1] if candidates else 1.01)
    # Float16 safetensors stays under GitHub's single-file limit; runtime can load fp32.
    model.encoder.to(dtype=torch.float16).save_pretrained(out/'encoder',safe_serialization=True);model.tokenizer.save_pretrained(out/'encoder')
    save_file({k:v.detach().float().cpu().contiguous() for k,v in model.head.state_dict().items()},str(out/'head.safetensors'))
    report={'arm':'finetuned' if trainable else 'frozen','TRAIN_rows':len(rows),'CAL_rows':len(cal),'epochs':epochs,'optimizer_steps':steps,'unique_TRAIN_rows_seen':len(seen),'encoder_changed_tensors':changed,'encoder_delta_L2':delta,'encoder_requires_grad_count':sum(p.requires_grad for p in model.encoder.parameters()),'curve':curve,'seconds':time.monotonic()-started,'device':device,'GPU':torch.cuda.get_device_name(0) if device=='cuda' else None,'max_clipped_gradient_input_norm':maxgrad,'CAL_raw':rawmetrics,'thresholds':thresholds,'CAL_selected':metrics(cal_logits,cal,thresholds),'bank_authority':False,'financial_permission':'UNKNOWN','encoder_fine_tuned':trainable,'all_train_rows_seen':len(seen)==len(rows)}
    (out/'training.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    manifest={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    (out/'manifest.json').write_text(json.dumps({'files':manifest,'labels':DOMAIN+AUX,'thresholds':thresholds,'bank_authority':False},indent=2)+'\n',encoding='utf8')
    return report

def train_both(train_path,cal_path,encoder,out,seconds=1800,epochs=2,batch_size=128):
    import torch
    torch.set_num_threads(4);torch.set_float32_matmul_precision('high');deadline=time.monotonic()+seconds
    rows=read_rows(train_path);cal=read_rows(cal_path)
    if set(r['group'] for r in rows)&set(r['group'] for r in cal):raise ValueError('TRAIN/CAL groups overlap')
    for part,expected in [(rows,'TRAIN'),(cal,'CAL')]:
        for r in part:
            if r.get('split')!=expected:raise ValueError('Wrong split supplied as '+expected)
            observed_text(r);targets(r)
    results={}
    for name,trainable in [('frozen',False),('finetuned',True)]:
        results[name]=train_arm(rows,cal,encoder,Path(out)/name,trainable,epochs,batch_size,deadline=deadline)
        if torch.cuda.is_available():torch.cuda.empty_cache()
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--train',required=True);p.add_argument('--cal',required=True);p.add_argument('--encoder',required=True);p.add_argument('--output',required=True);p.add_argument('--seconds',type=int,default=1800);p.add_argument('--epochs',type=int,default=2);p.add_argument('--batch-size',type=int,default=128);a=p.parse_args()
    result=train_both(a.train,a.cal,a.encoder,a.output,a.seconds,a.epochs,a.batch_size)
    print(json.dumps(result),flush=True)
