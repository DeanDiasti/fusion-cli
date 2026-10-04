"""Native Animation workspace lifecycle. Never substitutes a motion preview."""
import adsk.core
import adsk.fusion
import uuid

NATIVE_AUTHORING_BUILD = "2705.1.15"

_selectors={}


def selector(b):
    document=adsk.core.Application.get().activeDocument.creationId
    for key,(owner,item) in list(_selectors.items()):
        if not item.isValid:
            del _selectors[key]
        elif owner==document and item==b:
            return key
    key='storyboard:'+uuid.uuid4().hex
    _selectors[key]=(document,b)
    return key


def manager():
    app=adsk.core.Application.get()
    if not app.activeDocument:
        raise ValueError('Open a Fusion document first')
    design=adsk.fusion.Design.cast(app.activeDocument.products.itemByProductType('DesignProductType'))
    if design is None or not hasattr(design,'animationManager'):
        raise RuntimeError('This Fusion runtime does not expose native Animation for this document')
    return design.animationManager


def require_workspace(m):
    if not m.isAnimationWorkspaceActive:
        raise ValueError('Activate the Animation workspace using fusion workspace activate first')


def board(args):
    m=manager(); require_workspace(m)
    saved=_selectors.get(args['storyboard'])
    if saved is None or saved[0]!=adsk.core.Application.get().activeDocument.creationId or not saved[1].isValid:
        raise ValueError('Storyboard selector is stale or invalid. List storyboards again.')
    return saved[1]


def info(b,index):
    return {'index':index,'selector':selector(b),'active':b.isActive,'end_seconds':b.end,
            'playhead_seconds':b.playheadPosition,'playing':b.isInPlayMode,
            'view_recording':b.isViewRecordingOn,
            'full_screen':b.isInFullScreenMode}


def board_index(b):
    storyboards=manager().storyboards
    for index in range(storyboards.count):
        if storyboards.item(index)==b:
            return index
    raise RuntimeError('Storyboard is no longer present in the active document')


def storyboards_list(args):
    m=manager(); require_workspace(m)
    return {'storyboards':[info(m.storyboards.item(i),i) for i in range(m.storyboards.count)]}


def storyboards_create(args):
    m=manager(); require_workspace(m)
    b=m.storyboards.add(not args.get('from_previous',False))
    if b is None: raise RuntimeError('Fusion did not create the storyboard')
    return storyboards_list({})


def storyboards_activate(args):
    if not board(args).activate(): raise RuntimeError('Storyboard activation failed')
    return storyboards_list({})


def storyboards_copy(args):
    source=board(args)
    target=None
    if args.get('target_storyboard'):
        target=board({'storyboard':args['target_storyboard']})
    copied=source.copy(args.get('name',''),target,args.get('before',False))
    if copied is None: raise RuntimeError('Storyboard copy failed')
    return storyboards_list({})


def storyboards_move(args):
    source=board(args)
    target=board({'storyboard':args['target_storyboard']})
    if source==target: raise ValueError('Source and target storyboards must be different')
    if not source.moveTo(target,args.get('before',False)):
        raise RuntimeError('Storyboard move failed')
    return storyboards_list({})


def storyboards_reverse(args):
    if not board(args).reverse(): raise RuntimeError('Storyboard reverse failed')
    return storyboards_list({})


def storyboards_delete(args):
    if not board(args).deleteMe(): raise RuntimeError('Storyboard deletion failed')
    return storyboards_list({})


def storyboards_seek(args):
    b=board(args)
    t=args['seconds']
    if t != -1 and not 0 <= t <= b.end:
        raise ValueError('Seek time must be -1 (scratch zone) or between 0 and storyboard end')
    b.playheadPosition=t
    adsk.doEvents()
    if abs(b.playheadPosition-t)>1e-6:
        raise RuntimeError('Seek was not observed: requested '+str(t)+' seconds, actual '+str(b.playheadPosition))
    return info(b,board_index(b))


def storyboards_play(args):
    b=board(args)
    begin=args.get('begin_seconds',0)
    end=args.get('end_seconds',0)
    if begin < 0 or end < 0: raise ValueError('Playback times cannot be negative')
    if end and begin > end: raise ValueError('Playback begin must not exceed end')
    if end > b.end: raise ValueError('Playback end must not exceed storyboard end')
    if not b.play(args.get('from_current',True),begin,end):
        raise RuntimeError('Playback did not start')
    return info(b,board_index(b))


def playback_status(args):
    b=board(args)
    return info(b,board_index(b))


def playback_full_screen(args):
    b=board(args); b.isInFullScreenMode=args['enabled']; adsk.doEvents()
    if bool(b.isInFullScreenMode) != args['enabled']:
        raise RuntimeError('Fusion did not apply the requested full-screen state')
    return info(b,board_index(b))


