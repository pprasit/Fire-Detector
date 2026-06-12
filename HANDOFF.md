# Fire Detector Handoff

Last checked: 2026-06-12 on Raspberry Pi host `iriv`.

This document is for continuing work in `/home/pi/Public/Fire-Detector` from another Codex account or shell session.

## Scope

This project is only the Fire Detector ODrive monitor/control dashboard.

Do not mix in the separate camera or Hailo detection files from the Desktop folder. Those are not part of this repository's current scope.

## Current Status

- Repository path: `/home/pi/Public/Fire-Detector`
- Git state: local repo exists, but there are no commits yet.
- Python virtualenv: `.venv` exists and can import `Flask` and `odrive`.
- Dashboard server is not currently running by default.
- Two ODrive USB devices are visible and readable.
- Motor/DC bus power is not present right now; both drives report about `0.04 V` on `vbus`.
- Both axes currently report `active_errors = 513`.
- Raspberry Pi IP observed on LAN: `192.168.1.111`.

Observed ODrive mapping:

| Axis | Serial | Notes |
| --- | --- | --- |
| Azimuth | `59898476770354` | First ODrive returned by `connect_many(count=2)` |
| Altitude | `59812575523890` | Second ODrive returned by `connect_many(count=2)` |

## What The App Does

The Flask app starts a background polling thread that reads two single-axis ODrive controllers over USB.

The web dashboard shows:

- Azimuth and Altitude axis status
- Position, velocity, current, state, errors, and armed status
- Per-drive serial, firmware, hardware, bus voltage, and bus current
- 60-second live charts for position, velocity, or current
- Tuning inputs for ODrive controller/trap trajectory parameters
- Optional Azimuth CW/CCW GPIO sensor status

The dashboard also lets the user apply tuning values and save ODrive configuration to a drive.

## Important Files

| File | Purpose |
| --- | --- |
| `README.md` | Basic setup and run commands |
| `HANDOFF.md` | This continuation note |
| `AppSetting.JSON` | Saved UI/app settings, tuning step sizes, and optional GPIO sensor pins |
| `requirements.txt` | Python dependencies |
| `scripts/check_odrive.py` | Quick single-ODrive USB connectivity check |
| `scripts/run_monitor.py` | Starts the Flask dashboard |
| `src/fire_detector/odrive_connection.py` | ODrive connection/status helpers |
| `src/fire_detector/web_server.py` | Flask app, API routes, ODrive monitor thread, settings handling |
| `web/templates/index.html` | Dashboard HTML |
| `web/static/js/dashboard.js` | Dashboard polling, rendering, charts, tuning interactions |
| `web/static/css/dashboard.css` | Dashboard styling |

## Run Commands

From the repo root:

```bash
cd /home/pi/Public/Fire-Detector
```

Check Python dependencies:

```bash
.venv/bin/python -c "import flask, odrive; print('ok')"
```

Check ODrive USB connectivity:

```bash
.venv/bin/python scripts/check_odrive.py
```

Run the dashboard:

```bash
.venv/bin/python scripts/run_monitor.py --host 0.0.0.0 --port 8000
```

Open from another machine on the same network:

```text
http://192.168.1.111:8000
```

Read JSON status directly:

```bash
curl http://127.0.0.1:8000/api/status
```

## API Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Dashboard page |
| `GET` | `/api/status` | Current ODrive and sensor status |
| `GET` | `/api/settings` | Current app settings from `AppSetting.JSON` |
| `POST` | `/api/settings` | Update app settings |
| `POST` | `/api/tuning/<axis_label>` | Apply tuning values to `Azimuth` or `Altitude` |
| `POST` | `/api/tuning/<axis_label>/save` | Save tuning configuration to the selected drive |

## Current Hardware Notes

The Pi can see both ODrives on USB:

```text
Bus 004 Device 005: ID 1209:0d32 Generic ODrive Robotics ODrive
Bus 004 Device 004: ID 1209:0d32 Generic ODrive Robotics ODrive
```

Recent dual-drive status check:

```text
devices 2
serials (59898476770354, 59812575523890)
vbus 0.04373008757829666
axes [
  ('Azimuth', True, 1, 513, 59898476770354, 0.04036623239517212),
  ('Altitude', True, 1, 513, 59812575523890, 0.04373008757829666)
]
```

Interpretation:

- USB communication is working.
- DC bus/motor power is not on, or not reaching the ODrives.
- The dashboard will likely show `USB only` until motor power is restored.
- Do not assume tuning/motion behavior is valid until the bus voltage and ODrive errors are resolved.

## Settings Notes

`AppSetting.JSON` currently stores:

```json
{
  "azimuth_sensors": {
    "ccw_active_high": true,
    "ccw_pin": null,
    "cw_active_high": true,
    "cw_pin": null
  },
  "tuning_steps": {
    "Altitude": {},
    "Azimuth": {
      "position_gain": 0.5
    }
  }
}
```

The GPIO sensor pins are unset. If limit sensors are wired later, set BCM pin numbers for `ccw_pin` and `cw_pin`.

## Verification Already Done

These checks passed:

```bash
.venv/bin/python -m py_compile scripts/check_odrive.py scripts/run_monitor.py src/fire_detector/odrive_connection.py src/fire_detector/web_server.py
.venv/bin/python -c "import flask, odrive; print('ok')"
```

ODrive USB check also succeeded, but reported low DC bus voltage.

## Suggested Next Steps

1. Turn on or verify ODrive DC bus/motor power.
2. Re-run `.venv/bin/python scripts/check_odrive.py`.
3. Confirm `vbus_voltage` is at the expected motor supply voltage.
4. Investigate and clear `active_errors = 513` on both drives.
5. Start the dashboard on port `8000` and verify `/api/status`.
6. Make the first git commit once the current baseline is accepted.

## Security Note

The Pi currently prints this warning when commands run:

```text
SSH is enabled and the default password for the 'pi' user has not been changed.
```

Change the password with:

```bash
passwd
```

