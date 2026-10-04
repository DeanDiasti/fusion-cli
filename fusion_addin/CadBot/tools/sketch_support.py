"""Face/plane sketch supports and bounded same-component projection."""
import adsk.core

from . import design_structure
from .sketch import _find_sketch


def native(entity):
    return getattr(entity, 'nativeObject', None) or entity


def owner(entity):
    entity = native(entity)
    body = getattr(entity, 'body', None)
    sketch = getattr(entity, 'parentSketch', None)
    return (body.parentComponent if body is not None else
            sketch.parentComponent if sketch is not None else
            getattr(entity, 'parentComponent', None) or getattr(entity, 'component', None))


def kind(entity):
    return entity.objectType.rsplit('::', 1)[-1]


def support(selector, component=None):
    entity = native(design_structure._resolve_token(selector))
    if kind(entity) == 'BRepFace':
        if adsk.core.Plane.cast(entity.geometry) is None:
            raise ValueError('Sketch support must be a planar face.')
    elif kind(entity) != 'ConstructionPlane':
        raise ValueError('Sketch support must be a planar face or construction-plane token.')
    parent = owner(entity)
    if parent is None or (component is not None and parent != component):
        raise ValueError('Sketch support must belong to the requested component.')
    return parent, entity


def frame(sketch):
    points = [sketch.sketchToModelSpace(adsk.core.Point3D.create(*p))
              for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))]
    origin = points[0]
    return {'origin_mm': [origin.x * 10, origin.y * 10, origin.z * 10],
            **{name: [p.x-origin.x, p.y-origin.y, p.z-origin.z]
               for name, p in zip(('x_axis', 'y_axis', 'normal'), points[1:])},
            'coordinate_space': 'owning_component'}


def project_geometry(args):
    from bridge.commands import validate_modeling
    validate_modeling('project_geometry', args)
    sketch = _find_sketch(args['sketch'])
    entities = []
    accepted = {'BRepEdge', 'BRepFace', 'BRepVertex', 'SketchPoint',
                'SketchLine', 'SketchArc', 'SketchCircle', 'SketchEllipse',
                'SketchEllipticalArc', 'SketchFittedSpline', 'SketchFixedSpline',
                'SketchControlPointSpline'}
    for token in args['entities']:
        entity = design_structure._resolve_token(token)
        if getattr(entity, 'assemblyContext', None) is not None:
            raise ValueError('Projection requires native component geometry, not assembly-context proxies.')
        if kind(entity) not in accepted or owner(entity) != sketch.parentComponent:
            raise ValueError('Project edges, faces, vertices, or sketch geometry from the same component.')
        if getattr(entity, 'parentSketch', None) == sketch:
            raise ValueError('Cannot project a sketch entity into its own sketch.')
        if any(entity == other for other in entities):
            raise ValueError('Projection sources resolve to duplicate entities.')
        entities.append(entity)
    if not hasattr(sketch, 'project2'):
        raise RuntimeError('This Fusion version does not support linked/unlinked project2.')
    linked = args.get('linked', True)
    created = list(sketch.project2(entities, linked) or [])
    if not created or any(not item.isValid for item in created):
        raise RuntimeError('Fusion did not produce valid projected geometry.')
    if any(bool(item.isLinked) != linked for item in created):
        raise RuntimeError('Fusion did not apply the requested projection link state.')
    return {'sketch': sketch.entityToken, 'linked': linked, 'created_count': len(created),
            'entities': [{'token': item.entityToken, 'type': kind(item)} for item in created],
            'profiles': sketch.profiles.count}


def body_topology(args):
    """Discover native face/edge/vertex tokens without selecting in the viewport."""
    from .design_solids import _body
    body = _body(args['body'])
    category = args.get('kind', 'faces')
    offset, limit = args.get('offset', 0), args.get('limit', 100)
    if category not in ('faces', 'edges', 'vertices') or type(offset) is not int or offset < 0 \
            or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Use faces/edges/vertices, nonnegative offset, and limit between 1 and 1000.')
    collection = getattr(body, category)
    rows = []
    for index in range(offset, min(offset + limit, collection.count)):
        entity = collection.item(index)
        row = {'index': index, 'token': entity.entityToken, 'type': kind(entity)}
        if category == 'faces':
            point = entity.pointOnFace
            plane = adsk.core.Plane.cast(entity.geometry)
            row.update(planar=plane is not None, area_mm2=entity.area * 100,
                       point_mm=[point.x * 10, point.y * 10, point.z * 10])
            if plane is not None:
                ok, normal = entity.evaluator.getNormalAtPoint(point)
                if ok:
                    row['normal'] = [normal.x, normal.y, normal.z]
        elif category == 'edges':
            row['length_mm'] = entity.length * 10
        else:
            point = entity.geometry
            row['point_mm'] = [point.x * 10, point.y * 10, point.z * 10]
        rows.append(row)
    next_offset = offset + len(rows)
    return {'body': body.entityToken, 'component': body.parentComponent.name,
            'coordinate_space': 'owning_component', 'kind': category, 'total': collection.count,
            'items': rows, 'next_offset': next_offset if next_offset < collection.count else None}
