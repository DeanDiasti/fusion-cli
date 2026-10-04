"""Run inside Fusion Python with __file__ set to this path.
Creates a separate disposable design; never edits the original document.
The report is written to /tmp/cadbot-undo-integration.json.
"""
import adsk.core,adsk.fusion,json,traceback,importlib.util,sys
from pathlib import Path
base=Path(__file__).resolve().parents[1] / 'fusion_addin/CadBot/bridge'
spec=importlib.util.spec_from_file_location('cadbot_checkpoint_probe',base/'__init__.py',submodule_search_locations=[str(base)])
package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
from cadbot_checkpoint_probe.fusion_undo import FusionUndo
app=adsk.core.Application.get();original=app.activeDocument
report={};controller=None
probe_doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
try:
 d=adsk.fusion.Design.cast(app.activeProduct)
 controller=FusionUndo()
 for number in range(3):
  controller.begin('checkpoint-'+str(number))
  controller.execute(lambda a: d.rootComponent.sketches.add(d.rootComponent.xYConstructionPlane).name,{})
  controller.finish()
 report['before']=d.rootComponent.sketches.count
 report['status']=controller.status()
 report['restore']=controller.restore('checkpoint-1')
 report['after']=d.rootComponent.sketches.count
 report['restore_all']=controller.restore('checkpoint-0')
 report['empty']=d.rootComponent.sketches.count
 controller.begin('checkpoint-new')
 controller.execute(lambda a:d.rootComponent.sketches.add(d.rootComponent.xYConstructionPlane).name,{})
 controller.finish()
 d.rootComponent.sketches.add(d.rootComponent.xYConstructionPlane)
 try:controller.restore('checkpoint-new');report['external']='FAILED: undo was allowed'
 except Exception as e:report['external']=str(e)
 report['after_external']=d.rootComponent.sketches.count
except Exception:report['error']=traceback.format_exc()
finally:
 if controller:controller.close()
 original.activate()
 Path('/tmp/cadbot-undo-integration.json').write_text(json.dumps(report,indent=2))
