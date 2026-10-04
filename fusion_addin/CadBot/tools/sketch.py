"""Sketch tools (run on Fusion's main thread). All coordinates/dimensions in mm."""

import adsk.core
import adsk.fusion

_PLANES = {
    "XY": "xYConstructionPlane",
    "XZ": "xZConstructionPlane",
    "YZ": "yZConstructionPlane",
}


def _mm(value):
    return adsk.core.ValueInput.createByReal(float(value) / 10.0)  # mm -> internal cm


def _get_root():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design")
    return design.rootComponent


def create_sketch(args):
    from bridge.commands import validate_modeling
    from . import design_structure, sketch_support
    validate_modeling('create_sketch', args)
    component = design_structure._component(args['component']) if args.get('component') else None
    if args.get('support'):
        root, target = sketch_support.support(args['support'], component)
    else:
        root = component or _get_root()
        plane = (args.get('plane') or 'XY').upper()
        if plane not in _PLANES:
            raise ValueError('plane must be one of XY, XZ, YZ')
        target = getattr(root, _PLANES[plane])
        offset_mm = float(args.get('offset_mm', 0.0))
        if offset_mm:
            plane_input = root.constructionPlanes.createInput()
            if not plane_input.setByOffset(target, _mm(offset_mm)):
                raise RuntimeError('Fusion rejected the offset sketch plane.')
            target = root.constructionPlanes.add(plane_input)
    sketch = root.sketches.addWithoutEdges(target) if args.get('support') else root.sketches.add(target)
    if sketch is None:
        raise RuntimeError('Fusion rejected sketch creation.')
    sketch.name = args.get('name') or sketch.name
    result = {'sketch_name': sketch.name, 'token': sketch.entityToken,
              'component': root.name, 'component_token': root.entityToken}
    if args.get('support'):
        result.update(support=target.entityToken, frame=sketch_support.frame(sketch))
    return result


def _find_sketch(name):
    root = _get_root()
    design=root.parentDesign
    matches=[]
    try:
        matches=[s for s in design.findEntityByToken(name) if adsk.fusion.Sketch.cast(s) is not None]
    except RuntimeError:
        pass  # A plain sketch name is not an entity token.
    if not matches:
        matches=[s for c in design.allComponents for s in c.sketches if s.name == name]
    if len(matches) != 1:
        raise ValueError('Sketch selector must match exactly one sketch. Use its token from sketches list.')
    return matches[0]


def list_sketches(args):
    return {'sketches':[{'name':s.name,'token':s.entityToken,'component':c.name,
                        'curves':s.sketchCurves.count,'profiles':s.profiles.count,
                        'fully_constrained':s.isFullyConstrained}
                       for c in _get_root().parentDesign.allComponents for s in c.sketches]}


def inspect_sketch(args):
    s=_find_sketch(args['sketch'])
    return {'name':s.name,'token':s.entityToken,'profiles':s.profiles.count,
            'curves':[{'index':i,'token':s.sketchCurves.item(i).entityToken,
                       'type':s.sketchCurves.item(i).objectType,
                       'construction':s.sketchCurves.item(i).isConstruction}
                      for i in range(s.sketchCurves.count)],
            'dimensions':[{'index':i,'parameter':s.sketchDimensions.item(i).parameter.name,
                           'expression':s.sketchDimensions.item(i).parameter.expression}
                          for i in range(s.sketchDimensions.count)]}


def rename_sketch(args):
    s=_find_sketch(args['sketch']);s.name=args['name']
    return {'name':s.name,'token':s.entityToken}


def delete_sketch(args):
    s=_find_sketch(args['sketch'])
    name=s.name
    if not s.deleteMe(): raise RuntimeError('Fusion rejected sketch deletion')
    return {'deleted':name}


def add_circle(args):
    sketch = _find_sketch(args["sketch"])
    # Sketch coordinates are in sketch space; adsk stores cm internally, mm -> cm.
    center = adsk.core.Point3D.create(
        float(args["center_x"]) / 10.0, float(args["center_y"]) / 10.0, 0
    )
    radius = float(args["radius"]) / 10.0
    circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(center, radius)
    return {"curve_index": sketch.sketchCurves.count - 1}


def add_rectangle(args):
    sketch = _find_sketch(args["sketch"])
    x1 = float(args["x1"]) / 10.0
    y1 = float(args["y1"]) / 10.0
    x2 = float(args["x2"]) / 10.0
    y2 = float(args["y2"]) / 10.0
    p1 = adsk.core.Point3D.create(x1, y1, 0)
    p2 = adsk.core.Point3D.create(x2, y2, 0)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)
    return {"curve_count": sketch.sketchCurves.count}


def add_line(args):
    sketch = _find_sketch(args["sketch"])
    p1 = adsk.core.Point3D.create(float(args["x1"]) / 10.0, float(args["y1"]) / 10.0, 0)
    p2 = adsk.core.Point3D.create(float(args["x2"]) / 10.0, float(args["y2"]) / 10.0, 0)
    sketch.sketchCurves.sketchLines.addByTwoPoints(p1, p2)
    return {"curve_count": sketch.sketchCurves.count}


def add_dimension(args):
    sketch = _find_sketch(args["sketch"])
    # Dimension between two points (first two curves' endpoints) is complex;
    # the common case the agent uses: dimension a circle's diameter or a line length.
    target = args.get("target")
    if target == "circle_diameter":
        idx = int(args.get("curve_index", sketch.sketchCurves.count - 1))
        curve = sketch.sketchCurves.item(idx)
        dim = sketch.sketchDimensions.addDiameterDimension(
            curve, adsk.core.Point3D.create(0, 0, 0)
        )
        dim.parameter.expression = "{} mm".format(args["value_mm"])
        return {"dimension": "diameter", "value_mm": args["value_mm"]}
    if target == "line_length":
        idx = int(args.get("curve_index", sketch.sketchCurves.count - 1))
        curve = sketch.sketchCurves.item(idx)
        dim = sketch.sketchDimensions.addDistanceDimension(
            curve.startSketchPoint, curve.endSketchPoint,
            adsk.fusion.DimensionOrientations.AlignedDimensionOrientation,
            adsk.core.Point3D.create(0, 0, 0),
        )
        dim.parameter.expression = "{} mm".format(args["value_mm"])
        return {"dimension": "length", "value_mm": args["value_mm"]}
    raise ValueError("target must be 'circle_diameter' or 'line_length'")
