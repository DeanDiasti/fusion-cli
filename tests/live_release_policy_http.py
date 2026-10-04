"""Verify release refusals over HTTP without opening or changing documents."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cli'))
from bridge_cli import call

commands = (
    'fusion design forms create-from-tsm --tsm-description fixture',
    'fusion design forms inspect --form fixture',
    'fusion design forms rename --form fixture --name test',
    'fusion design forms delete --form fixture',
    'fusion design configurations edit --configuration fixture --column-index 0 --expression "12 mm"',
)
report = {'transport': 'installed HTTP CLI dispatch', 'passed': False, 'results': []}
try:
    before, status = call('fusion', {'command': 'fusion app inspect'})
    assert status == 200 and 'error' not in before, before
    report['build'] = before['build']
    for command in commands:
        result, status = call('fusion', {'command': command})
        matched = (result.get('status') == 'blocked' and result.get('changes') == []
                   and result.get('error', {}).get('code') == 'release_capability_unavailable')
        report['results'].append({'command': command, 'result': result, 'http_status': status,
                                 'passed': False, 'blocker_matched': matched,
                                 'outcome': 'capability_blocked' if matched else 'failed'})
        assert matched, result
    after, status = call('fusion', {'command': 'fusion app inspect'})
    assert status == 200 and before['document'] == after['document'] and before['workspace'] == after['workspace']
    report['passed'] = True
except Exception as exc:
    report['error'] = str(exc)
(Path('/tmp') / 'cadbot-release-policy-http.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': report['passed'], 'error': report.get('error')}))
sys.exit(0 if report['passed'] else 1)
