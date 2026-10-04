"""Bounded public-API support for Fusion's extended Design areas.

This module deliberately avoids native UI commands.  ``capabilities`` reports
the operations that the running Fusion build actually exposes; callers must not
interpret a missing API as a modelling failure.
"""
import math

import adsk.core
import adsk.fusion

from .features import _get_design, _vi_mm


def _items(collection):
    return [collection.item(i) for i in range(collection.count)]


def _available(obj, *path):
    try:
        for name in path:
            obj = getattr(obj, name)
        return obj is not None
    except Exception:
        return False


def _operation_status(available, blocker=None):
    result = {"available": bool(available)}
    if not available:
        result["blocker"] = blocker or "The running Fusion API does not expose this operation."
    return result


def _checked(value, operation):
    if not value:
        raise RuntimeError("Fusion rejected {}".format(operation))
    return value


def _feature_operation(value):
    names = {"new": "NewBodyFeatureOperation", "join": "JoinFeatureOperation"}
    if value not in names:
        raise ValueError("Operation must be new or join")
    return getattr(adsk.fusion.FeatureOperations, names[value])


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must not be empty".format(label))
    return value


def _unique(values, selector, kind):
    matches = []
    for value in values:
        if selector in (getattr(value, "entityToken", None),
                        getattr(value, "id", None), getattr(value, "name", None)):
            matches.append(value)
    if len(matches) != 1:
        raise ValueError("{} selector must resolve uniquely; matches: {}".format(kind, len(matches)))
    return matches[0]


def _health(feature):
    state = getattr(feature, "healthState", None)
    error_state = getattr(adsk.fusion.FeatureHealthStates, "ErrorFeatureHealthState", object())
    if state == error_state:
        raise RuntimeError(getattr(feature, "errorOrWarningMessage", "Fusion created an unhealthy feature"))
    return {"name": feature.name, "token": getattr(feature, "entityToken", None),
            "health": str(state), "message": getattr(feature, "errorOrWarningMessage", "")}


def capabilities(args):
    design = _get_design()
    root = design.rootComponent
    features = root.features
    configured = bool(getattr(design, "isConfiguredDesign", False))
    patch = _available(features, "patchFeatures")
    stitch = _available(features, "stitchFeatures")
    thicken = _available(features, "thickenFeatures")
    mesh = _available(root, "meshBodies")
    mesh_create = mesh and (_available(features, "baseFeatures") or
                            getattr(design, "designType", None) ==
                            getattr(adsk.fusion.DesignTypes, "DirectDesignType", object()))
    forms = _available(features, "formFeatures")
    rules = _available(design, "designSheetMetalRules")
    materials = _available(design, "materials") and _available(design, "appearances")
    configuration_api = hasattr(design, "createConfiguredDesign")
    return {
        "scope": "extended_design_public_api",
        "areas": {
            "surfaces": {"available": patch or stitch or thicken,
                         "operations": {
                             "list": _operation_status(True),
                             "inspect": _operation_status(True),
                             "patch": _operation_status(patch),
                             "stitch": _operation_status(stitch),
                             "thicken": _operation_status(thicken),
                             "delete": _operation_status(True),
                         },
                         "blocker": "Editing parameters of an existing surface feature is not exposed by this bounded layer."},
            "meshes": {"available": mesh,
                       "operations": {
                           "list": _operation_status(mesh),
                           "inspect": _operation_status(mesh),
                           "create-triangles": _operation_status(
                               mesh_create,
                               "Parametric mesh creation requires the BaseFeature API."),
                           "edit": {**_operation_status(mesh),
                                    "scope": "name, visibility, and opacity"},
                           "delete": _operation_status(mesh),
                       }},
            "forms": {"available": forms,
                      "operations": {
                          name: _operation_status(forms) for name in
                          ("list", "inspect", "create-from-tsm", "rename", "delete")
                      },
                      "blocker": ("Fusion's public TSplineBody exposes name, TSM serialization, "
                                  "and texture mapping, but no vertex, edge, or face collections "
                                  "and no geometric transform methods. General Edit Form operations "
                                  "cannot be implemented through the installed public API.")},
            "sheet_metal": {"available": rules,
                            "operations": {
                                name: _operation_status(rules) for name in
                                ("rules-list", "rules-inspect", "rules-copy", "rules-edit", "rules-delete")
                            },
                            "blocker": "Feature creation remains unavailable until a typed flange/bend API is added."},
            "materials": {"available": materials,
                          "operations": {
                              name: _operation_status(materials) for name in
                              ("libraries", "list", "inspect", "copy", "edit", "delete",
                               "apply", "clear-appearance")
                          },
                          "blocker": "Property-level material and appearance schema editing is not exposed by this bounded layer."},
            "configurations": {"available": configuration_api,
                               "configured": configured,
                               "operations": {
                                   "list": _operation_status(configuration_api),
                                   "initialize": _operation_status(configuration_api),
                                   **{name: _operation_status(
                                      configured,
                                       "The active document must be initialized as a configured design first.")
                                      for name in ("inspect", "create", "copy", "edit", "rename", "activate", "delete")},
                               },
                               "blocker": "Configuration column and theme-table creation is not exposed by this bounded layer."},
        },
        "limitations": [
            "Availability is determined from the running Fusion API and current document.",
            "Preview or licensed APIs are reported as blockers when Fusion rejects them.",
            "No command here uses arbitrary Python, native UI automation, or undocumented text commands.",
        ],
    }


