"""Typed sheet-metal operations backed by Fusion's public Design API.

All geometry is selected by entity token (or an unambiguous component/body/
sketch name).  The module intentionally does not invoke UI commands or accept
arbitrary Python.
"""

import adsk.core
import adsk.fusion


def _items(collection):
    if collection is None:
        return []
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(index) for index in range(collection.count)]
    return list(collection)


def _design():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(getattr(app, "activeProduct", None))
    if design is None:
        raise RuntimeError("No active Fusion design.")
    return design


def _same(left, right):
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:
        return False


def _unique(values, selector, kind, names=True):
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("Provide a {} selector from an inspection command.".format(kind.lower()))
    selector = selector.strip()
    matches = []
    for value in values:
        identifiers = [getattr(value, "entityToken", None), getattr(value, "id", None)]
        if names:
            identifiers.append(getattr(value, "name", None))
        if selector in identifiers:
            matches.append(value)
    if len(matches) != 1:
        raise ValueError("{} selector must resolve uniquely; matches: {}.".format(kind, len(matches)))
    return matches[0]


def _component(selector=None):
    design = _design()
    if selector is None:
        return design.activeComponent
    if isinstance(selector, str) and selector.startswith("design-component:"):
        from tools import design_assemblies
        return design_assemblies._resolve("component", selector)
    return _unique(_items(design.allComponents), selector, "Component")


def _entity_by_token(token, kind):
    design = _design()
    if not isinstance(token, str) or not token.strip():
        raise ValueError("Provide a {} entity token.".format(kind.lower()))
    try:
        values = [item for item in _items(design.findEntityByToken(token.strip()))
                  if getattr(item, "isValid", True)]
    except Exception:
        values = []
    if len(values) != 1:
        raise ValueError("{} token is stale, invalid, or ambiguous; inspect again.".format(kind))
    return values[0]


def _body(component, selector):
    return _unique(_items(component.bRepBodies), selector, "Body")


def _face(component, token, sheet_metal=None):
    face = _entity_by_token(token, "Face")
    body = getattr(face, "body", None)
    if body is None or not any(_same(body, item) for item in _items(component.bRepBodies)):
        raise ValueError("Face does not belong to the selected component.")
    if sheet_metal is not None and bool(getattr(body, "isSheetMetal", False)) != sheet_metal:
        requirement = "sheet-metal" if sheet_metal else "standard solid"
        raise ValueError("Face must belong to a {} body.".format(requirement))
    return face


def _feature_info(feature, kind):
    return {
        "kind": kind,
        "name": getattr(feature, "name", ""),
        "token": getattr(feature, "entityToken", None),
        "health": str(getattr(feature, "healthState", "")),
        "message": getattr(feature, "errorOrWarningMessage", ""),
    }


def _checked(value, operation):
    if not value:
        raise RuntimeError("Fusion rejected {}.".format(operation))
    return value


def _verify_feature(feature, kind):
    states = getattr(adsk.fusion, "FeatureHealthStates", None)
    error_state = getattr(states,
                          "ErrorFeatureHealthState", object())
    if getattr(feature, "healthState", None) == error_state:
        raise RuntimeError("Fusion created an unhealthy {}: {}".format(
            kind, getattr(feature, "errorOrWarningMessage", "unknown feature error")))
    return _feature_info(feature, kind)


def _rule_info(rule, scope):
    def value(item):
        return {"expression": getattr(item, "expression", None),
                "value_cm": getattr(item, "value", None)}
    return {
        "scope": scope,
        "name": rule.name,
        "units": getattr(rule, "units", None),
        "used": bool(getattr(rule, "isUsed", False)) if scope == "design" else None,
        "k_factor": getattr(rule, "kFactor", None),
        "thickness": value(rule.thickness),
        "bend_radius": value(rule.bendRadius),
        "gap": value(rule.gap),
    }


