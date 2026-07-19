#!/usr/bin/env python3
"""Pull, validate, and activate Fire Detector dashboard updates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
STATE_PATH = PROJECT_ROOT / ".update_state.json"
SERVICE_NAME = "fire-detector.service"
DEFAULT_BRANCH = "main"
DEFAULT_INTERVAL_MINUTES = 15
HEALTHCHECK_URL = "http://127.0.0.1:8000/api/status"


class UpdateError(RuntimeError):
    """Raised when an update step fails."""


class PreflightError(UpdateError):
    """Raised before any revision has been activated."""


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the Fire Detector app from git.")
    parser.add_argument("--once", action="store_true", help="Run one update pass if the configured interval is due.")
    parser.add_argument("--force", action="store_true", help="Ignore the configured interval and check immediately.")
    parser.add_argument("--status", action="store_true", help="Print updater status as JSON.")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(update_status(), indent=2, sort_keys=True))
        return 0

    if not args.once:
        parser.error("Use --once or --status.")

    settings = load_settings()
    updater = settings.get("updater", {})
    if updater.get("enabled") is False:
        record_state(status="disabled", message="Automatic updates are disabled.")
        return 0

    interval_minutes = clean_interval(updater.get("check_interval_minutes"))
    if not args.force and not update_due(interval_minutes):
        return 0

    return run_update(settings, force=args.force)


def run_update(settings: dict[str, Any], force: bool = False) -> int:
    branch = str(settings.get("updater", {}).get("channel") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    previous_sha = git("rev-parse", "HEAD").stdout.strip()
    target_ref = f"origin/{branch}"

    try:
        ensure_worktree_ready()
        record_state(status="checking", message=f"Checking {target_ref} for updates.")
        git("fetch", "origin", branch)
        target_sha = git("rev-parse", target_ref).stdout.strip()

        if target_sha == previous_sha:
            record_state(
                status="current",
                message="Already running the latest version.",
                current_sha=previous_sha,
                target_sha=target_sha,
            )
            return 0

        app_settings = APP_SETTINGS_PATH.read_text(encoding="utf-8") if APP_SETTINGS_PATH.exists() else None
        record_state(
            status="updating",
            message=f"Updating from {previous_sha[:7]} to {target_sha[:7]}.",
            previous_sha=previous_sha,
            target_sha=target_sha,
        )
        activate_revision(target_ref, app_settings)
        healthcheck()
        record_state(
            status="updated",
            message=f"Updated to {target_sha[:7]}.",
            previous_sha=previous_sha,
            current_sha=target_sha,
            target_sha=target_sha,
        )
        return 0
    except Exception as exc:
        message = str(exc)
        if isinstance(exc, PreflightError):
            record_state(status="failed", message=message, previous_sha=previous_sha)
            return 1
        record_state(status="failed", message=message, previous_sha=previous_sha)
        try:
            app_settings = APP_SETTINGS_PATH.read_text(encoding="utf-8") if APP_SETTINGS_PATH.exists() else None
            activate_revision(previous_sha, app_settings)
            healthcheck()
            record_state(status="rolled_back", message=f"Update failed and rolled back: {message}", current_sha=previous_sha)
        except Exception as rollback_exc:
            record_state(
                status="rollback_failed",
                message=f"Update failed: {message}; rollback failed: {rollback_exc}",
                previous_sha=previous_sha,
            )
            return 2
        return 1


def activate_revision(ref: str, app_settings: str | None) -> None:
    git("reset", "--hard", ref)
    if app_settings is not None:
        write_project_file(APP_SETTINGS_PATH, app_settings)
    pip_install_requirements()
    restart_dashboard()


def pip_install_requirements() -> None:
    run_as_project_owner([str(PROJECT_ROOT / ".venv" / "bin" / "python"), "-m", "pip", "install", "-r", "requirements.txt"], timeout=180)


def restart_dashboard() -> None:
    run(["systemctl", "restart", SERVICE_NAME], timeout=30)
    time.sleep(1.2)


def healthcheck() -> None:
    deadline = time.monotonic() + 30
    last_error = "healthcheck did not run"
    while time.monotonic() < deadline:
        try:
            with urlopen(HEALTHCHECK_URL, timeout=2) as response:
                if response.status != 200:
                    last_error = f"HTTP {response.status}"
                else:
                    payload = json.loads(response.read().decode("utf-8"))
                    if "timestamp" in payload:
                        return
                    last_error = "status payload missing timestamp"
        except (OSError, URLError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise UpdateError(f"Dashboard healthcheck failed: {last_error}")


def ensure_worktree_ready() -> None:
    result = git("status", "--porcelain")
    dirty = [line for line in result.stdout.splitlines() if line and not line.endswith(" AppSetting.JSON")]
    if dirty:
        raise PreflightError("Working tree has local changes outside AppSetting.JSON; refusing automatic update.")


def update_due(interval_minutes: int) -> bool:
    state = load_state()
    checked_at = parse_time(state.get("checked_at"))
    if checked_at is None:
        return True
    elapsed = datetime.now(timezone.utc) - checked_at
    return elapsed.total_seconds() >= interval_minutes * 60


def update_status() -> dict[str, Any]:
    settings = load_settings()
    updater = settings.get("updater", {})
    return {
        "device_id": updater.get("device_id"),
        "enabled": updater.get("enabled", True),
        "check_interval_minutes": clean_interval(updater.get("check_interval_minutes")),
        "channel": updater.get("channel") or DEFAULT_BRANCH,
        "current_sha": git_optional("rev-parse", "HEAD"),
        "current_branch": git_optional("branch", "--show-current"),
        "remote_url": git_optional("remote", "get-url", "origin"),
        "state": load_state(),
    }


def load_settings() -> dict[str, Any]:
    if not APP_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def record_state(status: str, message: str, **extra: Any) -> None:
    state = load_state()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state.update(
        {
            "status": status,
            "message": message,
            "checked_at": now,
        }
    )
    state.update(extra)
    write_project_file(STATE_PATH, json.dumps(state, indent=2, sort_keys=True) + "\n")


def clean_interval(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_MINUTES
    return max(1, min(interval, 1440))


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return run_as_project_owner(["git", *args])


def git_optional(*args: str) -> str | None:
    try:
        return git(*args).stdout.strip()
    except UpdateError:
        return None


def run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise UpdateError(f"{' '.join(command)}: {detail}")
    return result


def run_as_project_owner(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    uid = PROJECT_ROOT.stat().st_uid
    if os.geteuid() == 0 and uid != 0:
        user = pwd.getpwuid(uid).pw_name
        return run(["runuser", "-u", user, "--", *command], timeout=timeout)
    return run(command, timeout=timeout)


def write_project_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    if os.geteuid() == 0:
        stat = PROJECT_ROOT.stat()
        os.chown(path, stat.st_uid, stat.st_gid)


if __name__ == "__main__":
    raise SystemExit(main())
