"""Native source CLI regression with a disposable parametric cube."""
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import types
import traceback
import adsk.core

ROOT=Path(__file__).resolve().parents[1]/'fusion_addin'/'CadBot'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,str(path));m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m);return m
package=types.ModuleType('cadbot_stage_tools');package.__path__=[str(ROOT/'tools')]
sys.modules[package.__name__]=package
sketch=load('cadbot_stage_tools.sketch',ROOT/'tools'/'sketch.py')
features=load('cadbot_stage_tools.features',ROOT/'tools'/'features.py')
inspection=load('cadbot_stage_tools.inspection',ROOT/'tools'/'inspection.py')
admin=load('cadbot_stage_tools.admin',ROOT/'tools'/'admin.py')
grammar=load('cadbot_stage_commands',ROOT/'bridge'/'commands.py')
handlers={name:getattr(module,name) for module,names in [(sketch,['create_sketch','add_rectangle','list_sketches','inspect_sketch','rename_sketch']),
          (features,['extrude','fillet']), (inspection,['measure_body','export_design']),
          (admin,['documents_create','documents_close','workspace_activate'])] for name in names}
report={'transport':'native CLI dispatch','results':[]}
def run(command):
    row={'command':command}
    try:
        h,a,_=grammar.prepare({'command':command});result=handlers[h](a)
        if 'error' in result: raise RuntimeError(str(result['error']))
        row.update(passed=True,result=result);return result
    except Exception:
        row.update(passed=False,error=traceback.format_exc());raise
    finally:report['results'].append(row)
app=adsk.core.Application.get();original=app.activeDocument;workspace=app.userInterface.activeWorkspace
fixture=None
try:
    run('fusion documents create --name CadBot-Design-CLI-fixture');fixture=app.activeDocument
    run('fusion workspace activate --workspace FusionSolidEnvironment')
    run('fusion design sketches create --name Cube')
    run('fusion design sketches rectangle --sketch Cube --x1 0 --y1 0 --x2 20 --y2 20')
    listing=run('fusion design sketches list')
    token=shlex.quote(listing['sketches'][0]['token'])
    details=run('fusion design sketches inspect --sketch '+token)
    assert details['profiles']==1 and len(details['curves'])==4
    run('fusion design sketches rename --sketch '+token+' --name CubeBase')
    run('fusion design features extrude --sketch CubeBase --distance-mm 20 --operation new')
    measure=run('fusion design bodies measure')
    run('fusion design features fillet --radius-mm 2')
    run('fusion design bodies measure')
    run('fusion design export --format step --path /tmp/cadbot-cli-cube.step')
    assert Path('/tmp/cadbot-cli-cube.step').stat().st_size>0
    report['passed']=True
except Exception:
    report['passed']=False;report['error']=traceback.format_exc()
finally:
    if fixture and fixture.isValid:run('fusion documents close --document '+fixture.creationId+' --discard-changes')
    if original and original.isValid:original.activate()
    if workspace:workspace.activate()
    Path('/tmp/cadbot-design-cli-smoke.json').write_text(json.dumps(report,indent=2))
    print('CadBot Design CLI fixture: passed='+str(report.get('passed')))
