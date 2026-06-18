const fields = {
  pageTitle: document.getElementById("pageTitle"),
  navDot: document.getElementById("navDot"),
  navStatus: document.getElementById("navStatus"),
  lastUpdated: document.getElementById("lastUpdated"),
  refreshBtn: document.getElementById("refreshBtn"),
  tuningStepPanel: document.getElementById("tuningStepPanel"),
  tuningStepTitle: document.getElementById("tuningStepTitle"),
  tuningStepInput: document.getElementById("tuningStepInput"),
  tuningStepClose: document.getElementById("tuningStepClose"),
  motorToggle: document.getElementById("motorToggle"),
  motorToggleLabel: document.getElementById("motorToggleLabel"),
  motorStop: document.getElementById("motorStop"),
  skyStop: document.getElementById("skyStop"),
  motorGoto: document.getElementById("motorGoto"),
  serverUptime: document.getElementById("serverUptime"),
  systemSetting: document.getElementById("systemSetting"),
  logEntries: document.getElementById("systemLogEntries"),
  gotoPanel: document.getElementById("gotoPanel"),
  gotoClose: document.getElementById("gotoClose"),
  gotoForm: document.getElementById("gotoForm"),
  gotoAzimuth: document.getElementById("gotoAzimuth"),
  gotoAltitude: document.getElementById("gotoAltitude"),
  gotoUseActual: document.getElementById("gotoUseActual"),
  gotoApply: document.getElementById("gotoApply"),
  velocityForm: document.getElementById("velocityForm"),
  velocityAzimuth: document.getElementById("velocityAzimuth"),
  velocityAltitude: document.getElementById("velocityAltitude"),
  velocityZero: document.getElementById("velocityZero"),
  velocityApply: document.getElementById("velocityApply"),
  azimuthTuningPanel: document.getElementById("azimuthTuningPanel"),
  altitudeTuningPanel: document.getElementById("altitudeTuningPanel"),
  settingsPanel: document.getElementById("settingsPanel"),
  settingsClose: document.getElementById("settingsClose"),
  settingsForm: document.getElementById("settingsForm"),
  settingsStationName: document.getElementById("settingsStationName"),
  settingsLatitude: document.getElementById("settingsLatitude"),
  settingsLongitude: document.getElementById("settingsLongitude"),
  settingsAzimuthSerial: document.getElementById("settingsAzimuthSerial"),
  settingsAzimuthSerialView: document.getElementById("settingsAzimuthSerialView"),
  settingsAltitudeSerialView: document.getElementById("settingsAltitudeSerialView"),
  settingsAzimuthCcwLimit: document.getElementById("settingsAzimuthCcwLimit"),
  settingsAzimuthCwLimit: document.getElementById("settingsAzimuthCwLimit"),
  settingsAzimuthOffset: document.getElementById("settingsAzimuthOffset"),
  settingsAzimuthCurrentLimit: document.getElementById("settingsAzimuthCurrentLimit"),
  settingsAltitudeUpperLimit: document.getElementById("settingsAltitudeUpperLimit"),
  settingsAltitudeLowerLimit: document.getElementById("settingsAltitudeLowerLimit"),
  settingsAltitudeOffset: document.getElementById("settingsAltitudeOffset"),
  settingsAltitudeCurrentLimit: document.getElementById("settingsAltitudeCurrentLimit"),
  settingsSlewRate: document.getElementById("settingsSlewRate"),
  settingsReloadSerials: document.getElementById("settingsReloadSerials"),
  settingsSave: document.getElementById("settingsSave"),
  azimuthCcwSensor: document.getElementById("azimuthCcwSensor"),
  azimuthCwSensor: document.getElementById("azimuthCwSensor"),
  axisView: document.getElementById("axisView"),
  skyView: document.getElementById("skyView"),
  skySphereCanvas: document.getElementById("skySphereCanvas"),
  skyAzimuthPositionValue: document.getElementById("skyAzimuthPositionValue"),
  skyAzimuthVelocityValue: document.getElementById("skyAzimuthVelocityValue"),
  skyAzimuthCurrentValue: document.getElementById("skyAzimuthCurrentValue"),
  skyAltitudePositionValue: document.getElementById("skyAltitudePositionValue"),
  skyAltitudeVelocityValue: document.getElementById("skyAltitudeVelocityValue"),
  skyAltitudeCurrentValue: document.getElementById("skyAltitudeCurrentValue"),
  skyGotoForm: document.getElementById("skyGotoForm"),
  skyGotoAzimuth: document.getElementById("skyGotoAzimuth"),
  skyGotoAltitude: document.getElementById("skyGotoAltitude"),
  skyGotoVelocity: document.getElementById("skyGotoVelocity"),
  skyGotoUseActual: document.getElementById("skyGotoUseActual"),
  skyTargetMessage: document.getElementById("skyTargetMessage"),
  skyVelocityForm: document.getElementById("skyVelocityForm"),
  skyVelocityAzimuth: document.getElementById("skyVelocityAzimuth"),
  skyVelocityAltitude: document.getElementById("skyVelocityAltitude"),
  skyVelocityZero: document.getElementById("skyVelocityZero"),
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
    amplitudeAverage: document.getElementById("azimuthAmplitudeAverage"),
    enableMeter: document.getElementById("azimuthEnableMeter"),
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
    amplitudeAverage: document.getElementById("altitudeAmplitudeAverage"),
    enableMeter: document.getElementById("altitudeEnableMeter"),
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

let appSettings = {
  tuning_steps: { Azimuth: {}, Altitude: {} },
  drive_serials: { azimuth_serial: null, altitude_serial: null },
  station: { name: "", latitude: null, longitude: null },
  motion_limits: {},
};
let activeStepTarget = null;
const autoApplyTimers = new WeakMap();
let settingsSaveTimer = null;
let latestStatus = null;
let motorCommandInFlight = false;
let logSequence = 0;
let selectedSkyTarget = null;
const floatingWindowStoragePrefix = "fireDetector.floatingWindow.";
const floatingWindowMargin = 12;
const viewModeStorageKey = "fireDetector.viewMode";
let activeViewMode = readStoredViewMode();

class MotionCommandGuard {
  constructor(statusProvider) {
    this.statusProvider = statusProvider;
  }

  validate(action, payload) {
    const targets = this.motionTargets(action, payload);
    if (targets.length === 0) {
      return { ok: true };
    }

    const axisMap = this.axesByLabel();
    const disabled = targets.filter((target) => {
      const axis = axisMap[target.label];
      return !axis || !axis.available || !axis.is_armed;
    });

    if (disabled.length === 0) {
      return { ok: true };
    }

    const axisNames = disabled.map((target) => target.label).join(", ");
    return {
      ok: false,
      message: `${axisNames} axis must be enabled before ${this.actionName(action)} commands.`,
    };
  }

  motionTargets(action, payload) {
    if (!payload || !["goto", "velocity"].includes(action)) {
      return [];
    }

    return ["Azimuth", "Altitude"].flatMap((label) => {
      const value = payload[label];
      if (value === undefined || value === null || value === "") {
        return [];
      }
      if (action === "velocity") {
        const velocity = Number(value);
        if (Number.isFinite(velocity) && velocity === 0) {
          return [];
        }
      }
      return [{ label, value }];
    });
  }

  axesByLabel() {
    const axes = Array.isArray(this.statusProvider()?.axes) ? this.statusProvider().axes : [];
    return Object.fromEntries(axes.map((axis) => [axis.label, axis]));
  }

  actionName(action) {
    return action === "goto" ? "Move/Goto" : "Jog/Velocity";
  }
}

const motionCommandGuard = new MotionCommandGuard(() => latestStatus);

class DriveEnableDiagnostics {
  constructor(busReadyVoltage = 5) {
    this.busReadyVoltage = busReadyVoltage;
  }

  enableWarnings(status, axisLabel = null) {
    const axes = this.targetAxes(status, axisLabel);
    if (axisLabel && axes.length === 0) {
      return [`${axisLabel} enable warning: axis status is unavailable.`];
    }

    return axes.flatMap((axis) => this.warningForAxis(axis));
  }

  targetAxes(status, axisLabel) {
    const axes = Array.isArray(status?.axes) ? status.axes : [];
    return axisLabel ? axes.filter((axis) => axis.label === axisLabel) : axes;
  }

  warningForAxis(axis) {
    if (!axis?.available) {
      return [`${valueOrDash(axis?.label)} enable warning: drive is not available.`];
    }
    if (axis.is_armed) {
      return [];
    }

    const issues = ["not armed"];
    const busVoltage = Number(axis.drive_vbus_voltage);
    if (!Number.isFinite(busVoltage)) {
      issues.push("bus voltage unavailable");
    } else if (busVoltage < this.busReadyVoltage) {
      issues.push(`bus voltage low (${formatNumber(busVoltage)} V)`);
    }
    if (Number(axis.active_errors) > 0) {
      issues.push(`active_errors=${valueOrDash(axis.active_errors)}`);
    }
    if (Number(axis.disarm_reason) > 0) {
      issues.push(`disarm_reason=${valueOrDash(axis.disarm_reason)}`);
    }
    if (axis.current_state !== 8) {
      issues.push(`state=${valueOrDash(axis.current_state)} expected=8`);
    }

    return [`${axis.label} enable warning: ${issues.join(", ")}.`];
  }
}

const driveEnableDiagnostics = new DriveEnableDiagnostics();

function readStoredViewMode() {
  try {
    return localStorage.getItem(viewModeStorageKey) === "sky" ? "sky" : "axis";
  } catch (error) {
    return "axis";
  }
}

function storeViewMode(mode) {
  try {
    localStorage.setItem(viewModeStorageKey, mode);
  } catch (error) {
    // View mode is convenience UI state; the dashboard should continue without storage.
  }
}

function floatingWindowStorageKey(panel) {
  return `${floatingWindowStoragePrefix}${panel.dataset.floatingWindow || panel.id}`;
}

function readFloatingWindowPosition(panel) {
  try {
    const raw = localStorage.getItem(floatingWindowStorageKey(panel));
    if (!raw) return null;
    const position = JSON.parse(raw);
    if (!Number.isFinite(position?.left) || !Number.isFinite(position?.top)) return null;
    return position;
  } catch (error) {
    return null;
  }
}

function saveFloatingWindowPosition(panel) {
  const rect = panel.getBoundingClientRect();
  try {
    localStorage.setItem(floatingWindowStorageKey(panel), JSON.stringify({
      left: Math.round(rect.left),
      top: Math.round(rect.top),
    }));
  } catch (error) {
    // Window placement is convenience UI state; dragging should still work if storage is blocked.
  }
}

function clampFloatingWindowPosition(panel, left, top) {
  const maxLeft = Math.max(floatingWindowMargin, window.innerWidth - panel.offsetWidth - floatingWindowMargin);
  const maxTop = Math.max(floatingWindowMargin, window.innerHeight - panel.offsetHeight - floatingWindowMargin);
  return {
    left: Math.min(Math.max(floatingWindowMargin, left), maxLeft),
    top: Math.min(Math.max(floatingWindowMargin, top), maxTop),
  };
}

function setFloatingWindowPosition(panel, left, top) {
  const position = clampFloatingWindowPosition(panel, left, top);
  panel.style.left = `${position.left}px`;
  panel.style.top = `${position.top}px`;
  panel.style.right = "auto";
}

function restoreFloatingWindowPosition(panel, fallbackPosition = null) {
  if (!panel) return;
  const savedPosition = readFloatingWindowPosition(panel);
  if (savedPosition) {
    setFloatingWindowPosition(panel, savedPosition.left, savedPosition.top);
    return;
  }
  if (fallbackPosition) {
    setFloatingWindowPosition(panel, fallbackPosition.left, fallbackPosition.top);
  }
}

function initializeFloatingWindows() {
  document.querySelectorAll("[data-floating-window]").forEach((panel) => {
    const handle = panel.querySelector("[data-floating-window-handle]");
    if (!handle) return;

    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      if (event.target.closest("button, input, select, textarea, a, label")) return;
      event.preventDefault();

      const rect = panel.getBoundingClientRect();
      const pointerOffsetX = event.clientX - rect.left;
      const pointerOffsetY = event.clientY - rect.top;
      panel.setPointerCapture?.(event.pointerId);
      panel.classList.add("is-dragging");
      setFloatingWindowPosition(panel, rect.left, rect.top);

      const movePanel = (moveEvent) => {
        setFloatingWindowPosition(
          panel,
          moveEvent.clientX - pointerOffsetX,
          moveEvent.clientY - pointerOffsetY,
        );
      };

      const stopDragging = () => {
        if (panel.hasPointerCapture?.(event.pointerId)) {
          panel.releasePointerCapture(event.pointerId);
        }
        panel.classList.remove("is-dragging");
        saveFloatingWindowPosition(panel);
        window.removeEventListener("pointermove", movePanel);
        window.removeEventListener("pointerup", stopDragging);
        window.removeEventListener("pointercancel", stopDragging);
      };

      window.addEventListener("pointermove", movePanel);
      window.addEventListener("pointerup", stopDragging, { once: true });
      window.addEventListener("pointercancel", stopDragging, { once: true });
    });
  });
}

