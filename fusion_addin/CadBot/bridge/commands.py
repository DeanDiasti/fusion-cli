"""Finite command grammar; no shell evaluation, Python execution or API reflection."""
import argparse
import json
import math
import shlex


def number(value):
    result = float(value)
    if not math.isfinite(result): raise ValueError('Use a finite number.')
    return result


def json_list(value):
    result = strict_json(value)
    if not isinstance(result, list) or not result: raise ValueError('Use a nonempty JSON array.')
    return result


def boolean(value):
    normalized = str(value).strip().lower()
    if normalized in ('true', 'yes', '1', 'on'):
        return True
    if normalized in ('false', 'no', '0', 'off'):
        return False
    raise ValueError('Use true or false.')


def json_value(value):
    result = strict_json(value)
    if isinstance(result, (dict, list)):
        raise ValueError('Use a JSON scalar value.')
    return result


def json_object(value):
    result = strict_json(value)
    if not isinstance(result, dict):
        raise ValueError('Use a JSON object.')
    return result


def strict_json(value):
    def reject_constant(value):
        raise ValueError('JSON numbers must be finite: ' + value)
    return json.loads(value, parse_float=number, parse_constant=reject_constant)


EASING = ('linear', 'ease-in', 'ease-out', 'ease-in-out', 'step')


def checkpoint_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value != value.strip() or not value.isprintable():
        raise ValueError('Use a printable checkpoint ID of 1–128 characters, without surrounding whitespace.')
    return value


def validate_tracks(tracks):
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 24:
        raise ValueError('Provide 1–24 tracks.')
    for track in tracks:
        if (not isinstance(track, dict) or not {'joint', 'axis', 'keys'} <= set(track)
                or set(track) - {'joint', 'axis', 'keys', 'easing'}):
            raise ValueError('Each track needs joint, axis, keys, and optional easing.')
        if not isinstance(track['joint'], str) or not track['joint'].strip():
            raise ValueError('Track joint must be a nonempty selector.')
        if track['axis'] not in ('rotation', 'slide') or track.get('easing', 'linear') not in EASING:
            raise ValueError('Use rotation/slide and a supported easing: ' + ', '.join(EASING))
        keys = track['keys']
        if not isinstance(keys, list) or not 2 <= len(keys) <= 32:
            raise ValueError('Use 2–32 [time,value] keyframes per track.')
        previous = -1
        for key in keys:
            if not isinstance(key, list) or len(key) != 2:
                raise ValueError('Keyframes are [normalized_time,value].')
            t, value = key
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in key):
                raise ValueError('Keyframe times and values must be finite numbers.')
            if not 0 <= t <= 1 or t <= previous:
                raise ValueError('Key times must increase from 0 to 1.')
            previous = t
        if keys[0][0] != 0 or keys[-1][0] != 1:
            raise ValueError('Keyframes must include times 0 and 1.')


def sample_times(tracks, count):
    if type(count) is not int or not 2 <= count <= 61:
        raise ValueError('Use samples between 2 and 61.')
    times = {i / (count - 1) for i in range(count)}
    times.update(key[0] for track in tracks for key in track['keys'])
    if len(times) > 120:
        raise ValueError('Uniform samples plus keyframe times must total at most 120 poses.')
    return sorted(times)


def validate_entities(entities):
    if (not isinstance(entities, list) or not 2 <= len(entities) <= 32
            or any(not isinstance(s, str) or not s.strip() for s in entities)
            or len(set(entities)) != len(entities)):
        raise ValueError('Provide 2–32 distinct body tokens/names or occurrence:<full path> selectors.')


