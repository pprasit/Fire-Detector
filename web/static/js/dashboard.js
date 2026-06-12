const fields = {
  navDot: document.getElementById("navDot"),
  navStatus: document.getElementById("navStatus"),
  lastUpdated: document.getElementById("lastUpdated"),
  refreshBtn: document.getElementById("refreshBtn"),
  tuningStepPanel: document.getElementById("tuningStepPanel"),
  tuningStepTitle: document.getElementById("tuningStepTitle"),
  tuningStepInput: document.getElementById("tuningStepInput"),
  tuningStepClose: document.getElementById("tuningStepClose"),
  azimuthCcwSensor: document.getElementById("azimuthCcwSensor"),
  azimuthCwSensor: document.getElementById("azimuthCwSensor"),
};

const axisFields = {
  Azimuth: {
    status: document.getElementById("azimuthStatus"),
    position: document.getElementById("azimuthPosition"),
    velocity: document.getElementById("azimuthVelocity"),
    current: document.getElementById("azimuthCurrent"),
    state: document.getElementById("azimuthState"),
    errors: document.getElementById("azimuthErrors"),
    armed: document.getElementById("azimuthArmed"),
    driveSerial: document.getElementById("azimuthDriveSerial"),
    driveFirmware: document.getElementById("azimuthDriveFirmware"),
    driveHardware: document.getElementById("azimuthDriveHardware"),
    driveBus: document.getElementById("azimuthDriveBus"),
    driveCurrent: document.getElementById("azimuthDriveCurrent"),
    driveFaults: document.getElementById("azimuthDriveFaults"),
    positionGain: document.getElementById("azimuthPositionGain"),
    velocityGain: document.getElementById("azimuthVelocityGain"),
    velocityIntegratorGain: document.getElementById("azimuthVelocityIntegratorGain"),
    velocityIntegratorLimit: document.getElementById("azimuthVelocityIntegratorLimit"),
    velocityIntegratorDecayGain: document.getElementById("azimuthVelocityIntegratorDecayGain"),
    velocityLimit: document.getElementById("azimuthVelocityLimit"),
    velocityLimitTolerance: document.getElementById("azimuthVelocityLimitTolerance"),
    velocityRampRate: document.getElementById("azimuthVelocityRampRate"),
    torqueRampRate: document.getElementById("azimuthTorqueRampRate"),
    inputFilterBandwidth: document.getElementById("azimuthInputFilterBandwidth"),
    inertia: document.getElementById("azimuthInertia"),
    trapVelocityLimit: document.getElementById("azimuthTrapVelocityLimit"),
    trapAccelLimit: document.getElementById("azimuthTrapAccelLimit"),
    trapDecelLimit: document.getElementById("azimuthTrapDecelLimit"),
    tuningMessage: document.getElementById("azimuthTuningMessage"),
    chartValue: document.getElementById("azimuthChartValue"),
    plotSelect: document.getElementById("azimuthPlotSelect"),
    canvas: document.getElementById("azimuthChart"),
    card: document.querySelector('[data-axis-card="Azimuth"]'),
  },
  Altitude: {
    status: document.getElementById("altitudeStatus"),
    position: document.getElementById("altitudePosition"),
    velocity: document.getElementById("altitudeVelocity"),
    current: document.getElementById("altitudeCurrent"),
    state: document.getElementById("altitudeState"),
    errors: document.getElementById("altitudeErrors"),
    armed: document.getElementById("altitudeArmed"),
    driveSerial: document.getElementById("altitudeDriveSerial"),
    driveFirmware: document.getElementById("altitudeDriveFirmware"),
    driveHardware: document.getElementById("altitudeDriveHardware"),
    driveBus: document.getElementById("altitudeDriveBus"),
    driveCurrent: document.getElementById("altitudeDriveCurrent"),
    driveFaults: document.getElementById("altitudeDriveFaults"),
    positionGain: document.getElementById("altitudePositionGain"),
    velocityGain: document.getElementById("altitudeVelocityGain"),
    velocityIntegratorGain: document.getElementById("altitudeVelocityIntegratorGain"),
    velocityIntegratorLimit: document.getElementById("altitudeVelocityIntegratorLimit"),
    velocityIntegratorDecayGain: document.getElementById("altitudeVelocityIntegratorDecayGain"),
    velocityLimit: document.getElementById("altitudeVelocityLimit"),
    velocityLimitTolerance: document.getElementById("altitudeVelocityLimitTolerance"),
    velocityRampRate: document.getElementById("altitudeVelocityRampRate"),
    torqueRampRate: document.getElementById("altitudeTorqueRampRate"),
    inputFilterBandwidth: document.getElementById("altitudeInputFilterBandwidth"),
    inertia: document.getElementById("altitudeInertia"),
    trapVelocityLimit: document.getElementById("altitudeTrapVelocityLimit"),
    trapAccelLimit: document.getElementById("altitudeTrapAccelLimit"),
    trapDecelLimit: document.getElementById("altitudeTrapDecelLimit"),
    tuningMessage: document.getElementById("altitudeTuningMessage"),
    chartValue: document.getElementById("altitudeChartValue"),
    plotSelect: document.getElementById("altitudePlotSelect"),
    canvas: document.getElementById("altitudeChart"),
    card: document.querySelector('[data-axis-card="Altitude"]'),
  },
};

