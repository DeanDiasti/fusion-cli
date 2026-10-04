import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup
from bridge.commands import EFFECTS, prepare
from tools import animation


class Storyboards:
    def __init__(self, boards): self.boards=list(boards)
    @property
    def count(self): return len(self.boards)
    def item(self,index): return self.boards[index]


class Board:
    def __init__(self, end=8):
        self.isValid=True; self.isActive=True; self.end=end
        self.playheadPosition=0; self.isInPlayMode=False
        self.isViewRecordingOn=False; self.isInFullScreenMode=False
        self.copy=Mock(return_value=Board.__new__(Board))
        self.moveTo=Mock(return_value=True); self.play=Mock(return_value=True)


class AnimationTests(unittest.TestCase):
    def setUp(self):
        animation._selectors.clear()
        self.first=Board(); self.second=Board()
        self.manager=SimpleNamespace(
            isAnimationWorkspaceActive=True,
            storyboards=Storyboards([self.first,self.second]),
            recordingMode=10,isWatermarkShown=False,
        )
        self.app=SimpleNamespace(activeDocument=SimpleNamespace(creationId='doc'))
        self.patches=[
            patch.object(animation,'manager',return_value=self.manager),
            patch.object(animation.adsk.core.Application,'get',return_value=self.app),
            patch.object(animation.adsk,'doEvents',create=True),
            patch.object(animation.adsk.fusion,'RecordingModeTypes',
                SimpleNamespace(RecordingModeStartFromTime0=10,
                                RecordingModeOverlappedByHalfSeconds=20,
                                RecordingModeSequential=30),create=True),
        ]
        for item in self.patches: item.start(); self.addCleanup(item.stop)
        self.first_selector=animation.selector(self.first)
        self.second_selector=animation.selector(self.second)

    def test_command_grammar_covers_typed_animation_controls(self):
        handler,args,_=prepare({'command':
            'fusion animation storyboards copy --storyboard s --name Explode '
            '--target-storyboard t --before true'})
        self.assertEqual(handler,'storyboards_copy')
        self.assertEqual(args,{'storyboard':'s','name':'Explode',
                               'target_storyboard':'t','before':True})
        handler,args,_=prepare({'command':
            'fusion animation playback play --storyboard s --from-current false '
            '--begin-seconds 2 --end-seconds 5'})
        self.assertEqual(handler,'storyboards_play')
        self.assertEqual(args['from_current'],False)
        self.assertEqual((args['begin_seconds'],args['end_seconds']),(2.0,5.0))
        self.assertEqual(EFFECTS['animation storyboards move'],'animation_change')
        self.assertEqual(EFFECTS['animation settings watermark'],'animation_change')

    def test_copy_and_move_use_public_storyboard_api(self):
        animation.storyboards_copy({'storyboard':self.first_selector,'name':'Copy',
            'target_storyboard':self.second_selector,'before':True})
        self.first.copy.assert_called_once_with('Copy',self.second,True)
        animation.storyboards_move({'storyboard':self.first_selector,
            'target_storyboard':self.second_selector,'before':False})
        self.first.moveTo.assert_called_once_with(self.second,False)

    def test_playback_range_and_state_controls(self):
        result=animation.storyboards_play({'storyboard':self.first_selector,
            'from_current':False,'begin_seconds':2,'end_seconds':5})
        self.first.play.assert_called_once_with(False,2,5)
        self.assertEqual(result['end_seconds'],8)
        with self.assertRaisesRegex(ValueError,'begin'):
            animation.storyboards_play({'storyboard':self.first_selector,
                'begin_seconds':6,'end_seconds':5})
        animation.playback_full_screen({'storyboard':self.first_selector,'enabled':True})
        animation.camera_recording({'storyboard':self.first_selector,'enabled':True})
        self.assertTrue(self.first.isInFullScreenMode)
        self.assertTrue(self.first.isViewRecordingOn)

    def test_authoring_discovery_outside_animation_does_not_activate_workspace(self):
        self.app.version = '2705.1.15'
        self.app.userInterface = Mock()
        self.manager.isAnimationWorkspaceActive = False
        result = animation.authoring_capabilities({})
        self.assertFalse(result['workspace_active'])
        self.assertIn('fusion workspace', result['next_step'])
        self.assertFalse(result['safe_to_attempt_action_writes'])
        self.app.userInterface.workspaces.itemById.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Animation workspace'):
            animation.storyboards_list({})

    def test_authoring_discovery_without_document_returns_context(self):
        self.app.version = '2705.1.15'
        self.app.userInterface = Mock()
        with patch.object(animation, 'manager', side_effect=ValueError('Open a Fusion document first')):
            result = animation.authoring_capabilities({})
        self.assertFalse(result['workspace_active'])
        self.assertEqual(result['context_error'], 'Open a Fusion document first')

    def test_recording_settings_round_trip(self):
        self.assertEqual(animation.settings_inspect({}),
                         {'recording_mode':'time-zero','watermark_shown':False})
        result=animation.settings_recording_mode({'mode':'sequential'})
        self.assertEqual(result['recording_mode'],'sequential')
        result=animation.settings_watermark({'enabled':True})
        self.assertTrue(result['watermark_shown'])


if __name__ == '__main__': unittest.main()
