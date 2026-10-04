"""
CadBot — AI CAD agent add-in for Autodesk Fusion (formerly Fusion 360).

Entry point required by Fusion's add-in loader. Fusion calls run(context) to
start the add-in and stop(context) to stop it.

Responsibilities here are deliberately thin:
  - create the toolbar button and docked palette
  - start/stop the local HTTP bridge (which relays work to this thread)
All CAD operations live in bridge/tools and run on Fusion's main thread.
"""

import os
import json
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# Lightweight file logger — Fusion swallows Python errors silently for add-ins,
# so all failures are written to ~/cadbot_debug.log for diagnosis.
_LOG_PATH = os.path.join(os.path.expanduser("~"), "cadbot_debug.log")


def _log(msg):
    try:
        with open(_LOG_PATH, "a") as f:
            f.write("[CadBot {}] {}\n".format(datetime.now().isoformat(timespec="seconds"), msg))
    except Exception:
        pass


_log("module load begin")

import adsk.core  # noqa: E402
import adsk.fusion  # noqa: E402,F401  (registers adsk.fusion types)

_log("adsk imported ok")

# Make sibling modules importable regardless of how Fusion loads us.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

BridgeServer = None
Dispatcher = None
tool_registry = None
try:
    from chat import ChatSession
    from bridge.server import _load_token
    from bridge.server import BridgeServer  # noqa: E402
    from bridge.dispatch import Dispatcher  # noqa: E402
    from tools import registry as tool_registry  # noqa: E402
    _log("sibling modules imported ok from {}".format(_HERE))
except Exception:
    _log("sibling import FAILED:\n" + traceback.format_exc())

_app = None
_ui = None
_bridge = None
_bridge_thread = None
_dispatcher = None
_handlers = []
_palette = None
_chat = None
_lifecycle_handlers = []
_BUTTON_ID = "CadBotToggleCommand"


def run(context):
    global _app, _ui, _bridge, _bridge_thread, _dispatcher, _handlers, _palette, _chat
    _log("=== run() called ===")
    try:
        if _bridge is not None:
            _ensure_palette()
            return
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        _log("got app/ui")

        if BridgeServer is None or Dispatcher is None or tool_registry is None:
            raise RuntimeError(
                "CadBot modules failed to import at load time — see " + _LOG_PATH
            )

        # 1. Main-thread dispatcher: HTTP thread posts custom events here.
        _dispatcher = Dispatcher()
        _dispatcher.start()
        _log("dispatcher started")

        # 2. Register CAD tools against the dispatcher.
        tool_registry.register_all(_dispatcher)
        _log("tools registered")

        # 3. HTTP bridge (background thread; only relays to dispatcher).
        _bridge = BridgeServer(
            host="localhost",
            port=8765,
            dispatcher=_dispatcher,
        )
        _log("bridge server created")
        _bridge_thread = threading.Thread(
            target=_bridge.serve_forever, name="CadBotBridge", daemon=True
        )
        _bridge_thread.start()
        _log("bridge thread running on port 8765")

        # 4. Toolbar button.
        _create_toolbar_button()
        _log("toolbar button created")

        # Fusion restores its UI after loading startup add-ins; that can
        # invalidate palettes created during run(). Recreate after startup.
        startup_handler = _StartupCompletedHandler()
        _app.startupCompleted.add(startup_handler)
        _lifecycle_handlers.append((_app.startupCompleted, startup_handler))
        if not (isinstance(context, dict) and context.get("IsApplicationStartup")):
            _ensure_palette()
        else:
            _log("Waiting for Fusion startupCompleted before creating the palette")


    except (Exception,):
        failure = traceback.format_exc()
        _log("run() FAILED:\n" + failure)
        stop(context)
        if _ui:
            _ui.messageBox("CadBot failed to start:\n{}".format(failure))


def _delete_palette(palette):
    # Fusion can invalidate UI objects before calling stop during app shutdown.
    if palette is None or not palette.isValid:
        return
    if palette.isNative:
        _log("Skipping native palette; Fusion owns its lifetime")
        return
    palette.deleteMe()


def stop(context):
    global _bridge, _bridge_thread, _dispatcher, _palette, _handlers, _chat
    _log("=== stop() called ===")
    from bridge import server
    if server._undo is not None:
        try:
            server._undo.close()
        except Exception:
            _log("Checkpoint cleanup: " + traceback.format_exc())
        finally:
            server._undo = None
    palette, bridge, thread, dispatcher = _palette, _bridge, _bridge_thread, _dispatcher
    _palette = _bridge = _bridge_thread = _dispatcher = None

    # One stale UI object must not prevent the server or events from stopping.
    chat = _chat
    _chat = None
    for event, handler in _lifecycle_handlers:
        try:
            event.remove(handler)
        except Exception:
            _log("Could not detach lifecycle handler")
    _lifecycle_handlers.clear()
    steps = [("chat", lambda: chat.close() if chat else None),
             ("palette", lambda: _delete_palette(palette)),
             ("toolbar", _remove_toolbar_button)]
    if bridge is not None:
        steps.append(("bridge", bridge.shutdown))
    if thread is not None:
        steps.append(("bridge thread", lambda: thread.join(timeout=5)))
    if dispatcher is not None:
        steps.append(("dispatcher", dispatcher.stop))
    for name, cleanup in steps:
        try:
            cleanup()
        except Exception:
            _log("Cleanup failed for {}:\n{}".format(name, traceback.format_exc()))
    _handlers = []
    # Do not open modal dialogs while Fusion itself is closing.


