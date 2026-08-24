# Station onboarding runbook

This runbook prepares a new Fire Detector Station to connect safely to the
central Receiver, publish Mount telemetry, and send simulated or real camera
frames. It is written for both operators and automation agents.

Never put a shared secret, enrollment token, private key, or a copy of a CA
private key in this repository, `AppSetting.JSON`, an issue, or chat.

## Architecture

```text
Station (outbound TLS/TCP :15001) ── Mount telemetry / camera events ──> Receiver
Station (HTTPS :8443) ── signed multipart image uploads ────────────────> Media service
Receiver ── WebSocket ─────────────────────────────────────────────────> Dashboard browser
```

The Station does not expose a remote Mount control port. The Mount Agent opens
the TLS connection to the Receiver, validates its CA, completes an HMAC
challenge, and reconnects with backoff if it is interrupted.

## Prerequisites

On the Station:

- Raspberry Pi OS with this repository and `.venv` installed.
- Tailscale connected and the Station has a stable tailnet IP.
- `fire-detector.service` installed and running as `pi`.
- The device ID, Station name/position, axis calibration, and camera metadata
  configured in `AppSetting.JSON`.

From the Server team:

- Receiver hostname/IP and TCP port (normally `15001`).
- HTTPS media-service base URL and port (normally `8443`).
- Receiver CA certificate, delivered to `/etc/fire-detector/receiver-ca.crt`.
- One-time Station enrollment authorization (token-based or Tailscale-IP-based).
- The current `station_enroll.py` download URL and its SHA-256 checksum.

## Install certificate and initial remote settings

Create the protected credential directory and install the CA. The private
shared secret is installed by enrollment; do not create it manually.

```bash
sudo install -d -o root -g pi -m 0750 /etc/fire-detector
sudo install -o root -g pi -m 0640 receiver-ca.crt /etc/fire-detector/receiver-ca.crt
```

Set `mount_agent.remote` in `AppSetting.JSON`. Use the values supplied by the
Server for the host, ports, and URL; this example deliberately contains no
secret value.

```json
{
  "enabled": true,
  "host": "<receiver-tailscale-ip>",
  "port": 15001,
  "server_name": "<receiver-tailscale-ip-or-dns-name>",
  "device_id": "<unique-device-id>",
  "ca_file": "/etc/fire-detector/receiver-ca.crt",
  "secret_file": "/etc/fire-detector/remote.secret",
  "secret_env": "",
  "media_upload_url": "https://<receiver-host>:8443/api/v1/media/upload",
  "heartbeat_sec": 15,
  "telemetry_sec": 0.2,
  "allowed_commands": [
    "system.hello",
    "system.get_info",
    "system.get_health",
    "mount.get_status"
  ]
}
```

The production allowlist above is read-only. Do not add motion commands unless
the safety review and Server authorization explicitly permit them.

## Station and camera registry metadata

The Station sends this static data in its first authenticated `hello` message:

- `device_id`, `station_name`, `latitude`, `longitude`,
  `elevation_above_ground_m`, `azimuth_north_offset_deg`.
- `visible_camera` and `thermal_camera` specifications from `camera_metadata`.

Use actual installation coordinates, not an IP-derived location. For the
SIP30-150-LWIR thermal module, configure the manufacturer values:

```json
{
  "native_width": 640,
  "native_height": 512,
  "frame_rate_hz": 50,
  "horizontal_fov_min_deg": 2.8,
  "horizontal_fov_max_deg": 14.2,
  "vertical_fov_min_deg": 2.3,
  "vertical_fov_max_deg": 11.4,
  "optical_zoom_x": 5,
  "focal_length_min_mm": 31,
  "focal_length_max_mm": 155,
  "digital_zoom_min_x": 1,
  "digital_zoom_max_x": 8,
  "palette_count": 16,
  "temperature_measurement": "min_max",
  "radiometric": false
}
```

`radiometric: false` means the Station does not claim to provide raw
per-pixel radiometric temperatures. It can still report the device's minimum
and maximum temperature measurements.

## Enroll the Station

Always download the helper anew and compare its checksum with the value from
the Server team before running it. Use the CA when downloading if the system
trust store does not already trust the Receiver certificate.

