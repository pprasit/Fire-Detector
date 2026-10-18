# Fire Detector

Python project for the Raspberry Pi based Fire Detector control and monitor system.

This repository includes the ODrive monitor/control dashboard and the deployed
thermal/visible camera, fire detection, NCNN model and panorama runtime in
`camera_runtime/`. Experimental Hailo pipelines remain outside this project.

**New Raspberry Pi:** follow [คู่มือติดตั้งเครื่องใหม่](docs/NEW_STATION_TH.md).
Local settings and runtime data are excluded from Git. Pulling source alone does
not install OS dependencies or supply camera credentials and axis calibration.

For the current project state and handoff notes, read [HANDOFF.md](HANDOFF.md).

The Station publisher page is available under **Settings → Software Updates**.
See [Software publishing UI](docs/SOFTWARE_UPDATES_UI.md) for HTTPS, signed-bundle
configuration, approval scope and the remaining build/agent integration.

For provisioning a Station for the central Receiver and media services, read
[Station onboarding runbook](docs/STATION_ONBOARDING.md).

For the authenticated daily pull-backup and confirm-before-delete workflow,
read [Station Backup Pull API](docs/BACKUP_PULL_API_TH.md).

## Simulated fire events

Generate three fire events at random times during the next 15 minutes. Each
event gets newly generated 15-second thermal and visible MP4 files, then the
videos are uploaded before the event is finalized:

```bash
python3 scripts/simulate_fire_events.py
```

The script reads the device ID, Receiver URL, CA, and protected shared-secret
path from `AppSetting.JSON`. It streams each upload from disk and enforces a
100 MiB simulator limit per video. Preview the generated event data and video
sizes without waiting or contacting the Receiver with:

```bash
python3 scripts/simulate_fire_events.py --dry-run --seed 42
```

Use `--server`, `--device-id`, `--station-id`, `--secret-file`, and `--ca` to
override Station configuration. Use `--window-sec 0` for an immediate test.

## Mission Design terrain view

The Mission Design panel renders an interactive WebGL terrain mesh from the
station DEM and satellite textures. **360° panorama** projects the 3D scene
from the configured station camera height into geographic bearing and altitude:
0°/360° true north, 90° east, 180° south, 270° west; altitude zero is the true
horizon. Camera markers and FOV corners are converted from mount coordinates
using the active Pointing Model and station north offset. The compact panel puts live position,
velocity and target telemetry next to its title. Toolbars are hidden to give
the terrain more height. Use the horizontal scrollbar or drag the panorama to
explore the full azimuth range; altitude labels stay fixed on the left. The
scrolling view is contained within the chart beside the live camera column.
The initial view centers on the live camera and expands its vertical range if
the compensated true altitude falls outside the default window. During manual
navigation, an edge arrow marks an offscreen camera; click it to return to the
real camera direction. The marker is never silently clamped to a false altitude.
Header telemetry and the scan-range summary remain explicitly labelled mount
coordinates; geographic display alignment does not change encoder calibration,
scan commands or safety limits.
Wheel zoom and display navigation do not change physical mount or camera zoom.
Wheel zoom smoothly scales both angular axes together (1–8×), rebuilding the
horizontal scroll track while keeping the geographic point under the cursor
fixed where the panorama boundaries permit. Shift-wheel scrolls horizontally.

Hover over terrain to see a thermal FOV preview at the selected planning zoom.
The compact chart footer shows the actual thermal optical FOV, chart angular
scale and imagery attribution. Hover coordinates and range, native sensor
sampling and navigation instructions are omitted to give the chart more room.
Source DEM and mesh spacing are available in the terrain-status tooltip.
The amber frame follows the **actual thermal optical FOV**, read from verified
live-frame metadata every 500 ms. It uses the current optical zoom, not the
hidden planning zoom. The dashed green frame remains a separate hover preview.
Stale, unverified or missing zoom metadata removes the amber frame and shows
an unavailable message rather than inventing a zoom value.

Thermal sampling uses the SIP30-150-LWIR datasheet's **640 × 512 native detector**:
average arcsec per sensor pixel = FOV in degrees × 3600 / native pixel count.
The readout separately reports geographic-axis arcsec per chart CSS pixel and
the projected FOV box size. Resizing/upscaling video does not create native
detector detail. Coverage is estimated from optical zoom/lens specifications;
unreported digital zoom/cropping is not included in the amber optical frame.
Refresh Mission Design after changing station or Pointing Model configuration.
The default **High** mode uses a 16-bit native DEM height texture and approximately
39 m mesh spacing across the 40 km footprint. Rendering detail remains limited
by the underlying DEM's survey resolution. The station caches high-precision elevation
assets separately, preserving the original GeoTIFF and existing map caches.

Terrain presentation uses soft daylight, neutral tone mapping and a small
vegetation saturation reduction. The panorama retains linear HDR colour in its
cube render target when floating-point rendering is supported, then applies
tone mapping at display time. Atmospheric haze follows sightline distance so
adjacent cube faces agree. Lighting and haze are illustrative rather than live
weather. They do not add canopy, buildings or new elevation samples; close-up
detail remains limited by the source DEM and satellite imagery.
The existing offline DEM panorama API remains available for image exports but
is not used as the interactive view's background.

## Mission Control worker

The Station polls the signed Mission API with its existing device credentials,
validates every revision against local mount/camera limits, applies safe
missions, stores applied state atomically, and ACKs only after successful
application. Install the worker with:

