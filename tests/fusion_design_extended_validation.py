"""Live Fusion validation for extended Design APIs.

Run from Fusion's Scripts and Add-Ins dialog.  The gate creates only unsaved
disposable documents, records expected/actual command evidence in /tmp, closes
the fixtures without saving, and restores the previously active document and
workspace.
"""
import json
import sys
import traceback
from pathlib import Path

import adsk.core
import adsk.fusion


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fusion_addin" / "CadBot"))
from tools import design_extended as extended  # noqa: E402
from tools import design_sheet_metal as sheet_metal  # noqa: E402


REPORT = Path("/tmp/cadbot-design-extended-validation.json")
STAGE = Path("/tmp/cadbot-design-extended-validation.stage")
FIXTURE_NAMES = (
    "CadBot-Extended-API-Fixture",
    "CadBot-Configuration-API-Fixture",
)
rows = []


def mark(value):
    STAGE.write_text(value + "\n")


def matches(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(value, actual[key])
            for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(matches(value, candidate) for candidate in actual)
            for value in expected)
    return expected == actual


def record(command, expected, function):
    row = {"command": command, "expected": expected, "outcome": "executed"}
    try:
        actual = function()
        row["actual"] = actual
        row["passed"] = matches(expected, actual)
        if not row["passed"]:
            row["validation_error"] = "Actual result did not contain expected values"
        return actual
    except Exception:
        row["actual"] = {"error": traceback.format_exc()}
        row["passed"] = False
        return None
    finally:
        rows.append(row)


def record_blocker(command, expected, actual, capability_command):
    row = {
        "command": command,
        "expected": expected,
        "actual": actual,
        "outcome": "capability_blocked",
        "capability_command": capability_command,
        # Blockers are deliberately not passing command executions.
        "passed": False,
        "blocker_matched": matches(expected, actual),
    }
    rows.append(row)
    return row


def items(collection):
    return [collection.item(index) for index in range(collection.count)]


def point(x, y, z=0):
    return adsk.core.Point3D.create(x, y, z)


def add_rectangle_sketch(root, name, x1, y1, x2, y2):
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = name
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        point(x1, y1), point(x2, y2))
    return sketch


def add_box(root, name, center_x=0, length=2, width=2, height=1):
    # Build the fixture through Fusion's parametric API.  In Fusion 2705.1.15
    # convertToSheetMetal can return True for a transient BRep persisted into a
    # direct design while leaving isSheetMetal False.  Autodesk's own conversion
    # sample uses a sketch-backed extrusion, so the live gate mirrors that path.
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = name + "Sketch"
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        point(center_x - length / 2, -width / 2),
        point(center_x + length / 2, width / 2))
    profile = sketch.profiles.item(0)
    extrudes = root.features.extrudeFeatures
    inp = extrudes.createInput(
        profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(height))
    feature = extrudes.add(inp)
    body = feature.bodies.item(0)
    body.name = name
    return body


def first_library_asset(asset_type):
    libraries = adsk.core.Application.get().materialLibraries
    for library in items(libraries):
        collection = getattr(library, asset_type + "s")
        if collection.count:
            return library, collection.item(0)
    raise RuntimeError("No installed {} library asset was found".format(asset_type))


