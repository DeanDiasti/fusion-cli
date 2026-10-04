"""Typed construction geometry, timeline, and selection operations.

All entity inputs are stable Fusion entity tokens or explicit origin aliases.  This
module deliberately does not evaluate code or infer topology from display names.
"""

import adsk.core
import adsk.fusion


_ORIGIN_ALIASES = {
    "origin:xy-plane": "xYConstructionPlane",
    "origin:xz-plane": "xZConstructionPlane",
    "origin:yz-plane": "yZConstructionPlane",
    "origin:x-axis": "xConstructionAxis",
    "origin:y-axis": "yConstructionAxis",
    "origin:z-axis": "zConstructionAxis",
    "origin:point": "originConstructionPoint",
}


def _items(collection):
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(index) for index in range(collection.count)]
    return list(collection)


def _design():
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design.")
    return design


def _component(selector=None):
    design = _design()
    if not selector:
        return design.rootComponent
    matches = []
    for component in _items(design.allComponents):
        if selector in (getattr(component, "entityToken", None), component.name):
            matches.append(component)
    if len(matches) != 1:
        raise ValueError("Component selector must identify exactly one component.")
    return matches[0]


def _resolve_token(selector):
    design = _design()
    alias = _ORIGIN_ALIASES.get(selector.lower()) if isinstance(selector, str) else None
    if alias:
        return getattr(design.rootComponent, alias)
    try:
        matches = [entity for entity in _items(design.findEntityByToken(selector))
                   if entity is not None and getattr(entity, "isValid", True)]
    except Exception:
        matches = []
    if len(matches) != 1:
        raise ValueError(
            "Entity selector must be one valid entity token or an origin alias: "
            "origin:xy-plane, origin:xz-plane, origin:yz-plane, origin:x-axis, "
            "origin:y-axis, origin:z-axis, origin:point."
        )
    return matches[0]


def _construction_entries(kind=None):
    design = _design()
    kinds = (("plane", "constructionPlanes"), ("axis", "constructionAxes"),
             ("point", "constructionPoints"))
    result = []
    for component in _items(design.allComponents):
        for item_kind, attr in kinds:
            if kind and kind != item_kind:
                continue
            for entity in _items(getattr(component, attr)):
                result.append((item_kind, component, entity))
    return result


def _resolve_construction(selector, kind=None):
    alias = _ORIGIN_ALIASES.get(selector.lower()) if isinstance(selector, str) else None
    if alias:
        entity = getattr(_design().rootComponent, alias)
        alias_kind = "plane" if "Plane" in alias else ("axis" if "Axis" in alias else "point")
        if kind and kind != alias_kind:
            raise ValueError("The origin alias does not match the requested construction kind.")
        return alias_kind, _design().rootComponent, entity
    token_matches = [(k, c, e) for k, c, e in _construction_entries(kind)
                     if getattr(e, "entityToken", None) == selector]
    matches = token_matches or [(k, c, e) for k, c, e in _construction_entries(kind)
                                if getattr(e, "name", None) == selector]
    if len(matches) != 1:
        raise ValueError(
            "Construction selector must identify exactly one item; use its token from construction list."
        )
    return matches[0]


def _xyz(point):
    return [round(float(point.x) * 10.0, 6), round(float(point.y) * 10.0, 6),
            round(float(point.z) * 10.0, 6)]


def _definition_info(definition):
    result = {"type": getattr(definition, "objectType", type(definition).__name__)}
    for name in ("offset", "angle", "distance"):
        try:
            parameter = getattr(definition, name)
            if parameter is not None:
                result[name] = {
                    "expression": getattr(parameter, "expression", None),
                    "unit": getattr(parameter, "unit", None),
                    "value": getattr(parameter, "value", None),
                }
        except Exception:
            pass
    return result


def _construction_info(kind, component, entity):
    result = {
        "kind": kind,
        "name": getattr(entity, "name", ""),
        "token": getattr(entity, "entityToken", ""),
        "component": component.name,
        "component_token": getattr(component, "entityToken", ""),
        "parametric": bool(getattr(entity, "isParametric", False)),
        "deletable": bool(getattr(entity, "isDeletable", False)),
        "visible": bool(getattr(entity, "isVisible", False)),
        "light_bulb_on": bool(getattr(entity, "isLightBulbOn", False)),
        "health": str(getattr(entity, "healthState", "")),
        "message": getattr(entity, "errorOrWarningMessage", ""),
    }
    try:
        geometry = entity.geometry
        if kind == "plane":
            result["geometry"] = {"origin_mm": _xyz(geometry.origin),
                                  "normal": _xyz_unitless(geometry.normal)}
        elif kind == "axis":
            result["geometry"] = {"origin_mm": _xyz(geometry.origin),
                                  "direction": _xyz_unitless(geometry.direction)}
        else:
            result["geometry"] = {"point_mm": _xyz(geometry)}
    except Exception:
        result["geometry"] = None
    try:
        result["definition"] = _definition_info(entity.definition)
    except Exception:
        result["definition"] = None
    return result


