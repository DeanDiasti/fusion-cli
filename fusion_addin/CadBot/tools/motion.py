"""Joint driving and bounded animation rendering using public Fusion motion APIs."""
from contextvars import ContextVar

_preview_active = ContextVar("cadbot_preview_active", default=False)

def run_preview(fn, args):
    token = _preview_active.set(True)
    try: return fn(args)
    finally: _preview_active.reset(token)

def require_preview():
    if not _preview_active.get():
        raise RuntimeError("Use the CLI transaction controller for animation previews.")

import base64
import json
import math
import tempfile
from pathlib import Path
import adsk.core
from .features import _get_design
from bridge.commands import validate_tracks, sample_times

# Deliberately limited to simple, independently drivable axes.
AXES = {'rotation': ('rotationValue', 'rotationLimits', math.pi / 180),
        'slide': ('slideValue', 'slideLimits', 0.1)}


def joint_entries():
    design = _get_design()
    contexts = [('@root', design.rootComponent, None)]
    contexts.extend((o.fullPathName, o.component, o) for o in design.rootComponent.allOccurrences)
    result=[]
    for path, component, occurrence in contexts:
        for kind, collection in (('joint',component.joints),('as-built',component.asBuiltJoints)):
            for native in collection:
                proxy = native.createForAssemblyContext(occurrence) if occurrence else native
                if proxy is None:
                    raise RuntimeError('Could not resolve assembly-context joint: '+path+'::'+native.name)
                result.append({'selector':path+'::'+kind+':'+native.name,
                    'path':path,'component':component.name,'joint':proxy})
    return result


def joints():
    return [entry['joint'] for entry in joint_entries()]


def resolve(name):
    entries=joint_entries()
    exact=[e['joint'] for e in entries if e['selector']==name]
    if len(exact)==1:return exact[0]
    # Tokens from older definition-level listings are intentionally not accepted.
    # They cannot safely identify one instance of a repeated component.
    matches=[e for e in entries if e['joint'].name==name]
    if len(matches)==1:return matches[0]['joint']
    raise ValueError('Joint selector is missing or ambiguous. Use the exact selector from joints list: '+str(name))


def joint_identity(j):
    context=getattr(j,'assemblyContext',None)
    return (context.fullPathName if context else '@root', j.name, getattr(j,'objectType','joint'))


def observe_axes():
    result={}
    for e in joint_entries():
        m=e['joint'].jointMotion
        if m is None:continue
        for name,(prop,_,scale) in AXES.items():
            if hasattr(m,prop):result[(e['selector'],name)]=getattr(m,prop)/scale
    return result


def observed_changes(before):
    after=observe_axes()
    return [{'joint':key[0],'axis':key[1],'before':value,'after':after[key],
             'delta':after[key]-value,'units':'deg' if key[1]=='rotation' else 'mm'}
            for key,value in before.items() if key in after and abs(after[key]-value)>1e-6]


def assembly_instances(args):
    d=_get_design();result=[]
    for o in d.rootComponent.allOccurrences:
        result.append({'path':o.fullPathName,'component':o.component.name,
            'grounded':o.isGrounded,'ground_to_parent':getattr(o,'isGroundToParent',None),
            'referenced':o.isReferencedComponent})
    return {'instances':result,'note':'Repeated component names may share a definition. Use full joint selectors for motion; grounding alone does not establish degrees of freedom.'}


def axis(joint, name):
    if name not in AXES: raise ValueError('axis must be rotation (degrees) or slide (mm).')
    motion = joint.jointMotion
    prop, limits, scale = AXES[name]
    if motion is None or not hasattr(motion, prop): raise ValueError('Joint does not support '+name+': '+joint.name)
    if getattr(joint, 'isSuppressed', False) or getattr(joint, 'isLocked', False):
        raise ValueError('Joint is suppressed or locked: '+joint.name)
    return motion, prop, getattr(motion,limits), scale


def validate_value(motion, limits, value, scale):
    if type(value) not in (int,float) or not math.isfinite(value): raise ValueError('Joint value must be finite.')
    native = value * scale
    if limits.isMinimumValueEnabled and native < limits.minimumValue - 1e-9: raise ValueError('Value is below joint limit.')
    if limits.isMaximumValueEnabled and native > limits.maximumValue + 1e-9: raise ValueError('Value is above joint limit.')
    return native


