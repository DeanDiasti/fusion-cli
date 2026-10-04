"""Bounded public-API assembly editing with session-scoped entity selectors."""

import math
import uuid

import adsk.core
import adsk.fusion


_selectors = {}
_PREFIXES = {
    "occurrence": "design-occurrence:",
    "component": "design-component:",
    "joint": "design-joint:",
}


def _items(collection):
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(i) for i in range(collection.count)]
    return list(collection)


def _context(args=None):
    app = adsk.core.Application.get()
    document = getattr(app, "activeDocument", None)
    if document is None:
        raise ValueError("Open a Fusion document first.")
    products = getattr(document, "products", None)
    design = None
    if products is not None:
        design = adsk.fusion.Design.cast(products.itemByProductType("DesignProductType"))
    if design is None:
        design = adsk.fusion.Design.cast(getattr(app, "activeProduct", None))
    if design is None:
        raise RuntimeError("The active document is not a Fusion design.")
    owner = str(document.creationId)
    expected = (args or {}).get("document_id")
    if expected is not None and str(expected) != owner:
        raise ValueError("Active document changed. List assembly entities again.")
    return document, design


def _same(left, right):
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:
        return False


def _occurrences(design):
    return _items(design.rootComponent.allOccurrences)


def _components(design):
    result = [design.rootComponent]
    for occurrence in _occurrences(design):
        component = occurrence.component
        if not any(_same(component, item) for item in result):
            result.append(component)
    return result


def _joint_entries(design):
    contexts = [("@root", design.rootComponent, None)]
    contexts.extend((o.fullPathName, o.component, o) for o in _occurrences(design))
    result = []
    for path, component, occurrence in contexts:
        for kind, collection in (("joint", component.joints),
                                 ("as-built", component.asBuiltJoints)):
            for native in _items(collection):
                item = native.createForAssemblyContext(occurrence) if occurrence else native
                if item is None:
                    raise RuntimeError("Could not resolve assembly-context joint: " + path + "::" + native.name)
                result.append({"item": item, "native": native, "path": path,
                               "context": occurrence, "kind": kind})
    return result


def _current_entities(kind, design):
    if kind == "occurrence":
        return _occurrences(design)
    if kind == "component":
        return _components(design)
    return [entry["item"] for entry in _joint_entries(design)]


def _find_by_token(design, token, current):
    if not token or not hasattr(design, "findEntityByToken"):
        return []
    try:
        found = _items(design.findEntityByToken(token))
    except Exception:
        return []
    return [item for item in current if any(_same(item, candidate) for candidate in found)]


def selector_for(kind, item, document_id=None):
    document, design = _context({"document_id": document_id} if document_id else {})
    if kind not in _PREFIXES:
        raise ValueError("Unknown assembly selector kind: " + str(kind))
    if not getattr(item, "isValid", True):
        raise ValueError("Cannot select an invalid " + kind + ".")
    owner = str(document.creationId)
    current = _current_entities(kind, design)
    if not any(_same(item, candidate) for candidate in current):
        raise ValueError("Cannot select an entity outside the active design.")
    for key, record in list(_selectors.items()):
        if record["kind"] != kind or record["document"] != owner:
            continue
        match = _selector_match(record, design)
        if match is None:
            _selectors.pop(key, None)
        elif _same(match, item):
            record["item"] = match
            return key
    key = _PREFIXES[kind] + uuid.uuid4().hex
    native = getattr(item, "nativeObject", None) or item
    context = getattr(item, "assemblyContext", None)
    _selectors[key] = {
        "kind": kind,
        "document": owner,
        "item": item,
        "native_item": native,
        "context_item": context,
        "entity_token": getattr(native, "entityToken", None) or None,
        "context_token": getattr(context, "entityToken", None) or None,
        "context_path": getattr(context, "fullPathName", None),
    }
    return key


