"""Live gate for every previously unverified core Design command.

Run from Fusion's Scripts and Add-Ins dialog after reloading CadBot.  Every
recorded case is parsed by the public CLI grammar and then sent to the exact
registered typed handler.  The gate uses one unsaved disposable document,
restores the active document/workspace/selection, and writes auditable
expected/actual evidence to /tmp/cadbot-design-core-release.json.
"""

import json
import shlex
import sys
import tempfile
import traceback
from pathlib import Path

import adsk.core
import adsk.fusion


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fusion_addin" / "CadBot"))
from bridge import commands  # noqa: E402
from tools import motion, registry  # noqa: E402


REPORT = Path("/tmp/cadbot-design-core-release.json")
TARGETS = {
    "design inspect", "design reset", "design assembly instances",
    "design joints list", "design joints drive", "design motion open",
    "design motion check", "design motion render", "design bodies delete",
    "design bodies combine", "design selection list", "design parameters list",
    "design parameters set", "design sketches circle", "design sketches line",
    "design sketches dimension", "design features delete-one",
    "design features revolve", "design features chamfer",
    "design features circular-pattern", "design features rectangular-pattern",
    "design features delete", "design viewport screenshot",
    "design sketches delete", "design sketches lines edit",
    "design sketches geometry fixed", "design sketches geometry delete",
    "design sketches dimensions list", "design sketches dimensions set",
    "design sketches dimensions delete", "design components list",
    "design components inspect", "design components rename",
    "design components delete", "design occurrences list",
    "design occurrences create", "design occurrences transform",
    "design joints edit", "design joints suppress",
    "design joints unsuppress", "design joints flip", "design joints unflip",
    "design construction list", "design construction planes create-midplane",
    "design construction planes create-three-points",
    "design construction planes create-angle",
    "design construction axes create-two-points",
    "design construction axes create-two-planes",
    "design construction axes create-edge",
    "design construction points create-on-entity",
    "design construction points create-center", "design construction rename",
    "design timeline inspect", "design timeline roll",
    "design timeline beginning", "design timeline end",
    "design timeline groups list", "design timeline groups rename",
    "design timeline groups delete-contents", "design selection remove",
    "design solid-features edit", "design holes create",
    "design shells create", "design drafts create",
}


rows = []
covered = set()


def quote(value):
    return shlex.quote(str(value))


def jquote(value):
    return quote(json.dumps(value, separators=(",", ":")))


def command_name(command):
    words = shlex.split(command)
    if words[:1] == ["fusion"]:
        words = words[1:]
    name, _ = commands.resolve(words)
    return name


def contains(expected, actual):
    if callable(expected):
        return bool(expected(actual))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(contains(value, candidate) for candidate in actual)
            for value in expected
        )
    return expected == actual


def evidence_value(value):
    """Convert predicate-based expectations into stable JSON evidence."""
    if callable(value):
        return {"predicate": getattr(value, "__name__", "callable")}
    if isinstance(value, dict):
        return {key: evidence_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [evidence_value(item) for item in value]
    return value


def execute(command, preview=False):
    handler_name, args, _mutates = commands.prepare({"command": command})
    handler = registry._TOOL_MAP[handler_name]
    return motion.run_preview(handler, args) if preview else handler(args)


def record(command, expected, preview=False):
    name = command_name(command)
    if name not in TARGETS:
        raise AssertionError("Unexpected target command: " + str(name))
    row = {"command": command, "expected": evidence_value(expected), "handler": None}
    try:
        handler_name, _args, _mutates = commands.prepare({"command": command})
        row["handler"] = handler_name
        actual = execute(command, preview=preview)
        row["actual"] = actual
        row["passed"] = contains(expected, actual)
        if not row["passed"]:
            raise AssertionError("Actual result did not contain expected evidence")
        covered.add(name)
        return actual
    except Exception:
        row.setdefault("actual", {"error": traceback.format_exc()})
        row["validation_error"] = traceback.format_exc()
        row["passed"] = False
        raise
    finally:
        rows.append(row)


def setup(command):
    """Use typed commands for fixture setup without claiming an extra case."""
    return execute(command)


def point(x, y, z=0):
    return adsk.core.Point3D.create(x, y, z)


def rectangle(sketch, x1, y1, x2, y2):
    return sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        point(x1, y1), point(x2, y2))


