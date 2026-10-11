"""Bounded pinned official source collection; no source execution/auth/install."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT.parent / 'tau-reference'
COMMIT = '4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699'
BUDGET = 10000000
PATHS = ['LICENSE', 'README.md', 'src/tau2/gym/README.md', 'src/tau2/gym/gym_agent.py', 'src/tau2/registry.py', 'src/tau2/utils/io_utils.py', 'src/tau2/domains/README.md', 'src/tau2/data_model/tasks.py', 'data/tau2/domains/airline/split_tasks.json', 'data/tau2/domains/retail/split_tasks.json']
for domain in ['airline', 'retail', 'banking_knowledge']:
    PATHS += [f'src/tau2/domains/{domain}/environment.py', f'data/tau2/domains/{domain}/tasks.json']
PATHS += ['data/tau2/domains/retail/policy.md', 'data/tau2/domains/airline/policy.md', 'data/tau2/domains/banking_knowledge/prompts/components/policy_header.md']

def sha(data): return hashlib.sha256(data).hexdigest()
def blob(data): return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')

def main():
    start = time.monotonic()
    inventory = json.loads((REFERENCE / 'tree-inventory.json').read_bytes()); assert inventory['commit'] == COMMIT
    PATHS.extend(x['path'] for x in inventory['files'] if x['path'].startswith('data/tau2/domains/banking_knowledge/documents/') and x['path'].endswith('.json'))
    files = {x['path']: x for x in inventory['files']}; assert sum(files[p]['bytes'] for p in PATHS) < BUDGET
    save(ROOT / 'pin.json', json.loads((REFERENCE / 'pin.json').read_bytes()))
    def fetch(path):
        item = files[path]; is_task = path.endswith('/tasks.json')
        target = ROOT / ('.cache/raw' if is_task else 'source') / path
        target.parent.mkdir(parents=True, exist_ok=True)
        old = REFERENCE / '.cache/raw' / path
        downloaded = False
        if target.exists(): data = target.read_bytes(); origin = 'own_verified_cache'
        elif old.exists(): data = old.read_bytes(); origin = 'frozen_reference_cache_reuse'
        else:
            assert time.monotonic() - start < 240
            with urlopen(Request('https://raw.githubusercontent.com/sierra-research/tau2-bench/' + COMMIT + '/' + quote(path, safe='/'), headers={'User-Agent': 'public-training-source-collector'}), timeout=15) as response:
                data = response.read(item['bytes'] + 1)
            downloaded = True; origin = 'official_pinned_download'
        assert len(data) == item['bytes'] and blob(data) == item['blob_sha1'], path
        target.write_bytes(data)
        return {**item, 'sha256': sha(data), 'url': 'https://raw.githubusercontent.com/sierra-research/tau2-bench/' + COMMIT + '/' + quote(path, safe='/'), 'stored_path': target.relative_to(ROOT).as_posix(), 'origin': origin, 'network_downloaded': downloaded, 'mixed_task_aggregate_cache_only': is_task}
    license_record = fetch('LICENSE')
    assert b'MIT License' in (ROOT / license_record['stored_path']).read_bytes()
    frozen_manifest = ROOT / 'sources.json'
    if frozen_manifest.exists():
        prior = json.loads(frozen_manifest.read_bytes())
        if prior['commit'] == COMMIT and {r['path'] for r in prior['files']} == set(PATHS):
            for record in prior['files']:
                fetch(record['path'])
                data = (ROOT / record['stored_path']).read_bytes()
                assert sha(data) == record['sha256'] and len(data) == record['bytes']
            print(json.dumps({'verified_or_restored_frozen_source_manifest': True, 'files': len(prior['files']), 'source_manifest_rewritten': False}))
            return
    with ThreadPoolExecutor(max_workers=12) as pool: records = [license_record] + list(pool.map(fetch, [p for p in PATHS if p != 'LICENSE']))
    records.sort(key=lambda x: x['path'])
    absence = {d: [x['path'] for x in inventory['files'] if Path(x['path']).parent.as_posix() == 'data/tau2/domains/' + d and (Path(x['path']).name.startswith('split_') or Path(x['path']).name.startswith('train'))] for d in ['airline', 'retail', 'banking_knowledge']}
    result = {'commit': COMMIT, 'license': 'MIT', 'files': records, 'total_selected_bytes': sum(r['bytes'] for r in records), 'new_network_bytes': sum(r['bytes'] for r in records if r['network_downloaded']), 'new_network_files': sum(r['network_downloaded'] for r in records), 'budget_bytes': BUDGET, 'partition_filename_inventory': absence, 'inventory_path': 'research/customer-benchmark/tau-reference/tree-inventory.json', 'inventory_sha256': sha((REFERENCE / 'tree-inventory.json').read_bytes()), 'publisher_code_executed': False}
    save(ROOT / 'sources.json', result)
    print(json.dumps({'files': len(records), 'selected_bytes': result['total_selected_bytes'], 'new_network_bytes': result['new_network_bytes'], 'new_network_files': result['new_network_files'], 'partition_filename_inventory': absence}))

if __name__ == '__main__': main()