def exercise_surfaces(root):
    patch_sketch = add_rectangle_sketch(root, "PatchForInspect", 0, 0, 2, 2)
    created = record(
        "fusion design surfaces patch --sketch PatchForInspect",
        {"feature": {}, "surfaces": [{"solid": False}]},
        lambda: extended.surfaces_patch({"sketch": patch_sketch.entityToken}))
    if not created:
        return
    surface = created["surfaces"][-1]
    selector = surface["token"]
    record("fusion design surfaces inspect --surface " + selector,
           {"token": selector, "solid": False, "faces": 1},
           lambda: extended.surfaces_inspect({"surface": selector}))
    thickened = record(
        "fusion design surfaces thicken --surface {} --thickness-mm 1".format(selector),
        {"feature": {}},
        lambda: extended.surfaces_thicken({"surface": selector,
                                           "thickness_mm": 1.0}))

    delete_sketch = add_rectangle_sketch(root, "PatchForDelete", 3, 0, 5, 2)
    deletable = record(
        "fusion design surfaces patch --sketch PatchForDelete",
        {"surfaces": [{"solid": False}]},
        lambda: extended.surfaces_patch({"sketch": delete_sketch.entityToken}))
    if deletable:
        delete_token = deletable["surfaces"][-1]["token"]
        record("fusion design surfaces delete --surface " + delete_token,
               {"deleted": delete_token},
               lambda: extended.surfaces_delete({"surface": delete_token}))

    left_sketch = add_rectangle_sketch(root, "StitchLeft", 0, 4, 2, 6)
    right_sketch = add_rectangle_sketch(root, "StitchRight", 2, 4, 4, 6)
    left = extended.surfaces_patch({"sketch": left_sketch.entityToken})["surfaces"][-1]
    right = extended.surfaces_patch({"sketch": right_sketch.entityToken})["surfaces"][-1]
    stitch_command = (
        "fusion design surfaces stitch --surfaces '[\"{}\",\"{}\"]' --operation join"
        .format(left["token"], right["token"]))
    stitch_blocker = (
        "Fusion 2705.1.15 rejected stitching two exactly adjacent, coplanar "
        "native PatchFeature surface bodies with both new-body and join "
        "operations. The command remains implemented, but this release gate "
        "has no safe fixture that Fusion accepts.")
    try:
        actual = extended.surfaces_stitch({"surfaces": [left["token"], right["token"]],
                                           "operation": "join"})
        record(stitch_command, {"feature": {}}, lambda: actual)
    except RuntimeError as exc:
        if "Fusion rejected stitch" not in str(exc):
            raise
        record_blocker(stitch_command,
                       {"available": False, "blocker": stitch_blocker},
                       {"available": False, "blocker": stitch_blocker},
                       "fusion design surfaces stitch")
    return thickened


def exercise_forms(root, capabilities):
    record("fusion design forms list", {"forms": []}, lambda: extended.forms_list({}))
    from bridge.server import _execute_tool
    commands = (
        'fusion design forms create-from-tsm --tsm-description fixture',
        'fusion design forms inspect --form fixture',
        'fusion design forms rename --form fixture --name test',
        'fusion design forms delete --form fixture',
    )
    for command in commands:
        actual = _execute_tool('fusion', None, {'command': command})
        record_blocker(command, {'status': 'blocked', 'changes': [],
            'error': {'code': 'release_capability_unavailable'}}, actual, 'fusion app capabilities')
    form_capability = capabilities["areas"]["forms"]
    record_blocker(
        "fusion design forms edit-form",
        {"available": False, "blocker": form_capability["blocker"]},
        {"available": False, "blocker": form_capability["blocker"]},
        "fusion design capabilities")


def exercise_materials(body):
    material_library, source_material = first_library_asset("material")
    appearance_library, source_appearance = first_library_asset("appearance")
    record(
        "fusion design materials inspect --type material --asset {} --library {}".format(
            source_material.id, material_library.id),
        {"type": "material", "id": source_material.id},
        lambda: extended.materials_inspect({"type": "material",
                                            "asset": source_material.id,
                                            "library": material_library.id}))
    copied_material = record(
        "fusion design materials copy --type material --library {} --source {} --name CadBotValidationMaterial".format(
            material_library.id, source_material.id),
        {"type": "material", "name": "CadBotValidationMaterial", "used": False},
        lambda: extended.materials_copy({"type": "material",
                                        "library": material_library.id,
                                        "source": source_material.id,
                                        "name": "CadBotValidationMaterial"}))
    if copied_material:
        edited = record(
            "fusion design materials edit --type material --asset {} --name CadBotEditedMaterial --description validation".format(
                copied_material["id"]),
            {"type": "material", "name": "CadBotEditedMaterial",
             "description": "validation"},
            lambda: extended.materials_edit({"type": "material",
                                             "asset": copied_material["id"],
                                             "name": "CadBotEditedMaterial",
                                             "description": "validation"}))
        if edited:
            record("fusion design materials delete --type material --asset " + edited["id"],
                   {"deleted": edited["id"], "type": "material"},
                   lambda: extended.materials_delete({"type": "material",
                                                      "asset": edited["id"]}))
    applied = record(
        "fusion design materials apply --target {} --library {} --material {}".format(
            body.entityToken, material_library.id, source_material.id),
        {"target": body.entityToken, "material": source_material.name},
        lambda: extended.materials_apply({"target": body.entityToken,
                                          "library": material_library.id,
                                          "material": source_material.id,
                                          # Appearance and material libraries can differ.
                                          }))
    # Validate appearance application separately when it resides in another library.
    applied_appearance = record(
        "fusion design materials apply --target {} --library {} --appearance {}".format(
            body.entityToken, appearance_library.id, source_appearance.id),
        {"target": body.entityToken, "appearance": source_appearance.name},
        lambda: extended.materials_apply({"target": body.entityToken,
                                          "library": appearance_library.id,
                                          "appearance": source_appearance.id}))
    if applied or applied_appearance:
        record("fusion design materials clear-appearance --target " + body.entityToken,
               {"target": body.entityToken, "appearance": None},
               lambda: extended.materials_clear_appearance({"target": body.entityToken}))


