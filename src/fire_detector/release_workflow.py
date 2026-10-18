"""Reviewed source snapshots and cancellable Station publication jobs.

Working files, HEAD and the real Git index are never reset during preparation
or cancellation. A candidate commit lives in a private Git ref until upload.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time


class WorkflowError(Exception):
    pass


def write_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class ReleaseWorkflow:
    TERMINAL = {"blocked", "cancelled", "failed", "github_failed", "completed", "interrupted", "cancelled_remote", "uploaded_cancelled"}

    def __init__(self, root, environ, protected, remote, verify):
        self.root, self.environ = Path(root), environ
        self.protected, self.remote, self.verify = protected, remote, verify
        self.reviews, self.jobs, self.events = {}, {}, {}
        self.gates = {}
        self.lock = threading.RLock()
        self.worker_lock = threading.Lock()
        self.runtime = None
        self.startup_fingerprint = None
        try:
            self.startup_fingerprint = self.fingerprint()
        except (WorkflowError, OSError, subprocess.SubprocessError):
            pass

    def directory(self):
        path = Path(self.environ.get("FIRE_UPDATE_STATE_DIR", str(self.root.parent / ".fire-detector-publisher"))).resolve()
        if path == self.root.resolve() or self.root.resolve() in path.parents:
            raise WorkflowError("publisher_state_must_be_outside_source")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path

    def command(self, *args, data=None, env=None, timeout=30, check=True):
        result = subprocess.run(["git", "-C", str(self.root), *args], input=data,
                                capture_output=True, timeout=timeout, env=env)
        if check and result.returncode:
            raise WorkflowError("git_operation_failed")
        return result

    def text(self, *args):
        return self.command(*args).stdout.decode().strip()

    def eligible(self, name):
        parts = PurePosixPath(name).parts
        if not name or self.protected(name) or not parts:
            return False
        return (parts[0] in {"src", "web", "scripts", "deploy", "docs", "tests", "camera_runtime"}
                or name in {"README.md", "HANDOFF.md", "requirements.txt", "AppSetting.example.JSON", "VERSION", "requirements-bookworm-aarch64.lock"})

    def read_file(self, name):
        if not self.eligible(name):
            raise WorkflowError("file_not_reviewable")
        path = self.root / name
        if not path.exists():
            return None
        if any(part.is_symlink() for part in [path, *path.parents] if part != self.root.parent):
            raise WorkflowError("symlink_not_reviewable")
        if not path.is_file() or self.root.resolve() not in path.resolve().parents:
            raise WorkflowError("file_not_reviewable")
        with path.open("rb") as stream:
            return stream.read()

    def inventory(self):
        names = self.command("ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout.decode().split("\0")
        return sorted({name for name in names if self.eligible(name)})

    def fingerprint(self):
        digest = hashlib.sha256()
        for name in self.inventory():
            content = self.read_file(name)
            if content is not None:
                digest.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
        return digest.hexdigest()

    def runtime_info(self):
        if self.runtime is not None:
            return self.runtime
        # Hash captured at construction, never relabel running code after edits.
        fingerprint = self.startup_fingerprint or self.fingerprint()
        path = self.directory() / "runtime.json"
        try:
            old = json.loads(path.read_text())
        except (OSError, ValueError):
            old = {}
        sequence = int(old.get("sequence", 0)) + (old.get("fingerprint") != fingerprint)
        sequence = max(1, sequence)
        version = self.environ.get("FIRE_DETECTOR_RELEASE_VERSION") or ("1.0.0" if sequence == 1 else f"1.0.0-dev.{sequence}")
        self.runtime = {"version": version, "id": f"run-{sequence:04d}-{fingerprint[:12]}",
                        "fingerprint": fingerprint, "sequence": sequence, "recorded_at": time.time()}
        write_json(path, self.runtime)
        return self.runtime

    def review(self, owner):
        head = self.text("rev-parse", "HEAD")
        staged = self.command("diff", "--cached", "--quiet", check=False).returncode != 0
        base = head
        rows, contents = [], {}
        for name in self.inventory():
            result = self.command("show", base + ":" + name, check=False)
            before = result.stdout if not result.returncode else None
            after = self.read_file(name)
            if before == after:
                continue
            binary = b"\0" in (after if after is not None else before or b"")
            digest = hashlib.sha256(after).hexdigest() if after is not None else None
            rows.append({"path": name, "status": "added" if before is None else "deleted" if after is None else "modified",
                         "sha256": digest, "size": len(after or b""), "binary": binary})
            contents[name] = (before, after)
        digest = hashlib.sha256(json.dumps({"head": head, "files": rows}, sort_keys=True).encode()).hexdigest()
        rid = "review-" + secrets.token_hex(12)
        version = "1.0.1"
        published = self.directory() / "last-published.json"
        if published.exists():
            last = json.loads(published.read_text())["version"]
            major, minor, patch = map(int, last.split("."))
            version = f"{major}.{minor}.{patch + 1}"
        result = {"id": rid, "digest": digest, "base_commit": head, "version": version,
                  "files": rows, "count": len(rows), "staged_changes": staged, "created_at": time.time()}
        with self.lock:
            self.reviews = {k: v for k, v in self.reviews.items() if time.time() - v["public"]["created_at"] < 1800}
            if len(self.reviews) >= 50:
                raise WorkflowError("too_many_reviews")
            self.reviews[rid] = {"owner": str(owner), "public": result, "contents": contents}
        return result

    def reviewed(self, rid, owner):
        with self.lock:
            review = self.reviews.get(rid)
        if not review or review["owner"] != str(owner) or time.time() - review["public"]["created_at"] > 1800:
            raise WorkflowError("review_expired")
        return review

    def preview(self, rid, name, owner):
        review = self.reviewed(rid, owner)
        if name not in review["contents"]:
            raise WorkflowError("file_not_reviewable")
        before, after = review["contents"][name]
        content = after if after is not None else before or b""
        if b"\0" in content or len(content) > 1024 * 1024:
            return {"path": name, "content": "Binary or large file. Review the size and checksum in the release file list.", "diff": ""}
        old, new = (before or b"").decode("utf-8", "replace"), (after or b"").decode("utf-8", "replace")
        return {"path": name, "content": content.decode("utf-8", "replace"),
                "diff": "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="Previous / " + name, tofile="Reviewed / " + name))}

    def snapshot(self, review, folder, release_id):
        if self.text("rev-parse", "HEAD") != review["public"]["base_commit"]:
            raise WorkflowError("source_changed_review_again")
        # Build a commit with a PRIVATE index. Never stage or overwrite user work.
        env = dict(os.environ, GIT_INDEX_FILE=str(folder / "index"),
                   GIT_AUTHOR_NAME="Station Publisher", GIT_AUTHOR_EMAIL="publisher@station.local",
                   GIT_COMMITTER_NAME="Station Publisher", GIT_COMMITTER_EMAIL="publisher@station.local")
        self.command("read-tree", review["public"]["base_commit"], env=env)
        for name, (_, after) in review["contents"].items():
            current = self.read_file(name)
            if current != after:
                raise WorkflowError("source_changed_review_again")
            if after is None:
                self.command("update-index", "--force-remove", "--", name, env=env)
            else:
                blob = self.command("hash-object", "-w", "--stdin", data=after).stdout.decode().strip()
                mode = "100755" if (self.root / name).stat().st_mode & 0o111 else "100644"
                self.command("update-index", "--add", "--cacheinfo", mode, blob, name, env=env)
        tree = self.command("write-tree", env=env).stdout.decode().strip()
        commit = self.command("commit-tree", tree, "-p", review["public"]["base_commit"],
                              data=("Release " + release_id + "\n").encode(), env=env).stdout.decode().strip()
        self.command("update-ref", "refs/publisher/" + release_id, commit)
        source = folder / "source"
        self.command("-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", str(source), commit)
        return commit, source

    def update(self, job, **fields):
        with self.lock:
            if fields.get("state") in self.TERMINAL:
                fields["paused"] = False
            job.update(fields, updated_at=time.time())
            write_json(self.directory() / "jobs" / (job["id"] + ".json"), job)

    def public_job(self, job):
        with self.lock:
            return {k: v for k, v in job.items() if k not in {"owner"}}

    def finalize_local_commit(self, job, review, folder):
        """Advance HEAD/index without overwriting working files or staged edits."""
        index = Path(self.text("rev-parse", "--git-path", "index"))
        if not index.is_absolute():
            index = self.root / index
        lock_path = index.with_name(index.name + ".lock")
        try:
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return "index_busy_preserved"
        try:
            with os.fdopen(fd, "wb") as stream:
                if (self.text("branch", "--show-current") != job["branch"]
                        or self.text("rev-parse", "HEAD") != review["public"]["base_commit"]
                        or self.command("diff", "--cached", "--quiet", check=False).returncode):
                    return "local_changes_preserved"
                stream.write((folder / "index").read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            self.command("update-ref", "HEAD", job["commit"], review["public"]["base_commit"])
            os.replace(lock_path, index)
            return "committed"
        finally:
            lock_path.unlink(missing_ok=True)

    def find_job(self, jid, owner):
        with self.lock:
            job = self.jobs.get(jid)
            if job is None and re.fullmatch(r"release-[a-zA-Z0-9_.-]+", jid):
                path = self.directory() / "jobs" / (jid + ".json")
                if path.exists():
                    job = json.loads(path.read_text())
                    if job["state"] not in self.TERMINAL:
                        job["state"], job["error"] = "interrupted", "reconcile_server_before_retry"
                    self.jobs[jid] = job
        if not job or job["owner"] != str(owner):
            raise WorkflowError("job_not_found")
        return job

    def start(self, rid, digest, owner, stations, session_cookie, source_station_id=None):
        if source_station_id is not None and (not isinstance(source_station_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", source_station_id)):
            raise WorkflowError("invalid_source_station_id")
        review = self.reviewed(rid, owner)
        if review["public"]["digest"] != digest:
            raise WorkflowError("source_changed_review_again")
        if review["public"]["staged_changes"]:
            raise WorkflowError("staged_changes_need_review")
        if not review["public"]["files"]:
            raise WorkflowError("no_source_changes")
        branch = self.text("branch", "--show-current")
        if not branch or not re.fullmatch(r"[A-Za-z0-9_./-]+", branch):
            raise WorkflowError("github_branch_not_configured")
        if not self.worker_lock.acquire(blocking=False):
            raise WorkflowError("publication_already_running")
        jid = "release-" + review["public"]["version"] + "-" + secrets.token_hex(6)
        job = {"id": jid, "owner": str(owner), "version": review["public"]["version"],
               "state": "preparing", "phase": "Preparing reviewed source", "progress": 0,
               "bytes_sent": 0, "bytes_total": 0, "uploaded": False, "github_pushed": False,
               "rollout_id": None, "stations": stations, "created_at": time.time(), "error": None,
               "branch": branch, "base_commit": review["public"]["base_commit"], "source_station_id": source_station_id}
        with self.lock:
            self.jobs[jid] = job
            self.events[jid] = threading.Event()
            self.gates[jid] = threading.Event()
            self.gates[jid].set()
        try:
            self.update(job)
            threading.Thread(target=self.run, args=(job, review, session_cookie), daemon=True, name="station-release").start()
        except Exception:
            self.worker_lock.release()
            raise
        return self.public_job(job)

    def run(self, job, review, session_cookie):
        folder = self.directory() / "jobs" / job["id"]
        folder.mkdir(mode=0o700, exist_ok=True)
        source = None
        cancel = self.events[job["id"]]
        try:
            helper = self.environ.get("FIRE_UPDATE_BUILD_HELPER")
            if not helper or not Path(helper).is_file() or not os.access(helper, os.X_OK):
                self.update(job, state="blocked", phase="Release builder is not configured", error="release_builder_not_configured")
                return
            if cancel.is_set():
                raise WorkflowError("cancelled")
            self.wait_for_resume(job)
            if review is None:
                commit, source = job["commit"], folder / "source"
                if not source.is_dir():
                    raise WorkflowError("candidate_snapshot_missing")
            else:
                if self.environ.get("FIRE_UPDATE_BUILD_CONFIG"):
                    config = json.loads(Path(self.environ["FIRE_UPDATE_BUILD_CONFIG"]).read_text())
                    info = self.remote("GET", "/api/updates/builds/info", session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
                    import fnmatch
                    if any(not any(fnmatch.fnmatchcase(name, pattern) for pattern in info.get("allowed_paths", [])) for name in config["files"]):
                        raise WorkflowError("server_source_policy_mismatch")
                    if not info.get("worker_heartbeat", {}).get("online"):
                        raise WorkflowError("server_signer_offline")
                    if any(row["path"] not in config["files"] for row in review["public"]["files"] if row["status"] != "deleted"):
                        raise WorkflowError("source_not_in_build_inventory")
                commit, source = self.snapshot(review, folder, job["id"])
            self.update(job, commit=commit, state="building", phase="Building and verifying the signed release")
            bundle = folder / "bundle"
            if not (bundle / "manifest.json").is_file() or not (bundle / "artifact.tar.gz").is_file():
                self.build(job, source, bundle, session_cookie, cancel)
            self.wait_for_resume(job)
            envelope, artifact, envelope_digest = self.verify(bundle, commit)
            if envelope["manifest"]["release_id"] != job["id"] or envelope["manifest"]["version"] != job["version"]:
                raise WorkflowError("builder_returned_wrong_release")
            if cancel.is_set():
                if job.get("signing_job_id") or job.get("signing_completed"):
                    self.reconcile_signing(job, session_cookie, True)
                raise WorkflowError("cancelled")
            self.update(job, state="uploading", phase="Uploading package", bytes_total=artifact.stat().st_size, artifact_sha256=envelope["manifest"]["sha256"], envelope_sha256=envelope_digest)
            def progress(sent, total):
                self.update(job, bytes_sent=sent, bytes_total=total, progress=round(sent * 100 / total, 1))
            if not job.get("uploaded"):
                self.remote("POST", "/api/updates/releases", artifact=artifact, envelope=envelope,
                            session_cookie=session_cookie, on_progress=progress, cancel=cancel, request_id=job["id"], source_station_id=job.get("source_station_id"), wait_for_resume=lambda: self.wait_for_resume(job))
            # A server ACK is the boundary: cancellation can no longer promise
            # that the immutable draft was not stored remotely.
            self.update(job, uploaded=True, state="uploaded", phase="Server accepted draft; backing up to GitHub", progress=100)
            write_json(self.directory() / "last-published.json", {"version": job["version"], "commit": commit, "release_id": job["id"]})
            if cancel.is_set():
                self.update(job, state="uploaded_cancelled", phase="Server already accepted the draft; no rollout or GitHub push started")
                return
            self.wait_for_resume(job)
            receipt = self.remote("GET", "/api/updates/releases/" + job["id"] + "/receipt", session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
            expected = {"release_id": job["id"], "git_commit": commit, "version": job["version"],
                        "size": envelope["manifest"]["size"], "sha256": envelope["manifest"]["sha256"],
                        "envelope_sha256": hashlib.sha256(json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=True, allow_nan=False).encode()).hexdigest(), "durable": True}
            if (not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items())
                    or receipt.get("durable") is not True or receipt.get("rollout_started") is not False):
                raise WorkflowError("server_release_verification_failed")
            self.update(job, receipt_verified=True)
            branch = job["branch"]
            if not branch or not re.fullmatch(r"[A-Za-z0-9_./-]+", branch):
                raise WorkflowError("github_branch_not_configured")
            self.update(job, state="github", phase="Pushing the accepted source to GitHub")
            # Atomic, non-forced push. A protected/ahead branch fails visibly;
            # it never undoes the successful server upload or overwrites GitHub.
            target = self.environ.get("FIRE_UPDATE_GITHUB_BRANCH", "main")
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", target):
                raise WorkflowError("github_branch_not_configured")
            refs = [commit + ":refs/heads/" + name for name in sorted({branch, target})]
            result = self.command("push", "--atomic", "origin", *refs,
                                  commit + ":refs/tags/station-" + job["version"],
                                  env=dict(os.environ, GIT_TERMINAL_PROMPT="0"), timeout=180, check=False)
            if result.returncode:
                self.update(job, state="github_failed", phase="Server draft saved; GitHub push needs retry", error="github_push_failed")
                return
            self.update(job, github_pushed=True)
            try:
                local_sync = self.finalize_local_commit(job, review or {"public": {"base_commit": job["base_commit"]}}, folder)
            except (OSError, WorkflowError):
                local_sync = "local_sync_needs_review"
            deployment_cancelled = job.get("rollout_disabled", False)
            self.update(job, state="uploaded_cancelled" if deployment_cancelled else "completed",
                        phase="Deployment cancelled; server draft and GitHub backup retained" if deployment_cancelled else "Draft uploaded and source pushed to GitHub",
                        github_pushed=True, local_sync=local_sync)
        except Exception as error:
            code = str(error) if isinstance(error, WorkflowError) else getattr(error, "code", "publication_failed")
            if job.get("uploaded") and (code == "cancelled" or cancel.is_set()):
                self.update(job, state="uploaded_cancelled", phase="Update cancelled; accepted server draft retained", error=None, paused=False)
            elif code == "server_signing_cancelled":
                self.update(job, state="cancelled", phase="Update cancelled; original source preserved", error=None)
            elif code == "signing_outcome_requires_reconciliation":
                self.update(job, state="interrupted", phase="Signing outcome requires reconciliation", error=code)
            elif job.get("state") == "uploading":
                self.update(job, state="interrupted", phase="Upload outcome requires server reconciliation", error="upload_outcome_unknown")
            elif code == "cancelled" or cancel.is_set():
                state = "interrupted" if job.get("state") == "uploading" else "cancelled"
                self.update(job, state=state, phase="Upload outcome requires server reconciliation" if state == "interrupted" else "Cancelled; original source preserved",
                            error="upload_outcome_unknown" if state == "interrupted" else None)
            else:
                self.update(job, state="failed", phase="Update failed", error=code)
        finally:
            # Preserve the candidate worktree for interrupted jobs/reconciliation.
            if source and job["state"] == "completed":
                self.command("worktree", "remove", "--force", str(source), check=False)
            self.gates.pop(job["id"], None)
            self.worker_lock.release()

    def resume(self, job, session_cookie):
        if self.environ.get("FIRE_UPDATE_BUILD_HELPER_ADAPTER") == "station-header" and not job.get("source_station_id"):
            raise WorkflowError("source_station_id_missing_review_again")
        if job.get("paused") and job["id"] in self.gates and job["state"] not in self.TERMINAL:
            self.update(job, paused=False)
            self.gates[job["id"]].set()
            return self.public_job(job)
        if job["state"] not in {"interrupted", "github_failed"} or not job.get("commit"):
            raise WorkflowError("job_not_resumable")
        if not self.worker_lock.acquire(blocking=False):
            raise WorkflowError("publication_already_running")
        try:
            self.events[job["id"]] = threading.Event()
            self.gates[job["id"]] = threading.Event()
            self.gates[job["id"]].set()
            self.update(job, paused=False, state="preparing", phase="Reconciling the same approved candidate", error=None, cancel_requested=False)
            threading.Thread(target=self.run, args=(job, None, session_cookie), daemon=True, name="station-release-resume").start()
        except Exception:
            self.worker_lock.release()
            raise
        return self.public_job(job)

    def build(self, job, source, bundle, session_cookie, cancel):
        """Pass this owner's session on a private inherited pipe, never argv/env."""
        helper = self.environ["FIRE_UPDATE_BUILD_HELPER"]
        command = [helper]
        env = dict(os.environ)
        if job.get("source_station_id"):
            env["FIRE_UPDATE_STATION_ID"] = job["source_station_id"]
        if self.environ.get("FIRE_UPDATE_BUILD_HELPER_ADAPTER") == "station-header":
            if not job.get("source_station_id"):
                raise WorkflowError("source_station_id_missing_review_again")
            command = [sys.executable, str(Path(__file__).with_name("publisher_builder.py")), helper]
        for name in ("FIRE_UPDATE_SERVER", "FIRE_UPDATE_BUILD_CONFIG", "FIRE_UPDATE_PUBLIC_KEY", "FIRE_UPDATE_KEY_ID", "FIRE_UPDATE_CA"):
            if self.environ.get(name):
                env[name] = self.environ[name]
        if job.get("source_station_id") and self.environ.get("FIRE_UPDATE_BUILD_CONFIG"):
            config = json.loads(Path(self.environ["FIRE_UPDATE_BUILD_CONFIG"]).read_text())
            config["notes"] = config.get("notes", "Station release").rstrip() + "\n\nSource Station ID: " + job["source_station_id"]
            job_config = bundle.parent / "build-config.json"
            write_json(job_config, config)
            env["FIRE_UPDATE_BUILD_CONFIG"] = str(job_config)
        read_fd, write_fd = os.pipe()
        process = None
        reader = None
        suspended = False
        try:
            cookie = session_cookie.encode("ascii")
            if not cookie or len(cookie) > 4096 or b"\n" in cookie or b"\r" in cookie:
                raise WorkflowError("invalid_server_session")
            os.write(write_fd, cookie)
            os.close(write_fd)
            write_fd = None
            env["FIRE_UPDATE_SESSION_FD"] = str(read_fd)
            with (bundle.parent / "build.log").open("wb") as log:
                process = subprocess.Popen([*command, "--source", str(source), "--commit", job["commit"],
                    "--version", job["version"], "--release-id", job["id"], "--output", str(bundle)],
                    cwd=source, stdout=subprocess.PIPE, stderr=log, env=env, pass_fds=(read_fd,), start_new_session=True)
                os.close(read_fd)
                read_fd = None
                def events():
                    for raw in iter(lambda: process.stdout.readline(16385), b""):
                        try:
                            event = json.loads(raw)
                            if not isinstance(event, dict):
                                continue
                            phase = event.get("phase")
                            labels = {"building": "Building and testing in sandbox", "signing_upload": "Sending unsigned package for signing",
                                      "signing_job": "Waiting for server signature", "completed": "Signed package ready; verifying"}
                            if phase in {"failed_or_unknown", "cancellation_unknown", "cancel_result"}:
                                diagnostics = {}
                                error_type = event.get("error_type")
                                if isinstance(error_type, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", error_type):
                                    diagnostics["helper_error_type"] = error_type
                                status = event.get("http_status")
                                if type(status) is int and 400 <= status <= 599:
                                    diagnostics["helper_http_status"] = status
                                self.update(job, signing_reconcile_required=bool(event.get("reconcile_required")) or phase != "failed_or_unknown", **diagnostics)
                                continue
                            if phase not in labels:
                                continue
                            values = {"phase": labels[phase], "helper_phase": phase}
                            if phase == "signing_upload":
                                sent, total = event.get("bytes_sent"), event.get("bytes_total")
                                if type(sent) is int and type(total) is int and 0 <= sent <= total and total > 0:
                                    values.update(bytes_sent=sent, bytes_total=total, progress=round(sent * 100 / total, 1))
                            if phase == "signing_job" and re.fullmatch(r"[a-f0-9]{32}", str(event.get("id", ""))):
                                values["signing_job_id"] = event["id"]
                            self.update(job, **values)
                        except (ValueError, TypeError):
                            continue
                reader = threading.Thread(target=events, daemon=True, name="release-events")
                reader.start()
                deadline = time.monotonic() + 2460
                stopped = False
                while process.poll() is None:
                    import signal
                    gate = self.gates.get(job["id"])
                    pause_now = gate is not None and not gate.is_set() and not cancel.is_set()
                    if pause_now and not suspended:
                        os.killpg(process.pid, signal.SIGSTOP)
                        suspended = True
                        paused_at = time.monotonic()
                    elif suspended and not pause_now:
                        os.killpg(process.pid, signal.SIGCONT)
                        suspended = False
                        deadline += time.monotonic() - paused_at
                    if cancel.wait(0.2) or (not suspended and time.monotonic() > deadline):
                        import signal
                        stopped = True
                        if suspended:
                            os.killpg(process.pid, signal.SIGCONT)
                            suspended = False
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=65)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                        break
                reader.join(timeout=5)
                if stopped or process.returncode:
                    if job.get("signing_reconcile_required") or job.get("helper_phase") in {"signing_upload", "signing_job", "completed"}:
                        self.reconcile_signing(job, session_cookie, cancel.is_set())
                    if stopped or process.returncode == 130:
                        raise WorkflowError("cancelled" if cancel.is_set() else "build_timed_out")
                    status = job.get("helper_http_status")
                    if status in {401, 403}:
                        raise WorkflowError("server_build_access_denied")
                    if status in {429, 503}:
                        raise WorkflowError("server_build_unavailable")
                    if job.get("helper_error_type") == "RecursionError":
                        raise WorkflowError("publisher_connection_failed")
                    raise WorkflowError("release_build_failed")
            self.update(job, bytes_sent=0, bytes_total=0, progress=0, helper_phase="verified_output", signing_completed=bool(job.get("signing_job_id")))
        finally:
            for fd in (read_fd, write_fd):
                if fd is not None:
                    os.close(fd)
            if suspended and process and process.poll() is None:
                import signal
                os.killpg(process.pid, signal.SIGCONT)
            if process and process.stdout:
                process.stdout.close()

    def reconcile_signing(self, job, session_cookie, cancelling):
        """Cancellation cannot promise remote rollback after signing starts."""
        try:
            path = "/api/updates/builds/by-key/" + job["id"]
            result = self.remote("GET", path, session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
            if cancelling and result.get("state") in {"queued", "validating"} and result.get("id"):
                try:
                    self.remote("POST", "/api/updates/builds/" + result["id"] + "/cancel", {}, session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
                except Exception:
                    pass
                result = self.remote("GET", path, session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
            actual = result.get("state")
            self.update(job, signing_state=actual if actual in {"queued", "validating", "signing", "completed", "cancelled", "failed", "interrupted"} else "unknown")
            if actual == "failed":
                raise WorkflowError("server_signing_failed")
            if actual == "cancelled" and not cancelling:
                raise WorkflowError("server_signing_cancelled")
            if actual != "cancelled":
                self.update(job, state="interrupted", phase="Signing outcome requires reconciliation", error="signing_outcome_requires_reconciliation")
                raise WorkflowError("signing_outcome_requires_reconciliation")
        except WorkflowError:
            raise
        except Exception:
            self.update(job, state="interrupted", phase="Signing outcome is unknown", error="signing_outcome_requires_reconciliation")
            raise WorkflowError("signing_outcome_requires_reconciliation") from None

    def pause(self, job):
        if job["state"] in self.TERMINAL or job.get("uploaded") or job.get("cancel_requested"):
            raise WorkflowError("job_cannot_be_stopped")
        gate = self.gates.get(job["id"])
        if gate is None:
            raise WorkflowError("job_not_running")
        gate.clear()
        self.update(job, paused=True)
        return self.public_job(job)

    def wait_for_resume(self, job):
        gate = self.gates.get(job["id"])
        while gate is not None and not gate.wait(0.2):
            if self.events[job["id"]].is_set():
                raise WorkflowError("cancelled")
        if self.events[job["id"]].is_set():
            raise WorkflowError("cancelled")

    def observe(self, job, session_cookie):
        """Read remote state automatically, without starting a build or upload."""
        if job["state"] == "interrupted" and job.get("error") == "upload_outcome_unknown":
            if time.time() - job.get("server_checked_at", 0) < 5:
                return
            self.update(job, server_checked_at=time.time())
            try:
                receipt = self.remote("GET", "/api/updates/releases/" + job["id"] + "/receipt", session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
                expected = {"release_id": job["id"], "git_commit": job["commit"], "version": job["version"],
                            "sha256": job["artifact_sha256"], "size": job["bytes_total"], "envelope_sha256": job["envelope_sha256"]}
                if receipt.get("durable") is True and receipt.get("rollout_started") is False and all(receipt.get(k) == v for k, v in expected.items()):
                    self.update(job, uploaded=True, receipt_verified=True, state="github_failed", phase="Upload verified; click Resume to finish GitHub backup", error="github_push_pending")
            except Exception:
                pass
            return
        if job["state"] != "interrupted" or not job.get("signing_reconcile_required"):
            return
        if job.get("signing_state") == "failed":
            self.update(job, state="failed", error="server_signing_failed", phase="Server rejected package signing", paused=False)
            return
        if time.time() - job.get("server_checked_at", 0) < 5:
            return
        self.update(job, server_checked_at=time.time())
        try:
            result = self.remote("GET", "/api/updates/builds/by-key/" + job["id"], session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
            actual = result.get("state")
            if actual in {"queued", "validating", "signing", "completed", "failed", "cancelled", "interrupted"}:
                self.update(job, signing_state=actual)
            if actual == "failed":
                self.update(job, state="failed", error="server_signing_failed", phase="Server rejected package signing", paused=False)
            elif actual == "cancelled":
                self.update(job, state="cancelled", error=None, phase="Update cancelled; original source preserved", paused=False)
            elif actual == "completed":
                self.update(job, phase="Signed package ready; click Resume to continue", error=None)
        except Exception:
            pass  # Keep an unknown outcome unknown; never claim rollback.

    def cancel_update(self, job, session_cookie):
        if job.get("rollout_id"):
            result = self.remote("POST", "/api/updates/rollouts/" + job["rollout_id"] + "/cancel", {}, session_cookie=session_cookie, source_station_id=job.get("source_station_id"))
            if result.get("state") != "cancelled":
                raise WorkflowError("rollout_cancellation_not_confirmed")
            self.update(job, state="cancelled_remote", phase="Deployment cancelled; stations already installing may finish", error=None)
        elif job.get("uploaded"):
            self.update(job, rollout_disabled=True)
            if job["state"] not in self.TERMINAL:
                if job["state"] != "github":
                    self.events[job["id"]].set()
                    if job["id"] in self.gates:
                        self.gates[job["id"]].set()
                self.update(job, phase="Cancelling deployment; accepted server draft retained")
            else:
                self.update(job, state="uploaded_cancelled", phase="Deployment cancelled; server draft and GitHub backup retained", error=None)
        elif job["state"] not in self.TERMINAL:
            return self.cancel(job)
        elif job.get("error") == "upload_outcome_unknown":
            raise WorkflowError("upload_outcome_unknown")
        elif job.get("signing_state") in {"failed", "cancelled"}:
            self.update(job, state="cancelled", phase="Update cancelled; original source preserved", error=None, paused=False)
        elif job.get("signing_reconcile_required") or job.get("signing_job_id"):
            try:
                self.reconcile_signing(job, session_cookie, True)
            except WorkflowError as error:
                if str(error) != "server_signing_failed":
                    raise
            self.update(job, state="cancelled", phase="Update cancelled; original source preserved", error=None, paused=False)
        else:
            self.update(job, state="cancelled", phase="Update cancelled; original source preserved", error=None, paused=False)
        return self.public_job(job)

    def cancel(self, job):
        if job.get("uploaded"):
            raise WorkflowError("server_already_accepted_draft")
        if job["state"] in self.TERMINAL:
            return self.public_job(job)
        self.events[job["id"]].set()
        if job["id"] in self.gates:
            self.gates[job["id"]].set()
        self.update(job, cancel_requested=True, paused=False, phase="Cancelling; preserving original source")
        return self.public_job(job)
