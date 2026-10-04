"""Explicit Fusion application/data operations. Called only on the main thread."""
import os
import time

import adsk.core
import adsk.fusion


def app():
    return adsk.core.Application.get()


def items(collection):
    return [collection.item(i) for i in range(collection.count)]


def unique(collection, selector, key='id'):
    matches = [x for x in collection if str(getattr(x,key)) == selector or x.name == selector]
    if len(matches) != 1:
        raise ValueError('Selector must identify exactly one object; use the ID from list. Matches: '+str(len(matches)))
    return matches[0]


def doc(selector):
    return unique([d for d in items(app().documents) if d.isVisible],selector,'creationId')


def doc_info(d):
    return {'id':d.creationId,'name':d.name,'active':d.isActive,
            'modified':d.isModified,'saved':d.isSaved,
            'file_id':d.dataFile.id if d.dataFile else None}


def project(selector):
    return unique(items(app().data.dataProjects),selector)


def folder(selector):
    # IDs only: scanning arbitrary cloud trees by name can be unbounded.
    result = app().data.findFolderById(selector)
    if result is None:
        raise ValueError('Folder ID not found. Use fusion folders list.')
    return result


def datafile(selector):
    result = app().data.findFileById(selector)
    if result is None:
        raise ValueError('File ID not found. Use fusion files list.')
    return result


def file_info(f):
    return {'id':f.id,'name':f.name,'extension':f.fileExtension,
            'version':f.versionNumber,'complete':f.isComplete,
            'folder':f.parentFolder.id,'project':f.parentProject.id,
            'has_child_references':f.hasChildReferences,
            'has_parent_references':f.hasParentReferences,
            'read_only':f.isReadOnly}


def project_info(p):
    return {'id':p.id,'name':p.name,'root_folder':p.rootFolder.id,
            'hub_id':p.parentHub.id,'hub_name':p.parentHub.name}


def folder_info(f):
    return {'id':f.id,'name':f.name,'project':f.parentProject.id,
            'parent':f.parentFolder.id if f.parentFolder else None,
            'root':f.isRoot,'folder_count':f.dataFolders.count,
            'file_count':f.dataFiles.count}


