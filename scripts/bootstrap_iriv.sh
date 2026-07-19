#!/usr/bin/env bash
# Provision an IRIV PiControl (CM4/CM5) as a Fire Detector development target.
# Run this script on Raspberry Pi OS as root, for example:
#   sudo bash bootstrap_iriv.sh --ssh-public-key-file /boot/firmware/id_ed25519.pub

set -Eeuo pipefail

TARGET_USER="pi"
PROJECT_DIR="/home/pi/Public/Fire-Detector"
REPO_URL="https://github.com/pprasit/Fire-Detector.git"
BRANCH="main"
DEVICE_HOSTNAME="firedetector"
SSH_PUBLIC_KEY_FILE=""
INSTALL_IRIV_SUPPORT=1
INSTALL_CODEX=1
ENABLE_UPDATER=1
REBOOT_WHEN_DONE=0

log() {
    printf '\n==> %s\n' "$*"
}

warn() {
    printf '\nWARNING: %s\n' "$*" >&2
}

die() {
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: sudo bash bootstrap_iriv.sh [options]

Options:
  --user USER                 Linux user that will own Codex and the project (default: pi)
  --project-dir PATH          Clone destination (default: /home/pi/Public/Fire-Detector)
  --repo URL                  Git repository URL
  --branch NAME               Branch to install and track (default: main)
  --hostname NAME             LAN hostname and mDNS name (default: firedetector)
  --ssh-public-key-file PATH  Add this public key to USER's authorized_keys
  --skip-iriv-support         Do not run Cytron's IRIV PiControl setup script
  --skip-codex                Do not install Codex CLI
  --disable-updater           Install the web service but not the automatic updater timer
  --reboot                    Reboot automatically after a successful installation
  -h, --help                  Show this help

The script is designed for Raspberry Pi OS Bookworm on an IRIV PiControl CM4/CM5.
It is safe to run again. Existing project changes are never overwritten.
EOF
}

while (($#)); do
    case "$1" in
        --user)
            TARGET_USER="${2:?Missing value for --user}"
            shift 2
            ;;
        --project-dir)
            PROJECT_DIR="${2:?Missing value for --project-dir}"
            shift 2
            ;;
        --repo)
            REPO_URL="${2:?Missing value for --repo}"
            shift 2
            ;;
        --branch)
            BRANCH="${2:?Missing value for --branch}"
            shift 2
            ;;
        --hostname)
            DEVICE_HOSTNAME="${2:?Missing value for --hostname}"
            shift 2
            ;;
        --ssh-public-key-file)
            SSH_PUBLIC_KEY_FILE="${2:?Missing value for --ssh-public-key-file}"
            shift 2
            ;;
        --skip-iriv-support)
            INSTALL_IRIV_SUPPORT=0
            shift
            ;;
        --skip-codex)
            INSTALL_CODEX=0
            shift
            ;;
        --disable-updater)
            ENABLE_UPDATER=0
            shift
            ;;
        --reboot)
            REBOOT_WHEN_DONE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

[[ ${EUID} -eq 0 ]] || die "Run this script with sudo or as root."
[[ -r /etc/os-release ]] || die "Cannot identify the operating system."

# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}" in
    debian|raspbian) ;;
    *) warn "This script was written for Raspberry Pi OS/Debian; detected ${PRETTY_NAME:-unknown}." ;;
esac

id "$TARGET_USER" >/dev/null 2>&1 || die "Linux user '$TARGET_USER' does not exist. Create it first."
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]] || die "Home directory for '$TARGET_USER' is unavailable."

if [[ "$PROJECT_DIR" == "/home/pi/Public/Fire-Detector" && "$TARGET_USER" != "pi" ]]; then
    PROJECT_DIR="$TARGET_HOME/Public/Fire-Detector"
fi

if [[ -n "$SSH_PUBLIC_KEY_FILE" ]]; then
    [[ -f "$SSH_PUBLIC_KEY_FILE" ]] || die "SSH public key file not found: $SSH_PUBLIC_KEY_FILE"
    grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-|sk-ssh-|sk-ecdsa-)' "$SSH_PUBLIC_KEY_FILE" \
        || die "The supplied file does not look like an OpenSSH public key."
