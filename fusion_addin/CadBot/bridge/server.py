"""
Local HTTP bridge for CadBot.

Runs on a background thread inside the Fusion process. Every request that
needs the adsk API is relayed through the Dispatcher so it executes on
Fusion's main thread.

Endpoints (all localhost-only, shared-token auth via X-CadBot-Token):
    GET  /ping    -> {"ok": true, "version": "..."}
    GET  /state   -> summary of the active design (components, bodies, params)
    POST /tool    -> {"tool": "<name>", "args": {...}} executes a registered tool
"""

import json
import os
import hmac
from .build import BUILD, PROTOCOL
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.6.0"
# Shared secret so random local processes can't drive Fusion.
# Overridable via CADBOT_BRIDGE_TOKEN; both sides must match.
TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".bridge_token"
)

_state = {"server": None, "token": None, "dispatcher": None, "tools": None}


_undo = None
MAX_REQUEST_BYTES = 1024 * 1024
_LEGACY_READS = {'get_state', 'measure_body', 'get_active_selection', 'list_features',
                 'list_parameters', 'list_timeline', 'list_sketches', 'inspect_sketch'}


def _checkpoint(args):
    global _undo
    action = args.get('action')
    required = {'action', 'id'} if action in ('begin', 'restore') else {'action'}
    if (action not in ('begin', 'finish', 'status', 'restore') or set(args) != required
            or ('id' in args and (not isinstance(args['id'], str) or not args['id'].strip()))):
        raise ValueError('Invalid checkpoint action or checkpoint ID.')
    if 'id' in args:
        from .commands import checkpoint_id
        checkpoint_id(args['id'])
    from .fusion_undo import FusionUndo
    if _undo is None:
        _undo = FusionUndo()
    if action == 'begin': return _undo.begin(args['id'])
    if action == 'finish': return _undo.finish()
    if action == 'status': return _undo.status()
    if action == 'restore': return _undo.restore(args['id'])
    raise ValueError('Unknown checkpoint action')


def _execute_tool(name, fn, args):
    if name == 'fusion':
        from .commands import prepare, resolve, EFFECTS
        import shlex
        handler, data, mutates = prepare(args)
        if handler is None: return data
        from tools.registry import _TOOL_MAP
        target = _TOOL_MAP[handler]
        words=shlex.split(args['command'])
        if words[:1]==['fusion']: words=words[1:]
        canonical, _depth=resolve(words)
        effect=EFFECTS[canonical]
        from .release_policy import refusal
        blocked = refusal(canonical)
        if blocked is not None:
            return blocked
        if effect in ('design_mutation','temporary_preview') or canonical in ('checkpoint begin','checkpoint restore'):
            import adsk.core
            workspace=adsk.core.Application.get().userInterface.activeWorkspace
            if workspace is None or workspace.id not in ('FusionSolidEnvironment','FusionSurfaceEnvironment',
                                                        'FusionSheetMetalEnvironment','TSplineEnvironment'):
                raise ValueError('Design editing requires a Design workspace. Use fusion workspace list and activate first.')
        expected_document=data.pop('document_id',None)
        if expected_document:
            import adsk.core
            active=adsk.core.Application.get().activeDocument
            if active is None or active.creationId != expected_document:
                raise ValueError('Active document changed. Inspect documents and retry with the intended document ID.')
        if handler == 'animation_actions_rotate':
            data['document_id'] = expected_document
        if effect in ('document_change','workspace_change','animation_change') and _undo is not None:
            _undo.invalidate('A '+effect.replace('_',' ')+' is outside Design checkpoints.')
        if mutates:
            if _undo is None or _undo.ledger is None or not _undo.ledger.active:
                raise RuntimeError('Editing commands require an active CLI checkpoint. Run fusion checkpoint begin --id <name> first.')
            if effect == 'temporary_preview':
                from tools import motion
                return _undo.preview(lambda a: motion.run_preview(target, a), data, motion.observe_axes)
            return _undo.execute(target, data)
        return target(data)
    if name not in _LEGACY_READS and name != '_checkpoint':
        raise ValueError('Use the structured fusion CLI; direct editing and administration tools are disabled.')
    return fn(args)


def _load_token():
    env = os.environ.get("CADBOT_BRIDGE_TOKEN")
    if env:
        return env
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError,):
        return "cadbot-dev-token"


