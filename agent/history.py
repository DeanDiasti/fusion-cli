"""CadBot-owned conversation records, stored outside the replaceable add-in."""
import json
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone


class History:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('CADBOT_HISTORY_DIR', str(Path.home() / 'Library/Application Support/CadBot/conversations')))
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, key):
        # IDs are generated here, never arbitrary paths from HTML.
        uuid.UUID(key)
        return self.root / key

    def create(self, thread_id, command):
        key = str(uuid.uuid4())
        folder = self.folder(key)
        folder.mkdir()
        self.save(key, {'id': key, 'thread_id': thread_id,
                       'title': (command.get('text') or 'Attached references')[:80],
                       'model': command.get('model', ''), 'effort': command.get('effort', '')})
        return key

    def save(self, key, record):
        record['updated'] = datetime.now(timezone.utc).isoformat()
        path = self.folder(key) / 'metadata.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record), encoding='utf-8')
        temporary.replace(path)

    def read(self, key):
        return json.loads((self.folder(key) / 'metadata.json').read_text(encoding='utf-8'))

    def append(self, key, event):
        with (self.folder(key) / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + '\n')

    def events(self, key):
        path = self.folder(key) / 'events.jsonl'
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    yield json.loads(line)
                except ValueError:
                    continue  # Preserve earlier events after an interrupted write.

    def list(self):
        records = []
        for path in self.root.glob('*/metadata.json'):
            try:
                records.append(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                continue
        return sorted(records, key=lambda item: item.get('updated', ''), reverse=True)
