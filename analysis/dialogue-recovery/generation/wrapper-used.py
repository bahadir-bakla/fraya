"""Automatically repair a hash-pinned public candidate from actual hosted evidence.

This starts a new, separately timed local practice build. It never edits the
shared release or pretends its prior run resumed. Publication is a later step.
"""
import argparse,hashlib,json,os,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'competition'))
import builder
from transcripts import compact_messages

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_evaluation(evaluation, release):
    manifest=json.loads((release/'release.json').read_text())
    for name,digest in manifest['files_sha256'].items():
        if name not in ('workflow.json','policy.json','coverage.json') or sha(release/name)!=digest:
            raise ValueError('Shared release pin mismatch')
    result=json.loads((evaluation/'results.json').read_text())
    if result.get('candidate')!=release.name or result.get('evaluation_completed') is not True:
        raise ValueError('Evaluation does not identify this completed candidate')
    records=[];hashes={str(release/'release.json'):sha(release/'release.json'),str(evaluation/'results.json'):sha(evaluation/'results.json')}
    for scope in ('public-a','stress-in-words'):
        folder=evaluation/scope
        ids=json.loads((folder/'published.json').read_text());version=json.loads((folder/'published-version.json').read_text())
        for path in sorted(folder.glob('repetition-*.json')):
            rep=json.loads(path.read_text());hashes[str(path)]=sha(path)
            for row in rep['rows']:
                # Three successful contrasts retain their original passing scope.
                contrast=(scope=='public-a' and (rep['repetition'],row['id']) in ((1,'PUB-01'),(2,'PUB-06'),(2,'PUB-10')))
                if row['pass'] and not contrast:continue
                call_path=folder/'calls'/f"{row['call_id']}.json";call=json.loads(call_path.read_text());hashes[str(call_path)]=sha(call_path)
                if not (call['assistantId']==ids['agent_id'] and call['assistantWorkflowId']==ids['workflow_id'] and call['entityVersionId']==version['id'] and call['entityVersionNumber']==ids['version']):
                    raise ValueError('Direct call provenance mismatch')
                records.append({'scope':scope,'case_id':row['id'],'repetition':rep['repetition'],'call_id':call['id'],'original_pass':row['pass'],'original_failed_checks':row['failed'],'messages':compact_messages(call['messages'])})
    if not records:raise ValueError('No actual observations')
    return records,hashes,result

class RepairRun(builder.Run):
    def prepare(self):
        super().prepare()
        records,hashes,result=read_evaluation(OPTIONS.evaluation,OPTIONS.release)
        for name in ('workflow.json','policy.json','coverage.json'):
            shutil.copyfile(OPTIONS.release/name,self.work/name)
        path=self.work/'previous-failed-calls.json'
        builder.write_json(path,self.clean(records));self.observed_sha=sha(path)
        self.feedback.append({'existing_candidate':'workflow.json','read_file':path.name,
          'scope':'Actual hosted failures and explicitly marked passing contrasts; new public practice repair, not resumed generation.',
          'instructions':[
             'Make minimal source-general repairs to this existing graph and its advertised extractor/consumer contracts. Preserve all input brief rules and the independent bank verification, readback, consent and receipt guards.',
             'Offer acceptance is not final write consent. Complete present self commitments must not depend on a tiny yes/will-pay allowlist or manufacture an unfinished amount. A ready response must restate the actual pending question, or give a fresh complete readback if all terms remain validated; never loop on an empty continuation cue.',
             'Track a genuinely unfinished condition separately from a changed amount/date. Recover with a precise policy-permitted question. Known terms cannot authorize a write while an actual condition remains unresolved. A new unequivocal commitment may supersede the unfinished condition only within its target and terms; require fresh readback and later consent.',
             'A canonical current-field security answer must not be rejected merely because a narrower raw parser cannot parse spoken digit years. Preserve source subject/completion/negation/quotation guards, never trust model verified status, and call the authoritative identity API. Keep wrong answers distinct from parser clarifications.',
             'Explicit assent to another operation, e.g. marketing, cannot count as payment consent even when the extractor wrongly labels confirm after a payment readback.',
             'Two PUB10 judges confuse mandatory opening recording disclosure with promise-recording acknowledgement. Keep original failed verdicts; do not remove required disclosure or alter correct retry/receipt behavior. Plain PUB06 rep1 customer never spoke Friday and accepted today; do not hardcode Friday or describe it as lost-date extraction.',
             'No case IDs, identities, fixture amounts or expected dates in runtime rules. Write and execute local positive and negative stateful regressions before returning the three artifacts. Keep output source compact and finish the artifact contract within the model deadline.'
          ]})
        self.event('shared_evaluated_release_seed',release=str(OPTIONS.release),source_hashes=hashes,artifact_sha256={n:sha(self.work/n) for n in ('workflow.json','policy.json','coverage.json')},recorded_calls=len(records),new_practice_budget=True,original_run_resumed=False)
    def check_pinned_evidence(self):
        super().check_pinned_evidence()
        if sha(self.work/'previous-failed-calls.json')!=self.observed_sha:raise ValueError('Observed repair packet modified')

def main():
    global OPTIONS
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True);parser.add_argument('--evaluation',type=Path,required=True)
    parser.add_argument('--semantic-python',required=True);parser.add_argument('--minutes',type=float,default=15)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--model')
    OPTIONS=parser.parse_args();OPTIONS.release=OPTIONS.release.resolve();OPTIONS.evaluation=OPTIONS.evaluation.resolve()
    if OPTIONS.output.exists():raise ValueError('Refusing to overwrite run report')
    read_evaluation(OPTIONS.evaluation,OPTIONS.release)
    command=['builder.py',str(builder.KIT/'briefs/brief-a.md'),'--local-only','--slot','dialogue-recovery-a','--minutes',str(OPTIONS.minutes),'--rounds','2','--semantic-assist','auto','--dialogue-assist','off','--finetuned-assist','required','--finetuned-version','v2','--semantic-python',OPTIONS.semantic_python]
    if OPTIONS.model:command+=['--model',OPTIONS.model]
    old=sys.argv
    try:sys.argv=command;args=builder.arguments()
    finally:sys.argv=old
    for name in tuple(os.environ):
        if any(x in name.upper() for x in ('API_KEY','TEAM_KEY','TOKEN','SECRET','PASSWORD')):os.environ.pop(name)
    with builder.slot_lock(builder.ROOT/'.state/slots/dialogue-recovery-a.lock'):
        run=RepairRun(args);success=False
        try:success=run.execute()
        except Exception as error:
            if run.status.get('phase')!='failed':run.phase('failed',ended=builder.stamp(),error=run.clean(str(error)))
        report={'success':success,'run_id':run.id,'run_path':str(run.path),'source_release':str(OPTIONS.release),'evaluation':str(OPTIONS.evaluation),'status':run.status,'published':False,'original_agent_modified':False}
        OPTIONS.output.parent.mkdir(parents=True,exist_ok=True);builder.write_json(OPTIONS.output,report)
        print(json.dumps(report,ensure_ascii=False),flush=True)
        return 0 if success else 1
if __name__=='__main__':raise SystemExit(main())