def camera_recording(args):
    b=board(args); b.isViewRecordingOn=args['enabled']; adsk.doEvents()
    if bool(b.isViewRecordingOn) != args['enabled']:
        raise RuntimeError('Fusion did not apply the requested camera-recording state')
    return info(b,board_index(b))


_RECORDING_MODES={
    'time-zero':'RecordingModeStartFromTime0',
    'overlap-half-second':'RecordingModeOverlappedByHalfSeconds',
    'sequential':'RecordingModeSequential',
}


def _recording_mode_name(value):
    for name,attribute in _RECORDING_MODES.items():
        if value == getattr(adsk.fusion.RecordingModeTypes,attribute): return name
    return str(value)


def settings_inspect(args):
    m=manager(); require_workspace(m)
    return {'recording_mode':_recording_mode_name(m.recordingMode),
            'watermark_shown':bool(m.isWatermarkShown)}


def settings_recording_mode(args):
    m=manager(); require_workspace(m)
    value=getattr(adsk.fusion.RecordingModeTypes,_RECORDING_MODES[args['mode']])
    m.recordingMode=value
    if m.recordingMode != value: raise RuntimeError('Fusion did not apply the recording mode')
    return settings_inspect({})


def settings_watermark(args):
    m=manager(); require_workspace(m); m.isWatermarkShown=args['enabled']
    if bool(m.isWatermarkShown) != args['enabled']:
        raise RuntimeError('Fusion did not apply the watermark state')
    return settings_inspect({})


def camera_inspect(args):
    b=board(args)
    camera=adsk.core.Application.get().activeViewport.camera
    def point(value): return {'x_cm':float(value.x),'y_cm':float(value.y),'z_cm':float(value.z)}
    def vector(value): return {'x':float(value.x),'y':float(value.y),'z':float(value.z)}
    return {
        'storyboard':info(b,board_index(b)),
        'camera':{
            'eye':point(camera.eye),'target':point(camera.target),'up':vector(camera.upVector),
            'perspective':camera.cameraType == adsk.core.CameraTypes.PerspectiveCameraType,
            'view_extents_cm':float(camera.viewExtents),
        },
    }


def authoring_capabilities(args):
    """Report action-authoring coverage without advertising unsafe private calls."""
    application=adsk.core.Application.get(); ui=application.userInterface
    context_error = None
    try:
        m = manager()
        workspace_active = bool(m.isAnimationWorkspaceActive)
    except (ValueError, RuntimeError, AttributeError) as exc:
        workspace_active = False
        context_error = str(exc)
    command_ids={
        'component_transform':'PublisherMoveComponentsCommand',
        'component_visibility':'PublisherVisibilityToggleCmd',
        'camera_action':'PublisherCreateCameraActionCmd',
        'camera_recording':'PublisherToggleCameraRecordingCmd',
        'callout_create':'CalloutCommand',
        'video_publish':'ExportVideoCommand',
    }
    commands={key:bool(ui.commandDefinitions.itemById(value)) for key,value in command_ids.items()}
    return {
        'fusion_version':application.version,
        'tested_fusion_version':NATIVE_AUTHORING_BUILD,
        'workspace_active':workspace_active,
        'context_error':context_error,
        'next_step': (context_error if context_error else
                      None if workspace_active else
                      'List workspaces with fusion workspace list, then activate Animation using fusion workspace activate.'),
        'public_api':{'storyboard_lifecycle':True,'storyboard_ordering':True,
                      'playback_and_seek':True,'playback_range':True,
                      'full_screen':True,'recording_settings':True,
                      'camera_recording_toggle':True,'occurrence_discovery':True,
                      'camera_inspection':True,'storyboard_rename':False,
                      'component_transform_action':False,'component_visibility_action':False,
                      'camera_action':False,'annotation_actions':False,
                      'action_timing_edit':False,'action_delete':False,
                      'video_publish':False,'action_collection':False},
        'native_commands_present':commands,
        'authoring_status':'blocked_unverified_private_adapter',
        'blocker':('Fusion exposes native authoring commands but no public Animation action API. '
                   'The installed build rejects programmatic transform input and scene property '
                   'changes do not create timeline actions. These operations remain unavailable '
                   'until their typed native transcript is live verified for this Fusion build.'),
        'safe_to_attempt_action_writes':False,
        'rotation_planning': {'available': True, 'command': 'fusion animation actions rotate --dry-run',
                              'native_action_writes': False,
                              'requires': ['document_id', 'storyboard', 'component', 'axis',
                                           'degrees', 'pivot_mm', 'start', 'end']},
    }
