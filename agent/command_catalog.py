"""Load the same pure-Python grammar used by the installed Fusion add-in."""
import functools
import importlib.util
from pathlib import Path


def source_root():
    parent = Path(__file__).resolve().parent.parent
    root = parent if (parent / 'CadBot.py').is_file() else parent / 'fusion_addin' / 'CadBot'
    if not (root / 'bridge' / 'commands.py').is_file():
        raise RuntimeError('Cannot locate the CadBot command catalog. Reinstall the add-in.')
    return root


@functools.lru_cache(maxsize=2)
def load(name):
    path = source_root() / 'bridge' / (name + '.py')
    spec = importlib.util.spec_from_file_location('_cadbot_client_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
