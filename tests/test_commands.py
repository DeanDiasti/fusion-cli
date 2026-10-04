import unittest
from unittest.mock import Mock, patch
import test_startup
from bridge.commands import prepare, SPECS
from bridge import server
from tools.registry import _TOOL_MAP


class CommandTests(unittest.TestCase):
    def setUp(self):
        test_startup.core.Application.get.return_value.userInterface.activeWorkspace.id='FusionSolidEnvironment'

    def test_every_command_has_handler_and_help(self):
        for cmd, (handler, *_rest) in SPECS.items():
            self.assertIn(handler, _TOOL_MAP)
            name, data, edit = prepare({'command': 'fusion '+cmd+' --help'})
            self.assertIsNone(name)
            self.assertIn('usage:',data['help'])

    def test_quoted_names_and_typed_flags(self):
        name, args, edit = prepare({'command': 'fusion features extrude --sketch "Base sketch" --distance-mm -10 --operation cut --symmetric'})
        self.assertEqual(name,'extrude')
        self.assertEqual(args,{'sketch':'Base sketch','distance_mm':-10,'operation':'cut','symmetric':True})
        self.assertTrue(edit)

    def test_rejects_invalid_commands_before_execution(self):
        for cmd in ('python print(1)', 'fusion execute --code x', 'fusion design inspect --wat 1',
                    'fusion features extrude --sketch x', 'fusion features extrude --sketch x --distance-mm nan',
                    'fusion features extrude --sketch x --distance-mm 1 --operation invalid',
                    'fusion bodies list ; rm file', 'fusion bodies combine --target x --tools \'[1]\''):
            with self.subTest(cmd=cmd), self.assertRaises((ValueError,TypeError)):
                prepare({'command':cmd})

    def test_shell_substitution_is_literal(self):
        _, args, _ = prepare({'command':'fusion bodies measure --body "$(touch /tmp/never)"'})
        self.assertEqual(args['body'],'$(touch /tmp/never)')

    def test_no_python_exposed(self):
        self.assertNotIn('fusion_execute',_TOOL_MAP)
        self.assertNotIn('fusion_api_help',_TOOL_MAP)

    def test_dispatch_read_vs_edit(self):
        owner = Mock()
        with patch.object(server,'_undo',owner), patch.dict(_TOOL_MAP,{'get_state':Mock(return_value={'ok':True}),'combine_bodies':Mock()}):
            self.assertEqual(server._execute_tool('fusion',None,{'command':'fusion design inspect'}),{'ok':True})
            owner.execute.assert_not_called()
            server._execute_tool('fusion',None,{'command':'fusion bodies combine --target arm --tools \'["ring"]\''})
            owner.execute.assert_called_once_with(_TOOL_MAP['combine_bodies'],{'target':'arm','tools':['ring']})

    def test_edit_without_checkpoint_rejected(self):
        with patch.object(server,'_undo',None), self.assertRaisesRegex(RuntimeError,'checkpoint'):
            server._execute_tool('fusion',None,{'command':'fusion design reset'})

    def test_animation_dispatch_uses_temporary_transaction(self):
        import json, shlex
        owner=Mock()
        command='fusion animation check --tracks '+shlex.quote(json.dumps([{'joint':'Hip','axis':'rotation','keys':[[0,0],[1,2]]}]))
        with patch.object(server,'_undo',owner):
            server._execute_tool('fusion',None,{'command':command})
        owner.preview.assert_called_once()
        owner.execute.assert_not_called()

    def test_expanded_design_cli_parses_typed_nested_commands(self):
        cases = {
            'fusion design sketches geometry construction --sketch s --entity e --construction false':
                ('geometry_set_construction', {'sketch':'s','entity':'e','construction':False}),
            'fusion design occurrences transform --occurrence o --matrix "[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]"':
                ('occurrences_transform', {'occurrence':'o','matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}),
            'fusion design surfaces thicken --surface s --thickness-mm 2 --symmetric false --chain true':
                ('surfaces_thicken', {'surface':'s','thickness_mm':2.0,'symmetric':False,'chain':True}),
            'fusion design meshes edit --mesh m --visible false --opacity 0.5':
                ('meshes_edit', {'mesh':'m','visible':False,'opacity':0.5}),
            'fusion design configurations edit --configuration c --column-index 1 --value "42"':
                ('configurations_edit', {'configuration':'c','column_index':1,'value':42}),
            'fusion design joints create --occurrence-one a --occurrence-two b --type rigid --geometry-one f --geometry-two e --keypoint-two middle':
                ('assembly_joints_create', {'occurrence_one':'a','occurrence_two':'b',
                    'type':'rigid','geometry_one':'f','geometry_two':'e','keypoint_two':'middle'}),
            'fusion design lofts create --sketches \'["a","b"]\' --rails \'[{"token":"r"}]\'':
                ('lofts_create', {'sketches':['a','b'],'rails':[{'token':'r'}]}),
            'fusion design sweeps create --profile-sketch p --path-entity e --guide-rail \'{"token":"g"}\' --profile-scaling stretch':
                ('sweeps_create', {'profile_sketch':'p','path_entity':'e',
                    'guide_rail':{'token':'g'},'profile_scaling':'stretch'}),
        }
        for command, (expected_handler, expected_args) in cases.items():
            with self.subTest(command=command):
                handler, args, mutates = prepare({'command':command})
                self.assertEqual(handler, expected_handler)
                self.assertEqual(args, expected_args)
                self.assertTrue(mutates)
        handler, args, mutates = prepare({
            'command': 'fusion design joints geometry list --occurrence o'})
        self.assertEqual((handler, args, mutates),
                         ('assembly_joint_geometry_list', {'occurrence': 'o'}, False))

    def test_expanded_design_cli_rejects_invalid_explicit_values(self):
        for command in (
            'fusion design sketches geometry fixed --sketch s --entity e --fixed maybe',
            'fusion design configurations edit --configuration c --column-index 1 --value "[]"',
        ):
            with self.subTest(command=command), self.assertRaises((ValueError, TypeError)):
                prepare({'command':command})