def _create_toolbar_button():
    global _handlers
    try:
        cmd_defs = _ui.commandDefinitions
        cmd_def = cmd_defs.itemById(_BUTTON_ID)
        if cmd_def:
            cmd_def.deleteMe()
        cmd_def = cmd_defs.addButtonDefinition(
            _BUTTON_ID,
            "CadBot",
            "Show the CadBot AI chat palette",
            "",  # icon resource; palette shows anyway
        )
        on_command_created = _TogglePaletteCommandCreatedHandler()
        cmd_def.commandCreated.add(on_command_created)
        _handlers.append(on_command_created)
        panels = _ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        controls = panels.controls.addCommand(cmd_def)
        controls.isPromoted = True
    except (Exception,):
        _ui.messageBox("Failed to create CadBot toolbar button:\n{}".format(traceback.format_exc()))


def _remove_toolbar_button():
    global _handlers, _palette
    try:
        if _ui is None:
            return
        panel = _ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        control = panel.controls.itemById(_BUTTON_ID) if panel else None
        if control:
            control.deleteMe()
        cmd_def = _ui.commandDefinitions.itemById(_BUTTON_ID)
        if cmd_def:
            cmd_def.deleteMe()
        _handlers = []
    except (Exception,):
        pass


class _TogglePaletteCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            _ensure_palette()
        except Exception:
            _log("Show chat failed: " + traceback.format_exc())


class _ChatHTMLHandler(adsk.core.HTMLEventHandler):
    def notify(self, args):
        global _chat
        try:
            action = args.action
            if action != "poll":
                _log("HTML action: " + action)
            if action in ("ready", "reconnect"):
                if action == "reconnect" and _chat:
                    from bridge import server
                    if server._undo:
                        server._undo.invalidate('The agent connection was restarted.')
                    _chat.close()
                    _chat = None
                if _chat is None:
                    session = ChatSession(_load_token())
                    session.start()
                    _chat = session
                args.returnData = json.dumps({"ok": True})
            elif action == "poll":
                if _dispatcher is not None:
                    _dispatcher.drain()
                from bridge import server
                checkpoint_state = server._undo.status() if server._undo else {'available': [], 'reason': 'No checkpoints in this Fusion session.'}
                args.returnData = json.dumps({"events": _chat.poll() if _chat else [], "checkpoints": checkpoint_state})
            elif action in ("send", "cancel", "new", "login", "history", "open", "restore"):
                if _chat is None:
                    raise RuntimeError("Agent is not connected. Click Reconnect.")
                if len(args.data) > 30 * 1024 * 1024:
                    raise ValueError("Attachments are too large. Use up to 4 files, 5 MB each.")
                command = json.loads(args.data or "{}")
                command['action'] = action
                _chat.send(command)
                args.returnData = json.dumps({"ok": True})
            else:
                args.returnData = json.dumps({"error": "Unknown chat action"})
        except Exception as exc:
            _log("Chat error: " + traceback.format_exc())
            args.returnData = json.dumps({"error": str(exc)})


def _show_palette():
    # Keep chat within the main window instead of restoring screen coordinates
    # that may belong to a disconnected display or another macOS Space.
    if hasattr(_palette, "isDockedInCanvas"):
        _palette.isDockedInCanvas = False
    _palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
    _palette.width = 440
    _palette.isVisible = True
    _log("Palette visibility: visible={}, valid={}, native={}, url={}".format(
        _palette.isVisible, _palette.isValid, _palette.isNative, _palette.htmlFileURL))


class _StartupCompletedHandler(adsk.core.ApplicationEventHandler):
    def notify(self, args):
        try:
            _ensure_palette()
        except Exception:
            _log("Startup palette failed: " + traceback.format_exc())


def _ensure_palette():
    global _palette
    # Look up the live UI object rather than trusting a stale Python wrapper.
    palette = _ui.palettes.itemById("CadBotPalette")
    if palette is None or not palette.isValid:
        palette = _ui.palettes.add(
            "CadBotPalette", "CadBot", Path(_HERE, "palette", "index.html").as_uri(),
            False, True, True, 440, 650,
        )
        if palette is None:
            raise RuntimeError("Fusion could not create the CadBot chat palette")
        handler = _ChatHTMLHandler()
        palette.incomingFromHTML.add(handler)
        _handlers.append(handler)
        _log("Created new chat palette")
    _palette = palette
    _show_palette()
