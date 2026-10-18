"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const terminal = new Set(["blocked", "cancelled", "failed", "github_failed", "completed", "interrupted", "cancelled_remote", "uploaded_cancelled"]);
  let state = null, review = null, job = null, busy = false, polling = false, historicalFailure = false;
  const errors = {
    publisher_connection_failed: "The publisher connection failed before upload. Refresh and try again after the station fix is installed.",
    server_build_access_denied: "The server refused the build/sign request. Sign in again or check this station’s publishing permissions.",
    server_build_unavailable: "The server build/sign service is busy or unavailable. No release was published.",
    invalid_source_station_id: "Station ID is missing or invalid. Check this station configuration before publishing.",
    source_station_id_missing: "Set the Station ID before uploading a release.",
    source_station_id_missing_review_again: "This older job has no source Station ID. Refresh the file list and approve a new release.",
    github_push_pending: "Server upload verified. Click Resume to finish the GitHub backup.",
    job_cannot_be_stopped: "This stage has already finished. Cancel update can stop future deployment.",
    server_signing_failed: "Server signing failed. No release was uploaded and GitHub was not updated.",
    server_source_policy_mismatch: "The server signing policy does not accept all required files. No upload was started.",
    server_signer_offline: "The server signing service is offline. No upload was started.",
    rollout_cancellation_not_confirmed: "Deployment cancellation is not confirmed yet. The server will be checked again.",
    target_agent_not_ready: "A selected station is offline, incompatible, or has not registered the required update-agent safety capabilities. No rollout was started.",
    signing_outcome_requires_reconciliation: "Waiting for the server to confirm signing. No release or GitHub push has started.",
    source_not_in_build_inventory: "Some reviewed files are missing from the configured release inventory. Ask Codex to update the build configuration before releasing.",
    release_builder_not_configured: "The release build/signing service is not configured yet. Your source has not been changed or uploaded.",
    source_changed_review_again: "Source files changed after the list loaded. Click Refresh before releasing.",
    staged_changes_need_review: "There are already staged Git changes. Review or commit those changes with Codex first.",
    no_source_changes: "There are no source changes to release.",
    review_expired: "This file list has expired. Click Refresh before releasing.",
    publisher_state_must_be_outside_source: "Publisher storage must be configured outside the source repository.",
    publication_already_running: "Another release is still running. Wait for it or cancel it first.",
    server_already_accepted_draft: "The server has already accepted this immutable draft. It has not been deployed unless you started rollout.",
    upload_outcome_unknown: "Upload was interrupted. Its server outcome must be reconciled; no rollout or GitHub push was started.",
    server_release_verification_failed: "The uploaded release could not be verified on the server. GitHub push was not started.",
    github_push_failed: "The server accepted the draft, but GitHub rejected the push. The draft is preserved; no force push was attempted.",
    release_build_failed: "The release builder failed. Your working files were preserved and no rollout was started.",
    release_not_ready_for_rollout: "The draft and GitHub backup must both succeed, and explicit target stations must be approved first.",
    updates_disabled: "Software updates are not enabled on the server.",
    update_storage_unavailable: "Server update storage is unavailable.",
    forbidden: "The server rejected this action. Check your administrator permissions.",
    conflict: "The server reported a conflict. Check the existing job before retrying.",
    server_unreachable_or_tls_failed: "A secure server connection could not be established.",
    server_auth_unavailable: "The server account service is unavailable. Please try again later.",
  };
  function notice(text, kind = "") { $("message").textContent = text; $("message").className = `notice ${kind}`; }
  function fail(error) { notice(errors[error.message] || `Operation stopped: ${error.message || "check connectivity and publisher settings"}`, "error"); }
  async function api(path, data) {
    const options = {credentials:"same-origin", cache:"no-store", headers:{Accept:"application/json"}};
    if (data !== undefined) Object.assign(options, {method:"POST", headers:{...options.headers,"Content-Type":"application/json","X-Update-Intent":"publisher"}, body:JSON.stringify(data)});
    const response = await fetch(`/api/software-updates/${path}`, options);
    let value; try { value = await response.json(); } catch { throw new Error("publisher_unavailable"); }
    if (!response.ok) {
      if (response.status === 401 && value.error === "login_required") window.location.replace("/software-updates/login");
      throw new Error(value.error || "server_rejected");
    }
    return value;
  }
  function active() { return Boolean(job && !terminal.has(job.state)); }
  function buttons() {
    $("refresh").disabled = busy;
    $("approvalFields").disabled = busy || active();
    $("approveRelease").disabled = busy || active() || !review?.count;
    $("rollout").disabled = busy || !job?.uploaded || !job?.github_pushed || !job?.stations?.length || Boolean(job?.rollout_id);
    $("rollout").hidden = !job?.uploaded || !job?.github_pushed || !job?.stations?.length || Boolean(job?.rollout_id);
    const resume = job?.paused || (job?.commit && ["interrupted", "github_failed"].includes(job.state));
    $("toggleJob").textContent = resume ? "Resume" : "Stop";
    $("toggleJob").disabled = busy || !job || (job.cancel_requested && active()) || (!resume && (!active() || job.uploaded));
    $("cancelUpdate").disabled = busy || !job || (job.cancel_requested && active()) || ["cancelled", "cancelled_remote", "uploaded_cancelled"].includes(job.state);
  }
  async function refresh(show = true) {
    state = await api("status");
    const source = state.source;
    $("signedInUser").textContent = `Signed in as ${state.user?.full_name || state.user?.username || "Administrator"}`;
    $("version").textContent = source.version;
    $("branch").textContent = source.branch || "Detached source";
    $("running").textContent = source.running_version || "Not recorded";
    $("runningNote").textContent = source.running_id || "Runtime ID unavailable";
    $("changes").textContent = source.changed_count === null ? "Unknown" : `${source.changed_count} files`;
    $("deviceId").textContent = state.device_id || "Not configured";
    $("commit").textContent = source.source_commit || "Git metadata unavailable";
    $("serverLink").href = `${state.server}/updates.html`; $("serverLink").hidden = false;
    if (!job) {
      $("approvalState").textContent = "Ready for review";
      $("approvalExpiry").textContent = "Authorized by your server sign-in";
    }
    await loadFiles(show);
    void readiness();
    buttons();
  }
  async function action(fn) { if (busy) return; busy = true; buttons(); try { await fn(); } catch (error) { fail(error); } finally { busy = false; buttons(); } }
  function renderJob() {
    if (!job) return;
    const previousFailure = historicalFailure && ["failed", "blocked"].includes(job.state) && !job.uploaded && !job.rollout_id;
    const ready = job.state === "completed" && job.uploaded && job.receipt_verified && job.github_pushed;
    const transfer = active() && !job.paused && (job.state === "uploading" || job.helper_phase === "signing_upload") && job.bytes_total > 0 && job.progress < 100;
    $("jobPhase").textContent = previousFailure ? "Previous attempt failed · Ready for a new attempt" : ready ? "Original ready to deploy" : job.paused ? "Stopped · Click Resume to continue" : job.phase === "Publication stopped" ? "Update failed" : job.phase;
    $("uploadPercent").hidden = !transfer;
    $("uploadPercent").textContent = transfer ? `${job.progress || 0}%` : "";
    $("uploadProgress").value = transfer || (job.paused && job.progress < 100) ? job.progress || 0 : 0;
    const mb = n => `${((n || 0) / 1048576).toFixed(1)} MB`;
    $("uploadBytes").textContent = ready ? "Server upload verified · GitHub updated" : transfer || job.paused ? `${mb(job.bytes_sent)} / ${mb(job.bytes_total)}` : job.uploaded ? "Server draft saved" : ["interrupted", "building", "uploading"].includes(job.state) ? "Waiting for confirmation" : "";
    $("approvalState").textContent = previousFailure ? "Ready for review" : ready ? "Ready to deploy" : job.paused ? "Stopped" : job.state === "failed" ? "Needs attention" : job.state.startsWith("cancelled") || job.state === "uploaded_cancelled" ? "Cancelled" : "Approved";
    $("approvalExpiry").textContent = `Release ${job.version}`;
    if (previousFailure) notice("The previous attempt failed before publication. Review the current checks before trying again.");
    else if (job.error) notice(errors[job.error] || `Update stopped: ${job.error}`, "warning");
    else if (ready) notice("Original ready to deploy · Server upload verified and GitHub updated.");
    else if (job.paused) notice("Update stopped. Click Resume to continue.");
    else if (["cancelled", "cancelled_remote", "uploaded_cancelled"].includes(job.state)) notice(job.phase);
    $("stationProgress").replaceChildren();
    for (const item of job.assignments || []) {
      const row = document.createElement("li"); row.textContent = `${item.station}: ${item.state}`; $("stationProgress").append(row);
    }
    buttons();
  }
  async function pollJob() {
    if (!job || polling) return;
    polling = true;
    try { job = await api(`job/${encodeURIComponent(job.id)}`); renderJob(); }
    catch (error) { fail(error); }
    finally { polling = false; }
  }
  async function readiness() {
    try {
      const result = await api("readiness");
      $("publisherReadiness").textContent = result.ready ? "Preflight checks passed · Server signer online" : `Server needs attention: ${result.blockers.some(text => text.includes("allowlist")) ? "Signing policy must be updated to accept all required files." : result.blockers[0] || "Check server configuration."}`;
      return result;
    } catch (error) {
      $("publisherReadiness").textContent = "Publisher readiness check failed. Refresh to retry."; fail(error);
    }
    buttons();
  }
  $("refresh").addEventListener("click", () => action(() => refresh()));
  async function loadFiles(show = true) {
    review = null;
    buttons();
    review = await api("prepare", {});
    $("fileList").replaceChildren();
    for (const file of review.files) {
      const row = document.createElement("li"), link = document.createElement("a"), badge = document.createElement("span");
      link.textContent = file.path;
      link.href = `/software-updates/file?review=${encodeURIComponent(review.id)}&path=${encodeURIComponent(file.path)}`;
      link.target = "_blank"; link.rel = "noopener noreferrer";
      badge.textContent = file.status; badge.className = `file-status ${file.status}`;
      row.append(link, badge); $("fileList").append(row);
    }
    $("plan").hidden = false; $("plan").open = true;
    $("planNote").textContent = `${review.count} changed files · Click a file to view changes.`;
    $("candidateVersion").textContent = `Version ${review.version}`;
    if (show) notice(review.count ? `${review.count} changed files ready for release.` : "No source changes were found.");
  }
  $("downloadPlan").addEventListener("click", () => {
    if (!review) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(review, null, 2)], {type:"application/json"}));
    const link = document.createElement("a"); link.href = url; link.download = "station-release-review.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("approvalForm").addEventListener("submit", event => {
    event.preventDefault(); if (!review?.count) return;
    const stations = [];
    action(async () => {
      const checks = await readiness();
      if (!checks?.ready) { notice(checks?.blockers?.[0] || "Preflight checks could not be completed. Try again.", "warning"); return; }
      historicalFailure = false;
      job = await api("release", {review_id:review.id, digest:review.digest, stations});
      sessionStorage.setItem("station-release-job", job.id); renderJob();
    });
  });
  $("toggleJob").addEventListener("click", () => action(async () => {
    const resume = job.paused || ["interrupted", "github_failed"].includes(job.state);
    job = await api(`job/${encodeURIComponent(job.id)}/${resume ? "resume" : "pause"}`, {}); renderJob();
  }));
  $("cancelUpdate").addEventListener("click", () => action(async () => {
    if (job.rollout_id && !window.confirm("Cancel deployment? Stations already installing may finish; rollback must be confirmed by each station.")) return;
    job = await api(`job/${encodeURIComponent(job.id)}/cancel-update`, {}); renderJob();
  }));
  $("rollout").addEventListener("click", () => action(async () => {
    if (!window.confirm(`Deploy ${job.version} to ${job.stations.join(", ")}?`)) return;
    job = await api(`job/${encodeURIComponent(job.id)}/rollout`, {}); renderJob();
  }));
  const signOut = () => action(async () => { await api("logout", {}); window.location.replace("/software-updates/login"); });
  $("sessionLogout").addEventListener("click", signOut);
  const timer = setInterval(() => { if (active() || job?.state === "interrupted" || (job?.rollout_id && job.state !== "cancelled_remote")) pollJob(); }, 2000);
  window.addEventListener("pagehide", () => clearInterval(timer));
  action(async () => {
    const id = sessionStorage.getItem("station-release-job");
    if (id) { try { job = await api(`job/${encodeURIComponent(id)}`); historicalFailure = true; renderJob(); } catch { sessionStorage.removeItem("station-release-job"); } }
    await refresh();
    if (job) renderJob();
  });
})();
