"""Bridge client used by unit tests (no Fusion required)."""

import json
import urllib.request

BRIDGE_URL = "http://localhost:8765"
TOKEN = "cadbot-dev-token"


def post_tool(tool, args=None):
    payload = json.dumps({"tool": tool, "args": args or {}}).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE_URL + "/tool",
        data=payload,
        headers={"Content-Type": "application/json", "X-CadBot-Token": TOKEN},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))