def list_joints(args):
    result=[]
    for entry in joint_entries():
        j=entry['joint'];m=j.jointMotion
        axes={}
        for name,(prop,lim,scale) in AXES.items():
            if m is not None and hasattr(m,prop):
                limits=getattr(m,lim)
                axes[name]={'value':getattr(m,prop)/scale,'units':'deg' if name=='rotation' else 'mm',
                    'min':limits.minimumValue/scale if limits.isMinimumValueEnabled else None,
                    'max':limits.maximumValue/scale if limits.isMaximumValueEnabled else None}
        result.append({'name':j.name,'selector':entry['selector'],'assembly_path':entry['path'],'component':entry['component'],'type':m.objectType if m else None,
            'axes':axes,'locked':getattr(j,'isLocked',False),'suppressed':getattr(j,'isSuppressed',False),
            'occurrence_one':j.occurrenceOne.fullPathName if j.occurrenceOne else None,
            'occurrence_two':j.occurrenceTwo.fullPathName if j.occurrenceTwo else None})
    return {'joints':result,'animation':'Use existing rotation/slide axes. This does not rig unjointed bodies or calculate a physically balanced gait.'}


def drive(args):
    j=resolve(args['joint']); m,prop,limits,scale=axis(j,args['axis'])
    value=validate_value(m,limits,args['value'],scale)
    setattr(m,prop,value)
    actual=getattr(m,prop)
    if abs(actual-value)>1e-6: raise RuntimeError('Fusion did not reach the requested joint value.')
    return {'joint':j.name,'axis':args['axis'],'value':actual/scale}


def sample(keys, t, easing='linear'):
    if t <= keys[0][0]: return keys[0][1]
    for (a,x),(b,y) in zip(keys,keys[1:]):
        if t < b:
            u = (t-a)/(b-a)
            if easing == 'ease-in': u = u*u
            elif easing == 'ease-out': u = 1-(1-u)*(1-u)
            elif easing == 'ease-in-out': u = u*u*(3-2*u)
            elif easing == 'step': u = 0
            return x+(y-x)*u
    return keys[-1][1]


def prepare_tracks(tracks):
    validate_tracks(tracks)
    prepared=[];seen=set()
    for track in tracks:
        j=resolve(track['joint']);m,prop,limits,scale=axis(j,track['axis'])
        identity=(joint_identity(j),prop)
        if identity in seen: raise ValueError('Duplicate joint axis track.')
        seen.add(identity)
        keys=track['keys']
        for _, value in keys: validate_value(m,limits,value,scale)
        prepared.append((m,prop,scale,keys,getattr(m,prop),track.get('easing','linear')))
    return prepared


def deviation(m, prop, requested):
    actual = getattr(m, prop)
    delta = actual - requested
    if prop == 'rotationValue':
        limits = m.rotationLimits
        if not limits.isMinimumValueEnabled and not limits.isMaximumValueEnabled:
            delta = math.remainder(delta, 2 * math.pi)
        return actual * 180 / math.pi, abs(delta) * 180 / math.pi, 'deg'
    return actual * 10, abs(delta) * 10, 'mm'


def position_report(tracks, targets, labels, restoring=False):
    report=[]
    for (m,prop,scale,_,_,_),value,label in zip(tracks,targets,labels):
        actual,error,units=deviation(m,prop,value)
        # Preview fidelity is distinct from restoration precision.
        tolerance = 0.001 if restoring else (0.05 if units == 'deg' else 0.01)
        report.append({'joint':label, 'axis':'rotation' if units=='deg' else 'slide',
            'requested':value/scale,'actual':actual,'error':error,'units':units,
            'tolerance':tolerance,'within_tolerance':error<=tolerance})
    return report


def move_frame(tracks, t, labels):
    values=[sample(keys,t,easing)*scale for _,_,scale,keys,_,easing in tracks]
    for (m,prop,_,_,_,_),value in zip(tracks,values): setattr(m,prop,value)
    report=position_report(tracks,values,labels)
    if any(not r['within_tolerance'] for r in report):
        raise RuntimeError('Joint target mismatch: '+json.dumps({'time':t,'joints':report,
            'next_step':'Inspect constraints; test one independent driver at a time using animation check. Do not repeatedly retry these tracks.'}))
    return report


def check(args):
    require_preview()
    tracks=prepare_tracks(args['tracks']); labels=[t['joint'] for t in args['tracks']]
    reports=[];before=observe_axes()
    times=sample_times(args['tracks'],args.get('samples',5))
    for t in times:
        report=move_frame(tracks,t,labels)
        reports.append({'time':t,'joints':report,'observed_changes':observed_changes(before)})
    return {'samples':reports,
            'sample_count':len(times), 'note':'Sampled feasibility check including keyframes; not proof of collision-free motion or every intermediate frame.'}


