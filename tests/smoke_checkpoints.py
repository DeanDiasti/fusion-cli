"""Live SDK bounded fork check. Only synthetic chat text; no Fusion data."""
import os,sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from http.server import ThreadingHTTPServer
from smoke_chat import FixtureHandler
from openai_codex.generated.v2_all import ListMcpServerStatusResponse
server=ThreadingHTTPServer(('127.0.0.1',0),FixtureHandler)
threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='cadbot-restore-fixture-') as folder:
 os.environ.update(CADBOT_PROJECT=folder,CADBOT_HISTORY_DIR=folder+'/history',CADBOT_BRIDGE_URL='http://127.0.0.1:'+str(server.server_port))
 import palette_worker
 events=[]
 palette_worker.emit=lambda kind,**data:events.append({'kind':kind,**data})
 worker=palette_worker.Worker()
 try:
  worker.run_turn({'text':'Synthetic conversation test. Reply only FIRST. Do not use tools.'})
  worker.run_turn({'text':'Synthetic conversation test. Reply only SECOND. Do not use tools.'})
  assert not any(e['kind']=='error' for e in events),events
  original=worker.thread
  users=[e for e in worker.history.events(worker.conversation) if e['kind']=='user']
  assert users[1]['previous_turn']
  events.clear()
  worker.restore_message({'id':users[1]['id'],'mode':'conversation'})
  assert not any(e['kind']=='error' for e in events), events
  assert len(worker.thread.read(include_turns=True).thread.turns)==1
  assert len(original.read(include_turns=True).thread.turns)==2
  print('PASS: native SDK bounded fork, original chat preserved, only earlier turn in restored model context')
 finally:
  worker.close();server.shutdown()
