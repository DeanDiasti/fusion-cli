#!/usr/bin/env python3
"""Exercise the installed expanded Design CLI through its authenticated bridge.

The fixture is an unsaved disposable document. The original active document and
workspace are restored, and the fixture is closed without saving.
"""

import json
import os
import shlex
import sys
import urllib.error
import urllib.request
from pathlib import Path


URL = os.environ.get("CADBOT_BRIDGE_URL", "http://localhost:8765")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cli'))
from bridge_cli import TOKEN
REPORT = Path("/tmp/cadbot-design-expanded-http.json")
rows = []


def post(tool, args):
    request = urllib.request.Request(
        URL + "/tool",
        data=json.dumps({"tool": tool, "args": args}).encode(),
        headers={"Content-Type": "application/json", "X-CadBot-Token": TOKEN},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def fusion(command, required=True):
    result = post("fusion", {"command": command})
    passed = result.get("status") in ("completed", "pending") and "error" not in result
    rows.append({"command": command, "passed": passed, "result": result})
    if required and not passed:
        raise RuntimeError(command + ": " + str(result.get("error", result)))
    return result


def quote(value):
    return shlex.quote(str(value))


fixture = None
original_document = None
original_workspace = None
report = {"transport": "installed HTTP CLI dispatch", "results": rows}
try:
    app = fusion("fusion app inspect")
    report['build'] = app['build']
    original_document = (app.get("document") or {}).get("id")
    original_workspace = app.get("workspace")
    created = fusion("fusion documents create --name CadBot-Expanded-Design-Fixture")
    fixture = created.get("id")
    fusion("fusion workspace activate --workspace FusionSolidEnvironment")
    fusion("fusion design capabilities")
    post("_checkpoint", {"action": "begin", "id": "expanded-design-smoke"})
    fusion("fusion design sketches create --name Layout")
    line = fusion("fusion design sketches lines add --sketch Layout --x1-mm 0 --y1-mm 0 --x2-mm 20 --y2-mm 0")["line"]
    line_token = quote(line["token"])
    fusion("fusion design sketches geometry construction --sketch Layout --entity " + line_token + " --construction true")
    fusion("fusion design sketches geometry construction --sketch Layout --entity " + line_token + " --construction false")
    constraint = fusion("fusion design sketches constraints add --sketch Layout --type horizontal --entity " + line_token)["constraint"]
    fusion("fusion design sketches constraints list --sketch Layout")
    fusion("fusion design sketches constraints delete --sketch Layout --constraint " + quote(constraint["token"]))
    circle = fusion("fusion design sketches circles add --sketch Layout --center-x-mm 10 --center-y-mm 10 --radius-mm 4")["circle"]
    fusion("fusion design sketches circles edit --sketch Layout --entity " + quote(circle["token"]) + " --center-x-mm 12 --center-y-mm 10 --radius-mm 5")
    fusion("fusion design sketches geometry list --sketch Layout")

    fusion("fusion design sketches create --name SolidBase")
    fusion("fusion design sketches rectangles add --sketch SolidBase --x1-mm 0 --y1-mm 0 --x2-mm 20 --y2-mm 15")
    fusion("fusion design features extrude --sketch SolidBase --distance-mm 10 --operation new")
    features = fusion("fusion design features list")["features"]
    feature = quote(features[-1]["token"])
    fusion("fusion design features inspect --feature " + feature)
    fusion("fusion design features rename --feature " + feature + " --name MainExtrude")
    fusion("fusion design features suppress --feature " + feature)
    fusion("fusion design features unsuppress --feature " + feature)
    body = fusion("fusion design bodies list")["bodies"][0]
    body_token = quote(body["token"])
    fusion("fusion design bodies inspect --body " + body_token)
    fusion("fusion design bodies rename --body " + body_token + " --name MainBody")
    fusion("fusion design parameters create --name smokeSize --expression '12 mm' --unit mm")
    fusion("fusion design parameters delete --name smokeSize")
    plane = fusion("fusion design construction planes create-offset --reference origin:xy-plane --offset '25 mm' --name SmokePlane")
    plane_token = quote(plane["token"])
    fusion("fusion design construction inspect --construction " + plane_token)
    fusion("fusion design construction set-parameter --construction " + plane_token + " --parameter offset --expression '30 mm'")
    fusion("fusion design construction hide --construction " + plane_token)
    fusion("fusion design construction show --construction " + plane_token)
    fusion("fusion design construction delete --construction " + plane_token)
    fusion("fusion design selection add --entity " + body_token)
    fusion("fusion design selection clear")
    fusion("fusion design solid-features capabilities")
    fusion("fusion design solid-features list")
    mirror = fusion("fusion design mirrors create --entity-type body --entities '[" + json.dumps(body["token"]) + "]' --plane YZ --combine false")
    mirror_token = quote(mirror["token"])
    fusion("fusion design solid-features inspect --feature " + mirror_token + " --family mirror")
    fusion("fusion design solid-features delete --feature " + mirror_token + " --family mirror")

    first = fusion("fusion design components create --name LinkA")["created"]
    second = fusion("fusion design components create --name LinkB")["created"]
    first_occurrence, second_occurrence = quote(first["selector"]), quote(second["selector"])
    fusion("fusion design occurrences inspect --occurrence " + first_occurrence)
    fusion("fusion design occurrences ground --occurrence " + first_occurrence)
    fusion("fusion design occurrences unground --occurrence " + first_occurrence)
    joint = fusion("fusion design joints create --occurrence-one " + first_occurrence +
                   " --occurrence-two " + second_occurrence + " --type revolute --axis z --name SmokeJoint")["created"]
    joint_token = quote(joint["selector"])
    fusion("fusion design joints inspect --joint " + joint_token)
    fusion("fusion design joints limits set --joint " + joint_token + " --axis rotation --minimum -15 --maximum 15 --rest 0")
    fusion("fusion design joints limits clear --joint " + joint_token + " --axis rotation --minimum --maximum --rest")
    fusion("fusion design joints lock --joint " + joint_token)
    fusion("fusion design joints unlock --joint " + joint_token)
    fusion("fusion design joints delete --joint " + joint_token)
    fusion("fusion design sheet-metal flat-pattern inspect --component " + quote(first["component_selector"]))
    fusion("fusion design occurrences delete --occurrence " + first_occurrence)
    fusion("fusion design occurrences delete --occurrence " + second_occurrence)

    fusion("fusion design surfaces list")
    fusion("fusion design meshes list")
    mesh = fusion("fusion design meshes create-triangles --coordinates-mm '[0,0,0,10,0,0,0,10,0]' --indices '[0,1,2]' --name SmokeMesh")["token"]
    fusion("fusion design meshes inspect --mesh " + quote(mesh))
    fusion("fusion design meshes edit --mesh " + quote(mesh) + " --visible false --opacity 0.5")
    fusion("fusion design meshes delete --mesh " + quote(mesh))
    fusion("fusion design forms list")
    fusion("fusion design sheet-metal capabilities")
    fusion("fusion design sheet-metal inspect")
    fusion("fusion design sheet-metal features list")
    fusion("fusion design sheet-metal rules list", required=False)
    fusion("fusion design materials libraries")
    fusion("fusion design materials list")
    fusion("fusion design configurations list")
    timeline = fusion("fusion design timeline list")
    if timeline.get("count", 0) >= 2:
        group = fusion("fusion design timeline groups create --start 0 --end 1 --name SmokeGroup")
        fusion("fusion design timeline groups inspect --group " + str(group["index"]))
        fusion("fusion design timeline groups collapse --group " + str(group["index"]))
        fusion("fusion design timeline groups expand --group " + str(group["index"]))
        fusion("fusion design timeline groups delete-keep --group " + str(group["index"]))
    fusion("fusion design diagnostics")
    post("_checkpoint", {"action": "finish"})
    report["passed"] = all(row["passed"] for row in rows if row["command"] != "fusion design sheet-metal rules list")
except Exception as exc:
    report["passed"] = False
    report["error"] = repr(exc)
finally:
    try:
        post("_checkpoint", {"action": "finish"})
    except Exception:
        pass
    if fixture:
        fusion("fusion documents close --document " + quote(fixture) + " --discard-changes", required=False)
    if original_document:
        fusion("fusion documents activate --document " + quote(original_document), required=False)
    if original_workspace:
        fusion("fusion workspace activate --workspace " + quote(original_workspace), required=False)
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report.get("passed"), "rows": len(rows), "report": str(REPORT)}))

sys.exit(0 if report.get("passed") else 1)
