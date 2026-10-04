"""Read-only, bounded interference reporting in root assembly coordinates."""
import math
import adsk.core
from bridge.commands import validate_entities
from .design_structure import _design, _items


def resolve_entities(selectors):
    validate_entities(selectors)
    design = _design()
    root = design.rootComponent
    occurrences = _items(root.allOccurrences)
    resolved = []
    for selector in selectors:
        if selector.startswith('occurrence:'):
            matches = [o for o in occurrences if o.fullPathName == selector[len('occurrence:'):]]
        else:
            try:
                matches = [e for e in _items(design.findEntityByToken(selector)) if e is not None and e.isValid]
            except RuntimeError:
                matches = []
            if not matches:
                matches = [b for b in root.bRepBodies if b.name == selector]
        if len(matches) != 1:
            raise ValueError('Interference selector is missing or ambiguous: ' + selector)
        entity = matches[0]
        kind = entity.objectType.rsplit('::', 1)[-1]
        if kind == 'BRepBody':
            context = entity.assemblyContext
            if not entity.isSolid or (context is None and entity.parentComponent != root):
                raise ValueError('Use root solid bodies, assembly-context body tokens, or occurrence:<full path>. Native child bodies do not identify an assembly instance.')
            if context is not None and not any(context == o for o in occurrences):
                raise ValueError('Body context does not belong to the active root assembly.')
        elif kind == 'Occurrence':
            if not any(entity == o for o in occurrences):
                raise ValueError('Occurrence does not belong to the active root assembly.')
        else:
            raise ValueError('Interference requires solid bodies or occurrences.')
        resolved.append(entity)
    # Expand scopes only to reject duplicates and bound native analysis cost.
    # Send original occurrences to Fusion so result identities preserve instances.
    scopes = []
    for entity in resolved:
        if entity.objectType.rsplit('::', 1)[-1] == 'BRepBody':
            bodies = [entity]
        else:
            subtree = [o for o in occurrences if o == entity or o.fullPathName.startswith(entity.fullPathName + '+')]
            bodies = [b.createForAssemblyContext(o) for o in subtree for b in o.component.bRepBodies if b.isSolid]
        if not bodies or any(b is None for b in bodies):
            raise ValueError('Every selected occurrence must contain solid geometry in root context.')
        if any(b == old for b in bodies for old in scopes):
            raise ValueError('Interference inputs overlap or resolve to duplicate assembly geometry.')
        scopes.extend(bodies)
        if len(scopes) > 100:
            raise ValueError('Interference selection may contain at most 100 solid body instances.')
    return design, resolved


def identity(entity):
    context = getattr(entity, 'assemblyContext', None)
    return {'name': getattr(entity, 'name', ''), 'token': entity.entityToken,
            'type': entity.objectType.rsplit('::', 1)[-1],
            'assembly_path': getattr(entity, 'fullPathName', None) or (context.fullPathName if context else '@root')}


def analyze(design, entities):
    collection = adsk.core.ObjectCollection.create()
    for entity in entities:
        collection.add(entity)
    inp = design.createInterferenceInput(collection)
    if inp is None:
        raise RuntimeError('Fusion rejected interference input.')
    inp.areCoincidentFacesIncluded = False
    results = design.analyzeInterference(inp)
    if results is None:
        raise RuntimeError('Fusion did not return interference results.')
    rows = []
    for result in _items(results):
        body = result.interferenceBody
        if body is None:
            raise RuntimeError('Fusion did not return an interference volume.')
        volume = body.volume * 1000
        if not math.isfinite(volume) or volume < 0:
            raise RuntimeError('Fusion returned an invalid interference volume.')
        rows.append({'entity_one': identity(result.entityOne), 'entity_two': identity(result.entityTwo),
                     'volume_mm3': volume})
    return {'interferences': rows, 'interference_count': len(rows),
            'total_pair_volume_mm3': sum(r['volume_mm3'] for r in rows),
            'coincident_faces_included': False, 'coordinate_space': 'root_assembly',
            'note': 'Pair volumes can overlap; their sum is not a union volume. This reports the current pose only and creates no model bodies.'}


def check(args):
    design, entities = resolve_entities(args['entities'])
    return analyze(design, entities)