```bash
sudo install -o root -g root -m 0644 deploy/fire-detector-mission.service \
  /etc/systemd/system/fire-detector-mission.service
sudo systemctl daemon-reload
sudo systemctl enable --now fire-detector-mission.service
```

Runtime state is stored under `data/mission/`. Mission logs never include the
shared secret or generated HMAC signature.

## Station Configuration Sync

The Station polls the signed configuration endpoint every 2–5 seconds using
the Mission API HMAC credentials. A revision is accepted only as a complete,
strictly validated object and only when its position, velocity, and
acceleration values stay inside local and live drive limits. The active and
revision state files are durably replaced with temporary-file, `fsync`, and
rename semantics under `data/station_configuration/`; the last-known-good file
is retained through network, validation, or write failures.

Install the worker with:

```sh
sudo install -o root -g root -m 0644 deploy/fire-detector-configuration.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fire-detector-configuration.service
```

## ODrive USB Check

Create and install the Python environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Check the ODrive connected over USB:

```bash
.venv/bin/python scripts/check_odrive.py
```

Optional serial-number filter:

```bash
.venv/bin/python scripts/check_odrive.py --serial-number 59898476770354
```

If the script connects but reports low `vbus_voltage`, USB communication is
working but the ODrive DC bus/motor power supply is not active.

## Web Monitor

Install dependencies, then start the dashboard server on the Raspberry Pi:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/run_monitor.py --host 0.0.0.0 --port 8000
```

From a Windows machine on the same network, open:

```text
http://<raspberry-pi-ip>:8000
```

The monitor also exposes a JSON endpoint at:

```text
http://<raspberry-pi-ip>:8000/api/status
```

## Autostart and LAN Name

This project includes systemd/Avahi deployment files in `deploy/`.

Install the dashboard as a boot service:

```bash
sudo cp deploy/fire-detector.service /etc/systemd/system/fire-detector.service
sudo cp deploy/fire-detector-http.service /etc/avahi/services/fire-detector-http.service
sudo sed -i 's/^#host-name=foo$/host-name=firedetector/' /etc/avahi/avahi-daemon.conf
sudo systemctl daemon-reload
sudo systemctl enable --now fire-detector.service
sudo systemctl restart avahi-daemon.service
```

On a LAN that supports mDNS, open:

```text
http://firedetector.local:8000
```

Bare names like `http://firedetector:8000` depend on router/client DNS behavior.
Use the `.local` form when in doubt.

## Provision a New IRIV PiControl

The repository includes an idempotent bootstrap script for a Raspberry Pi OS
Bookworm installation on an IRIV PiControl CM4/CM5. It installs the IRIV board
support, SSH development tools, Codex CLI, GitHub CLI, Tailscale, ODrive USB
permissions, this Python environment, the dashboard service, Avahi/mDNS, and
the automatic updater.

Copy `scripts/bootstrap_iriv.sh` to the new IRIV, then run:

```bash
sudo bash scripts/bootstrap_iriv.sh
```

The script already contains the public half of the authorized Windows Codex
SSH key. The matching private key remains on the Windows workstation and must
never be copied into this repository. Use `--ssh-public-key-file PATH` only to
override the bundled public key.

The published station version is available on `main`. Run `--help` to see every
option. New stations start in simulation with automatic updates disabled until
hardware acceptance. Install the camera runtime separately using the new-station
runbook; bootstrap alone installs the mount dashboard.

After the required reboot, connect from Windows and authenticate Codex using
the headless device-code flow:

```text
ssh pi@iriv-production.local
codex login --device-auth
gh auth login --web --git-protocol https
cd /home/pi/Public/Fire-Detector
codex
```

Do not copy `~/.codex/auth.json` from another machine or put an OpenAI token,
GitHub password, or private SSH key in the bootstrap script. The default
production hostname is `iriv-production`; the dashboard is available at
`http://iriv-production.local:8000` or through the assigned Tailscale IP after
installation.

## Mission Design (desktop menu 07)

Open `/?view=mission` on the Station dashboard to design ordered Azimuth /
Altitude waypoints with independent Thermal / Visible target zoom, arrival
speed, and scan duration. Select a numbered point directly on the Scan Path to
open its draggable editor. Preview runs the ordered points once. The centre
Scan Path and vertically stacked camera views remain visible together without
a separate scan-pattern control. Reports and Settings are menu items 08 and 09.

The Panorama Mapping planner starts at Azimuth 0° / Altitude 0°, completes a
full 360° row, then steps downward using the effective Thermal vertical FOV
minus the requested edge overlap. Alternate rows reverse direction to avoid an
empty return rotation. The planner reads the Station's Thermal 1× horizontal
and vertical FOV plus lower Altitude limit from `/api/settings`; operators may
override those values, zoom, and overlap. These inputs are stored with the
browser draft. Its amber path remains a preview until the operator accepts it
as the main Mission path.

Drafts are saved in this browser's local storage and can be exported as CSV.
Camera panels use the same continuous live MJPEG transport as Camera View and
show the mount's **current** view at the incoming feed rate, not a prediction of a selected waypoint. Draft zoom values
and motion previews do not send hardware commands. The example angle/zoom
ranges are design constraints, not verified Station capabilities. Applying
waypoint missions to hardware is not implemented in this editor; the existing
Mission Control worker and its validation remain separate.
