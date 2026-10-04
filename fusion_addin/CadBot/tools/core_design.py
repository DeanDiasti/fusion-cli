"""Bounded, typed editing for existing Fusion sketch geometry.

All public coordinates are millimetres. Entity, constraint, and dimension targets
are Fusion entity tokens returned by the list/create handlers in this module.
"""

import math

import adsk.core

from .sketch import _find_sketch


def _items(collection):
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(index) for index in range(collection.count)]
    return list(collection)


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + " must be a finite number.")
    return float(value)


def _point(x_mm, y_mm):
    return adsk.core.Point3D.create(
        _number(x_mm, "x") / 10.0, _number(y_mm, "y") / 10.0, 0
    )


def _xy(point):
    return {"x_mm": float(point.x) * 10.0, "y_mm": float(point.y) * 10.0}


def _kind(item):
    return str(item.objectType).rsplit("::", 1)[-1]


def _same(left, right):
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:
        return False


def _design(sketch):
    component = sketch.parentComponent
    return component.parentDesign


def _resolve(sketch, token, collection, label):
    if not isinstance(token, str) or not token:
        raise ValueError("Provide a " + label + " token returned by its list command.")
    try:
        candidates = _items(_design(sketch).findEntityByToken(token))
    except RuntimeError:
        candidates = []
    current = _items(collection)
    matches = [
        candidate
        for candidate in candidates
        if getattr(candidate, "isValid", False)
        and any(_same(candidate, item) for item in current)
    ]
    if len(matches) != 1:
        raise ValueError(
            label.capitalize()
            + " token is stale, invalid, or ambiguous. List the sketch again."
        )
    return matches[0]


def _curve(sketch, token):
    return _resolve(sketch, token, sketch.sketchCurves, "curve")


def _constraint(sketch, token):
    return _resolve(sketch, token, sketch.geometricConstraints, "constraint")


def _dimension(sketch, token):
    return _resolve(sketch, token, sketch.sketchDimensions, "dimension")


def _require_kind(entity, expected, label):
    if _kind(entity) not in expected:
        raise ValueError(label + " requires " + " or ".join(sorted(expected)) + ".")
    return entity


def geometry_info(curve):
    info = {
        "token": curve.entityToken,
        "type": _kind(curve),
        "construction": bool(curve.isConstruction),
        "fixed": bool(curve.isFixed),
        "fully_constrained": bool(curve.isFullyConstrained),
        "deletable": bool(curve.isDeletable),
        "linked": bool(curve.isLinked),
    }
    if info["type"] == "SketchLine":
        info["start"] = _xy(curve.startSketchPoint.geometry)
        info["end"] = _xy(curve.endSketchPoint.geometry)
        info["length_mm"] = float(curve.length) * 10.0
        info["centerline"] = bool(curve.isCenterLine)
    elif info["type"] == "SketchCircle":
        info["center"] = _xy(curve.centerSketchPoint.geometry)
        info["radius_mm"] = float(curve.radius) * 10.0
    elif info["type"] == "SketchArc":
        info.update(start=_xy(curve.startSketchPoint.geometry),
                    end=_xy(curve.endSketchPoint.geometry),
                    center=_xy(curve.centerSketchPoint.geometry),
                    radius_mm=float(curve.radius) * 10.0,
                    length_mm=float(curve.length) * 10.0)
    elif info["type"] == "SketchFittedSpline":
        info.update(fit_points_mm=[_xy(p.geometry) for p in _items(curve.fitPoints)],
                    closed=bool(curve.isClosed), length_mm=float(curve.length) * 10.0)
    return info


def geometry_list(args):
    sketch = _find_sketch(args["sketch"])
    return {
        "sketch": {"name": sketch.name, "token": sketch.entityToken},
        "geometry": [geometry_info(item) for item in _items(sketch.sketchCurves)],
        "points": [
            {"index": index, "token": point.entityToken,
             "position": _xy(point.geometry), "fixed": bool(point.isFixed)}
            for index, point in enumerate(_items(getattr(sketch, "sketchPoints", [])))
        ],
        "rectangle_note": "Fusion stores rectangles as four SketchLine entities, not as a persistent rectangle object.",
    }