const history = {
  Azimuth: [],
  Altitude: [],
};

const historyWindowMs = 60000;
let refreshInFlight = false;

const seriesConfig = {
  position: { key: "position", color: "#8e45e6", unit: "Deg" },
  velocity: { key: "velocity", color: "#ff8a2a", unit: "Deg/Sec" },
  current: { key: "current", color: "#49c7d9", unit: "Amp" },
};

const tuningBindings = [
  ["positionGain", "position_gain"],
  ["velocityGain", "velocity_gain"],
  ["velocityIntegratorGain", "velocity_integrator_gain"],
  ["velocityIntegratorLimit", "velocity_integrator_limit"],
  ["velocityIntegratorDecayGain", "velocity_integrator_decay_gain"],
  ["velocityLimit", "velocity_limit"],
  ["velocityLimitTolerance", "velocity_limit_tolerance"],
  ["velocityRampRate", "velocity_ramp_rate"],
  ["torqueRampRate", "torque_ramp_rate"],
  ["inputFilterBandwidth", "input_filter_bandwidth"],
  ["inertia", "inertia"],
  ["trapVelocityLimit", "trap_velocity_limit"],
  ["trapAccelLimit", "trap_accel_limit"],
  ["trapDecelLimit", "trap_decel_limit"],
];

let appSettings = { tuning_steps: { Azimuth: {}, Altitude: {} } };
let activeStepTarget = null;
const autoApplyTimers = new WeakMap();
let settingsSaveTimer = null;

async function refreshStatus() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    const data = await response.json();
    renderStatus(data);
  } catch (error) {
    renderStatus({
      connected: false,
      error: `Monitor API unavailable: ${error.message}`,
      timestamp: new Date().toISOString(),
    });
  } finally {
    refreshInFlight = false;
  }
}

function renderStatus(data) {
  const timestamp = data.timestamp ? new Date(data.timestamp) : new Date();
  if (fields.lastUpdated) {
    fields.lastUpdated.textContent = `Updated ${timestamp.toLocaleTimeString()}`;
  }
  if (fields.navDot) {
    setLight(fields.navDot, data.connected, data.has_bus_power);
  }
  renderAzimuthSensors(data.azimuth_sensors);

  if (!data.connected) {
    if (fields.navStatus) {
      fields.navStatus.textContent = "Offline";
    }
    renderAxis("Azimuth", null, timestamp);
    renderAxis("Altitude", null, timestamp);
    return;
  }

  if (fields.navStatus) {
    fields.navStatus.textContent = data.has_bus_power ? "Ready" : "USB only";
  }

  const axes = Array.isArray(data.axes) ? data.axes : [];
  renderAxis("Azimuth", axes.find((axis) => axis.label === "Azimuth"), timestamp);
  renderAxis("Altitude", axes.find((axis) => axis.label === "Altitude"), timestamp);
}

