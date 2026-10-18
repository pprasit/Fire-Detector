import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from fire_detector.release_workflow import ReleaseWorkflow, WorkflowError
from fire_detector.software_updates import Publisher, protected


class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        (self.root / "src").mkdir(parents=True)
        (self.root / "src/main.py").write_text("print('old')\n")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("add", "src/main.py")
        self.git("commit", "-qm", "Initial")
        self.head = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.bare = self.base / "github.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.bare)], check=True)
        self.git("remote", "add", "origin", str(self.bare))
        self.private, self.public = self.base / "private.pem", self.base / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.private)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(self.private), "-pubout", "-out", str(self.public)], check=True, capture_output=True)
        self.env = {"FIRE_UPDATE_STATE_DIR":str(self.base / "state"), "FIRE_UPDATE_VERIFY_KEY":str(self.public),
                    "FIRE_UPDATE_VERIFY_KEY_ID":"test-key"}
        self.publisher = Publisher(self.root, environ=self.env)
        self.calls = []
        self.accepted = None
        self.workflow = ReleaseWorkflow(self.root, self.env, protected, self.remote, self.publisher.verify_bundle)
        self.initial_index = (self.root / ".git/index").read_bytes()

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, check=check)

    def edit(self):
        (self.root / "src/main.py").write_text("print('new')\n")
        (self.root / "src/added.py").write_text("value = 42\n")
        (self.root / "AppSetting.JSON").write_text('{"password":"never-release-this"}')

    def builder(self, body=None):
        path = self.base / "builder.py"
        if body is None:
            body = '''import argparse,base64,hashlib,json,pathlib,subprocess,tarfile
p=argparse.ArgumentParser()
for name in ('source','commit','version','release-id','output'):p.add_argument('--'+name,required=True)
a=p.parse_args();folder=pathlib.Path(a.output);folder.mkdir()
artifact=folder/'artifact.tar.gz'
with tarfile.open(artifact,'w:gz') as archive:archive.add(pathlib.Path(a.source)/'src',arcname='app/src')
m={'release_id':a.release_id,'version':a.version,'git_commit':a.commit,'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'size':artifact.stat().st_size}
canonical=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
data=folder/'sign-data';data.write_bytes(canonical(m))
sig=subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',PRIVATE,'-in',str(data)],check=True,capture_output=True).stdout
(folder/'manifest.json').write_bytes(canonical({'manifest':m,'key_id':'test-key','signature':base64.b64encode(sig).decode()}))
'''.replace("PRIVATE", repr(str(self.private)))
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o700)
        self.env["FIRE_UPDATE_BUILD_HELPER"] = str(path)

    def remote(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path))
        self.assertFalse(self.github_has_main())
        if path.endswith("/releases"):
            self.assertEqual(kwargs["session_cookie"], "server-session-test")
            total = kwargs["artifact"].stat().st_size
            kwargs["on_progress"](total // 2, total)
            kwargs["on_progress"](total, total)
            self.accepted = kwargs["envelope"]
            return {"release_id": self.accepted["manifest"]["release_id"]}
        m = self.accepted["manifest"]
        return {**{k: m[k] for k in ("release_id", "git_commit", "version", "size", "sha256")},
                "envelope_sha256": hashlib.sha256(json.dumps(self.accepted,sort_keys=True,separators=(",", ":"),ensure_ascii=True,allow_nan=False).encode()).hexdigest(),
                "durable": True, "rollout_started": False}

    def github_has_main(self):
        return subprocess.run(["git", "--git-dir", str(self.bare), "rev-parse", "--verify", "refs/heads/main"], capture_output=True).returncode == 0

    def start(self):
        review = self.workflow.review(7)
        job = self.workflow.start(review["id"], review["digest"], 7, ["pi-test"], "server-session-test")
        return review, job

    def wait(self, jid):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.workflow.find_job(jid, 7)
            if job["state"] in self.workflow.TERMINAL:
                self.assertTrue(self.workflow.worker_lock.acquire(timeout=10))
                self.workflow.worker_lock.release()
                return job
            time.sleep(.03)
        self.fail("Job timed out")

    def test_review_only_contains_changed_source_and_safe_exact_file_preview(self):
        self.edit()
        review = self.workflow.review(7)
        self.assertEqual({f["path"]:f["status"] for f in review["files"]}, {"src/main.py":"modified", "src/added.py":"added"})
        before = self.workflow.preview(review["id"], "src/main.py", 7)
        (self.root / "src/main.py").write_text("later edit")
        self.assertEqual(self.workflow.preview(review["id"], "src/main.py", 7), before)
        self.assertIn("-print('old')", before["diff"])
        for name in ("AppSetting.JSON", "../repo/src/main.py", ".git/config"):
            with self.assertRaises(WorkflowError):self.workflow.preview(review["id"], name, 7)
        with self.assertRaises(WorkflowError):self.workflow.preview(review["id"], "src/main.py", 8)

    def test_deleted_file_and_symlink_are_handled_without_reading_external_data(self):
        (self.root / "src/main.py").unlink()
        review = self.workflow.review(7)
        self.assertEqual(review["files"][0]["status"], "deleted")
        outside = self.base / "private.txt";outside.write_text("private")
        (self.root / "src/leak.py").symlink_to(outside)
        with self.assertRaises(WorkflowError):self.workflow.review(7)

    def test_initial_running_version_is_numbered_and_does_not_relabel_after_edits(self):
        initial = self.workflow.runtime_info()
        self.assertEqual(initial["version"], "1.0.0")
        self.assertTrue(initial["id"].startswith("run-0001-"))
        self.edit()
        self.assertEqual(self.workflow.runtime_info(), initial)
        restarted = ReleaseWorkflow(self.root, self.env, protected, self.remote, self.publisher.verify_bundle)
        self.assertNotEqual(restarted.runtime_info()["id"], initial["id"])

    def test_missing_builder_is_explicit_and_preserves_all_original_work(self):
        self.edit(); _, job = self.start(); result = self.wait(job["id"])
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["error"], "release_builder_not_configured")
        self.assertFalse(self.calls)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.decode().strip(), self.head)
        self.assertEqual((self.root / ".git/index").read_bytes(), self.initial_index)
        self.assertEqual((self.root / "src/main.py").read_text(), "print('new')\n")

    def test_success_verifies_server_before_push_and_preserves_source(self):
        self.builder();self.edit();_, job = self.start();result = self.wait(job["id"])
        self.assertEqual(result["state"], "completed", result)
        self.assertTrue(result["uploaded"])
        self.assertTrue(result["github_pushed"])
        self.assertEqual(result["progress"], 100)
        self.assertEqual(self.calls, [("POST","/api/updates/releases"),("GET","/api/updates/releases/"+job["id"]+"/receipt")])
        self.assertTrue(self.github_has_main())
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.decode().strip(), result["commit"])
        self.assertEqual((self.root / "src/main.py").read_text(), "print('new')\n")
        self.assertNotIn("AppSetting.JSON", self.git("ls-tree", "-r", "--name-only", result["commit"]).stdout.decode())
        self.assertEqual(self.workflow.review(7)["version"], "1.0.2")

    def test_source_edit_after_review_rejects_release_without_git_or_server_changes(self):
        self.builder();self.edit();review = self.workflow.review(7)
        (self.root / "src/main.py").write_text("unreviewed change")
        job = self.workflow.start(review["id"], review["digest"], 7, [], "server-session-test")
        result = self.wait(job["id"])
        self.assertEqual(result["error"], "source_changed_review_again")
        self.assertFalse(self.calls)
        self.assertFalse(self.github_has_main())
        self.assertEqual((self.root / "src/main.py").read_text(), "unreviewed change")

    def test_existing_staged_changes_are_never_overwritten(self):
        self.builder();self.edit();self.git("add", "src/main.py")
        index = (self.root / ".git/index").read_bytes();review = self.workflow.review(7)
        with self.assertRaises(WorkflowError):self.workflow.start(review["id"], review["digest"], 7, [], "server-session-test")
        self.assertEqual((self.root / ".git/index").read_bytes(), index)

    def test_cancel_during_build_restores_no_files_because_source_was_never_changed(self):
        self.builder("import time\ntime.sleep(30)\n");self.edit();_, job = self.start()
        deadline = time.monotonic()+5
        while self.workflow.find_job(job["id"],7)["state"] != "building" and time.monotonic()<deadline:time.sleep(.02)
        self.workflow.cancel(self.workflow.find_job(job["id"],7))
        result=self.wait(job["id"])
        self.assertEqual(result["state"],"cancelled")
        self.assertFalse(self.calls)
        self.assertEqual(self.git("rev-parse","HEAD").stdout.decode().strip(),self.head)
        self.assertEqual((self.root/"src/main.py").read_text(),"print('new')\n")

    def test_upload_cancel_is_not_falsely_reported_as_remote_rollback(self):
        self.builder();self.edit();entered=threading.Event()
        def upload(*args,**kwargs):
            entered.set();kwargs["cancel"].wait(5);raise WorkflowError("cancelled")
        self.workflow.remote=upload
        _,job=self.start();self.assertTrue(entered.wait(5))
        self.workflow.cancel(self.workflow.find_job(job["id"],7));result=self.wait(job["id"])
        self.assertEqual(result["state"],"interrupted")
        self.assertEqual(result["error"],"upload_outcome_unknown")
        self.assertFalse(result["github_pushed"])

    def test_server_rejection_or_unverified_ack_never_pushes_github(self):
        self.builder();self.edit()
        self.workflow.remote=lambda *a,**kw: {"releases":[]}
        _,job=self.start();result=self.wait(job["id"])
        self.assertEqual(result["error"],"server_release_verification_failed")
        self.assertFalse(self.github_has_main())
        self.assertEqual(self.git("rev-parse","HEAD").stdout.decode().strip(),self.head)

    def test_helper_receives_session_only_on_private_fd(self):
        self.builder("import os\nfd=int(os.environ['FIRE_UPDATE_SESSION_FD'])\nassert os.read(fd,4096)==b'server-session-test'\nassert not any('server-session-test' in value for value in os.environ.values())\nraise SystemExit(1)\n")
        self.edit();_,job=self.start();result=self.wait(job["id"])
        self.assertEqual(result["error"],"release_build_failed")
        self.assertNotIn("server-session-test",json.dumps(result))
        self.assertFalse(self.calls)

    def test_receipt_requires_actual_durable_checksum_before_push(self):
        self.builder();self.edit()
        remote=self.workflow.remote
        def bad_receipt(method,path,*args,**kwargs):
            result=remote(method,path,*args,**kwargs)
            if path.endswith('/receipt'):result['sha256']='0'*64
            return result
        self.workflow.remote=bad_receipt
        _,job=self.start();result=self.wait(job['id'])
        self.assertEqual(result['error'],'server_release_verification_failed')
        self.assertFalse(self.github_has_main())

    def test_resume_after_github_failure_reuses_exact_candidate_and_signed_package(self):
        self.builder();self.edit()
        self.git('remote','set-url','origin',str(self.base/'unavailable.git'))
        _,job=self.start();first=self.wait(job['id'])
        self.assertEqual(first['state'],'github_failed')
        commit=first['commit']
        self.git('remote','set-url','origin',str(self.bare))
        # A resume must neither invoke the builder nor create another candidate.
        Path(self.env['FIRE_UPDATE_BUILD_HELPER']).write_text('#!/bin/sh\nexit 99\n')
        self.workflow.resume(first,'server-session-test')
        result=self.wait(job['id'])
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['commit'],commit)
        self.assertEqual(sum(path.endswith('/releases') for _,path in self.calls),1)

    def test_unknown_signing_cancellation_is_preserved_for_reconciliation(self):
        self.builder("import json,time\nprint(json.dumps({'phase':'signing_job','id':'a'*32,'state':'signing'}),flush=True)\ntime.sleep(30)\n")
        self.edit()
        self.workflow.remote=lambda *a,**kw:{'state':'signing','id':'a'*32}
        _,job=self.start()
        deadline=time.monotonic()+5
        while not self.workflow.find_job(job['id'],7).get('signing_job_id') and time.monotonic()<deadline:time.sleep(.02)
        self.workflow.cancel(self.workflow.find_job(job['id'],7))
        result=self.wait(job['id'])
        self.assertEqual(result['state'],'interrupted')
        self.assertEqual(result['signing_state'],'signing')
        self.assertFalse(result['uploaded'])

    def test_stop_and_resume_upload_preserves_candidate_and_original_source(self):
        self.builder();self.edit()
        entered, proceed, second = threading.Event(), threading.Event(), threading.Event()
        remote=self.workflow.remote
        def upload(method,path,*args,**kwargs):
            if path.endswith('/releases'):
                entered.set();proceed.wait(5)
                kwargs['wait_for_resume']()
                second.set()
            return remote(method,path,*args,**kwargs)
        self.workflow.remote=upload
        _,job=self.start();self.assertTrue(entered.wait(5))
        current=self.workflow.find_job(job['id'],7);commit=current['commit']
        self.workflow.pause(current);proceed.set()
        self.assertFalse(second.wait(.3))
        self.assertTrue(current['paused'])
        self.assertEqual(self.git('rev-parse','HEAD').stdout.decode().strip(),self.head)
        self.workflow.resume(current,'server-session-test')
        result=self.wait(job['id'])
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['commit'],commit)

    def test_cancel_while_helper_is_stopped_does_not_leave_a_frozen_process(self):
        self.builder("import time\ntime.sleep(30)\n");self.edit();_,job=self.start()
        deadline=time.monotonic()+5
        while self.workflow.find_job(job['id'],7)['state']!='building' and time.monotonic()<deadline:time.sleep(.02)
        current=self.workflow.find_job(job['id'],7)
        self.workflow.pause(current);time.sleep(.4)
        self.workflow.cancel_update(current,'server-session-test')
        result=self.wait(job['id'])
        self.assertEqual(result['state'],'cancelled',result)
        self.assertFalse(self.calls)
        self.assertEqual(self.git('rev-parse','HEAD').stdout.decode().strip(),self.head)

    def test_known_signing_failure_is_not_left_as_unknown_100_percent(self):
        job={'id':'release-test','owner':'7','state':'interrupted','signing_reconcile_required':True,
             'signing_state':'failed','uploaded':False,'github_pushed':False,'progress':100}
        self.workflow.jobs[job['id']]=job
        self.workflow.observe(job,'server-session-test')
        self.assertEqual(job['state'],'failed')
        self.assertEqual(job['error'],'server_signing_failed')
        self.assertFalse(job['uploaded']);self.assertFalse(job['github_pushed'])
        self.assertFalse(self.calls)

    def test_cancel_interrupted_signing_waits_for_actual_server_cancellation(self):
        job={'id':'release-test','owner':'7','state':'interrupted','signing_reconcile_required':True,'uploaded':False}
        cancelled=[]
        def remote(method,path,*args,**kwargs):
            if method=='POST':cancelled.append(path)
            return {'id':'a'*32,'state':'cancelled' if cancelled else 'validating'}
        self.workflow.remote=remote
        self.workflow.cancel_update(job,'server-session-test')
        self.assertEqual(job['state'],'cancelled')
        self.assertEqual(cancelled,['/api/updates/builds/'+('a'*32)+'/cancel'])

    def test_cancel_saved_draft_never_undoes_github_or_working_source(self):
        self.builder();self.edit();_,job=self.start();result=self.wait(job['id'])
        commit=result['commit'];self.workflow.cancel_update(result,'server-session-test')
        self.assertEqual(result['state'],'uploaded_cancelled')
        self.assertTrue(result['uploaded']);self.assertTrue(result['github_pushed'])
        self.assertTrue(result['rollout_disabled'])
        self.assertEqual(self.git('rev-parse','HEAD').stdout.decode().strip(),commit)
        self.assertTrue(self.github_has_main())

    def test_unknown_upload_is_observed_using_exact_receipt_without_pushing(self):
        job={'id':'release-test','owner':'7','state':'interrupted','error':'upload_outcome_unknown',
             'commit':'a'*40,'version':'1.0.1','artifact_sha256':'b'*64,'envelope_sha256':'c'*64,'bytes_total':123}
        self.workflow.remote=lambda *a,**kw:{'release_id':job['id'],'git_commit':job['commit'],'version':job['version'],
            'sha256':job['artifact_sha256'],'envelope_sha256':job['envelope_sha256'],'size':123,'durable':True,'rollout_started':False}
        self.workflow.observe(job,'server-session-test')
        self.assertTrue(job['uploaded']);self.assertTrue(job['receipt_verified'])
        self.assertEqual(job['state'],'github_failed')
        self.assertFalse(self.github_has_main())

    def test_real_helper_process_stops_and_resumes_without_changing_commit(self):
        marker=self.base/'heartbeat';pid_file=self.base/'helper-pid'
        self.builder("import os,pathlib,time\npathlib.Path("+repr(str(pid_file))+").write_text(str(os.getpid()))\np=pathlib.Path("+repr(str(marker))+")\nfor index in range(1000):\n p.write_text(str(index))\n time.sleep(.03)\n")
        self.edit();_,job=self.start()
        deadline=time.monotonic()+5
        while (not marker.exists() or not pid_file.exists()) and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(marker.exists())
        current=self.workflow.find_job(job['id'],7);commit=current['commit']
        self.workflow.pause(current)
        status=Path('/proc')/pid_file.read_text()/'status'
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            process_state=next(line for line in status.read_text().splitlines() if line.startswith('State:'))
            if process_state.split()[1]=='T':break
            time.sleep(.02)
        else:self.fail('Helper did not enter the stopped process state')
        stopped=marker.read_text();time.sleep(.15)
        self.assertEqual(marker.read_text(),stopped)
        self.workflow.resume(current,'server-session-test')
        deadline=time.monotonic()+5
        while marker.read_text()==stopped and time.monotonic()<deadline:time.sleep(.02)
        self.assertNotEqual(marker.read_text(),stopped)
        self.assertEqual(current['commit'],commit)
        self.workflow.cancel_update(current,'server-session-test')
        result=self.wait(job['id']);self.assertEqual(result['state'],'cancelled')

    def test_source_station_id_is_persisted_and_forwarded_with_same_snapshot(self):
        self.builder();self.edit()
        helper=Path(self.env['FIRE_UPDATE_BUILD_HELPER'])
        lines=helper.read_text().splitlines(keepends=True)
        helper.write_text(lines[0]+"import os\nassert os.environ['FIRE_UPDATE_STATION_ID']=='station-original'\n"+''.join(lines[1:]))
        remote=self.workflow.remote
        def upload(method,path,*args,**kwargs):
            if path.endswith('/releases'):self.assertEqual(kwargs['source_station_id'],'station-original')
            return remote(method,path,*args,**kwargs)
        self.workflow.remote=upload
        review=self.workflow.review(7)
        job=self.workflow.start(review['id'],review['digest'],7,[],'server-session-test',source_station_id='station-original')
        result=self.wait(job['id'])
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['source_station_id'],'station-original')
        saved=json.loads((self.workflow.directory()/'jobs'/(job['id']+'.json')).read_text())
        self.assertEqual(saved['source_station_id'],'station-original')

    def test_station_origin_is_added_to_per_job_notes_without_editing_base_config(self):
        self.builder()
        config=self.base/'native-build.json';config.write_text(json.dumps({'notes':'Approved release'}))
        self.env['FIRE_UPDATE_BUILD_CONFIG']=str(config)
        helper=Path(self.env['FIRE_UPDATE_BUILD_HELPER']);lines=helper.read_text().splitlines(keepends=True)
        helper.write_text(lines[0]+"import os,json\nassert json.load(open(os.environ['FIRE_UPDATE_BUILD_CONFIG']))['notes']=='Approved release\\n\\nSource Station ID: station-alpha'\n"+''.join(lines[1:]))
        folder=self.base/'origin-build';folder.mkdir()
        job={'id':'release-origin','owner':'7','state':'building','version':'1.0.1','commit':self.head,'source_station_id':'station-alpha'}
        self.workflow.build(job,self.root,folder/'bundle','server-session-test',threading.Event())
        self.assertEqual(json.loads(config.read_text()),{'notes':'Approved release'})
        copied=json.loads((folder/'build-config.json').read_text())
        self.assertIn('Source Station ID: station-alpha',copied['notes'])

    def test_helper_access_denied_has_a_safe_specific_error(self):
        self.builder("import json\nprint(json.dumps({'phase':'failed_or_unknown','error_type':'RemoteError','http_status':403,'reconcile_required':False}),flush=True)\nraise SystemExit(1)\n")
        self.edit();_,job=self.start();result=self.wait(job['id'])
        self.assertEqual(result['error'],'server_build_access_denied')
        self.assertEqual(result['helper_http_status'],403)
        self.assertFalse(result['uploaded']);self.assertFalse(result['github_pushed'])

    def test_restart_marks_unfinished_job_interrupted_and_checks_owner(self):
        self.edit();_,job=self.start();result=self.wait(job["id"])
        path=self.workflow.directory()/"jobs"/(job["id"]+".json")
        data=json.loads(path.read_text());data["state"]="uploading";path.write_text(json.dumps(data))
        restarted=ReleaseWorkflow(self.root,self.env,protected,self.remote,self.publisher.verify_bundle)
        self.assertEqual(restarted.find_job(job["id"],7)["state"],"interrupted")
        with self.assertRaises(WorkflowError):restarted.find_job(job["id"],8)
