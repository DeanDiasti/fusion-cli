# Security policy

Security fixes target the latest supported release. Older releases may receive
fixes when practical; no response or support deadline is guaranteed.

## Report a vulnerability privately

Use [GitHub's private vulnerability reporting form](https://github.com/DeanDiasti/fusion-cli/security/advisories/new).
Describe the affected version/build, reproduction with synthetic data, expected
trust boundary and observed impact. Do not open a public issue containing an
exploit, bridge token, Codex credentials, private CAD model or account identifiers.
A maintainer will coordinate disclosure after reviewing the report.

## Trust boundaries

The bridge binds to loopback and authenticates using `X-CadBot-Token`. The installer
creates an owner-only random `.bridge_token` and preserves an existing token.
The uninstalled development fallback is a known test value: use the installer or
an explicit private `CADBOT_BRIDGE_TOKEN` for real designs. Authentication protects
a single-user local workflow; this is not a multi-user or remote CAD service.

Do not expose port 8765 through forwarding, tunnels, proxies or a public interface.
Treat same-user local processes, the running Fusion application and the Codex
worker as trusted parts of the installation. Keep the project checkout and its
virtual environment protected from untrusted writes.

The CAD tool exposes a finite command grammar. Raw editing/administration calls,
shell evaluation and arbitrary Python execution are disabled. CAD API work runs
on Fusion's main thread. Design mutations require tracked message transactions;
previews abort and verify model/pose restoration. Other operation classes have
separate side effects and can invalidate Design checkpoints.

Timeouts and cancellation do not prove an in-progress native call stopped. Inspect
state before retrying. Native Fusion APIs and PTransaction behavior are runtime
specific; use saved work and disposable fixtures when validating upgrades.

## Data handling

AI chat can send prompts, reference images, requested CAD tool results and
screenshots to Codex. Select only data you intend to use with that service. Saved
conversations and reference attachments remain in the user's application-support
history directory; they are not repository artifacts. The terminal CLI and
read-only help do not invoke a model by themselves.

Ignore credentials, history, logs, private designs and runtime configuration.
Raw validation reports can contain account metadata even when the geometry is
synthetic. Publish the redacted summaries described in `docs/validation.md`.
The publication scanner detects selected patterns; manual review is still needed.
