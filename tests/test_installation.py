import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install_addin.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_complete_install_preserves_token_and_old_files_in_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'CadBot'
            dest.mkdir()
            (dest / '.bridge_token').write_text('existing-test-token')
            (dest / 'previous.txt').write_text('old installation')
            backup = installer.install(ROOT, dest)
            self.assertEqual((dest / '.bridge_token').read_text(), 'existing-test-token')
            self.assertEqual((dest / '.bridge_token').stat().st_mode & 0o777, 0o600)
            self.assertTrue((backup / 'previous.txt').is_file())
            self.assertTrue((dest / 'cli/command_catalog.py').is_file())
            self.assertFalse(list(dest.rglob('*.pyc')))
            self.assertFalse((dest / 'runtime_config.json').exists())
            self.assertFalse((dest / 'chat.py').exists())
            self.assertFalse((dest / 'palette').exists())
            help_result = subprocess.run([sys.executable, '-S', str(dest / 'cli/fusion_cli.py'),
                'design', 'sketches', 'arcs', 'add', '--help'], capture_output=True, text=True)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn('--points-mm', help_result.stdout)


    def test_first_install_generates_private_random_token(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'CadBot'
            installer.install(ROOT, dest)
            token = (dest / '.bridge_token').read_text()
            self.assertGreaterEqual(len(token), 32)
            self.assertNotEqual(token, 'cadbot-dev-token')

    def test_failed_swap_restores_previous_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'CadBot'
            dest.mkdir()
            (dest / 'previous.txt').write_text('intact')
            original_replace = installer.os.replace
            def replace(source, target):
                if Path(source).name.startswith('.cadbot-stage-'):
                    raise OSError('simulated swap failure')
                return original_replace(source, target)
            with patch.object(installer.os, 'replace', side_effect=replace), self.assertRaises(OSError):
                installer.install(ROOT, dest)
            self.assertEqual((dest / 'previous.txt').read_text(), 'intact')
            self.assertFalse(list(Path(directory).glob('.cadbot-stage-*')))