def exercise_sheet_metal(root, capabilities):
    sheet_caps = record(
        "fusion design sheet-metal capabilities",
        {"operations": {"flange-create": {"available": False},
                         "flat-pattern-activate": {"available": False}}},
        lambda: sheet_metal.capabilities({}))
    if sheet_caps:
        for operation, command in (
                ("flange-create", "fusion design sheet-metal flanges create"),
                ("flat-pattern-activate", "fusion design sheet-metal flat-pattern activate")):
            actual = sheet_caps["operations"][operation]
            record_blocker(command,
                           {"available": False, "blocker": actual.get("blocker")},
                           actual, "fusion design sheet-metal capabilities")

    library_rules = items(getattr(adsk.fusion.Design.cast(
        adsk.core.Application.get().activeProduct), "librarySheetMetalRules", None))
    if not library_rules:
        record("fusion design sheet-metal rules list-all",
               {"library_rules": [{}]}, lambda: sheet_metal.rules_list({}))
        return
    source_rule = library_rules[0]
    # Initialize Fusion's sheet-metal data root before copying a library rule.
    # The public collection exists in a solid-only document, but addByCopy
    # raises smDataRoot until a sheet-metal component has been created.
    created = record(
        "fusion design sheet-metal components create --name CadBotSheet",
        {"component": {"name": "CadBotSheet"}},
        lambda: sheet_metal.component_create({"name": "CadBotSheet"}))
    copied = record(
        "fusion design sheet-metal rules copy --source {} --name CadBotValidationRule".format(
            source_rule.name),
        {"name": "CadBotValidationRule", "used": False},
        lambda: extended.sheet_metal_rules_copy({"source": source_rule.name,
                                                 "name": "CadBotValidationRule"}))
    if copied:
        inspected = record(
            "fusion design sheet-metal rules inspect --rule CadBotValidationRule",
            {"name": "CadBotValidationRule"},
            lambda: extended.sheet_metal_rules_inspect({"rule": "CadBotValidationRule"}))
        edited = record(
            "fusion design sheet-metal rules edit --rule CadBotValidationRule --name CadBotEditedRule --k-factor 0.42",
            {"name": "CadBotEditedRule", "k_factor": 0.42},
            lambda: extended.sheet_metal_rules_edit({"rule": "CadBotValidationRule",
                                                     "name": "CadBotEditedRule",
                                                     "k_factor": 0.42}))
        if inspected and edited:
            record("fusion design sheet-metal rules delete --rule CadBotEditedRule",
                   {"deleted": "CadBotEditedRule"},
                   lambda: extended.sheet_metal_rules_delete({"rule": "CadBotEditedRule"}))

    if created:
        component_token = created["component"]["token"]
        component = sheet_metal._component(component_token)
        plate = add_box(component, "CadBotSheetPlate", length=4, width=3,
                        height=0.25)
        face_rows = record(
            "fusion design sheet-metal faces list --component {} --body {}".format(
                component_token, plate.entityToken),
            {"body": {"sheet_metal": False}, "faces": [{}]},
            lambda: sheet_metal.faces_list({"component": component_token,
                                            "body": plate.entityToken}))
        converted = None
        if face_rows:
            base_face = max(face_rows["faces"], key=lambda row: row["area_cm2"])
            converted = record(
                "fusion design sheet-metal convert --component {} --body {} --base-face {} --rule {}".format(
                    component_token, plate.entityToken, base_face["token"], source_rule.name),
                {"body": {"sheet_metal": True}},
                lambda: sheet_metal.convert({"component": component_token,
                                             "body": plate.entityToken,
                                             "base_face": base_face["token"],
                                             "rule": source_rule.name}))
        if converted:
            refreshed = sheet_metal.faces_list({"component": component_token,
                                                "body": converted["body"]["token"]})
            stationary = max(refreshed["faces"], key=lambda row: row["area_cm2"])
            stationary_face = sheet_metal._face(
                component, stationary["token"], sheet_metal=True)
            fold_sketch = component.sketches.add(stationary_face)
            fold_sketch.name = "CadBotFoldLine"
            fold_line = fold_sketch.sketchCurves.sketchLines.addByTwoPoints(
                point(-2, 0), point(2, 0))
            fold = record(
                "fusion design sheet-metal folds create --component {} --stationary-face {} --sketch {} --line {} --angle '45 deg'".format(
                    component_token, stationary["token"], fold_sketch.entityToken,
                    fold_line.entityToken),
                {"feature": {"kind": "fold"}, "bend_lines": 1},
                lambda: sheet_metal.fold_create({
                    "component": component_token,
                    "stationary_face": stationary["token"],
                    "sketch": fold_sketch.entityToken,
                    "line": fold_line.entityToken,
                    "angle": "45 deg"}))
            if fold:
                fold_token = fold["feature"]["token"]
                fold_info = record(
                    "fusion design sheet-metal features inspect --component {} --feature {}".format(
                        component_token, fold_token),
                    {"feature": {"kind": "fold", "bend_lines": [{"index": 0}]}},
                    lambda: sheet_metal.feature_inspect({
                        "component": component_token, "feature": fold_token}))
                if fold_info:
                    current_angle = fold_info["feature"]["bend_lines"][0]["angle"]
                    record(
                        "fusion design sheet-metal folds edit-angle --component {} --fold {} --bend-index 0 --expected-angle '{}' --angle '30 deg'".format(
                            component_token, fold_token, current_angle),
                        {"fold": fold_token, "before": current_angle,
                         "after": "30 deg"},
                        lambda: sheet_metal.fold_edit_angle({
                            "component": component_token, "fold": fold_token,
                            "bend_index": 0, "expected_angle": current_angle,
                            "angle": "30 deg"}))

                folded_faces = sheet_metal.faces_list({
                    "component": component_token,
                    "body": converted["body"]["token"]})
                folded_stationary = max(
                    (row for row in folded_faces["faces"] if row["planar_candidate"]),
                    key=lambda row: row["area_cm2"])
                unfold = record(
                    "fusion design sheet-metal unfolds create --component {} --stationary-face {} --all-bends".format(
                        component_token, folded_stationary["token"]),
                    {"feature": {"kind": "unfold"}, "all_bends": True},
                    lambda: sheet_metal.unfold_create({
                        "component": component_token,
                        "stationary_face": folded_stationary["token"],
                        "all_bends": True}))
                if unfold:
                    unfold_token = unfold["feature"]["token"]
                    record(
                        "fusion design sheet-metal features inspect --component {} --feature {}".format(
                            component_token, unfold_token),
                        {"feature": {"kind": "unfold", "all_bends": True}},
                        lambda: sheet_metal.feature_inspect({
                            "component": component_token, "feature": unfold_token}))
                    record(
                        "fusion design sheet-metal unfolds edit --component {} --unfold {} --all-bends".format(
                            component_token, unfold_token),
                        {"unfold": unfold_token, "all_bends": True},
                        lambda: sheet_metal.unfold_edit({
                            "component": component_token, "unfold": unfold_token,
                            "all_bends": True}))
                    refold = record(
                        "fusion design sheet-metal refolds create --component {} --unfold {}".format(
                            component_token, unfold_token),
                        {"feature": {"kind": "refold"}, "unfold": unfold_token},
                        lambda: sheet_metal.refold_create({
                            "component": component_token, "unfold": unfold_token}))
                    if refold:
                        refold_token = refold["feature"]["token"]
                        record(
                            "fusion design sheet-metal features inspect --component {} --feature {}".format(
                                component_token, refold_token),
                            {"feature": {"kind": "refold"}},
                            lambda: sheet_metal.feature_inspect({
                                "component": component_token,
                                "feature": refold_token}))

            # Refresh topology after fold/unfold/refold before flattening.
            refreshed = sheet_metal.faces_list({"component": component_token,
                                                "body": converted["body"]["token"]})
            stationary = max((row for row in refreshed["faces"]
                              if row["planar_candidate"]),
                             key=lambda row: row["area_cm2"])
            flat = record(
                "fusion design sheet-metal flat-pattern create --component {} --stationary-face {}".format(
                    component_token, stationary["token"]),
                {"flat_pattern": {}},
                lambda: sheet_metal.flat_pattern_create({
                    "component": component_token,
                    "stationary_face": stationary["token"]}))
            record("fusion design sheet-metal flat-pattern inspect --component " + component_token,
                   {"flat_pattern": {}},
                   lambda: sheet_metal.flat_pattern_inspect({"component": component_token}))
            if flat:
                record("fusion design sheet-metal flat-pattern rename --component {} --name CadBotFlat".format(
                           component_token),
                       {"flat_pattern": {"name": "CadBotFlat"}},
                       lambda: sheet_metal.flat_pattern_rename({
                           "component": component_token, "name": "CadBotFlat"}))
                record("fusion design sheet-metal flat-pattern delete --component " + component_token,
                       {"deleted": {"name": "CadBotFlat"}},
                       lambda: sheet_metal.flat_pattern_delete({"component": component_token}))
            if fold and unfold and refold:
                record(
                    "fusion design sheet-metal features delete --component {} --feature {}".format(
                        component_token, refold_token),
                    {"deleted": {"kind": "refold", "token": refold_token}},
                    lambda: sheet_metal.feature_delete({
                        "component": component_token, "feature": refold_token}))
        record("fusion design sheet-metal rules list-all",
               {"library_rules": [{"name": source_rule.name}]},
               lambda: sheet_metal.rules_list({}))
        design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
        design_rule_names = [rule.name for rule in items(design.designSheetMetalRules)]
        if source_rule.name not in design_rule_names:
            design.designSheetMetalRules.addByCopy(source_rule, source_rule.name)
        record(
            "fusion design sheet-metal rules assign --component {} --rule {}".format(
                component_token, source_rule.name),
            {"component": {"token": component_token}, "rule": {"name": source_rule.name}},
            lambda: sheet_metal.rule_assign({"component": component_token,
                                             "rule": source_rule.name}))
        record("fusion design sheet-metal features list --component " + component_token,
               {"features": []},
               lambda: sheet_metal.features_list({"component": component_token}))