def _resolve_rule(selector, allow_library=False):
    design = _design()
    design_rules = _items(getattr(design, "designSheetMetalRules", None))
    library_rules = _items(getattr(design, "librarySheetMetalRules", None)) if allow_library else []
    exact_design = [rule for rule in design_rules if selector == rule.name]
    exact_library = [rule for rule in library_rules if selector == rule.name]
    # A library rule is commonly copied into the design under the same name.
    # Prefer that document-local rule because it is the one Fusion can assign
    # and mutate; only fall back to the library when no design rule exists.
    if len(exact_design) == 1:
        return exact_design[0], "design"
    if len(exact_design) > 1:
        raise ValueError("Sheet-metal design rule must resolve uniquely; matches: {}. List rules again.".format(len(exact_design)))
    if len(exact_library) == 1:
        return exact_library[0], "library"
    raise ValueError("Sheet-metal rule must resolve uniquely; matches: {}. List rules again.".format(len(exact_library)))


def capabilities(args):
    design = _design()
    component = _component(args.get("component"))
    features = component.features
    public = lambda value: {"available": bool(value)}
    flange_create = hasattr(getattr(features, "flangeFeatures", None), "createInput")
    result = {
        "component": {"name": component.name, "token": component.entityToken},
        "operations": {
            "inspect": public(True),
            "faces-list": public(True),
            "component-create": public(hasattr(design.rootComponent.occurrences,
                                                   "addNewSheetMetalComponent")),
            "convert": {**public(hasattr(getattr(adsk.fusion, "BRepBody", None),
                                           "convertToSheetMetal")),
                        "preview_api": True},
            "rule-assign": public(hasattr(component, "activeSheetMetalRule")),
            "flange-create": public(flange_create),
            "fold-create": {**public(hasattr(features, "foldFeatures")), "preview_api": True},
            "fold-edit-angle": {**public(hasattr(features, "foldFeatures")), "preview_api": True},
            "unfold-create": {**public(hasattr(features, "unfoldFeatures")), "preview_api": True},
            "unfold-edit": {**public(hasattr(features, "unfoldFeatures")), "preview_api": True},
            "refold-create": {**public(hasattr(features, "refoldFeatures")), "preview_api": True},
            "feature-inspect": public(True),
            "feature-delete": public(True),
            "flat-pattern-create": public(hasattr(component, "createFlatPattern")),
            "flat-pattern-inspect": public(hasattr(component, "flatPattern")),
            "flat-pattern-rename": public(hasattr(component, "flatPattern")),
            "flat-pattern-delete": public(hasattr(component, "flatPattern")),
            "flat-pattern-activate": {
                "available": False,
                "blocker": "The installed public API exposes flat-pattern creation and inspection, but no flat-pattern activation method.",
            },
        },
        "limitations": [
            "Flange creation is unavailable when FlangeFeatures has no public createInput/add API.",
            "Fold, unfold, refold, and solid conversion are preview APIs in this Fusion build.",
            "Tokens must be refreshed after topology-changing operations.",
        ],
    }
    if not flange_create:
        result["operations"]["flange-create"]["blocker"] = (
            "This Fusion build exposes existing flange features read-only through FlangeFeatures; "
            "the public collection has no creation method."
        )
    return result


def inspect(args):
    design = _design()
    component = _component(args.get("component"))
    active_rule = getattr(component, "activeSheetMetalRule", None)
    bodies = []
    for body in _items(component.bRepBodies):
        bodies.append({"name": body.name, "token": body.entityToken,
                       "sheet_metal": bool(getattr(body, "isSheetMetal", False)),
                       "faces": body.faces.count, "edges": body.edges.count})
    return {
        "document": design.parentDocument.name,
        "component": {"name": component.name, "token": component.entityToken,
                      "id": getattr(component, "id", None)},
        "active_rule": _rule_info(active_rule, "design") if active_rule else None,
        "bodies": bodies,
        "flat_pattern": _flat_info(component.flatPattern) if component.flatPattern else None,
        "features": features_list({"component": component.entityToken})["features"],
    }


