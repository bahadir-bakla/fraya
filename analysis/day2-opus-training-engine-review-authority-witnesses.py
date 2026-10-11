"""Pure frozen-export output authority scan; zero fit or external calls."""
import hashlib,json,sys,time
from collections import Counter
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'integrations/learned-dialogue';sys.path.insert(0,str(BASE))
import day2_public_model_v2 as m,day2_public_train_v2 as t
def main():
    out=ROOT/'analysis/day2-opus-training-engine-review-authority-witnesses.json'
    if out.exists():raise RuntimeError('Frozen authority report exists')
    start=time.monotonic();plan=json.loads((BASE/'day2_public_plan_v2.json').read_text());rows,labels=t.load(plan['config']);evaluation=[r for r in rows if r['observed_mask'] and r['partition']=='internal_publisher_TRAIN_eval'];result={};checks=[]
    for name in ('sparse','gnn','no_edges'):
        path=BASE/('day2_public_model_v2.'+name+'.json');raw=path.read_bytes();bundle=json.loads(raw);count=Counter()
        for r in evaluation:
            p=m.predict(r['text'],bundle);count[p['source_intent_diagnostic_decision']]+=1
            if p['authority']=='none' and p['status']=='bank_abstain' and p['acceptance'] is False and p['qualified'] is False:count['bank_abstain']+=1
        result[name]={'actual_predict_calls':len(evaluation),'output_counts':dict(count),'full_weights_sha256':hashlib.sha256(raw).hexdigest(),'unchanged':path.read_bytes()==raw};checks.append(count['bank_abstain']==len(evaluation) and path.read_bytes()==raw)
    sample=sorted([r for r in rows if r['observed_mask']],key=lambda r:r['id'])[:256]
    parity_scope={'rows':256,'class_rows':dict(Counter(r['publisher_label'] for r in sample)),'partitions':dict(Counter(r['partition'] for r in sample)),'interpretation':'Producer full-precision parity samples only2of77classes. Independent288export-vs-NumPy checks do not establish missing full-precision parity.'}
    v={'status':'CLOSED_FROZEN_AUTHORITY_OUTPUT_CPU_SCAN','models':result,'actual_predict_calls':sum(r['actual_predict_calls'] for r in result.values()),'all_checked_bank_outputs_abstain':all(checks),'producer_full_precision_parity_sample_scope':parity_scope,'elapsed_seconds':round(time.monotonic()-start,3),'fits':0,'platform_calls':0,'GPU':0}
    out.write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
if __name__=='__main__':main()
