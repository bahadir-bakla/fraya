"""Verify a private-repo snapshot excludes credentials and nested environments."""
from pathlib import Path
import os
import re
import zipfile
import subprocess

from freya_dpapi_server import inject_credentials, unprotect

ROOT = Path(__file__).resolve().parents[1]


def main():
    inject_credentials()
    target = ROOT / 'fraya' if (ROOT / 'fraya').is_dir() else ROOT
    secrets = [os.environ[name].encode() for name in ('FREYA_API_KEY', 'FREYA_BANK_TEAM_KEY') if os.environ.get(name)]
    for filename in ('zep-key.dpapi', 'llm-proxy-key.dpapi'):
        secret_path = ROOT / '.local-secrets' / filename
        if secret_path.is_file() and os.name == 'nt':
            secrets.append(unprotect(secret_path).encode())
    problems, count = [], 0
    # Audit the exact shareable set; ignored local runtimes and DPAPI stores stay local.
    listing = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                             cwd=target, stdout=subprocess.PIPE, check=True).stdout
    for item in listing.split(b'\0'):
        if not item:
            continue
        path = target / os.fsdecode(item)
        relative = path.relative_to(target)
        if relative.parts[0] == '.git' or not path.is_file():
            continue
        if any(p in {'.git', '.venv', '.local-secrets', '__pycache__'} for p in relative.parts):
            problems.append(str(relative) + ': forbidden file tree')
        chunks = [path.read_bytes()]
        if path.suffix.lower() == '.docx':
            with zipfile.ZipFile(path) as archive:
                chunks += [archive.read(n) for n in archive.namelist() if n.endswith(('.xml', '.rels'))]
        for data in chunks:
            matches = re.findall(rb'fak_[A-Za-z0-9_-]{20,}', data)
            # This exact literal is a deliberately fake mocked-HTTP fixture;
            # actual supplied credentials are checked independently below.
            matches = [m for m in matches if m != b'fak_mock_do_not_use_0123456789']
            if any(secret in data for secret in secrets) or matches:
                problems.append(str(relative) + ': credential-like content; value withheld')
                break
        count += 1
    if problems:
        print('\n'.join(problems))
        raise SystemExit(1)
    print(f'{count} files checked; no credential matches, nested Git or virtual environments.')


if __name__ == '__main__':
    main()