def make_box(root, name, x1, y1, x2, y2, height_cm):
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = name + "Sketch"
    rectangle(sketch, x1, y1, x2, y2)
    feature_input = root.features.extrudeFeatures.createInput(
        sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    feature_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(height_cm))
    feature = root.features.extrudeFeatures.add(feature_input)
    feature.name = name + "Extrude"
    feature.bodies.item(0).name = name
    return feature.bodies.item(0), feature


app = adsk.core.Application.get()
ui = app.userInterface
original_document = app.activeDocument
original_workspace = ui.activeWorkspace
fixture = None
generated_paths = []
report = {
    "transport": "native source CLI dispatch",
    "fixture": "unsaved disposable Fusion design",
    "results": rows,
    "target_count": len(TARGETS),
    "original_model_touched": False,
}

try:
    fixture = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    fixture.name = "CadBot-Core-Design-Release-Fixture"
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = design.rootComponent
    ui.activeSelections.clear()

    # State, legacy sketch operations, dimensions, parameters, and selection.
    record("fusion design inspect", {"body_count": 0, "bodies": []})
    setup("fusion design sketches create --name ResetVictim")
    record("fusion design reset", {"reset": True})
    if root.sketches.count:
        raise AssertionError("Design reset left its disposable sketch behind")
    legacy = setup("fusion design sketches create --name LegacySketch")
    record("fusion design sketches circle --sketch LegacySketch --center-x 5 --center-y 5 --radius 3",
           {"curve_index": 0})
    record("fusion design sketches line --sketch LegacySketch --x1 0 --y1 0 --x2 10 --y2 0",
           {"curve_count": 2})
    record("fusion design sketches dimension --sketch LegacySketch --target circle_diameter --curve-index 0 --value-mm 8",
           {"value_mm": 8.0})
    core_parameter = setup(
        "fusion design parameters create --name coreSize --expression '8 mm' --unit mm")
    record("fusion design parameters list", {"document": fixture.name,
                                               "parameters": lambda value: len(value) > 0})
    change = [{"name": core_parameter["name"],
               "expected_expression": core_parameter["expression"],
               "expression": "9 mm"}]
    record("fusion design parameters set --document {} --changes {}".format(
        quote(fixture.name), jquote(change)), {"changes": [{"after": "9 mm"}]})

    editable = setup("fusion design sketches lines add --sketch LegacySketch --x1-mm 0 --y1-mm 12 --x2-mm 10 --y2-mm 12")["line"]
    token = editable["token"]
    record("fusion design sketches lines edit --sketch LegacySketch --entity {} --x1-mm 0 --y1-mm 13 --x2-mm 12 --y2-mm 13".format(quote(token)),
           {"line": {"length_mm": 12.0}})
    record("fusion design sketches geometry fixed --sketch LegacySketch --entity {} --fixed true".format(quote(token)),
           {"geometry": {"fixed": True}})
    record("fusion design sketches geometry fixed --sketch LegacySketch --entity {} --fixed false".format(quote(token)),
           {"geometry": {"fixed": False}})
    dimension_rows = record("fusion design sketches dimensions list --sketch LegacySketch",
                            {"dimensions": lambda value: len(value) > 0})["dimensions"]
    dim = dimension_rows[0]
    record("fusion design sketches dimensions set --sketch LegacySketch --dimension {} --expression '10 mm' --expected-expression {}".format(
        quote(dim["token"]), quote(dim["expression"])),
        {"dimension": {"expression": "10 mm"}})
    record("fusion design sketches dimensions delete --sketch LegacySketch --dimension {}".format(quote(dim["token"])),
           {"deleted": {"token": dim["token"]}})
    delete_line = setup("fusion design sketches lines add --sketch LegacySketch --x1-mm 0 --y1-mm 15 --x2-mm 5 --y2-mm 15")["line"]
    record("fusion design sketches geometry delete --sketch LegacySketch --entity " + quote(delete_line["token"]),
           {"deleted": {"type": "SketchLine"}})
    setup("fusion design sketches create --name DeleteSketch")
    record("fusion design sketches delete --sketch DeleteSketch",
           {"deleted": "DeleteSketch"})

    body_a, feature_a = make_box(root, "Target", 0, 0, 2, 2, 1)
    body_b, _ = make_box(root, "Tool", 1, 0, 3, 2, 1)
    record("fusion design selection list", {"selections": []})
    setup("fusion design selection add --entity " + quote(body_a.entityToken))
    record("fusion design selection remove --entity " + quote(body_a.entityToken),
           {"selection_count": 0, "removed": body_a.entityToken})
    record("fusion design bodies combine --target {} --tools {} --operation join".format(
        quote(body_a.entityToken), jquote([body_b.entityToken])),
        {"operation": "join", "remaining_bodies": lambda value: value >= 1})
    doomed, _ = make_box(root, "Doomed", 5, 0, 6, 1, 1)
    record("fusion design bodies delete --body " + quote(doomed.entityToken),
           {"deleted": {"name": "Doomed"}})

    # Legacy solid feature families and both deletion APIs.
    rev_sketch = root.sketches.add(root.xYConstructionPlane)
    rev_sketch.name = "RevolveProfile"
    rectangle(rev_sketch, 3, 1, 4, 2)
    record("fusion design features revolve --sketch RevolveProfile --axis X --angle-deg 180",
           {"feature": lambda value: bool(value)})
    pattern_source, _ = make_box(root, "PatternSource", 8, 0, 9, 1, 1)
    record("fusion design features circular-pattern --body {} --count 3 --axis Z --angle-deg 180".format(quote(pattern_source.name)),
           {"feature": lambda value: bool(value)})
    rect_source, _ = make_box(root, "RectPatternSource", 12, 0, 13, 1, 1)
    record("fusion design features rectangular-pattern --body {} --direction-x-count 2 --direction-y-count 2 --spacing-x-mm 20 --spacing-y-mm 20".format(quote(rect_source.name)),
           {"feature": lambda value: bool(value)})
    chamfer_source, _ = make_box(root, "ChamferSource", 16, 0, 18, 2, 2)
    record("fusion design features chamfer --body {} --distance-mm 1 --edge-indices '[0]'".format(quote(chamfer_source.name)),
           {"feature": lambda value: bool(value)})
    delete_one_body, delete_one_feature = make_box(root, "DeleteOne", 20, 0, 21, 1, 1)
    del delete_one_body
    record("fusion design features delete-one --feature " + quote(delete_one_feature.entityToken),
           {"deleted": {"name": delete_one_feature.name}})
    delete_many_body, delete_many_feature = make_box(root, "DeleteMany", 22, 0, 23, 1, 1)
    del delete_many_body
    record("fusion design features delete --names " + jquote([delete_many_feature.name]),
           {"deleted": [delete_many_feature.name], "failed": []})

    # Components, occurrences, joints, and the older motion selectors.
    first = setup("fusion design components create --name LinkA")["created"]
    second = setup("fusion design components create --name LinkB")["created"]
    record("fusion design components list", {"components": [{"name": "LinkA"}]})
    record("fusion design components inspect --component " + quote(first["component_selector"]),
           {"name": "LinkA", "selector": first["component_selector"]})
    record("fusion design components rename --component {} --name LinkRenamed".format(
        quote(first["component_selector"])), {"after": "LinkRenamed"})
    record("fusion design occurrences list", {"occurrences": [{"path": lambda value: bool(value)}]})
    extra = record("fusion design occurrences create --component " + quote(first["component_selector"]),
                   {"created": {"component": "LinkRenamed"}})["created"]
    matrix = [1, 0, 0, 25, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    record("fusion design occurrences transform --occurrence {} --matrix {}".format(
        quote(extra["selector"]), jquote(matrix)), {"matrix": matrix})
    joint = setup("fusion design joints create --occurrence-one {} --occurrence-two {} --type revolute --axis z --name CoreJoint".format(
        quote(first["selector"]), quote(second["selector"])))["created"]
    joint_selector = joint["selector"]
    edited_joint = record("fusion design joints edit --joint {} --name CoreJointEdited --type revolute --axis z".format(quote(joint_selector)),
                          {"changed": {"name": {"after": "CoreJointEdited"}, "type": "revolute"}})
    joint_selector = edited_joint["current"]["selector"]
    record("fusion design joints suppress --joint " + quote(joint_selector),
           {"changed": {"suppressed": True}})
    record("fusion design joints unsuppress --joint " + quote(joint_selector),
           {"changed": {"suppressed": False}})
    record("fusion design joints flip --joint " + quote(joint_selector),
           {"changed": {"flipped": True}})
    record("fusion design joints unflip --joint " + quote(joint_selector),
           {"changed": {"flipped": False}})
    record("fusion design assembly instances", {"instances": lambda value: len(value) >= 3})
    legacy_joints = record("fusion design joints list", {"joints": [{"name": "CoreJointEdited"}]})["joints"]
    motion_joint = next(value for value in legacy_joints if value["name"] == "CoreJointEdited")
    motion_selector = motion_joint["name"]
    record("fusion design joints drive --joint {} --axis rotation --value 5".format(quote(motion_selector)),
           {"axis": "rotation", "value": lambda value: abs(value - 5) < 0.05})
    tracks = [{"joint": motion_selector, "axis": "rotation", "keys": [[0, 0], [1, 10]]}]
    record("fusion design motion check --tracks " + jquote(tracks),
           {"samples": lambda value: len(value) == 5}, preview=True)
    rendered = record("fusion design motion render --tracks {} --fps 1 --seconds 1".format(jquote(tracks)),
                      {"frames": 2, "format": lambda value: "HTML" in value}, preview=True)
    generated_paths.append(Path(rendered["path"]).parent)
    record("fusion design motion open --path " + quote(rendered["path"]),
           {"opened": str(Path(rendered["path"]).resolve())})

    delete_component = setup("fusion design components create --name DeleteComponent")["created"]
    record("fusion design components delete --component " + quote(delete_component["component_selector"]),
           {"deleted_component": "DeleteComponent"})

    # Construction geometry uses exact tokens from native fixture entities.
    geo = root.sketches.add(root.xYConstructionPlane)
    geo.name = "ConstructionRefs"
    circle = geo.sketchCurves.sketchCircles.addByCenterRadius(point(30, 0), 2)
    edge_line = geo.sketchCurves.sketchLines.addByTwoPoints(point(26, 0), point(28, 0))
    p1 = geo.sketchPoints.add(point(26, 2))
    p2 = geo.sketchPoints.add(point(28, 2))
    p3 = geo.sketchPoints.add(point(27, 4))
    offset = setup("fusion design construction planes create-offset --reference origin:xy-plane --offset '10 mm' --name OffsetRef")
    midpoint = record("fusion design construction planes create-midplane --first origin:xy-plane --second {} --name MidPlane".format(quote(offset["token"])),
                      {"name": "MidPlane", "kind": "plane"})
    record("fusion design construction planes create-three-points --first {} --second {} --third {} --name ThreePointPlane".format(
        quote(p1.entityToken), quote(p2.entityToken), quote(p3.entityToken)),
        {"name": "ThreePointPlane", "kind": "plane"})
    angle_plane = record("fusion design construction planes create-angle --axis origin:x-axis --reference origin:xy-plane --angle '30 deg' --name AnglePlane",
                         {"name": "AnglePlane", "kind": "plane"})
    record("fusion design construction axes create-two-points --first {} --second {} --name PointAxis".format(
        quote(p1.entityToken), quote(p2.entityToken)), {"name": "PointAxis", "kind": "axis"})
    record("fusion design construction axes create-two-planes --first origin:xy-plane --second origin:yz-plane --name PlaneAxis",
           {"name": "PlaneAxis", "kind": "axis"})
    record("fusion design construction axes create-edge --edge {} --name EdgeAxis".format(quote(edge_line.entityToken)),
           {"name": "EdgeAxis", "kind": "axis"})
    record("fusion design construction points create-on-entity --point {} --name OnEntity".format(quote(p1.entityToken)),
           {"name": "OnEntity", "kind": "point"})
    record("fusion design construction points create-center --circular-entity {} --name CircleCenter".format(quote(circle.entityToken)),
           {"name": "CircleCenter", "kind": "point"})
    record("fusion design construction rename --construction {} --kind plane --name RenamedAnglePlane".format(quote(angle_plane["token"])),
           {"name": "RenamedAnglePlane"})
    record("fusion design construction list", {"construction": [{"name": "RenamedAnglePlane"}]})

    # Solid feature create/edit paths. Use separate simple bodies so topology
    # changes cannot invalidate later selectors.
    hole_base, _ = make_box(root, "HoleBase", 34, 0, 38, 4, 2)
    hole_sketch = root.sketches.add(root.xYConstructionPlane)
    hole_sketch.name = "HolePoints"
    hole_point = hole_sketch.sketchPoints.add(point(36, 2))
    hole_point_index = next(
        index for index in range(hole_sketch.sketchPoints.count)
        if hole_sketch.sketchPoints.item(index).entityToken == hole_point.entityToken)
    hole = record("fusion design holes create --sketch HolePoints --point-index {} --diameter-mm 4 --depth-mm 10 --reverse true --name CoreHole".format(hole_point_index),
                  {"family": "hole", "name": "CoreHole"})
    record("fusion design solid-features edit --feature {} --family hole --name CoreHoleEdited --expressions '{{}}'".format(quote(hole["token"])),
           {"name": "CoreHoleEdited", "changes": {"name": {"after": "CoreHoleEdited"}}})
    shell_body, _ = make_box(root, "ShellBase", 40, 0, 44, 4, 2)
    record("fusion design shells create --body {} --remove-face-indices '[1]' --inside-mm 1".format(quote(shell_body.entityToken)),
           {"family": "shell"})
    draft_body, _ = make_box(root, "DraftBase", 46, 0, 50, 4, 2)
    draft_index = next(
        index for index in range(draft_body.faces.count)
        if hasattr(draft_body.faces.item(index).geometry, "normal")
        and abs(float(draft_body.faces.item(index).geometry.normal.z)) < 0.1)
    record("fusion design drafts create --body {} --face-indices {} --angle-deg 2 --plane XY".format(
        quote(draft_body.entityToken), jquote([draft_index])),
           {"family": "draft"})

    # Timeline inspection and controls, including destructive group deletion.
    timeline = design.timeline
    record("fusion design timeline inspect --index 0", {"item": {"index": 0}})
    record("fusion design timeline roll --position 1", {"marker_position": 1})
    record("fusion design timeline beginning", {"marker_position": 0})
    record("fusion design timeline end", {"marker_position": int(timeline.count)})
    group = setup("fusion design timeline groups create --start 0 --end 1 --name CoreGroup")
    record("fusion design timeline groups list", {"groups": [{"name": "CoreGroup"}]})
    record("fusion design timeline groups rename --group {} --name RenamedCoreGroup".format(group["index"]),
           {"name": "RenamedCoreGroup"})
    delete_group_a = root.sketches.add(root.xYConstructionPlane)
    delete_group_a.name = "DeleteGroupA"
    delete_group_b = root.sketches.add(root.xYConstructionPlane)
    delete_group_b.name = "DeleteGroupB"
    destructive_group = setup(
        "fusion design timeline groups create --start {} --end {} --name DeleteContents".format(
            delete_group_a.timelineObject.index, delete_group_b.timelineObject.index))
    record("fusion design timeline groups delete-contents --group " + str(destructive_group["index"]),
           {"deleted_group": {"name": "DeleteContents"}, "contents_kept": False})

    screenshot = Path(tempfile.gettempdir()) / "cadbot-design-core-release.png"
    generated_paths.append(screenshot)
    record("fusion design viewport screenshot --path " + quote(screenshot),
           {"path": str(screenshot), "png_base64": lambda value: len(value) > 100})

    missing = sorted(TARGETS - covered)
    extra = sorted(covered - TARGETS)
    if missing or extra:
        raise AssertionError("Coverage mismatch: missing={} extra={}".format(missing, extra))
    report["passed"] = all(row["passed"] for row in rows)
    report["covered_commands"] = sorted(covered)
except Exception:
    report["passed"] = False
    report["error"] = traceback.format_exc()
finally:
    cleanup_errors = []
    try:
        ui.activeSelections.clear()
    except Exception:
        cleanup_errors.append(traceback.format_exc())
    try:
        if fixture and fixture.isValid:
            fixture.close(False)
    except Exception:
        cleanup_errors.append(traceback.format_exc())
    try:
        if original_document and original_document.isValid:
            original_document.activate()
        if original_workspace:
            original_workspace.activate()
    except Exception:
        cleanup_errors.append(traceback.format_exc())
    for path in generated_paths:
        try:
            if path.is_dir():
                for child in path.iterdir():
                    child.unlink()
                path.rmdir()
            elif path.exists():
                path.unlink()
        except Exception:
            cleanup_errors.append(traceback.format_exc())
    report["fixture_closed"] = not (fixture and fixture.isValid)
    report["original_document_restored"] = bool(
        not original_document or not original_document.isValid
        or app.activeDocument == original_document)
    if cleanup_errors:
        report["cleanup_errors"] = cleanup_errors
        report["passed"] = False
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print("Core Design release gate: {} passed={} cases={}/{}".format(
        REPORT, report.get("passed"), len(covered), len(TARGETS)))