# command: (handler, mutates design, required options, optional options)
# Option names are converted from underscores to hyphens in the CLI.
SPECS = {
 'checkpoint begin': ('checkpoint_begin',False,{'id':checkpoint_id},{'document_id':str}),
 'checkpoint finish': ('checkpoint_finish',False,{},{}),
 'checkpoint status': ('checkpoint_status',False,{},{}),
 'checkpoint restore': ('checkpoint_restore',False,{'id':checkpoint_id},{'document_id':str}),
 'assembly instances': ('assembly_instances',False,{},{}),
 'joints list': ('list_joints',False,{},{}),
 'joints drive': ('drive_joint',True,{'joint':str,'axis':('rotation','slide'),'value':number},{}),
 'animation open': ('open_animation',False,{'path':str},{}),
 'animation check': ('check_animation',True,{'tracks':json_list},{'samples':int}),
 'animation render': ('render_animation',True,{'tracks':json_list},{'fps':int,'seconds':number,'playback':('once','loop','ping-pong')}),
 'design inspect': ('get_state',False,{},{}),
 'design diagnostics': ('design_diagnostics',False,{},{}),
 'bodies list': ('list_bodies',False,{},{}),
 'bodies measure': ('measure_body',False,{}, {'body':str}),
 'bodies inspect': ('body_inspect',False,{'body':str},{}),
 'bodies rename': ('body_rename',True,{'body':str,'name':str},{}),
 'bodies delete': ('body_delete',True,{'body':str},{}),
 'bodies combine': ('combine_bodies',True,{'target':str,'tools':json_list},{'operation':('join','cut','intersect'),'keep_tools':bool}),
 'selection list': ('get_active_selection',False,{},{}),
 'timeline list': ('list_timeline',False,{},{}),
 'parameters list': ('list_parameters',False,{}, {'query':str}),
 'parameters set': ('edit_parameters',True,{'document':str,'changes':json_list},{}),
 'parameters create': ('parameter_create',True,{'name':str,'expression':str},{'unit':str,'comment':str}),
 'parameters delete': ('parameter_delete',True,{'name':str},{}),
 'sketches create': ('create_sketch',True,{}, {'plane':('XY','XZ','YZ'),'offset_mm':number,'name':str,'support':str,'component':str}),
 'sketches circle': ('add_circle',True,{'sketch':str,'center_x':number,'center_y':number,'radius':number},{}),
 'sketches rectangle': ('add_rectangle',True,{'sketch':str,'x1':number,'y1':number,'x2':number,'y2':number},{}),
 'sketches line': ('add_line',True,{'sketch':str,'x1':number,'y1':number,'x2':number,'y2':number},{}),
 'sketches dimension': ('add_dimension',True,{'sketch':str,'target':('circle_diameter','line_length'),'value_mm':number},{'curve_index':int}),
 'features list': ('list_features',False,{},{}),
 'features inspect': ('feature_inspect',False,{'feature':str},{}),
 'features rename': ('feature_rename',True,{'feature':str,'name':str},{}),
 'features suppress': ('feature_suppress',True,{'feature':str},{}),
 'features unsuppress': ('feature_unsuppress',True,{'feature':str},{}),
 'features delete-one': ('feature_delete',True,{'feature':str},{}),
 'features extrude': ('extrude',True,{'sketch':str},{'distance_mm':number,'extent':('distance','through-all'),'direction':('positive','negative','both'),'participants':json_list,'operation':('join','cut','new','intersect'),'taper_angle_deg':number,'symmetric':bool,'profile_index':int}),
 'features revolve': ('revolve',True,{'sketch':str},{'axis':('X','Y'),'angle_deg':number,'profile_index':int}),
 'features fillet': ('fillet',True,{'radius_mm':number},{'body':str,'edge_indices':json_list}),
 'features chamfer': ('chamfer',True,{'distance_mm':number},{'body':str,'edge_indices':json_list}),
 'features circular-pattern': ('circular_pattern',True,{'count':int},{'body':str,'axis':('X','Y','Z'),'angle_deg':number}),
 'features rectangular-pattern': ('rectangular_pattern',True,{'direction_x_count':int,'direction_y_count':int,'spacing_x_mm':number,'spacing_y_mm':number},{'body':str}),
 'features delete': ('delete_features',True,{'names':json_list},{}),
 'design reset': ('reset_design',True,{},{}),
 'design export': ('export_design',False,{'format':('step','stl')},{'path':str}),
 'viewport screenshot': ('screenshot_viewport',False,{}, {'path':str}),
}


# Canonical workspace-scoped grammar. Compatibility aliases are resolved before
# parsing; they never add duplicate canonical commands.
ALIASES = {}
for _old in list(SPECS):
    if _old.startswith(('design ', 'checkpoint ')):
        continue
    _new = ('design motion ' + _old.split(' ', 1)[1]
            if _old.startswith('animation ') else 'design ' + _old)
    ALIASES[_old] = _new
    SPECS[_new] = SPECS.pop(_old)

