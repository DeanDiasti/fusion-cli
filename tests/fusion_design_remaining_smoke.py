"""Live Fusion gate for the remaining Design selector paths.

Run this file from Fusion's Scripts and Add-Ins dialog after reloading CadBot.
It creates an unsaved disposable design, never reads or mutates the user's model,
and writes command/expected/actual evidence to /tmp.
"""
import json
import sys
import traceback
from pathlib import Path

import adsk.core
import adsk.fusion


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fusion_addin" / "CadBot"))
from tools import design_assemblies as assemblies  # noqa: E402
from tools import design_extended as extended  # noqa: E402
from tools import design_sheet_metal as sheet_metal  # noqa: E402
from tools import design_solids as solids  # noqa: E402


REPORT = Path("/tmp/cadbot-design-remaining.json")
rows = []


def matches(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(matches(value, candidate) for candidate in actual)
            for value in expected)
    return expected == actual


def record(command, expected, function):
    row = {"command": command, "expected": expected}
    try:
        actual = function()
        row["actual"] = actual
        row["passed"] = matches(expected, actual)
        if not row["passed"]:
            raise AssertionError("Actual result did not contain expected values")
        return actual
    except Exception:
        if "actual" in row:
            row["validation_error"] = traceback.format_exc()
        else:
            row["actual"] = {"error": traceback.format_exc()}
        row["passed"] = False
        raise
    finally:
        rows.append(row)


def point(x, y, z=0):
    return adsk.core.Point3D.create(x, y, z)


def add_component_box(root, name, x):
    occurrence = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occurrence.component.name = name
    temporary = adsk.fusion.TemporaryBRepManager.get().createBox(
        adsk.core.OrientedBoundingBox3D.create(
            point(x, 0, 0), adsk.core.Vector3D.create(1, 0, 0),
            adsk.core.Vector3D.create(0, 1, 0), 1, 1, 1))
    occurrence.component.bRepBodies.add(temporary)
    return occurrence


def add_circle_sketch(root, name, z):
    plane_input = root.constructionPlanes.createInput()
    plane_input.setByOffset(root.xYConstructionPlane,
                            adsk.core.ValueInput.createByReal(z))
    plane = root.constructionPlanes.add(plane_input)
    sketch = root.sketches.add(plane)
    sketch.name = name
    sketch.sketchCurves.sketchCircles.addByCenterRadius(point(0, 0), 1)
    return sketch


app = adsk.core.Application.get()
original = app.activeDocument
original_workspace = app.userInterface.activeWorkspace
fixture = None
report = {"transport": "native Fusion disposable fixture", "results": rows,
          "fixture": "CadBot-Remaining-Design-Fixture", "original_model_touched": False}
