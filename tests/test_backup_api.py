from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest

from fire_detector.backup_api import (
    BACKUP_TABLES,
    BackupError,
    BackupManager,
    BackupNonceCache,
    require_tailscale_source,
    verify_backup_signature,
)


class BackupAuthenticationTests(unittest.TestCase):
    def signed_headers(self, *, nonce: str = "nonce-1234567890-abcd", timestamp: int = 1_000):
        body = b'{"request_id":"daily-1"}'
        body_sha256 = hashlib.sha256(body).hexdigest()
        canonical = "\n".join((
            "station-1", "POST", "/api/v1/backups", str(timestamp), nonce, body_sha256,
        ))
        signature = hmac.new(b"secret", canonical.encode(), hashlib.sha256).hexdigest()
        return body, {
            "X-Narit-Device-Id": "station-1",
            "X-Narit-Timestamp": str(timestamp),
            "X-Narit-Nonce": nonce,
            "X-Narit-Content-SHA256": body_sha256,
            "X-Narit-Signature": signature,
        }

    def test_valid_signature_is_accepted_and_replay_is_rejected(self):
        body, headers = self.signed_headers()
        nonce_cache = BackupNonceCache()

        verify_backup_signature(
            headers=headers,
            method="POST",
            path="/api/v1/backups",
            body=body,
            expected_device_id="station-1",
            secret=b"secret",
            nonce_cache=nonce_cache,
            now=1_000,
        )

        with self.assertRaises(BackupError) as replay:
            verify_backup_signature(
                headers=headers,
                method="POST",
                path="/api/v1/backups",
                body=body,
                expected_device_id="station-1",
                secret=b"secret",
                nonce_cache=nonce_cache,
                now=1_001,
            )
        self.assertEqual(replay.exception.code, "BACKUP_REPLAY")

    def test_modified_body_is_rejected(self):
        _, headers = self.signed_headers()
        with self.assertRaises(BackupError) as mismatch:
            verify_backup_signature(
                headers=headers,
                method="POST",
                path="/api/v1/backups",
                body=b"modified",
                expected_device_id="station-1",
                secret=b"secret",
                nonce_cache=BackupNonceCache(),
                now=1_000,
            )
        self.assertEqual(mismatch.exception.code, "BACKUP_BODY_MISMATCH")

    def test_backup_api_accepts_only_tailnet_source_addresses(self):
        require_tailscale_source("100.102.91.123")
        require_tailscale_source("fd7a:115c:a1e0::1234")

        for address in ("192.168.1.20", "127.0.0.1", None):
            with self.subTest(address=address), self.assertRaises(BackupError) as denied:
                require_tailscale_source(address)
            self.assertEqual(denied.exception.code, "BACKUP_TAILSCALE_REQUIRED")
            self.assertEqual(denied.exception.status, 403)


class BackupManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database_path = self.root / "data" / "telemetry" / "mount_telemetry.sqlite3"
        self.database_path.parent.mkdir(parents=True)
        (self.root / "data" / "control").mkdir(parents=True)
        (self.root / "data" / "control" / "state.json").write_text('{"enabled":true}')
        (self.root / "AppSetting.JSON").write_text('{"mount_agent":{}}')
        with sqlite3.connect(self.database_path) as connection:
            for table in BACKUP_TABLES:
                connection.execute(
                    f"CREATE TABLE {table} (captured_ms INTEGER PRIMARY KEY, value REAL)"
                )
                connection.executemany(
                    f"INSERT INTO {table} VALUES (?, ?)",
                    [(1_000, 1.0), (2_000, 2.0)],
                )
        self.manager = BackupManager(
            self.root,
            self.database_path,
            self.root / "data" / "backups",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_backup_requires_confirmation_before_delete_and_preserves_new_rows(self):
        record = self.manager.create_backup("daily-2026-08-27")
        self.assertEqual(record["status"], "ready")
        self.assertEqual(record["coverage_through_ms"], 2_000)
        archive_path = next((self.root / "data" / "backups").glob("*.tar.gz"))
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(), record["sha256"])
        with tarfile.open(archive_path, "r:gz") as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertEqual(manifest["backup_id"], record["backup_id"])
            self.assertIn("telemetry/mount_telemetry.sqlite3", archive.getnames())

        with self.assertRaises(BackupError) as unconfirmed:
            self.manager.delete_confirmed_backup(record["backup_id"])
        self.assertEqual(unconfirmed.exception.code, "BACKUP_NOT_CONFIRMED")

        with sqlite3.connect(self.database_path) as connection:
            for table in BACKUP_TABLES:
                connection.execute(f"INSERT INTO {table} VALUES (?, ?)", (3_000, 3.0))
        confirmed = self.manager.confirm_backup(
            record["backup_id"], record["sha256"], "receiver-object-123",
        )
        self.assertEqual(confirmed["status"], "confirmed")
        deleted = self.manager.delete_confirmed_backup(record["backup_id"])

        self.assertEqual(deleted["status"], "deleted")
        self.assertFalse(archive_path.exists())
        with sqlite3.connect(self.database_path) as connection:
            for table in BACKUP_TABLES:
                self.assertEqual(
                    connection.execute(f"SELECT captured_ms FROM {table}").fetchall(),
                    [(3_000,)],
                )

    def test_create_is_idempotent_for_request_id(self):
        first = self.manager.create_backup("daily-1")
        second = self.manager.create_backup("daily-1")
        self.assertEqual(first["backup_id"], second["backup_id"])

    def test_checksum_mismatch_never_confirms_or_deletes(self):
        record = self.manager.create_backup("daily-2")
        with self.assertRaises(BackupError) as mismatch:
            self.manager.confirm_backup(record["backup_id"], "0" * 64, "receipt-1")
        self.assertEqual(mismatch.exception.code, "BACKUP_CHECKSUM_MISMATCH")
        self.assertEqual(self.manager.list_backups()["backups"][0]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
