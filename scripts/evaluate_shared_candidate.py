"""Publish an immutable release to an owned slot and retain original kit scores.

No model/generator calls or workflow edits. POST/PUT failures are never retried.
Use --existing-publication <previous-out>/published.json for the exact same release.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'build-the-builder 2'
sys.path[:0] = [str(KIT / 'tools'), str(KIT), str(ROOT / 'competition')]
import freya
import run_cases
import score
from validation import validate, validate_coverage


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def authored_equal(expected, actual, path='workflow'):
    """Platform may add defaults, but cannot alter authored fields or ordering."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError('Readback type mismatch at ' + path)
        for key, value in expected.items():
            if key not in actual:
                raise ValueError('Readback missing ' + path + '.' + key)
            authored_equal(value, actual[key], path + '.' + key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ValueError('Readback list mismatch at ' + path)
        for index, value in enumerate(expected):
            authored_equal(value, actual[index], f'{path}[{index}]')
    elif type(expected) is not type(actual) or expected != actual:
        raise ValueError('Readback value mismatch at ' + path)


def select_workspace(result, configured=None):
    items = result if isinstance(result, list) else result.get('workspaces', result.get('items', []))
    ids = [item['id'] for item in items]
    if configured:
        if configured not in ids:
            raise ValueError('Configured workspace is not accessible with this credential')
        return configured
    if len(ids) != 1:
        raise ValueError('Expected one workspace; set FREYA_WORKSPACE_ID explicitly')
    return ids[0]


def call_binding(row, call, run, publication, persona_id, session_customer):
    customers = set()
    for message in call.get('messages', []):
        if message.get('role') != 'system':
            continue
        try:
            event = json.loads(message.get('message', ''))
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict) or event.get('event') != 'function_call_start' or event.get('function') != 'api_call':
            continue
        args = event.get('args', {})
        body = args.get('body', {})
        if isinstance(body, dict) and body.get('customer_id'):
            customers.add(body['customer_id'])
    checks = {
        'call_id': bool(row.get('call_id')) and row['call_id'] == call.get('id') == run.get('callId'),
        'persona': run.get('personaId') == persona_id,
        'agent': call.get('assistantId') == run.get('agentId') == publication['agent_id'],
        'workflow': call.get('assistantWorkflowId') == run.get('agentWorkflowId') == publication['workflow_id'],
        'version_id': call.get('entityVersionId') == run.get('agentVersionId') == publication['version_id'],
        'version_number': call.get('entityVersionNumber') == run.get('agentVersionNumber') == publication['version'],
        'workspace': call.get('workspaceId') == publication['workspace_id'],
        # Calls that stop before any bank operation still belong to their fresh
        # session/persona. Missing tool evidence is unobserved, not a mismatch.
        'customer': bool(session_customer) and row.get('customer_id') == session_customer and customers <= {session_customer},
    }
    return {'case': row['id'], 'call_id': row.get('call_id'), 'verified': all(checks.values()),
            'checks': checks, 'observed_customer_ids': sorted(customers),
            'bank_customer_observation': ('unobserved' if not customers else
                                          'verified' if customers == {session_customer} else 'mismatch')}


