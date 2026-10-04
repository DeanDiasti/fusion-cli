#!/usr/bin/env python3
"""Create public case summaries without publishing raw CAD/account metadata.

Requires passing raw gates for the current build. Commands retain their canonical
names; flags, entity tokens, cloud identifiers and raw tool results are withheld.
Publication never changes the gate's pass/fail disposition or fabricates cases.
"""
import argparse
import hashlib
import json
from pathlib import Path
from cli_coverage import REPORTS, ROOT, load
import shlex


def summarize(raw):
    grammar = load('commands')
    output = {k: v for k, v in raw.items() if type(v) in (bool, int, float)}
    for k in ('build', 'transport', 'fusion_version'):
        if k in raw:output[k] = raw[k]
    output['evidence_format'] = 'public_case_summary_v1'
    output['details_redacted'] = True
    output['results'] = []
    for result in raw.get('results', []):
        words = shlex.split(result.get('command', ''))
        if words[:1] == ['fusion']:words = words[1:]
        name, _ = grammar.resolve(words)
        row = {'command': 'fusion ' + name if name else 'fusion help',
               'passed': result.get('passed') is True}
        for key in ('blocker_matched', 'outcome'):
            if key in result:row[key] = result[key]
        if not row['passed'] and not result.get('blocker_matched'):
            row['error'] = 'Gate reported failure; raw details are private.'
        output['results'].append(row)
    if 'summary' in raw:
        output['summary'] = {k: v for k, v in raw['summary'].items() if type(v) in (bool, int, float)}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports-dir', type=Path, required=True)
    args = parser.parse_args()
    build = load('build').BUILD
    source = args.reports_dir.resolve()
    destination = ROOT / 'docs/public-evidence' / build
    if source == destination.resolve():raise ValueError('Do not summarize public reports again; use private raw gates.')
    staged = {}
    for filename in REPORTS:
        path = source / filename
        if not path.exists():continue
        raw = json.loads(path.read_text())
        if raw.get('build') != build:continue
        if raw.get('passed') is not True:raise ValueError('Gate failed: ' + filename)
        report = summarize(raw)
        report['raw_report_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        staged[filename] = report
    if not staged:raise ValueError('No passing current-build reports found.')
    destination.mkdir(parents=True, exist_ok=True)
    for filename, report in staged.items():
        (destination / filename).write_text(json.dumps(report, indent=2) + '\n')
    print('Published redacted summaries:', len(staged), 'reports in', destination.relative_to(ROOT))


if __name__ == '__main__':main()