def _xyz_unitless(vector):
    return [round(float(vector.x), 9), round(float(vector.y), 9),
            round(float(vector.z), 9)]


def construction_list(args):
    kind = args.get("kind")
    if kind and kind not in ("plane", "axis", "point"):
        raise ValueError("kind must be plane, axis, or point.")
    design = _design()
    origins = []
    for alias, attribute in sorted(_ORIGIN_ALIASES.items()):
        alias_kind = "plane" if "Plane" in attribute else ("axis" if "Axis" in attribute else "point")
        if not kind or kind == alias_kind:
            origins.append({"alias": alias,
                            "entity": _construction_info(alias_kind, design.rootComponent,
                                                         getattr(design.rootComponent, attribute))})
    return {"construction": [_construction_info(k, c, e)
                              for k, c, e in _construction_entries(kind)],
            "origins": origins}


def construction_inspect(args):
    kind, component, entity = _resolve_construction(args["construction"], args.get("kind"))
    return _construction_info(kind, component, entity)


def _finish_construction(entity, name=None):
    if entity is None:
        raise RuntimeError("Fusion did not create the construction geometry.")
    if name:
        entity.name = name
        if entity.name != name:
            raise RuntimeError("Fusion created the geometry but did not apply its name.")
    kind = "plane" if "Plane" in entity.objectType else ("axis" if "Axis" in entity.objectType else "point")
    return _construction_info(kind, entity.component, entity)


def plane_create_offset(args):
    component = _component(args.get("component"))
    construction_input = component.constructionPlanes.createInput()
    ok = construction_input.setByOffset(
        _resolve_token(args["reference"]),
        adsk.core.ValueInput.createByString(args["offset"]),
    )
    if not ok:
        raise ValueError("Fusion rejected the offset-plane definition; verify the planar reference and expression.")
    return _finish_construction(component.constructionPlanes.add(construction_input), args.get("name"))


def plane_create_midplane(args):
    component = _component(args.get("component"))
    construction_input = component.constructionPlanes.createInput()
    if not construction_input.setByTwoPlanes(_resolve_token(args["first"]),
                                              _resolve_token(args["second"])):
        raise ValueError("Fusion rejected the midplane definition; references must be distinct planar entities.")
    return _finish_construction(component.constructionPlanes.add(construction_input), args.get("name"))


def plane_create_three_points(args):
    component = _component(args.get("component"))
    construction_input = component.constructionPlanes.createInput()
    if not construction_input.setByThreePoints(_resolve_token(args["first"]),
                                                _resolve_token(args["second"]),
                                                _resolve_token(args["third"])):
        raise ValueError("Fusion rejected the plane; the three point entities may be coincident or collinear.")
    return _finish_construction(component.constructionPlanes.add(construction_input), args.get("name"))


def plane_create_angle(args):
    component = _component(args.get("component"))
    construction_input = component.constructionPlanes.createInput()
    if not construction_input.setByAngle(
            _resolve_token(args["axis"]), adsk.core.ValueInput.createByString(args["angle"]),
            _resolve_token(args["reference"])):
        raise ValueError("Fusion rejected the angled-plane definition; verify the axis, plane, and angle.")
    return _finish_construction(component.constructionPlanes.add(construction_input), args.get("name"))


def axis_create_two_points(args):
    component = _component(args.get("component"))
    construction_input = component.constructionAxes.createInput()
    if not construction_input.setByTwoPoints(_resolve_token(args["first"]),
                                              _resolve_token(args["second"])):
        raise ValueError("Fusion rejected the axis; the two point entities may be coincident.")
    return _finish_construction(component.constructionAxes.add(construction_input), args.get("name"))


def axis_create_two_planes(args):
    component = _component(args.get("component"))
    construction_input = component.constructionAxes.createInput()
    if not construction_input.setByTwoPlanes(_resolve_token(args["first"]),
                                              _resolve_token(args["second"])):
        raise ValueError("Fusion rejected the axis; the planar entities may be parallel.")
    return _finish_construction(component.constructionAxes.add(construction_input), args.get("name"))


def axis_create_edge(args):
    component = _component(args.get("component"))
    construction_input = component.constructionAxes.createInput()
    if not construction_input.setByEdge(_resolve_token(args["edge"])):
        raise ValueError("Fusion rejected the axis; reference must be a supported linear or circular entity.")
    return _finish_construction(component.constructionAxes.add(construction_input), args.get("name"))


