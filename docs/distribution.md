# Distribution and discoverability

The [project website](https://deandiasti.github.io/fusion-cli/) provides crawlable
HTML pages for Autodesk Fusion CLI workflows, installation, and command help.
Each page has a descriptive title, summary, canonical URL, social preview metadata,
and structured data. The sitemap lists the public pages. GitHub Pages deploys
only `site/`, after navigation and metadata checks; private reports are not inputs.

Search engines decide whether and when to index a new site. No ranking or indexing
guarantee is implied. A project site cannot set the origin's root `robots.txt`;
these pages permit indexing through their own robots metadata. A maintainer can
verify the URL-prefix property in Google Search Console and submit
`https://deandiasti.github.io/fusion-cli/sitemap.xml` using their own account.
Do not publish verification credentials or invent analytics/verification IDs.

## Homebrew on macOS

```bash
brew install DeanDiasti/tap/fusion-cli
fusion-install-addin
fusion help
```

Formula source: [DeanDiasti/homebrew-tap](https://github.com/DeanDiasti/homebrew-tap).
It installs the source release, Python 3.14, and an isolated environment containing
explicit, checksummed SDK dependencies. It does not install Autodesk Fusion,
modify an open document, sign into Codex, or automatically replace the add-in.
The tap packages upstream SDK wheels for Apple Silicon and Intel Macs; it is a
third-party tap, not a Homebrew core submission. Core's dependency rules prohibit
a formula from depending on proprietary software such as Fusion.

The `fusion` wrapper provides the same typed CLI as `scripts/fusion`.
`fusion-install-addin` runs the existing transactional add-in installer using the
Homebrew environment. Save work, restart Fusion, and run CadBot from Scripts and
Add-Ins afterward. AI chat still requires Codex sign-in; offline help does not.

Save work and stop CadBot before upgrading:

```bash
brew update
brew upgrade DeanDiasti/tap/fusion-cli
fusion-install-addin
```

Run the add-in installer after every upgrade and before `brew cleanup` removes an
old environment. A running worker can retain its old version until restarted.
`fusion doctor` detects a different loaded CAD build. Uninstalling the formula does
not remove the separately installed add-in, bridge credentials, backup files, or
saved conversations. Stop/remove CadBot through Fusion if you no longer need it.

## Release maintenance

1. Run the relevant host and native validation and publication checks. Changes to
   CAD Python require a fresh native build certificate. Documentation or packaging
   changes do not prove additional CAD support.
2. Create an immutable version tag and GitHub release for the verified source.
3. Download that tag's source archive, compute SHA-256, and update the tap's formula
   URL/version/checksum. Do not move an already published release tag.
4. Resolve every Python dependency and its architecture-specific wheels to exact
   versions, URLs, and SHA-256 checksums. Review upstream compatibility and licenses.
   Do not enable unconstrained pip dependency downloads during formula installation.
5. Run `brew install --build-from-source DeanDiasti/tap/fusion-cli` and `brew test
   DeanDiasti/tap/fusion-cli`; check isolated add-in installation using a temporary
   destination. Tap CI runs on macOS and does not need a Fusion account.
6. Push the reviewed formula and confirm tap CI. Document which architectures
   actually ran the install tests; resource availability alone is not native validation.

The main repository's host CI and tap install tests are separate from live Fusion
geometry evidence. Use the release report for CAD support boundaries.
