"""Package a completed final run using offline publication/readback evidence.

--publication-proof JSON: run_id, source_workflow_sha256, workflow_id, agent_id,
version, export_sha256, mock_url, published_version. published_version is the
actual platform readback (entityType, entityId, versionNumber, isPublished).
This proof stays separate from the official eight-field submission schema.
Validation checks local consistency and never calls the platform or network.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def json_object(raw, label):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON key in ' + label)
            value[key] = item
        return value
    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(label + ' must be a JSON object')
    return value


def jsonl(raw, label, allow_diagnostics=False):
    if not raw.strip():
        raise ValueError('Full nonempty log required: ' + label)
    records = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        # codex --json merges timestamped stderr diagnostics into stdout.
        # Keep these bytes in the original copies and framed trace.
        if allow_diagnostics and re.match(rb'^\d{4}-\d{2}-\d{2}T\S+\s+(?:WARN|ERROR|INFO|DEBUG|TRACE)\s', line):
            continue
        records.append(json_object(line, label))
    if not records:
        raise ValueError('Full coding-session JSON events required: ' + label)
    return records


def mock_origin(value):
    if not isinstance(value, str) or value != value.strip():
        raise ValueError('A public HTTPS mock origin is required')
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('A public HTTPS mock origin is required')
    return value.rstrip('/')


def contained(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('Package paths must remain inside the repository')
    return path


def validate_evidence(run, export, proof_path, mock_url):
    """Snapshot original bytes and validate everything before creating output."""
    run, export, proof_path = map(contained, (run, export, proof_path))
    status = json_object((run / 'status.json').read_bytes(), 'run status')
    if status.get('phase') != 'completed' or status.get('id') != run.name:
        raise ValueError('Only the identified completed run can be submitted')
    source = (run / 'work/workflow.json').read_bytes()
    source_nodes = json_object(source, 'generated workflow').get('nodes')
    if not isinstance(source_nodes, dict) or not source_nodes:
        raise ValueError('Generated workflow contains no nodes')
    raw_export = export.read_bytes()
    envelope = json_object(raw_export, 'platform export')
    workflow = envelope.get('workflow')
    if (not isinstance(workflow, dict) or not isinstance(workflow.get('nodes'), dict)
            or not workflow['nodes']):
        raise ValueError('An actual platform export envelope is required')
    proof_raw = proof_path.read_bytes()
    proof = json_object(proof_raw, 'publication proof')
    required = {'run_id', 'source_workflow_sha256', 'workflow_id', 'agent_id',
                'version', 'export_sha256', 'mock_url', 'published_version'}
    if not required.issubset(proof):
        raise ValueError('Publication proof is missing required fields')
    if proof['run_id'] != status['id']:
        raise ValueError('Publication proof identifies an unrelated run')
    for field, raw in (('source_workflow_sha256', source), ('export_sha256', raw_export)):
        if proof[field] != sha256(raw):
            raise ValueError('Publication proof hash mismatch: ' + field)
    for field in ('workflow_id', 'agent_id'):
        if not isinstance(proof[field], str) or not proof[field].strip() or envelope.get(field) != proof[field]:
            raise ValueError('Publication proof/export identity mismatch: ' + field)
    version = proof['version']
    if type(version) is not int or version < 1:
        raise ValueError('Publication proof needs a positive integer version')
    published = proof['published_version']
    if (not isinstance(published, dict) or published.get('entityType') != 'workflow'
            or published.get('entityId') != proof['workflow_id']
            or type(published.get('versionNumber')) is not int
            or published['versionNumber'] != version or published.get('isPublished') is not True):
        raise ValueError('Published version readback does not match publication proof')
    if 'version' in envelope and (type(envelope['version']) is not int or envelope['version'] != version):
        raise ValueError('Platform export version mismatch')
    origin = mock_origin(mock_url)
    if mock_origin(proof['mock_url']) != origin:
        raise ValueError('Publication proof mock_url mismatch')
    api = json_object((run / 'work/inputs/openapi.json').read_bytes(), 'run tool API')
    if api.get('servers') != [{'url': origin}]:
        raise ValueError('Run tool API mock_url mismatch')
    logs = {p.name: p.read_bytes() for p in sorted(run.glob('model-*.jsonl'))}
    host_raw = (run / 'trace.jsonl').read_bytes()
    events = jsonl(host_raw, 'host trace')
    if (events[0].get('kind') != 'run_start' or events[-1].get('kind') != 'run_end'
            or events[-1].get('phase') != 'completed'):
        raise ValueError('Full host trace must include run_start and completed run_end')
    phases = [e for e in events if e.get('kind') == 'phase']
    if not phases or phases[-1].get('phase') != 'completed':
        raise ValueError('Host trace does not finish with a completed run')
    calls = [e for e in events if e.get('kind') == 'model_call']
    if not calls or any(type(e.get('round')) is not int or e['round'] < 1 for e in calls):
        raise ValueError('Host trace must record every model round')
    expected = {'model-%s.jsonl' % e['round'] for e in calls}
    ends = [e for e in events if e.get('kind') == 'command_end'
            and str(e.get('log', '')).startswith('model-')]
    if (set(logs) != expected or {e.get('log') for e in ends} != expected
            or len(calls) != len(expected) or len(ends) != len(expected)):
        raise ValueError('Full model JSONL inventory does not match host trace')
    for name, raw in logs.items():
        records = jsonl(raw, name, allow_diagnostics=True)
        types = [r.get('type') for r in records]
        end = [e for e in ends if e.get('log') == name][-1]
        if 'thread.started' not in types or 'turn.started' not in types:
            raise ValueError('Full coding-session log required: ' + name)
        if end.get('returncode') == 0 and end.get('timed_out') is False and types[-1] != 'turn.completed':
            raise ValueError('Truncated successful coding-session log: ' + name)
    last_log = 'model-%s.jsonl' % calls[-1]['round']
    last_end = [e for e in ends if e.get('log') == last_log][-1]
    if last_end.get('returncode') != 0 or last_end.get('timed_out') is not False:
        raise ValueError('Final model command did not complete successfully')
    for ids in [status.get('freya')] + [e for e in events if e.get('kind') == 'freya_published'][-1:]:
        if ids is not None and (not isinstance(ids, dict) or
                any(ids.get(k) != proof[k] for k in ('workflow_id', 'agent_id', 'version'))):
            raise ValueError('Run publication identity/version mismatch')
    complete_logs={'trace.jsonl':host_raw,**logs}
    # A fresh refinement depends on the original generator. Include its complete
    # sessions too, preserving original bytes and explicit ancestry frame names.
    visited={run.name}
    def ancestors(current_events):
        for event in current_events:
            if event.get('kind')!='source_refinement':continue
            seed_id=event.get('source_run','')
            if not re.fullmatch(r'[A-Za-z0-9_-]+',seed_id) or seed_id in visited:raise ValueError('Invalid refinement ancestry')
            visited.add(seed_id);seed=contained(run.parent/seed_id)
            seed_status=json_object((seed/'status.json').read_bytes(),'ancestor status')
            if seed_status.get('phase')!='completed':raise ValueError('Ancestor generator did not complete')
            seed_host=(seed/'trace.jsonl').read_bytes();seed_events=jsonl(seed_host,'ancestor trace')
            if seed_events[0].get('kind')!='run_start' or seed_events[-1].get('kind')!='run_end' or seed_events[-1].get('phase')!='completed':raise ValueError('Incomplete ancestor host log')
            complete_logs['ancestors/'+seed_id+'/trace.jsonl']=seed_host
            for source_log in sorted(seed.glob('model-*.jsonl')):
                raw=source_log.read_bytes();records=jsonl(raw,source_log.name,allow_diagnostics=True)
                if 'thread.started' not in [e.get('type') for e in records] or 'turn.started' not in [e.get('type') for e in records]:raise ValueError('Incomplete ancestor coding session')
                complete_logs['ancestors/'+seed_id+'/'+source_log.name]=raw
            ancestors(seed_events)
    ancestors(events)
    return raw_export, complete_logs, proof_raw


def package(args):
    if not re.fullmatch(r'[0-9a-f]{40}', args.commit):
        raise ValueError('Use a real full Git commit SHA')
    if not args.team.strip() or not args.repo.strip() or not args.run_command.strip():
        raise ValueError('Team, repo and run_command must be supplied')
    members = []
    for member in args.member:
        name, email = member.rsplit('=', 1)
        if not name.strip() or '@' not in email:
            raise ValueError('Member name and email are required')
        members.append({'name': name.strip(), 'email': email.strip()})
    if not members:
        raise ValueError('At least one member is required')
    raw_export, logs, proof = validate_evidence(args.run, args.export_file, args.publication_proof, args.mock_url)
    output = contained(args.output)
    if output.exists():
        raise ValueError('Submission output must not already exist')
    if output.is_relative_to(contained(args.run)):
        raise ValueError('Submission output must be outside the original run')
    output.mkdir(parents=True)
    exported = output / 'final.workflow.json'
    exported.write_bytes(raw_export)
    originals = output / 'raw-logs'
    originals.mkdir()
    trace = output / 'final.trace.jsonl'
    with trace.open('wb') as stream:
        for name, raw in logs.items():
            target=originals/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            header = {'trace_file': name, 'sha256': sha256(raw), 'bytes': len(raw),
                      'scope': 'full original run log follows; bytes unmodified'}
            stream.write((json.dumps(header) + '\n').encode())
            stream.write(raw)
            if not raw.endswith(b'\n'):
                stream.write(b'\n')
    (output / 'publication-proof.json').write_bytes(proof)
    value = {'team': args.team, 'members': members, 'repo': args.repo, 'commit': args.commit,
             'run_command': args.run_command, 'workflow': exported.relative_to(ROOT).as_posix(),
             'trace': trace.relative_to(ROOT).as_posix(), 'mock_url': mock_origin(args.mock_url)}
    (output / 'submission.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'output': str(output), 'files': ['submission.json', exported.name, trace.name,
            'publication-proof.json', *['raw-logs/' + name for name in logs]],
            'workflow_sha256': sha256(raw_export), 'trace_sha256': sha256(trace.read_bytes()), 'emailed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--export', dest='export_file', required=True)
    parser.add_argument('--publication-proof', required=True)
    parser.add_argument('--mock-url', required=True)
    parser.add_argument('--team', required=True)
    parser.add_argument('--member', action='append', required=True, help='Name=email')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', default='submission')
    parser.add_argument('--run-command', required=True)
    print(json.dumps(package(parser.parse_args()), ensure_ascii=False))


if __name__ == '__main__':
    main()
