"""Real isolated CPU builder bridge; fixtures are diagnostics, not qualification."""
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
from finetuned_assist import observed_turns

def main():
    path=ROOT/'local-runs/minilm-finetune-v2/builder-release-smoke'
    path.mkdir(parents=True,exist_ok=False)
    run=builder.Run.__new__(builder.Run)
    run.args=SimpleNamespace(finetuned_assist='required',finetuned_version='v2',semantic_assist='auto',finetuned_model=None,semantic_python=sys.executable)
    run.start=time.monotonic();run.deadline=run.start+180;run.wall_deadline=time.time()+180
    run.path=path;run.work=path/'work';run.work.mkdir();run.builder_source=path/'builder-source';run.builder_source.mkdir()
    shutil.copyfile(ROOT/'competition/finetuned_assist.py',run.builder_source/'finetuned_assist.py')
    run.trace=path/'trace.jsonl';run.secrets=[];run.status={}
    calls=[{'messages':[{'role':'user','message':'I agreed to pay that instalment.'},{'role':'assistant','message':'Do you still want that arrangement?'},{'role':'user','message':'I withdraw that agreement. Do not record it.'}]},
           {'messages':[{'role':'assistant','message':'Ne zaman ödeme yapabilirsiniz?'},{'role':'user','message':'Cuma günü 420 lira ödeyebilirim.'}]},
           {'messages':[{'role':'assistant','message':'Bu borç size mi ait?'},{'role':'user','message':'Hayır, bu borcun bana ait olduğunu kabul etmiyorum.'}]},
           {'messages':[{'role':'assistant','message':'Beyanınızı tekrarlayabilir misiniz?'},{'role':'user','message':'Hava durumundan söz ediyordum. '*180+' Son düzeltmem: pazartesi değil perşembe, 200 değil 320 lira.'}]}]
    builder.write_json(run.work/'failed-calls.json',calls);run.prepare_finetuned_assist()
    assert run.finetuned_ready
    result=json.loads((run.work/'finetuned-evidence.json').read_text(encoding='utf8'))
    assert len(result['rows'])==5 and result['bank_authority'] is False
    observed,_=observed_turns(calls,context_turns=2)
    assert len(observed[1]['input']['previous_utterances'])==2
    assert observed[1]['input']['previous_utterances'][0]['speaker']=='USER'
    assert result['rows'][1]['input_sha256']==observed[1]['input_sha256']
    package=finetuned_files(ROOT)
    assert any('/minilm_ft_v2/runtime/minilm_ft_core.py' in name for _,name in package)
    run.args.semantic_assist='off';run.prepare_finetuned_assist();assert not run.finetuned_ready
    r={'status':'ACTUAL_V2_CPU_BUILDER_BRIDGE_PASS','rows':len(result['rows']),'prior_own_turn_retained':True,'classic_off_disabled':True,'package_files_checked':len(package),
       'manifest_sha256':result['manifest_sha256'],'runtime_sha256':result['runtime_sha256'],'builder_sha256':hashlib.sha256((ROOT/'competition/builder.py').read_bytes()).hexdigest(),
       'seconds':time.monotonic()-run.start,'bank_authority':False,'financial_authorization':'UNKNOWN','hosted_tested':False,'scope':'Actual production helper/producer/validator/offline CPU wiring; semantic fixture outcomes are not asserted as a pass rate.'}
    (ROOT/'analysis/minilm-v2-builder-smoke.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf8');print(json.dumps(r))

if __name__=='__main__':main()
