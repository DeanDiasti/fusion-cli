"""Installed HTTP workflow for planar support, projection, targeted cuts, and undo."""
import json
import math
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cli'))
from bridge_cli import call
q = shlex.quote
report = {'transport':'installed HTTP CLI dispatch','passed':False,'results':[]}
fixture = original = workspace = None

def run(command):
    result,status = call('fusion',{'command':command})
    ok = status < 400 and 'error' not in result
    report['results'].append({'command':command,'passed':ok,'result':result})
    if not ok: raise RuntimeError(str(result))
    return result

def checkpoint(action, key=None):
    args={'action':action}
    if key: args['id']=key
    result,status=call('_checkpoint',args)
    assert status<400 and 'error' not in result,result
    return result

def volume(name, expected):
    result=run('fusion design bodies inspect --body '+name)
    actual=result['volume_cm3']*1000
    assert math.isclose(actual,expected,rel_tol=1e-5),(actual,expected)

try:
    state=run('fusion app inspect');report['build']=state['build']
    original=state['document']['id'];workspace=state['workspace']
    fixture=run('fusion documents create --name CadBot-Face-HTTP-Fixture')['id']
    run('fusion workspace activate --workspace FusionSolidEnvironment')
    checkpoint('begin','face-http-base')
    for name,z in (('Plate',0),('Neighbor',20)):
        run('fusion design sketches create --name '+name+'Base --offset-mm '+str(z))
        run('fusion design sketches rectangles add --sketch '+name+'Base --x1-mm 0 --y1-mm 0 --x2-mm 40 --y2-mm 30')
        result=run('fusion design features extrude --sketch '+name+'Base --distance-mm 10 --operation new')
        run('fusion design bodies rename --body '+q(result['body'])+' --name '+name)
    checkpoint('finish')
    checkpoint('begin','face-http-cut')
    face=max(run('fusion design bodies topology list --body Plate')['items'],key=lambda f:f['point_mm'][2])
    run('fusion design sketches create --support '+q(face['token'])+' --name Rim')
    run('fusion design sketches project --sketch Rim --entities '+q(json.dumps([face['token']])))
    profiles=run('fusion design sketches profiles list --sketch Rim')['profiles']
    assert math.isclose(profiles[0]['area_mm2'],1200,rel_tol=1e-5)
    created=run('fusion design sketches create --support '+q(face['token'])+' --name Holes')
    frame=created['frame'];delta=[v-o for v,o in zip([20,15,10],frame['origin_mm'])]
    x=sum(a*b for a,b in zip(delta,frame['x_axis']));y=sum(a*b for a,b in zip(delta,frame['y_axis']))
    run('fusion design sketches circles add --sketch Holes --center-x-mm {} --center-y-mm {} --radius-mm 2'.format(x,y))
    direction='negative' if frame['normal'][2]>0 else 'positive'
    run('fusion design features extrude --sketch Holes --extent through-all --operation cut --participants \'["Plate"]\' --direction '+direction)
    volume('Plate',12000-40*math.pi);volume('Neighbor',12000)
    checkpoint('finish');checkpoint('restore','face-http-cut')
    volume('Plate',12000);volume('Neighbor',12000)
    names={s['name'] for s in run('fusion design sketches list')['sketches']}
    assert names=={'PlateBase','NeighborBase'},names
    report.update(passed=True,undo_verified=True,participant_isolation_verified=True)
except Exception as exc:
    report['error']=str(exc)
finally:
    try:
        checkpoint('finish')
        if fixture: run('fusion documents close --document '+q(fixture)+' --discard-changes')
        if original: run('fusion documents activate --document '+q(original))
        if workspace: run('fusion workspace activate --workspace '+q(workspace))
        final=run('fusion app inspect')
        assert final['document']['id']==original and final['workspace']==workspace
        report['original_context_restored']=True
    except Exception as exc:
        report.update(passed=False,cleanup_error=str(exc))
    Path('/tmp/cadbot-face-modeling-http.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'error':report.get('error'),'cleanup_error':report.get('cleanup_error')}))
sys.exit(0 if report['passed'] else 1)
