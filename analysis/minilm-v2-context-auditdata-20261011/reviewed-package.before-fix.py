"""Package a completed builder run, its provenance and matching platform export, without credentials."""
import argparse,hashlib,json,pathlib,re,zipfile
ROOT=pathlib.Path(__file__).resolve().parent
KIT=ROOT.parent/'build-the-builder 2'

def finetuned_files(repo):
    """Include the verified optional trained encoder and its offline runtime."""
    from finetuned_assist import read_json, sha, verify_manifest
    base=repo/'integrations/learned-dialogue'
    entries=[]
    for version in ('v1','v2'):entries.extend(_finetuned_release_files(repo,base,version))
    return entries

def _finetuned_release_files(repo,base,version):
    from finetuned_assist import read_json, sha, verify_manifest
    release=base/f'minilm_ft_{version}/release.json'
    if not release.exists():return []
    pins=read_json(release)
    runtime=base/'minilm_ft_v2/runtime' if version=='v2' else base
    request={'schema':'builder.finetuned_proposals.v1','calls':str((repo/'unused-calls.json').resolve()),'calls_sha256':'0'*64,'model_directory':str((release.parent/'model').resolve()),'manifest_sha256':pins['manifest_sha256'],'runtime_directory':str(runtime.resolve()),'runtime_sha256':pins['runtime_sha256'],'seconds':60}
    model=verify_manifest(request)
    files=[release,release.parent/'model/manifest.json']
    files.extend(release.parent/'model'/name for name in model['files'])
    for name,digest in pins['runtime_sha256'].items():
        if sha(runtime/name)!=digest:raise ValueError('Fine-tuned runtime pin mismatch: '+name)
        files.append(runtime/name)
    return [(file,file.relative_to(repo).as_posix()) for file in files]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',nargs='+');parser.add_argument('--output');args=parser.parse_args()
    ids=args.run or [json.loads((ROOT/'.state/latest.json').read_text())['run_id']]
    entries=[]
    for ident in ids:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',ident):parser.error('Invalid run ID')
        run=ROOT/'runs'/ident;status=json.loads((run/'status.json').read_text())
        if status['phase'] not in {'completed','needs_attention'}:parser.error('Wait for every run to finish before packaging.')
        if status.get('evaluation')=='local_validation_only' or status.get('published') is False:parser.error('Local-only builds have no platform export; select a published run.')
        if status.get('within_30_minutes') is False:parser.error('A selected run exceeds the 30-minute limit; retain it as diagnostic provenance, not as the submission run.')
        export=run/status.get('artifacts',{}).get('workflow','missing')
        if not export.is_file():parser.error('A run has no matching Freya platform export.')
        entries.append({'run_id':run.name,'test_brief':status.get('test_brief'),'status':status['phase'],'score':status.get('latest_score'),'freya':status['freya'],'platform_export':'competition/runs/'+run.name+'/'+export.name,'trace':'competition/runs/'+run.name+'/trace.jsonl'})
    output=pathlib.Path(args.output).resolve() if args.output else ROOT/'submissions'/((ids[0] if len(ids)==1 else 'freya-hackathon-demo')+'.zip')
    output.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for name in ('builder.py','validation.py','bounded_freya.py','simulate.py','transcripts.py','semantic_assist.py','dialogue_assist.py','finetuned_assist.py','finetuned_context_audit.py','setup_minilm.py','server.py','package_submission.py','README.md'):
        files.append((ROOT/name,'competition/'+name))
    # The optional encoder is installed separately using its exact public pins.
    for name in ('day2_pretrained_head.json','day2_pretrained_runtime.py','sgd_act_aux_runtime.py','sgd_act_aux_weights.json','sgd_act_aux_calibration.json'):
        file=ROOT.parent/'integrations/learned-dialogue'/name
        files.append((file,'integrations/learned-dialogue/'+name))
    files.extend(finetuned_files(ROOT.parent))
    for directory in ('skills','tests','web'):
        files.extend((file,'competition/'+str(file.relative_to(ROOT))) for file in (ROOT/directory).rglob('*') if file.is_file() and '__pycache__' not in file.parts)
    ancestry=[];pending=[ROOT/'runs'/ident for ident in ids];seen=set()
    while pending:
        ancestor=pending.pop()
        if ancestor.name in seen:continue
        seen.add(ancestor.name);ancestry.append(ancestor.name)
        if not ancestor.is_dir():raise SystemExit('Missing provenance run: '+ancestor.name)
        files.extend((file,'competition/runs/'+ancestor.name+'/'+str(file.relative_to(ancestor))) for file in ancestor.rglob('*') if file.is_file() and '__pycache__' not in file.parts and not file.name.endswith('.tmp'))
        for line in (ancestor/'trace.jsonl').read_text().splitlines():
            event=json.loads(line)
            if event.get('kind')=='practice_seed':
                parent=event['source_run']
                if not re.fullmatch(r'[A-Za-z0-9_-]+',parent):raise SystemExit('Invalid provenance run')
                pending.append(ROOT/'runs'/parent)
    for name in ('README.md','VERSION','freya.py','public-test-set.json','env.example'):
        files.append((KIT/name,'build-the-builder 2/'+name))
    for directory in ('docs','briefs','tools','examples','.claude/skills'):
        files.extend((file,'build-the-builder 2/'+str(file.relative_to(KIT))) for file in (KIT/directory).rglob('*') if file.is_file() and '__pycache__' not in file.parts)
    manifest={'runs':entries,'ancestry':ancestry,'files':[]}
    payload=[]
    for file,name in files:
        data=file.read_bytes()
        if re.search(rb'fak_[A-Za-z0-9_-]{20,}',data):raise SystemExit(f'Refusing to package potential credential in {name}')
        payload.append((name,data));manifest['files'].append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in payload:archive.writestr(name,data)
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(str(output))

if __name__=='__main__':main()