def _surface_bodies():
    return [b for c in _get_design().allComponents for b in _items(c.bRepBodies)
            if not bool(getattr(b, "isSolid", False))]


def _body_info(body):
    box = body.boundingBox
    return {"name": body.name, "token": body.entityToken,
            "component": body.parentComponent.name, "solid": bool(body.isSolid),
            "faces": body.faces.count, "edges": body.edges.count,
            "bounds_cm": {"min": [box.minPoint.x, box.minPoint.y, box.minPoint.z],
                          "max": [box.maxPoint.x, box.maxPoint.y, box.maxPoint.z]}}


def surfaces_list(args):
    return {"surfaces": [_body_info(body) for body in _surface_bodies()]}


def surfaces_inspect(args):
    return _body_info(_unique(_surface_bodies(), args["surface"], "Surface"))


def surfaces_patch(args):
    root = _get_design().rootComponent
    sketch = _unique(_items(root.sketches), args["sketch"], "Sketch")
    index = int(args.get("profile_index", 0))
    if index < 0 or index >= sketch.profiles.count:
        raise ValueError("Profile index is outside the sketch profile collection")
    collection = root.features.patchFeatures
    inp = _checked(collection.createInput(
        sketch.profiles.item(index), adsk.fusion.FeatureOperations.NewBodyFeatureOperation),
        "surface patch input")
    feature = _checked(collection.add(inp), "surface patch")
    return {"feature": _health(feature), "surfaces": surfaces_list({})["surfaces"]}


def surfaces_stitch(args):
    candidates = _surface_bodies()
    selected = [_unique(candidates, value, "Surface") for value in args["surfaces"]]
    if len(selected) < 2:
        raise ValueError("Stitch requires at least two distinct surface bodies")
    if len({body.entityToken for body in selected}) != len(selected):
        raise ValueError("Stitch surfaces must be distinct")
    component = selected[0].parentComponent
    if any(body.parentComponent != component for body in selected):
        raise ValueError("Stitch currently requires surfaces in one component")
    objects = adsk.core.ObjectCollection.create()
    for body in selected:
        objects.add(body)
    tolerance = float(args.get("tolerance_mm", 0.1))
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Stitch tolerance must be a positive finite number")
    operation = _feature_operation(args.get("operation", "new"))
    inp = _checked(component.features.stitchFeatures.createInput(
        objects, _vi_mm(tolerance), operation), "stitch input")
    feature = _checked(component.features.stitchFeatures.add(inp), "stitch")
    return {"feature": _health(feature)}


def surfaces_thicken(args):
    body = _unique(_surface_bodies(), args["surface"], "Surface")
    faces = adsk.core.ObjectCollection.create()
    for face in _items(body.faces):
        faces.add(face)
    thickness = float(args["thickness_mm"])
    if not math.isfinite(thickness) or thickness == 0:
        raise ValueError("Thickness must be a non-zero finite number")
    operation = _feature_operation(args.get("operation", "new"))
    features = body.parentComponent.features.thickenFeatures
    inp = _checked(features.createInput(faces, _vi_mm(thickness),
                                       bool(args.get("symmetric", False)), operation,
                                       bool(args.get("chain", True))), "thicken input")
    feature = _checked(features.add(inp), "thicken")
    return {"feature": _health(feature)}


def surfaces_delete(args):
    body = _unique(_surface_bodies(), args["surface"], "Surface")
    token = body.entityToken
    _checked(body.deleteMe(), "surface deletion")
    return {"deleted": token}


