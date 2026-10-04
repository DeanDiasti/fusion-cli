"""Fingerprint source at import time, so changing disk files cannot fake reload."""
import hashlib
from pathlib import Path

PROTOCOL=3


def fingerprint(root):
    digest=hashlib.sha256()
    for path in sorted(Path(root).rglob('*.py')):
        if 'agent' in path.relative_to(root).parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


BUILD=fingerprint(Path(__file__).resolve().parents[1])
