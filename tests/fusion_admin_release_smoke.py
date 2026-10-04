"""Run in Fusion's Python console: full Administration gate on disposable data.

The script creates UUID-named local/cloud fixtures, never edits an existing
cloud design, deletes every file/folder it creates, and restores the original
document/workspace. Fusion's public API cannot delete projects, so one empty,
clearly named test project is retained and recorded in the report.
"""
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import time
import traceback
import types
import uuid

import adsk.core
import adsk.fusion

ROOT=Path(__file__).resolve().parents[1]/'fusion_addin'/'CadBot'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,str(path)); module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module; spec.loader.exec_module(module); return module

package=types.ModuleType('cadbot_admin_stage'); package.__path__=[str(ROOT/'tools')]
sys.modules[package.__name__]=package
jobs=load('cadbot_admin_stage.jobs',ROOT/'tools'/'jobs.py')
admin=load('cadbot_admin_stage.admin',ROOT/'tools'/'admin.py')
grammar=load('cadbot_admin_commands',ROOT/'bridge'/'commands.py')

report={'transport':'native source CLI dispatch','results':[]}
JOB_HANDLERS={
    'jobs_list': jobs.list_jobs,
    'jobs_inspect': jobs.inspect,
    'jobs_cancel': jobs.cancel,
    'jobs_forget': jobs.forget,
}
def run(parts):
    command=shlex.join(['fusion',*parts]); row={'command':command}
    try:
        handler,args,_=grammar.prepare({'command':command})
        function=JOB_HANDLERS.get(handler, getattr(admin,handler,None))
        if function is None: raise RuntimeError('No live-gate handler for '+handler)
        result=function(args)
        row.update(passed=True,result=result); return result
    except Exception:
        row.update(passed=False,error=traceback.format_exc()); raise
    finally:
        report['results'].append(row)

def expected_blocker(parts,contains):
    command=shlex.join(['fusion',*parts]); row={'command':command}
    try:
        handler,args,_=grammar.prepare({'command':command})
        getattr(admin,handler)(args)
        raise AssertionError('Expected capability blocker was not raised')
    except RuntimeError as exc:
        if contains not in str(exc): raise
        row.update(passed=True,expected_blocker=str(exc),blocker_matched=True,outcome="capability_blocked")
    except Exception:
        row.update(passed=False,error=traceback.format_exc()); raise
    finally:
        report['results'].append(row)

