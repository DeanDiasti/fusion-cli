"""Autodesk Fusion CLI bridge.

Fusion calls run/stop on its main thread. HTTP requests are dispatched through
custom events; CAD operations never run on the HTTP thread.
"""
import threading
import traceback
import sys
from pathlib import Path
import adsk.core
import adsk.fusion

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from bridge.server import BridgeServer
from bridge.dispatch import Dispatcher
from tools import registry as tool_registry

_app = _ui = _bridge = _bridge_thread = _dispatcher = None
_startup_handler = None


def _start_bridge():
    global _bridge, _bridge_thread, _dispatcher
    if _bridge is not None:
        return
    try:
        _dispatcher = Dispatcher()
        _dispatcher.start()
        tool_registry.register_all(_dispatcher)
        _bridge = BridgeServer('localhost', 8765, _dispatcher)
        _bridge_thread = threading.Thread(target=_bridge.serve_forever,
                                         name='FusionCliBridge', daemon=True)
        _bridge_thread.start()
    except Exception:
        error = traceback.format_exc()
        stop(None)
        _ui.messageBox('Fusion CLI bridge failed to start:\n' + error)


def run(context):
    global _app, _ui, _startup_handler
    if _bridge is not None or _startup_handler is not None:
        return
    _app = adsk.core.Application.get()
    _ui = _app.userInterface
    if not _app.isStartupComplete:
        _startup_handler = _StartupCompletedHandler()
        _app.startupCompleted.add(_startup_handler)
    else:
        _start_bridge()


def stop(context):
    global _bridge, _bridge_thread, _dispatcher, _startup_handler
    from bridge import server
    if server._undo is not None:
        try:
            server._undo.close()
        except Exception:
            pass
        finally:
            server._undo = None
    if _startup_handler is not None:
        try:
            _app.startupCompleted.remove(_startup_handler)
        except Exception:
            pass
        _startup_handler = None
    bridge, thread, dispatcher = _bridge, _bridge_thread, _dispatcher
    _bridge = _bridge_thread = _dispatcher = None
    # A failed cleanup must not prevent the remaining owned resources stopping.
    for cleanup in (lambda: bridge.shutdown() if bridge else None,
                    lambda: thread.join(timeout=5) if thread else None,
                    lambda: dispatcher.stop() if dispatcher else None):
        try:
            cleanup()
        except Exception:
            pass


class _StartupCompletedHandler(adsk.core.ApplicationEventHandler):
    def notify(self, args):
        global _startup_handler
        if _startup_handler is not None:
            _app.startupCompleted.remove(_startup_handler)
            _startup_handler = None
        _start_bridge()
