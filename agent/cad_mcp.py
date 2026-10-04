"""Minimal stdio MCP adapter for the existing authenticated Fusion bridge."""
import json
import sys
from bridge_cli import call


def tool_specs():
    return [{"name":"fusion", "description":"Run one structured Fusion CLI command inside Fusion. Start with `fusion app inspect`; discover supported operations using `fusion help`, `fusion help <namespace>`, and full-command `--help`. Use `fusion design ...` for modeling and joint previews; use `fusion animation ...` only for native persistent storyboards. No shell, scripts, Python, or arbitrary API access. Lengths are millimeters, angles degrees, names with spaces require quoting, and list flags use JSON arrays. Inspect stable IDs/selectors before mutation and independently verify results. Design edits are tracked by message checkpoints; document, workspace, cloud, and native Animation changes are not Design-undo steps.",
        "inputSchema":{"type":"object","properties":{"command":{"type":"string","minLength":1,"maxLength":20000}},"required":["command"],"additionalProperties":False},
        "annotations":{"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False}}]


def respond(request):
    method = request.get('method')
    if method == 'initialize':
        return {'protocolVersion': request.get('params', {}).get('protocolVersion', '2024-11-05'),
                'capabilities': {'tools': {}}, 'serverInfo': {'name': 'cadbot', 'version': '0.2.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': tool_specs()}
    if method == 'tools/call':
        params = request.get('params', {})
        name = params.get('name')
        if name not in {t['name'] for t in tool_specs()}:
            raise ValueError('Unknown CAD tool')
        result, status = call(name, params.get('arguments') or {})
        # Images are returned as MCP image content, not megabytes of base64 text.
        image = result.pop('png_base64', None) if isinstance(result, dict) else None
        content = [{'type': 'text', 'text': json.dumps(result)}]
        if image:
            content.append({'type': 'image', 'mimeType': 'image/png', 'data': image})
        return {'content': content, 'isError': status >= 400 or 'error' in result}
    raise ValueError('Unsupported method: ' + str(method))


def main():
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            if 'id' not in request:
                continue
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': respond(request)}
        except Exception as exc:
            response = {'jsonrpc': '2.0', 'id': request.get('id') if isinstance(request, dict) else None,
                        'error': {'code': -32603, 'message': str(exc)}}
        print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