fi

log "Installing Raspberry Pi development and runtime packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    avahi-daemon \
    build-essential \
    ca-certificates \
    curl \
    git \
    htop \
    jq \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    openssh-server \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    ripgrep \
    tmux \
    usbutils

log "Configuring SSH and the LAN hostname"
hostnamectl set-hostname "$DEVICE_HOSTNAME"
install -d -m 0755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/20-fire-detector.conf <<'EOF'
PubkeyAuthentication yes
PermitRootLogin no
X11Forwarding no
EOF
sshd -t
systemctl enable --now ssh.service avahi-daemon.service

install -d -m 0700 -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.ssh"
touch "$TARGET_HOME/.ssh/authorized_keys"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.ssh/authorized_keys"
chmod 0600 "$TARGET_HOME/.ssh/authorized_keys"
if [[ -n "$SSH_PUBLIC_KEY_FILE" ]]; then
    PUBLIC_KEY="$(tr -d '\r\n' < "$SSH_PUBLIC_KEY_FILE")"
    grep -Fqx "$PUBLIC_KEY" "$TARGET_HOME/.ssh/authorized_keys" \
        || printf '%s\n' "$PUBLIC_KEY" >> "$TARGET_HOME/.ssh/authorized_keys"
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
    ufw allow OpenSSH
    ufw allow 8000/tcp
fi

if ((INSTALL_IRIV_SUPPORT)); then
    log "Installing IRIV PiControl board support from Cytron"
    IRIV_SETUP="$(mktemp)"
    trap 'rm -f "${IRIV_SETUP:-}"' EXIT
    curl --fail --location --proto '=https' --tlsv1.2 \
        https://tinyurl.com/setup-iriv-picontrol -o "$IRIV_SETUP"
    bash "$IRIV_SETUP"
    rm -f "$IRIV_SETUP"
    trap - EXIT
else
    warn "IRIV vendor support was skipped. USB host, RTC, I2C, OLED, and safe-shutdown support may be unavailable."
fi

log "Installing ODrive USB permissions"
cat > /etc/udev/rules.d/91-odrive.rules <<'EOF'
# ODrive native USB interface (0d30-0d39) and STM32 DFU bootloader.
SUBSYSTEM=="usb", ATTR{idVendor}=="1209", ATTR{idProduct}=="0d3[0-9]", MODE="0666", ENV{ID_MM_DEVICE_IGNORE}="1"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="df11", MODE="0666"
EOF
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb || true
getent group plugdev >/dev/null || groupadd --system plugdev
usermod -aG dialout,plugdev "$TARGET_USER"

log "Cloning the Fire Detector project"
install -d -m 0755 -o "$TARGET_USER" -g "$TARGET_USER" "$(dirname "$PROJECT_DIR")"
if [[ -d "$PROJECT_DIR/.git" ]]; then
    CURRENT_REMOTE="$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null || true)"
    [[ "$CURRENT_REMOTE" == "$REPO_URL" ]] \
        || die "Existing checkout uses a different origin: ${CURRENT_REMOTE:-none}"
    if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]]; then
        die "Existing checkout has local changes; refusing to overwrite it."
    fi
    runuser -u "$TARGET_USER" -- git -C "$PROJECT_DIR" fetch origin "$BRANCH"
    runuser -u "$TARGET_USER" -- git -C "$PROJECT_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
else
    runuser -u "$TARGET_USER" -- git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$PROJECT_DIR"
fi

log "Creating the Python environment"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    runuser -u "$TARGET_USER" -- python3 -m venv "$PROJECT_DIR/.venv"
fi
runuser -u "$TARGET_USER" -- "$PROJECT_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
runuser -u "$TARGET_USER" -- "$PROJECT_DIR/.venv/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

# Keep the updater on the same release channel used by this installation.
runuser -u "$TARGET_USER" -- "$PROJECT_DIR/.venv/bin/python" - "$PROJECT_DIR/AppSetting.JSON" "$BRANCH" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
branch = sys.argv[2]
settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
settings.setdefault("updater", {})["channel"] = branch
path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

