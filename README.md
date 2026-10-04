# fusion-cli

[![CI](https://github.com/DeanDiasti/fusion-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/DeanDiasti/fusion-cli/actions/workflows/ci.yml)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

A typed command-line interface for **Autodesk Fusion**, with **CadBot**, an optional
Codex-powered chat assistant inside Fusion. Build parametric parts, edit assemblies,
preview joint motion, and inspect interference through validated commands.

[Website and installation guide](https://deandiasti.github.io/fusion-cli/) ·
[Homebrew tap](https://github.com/DeanDiasti/homebrew-tap) ·
[Command reference](https://deandiasti.github.io/fusion-cli/commands/)

The Python add-in runs CAD operations on Fusion's main thread. A separate Python
worker handles the AI conversation. Both chat and terminal clients use the same
finite command catalog and authenticated localhost bridge.

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
- **Chat:** reference images, streaming tool activity, saved conversations and
  verified message-level Design undo.

Release **0.5.0** has 257 canonical commands. Recorded live cases cover 251 commands;
six paths are explicitly unavailable. Native component animation authoring remains
blocked. Read the [release scope](docs/release-0.5.0.md) before relying on a specific
operation; passing cases do not certify arbitrary geometry or every flag combination.

## Requirements

- Autodesk Fusion installed separately. Native validation used Fusion 2705.1.15
  on macOS; other Fusion versions need live revalidation.
- Python 3.10+ for the external worker. Python 3.14 is the validated local runtime.
- The pinned Python dependency in [requirements.txt](requirements.txt).
- A local Codex runtime and sign-in for AI chat. Offline help and the structured
  CAD bridge do not require a model call.
- Node.js for development tests only.

The included installer targets **macOS**. Windows installation and native behavior
are not validated. Fusion's bundled Python loads the add-in; your virtual environment
runs the external worker. This repository does not include Fusion, its API binaries,
or the Codex runtime.

## Install on macOS

### Homebrew

```bash
brew install DeanDiasti/tap/fusion-cli
fusion-install-addin
```

The dedicated tap installs the CLI and an isolated Python environment with pinned,
checksummed dependencies. Autodesk Fusion must be installed separately. This is a
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
.venv/bin/python -m pip install -r requirements.txt
./scripts/install_addin.sh
```

Save your work, restart Fusion, then open **Scripts and Add-Ins → Add-Ins → CadBot →
Run**. Open the chat palette and complete Codex sign-in if requested. Fusion starts
and stops the external worker automatically. Keep this checkout and its `.venv` in
place, and reinstall after moving them or changing source files.

```bash
./scripts/fusion help
./scripts/fusion design sketches offset --help
./scripts/fusion doctor
./scripts/fusion design inspect
```

Help works without Fusion. `doctor` checks credentials and the exact installed build.
Homebrew users run `fusion` in place of `./scripts/fusion` in these examples.
Read-only commands work from the terminal once the add-in is running. **Design edits
and motion previews require an active CadBot message checkpoint**; independent
terminal mutations are rejected. Use the Fusion chat as the normal modeling entry
point. No arbitrary Python executor or shell evaluation is exposed by the CAD tool.

Example chat requests:

- “Create a parametric mounting bracket and verify its dimensions.”
- “Offset this sketch by 2 mm, then inspect the resulting profiles.”
- “List the joints, preview the slider motion with a pause, and report interference.”

See the [CLI and chat guide](docs/cli-guide.md) for command examples, selectors,
units, reference images, saved conversations, recovery and architecture.

## Development and validation

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_palette.cjs
node tests/test_motion_player.cjs
.venv/bin/python scripts/check_public.py
.venv/bin/python scripts/check_release.py
```

Host tests use fake Fusion objects and SDK responses, with no CAD application or
account required. GitHub CI runs them without credentials.
The publication guard needs Python 3.14+ to decompress the native Fusion fixture;
the external worker and host tests support Python 3.10+.

Native behavior is verified separately: the current release has nine native Fusion gates and six
installed HTTP gates. [Public evidence](docs/public-evidence/41b3c0f4c7e81a3a/) preserves
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
the bridge to a network. AI chat sends prompts, reference images and requested CAD
tool results to Codex. [SECURITY.md](SECURITY.md) covers the trust boundary and
private vulnerability reporting. Never include credentials, private designs or
unredacted cloud/account identifiers in public issues or pull requests.

## Community and license

Bug reports and feature proposals belong in [GitHub Issues](https://github.com/DeanDiasti/fusion-cli/issues).
Contributions are welcome; start with [CONTRIBUTING.md](CONTRIBUTING.md),
[the roadmap](docs/roadmap.md) and [the code of conduct](CODE_OF_CONDUCT.md).

Copyright © 2026 Dean Diasti and contributors. Licensed under **GNU GPL version 3
only**, `GPL-3.0-only`; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Autodesk Fusion and OpenAI Codex are separately licensed products. This is an
independent community project, not an official Autodesk or OpenAI product.