try:
    fixture = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    fixture.name = "CadBot-Remaining-Design-Fixture"
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.DirectDesignType
    root = design.rootComponent

    first = add_component_box(root, "JointBoxA", 0)
    second = add_component_box(root, "JointBoxB", 3)
    first_selector = assemblies.selector_for("occurrence", first)
    second_selector = assemblies.selector_for("occurrence", second)
    first_geometry = record(
        "fusion design joints geometry list --occurrence " + first_selector,
        {"geometry": [{"kind": "origin"}, {"kind": "face"},
                      {"kind": "edge"}, {"kind": "vertex"}]},
        lambda: assemblies.joint_geometry_list({"occurrence": first_selector}))
    second_geometry = assemblies.joint_geometry_list({"occurrence": second_selector})
    by_kind_one = {item["kind"]: item for item in first_geometry["geometry"]}
    by_kind_two = {item["kind"]: item for item in second_geometry["geometry"]}
    for kind, keypoint in (("face", "center"), ("edge", "middle"),
                           ("vertex", "center")):
        command = "fusion design joints create --occurrence-one {} --occurrence-two {} --type rigid --geometry-one {} --geometry-two {} --keypoint-one {} --keypoint-two {}".format(
            first_selector, second_selector, by_kind_one[kind]["token"],
            by_kind_two[kind]["token"], keypoint, keypoint)
        created = record(command, {"geometry": {"one": kind, "two": kind}},
                         lambda kind=kind, keypoint=keypoint: assemblies.joints_create({
                             "occurrence_one": first_selector,
                             "occurrence_two": second_selector, "type": "rigid",
                             "geometry_one": by_kind_one[kind]["token"],
                             "geometry_two": by_kind_two[kind]["token"],
                             "keypoint_one": keypoint, "keypoint_two": keypoint}))
        assemblies.joints_delete({"joint": created["created"]["selector"]})

    section_a = add_circle_sketch(root, "LoftSectionA", 0)
    section_b = add_circle_sketch(root, "LoftSectionB", 3)
    rail_sketch = root.sketches.add(root.xYConstructionPlane)
    rail_sketch.is3D = True
    rail_sketch.name = "LoftRail"
    rail = rail_sketch.sketchCurves.sketchLines.addByTwoPoints(
        point(1, 0, 0), point(1, 0, 3))
    centerline = rail_sketch.sketchCurves.sketchLines.addByTwoPoints(
        point(0, 0, 0), point(0, 0, 3))
    loft = record(
        "fusion design lofts create --sketches '[\"LoftSectionA\",\"LoftSectionB\"]' --rails '[{{\"token\":\"{}\"}}]'".format(rail.entityToken),
        {"family": "loft", "guides": {"rail_count": 1, "centerline": False}},
        lambda: solids.lofts_create({"sketches": [section_a.entityToken,
                                                   section_b.entityToken],
                                     "rails": [{"token": rail.entityToken}]}))
    loft_rename_command = (
        "fusion design solid-features edit --feature {} --family loft "
        "--name CoverageRailLoft".format(loft["token"]))
    try:
        solids.solid_feature_edit({"feature": loft["token"],
                                   "family": "loft",
                                   "name": "CoverageRailLoft"})
        raise AssertionError("Installed Fusion unexpectedly accepted a loft feature rename")
    except RuntimeError as exc:
        if "did not apply the feature name" not in str(exc):
            raise
        rows.append({
            "command": loft_rename_command,
            "outcome": "capability_blocked",
            "blocker_matched": True,
            "passed": False,
            "actual": {"error": str(exc)},
        })
    solids.solid_feature_delete({"feature": loft["token"], "family": "loft"})
    record(
        "fusion design lofts create --sketches '[\"LoftSectionA\",\"LoftSectionB\"]' --centerline '{{\"token\":\"{}\"}}'".format(centerline.entityToken),
        {"family": "loft", "guides": {"rail_count": 0, "centerline": True}},
        lambda: solids.lofts_create({"sketches": [section_a.entityToken,
                                                   section_b.entityToken],
                                     "centerline": {"token": centerline.entityToken}}))

    profile = root.sketches.add(root.yZConstructionPlane)
    profile.name = "SweepProfile"
    profile.sketchCurves.sketchCircles.addByCenterRadius(point(0, 0), 0.5)
    paths = root.sketches.add(root.xYConstructionPlane)
    paths.name = "SweepPaths"
    path_curve = paths.sketchCurves.sketchLines.addByTwoPoints(point(0, 0), point(5, 0))
    guide_curve = paths.sketchCurves.sketchLines.addByTwoPoints(point(0, 0.5), point(5, 0.5))
    record(
        "fusion design sweeps create --profile-sketch SweepProfile --path-entity {} --guide-rail '{{\"token\":\"{}\"}}'".format(
            path_curve.entityToken, guide_curve.entityToken),
        {"family": "sweep", "path_selector": "entity_token", "guide_rail": True},
        lambda: solids.sweeps_create({"profile_sketch": profile.entityToken,
                                      "path_entity": path_curve.entityToken,
                                      "guide_rail": {"token": guide_curve.entityToken}}))

    surface_sketch = root.sketches.add(root.xYConstructionPlane)
    surface_sketch.name = "CoverageSurface"
    surface_sketch.sketchCurves.sketchLines.addTwoPointRectangle(point(8, 0), point(10, 2))
    surface = record(
        "fusion design surfaces patch --sketch CoverageSurface",
        {"surfaces": [{}]},
        lambda: extended.surfaces_patch({"sketch": surface_sketch.entityToken}))
    surface_token = surface["surfaces"][-1]["token"]
    record("fusion design surfaces inspect --surface " + surface_token,
           {"token": surface_token, "solid": False},
           lambda: extended.surfaces_inspect({"surface": surface_token}))
    record("fusion design surfaces delete --surface " + surface_token,
           {"deleted": surface_token},
           lambda: extended.surfaces_delete({"surface": surface_token}))
    surface2 = extended.surfaces_patch({"sketch": surface_sketch.entityToken})
    surface2_token = surface2["surfaces"][-1]["token"]
    record("fusion design surfaces thicken --surface {} --thickness-mm 1".format(surface2_token),
           {"feature": {}},
           lambda: extended.surfaces_thicken({"surface": surface2_token,
                                              "thickness_mm": 1}))

    form_caps = record("fusion design capabilities",
                       {"areas": {"forms": {"available": True}}},
                       lambda: extended.capabilities({}))
    sheet_caps = record("fusion design sheet-metal capabilities",
                        {"operations": {"flange-create": {"available": False},
                                        "flat-pattern-activate": {"available": False}}},
                        lambda: sheet_metal.capabilities({}))
    blockers = {
        "loft_feature_rename": "Installed Fusion ignores both LoftFeature.name and its timeline object's name.",
        "t_spline_topology_edit": form_caps["areas"]["forms"]["blocker"],
        "flange_create": sheet_caps["operations"]["flange-create"].get("blocker"),
        "flat_pattern_activate": sheet_caps["operations"]["flat-pattern-activate"].get("blocker"),
    }
    report["blockers"] = blockers
    report["passed"] = all(
        row["passed"] or row.get("blocker_matched") for row in rows
    ) and all(blockers.values())
except Exception:
    report["passed"] = False
    report["error"] = traceback.format_exc()
finally:
    try:
        if fixture:
            fixture.close(False)
        if original:
            original.activate()
        if original_workspace:
            original_workspace.activate()
    except Exception:
        report["cleanup_error"] = traceback.format_exc()
        report["passed"] = False
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print("Remaining Design gate: {} passed={} rows={}".format(
        REPORT, report.get("passed"), len(rows)))
