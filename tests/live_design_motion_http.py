"""Installed HTTP design/edit/animate/inspect workflow in an unsaved fixture."""
import json
import math
from pathlib import Path
import shlex
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'agent'))
from bridge_cli import call
q=shlex.quote
report={'transport':'installed HTTP CLI dispatch','passed':False,'results':[]}
fixture=original=workspace=None

def run(command):
    result,status=call('fusion',{'command':command});ok=status<400 and 'error' not in result
    report['results'].append({'command':command,'passed':ok,'result':result})
    if not ok:raise RuntimeError(str(result))
    return result

def checkpoint(action,key=None):
    args={'action':action}
    if key:args['id']=key
    result,status=call('_checkpoint',args)
    assert status<400 and 'error' not in result,result
    return result

def close(actual,expected):assert math.isclose(actual,expected,abs_tol=1e-4,rel_tol=1e-5),(actual,expected)

try:
    state=run('fusion app inspect');report['build']=state['build'];original=state['document']['id'];workspace=state['workspace']
    fixture=run('fusion documents create --name CadBot-Design-Motion-HTTP')['id']
    run('fusion workspace activate --workspace FusionSolidEnvironment');checkpoint('begin','motion-http-base')
    occurrences=[]
    for name,x in (('Base',0),('Slider',20)):
        created=run('fusion design components create --name '+name)['created'];occurrences.append(created)
        run('fusion design sketches create --component '+name+' --name '+name+'Box')
        run(f'fusion design sketches rectangles add --sketch {name}Box --x1-mm {x} --y1-mm 0 --x2-mm {x+10} --y2-mm 10')
        run(f'fusion design features extrude --sketch {name}Box --distance-mm 10 --operation new')
    run('fusion design occurrences ground --occurrence '+q(occurrences[0]['selector']))
    run('fusion design joints create --occurrence-one '+q(occurrences[1]['selector'])+' --occurrence-two '+q(occurrences[0]['selector'])+' --type slider --axis x --name Slide')
    run('fusion design sketches create --name EditCircle')
    token=run('fusion design sketches circles add --sketch EditCircle --center-x-mm 0 --center-y-mm 0 --radius-mm 10')['circle']['token']
    run('fusion design sketches create --name Trim')
    line=run('fusion design sketches lines add --sketch Trim --x1-mm 0 --y1-mm 0 --x2-mm 30 --y2-mm 0')['line']['token']
    for x in (10,20):run(f'fusion design sketches lines add --sketch Trim --x1-mm {x} --y1-mm -10 --x2-mm {x} --y2-mm 10')
    checkpoint('finish');checkpoint('begin','motion-http-edit')
    offset=run('fusion design sketches offset --sketch EditCircle --entities '+q(json.dumps([token]))+' --distance-mm -2')
    close(offset['created'][0]['radius_mm'],8)
    result=run('fusion design sketches trim --sketch Trim --entity '+q(line)+' --x-mm 15 --y-mm 0')
    close(sum(c['length_mm'] for c in result['result_curves']),20)
    checkpoint('finish');checkpoint('restore','motion-http-edit')
    geometry=run('fusion design sketches geometry list --sketch EditCircle')['geometry'];assert len(geometry)==1;close(geometry[0]['radius_mm'],10)
    checkpoint('begin','motion-http-inspect')
    initial=run('fusion design joints list')['joints'][0]['slide_mm']
    joint=run('fusion design motion joints list')['joints'][0]['selector']
    entities=['occurrence:'+o['path'] for o in occurrences]
    assert run('fusion design interference check --entities '+q(json.dumps(entities)))['interference_count']==0
    tracks=[{'joint':joint,'axis':'slide','keys':[[0,0],[.4,-15],[.6,-15],[1,0]],'easing':'ease-in-out'}]
    suffix=' --tracks '+q(json.dumps(tracks))
    assert run('fusion design motion check'+suffix+' --samples 5')['pose_restored']
    result=run('fusion design motion inspect'+suffix+' --entities '+q(json.dumps(entities))+' --samples 5')
    assert result['poses_with_interference']>0,result
    for sample in result['samples']:
        if sample['time'] in (.4,.5,.6):close(sample['total_pair_volume_mm3'],500)
    rendered=run('fusion design motion render'+suffix+' --fps 4 --seconds 1 --playback ping-pong')
    assert rendered['pose_restored'] and Path(rendered['path']).is_file()
    assert run('fusion design joints list')['joints'][0]['slide_mm']==initial
    checkpoint('finish');checkpoint('restore','motion-http-inspect')
    report.update(passed=True,geometry_undo_verified=True,collision_volume_verified=True,pose_restored_verified=True,preview_path=rendered['path'])
except Exception as exc:report['error']=str(exc)
finally:
    try:
        checkpoint('finish')
        if fixture:run('fusion documents close --document '+q(fixture)+' --discard-changes')
        if original:run('fusion documents activate --document '+q(original))
        if workspace:run('fusion workspace activate --workspace '+q(workspace))
        final=run('fusion app inspect');assert final['document']['id']==original and final['workspace']==workspace
        report['original_context_restored']=True
    except Exception as exc:report.update(passed=False,cleanup_error=str(exc))
    Path('/tmp/cadbot-design-motion-http.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ('passed','error','cleanup_error')}))
sys.exit(0 if report['passed'] else 1)