async function refreshStatus() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    const data = await response.json();
    renderStatus(data);
  } catch (error) {
    addLog("error", `Monitor API unavailable: ${error.message}`);
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
  latestStatus = data;
  const timestamp = data.timestamp ? new Date(data.timestamp) : new Date();
  if (fields.lastUpdated) {
    fields.lastUpdated.textContent = `Updated ${timestamp.toLocaleTimeString()}`;
  }
  renderDeviceUptime(data.server_started_at, data.timestamp);
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
    renderMotorControls(data);
    renderAxisControls(data);
    renderSkySphere(data);
    return;
  }

  if (fields.navStatus) {
    fields.navStatus.textContent = data.has_bus_power ? "Ready" : "USB only";
  }

  const axes = Array.isArray(data.axes) ? data.axes : [];
  renderAxis("Azimuth", axes.find((axis) => axis.label === "Azimuth"), timestamp);
  renderAxis("Altitude", axes.find((axis) => axis.label === "Altitude"), timestamp);
  renderMotorControls(data);
  renderAxisControls(data);
  renderSkySphere(data);
  if (fields.settingsPanel && !fields.settingsPanel.hidden) {
    populateDriveSerialOptions();
  }
}

function renderAzimuthSensors(sensors) {
  setSensorPill(fields.azimuthCcwSensor, Boolean(sensors?.ccw_sensor));
  setSensorPill(fields.azimuthCwSensor, Boolean(sensors?.cw_sensor));
}

function setSensorPill(element, active) {
  if (!element) return;
  element.classList.toggle("is-active", active);
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
    setTuningInputs(label, null);
    renderActualReadouts(ui.chartValue, null);
    renderAmplitudeAverage(ui.amplitudeAverage, [], selectedSeries(label));
    setAxisEnableMeter(ui.enableMeter, false, false);
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
  setAxisEnableMeter(ui.enableMeter, Boolean(axis.is_armed), true);
  setTuningInputs(label, axis);
  renderActualReadouts(ui.chartValue, axis);
  ui.card.classList.add("axis-ready");
  drawChart(label, timestamp);
}

function setAxisEnableMeter(element, enabled, available = true) {
  if (!element) return;
  element.classList.toggle("is-enabled", available && enabled);
  element.classList.toggle("is-disabled", !available || !enabled);
  element.setAttribute("aria-label", available && enabled ? "Axis enabled" : "Axis disabled");
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
  ctx.fillStyle = "rgba(7, 10, 18, 0.34)";
  ctx.fillRect(0, 0, width, height);
  drawGrid(ctx, width, height, padLeft, padRight, padTop, padBottom);
  drawTimeLabels(ctx, width, height, padLeft, padRight, padBottom);

  const selected = selectedSeries(label);
  const values = samples.map((sample) => sample[selected.key]).filter((value) => value !== null);
  renderAmplitudeAverage(ui.amplitudeAverage, values, selected);

  if (samples.length < 2) {
    ctx.fillStyle = "rgba(244, 246, 255, 0.55)";
    ctx.font = "24px Segoe UI";
    ctx.fillText("Waiting for telemetry samples", padLeft, height / 2);
    return;
  }

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

function renderAmplitudeAverage(container, values, selected) {
  if (!container) return;
  const valueElement = container.querySelector("em");
  if (!valueElement) return;

  const amplitudes = values
    .map((value) => Math.abs(value))
    .filter((value) => Number.isFinite(value));
  if (!amplitudes.length) {
    valueElement.textContent = "--";
    return;
  }

  const average = amplitudes.reduce((sum, value) => sum + value, 0) / amplitudes.length;
  valueElement.textContent = `${formatNumber(average)} ${selected.unit}`;
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
  ctx.font = "10.5px Segoe UI";
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
  ctx.font = "11.5px Segoe UI";
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

function renderSkySphere(data) {
  const axes = Array.isArray(data?.axes) ? data.axes : [];
  const azimuth = axes.find((axis) => axis.label === "Azimuth");
  const altitude = axes.find((axis) => axis.label === "Altitude");
  const azimuthDeg = toNumber(azimuth?.position_deg);
  const altitudeDeg = toNumber(altitude?.position_deg);

  renderSkyAxisActuals("Azimuth", azimuth);
  renderSkyAxisActuals("Altitude", altitude);

  drawSkySphere(azimuthDeg, altitudeDeg, Boolean(data?.connected), data?.azimuth_sensors);
}

function renderSkyAxisActuals(label, axis) {
  const prefix = label === "Azimuth" ? "skyAzimuth" : "skyAltitude";
  const position = fields[`${prefix}PositionValue`];
  const velocity = fields[`${prefix}VelocityValue`];
  const current = fields[`${prefix}CurrentValue`];
  if (position) position.textContent = `${formatNumber(axis?.position_deg)} Deg`;
  if (velocity) velocity.textContent = `${formatNumber(axis?.velocity_deg_per_sec)} Deg/Sec`;
  if (current) current.textContent = `${formatNumber(axis?.current)} Amp`;
}

function drawSkySphere(azimuthDeg, altitudeDeg, connected, sensors = null) {
  const canvas = fields.skySphereCanvas;
  if (!canvas) return;
  const rect = canvas.parentElement?.getBoundingClientRect() || canvas.getBoundingClientRect();
  const availableWidth = rect.width || 720;
  const availableHeight = rect.height || availableWidth;
  const size = Math.max(320, Math.floor(Math.min(availableWidth, availableHeight, 820)));
  canvas.style.width = `${size}px`;
  canvas.style.height = `${size}px`;
  const dpr = window.devicePixelRatio || 1;
  const scaledSize = Math.floor(size * dpr);
  if (canvas.width !== scaledSize || canvas.height !== scaledSize) {
    canvas.width = scaledSize;
    canvas.height = scaledSize;
  }

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);

  const cx = size / 2;
  const cy = size / 2;
  const radius = size * 0.42;
  const horizonRadius = skyAltitudeRadius(0, radius);

  ctx.fillStyle = "#101521";
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fill();

  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.clip();
  drawSkyAltitudeBand(ctx, cx, cy, radius, sensors);
  drawSkyGrid(ctx, cx, cy, radius, horizonRadius);
  drawSkySoftwareLimits(ctx, cx, cy, radius, sensors);
  drawSkyMarker(ctx, cx, cy, radius, azimuthDeg, altitudeDeg, connected);
  drawSkyTargetMarker(ctx, cx, cy, radius);
  ctx.restore();

  ctx.strokeStyle = "rgba(244, 246, 255, 0.24)";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.arc(cx, cy, radius - 1, 0, Math.PI * 2);
  ctx.stroke();
  drawSkyOverlayLabels(ctx, cx, cy, radius, horizonRadius);
  drawSelectedAzimuthLimitLabel(ctx, cx, cy, radius, sensors, size);
  drawAltitudeLabels(ctx, cx, cy, radius);
}

function drawSkyGrid(ctx, cx, cy, radius, horizonRadius) {
  ctx.lineWidth = 1;
  const altitudeValues = skyAltitudeGridValues();
  altitudeValues.forEach((altitude, index) => {
    const ringRadius = skyAltitudeRadius(altitude, radius);
    ctx.strokeStyle = altitude === 0 ? "rgba(87, 214, 141, 0.56)" : "rgba(244, 246, 255, 0.12)";
    ctx.setLineDash(altitude < 0 ? [6, 8] : []);
    ctx.beginPath();
    ctx.arc(cx, cy, ringRadius, 0, Math.PI * 2);
    ctx.stroke();
  });
  ctx.setLineDash([]);

  skyAzimuthGridValues().forEach((azimuth) => {
    const angle = (azimuth * Math.PI) / 180;
    ctx.strokeStyle = azimuth % 90 === 0 ? "rgba(244, 246, 255, 0.18)" : "rgba(244, 246, 255, 0.08)";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.sin(angle) * radius, cy - Math.cos(angle) * radius);
    ctx.stroke();
  });
}

