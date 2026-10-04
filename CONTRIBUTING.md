# Contributing to fusion-cli

Start with a reproducible issue or a small pull request. For a new command, explain
the CAD operation, proposed flags, expected geometry and failure behavior. Check
[the roadmap](docs/roadmap.md) and existing issues before taking on a large feature.

## Set up

Fork and clone the repository, then create a virtual environment and install
`requirements.txt`. Python 3.10+ and Node.js are needed for host checks. Autodesk
Fusion is required only for native gates. The included installation workflow is
validated on macOS; do not claim Windows support based on mock tests.
Use Python 3.14+ for the publication guard, which decompresses the Fusion fixture.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_palette.cjs
node tests/test_motion_player.cjs
.venv/bin/python agent/fusion_cli.py help
```

The tests use mocked SDK calls and fake Fusion objects. They must not connect to
a model, modify a real design, require credentials or operate a cloud account.
`tests/smoke_chat.py` is an optional account-backed test and is excluded from CI.
Native and HTTP scripts are explicit manual gates, not unit-test discovery targets.

## Implement a command

1. Add a finite command and typed flags to `bridge/commands.py`, with useful offline
   help and input validation. Register its handler in `tools/registry.py`.
2. Classify its effect correctly. Design mutations use message transactions;
   temporary previews use the preview controller and verified rollback. Native
   Animation, cloud and document operations have different restoration boundaries.
3. Validate the complete request before changing geometry. Use explicit selectors,
   component ownership checks and documented units. Check actual API outcomes;
   warnings or no-op native features must not count as successful geometry.
4. Add meaningful host tests for contracts and failure paths. Use a disposable,
   synthetic native fixture to check geometry, associations and cleanup. Exercise
   installed HTTP dispatch when the transport or transaction path matters.
5. Update the guide and operation limits. Report unverified or unavailable paths
   clearly instead of silently approximating another operation.

Fusion objects stay on its main thread through the dispatcher. Never add arbitrary
Python evaluation, shell execution, raw-mutation shortcuts, automatic replay after
timeout, credentials in source, or network binding beyond loopback.

## Validation and release evidence

CI runs host checks and the publication guard. It does not execute Autodesk Fusion.
Code changes can invalidate the archived release certificate even when host tests
pass. `scripts/check_release.py` is the stricter release check and intentionally
fails until relevant source hashes and current-build evidence agree.

For changes to CAD runtime Python, install/reload the candidate and run fresh live
gates for its new build. Start with saved work and synthetic disposable designs.
The Administration gate creates cloud fixtures and leaves an empty project because
the public API has no project deletion method; do not run it for routine health.
Never run experiments on a contributor's private or unsaved design.

Keep raw reports private, publish redacted summaries, then update the release
manifest only after successful checks. Do not change hashes or pass flags merely
to make a checker green. See [docs/validation.md](docs/validation.md).

## Pull requests

Describe the concrete before/after behavior, relevant validation and remaining
limits. Use small, reviewable changes. A meaningful native test should establish
geometry or behavior independently, not just assert that an API method returned.
Disclose whether Fusion checks ran and the tested Fusion version/platform.

Before pushing, run `scripts/check_public.py` against the Git publication list.
Exclude tokens, runtime configuration, conversation history, private models,
raw cloud reports, developer paths and generated caches. Report security issues
privately using [SECURITY.md](SECURITY.md).

Contributions to this repository are made under GPL-3.0-only. Retain attribution
and applicable notices. There is no additional contributor agreement or DCO
sign-off requirement. Respect [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
