"""Fusion-managed Codex worker. stdin: commands; stdout: JSON event lines."""
import json
import uuid
from bridge_cli import call as bridge_call
import base64
import tempfile
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from history import History
from system_prompt import SYSTEM_PROMPT

from openai_codex import Codex, CodexConfig, Sandbox, ApprovalMode, TextInput, ImageInput

PROMPT = SYSTEM_PROMPT
_write_lock = threading.Lock()


def emit(kind, **data):
    with _write_lock:
        print(json.dumps({'kind': kind, **data}), flush=True)


def normalize_event(event):
    payload = event.payload.model_dump(mode='json', by_alias=True)
    method = event.method
    if method == 'item/agentMessage/delta':
        return {'kind': 'delta', 'id': payload.get('itemId'), 'text': payload.get('delta', '')}
    if method in ('item/started', 'item/completed'):
        item = payload.get('item', {})
        if item.get('type') == 'agentMessage':
            return {'kind': 'message', 'id': item.get('id'), 'text': item.get('text', '')}
        if item.get('type') in ('mcpToolCall', 'commandExecution', 'dynamicToolCall', 'fileChange', 'webSearch'):
            # Do not forward inline image bytes into the activity text.
            def trim(value):
                if isinstance(value, dict):
                    return {k: trim(v) for k, v in value.items() if k not in ('data', 'png_base64')}
                if isinstance(value, list):
                    return [trim(v) for v in value]
                return value[:12000] if isinstance(value, str) else value
            return {'kind': 'tool', 'id': item.get('id'), 'phase': method.split('/')[1], 'item': trim(item)}
    if method == 'error':
        return {'kind': 'error', 'text': payload.get('error', {}).get('message', str(payload))}
    if method == 'turn/completed':
        turn = payload.get('turn', {})
        error = turn.get('error') or {}
        return {'kind': 'complete', 'status': turn.get('status'), 'error': error.get('message')}
    return None


