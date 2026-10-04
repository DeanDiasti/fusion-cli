#!/usr/bin/env python3
"""Exercise omitted Design CRUD paths in an unsaved disposable document."""
import json, os, shlex, sys, urllib.error, urllib.request
from pathlib import Path

URL=os.environ.get('CADBOT_BRIDGE_URL','http://localhost:8765')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from bridge_cli import TOKEN
REPORT=Path('/tmp/cadbot-design-coverage-http.json'); rows=[]

def post(tool,args):
    req=urllib.request.Request(URL+'/tool',data=json.dumps({'tool':tool,'args':args}).encode(),headers={'Content-Type':'application/json','X-CadBot-Token':TOKEN})
    try:
        with urllib.request.urlopen(req,timeout=180) as response:return json.loads(response.read())
    except urllib.error.HTTPError as exc:return json.loads(exc.read())

def contains(expected,actual):
    if isinstance(expected,dict):return isinstance(actual,dict) and all(k in actual and contains(v,actual[k]) for k,v in expected.items())
    if isinstance(expected,list):return isinstance(actual,list) and len(actual)>=len(expected)
    return expected==actual

def run(command,expected):
    actual=post('fusion',{'command':command}); passed='error' not in actual and contains(expected,actual)
    evidence=dict(actual)
    if 'png_base64' in evidence:evidence['png_base64']='<{} base64 characters>'.format(len(evidence['png_base64']))
    rows.append({'command':command,'expected':expected,'actual':evidence,'passed':passed})
    if not passed:raise RuntimeError(command+': expected '+repr(expected)+', actual '+repr(actual))
    return actual