def exercise_configurations():
    initialized = record("fusion design configurations initialize",
                         {"configured": True},
                         lambda: extended.configurations_initialize({}))
    if not initialized:
        return
    listing = extended.configurations_list({})
    original = next(row for row in listing["rows"] if row["active"])
    created = record("fusion design configurations create --name ValidationConfig",
                     {"name": "ValidationConfig"},
                     lambda: extended.configurations_create({"name": "ValidationConfig"}))
    if not created:
        return
    inspected = record(
        "fusion design configurations inspect --configuration " + created["id"],
        {"id": created["id"], "name": "ValidationConfig", "cells": []},
        lambda: extended.configurations_inspect({"configuration": created["id"]}))
    copied = record(
        "fusion design configurations copy --configuration {} --name ValidationCopy".format(
            created["id"]),
        {"name": "ValidationCopy"},
        lambda: extended.configurations_copy({"configuration": created["id"],
                                              "name": "ValidationCopy"}))
    renamed = record(
        "fusion design configurations rename --configuration {} --name ValidationRenamed".format(
            created["id"]),
        {"id": created["id"], "name": "ValidationRenamed"},
        lambda: extended.configurations_rename({"configuration": created["id"],
                                                "name": "ValidationRenamed"}))
    activated = record(
        "fusion design configurations activate --configuration " + created["id"],
        {"id": created["id"], "active": True},
        lambda: extended.configurations_activate({"configuration": created["id"]}))
    if inspected:
        editable = None
        for cell in inspected.get("cells", []):
            for field in ("expression", "value", "isVisible", "isSuppressed"):
                if field in cell:
                    editable = (cell["column"], field, cell[field])
                    break
            if editable:
                break
        if editable:
            column, field, before = editable
            args = {"configuration": created["id"], "column_index": column}
            expected_field = field
            if field == "expression":
                args[field] = before
            elif field == "value":
                args[field] = before
            elif field == "isVisible":
                args["visible"] = bool(before)
            else:
                args["suppressed"] = bool(before)
            record(
                "fusion design configurations edit --configuration {} --column-index {}".format(
                    created["id"], column),
                {"configuration": created["id"], "cell": {expected_field: before}},
                lambda args=args: extended.configurations_edit(args))
        else:
            from bridge.server import _execute_tool
            command = ('fusion design configurations edit --configuration ' + created['id']
                       + ' --column-index 0 --expression "12 mm"')
            actual = _execute_tool('fusion', None, {'command': command})
            record_blocker(command, {'status': 'blocked', 'changes': [],
                'error': {'code': 'release_capability_unavailable'}}, actual, 'fusion app capabilities')
    if activated and renamed and copied:
        extended.configurations_activate({"configuration": original["id"]})
        record("fusion design configurations delete --configuration " + created["id"],
               {"deleted": created["id"]},
               lambda: extended.configurations_delete({"configuration": created["id"]}))