def _point_pairs(value, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError('points_mm must contain {} to {} [x, y] points.'.format(minimum, maximum))
    points = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError('Each points_mm entry must be an [x, y] pair in millimetres.')
        points.append((_number(pair[0], 'x'), _number(pair[1], 'y')))
    if len(set(points)) != len(points):
        raise ValueError('Use distinct points; use --closed true to close a spline.')
    return points


def arcs_add(args):
    """Three sketch-space points: start, a point along the arc, end."""
    points = _point_pairs(args['points_mm'], 3, 3)
    a, b, c = points
    u = (b[0] - a[0], b[1] - a[1])
    v = (c[0] - a[0], c[1] - a[1])
    if abs(u[0] * v[1] - u[1] * v[0]) <= 1e-10 * math.hypot(*u) * math.hypot(*v):
        raise ValueError('Arc points must not be collinear.')
    sketch = _find_sketch(args['sketch'])
    arc = sketch.sketchCurves.sketchArcs.addByThreePoints(*[_point(*p) for p in points])
    if arc is None or not arc.isValid:
        raise RuntimeError('Fusion rejected sketch arc creation.')
    return {'arc': geometry_info(arc),
            'note': 'Fusion stores arcs counterclockwise; returned endpoints may be reversed.'}


def splines_add(args):
    closed = args.get('closed', False)
    if type(closed) is not bool:
        raise ValueError('closed must be true or false.')
    points = _point_pairs(args['points_mm'], 3 if closed else 2, 100)
    sketch = _find_sketch(args['sketch'])
    fit_points = adsk.core.ObjectCollection.create()
    for pair in points:
        fit_points.add(_point(*pair))
    spline = sketch.sketchCurves.sketchFittedSplines.add(fit_points)
    if spline is None or not spline.isValid:
        raise RuntimeError('Fusion rejected fitted spline creation.')
    if closed:
        spline.isClosed = True
    if bool(spline.isClosed) != closed:
        raise RuntimeError('Fusion did not apply the requested spline closure.')
    return {'spline': geometry_info(spline)}


def points_add(args):
    position = _point(args['x_mm'], args['y_mm'])
    sketch = _find_sketch(args['sketch'])
    point = sketch.sketchPoints.add(position)
    if point is None or not point.isValid:
        raise RuntimeError('Fusion rejected sketch point creation.')
    return {'point': {'token': point.entityToken, 'position': _xy(point.geometry)},
            'note': 'Use geometry list for the current point index before creating a hole.'}


def profiles_list(args):
    sketch = _find_sketch(args['sketch'])
    profiles = []
    for index, profile in enumerate(_items(sketch.profiles)):
        area = profile.areaProperties()
        if area is None:
            raise RuntimeError('Fusion could not calculate profile area properties.')
        profiles.append({'index': index, 'area_mm2': float(area.area) * 100.0,
                         'perimeter_mm': float(area.perimeter) * 10.0,
                         'centroid': _xy(area.centroid),
                         'loop_count': profile.profileLoops.count})
    return {'sketch': {'name': sketch.name, 'token': sketch.entityToken},
            'profiles': profiles,
            'note': 'Indices can change after sketch edits. List again before using --profile-index. '
                    'Coordinates are in sketch space; area properties use Fusion default accuracy (about 1%).'}


def lines_add(args):
    sketch = _find_sketch(args["sketch"])
    line = sketch.sketchCurves.sketchLines.addByTwoPoints(
        _point(args["x1_mm"], args["y1_mm"]),
        _point(args["x2_mm"], args["y2_mm"]),
    )
    if line is None:
        raise RuntimeError("Fusion rejected sketch line creation.")
    return {"line": geometry_info(line)}


def lines_edit(args):
    sketch = _find_sketch(args["sketch"])
    line = _require_kind(_curve(sketch, args["entity"]), {"SketchLine"}, "Line edit")
    targets = (
        (line.startSketchPoint, args["x1_mm"], args["y1_mm"]),
        (line.endSketchPoint, args["x2_mm"], args["y2_mm"]),
    )
    for point, x_mm, y_mm in targets:
        current = point.geometry
        translation = adsk.core.Vector3D.create(
            _number(x_mm, "x") / 10.0 - current.x,
            _number(y_mm, "y") / 10.0 - current.y,
            -current.z,
        )
        if not point.move(translation):
            raise RuntimeError("Fusion constraints rejected a line endpoint move.")
    return {"line": geometry_info(line)}


def circles_add(args):
    sketch = _find_sketch(args["sketch"])
    radius = _number(args["radius_mm"], "radius_mm")
    if radius <= 0:
        raise ValueError("radius_mm must be greater than zero.")
    circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(
        _point(args["center_x_mm"], args["center_y_mm"]), radius / 10.0
    )
    if circle is None:
        raise RuntimeError("Fusion rejected sketch circle creation.")
    return {"circle": geometry_info(circle)}


def circles_edit(args):
    sketch = _find_sketch(args["sketch"])
    circle = _require_kind(
        _curve(sketch, args["entity"]), {"SketchCircle"}, "Circle edit"
    )
    radius = _number(args["radius_mm"], "radius_mm")
    if radius <= 0:
        raise ValueError("radius_mm must be greater than zero.")
    current = circle.centerSketchPoint.geometry
    translation = adsk.core.Vector3D.create(
        _number(args["center_x_mm"], "center_x_mm") / 10.0 - current.x,
        _number(args["center_y_mm"], "center_y_mm") / 10.0 - current.y,
        -current.z,
    )
    if not circle.centerSketchPoint.move(translation):
        raise RuntimeError("Fusion constraints rejected the circle center move.")
    circle.radius = radius / 10.0
    if abs(float(circle.radius) * 10.0 - radius) > 1e-6:
        raise RuntimeError("Fusion constraints rejected the requested circle radius.")
    return {"circle": geometry_info(circle)}


def rectangles_add(args):
    sketch = _find_sketch(args["sketch"])
    created = sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        _point(args["x1_mm"], args["y1_mm"]),
        _point(args["x2_mm"], args["y2_mm"]),
    )
    lines = _items(created)
    if len(lines) != 4:
        raise RuntimeError("Fusion did not create the expected four rectangle lines.")
    return {
        "lines": [geometry_info(line) for line in lines],
        "note": "The rectangle is represented by four independently selectable lines.",
    }


