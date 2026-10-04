"""Measurement, selection, screenshot, export, and feature-management tools."""

import base64
import os
import tempfile

import adsk.core
import adsk.fusion


def measure_body(args):
    """args: body (optional, default last). Returns real geometry numbers for self-verification."""
    body = _body_by_name_or_last(args.get("body"))
    bb = body.boundingBox
    return {
        "body": body.name,
        "volume_cm3": round(body.volume, 3),
        "bbox_min_mm": [_f(bb.minPoint.x), _f(bb.minPoint.y), _f(bb.minPoint.z)],
        "bbox_max_mm": [_f(bb.maxPoint.x), _f(bb.maxPoint.y), _f(bb.maxPoint.z)],
        "size_mm": [
            _f(bb.maxPoint.x - bb.minPoint.x),
            _f(bb.maxPoint.y - bb.minPoint.y),
            _f(bb.maxPoint.z - bb.minPoint.z),
        ],
        "face_count": body.faces.count,
        "edge_count": body.edges.count,
    }


def get_active_selection(args):
    app = adsk.core.Application.get()
    sel = app.userInterface.activeSelections
    out = []
    for i in range(sel.count):
        entity = sel.item(i).entity
        out.append({
            "index": i,
            "type": entity.objectType,
            "name": getattr(entity, "name", ""),
        })
    return {"selections": out}


def screenshot_viewport(args):
    app = adsk.core.Application.get()
    viewport = app.activeViewport
    if viewport is None:
        raise RuntimeError("No active viewport. Open a Fusion design first.")
    path = args.get("path")
    if not path:
        descriptor, path = tempfile.mkstemp(prefix="cadbot-viewport-", suffix=".png")
        os.close(descriptor)
    path = os.path.abspath(os.path.expanduser(path))
    try:
        if not viewport.saveAsImageFile(path, 800, 600):
            raise RuntimeError("Fusion could not save the viewport image.")
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            raise RuntimeError("Fusion returned an empty viewport image.")
        return {"path": path, "png_base64": base64.b64encode(data).decode("ascii")}
    finally:
        if not args.get("path"):
            os.unlink(path)


def export_design(args):
    """args: format (step|stl), path (optional; default Desktop/CadBotExport.<fmt>)"""
    app = adsk.core.Application.get()
    fmt = (args.get("format") or "step").lower()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design")
    ext = "step" if fmt == "step" else "stl"
    path = args.get("path") or os.path.expanduser(
        "~/Desktop/CadBotExport.{}".format(ext)
    )
    export_mgr = design.exportManager
    if fmt == "step":
        options = export_mgr.createSTEPExportOptions(path)
    else:
        options = export_mgr.createSTLExportOptions(design.rootComponent, path)
        options.sendToPrintUtility = False
    export_mgr.execute(options)
    return {"path": path, "format": fmt}


def list_features(args):
    root = _get_root()
    groups = [
        ("extrude", root.features.extrudeFeatures),
        ("revolve", root.features.revolveFeatures),
        ("fillet", root.features.filletFeatures),
        ("chamfer", root.features.chamferFeatures),
        ("circular_pattern", root.features.circularPatternFeatures),
        ("rectangular_pattern", root.features.rectangularPatternFeatures),
    ]
    out = []
    for kind, coll in groups:
        for i in range(coll.count):
            out.append("{}[{}]".format(kind, coll.item(i).name))
    return {"features": out}


def delete_features(args):
    """Delete named timeline entities, newest first; report partial failures."""
    names = args.get('names')
    if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
        raise ValueError('Provide a nonempty list of exact names from list_timeline.')
    timeline = _get_design().timeline
    targets = []
    for i in range(timeline.count - 1, -1, -1):
        entity = timeline.item(i).entity
        name = getattr(entity, 'name', '')
        if name in names:
            targets.append((name, entity))
    for name in set(names):
        matches = [e for n, e in targets if n == name]
        if len(matches) != 1:
            raise ValueError('Expected one timeline entity named {!r}; found {}. No deletion attempted.'.format(name, len(matches)))
    deleted, failures = [], []
    for name, entity in targets:
        try:
            if not entity.isValid:
                failures.append({'name': name, 'error': 'Entity was invalidated by an earlier deletion; inspect the timeline.'})
                break
            if not entity.deleteMe():
                raise RuntimeError('Fusion declined the deletion.')
            deleted.append(name)
        except Exception as exc:
            failures.append({'name': name, 'error': str(exc)})
            break
    result = {'deleted': deleted, 'failed': failures,
              'unprocessed': [name for name, _ in targets if name not in deleted and name not in [f['name'] for f in failures]]}
    if failures:
        result['error'] = 'Deletion did not fully complete. Inspect deleted/failed/unprocessed before retrying.'
    return result


def reset_design(args):
    """Wipe all root features/sketches/bodies to start fresh."""
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design")
    root = design.rootComponent
    # Delete dependent features before the features and bodies they consume.
    # Fusion rejects deleting an extrusion that is still referenced by a
    # Combine (and similarly for several finishing/derived feature families).
    collection_names = (
        "combineFeatures", "splitBodyFeatures", "threadFeatures",
        "shellFeatures", "draftFeatures", "holeFeatures",
        "filletFeatures", "chamferFeatures",
        "circularPatternFeatures", "rectangularPatternFeatures",
        "mirrorFeatures", "loftFeatures", "sweepFeatures",
        "revolveFeatures", "extrudeFeatures",
    )
    for name in collection_names:
        coll = getattr(root.features, name, None)
        if coll is None:
            continue
        while coll.count:
            coll.item(0).deleteMe()
    while root.sketches.count:
        root.sketches.item(0).deleteMe()
    while root.constructionPlanes.count:
        try:
            root.constructionPlanes.item(0).deleteMe()
        except (Exception,):
            break
    return {"reset": True}


def _f(cm_value):
    return round(cm_value * 10.0, 3)


def _get_root():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design")
    return design.rootComponent


def _get_design():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design")
    return design


def _design_bodies(root):
    """Include occurrence proxies so measurements use assembly coordinates."""
    bodies = [(body.name, body) for body in root.bRepBodies]
    for occurrence in root.allOccurrences:
        bodies.extend((occurrence.fullPathName + '/' + body.name, body)
                      for body in occurrence.bRepBodies)
    return bodies


def _body_by_name_or_last(name):
    bodies = _design_bodies(_get_root())
    if name:
        exact = [body for path, body in bodies if path == name]
        matches = exact or [body for path, body in bodies if body.name == name]
        if len(matches) > 1:
            raise ValueError("Body name is ambiguous. Use a component/body path from get_state.")
        if not matches:
            raise ValueError("Body not found: {}".format(name))
        return matches[0]
    if not bodies:
        raise RuntimeError("No BRep bodies available to measure. Create or open a solid/surface body first; sketches and mesh bodies cannot be measured by this tool.")
    return bodies[-1][1]