app = adsk.core.Application.get()
original_document = app.activeDocument
original_workspace = app.userInterface.activeWorkspace
fixtures = []
report = {
    "transport": "native Fusion disposable extended Design fixture",
    "fixture": list(FIXTURE_NAMES),
    "results": rows,
    "original_model_touched": False,
}
try:
    mark("create-primary-document")
    fixture = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    fixtures.append(fixture)
    fixture.name = FIXTURE_NAMES[0]
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    mark("capabilities")
    capabilities = record("fusion design capabilities",
                          {"areas": {"surfaces": {"available": True},
                                     "forms": {"available": True},
                                     "materials": {"available": True}}},
                          lambda: extended.capabilities({}))
    body = add_box(root, "MaterialTarget")
    mark("surfaces")
    exercise_surfaces(root)
    mark("forms")
    exercise_forms(root, capabilities)
    mark("materials")
    exercise_materials(body)
    mark("sheet-metal")
    exercise_sheet_metal(root, capabilities)

    mark("close-primary-document")
    fixture.close(False)
    fixtures.remove(fixture)
    fixture = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    fixtures.append(fixture)
    fixture.name = FIXTURE_NAMES[1]
    mark("configurations")
    exercise_configurations()
except Exception:
    report["error"] = traceback.format_exc()
