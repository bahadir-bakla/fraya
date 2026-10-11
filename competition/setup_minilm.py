"""Install or verify the exact public encoder snapshot; no auth or remote code."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen
from semantic_assist import HEAD_SHA256, sha

ROOT = Path(__file__).resolve().parent.parent


def install(verify_only=False, seconds=300):
    head_path = ROOT / 'integrations/learned-dialogue/day2_pretrained_head.json'
    if sha(head_path) != HEAD_SHA256: raise ValueError('Unpinned model manifest')
    encoder = json.loads(head_path.read_text(encoding='utf-8'))['encoder']
    directory = (ROOT / encoder['local_directory']).resolve()
    if not directory.is_relative_to(ROOT): raise ValueError('Invalid encoder directory')
    deadline = time.monotonic() + seconds
    downloaded = 0
    prefix = 'https://huggingface.co/' + encoder['model_id'] + '/resolve/' + encoder['revision'] + '/'
    for name, record in encoder['files'].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or record['official_url'] != prefix + name:
            raise ValueError('Invalid publisher binding')
        if path.is_file() and path.stat().st_size == record['bytes'] and sha(path) == record['sha256']:
            continue
        if verify_only: raise ValueError('Missing or changed encoder file: ' + name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + '.download')
        digest = hashlib.sha256(); count = 0
        try:
            left = deadline - time.monotonic()
            if left <= 0: raise TimeoutError('Download budget expired')
            with urlopen(record['official_url'], timeout=min(30, left)) as response, temp.open('wb') as output:
                while True:
                    if time.monotonic() >= deadline: raise TimeoutError('Download budget expired')
                    chunk = response.read(65536)
                    if not chunk: break
                    count += len(chunk)
                    if count > record['bytes']: raise ValueError('Encoder download exceeds pinned size')
                    digest.update(chunk); output.write(chunk)
            if count != record['bytes'] or digest.hexdigest() != record['sha256']:
                raise ValueError('Encoder download hash/size mismatch')
            temp.replace(path); downloaded += count
        finally:
            temp.unlink(missing_ok=True)
    return {'status': 'verified', 'revision': encoder['revision'], 'files': len(encoder['files']),
            'total_bytes': encoder['total_encoder_files_bytes'], 'downloaded_bytes': downloaded,
            'license': encoder['license']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.verify_only), indent=2))