SPECS.update({
 'design interference check': ('interference_check',False,{'entities':json_list},{}),
 'design motion joints list': ('list_joints',False,{},{}),
 'design motion inspect': ('inspect_motion',True,{'tracks':json_list,'entities':json_list},{'samples':int}),
 'design sketches offset': ('sketch_offset',True,{'sketch':str,'entities':json_list,'distance_mm':number},{}),
 'design sketches trim': ('sketch_trim',True,{'sketch':str,'entity':str,'x_mm':number,'y_mm':number},{}),
 'app jobs list': ('jobs_list',False,{},{}),
 'app jobs inspect': ('jobs_inspect',False,{'job':str},{}),
 'app jobs cancel': ('jobs_cancel',False,{'job':str},{}),
 'app jobs forget': ('jobs_forget',False,{'job':str},{}),
 'design sketches list': ('list_sketches',False,{},{}),
 'design sketches inspect': ('inspect_sketch',False,{'sketch':str},{}),
 'design sketches rename': ('rename_sketch',True,{'sketch':str,'name':str},{}),
 'design sketches delete': ('delete_sketch',True,{'sketch':str},{}),
 'app inspect': ('app_inspect',False,{},{}),
 'app capabilities': ('app_capabilities',False,{},{}),
 'app state': ('app_state',False,{},{}),
 'app diagnostics': ('app_diagnostics',False,{},{}),
 'app preferences': ('app_preferences',False,{},{}),
 'workspace list': ('workspace_list',False,{},{}),
 'workspace activate': ('workspace_activate',False,{'workspace':str},{}),
 'documents list': ('documents_list',False,{},{}),
 'documents inspect': ('documents_inspect',False,{'document':str},{}),
 'documents create': ('documents_create',False,{}, {'name':str}),
 'documents activate': ('documents_activate',False,{'document':str},{}),
 'documents close': ('documents_close',False,{'document':str},{'discard_changes':bool}),
 'documents save': ('documents_save',False,{'document':str},{'description':str}),
 'documents save-as': ('documents_save_as',False,{'document':str,'folder':str,'name':str},{'description':str}),
 'documents open': ('documents_open',False,{'file':str},{}),
 'documents import': ('documents_import',False,{'path':str},{'format':('f3d','fusion_archive','step','stp','iges','sat','smt')}),
 'documents export': ('documents_export',False,{'document':str,'format':('f3d','fusion_archive','step','iges','sat','smt','stl'),'path':str},{}),
 'projects list': ('projects_list',False,{},{}),
 'projects inspect': ('projects_inspect',False,{'project':str},{}),
 'projects create': ('projects_create',False,{'name':str},{}),
 'projects rename': ('projects_rename',False,{'project':str,'name':str},{}),
 'projects delete': ('projects_delete',False,{'project':str},{}),
 'folders list': ('folders_list',False,{'project':str},{'folder':str}),
 'folders inspect': ('folders_inspect',False,{'folder':str},{}),
 'folders search': ('folders_search',False,{'project':str,'query':str},{'limit':int}),
 'folders create': ('folders_create',False,{'folder':str,'name':str},{}),
 'folders rename': ('folders_rename',False,{'folder':str,'name':str},{}),
 'folders delete': ('folders_delete',False,{'folder':str},{'recursive':bool}),
 'files list': ('files_list',False,{'folder':str},{}),
 'files search': ('files_search',False,{'project':str,'query':str},{'limit':int}),
 'files inspect': ('files_inspect',False,{'file':str},{}),
 'files rename': ('files_rename',False,{'file':str,'name':str},{}),
 'files copy': ('files_copy',False,{'file':str,'folder':str},{'include_references':bool}),
 'files move': ('files_move',False,{'file':str,'folder':str},{}),
 'files delete': ('files_delete',False,{'file':str},{'allow_referenced':bool}),
 'files upload': ('files_upload',False,{'folder':str,'path':str},{}),
 'files download': ('files_download',False,{'file':str,'path':str},{}),
 'animation storyboards list': ('storyboards_list',False,{},{}),
 'animation storyboards create': ('storyboards_create',False,{}, {'from_previous':bool}),
 'animation storyboards activate': ('storyboards_activate',False,{'storyboard':str},{}),
 'animation storyboards copy': ('storyboards_copy',False,{'storyboard':str},
     {'name':str,'target_storyboard':str,'before':boolean}),
 'animation storyboards move': ('storyboards_move',False,
     {'storyboard':str,'target_storyboard':str},{'before':boolean}),
 'animation storyboards reverse': ('storyboards_reverse',False,{'storyboard':str},{}),
 'animation storyboards delete': ('storyboards_delete',False,{'storyboard':str},{}),
 'animation playback seek': ('storyboards_seek',False,{'storyboard':str,'seconds':number},{}),
 'animation playback play': ('storyboards_play',False,{'storyboard':str},
     {'from_current':boolean,'begin_seconds':number,'end_seconds':number}),
 'animation playback status': ('animation_playback_status',False,{'storyboard':str},{}),
 'animation playback full-screen': ('animation_playback_full_screen',False,
     {'storyboard':str,'enabled':boolean},{}),
 'animation components list': ('animation_components_list',False,{}, {'query':str,'visible_only':bool}),
 'animation components inspect': ('animation_component_inspect',False,{'component':str},{}),
 'animation camera inspect': ('camera_inspect',False,{'storyboard':str},{}),
 'animation camera recording': ('animation_camera_recording',False,
     {'storyboard':str,'enabled':boolean},{}),
 'animation settings inspect': ('animation_settings_inspect',False,{},{}),
 'animation settings recording-mode': ('animation_settings_recording_mode',False,
     {'mode':('time-zero','overlap-half-second','sequential')},{}),
 'animation settings watermark': ('animation_settings_watermark',False,
     {'enabled':boolean},{}),
 'animation authoring capabilities': ('animation_authoring_capabilities',False,{},{}),
 'animation actions rotate': ('animation_actions_rotate',False,
     {'document_id':str,'storyboard':str,'component':str,'axis':('x','y','z'),
      'degrees':number,'pivot_mm':json_list,'start':number,'end':number}, {'dry_run':bool}),
 'design sketches geometry list': ('geometry_list',False,{'sketch':str},{}),
 'design sketches arcs add': ('arcs_add',True,{'sketch':str,'points_mm':json_list},{}),
 'design sketches splines add': ('splines_add',True,{'sketch':str,'points_mm':json_list},{'closed':boolean}),
 'design sketches points add': ('points_add',True,{'sketch':str,'x_mm':number,'y_mm':number},{}),
 'design bodies topology list': ('body_topology',False,{'body':str},{'kind':('faces','edges','vertices'),'offset':int,'limit':int}),
 'design sketches project': ('project_geometry',True,{'sketch':str,'entities':json_list},{'linked':boolean}),
 'design sketches profiles list': ('profiles_list',False,{'sketch':str},{}),
 'design sketches lines add': ('lines_add',True,{
     'sketch':str,'x1_mm':number,'y1_mm':number,'x2_mm':number,'y2_mm':number},{}),
 'design sketches lines edit': ('lines_edit',True,{
     'sketch':str,'entity':str,'x1_mm':number,'y1_mm':number,'x2_mm':number,'y2_mm':number},{}),
 'design sketches circles add': ('circles_add',True,{
     'sketch':str,'center_x_mm':number,'center_y_mm':number,'radius_mm':number},{}),
 'design sketches circles edit': ('circles_edit',True,{
     'sketch':str,'entity':str,'center_x_mm':number,'center_y_mm':number,'radius_mm':number},{}),
 'design sketches rectangles add': ('rectangles_add',True,{
     'sketch':str,'x1_mm':number,'y1_mm':number,'x2_mm':number,'y2_mm':number},{}),
 'design sketches geometry construction': ('geometry_set_construction',True,
     {'sketch':str,'entity':str,'construction':boolean},{}),
 'design sketches geometry fixed': ('geometry_set_fixed',True,
     {'sketch':str,'entity':str,'fixed':boolean},{}),
 'design sketches geometry delete': ('geometry_delete',True,{'sketch':str,'entity':str},{}),
 'design sketches constraints list': ('constraints_list',False,{'sketch':str},{}),
 'design sketches constraints add': ('constraints_add',True,{
     'sketch':str,
     'type':('horizontal','vertical','parallel','perpendicular','collinear','tangent',
             'equal','concentric','smooth','coincident','midpoint','horizontal-points',
             'vertical-points','symmetry'),
     'entity':str},
     {'second_entity':str,'symmetry_line':str,
      'point':('start','end','center'),'second_point':('start','end','center')}),
 'design sketches constraints delete': ('constraints_delete',True,
     {'sketch':str,'constraint':str},{}),
 'design sketches dimensions list': ('dimensions_list',False,{'sketch':str},{}),
 'design sketches dimensions set': ('dimensions_set',True,
     {'sketch':str,'dimension':str,'expression':str},{'expected_expression':str}),
 'design sketches dimensions delete': ('dimensions_delete',True,
     {'sketch':str,'dimension':str},{}),
 'design components list': ('components_list',False,{},{}),
 'design components inspect': ('components_inspect',False,{'component':str},{}),
 'design components create': ('components_create',True,{'name':str},{}),
 'design components rename': ('components_rename',True,{'component':str,'name':str},{}),
 'design components delete': ('components_delete',True,{'component':str},{'all_instances':bool}),
 'design occurrences list': ('occurrences_list',False,{}, {'query':str}),
 'design occurrences inspect': ('occurrences_inspect',False,{'occurrence':str},{}),
 'design occurrences create': ('occurrences_create',True,{'component':str},{}),
 'design occurrences delete': ('occurrences_delete',True,{'occurrence':str},{}),
 'design occurrences ground': ('occurrences_ground',True,{'occurrence':str},{'to_parent':bool}),
 'design occurrences unground': ('occurrences_unground',True,{'occurrence':str},{'to_parent':bool}),
 'design occurrences transform': ('occurrences_transform',True,
     {'occurrence':str,'matrix':json_list},{}),
 'design joints list': ('assembly_joints_list',False,{},{}),
 'design joints inspect': ('assembly_joints_inspect',False,{'joint':str},{}),
 'design joints geometry list': ('assembly_joint_geometry_list',False,
     {'occurrence':str},{}),
 'design joints create': ('assembly_joints_create',True,
     {'occurrence_one':str,'occurrence_two':str,'type':('rigid','revolute','slider')},
     {'geometry_one':str,'geometry_two':str,
      'keypoint_one':('start','middle','end','center'),
      'keypoint_two':('start','middle','end','center'),
      'axis':('x','y','z'),'flipped':bool,'angle_deg':number,'offset_mm':number,'name':str}),
 'design joints edit': ('assembly_joints_edit',True,{'joint':str},
     {'name':str,'type':('rigid','revolute','slider'),'axis':('x','y','z')}),
 'design joints lock': ('assembly_joints_lock',True,{'joint':str},{}),
 'design joints unlock': ('assembly_joints_unlock',True,{'joint':str},{}),
 'design joints suppress': ('assembly_joints_suppress',True,{'joint':str},{}),
 'design joints unsuppress': ('assembly_joints_unsuppress',True,{'joint':str},{}),
 'design joints flip': ('assembly_joints_flip',True,{'joint':str},{}),
 'design joints unflip': ('assembly_joints_unflip',True,{'joint':str},{}),
 'design joints delete': ('assembly_joints_delete',True,{'joint':str},{}),
 'design joints limits set': ('assembly_joints_limits_set',True,
     {'joint':str,'axis':('rotation','slide')},
     {'minimum':number,'maximum':number,'rest':number}),
 'design joints limits clear': ('assembly_joints_limits_clear',True,
     {'joint':str,'axis':('rotation','slide')},
     {'minimum':bool,'maximum':bool,'rest':bool}),
 'design capabilities': ('extended_design_capabilities',False,{},{}),
 'design surfaces list': ('surfaces_list',False,{},{}),
 'design surfaces inspect': ('surfaces_inspect',False,{'surface':str},{}),
 'design surfaces patch': ('surfaces_patch',True,{'sketch':str},{'profile_index':int}),
 'design surfaces stitch': ('surfaces_stitch',True,{'surfaces':json_list},
     {'tolerance_mm':number,'operation':('new','join')}),
 'design surfaces thicken': ('surfaces_thicken',True,
     {'surface':str,'thickness_mm':number},
     {'symmetric':boolean,'chain':boolean,'operation':('new','join')}),
 'design surfaces delete': ('surfaces_delete',True,{'surface':str},{}),
 'design meshes list': ('meshes_list',False,{},{}),
 'design meshes inspect': ('meshes_inspect',False,{'mesh':str},{}),
 'design meshes create-triangles': ('meshes_create_triangles',True,
     {'coordinates_mm':json_list,'indices':json_list},{'name':str}),
 'design meshes edit': ('meshes_edit',True,{'mesh':str},
     {'name':str,'visible':boolean,'opacity':number}),
 'design meshes delete': ('meshes_delete',True,{'mesh':str},{}),
 'design forms list': ('forms_list',False,{},{}),
 'design forms inspect': ('forms_inspect',False,{'form':str},{}),
 'design forms create-from-tsm': ('forms_create_tsm',True,{'tsm_description':str},{'name':str}),
 'design forms rename': ('forms_rename',True,{'form':str,'name':str},{}),
 'design forms delete': ('forms_delete',True,{'form':str},{}),
 'design sheet-metal rules list': ('sheet_metal_rules_list',False,{},{}),
 'design sheet-metal rules inspect': ('sheet_metal_rules_inspect',False,{'rule':str},{}),
 'design sheet-metal rules copy': ('sheet_metal_rules_copy',True,{'source':str,'name':str},{}),
 'design sheet-metal rules edit': ('sheet_metal_rules_edit',True,{'rule':str},
     {'name':str,'k_factor':number,'thickness':str,'bend_radius':str,'gap':str}),
 'design sheet-metal rules delete': ('sheet_metal_rules_delete',True,{'rule':str},{}),
 'design materials libraries': ('material_libraries',False,{},{}),
 'design materials list': ('materials_list',False,{}, {'library':str}),
 'design materials inspect': ('materials_inspect',False,
     {'type':('material','appearance'),'asset':str},{'library':str}),
 'design materials copy': ('materials_copy',True,
     {'type':('material','appearance'),'library':str,'source':str,'name':str},{}),
 'design materials edit': ('materials_edit',True,
     {'type':('material','appearance'),'asset':str},{'name':str,'description':str}),
 'design materials delete': ('materials_delete',True,
     {'type':('material','appearance'),'asset':str},{}),
 'design materials apply': ('materials_apply',True,{'target':str,'library':str},
     {'material':str,'appearance':str}),
 'design materials clear-appearance': ('materials_clear_appearance',True,{'target':str},{}),
 'design configurations list': ('configurations_list',False,{},{}),
 'design configurations inspect': ('configurations_inspect',False,{'configuration':str},{}),
 'design configurations initialize': ('configurations_initialize',True,{},{}),
 'design configurations create': ('configurations_create',True,{'name':str},{}),
 'design configurations copy': ('configurations_copy',True,{'configuration':str,'name':str},{}),
 'design configurations edit': ('configurations_edit',True,{'configuration':str},
     {'column_id':str,'column_index':int,'expression':str,'value':json_value,
      'visible':boolean,'suppressed':boolean}),
 'design configurations rename': ('configurations_rename',True,{'configuration':str,'name':str},{}),
 'design configurations activate': ('configurations_activate',True,{'configuration':str},{}),
 'design configurations delete': ('configurations_delete',True,{'configuration':str},{}),
 'design construction list': ('construction_list',False,{}, {'kind':('plane','axis','point')}),
 'design construction inspect': ('construction_inspect',False,{'construction':str},
     {'kind':('plane','axis','point')}),
 'design construction planes create-offset': ('plane_create_offset',True,
     {'reference':str,'offset':str},{'component':str,'name':str}),
 'design construction planes create-midplane': ('plane_create_midplane',True,
     {'first':str,'second':str},{'component':str,'name':str}),
 'design construction planes create-three-points': ('plane_create_three_points',True,
     {'first':str,'second':str,'third':str},{'component':str,'name':str}),
 'design construction planes create-angle': ('plane_create_angle',True,
     {'axis':str,'reference':str,'angle':str},{'component':str,'name':str}),
 'design construction axes create-two-points': ('axis_create_two_points',True,
     {'first':str,'second':str},{'component':str,'name':str}),
 'design construction axes create-two-planes': ('axis_create_two_planes',True,
     {'first':str,'second':str},{'component':str,'name':str}),
 'design construction axes create-edge': ('axis_create_edge',True,{'edge':str},
     {'component':str,'name':str}),
 'design construction points create-on-entity': ('point_create_on_entity',True,{'point':str},
     {'component':str,'name':str}),
 'design construction points create-center': ('point_create_center',True,
     {'circular_entity':str},{'component':str,'name':str}),
 'design construction rename': ('construction_rename',True,
     {'construction':str,'name':str},{'kind':('plane','axis','point')}),
 'design construction show': ('construction_show',True,{'construction':str},
     {'kind':('plane','axis','point')}),
 'design construction hide': ('construction_hide',True,{'construction':str},
     {'kind':('plane','axis','point')}),
 'design construction set-parameter': ('construction_set_parameter',True,
     {'construction':str,'parameter':('offset','angle','distance'),'expression':str},
     {'kind':('plane','axis','point')}),
 'design construction delete': ('construction_delete',True,{'construction':str},
     {'kind':('plane','axis','point')}),
 'design timeline inspect': ('timeline_inspect',False,{'index':int},{}),
 'design timeline roll': ('timeline_roll',False,{'position':int},{}),
 'design timeline beginning': ('timeline_move_beginning',False,{},{}),
 'design timeline end': ('timeline_move_end',False,{},{}),
 'design timeline groups list': ('timeline_groups_list',False,{},{}),
 'design timeline groups inspect': ('timeline_group_inspect',False,{'group':int},{}),
 'design timeline groups create': ('timeline_group_create',True,{'start':int,'end':int},{'name':str}),
 'design timeline groups rename': ('timeline_group_rename',True,{'group':int,'name':str},{}),
 # Fusion increments component revisions when timeline-group display state
 # changes. Track these UI operations so checkpoint signatures stay in sync.
 'design timeline groups collapse': ('timeline_group_collapse',True,{'group':int},{}),
 'design timeline groups expand': ('timeline_group_expand',True,{'group':int},{}),
 'design timeline groups delete-keep': ('timeline_group_delete_keep',True,{'group':int},{}),
 'design timeline groups delete-contents': ('timeline_group_delete_contents',True,{'group':int},{}),
 'design selection clear': ('selection_clear',False,{},{}),
 'design selection add': ('selection_add',False,{'entity':str},{}),
 'design selection remove': ('selection_remove',False,{'entity':str},{}),
 'design solid-features capabilities': ('solid_features_capabilities',False,{},{}),
 'design solid-features list': ('solid_features_list',False,{},
     {'family':('hole','shell','draft','mirror','loft','sweep')}),
 'design solid-features inspect': ('solid_feature_inspect',False,{'feature':str},
     {'family':('hole','shell','draft','mirror','loft','sweep')}),
 'design solid-features edit': ('solid_feature_edit',True,{'feature':str},
     {'family':('hole','shell','draft','mirror','loft','sweep'),'name':str,
      'expressions':json_object}),
 'design solid-features delete': ('solid_feature_delete',True,{'feature':str},
     {'family':('hole','shell','draft','mirror','loft','sweep')}),
 'design holes create': ('holes_create',True,
     {'sketch':str,'point_index':int,'diameter_mm':number},
     {'kind':('simple','counterbore','countersink'),
      'counterbore_diameter_mm':number,'counterbore_depth_mm':number,
      'countersink_diameter_mm':number,'countersink_angle_deg':number,
      'depth_mm':number,'reverse':boolean,'name':str}),
 'design shells create': ('shells_create',True,{'body':str},
     {'remove_face_indices':json_list,'inside_mm':number,'outside_mm':number,
      'tangent_chain':boolean}),
 'design drafts create': ('drafts_create',True,
     {'body':str,'face_indices':json_list,'angle_deg':number},
     {'plane':('XY','XZ','YZ'),'tangent_chain':boolean,'reverse':boolean}),
 'design mirrors create': ('mirrors_create',True,
     {'entity_type':('body','feature'),'entities':json_list},
     {'component':str,'plane':('XY','XZ','YZ'),'combine':boolean}),
 'design lofts create': ('lofts_create',True,{'sketches':json_list},
     {'profile_indices':json_list,'operation':('new','join','cut','intersect'),
      'solid':boolean,'closed':boolean,'rails':json_list,'centerline':json_object}),
 'design sweeps create': ('sweeps_create',True,
     {'profile_sketch':str},
     {'profile_index':int,'operation':('new','join','cut','intersect'),
      'path_sketch':str,'path_curve_index':int,'path_entity':str,
      'chain':boolean,'solid':boolean,'taper_angle_deg':number,'twist_angle_deg':number,
      'guide_rail':json_object,'guide_surfaces':json_list,'guide_chain':boolean,
      'profile_scaling':('scale','stretch','none'),'direction_flipped':boolean}),
 'design sheet-metal capabilities': ('sheet_metal_capabilities',False,{}, {'component':str}),
 'design sheet-metal inspect': ('sheet_metal_inspect',False,{}, {'component':str}),
 'design sheet-metal faces list': ('sheet_metal_faces_list',False,
     {'component':str,'body':str},{}),
 'design sheet-metal rules list-all': ('sheet_metal_rules_list_all',False,{},{}),
 'design sheet-metal rules assign': ('sheet_metal_rule_assign',True,
     {'component':str,'rule':str},{}),
 'design sheet-metal components create': ('sheet_metal_component_create',True,{'name':str},
     {'rule':str}),
 'design sheet-metal convert': ('sheet_metal_convert',True,
     {'component':str,'body':str,'base_face':str,'rule':str},{}),
 'design sheet-metal features list': ('sheet_metal_features_list',False,{}, {'component':str}),
 'design sheet-metal features inspect': ('sheet_metal_feature_inspect',False,
     {'component':str,'feature':str},{}),
 'design sheet-metal features delete': ('sheet_metal_feature_delete',True,
     {'component':str,'feature':str},{}),
 'design sheet-metal folds create': ('sheet_metal_fold_create',True,
     {'component':str,'stationary_face':str,'sketch':str,'line':str,'angle':str},
     {'line_position':('start','center','end'),'bend_relief':boolean,'corner_relief':boolean}),
 'design sheet-metal folds edit-angle': ('sheet_metal_fold_edit_angle',True,
     {'component':str,'fold':str,'bend_index':int,'expected_angle':str,'angle':str},{}),
 'design sheet-metal unfolds create': ('sheet_metal_unfold_create',True,
     {'component':str,'stationary_face':str},{'all_bends':boolean,'bend_faces':json_list}),
 'design sheet-metal unfolds edit': ('sheet_metal_unfold_edit',True,
     {'component':str,'unfold':str},{'all_bends':boolean,'bend_faces':json_list}),
 'design sheet-metal refolds create': ('sheet_metal_refold_create',True,
     {'component':str,'unfold':str},{}),
 'design sheet-metal flat-pattern create': ('sheet_metal_flat_pattern_create',True,
     {'component':str,'stationary_face':str},{}),
 'design sheet-metal flat-pattern inspect': ('sheet_metal_flat_pattern_inspect',False,
     {'component':str},{}),
 'design sheet-metal flat-pattern rename': ('sheet_metal_flat_pattern_rename',True,
     {'component':str,'name':str},{}),
 'design sheet-metal flat-pattern delete': ('sheet_metal_flat_pattern_delete',True,
     {'component':str},{}),
})