class Evaluation:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out).resolve()
        # A fresh directory prevents accidental reruns/overwriting uncertain writes.
        self.out.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic()
        self.deadline = self.started + 3600
        self.secrets = [os.environ[key] for key in ('FREYA_API_KEY', 'FREYA_BANK_TEAM_KEY') if os.environ.get(key)]
        self.sessions = {}
        self.original_get_call = freya.get_call

    def clean(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, '[REDACTED]')
        elif isinstance(value, list):
            value = [self.clean(item) for item in value]
        elif isinstance(value, dict):
            value = {key: self.clean(item) for key, item in value.items()}
        return value

    def save(self, name, value):
        path = self.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_text(json.dumps(self.clean(value), indent=2, ensure_ascii=False) + '\n')
        temp.replace(path)

    def event(self, kind, **fields):
        entry = self.clean({'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'kind': kind, **fields})
        with (self.out / 'events.jsonl').open('a') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Evaluation deadline reached')
        return remaining

    def request(self, url, method='GET', body=None, headers=None):
        for attempt in range(3):
            request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                             headers=headers or {}, method=method)
            try:
                with urllib.request.urlopen(request, timeout=min(45, self.remaining())) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if method != 'GET' or status not in (502, 503, 504) or attempt == 2:
                    raise RuntimeError(f'{method} HTTP {status}; response withheld; mutation not retried') from None
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if method != 'GET' or attempt == 2:
                    raise RuntimeError(f'{method} transport failure; uncertain writes are not repeated') from None
            time.sleep(min(5, self.remaining()))

    def api(self, method, path, body=None, **params):
        raw = self.request(freya.URL + path + ('?' + urllib.parse.urlencode(params) if params else ''),
                           method, body, freya.HEADERS)
        if isinstance(raw, dict) and raw.get('success') is False:
            raise RuntimeError(f'{method} {path} returned success=false')
        result = raw.get('data', {}).get('result', raw) if isinstance(raw, dict) else raw
        if method == 'POST' and path == '/api/v2/simulations':
            self.save('active-simulation.json', result.get('simulation') or result)
        return result

    def bank_http(self, path, body=None):
        result = self.request(score.HOST + path, 'POST' if body is not None else 'GET', body,
                              {**score.UA, 'x-team-key': os.environ['FREYA_BANK_TEAM_KEY']})
        if body is not None and path == '/v1/practice/sessions':
            customer = result['variables']['customer_id']
            self.sessions[body['case']] = customer
            self.save('sessions/' + customer + '.json', {'request': body, 'response': result})
        elif path.startswith('/v1/practice/ledger/'):
            self.save('ledgers/' + path.rsplit('/', 1)[-1] + '.json', result)
        return result

    def get_call(self, call_id):
        result = self.original_get_call(call_id)
        self.save('calls/' + call_id + '.json', result)
        return result

    def wait_idle(self):
        while True:
            offset, seen, active = 0, set(), []
            while True:
                result = self.api('GET', '/api/v2/simulations', workspaceId=freya.workspace_id(), limit=25, offset=offset)
                rows = result if isinstance(result, list) else result.get('simulations', result.get('items', []))
                for row in rows:
                    if row['id'] in seen:
                        raise ValueError('Simulation pagination repeated')
                    seen.add(row['id'])
                    if row.get('status') not in ('completed', 'failed', 'canceled', 'cancelled'):
                        active.append({'id': row['id'], 'status': row.get('status')})
                if len(rows) < 25:
                    if isinstance(result, dict) and (result.get('hasMore') or isinstance(result.get('total'), int) and result['total'] > len(seen)):
                        raise ValueError('Simulation pagination incomplete')
                    break
                offset += 25
            if not active:
                return
            self.event('waiting_for_workspace', active=active)
            time.sleep(min(30, self.remaining()))

    def pin(self, publication, workflow):
        record = self.api('GET', f"/api/v2/workflow/{publication['workflow_id']}", workspaceId=freya.workspace_id())['workflow']
        if record['id'] != publication['workflow_id'] or record.get('agentId') != publication['agent_id']:
            raise ValueError('Workflow identity mismatch')
        authored_equal(workflow, record['workflow'])
        llm = record['workflow'].get('agent_config', {}).get('llmConfig', {})
        if any(llm.get(key) != value for key, value in freya.AGENT_LLM.items()):
            raise ValueError('Phone model mismatch')
        versions = self.api('GET', f"/api/v2/versions/workflow/{publication['workflow_id']}", workspaceId=freya.workspace_id())['versions']
        published = [version for version in versions if version.get('isPublished')]
        if len(published) != 1 or published[0]['versionNumber'] != publication['version']:
            raise ValueError('Published version mismatch')
        if publication.get('version_id') and publication['version_id'] != published[0]['id']:
            raise ValueError('Published version ID changed')
        self.save('platform-export.workflow.json', {'workflow_id': record['id'], 'agent_id': record['agentId'], 'workflow': record['workflow']})
        self.save('published-version.json', published[0])
        return published[0]

    def publish_created(self, publication, workflow):
        """A new slot may already have published v1; do not PUT it again."""
        workflow_id = publication['workflow_id']
        record = self.api('GET', f'/api/v2/workflow/{workflow_id}', workspaceId=freya.workspace_id())['workflow']
        if record['id'] != workflow_id or record.get('agentId') != publication['agent_id']:
            raise ValueError('Created workflow identity mismatch')
        authored_equal(workflow, record['workflow'])
        llm = record['workflow'].get('agent_config', {}).get('llmConfig', {})
        if any(llm.get(key) != value for key, value in freya.AGENT_LLM.items()):
            # Only the official helper normalizes the platform-added model.
            return freya.update_workflow(workflow_id, workflow)
        versions = self.api('GET', f'/api/v2/versions/workflow/{workflow_id}', workspaceId=freya.workspace_id())['versions']
        newest = max(versions, key=lambda version: version['versionNumber'])
        if not newest.get('isPublished'):
            self.api('POST', f'/api/v2/versions/workflow/{workflow_id}/publish', {'versionId': newest['id']})
        return newest['versionNumber']

    def run(self):
        if len(self.secrets) != 2:
            raise ValueError('Missing FREYA_API_KEY or FREYA_BANK_TEAM_KEY')
        release = Path(self.args.release).resolve()
        manifest = json.loads((release / 'release.json').read_text())
        files = manifest['files_sha256']
        if not {'workflow.json', 'policy.json', 'coverage.json'} <= files.keys():
            raise ValueError('Release manifest lacks required hashes')
        for name, expected in files.items():
            path = (release / name).resolve()
            if not path.is_relative_to(release) or digest(path) != expected:
                raise ValueError('Release source hash mismatch')
        workflow = json.loads((release / 'workflow.json').read_text())
        errors = validate(workflow, json.loads((KIT / 'tools/openapi.json').read_text())) + validate_coverage(json.loads((release / 'coverage.json').read_text()))
        if errors:
            raise ValueError('Local validation failed: ' + str(errors))
        selected = set(self.args.only.split(',')) if self.args.only else None
        cases = [case for case in json.loads((KIT / 'public-test-set.json').read_text()) if case['brief'] == 'A' and (selected is None or case['id'] in selected)]
        if not cases or selected is not None and selected != {case['id'] for case in cases}:
            raise ValueError('Empty selection or unknown/non-A case IDs')
        self.save('provenance.json', {'release': str(release), 'release_sha256': digest(release / 'release.json'), 'files_sha256': files,
                                     'official_files_sha256': {name: digest(KIT / name) for name in ('freya.py', 'tools/run_cases.py', 'tools/score.py', 'public-test-set.json', 'tools/openapi.json')},
                                     'harness_sha256': digest(__file__), 'repetitions': self.args.reps, 'style': self.args.style, 'cases': [case['id'] for case in cases]})
        freya.api, freya.get_call, run_cases.http = self.api, self.get_call, self.bank_http
        freya._ws = select_workspace(self.api('GET', '/api/v2/workspaces'), os.environ.get('FREYA_WORKSPACE_ID'))
        self.event('start', workspace_id=freya._ws, source_run=manifest.get('source_run'), repetitions=self.args.reps)
        if self.args.existing_publication:
            publication = json.loads(Path(self.args.existing_publication).read_text())
            if publication.get('owner') != 'evaluate_shared_candidate' or publication.get('workspace_id') != freya._ws or publication.get('files_sha256') != files or not publication.get('version_id'):
                raise ValueError('Existing publication ownership/workspace/source binding mismatch')
            self.pin(publication, workflow)
        else:
            self.wait_idle()
            self.event('dry_run_started')
            freya.validate_workflow('codex-shared-eval-dryrun', workflow)
            self.event('dry_run_passed')
            slot = 'codex-shared-eval-' + uuid.uuid4().hex[:10]
            self.event('create_started', slot=slot)
            publication = freya.save_workflow(slot, workflow, str(self.out / 'slot-state.json'))
            self.save('created.json', publication)
            self.event('publish_started', **publication)
            if 'version' not in publication:
                publication['version'] = self.publish_created(publication, workflow)
            publication.update(owner='evaluate_shared_candidate', workspace_id=freya._ws, files_sha256=files)
            publication['version_id'] = self.pin(publication, workflow)['id']
        self.save('published.json', publication)
        self.event('published_and_verified', agent_id=publication['agent_id'], workflow_id=publication['workflow_id'], version_id=publication['version_id'])
        repetitions = []
        observed_call_ids, observed_customer_ids = set(), set()
        for repetition in range(1, self.args.reps + 1):
            self.wait_idle()
            self.pin(publication, workflow)
            specs = [run_cases.persona_for(case, {'identity': case['identity']}, self.args.style) for case in cases]
            made = freya.create_personas(specs)['personas']
            if len(made) != len(cases) or len({item['id'] for item in made}) != len(cases):
                raise ValueError('Persona count/uniqueness mismatch')
            personas = {case['id']: persona['id'] for case, persona in zip(cases, made)}
            self.save(f'personas-{repetition}.json', {'specs': specs, 'mapping': personas})
            self.event('repetition_start', repetition=repetition, cases=len(cases))
            self.sessions = {}
            rows, simulation, iteration_id, status, elapsed, median = run_cases.run_once(publication['agent_id'], cases, personas)
            # Save the unmodified original verdicts before any independent audit.
            result = {'repetition': repetition, 'rows': rows, 'simulation_id': simulation, 'iteration_id': iteration_id,
                      'status': status, 'seconds': elapsed, 'median_slowest_turn_s': median, 'published': publication}
            self.save(f'original-score-{repetition}.json', result)
            iteration = freya.get_iteration(simulation, iteration_id)
            self.save(f'iteration-{repetition}.json', iteration)
            runs = iteration['runs']
            bindings = []
            for row in rows:
                matching = [run for run in runs if run.get('personaId') == personas[row['id']]]
                call = self.get_call(row['call_id']) if row.get('call_id') else {}
                binding = call_binding(row, call, matching[0] if len(matching) == 1 else {}, publication,
                                       personas[row['id']], self.sessions.get(row['id']))
                fresh = bool(row.get('call_id')) and row['call_id'] not in observed_call_ids and row.get('customer_id') not in observed_customer_ids
                binding['checks']['independent_call_and_session'] = fresh
                binding['verified'] = binding['verified'] and fresh
                observed_call_ids.add(row.get('call_id'))
                observed_customer_ids.add(row.get('customer_id'))
                bindings.append(binding)
            result.update(bindings=bindings, provenance_verified=len(runs) == len(cases) and all(item['verified'] for item in bindings))
            self.save(f'repetition-{repetition}.json', result)
            repetitions.append(result)
            self.save('progress.json', {'completed_repetitions': repetition, 'repetitions': repetitions})
            self.pin(publication, workflow)
            if status != 'completed' or not result['provenance_verified']:
                raise ValueError('Hosted run incomplete or provenance mismatch; original score preserved')
            self.event('repetition_complete', repetition=repetition, passed=sum(row['pass'] for row in rows), total=len(rows))
        final = [{'id': case['id'], 'passes': sum(next(row['pass'] for row in rep['rows'] if row['id'] == case['id']) for rep in repetitions), 'runs': self.args.reps} for case in cases]
        summary = {'completed': True, 'scope': 'official public A' if not self.args.style else 'public A with delivery-style stress',
                   'style': self.args.style, 'published': publication, 'final': final, 'passed_calls': sum(item['passes'] for item in final),
                   'total_calls': len(cases) * self.args.reps, 'all_repetitions_pass': sum(item['passes'] == self.args.reps for item in final),
                   'total_cases': len(cases), 'original_scores_unchanged': True, 'provenance_verified': True,
                   'seconds': round(time.monotonic() - self.started)}
        self.save('summary.json', summary)
        self.event('complete', **summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--out', required=True, help='Fresh output directory; existing directories are refused')
    parser.add_argument('--reps', type=int, default=3)
    parser.add_argument('--style', choices=sorted(run_cases.STYLES))
    parser.add_argument('--only')
    parser.add_argument('--existing-publication')
    args = parser.parse_args()
    if args.reps < 1:
        parser.error('--reps must be positive')
    evaluation = Evaluation(args)
    try:
        evaluation.run()
    except Exception as error:
        evaluation.save('incomplete.json', {'type': type(error).__name__, 'message': str(error), 'elapsed': time.monotonic() - evaluation.started, 'not_an_agent_score': True})
        evaluation.event('incomplete', error_type=type(error).__name__, message=str(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
