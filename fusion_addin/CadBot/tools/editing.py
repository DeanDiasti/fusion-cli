"""Inspect and edit existing parametric dimensions and feature parameters."""
from .inspection import _get_design


def _describe(parameter):
    owner = getattr(parameter, 'createdBy', None)
    component = getattr(parameter, 'component', None)
    return {'name': parameter.name, 'expression': parameter.expression,
            'unit': parameter.unit, 'value_internal': parameter.value,
            'owner': getattr(owner, 'name', ''),
            'owner_type': getattr(owner, 'objectType', ''),
            'component': getattr(component, 'name', ''),
            'comment': parameter.comment}


def list_parameters(args):
    design = _get_design()
    query = (args.get('query') or '').lower()
    items = [_describe(p) for p in design.allParameters]
    if query:
        items = [p for p in items if query in ' '.join(str(v) for v in p.values()).lower()]
    return {'parameters': items, 'document': design.parentDocument.name,
            'note': 'Model parameter values use internal units (cm/radians); use expressions with explicit units when editing.'}


def list_timeline(args):
    design = _get_design()
    timeline = design.timeline
    items = []
    for i in range(timeline.count):
        item = timeline.item(i)
        entity = item.entity
        items.append({'index': i, 'name': getattr(entity, 'name', ''),
                      'type': getattr(entity, 'objectType', ''),
                      'health': str(getattr(entity, 'healthState', '')),
                      'message': getattr(entity, 'errorOrWarningMessage', '')})
    return {'marker': timeline.markerPosition, 'items': items}


def edit_parameters(args):
    """Compare-and-set existing expressions; roll back on failed recomputation."""
    design = _get_design()
    if args.get('document') != design.parentDocument.name:
        raise ValueError('Active document changed. Run list_parameters and use its document name.')
    changes = args.get('changes')
    if not isinstance(changes, list) or not changes:
        raise ValueError('Provide changes with name, expected_expression, and expression.')
    resolved = []
    seen = set()
    for change in changes:
        name = change['name']
        if name in seen:
            raise ValueError('Duplicate parameter: ' + name)
        seen.add(name)
        parameter = design.allParameters.itemByName(name)
        if parameter is None:
            raise ValueError('Parameter not found: ' + name)
        if parameter.expression != change.get('expected_expression'):
            raise ValueError('Parameter changed since inspection: ' + name + '. Inspect again.')
        expression = change.get('expression')
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError('Provide a nonempty expression with explicit units.')
        resolved.append((parameter, parameter.expression, expression))
    before = {(i['index'], i['message']) for i in list_timeline({})['items'] if i['message']}
    try:
        for parameter, old, new in resolved:
            parameter.expression = new
        if not design.computeAll():
            raise RuntimeError('Fusion could not recompute the design.')
        issues = [i for i in list_timeline({})['items'] if i['message'] and (i['index'], i['message']) not in before]
        if issues:
            raise RuntimeError('Edit introduced feature problems: ' + str(issues))
    except Exception as exc:
        try:
            for parameter, old, new in reversed(resolved):
                parameter.expression = old
            design.computeAll()
        except Exception as rollback:
            raise RuntimeError('Edit failed and restoration failed. Inspect the design before continuing. ' + str(rollback)) from exc
        raise RuntimeError('Edit failed; original expressions restored: ' + str(exc)) from exc
    return {'changes': [{'name': p.name, 'before': old, 'after': p.expression} for p, old, new in resolved],
            'document': design.parentDocument.name,
            'next': 'Measure affected bodies and verify connected components before reporting success.'}