EFFECTS = {name: ('design_mutation' if spec[1] else 'inspection') for name, spec in SPECS.items()}
for _name in SPECS:
    if _name.startswith('checkpoint '):
        EFFECTS[_name] = 'checkpoint_control'
    elif _name == 'documents export' or _name == 'files download':
        EFFECTS[_name] = 'file_output'
    elif _name.startswith(('projects ', 'folders ', 'files ')) and _name.split()[-1] not in ('list','inspect','search'):
        EFFECTS[_name] = 'cloud_mutation'
    elif _name.startswith('documents ') and _name.split()[-1] not in ('list','inspect'):
        EFFECTS[_name] = 'document_change'
    elif _name == 'workspace activate':
        EFFECTS[_name] = 'workspace_change'
    elif _name in {
        'animation storyboards create',
        'animation storyboards activate',
        'animation storyboards copy',
        'animation storyboards move',
        'animation storyboards reverse',
        'animation storyboards delete',
        'animation playback seek',
        'animation playback play',
        'animation playback full-screen',
        'animation camera recording',
        'animation settings recording-mode',
        'animation settings watermark',
    }:
        EFFECTS[_name] = 'animation_change'
    elif _name in ('design motion check','design motion render','design motion inspect'):
        EFFECTS[_name] = 'temporary_preview'
    elif _name in ('design export','design viewport screenshot','design motion open'):
        EFFECTS[_name] = 'file_output'
    elif _name in ('design timeline roll','design timeline beginning','design timeline end'):
        EFFECTS[_name] = 'workspace_change'
    elif _name in ('design timeline groups collapse','design timeline groups expand',
                   'design selection clear','design selection add','design selection remove'):
        EFFECTS[_name] = 'ui_change'