def _selector_match(record, design):
    saved = record["item"]
    if not getattr(saved, "isValid", True):
        return None
    if record["kind"] == "joint":
        entries = _joint_entries(design)
        matches = []
        for entry in entries:
            native_matches = _same(entry["native"], record.get("native_item"))
            context_matches = _same(entry["context"], record.get("context_item"))
            if record.get("entity_token"):
                native_matches = native_matches or bool(
                    _find_by_token(design, record["entity_token"], [entry["native"]]))
            if record.get("context_path") is not None:
                context_matches = (entry["path"] == record["context_path"])
            if native_matches and context_matches:
                matches.append(entry["item"])
        return matches[0] if len(matches) == 1 else None
    current = _current_entities(record["kind"], design)
    matches = _find_by_token(design, record.get("entity_token"), current)
    if not matches:
        matches = [item for item in current if _same(item, saved)]
    return matches[0] if len(matches) == 1 else None


def _resolve(kind, value, args=None):
    document, design = _context(args)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Provide a " + kind + " selector from the corresponding list command.")
    value = value.strip()
    if value.startswith(_PREFIXES[kind]):
        record = _selectors.get(value)
        if record is None or record["kind"] != kind or record["document"] != str(document.creationId):
            raise ValueError(kind.capitalize() + " selector is stale or belongs to another document or session.")
        match = _selector_match(record, design)
        if match is None:
            _selectors.pop(value, None)
            raise ValueError(kind.capitalize() + " selector is stale because the entity changed or was deleted.")
        record["item"] = match
        return match

    current = _current_entities(kind, design)
    if kind == "occurrence":
        exact = [item for item in current if item.fullPathName == value]
        loose = [item for item in current if item.name == value or item.component.name == value]
    elif kind == "component":
        exact = [item for item in current if getattr(item, "id", None) == value]
        loose = [item for item in current if item.name == value]
    else:
        entries = _joint_entries(design)
        exact = [e["item"] for e in entries
                 if e["path"] + "::" + e["kind"] + ":" + e["item"].name == value]
        loose = [item for item in current if item.name == value]
    matches = exact or loose
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(kind.capitalize() + " name is ambiguous. Use the exact opaque selector from list.")
    raise ValueError(kind.capitalize() + " was not found. List entities and use an exact selector.")


def _matrix_values(matrix):
    return [float(value) for value in matrix.asArray()]


def _occurrence_info(occurrence, owner):
    matrix = occurrence.transform2
    translation = matrix.translation
    return {
        "selector": selector_for("occurrence", occurrence, owner),
        "path": occurrence.fullPathName,
        "name": occurrence.name,
        "component": occurrence.component.name,
        "component_selector": selector_for("component", occurrence.component, owner),
        "grounded": bool(occurrence.isGrounded),
        "ground_to_parent": getattr(occurrence, "isGroundToParent", None),
        "referenced": bool(occurrence.isReferencedComponent),
        "derived": bool(getattr(occurrence, "isDerived", False)),
        "visible": bool(occurrence.isVisible),
        "transform": {"matrix": _matrix_values(matrix), "matrix_length_units": "cm",
                      "translation_mm": {"x": float(translation.x) * 10,
                                         "y": float(translation.y) * 10,
                                         "z": float(translation.z) * 10}},
    }


def occurrences_list(args):
    document, design = _context(args)
    owner = str(document.creationId)
    query = args.get("query")
    items = _occurrences(design)
    if query:
        needle = query.casefold()
        items = [item for item in items if needle in item.fullPathName.casefold()
                 or needle in item.component.name.casefold()]
    items.sort(key=lambda item: item.fullPathName.casefold())
    return {"document": {"id": owner, "name": document.name},
            "occurrences": [_occurrence_info(item, owner) for item in items],
            "selector_scope": "current Fusion add-in session and owning document"}


def occurrences_inspect(args):
    document, _ = _context(args)
    occurrence = _resolve("occurrence", args["occurrence"], args)
    return {"document": {"id": str(document.creationId), "name": document.name},
            "occurrence": _occurrence_info(occurrence, str(document.creationId))}


def _identity_matrix():
    return adsk.core.Matrix3D.create()


