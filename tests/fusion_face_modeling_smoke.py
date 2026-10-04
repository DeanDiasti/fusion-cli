"""Disposable native geometry, association, participant isolation, and undo gate."""
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

app = adsk.core.Application.get()
ui = app.userInterface
original, workspace = app.activeDocument, ui.activeWorkspace
selections = [ui.activeSelections.item(i).entity for i in range(ui.activeSelections.count)]
report = {'build': BUILD, 'transport': 'native CLI with checkpoint transactions', 'passed': False, 'results': []}
fixture = controller = None
q = shlex.quote

def run(command):
    assert app.activeDocument == fixture
    row = {'command': command, 'passed': False}
    report['results'].append(row)
    handler, args, mutates = commands.prepare({'command': command})
    result = controller.execute(_TOOL_MAP[handler], args) if mutates else _TOOL_MAP[handler](args)
    assert 'error' not in result, result
    row.update(result=result, passed=True)
    return result

def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-4), (actual, expected)

def box(component, z, name):
    plane = component.xYConstructionPlane
    if z:
        inp = component.constructionPlanes.createInput()
        inp.setByOffset(plane, adsk.core.ValueInput.createByReal(z))
        plane = component.constructionPlanes.add(inp)
    sk = component.sketches.add(plane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0),adsk.core.Point3D.create(4,3,0))
    inp = component.features.extrudeFeatures.createInput(sk.profiles.item(0),adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False,adsk.core.ValueInput.createByReal(1))
    feature = component.features.extrudeFeatures.add(inp)
    body = feature.bodies.item(0); body.name = name
    return feature, body