def inspect_motion(args):
    require_preview()
    from . import interference
    tracks=prepare_tracks(args['tracks'])
    times=sample_times(args['tracks'],args.get('samples',21))
    design,entities=interference.resolve_entities(args['entities'])
    labels=[t['joint'] for t in args['tracks']]
    reports=[]
    for t in times:
        joints=move_frame(tracks,t,labels)
        reports.append({'time':t,'joints':joints,**interference.analyze(design,entities)})
    collisions=[r for r in reports if r['interference_count']]
    return {'samples':reports,'sample_count':len(reports),
            'poses_with_interference':len(collisions),
            'first_interference_time':collisions[0]['time'] if collisions else None,
            'max_pair_volume_mm3':max((r['total_pair_volume_mm3'] for r in reports),default=0),
            'note':'Uniform samples plus keyframe poses only. Thin or brief collisions between samples may be missed; this is not continuous collision detection or dynamics simulation.'}


def render(args):
    require_preview()
    from bridge.commands import validate_modeling
    validate_modeling('render_animation',args)
    fps=args.get('fps',12);seconds=args.get('seconds',2)
    playback=args.get('playback','loop')
    if not 1<=fps<=30 or not math.isfinite(seconds) or not 0<seconds<=10: raise ValueError('Use fps 1–30 and seconds >0–10.')
    count=max(2,round(fps*seconds))
    if count>120: raise ValueError('Use at most 120 frames (fps × seconds).')
    tracks=prepare_tracks(args['tracks'])  # validate everything before moving anything
    app=adsk.core.Application.get();viewport=app.activeViewport
    folder=Path(tempfile.mkdtemp(prefix='cadbot-animation-'));frames=[]
    try:
        labels=[t['joint'] for t in args['tracks']]
        diagnostics=[]
        for i in range(count):
            diagnostics.append(move_frame(tracks,i/(count-1),labels))
            viewport.refresh()
            path=folder/'frame.png'
            if not viewport.saveAsImageFile(str(path),640,480): raise RuntimeError('Could not capture animation frame.')
            frames.append('data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode())
        (folder/'frame.png').unlink(missing_ok=True)
        html='''<!doctype html><meta charset="utf-8"><title>CadBot motion preview</title>
    <style>body{background:#171b22;color:white;font:16px system-ui;text-align:center}img{max-width:100%}button,input{margin:12px}</style>
    <h1>Joint motion preview</h1><img id="frame"><div><button id="play">Pause</button><input id="seek" type="range" min="0" value="0"></div>
    <p>CadBot keyframe preview · Joint keyframe visualization</p><script>
    const frames=FRAMES;const fps=FPS;const mode=MODE;let i=0,running=true,direction=1;
    const view=document.getElementById('frame'),seek=document.getElementById('seek');seek.max=frames.length-1;
    function show(){view.src=frames[i];seek.value=i;}show();
    document.getElementById('play').onclick=function(){if(mode==='once' && i===frames.length-1){i=0;show();}running=!running;this.textContent=running?'Pause':'Play';};
    seek.oninput=()=>{i=Number(seek.value);show();};
    setInterval(()=>{if(!running)return;
    if(mode==='once' && i===frames.length-1){running=false;document.getElementById('play').textContent='Replay';return;}
    if(mode==='ping-pong' && (i===frames.length-1 || (i===0 && direction<0)))direction=-direction;
    i=mode==='ping-pong'?i+direction:(i+1)%frames.length;show();},1000/fps);
    </script>'''.replace('FRAMES',json.dumps(frames)).replace('FPS',str((count-1)/seconds)).replace('MODE',json.dumps(playback))
        path=folder/'animation.html';path.write_text(html)
        return {'path':str(path),'frames':count,'fps':fps,'seconds':seconds,'playback':playback,'max_preview_error':max((r['error'] for frame in diagnostics for r in frame),default=0),
                'format':'self-contained HTML animation with play/pause and scrubbing',
                'limitations':'Kinematic joint preview; not a native Motion Study, video file, collision check, or dynamics simulation.'}

    except Exception:
        import shutil
        shutil.rmtree(folder,ignore_errors=True)
        raise


def open_preview(args):
    import webbrowser
    path=Path(args['path']).resolve()
    temp_root=Path(tempfile.gettempdir()).resolve()
    if path.name!='animation.html' or not path.parent.name.startswith('cadbot-animation-') or path.parent.parent!=temp_root or not path.is_file():
        raise ValueError('Choose the animation.html path returned by animation render.')
    if not webbrowser.open(path.as_uri()): raise RuntimeError('Could not open the animation in your browser.')
    return {'opened':str(path)}
