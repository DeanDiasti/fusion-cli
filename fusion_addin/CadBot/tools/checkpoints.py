"""Explicit CLI controls for verified, session-only Design undo boundaries."""


def _call(action, args):
    from bridge.server import _checkpoint
    return _checkpoint({'action': action, **args})


def begin(args): return _call('begin', args)
def finish(args): return _call('finish', args)
def status(args): return _call('status', args)
def restore(args): return _call('restore', args)
