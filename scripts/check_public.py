#!/usr/bin/env python3
"""Check Git's publication list for private files and known sensitive markers.

Reports paths and marker categories, never the matched values. This check is a
publication guard, not a guarantee that every possible secret can be recognized.
Use Python 3.14+ to scan native Fusion archives containing ZIP Zstandard entries.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from public_files import is_public_path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'personal home path': re.compile(rb'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'personal email': re.compile(rb'[A-Za-z0-9._%+-]+@(?:gmail|hotmail|outlook)\.com', re.I),
    'cloud account identifier': re.compile(rb'a\.YnVzaW5lc3M[A-Za-z0-9_-]+'),
    'cloud file identifier': re.compile(rb'urn:adsk\.wipprod:[A-Za-z0-9_.:-]+'),
    'GitHub credential': re.compile(rb'gh[pousr]_[A-Za-z0-9]{20,}'),
    'OpenAI credential': re.compile(rb'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}


def scan_bytes(data):
    # Native Fusion archives can include UTF-16 metadata.
    views = (data, data.replace(b'\x00', b''))
    return [label for label, pattern in PATTERNS.items() if any(pattern.search(v) for v in views)]


def tracked_paths():
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True)
    return [Path(p) for p in result.stdout.decode().split('\0') if p]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', action='store_true', help='Check eligible source files before Git initialization.')
    args = parser.parse_args()
    paths = ([p.relative_to(ROOT) for p in ROOT.rglob('*') if p.is_file() and is_public_path(p.relative_to(ROOT))]
             if args.tree else tracked_paths())
    failures = []
    for relative in paths:
        if not is_public_path(relative):
            failures.append((str(relative), 'private/generated file'));continue
        path = ROOT / relative
        if path.is_symlink():
            failures.append((str(relative), 'symlink; publish regular reviewed files'));continue
        data = path.read_bytes()
        for marker in scan_bytes(data):failures.append((str(relative), marker))
        if path.suffix == '.f3d':
            try:
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        for marker in scan_bytes(archive.read(name)):
                            failures.append((str(relative) + '!' + name, marker))
            except NotImplementedError:
                failures.append((str(relative), 'archive compression unsupported; rerun with Python 3.14+'))
            except (zipfile.BadZipFile, RuntimeError):
                failures.append((str(relative), 'archive unreadable; contents were not scanned'))
    if failures:
        for path, marker in failures:print(path + ': ' + marker, file=sys.stderr)
        return 1
    print('Publication check passed:', len(paths), 'files; no prohibited files or known sensitive markers.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