def _mesh_bodies():
    return [b for c in _get_design().allComponents for b in _items(c.meshBodies)]


def _mesh_info(body):
    box = body.boundingBox
    mesh = body.mesh
    return {"name": body.name, "token": body.entityToken, "component": body.parentComponent.name,
            "closed": bool(body.isClosed), "oriented": bool(body.isOriented),
            "area_cm2": body.area, "volume_cm3": body.volume,
            "vertices": getattr(mesh, "nodeCount", None), "faces": getattr(mesh, "polygonCount", None),
            "visible": bool(body.isVisible), "opacity": body.opacity,
            "bounds_cm": {"min": [box.minPoint.x, box.minPoint.y, box.minPoint.z],
                          "max": [box.maxPoint.x, box.maxPoint.y, box.maxPoint.z]}}


def meshes_list(args):
    return {"meshes": [_mesh_info(body) for body in _mesh_bodies()]}


def meshes_inspect(args):
    return _mesh_info(_unique(_mesh_bodies(), args["mesh"], "Mesh"))


def meshes_create_triangles(args):
    raw_coordinates = args["coordinates_mm"]
    raw_indices = args["indices"]
    if any(type(value) not in (int, float) or not math.isfinite(value)
           for value in raw_coordinates):
        raise ValueError("coordinates-mm must contain finite numbers")
    if any(type(value) is not int for value in raw_indices):
        raise ValueError("indices must contain integers")
    coordinates = [float(value) / 10.0 for value in raw_coordinates]
    indices = list(raw_indices)
    if len(coordinates) < 9 or len(coordinates) % 3:
        raise ValueError("coordinates-mm must contain xyz triples for at least three vertices")
    if len(indices) < 3 or len(indices) % 3:
        raise ValueError("indices must contain triangle index triples")
    if min(indices) < 0 or max(indices) >= len(coordinates) // 3:
        raise ValueError("Triangle index is outside the coordinate array")
    design = _get_design()
    root = design.rootComponent
    direct_type = getattr(adsk.fusion.DesignTypes, "DirectDesignType", object())
    base_feature = None
    if getattr(design, "designType", None) != direct_type:
        base_features = getattr(root.features, "baseFeatures", None)
        if base_features is None:
            raise RuntimeError("Parametric mesh creation requires Fusion's BaseFeature API")
        base_feature = _checked(base_features.add(), "mesh base feature creation")
    try:
        if base_feature is not None:
            _checked(base_feature.startEdit(), "mesh base feature edit start")
        body = _checked(root.meshBodies.addByTriangleMeshData(coordinates, indices, [], []),
                        "triangle mesh creation")
        if base_feature is not None:
            _checked(base_feature.finishEdit(), "mesh base feature edit finish")
    except Exception:
        if base_feature is not None:
            try:
                base_feature.finishEdit()
                base_feature.deleteMe()
            except Exception:
                pass
        raise
    if args.get("name"):
        body.name = args["name"]
    return _mesh_info(body)


def meshes_edit(args):
    body = _unique(_mesh_bodies(), args["mesh"], "Mesh")
    if "name" in args:
        if not args["name"].strip():
            raise ValueError("Mesh name must not be empty")
        body.name = args["name"]
    if "visible" in args:
        body.isLightBulbOn = bool(args["visible"])
    if "opacity" in args:
        opacity = float(args["opacity"])
        if not math.isfinite(opacity) or opacity < 0 or opacity > 1:
            raise ValueError("Opacity must be between 0 and 1")
        body.opacity = opacity
    return _mesh_info(body)


def meshes_delete(args):
    body = _unique(_mesh_bodies(), args["mesh"], "Mesh")
    token = body.entityToken
    _checked(body.deleteMe(), "mesh deletion")
    return {"deleted": token}


def _form_features():
    return [f for c in _get_design().allComponents for f in _items(c.features.formFeatures)]


def _form_info(feature):
    bodies = feature.tSplineBodies
    return {"name": feature.name, "token": feature.entityToken,
            "component": feature.parentComponent.name,
            "parametric": bool(feature.isParametric), "suppressed": bool(feature.isSuppressed),
            "health": str(feature.healthState), "message": feature.errorOrWarningMessage,
            "bodies": [{"name": body.name, "token": body.entityToken,
                        "editable_properties": ["name"],
                        "tsm_export": hasattr(body, "getTSMDescription")}
                       for body in _items(bodies)],
            "topology_edit": {
                "available": False,
                "blocker": ("The installed public TSplineBody API has no vertex, edge, or face "
                            "collections and no geometry transform methods.")}}