q=lambda value:shlex.quote(str(value))
jq=lambda value:q(json.dumps(value,separators=(',',':')))
fixture=original_document=original_workspace=None
report={'transport':'installed HTTP CLI dispatch','results':rows,'fixture':'unsaved disposable Fusion design','original_model_touched':False}
try:
    app=run('fusion app inspect',{'status':'completed'}); original_document=(app.get('document') or {}).get('id'); original_workspace=app.get('workspace')
    report['build'] = app['build']
    fixture=run('fusion documents create --name CadBot-Design-Coverage-Fixture',{'status':'completed'})['id']
    run('fusion workspace activate --workspace FusionSolidEnvironment',{'status':'completed'})
    post('_checkpoint',{'action':'begin','id':'design-coverage-smoke'})
    run('fusion design inspect',{'status':'completed'}); run('fusion design assembly instances',{'status':'completed'}); run('fusion design components list',{'components':[{}]})
    first=run('fusion design components create --name CoverageLinkA',{'created':{'component':'CoverageLinkA'}})['created']
    second=run('fusion design components create --name CoverageLinkB',{'created':{'component':'CoverageLinkB'}})['created']
    first_occ,second_occ,first_comp=first['selector'],second['selector'],first['component_selector']
    run('fusion design components inspect --component '+q(first_comp),{'name':'CoverageLinkA'})
    run('fusion design components rename --component '+q(first_comp)+' --name CoverageLinkRenamed',{'after':'CoverageLinkRenamed'})
    run('fusion design occurrences list --query CoverageLink',{'occurrences':[{},{}]})
    extra=run('fusion design occurrences create --component '+q(first_comp),{'created':{'component':'CoverageLinkRenamed'}})['created']
    matrix=[1,0,0,12,0,1,0,0,0,0,1,0,0,0,0,1]
    run('fusion design occurrences transform --occurrence '+q(extra['selector'])+' --matrix '+jq(matrix),{'matrix':matrix})
    run('fusion design occurrences delete --occurrence '+q(extra['selector']),{'deleted':extra['path']})
    joint=run('fusion design joints create --occurrence-one '+q(first_occ)+' --occurrence-two '+q(second_occ)+' --type revolute --axis z --name CoverageJoint',{'created':{'name':'CoverageJoint','type':'revolute'}})['created']; js=joint['selector']
    run('fusion design joints list',{'joints':[{}]})
    run('fusion design joints edit --joint '+q(js)+' --name CoverageJointEdited',{'changed':{'name':{'after':'CoverageJointEdited'}}})
    run('fusion design joints suppress --joint '+q(js),{'current':{'suppressed':True}}); run('fusion design joints unsuppress --joint '+q(js),{'current':{'suppressed':False}})
    run('fusion design joints flip --joint '+q(js),{'current':{'name':'CoverageJointEdited'}}); run('fusion design joints unflip --joint '+q(js),{'current':{'name':'CoverageJointEdited'}})
    run('fusion design joints drive --joint CoverageJointEdited --axis rotation --value 5',{'axis':'rotation','value':5.0})
    run('fusion design joints delete --joint '+q(js),{'deleted':'CoverageJointEdited'})
    run('fusion design components delete --component '+q(first_comp)+' --all-instances',{'deleted_component':'CoverageLinkRenamed'})
    run('fusion design occurrences delete --occurrence '+q(second_occ),{'deleted':second['path']})
    run('fusion design sketches create --name CoverageSketch',{'sketch_name':'CoverageSketch'})
    line=run('fusion design sketches lines add --sketch CoverageSketch --x1-mm 0 --y1-mm 0 --x2-mm 20 --y2-mm 0',{'line':{'construction':False}})['line']
    run('fusion design sketches lines edit --sketch CoverageSketch --entity '+q(line['token'])+' --x1-mm 0 --y1-mm 0 --x2-mm 25 --y2-mm 0',{'line':{'end':{'x_mm':25.0,'y_mm':0.0}}})
    run('fusion design sketches geometry fixed --sketch CoverageSketch --entity '+q(line['token'])+' --fixed true',{'geometry':{'fixed':True}})
    run('fusion design sketches geometry fixed --sketch CoverageSketch --entity '+q(line['token'])+' --fixed false',{'geometry':{'fixed':False}})
    run('fusion design sketches dimension --sketch CoverageSketch --target line_length --value-mm 25 --curve-index 0',{'dimension':'length'})
    dimension=run('fusion design sketches dimensions list --sketch CoverageSketch',{'dimensions':[{}]})['dimensions'][0]
    run('fusion design sketches dimensions set --sketch CoverageSketch --dimension '+q(dimension['token'])+' --expected-expression '+q(dimension['expression'])+" --expression '30 mm'",{'dimension':{'expression':'30 mm'}})
    run('fusion design sketches dimensions delete --sketch CoverageSketch --dimension '+q(dimension['token']),{'deleted':{'token':dimension['token']}})
    run('fusion design sketches geometry delete --sketch CoverageSketch --entity '+q(line['token']),{'deleted':{'token':line['token']}})
    run('fusion design sketches line --sketch CoverageSketch --x1 0 --y1 0 --x2 10 --y2 0',{'curve_count':1}); run('fusion design sketches circle --sketch CoverageSketch --center-x 5 --center-y 5 --radius 2',{'curve_index':1})
    run('fusion design sketches delete --sketch CoverageSketch',{'deleted':'CoverageSketch'})
    run('fusion design sketches create --name CombineA',{'sketch_name':'CombineA'}); run('fusion design sketches rectangles add --sketch CombineA --x1-mm 0 --y1-mm 0 --x2-mm 10 --y2-mm 10',{'lines':[{}, {}, {}, {}]}); run('fusion design features extrude --sketch CombineA --distance-mm 10 --operation new',{'status':'completed'})
    run('fusion design sketches create --name CombineB',{'sketch_name':'CombineB'}); run('fusion design sketches rectangles add --sketch CombineB --x1-mm 5 --y1-mm 0 --x2-mm 15 --y2-mm 10',{'lines':[{}, {}, {}, {}]}); run('fusion design features extrude --sketch CombineB --distance-mm 10 --operation new',{'status':'completed'})
    bodies=run('fusion design bodies list',{'bodies':[{},{}]})['bodies']; run('fusion design bodies combine --target '+q(bodies[0]['token'])+' --tools '+jq([bodies[1]['token']])+' --operation join',{'operation':'join','remaining_bodies':1}); body=run('fusion design bodies list',{'bodies':[{}]})['bodies'][0]['token']
    run('fusion design selection add --entity '+q(body),{'selection_count':1}); run('fusion design selection list',{'selections':[{}]}); run('fusion design selection remove --entity '+q(body),{'selection_count':0})
    run('fusion design construction list',{'origins':[{}, {}, {}, {}, {}, {}, {}]})
    plane=run("fusion design construction planes create-angle --axis origin:x-axis --reference origin:xy-plane --angle '30 deg' --name CoverageAnglePlane",{'kind':'plane','name':'CoverageAnglePlane'})
    renamed=run('fusion design construction rename --construction '+q(plane['token'])+' --name CoverageAngleRenamed --kind plane',{'name':'CoverageAngleRenamed'})
    run('fusion design construction axes create-two-planes --first origin:xy-plane --second origin:yz-plane --name CoverageAxis',{'kind':'axis','name':'CoverageAxis'})
    run('fusion design construction delete --construction '+q(renamed['token'])+' --kind plane',{'deleted':{'name':'CoverageAngleRenamed'}})
    timeline=run('fusion design timeline list',{'items':[{}]})
    if timeline['count']:
        run('fusion design timeline inspect --index 0',{'item':{'index':0}}); run('fusion design timeline beginning',{'marker_position':0}); run('fusion design timeline end',{'marker_position':timeline['count']}); run('fusion design timeline roll --position 0',{'marker_position':0}); run('fusion design timeline end',{'marker_position':timeline['count']})
    run('fusion design timeline groups list',{'groups':[]}); run('fusion design viewport screenshot --path /tmp/cadbot-design-coverage.png',{'path':'/tmp/cadbot-design-coverage.png'})
    # Timeline marker and screenshot operations intentionally invalidate the
    # current message-level Design checkpoint.  Start a fresh message boundary
    # before validating subsequent mutations, matching the palette workflow.
    post('_checkpoint',{'action':'finish'})
    post('_checkpoint',{'action':'begin','id':'design-coverage-reset-smoke'})
    live_bodies=run('fusion design bodies list',{'bodies':[]})['bodies']
    if live_bodies:run('fusion design bodies delete --body '+q(live_bodies[0]['token']),{'deleted':{'name':live_bodies[0]['name']}})
    run('fusion design reset',{'reset':True})
    report['passed']=all(row['passed'] for row in rows)
except Exception as exc:report['passed']=False; report['error']=repr(exc)
finally:
    try:post('_checkpoint',{'action':'finish'})
    except Exception:pass
    if fixture:post('fusion',{'command':'fusion documents close --document '+q(fixture)+' --discard-changes'})
    if original_document:post('fusion',{'command':'fusion documents activate --document '+q(original_document)})
    if original_workspace:post('fusion',{'command':'fusion workspace activate --workspace '+q(original_workspace)})
    REPORT.write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps({'passed':report.get('passed'),'rows':len(rows),'report':str(REPORT)}))
sys.exit(0 if report.get('passed') else 1)
