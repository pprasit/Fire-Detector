# Station release builder integration

The browser now uses the administrator's existing Server Dashboard session.
It does not submit a second password or use Station HMAC credentials for publishing.
Server upload and rollout requests carry that session cookie and the Server's
HTTPS Origin. The existing Server implementation supports administrator sessions
for these operations; the scoped CLI approval-token workflow remains separate.

## Installed integration (2026-10-17)

The server-provided archive was downloaded using the signed-in owner's session,
checked against SHA-256 `defea22dc88c1657901643a486a6f4f791fcf78aad3c3536001117505b1adfe7`,
and every module hash in TOOLING.json was checked before installation.
The root-owned helper is `/opt/narit-publisher/build-signed-release`, revision
`494d3880e0b01a0b159b78e0312f9ec52998857f492a78c3f2258c09f9c475ab`.
The verification key is `release-20261017`; the private signing key stays on Server.

The Station uses the existing trusted tailnet HTTPS Server origin for both
Dashboard login and helper requests. Public and tailnet hosts were reachable;
the unauthenticated build endpoint correctly rejected access. The browser's
Check publisher readiness action verifies the real administrator-owned connection,
pinned revision/key, server allowlist and current signer heartbeat.

The backend sends this owner's session on an inherited pipe using
FIRE_UPDATE_SESSION_FD and pass_fds. Credentials are absent from arguments,
environment values, job JSON and browser responses. The trusted helper keeps
that descriptor out of the application test sandbox.

`requirements-bookworm-aarch64.lock` pins the complete runtime/camera/test wheel
set with SHA-256 hashes. Wheels are provisioned read-only under
`/var/lib/narit-publisher/wheelhouse-bookworm-aarch64`. Native build settings and
the exact source inventory are in `/etc/narit-publisher/native-build.json`.
Changes adding new source paths require updating that inventory; unlisted
reviewed files block publication instead of silently disappearing from a release.

The source template for the stream credential service is now
`deploy/fire-detector-stream-auth.service`, because the builder prohibits
credential-named non-code archive members. This renames the repository template
only; no installed/running service was renamed or restarted by that change.

## Authentication, progress and recovery

The helper reports isolated build, unsigned signing-upload bytes and signing-job
state separately. Draft upload progress resets and reports its own actual bytes.
After upload, Station reads `/api/updates/releases/<id>/receipt` and requires an
exact durable size/hash/envelope-hash/commit/version/release match, with no rollout
started, before the same candidate SHA may be pushed to GitHub.

Interrupted signing/upload jobs preserve their candidate and private worktree.
The explicit Resume action uses the same release ID, source commit,
output directory and helper idempotency contract. It never creates a replacement
commit or force pushes. An already accepted draft is not uploaded again when
retrying GitHub. Cancellation with uncertain remote outcome remains interrupted;
it is not described as a completed rollback. No rollout starts automatically.

## Executable contract

Configure a trusted executable **outside the application checkout**:

```ini
[Service]
Environment=FIRE_UPDATE_BUILD_HELPER=/opt/narit-publisher/build-signed-release
Environment=FIRE_UPDATE_VERIFY_KEY=/opt/narit-publisher/release-20261017.pub
Environment=FIRE_UPDATE_PUBLIC_KEY=/opt/narit-publisher/release-20261017.pub
Environment=FIRE_UPDATE_KEY_ID=release-20261017
Environment=FIRE_UPDATE_BUILD_CONFIG=/etc/narit-publisher/native-build.json
Environment=FIRE_UPDATE_VERIFY_KEY_ID=release-20261017
# Optional; defaults to a private sibling directory outside the checkout:
# Environment=FIRE_UPDATE_STATE_DIR=/var/lib/fire-detector-publisher
# Optional; the successful source is pushed to main and the development branch:
# Environment=FIRE_UPDATE_GITHUB_BRANCH=main
```

The worker invokes it directly, without a shell:

```text
/opt/narit-publisher/build-signed-release
  --source /private/job/source
  --commit <full candidate Git commit>
  --version 1.0.1
  --release-id release-1.0.1-<unique suffix>
  --output /private/job/bundle
```

- `source` is a detached worktree containing the approved candidate commit.
  It is not the running Station checkout. No live settings, credentials or
  recordings are copied from the Station's working directory.
- Use the trusted `update_system` publisher tooling from the deployed Server
  revision. Build from a reviewed exact-file allowlist, committed hash lock and
  offline wheels on the required Pi/OS/Python profile. Run the actual application
  tests in the isolated environment. Do not use the developer's installed venv
  as proof that the package can be installed offline.
- Perform Ed25519 signing on the authorized signing host. The helper may
  delegate through an authenticated service, but its transport and ownership
  checks need review; there is no invented fallback endpoint here.
- Output `artifact.tar.gz` and `manifest.json` in the requested directory. The
  manifest is the COMPLETE signed Server envelope `{manifest,key_id,signature}`.
  `release_id`, `version`, and `git_commit` must match the requested values.
- The application validates the signature, trusted key ID, artifact size and
  SHA-256, source commit, version and release ID before uploading.
- Exit nonzero on failure. No upload or rollout may be performed by the helper.
  Do not print credentials or private keys. Diagnostic output is kept in the
  private job directory, never relayed to the browser.
- Cancellation terminates the helper process group. The helper must propagate
  cancellation to any remote signing/build job it creates. Its server-side
  cleanup contract must be documented before deploying that integration.

## Worker transaction and recovery