def forms_list(args):
    return {"forms": [_form_info(feature) for feature in _form_features()]}


def forms_inspect(args):
    return _form_info(_unique(_form_features(), args["form"], "Form"))


def forms_create_tsm(args):
    description = args["tsm_description"]
    _nonempty(description, "TSM description")
    root = _get_design().rootComponent
    feature = _checked(root.features.formFeatures.add(), "form feature creation")
    try:
        _checked(feature.startEdit(), "form edit start")
        body = _checked(feature.tSplineBodies.addByTSMDescription(description), "T-Spline creation")
        if args.get("name"):
            body.name = args["name"]
        _checked(feature.finishEdit(), "form edit finish")
    except Exception:
        try:
            feature.deleteMe()
        except Exception:
            pass
        raise
    return _form_info(feature)


def forms_rename(args):
    feature = _unique(_form_features(), args["form"], "Form")
    if not args["name"].strip():
        raise ValueError("Form name must not be empty")
    feature.name = args["name"]
    return _form_info(feature)


def forms_delete(args):
    feature = _unique(_form_features(), args["form"], "Form")
    token = feature.entityToken
    _checked(feature.deleteMe(), "form deletion")
    return {"deleted": token}


def _rules():
    design = _get_design()
    collection = getattr(design, "designSheetMetalRules", None)
    if collection is None:
        raise RuntimeError("This Fusion build or license does not expose design sheet-metal rules")
    return collection


def _rule_value(value):
    return {"expression": getattr(value, "expression", None), "value_cm": getattr(value, "value", None)}


def _rule_info(rule):
    return {"name": rule.name, "units": rule.units, "used": bool(rule.isUsed),
            "k_factor": rule.kFactor, "thickness": _rule_value(rule.thickness),
            "bend_radius": _rule_value(rule.bendRadius), "gap": _rule_value(rule.gap)}


def sheet_metal_rules_list(args):
    try:
        rules = [_rule_info(rule) for rule in _items(_rules())]
    except Exception as exc:
        # A solid-only document can expose this collection while its native
        # sheet-metal data root is unavailable. Keep discovery actionable.
        return {
            "available": False,
            "rules": [],
            "warning": (
                "Sheet-metal rules are unavailable in this document. Create or "
                "activate a sheet-metal component, then list rules again."
            ),
            "fusion_error": str(exc),
        }
    return {"available": True, "rules": rules}


def sheet_metal_rules_inspect(args):
    return _rule_info(_unique(_items(_rules()), args["rule"], "Sheet-metal rule"))


def sheet_metal_rules_copy(args):
    design = _get_design()
    source = _unique(_items(design.librarySheetMetalRules), args["source"], "Library sheet-metal rule")
    rule = _checked(_rules().addByCopy(source, _nonempty(args["name"], "Rule name")),
                    "sheet-metal rule copy")
    return _rule_info(rule)


def sheet_metal_rules_edit(args):
    rule = _unique(_items(_rules()), args["rule"], "Sheet-metal rule")
    if "name" in args:
        rule.name = _nonempty(args["name"], "Rule name")
    if "k_factor" in args:
        value = float(args["k_factor"])
        if not 0 <= value <= 1:
            raise ValueError("K factor must be between 0 and 1")
        rule.kFactor = value
    for key, attr in (("thickness", "thickness"), ("bend_radius", "bendRadius"), ("gap", "gap")):
        if key in args:
            getattr(rule, attr).expression = args[key]
    return _rule_info(rule)


def sheet_metal_rules_delete(args):
    rule = _unique(_items(_rules()), args["rule"], "Sheet-metal rule")
    if rule.isUsed:
        raise ValueError("Cannot delete a sheet-metal rule used by a component")
    name = rule.name
    _checked(rule.deleteMe(), "sheet-metal rule deletion")
    return {"deleted": name}


def material_libraries(args):
    libraries = adsk.core.Application.get().materialLibraries
    return {"libraries": [{"id": lib.id, "name": lib.name,
                            "materials": lib.materials.count,
                            "appearances": lib.appearances.count} for lib in _items(libraries)]}


def materials_list(args):
    design = _get_design()
    libraries = adsk.core.Application.get().materialLibraries
    if args.get("library"):
        source = _unique(_items(libraries), args["library"], "Material library")
        materials, appearances = source.materials, source.appearances
    else:
        materials, appearances = design.materials, design.appearances
    return {"materials": [{"id": value.id, "name": value.name} for value in _items(materials)],
            "appearances": [{"id": value.id, "name": value.name} for value in _items(appearances)]}


