import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from fire_detector.software_updates import LOGIN_COOKIE, Publisher, PublisherError, canonical, protected, register_update_routes


class SoftwareUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.run_git("init", "-q")
        self.run_git("config", "user.email", "test@example.invalid")
        self.run_git("config", "user.name", "Test")
        (self.root / "main.py").write_text("print('test')\n")
        self.run_git("add", "main.py")
        self.run_git("commit", "-qm", "Initial")
        self.commit = self.run_git("rev-parse", "HEAD").strip()
        self.bundle = self.base / "bundle"
        self.bundle.mkdir()
        self.artifact = self.bundle / "artifact.tar.gz"
        self.artifact.write_bytes(b"synthetic artifact; no real station data")
        self.private_key, self.public_key = self.base / "private.pem", self.base / "public.pem"
        self.run_cmd("openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.private_key))
        self.run_cmd("openssl", "pkey", "-in", str(self.private_key), "-pubout", "-out", str(self.public_key))
        manifest = {"release_id": "test-release", "version": "1.0", "git_commit": self.commit,
                    "size": self.artifact.stat().st_size, "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest()}
        canonical_path = self.base / "manifest-data"
        canonical_path.write_bytes(canonical(manifest))
        sig = self.run_cmd("openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(self.private_key), "-in", str(canonical_path))
        self.envelope = {"manifest": manifest, "signature": base64.b64encode(sig).decode(), "key_id": "test-key"}
        (self.bundle / "manifest.json").write_bytes(canonical(self.envelope))
        self.app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "web/templates"))
        self.app.testing = True
        self.publisher = register_update_routes(self.app, self.root, lambda: "test-pi")
        self.publisher.environ = {"FIRE_UPDATE_BUNDLE": str(self.bundle), "FIRE_UPDATE_VERIFY_KEY": str(self.public_key),
                                  "FIRE_UPDATE_VERIFY_KEY_ID": "test-key", "FIRE_UPDATE_SERVER": "https://server.example"}
        self.client = self.app.test_client()
        self.user = {"id": 7, "username": "admin", "full_name": "Test Admin", "role": "administrator", "active": True}
        self.auth = patch.object(self.publisher, "auth_remote", side_effect=lambda *a, **kw: ({"user": self.user}, "__Host-narit_session=" + "a" * 48))
        self.mock_auth = self.auth.start()
        self.addCleanup(self.auth.stop)
        self.assertEqual(self.post("login", {"login":"admin", "password":"test-password"}).status_code, 200)
        self.remote = patch.object(self.publisher, "remote", side_effect=self.remote_reply)
        self.mock_remote = self.remote.start()
        self.addCleanup(self.remote.stop)
        self.calls = []
        self.uploaded = False

    def run_cmd(self, *args):
        return subprocess.run(args, check=True, capture_output=True).stdout

    def run_git(self, *args):
        return self.run_cmd("git", "-C", str(self.root), *args).decode()

    def remote_reply(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path, payload, kwargs))
        if path.endswith("/approvals"):
            return {"token": "approval_test-private-token", "expires_at": time.time() + 590,
                    "release_id": payload["release_id"], "rollout": payload["rollout"],
                    "request_id": payload["request_id"], "upload_allowed": True}
        if path.endswith("/releases"):
            self.uploaded = True
            return {"id": "test-release"}
        if path.endswith("/snapshot"):
            return {"releases": [{"id":"test-release", "envelope":self.envelope}] if self.uploaded else [], "rollouts":[], "assignments":[]}
        if path.endswith("/approval-status"):
            return {"release_id": "test-release", "uploaded": self.uploaded, "rollout": None, "assignments": []}
        return {"id": "rollout-test"}

    def post(self, path, payload, secure=True, origin="https://station.example"):
        return self.client.post("/api/software-updates/" + path, json=payload,
                                base_url="https://station.example" if secure else "http://station.example",
                                headers={"Origin": origin, "X-Update-Intent": "publisher"})

    def approve(self, stations=None):
        return self.post("approve", {"stations": stations or [],
                                    "envelope_sha256": hashlib.sha256(canonical(self.envelope)).hexdigest()})

    def test_stop_resume_cancel_routes_are_owned_and_authenticated(self):
        import threading
        workflow=self.publisher.release_workflow()
        job={'id':'release-controls','owner':'7','state':'building','uploaded':False,'commit':'a'*40}
        workflow.jobs[job['id']]=job
        workflow.events[job['id']]=threading.Event()
        workflow.gates[job['id']]=threading.Event();workflow.gates[job['id']].set()
        paused=self.post('job/'+job['id']+'/pause',{})
        self.assertEqual(paused.status_code,200);self.assertTrue(paused.json['paused'])
        resumed=self.post('job/'+job['id']+'/resume',{})
        self.assertEqual(resumed.status_code,200);self.assertFalse(resumed.json['paused'])
        cancelled=self.post('job/'+job['id']+'/cancel-update',{})
        self.assertEqual(cancelled.status_code,200);self.assertTrue(cancelled.json['cancel_requested'])
        self.assertTrue(workflow.events[job['id']].is_set())
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.post('/api/software-updates/job/'+job['id']+'/pause',json={},base_url='https://station.example',headers={'Origin':'https://station.example','X-Update-Intent':'publisher'}).status_code,401)
        job['owner']='another-owner'
        denied=self.post('job/'+job['id']+'/cancel-update',{})
        self.assertEqual(denied.status_code,409)
        self.assertNotIn('another-owner',denied.get_data(as_text=True))

    def test_real_transport_checks_pause_before_sending_each_chunk(self):
        artifact=self.bundle/'transport-test.bin';artifact.write_bytes(b'x'*(600*1024))
        order=[];connection=MagicMock()
        connection.send.side_effect=lambda chunk:order.append('send')
        response=connection.getresponse.return_value
        response.status=200;response.read.return_value=b'{}'
        with patch('fire_detector.software_updates.http.client.HTTPSConnection',return_value=connection):
            Publisher.remote(self.publisher,'POST','/api/updates/releases',artifact=artifact,
                             envelope={'manifest':{'size':artifact.stat().st_size}},
                             wait_for_resume=lambda:order.append('checkpoint'))
        self.assertEqual(order,['checkpoint','checkpoint','send','checkpoint','send'])
        connection.putheader.assert_any_call("X-Narit-Station-ID", "test-pi")
        connection.close.assert_called_once()

    def test_release_source_station_id_comes_from_station_settings_not_browser(self):
        payload={"review_id":"review-"+'a'*24,"digest":'b'*64,"stations":[]}
        workflow=self.publisher.release_workflow()
        with patch.object(workflow,'start',return_value={'id':'release-test'}) as start:
            response=self.post('release',payload)
            self.assertEqual(response.status_code,202)
            self.assertEqual(start.call_args.kwargs['source_station_id'],'test-pi')
            spoof=self.post('release',{**payload,'source_station_id':'another-station'})
            self.assertEqual(spoof.status_code,400)
            self.assertEqual(start.call_count,1)

    def test_readiness_uses_owner_session_and_exposes_no_credentials(self):
        from fire_detector.publisher_tooling import TOOLING_SHA256, PUBLIC_KEY_SHA256
        info = {"tooling_sha256":TOOLING_SHA256,"key_id":"release-20261017", "public_key_sha256":PUBLIC_KEY_SHA256,
                "worker_heartbeat":{"online":True},"allowed_paths":["src/*"]}
        self.mock_remote.side_effect=lambda *a,**kw: info
        response=self.client.get('/api/software-updates/readiness',base_url='https://station.example')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json['ready'])
        self.assertTrue(response.json['signer_online'])
        self.assertNotIn('__Host-narit_session',response.get_data(as_text=True))
        self.assertEqual(self.mock_remote.call_args.kwargs['session_cookie'],'__Host-narit_session='+'a'*48)
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/api/software-updates/readiness',base_url='https://station.example').status_code,401)

    def test_read_only_status_and_plan_do_not_commit_or_contact_server(self):
        response = self.client.get("/api/software-updates/status", base_url="https://station.example")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["source"]["running_commit"], self.commit)
        self.assertIsNotNone(response.json["bundle"])
        plan = self.post("prepare", {})
        self.assertFalse(plan.json["committed"])
        self.assertFalse(plan.json["uploaded"])
        self.assertFalse(plan.json["rollout_started"])
        self.assertEqual(self.run_git("rev-parse", "HEAD").strip(), self.commit)
        self.assertFalse(self.calls)

    def test_page_has_automatic_review_and_scope_without_extra_approval_gates(self):
        response = self.client.get("/software-updates", base_url="https://station.example")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="approvalFields" class="release-actions">', response.text)
        self.assertNotIn('id="scope"', response.text)
        self.assertNotIn('Upload draft only', response.text)
        self.assertNotIn('id="prepare"', response.text)
        self.assertNotIn('id="reviewed"', response.text)
        self.assertNotIn('<h2>Release package</h2>', response.text)
        self.assertIn('id="approveRelease"', response.text)
        self.assertIn('id="rollout" type="button" hidden disabled', response.text)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertFalse(self.calls)

    def test_uncommitted_start_is_not_reported_as_committed_running_version(self):
        (self.root / "main.py").write_text("changed startup")
        app = Flask("dirty-start")
        publisher = register_update_routes(app, self.root)
        state = publisher.source()
        self.assertTrue(state["started_dirty"])
        self.assertIsNone(state["running_commit"])
        self.assertFalse(state["running_matches_source"])

    def test_login_gate_protects_page_metadata_and_actions(self):
        client = self.app.test_client()
        response = client.get("/software-updates", base_url="https://station.example")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/software-updates/login"))
        self.assertNotIn(self.commit, response.text)
        for endpoint in ("status", "progress"):
            response = client.get("/api/software-updates/" + endpoint, base_url="https://station.example")
            self.assertEqual(response.status_code, 401)
            self.assertNotIn(self.commit, response.text)
        response = client.post("/api/software-updates/prepare", json={}, base_url="https://station.example",
            headers={"Origin":"https://station.example", "X-Update-Intent":"publisher"})
        self.assertEqual(response.status_code, 401)

    def test_sign_in_works_before_any_release_bundle_exists(self):
        self.publisher.environ.pop("FIRE_UPDATE_BUNDLE")
        self.post("logout", {})
        response = self.post("login", {"login":"admin", "password":"test-password"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("narit_session", response.text)
        self.assertNotIn("test-password", repr(self.publisher.logins))
        state = self.client.get("/api/software-updates/status", base_url="https://station.example")
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json["blocker"], "signed_bundle_not_configured")
        self.assertEqual(self.post("prepare", {}).status_code, 200)
        self.assertFalse(self.calls)

    def test_server_role_revocation_blocks_existing_login(self):
        self.user["role"] = "standard_user"
        response = self.client.get("/api/software-updates/status", base_url="https://station.example")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.publisher.logins)

    def test_non_admin_and_wrong_password_do_not_create_login(self):
        self.post("logout", {})
        self.user["role"] = "standard_user"
        self.assertEqual(self.post("login", {"login":"admin", "password":"test-password"}).status_code, 403)
        self.assertFalse(self.publisher.logins)
        self.mock_auth.side_effect = PublisherError("server_login_rejected", 401)
        self.assertEqual(self.post("login", {"login":"admin", "password":"wrong"}).status_code, 401)
        self.assertFalse(self.publisher.logins)

    def test_login_cookie_is_secure_and_server_session_expires_closed(self):
        response = self.post("login", {"login":"admin", "password":"test-password"})
        cookie = response.headers.getlist("Set-Cookie")[0]
        for value in (LOGIN_COOKIE, "HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            self.assertIn(value, cookie)
        for session in self.publisher.logins.values():
            session["expires_at"] = time.time() - 1
        self.assertEqual(self.post("prepare", {}).status_code, 401)

    def test_http_entry_redirects_to_configured_secure_station(self):
        self.publisher.environ["FIRE_UPDATE_BROWSER_ORIGIN"] = "https://station.example"
        response = self.client.get("/software-updates", base_url="http://192.0.2.2:8000")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://station.example/software-updates")

    def test_auth_connection_never_discloses_a_password_on_network_failure(self):
        with patch("fire_detector.software_updates.http.client.HTTPSConnection", side_effect=OSError("do-not-print-password")):
            with self.assertRaises(PublisherError) as error:
                Publisher.auth_remote(self.publisher, "POST", "/api/auth/login", {"login":"admin", "password":"do-not-print-password"})
            self.assertEqual(error.exception.code, "server_auth_unavailable")
            self.assertNotIn("do-not-print-password", str(error.exception))

    def test_password_requires_https_and_same_origin_before_remote_call(self):
        self.assertEqual(self.post("approve", {}, secure=False).json["error"], "station_https_required")
        self.assertEqual(self.post("approve", {}, origin="https://other.example").status_code, 403)
        self.assertFalse(self.calls)

    def test_spoofed_forwarded_header_from_lan_is_not_trusted(self):
        self.publisher.environ["FIRE_UPDATE_TRUST_LOCAL_PROXY"] = "1"
        response = self.client.post("/api/software-updates/prepare", json={}, base_url="http://station.example",
            headers={"Origin": "https://station.example", "X-Update-Intent": "publisher", "X-Forwarded-Proto": "https"},
            environ_overrides={"REMOTE_ADDR": "192.0.2.5"})
        self.assertEqual(response.json["error"], "station_https_required")

    def test_approval_does_not_upload_or_distribute_and_never_returns_token(self):
        response = self.approve()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["uploaded"])
        self.assertNotIn("test-private-token", response.text)
        self.assertNotIn("test-password", response.text)
        cookie = response.headers["Set-Cookie"]
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertFalse(self.calls)
        self.assertNotIn("test-password", repr(self.publisher.sessions))

    def test_draft_approval_cannot_rollout_even_after_upload(self):
        self.approve()
        self.assertEqual(self.post("upload", {"confirm_release_id": "test-release"}).status_code, 200)
        response = self.post("rollout", {"confirm_release_id": "test-release"})
        self.assertEqual(response.json["error"], "upload_only_approval_cannot_rollout")
        self.assertFalse(any(call[1].endswith("/rollouts") for call in self.calls))

    def test_rollout_requires_exact_targets_confirmation_and_prior_upload(self):
        self.approve(["pi-b", "pi-a", "pi-a"])
        self.assertEqual(next(iter(self.publisher.sessions.values()))["rollout"]["stations"], ["pi-a", "pi-b"])
        self.assertEqual(self.post("rollout", {"confirm_release_id": "test-release"}).json["error"], "upload_before_rollout")
        self.assertEqual(self.post("upload", {"confirm_release_id": "wrong-release"}).status_code, 400)
        self.post("upload", {"confirm_release_id": "test-release"})
        result = self.post("rollout", {"confirm_release_id": "test-release"})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json["installed"])
        self.assertEqual(self.calls[-1][2]["stations"], ["pi-a", "pi-b"])
        self.assertEqual(self.calls[-1][3]["request_id"], next(iter(self.publisher.sessions.values()))["request_id"])

    def test_tampering_and_dirty_worktree_block_approval(self):
        (self.root / "main.py").write_text("changed")
        self.assertEqual(self.approve().json["error"], "commit_source_before_publishing")
        self.assertFalse(self.calls)
        self.run_git("checkout", "--", "main.py")
        self.artifact.write_bytes(b"tampered")
        self.assertEqual(self.approve().json["error"], "artifact_checksum_mismatch")
        self.assertFalse(self.calls)

    def test_signature_and_review_digest_are_required(self):
        changed = json.loads(canonical(self.envelope))
        changed["manifest"]["version"] = "altered"
        (self.bundle / "manifest.json").write_bytes(canonical(changed))
        self.assertEqual(self.approve().json["error"], "invalid_package_signature")
        self.assertFalse(self.calls)

    def test_expired_or_logged_out_session_cannot_upload(self):
        self.approve()
        self.post("logout", {})
        self.assertEqual(self.post("upload", {"confirm_release_id": "test-release"}).status_code, 401)
        self.post("login", {"login":"admin", "password":"test-password"})
        self.approve()
        for grant in self.publisher.sessions.values():
            grant["expires_at"] = time.time() - 1
        self.assertEqual(self.post("upload", {"confirm_release_id": "test-release"}).status_code, 401)

    def test_server_unavailable_does_not_create_session_or_upload(self):
        self.mock_remote.side_effect = PublisherError("updates_disabled", 503)
        self.assertEqual(self.approve().status_code, 200)
        response = self.post("upload", {"confirm_release_id":"test-release"})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(self.uploaded)

    def test_wrong_role_rate_limit_and_expiry_errors_are_not_success(self):
        for code, status in (("forbidden", 403), ("approval_rate_limited", 429)):
            self.mock_remote.side_effect = PublisherError(code, status)
            self.assertEqual(self.approve().status_code, 200)
            response = self.post("upload", {"confirm_release_id":"test-release"})
            self.assertEqual(response.status_code, status)
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "30")

    def test_network_failure_never_discloses_credentials(self):
        with patch("fire_detector.software_updates.http.client.HTTPSConnection", side_effect=OSError("test-private-token")):
            with self.assertRaises(PublisherError) as error:
                Publisher.remote(self.publisher, "GET", "/api/updates/approval-status", token="test-private-token")
            self.assertEqual(error.exception.code, "server_unreachable_or_tls_failed")
            self.assertNotIn("test-private-token", str(error.exception))

    def test_forged_targets_and_changed_review_cannot_be_submitted(self):
        response = self.post("approve", {"stations": ["pi1"],
                                         "envelope_sha256": "0" * 64})
        self.assertEqual(response.json["error"], "review_changed_bundle_again")
        self.assertFalse(self.calls)
        self.approve(["pi1"])
        response = self.post("rollout", {"confirm_release_id": "test-release", "stations": ["other"]})
        self.assertEqual(response.status_code, 400)

    def test_local_proxy_must_be_explicitly_trusted(self):
        headers = {"Origin": "https://station.example", "X-Update-Intent": "publisher", "X-Forwarded-Proto": "https"}
        response = self.client.post("/api/software-updates/prepare", json={}, base_url="http://station.example", headers=headers)
        self.assertEqual(response.status_code, 403)
        self.publisher.environ["FIRE_UPDATE_TRUST_LOCAL_PROXY"] = "1"
        response = self.client.post("/api/software-updates/prepare", json={}, base_url="http://station.example", headers=headers)
        self.assertEqual(response.status_code, 200)

    def test_unpackaged_source_without_git_does_not_prevent_registration(self):
        root = self.base / "unpacked"
        root.mkdir()
        app = Flask("unpacked")
        publisher = register_update_routes(app, root)
        publisher.environ = {}
        response = app.test_client().get("/api/software-updates/status")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(publisher.source()["available"])

    def test_protected_state_and_keys_are_not_proposed_as_source(self):
        for path in ("AppSetting.JSON", "camera_runtime/system_settings.json", "data/model.json",
                     "camera_runtime/incident_records/test.png", ".git/config", "keys/publisher.pem", "../other"):
            self.assertTrue(protected(path), path)
        self.assertFalse(protected("src/fire_detector/software_updates.py"))

    def test_changed_file_preview_is_authenticated_and_html_escaped(self):
        (self.root / "src").mkdir()
        (self.root / "src/new.py").write_text('<script>alert("not executed")</script>')
        response = self.post("prepare", {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([f["path"] for f in response.json["files"]], ["src/new.py"])
        url = "/software-updates/file?review=" + response.json["id"] + "&path=src/new.py"
        preview = self.client.get(url, base_url="https://station.example")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("&lt;script&gt;", preview.text)
        self.assertNotIn('<script>alert(', preview.text)
        anonymous = self.app.test_client().get(url, base_url="https://station.example")
        self.assertEqual(anonymous.status_code, 401)

    def test_post_login_approval_does_not_require_or_forward_a_password(self):
        response = self.approve(["pi1"])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.calls)
        page = self.client.get("/software-updates", base_url="https://station.example")
        self.assertNotIn('id="password"', page.text)
        self.assertNotIn("Confirm your Dashboard password", page.text)
        self.assertIn("Approve &amp; Release", page.text)


if __name__ == "__main__":
    unittest.main()
