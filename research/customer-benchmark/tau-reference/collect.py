"""Bounded official-source downloads; never install or execute publisher code."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / '.cache/raw'
LIMIT = 40_000_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def verify(data, item):
    assert len(data) == item['bytes']
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == item['blob_sha1']


def main():
    pin = json.loads((ROOT / 'pin.json').read_bytes())
    inventory = json.loads((ROOT / 'tree-inventory.json').read_bytes())
    items = {x['path']: x for x in inventory['files']}
    fixed = ['LICENSE', 'README.md', 'CHANGELOG.md', 'RELEASE_NOTES.md', 'docs/evaluation.md', 'src/tau2/domains/README.md', 'src/tau2/knowledge/README.md', 'src/tau2/data_model/tasks.py', 'src/tau2/environment/tool.py', 'src/tau2/environment/toolkit.py', 'src/tau2/domains/banking_knowledge/data_model.py', 'src/tau2/domains/banking_knowledge/tools.py', 'src/tau2/domains/banking_knowledge/retrieval_mixins.py', 'src/tau2/domains/banking_knowledge/retrieval_toolkits.py', 'src/tau2/domains/banking_knowledge/DATABASE_GUIDE.md', 'data/tau2/domains/banking_knowledge/prompts/components/policy_header.md', 'data/tau2/domains/retail/policy.md', 'data/tau2/domains/airline/policy.md', 'data/tau2/domains/telecom/main_policy.md', 'data/tau2/domains/banking_knowledge/tasks.json', 'data/tau2/domains/retail/tasks.json', 'data/tau2/domains/airline/tasks.json']
    groups = {'doc_bank_accounts_bank_accounts_(general)', 'doc_credit_cards_credit_cards_(general)', 'doc_buy_now_pay_later_bnpl_management_dashboard', 'doc_everyone_pay_scheduled_payments', 'doc_business_savings_accounts_joint_business_holders_+_user_roles', 'doc_everyone_pay_everyone_pay', 'doc_credit_cards_credit_card_account_logistics', 'doc_credit_cards_credit_card_replacements', 'doc_credit_cards_virtual_card_management'}
    documents = [x['path'] for x in inventory['files'] if x['path'].startswith('data/tau2/domains/banking_knowledge/documents/') and x['path'].rsplit('/', 1)[1].rsplit('_', 1)[0] in groups]
    selected = [items[x] for x in sorted(set(fixed + documents))]
    assert sum(x['bytes'] for x in selected) < LIMIT
    (ROOT / 'selection.json').write_bytes(encode({'commit': pin['commit'], 'selection': 'fixed docs/schema/source actions plus nine policy document families; no voice, model results, customer databases, repo install or credentials', 'files': selected, 'inventory_document_count': sum('/documents/' in x['path'] for x in inventory['files']), 'selected_policy_documents': len(documents), 'byte_ceiling': LIMIT}))
    started = time.monotonic()

    def fetch(item):
        assert time.monotonic() - started < 480, 'Collection time bound'
        path = CACHE / item['path']; path.parent.mkdir(parents=True, exist_ok=True)
        url = 'https://raw.githubusercontent.com/' + pin['repo'] + '/' + pin['commit'] + '/' + urllib.parse.quote(item['path'], safe='/')
        if path.exists():
            data = path.read_bytes(); verify(data, item)
        else:
            request = urllib.request.Request(url, headers={'User-Agent': 'public-reference-source-collector'})
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read(min(item['bytes'] + 1, LIMIT + 1))
            verify(data, item); path.write_bytes(data)
        quarantine = item['path'].endswith('/tasks.json')
        if not quarantine:
            target = ROOT / 'source' / item['path']; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        return {**item, 'sha256': digest(data), 'url': url, 'role': 'QUARANTINED_BENCHMARK_TASKS' if quarantine else 'REFERENCE_ONLY', 'stored_path': path.relative_to(ROOT).as_posix() if quarantine else target.relative_to(ROOT).as_posix()}

    license_item = next(x for x in selected if x['path'] == 'LICENSE')
    license_record = fetch(license_item)
    text = (CACHE / 'LICENSE').read_text(encoding='utf-8')
    assert 'MIT License' in text and 'Permission is hereby granted' in text
    records = [license_record]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch, item) for item in selected if item['path'] != 'LICENSE']
        for future in as_completed(futures):
            records.append(future.result())
            if len(records) % 25 == 0:
                print(json.dumps({'stage': 'download', 'files_verified': len(records), 'bytes_verified': sum(x['bytes'] for x in records)}), flush=True)
    website = {'url': 'https://taubench.com/', 'immutable': False, 'role': 'REFERENCE_ONLY', 'not_used_as_training_or_model_outcomes': True}
    try:
        req = urllib.request.Request(website['url'], headers={'User-Agent': 'public-reference-source-collector'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read(2_000_001)
        assert len(data) <= 2_000_000
        (ROOT / '.cache/taubench.html').write_bytes(data)
        website.update(status='downloaded', bytes=len(data), sha256=digest(data), retrieved_utc='2026-10-11T11:01:20Z or later; see final report')
    except Exception as error:
        website.update(status='unavailable_for_local_snapshot', error_type=type(error).__name__)
    assert sum(x['bytes'] for x in records) + website.get('bytes', 0) < LIMIT
    manifest = {'status': 'downloaded_and_blob_verified', 'pin': pin, 'license': 'MIT', 'publisher_code_executed': False, 'files': sorted(records, key=lambda x: x['path']), 'downloaded_repo_bytes': sum(x['bytes'] for x in records), 'website': website, 'models_or_cloud_calls': 0}
    (ROOT / 'sources.json').write_bytes(encode(manifest))
    print(json.dumps({'status': manifest['status'], 'files': len(records), 'policy_documents': len(documents), 'repo_bytes': manifest['downloaded_repo_bytes'], 'website': website}, sort_keys=True), flush=True)


if __name__ == '__main__': main()
