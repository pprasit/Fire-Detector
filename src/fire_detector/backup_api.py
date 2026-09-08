"""Authenticated pull-backup snapshots for the Station runtime database."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tarfile
from threading import Lock
from time import time
from typing import Any, Mapping
from uuid import uuid4


BACKUP_TABLES = (
    "telemetry",
    "network_metrics",
    "power_metrics",
    "network_usage_metrics",
    "system_health_metrics",
)
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
TAILSCALE_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_IPV6_NETWORK = ipaddress.ip_network("fd7a:115c:a1e0::/48")


class BackupError(ValueError):
    """A safe, client-visible backup workflow error."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class BackupNonceCache:
    """In-memory replay protection for signed HTTP requests."""

    def __init__(self, ttl_sec: int = 600) -> None:
        self._ttl_sec = max(60, int(ttl_sec))
        self._seen: dict[str, float] = {}
        self._lock = Lock()

    def claim(self, nonce: str, now: float) -> bool:
        with self._lock:
            cutoff = now - self._ttl_sec
            self._seen = {key: seen_at for key, seen_at in self._seen.items() if seen_at >= cutoff}
            if nonce in self._seen:
                return False
            self._seen[nonce] = now
            return True


def require_tailscale_source(remote_address: str | None) -> None:
    """Reject Backup API traffic that did not originate from the tailnet."""
    try:
        address = ipaddress.ip_address(str(remote_address or "").split("%", 1)[0])
    except ValueError as exc:
        raise BackupError(
            "BACKUP_TAILSCALE_REQUIRED",
            "Backup API is available through Tailscale only.",
            403,
        ) from exc
    if address not in (TAILSCALE_IPV4_NETWORK if address.version == 4 else TAILSCALE_IPV6_NETWORK):
        raise BackupError(
            "BACKUP_TAILSCALE_REQUIRED",
            "Backup API is available through Tailscale only.",
            403,
        )


def verify_backup_signature(
    *,
    headers: Mapping[str, str],
    method: str,
    path: str,
    body: bytes,
    expected_device_id: str,
    secret: bytes,
    nonce_cache: BackupNonceCache,
    now: float | None = None,
    max_clock_skew_sec: int = 300,
) -> None:
    """Verify body integrity, HMAC identity, freshness, and nonce uniqueness."""
    if not secret:
        raise BackupError("BACKUP_AUTH_UNAVAILABLE", "Backup API secret is unavailable.", 503)
    device_id = str(headers.get("X-Narit-Device-Id") or "")
    timestamp = str(headers.get("X-Narit-Timestamp") or "")
    nonce = str(headers.get("X-Narit-Nonce") or "")
    body_sha256 = str(headers.get("X-Narit-Content-SHA256") or "").lower()
    signature = str(headers.get("X-Narit-Signature") or "").lower()
    if not hmac.compare_digest(device_id, expected_device_id):
        raise BackupError("BACKUP_AUTH_FAILED", "Device ID is invalid.", 401)
    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise BackupError("BACKUP_AUTH_FAILED", "Timestamp must be Unix seconds.", 401) from exc
    checked_at = time() if now is None else float(now)
    if abs(checked_at - request_time) > max(30, int(max_clock_skew_sec)):
        raise BackupError("BACKUP_AUTH_EXPIRED", "Signed request timestamp is outside the allowed window.", 401)
    if NONCE_PATTERN.fullmatch(nonce) is None:
        raise BackupError("BACKUP_AUTH_FAILED", "Nonce format is invalid.", 401)
    actual_body_sha256 = hashlib.sha256(body).hexdigest()
    if (
        SHA256_PATTERN.fullmatch(body_sha256) is None
        or not hmac.compare_digest(body_sha256, actual_body_sha256)
    ):
        raise BackupError("BACKUP_BODY_MISMATCH", "Request body checksum is invalid.", 401)
    if SHA256_PATTERN.fullmatch(signature) is None:
        raise BackupError("BACKUP_AUTH_FAILED", "Signature format is invalid.", 401)
    canonical = "\n".join((
        device_id,
        method.upper(),
        path,
        timestamp,
        nonce,
        body_sha256,
    ))
    expected_signature = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise BackupError("BACKUP_AUTH_FAILED", "Request signature is invalid.", 401)
    if not nonce_cache.claim(nonce, checked_at):
        raise BackupError("BACKUP_REPLAY", "Signed request nonce was already used.", 409)