def point_create_on_entity(args):
    component = _component(args.get("component"))
    construction_input = component.constructionPoints.createInput()
    if not construction_input.setByPoint(_resolve_token(args["point"])):
        raise ValueError("Fusion rejected the point; use a vertex, sketch point, or construction point token.")
    return _finish_construction(component.constructionPoints.add(construction_input), args.get("name"))


def point_create_center(args):
    component = _component(args.get("component"))
    construction_input = component.constructionPoints.createInput()
    if not construction_input.setByCenter(_resolve_token(args["circular_entity"])):
        raise ValueError("Fusion rejected the point; use a circular edge/curve or spherical face token.")
    return _finish_construction(component.constructionPoints.add(construction_input), args.get("name"))


def construction_rename(args):
    kind, component, entity = _resolve_construction(args["construction"], args.get("kind"))
    name = args["name"].strip()
    if not name:
        raise ValueError("Construction name must not be empty.")
    entity.name = name
    if entity.name != name:
        raise RuntimeError("Fusion did not apply the construction name.")
    return _construction_info(kind, component, entity)


def _set_construction_visibility(args, visible):
    kind, component, entity = _resolve_construction(args["construction"], args.get("kind"))
    entity.isLightBulbOn = visible
    if bool(entity.isLightBulbOn) != visible:
        raise RuntimeError("Fusion did not apply the requested construction visibility.")
    return _construction_info(kind, component, entity)


def construction_show(args):
    return _set_construction_visibility(args, True)


def construction_hide(args):
    return _set_construction_visibility(args, False)


def construction_set_parameter(args):
    kind, component, entity = _resolve_construction(args["construction"], args.get("kind"))
    parameter_name = args["parameter"]
    if parameter_name not in ("offset", "angle", "distance"):
        raise ValueError("Editable construction parameter must be offset, angle, or distance.")
    definition = entity.definition
    parameter = getattr(definition, parameter_name, None)
    if parameter is None or not hasattr(parameter, "expression"):
        raise ValueError("This construction definition does not expose that editable parameter.")
    parameter.expression = args["expression"]
    if parameter.expression != args["expression"]:
        raise RuntimeError("Fusion did not apply the construction parameter expression.")
    return _construction_info(kind, component, entity)


def construction_delete(args):
    selector = args["construction"]
    if isinstance(selector, str) and selector.lower() in _ORIGIN_ALIASES:
        raise ValueError("Origin construction geometry is owned by Fusion and cannot be deleted.")
    _kind, _component_value, entity = _resolve_construction(args["construction"], args.get("kind"))
    identity = {"name": entity.name, "token": entity.entityToken}
    if not entity.deleteMe():
        raise RuntimeError(
            "Fusion rejected construction-geometry deletion; the item may be referenced, derived, or owned by another feature."
        )
    return {"deleted": identity}


def _safe_timeline_index(item):
    """Return the global index when Fusion currently exposes one."""
    try:
        index = int(item.index)
        return index if index >= 0 else None
    except Exception:
        # Grouped children do not have a global timeline index while their
        # parent is collapsed. Some Fusion builds raise here instead of -1.
        return None


def _timeline_item_info(item, group_index=None):
    entity = None
    try:
        entity = item.entity
    except Exception:
        pass
    return {
        "index": _safe_timeline_index(item),
        "group_index": group_index,
        "name": getattr(item, "name", ""),
        "group": bool(getattr(item, "isGroup", False)),
        "suppressed": bool(getattr(item, "isSuppressed", False)),
        "rolled_back": bool(getattr(item, "isRolledBack", False)),
        "health": str(getattr(item, "healthState", "")),
        "message": getattr(item, "errorOrWarningMessage", ""),
        "entity_type": getattr(entity, "objectType", None),
        "entity_token": getattr(entity, "entityToken", None),
    }


def timeline_list(args):
    timeline = _design().timeline
    return {"marker_position": int(timeline.markerPosition), "count": int(timeline.count),
            "items": [_timeline_item_info(timeline.item(index))
                      for index in range(timeline.count)]}


def timeline_inspect(args):
    timeline = _design().timeline
    index = int(args["index"])
    if index < 0 or index >= timeline.count:
        raise ValueError("Timeline index is outside the current timeline.")
    return {"marker_position": int(timeline.markerPosition),
            "item": _timeline_item_info(timeline.item(index))}


def timeline_roll(args):
    timeline = _design().timeline
    position = int(args["position"])
    if position < 0 or position > timeline.count:
        raise ValueError("Timeline marker position must be between 0 and timeline count.")
    timeline.markerPosition = position
    if int(timeline.markerPosition) != position:
        raise RuntimeError("Fusion did not move the timeline marker to the requested position.")
    return {"marker_position": position, "count": int(timeline.count),
            "warning": "Features after the marker are temporarily rolled back; this did not delete them."}


