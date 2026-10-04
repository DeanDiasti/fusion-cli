"""Native parametric offset and segment trimming, inside Design checkpoints."""
import adsk.core
from . import core_design
from .sketch import _find_sketch


def offset(args):
    from bridge.commands import validate_modeling
    validate_modeling('sketch_offset', args)
    sketch = _find_sketch(args['sketch'])
    curves = [core_design._curve(sketch, token) for token in args['entities']]
    if any(curve == other for i, curve in enumerate(curves) for other in curves[:i]):
        raise ValueError('Offset sources resolve to duplicate curves.')
    constraints = sketch.geometricConstraints
    if not hasattr(constraints, 'createOffsetInput') or not hasattr(constraints, 'addOffset2'):
        raise RuntimeError('This Fusion version does not support parametric addOffset2.')
    inp = constraints.createOffsetInput(curves, adsk.core.ValueInput.createByReal(args['distance_mm'] / 10))
    if inp is None:
        raise RuntimeError('Fusion rejected the offset input; provide end-connected curves in flow order.')
    inp.isTopologyMatched = True
    result = constraints.addOffset2(inp)
    if result is None or not result.isValid:
        raise RuntimeError('Fusion did not create a valid offset constraint.')
    created = list(result.childCurves)
    if not created or any(not curve.isValid for curve in created):
        raise RuntimeError('Fusion did not create valid offset curves.')
    return {'sketch': sketch.entityToken, 'constraint': result.entityToken,
            'distance_mm': args['distance_mm'], 'topology_matched': True,
            'created': [core_design.geometry_info(curve) for curve in created],
            'profiles': sketch.profiles.count}


def trim(args):
    sketch = _find_sketch(args['sketch'])
    point = core_design._point(args['x_mm'], args['y_mm'])
    curve = core_design._curve(sketch, args['entity'])
    token = curve.entityToken
    if curve.isLinked or curve.isFixed:
        raise ValueError('Cannot trim linked or fixed geometry; detach/unfix it first.')
    result = curve.trim(point, True)
    if result is None:
        raise RuntimeError('Fusion rejected trimming.')
    created = core_design._items(result)
    if any(not c.isValid for c in created):
        raise RuntimeError('Fusion returned invalid trimmed geometry.')
    return {'sketch': sketch.entityToken, 'original_token': token,
            'original_survives': bool(curve.isValid),
            'result_curves': [core_design.geometry_info(c) for c in created],
            'profiles': sketch.profiles.count,
            'note': 'The segment nearest the sketch-space point is removed. Without intersections the entire curve is deleted. Refresh geometry tokens after trimming.'}