def resolve(words):
    for n in range(len(words), 0, -1):
        candidate = ' '.join(words[:n])
        if candidate in SPECS or candidate in ALIASES:
            return ALIASES.get(candidate,candidate), n
    return None, 0


class Parser(argparse.ArgumentParser):
    def error(self, message): raise ValueError(message + '\n' + self.format_usage())


def parser(command):
    details = {
        'checkpoint begin': 'Start a named Design checkpoint before editing. IDs must be unique in the current verified session. Optional document-id prevents editing the wrong active design.',
        'checkpoint finish': 'Finish the active checkpoint. Finish before restoring; this does not undo its changes.',
        'checkpoint status': 'List available session checkpoints and the active ID. Reloading the bridge or external edits invalidate restoration.',
        'checkpoint restore': 'Restore the Design to before this checkpoint, undoing its transactions and all later checkpoints. Requires a finished, verified chain; no selective undo or redo.',
        'design sketches offset': 'Offset 1–100 end-connected curve tokens in flow order with signed distance-mm. Positive is right of flow (outside for circles); negative is left. Creates a parametric topology-matched offset.',
        'design sketches trim': 'Remove the segment nearest x-mm,y-mm in sketch coordinates. Without intersections the entire curve is deleted. Fixed/linked curves are refused. Refresh geometry and profiles after trimming.',
        'design interference check': 'Analyze 2–32 root solid body names/tokens or occurrence:<full path> selectors. Use assembly instances to discover paths. At most 100 body instances; overlapping selections are refused. Coincident faces are excluded.',
        'design motion inspect': 'Drive coordinated tracks and analyze selected entities at uniform samples plus every keyframe time (maximum 120 poses). Default samples=21. Restores starting pose via verified transaction abort. Sampling cannot prove continuous collision-free motion.',
        'design motion check': 'Check joint positions at uniform samples plus keyframes; default samples=5. Tracks use joint, axis, keys, optional easing: linear, ease-in, ease-out, ease-in-out, step. Equal consecutive values create a pause.',
        'design motion render': 'Capture coordinated joint tracks with optional easing and playback once, loop (default), or ping-pong. Equal consecutive key values create pauses. At most 120 frames; restores starting pose.',

        'design sketches arcs add': 'points-mm is exactly three distinct [x,y] pairs: start, through, end. '
                                   'Points must not be collinear. Returned arc endpoints follow Fusion counterclockwise order.',
        'design sketches splines add': 'points-mm is 2 to 100 distinct [x,y] pairs. '
                                      'Use --closed true for a periodic spline with at least 3 points; do not repeat the first point.',
        'design sketches points add': 'Creates a sketch-space point. Use geometry list to get its current index for holes create.',
        'design sketches profiles list': 'Lists closed profile indices, approximate area, perimeter and sketch-space centroid. '
                                        'Refresh after edits before choosing --profile-index.',
        'design sketches create': 'Use --support with a planar face or construction-plane token. The sketch belongs to its support component. '
                                  'Face sketches start empty. --component may assert ownership or select a component for an origin-plane sketch.',
        'design sketches project': 'Project 1–100 native edge/face/vertex/sketch-entity tokens from the same component. '
                                   '--linked true (default) tracks source changes; false creates independent geometry.',
        'design features extrude': 'Through-all requires --extent through-all, --operation cut or intersect, explicit --participants JSON, '
                                   'and optional --direction positive, negative, or both. Both needs material on each side. '
                                   'Moved/rotated component through-all is unavailable. Distance remains the default. profile-index defaults to 0. Use sketches profiles list to select a closed region. '
                                   'Sketch accepts a token or unique name; creates the feature in the sketch component.',
        'design features revolve': 'profile-index defaults to 0. Use sketches profiles list to select a closed region. '
                                   'Sketch accepts a token or unique name; X/Y axes belong to the sketch component.',
    }
    p = Parser(prog='fusion ' + command, add_help=False, allow_abbrev=False,
               description='Lengths/coordinates in mm; angles in degrees. Lists use JSON arrays. '
                           + details.get(command, ''))
    _, _, required, optional = SPECS[command]
    if command.startswith(('design ', 'animation ')):
        optional={**optional,'document_id':str}
    for name, kind in {**required, **optional}.items():
        options = {'required':name in required, 'default':argparse.SUPPRESS}
        if kind is bool: options['action'] = 'store_true'
        elif isinstance(kind,tuple): options['choices'] = kind
        else: options['type'] = kind
        p.add_argument('--'+name.replace('_','-'), **options)
    return p