try:
    fixture = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    fixture.name = 'CadBot Face Modeling Fixture'
    ui.workspaces.itemById('FusionSolidEnvironment').activate()
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(0,0,0)
    component = design.rootComponent.occurrences.addNewComponent(transform).component
    component.name = 'FaceBracket'
    base, body = box(component, 0, 'TargetPlate')
    _, neighbor = box(component, 2, 'NeighborPlate')
    original_sketches = component.sketches.count
    controller = FusionUndo()
    for direction in ('negative', 'positive', 'both', 'intersect'):
        controller.begin('face-cut-' + direction)
        faces = run('fusion design bodies topology list --body TargetPlate')['items']
        face = max((f for f in faces if f['planar']), key=lambda f:f['point_mm'][2])
        created = (run('fusion design sketches create --component FaceBracket --offset-mm 5 --name Holes')
                   if direction == 'both' else
                   run('fusion design sketches create --component FaceBracket --plane XY --name Holes')
                   if direction == 'positive' else
                   run('fusion design sketches create --support ' + q(face['token']) + ' --component FaceBracket --name Holes'))
        sk = design.findEntityByToken(created['token'])[0]
        assert sk.parentComponent == component and sk.sketchCurves.count == 0
        if direction not in ('both', 'positive'):
            assert created['frame']['coordinate_space'] == 'owning_component'
            close(created['frame']['origin_mm'][2], 10)
        point = sk.modelToSketchSpace(adsk.core.Point3D.create(2,1.5,.5 if direction == 'both' else 0 if direction == 'positive' else 1))
        run('fusion design sketches circles add --sketch Holes --center-x-mm {} --center-y-mm {} --radius-mm 2'.format(point.x*10,point.y*10))
        actual_direction = direction if direction in ('both','positive') else 'negative' if created['frame']['normal'][2]>0 else 'positive'
        operation = 'intersect' if direction == 'intersect' else 'cut'
        if direction == 'negative':
            bad_command = 'fusion design features extrude --sketch Holes --extent through-all --operation cut --participants \'["NeighborPlate"]\' --direction '+actual_direction
            handler,args,_ = commands.prepare({'command':bad_command})
            before_head = controller.head()
            try:
                controller.execute(_TOOL_MAP[handler], args)
                raise AssertionError('A nonintersecting participant unexpectedly cut')
            except RuntimeError as exc:
                assert 'healthy extrusion' in str(exc) or 'body not found' in str(exc).lower(), str(exc)
                assert controller.head() == before_head
                assert component.features.extrudeFeatures.count == 2
                close(body.volume*1000,12000);close(neighbor.volume*1000,12000)
                report['results'].append({'command':bad_command,'passed':True,
                    'outcome':'expected_error_with_verified_rollback','error':str(exc)})
                report['failed_cut_rollback_verified'] = True
        cut = run('fusion design features extrude --sketch Holes --extent through-all --operation '+operation+' --participants \'["TargetPlate"]\' --direction '+actual_direction)
        close(body.volume*1000, 40*math.pi if operation == 'intersect' else 12000-40*math.pi)
        close(neighbor.volume*1000, 12000)
        assert component.features.extrudeFeatures.count == 3
        # The hole must remain through-all when thickness changes.
        parameter = base.extentOne.distance
        run('fusion design parameters set --document ' + q(fixture.name) + ' --changes ' +
            q(json.dumps([{'name':parameter.name,'expected_expression':parameter.expression,'expression':'15 mm'}])))
        close(body.volume*1000, 60*math.pi if operation == 'intersect' else 18000-60*math.pi)
        close(neighbor.volume*1000,12000)
        controller.finish(); controller.restore('face-cut-'+direction)
        close(body.volume*1000,12000)
        assert component.sketches.count == original_sketches
        assert component.features.extrudeFeatures.count == 2
    report['through_all_cut_and_parametric_resize_verified'] = True
    report['participant_isolation_verified'] = True

    controller.begin('projection')
    face = max(run('fusion design bodies topology list --body TargetPlate')['items'],key=lambda f:f['point_mm'][2])
    created = run('fusion design sketches create --support '+q(face['token'])+' --name Perimeter')
    projected = run('fusion design sketches project --sketch Perimeter --entities '+q(json.dumps([face['token']])))
    assert projected['created_count']==4
    perimeter = run('fusion design sketches profiles list --sketch Perimeter')['profiles']
    close(perimeter[0]['area_mm2'],1200)
    plane = component.constructionPlanes.item(0)
    run('fusion design sketches create --support '+q(plane.entityToken)+' --name PlaneSketch')
    run('fusion design sketches create --component FaceBracket --name Source')
    source = run('fusion design sketches circles add --sketch Source --center-x-mm 10 --center-y-mm 10 --radius-mm 2')['circle']
    for name, linked in (('Linked','true'),('Independent','false')):
        run('fusion design sketches create --component FaceBracket --offset-mm 5 --name '+name)
        run('fusion design sketches project --sketch '+name+' --entities '+q(json.dumps([source['token']]))+' --linked '+linked)
    run('fusion design sketches circles edit --sketch Source --entity '+q(source['token'])+' --center-x-mm 10 --center-y-mm 10 --radius-mm 3')
    linked = run('fusion design sketches profiles list --sketch Linked')['profiles']
    independent = run('fusion design sketches profiles list --sketch Independent')['profiles']
    close(linked[0]['area_mm2'],9*math.pi)
    close(independent[0]['area_mm2'],4*math.pi)
    for kind in ('edges','vertices'):
        first = run('fusion design bodies topology list --body TargetPlate --kind '+kind+' --limit 2')
        assert len(first['items']) == 2 and first['next_offset'] == 2
    controller.finish(); controller.restore('projection')
    assert component.sketches.count == original_sketches
    close(body.volume*1000,12000)
    controller.close()
    moved_transform = adsk.core.Matrix3D.create()
    moved_transform.translation = adsk.core.Vector3D.create(5,2,1)
    moved_occurrence = design.rootComponent.occurrences.addNewComponent(moved_transform)
    moved_component = moved_occurrence.component
    moved_component.name = 'MovedBracket'
    _, moved_body = box(moved_component, 0, 'MovedTarget')
    controller = FusionUndo()
    controller.begin('moved-component')
    assert abs(moved_occurrence.transform2.translation.x - 5) < 1e-6
    face = max(run('fusion design bodies topology list --body MovedTarget')['items'],key=lambda f:f['point_mm'][2])
    created = run('fusion design sketches create --support '+q(face['token'])+' --name MovedFace')
    close(created['frame']['origin_mm'][2], 10)
    run('fusion design sketches project --sketch MovedFace --entities '+q(json.dumps([face['token']])))
    command = 'fusion design features extrude --sketch MovedFace --extent through-all --operation cut --participants \'["MovedTarget"]\' --direction negative'
    handler,args,_ = commands.prepare({'command':command})
    try:
        controller.execute(_TOOL_MAP[handler], args)
        raise AssertionError('Moved component through-all unexpectedly accepted')
    except ValueError as exc:
        assert 'moved or rotated' in str(exc)
        report['results'].append({'command':command,'passed':False,'blocker_matched':True,
            'outcome':'capability_blocked','error':str(exc)})
    controller.finish(); controller.restore('moved-component')
    close(moved_body.volume*1000,12000)
    assert moved_component.sketches.count == 1
    report['moved_component_support_projection_and_cut_refusal_verified'] = True
    report.update(linked_and_independent_projection_verified=True, native_undo_verified=True, passed=True)
except Exception:
    report['error'] = traceback.format_exc()
finally:
    cleanup=[]
    if controller: cleanup.append(controller.close)
    if fixture and fixture.isValid: cleanup.append(lambda:fixture.close(False))
    if original and original.isValid: cleanup.append(original.activate)
    if workspace: cleanup.append(workspace.activate)
    for action in cleanup:
        try: action()
        except Exception:
            report['passed']=False
            report.setdefault('cleanup_errors',[]).append(traceback.format_exc())
    try:
        ui.activeSelections.clear()
        for entity in selections:
            if entity.isValid: ui.activeSelections.add(entity)
        assert original.isValid and app.activeDocument == original and ui.activeWorkspace.id == workspace.id
        report['original_context_restored']=True
    except Exception:
        report['passed']=False
        report.setdefault('cleanup_errors',[]).append(traceback.format_exc())
    Path('/tmp/cadbot-face-modeling-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Face modeling gate:', report['passed'],report.get('error',''))