function renderAzimuthSensors(sensors) {
  setSensorPill(fields.azimuthCcwSensor, Boolean(sensors?.ccw_sensor));
  setSensorPill(fields.azimuthCwSensor, Boolean(sensors?.cw_sensor));
}

function setSensorPill(element, active) {
  if (!element) return;
  element.classList.toggle("is-active", active);
  const value = element.querySelector("strong");
  if (value) value.textContent = active ? "True" : "False";
}

function renderAxis(label, axis, timestamp) {
  const ui = axisFields[label];
  if (!ui) return;

  ui.card.classList.remove("axis-ready", "axis-warning", "axis-missing");

  if (!axis || !axis.available) {
    ui.status.textContent = "Disconnected";
    ui.position.textContent = "--";
    ui.velocity.textContent = "--";
    ui.current.textContent = "--";
    ui.state.textContent = "--";
    ui.errors.textContent = "--";
    ui.armed.textContent = "--";
    ui.driveSerial.textContent = "--";
    ui.driveFirmware.textContent = "--";
    ui.driveHardware.textContent = "--";
    ui.driveBus.textContent = "--";
    ui.driveCurrent.textContent = "--";
    ui.driveFaults.textContent = "--";
    setTuningInputs(ui, null);
    ui.chartValue.textContent = selectedChartValue(label, null);
    ui.card.classList.add("axis-missing");
    pruneHistory(label, timestamp);
    drawChart(label, timestamp);
    return;
  }

  const sample = {
    timeMs: timestamp.getTime(),
    position: toNumber(axis.position_deg),
    velocity: toNumber(axis.velocity_deg_per_sec),
    current: toNumber(axis.current),
  };
  history[label].push(sample);
  pruneHistory(label, timestamp);

  ui.status.textContent = "Connected";
  ui.position.textContent = `${formatNumber(axis.position_deg)} Deg`;
  ui.velocity.textContent = `${formatNumber(axis.velocity_deg_per_sec)} Deg/Sec`;
  ui.current.textContent = `${formatNumber(axis.current)} Amp`;
  ui.state.textContent = valueOrDash(axis.current_state);
  ui.errors.textContent = valueOrDash(axis.active_errors);
  ui.armed.textContent = axis.is_armed ? "Yes" : "No";
  ui.driveSerial.textContent = valueOrDash(axis.drive_serial);
  ui.driveFirmware.textContent = valueOrDash(axis.drive_firmware);
  ui.driveHardware.textContent = valueOrDash(axis.drive_hardware);
  ui.driveBus.textContent = `${formatNumber(axis.drive_vbus_voltage)} V`;
  ui.driveCurrent.textContent = `${formatNumber(axis.drive_ibus)} Amp`;
  ui.driveFaults.textContent = valueOrDash(axis.active_errors);
  setTuningInputs(ui, axis);
  ui.chartValue.textContent = selectedChartValue(label, axis);
  ui.card.classList.add("axis-ready");
  drawChart(label, timestamp);
}

function pruneHistory(label, now) {
  const cutoff = now.getTime() - historyWindowMs;
  history[label] = history[label].filter((sample) => sample.timeMs >= cutoff);
}

