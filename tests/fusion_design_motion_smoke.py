"""Native geometry and rollback gate for design → motion → interference."""
import json
import math
from pathlib import Path
import shlex
import traceback
import adsk.core
import adsk.fusion
from bridge import commands
from bridge.build import BUILD
from bridge.fusion_undo import FusionUndo
from tools.registry import _TOOL_MAP
from tools import motion

app=adsk.core.Application.get();ui=app.userInterface
original,workspace=app.activeDocument,ui.activeWorkspace
selections=[ui.activeSelections.item(i).entity for i in range(ui.activeSelections.count)]
fixture=controller=None
report={'build':BUILD,'transport':'native CLI with checkpoint transactions','passed':False,'results':[]}
q=shlex.quote

def run(command):
    row={'command':command,'passed':False};report['results'].append(row)
    handler,args,mutates=commands.prepare({'command':command})
    target=_TOOL_MAP[handler]
    if handler in ('check_animation','render_animation','inspect_motion'):
        result=controller.preview(lambda a:motion.run_preview(target,a),args,motion.observe_axes)
    else:result=controller.execute(target,args) if mutates else target(args)
    row.update(passed=True,result=result)
    return result

def close(actual,expected):assert math.isclose(actual,expected,abs_tol=1e-4,rel_tol=1e-5),(actual,expected)

def box(comp,x,y,name):
    sk=comp.sketches.add(comp.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(x,y,0),adsk.core.Point3D.create(x+1,y+1,0))
    inp=comp.features.extrudeFeatures.createInput(sk.profiles.item(0),adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False,adsk.core.ValueInput.createByReal(1))
    body=comp.features.extrudeFeatures.add(inp).bodies.item(0);body.name=name
    return body