def faces_list(args):
    """List stable face tokens used by convert/fold/unfold/flat-pattern commands."""
    component = _component(args["component"])
    body = _body(component, args["body"])
    faces = []
    for index, face in enumerate(_items(body.faces)):
        geometry = getattr(face, "geometry", None)
        geometry_type = str(getattr(geometry, "objectType", type(geometry).__name__))
        faces.append({
            "index": index,
            "token": getattr(face, "entityToken", None),
            "surface_type": geometry_type.rsplit("::", 1)[-1],
            "area_cm2": getattr(face, "area", None),
            "planar_candidate": "Plane" in geometry_type,
            "bend_candidate": "Cylinder" in geometry_type or "Cone" in geometry_type,
        })
    return {"component": {"name": component.name, "token": component.entityToken},
            "body": {"name": body.name, "token": body.entityToken,
                     "sheet_metal": bool(getattr(body, "isSheetMetal", False))},
            "faces": faces,
            "selection_note": (
                "Use tokens, not indices. Planar top/bottom faces are stationary-face candidates. "
                "Cylindrical candidates can also be holes; Fusion validates bend membership."
            )}


def rules_list(args):
    design = _design()
    return {
        "design_rules": [_rule_info(rule, "design")
                         for rule in _items(design.designSheetMetalRules)],
        "library_rules": [_rule_info(rule, "library")
                          for rule in _items(design.librarySheetMetalRules)],
    }


def rule_assign(args):
    component = _component(args["component"])
    rule, scope = _resolve_rule(args["rule"], allow_library=False)
    component.activeSheetMetalRule = rule
    assigned = getattr(component, "activeSheetMetalRule", None)
    if assigned is None or assigned.name != rule.name:
        raise RuntimeError("Fusion did not apply the requested sheet-metal rule.")
    return {"component": {"name": component.name, "token": component.entityToken},
            "rule": _rule_info(assigned, scope)}


def component_create(args):
    design = _design()
    occurrences = design.rootComponent.occurrences
    if not hasattr(occurrences, "addNewSheetMetalComponent"):
        raise RuntimeError("This Fusion build does not expose sheet-metal component creation.")
    name = args["name"].strip()
    if not name:
        raise ValueError("Component name must not be empty.")
    occurrence = _checked(occurrences.addNewSheetMetalComponent(adsk.core.Matrix3D.create()),
                          "sheet-metal component creation")
    occurrence.component.name = name
    if args.get("rule"):
        rule, _scope = _resolve_rule(args["rule"], allow_library=False)
        occurrence.component.activeSheetMetalRule = rule
    return {"component": {"name": occurrence.component.name,
                          "token": occurrence.component.entityToken,
                          "occurrence": occurrence.fullPathName},
            "active_rule": getattr(getattr(occurrence.component, "activeSheetMetalRule", None),
                                   "name", None)}


def convert(args):
    component = _component(args["component"])
    body = _body(component, args["body"])
    if bool(getattr(body, "isSheetMetal", False)):
        raise ValueError("Body is already sheet metal.")
    face = _face(component, args["base_face"], sheet_metal=False)
    if getattr(face, "geometry", None) is None:
        raise ValueError("Base face has no usable geometry.")
    rule, scope = _resolve_rule(args["rule"], allow_library=True)
    _checked(body.convertToSheetMetal(face, rule), "solid-to-sheet-metal conversion")
    if not bool(getattr(body, "isSheetMetal", False)):
        raise RuntimeError("Fusion returned success but the body is not marked as sheet metal.")
    return {"body": {"name": body.name, "token": body.entityToken,
                     "sheet_metal": True},
            "rule": _rule_info(component.activeSheetMetalRule, "design")
                    if component.activeSheetMetalRule else _rule_info(rule, scope),
            "preview_api": True}


def _collection_features(component):
    groups = (
        ("flange", "flangeFeatures"),
        ("fold", "foldFeatures"),
        ("unfold", "unfoldFeatures"),
        ("refold", "refoldFeatures"),
    )
    result = []
    collection_errors = []
    for kind, name in groups:
        collection = getattr(component.features, name, None)
        try:
            values = _items(collection)
        except RuntimeError as exc:
            # Fresh or direct-model sheet-metal components can expose a
            # collection proxy whose count raises `fragment` until Fusion has
            # created that feature family. Other collections remain useful.
            collection_errors.append({"kind": kind, "error": str(exc)})
            continue
        for feature in values:
            item = _feature_info(feature, kind)
            if kind == "fold":
                item["bend_line_count"] = feature.bendLines.count
            elif kind == "unfold":
                item["all_bends"] = bool(feature.isUnfoldAllBends)
                item["bend_face_count"] = len(_items(feature.bendFaces))
            result.append(item)
    return result, collection_errors


