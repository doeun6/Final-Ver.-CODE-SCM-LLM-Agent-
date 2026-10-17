"""Verify published bytes without network access or model calls."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
    failures = []
    for name, expected in manifest['files_sha256'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            failures.append({'file': name, 'error': 'invalid path'})
        elif not path.is_file():
            failures.append({'file': name, 'error': 'missing'})
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append({'file': name, 'error': 'hash mismatch'})
    print(json.dumps({'checked': len(manifest['files_sha256']),
                      'successful': not failures, 'failures': failures}, indent=2))
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
