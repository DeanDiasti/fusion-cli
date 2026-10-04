"""Run a named release fixture in Fusion and stamp evidence with its exact build.

Use runpy.run_path(this_file, init_globals={'GATE_NAME': 'curves'}).
No gate is run by ordinary host-side test discovery.
"""
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'fusion_addin/CadBot'))
from bridge.build import BUILD, fingerprint

GATES = {
    'design-motion': ('fusion_design_motion_smoke.py', 'cadbot-design-motion-smoke.json'),
    'face-modeling': ('fusion_face_modeling_smoke.py', 'cadbot-face-modeling-smoke.json'),
    'basic': ('fusion_design_cli_smoke.py', 'cadbot-design-cli-smoke.json'),
    'curves': ('fusion_sketch_curves_smoke.py', 'cadbot-design-sketch-curves-smoke.json'),
    'core': ('fusion_design_core_release_smoke.py', 'cadbot-design-core-release.json'),
    'extended': ('fusion_design_extended_validation.py', 'cadbot-design-extended-validation.json'),
    'remaining': ('fusion_design_remaining_smoke.py', 'cadbot-design-remaining.json'),
    'animation': ('fusion_animation_release_smoke.py', 'cadbot-animation-release-smoke.json'),
    'admin': ('fusion_admin_release_smoke.py', 'cadbot-admin-release-smoke.json'),
}

if 'GATE_NAME' in globals():
    assert fingerprint(ROOT / 'fusion_addin/CadBot') == BUILD, 'Loaded add-in and source builds differ; reload before testing.'
    script, report_name = GATES[GATE_NAME]
    output = Path('/tmp') / report_name
    before = output.stat().st_mtime_ns if output.exists() else None
    namespace = runpy.run_path(str(ROOT / 'tests' / script))
    if GATE_NAME == 'curves':
        namespace['run'](None)
    assert output.exists() and output.stat().st_mtime_ns != before, 'Gate did not produce fresh evidence.'
    report = json.loads(output.read_text())
    report['build'] = BUILD
    output.write_text(json.dumps(report, indent=2) + '\n')
    print('Stamped release evidence:', GATE_NAME, BUILD, 'passed=', report.get('passed'))
