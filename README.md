# fusion-cli

[![CI](https://github.com/DeanDiasti/fusion-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/DeanDiasti/fusion-cli/actions/workflows/ci.yml)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

A typed command-line interface for **Autodesk Fusion**. Build parametric parts, edit assemblies,
preview joint motion, and inspect interference through validated commands.

[Website and installation guide](https://deandiasti.github.io/fusion-cli/) ·
[Homebrew tap](https://github.com/DeanDiasti/homebrew-tap) ·
[Command reference](https://deandiasti.github.io/fusion-cli/commands/)

The Python add-in runs CAD operations on Fusion's main thread. The terminal CLI
uses a finite command catalog and an authenticated localhost bridge. The CLI and
installer use only Python's standard library.

## What it can do

- **Model:** sketches, arcs, splines, profiles, face supports, projection, offset,
  trim, extrude, revolve, loft, sweep, fillet, chamfer, patterns and solid features.
- **Assemble:** components, occurrences, joints, limits and construction geometry.
- **Animate:** coordinated rotation/slide tracks, easing, pauses and an HTML player
  with once, loop or ping-pong playback.
- **Inspect:** dimensions, topology, geometry, current-pose interference and
  sampled interference along joint trajectories.
- **Manage:** parameters, materials, supported sheet-metal operations, timeline,
  documents, exports and cloud administration.
- **Recover:** explicit, named Design checkpoints with verified session undo.

Release **0.6.0** has 261 canonical commands. Recorded live cases cover 255 commands;
six paths are explicitly unavailable. Native component animation authoring remains
blocked. Read the [release scope](docs/release-0.6.0.md) before relying on a specific
operation; passing cases do not certify arbitrary geometry or every flag combination.

## Requirements

- Autodesk Fusion installed separately. Native validation used Fusion 2705.1.15
  on macOS; other Fusion versions need live revalidation.
- Python 3.10+ for the terminal CLI. Homebrew installs Python 3.14.
- No third-party Python packages or AI account are required.
- Node.js for development tests only.

The included installer targets **macOS**. Windows installation and native behavior
are not validated. Fusion's bundled Python loads the add-in; the terminal CLI
uses a separate Python interpreter. This repository does not include Fusion or
its API binaries.

## Install on macOS

### Homebrew

```bash
brew install DeanDiasti/tap/fusion-cli
fusion-install-addin
```

The dedicated tap installs the CLI and Python. Autodesk Fusion must be installed separately. This is a
community tap, not a Homebrew core package. `fusion-install-addin` preserves an
existing bridge token and backs up the previous add-in.

Save work and stop CadBot before `brew upgrade DeanDiasti/tap/fusion-cli`, then run
`fusion-install-addin` again and restart Fusion. Homebrew upgrades do not modify
the running add-in automatically. See [distribution details](docs/distribution.md).

### Source checkout

```bash
git clone https://github.com/DeanDiasti/fusion-cli.git
cd fusion-cli
python3 -m venv .venv
./scripts/install_addin.sh
```

Save your work, restart Fusion, then open **Scripts and Add-Ins → Add-Ins → CadBot →
Run**. CadBot is the bridge add-in name. Use the CLI from your terminal.
Reinstall after changing add-in source files.

```bash
./scripts/fusion help
./scripts/fusion design sketches offset --help
./scripts/fusion doctor
./scripts/fusion design inspect
```

Help works without Fusion. `doctor` checks credentials and the exact installed build.
Homebrew users run `fusion` in place of `./scripts/fusion` in these examples.
Read-only commands work once the add-in is running. **Design edits and motion
previews require an explicit CLI checkpoint**. For example, in an empty Design:

```bash
fusion checkpoint begin --id plate
fusion design sketches create --name Base
fusion design sketches rectangles add --sketch Base --x1-mm 0 --y1-mm 0 --x2-mm 20 --y2-mm 10
fusion design features extrude --sketch Base --distance-mm 5 --operation new
fusion checkpoint finish
fusion checkpoint status
# Optional: undo this checkpoint and all later recorded edits.
fusion checkpoint restore --id plate
```

Source users substitute `./scripts/fusion` for `fusion`. Use `--document-id` on
`checkpoint begin` and `restore` to assert the intended active document. Checkpoints
are session-only; external edits, document changes and bridge restarts can invalidate
them. See the [CLI guide](docs/cli-guide.md) for selectors, units and recovery.

## Development and validation

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_motion_player.cjs
.venv/bin/python scripts/check_public.py
.venv/bin/python scripts/check_release.py
```

Host tests use fake Fusion objects, with no CAD application or
account required. GitHub CI runs them without credentials.
The publication guard needs Python 3.14+ to decompress the native Fusion fixture;
the CLI and host tests support Python 3.10+.

Native behavior is verified separately: the current release has nine native Fusion gates and seven
installed HTTP gates. [Public evidence](docs/public-evidence/eed1b12ce2969c86/) preserves
case dispositions and geometry/cleanup assertion summaries; raw account identifiers,
entity selectors, local paths and tool responses are withheld.

The release verifier binds evidence to source/fixture hashes and the loaded CAD
build. It should fail after relevant source changes until the affected checks and
live gates have been rerun. CI host success alone does not certify native Fusion
behavior. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and
[docs/validation.md](docs/validation.md) for evidence publication.

## Limits and data handling

Motion previews restore the starting pose through verified transaction aborts.
Interference sampling can miss collisions between poses; it is not continuous
collision detection, clearance analysis, physics simulation or automatic rigging.
Generated preview files are temporary artifacts outside CAD undo. Native undo uses
Fusion's runtime-specific PTransaction interface and needs revalidation after upgrades.

The bridge is a single-user loopback service, not a remote server. The installer
creates a random private token and preserves existing credentials. Do not expose
the bridge to a network. [SECURITY.md](SECURITY.md) covers the trust boundary and
private vulnerability reporting. Never include credentials, private designs or
unredacted cloud/account identifiers in public issues or pull requests.

## Community and license

Bug reports and feature proposals belong in [GitHub Issues](https://github.com/DeanDiasti/fusion-cli/issues).
Contributions are welcome; start with [CONTRIBUTING.md](CONTRIBUTING.md),
[the roadmap](docs/roadmap.md) and [the code of conduct](CODE_OF_CONDUCT.md).

Copyright © 2026 Dean Diasti and contributors. Licensed under **GNU GPL version 3
only**, `GPL-3.0-only`; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Autodesk Fusion is a separately licensed product. This is an independent
community project, not an official Autodesk product.
