"""Bounded, typed solid-feature operations built on Fusion's public API.

Selectors are entity tokens or exact names.  Topology is selected by a body-local
face/edge index only after the owning body has been resolved unambiguously.
"""

import math

import adsk.core
import adsk.fusion


FAMILIES = {
    "hole": "holeFeatures",
    "shell": "shellFeatures",
    "draft": "draftFeatures",
    "mirror": "mirrorFeatures",
    "loft": "loftFeatures",
    "sweep": "sweepFeatures",
}


def _items(collection):
    if collection is None:
        return []
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(index) for index in range(collection.count)]
    return list(collection)


def _design():
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design")
    return design


def _components():
    return _items(_design().allComponents)


def _unique(values, selector, label):
    token_matches = [value for value in values
                     if getattr(value, "entityToken", "") == selector]
    matches = token_matches or [value for value in values
                                if getattr(value, "name", "") == selector]
    if len(matches) != 1:
        raise ValueError("{} selector must resolve uniquely; matches: {}. List first and use the token."
                         .format(label, len(matches)))
    return matches[0]


def _component(selector=None):
    design = _design()
    if not selector:
        return design.activeComponent or design.rootComponent
    return _unique(_items(design.allComponents), selector, "Component")


def _sketch(selector):
    return _unique([sketch for component in _components()
                    for sketch in _items(component.sketches)], selector, "Sketch")


def _body(selector):
    return _unique([body for component in _components()
                    for body in _items(component.bRepBodies)], selector, "Body")


def _entity_token(selector, label, component=None):
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("{} token must be a nonempty string.".format(label))
    try:
        values = [value for value in _items(_design().findEntityByToken(selector.strip()))
                  if getattr(value, "isValid", True)]
    except Exception:
        values = []
    if component is not None:
        values = [value for value in values
                  if getattr(value, "parentComponent", None) == component or
                  getattr(getattr(value, "parentSketch", None), "parentComponent", None) == component or
                  getattr(getattr(value, "body", None), "parentComponent", None) == component]
    if len(values) != 1:
        raise ValueError("{} token is stale, ambiguous, or outside the selected component."
                         .format(label))
    return values[0]


def _curve_spec(component, spec, label):
    """Resolve a stable curve token or a sketch/index pair."""
    if not isinstance(spec, dict):
        raise ValueError("{} must be an object containing token or sketch/curve_index."
                         .format(label))
    if spec.get("token"):
        curve = _entity_token(spec["token"], label, component)
    else:
        if "sketch" not in spec or "curve_index" not in spec:
            raise ValueError("{} requires token or both sketch and curve_index."
                             .format(label))
        sketch = _sketch(spec["sketch"])
        if sketch.parentComponent != component:
            raise ValueError("{} sketch must belong to the feature component.".format(label))
        curve = _indexed(sketch.sketchCurves, spec["curve_index"], label)
    kind = (getattr(curve, "objectType", "") or type(curve).__name__).lower()
    if "sketch" not in kind and "brepedge" not in kind and "edge" not in kind:
        raise ValueError("{} must identify a sketch curve or BRep edge.".format(label))
    return curve


def _path_from_spec(component, spec, label):
    curve = _curve_spec(component, spec, label)
    path = component.features.createPath(curve, spec.get("chain") is not False)
    if path is None:
        raise RuntimeError("Fusion could not create {} from the selected curve.".format(label))
    return path


def _family_collection(component, family):
    if family not in FAMILIES:
        raise ValueError("Unknown solid feature family: {}".format(family))
    return getattr(component.features, FAMILIES[family])


def _family_features(family=None):
    families = [family] if family else list(FAMILIES)
    result = []
    for component in _components():
        for current in families:
            for feature in _items(_family_collection(component, current)):
                result.append((current, component, feature))
    return result


def _feature(selector, family=None):
    entries = _family_features(family)
    value = _unique([entry[2] for entry in entries], selector, "Solid feature")
    return next(entry for entry in entries if entry[2] == value)