def wait_job(key,seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=run(['app','jobs','inspect','--job',key])
        if result['status']!='pending': return result
        adsk.doEvents(); time.sleep(.1)
    raise RuntimeError('Cloud job remained pending after {} seconds'.format(seconds))

app=adsk.core.Application.get(); original=app.activeDocument
original_workspace=app.userInterface.activeWorkspace
original_pristine = bool(original and not original.isModified and not original.isSaved
                         and original.name == 'Untitled')
if original_pristine:
    original_design = adsk.fusion.Design.cast(original.products.itemByProductType('DesignProductType'))
    original_pristine = bool(original_design and original_design.rootComponent.sketches.count == 0
                            and original_design.rootComponent.bRepBodies.count == 0
                            and original_design.rootComponent.occurrences.count == 0)
fixture_documents=[]; created_files=[]; created_folders=[]
project=None
token=uuid.uuid4().hex[:10]
archive=Path('/tmp/cadbot-admin-'+token+'.f3d')
upload_source=Path('/tmp/cadbot-admin-'+token+'.txt')
download_target=Path('/tmp/cadbot-admin-'+token+'-download.txt')
upload_source.write_text('CadBot Administration disposable fixture\n')
try:
    run(['app','inspect']); run(['app','capabilities']); run(['app','state'])
    run(['app','diagnostics']); run(['app','preferences'])
    workspaces=run(['workspace','list'])['workspaces']
    run(['workspace','activate','--workspace',app.userInterface.activeWorkspace.id])
    run(['documents','list']); run(['projects','list'])

    first=run(['documents','create','--name','CadBot-Admin-Export-'+token]); fixture_documents.append(app.activeDocument)
    first_id=first['id']; run(['documents','inspect','--document',first_id])
    second=run(['documents','create','--name','CadBot-Admin-Activation-'+token]); fixture_documents.append(app.activeDocument)
    run(['documents','activate','--document',first_id])
    run(['documents','export','--document',first_id,'--format','fusion_archive','--path',str(archive)])
    run(['documents','close','--document',second['id'],'--discard-changes']); fixture_documents.pop()
    imported=run(['documents','import','--path',str(archive)]); fixture_documents.append(app.activeDocument)
    imported_id=imported['document']['id']
    run(['documents','inspect','--document',imported_id])
    run(['documents','close','--document',imported_id,'--discard-changes']); fixture_documents.pop()

    project_name='CadBot-Admin-Gate-'+token
    project=run(['projects','create','--name',project_name])
    run(['projects','inspect','--project',project['id']])
    run(['projects','rename','--project',project['id'],'--name',project_name+'-complete'])
    expected_blocker(['projects','delete','--project',project['id']],'does not expose project deletion')
    source=run(['folders','create','--folder',project['root_folder'],'--name','source-'+token]); created_folders.append(source['id'])
    target=run(['folders','create','--folder',project['root_folder'],'--name','target-'+token]); created_folders.append(target['id'])
    run(['folders','inspect','--folder',source['id']])
    run(['folders','rename','--folder',source['id'],'--name','source-'+token+'-renamed'])
    run(['folders','list','--project',project['id']])
    run(['folders','search','--project',project['id'],'--query',token,'--limit','20'])

    upload=run(['files','upload','--folder',source['id'],'--path',str(upload_source)])
    run(['app','jobs','list'])
    uploaded=wait_job(upload['job']); uploaded_id=uploaded['file']['id']; created_files.append(uploaded_id)
    cancellation=run(['app','jobs','cancel','--job',upload['job']])
    assert cancellation['cancelled'] is False and cancellation['cancel_supported'] is False
    run(['app','jobs','forget','--job',upload['job']])
    run(['files','list','--folder',source['id']])
    run(['files','search','--project',project['id'],'--query','cadbot-admin','--limit','20'])
    run(['files','inspect','--file',uploaded_id])
    run(['files','rename','--file',uploaded_id,'--name','uploaded-'+token])
    run(['files','move','--file',uploaded_id,'--folder',target['id']])
    run(['files','download','--file',uploaded_id,'--path',str(download_target)])
    copied=run(['files','copy','--file',uploaded_id,'--folder',source['id']])['file']; created_files.append(copied['id'])

    # Save/save-as/open use a design created by this test. Add one sketch after
    # save-as so documents save verifies a real new version request.
    run(['documents','activate','--document',first_id])
    saved=run(['documents','save-as','--document',first_id,'--folder',source['id'],'--name','saved-'+token])
    deadline=time.monotonic()+90
    while (app.activeDocument.dataFile is None or not app.activeDocument.dataFile.isComplete) and time.monotonic()<deadline:
        adsk.doEvents(); time.sleep(.1)
    if app.activeDocument.dataFile is None or not app.activeDocument.dataFile.isComplete:
        raise RuntimeError('save-as did not complete')
    saved_id=app.activeDocument.dataFile.id; created_files.append(saved_id)
    design=adsk.fusion.Design.cast(app.activeDocument.products.itemByProductType('DesignProductType'))
    design.rootComponent.sketches.add(design.rootComponent.xYConstructionPlane)
    run(['documents','save','--document',app.activeDocument.creationId,'--description','CadBot admin gate version'])
    run(['documents','close','--document',app.activeDocument.creationId]); fixture_documents.remove(app.activeDocument) if app.activeDocument in fixture_documents else None
    reopened=run(['documents','open','--file',saved_id]); fixture_documents.append(app.activeDocument)
    run(['documents','close','--document',reopened['id']]); fixture_documents.pop()

    for file_id in list(reversed(created_files)):
        run(['files','delete','--file',file_id]); created_files.remove(file_id)
    for folder_id in list(reversed(created_folders)):
        run(['folders','delete','--folder',folder_id]); created_folders.remove(folder_id)
    report.update(passed=True,admin_command_count=len({grammar.resolve(shlex.split(row['command'])[1:])[0]
                                                     for row in report['results']}),
                  retained_empty_project=project['id'],
                  retained_empty_project_name=project_name+'-complete',
                  retained_reason='Installed Fusion API exposes no DataProject deletion method.',
                  original_cloud_designs_modified=False)
except Exception:
    report.update(passed=False,error=traceback.format_exc())
finally:
    cleanup_errors=[]
    for document in list(fixture_documents):
        try:
            if document.isValid: document.close(False)
        except Exception: cleanup_errors.append(traceback.format_exc())
    for file_id in list(reversed(created_files)):
        try:
            item=app.data.findFileById(file_id)
            if item: item.deleteMe()
        except Exception: cleanup_errors.append(traceback.format_exc())
    for folder_id in list(reversed(created_folders)):
        try:
            item=app.data.findFolderById(folder_id)
            if item: item.deleteMe()
        except Exception: cleanup_errors.append(traceback.format_exc())
    if original and original.isValid: original.activate()
    if original_workspace: original_workspace.activate()
    report['original_document_restored']=bool(original and original.isValid and app.activeDocument==original)
    report['original_workspace_restored']=bool(original_workspace and app.userInterface.activeWorkspace==original_workspace)
    # Fusion can automatically close its pristine startup placeholder on cloud
    # open. Verify equivalent empty state explicitly; never call it restoration
    # of the original document identity.
    replacement=app.activeDocument
    replacement_design=adsk.fusion.Design.cast(replacement.products.itemByProductType('DesignProductType')) if replacement else None
    report['pristine_placeholder_replaced']=bool(original_pristine and not original.isValid
        and replacement and not replacement.isModified and not replacement.isSaved
        and replacement_design and replacement_design.rootComponent.sketches.count == 0
        and replacement_design.rootComponent.bRepBodies.count == 0
        and replacement_design.rootComponent.occurrences.count == 0)
    report['cleanup_verified']=bool(not cleanup_errors and report['original_workspace_restored']
        and (report['original_document_restored'] or report['pristine_placeholder_replaced']))
    if cleanup_errors: report['cleanup_errors']=cleanup_errors
    report['passed']=bool(report.get('passed') and report['cleanup_verified'])
    for path in (archive,upload_source,download_target):
        try: path.unlink()
        except FileNotFoundError: pass
    output=Path('/tmp/cadbot-admin-release-smoke.json')
    output.write_text(json.dumps(report,indent=2,default=str))
    print('CadBot Administration release gate: '+str(output)+' passed='+str(report.get('passed')))
