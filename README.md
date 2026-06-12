# Fire Detector

Python project for the Raspberry Pi based Fire Detector control and monitor system.

This repository currently contains only the ODrive monitor/control dashboard.
Camera and Hailo detection experiments are intentionally outside this project.

For the current project state and handoff notes, read [HANDOFF.md](HANDOFF.md).

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
