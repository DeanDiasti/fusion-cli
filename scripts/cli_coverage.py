#!/usr/bin/env python3
"""Merge live evidence without treating older builds or failed gates as release proof."""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[1]
REPORTS = (
    'cadbot-design-motion-smoke.json', 'cadbot-design-motion-http.json',
    'cadbot-face-modeling-smoke.json', 'cadbot-face-modeling-http.json',
    'cadbot-admin-smoke.json', 'cadbot-cloud-smoke.json', 'cadbot-design-cli-smoke.json',
    'cadbot-design-expanded-http.json', 'cadbot-design-remaining.json',
    'cadbot-design-core-release.json', 'cadbot-design-extended-validation.json',
    'cadbot-admin-release-smoke.json', 'cadbot-animation-release-smoke.json',
    'cadbot-design-coverage-http.json', 'cadbot-design-sketch-curves-smoke.json',
    'cadbot-animation-playback-http.json', 'cadbot-release-policy-http.json',
)


def load(name):
    spec = importlib.util.spec_from_file_location('coverage_' + name, ROOT / 'fusion_addin/CadBot/bridge' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(previous, reports_dir):
    commands, build, coverage = load('commands'), load('build'), load('coverage')
    report = coverage.reconcile(previous, commands.SPECS, commands.EFFECTS, build.BUILD)
    rows = {row['command'][7:]: row for row in report['commands']}
    summaries = {r['source']: r for r in previous.get('reports', [])}
    for filename in REPORTS:
        path = reports_dir / filename
        if not path.exists():
            continue
        live = json.loads(path.read_text())
        evidence_build = live.get('build')
        summaries[filename] = {'source': filename, 'build': evidence_build,
                               'passed': live.get('passed') is True, 'case_count': len(live.get('results', []))}
        # Replace that report's earlier cases only for the same build.
        for row in rows.values():
            row['cases'] = [c for c in row['cases'] if not
                (c.get('source') == filename and c.get('build') == evidence_build)]
        for result in live.get('results', []):
            words = shlex.split(result.get('command', ''))
            if words[:1] == ['fusion']:
                words = words[1:]
            name, _ = commands.resolve(words)
            if name not in rows:
                continue
            blocked = bool(result.get('blocker_matched') or result.get('outcome') == 'capability_blocked')
            passed = result.get('passed') is True
            # Cleanup/geometry assertions can fail after an individual API call succeeds.
            if live.get('passed') is not True:
                passed = blocked = False
            case = {'source': filename, 'build': evidence_build, 'passed': passed,
                    'capability_blocked': blocked, 'transport': live.get('transport', 'native Fusion fixture')}
            if not passed and not blocked:
                case['error'] = str(result.get('error', live.get('error', 'Live gate failed or did not complete.')))[-1000:]
            rows[name]['cases'].append(case)
    report['reports'] = list(summaries.values())
    report.pop('latest_design_gate', None)
    report.pop('transport_note', None)
    return coverage.reconcile(report, commands.SPECS, commands.EFFECTS, build.BUILD)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports-dir', type=Path, default=Path('/tmp'))
    parser.add_argument('--write', action='store_true', help='Write both checked-in coverage snapshots; older evidence is retained.')
    args = parser.parse_args()
    path = ROOT / 'docs/cli-live-coverage.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    report = generate(previous, args.reports_dir)
    if args.write:
        content = json.dumps(report, indent=2) + '\n'
        path.write_text(content)
        (ROOT / 'fusion_addin/CadBot/bridge/coverage.json').write_text(content)
    print(json.dumps({key: report[key] for key in ('build', 'command_count', 'release_ready', 'section_summary')}, indent=2))


if __name__ == '__main__':
    main()