function drawAltitudeLabels(ctx, cx, cy, radius) {
  skyAltitudeGridValues().forEach((altitude) => {
    drawAltitudeLabel(ctx, cx, cy, skyAltitudeRadius(altitude, radius), altitude);
  });
}

function drawAltitudeLabel(ctx, cx, cy, ringRadius, altitude) {
  const labelAngle = (148 * Math.PI) / 180;
  const labelRadius = ringRadius + 8;
  const x = cx + Math.sin(labelAngle) * labelRadius;
  const y = cy - Math.cos(labelAngle) * labelRadius;
  ctx.setLineDash([]);
  ctx.fillStyle = altitude === 0 ? "rgba(87, 214, 141, 0.78)" : "rgba(244, 246, 255, 0.54)";
  ctx.font = "10.5px Segoe UI";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(`${formatSignedAngle(altitude)}`, x, y);
}

function drawSkyAltitudeBand(ctx, cx, cy, radius, sensors) {
  const limits = appSettings.motion_limits || {};
  const lowerLimit = toNumber(limits.altitude_lower_limit_deg);
  const upperLimit = toNumber(limits.altitude_upper_limit_deg);
  const selectedLimit = skySelectedAzimuthLimit(sensors);
  const lowerAltitude = lowerLimit === null ? skyVisibleMinimumAltitude() : lowerLimit;
  const upperAltitude = upperLimit === null ? skyVisibleMaximumAltitude() : upperLimit;
  const innerAltitude = Math.max(skyVisibleMinimumAltitude(), Math.min(skyVisibleMaximumAltitude(), upperAltitude));
  const outerAltitude = Math.max(skyVisibleMinimumAltitude(), Math.min(skyVisibleMaximumAltitude(), lowerAltitude));
  const innerRadius = skyAltitudeRadius(innerAltitude, radius);
  const outerRadius = skyAltitudeRadius(outerAltitude, radius);
  const targetAzimuth = selectedLimit ?? (skySelectedAzimuthSide(sensors) === "ccw" ? -360 : 360);

  ctx.setLineDash([]);
  ctx.fillStyle = "rgba(93, 189, 255, 0.16)";
  ctx.beginPath();
  drawAzimuthAnnularSectorPath(ctx, cx, cy, innerRadius, outerRadius, targetAzimuth);
  ctx.closePath();
  ctx.fill();
}

function drawSkySoftwareLimits(ctx, cx, cy, radius, sensors) {
  const limits = appSettings.motion_limits || {};
  const selectedLimit = skySelectedAzimuthLimit(sensors);
  drawAltitudeLimit(ctx, cx, cy, radius, toNumber(limits.altitude_lower_limit_deg));
  drawAltitudeLimit(ctx, cx, cy, radius, toNumber(limits.altitude_upper_limit_deg));
  drawAzimuthLimit(ctx, cx, cy, radius, selectedLimit);
}

