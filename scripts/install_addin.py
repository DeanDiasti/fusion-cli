"""Stage a complete install before replacing CadBot; retain a recoverable backup."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import secrets
import shutil
import tempfile


def install(project, destination):
    project, destination = Path(project).resolve(), Path(destination).absolute()
    source = project / 'fusion_addin' / 'CadBot'
    if not (source / 'CadBot.py').is_file() or not (project / 'cli' / 'fusion_cli.py').is_file():
        raise ValueError('Incomplete source tree; no installed files were changed.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.cadbot-stage-', dir=destination.parent))
    backup = None
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
        shutil.copytree(project / 'cli', staging / 'cli', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
        token = ''
        for candidate in (source / '.bridge_token', destination / '.bridge_token'):
            if candidate.is_file():
                token = candidate.read_text().strip()
                if token:
                    break
        (staging / '.bridge_token').write_text(token or secrets.token_urlsafe(32))
        (staging / '.bridge_token').chmod(0o600)
        if destination.exists() or destination.is_symlink():
            backup = destination.with_name(destination.name + '.backup.' + datetime.now().strftime('%Y%m%d%H%M%S%f'))
            os.replace(destination, backup)
        try:
            os.replace(staging, destination)
        except Exception:
            if backup is not None:
                os.replace(backup, destination)
            raise
        return backup
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=Path.home() / 'Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/CadBot')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    backup = install(project, args.destination)
    print('Installed:', args.destination)
    if backup:
        print('Previous installation:', backup)
    print('Save work and restart Fusion, then run CadBot from Scripts and Add-Ins.')


if __name__ == '__main__':
    main()
