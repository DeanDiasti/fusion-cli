"""Design-state introspection tool (runs on Fusion's main thread)."""

import adsk.core
import adsk.fusion  # noqa: F401


def get_state(args=None):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        return {"error": "No active Fusion design. Open a design first."}
    root = design.rootComponent
    bodies = []
    from .inspection import _design_bodies
    for body_path, body in _design_bodies(root):
        bb = body.boundingBox
        bodies.append({
            "name": body.name,
            "path": body_path,
            "volume_cm3": round(body.volume, 3),
            "bbox_min": [_f(bb.minPoint.x), _f(bb.minPoint.y), _f(bb.minPoint.z)],
            "bbox_max": [_f(bb.maxPoint.x), _f(bb.maxPoint.y), _f(bb.maxPoint.z)],
        })
    params = []
    for param in design.userParameters:
        params.append({
            "name": param.name,
            "value": param.expression,
            "unit": param.unit,
        })
    features = []
    for feat in root.features.extrudeFeatures:
        features.append("extrude:" + feat.name)
    return {
        "units": design.fusionUnitsManager.distanceDisplayUnits,
        "body_count": len(bodies),
        "bodies": bodies,
        "user_parameters": params,
        "features": features,
    }


def _f(cm_value):
    # adsk returns cm internally; report mm (the Fusion UI default).
    return round(cm_value * 10.0, 3)