def components_create(args):
    document, design = _context(args)
    matrix = _identity_matrix()
    occurrence = design.rootComponent.occurrences.addNewComponent(matrix)
    if occurrence is None:
        raise RuntimeError("Fusion did not create the component occurrence.")
    occurrence.component.name = args["name"]
    if occurrence.component.name != args["name"]:
        raise RuntimeError("Fusion did not apply the requested component name.")
    return {"created": _occurrence_info(occurrence, str(document.creationId))}


def occurrences_create(args):
    document, design = _context(args)
    component = _resolve("component", args["component"], args)
    if _same(component, design.rootComponent):
        raise ValueError("The root component cannot be instantiated as an occurrence.")
    occurrence = design.rootComponent.occurrences.addExistingComponent(component, _identity_matrix())
    if occurrence is None:
        raise RuntimeError("Fusion did not create the component occurrence.")
    return {"created": _occurrence_info(occurrence, str(document.creationId))}


def components_list(args):
    document, design = _context(args)
    owner = str(document.creationId)
    occurrences = _occurrences(design)
    result = []
    for component in _components(design):
        paths = [item.fullPathName for item in occurrences if _same(item.component, component)]
        result.append({"selector": selector_for("component", component, owner),
                       "id": getattr(component, "id", None), "name": component.name,
                       "root": _same(component, design.rootComponent),
                       "occurrence_count": len(paths), "occurrence_paths": paths,
                       "referenced_instances": sum(1 for item in occurrences
                                                   if _same(item.component, component)
                                                   and item.isReferencedComponent)})
    return {"document": {"id": owner, "name": document.name}, "components": result}


def components_inspect(args):
    _, design = _context(args)
    component = _resolve("component", args["component"], args)
    return next(item for item in components_list(args)["components"]
                if _same(_resolve("component", item["selector"], args), component))


def components_rename(args):
    _, design = _context(args)
    component = _resolve("component", args["component"], args)
    if _same(component, design.rootComponent):
        raise ValueError("Rename the document instead of the root component.")
    previous = component.name
    component.name = args["name"]
    if component.name != args["name"]:
        raise RuntimeError("Fusion did not rename the component.")
    count = sum(1 for item in _occurrences(design) if _same(item.component, component))
    return {"component": selector_for("component", component), "before": previous,
            "after": component.name, "affected_occurrences": count}


def occurrences_delete(args):
    _, design = _context(args)
    occurrence = _resolve("occurrence", args["occurrence"], args)
    path = occurrence.fullPathName
    if getattr(occurrence, "isDerived", False):
        raise ValueError("Derived occurrences cannot be deleted through the public API.")
    if not occurrence.deleteMe():
        raise RuntimeError("Fusion did not delete the occurrence.")
    if getattr(occurrence, "isValid", False) and any(
            _same(item, occurrence) for item in _occurrences(design)):
        raise RuntimeError("The occurrence still exists after deletion.")
    return {"deleted": path}


def components_delete(args):
    _, design = _context(args)
    component = _resolve("component", args["component"], args)
    if _same(component, design.rootComponent):
        raise ValueError("The root component cannot be deleted.")
    instances = [item for item in _occurrences(design) if _same(item.component, component)]
    if len(instances) > 1 and not args.get("all_instances", False):
        raise ValueError("Component has multiple occurrences. Pass --all-instances or delete one occurrence.")
    component_name = component.name
    paths = [item.fullPathName for item in instances]
    for item in sorted(instances, key=lambda value: value.fullPathName.count("+"), reverse=True):
        if getattr(item, "isDerived", False):
            raise ValueError("Derived component occurrences cannot be deleted through the public API.")
        if not item.deleteMe():
            raise RuntimeError("Fusion failed while deleting component occurrences.")
    return {"deleted_component": component_name, "deleted_occurrences": paths}


def _set_ground(args, value):
    occurrence = _resolve("occurrence", args["occurrence"], args)
    if args.get("to_parent", False):
        if not hasattr(occurrence, "isGroundToParent"):
            raise RuntimeError("This Fusion runtime does not support ground-to-parent.")
        occurrence.isGroundToParent = value
        actual = bool(occurrence.isGroundToParent)
        mode = "parent"
    else:
        occurrence.isGrounded = value
        actual = bool(occurrence.isGrounded)
        mode = "root"
    if actual != value:
        raise RuntimeError("Fusion did not apply the requested grounding state.")
    return {"occurrence": selector_for("occurrence", occurrence), "grounded": actual,
            "relative_to": mode}