def _asset_collection(owner, asset_type):
    if asset_type == "material":
        return owner.materials
    if asset_type == "appearance":
        return owner.appearances
    raise ValueError("Asset type must be material or appearance")


def _design_asset(asset_type, selector):
    collection = _asset_collection(_get_design(), asset_type)
    return _unique(_items(collection), selector, asset_type.title())


def _asset_info(asset, asset_type):
    result = {"type": asset_type, "id": asset.id, "name": asset.name,
              "used": bool(getattr(asset, "isUsed", False))}
    if asset_type == "material":
        result["description"] = getattr(asset, "description", "")
        appearance = getattr(asset, "appearance", None)
        result["appearance"] = _cell_value(appearance)
    else:
        result["has_texture"] = bool(getattr(asset, "hasTexture", False))
    return result


def materials_inspect(args):
    asset_type = args["type"]
    if args.get("library"):
        libraries = adsk.core.Application.get().materialLibraries
        owner = _unique(_items(libraries), args["library"], "Material library")
        asset = _unique(_items(_asset_collection(owner, asset_type)), args["asset"],
                        asset_type.title())
    else:
        asset = _design_asset(asset_type, args["asset"])
    return _asset_info(asset, asset_type)


def materials_copy(args):
    design = _get_design()
    libraries = adsk.core.Application.get().materialLibraries
    library = _unique(_items(libraries), args["library"], "Material library")
    asset_type = args["type"]
    source = _unique(_items(_asset_collection(library, asset_type)), args["source"],
                     asset_type.title())
    asset = _checked(_asset_collection(design, asset_type).addByCopy(
        source, _nonempty(args["name"], "Asset name")),
        "{} copy into the active design".format(asset_type))
    return _asset_info(asset, asset_type)


def materials_edit(args):
    asset_type = args["type"]
    asset = _design_asset(asset_type, args["asset"])
    if "name" not in args and "description" not in args:
        raise ValueError("Specify name or description")
    if "name" in args:
        asset.name = _nonempty(args["name"], "Asset name")
    if "description" in args:
        if asset_type != "material":
            raise ValueError("Description editing is only supported for materials")
        asset.description = args["description"]
    return _asset_info(asset, asset_type)


def materials_delete(args):
    asset_type = args["type"]
    asset = _design_asset(asset_type, args["asset"])
    if asset.isUsed:
        raise ValueError("Cannot delete a {} used by the design".format(asset_type))
    identity = asset.id
    _checked(asset.deleteMe(), "{} deletion".format(asset_type))
    return {"deleted": identity, "type": asset_type}


def _material_target(selector):
    design = _get_design()
    values = []
    for component in design.allComponents:
        values.append(component)
        values.extend(_items(component.bRepBodies))
        values.extend(_items(component.meshBodies))
    return _unique(values, selector, "Material target")


def materials_apply(args):
    target = _material_target(args["target"])
    libraries = adsk.core.Application.get().materialLibraries
    library = _unique(_items(libraries), args["library"], "Material library")
    if not args.get("material") and not args.get("appearance"):
        raise ValueError("Specify a material, an appearance, or both")
    design = _get_design()
    if args.get("material"):
        source = _unique(_items(library.materials), args["material"], "Material")
        material = design.materials.itemById(source.id)
        if material is None:
            material = _checked(design.materials.addByCopy(source, source.name),
                                "material copy into the active design")
        target.material = material
    if args.get("appearance"):
        source = _unique(_items(library.appearances), args["appearance"], "Appearance")
        appearance = design.appearances.itemById(source.id)
        if appearance is None:
            appearance = _checked(design.appearances.addByCopy(source, source.name),
                                  "appearance copy into the active design")
        target.appearance = appearance
    return {"target": getattr(target, "entityToken", None) or target.name,
            "material": getattr(getattr(target, "material", None), "name", None),
            "appearance": getattr(getattr(target, "appearance", None), "name", None)}


def materials_clear_appearance(args):
    target = _material_target(args["target"])
    target.appearance = None
    return {"target": getattr(target, "entityToken", None) or target.name,
            "appearance": None}


def _configuration_table(require=False):
    design = _get_design()
    table = getattr(design, "configurationTopTable", None)
    if table is None and require:
        raise RuntimeError("The active document is not a configured design; initialize it first")
    return table


