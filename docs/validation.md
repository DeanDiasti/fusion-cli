# Validation and evidence publication

Host tests establish grammar, transport, transaction-controller contracts
and failure paths using mocks. Native fixtures establish actual Fusion
geometry, associations, solver behavior and cleanup. Installed HTTP gates exercise
the bridge and main-thread dispatch end to end. Treat these as separate evidence.

## Checks without Fusion

```bash
python -m unittest discover -s tests -p 'test_*.py'
node tests/test_motion_player.cjs
python scripts/check_public.py
```

The complete host suite uses the standard library. No Autodesk account or native
Fusion operation is required. GitHub CI
runs these checks on Linux and macOS. CI uses pinned action revisions, read-only
repository permissions and no project credentials.
The publication guard requires Python 3.14+ for ZIP Zstandard entries in the native
Fusion fixture; CI runs that complete scan on both Python 3.14 jobs. Python 3.10
also runs host tests and offline CLI checks.

`python scripts/check_release.py` additionally checks the durable public evidence
and exact source/fixture hashes for the current build. Run this for a release;
a source-changing pull request may pass host CI while correctly invalidating the
old release certificate. `--runtime` also verifies the running add-in handshake.

## Native and HTTP gates

Save work first. Install/reload the candidate and confirm the build with `doctor`.
Run the disposable gates described in the current release report. Verify geometry,
not only API return values, and restore the original document/workspace. A failed
cleanup invalidates a gate even if an individual command succeeded.

Do not run cloud tests routinely: Administration creates files/folders and leaves
an empty project because Fusion's public API cannot delete projects. Do not use
private designs as fixtures.

## Publish evidence without private data

Raw JSON reports can include cloud account/project IDs, local user paths, active
project listings, entity tokens and tool results. Keep them in `/tmp` or the
Git-ignored `docs/release-evidence/BUILD/` directory. Do not attach them to issues.
Historical private investigations and scratch probes are excluded from the
public source tree.

After reviewing passing current-build gates:

```bash
python scripts/publish_evidence.py --reports-dir /path/to/private/raw/reports
python scripts/cli_coverage.py --reports-dir docs/public-evidence/BUILD --write
```

Replace `BUILD` with the fingerprint returned by the bridge. The publisher keeps
canonical command names, original pass/blocker dispositions, numeric gate metrics
and boolean geometry/cleanup assertions. It removes command flags, raw tool
responses and identifying strings. Each summary records the raw report SHA-256;
that hash is provenance, not a claim that withheld details are publicly auditable.
The synthetic fixtures and assertion code are included so native tests can be
repeated independently. Do not fabricate reports or promote failed cases.

Once relevant host checks and live gates have passed, review the public reports
and create/update `manifest.json` in their build directory. It must contain:

- `build`: the exact loaded runtime fingerprint.
- `source_sha256`: the public source map returned by `scripts/check_release.py`'s
  `source_hashes()` function, including tests, scripts and the synthetic fixture.
- `reports_sha256`: SHA-256 of every included public JSON report except the manifest.

Record platform, Fusion version, host-test count and publication format as well.
Keep the private raw manifest intact. Changes to publication tooling or host tests
require rerunning their checks; CAD-runtime changes require fresh native evidence
for the new build. Hash refresh is bookkeeping after validation, not validation.

Run `scripts/check_release.py`, reinstall to package the coverage snapshot, then
verify the runtime. It never regenerates evidence silently. Current failures take
precedence over passing cases; historical cases cannot certify a new build.

## Public release review

Run `git diff --cached --check` and `scripts/check_public.py` before pushing. The
scanner checks Git's publication list, including decompressed Fusion fixture
metadata, for prohibited files and selected credential/account/path patterns.
It reports filenames/categories without printing matched sensitive values. It
cannot recognize all private content; review newly added artifacts manually.
The initial public import includes redacted summaries for 0.5.0 and retains raw
historical reports locally. No Autodesk API/runtime binaries, credentials,
conversation history or developer virtual environment are distributed.
