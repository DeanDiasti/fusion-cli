"""Public summaries preserve dispositions while withholding identifying data."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish_evidence import summarize
from check_public import scan_bytes
from public_files import is_public_path


class PublicationTests(unittest.TestCase):
    def test_summary_preserves_pass_blocker_and_geometry_assertions(self):
        raw={'build':'build','passed':True,'undo_verified':True,'volume_mm3':500,
             'account':'private-account','retained_project':'private-project',
             'results':[{'command':'fusion design sketches offset --sketch private-sketch --entities \'["private-token"]\' --distance-mm 2',
                         'passed':True,'result':{'token':'private-token'}},
                        {'command':'fusion projects delete --project private-project','passed':True,
                         'blocker_matched':True,'outcome':'capability_blocked'}]}
        report=summarize(raw)
        self.assertTrue(report['passed']);self.assertTrue(report['undo_verified'])
        self.assertEqual(report['volume_mm3'],500)
        self.assertEqual(report['results'][0],{'command':'fusion design sketches offset','passed':True})
        self.assertTrue(report['results'][1]['blocker_matched'])
        self.assertNotIn('private-',json.dumps(report))

    def test_failed_case_is_never_promoted(self):
        row=summarize({'passed':False,'results':[{'command':'fusion design inspect','passed':False,'error':'private-error'}]})
        self.assertFalse(row['passed']);self.assertFalse(row['results'][0]['passed'])
        self.assertNotIn('private-error',json.dumps(row))

    def test_private_and_generated_files_are_excluded(self):
        for path in ('agent/__pycache__/x.pyc','.venv/lib/module.py','fusion_addin/CadBot/.bridge_token',
                     'fusion_addin/CadBot/runtime_config.json','docs/release-evidence/build/report.json',
                     'docs/native-animation-authoring-proof.md','tests/fusion_animation_time_probe.py',
                     '.env.production'):
            with self.subTest(path=path):self.assertFalse(is_public_path(path))
        for path in ('LICENSE','.github/workflows/ci.yml','tests/fusion_design_motion_smoke.py',
                     'docs/public-evidence/build/report.json','cli/fusion_cli.py'):
            self.assertTrue(is_public_path(path),path)

    def test_scanner_recognizes_sensitive_markers_without_returning_them(self):
        data=b'/'+b'Users/'+b'private-person/file '+b'ghp_'+b'a'*32
        labels=scan_bytes(data)
        self.assertIn('personal home path',labels);self.assertIn('GitHub credential',labels)
        self.assertNotIn('private-person',repr(labels))
        self.assertFalse(scan_bytes(b'fake-test-token and @root::joint:Slide'))