function drawChart(label, now = new Date()) {
  const ui = axisFields[label];
  const canvas = ui.canvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const padLeft = 58;
  const padRight = 42;
  const padTop = 28;
  const padBottom = 42;
  const samples = history[label];
  const nowMs = now.getTime();

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(17, 21, 37, 0.12)";
  ctx.fillRect(0, 0, width, height);
  drawGrid(ctx, width, height, padLeft, padRight, padTop, padBottom);
  drawTimeLabels(ctx, width, height, padLeft, padRight, padBottom);

  if (samples.length < 2) {
    ctx.fillStyle = "rgba(244, 246, 255, 0.55)";
    ctx.font = "24px Segoe UI";
    ctx.fillText("Waiting for telemetry samples", padLeft, height / 2);
    return;
  }

  const selected = selectedSeries(label);
  const values = samples.map((sample) => sample[selected.key]).filter((value) => value !== null);
  if (values.length < 2) return;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (Math.abs(max - min) < 0.001) {
    const padding = Math.max(Math.abs(max) * 0.05, 1);
    min -= padding;
    max += padding;
  }
  const range = max - min;
  drawValueLabels(ctx, min, max, width, height, padLeft, padTop, padBottom);

  ctx.beginPath();
  let lineStarted = false;
  samples.forEach((sample) => {
    const value = sample[selected.key];
    if (value === null) return;
    const ageMs = Math.max(0, nowMs - sample.timeMs);
    if (ageMs > historyWindowMs) return;
    const x = width - padRight - (ageMs / historyWindowMs) * (width - padLeft - padRight);
    const y = height - padBottom - ((value - min) / range) * (height - padTop - padBottom);
    if (!lineStarted) {
      ctx.moveTo(x, y);
      lineStarted = true;
    }
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = selected.color;
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.stroke();
}

function drawGrid(ctx, width, height, padLeft, padRight, padTop, padBottom) {
  ctx.strokeStyle = "rgba(255, 255, 255, 0.075)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i += 1) {
    const y = padTop + i * ((height - padTop - padBottom) / 5);
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(width - padRight, y);
    ctx.stroke();
  }
  for (let i = 0; i <= 6; i += 1) {
    const x = padLeft + i * ((width - padLeft - padRight) / 6);
    ctx.beginPath();
    ctx.moveTo(x, padTop);
    ctx.lineTo(x, height - padBottom);
    ctx.stroke();
  }
}

function drawTimeLabels(ctx, width, height, padLeft, padRight, padBottom) {
  ctx.fillStyle = "rgba(244, 246, 255, 0.48)";
  ctx.font = "9px Segoe UI";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  for (let i = 0; i <= 6; i += 1) {
    const secondsAgo = 60 - i * 10;
    const x = padLeft + i * ((width - padLeft - padRight) / 6);
    const label = secondsAgo === 0 ? "0s" : `-${secondsAgo}s`;
    ctx.fillText(label, x, height - padBottom + 12);
  }
}

function drawValueLabels(ctx, min, max, width, height, padLeft, padTop, padBottom) {
  ctx.fillStyle = "rgba(244, 246, 255, 0.50)";
  ctx.font = "10px Segoe UI";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 4; i += 1) {
    const ratio = i / 4;
    const value = max - (max - min) * ratio;
    const y = padTop + ratio * (height - padTop - padBottom);
    ctx.fillText(formatAxisLabel(value), padLeft - 10, y);
  }
}