def features_list(args):
    component = _component(args.get("component"))
    features, collection_errors = _collection_features(component)
    return {"component": {"name": component.name, "token": component.entityToken},
            "features": features, "collection_errors": collection_errors}


def _feature_entry(component, selector):
    entries = []
    for kind, collection_name in (("flange", "flangeFeatures"),
                                  ("fold", "foldFeatures"),
                                  ("unfold", "unfoldFeatures"),
                                  ("refold", "refoldFeatures")):
        for item in _items(getattr(component.features, collection_name, None)):
            if selector in (getattr(item, "entityToken", None), getattr(item, "name", None)):
                entries.append((kind, item))
    if len(entries) != 1:
        raise ValueError("Sheet-metal feature selector must resolve uniquely; matches: {}.".format(len(entries)))
    return entries[0]


def feature_inspect(args):
    component = _component(args["component"])
    kind, feature = _feature_entry(component, args["feature"])
    result = _feature_info(feature, kind)
    result["suppressed"] = bool(getattr(feature, "isSuppressed", False))
    if kind == "fold":
        result["corner_relief"] = bool(feature.isUseCornerRelief)
        result["bend_lines"] = []
        for index, bend in enumerate(_items(feature.bendLines)):
            parameter = getattr(bend, "bendAngle", None)
            result["bend_lines"].append({
                "index": index,
                "angle": getattr(parameter, "expression", None),
                "line_token": getattr(getattr(bend, "bendLine", None), "entityToken", None),
                "line_position": str(getattr(bend, "linePosition", "")),
                "bend_relief": bool(getattr(bend, "isBendReliefAllowed", False)),
            })
    elif kind == "unfold":
        result["all_bends"] = bool(feature.isUnfoldAllBends)
        result["bend_faces"] = [getattr(face, "entityToken", None)
                                for face in _items(feature.bendFaces)]
        result["stationary_face"] = getattr(feature.stationaryFace, "entityToken", None)
        result["refold"] = getattr(getattr(feature, "refoldFeature", None),
                                   "entityToken", None)
    elif kind == "refold":
        result["unfold"] = getattr(feature.unfoldFeature, "entityToken", None)
    return {"component": {"name": component.name, "token": component.entityToken},
            "feature": result}


def feature_delete(args):
    component = _component(args["component"])
    kind, feature = _feature_entry(component, args["feature"])
    identity = _feature_info(feature, kind)
    _checked(feature.deleteMe(), "{} deletion".format(kind))
    return {"deleted": identity}


def _sketch_line(component, sketch_selector, line_token):
    sketch = _unique(_items(component.sketches), sketch_selector, "Sketch")
    line = _entity_by_token(line_token, "Sketch line")
    lines = _items(sketch.sketchCurves.sketchLines)
    if not any(_same(line, item) for item in lines):
        raise ValueError("Sketch-line token does not belong to the selected sketch.")
    return line


def fold_create(args):
    component = _component(args["component"])
    stationary = _face(component, args["stationary_face"], sheet_metal=True)
    line = _sketch_line(component, args["sketch"], args["line"])
    positions = {
        "start": "StartFoldBendLinePositionType",
        "center": "CenterFoldBendLinePositionType",
        "end": "EndFoldBendLinePositionType",
    }
    position_name = args.get("line_position", "center")
    if position_name not in positions:
        raise ValueError("line_position must be start, center, or end.")
    expression = args["angle"].strip()
    if not expression:
        raise ValueError("Bend angle expression must not be empty.")
    features = getattr(component.features, "foldFeatures", None)
    if features is None:
        raise RuntimeError("This Fusion build does not expose fold creation.")
    inp = _checked(features.createInput(stationary), "fold input creation")
    inp.isUseCornerRelief = bool(args.get("corner_relief", True))
    definition = _checked(inp.bendLines.add(
        line, adsk.core.ValueInput.createByString(expression),
        getattr(adsk.fusion.FoldBendLinePositionTypes, positions[position_name]),
        bool(args.get("bend_relief", True))), "fold bend-line definition")
    feature = _checked(features.add(inp), "fold creation")
    return {"feature": _verify_feature(feature, "fold"),
            "bend_lines": feature.bendLines.count,
            "line_position": position_name, "preview_api": True}