try:
    fixture=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType);fixture.name='CadBot Design Motion Fixture'
    ui.workspaces.itemById('FusionSolidEnvironment').activate()
    d=adsk.fusion.Design.cast(app.activeProduct);root=d.rootComponent
    a=root.occurrences.addNewComponent(adsk.core.Matrix3D.create());a.component.name='Base';a.isGrounded=True
    b=root.occurrences.addNewComponent(adsk.core.Matrix3D.create());b.component.name='Slider'
    c=root.occurrences.addNewComponent(adsk.core.Matrix3D.create());c.component.name='Hinge'
    ground=box(a.component,0,0,'GroundCube');moving=box(b.component,2,0,'MovingCube');box(c.component,0,5,'HingeCube')
    for occurrence,name,revolute in ((b,'Slide',False),(c,'Turn',True)):
        geo=adsk.fusion.JointGeometry.createByPoint(occurrence.component.originConstructionPoint.createForAssemblyContext(occurrence))
        inp=root.asBuiltJoints.createInput(a,occurrence,geo)
        if revolute:inp.setAsRevoluteJointMotion(adsk.fusion.JointDirections.ZAxisJointDirection)
        else:inp.setAsSliderJointMotion(adsk.fusion.JointDirections.XAxisJointDirection)
        root.asBuiltJoints.add(inp).name=name
    initial_pose=motion.observe_axes();initial_transforms=[o.transform2.asArray() for o in (a,b,c)]
    base_body=box(root,10,10,'RootA');other_body=box(root,10.5,10,'RootB')
    controller=FusionUndo();controller.begin('baseline')
    listed=run('fusion design motion joints list')['joints']
    assert {r['name'] for r in listed}=={'Slide','Turn'}
    assert all('::as-built:' in r['selector'] for r in listed)
    run('fusion design sketches create --name OffsetCircle')
    circle=run('fusion design sketches circles add --sketch OffsetCircle --center-x-mm 0 --center-y-mm 0 --radius-mm 10')['circle']['token']
    controller.execute(lambda _:d.findEntityByToken(circle)[0].parentSketch.sketchDimensions.addDiameterDimension(adsk.fusion.SketchCircle.cast(d.findEntityByToken(circle)[0]),adsk.core.Point3D.create(2,2,0)),{})
    run('fusion design sketches create --name TrimLines')
    line=run('fusion design sketches lines add --sketch TrimLines --x1-mm 0 --y1-mm 0 --x2-mm 30 --y2-mm 0')['line']['token']
    for x in (10,20):run(f'fusion design sketches lines add --sketch TrimLines --x1-mm {x} --y1-mm -10 --x2-mm {x} --y2-mm 10')
    run('fusion design sketches create --name DeleteTrim')
    whole=run('fusion design sketches lines add --sketch DeleteTrim --x1-mm 0 --y1-mm 0 --x2-mm 10 --y2-mm 0')['line']['token']
    controller.finish();controller.begin('edit')
    offset=run('fusion design sketches offset --sketch OffsetCircle --entities '+q(json.dumps([circle]))+' --distance-mm 2')
    close(offset['created'][0]['radius_mm'],12)
    child=d.findEntityByToken(offset['created'][0]['token'])[0]
    dim=d.findEntityByToken(circle)[0].parentSketch.sketchDimensions.item(0)
    run('fusion design sketches dimensions set --sketch OffsetCircle --dimension '+q(dim.entityToken)+' --expression '+q('30 mm'))
    close(child.radius*10,17)
    trimmed=run('fusion design sketches trim --sketch TrimLines --entity '+q(line)+' --x-mm 15 --y-mm 0')
    assert len(trimmed['result_curves'])==2,trimmed
    close(sum(c['length_mm'] for c in trimmed['result_curves']),20)
    deleted=run('fusion design sketches trim --sketch DeleteTrim --entity '+q(whole)+' --x-mm 5 --y-mm 0')
    assert not deleted['original_survives'] and not deleted['result_curves'],deleted
    controller.finish();controller.restore('edit');controller.begin('inspection')
    sk=d.findEntityByToken(circle)[0].parentSketch
    assert sk.sketchCurves.count==1;close(sk.sketchCurves.item(0).radius*10,10)
    assert d.findEntityByToken(line)[0].length*10==30
    static=run('fusion design interference check --entities \'["RootA","RootB"]\'')
    assert static['interference_count']==1;close(static['total_pair_volume_mm3'],500)
    entities=['occurrence:'+a.fullPathName,'occurrence:'+b.fullPathName]
    empty=run('fusion design interference check --entities '+q(json.dumps(entities)))
    assert empty['interference_count']==0
    tracks=[{'joint':'Slide','axis':'slide','keys':[[0,0],[.4,15],[.6,15],[1,0]],'easing':'ease-in-out'},
            {'joint':'Turn','axis':'rotation','keys':[[0,0],[1,30]],'easing':'ease-out'}]
    suffix=' --tracks '+q(json.dumps(tracks))
    check=run('fusion design motion check'+suffix+' --samples 5')
    assert check['pose_restored'];assert motion.observe_axes()==initial_pose
    from tools import interference
    native_analyze=interference.analyze
    def observe_interference(design,entities):
        report.setdefault('pose_geometry',[]).append({'translation':b.transform2.translation.asArray(),'moving_bbox':moving.createForAssemblyContext(b).boundingBox.minPoint.asArray()})
        return native_analyze(design,entities)
    interference.analyze=observe_interference
    try: inspected=run('fusion design motion inspect'+suffix+' --entities '+q(json.dumps(entities))+' --samples 5')
    finally: interference.analyze=native_analyze
    assert inspected['pose_restored'];assert inspected['sample_count']==7
    assert inspected['poses_with_interference']>0,inspected
    for sample in inspected['samples']:
        if sample['time'] in (.4,.5,.6):close(sample['total_pair_volume_mm3'],500)
    assert motion.observe_axes()==initial_pose
    assert [o.transform2.asArray() for o in (a,b,c)]==initial_transforms
    app.activeViewport.fit()
    for mode in ('once','loop','ping-pong'):
        rendered=run('fusion design motion render'+suffix+' --fps 4 --seconds 1 --playback '+mode)
        assert rendered['pose_restored'] and rendered['playback']==mode
        assert Path(rendered['path']).is_file();assert motion.observe_axes()==initial_pose
        report.setdefault('preview_paths',[]).append(rendered['path'])
    # A real native interference failure after the joints move must still abort.
    from tools import interference
    original_analyze=interference.analyze
    def fail_analysis(*args):
        if motion.observe_axes()!=initial_pose:
            report['failure_injected_at_changed_pose']=True
            raise RuntimeError('injected analysis failure after motion')
        return original_analyze(*args)
    interference.analyze=fail_analysis
    try:
        try:controller.preview(lambda a:motion.run_preview(motion.inspect_motion,a),{'tracks':tracks,'entities':entities},motion.observe_axes)
        except RuntimeError as exc:assert 'rolled back' in str(exc),str(exc)
        else:raise AssertionError('Expected analysis failure')
    finally:interference.analyze=original_analyze
    assert motion.observe_axes()==initial_pose
    assert report.get('failure_injected_at_changed_pose') is True
    controller.finish();controller.restore('inspection')
    close(base_body.volume*1000,1000);close(other_body.volume*1000,1000)
    report.update(passed=True,offset_association_verified=True,trim_geometry_verified=True,
                  collision_volume_verified=True,coordinated_motion_verified=True,failed_analysis_rollback_verified=True)
except Exception:report['error']=traceback.format_exc()
finally:
    try:
        if controller:controller.close()
        if fixture:fixture.close(False)
        original.activate();workspace.activate();ui.activeSelections.clear()
        for entity in selections:ui.activeSelections.add(entity)
        assert app.activeDocument==original and ui.activeWorkspace==workspace
        report['original_context_restored']=True
    except Exception:report.update(passed=False,cleanup_error=traceback.format_exc())
    Path('/tmp/cadbot-design-motion-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Design motion gate:',report['passed'],report.get('error',''))