def occurrences_ground(args):
    return _set_ground(args, True)


def occurrences_unground(args):
    return _set_ground(args, False)


def occurrences_transform(args):
    occurrence = _resolve("occurrence", args["occurrence"], args)
    values = args["matrix"]
    if not isinstance(values, list) or len(values) != 16 or any(
            type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("Matrix must be a JSON array of 16 finite numbers in Fusion Matrix3D order; translation entries use mm.")
    requested = [float(value) for value in values]
    native_values = list(requested)
    for index in (3, 7, 11):
        native_values[index] /= 10.0
    matrix = adsk.core.Matrix3D.create()
    if not matrix.setWithArray(native_values):
        raise ValueError("Fusion rejected the transform matrix.")
    occurrence.transform2 = matrix
    actual = _matrix_values(occurrence.transform2)
    if any(abs(a - b) > 1e-8 for a, b in zip(actual, native_values)):
        raise RuntimeError("Fusion did not apply the requested occurrence transform.")
    return {"occurrence": selector_for("occurrence", occurrence),
            "matrix": requested, "matrix_translation_units": "mm",
            "native_matrix": actual, "native_matrix_length_units": "cm"}


def _axis(name):
    choices = {"x": adsk.fusion.JointDirections.XAxisJointDirection,
               "y": adsk.fusion.JointDirections.YAxisJointDirection,
               "z": adsk.fusion.JointDirections.ZAxisJointDirection}
    try:
        return choices[name.lower()]
    except (AttributeError, KeyError):
        raise ValueError("Joint axis must be x, y, or z.")


def _motion_kind(motion):
    name = getattr(motion, "objectType", "") or type(motion).__name__
    lowered = name.lower()
    for kind in ("revolute", "slider", "rigid", "cylindrical", "pinslot", "planar", "ball"):
        if kind in lowered.replace("-", ""):
            return "pin-slot" if kind == "pinslot" else kind
    return "unknown"


def _limit_info(limits, scale, units):
    return {"units": units,
            "minimum": limits.minimumValue / scale if limits.isMinimumValueEnabled else None,
            "maximum": limits.maximumValue / scale if limits.isMaximumValueEnabled else None,
            "rest": limits.restValue / scale if limits.isRestValueEnabled else None}


def _joint_info(joint, owner):
    motion = joint.jointMotion
    result = {"selector": selector_for("joint", joint, owner), "name": joint.name,
              "type": _motion_kind(motion),
              "locked": bool(getattr(joint, "isLocked", False)),
              "lock_supported": hasattr(joint, "isLocked"),
              "suppressed": bool(getattr(joint, "isSuppressed", False)),
              "health": str(getattr(joint, "healthState", "")),
              "message": getattr(joint, "errorOrWarningMessage", ""),
              "occurrence_one": joint.occurrenceOne.fullPathName if joint.occurrenceOne else None,
              "occurrence_two": joint.occurrenceTwo.fullPathName if joint.occurrenceTwo else None}
    if motion is not None and hasattr(motion, "rotationLimits"):
        result["rotation_limits"] = _limit_info(motion.rotationLimits, math.pi / 180, "deg")
        result["rotation_deg"] = float(motion.rotationValue) * 180 / math.pi
    if motion is not None and hasattr(motion, "slideLimits"):
        result["slide_limits"] = _limit_info(motion.slideLimits, 0.1, "mm")
        result["slide_mm"] = float(motion.slideValue) * 10
    return result


def joints_list(args):
    document, design = _context(args)
    owner = str(document.creationId)
    return {"document": {"id": owner, "name": document.name},
            "joints": [_joint_info(entry["item"], owner) for entry in _joint_entries(design)]}


def joints_inspect(args):
    document, _ = _context(args)
    return {"document": {"id": str(document.creationId), "name": document.name},
            "joint": _joint_info(_resolve("joint", args["joint"], args), str(document.creationId))}


def _topology_for_occurrence(occurrence):
    """Return native topology and its assembly-context proxy for an occurrence."""
    result = []
    for body_index, body in enumerate(_items(occurrence.component.bRepBodies)):
        for kind, collection_name in (("face", "faces"), ("edge", "edges"),
                                      ("vertex", "vertices")):
            for index, native in enumerate(_items(getattr(body, collection_name))):
                proxy = native.createForAssemblyContext(occurrence)
                if proxy is None:
                    raise RuntimeError("Could not create assembly-context {} geometry for {}."
                                       .format(kind, occurrence.fullPathName))
                result.append({"kind": kind, "body_index": body_index, "index": index,
                               "native": native, "proxy": proxy})
    return result


def joint_geometry_list(args):
    """List topology tokens accepted by ``joints create --geometry-*``."""
    occurrence = _resolve("occurrence", args["occurrence"], args)
    geometry = [{"kind": "origin", "token": None, "keypoints": ["center"]}]
    for entry in _topology_for_occurrence(occurrence):
        item = entry["native"]
        row = {"kind": entry["kind"], "token": getattr(item, "entityToken", None),
               "body_index": entry["body_index"], "index": entry["index"]}
        if entry["kind"] == "face":
            surface = getattr(item, "geometry", None)
            row["surface_type"] = (getattr(surface, "objectType", "") or
                                   type(surface).__name__).rsplit("::", 1)[-1]
            row["keypoints"] = ["center"]
        elif entry["kind"] == "edge":
            row["keypoints"] = ["start", "middle", "end", "center"]
        else:
            row["keypoints"] = ["center"]
        geometry.append(row)
    return {"occurrence": {"selector": selector_for("occurrence", occurrence),
                            "path": occurrence.fullPathName},
            "geometry": geometry,
            "token_scope": "native topology in the active design; list again after topology changes"}


def _origin_geometry(occurrence):
    origin = occurrence.component.originConstructionPoint
    point = origin.createForAssemblyContext(occurrence)
    if point is None:
        raise RuntimeError("Could not create assembly-context origin geometry for " + occurrence.fullPathName)
    geometry = adsk.fusion.JointGeometry.createByPoint(point)
    if geometry is None:
        raise RuntimeError("Fusion could not create joint geometry at " + occurrence.fullPathName)
    return geometry


def _keypoint(value):
    names = {"start": "StartKeyPoint", "middle": "MiddleKeyPoint",
             "end": "EndKeyPoint", "center": "CenterKeyPoint"}
    try:
        return getattr(adsk.fusion.JointKeyPointTypes, names[(value or "center").lower()])
    except (AttributeError, KeyError):
        raise ValueError("Joint keypoint must be start, middle, end, or center.")


def _joint_geometry(occurrence, token, keypoint="center"):
    if token is None:
        return _origin_geometry(occurrence), "origin"
    matches = [entry for entry in _topology_for_occurrence(occurrence)
               if getattr(entry["native"], "entityToken", None) == token]
    if len(matches) != 1:
        raise ValueError("Joint geometry token must identify one face, edge, or vertex in "
                         "the selected occurrence. List joint geometry again.")
    entry = matches[0]
    kind, entity = entry["kind"], entry["proxy"]
    if kind == "vertex":
        if keypoint not in (None, "center"):
            raise ValueError("Vertex joint geometry only supports the center keypoint.")
        geometry = adsk.fusion.JointGeometry.createByPoint(entity)
    elif kind == "edge":
        geometry = adsk.fusion.JointGeometry.createByCurve(entity, _keypoint(keypoint))
    else:
        if keypoint not in (None, "center"):
            raise ValueError("Face joint geometry without a boundary edge uses the center keypoint.")
        surface_type = (getattr(getattr(entity, "geometry", None), "objectType", "") or
                        type(getattr(entity, "geometry", None)).__name__).lower()
        if "plane" in surface_type:
            geometry = adsk.fusion.JointGeometry.createByPlanarFace(
                entity, None, _keypoint("center"))
        else:
            geometry = adsk.fusion.JointGeometry.createByNonPlanarFace(
                entity, _keypoint("center"))
    if geometry is None:
        raise RuntimeError("Fusion could not create joint geometry from the selected {}."
                           .format(kind))
    return geometry, kind


def _set_input_motion(value, kind, axis):
    if kind == "rigid":
        ok = value.setAsRigidJointMotion()
    elif kind == "revolute":
        ok = value.setAsRevoluteJointMotion(_axis(axis))
    elif kind == "slider":
        ok = value.setAsSliderJointMotion(_axis(axis))
    else:
        raise ValueError("Joint type must be rigid, revolute, or slider.")
    if ok is False:
        raise RuntimeError("Fusion rejected the requested joint motion type.")


def joints_create(args):
    document, design = _context(args)
    one = _resolve("occurrence", args["occurrence_one"], args)
    two = _resolve("occurrence", args["occurrence_two"], args)
    if _same(one, two):
        raise ValueError("A joint requires two different occurrences.")
    joints = design.rootComponent.joints
    geometry_one, kind_one = _joint_geometry(one, args.get("geometry_one"),
                                             args.get("keypoint_one", "center"))
    geometry_two, kind_two = _joint_geometry(two, args.get("geometry_two"),
                                             args.get("keypoint_two", "center"))
    value = joints.createInput(geometry_one, geometry_two)
    if value is None:
        raise RuntimeError("Fusion could not create joint input from the selected geometry.")
    _set_input_motion(value, args["type"], args.get("axis", "z"))
    value.isFlipped = bool(args.get("flipped", False))
    if "angle_deg" in args:
        value.angle = adsk.core.ValueInput.createByString(str(args["angle_deg"]) + " deg")
    if "offset_mm" in args:
        value.offset = adsk.core.ValueInput.createByString(str(args["offset_mm"]) + " mm")
    joint = joints.add(value)
    if joint is None:
        raise RuntimeError("Fusion did not create the joint.")
    if args.get("name"):
        joint.name = args["name"]
    return {"created": _joint_info(joint, str(document.creationId)),
            "geometry": {"one": kind_one, "two": kind_two}}


def _roll_before(joint, design, function):
    timeline = getattr(joint, "timelineObject", None)
    if timeline is None or not timeline.rollTo(True):
        raise RuntimeError("Fusion could not roll the timeline before the joint for editing.")
    try:
        return function()
    finally:
        design.timeline.moveToEnd()


def joints_edit(args):
    _, design = _context(args)
    joint = _resolve("joint", args["joint"], args)
    changed = {}
    if "name" in args:
        before = joint.name
        joint.name = args["name"]
        if joint.name != args["name"]:
            raise RuntimeError("Fusion did not rename the joint.")
        changed["name"] = {"before": before, "after": joint.name}
    for key, attr in (("locked", "isLocked"), ("suppressed", "isSuppressed")):
        if key in args:
            if not hasattr(joint, attr):
                raise ValueError("This joint kind does not support " + key + ".")
            setattr(joint, attr, bool(args[key]))
            if bool(getattr(joint, attr)) != bool(args[key]):
                raise RuntimeError("Fusion did not apply joint " + key + ".")
            changed[key] = bool(args[key])
    if "flipped" in args:
        if not hasattr(joint, "isFlipped"):
            raise ValueError("As-built joints do not expose a flipped property.")
        _roll_before(joint, design, lambda: setattr(joint, "isFlipped", bool(args["flipped"])))
        if bool(joint.isFlipped) != bool(args["flipped"]):
            raise RuntimeError("Fusion did not apply the requested flipped state.")
        changed["flipped"] = bool(args["flipped"])
    if "type" in args:
        _roll_before(joint, design,
                     lambda: _set_input_motion(joint, args["type"], args.get("axis", "z")))
        if _motion_kind(joint.jointMotion) != args["type"]:
            raise RuntimeError("Fusion did not apply the requested joint motion type.")
        changed["type"] = args["type"]
    if not changed:
        raise ValueError("Specify at least one joint property to edit.")
    return {"joint": selector_for("joint", joint), "changed": changed,
            "current": _joint_info(joint, str(_context(args)[0].creationId))}


def _joint_edit_value(args, key, value):
    request = {"joint": args["joint"], key: value}
    if "document_id" in args:
        request["document_id"] = args["document_id"]
    return joints_edit(request)


def joints_lock(args):
    return _joint_edit_value(args, "locked", True)


def joints_unlock(args):
    return _joint_edit_value(args, "locked", False)


def joints_suppress(args):
    return _joint_edit_value(args, "suppressed", True)


def joints_unsuppress(args):
    return _joint_edit_value(args, "suppressed", False)


def joints_flip(args):
    return _joint_edit_value(args, "flipped", True)


def joints_unflip(args):
    return _joint_edit_value(args, "flipped", False)


def joints_delete(args):
    _, design = _context(args)
    joint = _resolve("joint", args["joint"], args)
    name = joint.name
    if not joint.deleteMe():
        raise RuntimeError("Fusion did not delete the joint.")
    if getattr(joint, "isValid", False) and any(
            _same(joint, entry["item"]) for entry in _joint_entries(design)):
        raise RuntimeError("The joint still exists after deletion.")
    return {"deleted": name}


def joints_limits_set(args):
    joint = _resolve("joint", args["joint"], args)
    motion = joint.jointMotion
    axis = args["axis"]
    if axis == "rotation" and hasattr(motion, "rotationLimits"):
        limits, scale, units = motion.rotationLimits, math.pi / 180, "deg"
    elif axis == "slide" and hasattr(motion, "slideLimits"):
        limits, scale, units = motion.slideLimits, 0.1, "mm"
    else:
        raise ValueError("Joint does not support the requested limit axis.")
    supplied = {key: key in args for key in ("minimum", "maximum", "rest")}
    if not any(supplied.values()):
        raise ValueError("Specify at least one minimum, maximum, or rest limit.")
    enabled = {"minimum": bool(limits.isMinimumValueEnabled),
               "maximum": bool(limits.isMaximumValueEnabled),
               "rest": bool(limits.isRestValueEnabled)}
    values = {"minimum": limits.minimumValue, "maximum": limits.maximumValue,
              "rest": limits.restValue}
    for key in supplied:
        if supplied[key]:
            enabled[key] = args[key] is not None
            if enabled[key]:
                values[key] = float(args[key]) * scale
    if enabled["minimum"] and enabled["maximum"] and values["minimum"] > values["maximum"]:
        raise ValueError("Minimum joint limit cannot exceed maximum.")
    if enabled["rest"]:
        if enabled["minimum"] and values["rest"] < values["minimum"]:
            raise ValueError("Rest value is below the minimum limit.")
        if enabled["maximum"] and values["rest"] > values["maximum"]:
            raise ValueError("Rest value is above the maximum limit.")
    for key, native in (("minimum", "minimumValue"), ("maximum", "maximumValue"),
                        ("rest", "restValue")):
        if supplied[key]:
            setattr(limits, "is" + key.capitalize() + "ValueEnabled", enabled[key])
            if enabled[key]:
                setattr(limits, native, values[key])
    result = _limit_info(limits, scale, units)
    for key in supplied:
        if not supplied[key]:
            continue
        expected = args[key]
        if expected is None and result[key] is not None:
            raise RuntimeError("Fusion did not disable the " + key + " joint limit.")
        if expected is not None and abs(result[key] - float(expected)) > 1e-7:
            raise RuntimeError("Fusion did not apply the " + key + " joint limit.")
    return {"joint": selector_for("joint", joint), "axis": axis, "limits": result}


def joints_limits_clear(args):
    requested = [key for key in ("minimum", "maximum", "rest") if args.get(key, False)]
    if not requested:
        raise ValueError("Choose at least one of minimum, maximum, or rest to clear.")
    values = {"joint": args["joint"], "axis": args["axis"]}
    values.update({key: None for key in requested})
    if "document_id" in args:
        values["document_id"] = args["document_id"]
    return joints_limits_set(values)
