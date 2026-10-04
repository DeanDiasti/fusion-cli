"""
Main-thread dispatch for the CadBot bridge.

Fusion's adsk API may only be called from Fusion's main thread. The HTTP
server runs on a background thread, so every request is handed to this
Dispatcher, which posts a Fusion custom event, executes the queued handler
on the main thread, and copies the result back to the waiting HTTP thread.
"""

import queue
import threading
import traceback
from pathlib import Path

import adsk.core

_CUSTOM_EVENT_ID = "CadBotDispatchEvent"
_CALL_TIMEOUT_SECONDS = 120.0


class Dispatcher:
    """Relays callable work onto Fusion's main thread and returns results."""

    def __init__(self):
        self._queue = queue.Queue()
        self._app = adsk.core.Application.get()
        self._ui = self._app.userInterface
        self._custom_event = None
        self._running = False
        self._handler = _DispatchHandler(self)
        self._pump = None
        self._pump_handler = _HTMLDispatchHandler(self)

    def start(self):
        self._custom_event = self._app.registerCustomEvent(_CUSTOM_EVENT_ID)
        if self._custom_event is None:
            raise RuntimeError('Fusion could not register the CLI dispatch event. Stop the old bridge before restarting.')
        self._custom_event.add(self._handler)
        try:
            # Fusion 2705.1.15 can register a custom event yet reject every
            # fireCustomEvent call. A hidden local HTML callback provides an
            # independent, main-thread wakeup; it exposes no commands or UI.
            self._pump = self._ui.palettes.add(
                'FusionCliDispatchPump', 'Fusion CLI dispatch',
                Path(__file__).with_name('dispatch.html').as_uri(),
                False, False, False, 1, 1)
            if self._pump is None or not self._pump.incomingFromHTML.add(self._pump_handler):
                raise RuntimeError('Fusion could not start the CLI dispatch callback.')
            self._running = True
        except Exception:
            self.stop()
            raise

    def stop(self):
        self._running = False
        while True:
            try:
                self._queue.get_nowait().cancel("CadBot dispatcher is stopped")
            except queue.Empty:
                break
        pump, event = self._pump, self._custom_event
        self._pump = self._custom_event = None
        try:
            if pump is not None and pump.isValid:
                try:
                    pump.incomingFromHTML.remove(self._pump_handler)
                finally:
                    pump.deleteMe()
        finally:
            if event is not None:
                try:
                    event.remove(self._handler)
                finally:
                    self._app.unregisterCustomEvent(_CUSTOM_EVENT_ID)

    def call(self, fn, *args, **kwargs):
        """Run fn on Fusion's main thread and return (ok, result_or_error)."""
        if not self._running:
            return False, {"error": "CadBot dispatcher is stopped"}
        work = _WorkItem(lambda: fn(*args, **kwargs))
        self._queue.put(work)
        try:
            if not self._app.fireCustomEvent(_CUSTOM_EVENT_ID) and self._pump is None:
                work.cancel('Fusion rejected the CLI dispatch event. Stop and restart the bridge add-in.')
        except Exception:
            if self._pump is None:
                work.cancel('Fusion could not queue the CLI dispatch event. Stop and restart the bridge add-in.')
        if not work.done.wait(_CALL_TIMEOUT_SECONDS):
            if not work.cancel("Timed out waiting for Fusion main thread. Inspect state before retrying."):
                # Execution already started. Do not report failure while a CAD
                # operation is still changing the design and invite a duplicate.
                work.done.wait()
        return work.result

    # ------------------------------------------------------------------
    # Runs on Fusion's main thread
    # ------------------------------------------------------------------
    def _on_custom_event(self, args):
        self.drain()

    def drain(self):
        """Called only from Fusion's main-thread custom or HTML callbacks."""
        while True:
            try:
                work = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if self._running:
                    work.run()
                else:
                    work.cancel("CadBot dispatcher is stopped")
            except (Exception,):
                # work() traps its own errors; this is a last resort.
                pass


class _WorkItem:
    def __init__(self, fn):
        self.fn = fn
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.started = False
        self.result = None

    def cancel(self, reason):
        with self.lock:
            if self.started:
                return False
            if not self.done.is_set():
                self.result = (False, {"error": reason})
                self.done.set()
            return True

    def run(self):
        with self.lock:
            if self.done.is_set():
                return
            self.started = True
        try:
            self.result = (True, self.fn())
        except Exception:
            self.result = (False, {"error": traceback.format_exc()})
        finally:
            self.done.set()


class _DispatchHandler(adsk.core.CustomEventHandler):
    def __init__(self, dispatcher):
        super().__init__()
        self._dispatcher = dispatcher

    def notify(self, args):
        self._dispatcher._on_custom_event(args)


class _HTMLDispatchHandler(adsk.core.HTMLEventHandler):
    def __init__(self, dispatcher):
        super().__init__()
        self._dispatcher = dispatcher

    def notify(self, args):
        # The local page is only a wakeup. No command/data is accepted from HTML.
        if args.action == 'dispatch' and args.data == '':
            self._dispatcher.drain()
        args.returnData = '{}'
