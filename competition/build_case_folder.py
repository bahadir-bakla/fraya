"""Prepare a source-pinned case folder and invoke the existing automatic builder.

No business constants or phone workflow are supplied by this adapter. The API
server replacement is deployment configuration; all policy comes from evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import urlopen


def digest(data):
    return hashlib.sha256(data).hexdigest()


def expand_references(value, document, active=()):
    """Inline only local JSON references without weakening any schema field."""
    if isinstance(value, list):
        return [expand_references(item, document, active) for item in value]
    if not isinstance(value, dict):
        return value
    if '$ref' in value:
        ref = value['$ref']
        if not isinstance(ref, str) or not ref.startswith('#/') or ref in active:
            raise ValueError('Unsupported external or recursive API reference')
        target = document
        for part in ref[2:].split('/'):
            target = target[part.replace('~1', '/').replace('~0', '~')]
        result = expand_references(target, document, active + (ref,))
        if not isinstance(result, dict):
            raise ValueError('API reference must resolve to an object')
        result.update({key: expand_references(item, document, active) for key, item in value.items() if key != '$ref'})
        return result
    return {key: expand_references(item, document, active) for key, item in value.items()}


def prepare(folder, api_path, mock_url, output):
    folder = Path(folder).resolve()
    origin = mock_url.rstrip('/')
    url = urlparse(origin)
    if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError('A public HTTPS mock origin is required')
    with urlopen(origin + '/health', timeout=20) as response:
        if response.status != 200:
            raise ValueError('Mock health failed before builder launch')
    output.mkdir(parents=True, exist_ok=True)
    docs = [p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in {'.md', '.txt', '.pdf'}
            and ('sources' in p.relative_to(folder).parts or p.parent == folder)]
    def order(path):
        if path.name.upper() == 'BRIEF.MD':
            return ('0000', str(path))
        match = re.search(r'\d{4}-\d{2}-\d{2}', path.name)
        return (match[0] if match else '0001', str(path.relative_to(folder)))
    records = []
    paths = []
    for index, path in enumerate(sorted(docs, key=order)):
        raw = path.read_bytes()
        if path.suffix.lower() == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(path)
            text = '\n'.join('PAGE %s\n%s' % (n + 1, p.extract_text() or '') for n, p in enumerate(reader.pages))
        else:
            text = raw.decode('utf-8-sig')
        dest = output / ('%02d-%s.txt' % (index, path.stem))
        dest.write_text('SOURCE: %s\nSOURCE_SHA256: %s\n\n%s' %
                        (path.relative_to(folder).as_posix(), digest(raw), text), encoding='utf-8')
        records.append({'source': str(path.relative_to(folder)), 'sha256': digest(raw),
                        'prepared': dest.name, 'prepared_sha256': digest(dest.read_bytes())})
        paths.append(str(dest))
    source_api = json.loads(Path(api_path).read_text(encoding='utf-8-sig'))
    api = expand_references(source_api, source_api)
    api['servers'] = [{'url': origin}]
    prepared_api = output / 'openapi.json'
    prepared_api.write_text(json.dumps(api, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {'case_folder': str(folder), 'mock_url': origin, 'documents': records,
                'source_api_sha256': digest(Path(api_path).read_bytes()),
                'prepared_api_sha256': digest(prepared_api.read_bytes()),
                'configuration_change': 'servers; local references expanded losslessly', 'manual_workflow_edits': False}
    (output / 'source-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return paths, prepared_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case_folder')
    parser.add_argument('--tool-api', required=True)
    parser.add_argument('--mock-url', required=True)
    parser.add_argument('--slot', default='final-case')
    parser.add_argument('--minutes', type=float, default=25)
    parser.add_argument('--prepare-only', action='store_true')
    args, extra = parser.parse_known_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.slot):
        parser.error('Invalid slot')
    root = Path(__file__).resolve().parent
    sources, api = prepare(args.case_folder, args.tool_api, args.mock_url,
                           root / '.state' / 'case-inputs' / args.slot)
    command = [sys.executable, '-X', 'utf8', '-B', str(root / 'builder.py'), *sources,
               '--tool-api', str(api), '--slot', args.slot, '--minutes', str(args.minutes),
               '--skip-tests', *extra]
    if args.prepare_only:
        print(json.dumps({'command': command, 'prepared_api': str(api)}, ensure_ascii=False))
        return 0
    return subprocess.call(command)


if __name__ == '__main__':
    raise SystemExit(main())