def _value_mm(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Length must be a positive finite number of millimeters.")
    return adsk.core.ValueInput.createByReal(value / 10.0)


def _angle_deg(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Angle must be finite.")
    return adsk.core.ValueInput.createByReal(math.radians(value))


def _operation(value):
    operations = {
        "new": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
        "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
    }
    try:
        return operations[(value or "new").lower()]
    except KeyError:
        raise ValueError("Operation must be new, join, cut, or intersect.")


def _plane(component, value):
    planes = {
        "XY": component.xYConstructionPlane,
        "XZ": component.xZConstructionPlane,
        "YZ": component.yZConstructionPlane,
    }
    try:
        return planes[(value or "XY").upper()]
    except KeyError:
        raise ValueError("Plane must be XY, XZ, or YZ.")


def _indexed(collection, index, label):
    if type(index) is not int:
        raise ValueError("{} index must be an integer.".format(label))
    index = int(index)
    count = collection.count
    if index < 0 or index >= count:
        raise ValueError("{} index {} is out of range (0..{}).".format(
            label, index, max(count - 1, 0)))
    return collection.item(index)


def _parameter(parameter):
    if parameter is None:
        return None
    return {"name": getattr(parameter, "name", ""),
            "expression": getattr(parameter, "expression", ""),
            "unit": getattr(parameter, "unit", "")}


def _optional_attr(value, name):
    """Read optional Fusion properties that may reject valid feature types."""
    try:
        return getattr(value, name, None)
    except RuntimeError:
        return None


def _feature_info(family, component, feature):
    result = {
        "family": family,
        "component": component.name,
        "name": feature.name,
        "token": feature.entityToken,
        "suppressed": bool(getattr(feature, "isSuppressed", False)),
        "health": str(getattr(feature, "healthState", "")),
        "message": getattr(feature, "errorOrWarningMessage", ""),
        "body_tokens": [getattr(body, "entityToken", "")
                        for body in _items(getattr(feature, "bodies", None))],
    }
    if family == "hole":
        result.update({"diameter": _parameter(getattr(feature, "holeDiameter", None)),
                       "tip_angle": _parameter(getattr(feature, "tipAngle", None)),
                       "counterbore_diameter": _parameter(getattr(feature, "counterboreDiameter", None)),
                       "counterbore_depth": _parameter(getattr(feature, "counterboreDepth", None)),
                       "countersink_diameter": _parameter(getattr(feature, "countersinkDiameter", None)),
                       "countersink_angle": _parameter(getattr(feature, "countersinkAngle", None))})
    elif family == "shell":
        result.update({"inside_thickness": _parameter(getattr(feature, "insideThickness", None)),
                       "outside_thickness": _parameter(getattr(feature, "outsideThickness", None))})
    elif family == "draft":
        definition = getattr(feature, "draftDefinition", None)
        result.update({"angle": _parameter(getattr(definition, "angle", None)),
                       "direction_flipped": bool(getattr(feature, "isDirectionFlipped", False))})
    elif family == "mirror":
        result["combine"] = bool(getattr(feature, "isCombine", False))
    elif family == "sweep":
        result.update({"taper_angle": _parameter(_optional_attr(feature, "taperAngle")),
                       "twist_angle": _parameter(_optional_attr(feature, "twistAngle"))})
    return result


def solid_features_list(args):
    family = args.get("family")
    return {"features": [_feature_info(*entry) for entry in _family_features(family)]}


def solid_feature_inspect(args):
    return _feature_info(*_feature(args["feature"], args.get("family")))


def solid_feature_delete(args):
    family, _component_value, feature = _feature(args["feature"], args.get("family"))
    identity = {"family": family, "name": feature.name, "token": feature.entityToken}
    if not feature.deleteMe():
        raise RuntimeError("Fusion rejected solid feature deletion.")
    return {"deleted": identity}


def _apply_expression(feature, attribute, expression, label):
    parameter = getattr(feature, attribute, None)
    if parameter is None:
        raise ValueError("This {} feature does not expose {}.".format(
            getattr(feature, "name", "selected"), label))
    previous = parameter.expression
    parameter.expression = expression
    if parameter.expression != expression:
        raise RuntimeError("Fusion did not apply {}.".format(label))
    return {"before": previous, "after": parameter.expression}


def solid_feature_edit(args):
    family, component, feature = _feature(args["feature"], args.get("family"))
    changes = {}
    rollback = []
    name = args.get("name")
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Feature name must not be empty.")
        before = feature.name
        feature.name = name
        if feature.name != name:
            timeline_object = getattr(feature, "timelineObject", None)
            if timeline_object is not None and hasattr(timeline_object, "name"):
                timeline_object.name = name
        if feature.name != name:
            raise RuntimeError("Fusion did not apply the feature name.")
        changes["name"] = {"before": before, "after": feature.name}
        rollback.append((feature, "name", before))
    expressions = args.get("expressions") or {}
    if not isinstance(expressions, dict):
        raise ValueError("expressions must be a JSON object of supported parameter names to expressions.")
    allowed = {
        "hole": {"diameter": "holeDiameter", "tip_angle": "tipAngle",
                 "counterbore_diameter": "counterboreDiameter",
                 "counterbore_depth": "counterboreDepth",
                 "countersink_diameter": "countersinkDiameter",
                 "countersink_angle": "countersinkAngle"},
        "shell": {"inside_thickness": "insideThickness",
                  "outside_thickness": "outsideThickness"},
        "draft": {}, "mirror": {}, "loft": {},
        "sweep": {"taper_angle": "taperAngle", "twist_angle": "twistAngle"},
    }[family]
    unknown = sorted(set(expressions) - set(allowed))
    if unknown:
        raise ValueError("Unsupported {} edit fields: {}".format(family, ", ".join(unknown)))
    for key, expression in expressions.items():
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("{} expression must be nonempty and include units.".format(key))
        change = _apply_expression(feature, allowed[key], expression.strip(), key)
        changes[key] = change
        rollback.append((getattr(feature, allowed[key]), "expression", change["before"]))
    if not changes:
        raise ValueError("Provide name or at least one supported parameter expression.")
    design = _design()
    if not design.computeAll():
        for target, attribute, previous in reversed(rollback):
            setattr(target, attribute, previous)
        if not design.computeAll():
            raise RuntimeError("Feature edit and local restoration both failed; use message restoration.")
        raise RuntimeError("Fusion could not recompute the edited feature; original values were restored.")
    result = _feature_info(family, component, feature)
    result["changes"] = changes
    return result


def holes_create(args):
    sketch = _sketch(args["sketch"])
    point = _indexed(sketch.sketchPoints, args["point_index"], "Sketch point")
    holes = sketch.parentComponent.features.holeFeatures
    kind = (args.get("kind") or "simple").lower()
    required_by_kind = {
        "simple": (),
        "counterbore": ("counterbore_diameter_mm", "counterbore_depth_mm"),
        "countersink": ("countersink_diameter_mm", "countersink_angle_deg"),
    }
    if kind not in required_by_kind:
        raise ValueError("Hole kind must be simple, counterbore, or countersink.")
    missing = [name for name in required_by_kind[kind] if args.get(name) is None]
    if missing:
        raise ValueError("{} hole requires: {}.".format(kind, ", ".join(missing)))
    diameter = _value_mm(args["diameter_mm"])
    if kind == "simple":
        feature_input = holes.createSimpleInput(diameter)
    elif kind == "counterbore":
        feature_input = holes.createCounterboreInput(
            diameter, _value_mm(args["counterbore_diameter_mm"]),
            _value_mm(args["counterbore_depth_mm"]))
    elif kind == "countersink":
        feature_input = holes.createCountersinkInput(
            diameter, _value_mm(args["countersink_diameter_mm"]),
            _angle_deg(args["countersink_angle_deg"]))
    if not feature_input.setPositionBySketchPoint(point):
        raise RuntimeError("Fusion rejected the hole position.")
    if args.get("depth_mm") is None:
        if not feature_input.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection):
            raise RuntimeError("Fusion rejected the through-all hole extent.")
    elif not feature_input.setDistanceExtent(_value_mm(args["depth_mm"])):
        raise RuntimeError("Fusion rejected the hole depth.")
    feature_input.isDefaultDirection = not bool(args.get("reverse"))
    feature = holes.add(feature_input)
    if feature is None:
        raise RuntimeError("Fusion did not create the hole.")
    if args.get("name"):
        feature.name = args["name"].strip()
    return _feature_info("hole", sketch.parentComponent, feature)


def shells_create(args):
    body = _body(args["body"])
    component = body.parentComponent
    inside = float(args.get("inside_mm", 0.0))
    outside = float(args.get("outside_mm", 0.0))
    if not math.isfinite(inside) or not math.isfinite(outside) or inside < 0 or outside < 0:
        raise ValueError("Shell thicknesses must be finite nonnegative millimeter values.")
    if inside <= 0 and outside <= 0:
        raise ValueError("Provide a positive inside-mm or outside-mm thickness.")
    entities = adsk.core.ObjectCollection.create()
    indices = args.get("remove_face_indices") or []
    if indices:
        for index in indices:
            entities.add(_indexed(body.faces, index, "Face"))
    else:
        entities.add(body)
    feature_input = component.features.shellFeatures.createInput(
        entities, args.get("tangent_chain") is not False)
    feature_input.insideThickness = (_value_mm(inside) if inside > 0
                                     else adsk.core.ValueInput.createByReal(0))
    feature_input.outsideThickness = (_value_mm(outside) if outside > 0
                                      else adsk.core.ValueInput.createByReal(0))
    feature = component.features.shellFeatures.add(feature_input)
    if feature is None:
        raise RuntimeError("Fusion did not create the shell.")
    return _feature_info("shell", component, feature)


def drafts_create(args):
    body = _body(args["body"])
    faces = [_indexed(body.faces, index, "Face") for index in args["face_indices"]]
    if not faces:
        raise ValueError("Provide at least one face index.")
    component = body.parentComponent
    feature_input = component.features.draftFeatures.createInput(
        faces, _plane(component, args.get("plane")), args.get("tangent_chain") is not False)
    feature_input.isDirectionFlipped = bool(args.get("reverse"))
    if not feature_input.setSingleAngle(False, _angle_deg(args["angle_deg"])):
        raise RuntimeError("Fusion rejected the draft angle.")
    feature = component.features.draftFeatures.add(feature_input)
    if feature is None:
        raise RuntimeError("Fusion did not create the draft.")
    return _feature_info("draft", component, feature)


def mirrors_create(args):
    component = _component(args.get("component"))
    kind = args["entity_type"]
    if kind == "body":
        values = [_body(selector) for selector in args["entities"]]
    elif kind == "feature":
        values = [_feature(selector)[2] for selector in args["entities"]]
    else:
        raise ValueError("entity-type must be body or feature.")
    if any(getattr(value, "parentComponent", component) != component for value in values):
        raise ValueError("All mirror entities must belong to the selected component.")
    entities = adsk.core.ObjectCollection.create()
    for value in values:
        entities.add(value)
    feature_input = component.features.mirrorFeatures.createInput(
        entities, _plane(component, args.get("plane")))
    if kind == "body":
        feature_input.isCombine = bool(args.get("combine"))
    feature = component.features.mirrorFeatures.add(feature_input)
    if feature is None:
        raise RuntimeError("Fusion did not create the mirror.")
    return _feature_info("mirror", component, feature)


def lofts_create(args):
    selectors = args["sketches"]
    if len(selectors) < 2:
        raise ValueError("A loft requires at least two section sketches.")
    sketches = [_sketch(selector) for selector in selectors]
    component = sketches[0].parentComponent
    if any(sketch.parentComponent != component for sketch in sketches):
        raise ValueError("All loft sketches must belong to the same component.")
    indices = args.get("profile_indices") or [0] * len(sketches)
    if len(indices) != len(sketches):
        raise ValueError("profile-indices must contain one index per sketch.")
    loft_input = component.features.loftFeatures.createInput(_operation(args.get("operation")))
    for sketch, index in zip(sketches, indices):
        loft_input.loftSections.add(_indexed(sketch.profiles, index, "Profile"))
    rails = args.get("rails") or []
    centerline = args.get("centerline")
    if rails and centerline:
        raise ValueError("A loft can use rails or one centerline, not both.")
    guide_collection = getattr(loft_input, "centerLineOrRails", None)
    if (rails or centerline) and guide_collection is None:
        raise RuntimeError("This Fusion build does not expose loft rails or centerlines.")
    for index, spec in enumerate(rails):
        entity = _path_from_spec(component, spec, "Loft rail {}".format(index))
        if guide_collection.addRail(entity) is None:
            raise RuntimeError("Fusion rejected loft rail {}.".format(index))
    if centerline:
        entity = _path_from_spec(component, centerline, "Loft centerline")
        if guide_collection.addCenterLine(entity) is None:
            raise RuntimeError("Fusion rejected the loft centerline.")
    loft_input.isSolid = args.get("solid") is not False
    loft_input.isClosed = bool(args.get("closed"))
    feature = component.features.loftFeatures.add(loft_input)
    if feature is None:
        raise RuntimeError("Fusion did not create the loft.")
    result = _feature_info("loft", component, feature)
    result["guides"] = {"rail_count": len(rails),
                        "centerline": bool(centerline)}
    return result


def sweeps_create(args):
    profile_sketch = _sketch(args["profile_sketch"])
    component = profile_sketch.parentComponent
    profile = _indexed(profile_sketch.profiles, args.get("profile_index", 0), "Profile")
    if args.get("path_entity"):
        if args.get("path_sketch") is not None or args.get("path_curve_index") is not None:
            raise ValueError("Specify path_entity or path_sketch/path_curve_index, not both.")
        path_spec = {"token": args["path_entity"], "chain": args.get("chain", True)}
    else:
        if args.get("path_sketch") is None or args.get("path_curve_index") is None:
            raise ValueError("A sweep requires path_entity or both path_sketch and path_curve_index.")
        path_spec = {"sketch": args["path_sketch"],
                     "curve_index": args["path_curve_index"],
                     "chain": args.get("chain", True)}
    path = _path_from_spec(component, path_spec, "Sweep path")
    sweep_input = component.features.sweepFeatures.createInput(
        profile, path, _operation(args.get("operation")))
    sweep_input.isSolid = args.get("solid") is not False
    if args.get("guide_rail"):
        sweep_input.guideRail = _path_from_spec(component, args["guide_rail"],
                                                "Sweep guide rail")
        scaling = {"scale": "SweepProfileScaleOption",
                   "stretch": "SweepProfileStretchOption",
                   "none": "SweepProfileNoScalingOption"}
        sweep_input.profileScaling = getattr(
            adsk.fusion.SweepProfileScalingOptions,
            scaling[args.get("profile_scaling", "scale")])
    guide_surfaces = args.get("guide_surfaces") or []
    if guide_surfaces:
        surfaces = adsk.core.ObjectCollection.create()
        for token in guide_surfaces:
            face = _entity_token(token, "Sweep guide surface", component)
            kind = (getattr(face, "objectType", "") or type(face).__name__).lower()
            if "profile" not in kind and "face" not in kind:
                raise ValueError("Sweep guide surfaces must identify profiles or planar faces.")
            surfaces.add(face)
        sweep_input.guideSurfaces = surfaces
        sweep_input.isChainSelection = args.get("guide_chain") is not False
    if args.get("direction_flipped"):
        sweep_input.isDirectionFlipped = True
    if args.get("taper_angle_deg") is not None:
        sweep_input.taperAngle = _angle_deg(args["taper_angle_deg"])
    if args.get("twist_angle_deg") is not None:
        sweep_input.twistAngle = _angle_deg(args["twist_angle_deg"])
    feature = component.features.sweepFeatures.add(sweep_input)
    if feature is None:
        raise RuntimeError("Fusion did not create the sweep.")
    result = _feature_info("sweep", component, feature)
    result["path_selector"] = "entity_token" if args.get("path_entity") else "sketch_index"
    result["guide_rail"] = bool(args.get("guide_rail"))
    result["guide_surface_count"] = len(guide_surfaces)
    return result


def capabilities(args):
    return {
        "families": {
            "holes": {"create": ["simple", "counterbore", "countersink"],
                      "edit": ["name", "diameter", "tip_angle", "counterbore_diameter",
                               "counterbore_depth", "countersink_diameter", "countersink_angle"]},
            "shells": {"create": True, "edit": ["name", "inside_thickness", "outside_thickness"]},
            "drafts": {"create": "fixed-plane single-angle", "edit": ["name"]},
            "mirrors": {"create": ["body", "feature"], "edit": ["name"]},
            "lofts": {"create": "profile sections with curve-token rails or centerline", "edit": ["name"]},
            "sweeps": {"create": "sketch-curve or BRep-edge path; optional guide rail/surfaces",
                       "edit": ["name", "taper_angle", "twist_angle"]},
        },
        "shared": ["list", "inspect", "delete"],
        "blockers": [
            "Parting-line drafts are excluded because their API is preview-only.",
            "Feature topology indices can become stale after upstream edits; list/inspect again before mutation.",
        ],
    }