def _enum(value):
    """Return Fusion enum values in a JSON-safe, stable representation."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def checked(result, operation):
    if not result:
        raise RuntimeError('Fusion rejected '+operation)
    return result


def rename(item,name):
    if not name.strip(): raise ValueError('Name must not be empty')
    item.name=name
    if item.name != name: raise RuntimeError('Rename was not observed; inspect before retrying')


def app_inspect(args):
    from bridge.server import VERSION
    from bridge.build import BUILD, PROTOCOL
    a=app()
    return {'version':VERSION,'protocol':PROTOCOL,'build':BUILD,'fusion_version':a.version,
            'document':doc_info(a.activeDocument) if a.activeDocument else None,
            'workspace':a.userInterface.activeWorkspace.id if a.userInterface.activeWorkspace else None}


def app_capabilities(args):
    from bridge.commands import SPECS, EFFECTS
    from bridge.build import BUILD
    from bridge.coverage import reconcile
    import json
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'bridge'/'coverage.json'
    try:
        report=json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(report, dict) or not isinstance(report.get('commands', []), list):
            raise ValueError('Invalid coverage snapshot')
    except (ValueError, OSError) as exc:
        report={'commands':[], 'coverage_error': str(exc)}
    from bridge.release_policy import RESTRICTIONS
    return {**reconcile(report, SPECS, EFFECTS, BUILD),
            "release_restrictions": {"fusion " + name: reason for name, reason in RESTRICTIONS.items()}}


def app_state(args):
    a=app(); data=a.data
    return {
        'offline':a.isOffLine,
        'has_active_jobs':a.hasActiveJobs,
        'active_document':doc_info(a.activeDocument) if a.activeDocument else None,
        'active_workspace':a.userInterface.activeWorkspace.id if a.userInterface.activeWorkspace else None,
        'active_hub':{'id':data.activeHub.id,'name':data.activeHub.name} if data.activeHub else None,
        'active_project':project_info(data.activeProject) if data.activeProject else None,
        'active_folder':folder_info(data.activeFolder) if data.activeFolder else None,
        'open_document_count':len([d for d in items(a.documents) if d.isVisible]),
    }


def app_diagnostics(args):
    a=app(); data=a.data
    checks={
        'application_valid':bool(a.isValid),
        'online':not a.isOffLine,
        'startup_complete':bool(a.isStartupComplete),
        'data_valid':bool(data.isValid),
        'active_hub_available':data.activeHub is not None,
        'active_project_available':data.activeProject is not None,
        'active_workspace_available':a.userInterface.activeWorkspace is not None,
    }
    return {'ok':all(checks.values()),'checks':checks,'fusion_version':a.version,
            'last_error':a.getLastError()}


def app_preferences(args):
    prefs=app().preferences
    general=prefs.generalPreferences
    graphics=prefs.graphicsPreferences
    values=prefs.unitAndValuePreferences
    api=prefs.apiPreferences
    # Deliberately omit proxy host/port and user identifiers. This command is
    # for operational settings, not account or network-secret discovery.
    return {'general':{
                'user_language':_enum(general.userLanguage),
                'automatic_save_on_close':general.isAutomaticSaveOnCloseEnabled,
                'automatic_versioning':general.isAutomaticVersioningEnabled,
                'automatic_versioning_minutes':general.automateVersioningTimeInterval,
                'tooltips':general.areTooltipsShown,
                'command_prompt':general.isCommandPromptShown,
                'active_ui_theme':_enum(general.activeUserInterfaceTheme),
            },
            'graphics':{
                'minimum_fps':graphics.minimumFramesPerSecond,
                'graphics_preset':_enum(graphics.graphicsPreset),
                'animate_view_transitions':graphics.isAnimateViewTransitions,
                'high_resolution_canvas':graphics.isHighResolutionCanvasGraphicsEnabled,
            },
            'units':{
                'general_precision':values.generalPrecision,
                'angular_precision':values.angularPrecision,
                'period_decimal_point':values.isPeriodDecimalPoint,
                'trailing_zeros_hidden':values.areTrailingZerosHidden,
            },
            'api':{
                'default_script_language':_enum(api.defaultScriptLanguage),
                'default_addin_language':_enum(api.defaultAddInLanguage),
                'developer_tools_enabled':api.isDeveloperToolsEnabled,
                'debugging_port':api.debuggingPort,
            }}


def workspace_list(args):
    return {'workspaces':[{'id':w.id,'name':w.name,'active':w.isActive}
                          for w in items(app().userInterface.workspaces)]}


def workspace_activate(args):
    w=unique(items(app().userInterface.workspaces),args['workspace'])
    if not w.isActive:
        checked(w.activate(),'workspace activation')
    if app().userInterface.activeWorkspace.id != w.id:
        raise RuntimeError('Workspace activation was not observed')
    return {'workspace':w.id}


def documents_list(args):
    return {'documents':[doc_info(d) for d in items(app().documents) if d.isVisible]}


def documents_inspect(args):
    return doc_info(doc(args['document']))


def documents_create(args):
    d=checked(app().documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType),'document creation')
    if args.get('name'): d.name=args['name']
    return doc_info(d)


def documents_activate(args):
    d=doc(args['document'])
    checked(d.activate(),'document activation')
    return doc_info(d)


def documents_close(args):
    d=doc(args['document'])
    if d.isModified and not args.get('discard_changes'):
        raise ValueError('Document has unsaved changes. Save first or explicitly use --discard-changes.')
    identity=d.creationId
    checked(d.close(False),'document close')
    return {'closed':identity}


def documents_save(args):
    d=doc(args['document'])
    if not d.isSaved: raise ValueError('Use documents save-as for an unsaved document.')
    checked(d.save(args.get('description','CadBot save')),'save')
    return {'document':doc_info(d),'cloud_complete':d.dataFile.isComplete}


def documents_save_as(args):
    d=doc(args['document'])
    checked(d.saveAs(args['name'],folder(args['folder']),args.get('description',''),'') ,'save-as')
    return {'document':doc_info(d),'cloud_complete':d.dataFile.isComplete if d.dataFile else False,
            'next':'Use the returned document ID; first save can change it. Inspect files after cloud completion.'}


def documents_open(args):
    return doc_info(checked(app().documents.open(datafile(args['file'])),'open'))


def _local_input(path):
    result=os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(result):
        raise ValueError('Input file does not exist: '+result)
    return result


def _local_output(path,extension):
    result=os.path.abspath(os.path.expanduser(path))
    if not result.lower().endswith('.'+extension):
        raise ValueError('Output path must end in .'+extension)
    parent=os.path.dirname(result)
    if not os.path.isdir(parent):
        raise ValueError('Output directory does not exist: '+parent)
    return result


def documents_import(args):
    path=_local_input(args['path'])
    fmt=args.get('format') or os.path.splitext(path)[1].lstrip('.').lower()
    aliases={'stp':'step','f3d':'fusion_archive'}
    fmt=aliases.get(fmt,fmt)
    creators={
        'step':'createSTEPImportOptions','iges':'createIGESImportOptions',
        'sat':'createSATImportOptions','smt':'createSMTImportOptions',
        'fusion_archive':'createFusionArchiveImportOptions',
    }
    if fmt not in creators:
        raise ValueError('Unsupported import format. Use f3d, step/stp, iges, sat, or smt.')
    manager=app().importManager
    options=getattr(manager,creators[fmt])(path)
    imported=checked(manager.importToNewDocument(options),'document import')
    return {'document':doc_info(imported),'source':path,'format':fmt}


def documents_export(args):
    d=doc(args['document'])
    design=adsk.fusion.Design.cast(d.products.itemByProductType('DesignProductType'))
    if design is None:
        raise ValueError('Document does not contain a Fusion Design product.')
    fmt='fusion_archive' if args['format']=='f3d' else args['format']
    extension={'fusion_archive':'f3d'}.get(fmt,fmt)
    path=_local_output(args['path'],extension)
    manager=design.exportManager
    creators={
        'fusion_archive':'createFusionArchiveExportOptions',
        'step':'createSTEPExportOptions','iges':'createIGESExportOptions',
        'sat':'createSATExportOptions','smt':'createSMTExportOptions',
    }
    if fmt=='stl':
        options=manager.createSTLExportOptions(design.rootComponent,path)
        options.sendToPrintUtility=False
    else:
        options=getattr(manager,creators[fmt])(path)
    checked(manager.execute(options),'document export')
    if not os.path.isfile(path) or os.path.getsize(path)==0:
        raise RuntimeError('Fusion reported export success but no nonempty output file was observed')
    return {'document':d.creationId,'path':path,'format':fmt,
            'bytes':os.path.getsize(path)}


def projects_list(args):
    return {'projects':[project_info(p) for p in items(app().data.dataProjects)]}


def projects_inspect(args):
    return project_info(project(args['project']))


def projects_create(args):
    p=checked(app().data.dataProjects.add(args['name']),'project creation')
    return {'id':p.id,'name':p.name,'root_folder':p.rootFolder.id}


def projects_rename(args):
    p=project(args['project']); rename(p,args['name'])
    return {'id':p.id,'name':p.name}


def projects_delete(args):
    # DataProject has no deleteMe (or equivalent) in Fusion 2705.1.15. Keep
    # the typed command so callers receive the real boundary instead of being
    # tempted to automate private text commands or the web UI.
    raise RuntimeError('Installed Fusion API does not expose project deletion. Delete the project in Fusion Team.')


def folders_list(args):
    p=project(args['project'])
    f=folder(args['folder']) if args.get('folder') else p.rootFolder
    if f.parentProject.id != p.id: raise ValueError('Folder belongs to a different project')
    return {'parent':f.id,'folders':[{'id':x.id,'name':x.name} for x in items(f.dataFolders)]}


def folders_inspect(args):
    return folder_info(folder(args['folder']))


def folders_create(args):
    f=checked(folder(args['folder']).dataFolders.add(args['name']),'folder creation')
    return {'id':f.id,'name':f.name}


def folders_rename(args):
    f=folder(args['folder']); rename(f,args['name'])
    return {'id':f.id,'name':f.name}


def folders_delete(args):
    f=folder(args['folder'])
    if f.isRoot: raise ValueError('Project root folders cannot be deleted')
    if (f.dataFolders.count or f.dataFiles.count) and not args.get('recursive'):
        raise ValueError('Folder is not empty. Delete its contents first or explicitly use --recursive.')
    identity=f.id
    checked(f.deleteMe(),'folder deletion')
    return {'deleted':identity}


def _walk_folders(root,limit):
    pending=[root]; result=[]
    while pending:
        current=pending.pop(0)
        result.append(current)
        if len(result)>limit:
            raise RuntimeError('Folder scan exceeded --limit; narrow the project or increase the limit.')
        pending.extend(items(current.dataFolders))
    return result


def folders_search(args):
    query=args['query'].casefold(); limit=args.get('limit',500)
    if not query: raise ValueError('Query must not be empty')
    matches=[]
    for f in _walk_folders(project(args['project']).rootFolder,limit):
        if query in f.name.casefold(): matches.append(folder_info(f))
    return {'query':args['query'],'folders':matches,'scanned_limit':limit}


def files_list(args):
    return {'files':[file_info(f) for f in items(folder(args['folder']).dataFiles)]}


def files_search(args):
    query=args['query'].casefold(); limit=args.get('limit',500)
    if not query: raise ValueError('Query must not be empty')
    matches=[]
    for f in _walk_folders(project(args['project']).rootFolder,limit):
        matches.extend(file_info(x) for x in items(f.dataFiles) if query in x.name.casefold())
    return {'query':args['query'],'files':matches,'scanned_limit':limit}


def files_inspect(args):
    f=datafile(args['file'])
    return {**file_info(f),'versions':[file_info(v) for v in items(f.versions)],
            'children':[file_info(v) for v in items(f.childReferences)],
            'parents':[file_info(v) for v in items(f.parentReferences)]}


def files_rename(args):
    f=datafile(args['file']); rename(f,args['name'])
    return file_info(f)


def files_copy(args):
    f=datafile(args['file'])
    if f.hasChildReferences and not args.get('include_references'):
        raise ValueError('Reference-aware copying requires --include-references to avoid retaining source dependencies.')
    if args.get('include_references'):
        from . import jobs
        if len(jobs._jobs)>=32: raise RuntimeError('Job capacity reached before starting copy')
        if not hasattr(f,'createCopyDesignFileInput'):
            raise RuntimeError('This Fusion version does not expose reference-aware copy')
        options=checked(f.createCopyDesignFileInput(folder(args['folder'])),'copy input')
        options.isCopyReferencedExternalComponents=True
        future=checked(f.copyWithInput(options),'reference-aware copy')
        return {**jobs.register(future,'reference-aware copy'),
                'warnings':['Uses the installed Fusion preview copy API; verify copied references before editing.']}
    copied=checked(f.copy(folder(args['folder'])),'file copy')
    return {'file':file_info(copied),'cloud_complete':copied.isComplete}


def files_move(args):
    f=datafile(args['file'])
    target=folder(args['folder'])
    checked(f.move(target),'file move')
    deadline=time.monotonic()+15
    current=f
    while time.monotonic()<deadline:
        current=app().data.findFileById(f.id) or current
        if current.parentFolder.id == target.id:
            return {'file':file_info(current),'destination':target.id}
        adsk.doEvents()
        time.sleep(.1)
    raise RuntimeError('Move was accepted but not observed within 15 seconds; inspect the file before retrying')


def files_delete(args):
    f=datafile(args['file'])
    if f.hasParentReferences and not args.get('allow_referenced'):
        raise ValueError('File is referenced by another design. Use --allow-referenced only after inspecting parent references.')
    identity=f.id
    checked(f.deleteMe(),'file deletion')
    return {'deleted':identity}


def files_upload(args):
    from . import jobs
    path=_local_input(args['path'])
    future=checked(folder(args['folder']).uploadFile(path),'file upload')
    return {**jobs.register(future,'file upload'),'source':path}


def files_download(args):
    f=datafile(args['file'])
    if f.fileExtension.lower() in ('f3d','f3z'):
        raise ValueError('Fusion design files cannot be downloaded with DataFile.download; use documents export.')
    path=os.path.abspath(os.path.expanduser(args['path']))
    parent=path if os.path.isdir(path) else os.path.dirname(path)
    if not os.path.isdir(parent):
        raise ValueError('Download directory does not exist: '+parent)
    checked(f.download(path,None),'file download')
    observed=path if os.path.isfile(path) else os.path.join(path,f.name+'.'+f.fileExtension)
    if not os.path.isfile(observed) or os.path.getsize(observed)==0:
        raise RuntimeError('Fusion reported download success but no nonempty output file was observed')
    return {'file':f.id,'path':observed,'bytes':os.path.getsize(observed)}