def fold_edit_angle(args):
    component = _component(args["component"])
    fold = _resolve_feature(component, args["fold"], "foldFeatures", "fold")
    index = int(args["bend_index"])
    bends = _items(fold.bendLines)
    if index < 0 or index >= len(bends):
        raise ValueError("bend_index is outside this fold's bend-line collection.")
    parameter = getattr(bends[index], "bendAngle", None)
    if parameter is None:
        raise RuntimeError("Fusion did not expose the persistent bend-angle parameter.")
    expected = args["expected_angle"]
    if parameter.expression != expected:
        raise ValueError("Bend angle changed since inspection; inspect the fold again.")
    expression = args["angle"].strip()
    if not expression:
        raise ValueError("Bend angle expression must not be empty.")
    design = _design()
    try:
        parameter.expression = expression
        if parameter.expression != expression:
            raise RuntimeError("Fusion rejected the bend-angle expression.")
        if not design.computeAll():
            raise RuntimeError("Fusion could not recompute the bend.")
        _verify_feature(fold, "fold")
    except Exception as exc:
        parameter.expression = expected
        if not design.computeAll():
            raise RuntimeError(
                "Bend edit failed and Fusion could not restore the original angle; inspect the design."
            ) from exc
        raise RuntimeError("Bend edit failed; the original angle was restored: {}".format(exc)) from exc
    return {"fold": getattr(fold, "entityToken", None), "bend_index": index,
            "before": expected, "after": parameter.expression, "preview_api": True}


def unfold_create(args):
    component = _component(args["component"])
    stationary = _face(component, args["stationary_face"], sheet_metal=True)
    features = getattr(component.features, "unfoldFeatures", None)
    if features is None:
        raise RuntimeError("This Fusion build does not expose unfold creation.")
    inp = _checked(features.createInput(stationary), "unfold input creation")
    bend_tokens = args.get("bend_faces", [])
    unfold_all = bool(args.get("all_bends", not bend_tokens))
    if not unfold_all and not bend_tokens:
        raise ValueError("Provide bend_faces when all_bends is false.")
    inp.isUnfoldAllBends = unfold_all
    if not unfold_all:
        inp.bendFaces = [_face(component, token, sheet_metal=True) for token in bend_tokens]
    feature = _checked(features.add(inp), "unfold creation")
    return {"feature": _verify_feature(feature, "unfold"),
            "all_bends": bool(feature.isUnfoldAllBends), "preview_api": True}


def unfold_edit(args):
    component = _component(args["component"])
    unfold = _resolve_feature(component, args["unfold"], "unfoldFeatures", "unfold")
    bend_tokens = args.get("bend_faces", [])
    unfold_all = bool(args.get("all_bends", not bend_tokens))
    if not unfold_all and not bend_tokens:
        raise ValueError("Provide bend_faces when all_bends is false.")
    faces = None if unfold_all else [
        _face(component, token, sheet_metal=True) for token in bend_tokens
    ]
    timeline = _design().timeline
    marker = timeline.markerPosition
    try:
        _checked(unfold.timelineObject.rollTo(True), "timeline roll before unfold")
        if unfold_all:
            _checked(unfold.setUnfoldBends(True), "unfold selection update")
        else:
            _checked(unfold.setUnfoldBends(False, faces), "unfold selection update")
    finally:
        timeline.markerPosition = marker
    _verify_feature(unfold, "unfold")
    return {"unfold": getattr(unfold, "entityToken", None),
            "all_bends": bool(unfold.isUnfoldAllBends),
            "bend_faces": [getattr(face, "entityToken", None)
                           for face in _items(unfold.bendFaces)],
            "preview_api": True}


def _resolve_feature(component, selector, collection_name, kind):
    return _unique(_items(getattr(component.features, collection_name, None)), selector,
                   kind.title())