function drawAltitudeLimit(ctx, cx, cy, radius, altitude) {
  if (altitude === null) return;
  const clampedAltitude = Math.max(skyVisibleMinimumAltitude(), Math.min(skyVisibleMaximumAltitude(), altitude));
  const ringRadius = skyAltitudeRadius(clampedAltitude, radius);
  ctx.setLineDash([]);
  ctx.strokeStyle = "rgba(93, 189, 255, 0.74)";
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  ctx.arc(cx, cy, ringRadius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawAzimuthLimit(ctx, cx, cy, radius, azimuth) {
  if (azimuth === null) return;
  const angle = (normalizeDegrees(azimuth) * Math.PI) / 180;
  ctx.setLineDash([10, 5]);
  ctx.strokeStyle = "rgba(142, 69, 230, 0.74)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.sin(angle) * radius, cy - Math.cos(angle) * radius);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawAzimuthLimitLabel(ctx, cx, cy, radius, azimuth, side, canvasSize) {
  if (azimuth === null) return;
  const labelPoint = skyPolarPoint(cx, cy, radius + 22, azimuth);
  const label = `${side === "ccw" ? "CCW" : "CW"} Limit ${formatSignedDegrees(azimuth)}`;
  ctx.setLineDash([]);
  ctx.font = "11px Segoe UI";
  const paddingX = 7;
  const boxHeight = 22;
  const boxWidth = ctx.measureText(label).width + paddingX * 2;
  const margin = 8;
  const normalized = normalizeDegrees(azimuth);
  let align = normalized > 180 ? "right" : normalized === 0 || normalized === 180 ? "center" : "left";
  let textX = labelPoint.x + (normalized > 180 ? -8 : normalized === 0 || normalized === 180 ? 0 : 8);
  let textY = labelPoint.y;
  let boxLeft = align === "right" ? textX - boxWidth : align === "center" ? textX - boxWidth / 2 : textX;

  if (boxLeft < margin) {
    boxLeft = margin;
    align = "left";
    textX = boxLeft + paddingX;
  } else if (boxLeft + boxWidth > canvasSize - margin) {
    boxLeft = canvasSize - margin - boxWidth;
    align = "left";
    textX = boxLeft + paddingX;
  }

  let boxTop = textY - boxHeight / 2;
  if (boxTop < margin) boxTop = margin;
  if (boxTop + boxHeight > canvasSize - margin) boxTop = canvasSize - margin - boxHeight;
  textY = boxTop + boxHeight / 2;

  ctx.fillStyle = "rgba(16, 21, 33, 0.78)";
  ctx.strokeStyle = "rgba(142, 69, 230, 0.38)";
  ctx.lineWidth = 1;
  roundedRectPath(ctx, boxLeft, boxTop, boxWidth, boxHeight, 6);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "rgba(218, 200, 255, 0.88)";
  ctx.textBaseline = "middle";
  ctx.textAlign = align;
  ctx.fillText(label, textX, textY);
}

function drawSelectedAzimuthLimitLabel(ctx, cx, cy, radius, sensors, canvasSize) {
  drawAzimuthLimitLabel(
    ctx,
    cx,
    cy,
    radius,
    skySelectedAzimuthLimit(sensors),
    skySelectedAzimuthSide(sensors),
    canvasSize,
  );
}

function roundedRectPath(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawAzimuthAnnularSectorPath(ctx, cx, cy, innerRadius, outerRadius, targetAzimuth) {
  const target = toNumber(targetAzimuth) ?? 0;
  const steps = Math.max(18, Math.ceil(Math.abs(target) / 6));
  for (let index = 0; index <= steps; index += 1) {
    const azimuth = (target * index) / steps;
    const point = skyPolarPoint(cx, cy, outerRadius, azimuth);
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  }
  for (let index = steps; index >= 0; index -= 1) {
    const azimuth = (target * index) / steps;
    const point = skyPolarPoint(cx, cy, innerRadius, azimuth);
    ctx.lineTo(point.x, point.y);
  }
}

function skyPolarPoint(cx, cy, radius, azimuth) {
  const angle = (azimuth * Math.PI) / 180;
  return {
    x: cx + Math.sin(angle) * radius,
    y: cy - Math.cos(angle) * radius,
  };
}

function skySelectedAzimuthSide(sensors) {
  const ccwActive = Boolean(sensors?.ccw_sensor);
  const cwActive = Boolean(sensors?.cw_sensor);
  return ccwActive && !cwActive ? "ccw" : "cw";
}

function skySelectedAzimuthLimit(sensors) {
  const limits = appSettings.motion_limits || {};
  return skySelectedAzimuthSide(sensors) === "ccw"
    ? toNumber(limits.azimuth_ccw_limit_deg)
    : toNumber(limits.azimuth_cw_limit_deg);
}

function drawSkyMarker(ctx, cx, cy, radius, azimuthDeg, altitudeDeg, connected) {
  if (!connected || azimuthDeg === null || altitudeDeg === null) {
    ctx.fillStyle = "rgba(244, 246, 255, 0.56)";
    ctx.font = "18px Segoe UI";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("Waiting for mount position", cx, cy);
    return;
  }

  const safeAltitude = Math.max(skyVisibleMinimumAltitude(), Math.min(skyVisibleMaximumAltitude(), altitudeDeg));
  const markerRadius = skyAltitudeRadius(safeAltitude, radius);
  const angle = (normalizeDegrees(azimuthDeg) * Math.PI) / 180;
  const x = cx + Math.sin(angle) * markerRadius;
  const y = cy - Math.cos(angle) * markerRadius;
  const belowHorizon = safeAltitude < 0;

  ctx.strokeStyle = "rgba(255, 138, 42, 0.58)";
  ctx.lineWidth = 1.2;
  ctx.setLineDash([5, 7]);
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(x, y);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = "rgba(255, 138, 42, 0.20)";
  ctx.beginPath();
  ctx.arc(x, y, 15, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#ff8a2a";
  ctx.beginPath();
  ctx.arc(x, y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "rgba(255, 244, 232, 0.86)";
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  ctx.arc(x, y, 9, 0, Math.PI * 2);
  ctx.stroke();

}

function drawSkyTargetMarker(ctx, cx, cy, radius) {
  if (!selectedSkyTarget) return;
  const altitude = Math.max(
    skyVisibleMinimumAltitude(),
    Math.min(skyVisibleMaximumAltitude(), selectedSkyTarget.altitude),
  );
  const markerRadius = skyAltitudeRadius(altitude, radius);
  const point = skyPolarPoint(cx, cy, markerRadius, normalizeDegrees(selectedSkyTarget.azimuth));

  ctx.setLineDash([]);
  ctx.strokeStyle = "rgba(87, 214, 141, 0.58)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(point.x, point.y);
  ctx.stroke();

  ctx.fillStyle = "rgba(87, 214, 141, 0.16)";
  ctx.beginPath();
  ctx.arc(point.x, point.y, 20, 0, Math.PI * 2);
  ctx.fill();

  ctx.strokeStyle = "rgba(87, 214, 141, 0.94)";
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  ctx.arc(point.x, point.y, 11, 0, Math.PI * 2);
  ctx.stroke();

  ctx.strokeStyle = "rgba(227, 255, 238, 0.88)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(point.x - 15, point.y);
  ctx.lineTo(point.x - 5, point.y);
  ctx.moveTo(point.x + 5, point.y);
  ctx.lineTo(point.x + 15, point.y);
  ctx.moveTo(point.x, point.y - 15);
  ctx.lineTo(point.x, point.y - 5);
  ctx.moveTo(point.x, point.y + 5);
  ctx.lineTo(point.x, point.y + 15);
  ctx.stroke();

  ctx.fillStyle = "#57d68d";
  ctx.beginPath();
  ctx.arc(point.x, point.y, 4.5, 0, Math.PI * 2);
  ctx.fill();
}

function drawSkyOverlayLabels(ctx, cx, cy, radius, horizonRadius) {
  drawSkyCardinals(ctx, cx, cy, radius);
  drawSkyAzimuthLabels(ctx, cx, cy, radius);
}

function drawSkyCardinals(ctx, cx, cy, radius) {
  const labels = [
    ["N", 0],
    ["E", 90],
    ["S", 180],
    ["W", 270],
  ];
  const labelRadius = radius + 12;
  ctx.font = "14px Segoe UI";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  labels.forEach(([label, degrees]) => {
    const angle = (degrees * Math.PI) / 180;
    ctx.fillStyle = "rgba(244, 246, 255, 0.72)";
    ctx.fillText(label, cx + Math.sin(angle) * labelRadius, cy - Math.cos(angle) * labelRadius);
  });
}

function drawSkyAzimuthLabels(ctx, cx, cy, radius) {
  const labels = [
    ["0", 0],
    ["90", 90],
    ["180", 180],
    ["270", 270],
  ];
  const labelRadius = radius + 32;
  ctx.setLineDash([]);
  ctx.fillStyle = "rgba(244, 246, 255, 0.66)";
  ctx.font = "12px Segoe UI";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  labels.forEach(([label, degrees]) => {
    const angle = (degrees * Math.PI) / 180;
    ctx.fillText(label, cx + Math.sin(angle) * labelRadius, cy - Math.cos(angle) * labelRadius);
  });
}

function skyAltitudeGridValues() {
  return [-60, -30, 0, 30, 60];
}

function skyAltitudeRadius(altitude, radius) {
  const altitudeNumber = toNumber(altitude);
  const visibleMinAltitude = skyVisibleMinimumAltitude();
  const visibleMaxAltitude = skyVisibleMaximumAltitude();
  const outerGapRatio = 0.08;
  const clampedAltitude = Math.max(visibleMinAltitude, Math.min(visibleMaxAltitude, altitudeNumber ?? visibleMinAltitude));
  const progress = (clampedAltitude - visibleMinAltitude) / (visibleMaxAltitude - visibleMinAltitude);
  return radius * (outerGapRatio + (1 - outerGapRatio) * (1 - progress));
}

function skyVisibleMinimumAltitude() {
  return -60;
}

function skyVisibleMaximumAltitude() {
  return 90;
}

function skyAzimuthGridValues() {
  const limits = appSettings.motion_limits || {};
  const ccw = toNumber(limits.azimuth_ccw_limit_deg);
  const cw = toNumber(limits.azimuth_cw_limit_deg);
  if (ccw === null || cw === null) {
    return Array.from({ length: 12 }, (_, index) => index * 30);
  }
  const start = Math.ceil(ccw / 30) * 30;
  const end = Math.floor(cw / 30) * 30;
  const values = [];
  for (let value = start; value <= end; value += 30) {
    values.push(normalizeDegrees(value));
  }
  values.push(normalizeDegrees(ccw), normalizeDegrees(cw));
  return uniqueSortedDegrees(values);
}

function uniqueSortedDegrees(values) {
  return [...new Set(values.map((value) => Number(normalizeDegrees(value).toFixed(3))))].sort((a, b) => a - b);
}

function formatSignedDegrees(value) {
  const number = toNumber(value);
  if (number === null) return "-- Deg";
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${formatNumber(number)} Deg`;
}

function formatSignedAngle(value) {
  const number = toNumber(value);
  if (number === null) return "--";
  if (number === 0) return "0.0";
  const prefix = number > 0 ? "+" : "-";
  return `${prefix}${Math.abs(number).toFixed(1)}`;
}

function normalizeDegrees(value) {
  if (!Number.isFinite(value)) return 0;
  return ((value % 360) + 360) % 360;
}

function selectedSeries(label) {
  const value = axisFields[label]?.plotSelect?.value || "position";
  return seriesConfig[value] || seriesConfig.position;
}

function renderActualReadouts(container, axis) {
  if (!container) return;
  const values = {
    position: axis?.position_deg,
    velocity: axis?.velocity_deg_per_sec,
    current: axis?.current,
  };
  Object.entries(seriesConfig).forEach(([name, config]) => {
    const valueElement = container.querySelector(`.${name} em`);
    if (valueElement) {
      valueElement.textContent = `${formatNumber(values[name])} ${config.unit}`;
    }
  });
}

function renderMotorControls(data) {
  const axes = Array.isArray(data?.axes) ? data.axes : [];
  const connectedAxes = axes.filter((axis) => axis.available);
  const allConnected = data?.connected && connectedAxes.length >= 2;
  const anyArmed = connectedAxes.some((axis) => axis.is_armed);
  const allArmed = connectedAxes.length >= 2 && connectedAxes.every((axis) => axis.is_armed);

  if (fields.motorToggle) {
    fields.motorToggle.disabled = !allConnected || motorCommandInFlight;
    fields.motorToggle.classList.toggle("is-enabled", allArmed);
    fields.motorToggle.classList.toggle("is-partial", anyArmed && !allArmed);
    fields.motorToggle.setAttribute("aria-pressed", allArmed ? "true" : "false");
  }
  if (fields.motorToggleLabel) {
    fields.motorToggleLabel.textContent = allArmed ? "Disable" : anyArmed ? "Enable All" : "Enable";
  }
  if (fields.motorStop) {
    fields.motorStop.disabled = !anyArmed || motorCommandInFlight;
  }
  if (fields.skyStop) {
    fields.skyStop.disabled = !anyArmed || motorCommandInFlight;
  }
  if (fields.motorGoto) {
    fields.motorGoto.disabled = !allConnected || motorCommandInFlight;
  }
}

function renderAxisControls(data) {
  const axisMap = Object.fromEntries((Array.isArray(data?.axes) ? data.axes : []).map((axis) => [axis.label, axis]));
  document.querySelectorAll("[data-axis-control]").forEach((form) => {
    const axis = axisMap[form.dataset.axisControl];
    const available = Boolean(data?.connected && axis?.available);
    const armed = Boolean(axis?.is_armed);
    form.querySelectorAll("button").forEach((button) => {
      button.disabled = motorCommandInFlight || !available;
    });
    const toggleButton = form.querySelector("[data-axis-toggle]");
    if (toggleButton) {
      toggleButton.dataset.axisAction = armed ? "disable" : "enable";
      toggleButton.textContent = armed ? "Disable" : "Enable";
      toggleButton.classList.toggle("axis-enable", !armed);
      toggleButton.classList.toggle("axis-disable", armed);
      toggleButton.setAttribute("aria-pressed", armed ? "true" : "false");
    }
  });
}

function setViewMode(mode, { persist = true } = {}) {
  activeViewMode = mode === "sky" ? "sky" : "axis";
  if (fields.axisView) fields.axisView.hidden = activeViewMode !== "axis";
  if (fields.skyView) fields.skyView.hidden = activeViewMode !== "sky";

  document.querySelectorAll("[data-view-mode]").forEach((button) => {
    const active = button.dataset.viewMode === activeViewMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });

  if (persist) {
    storeViewMode(activeViewMode);
    addLog("message", `Dashboard view changed to ${activeViewMode === "sky" ? "Horizon View" : "Axis View"}`);
  }
  if (activeViewMode === "sky") {
    renderSkySphere(latestStatus);
  }
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

function renderDeviceUptime(serverStartedAt, serverTimestamp) {
  if (!fields.serverUptime) return;
  const startedAt = serverStartedAt ? new Date(serverStartedAt) : null;
  const currentServerTime = serverTimestamp ? new Date(serverTimestamp) : new Date();
  fields.serverUptime.textContent = startedAt
    && !Number.isNaN(startedAt.getTime())
    && !Number.isNaN(currentServerTime.getTime())
    ? formatDuration(currentServerTime.getTime() - startedAt.getTime())
    : "--";
}

function formatDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(days).padStart(2, "0")}-${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
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

function setTuningInputs(label, axis) {
  tuningBindings.forEach(([uiKey, axisKey]) => {
    setTuningFieldValue(label, uiKey, axisKey, axis?.[axisKey]);
  });
}

function setTuningFieldValue(label, uiKey, fieldName, value) {
  const ui = axisFields[label];
  setInputValueIfIdle(ui?.[uiKey], value);
  tuningFormsForAxis(label).forEach((form) => {
    setInputValueIfIdle(form.elements[fieldName], value);
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

function tuningFormsForAxis(label) {
  return [...document.querySelectorAll(`[data-tuning-form="${label}"]`)];
}

function buildFloatingTuningForms() {
  document.querySelectorAll("[data-floating-tuning-form]").forEach((form) => {
    const label = form.dataset.floatingTuningForm;
    const sourceForm = tuningFormsForAxis(label).find((candidate) => !candidate.dataset.floatingTuningForm);
    if (!sourceForm) return;

    const fragment = document.createDocumentFragment();
    tuningBindings.forEach(([, fieldName]) => {
      const sourceInput = sourceForm.elements[fieldName];
      if (!sourceInput) return;

      const field = document.createElement("label");
      const fieldLabel = document.createElement("span");
      const input = document.createElement("input");
      fieldLabel.textContent = sourceInput.closest("label")?.querySelector("span")?.textContent || labelForField(fieldName);
      input.name = fieldName;
      input.type = sourceInput.type || "number";
      input.min = sourceInput.min;
      input.step = sourceInput.step;
      input.inputMode = sourceInput.inputMode || "decimal";
      field.append(fieldLabel, input);
      fragment.append(field);
    });

    const applyButton = document.createElement("button");
    applyButton.className = "tuning-apply";
    applyButton.type = "submit";
    applyButton.textContent = "Apply Tuning";

    const saveButton = document.createElement("button");
    saveButton.className = "tuning-save";
    saveButton.type = "button";
    saveButton.dataset.saveTuning = label;
    saveButton.textContent = "Save to Drive";

    const message = document.createElement("p");
    message.className = "tuning-message";
    message.dataset.tuningMessage = label;

    fragment.append(applyButton, saveButton, message);
    form.replaceChildren(fragment);
  });
}

function syncMatchingTuningInputs(sourceInput) {
  const form = sourceInput.closest("[data-tuning-form]");
  const axis = form?.dataset.tuningForm;
  if (!axis || !sourceInput.name) return;

  tuningFormsForAxis(axis).forEach((candidate) => {
    const target = candidate.elements[sourceInput.name];
    if (!target || target === sourceInput || document.activeElement === target) return;
    target.value = sourceInput.value;
  });
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

  addLog("message", options.pendingMessage || `Applying ${label} tuning`);
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
    addLog("message", options.successMessage || `${label} tuning applied`);
    setTuningMessage(ui, options.successMessage || "Tuning applied", "is-ok");
  } catch (error) {
    addLog("error", `${label} tuning failed: ${error.message}`);
    setTuningMessage(ui, error.message, "is-error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveTuning(label, button) {
  const ui = axisFields[label];
  addLog("warning", "Stopping motion and disabling both axes before flashing configuration");
  addLog("message", `Flashing ${label} configuration to drive`);
  setTuningMessage(ui, "Flashing configuration to drive...", "");
  button.disabled = true;
  try {
    const response = await fetch(`/api/tuning/${encodeURIComponent(label)}/save`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Save failed.");
    }
    if (data.flash?.warning) addLog("warning", data.flash.warning);
    addLog("success", data.message || `${label} configuration flashed to drive`);
    setTuningMessage(ui, data.message || "Configuration flashed to drive", "is-ok");
  } catch (error) {
    addLog("error", `${label} flash failed: ${error.message}`);
    setTuningMessage(ui, error.message, "is-error");
  } finally {
    button.disabled = false;
  }
}

async function sendMotorCommand(action, payload = null) {
  const guardResult = motionCommandGuard.validate(action, payload);
  if (!guardResult.ok) {
    addLog("warning", guardResult.message);
    return;
  }
  const velocityLimitResult = validateMaxVelocity(action, payload);
  if (!velocityLimitResult.ok) {
    addLog("warning", velocityLimitResult.message);
    return;
  }

  motorCommandInFlight = true;
  addLog("message", `${labelForMotorAction(action)}...`);
  renderMotorControls(latestStatus);
  renderAxisControls(latestStatus);
  try {
    const options = { method: "POST" };
    if (payload) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(`/api/motors/${action}`, options);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Motor command failed.");
    }
    renderStatus(data.status);
    logMotorOutcome(action, data.status);
    if (action === "goto" || action === "velocity") closeGotoPanel();
  } catch (error) {
    addLog("error", `${labelForMotorAction(action)} failed: ${error.message}`);
  } finally {
    motorCommandInFlight = false;
    renderMotorControls(latestStatus);
    renderAxisControls(latestStatus);
  }
}

async function sendAxisMotorCommand(axis, action, payload = null, form = null) {
  const guardResult = motionCommandGuard.validate(action, payload);
  if (!guardResult.ok) {
    setAxisControlMessage(form, guardResult.message, "is-warning");
    addLog("warning", guardResult.message);
    return;
  }
  const velocityLimitResult = validateMaxVelocity(action, payload);
  if (!velocityLimitResult.ok) {
    setAxisControlMessage(form, velocityLimitResult.message, "is-warning");
    addLog("warning", velocityLimitResult.message);
    return;
  }

  motorCommandInFlight = true;
  setAxisControlMessage(form, `${axis} ${labelForMotorAction(action).toLowerCase()}...`);
  addLog("message", `${axis} ${labelForMotorAction(action)}...`);
  renderMotorControls(latestStatus);
  renderAxisControls(latestStatus);
  try {
    const options = { method: "POST" };
    if (payload) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(payload);
    }
    const axisPath = action === "enable" || action === "disable" ? `/${encodeURIComponent(axis)}` : "";
    const response = await fetch(`/api/motors/${action}${axisPath}`, options);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Axis command failed.");
    }
    renderStatus(data.status);
    const warnings = action === "enable"
      ? driveEnableDiagnostics.enableWarnings(data.status, axis)
      : [];
    if (warnings.length > 0) {
      warnings.forEach((message) => addLog("warning", message));
      setAxisControlMessage(form, warnings[0], "is-warning");
    } else {
      setAxisControlMessage(form, `${axis} command complete`, "is-ok");
      addLog("message", `${axis} ${labelForMotorAction(action)} complete`);
    }
  } catch (error) {
    setAxisControlMessage(form, error.message, "is-error");
    addLog("error", `${axis} ${labelForMotorAction(action)} failed: ${error.message}`);
  } finally {
    motorCommandInFlight = false;
    renderMotorControls(latestStatus);
    renderAxisControls(latestStatus);
  }
}

function setAxisControlMessage(form, message, className = "") {
  const messageElement = form?.querySelector("[data-axis-control-message]");
  if (!messageElement) return;
  messageElement.classList.remove("is-ok", "is-error", "is-warning");
  if (className) messageElement.classList.add(className);
  messageElement.textContent = message;
}

function validateMaxVelocity(action, payload) {
  const maxVelocity = toNumber(appSettings.motion_limits?.slew_rate_deg_per_sec);
  if (maxVelocity === null || maxVelocity <= 0 || !payload || !["goto", "velocity"].includes(action)) {
    return { ok: true };
  }

  const violations = [];
  if (action === "goto") {
    const targetVelocity = toNumber(payload.velocity_target_deg_per_sec);
    if (targetVelocity !== null && targetVelocity > maxVelocity) {
      violations.push(`Velocity Target ${formatNumber(targetVelocity)} Deg/Sec`);
    }
  }

  if (action === "velocity") {
    ["Azimuth", "Altitude"].forEach((label) => {
      const velocity = toNumber(payload[label]);
      if (velocity !== null && Math.abs(velocity) > maxVelocity) {
        violations.push(`${label} velocity ${formatNumber(velocity)} Deg/Sec`);
      }
    });
  }

  if (violations.length === 0) {
    return { ok: true };
  }
  return {
    ok: false,
    message: `${violations.join(", ")} exceeds Max Velocity ${formatNumber(maxVelocity)} Deg/Sec.`,
  };
}

function logMotorOutcome(action, status) {
  if (action === "enable") {
    const warnings = driveEnableDiagnostics.enableWarnings(status);
    if (warnings.length > 0) {
      warnings.forEach((message) => addLog("warning", message));
      return;
    }
  }
  if (action === "disable") {
    const axes = Array.isArray(status?.axes) ? status.axes : [];
    const stillArmed = axes.filter((axis) => axis.available && axis.is_armed);
    if (stillArmed.length > 0) {
      addLog("warning", `Disable command sent, but ${stillArmed.map((axis) => axis.label).join(", ")} still reports armed.`);
      return;
    }
  }
  addLog("message", `${labelForMotorAction(action)} complete`);
}

function labelForMotorAction(action) {
  return {
    enable: "Enabling motors",
    disable: "Disabling motors",
    stop: "Stopping motors",
    goto: "Moving motors",
    velocity: "Setting motor velocity",
  }[action] || "Sending command";
}

function addLog(level, message) {
  if (!fields.logEntries || !message) return;
  const entry = document.createElement("div");
  entry.className = `log-entry is-${level}`;
  entry.dataset.sequence = String(++logSequence);

  const time = document.createElement("time");
  time.dateTime = new Date().toISOString();
  time.textContent = new Date().toLocaleString();

  const status = document.createElement("span");
  status.className = "log-level";
  status.textContent = level.toUpperCase();

  const text = document.createElement("span");
  text.className = "log-message";
  text.textContent = message;

  entry.append(time, status, text);
  fields.logEntries.prepend(entry);

  const maxEntries = 500;
  while (fields.logEntries.children.length > maxEntries) {
    fields.logEntries.lastElementChild?.remove();
  }
}

function openGotoPanel() {
  if (!fields.gotoPanel) return;
  fillGotoFromActual();
  fields.gotoPanel.hidden = false;
  restoreFloatingWindowPosition(fields.gotoPanel);
  addLog("message", "Opened Goto position panel");
  fields.gotoAzimuth?.focus();
  fields.gotoAzimuth?.select();
}

function closeGotoPanel() {
  if (fields.gotoPanel) fields.gotoPanel.hidden = true;
}

function tuningPanelForAxis(label) {
  return document.querySelector(`[data-floating-tuning-panel="${label}"]`);
}

function openFloatingTuningPanel(label, event = null) {
  const panel = tuningPanelForAxis(label);
  if (!panel) return;

  const axis = axesByLabel()[label];
  if (axis) setTuningInputs(label, axis);
  panel.hidden = false;
  restoreFloatingWindowPosition(panel, event ? { left: event.clientX, top: event.clientY } : null);
  addLog("message", `Opened ${label} floating tuning panel`);

  const firstInput = panel.querySelector("input");
  firstInput?.focus();
  firstInput?.select();
}

function closeFloatingTuningPanel(label) {
  const panel = tuningPanelForAxis(label);
  if (panel) panel.hidden = true;
}

function closeFloatingTuningPanels() {
  document.querySelectorAll("[data-floating-tuning-panel]").forEach((panel) => {
    panel.hidden = true;
  });
}

async function openSettingsPanel() {
  if (!fields.settingsPanel) return;
  await loadAppSettings();
  populateSettingsForm();
  fields.settingsPanel.hidden = false;
  restoreFloatingWindowPosition(fields.settingsPanel);
  closeGotoPanel();
  addLog("message", "Opened system settings");
  fields.settingsAzimuthSerial?.focus();
}

function closeSettingsPanel() {
  if (fields.settingsPanel) fields.settingsPanel.hidden = true;
}

function populateSettingsForm() {
  updatePageTitle();
  populateDriveSerialOptions();
  const station = appSettings.station || {};
  if (fields.settingsStationName) fields.settingsStationName.value = station.name || "";
  setInputNumber(fields.settingsLatitude, station.latitude);
  setInputNumber(fields.settingsLongitude, station.longitude);
  const limits = appSettings.motion_limits || {};
  setInputNumber(fields.settingsAzimuthCcwLimit, limits.azimuth_ccw_limit_deg);
  setInputNumber(fields.settingsAzimuthCwLimit, limits.azimuth_cw_limit_deg);
  setInputNumber(fields.settingsAzimuthOffset, limits.azimuth_position_offset_deg);
  setInputNumber(fields.settingsAzimuthCurrentLimit, limits.azimuth_current_limit_amp);
  setInputNumber(fields.settingsAltitudeUpperLimit, limits.altitude_upper_limit_deg);
  setInputNumber(fields.settingsAltitudeLowerLimit, limits.altitude_lower_limit_deg);
  setInputNumber(fields.settingsAltitudeOffset, limits.altitude_position_offset_deg);
  setInputNumber(fields.settingsAltitudeCurrentLimit, limits.altitude_current_limit_amp);
  setInputNumber(fields.settingsSlewRate, limits.slew_rate_deg_per_sec);
}

function updatePageTitle() {
  const stationName = String(appSettings.station?.name || "").trim();
  const title = stationName ? `Fire Detector Mount (${stationName})` : "Fire Detector Mount";
  if (fields.pageTitle) fields.pageTitle.textContent = title;
  document.title = title;
}

function populateDriveSerialOptions() {
  const select = fields.settingsAzimuthSerial;
  if (!select) return;
  const previous = select.value || appSettings.drive_serials?.azimuth_serial || "";
  const serials = availableDriveSerials();
  select.replaceChildren();

  if (serials.length === 0) {
    const option = new Option("No drives detected", "");
    select.append(option);
    select.disabled = true;
  } else {
    select.disabled = false;
    serials.forEach((serial) => select.append(new Option(serial, serial)));
    if (previous && !serials.includes(previous)) {
      select.append(new Option(`${previous} (saved, not detected)`, previous));
    }
    select.value = previous && [...select.options].some((option) => option.value === previous)
      ? previous
      : serials[0];
  }
  updateSerialMapPreview();
}

function availableDriveSerials() {
  const serials = new Set();
  ["azimuth_serial", "altitude_serial"].forEach((key) => {
    const serial = appSettings.drive_serials?.[key];
    if (serial !== null && serial !== undefined && serial !== "") serials.add(String(serial));
  });
  if (Array.isArray(latestStatus?.device_serials)) {
    latestStatus.device_serials.forEach((serial) => {
      if (serial !== null && serial !== undefined && serial !== "") serials.add(String(serial));
    });
  }
  if (Array.isArray(latestStatus?.axes)) {
    latestStatus.axes.forEach((axis) => {
      if (axis.drive_serial !== null && axis.drive_serial !== undefined && axis.drive_serial !== "") {
        serials.add(String(axis.drive_serial));
      }
    });
  }
  return [...serials];
}

function updateSerialMapPreview() {
  const selectedAzimuth = fields.settingsAzimuthSerial?.value || "";
  const serials = availableDriveSerials();
  const altitude = serials.find((serial) => serial !== selectedAzimuth)
    || appSettings.drive_serials?.altitude_serial
    || "";
  if (fields.settingsAzimuthSerialView) {
    setSerialBadge(fields.settingsAzimuthSerialView, selectedAzimuth);
  }
  if (fields.settingsAltitudeSerialView) {
    setSerialBadge(fields.settingsAltitudeSerialView, altitude);
  }
}

function setSerialBadge(element, serial) {
  const value = serial || "--";
  element.textContent = value;
  element.title = value === "--" ? "No drive serial selected" : `Drive serial ${value}`;
}

function settingsPayloadFromForm() {
  return {
    station: {
      name: fields.settingsStationName?.value || "",
      latitude: fields.settingsLatitude?.value || null,
      longitude: fields.settingsLongitude?.value || null,
    },
    drive_serials: {
      azimuth_serial: fields.settingsAzimuthSerial?.value || null,
      available_serials: availableDriveSerials(),
    },
    motion_limits: {
      azimuth_ccw_limit_deg: fields.settingsAzimuthCcwLimit?.value || null,
      azimuth_cw_limit_deg: fields.settingsAzimuthCwLimit?.value || null,
      azimuth_position_offset_deg: fields.settingsAzimuthOffset?.value || null,
      azimuth_current_limit_amp: fields.settingsAzimuthCurrentLimit?.value || null,
      altitude_upper_limit_deg: fields.settingsAltitudeUpperLimit?.value || null,
      altitude_lower_limit_deg: fields.settingsAltitudeLowerLimit?.value || null,
      altitude_position_offset_deg: fields.settingsAltitudeOffset?.value || null,
      altitude_current_limit_amp: fields.settingsAltitudeCurrentLimit?.value || null,
      slew_rate_deg_per_sec: fields.settingsSlewRate?.value || null,
    },
  };
}

function activateSettingsTab(tabName) {
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    const active = button.dataset.settingsTab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-settings-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.settingsPanel === tabName);
  });
}

async function saveSystemSettings() {
  addLog("warning", "Stopping motion and disabling both axes before saving settings");
  addLog("message", "Saving system settings");
  if (fields.settingsSave) fields.settingsSave.disabled = true;
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settingsPayloadFromForm()),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Settings update failed.");
    }
    appSettings = data.settings;
    populateSettingsForm();
    updatePageTitle();
    addLog("message", "System settings saved");
    logDriveFlashResult(data.drive_flash);
    await refreshStatus();
    if (hasDriveFlash(data.drive_flash)) {
      addLog("success", "Drive flash completed and the system is ready.");
    }
  } catch (error) {
    addLog("error", `System settings save failed: ${error.message}`);
  } finally {
    if (fields.settingsSave) fields.settingsSave.disabled = false;
  }
}

function hasDriveFlash(result) {
  return Array.isArray(result?.flashed) && result.flashed.length > 0;
}

function logDriveFlashResult(result) {
  if (!result) return;
  const flashed = Array.isArray(result.flashed) ? result.flashed : [];
  if (flashed.length > 0) {
    flashed.forEach((item) => {
      addLog(
        "message",
        `${item.axis} drive limits flashed to serial ${item.serial || "--"}${item.current_limit_amp ? `, current limit ${formatNumber(item.current_limit_amp)} Amp` : ""}`,
      );
    });
  }
  if (Array.isArray(result.warnings)) {
    result.warnings.forEach((warning) => addLog("warning", warning));
  }
}

async function resetMountServer() {
  const button = fields.settingsReloadSerials;
  if (button) button.disabled = true;
  addLog("warning", "Resetting mount server and reconnecting hardware");
  try {
    const response = await fetch("/api/system/reset", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Mount server reset failed.");
    }
    addLog("message", data.message || "Mount server reset requested");
    await waitForMountServer();
    addLog("success", "Mount server and drives are online again.");
    await loadAppSettings();
    await refreshStatus();
  } catch (error) {
    addLog("error", `Mount server reset failed: ${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

async function waitForMountServer() {
  await delay(900);
  let lastError = "Mount server did not come back online in time.";
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (response.ok) {
        const data = await response.json();
        if (data.connected) return;
        lastError = data.error || "Mount server is online, but drives are not connected yet.";
      }
    } catch (error) {
      // The Flask process is expected to be down briefly while systemd restarts it.
    }
    await delay(500);
  }
  throw new Error(lastError);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function fillGotoFromActual() {
  const axisMap = axesByLabel();
  setInputNumber(fields.gotoAzimuth, axisMap.Azimuth?.position_deg);
  setInputNumber(fields.gotoAltitude, axisMap.Altitude?.position_deg);
  addLog("message", "Loaded actual positions into Goto targets");
}

function fillSkyGotoFromActual() {
  const axisMap = axesByLabel();
  setInputNumber(fields.skyGotoAzimuth, axisMap.Azimuth?.position_deg);
  setInputNumber(fields.skyGotoAltitude, axisMap.Altitude?.position_deg);
  updateSkyTargetFromInputs();
  addLog("message", "Loaded actual positions into Horizon View targets");
}

function fillSkyGotoFromMapClick(event) {
  const target = skyTargetFromPointerEvent(event);
  if (!target) return;
  selectedSkyTarget = target;
  if (fields.skyGotoAzimuth) fields.skyGotoAzimuth.value = target.azimuth.toFixed(2);
  if (fields.skyGotoAltitude) fields.skyGotoAltitude.value = target.altitude.toFixed(2);
  setSkyTargetMessage("", "");
  renderSkySphere(latestStatus);
  addLog("message", `Horizon map target selected: Azimuth ${target.azimuth.toFixed(2)} Deg, Altitude ${target.altitude.toFixed(2)} Deg`);
}

function updateSkyTargetFromInputs() {
  const azimuth = toNumber(fields.skyGotoAzimuth?.value);
  const altitude = toNumber(fields.skyGotoAltitude?.value);
  if (azimuth === null || altitude === null) {
    selectedSkyTarget = null;
    setSkyTargetMessage("Enter both target angles to show the map target.", "is-error");
    renderSkySphere(latestStatus);
    return;
  }

  selectedSkyTarget = { azimuth, altitude };
  updateSkyTargetMessageForAltitude(altitude);
  renderSkySphere(latestStatus);
}

function updateSkyTargetMessageForAltitude(altitude) {
  const minAltitude = skyVisibleMinimumAltitude();
  const maxAltitude = skyVisibleMaximumAltitude();
  if (altitude < minAltitude || altitude > maxAltitude) {
    setSkyTargetMessage(`Target altitude is outside map range and is shown at the nearest edge (${formatNumber(Math.max(minAltitude, Math.min(maxAltitude, altitude)))} Deg).`, "is-warning");
    return;
  }
  setSkyTargetMessage("", "");
}

function setSkyTargetMessage(message, className) {
  if (!fields.skyTargetMessage) return;
  fields.skyTargetMessage.classList.remove("is-warning", "is-error");
  if (className) fields.skyTargetMessage.classList.add(className);
  fields.skyTargetMessage.textContent = message;
}

function skyTargetFromPointerEvent(event) {
  const canvas = fields.skySphereCanvas;
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const size = Math.min(rect.width, rect.height);
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const radius = size * 0.42;
  const dx = event.clientX - cx;
  const dy = event.clientY - cy;
  const distance = Math.hypot(dx, dy);
  if (!skyPointerWithinMotionArea(distance, dx, dy, radius)) return null;

  const azimuth = normalizeDegrees((Math.atan2(dx, -dy) * 180) / Math.PI);
  return {
    azimuth,
    altitude: skyAltitudeFromRadius(distance, radius),
  };
}

function skyPointerWithinMotionArea(distance, dx, dy, radius) {
  const limits = appSettings.motion_limits || {};
  const lowerLimit = toNumber(limits.altitude_lower_limit_deg);
  const upperLimit = toNumber(limits.altitude_upper_limit_deg);
  const lowerAltitude = lowerLimit === null ? skyVisibleMinimumAltitude() : lowerLimit;
  const upperAltitude = upperLimit === null ? skyVisibleMaximumAltitude() : upperLimit;
  const innerRadius = skyAltitudeRadius(Math.max(skyVisibleMinimumAltitude(), Math.min(skyVisibleMaximumAltitude(), upperAltitude)), radius);
  const outerRadius = skyAltitudeRadius(Math.max(skyVisibleMinimumAltitude(), Math.min(skyVisibleMaximumAltitude(), lowerAltitude)), radius);
  const hitPadding = 2;
  if (distance < innerRadius - hitPadding || distance > outerRadius + hitPadding) {
    return false;
  }

  const ccwLimit = toNumber(limits.azimuth_ccw_limit_deg);
  const cwLimit = toNumber(limits.azimuth_cw_limit_deg);
  if (ccwLimit === null && cwLimit === null) return true;
  const azimuth = normalizeDegrees((Math.atan2(dx, -dy) * 180) / Math.PI);
  return skyAzimuthWithinLimitSweep(azimuth, cwLimit) || skyAzimuthWithinLimitSweep(azimuth, ccwLimit);
}

function skyAzimuthWithinLimitSweep(azimuth, limit) {
  if (limit === null) return false;
  const signedAzimuth = azimuth > 180 ? azimuth - 360 : azimuth;
  if (limit >= 0) {
    return azimuth >= -0.0001 && azimuth <= normalizeDegrees(limit) + 0.0001;
  }
  return signedAzimuth >= limit - 0.0001 && signedAzimuth <= 0.0001;
}

function skyAltitudeFromRadius(distance, radius) {
  const visibleMinAltitude = skyVisibleMinimumAltitude();
  const visibleMaxAltitude = skyVisibleMaximumAltitude();
  const outerGapRatio = 0.08;
  const normalized = Math.max(0, Math.min(1, distance / radius));
  const progress = 1 - ((normalized - outerGapRatio) / (1 - outerGapRatio));
  const altitude = visibleMinAltitude + progress * (visibleMaxAltitude - visibleMinAltitude);
  return Math.max(visibleMinAltitude, Math.min(visibleMaxAltitude, altitude));
}

function axesByLabel() {
  const axes = Array.isArray(latestStatus?.axes) ? latestStatus.axes : [];
  return Object.fromEntries(axes.map((axis) => [axis.label, axis]));
}

function setInputNumber(input, value) {
  if (!input) return;
  const number = toNumber(value);
  input.value = number === null ? "" : number.toFixed(3);
}

function gotoPayloadFromForm() {
  return {
    Azimuth: fields.gotoAzimuth?.value || "",
    Altitude: fields.gotoAltitude?.value || "",
  };
}

function velocityPayloadFromForm() {
  return {
    Azimuth: fields.velocityAzimuth?.value || "",
    Altitude: fields.velocityAltitude?.value || "",
  };
}

function skyGotoPayloadFromForm() {
  return {
    Azimuth: fields.skyGotoAzimuth?.value || "",
    Altitude: fields.skyGotoAltitude?.value || "",
    velocity_target_deg_per_sec: fields.skyGotoVelocity?.value || "",
  };
}

function skyVelocityPayloadFromForm() {
  return {
    Azimuth: fields.skyVelocityAzimuth?.value || "",
    Altitude: fields.skyVelocityAltitude?.value || "",
  };
}

function zeroVelocityInputs() {
  if (fields.velocityAzimuth) fields.velocityAzimuth.value = "0";
  if (fields.velocityAltitude) fields.velocityAltitude.value = "0";
  addLog("message", "Velocity targets set to zero");
}

function zeroSkyVelocityInputs() {
  if (fields.skyVelocityAzimuth) fields.skyVelocityAzimuth.value = "0";
  if (fields.skyVelocityAltitude) fields.skyVelocityAltitude.value = "0";
  addLog("message", "Horizon View velocity targets set to zero");
}

function axisPayload(axis, value) {
  return { [axis]: value };
}

function axisFormValue(form, fieldName) {
  return form?.elements?.[fieldName]?.value || "";
}

function axisJogVelocity(form, direction) {
  if (direction === "stop") return "0";
  const speed = toNumber(axisFormValue(form, "jog_velocity"));
  if (speed === null || speed <= 0) {
    throw new Error("Jog speed must be greater than 0.");
  }
  return String(direction === "backward" ? -speed : speed);
}

function activateGotoTab(tabName) {
  document.querySelectorAll("[data-goto-tab]").forEach((button) => {
    const active = button.dataset.gotoTab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-goto-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.gotoPanel === tabName);
  });
  addLog("message", `Motor command tab changed to ${tabName === "velocity" ? "Velocity Control" : "Goto Position"}`);
}

function tuningPayloadFromForm(form) {
  const payload = {};
  tuningBindings.forEach(([, fieldName]) => {
    payload[fieldName] = form.elements[fieldName].value;
  });
  return payload;
}

function setTuningMessage(ui, message, className) {
  const messages = new Set([
    ui?.tuningMessage,
    ...document.querySelectorAll(`[data-tuning-message="${axisLabelForUi(ui)}"]`),
  ]);
  messages.forEach((element) => {
    if (!element) return;
    element.classList.remove("is-ok", "is-error");
    if (className) element.classList.add(className);
    element.textContent = message;
  });
}

function axisLabelForUi(ui) {
  return Object.entries(axisFields).find(([, fieldsForAxis]) => fieldsForAxis === ui)?.[0] || "";
}

async function loadAppSettings() {
  try {
    const response = await fetch("/api/settings", { cache: "no-store" });
    appSettings = await response.json();
    updatePageTitle();
    applyTuningSteps();
    if (fields.settingsPanel && !fields.settingsPanel.hidden) populateSettingsForm();
  } catch (error) {
    appSettings = {
      tuning_steps: { Azimuth: {}, Altitude: {} },
      drive_serials: { azimuth_serial: null, altitude_serial: null },
      station: { name: "", latitude: null, longitude: null },
      motion_limits: {},
    };
    updatePageTitle();
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
  restoreFloatingWindowPosition(panel, { left: event.clientX, top: event.clientY });
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

buildFloatingTuningForms();

document.querySelectorAll("[data-tab-button]").forEach((button) => {
  button.addEventListener("click", () => {
    const axis = button.dataset.tabButton;
    const target = button.dataset.tabTarget;
    addLog("message", `${axis} tab changed to ${button.textContent.trim()}`);
    document.querySelectorAll(`[data-tab-button="${axis}"]`).forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    document.querySelectorAll(`[data-tab-panel="${axis}"]`).forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.tabName === target);
    });
  });

  button.addEventListener("contextmenu", (event) => {
    if (button.dataset.tabTarget !== "tuning") return;
    event.preventDefault();
    openFloatingTuningPanel(button.dataset.tabButton, event);
  });
});

if (fields.refreshBtn) {
  fields.refreshBtn.addEventListener("click", refreshStatus);
}

Object.entries(axisFields).forEach(([label, ui]) => {
  ui.plotSelect?.addEventListener("change", () => {
    addLog("message", `${label} chart changed to ${ui.plotSelect.value}`);
    drawChart(label, new Date());
  });
});

document.querySelectorAll("[data-view-mode]").forEach((button) => {
  button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
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
      syncMatchingTuningInputs(input);
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
document.querySelectorAll("[data-close-floating-tuning]").forEach((button) => {
  button.addEventListener("click", () => closeFloatingTuningPanel(button.dataset.closeFloatingTuning));
});
fields.motorToggle?.addEventListener("click", () => {
  const allArmed = Array.isArray(latestStatus?.axes)
    && latestStatus.axes.length >= 2
    && latestStatus.axes.every((axis) => axis.available && axis.is_armed);
  sendMotorCommand(allArmed ? "disable" : "enable");
});

fields.motorStop?.addEventListener("click", () => {
  sendMotorCommand("stop");
});

fields.skyStop?.addEventListener("click", () => {
  sendMotorCommand("stop");
});

fields.motorGoto?.addEventListener("click", openGotoPanel);
fields.systemSetting?.addEventListener("click", openSettingsPanel);
fields.gotoClose?.addEventListener("click", closeGotoPanel);
fields.gotoUseActual?.addEventListener("click", fillGotoFromActual);
fields.gotoForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMotorCommand("goto", gotoPayloadFromForm());
});
fields.velocityZero?.addEventListener("click", zeroVelocityInputs);
fields.velocityForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMotorCommand("velocity", velocityPayloadFromForm());
});
fields.skyGotoUseActual?.addEventListener("click", fillSkyGotoFromActual);
fields.skySphereCanvas?.addEventListener("click", fillSkyGotoFromMapClick);
[fields.skyGotoAzimuth, fields.skyGotoAltitude].forEach((input) => {
  input?.addEventListener("input", updateSkyTargetFromInputs);
  input?.addEventListener("change", updateSkyTargetFromInputs);
});
fields.skyGotoForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMotorCommand("goto", skyGotoPayloadFromForm());
});
fields.skyVelocityZero?.addEventListener("click", zeroSkyVelocityInputs);
fields.skyVelocityForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMotorCommand("velocity", skyVelocityPayloadFromForm());
});