def geometry_set_construction(args):
    sketch = _find_sketch(args["sketch"])
    curve = _curve(sketch, args["entity"])
    requested = args["construction"]
    if type(requested) is not bool:
        raise ValueError("construction must be true or false.")
    curve.isConstruction = requested
    if bool(curve.isConstruction) != requested:
        raise RuntimeError("Fusion rejected the construction geometry change.")
    return {"geometry": geometry_info(curve)}


def geometry_set_fixed(args):
    sketch = _find_sketch(args["sketch"])
    curve = _curve(sketch, args["entity"])
    requested = args["fixed"]
    if type(requested) is not bool:
        raise ValueError("fixed must be true or false.")
    curve.isFixed = requested
    if bool(curve.isFixed) != requested:
        raise RuntimeError("Fusion rejected the fixed geometry change.")
    return {"geometry": geometry_info(curve)}


def geometry_delete(args):
    sketch = _find_sketch(args["sketch"])
    curve = _curve(sketch, args["entity"])
    token, kind = curve.entityToken, _kind(curve)
    if not curve.isDeletable:
        raise ValueError("Sketch entity is not deletable because other geometry depends on it.")
    if not curve.deleteMe():
        raise RuntimeError("Fusion rejected sketch entity deletion.")
    return {"deleted": {"token": token, "type": kind}}


def constraint_info(constraint):
    return {
        "token": constraint.entityToken,
        "type": _kind(constraint),
        "deletable": bool(constraint.isDeletable),
    }


def constraints_list(args):
    sketch = _find_sketch(args["sketch"])
    return {
        "sketch": {"name": sketch.name, "token": sketch.entityToken},
        "constraints": [
            constraint_info(item) for item in _items(sketch.geometricConstraints)
        ],
    }


def _point_on(entity, point_name):
    choices = {
        "start": "startSketchPoint",
        "end": "endSketchPoint",
        "center": "centerSketchPoint",
    }
    prop = choices.get(point_name)
    if prop is None or not hasattr(entity, prop):
        raise ValueError("Point must be start/end for a line or center for a circle.")
    return getattr(entity, prop)


