"""Explicit native-body selection and Combine operations."""
import adsk.core
import adsk.fusion
from .features import _get_design


def entries():
    d = _get_design()
    return [(c,b) for c in d.allComponents for b in c.bRepBodies]


def list_bodies(args):
    return {'bodies':[{'name':b.name,'component':c.name,'token':b.entityToken} for c,b in entries()],
            'selection':'Use a token, or a unique body name. Combine requires bodies in the same component.'}


def combine_bodies(args):
    available = entries()
    def resolve(value):
        matches = [(c,b) for c,b in available if b.entityToken == value or b.name == value]
        if len(matches) != 1: raise ValueError('Body must resolve uniquely; use token from bodies list: '+value)
        return matches[0]
    component, target = resolve(args['target'])
    tools = [resolve(v) for v in args['tools']]
    tokens = [b.entityToken for _,b in tools]
    if not tools or len(set(tokens)) != len(tokens) or target.entityToken in tokens:
        raise ValueError('Choose distinct tool bodies, excluding the target.')
    if any(c != component for c,b in tools):
        raise ValueError('Combine currently requires native bodies in the same component.')
    collection = adsk.core.ObjectCollection.create()
    for _,body in tools: collection.add(body)
    inp = component.features.combineFeatures.createInput(target,collection)
    inp.operation = {'join':adsk.fusion.FeatureOperations.JoinFeatureOperation,
                     'cut':adsk.fusion.FeatureOperations.CutFeatureOperation,
                     'intersect':adsk.fusion.FeatureOperations.IntersectFeatureOperation}[args.get('operation','join')]
    inp.isKeepToolBodies = args.get('keep_tools',False)
    feature = component.features.combineFeatures.add(inp)
    if feature.healthState == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
        raise RuntimeError(feature.errorOrWarningMessage)
    return {'feature':feature.name,'operation':args.get('operation','join'),
            'component':component.name,'remaining_bodies':component.bRepBodies.count,
            'bodies':[{'name':b.name,'token':b.entityToken,'volume_cm3':b.volume} for b in component.bRepBodies]}