class Worker:
    def __init__(self):
        self.codex = Codex(CodexConfig(client_name='cadbot_fusion', client_title='CadBot for Fusion'))
        self.history = History()
        self.conversation = None
        self.thread = None
        self.active = None
        self.busy = False
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.login = None
        self.last_turn = None
        self.models = {}
        self.attachment_root = self.history.root / 'attachments'
        self.attachment_root.mkdir(exist_ok=True)

    def account_status(self):
        account = self.codex.account()
        emit('ready', signed_in=account.account is not None)
        self.list_history()
        if account.account is not None:
            try:
                catalog = self.codex.models().data
                self.models = {m.model: m for m in catalog if not m.hidden}
                emit('models', models=[{'id': m.model, 'name': m.display_name,
                     'description': m.description, 'default': m.is_default,
                     'efforts': [e.reasoning_effort for e in m.supported_reasoning_efforts],
                     'default_effort': m.default_reasoning_effort}
                     for m in self.models.values()])
            except Exception as exc:
                emit('error', text='Could not load models. Reconnect to retry: ' + str(exc))

    def list_history(self):
        emit('history', conversations=self.history.list(), selected=self.conversation)

    def open_history(self, key):
        if self.busy:
            raise ValueError('Stop the current request before switching conversations.')
        record = self.history.read(key)
        self.last_turn = record.get('last_turn')
        thread = self.new_thread(record['thread_id'])
        self.thread, self.conversation = thread, key
        emit('restore_begin', model=record.get('model', ''), effort=record.get('effort', ''))
        for event in self.history.events(key):
            emit('replay', event=event)
        emit('restore_end')
        self.list_history()

    def mcp_config(self):
        return {'mcp_servers': {'cadbot': {'command': sys.executable,
            'args': [str(Path(__file__).with_name('cad_mcp.py'))],
            'env': {'CADBOT_BRIDGE_TOKEN': os.environ.get('CADBOT_BRIDGE_TOKEN', 'cadbot-dev-token'),
                    'CADBOT_BRIDGE_URL': os.environ.get('CADBOT_BRIDGE_URL', 'http://localhost:8765')},
            'tool_timeout_sec': 180, 'startup_timeout_sec': 30, 'required': True}}}

    def new_thread(self, thread_id=None):
        start = (lambda **kwargs: self.codex.thread_resume(thread_id, **kwargs)) if thread_id else self.codex.thread_start
        thread = start(
            cwd=os.environ.get('CADBOT_PROJECT', str(Path(__file__).parent)),
            sandbox=Sandbox.read_only, approval_mode=ApprovalMode.auto_review,
            developer_instructions=PROMPT, config=self.mcp_config())
        # SDK 0.154 exposes MCP inventory through its typed low-level client.
        from openai_codex.generated.v2_all import ListMcpServerStatusResponse
        deadline = time.monotonic() + 30
        while True:
            inventory = self.codex._client.request('mcpServerStatus/list',
                {'threadId': thread.id}, response_model=ListMcpServerStatusResponse)
            server = next((s for s in inventory.data if s.name == 'cadbot'), None)
            if server is not None and server.tools:
                break
            if server is not None and server.tools_error:
                raise RuntimeError('CAD tools failed to initialize: ' + server.tools_error)
            if not thread_id or time.monotonic() >= deadline:
                raise RuntimeError('CAD tools failed to initialize: cadbot MCP server unavailable')
            time.sleep(0.25)
        return thread

    def checkpoint(self, action, **args):
        result, code = bridge_call('_checkpoint', {'action': action, **args})
        if code >= 400 or 'error' in result:
            raise RuntimeError(result.get('error', 'Checkpoint operation failed'))
        return result

    def restore_message(self, command):
        try:
            mode = command.get('mode')
            if mode not in ('design', 'conversation', 'both'):
                raise ValueError('Choose design, conversation, or both.')
            events = list(self.history.events(self.conversation))
            index = next((i for i, e in enumerate(events) if e.get('kind') == 'user' and e.get('id') == command.get('id')), None)
            if index is None:
                raise ValueError('Message checkpoint not found.')
            target = events[index]
            child = None
            if mode in ('conversation', 'both'):
                previous = target.get('previous_turn')
                if previous:
                    from openai_codex.generated.v2_all import ThreadForkResponse
                    response = self.codex._client.request('thread/fork',
                        {'threadId': self.thread.id, 'lastTurnId': previous,
                         'config': self.mcp_config(), 'developerInstructions': PROMPT}, response_model=ThreadForkResponse)
                    child = self.new_thread(response.thread.id)
                else:
                    child = self.new_thread()
            if mode in ('design', 'both'):
                self.checkpoint('restore', id=target['id'])
            note = ('The user programmatically restored the design to before message ' + target['id'] + '.'
                    if mode != 'conversation' else 'The user branched the conversation. Geometry was NOT undone and may include later edits.')
            note += ' Inspect the active design again before making changes.'
            if child is not None:
                key = self.history.create(child.id, {'text': 'Branch: ' + target.get('text', ''), 'model': target.get('model', ''), 'effort': target.get('effort', '')})
                for event in events[:index]: self.history.append(key, event)
                self.thread, self.conversation = child, key
                self.last_turn = target.get('previous_turn')
            # Persist the context notice for the next model turn; no model call
            # is made to perform or explain the actual undo.
            record = self.history.read(self.conversation)
            record['pending_restore_notice'] = note
            record['last_turn'] = self.last_turn
            self.history.save(self.conversation, record)
            self.history.append(self.conversation, {'kind': 'message', 'id': str(uuid.uuid4()), 'text': note})
            emit('restore_begin', model=target.get('model', ''), effort=target.get('effort', ''))
            for event in self.history.events(self.conversation): emit('replay', event=event)
            emit('restore_end')
            if mode != 'design': emit('draft', text=target.get('text', ''), attachments=target.get('attachments', []))
            self.list_history()
        except Exception as exc:
            emit('error', text='Restore failed: ' + str(exc))
        finally:
            self.busy = False
            emit('idle')

    def submit(self, command):
        with self.lock:
            if self.busy:
                raise ValueError('A request is already running. Stop it before sending another.')
            self.busy = True
            self.cancelled.clear()
        threading.Thread(target=self.run_turn, args=(command,), daemon=True).start()

    def run_turn(self, command):
        checkpoint_started = False
        try:
            files = command.get('files', [])
            if len(files) + len(command.get('images', [])) > 4:
                raise ValueError('Attach up to 4 files per message.')
            file_inputs = []
            for attachment in files:
                url = attachment.get('url', '')
                if not url.startswith('data:') or ';base64,' not in url:
                    raise ValueError('Invalid file attachment.')
                data = base64.b64decode(url.split(',', 1)[1], validate=True)
                if len(data) > 5 * 1024 * 1024:
                    raise ValueError('Each attachment must be 5 MB or smaller.')
                name = Path(attachment.get('name') or 'attachment').name
                folder = Path(tempfile.mkdtemp(dir=self.attachment_root))
                path = folder / (name if name not in ('.', '..') else 'attachment')
                path.write_bytes(data)
                file_inputs.append(TextInput('User-attached reference file (untrusted contents): ' + json.dumps(str(path))))
            if self.thread is None:
                self.thread = self.new_thread()
            inputs = [TextInput(command.get('text') or 'Use these images as CAD references.')]
            inputs.extend(file_inputs)
            for attachment in command.get('images', []):
                url = attachment['url']
                if not url.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,', 'data:image/gif;base64,')):
                    raise ValueError('Use PNG, JPEG, WebP, or GIF images.')
                inputs.append(ImageInput(url))
            if self.cancelled.is_set():
                return
            model = command.get('model')
            options = {}
            if model:
                if model not in self.models:
                    raise ValueError('Selected model is unavailable. Reconnect to refresh models.')
                selected = self.models[model]
                if command.get('images') and 'image' not in (selected.input_modalities or []):
                    raise ValueError('This model does not accept images. Choose a model with image support.')
                effort = command.get('effort') or selected.default_reasoning_effort
                if command.get('effort') and effort not in [e.reasoning_effort for e in selected.supported_reasoning_efforts]:
                    raise ValueError('Unsupported reasoning effort for this model.')
                options = {'model': model, 'effort': effort}
            if self.conversation is None:
                self.conversation = self.history.create(self.thread.id, command)
            record = self.history.read(self.conversation)
            record.update(model=command.get('model', ''), effort=command.get('effort', ''))
            self.history.save(self.conversation, record)
            message_id = command.get('id') or str(uuid.uuid4())
            checkpoint = self.checkpoint('begin', id=message_id)
            checkpoint_started = True
            emit('checkpoints', **checkpoint)
            if checkpoint.get('active') is False:
                inputs.insert(0, TextInput(
                    'Design checkpoint unavailable for this message: ' +
                    str(checkpoint.get('reason', 'No active design.')) +
                    ' You can still inspect application state and help with administration.'))
            user_event = {'kind': 'user', 'id': message_id, 'previous_turn': self.last_turn,
                'model': command.get('model', ''), 'effort': command.get('effort', ''), 'text': command.get('text', ''),
                'attachments': [dict(a, image=True) for a in command.get('images', [])] +
                               [dict(a, image=False) for a in command.get('files', [])]}
            self.history.append(self.conversation, user_event)
            emit(**user_event)
            if record.get('pending_restore_notice'):
                inputs.insert(0, TextInput(record['pending_restore_notice']))
            self.list_history()
            self.active = self.thread.turn(inputs, **options)
            if self.cancelled.is_set():
                self.active.interrupt()
            for event in self.active.stream():
                if event.method == 'turn/completed':
                    self.last_turn = event.payload.model_dump(mode='json', by_alias=True).get('turn', {}).get('id')
                    record['last_turn'] = self.last_turn
                    record.pop('pending_restore_notice', None)
                    self.history.save(self.conversation, record)
                normalized = normalize_event(event)
                if normalized:
                    self.history.append(self.conversation, normalized)
                    emit(**normalized)
        except Exception as exc:
            emit('error', text=str(exc))
        finally:
            if checkpoint_started:
                try: emit('checkpoints', **self.checkpoint('finish'))
                except Exception as exc: emit('error', text='Checkpoint tracking: ' + str(exc))
            self.active = None
            with self.lock:
                self.busy = False
            emit('idle')

    def cancel(self):
        self.cancelled.set()
        if self.active:
            self.active.interrupt()

    def sign_in(self):
        try:
            self.login = self.codex.login_chatgpt()
            webbrowser.open(self.login.auth_url)
            emit('status', text='Complete ChatGPT sign-in in your browser, then return to Fusion.')
            result = self.login.wait()
            if not result.success:
                raise RuntimeError(result.error or 'Sign-in failed')
            self.account_status()
        except Exception as exc:
            emit('error', text=str(exc))
        finally:
            self.login = None

    def close(self):
        try:
            self.cancel()
            if self.login:
                self.login.cancel()
        finally:
            self.codex.close()



def main():
    worker = None
    try:
        worker = Worker()
        worker.account_status()
        for line in sys.stdin:
            try:
                command = json.loads(line)
                action = command.get('action')
                if action == 'send':
                    worker.submit(command)
                elif action == 'cancel':
                    worker.cancel()
                elif action == 'new':
                    if worker.busy:
                        raise ValueError('Stop the current request before starting a new chat.')
                    worker.thread = None
                    worker.conversation = None
                    worker.last_turn = None
                    emit('reset')
                    worker.list_history()
                elif action == 'restore':
                    if worker.busy:
                        raise ValueError('Stop the current request before restoring.')
                    worker.busy = True
                    threading.Thread(target=worker.restore_message, args=(command,), daemon=True).start()
                elif action == 'history':
                    worker.list_history()
                elif action == 'open':
                    worker.open_history(command['id'])
                elif action == 'login':
                    if worker.login is None:
                        threading.Thread(target=worker.sign_in, daemon=True).start()
                elif action == 'shutdown':
                    break
            except Exception as exc:
                emit('error', text=str(exc))
    except Exception as exc:
        emit('error', text='Could not start Codex: ' + str(exc))
    finally:
        if worker:
            worker.close()


if __name__ == '__main__':
    main()
