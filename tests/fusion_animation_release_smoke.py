"""Live native-Animation CLI gate using an unsaved disposable document.

Run from Fusion's Text Commands Python console after reloading CadBot.  It
dispatches the same finite command grammar and handlers used by the bridge,
records command/expected/actual evidence, and restores the user's document and
workspace without saving the fixture.
"""
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import traceback
import types

import adsk.core
import adsk.fusion


ROOT = Path(__file__).resolve().parents[1] / "fusion_addin" / "CadBot"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(ROOT))
from tools import animation, animation_entities as entities, animation_actions
from bridge import commands as grammar

report = {"transport": "native source CLI dispatch", "results": []}

HANDLERS = {
    "animation_components_list": entities.list_occurrences,
    "animation_component_inspect": entities.inspect_component,
    "animation_playback_status": animation.playback_status,
    "animation_playback_full_screen": animation.playback_full_screen,
    "animation_camera_recording": animation.camera_recording,
    "animation_settings_inspect": animation.settings_inspect,
    "animation_settings_recording_mode": animation.settings_recording_mode,
    "animation_settings_watermark": animation.settings_watermark,
    "animation_authoring_capabilities": animation.authoring_capabilities,
    "camera_inspect": animation.camera_inspect,
    "animation_actions_rotate": animation_actions.rotate,
}


def run(parts, expected=None, allow_failure=False, expected_error=None):
    command = shlex.join(["fusion", *parts])
    row = {"command": command, "expected": expected}
    try:
        handler, args, _ = grammar.prepare({"command": command})
        function = HANDLERS.get(handler, getattr(animation, handler, None))
        if function is None:
            raise RuntimeError("No live-gate handler for {}".format(handler))
        actual = function(args)
        row["actual"] = actual
        if expected_error:
            if actual.get('error', {}).get('code') != expected_error:
                raise AssertionError('Expected explicit capability blocker: ' + expected_error)
            row.update(outcome='capability_blocked', blocker_matched=True)
        elif 'error' in actual:
            raise AssertionError(str(actual['error']))
        if expected:
            for key, value in expected.items():
                if actual.get(key) != value:
                    raise AssertionError("Expected {}={!r}, got {!r}".format(
                        key, value, actual.get(key)))
        row["passed"] = True
        return actual
    except Exception:
        row["error"] = traceback.format_exc()
        row["passed"] = False
        if not allow_failure:
            raise
        return None
    finally:
        report["results"].append(row)


app = adsk.core.Application.get()
ui = app.userInterface
original = app.activeDocument
original_workspace = ui.activeWorkspace
fixture = None
try:
    fixture = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    fixture.name = "CadBot-Native-Animation-Release"
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.DirectDesignType
    occurrence = design.rootComponent.occurrences.addNewComponent(
        adsk.core.Matrix3D.create())
    occurrence.component.name = "AnimationGateComponent"
    box = adsk.core.OrientedBoundingBox3D.create(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Vector3D.create(1, 0, 0),
        adsk.core.Vector3D.create(0, 1, 0), 2, 2, 2)
    occurrence.component.bRepBodies.add(
        adsk.fusion.TemporaryBRepManager.get().createBox(box))

    manager = design.animationManager
    if not manager.activateAnimationWorkspace():
        raise RuntimeError("Animation workspace activation failed")
    adsk.doEvents()

    run(["animation", "authoring", "capabilities"],
        {"authoring_status": "blocked_unverified_private_adapter"})
    run(["animation", "settings", "inspect"])
    for mode in ("time-zero", "overlap-half-second", "sequential"):
        run(["animation", "settings", "recording-mode", "--mode", mode],
            {"recording_mode": mode})
    run(["animation", "settings", "watermark", "--enabled", "true"],
        {"watermark_shown": True})
    run(["animation", "settings", "watermark", "--enabled", "false"],
        {"watermark_shown": False})

    listed = run(["animation", "storyboards", "list"])
    first = listed["storyboards"][0]["selector"] if listed["storyboards"] else None
    if first is None:
        first = run(["animation", "storyboards", "create"])["storyboards"][-1]["selector"]
    created = run(["animation", "storyboards", "create", "--from-previous"])
    second = created["storyboards"][-1]["selector"]
    run(["animation", "storyboards", "activate", "--storyboard", first])
    copied = run(["animation", "storyboards", "copy", "--storyboard", first,
                  "--name", "CadBot Release Copy", "--target-storyboard", second,
                  "--before", "true"])
    copy_selector = next(item["selector"] for item in copied["storyboards"]
                         if item["selector"] not in (first, second))
    run(["animation", "storyboards", "move", "--storyboard", copy_selector,
         "--target-storyboard", second, "--before", "false"])
    run(["animation", "storyboards", "reverse", "--storyboard", copy_selector])
    run(["animation", "playback", "seek", "--storyboard", copy_selector,
         "--seconds", "0"], {"playhead_seconds": 0.0})
    run(["animation", "playback", "status", "--storyboard", copy_selector])
    run(["animation", "playback", "full-screen", "--storyboard", copy_selector,
         "--enabled", "true"], {"full_screen": True})
    run(["animation", "playback", "full-screen", "--storyboard", copy_selector,
         "--enabled", "false"], {"full_screen": False})
    run(["animation", "camera", "recording", "--storyboard", copy_selector,
         "--enabled", "true"], {"view_recording": True})
    run(["animation", "camera", "recording", "--storyboard", copy_selector,
         "--enabled", "false"], {"view_recording": False})
    components = run(["animation", "components", "list"])
    component = components["occurrences"][0]["selector"]
    run(["animation", "components", "inspect", "--component", component])
    run(["animation", "camera", "inspect", "--storyboard", copy_selector])

    run(["animation", "storyboards", "activate", "--storyboard", copy_selector])
    rotation = ["animation", "actions", "rotate", "--document-id", fixture.creationId,
                "--storyboard", copy_selector, "--component", component, "--axis", "x",
                "--degrees", "10", "--pivot-mm", "[0,0,0]", "--start", "0", "--end", "1"]
    run(rotation + ['--dry-run'], {'status': 'planned', 'animation_created': False})
    run(rotation, {'status': 'blocked', 'animation_created': False},
        expected_error='native_animation_backend_unverified')

    # Positive playback is verified by live_animation_playback_http.py using
    # a persisted nonempty native storyboard, outside this synchronous UI call.
    run(["animation", "storyboards", "delete", "--storyboard", copy_selector])
    report["passed"] = all(row["passed"] for row in report["results"])

except Exception:
    report["passed"] = False
    report["error"] = traceback.format_exc()
finally:
    try:
        if fixture and fixture.isValid:
            fixture.close(False)
        if original and original.isValid:
            original.activate()
        if original_workspace:
            original_workspace.activate()
    except Exception:
        report["cleanup_error"] = traceback.format_exc()
        report["passed"] = False
    report["original_document_restored"] = bool(
        original and original.isValid and app.activeDocument == original)
    report["original_workspace_restored"] = bool(
        original_workspace and ui.activeWorkspace == original_workspace)
    output = Path("/tmp/cadbot-animation-release-smoke.json")
    output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print("CadBot Animation release gate: {} passed={}".format(
        output, report.get("passed")))
