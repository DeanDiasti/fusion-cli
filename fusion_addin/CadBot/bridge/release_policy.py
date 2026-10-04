"""Fail closed for command paths without safe native integration evidence.

Remove a restriction only after a disposable live fixture verifies its success
and rollback. Underlying adapters remain available for developing that fixture.
"""
_FORM_REASON = ('Form import and entity operations are unavailable in this release. '
                'A valid Fusion-emitted TSM fixture has not been verified; empty Form creation can block Fusion.')
RESTRICTIONS = {name: _FORM_REASON for name in (
    'design forms create-from-tsm', 'design forms inspect',
    'design forms rename', 'design forms delete')}
RESTRICTIONS['design configurations edit'] = (
    'Configuration cell editing is unavailable in this release. '
    'An editable-cell fixture and native rollback have not been verified.')


def refusal(command):
    reason = RESTRICTIONS.get(command)
    if reason is None:
        return None
    return {'status': 'blocked', 'writes_available': False,
            'error': {'code': 'release_capability_unavailable', 'message': reason},
            'command': 'fusion ' + command, 'changes': []}
