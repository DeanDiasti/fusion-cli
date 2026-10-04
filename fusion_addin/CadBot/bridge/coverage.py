"""Current-build coverage, retaining older evidence without certifying it."""
from collections import Counter


def section(command):
    if command.startswith('design '):
        return 'design'
    if command.startswith('animation '):
        return 'animation'
    return 'administration'


def reconcile(evidence, specs, effects, build):
    recorded = {row['command']: row for row in evidence.get('commands', [])}
    rows = []
    for name in sorted(specs):
        old = recorded.get('fusion ' + name, {})
        cases = [dict(case, build=case.get('build', evidence.get('build')))
                 for case in old.get('cases', [])]
        current = [case for case in cases if case.get('build') == build]
        # Any failing current case blocks release, even if another case passed.
        if any(not c.get('passed') and not c.get('capability_blocked') for c in current):
            validation = 'live_failure'
        elif any(c.get('passed') and not c.get('capability_blocked') for c in current):
            validation = 'live_case_passed'
        elif current and all(c.get('capability_blocked') for c in current):
            validation = 'live_capability_blocked'
        else:
            validation = 'not_live_verified'
        rows.append({'command': 'fusion ' + name, 'effect': effects[name],
                     'validation': validation, 'cases': cases})
    summaries = {}
    for group in ('administration', 'design', 'animation'):
        scoped = [r for r in rows if section(r['command'][7:]) == group]
        counts = Counter(r['validation'] for r in scoped)
        summaries[group] = {'command_count': len(scoped), **{key: counts[key] for key in
            ('live_case_passed', 'live_failure', 'live_capability_blocked', 'not_live_verified')},
            'live_pass_percent': round(100 * counts['live_case_passed'] / len(scoped), 1) if scoped else 0}
    ready = bool(rows) and all(r['validation'] in ('live_case_passed', 'live_capability_blocked') for r in rows)
    return {**evidence, 'build': build, 'evidence_build': evidence.get('evidence_build', evidence.get('build')),
            'coverage': 'complete' if ready else 'partial', 'release_ready': ready,
            'release_scope': 'Recorded command cases on this add-in build; not every input geometry or option combination.',
            'command_count': len(rows), 'design_command_count': summaries['design']['command_count'],
            'design_commands_with_passing_live_case': summaries['design']['live_case_passed'],
            'section_summary': summaries, 'commands': rows}