def refold_create(args):
    component = _component(args["component"])
    unfold = _resolve_feature(component, args["unfold"], "unfoldFeatures", "unfold")
    if getattr(unfold, "refoldFeature", None) is not None:
        raise ValueError("The unfold feature already has an associated refold feature.")
    features = getattr(component.features, "refoldFeatures", None)
    if features is None:
        raise RuntimeError("This Fusion build does not expose refold creation.")
    inp = _checked(features.createInput(unfold), "refold input creation")
    feature = _checked(features.add(inp), "refold creation")
    return {"feature": _verify_feature(feature, "refold"),
            "unfold": getattr(unfold, "entityToken", None), "preview_api": True}


def _flat_info(flat):
    body = flat.flatBody
    box = body.boundingBox
    bend_lines_body = getattr(flat, "bendLinesBody", None)
    return {
        "name": flat.name,
        "token": getattr(flat, "entityToken", None),
        "folded_body": {"name": flat.foldedBody.name,
                        "token": flat.foldedBody.entityToken},
        "flat_body": {"name": body.name, "token": body.entityToken,
                      "faces": body.faces.count, "edges": body.edges.count,
                      "bounds_mm": {
                          "min": [box.minPoint.x * 10, box.minPoint.y * 10, box.minPoint.z * 10],
                          "max": [box.maxPoint.x * 10, box.maxPoint.y * 10, box.maxPoint.z * 10],
                      }},
        # A valid flat pattern of a converted flat plate has no bends and
        # Fusion returns null for bendLinesBody.  Treat that as zero rather
        # than failing inspection after successful pattern creation.
        "bend_line_count": (bend_lines_body.edges.count
                            if bend_lines_body is not None else 0),
        "health": str(getattr(flat, "healthState", "")),
        "message": getattr(flat, "errorOrWarningMessage", ""),
    }


def flat_pattern_create(args):
    component = _component(args["component"])
    if component.flatPattern is not None:
        raise ValueError("Component already has a flat pattern.")
    face = _face(component, args["stationary_face"], sheet_metal=True)
    flat = _checked(component.createFlatPattern(face), "flat-pattern creation")
    return {"component": {"name": component.name, "token": component.entityToken},
            "flat_pattern": _flat_info(flat)}


def flat_pattern_inspect(args):
    component = _component(args["component"])
    if component.flatPattern is None:
        return {"component": {"name": component.name, "token": component.entityToken},
                "flat_pattern": None}
    return {"component": {"name": component.name, "token": component.entityToken},
            "flat_pattern": _flat_info(component.flatPattern)}


def flat_pattern_rename(args):
    component = _component(args["component"])
    flat = component.flatPattern
    if flat is None:
        raise ValueError("Component has no flat pattern to rename.")
    name = args["name"].strip()
    if not name:
        raise ValueError("Flat-pattern name must not be empty.")
    flat.name = name
    if flat.name != name:
        raise RuntimeError("Fusion did not apply the flat-pattern name.")
    return {"component": {"name": component.name, "token": component.entityToken},
            "flat_pattern": _flat_info(flat)}


def flat_pattern_delete(args):
    component = _component(args["component"])
    flat = component.flatPattern
    if flat is None:
        raise ValueError("Component has no flat pattern to delete.")
    identity = {"name": flat.name, "token": getattr(flat, "entityToken", None)}
    _checked(flat.deleteMe(), "flat-pattern deletion")
    deleted_handle_invalid = not bool(getattr(flat, "isValid", True))
    try:
        remaining = component.flatPattern
    except RuntimeError:
        # Fusion 2705.1.15 can throw InternalValidationError: res when the
        # component's flatPattern property is queried immediately after a
        # successful deletion.  The invalidated feature handle is still a
        # native, deterministic deletion check.
        if not deleted_handle_invalid:
            raise
        remaining = None
    if remaining is not None and getattr(remaining, "isValid", True):
        raise RuntimeError("Fusion returned success but the flat pattern still exists.")
    return {"deleted": identity,
            "verified": "feature_handle_invalid" if deleted_handle_invalid
                        else "component_has_no_flat_pattern"}
