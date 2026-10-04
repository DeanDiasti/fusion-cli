#!/usr/bin/env python3
"""Run local release checks and verify durable evidence for the exact source tree.

This does not operate Fusion or create cloud fixtures. Use --runtime to also
check that the running add-in matches. See docs/release-0.6.0.md for live gates.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from cli_coverage import ROOT, generate, load
from public_files import is_public_path


def source_hashes():
    paths = []
    for directory in ('cli', 'fusion_addin/CadBot', 'scripts', 'tests'):
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and not p.name.startswith('.')
                     and p.suffix not in ('.pyc', '.log')
                     and p.name not in ('coverage.json', 'runtime_config.json')
                     and is_public_path(p.relative_to(ROOT)))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def verify_evidence(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    build = load('build').BUILD
    if manifest['build'] != build:
        raise ValueError('Live evidence belongs to another add-in build; rerun live gates.')
    if manifest['source_sha256'] != source_hashes():
        raise ValueError('Source, fixture, or test files changed since certification; rerun the affected checks and refresh evidence.')
    for filename, digest in manifest['reports_sha256'].items():
        path = directory / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Live evidence changed: ' + filename)
        live = json.loads(path.read_text())
        if live.get('build') != build or live.get('passed') is not True:
            raise ValueError('Live gate failed or is stale: ' + filename)
    current = generate({}, directory)
    if not current['release_ready']:
        raise ValueError('Current build has failed or unverified command cases.')
    saved = json.loads((ROOT / 'docs/cli-live-coverage.json').read_text())
    packaged = json.loads((ROOT / 'fusion_addin/CadBot/bridge/coverage.json').read_text())
    expected = {r['command']: r['validation'] for r in current['commands']}
    if saved != packaged or saved.get('build') != build or not saved.get('release_ready') \
            or {r['command']: r['validation'] for r in saved['commands']} != expected:
        raise ValueError('Coverage snapshots do not match the durable live evidence.')
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'docs/public-evidence' / load('build').BUILD
    try:
        report = verify_evidence(directory)
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'], cwd=ROOT, check=True)
        subprocess.run(['node', 'tests/test_motion_player.cjs'], cwd=ROOT, check=True)
        if args.runtime:
            subprocess.run([sys.executable, 'cli/fusion_cli.py', 'doctor'], cwd=ROOT, check=True)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print('Release check failed: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps({'passed': True, 'build': report['build'], 'command_count': report['command_count'],
                      'section_summary': report['section_summary'], 'scope': report['release_scope']}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
