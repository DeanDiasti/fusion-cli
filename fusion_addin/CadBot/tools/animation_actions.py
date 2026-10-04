"""Typed native rotation planning. Writes stay blocked until a backend is proven.

Planning never moves the playhead, changes selection, or assigns a scene transform.
There is intentionally no arbitrary command/Python escape hatch.
"""
import math

import adsk.core

from tools import animation, animation_entities


def rotation_request(args):
    axis = args['axis']
    if axis not in ('x', 'y', 'z'):
        raise ValueError('Rotation axis must be x, y, or z (assembly/world coordinates).')
    values = {}
    for key in ('degrees', 'start', 'end'):
        value = args[key]
        if isinstance(value, bool):
            raise ValueError(key + ' must be a finite number.')
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(key + ' must be a finite number.')
        values[key] = value
    if not 0 <= values['start'] < values['end'] <= 3600:
        raise ValueError('Require 0 <= start < end <= 3600 seconds.')
    if not 0 < abs(values['degrees']) <= 180:
        raise ValueError('Use a nonzero rotation of at most 180 degrees per action.')
    pivot = args['pivot_mm']
    if not isinstance(pivot, list) or len(pivot) != 3:
        raise ValueError('pivot-mm must be a JSON array of three world coordinates in mm.')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in pivot):
        raise ValueError('pivot-mm coordinates must be finite numbers.')
    return {**values, 'axis': axis, 'pivot_mm': [float(v) for v in pivot],
            'coordinate_space': 'assembly_world', 'angle_mode': 'relative'}


def rotate(args):
    request = rotation_request(args)
    app = adsk.core.Application.get()
    document = app.activeDocument
    if document is None or document.creationId != args['document_id']:
        raise ValueError('Active document changed. Inspect documents and use its current ID.')
    storyboard = animation.board(args)
    if not storyboard.isActive:
        raise ValueError('Activate the selected storyboard before planning a rotation.')
    if storyboard.isInPlayMode:
        raise ValueError('Stop playback before planning a rotation.')
    occurrence = animation_entities.resolve_occurrence(args['component'], document.creationId)
    plan = {
        'document': {'id': document.creationId, 'name': document.name},
        'storyboard': args['storyboard'],
        'component': {'selector': animation_entities.selector_for(occurrence),
                      'path': occurrence.fullPathName},
        'rotation': request,
        'existing_storyboard_end_seconds': float(storyboard.end),
        'required_verification': [
            'native transform action exists with the requested start/end times',
            'start, midpoint, and end poses match the requested pivot and rotation',
            'unselected assembly instances remain unchanged',
            'motion persists after saving and reopening the test fixture',
        ],
    }
    result = {'plan': plan, 'changes': [], 'artifacts': [], 'writes_available': False,
              'fusion_version': app.version,
              'next_step': 'Native rotation input and action timing need a live-verified backend. '
                           'Do not substitute direct occurrence transforms or retry the same write.'}
    if args.get('dry_run', False):
        return {**result, 'status': 'planned', 'animation_created': False}
    return {**result, 'status': 'blocked', 'animation_created': False,
            'error': {'code': 'native_animation_backend_unverified',
                      'message': 'Rotation planning is implemented; native action recording is not yet verified.'}}
