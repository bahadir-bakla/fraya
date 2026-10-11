"""V2 observed current/global/tail/context MiniLM features; no bank authority."""
import gzip
import hashlib
import json
import time
from pathlib import Path

DOMAIN=['proposal','dispute','correction','current_affirm','current_withdraw','uncertain','reported_third_party']
AUX=['AFFIRM','NEGATE','INFORM','REQUEST']


def read_rows(path):
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',encoding='utf8') as stream:return [json.loads(line) for line in stream if line.strip()]


def targets(row):
    for name,n in [('domain_labels',7),('domain_mask',7),('aux_labels',4),('aux_mask',4)]:
        if type(row[name]) is not list or len(row[name])!=n:raise ValueError('Separate 7/7/4/4 target arrays required')
    values=row['domain_labels']+row['aux_labels'];mask=row['domain_mask']+row['aux_mask']
    if any(type(v) not in (int,float) or v not in (0,1) for v in values):raise ValueError('Binary target labels')
    if any(type(v) is not bool for v in mask):raise ValueError('Boolean masks')
    return values,mask


def observed_parts(row):
    inp=row['input']
    if type(inp) is not dict or set(inp)!= {'current_utterance','previous_utterances'}:raise ValueError('Only observed language features accepted')
    current=inp['current_utterance'];prior=inp['previous_utterances']
    if type(current) is not str or not current.strip() or len(current)>16384:raise ValueError('Invalid current speech')
    if type(prior) is not list or len(prior)>2:raise ValueError('At most two observed prior turns')
    pieces=[]
    for turn in prior:
        if type(turn) is not dict or set(turn)!= {'speaker','text'}:raise ValueError('Observed role/text only')
        role=turn['speaker'];text=turn['text']
        if role not in ('ASSISTANT','USER','SYSTEM') or type(text) is not str or len(text)>16384:raise ValueError('Invalid observed context')
        pieces.append(('ASSISTANT' if role=='SYSTEM' else role)+': '+text)
    return 'USER: '+current,'\n'.join(pieces)


def observed_text(row):
    current,prior=observed_parts(row)
    return prior+'\n'+current if prior else current


def metrics(logits,rows,thresholds=None):
    import numpy as np
    if len(rows)==0:raise ValueError('No metric rows')
    y=np.asarray([targets(r)[0] for r in rows]);known=np.asarray([targets(r)[1] for r in rows],dtype=bool)
    pred=(1/(1+np.exp(-np.clip(logits,-50,50))))>=np.asarray(thresholds if thresholds is not None else [0.5]*11)
    results={};f1=[];tpall=fpall=fnall=0
    for j,name in enumerate(DOMAIN+AUX):
        k=known[:,j];a=pred[:,j]&k;positive=(y[:,j]==1)&k
        tp=int((a&positive).sum());fp=int((a&~positive).sum());fn=int((~a&positive).sum())
        precision=tp/(tp+fp) if tp+fp else None;recall=tp/(tp+fn) if tp+fn else None
        score=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
        results[name]={'known':int(k.sum()),'positive':int(positive.sum()),'TP':tp,'FP':fp,'FN':fn,'precision':precision,'recall':recall,'F1':score,'positive_prediction_coverage':float(a.sum()/max(1,k.sum()))}
        if j<7:
            tpall+=tp;fpall+=fp;fnall+=fn
            if score is not None:f1.append(score)
    return {'heads':results,'domain_macro_F1':sum(f1)/len(f1) if f1 else None,'domain_micro_F1':2*tpall/max(1,2*tpall+fpall+fnall),'rows':len(rows)}


class Model:
    def __init__(self,directory,device='cpu',trainable=False):
        import torch
        from transformers import AutoTokenizer,AutoModel
        self.torch=torch;self.device=device
        self.tokenizer=AutoTokenizer.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False,token=False)
        self.encoder=AutoModel.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False,token=False,use_safetensors=True,attn_implementation='sdpa').to(device=device,dtype=torch.float32)
        if self.encoder.config.hidden_size!=384:raise ValueError('MiniLM384 required')
        self.head=torch.nn.Linear(1152,11).to(device)
        for param in self.encoder.parameters():param.requires_grad_(trainable)
        self.trainable=trainable

    def encode(self,rows,no_context=False,no_tail=False):
        """No current-speech truncation. Preserve a separate last-window vector."""
        t=self.torch;parts=[observed_parts(r) for r in rows]
        currents=[p[0] for p in parts];contexts=[p[1] for p in parts]
        active=[i for i,p in enumerate(contexts) if p and not no_context]
        texts=currents+[contexts[i] for i in active]
        batch=self.tokenizer(texts,return_tensors='pt',padding=True,truncation=True,max_length=256,stride=32,return_overflowing_tokens=True)
        mapping=batch.pop('overflow_to_sample_mapping').to(self.device)
        batch={k:v.to(self.device) for k,v in batch.items()}
        large_training=self.trainable and self.encoder.training and len(mapping)>48
        if large_training:self.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        pooled_parts=[]
        for start in range(0,len(mapping),48):
            section={k:v[start:start+48] for k,v in batch.items()}
            output=self.encoder(**section).last_hidden_state
            mask=section['attention_mask'].unsqueeze(-1).to(output.dtype)
            pooled_parts.append((output*mask).sum(1)/mask.sum(1).clamp(min=1))
        pooled=t.cat(pooled_parts,dim=0)
        if large_training:self.encoder.gradient_checkpointing_disable()
        sums=t.zeros((len(texts),384),device=self.device,dtype=pooled.dtype).index_add(0,mapping,pooled)
        counts=t.bincount(mapping,minlength=len(texts)).clamp(min=1).unsqueeze(1)
        means=t.nn.functional.normalize(sums/counts,p=2,dim=1)
        last=t.full((len(texts),),-1,device=self.device,dtype=t.long)
        last.scatter_reduce_(0,mapping,t.arange(len(mapping),device=self.device),reduce='amax',include_self=True)
        tails=t.nn.functional.normalize(pooled[last[:len(rows)]],p=2,dim=1)
        context=t.zeros((len(rows),384),device=self.device,dtype=means.dtype)
        if active:context=context.index_copy(0,t.tensor(active,device=self.device),means[len(rows):])
        if no_tail:tails=t.zeros_like(tails)
        return t.cat([means[:len(rows)],tails,context],dim=1)

    def predict(self,rows,batch_size=16,no_context=False,no_tail=False,deadline=None):
        import numpy as np
        t=self.torch;self.encoder.eval();self.head.eval();chunks=[]
        with t.inference_mode():
            for start in range(0,len(rows),batch_size):
                if deadline and time.monotonic()>=deadline:raise TimeoutError('V2 evaluation deadline')
                with t.autocast(device_type='cuda',dtype=t.bfloat16,enabled=str(self.device).startswith('cuda')):
                    logits=self.head(self.encode(rows[start:start+batch_size],no_context,no_tail))
                chunks.append(logits.float().cpu().numpy())
        return np.concatenate(chunks) if chunks else np.zeros((0,11),dtype='float32')