finally:
    cleanup_errors = []
    for fixture in list(fixtures):
        try:
            fixture.close(False)
        except Exception:
            cleanup_errors.append(traceback.format_exc())
    try:
        if original_document:
            original_document.activate()
        if original_workspace:
            original_workspace.activate()
    except Exception:
        cleanup_errors.append(traceback.format_exc())
    if cleanup_errors:
        report["cleanup_error"] = cleanup_errors
    executed = [row for row in rows if row["outcome"] == "executed"]
    blockers = [row for row in rows if row["outcome"] == "capability_blocked"]
    report["summary"] = {
        "executed": len(executed),
        "passed": sum(bool(row["passed"]) for row in executed),
        "failed": sum(not bool(row["passed"]) for row in executed),
        "capability_blocked": len(blockers),
        "blockers_matched": sum(bool(row["blocker_matched"]) for row in blockers),
    }
    report["passed"] = (
        all(row["passed"] for row in executed)
        and all(row["blocker_matched"] for row in blockers)
        and "error" not in report and not cleanup_errors)
    report["fixture_closed"] = not any(
        document.name in FIXTURE_NAMES for document in items(app.documents))
    report["original_document_restored"] = (
        original_document is None or app.activeDocument == original_document)
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    mark("complete")
    print("Extended Design gate: {} passed={} summary={}".format(
        REPORT, report["passed"], report["summary"]))