```bash
curl --fail --location --cacert /etc/fire-detector/receiver-ca.crt \
  --output /tmp/station_enroll.py \
  https://<receiver-dns-name>/station_enroll.py
sha256sum /tmp/station_enroll.py
```

For a Server-authorized Tailscale enrollment, run the exact one-time command
given by the Server team. This is the standard shape:

```bash
sudo python3 /tmp/station_enroll.py \
  --server https://<receiver-tailscale-ip>:8443 \
  --device-id <unique-device-id> \
  --ca /etc/fire-detector/receiver-ca.crt \
  --secret-path /etc/fire-detector/remote.secret \
  --secret-owner root \
  --secret-group pi \
  --secret-mode 0640 \
  --tailscale-authorized \
  --restart-service fire-detector.service
```

For token-based enrollment, pass the Server-delivered protected file with
`--token-file`; do not paste a token into a shell history or chat. After a
successful enrollment, delete that explicitly named temporary token file.

Verify the installed secret without displaying its contents:

```bash
stat -c '%A %a %U:%G %s %n' /etc/fire-detector/remote.secret
```

Expected owner/mode: `root:pi`, `640`.

## Media uploads and camera events

The Station uploads image bytes through HTTPS `multipart/form-data`, not over
the TLS telemetry socket. The current media API expects fields `metadata` and
`frame` and these signed headers:

- `X-Narit-Device-Id`
- `X-Narit-Timestamp`
- `X-Narit-Metadata-SHA256`
- `X-Narit-Frame-SHA256`
- `X-Narit-Signature`

The HMAC input is newline-separated:

```text
device_id
POST
/api/v1/media/upload
timestamp
metadata_sha256
frame_sha256
```

Use `storage_mode: "latest"` for continuous preview streams; Server atomically
replaces a stable `latest.png` or `latest.jpg`. Use `storage_mode: "archive"`
only for alarm/event frames. Include `rotation_deg` as exactly `0`, `90`, `180`,
or `270`; send `0` when the Station has already rotated pixels.

After a successful upload, publish `camera.frame_ready` over the existing TLS
connection with the returned `storage_url`; never attach image bytes to that
event. The Station also publishes compact `camera.telemetry` at 5 Hz with
Mount pointing and camera FOV/zoom state.

The simulator uses:

- `scripts/upload_simulated_thermal_frame.py` for both camera types.
- `fire-detector-simulated-thermal.service` for the `640x512` thermal feed.
- `fire-detector-simulated-visible.service` for the `1920x1080` visible feed.

Install and enable the optional simulator units only on development Stations:

```bash
sudo install -o root -g root -m 0644 \
  deploy/fire-detector-simulated-thermal.service \
  /etc/systemd/system/fire-detector-simulated-thermal.service
sudo install -o root -g root -m 0644 \
  deploy/fire-detector-simulated-visible.service \
  /etc/systemd/system/fire-detector-simulated-visible.service
sudo systemctl daemon-reload
sudo systemctl enable --now fire-detector-simulated-thermal.service
sudo systemctl enable --now fire-detector-simulated-visible.service
```

Do not enable simulated feeds on an operational Station after real cameras are
installed.

## Acceptance checks

```bash
systemctl is-active fire-detector.service
ss -ntp | rg ':15001'
journalctl -u fire-detector.service --since '5 minutes ago' --no-pager
curl --fail --silent http://127.0.0.1:8000/api/status
```

For a healthy Station, expect:

- `fire-detector.service` is `active`.
- Log line: `Remote mount protocol authenticated`.
- An established outbound TCP/TLS connection to the Receiver port.
- Local `/api/status` reports `connected: true` and `health: ready`.
- Media upload logs return stable `.../thermal/latest.png` and
  `.../visible/latest.jpg` URLs when simulators are enabled.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `AUTH_FAILED` or HTTP `401` | Re-enroll; verify the secret owner/mode and Server device record. |
| TLS certificate error | Confirm the CA file and `server_name`/certificate SAN match. |
| No Receiver connection | Check Tailscale status, TCP port `15001`, and `mount_agent.remote.enabled`. |
| Camera event but no image | Verify HTTPS endpoint, signed header hashes, and the returned `storage_url`. |
| Dashboard shows stale preview | Confirm `storage_mode: latest` and `Cache-Control: no-store` on the media URL. |