log "Installing the dashboard and updater services"
install_service() {
    local source_file="$1"
    local destination="$2"
    sed \
        -e "s|User=pi|User=$TARGET_USER|g" \
        -e "s|Group=pi|Group=$TARGET_USER|g" \
        -e "s|/home/pi/Public/Fire-Detector|$PROJECT_DIR|g" \
        "$source_file" > "$destination"
    chmod 0644 "$destination"
}

install_service "$PROJECT_DIR/deploy/fire-detector.service" "/etc/systemd/system/fire-detector.service"
install -m 0644 "$PROJECT_DIR/deploy/fire-detector-http.service" \
    /etc/avahi/services/fire-detector-http.service

if [[ -f "$PROJECT_DIR/deploy/fire-detector-updater.service" ]]; then
    install_service "$PROJECT_DIR/deploy/fire-detector-updater.service" \
        "/etc/systemd/system/fire-detector-updater.service"
fi
if [[ -f "$PROJECT_DIR/deploy/fire-detector-updater.timer" ]]; then
    install -m 0644 "$PROJECT_DIR/deploy/fire-detector-updater.timer" \
        /etc/systemd/system/fire-detector-updater.timer
fi

systemctl daemon-reload
systemctl enable --now fire-detector.service
systemctl restart avahi-daemon.service
if ((ENABLE_UPDATER)) && [[ -f /etc/systemd/system/fire-detector-updater.timer ]]; then
    systemctl enable --now fire-detector-updater.timer
else
    systemctl disable --now fire-detector-updater.timer 2>/dev/null || true
fi

if ((INSTALL_CODEX)); then
    log "Installing Codex CLI for $TARGET_USER"
    runuser -u "$TARGET_USER" -- env \
        HOME="$TARGET_HOME" \
        CODEX_NON_INTERACTIVE=1 \
        bash -o pipefail -c "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
    PROFILE="$TARGET_HOME/.profile"
    touch "$PROFILE"
    chown "$TARGET_USER:$TARGET_USER" "$PROFILE"
    if ! grep -Fq '# Codex CLI path' "$PROFILE"; then
        cat >> "$PROFILE" <<'EOF'

# Codex CLI path
case ":$PATH:" in
    *:"$HOME/.local/bin":*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
EOF
    fi
    chown "$TARGET_USER:$TARGET_USER" "$PROFILE"
fi

log "Checking the dashboard"
for _ in {1..20}; do
    if curl --fail --silent --show-error http://127.0.0.1:8000/api/status >/dev/null; then
        DASHBOARD_OK=1
        break
    fi
    sleep 1
done
if [[ "${DASHBOARD_OK:-0}" != 1 ]]; then
    systemctl --no-pager --full status fire-detector.service || true
    die "Dashboard health check failed. Review: journalctl -u fire-detector.service"
fi

IP_ADDRESS="$(hostname -I | awk '{print $1}')"
cat <<EOF

Installation complete.

From Windows:
  ssh ${TARGET_USER}@${DEVICE_HOSTNAME}.local
  # fallback: ssh ${TARGET_USER}@${IP_ADDRESS:-<ip-address>}

First Codex login on the IRIV (run after SSH login):
  codex login --device-auth
  codex login status

Start developing:
  cd ${PROJECT_DIR}
  codex

Dashboard:
  http://${DEVICE_HOSTNAME}.local:8000
  http://${IP_ADDRESS:-<ip-address>}:8000

ODrive check after connecting USB and motor power:
  cd ${PROJECT_DIR}
  .venv/bin/python scripts/check_odrive.py
EOF

if [[ -z "$SSH_PUBLIC_KEY_FILE" ]]; then
    warn "No SSH public key was installed. Add one to $TARGET_HOME/.ssh/authorized_keys and verify login before disabling password authentication."
fi

if ((REBOOT_WHEN_DONE)); then
    log "Rebooting to activate IRIV hardware configuration"
    systemctl reboot
else
    warn "Reboot the IRIV before hardware use: sudo reboot"
fi