document.querySelectorAll("[data-goto-tab]").forEach((button) => {
  button.addEventListener("click", () => activateGotoTab(button.dataset.gotoTab));
});

document.querySelectorAll("[data-axis-control]").forEach((form) => {
  const axis = form.dataset.axisControl;
  form.querySelectorAll("[data-axis-action]").forEach((button) => {
    button.addEventListener("click", () => {
      sendAxisMotorCommand(axis, button.dataset.axisAction, null, form);
    });
  });

  form.querySelectorAll("[data-axis-jog]").forEach((button) => {
    button.addEventListener("click", () => {
      try {
        const velocity = axisJogVelocity(form, button.dataset.axisJog);
        sendAxisMotorCommand(axis, "velocity", axisPayload(axis, velocity), form);
      } catch (error) {
        setAxisControlMessage(form, error.message, "is-error");
      }
    });
  });

  form.querySelectorAll("[data-axis-goto]").forEach((button) => {
    button.addEventListener("click", () => {
      const mode = button.dataset.axisGoto;
      const fieldName = mode === "position" ? "position_target" : "velocity_target";
      const value = axisFormValue(form, fieldName);
      if (value === "") {
        setAxisControlMessage(form, `${mode === "position" ? "Position" : "Velocity"} target is required.`, "is-error");
        return;
      }
      sendAxisMotorCommand(axis, mode === "position" ? "goto" : "velocity", axisPayload(axis, value), form);
    });
  });
});

