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

def require_source_match(source, exported):
    """Platform may add dictionary defaults, but never replace source values."""
    if isinstance(source,dict):
        if not isinstance(exported,dict) or not source.keys()<=exported.keys():
            raise ValueError('Platform export source mismatch')
        for key,value in source.items():require_source_match(value,exported[key])
    elif isinstance(source,list):
        if not isinstance(exported,list) or len(source)!=len(exported):
            raise ValueError('Platform export source mismatch')
        for value,actual in zip(source,exported):require_source_match(value,actual)
    elif type(source) is not type(exported) or source!=exported:
        raise ValueError('Platform export source mismatch')

def read_evaluation(evaluation, release):
    hashes={}
    def read(path):
        value=json.loads(path.read_text());hashes[str(path)]=sha(path);return value
    manifest=read(release/'release.json')
    artifacts={'workflow.json','policy.json','coverage.json'}
    if set(manifest['files_sha256'])!=artifacts:
        raise ValueError('Shared release manifest is incomplete')
    for name,digest in manifest['files_sha256'].items():
        if sha(release/name)!=digest:raise ValueError('Shared release pin mismatch')
    source=read(release/'workflow.json')
    source_manifest=read(evaluation/'public-a/source-manifest.json')
    for name in ('workflow.json','release.json'):
        if source_manifest.get(f'competition/releases/{release.name}/{name}')!=sha(release/name):
            raise ValueError('Evaluated source manifest mismatch')
    result=read(evaluation/'results.json')
    if result.get('candidate')!=release.name or result.get('evaluation_completed') is not True:
        raise ValueError('Evaluation does not identify this completed candidate')
    records=[];published_pin=None
    for scope in ('public-a','stress-in-words'):
        folder=evaluation/scope
        ids=read(folder/'published.json');version=read(folder/'published-version.json')
        pin=(ids,version['id'])
        if published_pin is None:published_pin=pin
        if pin!=published_pin or version.get('entityId')!=ids['workflow_id'] or version.get('versionNumber')!=ids['version'] or version.get('isPublished') is not True:
            raise ValueError('Published workflow version mismatch')
        if result['scopes'][scope]['published']!=ids:
            raise ValueError('Evaluation published scope mismatch')
        exported=read(folder/'platform-export.workflow.json')
        if exported.get('workflow_id')!=ids['workflow_id'] or exported.get('agent_id')!=ids['agent_id']:
            raise ValueError('Platform export identity mismatch')
        if set(source['nodes'])!=set(exported['workflow']['nodes']):
            raise ValueError('Platform export node mismatch')
        require_source_match(source,exported['workflow'])
        provenance=read(folder/'direct-provenance.json')
        entries=provenance['calls']
        by_key={(item['rep'],item['case'],item['call_id']):item for item in entries}
        if len(by_key)!=len(entries):raise ValueError('Duplicate direct provenance')
        seen=set()
        for path in sorted(folder.glob('repetition-*.json')):
            rep=read(path)
            if rep.get('published')!=ids or rep.get('version_id')!=version['id']:
                raise ValueError('Repetition published version mismatch')
            for row in rep['rows']:
                key=(rep['repetition'],row['id'],row['call_id'])
                direct=by_key.get(key)
                if key in seen or direct is None:raise ValueError('Call score provenance missing or duplicated')
                seen.add(key)
                call_path=folder/'calls'/f"{row['call_id']}.json";call=read(call_path)
                if not (call['id']==row['call_id'] and call['assistantId']==ids['agent_id'] and call['assistantWorkflowId']==ids['workflow_id'] and call['entityVersionId']==version['id'] and call['entityVersionNumber']==ids['version']):
                    raise ValueError('Direct call provenance mismatch')
                if direct.get('agent_workflow_version_verified') is not True or direct.get('call_sha256')!=sha(call_path):
                    raise ValueError('Direct call hash mismatch')
                if type(row['pass']) is not bool or direct.get('combined_pass') is not row['pass']:
                    raise ValueError('Original score verdict mismatch')
                # Validate all rows before selection, including passing non-contrasts.
                contrast=(scope=='public-a' and (rep['repetition'],row['id']) in ((1,'PUB-01'),(2,'PUB-06'),(2,'PUB-10')))
                if row['pass'] and not contrast:continue
                records.append({'scope':scope,'case_id':row['id'],'repetition':rep['repetition'],'call_id':call['id'],'original_pass':row['pass'],'original_failed_checks':row['failed'],'messages':compact_messages(call['messages'])})
        if seen!=set(by_key):raise ValueError('Incomplete scored call set')
    if not records:raise ValueError('No actual observations')
    return records,hashes,result

class RepairRun(builder.Run):
    def prepare(self):
        super().prepare()
        wrapper=self.path/'builder-source'/Path(__file__).name
        shutil.copyfile(Path(__file__),wrapper)
        self.event('repair_wrapper_source',path=str(wrapper),sha256=sha(wrapper))
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
