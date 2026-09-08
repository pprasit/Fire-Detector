"use strict";

const fields = {
  cameraPoolStatus: document.getElementById("cameraPoolStatus"),
  mountStatus: document.getElementById("mountStatus"),
  mountAzimuth: document.getElementById("mountAzimuth"),
  mountAltitude: document.getElementById("mountAltitude"),
  armedStatus: document.getElementById("armedStatus"),
  thermalImage: document.getElementById("thermalImage"),
  visibleImage: document.getElementById("visibleImage"),
  thermalState: document.getElementById("thermalState"),
  visibleState: document.getElementById("visibleState"),
  thermalZoom: document.getElementById("thermalZoom"),
  visibleZoom: document.getElementById("visibleZoom"),
  thermalResolution: document.getElementById("thermalResolution"),
  visibleResolution: document.getElementById("visibleResolution"),
  directionMode: document.getElementById("directionMode"),
  directionValue: document.getElementById("directionValue"),
  directionValueLabel: document.getElementById("directionValueLabel"),
  directionUnit: document.getElementById("directionUnit"),
  directionPad: document.getElementById("directionPad"),
  directionStop: document.getElementById("directionStop"),
  directionMessage: document.getElementById("directionMessage"),
};

const frameTimers = new Map();
const frameObjectUrls = new Map();
const readyCameras = new Set();
const modeValues = { jog: "5.0", offset: "0.100" };
const motionClientId = `camera-monitor-${crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`}`;
let frameSession = 0;
let motionSequence = 0;
let latestStatus = null;
let activeJog = null;
let activeMode = "jog";
let statusTimer = null;
let frameController = null;

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function axesByLabel() {
  const result = {};
  (latestStatus?.axes || []).forEach((axis) => { result[axis.label] = axis; });
  return result;
}

function formatAngle(value) {
  const number = numberOrNull(value);
  return number === null ? "--" : `${number >= 0 ? "+" : "−"}${Math.abs(number).toFixed(3)}°`;
}

function setDirectionMessage(message, state = "") {
  fields.directionMessage.textContent = message;
  fields.directionMessage.classList.remove("is-ok", "is-warning", "is-error");
  if (state) fields.directionMessage.classList.add(state);
}

function cameraElements(camera) {
  return camera === "thermal"
    ? { image: fields.thermalImage, state: fields.thermalState, zoom: fields.thermalZoom, resolution: fields.thermalResolution }
    : { image: fields.visibleImage, state: fields.visibleState, zoom: fields.visibleZoom, resolution: fields.visibleResolution };
}

function renderPoolStatus() {
  const status = fields.cameraPoolStatus;
  status.classList.remove("is-ok", "is-error");
  if (readyCameras.size === 2) {
    status.innerHTML = "<i></i>LIVE · CENTRAL POOL";
    status.classList.add("is-ok");
  } else if (readyCameras.size === 1) {
    status.innerHTML = "<i></i>ONE FEED LIVE";
  } else {
    status.innerHTML = "<i></i>CONNECTING";
  }
}

function releaseFrameStreams() {
  frameSession += 1;
  frameTimers.forEach((timer) => clearTimeout(timer));
  frameTimers.clear();
  frameController?.abort();
  frameController = null;
  frameObjectUrls.forEach((url) => URL.revokeObjectURL(url));
  frameObjectUrls.clear();
  readyCameras.clear();
  [fields.thermalImage, fields.visibleImage].forEach((image) => {
    image.onload = null;
    image.onerror = null;
    image.removeAttribute("src");
    image.classList.remove("is-ready", "is-error");
  });
  renderPoolStatus();
}

async function displayCameraBlob(camera, blob, session) {
  if (session !== frameSession || document.hidden) return false;
  const { image, state } = cameraElements(camera);
  const objectUrl = URL.createObjectURL(blob);
  const previousUrl = frameObjectUrls.get(camera);
  try {
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error("Camera frame could not be decoded."));
      image.src = objectUrl;
    });
    if (session !== frameSession) {
      URL.revokeObjectURL(objectUrl);
      return false;
    }
    frameObjectUrls.set(camera, objectUrl);
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    readyCameras.add(camera);
    image.classList.add("is-ready");
    image.classList.remove("is-error");
    state.hidden = true;
    renderPoolStatus();
    return true;
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    if (session !== frameSession || document.hidden) return false;
    readyCameras.delete(camera);
    image.classList.remove("is-ready");
    image.classList.add("is-error");
    state.hidden = false;
    state.textContent = "Camera frame could not be decoded. Retrying…";
    renderPoolStatus();
    return false;
  }
}

function markCameraPairUnavailable(message) {
  ["thermal", "visible"].forEach((camera) => {
    const { image, state } = cameraElements(camera);
    readyCameras.delete(camera);
    image.classList.remove("is-ready");
    image.classList.add("is-error");
    state.hidden = false;
    state.textContent = message;
  });
  renderPoolStatus();
}

async function loadLatestPair(session) {
  if (session !== frameSession || document.hidden) return false;
  const controller = new AbortController();
  frameController?.abort();
  frameController = controller;
  const timeout = setTimeout(() => controller.abort(), 3000);
  try {
    const response = await fetch(
      `/api/camera-frame/latest-pair/live?_=${Date.now()}`,
      { cache: "no-store", signal: controller.signal },
    );
    if (!response.ok) throw new Error(`Camera pair unavailable (${response.status})`);
    const metadataHeader = response.headers.get("X-Camera-Pair-Metadata");
    if (metadataHeader) {
      try {
        const metadata = JSON.parse(metadataHeader);
        updateMetadata("thermal", metadata.thermal || {});
        updateMetadata("visible", metadata.visible || {});
      } catch (_error) {
        // A malformed metadata header must not interrupt either image.
      }
    }
    const buffer = await response.arrayBuffer();
    const view = new DataView(buffer);
    if (
      buffer.byteLength < 12
      || view.getUint8(0) !== 78
      || view.getUint8(1) !== 67
      || view.getUint8(2) !== 80
      || view.getUint8(3) !== 49
    ) throw new Error("Camera pair response has an invalid format.");
    const thermalLength = view.getUint32(4, false);
    const visibleLength = view.getUint32(8, false);
    if (12 + thermalLength + visibleLength !== buffer.byteLength) {
      throw new Error("Camera pair response is incomplete.");
    }
    const thermalType = response.headers.get("X-Camera-Thermal-Type") || "image/jpeg";
    const visibleType = response.headers.get("X-Camera-Visible-Type") || "image/jpeg";
    const thermalBlob = new Blob([buffer.slice(12, 12 + thermalLength)], { type: thermalType });
    const visibleBlob = new Blob([buffer.slice(12 + thermalLength)], { type: visibleType });
    const results = await Promise.allSettled([
      displayCameraBlob("thermal", thermalBlob, session),
      displayCameraBlob("visible", visibleBlob, session),
    ]);
    return results.some((result) => result.status === "fulfilled" && result.value === true);
  } catch (error) {
    if (session !== frameSession || document.hidden) return false;
    markCameraPairUnavailable(error.name === "AbortError"
      ? "Camera pair request timed out. Retrying…"
      : "Waiting for latest camera pair from central pool…");
    return false;
  } finally {
    clearTimeout(timeout);
    if (frameController === controller) frameController = null;
  }
}

async function runFrameCycle(session) {
  if (session !== frameSession || document.hidden) return;
  const startedAt = performance.now();
  await loadLatestPair(session);
  if (session !== frameSession || document.hidden) return;
  const delay = Math.max(0, 100 - (performance.now() - startedAt));
  frameTimers.set("cycle", setTimeout(() => runFrameCycle(session), delay));
}

function startFrameStreams() {
  releaseFrameStreams();
  const session = frameSession;
  runFrameCycle(session);
}

function zoomPercentage(metadata) {
  const direct = numberOrNull(metadata?.zoom_pct);
  if (direct !== null) return direct;
  const ratio = numberOrNull(metadata?.zoom_ratio);
  return ratio === null ? null : ratio * 100;
}

function updateMetadata(camera, metadata) {
  const { zoom, resolution } = cameraElements(camera);
  const percentage = zoomPercentage(metadata);
  zoom.textContent = percentage === null ? "ZOOM --.-%" : `ZOOM ${percentage.toFixed(1)}%`;
  const width = numberOrNull(metadata?.width);
  const height = numberOrNull(metadata?.height);
  if (width !== null && height !== null) resolution.textContent = `${Math.round(width)} × ${Math.round(height)}`;
}

function renderStatus() {
  const axes = axesByLabel();
  const azimuth = axes.Azimuth;
  const altitude = axes.Altitude;
  const connected = Boolean(latestStatus?.connected);
  const armed = connected
    && azimuth?.available && altitude?.available
    && azimuth?.is_armed && altitude?.is_armed;
  fields.mountStatus.textContent = connected ? "CONNECTED" : "OFFLINE";
  fields.mountStatus.className = connected ? "is-ok" : "is-error";
  fields.mountAzimuth.textContent = formatAngle(azimuth?.position_deg);
  fields.mountAltitude.textContent = formatAngle(altitude?.position_deg);
  fields.armedStatus.textContent = armed ? "ARMED" : "DISARMED";
  fields.armedStatus.classList.toggle("is-armed", armed);
  fields.directionPad.querySelectorAll("[data-az]").forEach((button) => { button.disabled = !armed; });
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Status unavailable");
    latestStatus = result;
    renderStatus();
  } catch (_error) {
    latestStatus = null;
    renderStatus();
    if (activeJog) stopActiveJog(false);
  } finally {
    clearTimeout(statusTimer);
    statusTimer = setTimeout(refreshStatus, document.hidden ? 2500 : 650);
  }
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.ok !== true) throw new Error(result.error || `Command failed (${response.status})`);
  if (result.status) {
    latestStatus = result.status;
    renderStatus();
  }
  return result;
}

async function sendJog(azimuth, altitude, showMessage = true) {
  motionSequence += 1;
  try {
    await requestJson("/api/motors/velocity-command", {
      method: "POST",
      keepalive: azimuth === 0 && altitude === 0,
      headers: {
        "Content-Type": "application/json",
        "X-Motion-Client-ID": motionClientId,
        "X-Motion-Command-Sequence": String(motionSequence),
      },
      body: JSON.stringify({ Azimuth: String(azimuth), Altitude: String(altitude) }),
    });
    if (showMessage) setDirectionMessage(
      azimuth === 0 && altitude === 0 ? "Direction jog stopped" : "Mount moving while button is held",
      azimuth === 0 && altitude === 0 ? "is-ok" : "",
    );
    return true;
  } catch (error) {
    setDirectionMessage(error.message, "is-error");
    return false;
  }
}

function stopActiveJog(sendStop = true) {
  const state = activeJog;
  if (!state) {
    if (sendStop) sendJog(0, 0);
    return;
  }
  activeJog = null;
  clearInterval(state.heartbeat);
  state.cleanup?.();
  state.button.classList.remove("is-pressed");
  if (sendStop) sendJog(0, 0);
}

function startJog(button, event) {
  const speed = numberOrNull(fields.directionValue.value);
  if (speed === null || speed <= 0) {
    setDirectionMessage("Movement speed must be greater than 0.", "is-error");
    return;
  }
  const azimuthSign = Number(button.dataset.az);
  const altitudeSign = Number(button.dataset.alt);
  const divisor = Math.hypot(azimuthSign, altitudeSign) || 1;
  const azimuth = speed * azimuthSign / divisor;
  const altitude = speed * altitudeSign / divisor;
  stopActiveJog(false);
  const state = { button, heartbeat: null, cleanup: null };
  activeJog = state;
  button.classList.add("is-pressed");
  button.setPointerCapture?.(event.pointerId);
  sendJog(azimuth, altitude);
  const stop = () => { if (activeJog === state) stopActiveJog(); };
  state.cleanup = () => {
    window.removeEventListener("pointerup", stop, true);
    window.removeEventListener("pointercancel", stop, true);
    window.removeEventListener("blur", stop);
    button.removeEventListener("lostpointercapture", stop);
  };
  window.addEventListener("pointerup", stop, { capture: true });
  window.addEventListener("pointercancel", stop, { capture: true });
  window.addEventListener("blur", stop);
  button.addEventListener("lostpointercapture", stop);
  state.heartbeat = setInterval(() => {
    if (activeJog === state) sendJog(azimuth, altitude, false);
  }, 250);
}

async function sendOffset(button) {
  const amount = numberOrNull(fields.directionValue.value);
  if (amount === null || amount <= 0) {
    setDirectionMessage("Movement offset must be greater than 0.", "is-error");
    return;
  }
  const axes = axesByLabel();
  const currentAzimuth = numberOrNull(axes.Azimuth?.position_deg);
  const currentAltitude = numberOrNull(axes.Altitude?.position_deg);
  if (currentAzimuth === null || currentAltitude === null) {
    setDirectionMessage("Current mount position is unavailable.", "is-warning");
    return;
  }
  const azimuthSign = Number(button.dataset.az);
  const altitudeSign = Number(button.dataset.alt);
  const divisor = Math.hypot(azimuthSign, altitudeSign) || 1;
  const round = (value) => Math.round(value * 1000) / 1000;
  const payload = {
    Azimuth: String(round(currentAzimuth + amount * azimuthSign / divisor)),
    Altitude: String(round(currentAltitude + amount * altitudeSign / divisor)),
    position_tolerance_deg: String(Math.max(0.0005, Math.min(0.08, amount / 4))),
  };
  button.classList.add("is-pressed");
  setDirectionMessage(`Applying ${amount.toFixed(3)}° offset…`);
  try {
    await requestJson("/api/motors/goto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setDirectionMessage(`${button.getAttribute("aria-label")} by ${amount.toFixed(3)}°`, "is-ok");
  } catch (error) {
    setDirectionMessage(error.message, "is-error");
  } finally {
    button.classList.remove("is-pressed");
  }
}

function updateDirectionMode() {
  modeValues[activeMode] = fields.directionValue.value;
  stopActiveJog();
  activeMode = fields.directionMode.value === "offset" ? "offset" : "jog";
  const offset = activeMode === "offset";
  fields.directionValue.value = modeValues[activeMode];
  fields.directionValue.step = offset ? "0.001" : "0.1";
  fields.directionValueLabel.textContent = offset ? "Movement Offset" : "Movement Speed";
  fields.directionUnit.textContent = offset ? "Deg" : "Deg/Sec";
  fields.directionPad.setAttribute("aria-label", offset
    ? "Click a direction to move by the configured offset"
    : "Press and hold a direction to move");
  setDirectionMessage(offset
    ? "Click a direction to move by the configured offset"
    : "Press and hold to move • Release to stop");
}

fields.directionMode.addEventListener("change", updateDirectionMode);
fields.directionValue.addEventListener("input", () => { modeValues[activeMode] = fields.directionValue.value; });
fields.directionPad.querySelectorAll("[data-az]").forEach((button) => {
  button.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || button.disabled) return;
    event.preventDefault();
    if (activeMode === "offset") sendOffset(button);
    else startJog(button, event);
  });
  button.addEventListener("click", (event) => event.preventDefault());
});
fields.directionStop.addEventListener("click", () => stopActiveJog(true));

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopActiveJog(true);
    releaseFrameStreams();
  } else {
    startFrameStreams();
    refreshStatus();
  }
});
window.addEventListener("pagehide", () => {
  stopActiveJog(true);
  releaseFrameStreams();
  clearTimeout(statusTimer);
});
window.addEventListener("offline", () => {
  stopActiveJog(true);
  releaseFrameStreams();
});
window.addEventListener("online", startFrameStreams);

startFrameStreams();
refreshStatus();
renderStatus();