def _row_info(row, active=None):
    return {"id": row.id, "name": row.name, "index": row.index,
            "active": row == active, "test": bool(getattr(row, "isTestRow", False))}


def _cell_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"id": getattr(value, "id", None), "name": getattr(value, "name", None)}


def _cell_info(cell, index):
    result = {"column": index, "type": getattr(cell, "objectType", type(cell).__name__)}
    for key in ("expression", "value", "isVisible", "isSuppressed"):
        try:
            result[key] = _cell_value(getattr(cell, key))
        except Exception:
            pass
    for key in ("material", "appearance", "sheetMetalRule", "plasticRule", "jointSnap"):
        try:
            value = getattr(cell, key)
        except Exception:
            continue
        result[key] = _cell_value(value)
    return result


def configurations_list(args):
    table = _configuration_table()
    if table is None:
        return {"configured": False, "rows": [],
                "blocker": "Initialize configurations before creating rows."}
    return {"configured": True, "table": {"id": table.id, "name": table.name},
            "rows": [_row_info(row, table.activeRow) for row in _items(table.rows)]}


def configurations_inspect(args):
    table = _configuration_table(True)
    row = _unique(_items(table.rows), args["configuration"], "Configuration")
    result = _row_info(row, table.activeRow)
    result["cells"] = [_cell_info(row.getCellByColumnIndex(i), i)
                       for i in range(table.columns.count)]
    return result


def configurations_initialize(args):
    design = _get_design()
    if design.isConfiguredDesign:
        raise ValueError("The active document is already a configured design")
    table = _checked(design.createConfiguredDesign(), "configuration initialization")
    return {"configured": True, "table": {"id": table.id, "name": table.name}}


def configurations_create(args):
    table = _configuration_table(True)
    row = _checked(table.rows.add(_nonempty(args["name"], "Configuration name")),
                   "configuration creation")
    return _row_info(row, table.activeRow)


def configurations_copy(args):
    table = _configuration_table(True)
    source = _unique(_items(table.rows), args["configuration"], "Configuration")
    return _row_info(_checked(source.copy(_nonempty(args["name"], "Configuration name")),
                              "configuration copy"), table.activeRow)


def configurations_edit(args):
    table = _configuration_table(True)
    row = _unique(_items(table.rows), args["configuration"], "Configuration")
    if "column_id" in args:
        cell = row.getCellByColumnId(args["column_id"])
        column = args["column_id"]
    elif "column_index" in args:
        column = int(args["column_index"])
        if column < 0 or column >= table.columns.count:
            raise ValueError("Column index is outside the configuration table")
        cell = row.getCellByColumnIndex(column)
    else:
        raise ValueError("Specify column-id or column-index")
    if cell is None:
        raise ValueError("Configuration column was not found")
    fields = [key for key in ("expression", "value", "visible", "suppressed") if key in args]
    if len(fields) != 1:
        raise ValueError("Specify exactly one of expression, value, visible, or suppressed")
    field = fields[0]
    attribute = {"visible": "isVisible", "suppressed": "isSuppressed"}.get(field, field)
    if not hasattr(cell, attribute):
        raise ValueError("This configuration cell does not support {}".format(field))
    value = args[field]
    if field in ("visible", "suppressed"):
        value = bool(value)
    setattr(cell, attribute, value)
    return {"configuration": row.id, "cell": _cell_info(cell, column)}


def configurations_rename(args):
    table = _configuration_table(True)
    row = _unique(_items(table.rows), args["configuration"], "Configuration")
    row.name = _nonempty(args["name"], "Configuration name")
    return _row_info(row, table.activeRow)


def configurations_activate(args):
    table = _configuration_table(True)
    row = _unique(_items(table.rows), args["configuration"], "Configuration")
    _checked(row.activate(), "configuration activation")
    if table.activeRow != row:
        raise RuntimeError("Configuration activation was not observed")
    return _row_info(row, table.activeRow)


def configurations_delete(args):
    table = _configuration_table(True)
    row = _unique(_items(table.rows), args["configuration"], "Configuration")
    if row == table.activeRow:
        raise ValueError("Activate another configuration before deleting the active row")
    if row.index == 0:
        raise ValueError("Fusion does not allow deleting the first configuration row")
    if bool(getattr(row, "isTestRow", False)):
        raise ValueError("Fusion does not allow deleting the test configuration row")
    identity = row.id
    _checked(row.deleteMe(), "configuration deletion")
    return {"deleted": identity}
