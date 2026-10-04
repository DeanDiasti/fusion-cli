"""Shared runtime state for CadBot (set at add-in startup, on Fusion's thread)."""

import adsk.core

app = None
ui = None
dispatcher = None