document.querySelectorAll("[data-settings-tab]").forEach((button) => {
  button.addEventListener("click", () => activateSettingsTab(button.dataset.settingsTab));
});

fields.settingsClose?.addEventListener("click", closeSettingsPanel);
fields.settingsReloadSerials?.addEventListener("click", resetMountServer);
fields.settingsAzimuthSerial?.addEventListener("change", updateSerialMapPreview);
fields.settingsForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  saveSystemSettings();
});

document.addEventListener("pointerdown", (event) => {
  if (!fields.tuningStepPanel || fields.tuningStepPanel.hidden) return;
  if (fields.tuningStepPanel.contains(event.target)) return;
  closeStepPanel();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeStepPanel();
    closeGotoPanel();
    closeSettingsPanel();
    closeFloatingTuningPanels();
  }
});

window.addEventListener("resize", () => {
  document.querySelectorAll("[data-floating-window]:not([hidden])").forEach((panel) => {
    const rect = panel.getBoundingClientRect();
    setFloatingWindowPosition(panel, rect.left, rect.top);
    saveFloatingWindowPosition(panel);
  });
  if (activeViewMode === "sky") renderSkySphere(latestStatus);
});

initializeFloatingWindows();
setViewMode(activeViewMode, { persist: false });
loadAppSettings();
addLog("message", "Page loaded successfully. Fire Detector dashboard is ready.");
refreshStatus();
setInterval(refreshStatus, 25);
