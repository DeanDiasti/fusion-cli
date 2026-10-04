"""Session-scoped occurrence discovery for native Animation commands.

Animation authoring must target occurrences, not shared component definitions.  The
opaque selectors in this module remain stable while this add-in process and the
owning document remain alive.  They intentionally become invalid after a reload,
document identity change, or occurrence deletion instead of silently selecting a
replacement with the same browser name.
"""

import uuid

import adsk.core
import adsk.fusion


_PREFIX = "animation-occurrence:"
_selectors = {}


def _items(collection):
    """Return a list for Fusion collections and ordinary host-test iterables."""
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(i) for i in range(collection.count)]
    return list(collection)


def _context():
    app = adsk.core.Application.get()
    document = getattr(app, "activeDocument", None)
    if document is None:
        raise ValueError("Open a Fusion document first.")

    design = None
    products = getattr(document, "products", None)
    if products is not None:
        design = adsk.fusion.Design.cast(
            products.itemByProductType("DesignProductType")
        )
    if design is None:
        design = adsk.fusion.Design.cast(getattr(app, "activeProduct", None))
    if design is None:
        raise RuntimeError("The active document is not a Fusion design.")
    return document, design


def _same_entity(left, right):
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:
        return False


def _current_occurrences(design):
    return _items(design.rootComponent.allOccurrences)


def _current_match(record, design):
    """Resolve a saved selector without falling back to a reused browser path."""
    saved = record["item"]
    if not getattr(saved, "isValid", False):
        return None

    current = _current_occurrences(design)
    token = record.get("entity_token")
    if token and hasattr(design, "findEntityByToken"):
        try:
            token_matches = _items(design.findEntityByToken(token))
        except Exception:
            token_matches = []
        matches = [
            occurrence
            for occurrence in current
            if any(_same_entity(occurrence, item) for item in token_matches)
        ]
    else:
        matches = [item for item in current if _same_entity(item, saved)]
    return matches[0] if len(matches) == 1 else None


def selector_for(occurrence, document_id=None):
    """Return an opaque selector stable for this occurrence in this add-in session."""
    document, design = _context()
    owner = str(document.creationId)
    if document_id is not None and str(document_id) != owner:
        raise ValueError("Active document changed. List Animation components again.")
    if not getattr(occurrence, "isValid", False):
        raise ValueError("Cannot create a selector for an invalid occurrence.")

    for key, record in list(_selectors.items()):
        if record["document"] != owner:
            continue
        current = _current_match(record, design)
        if current is None:
            del _selectors[key]
        elif _same_entity(current, occurrence):
            record["item"] = current
            return key

    key = _PREFIX + uuid.uuid4().hex
    _selectors[key] = {
        "document": owner,
        "item": occurrence,
        "entity_token": getattr(occurrence, "entityToken", None) or None,
    }
    return key


def resolve_occurrence(value, document_id=None):
    """Resolve an opaque selector or an unambiguous path/name in the active design."""
    document, design = _context()
    owner = str(document.creationId)
    if document_id is not None and str(document_id) != owner:
        raise ValueError("Active document changed. List Animation components again.")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Provide an occurrence selector from Animation components list.")
    value = value.strip()

    if value.startswith(_PREFIX):
        record = _selectors.get(value)
        if record is None or record["document"] != owner:
            raise ValueError(
                "Occurrence selector is stale or belongs to another Fusion session or document. "
                "List Animation components again."
            )
        occurrence = _current_match(record, design)
        if occurrence is None:
            _selectors.pop(value, None)
            raise ValueError(
                "Occurrence selector is stale because the occurrence changed or was deleted. "
                "List Animation components again."
            )
        record["item"] = occurrence
        return occurrence

    occurrences = _current_occurrences(design)
    exact_paths = [item for item in occurrences if item.fullPathName == value]
    if len(exact_paths) == 1:
        return exact_paths[0]
    if len(exact_paths) > 1:
        raise ValueError("Occurrence path is ambiguous. Use an opaque selector.")

    matches = [
        item
        for item in occurrences
        if item.name == value or item.component.name == value
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            "Occurrence name is ambiguous. Use the exact selector from Animation components list."
        )
    raise ValueError(
        "Occurrence was not found. List Animation components and use its exact selector."
    )


def occurrence_info(occurrence, document_id=None):
    matrix = occurrence.transform2
    translation = matrix.translation
    return {
        "selector": selector_for(occurrence, document_id),
        "path": occurrence.fullPathName,
        "name": occurrence.name,
        "component": occurrence.component.name,
        "visibility": {
            "light_bulb": bool(occurrence.isLightBulbOn),
            "effective": bool(occurrence.isVisible),
        },
        "transform": {
            "matrix": [float(value) for value in matrix.asArray()],
            "matrix_length_units": "cm",
            "translation_mm": {
                "x": float(translation.x) * 10.0,
                "y": float(translation.y) * 10.0,
                "z": float(translation.z) * 10.0,
            },
            "space": "assembly_context",
        },
    }


def list_occurrences(args):
    document, design = _context()
    owner = str(document.creationId)
    expected_document = args.get("document_id")
    if expected_document is not None and str(expected_document) != owner:
        raise ValueError("Active document changed. List Animation components again.")
    requested = args.get("query")
    include_hidden = not args.get("visible_only", False)
    occurrences = _current_occurrences(design)
    if requested:
        needle = requested.casefold()
        occurrences = [
            item
            for item in occurrences
            if needle in item.fullPathName.casefold()
            or needle in item.name.casefold()
            or needle in item.component.name.casefold()
        ]
    if not include_hidden:
        occurrences = [item for item in occurrences if item.isVisible]
    occurrences.sort(key=lambda item: item.fullPathName.casefold())
    return {
        "document": {"id": owner, "name": document.name},
        "occurrences": [occurrence_info(item, owner) for item in occurrences],
        "selector_scope": "current Fusion add-in session and owning document",
    }


# Command handlers can use component terminology while retaining occurrence-level
# targeting, which is required when a component definition has several instances.
list_components = list_occurrences


def inspect_component(args):
    document, _design = _context()
    owner = str(document.creationId)
    expected_document = args.get("document_id")
    if expected_document is not None and str(expected_document) != owner:
        raise ValueError("Active document changed. List Animation components again.")
    occurrence = resolve_occurrence(args["component"], owner)
    return {
        "document": {"id": owner, "name": document.name},
        "occurrence": occurrence_info(occurrence, owner),
    }
