# Station Software Updates

Current workflow: sign in with the Server Dashboard administrator account →
automatically load **changed** source files on entry/Refresh → open captured file/diff previews in new tabs →
Approve & Release using the same session → stream draft upload with byte progress
→ verify Server acceptance → push the exact commit to GitHub → optionally start
deploy through the Server Dashboard. No password confirmation is requested after login.

Running version is independent of approval and now includes a generated runtime
ID. The initial local runtime starts at `1.0.0`; the first proposed publication is
`1.0.1`. Actual installation agents must supply installed-manifest identity.

The page automatically captures the changed-file list on entry and Refresh.
There is no separate review button, review checkbox or release-package panel.
The compact approval card has no publication-scope dropdown or target input.
New browser publications create drafts; fleet deployment remains a separate
server action. Readiness warnings do not disable approval;
Approve & Release is available when a source snapshot has changes and no job is
running. Readiness problems are explained separately. Authentication, exact
snapshot checks, signature validation and the explicit rollout action still
apply on the backend. See [Release builder integration](RELEASE_BUILD_HELPER.md).

## Login and HTTPS



Opening Software Updates first requires a server Dashboard administrator login.
The Station uses the real `/api/auth/login` and `/api/auth/status` endpoints over
verified HTTPS. The upstream `__Host-narit_session` cookie stays in Station
process memory, never in JavaScript, logs or files. A separate opaque Secure,
HttpOnly, SameSite=Strict Station cookie authorizes access for up to 30 minutes.
The Server account and administrator role are rechecked on every management
request; anonymous requests cannot read source/status/plan data. Logout removes
both local sessions and attempts to revoke the upstream Dashboard session.

Login works without a signed bundle. Source review and review-plan download are
available after login. Publication requires an explicit review approval after login. The login alone
does not start a build, upload or rollout. Build/signing and the fleet install
agent require the integrations described in RELEASE_BUILD_HELPER.md.

The Station's HTTP entry redirects to its configured HTTPS browser origin.
The production Station now uses Tailscale Serve at
`https://iriv-production.tailc95dd4.ts.net/software-updates` (Tailnet only), while
local mount/worker HTTP endpoints remain on port 8000. Authentication uses the
same Server Dashboard account store through its trusted Tailnet HTTPS origin.

## Configuration

Set these environment variables in the dashboard service's override, using
actual reviewed values supplied by the Server team:

```ini
[Service]
Environment=FIRE_UPDATE_BROWSER_ORIGIN=https://iriv-production.tailc95dd4.ts.net
Environment=FIRE_UPDATE_SERVER=https://narit-fire-detector.tailc95dd4.ts.net
Environment=FIRE_UPDATE_BUNDLE=/var/lib/fire-publisher/releases/RELEASE_ID
Environment=FIRE_UPDATE_VERIFY_KEY=/etc/fire-detector/release-verification.pem
Environment=FIRE_UPDATE_VERIFY_KEY_ID=SERVER_KEY_ID
# Only when the Server uses a private CA:
# Environment=FIRE_UPDATE_CA=/etc/fire-detector/update-server-ca.crt
# Only for a TLS reverse proxy connecting from loopback:
# Environment=FIRE_UPDATE_TRUST_LOCAL_PROXY=1
```

`FIRE_UPDATE_BUNDLE` must contain `manifest.json` (complete signed envelope) and
`artifact.tar.gz`, following the deployed Server publisher format, not a GitHub
source tarball. Keep the directory outside the repository/static web root, owned
by the trusted provisioning account and not mutable by web users. The configured
key is an Ed25519 **public** PEM, bound to the exact `key_id`. Manifests use the
Server's canonical JSON: sorted keys, compact separators, ASCII escaping and no
NaN. Do not edit a bundle in place; install a new immutable directory and switch
the configuration during planned provisioning.

No bundle/key is provisioned automatically. There is no endpoint for uploading
private signing keys, changing the Server URL, supplying arbitrary local paths,
executing shell commands, or accepting executable archive content from a browser.
The Server remains responsible for full archive, dependency and profile checks.

## HTTPS on the Station

The existing mount API listens on HTTP port 8000 and its local workers depend
on it. Preserve that endpoint. Put a TLS reverse proxy in front of it for browser
access, with a certificate trusted by the operator's computer. Example location
inside an already-configured HTTPS virtual host:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto https;
}
```

Explicitly configure `FIRE_UPDATE_TRUST_LOCAL_PROXY=1` only for this setup. A
forwarded HTTPS header is accepted only from loopback; direct LAN clients cannot
enable password submission by forging it. Management metadata and actions require server login over HTTPS. All publisher
POSTs refuse plain HTTP. Do not disable certificate checks or
send passwords through a plain-HTTP Station URL. The publisher Server origin is
always HTTPS with hostname validation; redirects are not followed.

The page uses same-origin JSON requests plus an explicit intent header, never
cross-origin password forms. Server approval tokens remain in memory, indexed
by an opaque `Secure; HttpOnly; SameSite=Strict` cookie; no password or token is
written to disk, returned to JavaScript or stored in browser localStorage.
Restarting the dashboard drops login and approval sessions. Logout drops the local grant;
the remote scoped token expires within ten minutes. No passwords are retained or refreshed. Interrupted jobs require reconciliation
before retrying remote mutations.

Restarting to load routes/configuration must wait for a planned safe stop of
scan/sentry and motors. No production service was restarted during development.
Existing camera migration and installation-agent acceptance remain separate.


## Simple publication controls

The page has Stop / Resume and Cancel update, with automatic server-status
checks. Optional target input and manual status buttons are removed; new browser
publications create drafts without implicitly selecting any fleet stations.
Previously approved target lists remain scoped to their original release.

Transfer percentages apply only to the active transfer, including the unsigned
package sent for signing. They are hidden and the bar returns to zero when the
phase ends. A completed upload alone is never publication success. The message
"Original ready to deploy" requires completed publication, an exact verified
durable Server receipt, and successful GitHub push of that candidate SHA.
Known signing failures show failure rather than indefinite reconciliation.

Stop retains the candidate/output and pauses the sender at a checkpoint (the
helper sender is suspended while paused). Resume continues that same job. A
long pause may exceed a remote connection timeout; a later Resume reconciles
and retries the same immutable release, potentially retransmitting bytes.
Tests already running in the separate native sandbox may finish while the
publication sender is stopped. Pause time is excluded from the helper deadline.

Cancel during build/upload preserves the original worktree/index/HEAD. A lost
upload response remains unconfirmed until an exact receipt is obtained. Cancel
can cancel queued signing or deployment work through Server; it cannot revoke
an existing signature, remove an immutable accepted draft, undo a GitHub push
or promise rollback on a Station already installing. Actual remote cancellation
must be confirmed. Accepted drafts/backups remain for inspection.

Source origin is captured from this Station's configured device ID, sent as
`X-Narit-Station-ID` on both signing and release uploads, and included in signed
manifest notes. The browser cannot choose a different source ID. Server-side
station/account permission mapping remains a separate Server change.