def timeline_move_beginning(args):
    timeline = _design().timeline
    if not timeline.moveToBeginning() or int(timeline.markerPosition) != 0:
        raise RuntimeError("Fusion could not move the timeline marker to the beginning.")
    return {"marker_position": 0, "count": int(timeline.count)}


def timeline_move_end(args):
    timeline = _design().timeline
    if not timeline.moveToEnd() or int(timeline.markerPosition) != int(timeline.count):
        raise RuntimeError("Fusion could not move the timeline marker to the end.")
    return {"marker_position": int(timeline.markerPosition), "count": int(timeline.count)}


def _group_info(index, group):
    return {"index": index, "name": group.name, "count": int(group.count),
            "collapsed": bool(group.isCollapsed),
            "items": [_timeline_item_info(group.item(i), i) for i in range(group.count)]}


def _timeline_group(index):
    groups = _design().timeline.timelineGroups
    index = int(index)
    if index < 0 or index >= groups.count:
        raise ValueError("Timeline group index is outside the current group collection.")
    return groups.item(index)


def timeline_groups_list(args):
    groups = _design().timeline.timelineGroups
    return {"groups": [_group_info(i, groups.item(i)) for i in range(groups.count)]}


def timeline_group_inspect(args):
    index = int(args["group"])
    return _group_info(index, _timeline_group(index))


def timeline_group_create(args):
    timeline = _design().timeline
    start, end = int(args["start"]), int(args["end"])
    if start < 0 or end < start or end >= timeline.count:
        raise ValueError("Group range must be an inclusive, ordered range within the timeline.")
    group = timeline.timelineGroups.add(start, end)
    if group is None:
        raise RuntimeError("Fusion could not group that range; it may overlap an existing group.")
    if args.get("name"):
        group.name = args["name"]
    groups = timeline.timelineGroups
    for index in range(groups.count):
        if groups.item(index) == group:
            return _group_info(index, group)
    raise RuntimeError("Fusion created the timeline group but it could not be found for verification.")


def timeline_group_rename(args):
    index = int(args["group"])
    group = _timeline_group(index)
    name = args["name"].strip()
    if not name:
        raise ValueError("Timeline group name must not be empty.")
    group.name = name
    if group.name != name:
        raise RuntimeError("Fusion did not apply the timeline group name.")
    return _group_info(index, group)


def _set_group_collapsed(args, collapsed):
    index = int(args["group"])
    group = _timeline_group(index)
    group.isCollapsed = collapsed
    if bool(group.isCollapsed) != collapsed:
        raise RuntimeError("Fusion did not apply the requested timeline-group display state.")
    return _group_info(index, group)


def timeline_group_collapse(args):
    return _set_group_collapsed(args, True)


def timeline_group_expand(args):
    return _set_group_collapsed(args, False)


def timeline_group_delete_keep(args):
    group = _timeline_group(args["group"])
    identity = {"name": group.name, "count": int(group.count)}
    # Fusion 2705 can reject deleteMe(False) for an expanded group. Collapse
    # first inside the same CadBot transaction; deleting the group then exposes
    # its retained children again.
    if not bool(group.isCollapsed):
        group.isCollapsed = True
        if not bool(group.isCollapsed):
            raise RuntimeError("Fusion could not collapse the timeline group before removal.")
    if not group.deleteMe(False):
        raise RuntimeError("Fusion rejected timeline-group removal.")
    return {"deleted_group": identity, "contents_kept": True}


def timeline_group_delete_contents(args):
    group = _timeline_group(args["group"])
    identity = {"name": group.name, "count": int(group.count)}
    if not group.deleteMe(True):
        raise RuntimeError("Fusion rejected deletion of the timeline group and its contents.")
    return {"deleted_group": identity, "contents_kept": False}


def selection_clear(args):
    selections = adsk.core.Application.get().userInterface.activeSelections
    if not selections.clear() or selections.count != 0:
        raise RuntimeError("Fusion could not clear the active selection.")
    return {"selection_count": 0}


def selection_add(args):
    entity = _resolve_token(args["entity"])
    selections = adsk.core.Application.get().userInterface.activeSelections
    if not selections.add(entity):
        raise RuntimeError("Fusion rejected the entity selection.")
    return {"selection_count": int(selections.count),
            "selected": {"token": getattr(entity, "entityToken", None),
                         "type": getattr(entity, "objectType", "")}}


def selection_remove(args):
    entity = _resolve_token(args["entity"])
    selections = adsk.core.Application.get().userInterface.activeSelections
    if not selections.removeByEntity(entity):
        raise RuntimeError("Fusion could not remove the entity from the active selection.")
    return {"selection_count": int(selections.count),
            "removed": getattr(entity, "entityToken", None)}
