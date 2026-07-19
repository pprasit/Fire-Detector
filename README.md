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
support, SSH development tools, Codex CLI, ODrive USB permissions, this Python
environment, the dashboard service, Avahi/mDNS, and the automatic updater.

Copy `scripts/bootstrap_iriv.sh` to the new IRIV, then run:

```bash
sudo bash scripts/bootstrap_iriv.sh
```

The script already contains the public half of the authorized Windows Codex
SSH key. The matching private key remains on the Windows workstation and must
never be copied into this repository. Use `--ssh-public-key-file PATH` only to
override the bundled public key.

If the current production code has not been merged to `main`, select its branch
explicitly with `--branch <branch-name>`. Run `--help` to see every option.

After the required reboot, connect from Windows and authenticate Codex using
the headless device-code flow:

```text
ssh pi@firedetector.local
codex login --device-auth
cd /home/pi/Public/Fire-Detector
codex
```

Do not copy `~/.codex/auth.json` from another machine or put an OpenAI token in
the bootstrap script. The dashboard is available at
`http://firedetector.local:8000` after installation.
