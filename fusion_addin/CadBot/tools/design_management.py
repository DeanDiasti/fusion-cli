"""Safe lifecycle operations for existing Design entities."""

import adsk.core
import adsk.fusion


def _design():
    value = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if value is None:
        raise RuntimeError("No active Fusion design")
    return value


def _items(collection):
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(index) for index in range(collection.count)]
    return list(collection)


def _feature_entries(design):
    result = []
    for index in range(design.timeline.count):
        timeline_object = design.timeline.item(index)
        entity = timeline_object.entity
        if entity is None or not getattr(entity, "isValid", True):
            continue
        if "Feature" not in getattr(entity, "objectType", ""):
            continue
        result.append((index, entity))
    return result


def _resolve_feature(value):
    design = _design()
    token_matches = []
    try:
        token_matches = [item for item in _items(design.findEntityByToken(value))
                         if "Feature" in getattr(item, "objectType", "")]
    except Exception:
        pass
    matches = token_matches or [entity for _index, entity in _feature_entries(design)
                                if getattr(entity, "name", "") == value]
    if len(matches) != 1:
        raise ValueError("Feature selector must identify exactly one feature; use its token from features list.")
    return matches[0]


def _feature_info(index, feature):
    return {
        "index": index,
        "name": getattr(feature, "name", ""),
        "token": getattr(feature, "entityToken", ""),
        "type": getattr(feature, "objectType", ""),
        "suppressed": bool(getattr(feature, "isSuppressed", False)),
        "health": str(getattr(feature, "healthState", "")),
        "message": getattr(feature, "errorOrWarningMessage", ""),
    }


def features_list(args):
    design = _design()
    return {"features": [_feature_info(index, feature)
                         for index, feature in _feature_entries(design)]}


def feature_inspect(args):
    design = _design()
    target = _resolve_feature(args["feature"])
    for index, feature in _feature_entries(design):
        if feature == target:
            result = _feature_info(index, feature)
            parameters = []
            for parameter in _items(design.allParameters):
                if getattr(parameter, "createdBy", None) == feature:
                    parameters.append({"name": parameter.name,
                                       "expression": parameter.expression,
                                       "unit": parameter.unit})
            result["parameters"] = parameters
            return result
    raise RuntimeError("Feature disappeared during inspection; list features again.")


def feature_rename(args):
    feature = _resolve_feature(args["feature"])
    name = args["name"].strip()
    if not name:
        raise ValueError("Feature name must not be empty.")
    feature.name = name
    if feature.name != name:
        raise RuntimeError("Feature rename was not observed.")
    return {"feature": getattr(feature, "entityToken", ""), "name": feature.name}


def _set_suppressed(args, value):
    feature = _resolve_feature(args["feature"])
    if not hasattr(feature, "isSuppressed"):
        raise RuntimeError("This Fusion feature type cannot be suppressed through the public API.")
    feature.isSuppressed = value
    if bool(feature.isSuppressed) != value:
        raise RuntimeError("Fusion did not apply the requested suppression state.")
    return {"feature": getattr(feature, "entityToken", ""), "suppressed": value}


def feature_suppress(args):
    return _set_suppressed(args, True)


def feature_unsuppress(args):
    return _set_suppressed(args, False)


def feature_delete(args):
    feature = _resolve_feature(args["feature"])
    token = getattr(feature, "entityToken", "")
    name = getattr(feature, "name", "")
    if not feature.deleteMe():
        raise RuntimeError("Fusion rejected feature deletion.")
    return {"deleted": {"token": token, "name": name}}


def _body_entries(design):
    return [(component, body) for component in _items(design.allComponents)
            for body in _items(component.bRepBodies)]


def _resolve_body(value):
    design = _design()
    matches = [(component, body) for component, body in _body_entries(design)
               if getattr(body, "entityToken", "") == value]
    if not matches:
        matches = [(component, body) for component, body in _body_entries(design)
                   if body.name == value]
    if len(matches) != 1:
        raise ValueError("Body selector must identify exactly one body; use its token from bodies list.")
    return matches[0]


def body_inspect(args):
    component, body = _resolve_body(args["body"])
    bounds = body.boundingBox
    return {
        "name": body.name,
        "token": body.entityToken,
        "component": component.name,
        "solid": bool(body.isSolid),
        "visible": bool(body.isVisible),
        "volume_cm3": float(body.volume),
        "faces": body.faces.count,
        "edges": body.edges.count,
        "bounds_mm": {
            "min": [float(bounds.minPoint.x) * 10, float(bounds.minPoint.y) * 10,
                    float(bounds.minPoint.z) * 10],
            "max": [float(bounds.maxPoint.x) * 10, float(bounds.maxPoint.y) * 10,
                    float(bounds.maxPoint.z) * 10],
        },
    }


def body_rename(args):
    _component, body = _resolve_body(args["body"])
    name = args["name"].strip()
    if not name:
        raise ValueError("Body name must not be empty.")
    body.name = name
    if body.name != name:
        raise RuntimeError("Body rename was not observed.")
    return {"token": body.entityToken, "name": body.name}


def body_delete(args):
    _component, body = _resolve_body(args["body"])
    identity = {"token": body.entityToken, "name": body.name}
    if not body.deleteMe():
        raise RuntimeError("Fusion rejected body deletion.")
    return {"deleted": identity}


def parameter_create(args):
    design = _design()
    name = args["name"].strip()
    expression = args["expression"].strip()
    unit = args.get("unit", "").strip()
    if not name or not expression:
        raise ValueError("Parameter name and expression must not be empty.")
    if design.allParameters.itemByName(name) is not None:
        raise ValueError("A parameter with that name already exists.")
    parameter = design.userParameters.add(
        name, adsk.core.ValueInput.createByString(expression), unit,
        args.get("comment", ""),
    )
    if parameter is None:
        raise RuntimeError("Fusion did not create the user parameter.")
    return {"name": parameter.name, "expression": parameter.expression,
            "unit": parameter.unit, "comment": parameter.comment}


def parameter_delete(args):
    design = _design()
    parameter = design.userParameters.itemByName(args["name"])
    if parameter is None:
        raise ValueError("User parameter not found. Model parameters cannot be deleted directly.")
    result = {"name": parameter.name, "expression": parameter.expression}
    if not parameter.deleteMe():
        raise RuntimeError("Fusion rejected user-parameter deletion; it may still be referenced.")
    return {"deleted": result}


def diagnostics(args):
    design = _design()
    feature_issues = []
    for index, feature in _feature_entries(design):
        message = getattr(feature, "errorOrWarningMessage", "")
        if message:
            feature_issues.append(_feature_info(index, feature))
    components = _items(design.allComponents)
    return {
        "document": design.parentDocument.name,
        "compute_ok": bool(design.computeAll()),
        "component_count": len(components),
        "body_count": sum(len(_items(component.bRepBodies)) for component in components),
        "sketch_count": sum(len(_items(component.sketches)) for component in components),
        "feature_count": len(_feature_entries(design)),
        "feature_issues": feature_issues,
    }
