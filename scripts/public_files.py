"""Shared publication boundaries, independent of Git or a developer's checkout."""
from pathlib import PurePosixPath

PRIVATE_TESTS = {'fusion_animation_rotation_fixture.py', 'fusion_admin_smoke.py',
                 'fusion_cloud_smoke.py', 'fusion_commands_smoke.py', 'fusion_motion_smoke.py'}


def is_public_path(path):
    path = PurePosixPath(str(path).replace('\\', '/'))
    if any(p in {'.git', '.venv', 'venv', '__pycache__', '.codex', '.agents', 'node_modules'} for p in path.parts):
        return False
    if path.name in {'.bridge_token', 'runtime_config.json', 'auth.json', '.DS_Store'}:
        return False
    if path.name.startswith('.env') and path.name != '.env.example':
        return False
    if path.suffix in {'.pyc', '.pyo', '.log', '.pem', '.key'}:
        return False
    if path.parts[:2] == ('docs', 'release-evidence') or str(path) == 'docs/native-animation-authoring-proof.md':
        return False
    if path.parts[:1] == ('tests',) and (path.name.endswith('_probe.py') or path.name in PRIVATE_TESTS):
        return False
    return True
