"""Local once-only heldout comparison after both arms and thresholds are frozen."""
import argparse,hashlib,json,time
from pathlib import Path
from minilm_ft_core import Model,read_rows,metrics,DOMAIN,AUX

DEFAULT_EVAL_SHA256='a563bca8e6f4a43680cef5ef881bfd8c15c2488392b04e191bb7880dd5da3aff'

def admit_eval(path,rows,expected_sha256):
    if not rows or any(row.get('split')!='EVAL' for row in rows):
        raise ValueError('Only nonempty EVAL-tagged rows may be reported as heldout')
    if type(expected_sha256) is not str or len(expected_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('Reviewed EVAL digest required')
    actual=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual!=expected_sha256:raise ValueError('EVAL source pin mismatch')
    return actual

def load_model(path,device='cpu'):
    import torch
    from safetensors.torch import load_file
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text(encoding='utf8'))
    for name,h in manifest['files'].items():
        if '..' in Path(name).parts or Path(name).is_absolute():raise ValueError('Manifest path')
        if hashlib.sha256((path/name).read_bytes()).hexdigest()!=h:raise ValueError('Model pin '+name)
    if manifest['labels']!=DOMAIN+AUX or manifest['bank_authority'] is not False:raise ValueError('Output contract')
    model=Model(path/'encoder',device,False);model.head.load_state_dict(load_file(str(path/'head.safetensors')));model.head.eval();model.encoder.eval()
    return model,manifest

def main():
    import numpy as np,torch
    p=argparse.ArgumentParser();p.add_argument('--models',required=True);p.add_argument('--eval',required=True);p.add_argument('--output',required=True);p.add_argument('--expected-eval-sha256',default=DEFAULT_EVAL_SHA256);a=p.parse_args()
    output=Path(a.output)
    if output.exists():raise ValueError('Evaluation already recorded; do not overwrite once-only measurements')
    rows=read_rows(a.eval);source_digest=admit_eval(a.eval,rows,a.expected_eval_sha256);device='cuda' if torch.cuda.is_available() else 'cpu';torch.set_num_threads(4)
    root=Path(a.models);result={'scope':'Synthetic authored root-heldout engineering metrics; generic publisher eval previously exposed. No Freya/bank policy/ASR qualification.','EVAL_sha256':source_digest,'rows':len(rows),'device':device,'bank_authority':False,'arms':{}};started=time.monotonic();deadline=started+1200
    for name in ['frozen','finetuned']:
        model,manifest=load_model(root/name,device);logits=model.predict(rows,64,deadline=deadline)
        sub={}
        for source in sorted({r['source'] for r in rows}):
            indices=[i for i,r in enumerate(rows) if r['source']==source]
            selected=[rows[i] for i in indices];values=logits[indices]
            sub[source]={'groups':len(set(r['group'] for r in selected)),'raw':metrics(values,selected),'selected':metrics(values,selected,manifest['thresholds'])}
        fresh=[i for i,r in enumerate(rows) if r['source']=='new-authored'];freshrows=[rows[i] for i in fresh]
        noctx=model.predict(freshrows,32,no_context=True,deadline=deadline)
        result['arms'][name]={'all_raw':metrics(logits,rows),'all_selected':metrics(logits,rows,manifest['thresholds']),'by_source':sub,'fresh_no_context_ablation':metrics(noctx,freshrows),'export_manifest_sha256':hashlib.sha256((root/name/'manifest.json').read_bytes()).hexdigest()}
        np.savez_compressed(output.with_name(output.stem+'.'+name+'.logits.npz'),logits=logits,no_context_logits=noctx)
        del model
        if device=='cuda':torch.cuda.empty_cache()
    result['seconds']=time.monotonic()-started;output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'rows':len(rows),'seconds':result['seconds'],'fresh':{name:arm['by_source'].get('new-authored') for name,arm in result['arms'].items()}},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
