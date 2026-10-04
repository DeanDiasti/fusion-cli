import unittest
import io
import json
from unittest.mock import Mock, patch
import test_startup
from bridge.commands import prepare, EFFECTS
from tools import admin, animation
import bridge_cli
from bridge.build import fingerprint
from pathlib import Path


class AdminCommandsTests(unittest.TestCase):
    def test_nested_command(self):
        handler,args,edit=prepare({'command':'fusion design sketches create --name "One two"'})
        self.assertEqual((handler,args,edit),('create_sketch',{'name':'One two'},True))

    def test_native_animation_is_not_motion(self):
        self.assertEqual(prepare({'command':'fusion animation storyboards list'})[0],'storyboards_list')
        self.assertEqual(prepare({'command':'fusion animation components list'})[0],'animation_components_list')
        self.assertEqual(prepare({'command':'fusion animation components inspect --component occurrence:1'})[0],
                         'animation_component_inspect')
        self.assertEqual(prepare({'command':'fusion animation authoring capabilities'})[0],
                         'animation_authoring_capabilities')
        self.assertEqual(EFFECTS['animation components inspect'], 'inspection')
        self.assertEqual(EFFECTS['animation camera inspect'], 'inspection')
        self.assertEqual(EFFECTS['animation authoring capabilities'], 'inspection')
        self.assertEqual(EFFECTS['design motion check'],'temporary_preview')
        with self.assertRaises(ValueError):
            prepare({'command':'fusion animation storyboards list --python x'})

    def test_ambiguous_document_rejected(self):
        a=Mock(); a.name='same'; a.creationId='a'
        b=Mock(); b.name='same'; b.creationId='b'
        with self.assertRaises(ValueError): admin.unique([a,b],'same','creationId')
        self.assertIs(admin.unique([a,b],'b','creationId'),b)

    def test_close_never_discards_by_default(self):
        d=Mock(isModified=True)
        with patch.object(admin,'doc',return_value=d),self.assertRaisesRegex(ValueError,'unsaved'):
            admin.documents_close({'document':'d'})
        d.close.assert_not_called()

    def test_reference_copy_refused_until_supported(self):
        with patch.object(admin,'datafile',return_value=Mock(hasChildReferences=True)),self.assertRaisesRegex(ValueError,'Reference-aware'):
            admin.files_copy({'file':'a','folder':'b'})

    def test_wrong_workspace_rejected(self):
        with self.assertRaisesRegex(ValueError,'Animation workspace'):
            animation.require_workspace(Mock(isAnimationWorkspaceActive=False))

    def test_out_of_range_seek_has_no_effect(self):
        b=Mock(end=2,playheadPosition=0)
        with patch.object(animation,'board',return_value=b),self.assertRaises(ValueError):
            animation.storyboards_seek({'storyboard':0,'seconds':3})
        self.assertEqual(b.playheadPosition,0)

    def test_stale_runtime_never_sends_edit(self):
        with patch.object(bridge_cli,'runtime_status',return_value=({'error':'stale'},409)),patch.object(bridge_cli,'_open') as request:
            result,status=bridge_cli.call('fusion',{'command':'fusion design reset'})
        request.assert_not_called()
        self.assertEqual(status,409)

    def test_build_handshake_accepts_matching_source(self):
        root=Path(__file__).resolve().parents[1]/'fusion_addin'/'CadBot'
        response=io.BytesIO(json.dumps({'protocol':3,'build':fingerprint(root)}).encode())
        response.status=200
        with patch.object(bridge_cli,'_open',return_value=response):
            self.assertIsNone(bridge_cli.verify_runtime())

    def test_old_protocol_is_rejected(self):
        response=io.BytesIO(b'{"ok":true}')
        response.status=200
        with patch.object(bridge_cli,'_open',return_value=response):
            self.assertIn('different CadBot build',bridge_cli.verify_runtime())

    def test_workspaces_do_not_use_geometry_undo(self):
        self.assertEqual(EFFECTS['workspace activate'],'workspace_change')
        self.assertEqual(EFFECTS['documents save-as'],'document_change')
        self.assertEqual(EFFECTS['files copy'],'cloud_mutation')

    def test_design_target_flag(self):
        _,args,_=prepare({'command':'fusion design sketches list --document-id abc'})
        self.assertEqual(args,{'document_id':'abc'})

    def test_capability_report_includes_new_registry_commands(self):
        with patch('pathlib.Path.exists', return_value=False):
            report=admin.app_capabilities({})
        commands={item['command'] for item in report['commands']}
        self.assertIn('fusion design diagnostics', commands)
        self.assertIn('fusion design features inspect', commands)
