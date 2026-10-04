"""Fingerprint source at import time, so changing disk files cannot fake reload."""
import hashlib
from pathlib import Path

PROTOCOL=4


def fingerprint(root):
    digest=hashlib.sha256()
    paths = list(Path(root).rglob('*.py'))
    pump = Path(root) / 'bridge' / 'dispatch.html'
    if pump.is_file():
        paths.append(pump)
    for path in sorted(paths):
        if 'cli' in path.relative_to(root).parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


BUILD=fingerprint(Path(__file__).resolve().parents[1])
