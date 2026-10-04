"""Verify CLI-only edit/restore through the installed bridge in a disposable design."""
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cli'))
from bridge_cli import call

report = {'transport': 'installed HTTP CLI dispatch without chat UI',
          'passed': False, 'results': [], 'original_model_touched': False}
fixture = original = workspace = None

def run(command):
    result, code = call('fusion', {'command': command})
    passed = code == 200 and 'error' not in result
    report['results'].append({'command': command, 'passed': passed, 'result': result})
    if not passed:
        raise RuntimeError(command + ': ' + repr(result))
    return result


def refuse(command, expected):
    result, code = call('fusion', {'command': command})
    assert code >= 400 and expected in str(result.get('error', '')), result

try:
    before = run('fusion app inspect')
    report['build'] = before['build']
    original = (before.get('document') or {}).get('id')
    workspace = before['workspace']
    fixture = run('fusion documents create --name FusionCli-Checkpoint-Fixture')['id']
    run('fusion workspace activate --workspace FusionSolidEnvironment')
    assert run('fusion design sketches list')['sketches'] == []
    refuse('fusion design sketches create --name Untracked', 'active CLI checkpoint')
    refuse('fusion checkpoint begin --id invalid --document-id wrong-document', 'Active document changed')
    command = 'fusion checkpoint begin --id plate --document-id ' + shlex.quote(fixture)
    assert run(command)['active_id'] == 'plate'
    run('fusion design sketches create --name Base')
    refuse('fusion checkpoint begin --id concurrent', 'already running')
    run('fusion design sketches rectangles add --sketch Base --x1-mm 0 --y1-mm 0 --x2-mm 20 --y2-mm 10')
    run('fusion design features extrude --sketch Base --distance-mm 5 --operation new')
    bodies = run('fusion design bodies list')['bodies']
    assert len(bodies) == 1
    measured = run('fusion design bodies measure --body ' + shlex.quote(bodies[0]['name']))
    assert measured['volume_cm3'] == 1.0 and measured['size_mm'] == [20.0,10.0,5.0], measured
    assert run('fusion checkpoint status')['active_id'] == 'plate'
    refuse('fusion checkpoint restore --id plate', 'Finish')
    assert run('fusion checkpoint finish')['available'] == ['plate']
    refuse('fusion checkpoint begin --id plate', 'Duplicate')
    refuse('fusion design sketches create --name Untracked', 'active CLI checkpoint')
    refuse('fusion checkpoint restore --id plate --document-id wrong-document', 'Active document changed')
    restored = run('fusion checkpoint restore --id plate --document-id ' + shlex.quote(fixture))
    assert restored['transactions_undone'] == 3, restored
    assert run('fusion design bodies list')['bodies'] == []
    assert run('fusion design sketches list')['sketches'] == []
    assert run('fusion checkpoint status')['available'] == []
    refuse('fusion checkpoint restore --id plate', 'not available')
    report.update(geometry_verified=True, undo_verified=True, guards_verified=True)
    report['passed'] = True
except Exception as exc:
    report['error'] = str(exc)
finally:
    try:
        if fixture:
            run('fusion checkpoint finish')
            run('fusion documents close --document ' + shlex.quote(fixture) + ' --discard-changes')
            report['fixture_closed'] = True
        if original:
            run('fusion documents activate --document ' + shlex.quote(original))
        if workspace:
            run('fusion workspace activate --workspace ' + shlex.quote(workspace))
        after = run('fusion app inspect')
        report['original_document_restored'] = (after.get('document') or {}).get('id') == original
        report['original_workspace_restored'] = after.get('workspace') == workspace
        assert report['original_document_restored'] and report['original_workspace_restored']
    except Exception as exc:
        report['passed'] = False
        report['cleanup_error'] = str(exc)
Path('/tmp/cadbot-cli-checkpoints-http.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': report['passed'], 'error': report.get('error'),
                  'cleanup_error': report.get('cleanup_error')}))
sys.exit(0 if report['passed'] else 1)
