"""Run in Fusion after reinstall/restart; creates only an unsaved disposable design.

Exercises CLI parsing, typed handlers and native checkpoint undo, not HTTP.
Writes /tmp/cadbot-design-sketch-curves-smoke.json with geometry and cleanup evidence.
"""
import json
import math
from pathlib import Path
import shlex
import sys
import traceback

import adsk.core
import adsk.fusion

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'fusion_addin' / 'CadBot'))
from bridge import commands
from bridge.build import BUILD
from bridge.fusion_undo import FusionUndo
from tools.registry import _TOOL_MAP


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    original_document, original_workspace = app.activeDocument, ui.activeWorkspace
    selections = [ui.activeSelections.item(i).entity for i in range(ui.activeSelections.count)]
    report = {'build': BUILD, 'transport': 'native CLI with checkpoint transactions',
              'passed': False, 'results': []}
    fixture = controller = None

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def execute(command):
        check(app.activeDocument == fixture, 'Fixture is no longer active.')
        row = {'command': command, 'passed': False}
        report['results'].append(row)
        try:
            handler, args, mutates = commands.prepare({'command': command})
            fn = _TOOL_MAP[handler]
            result = controller.execute(fn, args) if mutates else fn(args)
            check('error' not in result, str(result))
            row.update(result=result, passed=True)
            return result
        except Exception:
            row['error'] = traceback.format_exc()
            raise

    try:
        fixture = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        fixture.name = 'CadBot curved sketch disposable fixture'
        ui.workspaces.itemById('FusionSolidEnvironment').activate()
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        # Duplicate sketch names test token routing in a component.
        root.sketches.add(root.xYConstructionPlane).name = 'Outline'
        component = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        outline = component.sketches.add(component.xYConstructionPlane)
        outline.name = 'Outline'
        selector = shlex.quote(outline.entityToken)
        controller = FusionUndo()
        controller.begin('curved-sketch-fixture')

        execute('fusion design sketches arcs add --sketch ' + selector +
                " --points-mm '[[0,0],[10,10],[20,0]]'")
        execute('fusion design sketches lines add --sketch ' + selector +
                ' --x1-mm 20 --y1-mm 0 --x2-mm 0 --y2-mm 0')
        execute('fusion design sketches circles add --sketch ' + selector +
                ' --center-x-mm 40 --center-y-mm 0 --radius-mm 2')
        profiles = execute('fusion design sketches profiles list --sketch ' + selector)['profiles']
        check(len(profiles) == 2, 'Expected semicircle and circle profiles.')
        semicircle = max(profiles, key=lambda p: p['area_mm2'])
        check(math.isclose(semicircle['area_mm2'], 50 * math.pi, rel_tol=.02), 'Incorrect arc profile area.')
        selected = min(profiles, key=lambda p: p['area_mm2'])
        execute('fusion design features extrude --sketch ' + selector +
                ' --profile-index {} --distance-mm 5 --operation new'.format(selected['index']))
        check(component.bRepBodies.count == 1 and root.bRepBodies.count == 0, 'Wrong body owner/count.')
        volume = component.bRepBodies.item(0).volume * 1000
        check(math.isclose(volume, 20 * math.pi, rel_tol=.001), 'Extrude used the wrong profile or units.')
        report['extruded_volume_mm3'] = volume

        created_point = execute('fusion design sketches points add --sketch ' + selector + ' --x-mm 35 --y-mm 5')
        resolved_point = design.findEntityByToken(created_point['point']['token'])[0]
        check(math.isclose(resolved_point.geometry.x * 10, 35) and
              math.isclose(resolved_point.geometry.y * 10, 5), 'Created point has incorrect coordinates.')
        geometry = execute('fusion design sketches geometry list --sketch ' + selector)
        check(any(p['position'] == {'x_mm': 35.0, 'y_mm': 5.0} for p in geometry['points']),
              'Point not found at the requested position.')

        execute('fusion design sketches create --name Spline')
        spline = execute("fusion design sketches splines add --sketch Spline --points-mm '[[0,0],[10,20],[20,0]]'")
        check(not spline['spline']['closed'], 'Open spline was closed.')
        execute('fusion design sketches create --name ClosedSpline')
        execute("fusion design sketches splines add --sketch ClosedSpline --closed true "
                "--points-mm '[[0,0],[10,20],[20,0]]'")
        closed = execute('fusion design sketches profiles list --sketch ClosedSpline')['profiles']
        check(len(closed) == 1 and closed[0]['area_mm2'] > 0, 'Closed spline did not form a profile.')

        execute('fusion design sketches create --name Turn')
        execute('fusion design sketches rectangles add --sketch Turn --x1-mm 10 --y1-mm 10 --x2-mm 20 --y2-mm 20')
        execute('fusion design features revolve --sketch Turn --profile-index 0 --axis X --angle-deg 360')
        check(root.bRepBodies.count == 1, 'Revolve did not create one root body.')
        check(math.isclose(root.bRepBodies.item(0).volume * 1000, 3000 * math.pi, rel_tol=.001),
              'Incorrect revolved volume.')
        controller.finish()
        controller.restore('curved-sketch-fixture')
        check(root.bRepBodies.count == 0 and component.bRepBodies.count == 0,
              'Checkpoint restore left created solids behind.')
        check(outline.sketchCurves.count == 0 and root.sketches.count == 1,
              'Checkpoint restore left created sketch geometry behind.')
        report['undo_verified'] = True
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        # Attempt every cleanup step even if an earlier one fails.
        cleanup = []
        if controller:
            cleanup.append(('controller_closed', controller.close))
        if fixture and fixture.isValid:
            cleanup.append(('fixture_closed', lambda: fixture.close(False)))
        if original_document and original_document.isValid:
            cleanup.append(('original_document_restored', original_document.activate))
        if original_workspace:
            def restore_workspace():
                if ui.activeWorkspace.id != original_workspace.id:
                    original_workspace.activate()
                check(ui.activeWorkspace.id == original_workspace.id, 'Original workspace not active')
            cleanup.append(('original_workspace_restored', restore_workspace))
        def restore_selection():
            ui.activeSelections.clear()
            for entity in selections:
                if entity.isValid:
                    ui.activeSelections.add(entity)
        cleanup.append(('selection_restored', restore_selection))
        for label, action in cleanup:
            try:
                result = action()
                check(result is not False, label + ' was rejected')
                report[label] = True
            except Exception:
                report[label] = False
                report['passed'] = False
                report.setdefault('cleanup_errors', []).append(traceback.format_exc())
        if not report['passed']:
            # A failed geometry assertion or cleanup must not become passing coverage.
            for row in report['results']:
                row['passed'] = False
                row.setdefault('error', report.get('error', 'Fixture cleanup failed.'))
        Path('/tmp/cadbot-design-sketch-curves-smoke.json').write_text(json.dumps(report, indent=2))
        print('CadBot curved sketches: passed=' + str(report['passed']))
