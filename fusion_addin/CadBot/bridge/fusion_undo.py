"""Application-controlled, session-only native Fusion undo checkpoints.

Uses Fusion's native PTransaction text commands. These are runtime-specific;
verify both the document marker and a model signature before/after each undo.
"""
import hashlib
import json
import uuid
import adsk.core
import adsk.fusion
from .message_undo import MessageUndo, UndoUnavailable


def _timeline_signature_item(item):
    """Describe timeline rows, including groups with no public API entity."""
    try:
        entity = item.entity
    except Exception:
        entity = None
    entity_type = getattr(entity, 'objectType', None)
    row_type = getattr(item, 'objectType', type(item).__name__)
    return (getattr(item, 'name', ''), str(entity_type or row_type),
            bool(getattr(item, 'isGroup', False)))


def _timeline_signature(timeline):
    """Canonical timeline content independent of group collapse/expand state."""
    groups = []
    collection = timeline.timelineGroups
    for index in range(collection.count):
        group = collection.item(index)
        groups.append((getattr(group, 'name', ''), tuple(
            _timeline_signature_item(group.item(child))
            for child in range(group.count)
        )))
    ungrouped = []
    for index in range(timeline.count):
        item = timeline.item(index)
        if bool(getattr(item, 'isGroup', False)):
            continue
        try:
            parent = item.parentGroup
        except Exception:
            parent = None
        if parent is None:
            ungrouped.append(_timeline_signature_item(item))
    return (tuple(ungrouped), tuple(groups))