function formatAxisLabel(value) {
  const absValue = Math.abs(value);
  if (absValue >= 100) return value.toFixed(0);
  if (absValue >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function selectedSeries(label) {
  const value = axisFields[label]?.plotSelect?.value || "position";
  return seriesConfig[value] || seriesConfig.position;
}

function selectedChartValue(label, axis) {
  const selected = selectedSeries(label);
  if (!axis) return `-- ${selected.unit}`;
  const valueMap = {
    position: axis.position_deg,
    velocity: axis.velocity_deg_per_sec,
    current: axis.current,
  };
  return `${formatNumber(valueMap[selected.key])} ${selected.unit}`;
}

function selectedChartValueFromHistory(label) {
  const selected = selectedSeries(label);
  const samples = history[label] || [];
  const latest = samples[samples.length - 1];
  if (!latest) return `-- ${selected.unit}`;
  return `${formatNumber(latest[selected.key])} ${selected.unit}`;
}

function setLight(element, connected, hasBusPower) {
  element.classList.remove("is-online", "is-warning", "is-offline");
  if (!connected) element.classList.add("is-offline");
  else if (!hasBusPower) element.classList.add("is-warning");
  else element.classList.add("is-online");
}

function labelForHealth(health) {
  if (health === "ready") return "Ready";
  if (health === "usb-only") return "USB only";
  if (health === "attention") return "Needs attention";
  return "Starting";
}

function valueOrDash(value) {
  return value === null || value === undefined || value === "" ? "--" : String(value);
}

function toNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Number(value);
}

function formatNumber(value) {
  const number = toNumber(value);
  if (number === null) return "--";
  return number.toFixed(3);
}

function setTuningInputs(ui, axis) {
  tuningBindings.forEach(([uiKey, axisKey]) => {
    setInputValueIfIdle(ui[uiKey], axis?.[axisKey]);
  });
}

function setInputValueIfIdle(input, value) {
  if (!input || document.activeElement === input) return;
  const number = toNumber(value);
  input.value = number === null ? "" : formatGain(number);
}

function formatGain(value) {
  if (Math.abs(value) >= 100) return value.toFixed(2);
  if (Math.abs(value) >= 10) return value.toFixed(3);
  return value.toFixed(4);
}

async function applyTuning(label, form) {
  const ui = axisFields[label];
  const button = form.querySelector("button[type='submit']");
  const payload = tuningPayloadFromForm(form);

  return applyTuningPayload(label, payload, {
    button,
    pendingMessage: "Applying tuning...",
    successMessage: "Tuning applied",
  });
}

async function applyTuningPayload(label, payload, options = {}) {
  const ui = axisFields[label];
  const button = options.button;

  setTuningMessage(ui, "Applying tuning...", "");
  if (options.pendingMessage) {
    setTuningMessage(ui, options.pendingMessage, "");
  }
  if (button) button.disabled = true;
  try {
    const response = await fetch(`/api/tuning/${encodeURIComponent(label)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Tuning update failed.");
    }
    renderStatus(data.status);
    setTuningMessage(ui, options.successMessage || "Tuning applied", "is-ok");
  } catch (error) {
    setTuningMessage(ui, error.message, "is-error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveTuning(label, button) {
  const ui = axisFields[label];
  setTuningMessage(ui, "Saving configuration to drive...", "");
  button.disabled = true;
  try {
    const response = await fetch(`/api/tuning/${encodeURIComponent(label)}/save`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Save failed.");
    }
    setTuningMessage(ui, data.message || "Configuration saved", "is-ok");
  } catch (error) {
    setTuningMessage(ui, error.message, "is-error");
  } finally {
    button.disabled = false;
  }
}

function tuningPayloadFromForm(form) {
  const payload = {};
  tuningBindings.forEach(([, fieldName]) => {
    payload[fieldName] = form.elements[fieldName].value;
  });
  return payload;
}

function setTuningMessage(ui, message, className) {
  if (!ui?.tuningMessage) return;
  ui.tuningMessage.classList.remove("is-ok", "is-error");
  if (className) ui.tuningMessage.classList.add(className);
  ui.tuningMessage.textContent = message;
}

async function loadAppSettings() {
  try {
    const response = await fetch("/api/settings", { cache: "no-store" });
    appSettings = await response.json();
    applyTuningSteps();
  } catch (error) {
    appSettings = { tuning_steps: { Azimuth: {}, Altitude: {} } };
  }
}

function applyTuningSteps() {
  document.querySelectorAll("[data-tuning-form] input[type='number']").forEach((input) => {
    const axis = input.closest("[data-tuning-form]")?.dataset.tuningForm;
    const step = getStoredStep(axis, input.name);
    input.step = String(step);
  });
}

function getStoredStep(axis, fieldName) {
  const value = appSettings?.tuning_steps?.[axis]?.[fieldName];
  const number = toNumber(value);
  return number !== null && number > 0 ? number : 0.001;
}

function setStoredStep(axis, fieldName, step) {
  if (!appSettings.tuning_steps) appSettings.tuning_steps = {};
  if (!appSettings.tuning_steps[axis]) appSettings.tuning_steps[axis] = {};
  appSettings.tuning_steps[axis][fieldName] = step;
}

function scheduleSettingsSave() {
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(saveAppSettings, 250);
}

async function saveAppSettings() {
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tuning_steps: appSettings.tuning_steps || {} }),
    });
  } catch (error) {
    // Step settings are convenience UI state; tuning control still works if saving fails.
  }
}

function openStepPanel(input, event) {
  const panel = fields.tuningStepPanel;
  if (!panel || !fields.tuningStepInput) return;

  const form = input.closest("[data-tuning-form]");
  const axis = form?.dataset.tuningForm;
  if (!axis) return;

  activeStepTarget = { axis, fieldName: input.name, input };
  fields.tuningStepTitle.textContent = `${axis} ${labelForField(input.name)}`;
  fields.tuningStepInput.value = String(getStoredStep(axis, input.name));

  panel.hidden = false;
  const left = Math.min(event.clientX, window.innerWidth - panel.offsetWidth - 12);
  const top = Math.min(event.clientY, window.innerHeight - panel.offsetHeight - 12);
  panel.style.left = `${Math.max(12, left)}px`;
  panel.style.top = `${Math.max(12, top)}px`;
  fields.tuningStepInput.focus();
  fields.tuningStepInput.select();
}

function closeStepPanel() {
  if (fields.tuningStepPanel) fields.tuningStepPanel.hidden = true;
  activeStepTarget = null;
}

function updateActiveStep() {
  if (!activeStepTarget) return;
  const step = toNumber(fields.tuningStepInput.value);
  if (step === null || step <= 0) return;
  activeStepTarget.input.step = String(step);
  setStoredStep(activeStepTarget.axis, activeStepTarget.fieldName, step);
  scheduleSettingsSave();
}

function labelForField(fieldName) {
  return fieldName
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function scheduleAutoApply(input) {
  const form = input.closest("[data-tuning-form]");
  const axis = form?.dataset.tuningForm;
  if (!axis || input.value === "") return;

  clearTimeout(autoApplyTimers.get(input));
  const timer = setTimeout(() => {
    applyTuningPayload(axis, { [input.name]: input.value }, {
      pendingMessage: `Applying ${labelForField(input.name)}...`,
      successMessage: `${labelForField(input.name)} applied`,
    });
  }, 220);
  autoApplyTimers.set(input, timer);
}

document.querySelectorAll("[data-tab-button]").forEach((button) => {
  button.addEventListener("click", () => {
    const axis = button.dataset.tabButton;
    const target = button.dataset.tabTarget;
    document.querySelectorAll(`[data-tab-button="${axis}"]`).forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    document.querySelectorAll(`[data-tab-panel="${axis}"]`).forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.tabName === target);
    });
  });
});

if (fields.refreshBtn) {
  fields.refreshBtn.addEventListener("click", refreshStatus);
}

Object.entries(axisFields).forEach(([label, ui]) => {
  ui.plotSelect?.addEventListener("change", () => {
    ui.chartValue.textContent = selectedChartValueFromHistory(label);
    drawChart(label, new Date());
  });
});

document.querySelectorAll("[data-tuning-form]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    applyTuning(form.dataset.tuningForm, form);
  });

  form.querySelectorAll("input[type='number']").forEach((input) => {
    input.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      openStepPanel(input, event);
    });
    input.addEventListener("input", () => {
      scheduleAutoApply(input);
    });
  });
});

document.querySelectorAll("[data-save-tuning]").forEach((button) => {
  button.addEventListener("click", () => {
    saveTuning(button.dataset.saveTuning, button);
  });
});

fields.tuningStepInput?.addEventListener("input", updateActiveStep);
fields.tuningStepInput?.addEventListener("change", updateActiveStep);
fields.tuningStepClose?.addEventListener("click", closeStepPanel);

document.addEventListener("pointerdown", (event) => {
  if (!fields.tuningStepPanel || fields.tuningStepPanel.hidden) return;
  if (fields.tuningStepPanel.contains(event.target)) return;
  closeStepPanel();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeStepPanel();
});

loadAppSettings();
refreshStatus();
setInterval(refreshStatus, 25);
