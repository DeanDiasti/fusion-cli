"""Authenticated local Fusion client. Prefer scripts/fusion for terminal use.

Exit codes: 0 success, 1 bridge/tool failure, 2 invalid input.
"""
import json
import os
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

from command_catalog import load, source_root

BRIDGE_URL = os.environ.get('CADBOT_BRIDGE_URL', 'http://localhost:8765').rstrip('/')
TIMEOUT = 180
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


def load_token():
    explicit = os.environ.get('CADBOT_BRIDGE_TOKEN')
    if explicit:
        return explicit
    roots = [source_root(), Path.home() / 'Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/CadBot']
    for root in roots:
        try:
            token = (root / '.bridge_token').read_text().strip()
            if token:
                return token
        except FileNotFoundError:
            pass
    return 'cadbot-dev-token'


TOKEN = load_token()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request, timeout):
    # Local credentials must never be forwarded to a proxy or redirect target.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


def problem(code, message, **details):
    return {'error': message, 'status': code, **details}


def _request(path, payload=None, timeout=TIMEOUT):
    """Exactly one attempt: never replay a CAD mutation after a timeout."""
    try:
        parsed = urllib.parse.urlsplit(BRIDGE_URL)
        parsed.port  # Validate malformed ports before constructing a request.
    except ValueError:
        return problem('invalid_configuration', 'CADBOT_BRIDGE_URL must be a valid loopback HTTP origin.'), 400
    if (parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1')
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        return problem('invalid_configuration', 'CADBOT_BRIDGE_URL must be a loopback HTTP origin.'), 400
    data = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
    request = urllib.request.Request(BRIDGE_URL + path, data=data,
        headers={'Content-Type': 'application/json', 'X-CadBot-Token': TOKEN})
    try:
        with _open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        with exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
        status = exc.code
        if status in (401, 403):
            return problem('unauthorized', 'Fusion bridge rejected authentication. Check CADBOT_BRIDGE_TOKEN or reinstall the add-in.'), status
        if 300 <= status < 400:
            return problem('invalid_response', 'Fusion bridge redirects are not allowed.'), 502
    except (TimeoutError, socket.timeout):
        return problem('timeout', 'Fusion bridge timed out. The operation may still finish; inspect the design before retrying.'), 504
    except (urllib.error.URLError, OSError) as exc:
        if isinstance(getattr(exc, 'reason', None), (TimeoutError, socket.timeout)):
            return problem('timeout', 'Fusion bridge timed out. Inspect the design before retrying.'), 504
        return problem('bridge_unavailable', 'Cannot reach Fusion bridge at {}. Start Fusion and run CadBot. ({})'.format(BRIDGE_URL, exc)), 503
    if len(raw) > MAX_RESPONSE_BYTES:
        return problem('invalid_response', 'Fusion bridge response exceeded the size limit. Inspect before retrying.'), 502
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('expected an object')
    except (ValueError, UnicodeError):
        return problem('invalid_response', 'Fusion bridge returned an invalid JSON object. Inspect before retrying.'), 502
    if status >= 400 and 'error' not in result:
        result = problem('bridge_error', 'Fusion bridge returned HTTP {}.'.format(status), response=result)
    return result, status


def runtime_status():
    """Read-only build/protocol handshake with distinct connection diagnostics."""
    try:
        expected = load('build')
    except (OSError, RuntimeError) as exc:
        return problem('invalid_installation', str(exc)), 500
    running, status = _request('/ping', timeout=5)
    if status >= 400 or 'error' in running:
        return running, status
    if running.get('protocol') != expected.PROTOCOL or running.get('build') != expected.BUILD:
        return problem('stale_runtime', 'Fusion is running a different CadBot build. Reinstall and reload the add-in before executing commands.',
                       expected={'build': expected.BUILD, 'protocol': expected.PROTOCOL}, running=running), 409
    return {'status': 'ready', 'bridge_url': BRIDGE_URL, 'runtime': running}, 200


def verify_runtime():
    """Compatibility diagnostic for callers expecting a message or None."""
    result, status = runtime_status()
    return result.get('error') if status >= 400 else None


def call(tool, args):
    if not isinstance(tool, str) or not isinstance(args, dict):
        return problem('invalid_arguments', 'Provide a tool name and an argument object.'), 400
    if tool == 'fusion':
        try:
            handler, parsed, _ = load('commands').prepare(args)
        except (ValueError, TypeError) as exc:
            return problem('invalid_arguments', str(exc)), 400
        except (OSError, RuntimeError) as exc:
            return problem('invalid_installation', str(exc)), 500
        if handler is None:
            return {**parsed, 'source': 'local_catalog'}, 200
        runtime, status = runtime_status()
        if status >= 400:
            return runtime, status
    try:
        return _request('/tool', {'tool': tool, 'args': args})
    except (TypeError, ValueError) as exc:
        return problem('invalid_arguments', str(exc)), 400


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    try:
        args = json.loads(argv[2]) if len(argv) == 3 else {}
    except ValueError as exc:
        print(json.dumps(problem('invalid_arguments', 'Invalid JSON args: ' + str(exc))))
        return 2
    result, status = call(argv[1], args)
    print(json.dumps(result, indent=2))
    return 2 if status == 400 else 1 if status >= 400 or 'error' in result else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
