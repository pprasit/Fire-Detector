#!/usr/bin/env bash
# Install on a newly provisioned station, after configuring camera credentials.
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
TARGET_USER="$(stat -c %U "$PROJECT_DIR")"
TARGET_GROUP="$(stat -c %G "$PROJECT_DIR")"
SETTINGS="$PROJECT_DIR/camera_runtime/system_settings.json"
[[ -x "$PROJECT_DIR/.venv/bin/python" ]] || { echo 'Run bootstrap_iriv.sh first.' >&2; exit 1; }
[[ -f "$SETTINGS" ]] || { echo 'Copy camera_runtime/system_settings.example.json to system_settings.json and configure both cameras first.' >&2; exit 1; }
# Never replace the running legacy camera service or interrupt an active scan.
if systemctl is-active --quiet wildlife-detection-runtime.service; then
    echo 'Legacy camera runtime is active. Stop its scan and service before migrating; see docs/NEW_STATION_TH.md.' >&2
    exit 1
fi
python3 - "$SETTINGS" <<'PY'
import json, sys
config = json.load(open(sys.argv[1]))
for name in ('thermal', 'visible'):
    cam = config.get('cameras', {}).get(name, {})
    if not all(cam.get(key) for key in ('ip', 'username', 'password', 'rtsp_url')):
        sys.exit(f'Configure {name} camera IP, credentials and RTSP URL before installation.')
if config.get('mission', {}).get('auto_sentry_enabled', False):
    sys.exit('Set mission.auto_sentry_enabled=false for first installation.')
PY
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libgomp1
runuser -u "$TARGET_USER" -- "$PROJECT_DIR/.venv/bin/python" -m pip install -r "$PROJECT_DIR/camera_runtime/requirements.txt"
chmod 0600 "$SETTINGS"
chown "$TARGET_USER:$TARGET_GROUP" "$SETTINGS"
sed -e "s|User=pi|User=$TARGET_USER|" -e "s|Group=pi|Group=$TARGET_GROUP|" \
    -e "s|/home/pi/Public/Fire-Detector|$PROJECT_DIR|g" \
    "$PROJECT_DIR/deploy/fire-detector-camera.service" > /etc/systemd/system/fire-detector-camera.service
systemctl daemon-reload
systemctl enable --now fire-detector-camera.service
for attempt in {1..30}; do
    if curl --fail --silent http://127.0.0.1:5005/api/telemetry >/dev/null; then
        echo 'Camera HTTP endpoint is responding; check actual image feeds next.'
        break
    fi
    if [[ "$attempt" == 30 ]]; then
        echo 'Camera endpoint did not start. Inspect journalctl -u fire-detector-camera.service.' >&2
        exit 1
    fi
    sleep 1
done
echo 'Camera runtime installed. Verify both live feeds and complete station acceptance before starting a scan.'
