"""Installed-bridge playback gate using a persisted native storyboard fixture."""
import json
import math
from pathlib import Path
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from bridge_cli import call

report = {'transport': 'installed HTTP CLI dispatch', 'results': [], 'passed': False}
fixture = original = workspace = None


def run(command):
    result, status = call('fusion', {'command': command})
    passed = status < 400 and 'error' not in result
    report['results'].append({'command': command, 'passed': passed, 'result': result})
    if not passed:
        raise RuntimeError(str(result))
    return result


try:
    state = run('fusion app inspect')
    report['build'] = state['build']
    original = (state.get('document') or {}).get('id')
    workspace = state['workspace']
    archive = ROOT / 'tests/fixtures/native-camera-playback.f3d'
    imported = run('fusion documents import --path ' + shlex.quote(str(archive)))
    fixture = imported['document']['id']
    run('fusion workspace activate --workspace Publisher3DEnvironment')
    boards = run('fusion animation storyboards list')['storyboards']
    selected = next(board for board in boards if board['end_seconds'] > 0)
    selector = shlex.quote(selected['selector'])
    run('fusion animation storyboards activate --storyboard ' + selector)
    run('fusion animation playback seek --storyboard ' + selector + ' --seconds 0')
    started = run('fusion animation playback play --storyboard ' + selector + ' --from-current false')
    if not started['playing']:
        raise AssertionError('Playback did not start')
    deadline = time.monotonic() + selected['end_seconds'] + 5
    observed = []
    while time.monotonic() < deadline:
        status = run('fusion animation playback status --storyboard ' + selector)
        observed.append(status['playhead_seconds'])
        if not status['playing']:
            break
        time.sleep(.05)
    if status['playing'] or not math.isclose(status['playhead_seconds'], selected['end_seconds'], abs_tol=.05):
        raise AssertionError('Playback did not finish at the recorded end time')
    if not any(0 < value < selected['end_seconds'] for value in observed):
        raise AssertionError('No intermediate playback position observed')
    report.update(passed=True, duration_seconds=selected['end_seconds'], sampled_playhead_seconds=observed,
                  verification_scope='Native timeline playback; not component-action authoring.')
except Exception as exc:
    report['error'] = str(exc)
finally:
    try:
        if fixture:
            run('fusion documents close --document ' + shlex.quote(fixture) + ' --discard-changes')
        if original:
            run('fusion documents activate --document ' + shlex.quote(original))
        if workspace:
            run('fusion workspace activate --workspace ' + shlex.quote(workspace))
        after = run('fusion app inspect')
        report['original_document_restored'] = (after.get('document') or {}).get('id') == original
        report['original_workspace_restored'] = after.get('workspace') == workspace
        if not report['original_document_restored'] or not report['original_workspace_restored']:
            raise AssertionError('Original context was not restored')
    except Exception as exc:
        report.update(passed=False, cleanup_error=str(exc))
    output = Path('/tmp/cadbot-animation-playback-http.json')
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'error': report.get('error'), 'cleanup_error': report.get('cleanup_error')}))
sys.exit(0 if report['passed'] else 1)