def validate_modeling(handler, data):
    if handler in ('check_animation', 'render_animation', 'inspect_motion'):
        validate_tracks(data['tracks'])
        if handler != 'render_animation':
            sample_times(data['tracks'], data.get('samples', 21 if handler == 'inspect_motion' else 5))
        else:
            fps, seconds = data.get('fps', 12), data.get('seconds', 2)
            if (type(fps) is not int or not 1 <= fps <= 30 or type(seconds) not in (int, float)
                    or not math.isfinite(seconds) or not 0 < seconds <= 10 or round(fps * seconds) > 120):
                raise ValueError('Use fps 1–30, seconds >0–10, and at most 120 frames.')
            if data.get('playback', 'loop') not in ('once', 'loop', 'ping-pong'):
                raise ValueError('Use playback once, loop, or ping-pong.')
    if handler in ('interference_check', 'inspect_motion'):
        validate_entities(data['entities'])
    if handler == 'sketch_offset':
        values = data['entities']
        if (not isinstance(values, list) or not 1 <= len(values) <= 100
                or any(not isinstance(v, str) or not v.strip() for v in values)
                or len(set(values)) != len(values)):
            raise ValueError('Offset requires 1–100 distinct curve tokens.')
        value = data['distance_mm']
        if type(value) not in (int, float) or not math.isfinite(value) or value == 0:
            raise ValueError('Offset distance-mm must be finite and nonzero.')

    if handler == 'create_sketch':
        if 'support' in data and ('plane' in data or 'offset_mm' in data):
            raise ValueError('--support cannot be combined with --plane or --offset-mm.')
        if 'offset_mm' in data and (type(data['offset_mm']) not in (int, float) or not math.isfinite(data['offset_mm'])):
            raise ValueError('offset-mm must be finite.')
    if handler in ('extrude', 'project_geometry'):
        key = 'participants' if handler == 'extrude' else 'entities'
        if key in data:
            values = data[key]
            if (not isinstance(values, list) or not 1 <= len(values) <= 100
                    or any(not isinstance(v, str) or not v.strip() for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError('--' + key + ' requires 1–100 distinct nonempty selectors.')
    if handler == 'project_geometry' and type(data.get('linked', True)) is not bool:
        raise ValueError('--linked must be true or false.')
    if handler == 'extrude':
        extent = data.get('extent', 'distance')
        operation = data.get('operation', 'join')
        if extent == 'through-all':
            if operation not in ('cut', 'intersect') or not data.get('participants'):
                raise ValueError('Through-all requires --operation cut or intersect and explicit --participants.')
            if any(k in data for k in ('distance_mm', 'symmetric')):
                raise ValueError('Through-all cannot use --distance-mm or --symmetric; use --direction.')
            if data.get('direction', 'positive') not in ('positive', 'negative', 'both'):
                raise ValueError('Invalid through-all direction.')
        elif extent == 'distance':
            value = data.get('distance_mm')
            if type(value) not in (int, float) or not math.isfinite(value) or value == 0:
                raise ValueError('Distance extrusion requires a finite nonzero --distance-mm.')
            if 'direction' in data:
                raise ValueError('--direction is for through-all; use signed --distance-mm for distance extrusion.')
        else:
            raise ValueError('Unknown extrusion extent.')
        if 'participants' in data and operation not in ('cut', 'intersect'):
            raise ValueError('--participants applies only to cut or intersect.')


def prepare(args):
    if not isinstance(args, dict) or set(args) != {'command'} or not isinstance(args['command'],str) or len(args['command']) > 20000:
        raise ValueError('Provide only command: a CLI string of at most 20000 characters.')
    words = shlex.split(args['command'])
    if words[:1] == ['fusion']: words = words[1:]
    if any(w in (';', '|', '&&', '||', '>', '<') for w in words):
        raise ValueError('One Fusion command per call; shell operators are not supported.')
    if not words or words[0] in ('help','--help') or '--help' in words:
        topic = ' '.join(w for w in words if w not in ('help','--help'))
        topic = ALIASES.get(topic,topic)
        if topic and not any(c == topic or c.startswith(topic+' ') for c in SPECS):
            alternatives={new.rsplit(' ',1)[0] for old,new in ALIASES.items() if old.startswith(topic+' ')}
            if len(alternatives)==1: topic=alternatives.pop()
        if topic in SPECS:
            return None, {'help':parser(topic).format_help(), 'mutates_design':SPECS[topic][1], 'effect':EFFECTS[topic]}, False
        matches = [c for c in SPECS if not topic or c.startswith(topic+' ') or c==topic]
        if not matches: raise ValueError('Unknown help topic: '+topic)
        return None, {'commands':matches,'usage':'fusion help <command> or fusion <command> --help',
                      'units':'mm and degrees; list flags accept JSON arrays',
                      'parameters_set_example': 'fusion parameters set --document "Design name" --changes \'[{"name":"d1","expected_expression":"100 mm","expression":"75 mm"}]\''}, False
    command, depth = resolve(words)
    if command is None: raise ValueError('Unknown command. Use fusion help.')
    handler, mutates, _, _ = SPECS[command]
    flags = [word.split('=', 1)[0] for word in words[depth:] if word.startswith('--')]
    if len(flags) != len(set(flags)):
        raise ValueError('Repeated flags are not supported; provide each option once.')
    data = vars(parser(command).parse_args(words[depth:]))
    for name in ('names','tools'):
        if name in data and any(not isinstance(v,str) or not v.strip() for v in data[name]):
            raise ValueError('--'+name+' must contain nonempty strings.')
    if 'edge_indices' in data and any(type(v) is not int or v < 0 for v in data['edge_indices']):
        raise ValueError('--edge-indices must contain nonnegative integers.')
    if 'limit' in data and data['limit'] <= 0:
        raise ValueError('--limit must be greater than zero.')
    if 'changes' in data:
        for c in data['changes']:
            if not isinstance(c,dict) or set(c) != {'name','expected_expression','expression'} or any(not isinstance(v,str) or not v for v in c.values()):
                raise ValueError('Each change requires name, expected_expression and expression strings.')
    validate_modeling(handler, data)
    return handler, data, mutates
