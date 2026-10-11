"""Actual CPU inference through the builder method; never calls Freya/LLM."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'competition'))
import builder
from package_submission import finetuned_files


def main():
    path=ROOT/'local-runs/minilm-finetune-v1/builder-release-smoke'
    if path.exists():path=path.with_name(path.name+'-'+str(time.time_ns()))
    path.mkdir(parents=True,exist_ok=False)
    run=builder.Run.__new__(builder.Run)
    run.args=SimpleNamespace(finetuned_assist='required',semantic_assist='auto',finetuned_model=None,semantic_python=sys.executable)
    run.start=time.monotonic();run.deadline=run.start+180;run.wall_deadline=time.time()+180
    run.path=path;run.work=path/'work';run.work.mkdir()
    run.builder_source=path/'builder-source';run.builder_source.mkdir()
    shutil.copyfile(ROOT/'competition/finetuned_assist.py',run.builder_source/'finetuned_assist.py')
    run.trace=path/'trace.jsonl';run.secrets=[];run.status={}
    questions=[('What can you pay and when?','I can pay 250 pounds on Friday.'),('Do you owe this personal loan?','That personal loan is not mine; I dispute it.'),('You said Monday, correct?','No, correction: Thursday instead of Monday.'),('Shall I keep the plan you accepted?','I withdraw my earlier consent. Do not record that plan.'),('Do you agree to this payment plan?','Yes, I agree to that plan.'),('Do you agree to that plan?','My brother said yes, but I have not decided.')]
    calls=[{'messages':[{'role':'assistant','message':q},{'role':'user','message':u}]} for q,u in questions]
    builder.write_json(run.work/'failed-calls.json',calls)
    run.prepare_finetuned_assist()
    if not run.finetuned_ready:raise AssertionError('Real builder method did not load trained model')
    result=json.loads((run.work/'finetuned-evidence.json').read_text(encoding='utf8'))
    if len(result['rows'])!=6 or result['bank_authority'] is not False:raise AssertionError('Inference contract')
    selected=[{head for head,p in row['heads'].items() if p['selected']} for row in result['rows']]
    # Positive semantics are observable proposals, never a policy or payment decision.
    expected=['proposal','dispute','correction','current_withdraw','current_affirm','reported_third_party']
    correct=[expected[i] in s for i,s in enumerate(selected)]
    if run.remaining()<=0:raise AssertionError('Unbounded builder subprocess')
    packaged=finetuned_files(ROOT)
    run.args.semantic_assist='off';run.prepare_finetuned_assist()
    if run.finetuned_ready or (run.work/'finetuned-evidence.json').exists():raise AssertionError('Classic off retained proposals')
    report={'status':'ACTUAL_CPU_BUILDER_BRIDGE_PASS','rows':6,'semantic_fixture_heads_matched':sum(correct),'semantic_fixture_heads_total':6,'heads_selected':[sorted(s) for s in selected],'model_manifest_sha256':result['manifest_sha256'],'runtime_sha256':result['runtime_sha256'],'builder_sha256':hashlib.sha256((ROOT/'competition/builder.py').read_bytes()).hexdigest(),'evidence_sha256':run.finetuned_hash,'seconds':time.monotonic()-run.start,'classic_off_disabled':True,'package_files_checked':len(packaged),'bank_authority':False,'financial_authorization':'UNKNOWN','hosted_tested':False,'scope':'Six new hand-authored diagnostic sentences through the actual builder child; not blind qualification or complete LLM workflow generation.'}
    (ROOT/'analysis/minilm-ft-builder-smoke.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':main()