Review captures only Added/Modified/Deleted eligible source paths against HEAD,
including their exact bytes. A file preview shows that captured copy and diff,
not a file that silently changes after review. Private/persistent paths and
symlinks are rejected. Authentication is required for previews as well as APIs.

Approval creates a candidate commit using a **private Git index** and a detached
worktree. The real working directory, HEAD and staged user changes are preserved.
Existing staged changes require review with Codex before publication. A source
edit or HEAD change after review invalidates that candidate.

The worker streams upload bytes and reports actual bytes sent and total size.
100% sent is not acceptance: it waits for the Server response, then verifies the
exact durable disk receipt from the Server. Only then does it push the same
commit to GitHub main, the development branch and a version tag in one atomic,
non-forced operation. GitHub rejection is reported separately from Server upload
success. The release remains an inert draft until the explicit Start rollout
button is pressed for the approved station IDs.

After successful push, local HEAD/index are advanced only if they still match
the reviewed base and the index has no new staged edits. Working files are never
overwritten. Concurrent edits remain as local work. If local reconciliation
cannot be done safely, the job records that fact instead of resetting the repo.

Cancel during build leaves original source/index/HEAD unchanged. Cancel during
upload closes the sender at its next cancellation checkpoint. A lost response
cannot establish whether the Server already stored the draft: such a job is
reported as interrupted and requires reconciliation, not “rolled back”. Cancel
after Server acceptance cannot delete an immutable release or undo a GitHub push.
Cancel rollout calls the Server's cancellation API; stations already installing
may finish. Installation rollback requires separate Server/agent evidence.

Jobs are persisted atomically without server cookies or passwords. Restart marks
unfinished work interrupted; it does not automatically retry an upload or GitHub
push with unknown outcome. Source snapshots/private refs remain for inspection.

## Runtime numbering

Runtime identity is independent of publication approval. On first use, current
source is recorded as `1.0.0` with `run-0001-<content fingerprint>`. Its fingerprint
is captured at application startup and is not recomputed to relabel already
running code after edits. A changed development tree at a subsequent start gets
a new runtime ID/development revision. Production installation agents should set
`FIRE_DETECTOR_RELEASE_VERSION` from the verified installed manifest.

The first proposed publication is `1.0.1`; accepted releases increment the patch
number persistently. IDs/checksums are not evidence of approval or installation.

## Validation limits

Unit/integration tests use temporary Git repositories, a temporary Ed25519 signer,
a synthetic package, a simulated Server response and a local bare Git remote.
They test real snapshot commits and real atomic pushes without touching GitHub,
production keys, accounts or Stations. A real native offline build is also checked separately during installation.
Production signing/upload/GitHub publication is exercised only after the owner
approves a release in the web UI. Fleet installation/rollback remains a separate
canary test and is not implied by successful publication.

## Installation validation

A fresh offline environment installed all 65 pinned wheels with hash checking.
The trusted unmodified helper sandbox built an actual unsigned application
package on this Pi, including the ARM camera modules and the configured release
test command. No source/tests ran on Server. The local evidence is saved outside
the checkout in `native-build-readiness.json`. This check did not request a
signature, upload a draft, push GitHub or start rollout.

Hardware-free test collection now tolerates unavailable GPIO detection; the
beacon process itself still refuses startup without a GPIO backend. Control
worker tests use synthetic settings, a test-only key and a mocked TLS context
instead of reading the Station's production settings, key or certificate.

## Source Station ID contract

Station captures `mount_agent.remote.device_id` from its own settings at approval
time as `source_station_id` in the private job record. Browser-supplied origin
IDs are rejected. The captured value survives pause/resume and is not changed
when live settings change. Jobs created before this metadata was supported
require a new approval rather than silently attributing an old snapshot.

Both unsigned signing uploads (`POST /api/updates/builds`) and signed draft
uploads (`POST /api/updates/releases`) send `X-Narit-Station-ID: <source ID>`.
The current pinned Server helper is launched through the Station's header adapter;
its installed code/fingerprint and signed manifest schema are not modified.
The adapter adds the header only to update requests on the configured HTTPS
Server origin. It preserves the private session descriptor contract.

The per-job build configuration also appends `Source Station ID: <source ID>` to
manifest notes. This makes origin visible in the existing Server's stored build
manifest/release metadata and covered by its signature, without introducing an
unsupported manifest field or altering the root-owned base build configuration.

For future per-station permission handling, Server should validate/log the
header as structured `source_station_id` alongside the authenticated account,
build job, release ID and candidate commit, and preserve it in receipts/audit.
Header/note values alone do not authenticate a Station or grant privileges;
Server must authorize the account for that Station ID. Current Server schemas
do not yet persist this header as a separate field or enforce that mapping.

## Station-ID adapter fix (2026-10-18)

The Station header adapter uses a helper-local HTTP client proxy. It must not
replace `http.client.HTTPSConnection` globally: Python 3.11 resolves that global
name in its superclass initializer, causing recursion before the first network
request. The regression test exercises the adapter entrypoint and the real
stdlib constructor, not only its header factory.

The installed pinned helper was also exercised against a temporary verified
local TLS signing simulator: five real HTTP requests included Station ID, an
Ed25519 test fixture was verified, and the helper completed without publishing
a release or starting rollout. Native offline package construction is tested
separately; none of these checks uses the owner's session or production signer.
Safe helper exception type and HTTP status are retained for diagnostics without
logging session cookies or arbitrary exception text.