class BridgeServer:
    def __init__(self, host, port, dispatcher):
        if host not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('CadBot bridge must bind to a loopback address.')
        self.host = host
        self.port = port
        _state["dispatcher"] = dispatcher
        _state["token"] = _load_token()
        # Bind on the startup thread so port conflicts reach the error dialog.
        self._server = ThreadingHTTPServer((host, port), _make_handler())
        _state["server"] = self._server

    def set_tools(self, tool_map):
        _state["tools"] = tool_map

    def serve_forever(self):
        self._server.serve_forever()

    def shutdown(self):
        server = _state.get("server")
        if server:
            server.shutdown()
            server.server_close()
            _state["server"] = None


def _make_handler():
    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def log_message(self, fmt, *args):  # quiet
            pass

        def _send_json(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            received = self.headers.get('X-CadBot-Token', '')
            expected = _state.get('token') or ''
            return bool(expected) and hmac.compare_digest(received.encode(), expected.encode())

        def do_GET(self):
            if not self._authorized():
                self._send_json(401, {"error": "Unauthorized"})
                return
            if self.path == "/ping":
                self._send_json(200, {"ok": True, "version": VERSION, "protocol":PROTOCOL,"build":BUILD})
            elif self.path == "/state":
                from tools import state as state_tool

                ok, result = _state["dispatcher"].call(state_tool.get_state)
                self._send_json(200 if ok else 500, result if ok else {"error": result["error"]})
            else:
                self._send_json(404, {"error": "Not found"})

        def do_POST(self):
            if not self._authorized():
                self._send_json(401, {"error": "Unauthorized"})
                return
            if self.path != "/tool":
                self._send_json(404, {"error": "Not found"})
                return
            try:
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Provide one Content-Length and no Transfer-Encoding.')
                length = int(lengths[0])
                if length <= 0:
                    raise ValueError('Content-Length must be positive.')
            except ValueError as exc:
                self._send_json(400, {'error': str(exc)})
                return
            if length > MAX_REQUEST_BYTES:
                self._send_json(413, {'error': 'Request body exceeds 1 MiB.'})
                return
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('Incomplete request body')
                payload = json.loads(raw)
            except (ValueError, UnicodeError, OSError):
                self._send_json(400, {"error": "Invalid JSON"})
                return
            if (not isinstance(payload, dict) or set(payload) - {'tool', 'args'}
                    or not isinstance(payload.get('tool'), str)
                    or not isinstance(payload.get('args', {}), dict)):
                self._send_json(400, {'error': 'Expected {tool: string, args: object}.'})
                return
            tool_name = payload['tool']
            args = payload.get('args', {})
            if tool_name not in _LEGACY_READS | {'fusion', '_checkpoint'}:
                self._send_json(400, {'error': 'Use the structured fusion CLI; direct editing and administration tools are disabled.'})
                return
            if tool_name == 'fusion':
                from .commands import prepare
                try:
                    prepare(args)
                except (ValueError, TypeError) as exc:
                    self._send_json(400, {'error': str(exc), 'status': 'invalid_arguments'})
                    return
            tools = _state.get("tools") or {}
            fn = _checkpoint if tool_name == '_checkpoint' else (lambda args: None) if tool_name == 'fusion' else tools.get(tool_name)
            if fn is None:
                self._send_json(400, {
                    "error": "Unknown tool: {}".format(tool_name),
                    "available": sorted(tools.keys()),
                })
                return
            ok, result = _state["dispatcher"].call(_execute_tool, tool_name, fn, args)
            if tool_name == 'fusion':
                from .commands import resolve, ALIASES, EFFECTS
                import shlex
                try:
                    words=shlex.split(args.get('command',''))
                    if words[:1]==['fusion']: words=words[1:]
                    canonical,depth=resolve(words)
                    original=' '.join(words[:depth])
                except (ValueError,AttributeError):
                    canonical,original=None,None
                if not isinstance(result,dict): result={'result':result}
                if not ok or 'error' in result:
                    result.setdefault('status','failed')
                else:
                    result.setdefault('status','completed')
                if result['status']=='completed' and result.get('cloud_complete') is False:
                    result['status']='pending'
                result['cli']={'command':'fusion '+canonical if canonical else None,
                               'effect':EFFECTS.get(canonical),'build':BUILD,'protocol':PROTOCOL}
                if original in ALIASES:
                    result['warnings']=result.get('warnings',[])+['Deprecated command. Use fusion '+canonical+'.']
            self._send_json(200 if ok else 500, result)

    return Handler
