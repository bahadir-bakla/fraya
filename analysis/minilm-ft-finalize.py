"""Record actual fit/eval evidence and release only the pinned fine-tuned arm."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integrations/learned-dialogue'))
from minilm_ft_core import read_rows, targets


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    import numpy as np
    from safetensors.torch import load_file
    p=argparse.ArgumentParser()
    p.add_argument('--models',required=True);p.add_argument('--eval-report',required=True)
    p.add_argument('--launch',required=True);p.add_argument('--release',required=True)
    a=p.parse_args();models=Path(a.models);evaluation=Path(a.eval_report)
    launch=json.loads(Path(a.launch).read_text(encoding='utf8'))
    if launch['status']!='completed' or launch.get('app_context_closed') is not True:
        raise ValueError('Actual returned training artifacts and closed app required')
    fit={name:json.loads((models/name/'training.json').read_text(encoding='utf8')) for name in ('frozen','finetuned')}
    for name,r in fit.items():
        if r['TRAIN_rows']!=156341 or r['unique_TRAIN_rows_seen']!=156341 or r['epochs']!=2 or not r['all_train_rows_seen']:
            raise ValueError('Full actual training row/epoch proof missing')
        if (r['encoder_changed_tensors']>0)!=(name=='finetuned'):raise ValueError('Encoder update proof')
    ev=json.loads(evaluation.read_text(encoding='utf8'))
    rows=read_rows(ROOT/'research/customer-benchmark/minilm-finetune-v1/eval.jsonl')
    if ev['EVAL_sha256']!=digest(ROOT/'research/customer-benchmark/minilm-finetune-v1/eval.jsonl'):raise ValueError('Evaluation source pin')
    indices=[i for i,r in enumerate(rows) if r['source']=='new-authored']
    fresh=[rows[i] for i in indices]
    if len(fresh)!=384 or len({r['group'] for r in fresh})!=24:raise ValueError('Fresh diagnostic cohort')
    groups={};comparison={}
    for name in ('frozen','finetuned'):
        logits=np.load(evaluation.with_name(evaluation.stem+'.'+name+'.logits.npz'))['logits'][indices,:7]
        y=np.asarray([targets(r)[0][:7] for r in fresh]);known=np.asarray([targets(r)[1][:7] for r in fresh],dtype=bool)
        pred=logits>=0;groupstats=[]
        for group in sorted({r['group'] for r in fresh}):
            mask=np.asarray([r['group']==group for r in fresh]);right=((pred==y)|~known)[mask].all(1)
            groupstats.append({'group':group,'rows':int(mask.sum()),'joint_known_correct':int(right.sum())})
        groups[name]=groupstats
        joint=((pred==y)|~known).all(1)
        m=ev['arms'][name]['by_source']['new-authored']
        comparison[name]={'raw':m['raw'],'selected':m['selected'],'joint_known_correct_rows':int(joint.sum()),'joint_known_row_accuracy':float(joint.mean()),'families_all_rows_joint_correct':sum(g['joint_known_correct']==g['rows'] for g in groupstats),'no_context_domain_macro_F1':ev['arms'][name]['fresh_no_context_ablation']['domain_macro_F1'],'all_aux_selected':{key:value for key,value in ev['arms'][name]['all_selected']['heads'].items() if key in ('AFFIRM','NEGATE','INFORM','REQUEST')}}
    base=load_file(str(models/'frozen/encoder/model.safetensors'))
    trained=load_file(str(models/'finetuned/encoder/model.safetensors'))
    deltas={}
    for i in range(6):
        keys=[k for k in trained if k.startswith(f'encoder.layer.{i}.')]
        if not keys:raise ValueError('Missing transformer layer')
        delta=sum(float((trained[k].float()-base[k].float()).square().sum()) for k in keys)**0.5
        if delta<=0:raise ValueError('Unchanged transformer layer')
        deltas[str(i)]={'tensors':len(keys),'changed_tensors':sum(not np.array_equal(trained[k].numpy(),base[k].numpy()) for k in keys),'export_delta_L2':delta}
    destination=Path(a.release)
    if destination.exists():raise ValueError('Release already exists; keep old artifacts immutable')
    shutil.copytree(models/'finetuned',destination/'model')
    pin={'schema':'minilm.real_encoder_finetune.v1','status':'EXPERIMENTAL_BUILDER_REPAIR_PROPOSALS','manifest_sha256':digest(destination/'model/manifest.json'),'runtime_sha256':{name:digest(ROOT/'integrations/learned-dialogue'/name) for name in ('minilm_ft_core.py','minilm_ft_eval.py')},'train_rows':156341,'domain_train_rows':23726,'SGD_aux_train_rows':132615,'epochs':2,'EVAL_rows':16703,'fresh_domain_EVAL_rows':384,'fresh_domain_families':24,'encoder_fine_tuned':True,'bank_authority':False,'financial_authorization':'UNKNOWN','hosted_evaluated':False,'in_voice_runtime':False,'scope':'Synthetic labels and engineered family holdout. Generic SGD eval was previously exposed. Not human/IID policy gold, ASR proof or Freya pass rate.'}
    (destination/'release.json').write_text(json.dumps(pin,indent=2)+'\n',encoding='utf8')
    report={'schema':'minilm.full_finetune.results.v1','scope':pin['scope'],'fit':fit,'fresh_domain_comparison':comparison,'fresh_family_diagnostics':groups,'six_layer_export_comparison':deltas,'eval_report_sha256':digest(evaluation),'EVAL_sha256':ev['EVAL_sha256'],'launch_source_sha256':launch['source_sha256'],'payload_sha256':launch['payload_sha256'],'Modal_app_id':launch['app_id'],'Modal_call_id':launch['call_id'],'cloud_artifacts_returned':True,'cloud_provider_shutdown_proof_pending':True,'budget_accounted_upper_USD':30,'hard_aggregate_USD':35,'actual_invoice_verified':False,'baseline_retrieval_basis_preserved':True,'classic_preserved':True,'release':pin,'release_sha256':digest(destination/'release.json')}
    (ROOT/'analysis/minilm-ft-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    lines=['Actual MiniLM full encoder fine-tune: all 156341 TRAIN rows, two epochs; 23726 domain rows and132615 source-act auxiliary rows.',f"GPU: {fit['finetuned']['GPU']}; steps per arm {fit['finetuned']['optimizer_steps']}; encoder changed tensors {fit['finetuned']['encoder_changed_tensors']}. All six transformer layers changed against the frozen matched export."]
    for name,m in comparison.items():lines.append(f"{name}: fresh384/24-family domain macro F1 {m['raw']['domain_macro_F1']:.6f}; joint-known accuracy {m['joint_known_row_accuracy']:.6f}; all-correct families {m['families_all_rows_joint_correct']}/24; no-context macro F1 {m['no_context_domain_macro_F1']:.6f}.")
    lines.extend([pin['scope'],'Model assists builder repair; no direct Freya voice runtime inference or bank permission. Classic and original retrieval encoder preserved.','Conservative cumulative accounting envelope30USD; hard35USD. This is not an actual invoice. Provider stop proof is collected separately.'])
    (ROOT/'analysis/minilm-ft-results.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'release':str(destination),'fresh':{k:{'macro_F1':v['raw']['domain_macro_F1'],'joint_accuracy':v['joint_known_row_accuracy']} for k,v in comparison.items()}}))


if __name__=='__main__':main()
