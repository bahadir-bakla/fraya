"""Package a completed builder run, its provenance and matching platform export, without credentials."""
import argparse,hashlib,json,pathlib,re,zipfile
ROOT=pathlib.Path(__file__).resolve().parent
KIT=ROOT.parent/'build-the-builder 2'

def validate_run_evidence(run, repo):
    """Validate original provenance in place; never rewrite request path/digest.

    Relocated/missing original sources fail closed. No runtime is imported or
    model inferred. Every validated source must also be in the archive payload.
    """
    from finetuned_assist import read_json, sha, validate_result, validate_request
    from finetuned_context_audit import validate_audit
    run=run.resolve(strict=True);repo=repo.resolve(strict=True)
    snapshots={path:sha(path) for path in (run/'trace.jsonl',run/'finetuned-request.json',
               run/'work/finetuned-evidence.json',run/'work/finetuned-context-evidence.json') if path.exists()}
    events=[json.loads(line) for line in (run/'trace.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    fullpath=run/'work/finetuned-evidence.json';auditpath=run/'work/finetuned-context-evidence.json'
    full_events=[e for e in events if e.get('kind')=='finetuned_assist']
    audit_events=[e for e in events if e.get('kind')=='finetuned_context_audit']
    def trace_binding(path, records, statuses):
        matching=[e for e in records if e.get('status') in statuses]
        if not matching or not records or records[-1].get('status') not in statuses:
            raise ValueError('Evidence lacks recorded ready trace: '+path.name)
        digest=sha(path)
        latest=records[-1]
        if latest.get('artifact_sha256')!=digest or latest.get('bank_authority') is not False:
            raise ValueError('Conflicting trace artifact hash/authority: '+path.name)
        return digest
    if not fullpath.exists():
        if auditpath.exists() or (full_events and full_events[-1].get('status')=='ready'):
            raise ValueError('Missing FULL companion')
        if audit_events and audit_events[-1].get('status') not in ('UNAVAILABLE',):
            raise ValueError('Missing context companion without explicit unavailable status')
        return {'full':'ABSENT','context':'UNAVAILABLE' if audit_events else 'ABSENT','bindings':snapshots}
    requestpath=run/'finetuned-request.json'
    request=read_json(requestpath);validate_request(request)
    calls=pathlib.Path(request['calls']).resolve(strict=True)
    runtime=pathlib.Path(request['runtime_directory']).resolve(strict=True)
    model=pathlib.Path(request['model_directory']).resolve(strict=True)
    if not calls.is_relative_to(run) or not runtime.is_relative_to(run):
        raise ValueError('Original observed source/runtime outside archived run; relocation unsupported')
    base=repo/'integrations/learned-dialogue'
    versions=[v for v in ('v1','v2') if model==(base/f'minilm_ft_{v}/model').resolve()]
    if len(versions)!=1:raise ValueError('Original model is not an archived frozen release')
    version=versions[0];release=read_json(base/f'minilm_ft_{version}/release.json')
    if request['manifest_sha256']!=release['manifest_sha256'] or request['runtime_sha256']!=release['runtime_sha256']:
        raise ValueError('Original request differs from frozen release pins')
    full=read_json(fullpath);validate_result(full,request)
    bindings={fullpath:trace_binding(fullpath,full_events,('ready',)),requestpath:snapshots[requestpath],
              calls:request['calls_sha256']}
    if full_events[-1].get('version',version)!=version:
        raise ValueError('Trace model version mismatch')
    bindings[model/'manifest.json']=request['manifest_sha256']
    manifest=read_json(model/'manifest.json')
    for name,digest in manifest['files'].items():bindings[model/name]=digest
    for name,digest in request['runtime_sha256'].items():bindings[runtime/name]=digest
    if auditpath.exists():
        envelope=read_json(auditpath);validate_audit(envelope,request,full)
        bindings[auditpath]=trace_binding(auditpath,audit_events,('AVAILABLE','UNAVAILABLE'))
        if audit_events[-1]['status']!=envelope['status']:
            raise ValueError('Context trace/envelope status mismatch')
        context=envelope['status']
    else:
        if audit_events and audit_events[-1].get('status')!='UNAVAILABLE':
            raise ValueError('Context evidence missing after recorded availability')
        if version=='v2' and not audit_events:
            context='ABSENT_LEGACY_V2'
        else:context='UNAVAILABLE' if audit_events else 'ABSENT'
    for path,digest in snapshots.items():
        if sha(path)!=digest:raise ValueError('Provenance changed during validation: '+str(path))
        bindings[path]=digest
    return {'full':'VALIDATED','context':context,'bindings':bindings}


def archive_payload(files, bindings):
    """Reject ambiguous names/sources and bind validated bytes before ZIP write."""
    payload=[];seen_names=set();seen_sources=set();actual={}
    for file,name in files:
        file=pathlib.Path(file)
        path=pathlib.PurePosixPath(name)
        if '\\' in name or path.is_absolute() or '..' in path.parts or path.as_posix()!=name or ':' in name or name=='manifest.json':
            raise ValueError('Noncanonical archive path: '+name)
        resolved=file.resolve(strict=True)
        if name in seen_names or resolved in seen_sources:raise ValueError('Duplicate archive entry/source collision: '+name)
        seen_names.add(name);seen_sources.add(resolved)
        data=file.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if re.search(rb'fak_[A-Za-z0-9_-]{20,}',data):raise ValueError('Potential credential in '+name)
        actual[resolved]=digest;payload.append((name,data))
    for source,digest in bindings.items():
        if actual.get(pathlib.Path(source).resolve())!=digest:
            raise ValueError('Validated source absent/changed in archive payload: '+str(source))
    return payload


def write_verified_archive(output, payload, manifest):
    manifest=dict(manifest,files=[{'path':name,'sha256':hashlib.sha256(data).hexdigest()} for name,data in payload])
    if len({name for name,_ in payload})!=len(payload):raise ValueError('Duplicate ZIP entries')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in payload:archive.writestr(name,data)
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(output) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)) or set(names)!={item['path'] for item in manifest['files']}|{'manifest.json'}:
            raise ValueError('ZIP inventory mismatch')
        stored=json.loads(archive.read('manifest.json'))
        if stored!=manifest:raise ValueError('ZIP manifest mismatch')
        for item in stored['files']:
            if names.count(item['path'])!=1 or hashlib.sha256(archive.read(item['path'])).hexdigest()!=item['sha256']:
                raise ValueError('ZIP manifest path/hash mismatch')

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
    if len(ids)!=len(set(ids)):parser.error('Duplicate selected run IDs')
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
    files=[];bindings={};evidence_status={}
    for name in ('builder.py','validation.py','bounded_freya.py','simulate.py','transcripts.py','semantic_assist.py','dialogue_assist.py','finetuned_assist.py','finetuned_context_audit.py','live_layer.py','recipient_assertion.py','setup_minilm.py','server.py','package_submission.py','README.md'):
        files.append((ROOT/name,'competition/'+name))
    # The optional encoder is installed separately using its exact public pins.
    for name in ('day2_pretrained_head.json','day2_pretrained_runtime.py','sgd_act_aux_runtime.py','sgd_act_aux_weights.json','sgd_act_aux_calibration.json'):
        file=ROOT.parent/'integrations/learned-dialogue'/name
        files.append((file,'integrations/learned-dialogue/'+name))
    files.extend(finetuned_files(ROOT.parent))
    for directory in ('skills','tests','web'):
        files.extend((file,'competition/'+file.relative_to(ROOT).as_posix()) for file in (ROOT/directory).rglob('*') if file.is_file() and '__pycache__' not in file.parts)
    ancestry=[];pending=[ROOT/'runs'/ident for ident in ids];seen=set()
    while pending:
        ancestor=pending.pop()
        if ancestor.name in seen:continue
        seen.add(ancestor.name);ancestry.append(ancestor.name)
        if not ancestor.is_dir():raise SystemExit('Missing provenance run: '+ancestor.name)
        evidence=validate_run_evidence(ancestor,ROOT.parent)
        evidence_status[ancestor.name]={k:v for k,v in evidence.items() if k!='bindings'}
        for source,digest in evidence['bindings'].items():
            if source in bindings and bindings[source]!=digest:raise ValueError('Conflicting ancestry source binding')
            bindings[source]=digest
        files.extend((file,'competition/runs/'+ancestor.name+'/'+file.relative_to(ancestor).as_posix()) for file in ancestor.rglob('*') if file.is_file() and '__pycache__' not in file.parts and not file.name.endswith('.tmp'))
        for line in (ancestor/'trace.jsonl').read_text().splitlines():
            event=json.loads(line)
            if event.get('kind')=='practice_seed':
                parent=event['source_run']
                if not re.fullmatch(r'[A-Za-z0-9_-]+',parent):raise SystemExit('Invalid provenance run')
                pending.append(ROOT/'runs'/parent)
    for name in ('README.md','VERSION','freya.py','public-test-set.json','env.example'):
        files.append((KIT/name,'build-the-builder 2/'+name))
    for directory in ('docs','briefs','tools','examples','.claude/skills'):
        files.extend((file,'build-the-builder 2/'+file.relative_to(KIT).as_posix()) for file in (KIT/directory).rglob('*') if file.is_file() and '__pycache__' not in file.parts)
    manifest={'runs':entries,'ancestry':ancestry,'evidence_status':evidence_status}
    payload=archive_payload(files,bindings)
    write_verified_archive(output,payload,manifest)
    print(str(output))

if __name__=='__main__':main()