class FusionUndo:
    def __init__(self):
        self.app = adsk.core.Application.get()
        self.ledger = None
        self.owned = False
        self.signatures = {}
        self.document_handler = _DocumentChanged(self)
        self.app.documentActivated.add(self.document_handler)
        self.handler = _ExternalCommand(self)
        self.app.userInterface.commandStarting.add(self.handler)

    def close(self):
        self.app.userInterface.commandStarting.remove(self.handler)
        self.app.documentActivated.remove(self.document_handler)
        self.invalidate('CadBot was reloaded.')

    def design(self):
        document = self.app.activeDocument
        if document is None:
            raise UndoUnavailable('Open a Fusion design first.')
        # Animation has a different activeProduct while the owning document
        # still contains the Design product needed for checkpoint signatures.
        design = adsk.fusion.Design.cast(
            document.products.itemByProductType('DesignProductType'))
        if design is None:
            raise UndoUnavailable('Open a Fusion design first.')
        return design

    def document_id(self):
        return self.app.activeDocument.creationId

    def marker(self):
        item = self.design().attributes.itemByName('CadBotUndo', 'head')
        return item.value if item else ''

    def signature(self):
        d = self.design()
        values = [self.document_id(), d.timeline.markerPosition,
                  [(p.name, p.expression) for p in d.allParameters]]
        for c in d.allComponents:
            values.append([c.name, c.revisionId,
                [(b.name, b.revisionId) for b in c.bRepBodies],
                [(s.name, s.revisionId) for s in c.sketches]])
        values.append([(o.fullPathName, o.transform2.asArray()) for o in d.rootComponent.allOccurrences])
        values.append(_timeline_signature(d.timeline))
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def head(self):
        marker = self.marker()
        expected = self.signatures.get(marker)
        if expected is not None and self.signature() != expected:
            self.invalidate('The design changed outside the recorded CadBot transactions.')
            raise UndoUnavailable('The design changed outside the recorded CadBot transactions.')
        return marker

    def invalidate(self, reason):
        if self.ledger:
            self.ledger.invalidate(reason)

    def begin(self, message_id):
        try:
            self.design()
        except UndoUnavailable as exc:
            self.invalidate(str(exc))
            return {'available': [], 'active': False, 'reason': str(exc)}
        # New work may establish a fresh chain after an invalidation.
        if self.ledger is None or self.ledger.reason or self.document_id() != self.ledger.document:
            self.signatures = {self.marker(): self.signature()}
            self.ledger = MessageUndo(self)
        self.ledger.begin(message_id)
        return self.status()

    def finish(self):
        if self.ledger and self.ledger.active:
            if self.ledger.reason:
                self.ledger.active = None
            else:
                self.ledger.finish()
        return self.status()

    def status(self):
        if not self.ledger:
            return {'available': [], 'reason': 'No checkpoints in this Fusion session.'}
        if self.owned:
            # Viewport capture can pump the palette's poll callback. A temporary
            # pose intentionally differs from the committed signature until the
            # transaction aborts; observing it must not invalidate the ledger.
            return {'available': [], 'reason': self.ledger.reason,
                    'active': bool(self.ledger.active), 'busy': True}
        try:
            self.ledger._check()
            self.head()
        except Exception as exc:
            self.invalidate(str(exc))
        return {'available': [] if self.ledger.reason or self.ledger.active else [m.id for m in self.ledger.messages],
                'reason': self.ledger.reason, 'active': bool(self.ledger.active)}

    def text(self, command):
        result = self.app.executeTextCommand(command)
        if str(result).strip() != '1':
            raise RuntimeError(result)
        return result

    def execute(self, fn, args):
        if self.ledger and self.ledger.active and self.ledger.reason:
            raise UndoUnavailable(self.ledger.reason + ' Send a new message to continue.')
        if not self.ledger or not self.ledger.active:
            self.invalidate('A model edit was not associated with a tracked message.')
            return fn(args)
        before = self.head()
        token = str(uuid.uuid4())
        self.owned = True
        started = False
        committing = False
        try:
            self.text('PTransaction.Start CadBotMessageEdit')
            started = True
            result = fn(args)
            self.design().attributes.add('CadBotUndo', 'head', token)
            committing = True
            self.text('PTransaction.Commit')
            started = False
            self.signatures[token] = self.signature()
            self.ledger.committed(before, token)
            return result
        except Exception:
            recovered = False
            if started:
                try:
                    self.text('PTransaction.Abort')
                    # Only a failed tool can recover here. A commit failure has
                    # uncertain stack semantics even if geometry looks equal.
                    if not committing:
                        self.ledger._check()
                        recovered = self.head() == before
                except Exception:
                    pass
            if not recovered:
                self.invalidate('A transaction failed and rollback could not be verified; earlier design checkpoints are unavailable.')
            # Preserve the original tool error so the model can correct its
            # arguments and retry within this message after verified rollback.
            raise
        finally:
            self.owned = False

    def preview(self, fn, args, observe):
        """Always abort transient motion, then verify before exposing its result."""
        if not self.ledger or not self.ledger.active:
            raise UndoUnavailable('Preview requires an active message checkpoint.')
        self.ledger._check()
        before = self.head()
        signature = self.signature()
        pose = observe()
        self.owned = True
        started = False
        failure = None
        result = None
        try:
            self.text('PTransaction.Start CadBotPreview')
            started = True
            try:
                result = fn(args)
            except Exception as exc:
                failure = exc
            # Do not commit a marker or append an undo entry for a preview.
            self.text('PTransaction.Abort')
            started = False
            self.ledger._check()
            if self.marker() != before or self.signature() != signature or observe() != pose:
                raise UndoUnavailable('Preview rollback did not restore the recorded model and joint state.')
        except Exception as exc:
            # An uncertain abort is never retried blindly.
            self.invalidate('Preview rollback could not be verified: ' + str(exc))
            raise UndoUnavailable((str(failure) + '; ' if failure else '') + self.ledger.reason) from exc
        finally:
            self.owned = False
        if failure:
            raise RuntimeError(str(failure) + '; temporary transaction rolled back and model/joint state verified.') from failure
        return {**result, 'pose_restored': True,
                'restoration': {'method': 'transaction_abort', 'verified': True,
                                'checks': ['document/model signature', 'undo marker', 'all observed joint axes']}}

    def undo(self, expected_head):
        if self.head() != expected_head:
            raise UndoUnavailable('Undo boundary changed.')
        self.owned = True
        try:
            self.text('PTransaction.Undo')
        finally:
            self.owned = False

    def restore(self, message_id):
        if not self.ledger:
            raise UndoUnavailable('This checkpoint belongs to an earlier Fusion session.')
        return self.ledger.restore_before(message_id)


class _ExternalCommand(adsk.core.ApplicationCommandEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
    def notify(self, args):
        # Conservative: even non-editing external commands invalidate the chain.
        # A UI whitelist must be verified before relaxing this rule.
        if not self.owner.owned:
            self.owner.invalidate('A Fusion command ran outside CadBot. Earlier design checkpoints are unavailable.')


class _DocumentChanged(adsk.core.DocumentEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
    def notify(self, args):
        self.owner.invalidate('The active Fusion document changed.')