def constraints_add(args):
    sketch = _find_sketch(args["sketch"])
    first = _curve(sketch, args["entity"])
    second = _curve(sketch, args["second_entity"]) if args.get("second_entity") else None
    third = _curve(sketch, args["symmetry_line"]) if args.get("symmetry_line") else None
    constraints = sketch.geometricConstraints
    kind = args["type"]

    if kind == "horizontal":
        result = constraints.addHorizontal(_require_kind(first, {"SketchLine"}, kind))
    elif kind == "vertical":
        result = constraints.addVertical(_require_kind(first, {"SketchLine"}, kind))
    elif kind in {"parallel", "collinear"}:
        _require_kind(first, {"SketchLine"}, kind)
        _require_kind(second, {"SketchLine"}, kind)
        method = constraints.addParallel if kind == "parallel" else constraints.addCollinear
        result = method(first, second)
    elif kind == "perpendicular":
        _require_kind(first, {"SketchLine"}, kind)
        if second is None:
            raise ValueError("perpendicular requires second_entity.")
        result = constraints.addPerpendicular2(first, second)
    elif kind in {"tangent", "equal", "concentric", "smooth"}:
        if second is None:
            raise ValueError(kind + " requires second_entity.")
        methods = {
            "tangent": constraints.addTangent,
            "equal": constraints.addEqual,
            "concentric": constraints.addConcentric,
            "smooth": constraints.addSmooth,
        }
        result = methods[kind](first, second)
    elif kind == "coincident":
        if second is None:
            raise ValueError("coincident requires second_entity.")
        target = (
            _point_on(second, args["second_point"])
            if args.get("second_point")
            else second
        )
        result = constraints.addCoincident(_point_on(first, args.get("point")), target)
    elif kind == "midpoint":
        if second is None:
            raise ValueError("midpoint requires second_entity.")
        result = constraints.addMidPoint(_point_on(first, args.get("point")), second)
    elif kind in {"horizontal-points", "vertical-points"}:
        if second is None:
            raise ValueError(kind + " requires second_entity.")
        one = _point_on(first, args.get("point"))
        two = _point_on(second, args.get("second_point"))
        method = (
            constraints.addHorizontalPoints
            if kind == "horizontal-points"
            else constraints.addVerticalPoints
        )
        result = method(one, two)
    elif kind == "symmetry":
        if second is None or third is None:
            raise ValueError("symmetry requires second_entity and symmetry_line.")
        result = constraints.addSymmetry(
            first, second, _require_kind(third, {"SketchLine"}, kind)
        )
    else:
        raise ValueError(
            "Unsupported constraint type. Use horizontal, vertical, parallel, perpendicular, "
            "collinear, tangent, equal, concentric, smooth, coincident, midpoint, "
            "horizontal-points, vertical-points, or symmetry."
        )
    if result is None:
        raise RuntimeError("Fusion rejected the geometric constraint.")
    return {"constraint": constraint_info(result)}


def constraints_delete(args):
    sketch = _find_sketch(args["sketch"])
    constraint = _constraint(sketch, args["constraint"])
    info = constraint_info(constraint)
    if not constraint.isDeletable:
        raise ValueError("Geometric constraint is not deletable.")
    if not constraint.deleteMe():
        raise RuntimeError("Fusion rejected geometric constraint deletion.")
    return {"deleted": info}


def dimension_info(dimension):
    parameter = dimension.parameter
    return {
        "token": dimension.entityToken,
        "type": _kind(dimension),
        "driving": bool(dimension.isDriving),
        "deletable": bool(dimension.isDeletable),
        "expression": parameter.expression if parameter is not None else None,
        "parameter": parameter.name if parameter is not None else None,
        "unit": parameter.unit if parameter is not None else None,
        "value_internal": float(dimension.value),
    }


def dimensions_list(args):
    sketch = _find_sketch(args["sketch"])
    return {
        "sketch": {"name": sketch.name, "token": sketch.entityToken},
        "dimensions": [dimension_info(item) for item in _items(sketch.sketchDimensions)],
    }


def dimensions_set(args):
    sketch = _find_sketch(args["sketch"])
    dimension = _dimension(sketch, args["dimension"])
    parameter = dimension.parameter
    if parameter is None:
        raise ValueError(
            "This direct-modeling dimension has no parameter; expression editing is unavailable."
        )
    expected = args.get("expected_expression")
    if expected is not None and parameter.expression != expected:
        raise ValueError(
            "Dimension changed since inspection; expected "
            + expected
            + " but found "
            + parameter.expression
            + "."
        )
    expression = args["expression"]
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("expression must be a non-empty Fusion expression.")
    parameter.expression = expression.strip()
    design = _design(sketch)
    if hasattr(design, "computeAll") and not design.computeAll():
        raise RuntimeError("Fusion could not recompute after changing the dimension.")
    return {"dimension": dimension_info(dimension)}


def dimensions_delete(args):
    sketch = _find_sketch(args["sketch"])
    dimension = _dimension(sketch, args["dimension"])
    info = dimension_info(dimension)
    if not dimension.isDeletable:
        raise ValueError("Sketch dimension is not deletable.")
    if not dimension.deleteMe():
        raise RuntimeError("Fusion rejected sketch dimension deletion.")
    return {"deleted": info}
