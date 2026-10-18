"""Station publisher UI for the Server's exact-release human approval API.

No motor commands, service restarts, private signing keys or password storage.
Tokens stay in process memory, scoped to a verified immutable signed bundle.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import ssl
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, make_response, redirect, render_template, request
from fire_detector.release_workflow import ReleaseWorkflow, WorkflowError

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
COOKIE = "__Secure-fire-publisher"
LOGIN_COOKIE = "__Host-fire-update-login"
MAX_JSON = 65536


class PublisherError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def canonical(value):
    # Matches update_system.crypto.canonical on the Server (schema v2).
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def git(root, *args):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        raise PublisherError("source_unavailable", 503) from None
    if result.returncode:
        raise PublisherError("source_unavailable", 503)
    return result.stdout.decode("utf-8", errors="replace").strip()


def protected(name):
    path = PurePosixPath(name)
    lower = name.lower()
    return (path.is_absolute() or ".." in path.parts or "\\" in name
            or any(p.startswith(".") for p in path.parts)
            or any(p in {"data", "calibration", "credentials", "incident_records", "panoramas"} for p in path.parts)
            or path.name.lower() in {"appsetting.json", "system_settings.json", "station-registry.json"}
            or lower.endswith((".key", ".secret", ".pem", ".sqlite3", ".log", ".bak")))


class Publisher:
    def __init__(self, root, environ=None):
        self.root = Path(root)
        self.environ = os.environ if environ is None else environ
        try:
            self.started_commit = git(self.root, "rev-parse", "HEAD")
            self.started_dirty = bool(git(self.root, "status", "--porcelain=v1", "--untracked-files=all"))
            if self.started_dirty:
                self.started_commit = None
        except PublisherError:
            # An unpacked release may have no Git metadata. Never prevent the
            # actual mount/camera application starting because publisher is off.
            self.started_commit = None
            self.started_dirty = False
        self.sessions = {}
        self.logins = {}
        self.login_attempts = {}
        self.lock = threading.Lock()
        self.get_station_id = lambda: ""
        self.workflow = ReleaseWorkflow(self.root, self.environ, protected, self.remote, self.verify_bundle)

    def release_workflow(self):
        self.workflow.environ = self.environ
        self.workflow.remote = self.remote
        return self.workflow

    def browser_origin(self):
        value = self.environ.get("FIRE_UPDATE_BROWSER_ORIGIN", "").rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not (parsed.path or parsed.username or parsed.password or parsed.query or parsed.fragment):
            return value
        return None

    def auth_remote(self, method, path, payload=None, cookie=None):
        """Use the existing Dashboard session API, never Station HMAC secrets."""
        if path not in {"/api/auth/login", "/api/auth/status", "/api/auth/logout"}:
            raise PublisherError("invalid_auth_operation", 400)
        url = urlsplit(self.origin())
        conn = None
        try:
            conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=15,
                context=ssl.create_default_context(cafile=self.environ.get("FIRE_UPDATE_CA") or None))
            headers = {"Content-Type": "application/json", "Accept": "application/json",
                       "Origin": self.origin(), "User-Agent": "Mozilla/5.0 (compatible; NARITStationPublisher/1.0)"}
            if cookie:
                headers["Cookie"] = cookie
            conn.request(method, path, canonical(payload) if payload is not None else None, headers)
            response = conn.getresponse()
            raw = response.read(MAX_JSON + 1)
            if response.status in {401, 403}:
                raise PublisherError("server_login_rejected", 401)
            if response.status == 429:
                raise PublisherError("approval_rate_limited", 429)
            if response.status not in {200, 201} or len(raw) > MAX_JSON:
                raise PublisherError("server_auth_unavailable", 503)
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise PublisherError("invalid_server_response", 502)
            server_cookie = None
            for header, value in response.getheaders():
                if header.lower() == "set-cookie":
                    jar = SimpleCookie()
                    jar.load(value)
                    item = jar.get("__Host-narit_session")
                    if item and item["secure"] and item["httponly"] and item["path"] == "/" and not item["domain"]:
                        if re.fullmatch(r"[A-Za-z0-9_-]{32,512}", item.value):
                            server_cookie = "__Host-narit_session=" + item.value
            return result, server_cookie
        except (OSError, ValueError, http.client.HTTPException):
            raise PublisherError("server_auth_unavailable", 503) from None
        finally:
            if conn:
                conn.close()

    def login_session(self):
        sid = request.cookies.get(LOGIN_COOKIE, "")
        with self.lock:
            self.logins = {k: v for k, v in self.logins.items() if v["expires_at"] > time.time()}
            session = self.logins.get(sid)
        if not session:
            raise PublisherError("login_required", 401)
        result, _ = self.auth_remote("GET", "/api/auth/status", cookie=session["server_cookie"])
        user = result.get("user")
        if (not isinstance(user, dict) or user.get("id") != session["user_id"]
                or user.get("role") != "administrator" or user.get("active") is False):
            with self.lock:
                self.logins.pop(sid, None)
            raise PublisherError("login_required", 401)
        return session

    def secure_transport(self):
        return request.is_secure or (
            self.environ.get("FIRE_UPDATE_TRUST_LOCAL_PROXY") == "1"
            and request.remote_addr in {"127.0.0.1", "::1"}
            and request.headers.get("X-Forwarded-Proto") == "https")

    def origin(self):
        origin = self.environ.get("FIRE_UPDATE_SERVER", "https://operations.narit.or.th").rstrip("/")
        url = urlsplit(origin)
        try:
            port = url.port
        except ValueError:
            raise PublisherError("invalid_server_configuration", 503) from None
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path or url.query or url.fragment):
            raise PublisherError("invalid_server_configuration", 503)
        return origin

    def remote(self, method, path, payload=None, token=None, artifact=None, envelope=None, request_id=None,
               session_cookie=None, on_progress=None, cancel=None, wait_for_resume=None, source_station_id=None):
        station_id = self.get_station_id() if source_station_id is None else source_station_id
        if station_id:
            if not isinstance(station_id, str) or not IDENTIFIER.fullmatch(station_id):
                raise PublisherError("invalid_source_station_id", 409)
        elif artifact:
            raise PublisherError("source_station_id_missing", 409)
        if wait_for_resume:
            wait_for_resume()
        url = urlsplit(self.origin())
        try:
            context = ssl.create_default_context(cafile=self.environ.get("FIRE_UPDATE_CA") or None)
            conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=60, context=context)
        except (OSError, ValueError):
            raise PublisherError("server_unreachable_or_tls_failed", 503) from None
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "Mozilla/5.0 (compatible; NARITStationPublisher/1.0)"}
        if station_id:
            headers["X-Narit-Station-ID"] = station_id
        if token:
            headers["Authorization"] = "Bearer " + token
        if session_cookie:
            headers["Cookie"] = session_cookie
            headers["Origin"] = self.origin()
        if request_id:
            headers["Idempotency-Key"] = request_id
        body = canonical(payload) if payload is not None else None
        try:
            if artifact:
                headers.update({"Content-Type": "application/gzip",
                                "Content-Length": str(envelope["manifest"]["size"]),
                                "X-Narit-Manifest": base64.b64encode(canonical(envelope)).decode()})
                conn.putrequest(method, path)
                for name, value in headers.items():
                    conn.putheader(name, value)
                conn.endheaders()
                sent, total = 0, artifact.stat().st_size
                with artifact.open("rb") as stream:
                    while chunk := stream.read(512 * 1024):
                        if wait_for_resume:
                            wait_for_resume()
                        if cancel and cancel.is_set():
                            raise WorkflowError("cancelled")
                        conn.send(chunk)
                        sent += len(chunk)
                        if on_progress:
                            on_progress(sent, total)
                if cancel and cancel.is_set():
                    raise WorkflowError("cancelled")
            else:
                conn.request(method, path, body, headers)
            response = conn.getresponse()
            raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise PublisherError("invalid_server_response", 502)
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise PublisherError("invalid_server_response", 502) from None
            if response.status != 200:
                code = result.get("error", "server_rejected") if isinstance(result, dict) else "server_rejected"
                allowed = {"updates_disabled", "update_storage_unavailable", "forbidden", "conflict",
                           "approval_rate_limited", "upload_busy", "release_approval_required", "invalid_request"}
                raise PublisherError(code if code in allowed else "server_rejected",
                                     response.status if response.status in {400, 403, 404, 409, 429, 503} else 502)
            if not isinstance(result, dict):
                raise PublisherError("invalid_server_response", 502)
            return result
        except (OSError, http.client.HTTPException):
            raise PublisherError("server_unreachable_or_tls_failed", 503) from None
        finally:
            conn.close()

    def source(self):
        try:
            head = git(self.root, "rev-parse", "HEAD")
        except PublisherError:
            return {"running_commit": self.started_commit, "source_commit": None, "branch": None,
                    "version": "Unknown", "clean": False, "changed_count": None,
                    "source_files": 0, "running_matches_source": False, "available": False,
                    "started_dirty": self.started_dirty}
        # Only return path/status, never diff content, credentials or remote URLs.
        changes = git(self.root, "status", "--porcelain=v1", "--untracked-files=all")
        files = git(self.root, "ls-files", "-z").split("\0")
        allowlist = [n for n in files if n and not protected(n)]
        runtime = self.release_workflow().runtime_info()
        return {"running_commit": self.started_commit, "running_version": runtime["version"], "running_id": runtime["id"], "source_commit": head,
                "branch": git(self.root, "branch", "--show-current"),
                "version": git(self.root, "describe", "--tags", "--always"),
                "clean": not changes, "changed_count": len(changes.splitlines()),
                "source_files": len(allowlist), "running_matches_source": not changes and head == self.started_commit,
                "available": True, "started_dirty": self.started_dirty}

    def bundle(self):
        configured = self.environ.get("FIRE_UPDATE_BUNDLE")
        if not configured:
            raise PublisherError("signed_bundle_not_configured")
        return self.verify_bundle(Path(configured), git(self.root, "rev-parse", "HEAD"), clean_required=True)

    def verify_bundle(self, folder, expected_commit, clean_required=False):
        folder = Path(folder).resolve()
        if folder == self.root.resolve() or self.root.resolve() in folder.parents:
            raise PublisherError("bundle_must_be_outside_source")
        path, artifact = folder / "manifest.json", folder / "artifact.tar.gz"
        if path.is_symlink() or artifact.is_symlink() or not path.is_file() or not artifact.is_file():
            raise PublisherError("signed_bundle_missing")
        if path.stat().st_size > 24576:
            raise PublisherError("invalid_bundle")
        try:
            envelope = json.loads(path.read_bytes())
            if not isinstance(envelope, dict) or set(envelope) != {"manifest", "key_id", "signature"}:
                raise ValueError()
            manifest = envelope["manifest"]
            if not isinstance(manifest, dict):
                raise ValueError()
            for key in ("release_id", "key_id"):
                value = manifest.get(key) if key == "release_id" else envelope.get(key)
                if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                    raise ValueError()
            if not re.fullmatch(r"[0-9a-f]{40}", manifest["git_commit"]):
                raise ValueError()
            if not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]):
                raise ValueError()
            if type(manifest["size"]) is not int or not 0 < manifest["size"] <= 2 * 1024**3:
                raise ValueError()
            if not isinstance(manifest["version"], str) or len(manifest["version"]) > 100:
                raise ValueError()
            signature = base64.b64decode(envelope["signature"], validate=True)
            if len(signature) != 64:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise PublisherError("invalid_bundle") from None
        key = self.environ.get("FIRE_UPDATE_VERIFY_KEY")
        key_id = self.environ.get("FIRE_UPDATE_VERIFY_KEY_ID")
        if not key or key_id != envelope["key_id"]:
            raise PublisherError("verification_key_not_configured")
        with tempfile.TemporaryDirectory(prefix="fire-verify-") as tmp:
            data, sig = Path(tmp) / "manifest", Path(tmp) / "signature"
            data.write_bytes(canonical(manifest))
            sig.write_bytes(signature)
            verified = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", key,
                                       "-rawin", "-in", str(data), "-sigfile", str(sig)],
                                      capture_output=True, timeout=10, check=False)
            if verified.returncode:
                raise PublisherError("invalid_package_signature")
        digest = hashlib.sha256()
        with artifact.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if artifact.stat().st_size != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
            raise PublisherError("artifact_checksum_mismatch")
        if expected_commit != manifest["git_commit"]:
            raise PublisherError("bundle_does_not_match_source")
        if clean_required and git(self.root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise PublisherError("commit_source_before_publishing")
        return envelope, artifact, hashlib.sha256(canonical(envelope)).hexdigest()

    def grant(self):
        sid = request.cookies.get(COOKIE, "")
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v["expires_at"] > time.time()}
            session = self.sessions.get(sid)
        if not session:
            raise PublisherError("approval_required", 401)
        if session.get("login_sid") != request.cookies.get(LOGIN_COOKIE):
            raise PublisherError("approval_required", 401)
        return session


def register_update_routes(app, root, get_device_id=lambda: ""):
    publisher = Publisher(root)
    publisher.get_station_id = get_device_id
    app.extensions["software_publisher"] = publisher
    bp = Blueprint("software_updates", __name__)

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        return response

    @bp.errorhandler(PublisherError)
    def rejected(error):
        response = jsonify({"error": error.code})
        response.status_code = error.status
        if error.status == 429:
            response.headers["Retry-After"] = "30"
        return response

    @bp.errorhandler(OSError)
    @bp.errorhandler(subprocess.SubprocessError)
    def unavailable(error):
        return jsonify({"error": "publisher_unavailable"}), 503

    @bp.before_request
    def protect_mutations():
        if request.path.startswith("/api/software-updates/") and request.path not in {
                "/api/software-updates/login", "/api/software-updates/logout"}:
            if not publisher.secure_transport():
                raise PublisherError("station_https_required", 403)
            publisher.login_session()
        if request.method != "POST":
            return
        # Never trust client-supplied forwarded headers to authorize passwords.
        if not publisher.secure_transport():
            raise PublisherError("station_https_required", 403)
        if (request.headers.get("Origin") != "https://" + request.host
                or request.headers.get("X-Update-Intent") != "publisher"
                or request.mimetype != "application/json"):
            raise PublisherError("same_origin_required", 403)
        if request.content_length is None or request.content_length > 16384:
            raise PublisherError("invalid_request", 400)

    @bp.get("/software-updates")
    def page():
        if not publisher.secure_transport():
            origin = publisher.browser_origin()
            if origin:
                return redirect(origin + "/software-updates", code=302)
            return redirect("/software-updates/login", code=302)
        try:
            publisher.login_session()
        except PublisherError:
            return redirect("/software-updates/login", code=302)
        return render_template("software_updates.html")

    @bp.get("/software-updates/login")
    def login_page():
        if not publisher.secure_transport() and publisher.browser_origin():
            return redirect(publisher.browser_origin() + "/software-updates/login", code=302)
        return render_template("software_updates_login.html", secure=publisher.secure_transport())

    @bp.post("/api/software-updates/login")
    def login():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"login", "password"}:
            raise PublisherError("invalid_request", 400)
        name, password = payload["login"], payload["password"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 254 or not isinstance(password, str) or not 1 <= len(password) <= 256:
            raise PublisherError("invalid_request", 400)
        key = hashlib.sha256(name.strip().lower().encode()).hexdigest()
        now = time.time()
        with publisher.lock:
            publisher.login_attempts = {k: [v for v in vs if v > now - 900]
                                        for k, vs in publisher.login_attempts.items() if any(v > now - 900 for v in vs)}
            attempts = publisher.login_attempts.setdefault(key, [])
            if len(attempts) >= 10 or sum(map(len, publisher.login_attempts.values())) >= 100:
                raise PublisherError("approval_rate_limited", 429)
            attempts.append(now)
        result, server_cookie = publisher.auth_remote("POST", "/api/auth/login", {"login": name.strip(), "password": password})
        user = result.get("user")
        if not isinstance(user, dict) or user.get("role") != "administrator" or user.get("active") is False:
            if server_cookie:
                try:
                    publisher.auth_remote("POST", "/api/auth/logout", {}, cookie=server_cookie)
                except PublisherError:
                    pass
            raise PublisherError("administrator_required", 403)
        if not server_cookie or user.get("id") is None:
            raise PublisherError("invalid_server_response", 502)
        sid = secrets.token_urlsafe(32)
        with publisher.lock:
            publisher.logins = {k: v for k, v in publisher.logins.items() if v["expires_at"] > now}
            publisher.logins.pop(request.cookies.get(LOGIN_COOKIE, ""), None)
            publisher.sessions.pop(request.cookies.get(COOKIE, ""), None)
            if len(publisher.logins) >= 100:
                raise PublisherError("publisher_busy", 429)
            publisher.logins[sid] = {"server_cookie": server_cookie, "user_id": user["id"],
                                    "expires_at": now + 1800,
                                    "user": {k: user.get(k) for k in ("username", "full_name", "role")}}
        response = make_response(jsonify({"authenticated": True, "redirect": "/software-updates"}))
        response.set_cookie(LOGIN_COOKIE, sid, secure=True, httponly=True, samesite="Strict", max_age=1800, path="/")
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="Strict", path="/api/software-updates")
        return response

    @bp.post("/api/software-updates/tooling/download")
    def download_tooling():
        from fire_detector.publisher_tooling import download
        login = publisher.login_session()
        try:
            download(publisher.release_workflow().directory(), publisher.origin(), login["server_cookie"],
                     publisher.environ.get("FIRE_UPDATE_CA") or None)
        except Exception:
            raise PublisherError("tooling_download_failed", 503) from None
        return jsonify({"downloaded": True, "checksum_verified": True})

    @bp.get("/api/software-updates/readiness")
    def publisher_readiness():
        from fire_detector.publisher_tooling import TOOLING_SHA256, PUBLIC_KEY_SHA256
        import fnmatch
        login = publisher.login_session()
        blockers = []
        config_path = publisher.environ.get("FIRE_UPDATE_BUILD_CONFIG", "")
        helper = publisher.environ.get("FIRE_UPDATE_BUILD_HELPER", "")
        config = None
        if not helper or not Path(helper).is_file() or not os.access(helper, os.X_OK):
            blockers.append("Release helper is not installed")
        elif hashlib.sha256(Path(helper).read_bytes()).hexdigest() != "6c78267a5e761d1c00eff151229a2f6e8da3718d7e6c103208854fd6bf3747a4":
            blockers.append("Installed helper checksum does not match the trusted revision")
        key = publisher.environ.get("FIRE_UPDATE_PUBLIC_KEY", "")
        if not Path(key).is_file() or hashlib.sha256(Path(key).read_bytes()).hexdigest() != PUBLIC_KEY_SHA256:
            blockers.append("Installed verification key does not match the trusted key")
        try:
            config = json.loads(Path(config_path).read_text())
            if not (publisher.root / config["lock"]).is_file():
                blockers.append("Dependency lock is missing")
            wheels = Path(config["wheelhouse"])
            if not wheels.is_dir() or not any(wheels.glob("*.whl")):
                blockers.append("Offline dependencies are missing")
        except (OSError, ValueError, KeyError, TypeError):
            blockers.append("Native build configuration is missing")
        station_id = get_device_id()
        if not isinstance(station_id, str) or not IDENTIFIER.fullmatch(station_id):
            blockers.append("Station ID is missing or invalid")
        if config:
            inventory = set(config.get("files", []))
            missing = [name for name in publisher.release_workflow().inventory()
                       if (publisher.root / name).is_file() and name not in inventory]
            if missing:
                blockers.append("Required source files are missing from the build inventory: " + ", ".join(missing[:5]))
        info = publisher.remote("GET", "/api/updates/builds/info", session_cookie=login["server_cookie"])
        from fire_detector.release_workflow import write_json
        write_json(publisher.release_workflow().directory() / "server-builder-info.json",
                   {k: info.get(k) for k in ("protocol", "mode", "tooling_sha256", "key_id", "public_key_sha256", "target", "allowed_paths", "worker_heartbeat")})
        if info.get("tooling_sha256") != TOOLING_SHA256 or info.get("key_id") != "release-20261017" or info.get("public_key_sha256") != PUBLIC_KEY_SHA256:
            blockers.append("Server tooling or verification key differs from the pinned revision")
        if not info.get("worker_heartbeat", {}).get("online"):
            blockers.append("Server signing worker is offline")
        if config and isinstance(info.get("allowed_paths"), list):
            rejected = [name for name in config.get("files", []) if not any(fnmatch.fnmatchcase(name, pattern) for pattern in info["allowed_paths"])]
            if rejected:
                blockers.append("Build inventory is outside the server allowlist: " + ", ".join(rejected[:5]))
        return jsonify({"ready": not blockers, "blockers": blockers, "tooling_revision": TOOLING_SHA256[:12],
                        "signer_online": bool(info.get("worker_heartbeat", {}).get("online"))})

    @bp.get("/api/software-updates/status")
    def status():
        source = publisher.source()
        data = {"source": source, "server": publisher.origin(), "device_id": get_device_id(),
                "https": publisher.secure_transport(), "bundle": None, "blocker": None, "approval": None,
                "user": publisher.login_session()["user"]}
        try:
            envelope, _, digest = publisher.bundle()
            m = envelope["manifest"]
            data["bundle"] = {key: m[key] for key in ("release_id", "version", "git_commit", "size", "sha256")}
            data["bundle"]["envelope_sha256"] = digest
        except PublisherError as error:
            data["blocker"] = error.code
        try:
            grant = publisher.grant()
            data["approval"] = {key: grant[key] for key in ("expires_at", "rollout", "release_id")}
        except PublisherError:
            pass
        return jsonify(data)

    @bp.errorhandler(WorkflowError)
    def workflow_rejected(error):
        return jsonify({"error": str(error)}), 409

    @bp.post("/api/software-updates/prepare")
    def prepare():
        login = publisher.login_session()
        review = publisher.release_workflow().review(login["user_id"])
        return jsonify({"source": publisher.source(), **review,
                        "committed": False, "uploaded": False, "rollout_started": False})

    @bp.get("/software-updates/file")
    def file_preview():
        if not publisher.secure_transport():
            raise PublisherError("station_https_required", 403)
        login = publisher.login_session()
        preview = publisher.release_workflow().preview(request.args.get("review", ""), request.args.get("path", ""), login["user_id"])
        return render_template("software_update_file.html", **preview)

    @bp.post("/api/software-updates/release")
    def release():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"review_id", "digest", "stations"}:
            raise PublisherError("invalid_request", 400)
        if (not isinstance(payload["review_id"], str) or not re.fullmatch(r"review-[0-9a-f]{24}", payload["review_id"])
                or not isinstance(payload["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["digest"])):
            raise PublisherError("invalid_request", 400)
        stations = payload["stations"]
        if not isinstance(stations, list) or len(stations) > 40 or any(not isinstance(s, str) or not IDENTIFIER.fullmatch(s) for s in stations):
            raise PublisherError("invalid_request", 400)
        login = publisher.login_session()
        job = publisher.release_workflow().start(payload["review_id"], payload["digest"], login["user_id"], sorted(set(stations)), login["server_cookie"], source_station_id=get_device_id())
        return jsonify(job), 202

    @bp.get("/api/software-updates/job/<job_id>")
    def job_status(job_id):
        login = publisher.login_session()
        workflow = publisher.release_workflow()
        job = workflow.find_job(job_id, login["user_id"])
        workflow.observe(job, login["server_cookie"])
        result = workflow.public_job(job)
        if job.get("rollout_id"):
            snapshot = publisher.remote("GET", "/api/updates/snapshot", session_cookie=login["server_cookie"])
            result["assignments"] = [{k: row.get(k) for k in ("station", "state", "updated")} for row in snapshot.get("assignments", []) if row.get("rollout") == job["rollout_id"]]
            rollout = next((row for row in snapshot.get("rollouts", []) if row.get("id") == job["rollout_id"]), {})
            result["rollout_state"] = rollout.get("state")
        return jsonify(result)

    @bp.post("/api/software-updates/job/<job_id>/cancel")
    def cancel_job(job_id):
        login = publisher.login_session()
        workflow = publisher.release_workflow()
        return jsonify(workflow.cancel(workflow.find_job(job_id, login["user_id"])))

    @bp.post("/api/software-updates/job/<job_id>/pause")
    def pause_job(job_id):
        login = publisher.login_session()
        workflow = publisher.release_workflow()
        return jsonify(workflow.pause(workflow.find_job(job_id, login["user_id"])))

    @bp.post("/api/software-updates/job/<job_id>/cancel-update")
    def cancel_update_job(job_id):
        login = publisher.login_session()
        workflow = publisher.release_workflow()
        return jsonify(workflow.cancel_update(workflow.find_job(job_id, login["user_id"]), login["server_cookie"]))

    @bp.post("/api/software-updates/job/<job_id>/resume")
    def resume_job(job_id):
        login = publisher.login_session()
        workflow = publisher.release_workflow()
        job = workflow.find_job(job_id, login["user_id"])
        return jsonify(workflow.resume(job, login["server_cookie"]))

    @bp.post("/api/software-updates/job/<job_id>/rollout")
    def rollout_job(job_id):
        login = publisher.login_session()
        workflow = publisher.release_workflow()
        job = workflow.find_job(job_id, login["user_id"])
        if job.get("rollout_disabled") or not job.get("uploaded") or not job.get("github_pushed") or not job.get("stations"):
            raise PublisherError("release_not_ready_for_rollout", 409)
        snapshot = publisher.remote("GET", "/api/updates/snapshot", session_cookie=login["server_cookie"])
        agents = {row.get("id"): row for row in snapshot.get("stations", [])}
        required = {"safe_stop", "transactional_switch", "health_checks", "rollback", "shared_updater_lock"}
        release = next((row for row in snapshot.get("releases", []) if row.get("id") == job["id"]), {})
        manifest = release.get("envelope", {}).get("manifest", {})
        for station in job["stations"]:
            agent = agents.get(station, {})
            profile = agent.get("profile", {})
            if (agent.get("online") is not True or not required.issubset(profile.get("capabilities", []))
                    or any(profile.get(k) not in manifest.get(k, []) for k in ("hardware", "os", "architecture"))):
                raise PublisherError("target_agent_not_ready", 409)
        payload = {"release_id": job["id"], "stations": job["stations"], "concurrency": 1, "failure_limit": 1, "action": "update"}
        result = publisher.remote("POST", "/api/updates/rollouts", payload, session_cookie=login["server_cookie"], request_id=job["id"])
        rollout_id = result.get("id")
        if not isinstance(rollout_id, str) or not IDENTIFIER.fullmatch(rollout_id):
            raise PublisherError("invalid_server_response", 502)
        workflow.update(job, rollout_id=rollout_id, phase="Server accepted rollout; waiting for station reports")
        return jsonify(workflow.public_job(job))

    @bp.post("/api/software-updates/job/<job_id>/cancel-rollout")
    def cancel_rollout_job(job_id):
        login = publisher.login_session()
        workflow = publisher.release_workflow()
        job = workflow.find_job(job_id, login["user_id"])
        rid = job.get("rollout_id")
        if not isinstance(rid, str) or not IDENTIFIER.fullmatch(rid):
            raise PublisherError("rollout_not_started", 409)
        publisher.remote("POST", "/api/updates/rollouts/" + rid + "/cancel", {}, session_cookie=login["server_cookie"])
        workflow.update(job, phase="Rollout cancellation requested; installations already in progress may still finish", state="cancelled_remote")
        return jsonify(workflow.public_job(job))

    @bp.post("/api/software-updates/approve")
    def approve():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"envelope_sha256", "stations"}:
            raise PublisherError("invalid_request", 400)
        stations = payload["stations"]
        if (not isinstance(stations, list) or len(stations) > 40
                or any(not isinstance(s, str) or not IDENTIFIER.fullmatch(s) for s in stations)):
            raise PublisherError("invalid_request", 400)
        login = publisher.login_session()
        envelope, _, digest = publisher.bundle()
        if payload["envelope_sha256"] != digest:
            raise PublisherError("review_changed_bundle_again")
        rid = envelope["manifest"]["release_id"]
        rollout = {"release_id": rid, "stations": sorted(set(stations)), "concurrency": 1,
                   "failure_limit": 1, "action": "update"} if stations else None
        request_id = "station-web-" + secrets.token_hex(16) if rollout else None
        sid, expiry = secrets.token_urlsafe(32), min(time.time() + 600, login["expires_at"])
        grant = {"token": None, "server_cookie": login["server_cookie"], "expires_at": expiry,
                 "release_id": rid, "digest": digest, "rollout": rollout, "request_id": request_id,
                 "lock": threading.Lock(), "login_sid": request.cookies.get(LOGIN_COOKIE)}
        with publisher.lock:
            publisher.sessions.pop(request.cookies.get(COOKIE, ""), None)
            publisher.sessions[sid] = grant
        response = make_response(jsonify({"approved": True, "expires_at": expiry,
                                         "release_id": rid, "rollout": rollout,
                                         "uploaded": False, "rollout_started": False}))
        response.set_cookie(COOKIE, sid, secure=True, httponly=True, samesite="Strict",
                            max_age=max(1, int(expiry - time.time())), path="/api/software-updates")
        return response

    @bp.post("/api/software-updates/upload")
    @bp.post("/api/software-updates/rollout")
    def publish():
        grant = publisher.grant()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"confirm_release_id"} or payload["confirm_release_id"] != grant["release_id"]:
            raise PublisherError("explicit_confirmation_required", 400)
        if not grant["lock"].acquire(blocking=False):
            raise PublisherError("publisher_busy", 409)
        try:
            envelope, artifact, digest = publisher.bundle()
            if digest != grant["digest"]:
                raise PublisherError("review_changed_bundle_again")
            if request.path.endswith("/upload"):
                publisher.remote("POST", "/api/updates/releases", session_cookie=grant["server_cookie"], artifact=artifact, envelope=envelope)
                return jsonify({"uploaded": True, "rollout_started": False})
            if not grant["rollout"]:
                raise PublisherError("upload_only_approval_cannot_rollout", 403)
            snapshot = publisher.remote("GET", "/api/updates/snapshot", session_cookie=grant["server_cookie"])
            found = any(row.get("id") == grant["release_id"] and row.get("envelope") == envelope for row in snapshot.get("releases", []))
            if not found:
                raise PublisherError("upload_before_rollout")
            publisher.remote("POST", "/api/updates/rollouts", grant["rollout"], session_cookie=grant["server_cookie"], request_id=grant["request_id"])
            return jsonify({"rollout_started": True, "installed": False})
        finally:
            grant["lock"].release()

    @bp.get("/api/software-updates/progress")
    def progress():
        grant = publisher.grant()
        snapshot = publisher.remote("GET", "/api/updates/snapshot", session_cookie=grant["server_cookie"])
        result = {"release_id": grant["release_id"], "uploaded": any(row.get("id") == grant["release_id"] for row in snapshot.get("releases", [])), "expires_at": grant["expires_at"], "rollout": next((row for row in snapshot.get("rollouts", []) if row.get("id") == "rollout-" + str(grant["request_id"])), None), "assignments": [row for row in snapshot.get("assignments", []) if row.get("release_id") == grant["release_id"]]}
        # Do not relay arbitrary Server fields or credentials to the browser.
        rollout = result.get("rollout")
        assignments = result.get("assignments")
        return jsonify({"release_id": result.get("release_id"), "uploaded": result.get("uploaded") is True,
                        "expires_at": result.get("expires_at"),
                        "rollout": {k: rollout.get(k) for k in ("id", "state")} if isinstance(rollout, dict) else None,
                        "assignments": [{k: row.get(k) for k in ("station", "state", "updated")}
                                        for row in assignments if isinstance(row, dict)] if isinstance(assignments, list) else []})

    @bp.post("/api/software-updates/logout")
    def logout():
        with publisher.lock:
            publisher.sessions.pop(request.cookies.get(COOKIE, ""), None)
            login = publisher.logins.pop(request.cookies.get(LOGIN_COOKIE, ""), None)
        if login:
            try:
                publisher.auth_remote("POST", "/api/auth/logout", {}, cookie=login["server_cookie"])
            except PublisherError:
                pass
        response = make_response(jsonify({"logged_out": True}))
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="Strict", path="/api/software-updates")
        response.delete_cookie(LOGIN_COOKIE, secure=True, httponly=True, samesite="Strict", path="/")
        return response

    app.register_blueprint(bp)
    return publisher
