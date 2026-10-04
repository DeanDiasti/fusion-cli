"""Feature tools: extrude, revolve, fillet, chamfer, patterns (main thread)."""

import math

import adsk.core
import adsk.fusion

from .sketch import _find_sketch


def _vi_mm(value):
    return adsk.core.ValueInput.createByReal(float(value) / 10.0)  # mm -> cm


def _get_design():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design")
    return design


def _get_root():
    return _get_design().rootComponent


def _profile_from_sketch(sketch, index=0):
    if sketch.profiles.count == 0:
        raise RuntimeError(
            "Sketch '{}' has no closed profile. Check that curves form a closed loop.".format(sketch.name)
        )
    if type(index) is not int or not 0 <= index < sketch.profiles.count:
        raise ValueError('profile_index must be between 0 and {}. Use sketches profiles list.'.format(
            sketch.profiles.count - 1))
    return sketch.profiles.item(index)


def extrude(args):
    """Extrude a selected profile (default 0) in its sketch's owning component."""
    from bridge.commands import validate_modeling
    validate_modeling("extrude", args)
    sketch = _find_sketch(args["sketch"])
    root = sketch.parentComponent
    participants = None
    if 'participants' in args:
        from .design_solids import _body
        participants = [_body(selector) for selector in args['participants']]
        if any(body.parentComponent != root or not body.isSolid for body in participants):
            raise ValueError('Participant bodies must be solid and belong to the sketch component.')
        if any(body == other for i, body in enumerate(participants) for other in participants[:i]):
            raise ValueError('Participant selectors resolve to duplicate bodies.')
    profile = _profile_from_sketch(sketch, args.get('profile_index', 0))
    if args.get('extent') == 'through-all' and root != root.parentDesign.rootComponent:
        occurrences = root.parentDesign.rootComponent.allOccurrencesByComponent(root)
        identity = (1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1)
        if occurrences.count == 0 or any(
                any(abs(a-b) > 1e-9 for a,b in zip(occurrences.item(i).transform2.asArray(), identity))
                for i in range(occurrences.count)):
            raise ValueError('Through-all in moved or rotated components is unavailable in this Fusion build. '
                             'Use a root/untransformed component or an explicit distance extrusion.')
    ext_input = root.features.extrudeFeatures.createInput(
        profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    op = (args.get("operation") or "join").lower()
    ops = {
        "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
        "new": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
    }
    ext_input.operation = ops[op]
    if args.get('extent', 'distance') == 'through-all':
        direction = args.get('direction', 'positive')
        extent = adsk.fusion.ThroughAllExtentDefinition.create()
        taper = _angle(float(args.get('taper_angle_deg', 0)))
        if direction == 'both':
            accepted = ext_input.setTwoSidesExtent(extent, adsk.fusion.ThroughAllExtentDefinition.create(), taper, taper)
        else:
            directions = adsk.fusion.ExtentDirections
            side = directions.PositiveExtentDirection if direction == 'positive' else directions.NegativeExtentDirection
            accepted = ext_input.setOneSideExtent(extent, side, taper)
        if not accepted:
            raise RuntimeError('Fusion rejected through-all extent.')
    else:
        distance = _vi_mm(args['distance_mm'])
        accepted = ext_input.setSymmetricExtent(distance, True) if args.get('symmetric') else ext_input.setDistanceExtent(False, distance)
        if not accepted:
            raise RuntimeError('Fusion rejected extrusion distance.')
        if args.get('taper_angle_deg'):
            ext_input.taperAngle = _angle(float(args['taper_angle_deg']))
    if participants is not None:
        ext_input.participantBodies = participants
    feature = root.features.extrudeFeatures.add(ext_input)
    if feature is None:
        raise RuntimeError("Fusion rejected extrusion creation.")
    if feature.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
        raise RuntimeError('Fusion could not produce a healthy extrusion: ' + feature.errorOrWarningMessage)
    return {"feature": feature.name, "token": feature.entityToken, "extent": args.get("extent", "distance"),
            "body": feature.bodies.item(0).name if feature.bodies.count else None}


def revolve(args):
    """Revolve a selected profile about its component's X or Y origin axis."""
    sketch = _find_sketch(args["sketch"])
    root = sketch.parentComponent
    profile = _profile_from_sketch(sketch, args.get('profile_index', 0))
    axis = (args.get("axis") or "X").upper()
    if axis == "X":
        axis_line = root.xConstructionAxis
    else:
        axis_line = root.yConstructionAxis
    rev_input = root.features.revolveFeatures.createInput(
        profile, axis_line, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    angle = _angle(float(args.get("angle_deg", 360)))
    rev_input.setAngleExtent(False, angle)
    feature = root.features.revolveFeatures.add(rev_input)
    return {"feature": feature.name}


def fillet(args):
    """args: radius_mm, edge_indices (optional list of body edges to fillet; default all convex edges)"""
    root = _get_root()
    body = _body_by_name_or_last(args.get("body"))
    edges = adsk.core.ObjectCollection.create()
    indices = args.get("edge_indices")
    if indices:
        for i in indices:
            edges.add(body.edges.item(int(i)))
    else:
        for i in range(body.edges.count):
            edges.add(body.edges.item(i))
    fillet_input = root.features.filletFeatures.createInput()
    fillet_input.addConstantRadiusEdgeSet(edges, _vi_mm(args["radius_mm"]), True)
    feature = root.features.filletFeatures.add(fillet_input)
    return {"feature": feature.name}


def chamfer(args):
    """args: distance_mm, edge_indices (optional)"""
    root = _get_root()
    body = _body_by_name_or_last(args.get("body"))
    edges = adsk.core.ObjectCollection.create()
    indices = args.get("edge_indices")
    if indices:
        for i in indices:
            edges.add(body.edges.item(int(i)))
    else:
        for i in range(body.edges.count):
            edges.add(body.edges.item(i))
    chamfer_input = root.features.chamferFeatures.createInput2()
    chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
        edges, _vi_mm(args["distance_mm"]), True
    )
    feature = root.features.chamferFeatures.add(chamfer_input)
    return {"feature": feature.name}


def circular_pattern(args):
    """args: body, axis 'X'|'Y'|'Z', count, angle_deg(optional, default 360)"""
    root = _get_root()
    body = _body_by_name_or_last(args.get("body"))
    input_entities = adsk.core.ObjectCollection.create()
    input_entities.add(body)
    axis = (args.get("axis") or "Z").upper()
    axes = {"X": root.xConstructionAxis, "Y": root.yConstructionAxis, "Z": root.zConstructionAxis}
    pattern_input = root.features.circularPatternFeatures.createInput(
        input_entities, axes[axis]
    )
    pattern_input.quantity = adsk.core.ValueInput.createByReal(int(args["count"]))
    pattern_input.isSymmetric = False
    pattern_input.angle = _angle(
        float(args.get("angle_deg", 360))
    )
    feature = root.features.circularPatternFeatures.add(pattern_input)
    return {"feature": feature.name}


def rectangular_pattern(args):
    """args: body, direction_x_count, direction_y_count, spacing_x_mm, spacing_y_mm"""
    root = _get_root()
    body = _body_by_name_or_last(args.get("body"))
    input_entities = adsk.core.ObjectCollection.create()
    input_entities.add(body)
    pattern_input = root.features.rectangularPatternFeatures.createInput(
        input_entities, root.xConstructionAxis,
        adsk.core.ValueInput.createByReal(int(args["direction_x_count"])),
        _vi_mm(args["spacing_x_mm"]),
        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
    )
    pattern_input.directionTwoEntity = root.yConstructionAxis
    pattern_input.quantityTwo = adsk.core.ValueInput.createByReal(int(args["direction_y_count"]))
    pattern_input.distanceTwo = _vi_mm(args["spacing_y_mm"])
    feature = root.features.rectangularPatternFeatures.add(pattern_input)
    return {"feature": feature.name}


def _body_by_name_or_last(name):
    root = _get_root()
    if name:
        body = root.bRepBodies.itemByName(name)
        if body is None:
            raise ValueError("Body not found: {}".format(name))
        return body
    if root.bRepBodies.count == 0:
        raise RuntimeError("No bodies in the design")
    return root.bRepBodies.item(root.bRepBodies.count - 1)


def _angle(degrees):
    return adsk.core.ValueInput.createByReal(math.radians(float(degrees)))