class BackupManager:
    """Create immutable bundles and purge source rows only after confirmation."""

    def __init__(self, project_root: Path, database_path: Path, backup_dir: Path) -> None:
        self.project_root = project_root.resolve()
        self.database_path = database_path.resolve()
        self.backup_dir = backup_dir.resolve()
        self.state_path = self.backup_dir / "state.json"
        self._lock = Lock()
        self.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o750)

    def list_backups(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_state()
            backups = [self._public_record(record) for record in state["backups"]]
            candidate = self._candidate_summary(state.get("last_confirmed_through_ms"))
        return {"candidate": candidate, "backups": backups}

    def create_backup(self, request_id: str) -> dict[str, Any]:
        request_id = str(request_id or "").strip()
        if REQUEST_ID_PATTERN.fullmatch(request_id) is None:
            raise BackupError(
                "INVALID_REQUEST_ID",
                "request_id must be 1-128 safe ASCII characters.",
            )
        with self._lock:
            state = self._load_state()
            existing = next(
                (record for record in state["backups"] if record.get("request_id") == request_id),
                None,
            )
            if existing is not None:
                return self._public_record(existing)
            active = next(
                (record for record in state["backups"] if record.get("status") in {"ready", "confirmed"}),
                None,
            )
            if active is not None:
                raise BackupError(
                    "BACKUP_ALREADY_ACTIVE",
                    f"Backup {active['backup_id']} must be confirmed and deleted first.",
                    409,
                )
            backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
            temporary_db = self.backup_dir / f".{backup_id}.sqlite3.tmp"
            temporary_archive = self.backup_dir / f".{backup_id}.tar.gz.tmp"
            archive_path = self.backup_dir / f"{backup_id}.tar.gz"
            try:
                self._copy_database(temporary_db)
                coverage = self._database_summary(temporary_db)
                manifest = {
                    "version": "1.0",
                    "backup_id": backup_id,
                    "request_id": request_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "coverage": coverage,
                    "contents": [
                        "manifest.json",
                        "telemetry/mount_telemetry.sqlite3",
                        "configuration/AppSetting.JSON",
                        "runtime/control/",
                        "runtime/mission/",
                        "runtime/station_configuration/",
                        "runtime/odrive_backups/",
                    ],
                    "excludes": [
                        "credentials and shared secrets",
                        "recorded video already handled by the media workflow",
                        "regenerable terrain and pointing caches",
                        "system journal logs",
                    ],
                }
                self._write_archive(temporary_archive, temporary_db, manifest)
                archive_sha256 = self._sha256_file(temporary_archive)
                byte_size = temporary_archive.stat().st_size
                os.replace(temporary_archive, archive_path)
                os.chmod(archive_path, 0o640)
                record = {
                    "backup_id": backup_id,
                    "request_id": request_id,
                    "status": "ready",
                    "created_at": manifest["created_at"],
                    "coverage_from_ms": coverage["from_ms"],
                    "coverage_through_ms": coverage["through_ms"],
                    "row_count": coverage["row_count"],
                    "byte_size": byte_size,
                    "sha256": archive_sha256,
                    "filename": archive_path.name,
                }
                state["backups"].append(record)
                state["backups"] = state["backups"][-200:]
                self._save_state(state)
                return self._public_record(record)
            finally:
                temporary_db.unlink(missing_ok=True)
                temporary_archive.unlink(missing_ok=True)

    def archive_path_for(self, backup_id: str) -> tuple[Path, dict[str, Any]]:
        with self._lock:
            record = self._find_record(self._load_state(), backup_id)
            if record.get("status") not in {"ready", "confirmed"}:
                raise BackupError("BACKUP_NOT_DOWNLOADABLE", "Backup is no longer downloadable.", 410)
            path = self.backup_dir / str(record["filename"])
            if not path.is_file() or path.parent != self.backup_dir:
                raise BackupError("BACKUP_FILE_MISSING", "Backup archive is unavailable.", 410)
            return path, self._public_record(record)

    def confirm_backup(self, backup_id: str, sha256: str, receipt_id: str) -> dict[str, Any]:
        sha256 = str(sha256 or "").lower()
        receipt_id = str(receipt_id or "").strip()
        if SHA256_PATTERN.fullmatch(sha256) is None:
            raise BackupError("INVALID_SHA256", "sha256 must contain 64 lowercase hex characters.")
        if REQUEST_ID_PATTERN.fullmatch(receipt_id) is None:
            raise BackupError("INVALID_RECEIPT_ID", "receipt_id format is invalid.")
        with self._lock:
            state = self._load_state()
            record = self._find_record(state, backup_id)
            if not hmac.compare_digest(str(record.get("sha256") or ""), sha256):
                raise BackupError("BACKUP_CHECKSUM_MISMATCH", "Server checksum does not match the archive.", 409)
            if record.get("status") == "deleted":
                return self._public_record(record)
            existing_receipt = str(record.get("receipt_id") or "")
            if record.get("status") == "confirmed" and existing_receipt != receipt_id:
                raise BackupError("BACKUP_ALREADY_CONFIRMED", "Backup has a different receipt ID.", 409)
            record.update(
                status="confirmed",
                receipt_id=receipt_id,
                confirmed_at=datetime.now(timezone.utc).isoformat(),
            )
            self._save_state(state)
            return self._public_record(record)

    def delete_confirmed_backup(self, backup_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._load_state()
            record = self._find_record(state, backup_id)
            if record.get("status") == "deleted":
                return self._public_record(record)
            if record.get("status") != "confirmed" or not record.get("receipt_id"):
                raise BackupError(
                    "BACKUP_NOT_CONFIRMED",
                    "Server confirmation is required before local deletion.",
                    409,
                )
            cutoff_ms = record.get("coverage_through_ms")
            purged_rows = self._purge_database_through(cutoff_ms)
            archive_path = self.backup_dir / str(record["filename"])
            archive_path.unlink(missing_ok=True)
            record.update(
                status="deleted",
                deleted_at=datetime.now(timezone.utc).isoformat(),
                purged_rows=purged_rows,
            )
            if cutoff_ms is not None:
                previous = state.get("last_confirmed_through_ms")
                state["last_confirmed_through_ms"] = max(
                    int(cutoff_ms), int(previous) if previous is not None else int(cutoff_ms),
                )
            self._save_state(state)
            return self._public_record(record)

    def _candidate_summary(self, last_confirmed_through_ms: int | None) -> dict[str, Any]:
        summary = self._database_summary(self.database_path, after_ms=last_confirmed_through_ms)
        return {
            "available": summary["row_count"] > 0,
            **summary,
            "database_bytes": self.database_path.stat().st_size if self.database_path.exists() else 0,
        }

    def _copy_database(self, destination: Path) -> None:
        source_uri = f"file:{self.database_path}?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=30.0) as source:
            with sqlite3.connect(destination, timeout=30.0) as target:
                source.backup(target, pages=2048, sleep=0.01)

    def _write_archive(self, destination: Path, database_copy: Path, manifest: dict[str, Any]) -> None:
        with tarfile.open(destination, "w:gz", compresslevel=6) as archive:
            manifest_bytes = json.dumps(
                manifest, ensure_ascii=False, sort_keys=True, indent=2,
            ).encode("utf-8")
            manifest_info = tarfile.TarInfo("manifest.json")
            manifest_info.size = len(manifest_bytes)
            manifest_info.mode = 0o640
            manifest_info.mtime = int(time())
            archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
            archive.add(
                database_copy,
                arcname="telemetry/mount_telemetry.sqlite3",
                recursive=False,
                filter=self._archive_filter,
            )
            optional_paths = (
                (self.project_root / "AppSetting.JSON", "configuration/AppSetting.JSON"),
                (self.project_root / "data" / "control", "runtime/control"),
                (self.project_root / "data" / "mission", "runtime/mission"),
                (self.project_root / "data" / "station_configuration", "runtime/station_configuration"),
                (self.project_root / "data" / "odrive_backups", "runtime/odrive_backups"),
            )
            for source, archive_name in optional_paths:
                if source.exists():
                    archive.add(
                        source,
                        arcname=archive_name,
                        recursive=True,
                        filter=self._archive_filter,
                    )

    @staticmethod
    def _archive_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if member.issym() or member.islnk():
            return None
        member.uid = 0
        member.gid = 0
        member.uname = "root"
        member.gname = "root"
        return member

    def _database_summary(self, database: Path, after_ms: int | None = None) -> dict[str, Any]:
        if not database.exists():
            return {"from_ms": None, "through_ms": None, "row_count": 0, "tables": {}}
        predicate = " WHERE captured_ms > ?" if after_ms is not None else ""
        params = (int(after_ms),) if after_ms is not None else ()
        table_summary: dict[str, dict[str, Any]] = {}
        all_minima: list[int] = []
        all_maxima: list[int] = []
        row_count = 0
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=10.0) as connection:
            available_tables = {
                str(row[0]) for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in BACKUP_TABLES:
                if table not in available_tables:
                    continue
                row = connection.execute(
                    f"SELECT MIN(captured_ms), MAX(captured_ms), COUNT(*) FROM {table}{predicate}",
                    params,
                ).fetchone()
                minimum, maximum, count = row if row is not None else (None, None, 0)
                table_summary[table] = {"from_ms": minimum, "through_ms": maximum, "row_count": count}
                if minimum is not None:
                    all_minima.append(int(minimum))
                if maximum is not None:
                    all_maxima.append(int(maximum))
                row_count += int(count or 0)
        return {
            "from_ms": min(all_minima) if all_minima else None,
            "through_ms": max(all_maxima) if all_maxima else None,
            "row_count": row_count,
            "tables": table_summary,
        }

    def _purge_database_through(self, cutoff_ms: int | None) -> dict[str, int]:
        if cutoff_ms is None:
            return {}
        deleted: dict[str, int] = {}
        with sqlite3.connect(self.database_path, timeout=30.0) as connection:
            available_tables = {
                str(row[0]) for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            connection.execute("BEGIN IMMEDIATE")
            for table in BACKUP_TABLES:
                if table not in available_tables:
                    continue
                cursor = connection.execute(
                    f"DELETE FROM {table} WHERE captured_ms <= ?", (int(cutoff_ms),),
                )
                deleted[table] = max(0, int(cursor.rowcount))
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        return deleted

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": 1, "last_confirmed_through_ms": None, "backups": []}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("backups"), list):
                raise ValueError("invalid backup state")
            return payload
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise BackupError(
                "BACKUP_STATE_UNAVAILABLE",
                "Backup state is unreadable; refusing to create or delete data.",
                503,
            ) from exc

    def _save_state(self, state: dict[str, Any]) -> None:
        temporary = self.state_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, self.state_path)
        directory_fd = os.open(self.backup_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "filename"}

    @staticmethod
    def _find_record(state: dict[str, Any], backup_id: str) -> dict[str, Any]:
        if REQUEST_ID_PATTERN.fullmatch(str(backup_id or "")) is None:
            raise BackupError("BACKUP_NOT_FOUND", "Backup was not found.", 404)
        record = next(
            (item for item in state["backups"] if item.get("backup_id") == backup_id),
            None,
        )
        if record is None:
            raise BackupError("BACKUP_NOT_FOUND", "Backup was not found.", 404)
        return record
