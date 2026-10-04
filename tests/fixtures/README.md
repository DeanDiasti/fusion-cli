# Native playback fixture

`native-camera-playback.f3d` was authored locally in Autodesk Fusion 2705.1.15
using a disposable direct-design document with one cube, one component, and a
one-second native camera action. It contains no user model or external links.
Fusion exported the archive after returning to its UI event loop to commit the
action. An immediate synchronous recording attempt reported a zero-length track.

`tests/live_animation_playback_http.py` imports this archive into a disposable
document and verifies play, intermediate playhead positions, completion at the
storyboard end, and restoration of the original document and workspace. It does
not certify camera image differences, component transform authoring, or export
of animation video. The release evidence manifest records the archive SHA-256.
