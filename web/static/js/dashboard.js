const fields = {
  pageTitle: document.getElementById("pageTitle"),
  stationTitle: document.getElementById("stationTitle"),
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
  updateProgress: document.getElementById("updateProgress"),
  updateProgressTitle: document.getElementById("updateProgressTitle"),
  updateProgressDetail: document.getElementById("updateProgressDetail"),
  updateProgressBar: document.getElementById("updateProgressBar"),
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
  azimuthAutoTunePanel: document.getElementById("azimuthAutoTunePanel"),
  azimuthAutoTuneClose: document.getElementById("azimuthAutoTuneClose"),
  azimuthAutoTuneForm: document.getElementById("azimuthAutoTuneForm"),
  azimuthAutoTuneMin: document.getElementById("azimuthAutoTuneMin"),
  azimuthAutoTuneMax: document.getElementById("azimuthAutoTuneMax"),
  azimuthAutoTuneMinSpeed: document.getElementById("azimuthAutoTuneMinSpeed"),
  azimuthAutoTuneMaxSpeed: document.getElementById("azimuthAutoTuneMaxSpeed"),
  azimuthAutoTuneCycles: document.getElementById("azimuthAutoTuneCycles"),
  azimuthAutoTuneSettleError: document.getElementById("azimuthAutoTuneSettleError"),
  azimuthAutoTuneSettleVelocity: document.getElementById("azimuthAutoTuneSettleVelocity"),
  azimuthAutoTuneMinStepTime: document.getElementById("azimuthAutoTuneMinStepTime"),
  azimuthAutoTuneMinTravel: document.getElementById("azimuthAutoTuneMinTravel"),
  azimuthAutoTuneMaxProfiles: document.getElementById("azimuthAutoTuneMaxProfiles"),
  azimuthAutoTuneFailLimit: document.getElementById("azimuthAutoTuneFailLimit"),
  azimuthAutoTuneStart: document.getElementById("azimuthAutoTuneStart"),
  azimuthAutoTuneMessage: document.getElementById("azimuthAutoTuneMessage"),
  azimuthAutoTuneProgress: document.getElementById("azimuthAutoTuneProgress"),
  azimuthAutoTuneProgressBar: document.getElementById("azimuthAutoTuneProgressBar"),
  azimuthAutoTuneResultBody: document.getElementById("azimuthAutoTuneResultBody"),
  azimuthAutoTuneStepLogEntries: document.getElementById("azimuthAutoTuneStepLogEntries"),
  altitudeAutoTunePanel: document.getElementById("altitudeAutoTunePanel"),
  altitudeAutoTuneClose: document.getElementById("altitudeAutoTuneClose"),
  altitudeAutoTuneForm: document.getElementById("altitudeAutoTuneForm"),
  altitudeAutoTuneMin: document.getElementById("altitudeAutoTuneMin"),
  altitudeAutoTuneMax: document.getElementById("altitudeAutoTuneMax"),
  altitudeAutoTuneMinSpeed: document.getElementById("altitudeAutoTuneMinSpeed"),
  altitudeAutoTuneMaxSpeed: document.getElementById("altitudeAutoTuneMaxSpeed"),
  altitudeAutoTuneCycles: document.getElementById("altitudeAutoTuneCycles"),
  altitudeAutoTuneSettleError: document.getElementById("altitudeAutoTuneSettleError"),
  altitudeAutoTuneSettleVelocity: document.getElementById("altitudeAutoTuneSettleVelocity"),
  altitudeAutoTuneMinStepTime: document.getElementById("altitudeAutoTuneMinStepTime"),
  altitudeAutoTuneMinTravel: document.getElementById("altitudeAutoTuneMinTravel"),
  altitudeAutoTuneMaxProfiles: document.getElementById("altitudeAutoTuneMaxProfiles"),
  altitudeAutoTuneFailLimit: document.getElementById("altitudeAutoTuneFailLimit"),
  altitudeAutoTuneStart: document.getElementById("altitudeAutoTuneStart"),
  altitudeAutoTuneMessage: document.getElementById("altitudeAutoTuneMessage"),
  altitudeAutoTuneProgress: document.getElementById("altitudeAutoTuneProgress"),
  altitudeAutoTuneProgressBar: document.getElementById("altitudeAutoTuneProgressBar"),
  altitudeAutoTuneResultBody: document.getElementById("altitudeAutoTuneResultBody"),
  altitudeAutoTuneStepLogEntries: document.getElementById("altitudeAutoTuneStepLogEntries"),
  settingsPanel: document.getElementById("settingsPanel"),
  settingsClose: document.getElementById("settingsClose"),
  settingsForm: document.getElementById("settingsForm"),
  settingsStationName: document.getElementById("settingsStationName"),
  settingsLatitude: document.getElementById("settingsLatitude"),
  settingsLongitude: document.getElementById("settingsLongitude"),
  settingsStationElevation: document.getElementById("settingsStationElevation"),
  settingsAzimuthSerial: document.getElementById("settingsAzimuthSerial"),
  settingsAzimuthSerialView: document.getElementById("settingsAzimuthSerialView"),
  settingsAltitudeSerialView: document.getElementById("settingsAltitudeSerialView"),
  settingsFirmwareVersionView: document.getElementById("settingsFirmwareVersionView"),
  settingsAzimuthCcwLimit: document.getElementById("settingsAzimuthCcwLimit"),
  settingsAzimuthCwLimit: document.getElementById("settingsAzimuthCwLimit"),
  settingsAzimuthOffset: document.getElementById("settingsAzimuthOffset"),
  settingsAzimuthCurrentLimit: document.getElementById("settingsAzimuthCurrentLimit"),
  settingsAltitudeUpperLimit: document.getElementById("settingsAltitudeUpperLimit"),
  settingsAltitudeLowerLimit: document.getElementById("settingsAltitudeLowerLimit"),
  settingsAltitudeOffset: document.getElementById("settingsAltitudeOffset"),
  settingsAltitudeCurrentLimit: document.getElementById("settingsAltitudeCurrentLimit"),
  settingsSlewRate: document.getElementById("settingsSlewRate"),
  settingsDeviceId: document.getElementById("settingsDeviceId"),
  settingsUpdateInterval: document.getElementById("settingsUpdateInterval"),
  settingsUpdateChannel: document.getElementById("settingsUpdateChannel"),
  settingsAutoUpdate: document.getElementById("settingsAutoUpdate"),
  systemFirmwareVersion: document.getElementById("systemFirmwareVersion"),
  systemGitBranch: document.getElementById("systemGitBranch"),
  systemLastUpdateCheck: document.getElementById("systemLastUpdateCheck"),
  systemUpdateStatus: document.getElementById("systemUpdateStatus"),
  systemUpdateCheck: document.getElementById("systemUpdateCheck"),
  systemUpdateMessage: document.getElementById("systemUpdateMessage"),
  settingsReloadSerials: document.getElementById("settingsReloadSerials"),
  settingsSave: document.getElementById("settingsSave"),
  azimuthCcwSensor: document.getElementById("azimuthCcwSensor"),
  azimuthCwSensor: document.getElementById("azimuthCwSensor"),
  axisView: document.getElementById("axisView"),
  skyView: document.getElementById("skyView"),
  skySphereCanvas: document.getElementById("skySphereCanvas"),
  pointingView: document.getElementById("pointingView"),
  pointingMapCanvas: document.getElementById("pointingMapCanvas"),
  pointingMapProgress: document.getElementById("pointingMapProgress"),
  pointingProgressTitle: document.getElementById("pointingProgressTitle"),
  pointingProgressDetail: document.getElementById("pointingProgressDetail"),
  pointingLayerSatellite: document.getElementById("pointingLayerSatellite"),
  pointingLayerTerrain: document.getElementById("pointingLayerTerrain"),
  pointingLayerVisibility: document.getElementById("pointingLayerVisibility"),
  pointingLayerGrid: document.getElementById("pointingLayerGrid"),
  pointingImageryAttribution: document.getElementById("pointingImageryAttribution"),
  pointingMapSubtitle: document.getElementById("pointingMapSubtitle"),
  pointingStationValue: document.getElementById("pointingStationValue"),
  pointingRangeValue: document.getElementById("pointingRangeValue"),
  pointingDemValue: document.getElementById("pointingDemValue"),
  pointingSelectionTitle: document.getElementById("pointingSelectionTitle"),
  pointingDistanceValue: document.getElementById("pointingDistanceValue"),
  pointingAzimuthValue: document.getElementById("pointingAzimuthValue"),
  pointingElevationValue: document.getElementById("pointingElevationValue"),
  pointingAltitudeValue: document.getElementById("pointingAltitudeValue"),
  pointingVisibilityValue: document.getElementById("pointingVisibilityValue"),
  pointingBlockerValue: document.getElementById("pointingBlockerValue"),
  pointingCoordinateValue: document.getElementById("pointingCoordinateValue"),
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
    torqueSoftMin: document.getElementById("azimuthTorqueSoftMin"),
    torqueSoftMax: document.getElementById("azimuthTorqueSoftMax"),
    spinoutElectricalPowerThreshold: document.getElementById("azimuthSpinoutElectricalPowerThreshold"),
    spinoutMechanicalPowerThreshold: document.getElementById("azimuthSpinoutMechanicalPowerThreshold"),
    spinoutElectricalPowerBandwidth: document.getElementById("azimuthSpinoutElectricalPowerBandwidth"),
    spinoutMechanicalPowerBandwidth: document.getElementById("azimuthSpinoutMechanicalPowerBandwidth"),
    inputFilterBandwidth: document.getElementById("azimuthInputFilterBandwidth"),
    inertia: document.getElementById("azimuthInertia"),
    trapVelocityLimit: document.getElementById("azimuthTrapVelocityLimit"),
    trapAccelLimit: document.getElementById("azimuthTrapAccelLimit"),
    trapDecelLimit: document.getElementById("azimuthTrapDecelLimit"),
    tuningMessage: document.getElementById("azimuthTuningMessage"),
    chartValue: document.getElementById("azimuthChartValue"),
    motionStatus: document.getElementById("azimuthMotionStatus"),
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
    torqueSoftMin: document.getElementById("altitudeTorqueSoftMin"),
    torqueSoftMax: document.getElementById("altitudeTorqueSoftMax"),
    spinoutElectricalPowerThreshold: document.getElementById("altitudeSpinoutElectricalPowerThreshold"),
    spinoutMechanicalPowerThreshold: document.getElementById("altitudeSpinoutMechanicalPowerThreshold"),
    spinoutElectricalPowerBandwidth: document.getElementById("altitudeSpinoutElectricalPowerBandwidth"),
    spinoutMechanicalPowerBandwidth: document.getElementById("altitudeSpinoutMechanicalPowerBandwidth"),
    inputFilterBandwidth: document.getElementById("altitudeInputFilterBandwidth"),
    inertia: document.getElementById("altitudeInertia"),
    trapVelocityLimit: document.getElementById("altitudeTrapVelocityLimit"),
    trapAccelLimit: document.getElementById("altitudeTrapAccelLimit"),
    trapDecelLimit: document.getElementById("altitudeTrapDecelLimit"),
    tuningMessage: document.getElementById("altitudeTuningMessage"),
    chartValue: document.getElementById("altitudeChartValue"),
    motionStatus: document.getElementById("altitudeMotionStatus"),
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
const STATUS_FALLBACK_REFRESH_MS = 500;
const STATUS_WS_RECONNECT_MS = 1200;
const JOG_COMMAND_INTERVAL_MS = 250;
const POSITION_REACHED_TOLERANCE_DEG = 0.2;
const VELOCITY_REACHED_TOLERANCE_DEG_PER_SEC = 0.2;
let refreshInFlight = false;
let statusSocket = null;
let statusFallbackTimer = null;
let statusReconnectTimer = null;
let statusStreamConnected = false;
let lastServerStartedAt = null;
const activeAxisJogs = new Map();
const lastDriveErrorLogKeys = new Map();
let driveErrorEventsSupported = false;
let lastDriveErrorEventId = 0;

const seriesConfig = {
  position: { key: "position", setpointKey: "positionSetpoint", color: "#63c978", setpointColor: "#ff5548", unit: "Deg" },
  velocity: { key: "velocity", setpointKey: "velocitySetpoint", color: "#ff8a2f", setpointColor: "#56b6c2", unit: "Deg/Sec" },
  current: { key: "current", setpointKey: "currentSetpoint", color: "#56b6c2", setpointColor: "#ff5548", unit: "Amp" },
};

const odriveErrorBits = {
  0x00000001: "INITIALIZING",
  0x00000002: "SYSTEM_LEVEL",
  0x00000004: "TIMING_ERROR",
  0x00000008: "MISSING_ESTIMATE",
  0x00000010: "BAD_CONFIG",
  0x00000020: "DRV_FAULT",
  0x00000040: "MISSING_INPUT",
  0x00000100: "DC_BUS_OVER_VOLTAGE",
  0x00000200: "DC_BUS_UNDER_VOLTAGE",
  0x00000400: "DC_BUS_OVER_CURRENT",
  0x00000800: "DC_BUS_OVER_REGEN_CURRENT",
  0x00001000: "CURRENT_LIMIT_VIOLATION",
  0x00002000: "MOTOR_OVER_TEMP",
  0x00004000: "INVERTER_OVER_TEMP",
  0x00008000: "VELOCITY_LIMIT_VIOLATION",
  0x00010000: "POSITION_LIMIT_VIOLATION",
  0x00020000: "REQUESTED_CURRENT_TOO_HIGH",
  0x01000000: "WATCHDOG_TIMER_EXPIRED",
  0x02000000: "ESTOP_REQUESTED",
  0x04000000: "SPINOUT_DETECTED",
  0x08000000: "BRAKE_RESISTOR_DISARMED",
  0x10000000: "THERMISTOR_DISCONNECTED",
  0x40000000: "CALIBRATION_ERROR",
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
  ["torqueSoftMin", "torque_soft_min"],
  ["torqueSoftMax", "torque_soft_max"],
  ["spinoutElectricalPowerThreshold", "spinout_electrical_power_threshold"],
  ["spinoutMechanicalPowerThreshold", "spinout_mechanical_power_threshold"],
  ["spinoutElectricalPowerBandwidth", "spinout_electrical_power_bandwidth"],
  ["spinoutMechanicalPowerBandwidth", "spinout_mechanical_power_bandwidth"],
  ["inputFilterBandwidth", "input_filter_bandwidth"],
  ["inertia", "inertia"],
  ["trapVelocityLimit", "trap_velocity_limit"],
  ["trapAccelLimit", "trap_accel_limit"],
  ["trapDecelLimit", "trap_decel_limit"],
];

let appSettings = {
  tuning_steps: { Azimuth: {}, Altitude: {} },
  drive_serials: { azimuth_serial: null, altitude_serial: null },
  station: { name: "", latitude: null, longitude: null, elevation_above_ground_m: 0 },
  motion_limits: {},
  updater: { device_id: "", enabled: true, check_interval_minutes: 15, channel: "main" },
};
let activeStepTarget = null;
const autoApplyTimers = new WeakMap();
let settingsSaveTimer = null;
let latestStatus = null;
let motorCommandInFlight = false;
let logSequence = 0;
let selectedSkyTarget = null;
const pendingAutoTuneTuning = { Azimuth: null, Altitude: null };
let autoTuneRunState = {
  running: false,
  stopping: false,
};
let pointingModel = null;
let selectedPointingSample = null;
let pointingModelLoading = false;
const pointingRasterImages = new Map();
let updatePollTimer = null;
let lastUpdateStatusKey = "";
const floatingWindowStoragePrefix = "fireDetector.floatingWindow.";
const floatingWindowMargin = 12;
const viewModeStorageKey = "fireDetector.viewMode";
const autoTuneStoragePrefix = "fireDetector.autoTune.";
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
      issues.push(`active_errors=${valueOrDash(axis.active_errors)} (${formatDriveErrorBits(axis.active_errors)})`);
    }
    if (Number(axis.disarm_reason) > 0) {
      issues.push(`disarm_reason=${valueOrDash(axis.disarm_reason)} (${formatDriveErrorBits(axis.disarm_reason)})`);
    }
    if (axis.current_state !== 8) {
      issues.push(`state=${valueOrDash(axis.current_state)} expected=8`);
    }

    return [`${axis.label} enable warning: ${issues.join(", ")}.`];
  }
}

const driveEnableDiagnostics = new DriveEnableDiagnostics();

function readStoredViewMode() {
  const queryMode = new URLSearchParams(window.location.search).get("view");
  if (["axis", "sky", "pointing"].includes(queryMode)) return queryMode;
  try {
    const stored = localStorage.getItem(viewModeStorageKey);
    return ["axis", "sky", "pointing"].includes(stored) ? stored : "axis";
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

function statusWebSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/status`;
}

function stopStatusFallbackPolling() {
  if (!statusFallbackTimer) return;
  clearInterval(statusFallbackTimer);
  statusFallbackTimer = null;
}

function startStatusFallbackPolling() {
  if (statusFallbackTimer) return;
  refreshStatus();
  statusFallbackTimer = setInterval(refreshStatus, STATUS_FALLBACK_REFRESH_MS);
}

function scheduleStatusReconnect() {
  if (statusReconnectTimer) return;
  statusReconnectTimer = setTimeout(() => {
    statusReconnectTimer = null;
    connectStatusStream();
  }, STATUS_WS_RECONNECT_MS);
}

function connectStatusStream() {
  if (!("WebSocket" in window)) {
    startStatusFallbackPolling();
    return;
  }
  if (statusSocket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(statusSocket.readyState)) {
    return;
  }

  statusSocket = new WebSocket(statusWebSocketUrl());
  statusSocket.addEventListener("open", () => {
    statusStreamConnected = true;
    stopStatusFallbackPolling();
    addLog("message", "Telemetry stream connected.");
  });
  statusSocket.addEventListener("message", (event) => {
    try {
      renderStatus(JSON.parse(event.data));
    } catch (error) {
      addLog("error", `Telemetry stream payload invalid: ${error.message}`);
    }
  });
  statusSocket.addEventListener("close", () => {
    if (statusStreamConnected) {
      addLog("warning", "Telemetry stream disconnected; retrying.");
    }
    statusStreamConnected = false;
    startStatusFallbackPolling();
    scheduleStatusReconnect();
  });
  statusSocket.addEventListener("error", () => {
    statusSocket?.close();
  });
}

function renderStatus(data) {
  latestStatus = data;
  const timestamp = data.timestamp ? new Date(data.timestamp) : new Date();
  resetHistoryWhenServerRestarts(data.server_started_at);
  renderDriveErrorEvents(data.drive_error_events);
  renderAutoTuneProgress(data.auto_tune_progress);
  renderAutoTuneStepEvents(data.auto_tune_step_events);
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

function decodeDriveErrorBits(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return [];

  let remaining = Math.trunc(numeric);
  const names = [];
  Object.entries(odriveErrorBits).forEach(([bitText, name]) => {
    const bit = Number(bitText);
    if ((remaining & bit) === bit) {
      names.push(name);
      remaining &= ~bit;
    }
  });

  if (remaining > 0) {
    names.push(`UNKNOWN_BITS=0x${remaining.toString(16).toUpperCase()}`);
  }
  return names;
}

function formatDriveErrorBits(value) {
  const names = decodeDriveErrorBits(value);
  return names.length > 0 ? names.join(" + ") : "NONE";
}

function renderDriveErrorEvents(events) {
  if (!Array.isArray(events)) return;
  driveErrorEventsSupported = true;
  events
    .filter((event) => Number(event?.id) > lastDriveErrorEventId)
    .sort((a, b) => Number(a.id) - Number(b.id))
    .forEach((event) => {
      const id = Number(event.id);
      lastDriveErrorEventId = Math.max(lastDriveErrorEventId, id);
      const label = event.label || "Axis";
      const activeErrors = Number(event.active_errors) || 0;
      const disarmReason = Number(event.disarm_reason) || 0;
      const key = `${activeErrors}:${disarmReason}`;
      lastDriveErrorLogKeys.set(label, key);

      if (event.cleared || (activeErrors <= 0 && disarmReason <= 0)) {
        addLog("success", `${label} drive errors cleared.`);
        return;
      }

      const parts = [];
      if (activeErrors > 0) {
        parts.push(`active_errors=${activeErrors} (${formatDriveErrorBits(activeErrors)})`);
      }
      if (disarmReason > 0) {
        parts.push(`disarm_reason=${disarmReason} (${formatDriveErrorBits(disarmReason)})`);
      }
      addLog("error", `${label} drive event ${parts.join("; ")}.`);
    });
}

function logAxisDriveErrors(label, axis) {
  if (driveErrorEventsSupported) return;
  if (!axis?.available) {
    lastDriveErrorLogKeys.delete(label);
    return;
  }

  const activeErrors = Number(axis.active_errors) || 0;
  const disarmReason = Number(axis.disarm_reason) || 0;
  const key = `${activeErrors}:${disarmReason}`;
  const previousKey = lastDriveErrorLogKeys.get(label);
  if (previousKey === key) return;

  lastDriveErrorLogKeys.set(label, key);
  if (activeErrors <= 0 && disarmReason <= 0) {
    if (previousKey && previousKey !== "0:0") {
      addLog("success", `${label} drive errors cleared.`);
    }
    return;
  }

  const parts = [];
  if (activeErrors > 0) {
    parts.push(`active_errors=${activeErrors} (${formatDriveErrorBits(activeErrors)})`);
  }
  if (disarmReason > 0) {
    parts.push(`disarm_reason=${disarmReason} (${formatDriveErrorBits(disarmReason)})`);
  }
  addLog("error", `${label} drive reported ${parts.join("; ")}.`);
}

function resetHistoryWhenServerRestarts(serverStartedAt) {
  if (!serverStartedAt) return;
  if (lastServerStartedAt === null) {
    lastServerStartedAt = serverStartedAt;
    return;
  }
  if (lastServerStartedAt === serverStartedAt) return;
  lastServerStartedAt = serverStartedAt;
  history.Azimuth = [];
  history.Altitude = [];
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
    renderMotionStatus(ui.motionStatus, null);
    setAxisEnableMeter(ui.enableMeter, false, false);
    ui.card.classList.add("axis-missing");
    logAxisDriveErrors(label, null);
    pruneHistory(label, timestamp);
    drawChart(label, timestamp);
    return;
  }

  const sample = {
    timeMs: timestamp.getTime(),
    position: toNumber(axis.position_deg),
    positionSetpoint: axisPositionSetpoint(axis),
    velocity: toNumber(axis.velocity_deg_per_sec),
    velocitySetpoint: axisVelocitySetpoint(axis),
    current: toNumber(axis.current),
    currentSetpoint: toNumber(axis.current_setpoint),
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
  ui.errors.title = formatDriveErrorBits(axis.active_errors);
  ui.driveFaults.title = formatDriveErrorBits(axis.active_errors);
  ui.armed.title = Number(axis.disarm_reason) > 0
    ? `Disarm reason: ${formatDriveErrorBits(axis.disarm_reason)}`
    : "";
  setAxisEnableMeter(ui.enableMeter, Boolean(axis.is_armed), true);
  setTuningInputs(label, axis);
  renderActualReadouts(ui.chartValue, axis);
  renderMotionStatus(ui.motionStatus, axis);
  logAxisDriveErrors(label, axis);
  ui.card.classList.add("axis-ready");
  drawChart(label, timestamp);
}

function setAxisEnableMeter(element, enabled, available = true) {
  if (!element) return;
  element.classList.toggle("is-enabled", available && enabled);
  element.classList.toggle("is-disabled", !available || !enabled);
  element.setAttribute("aria-label", available && enabled ? "Axis enabled" : "Axis disabled");
}

function axisPositionSetpoint(axis) {
  const softwarePosition = axis?.software_position;
  if (softwarePosition?.active === true) {
    return toNumber(softwarePosition.target_deg);
  }
  if (Number(axis?.control_mode) === 2) {
    return null;
  }
  const rawSetpoint = toNumber(axis?.pos_setpoint) ?? toNumber(axis?.input_pos);
  if (rawSetpoint === null) return null;
  const offset = toNumber(axis?.position_offset_deg) ?? 0;
  return axis?.label === "Azimuth" ? rawSetpoint + offset : normalizeDegrees(rawSetpoint + offset);
}

function axisVelocitySetpoint(axis) {
  const sineTest = axis?.sine_velocity_test;
  if (sineTest?.active === true) {
    return toNumber(sineTest.command_velocity_deg_per_sec);
  }
  const softwarePosition = axis?.software_position;
  if (softwarePosition?.active === true) {
    return toNumber(softwarePosition.command_velocity_deg_per_sec);
  }
  return toNumber(axis?.input_vel) ?? toNumber(axis?.vel_setpoint);
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
  const actualValues = samples.map((sample) => sample[selected.key]).filter((value) => Number.isFinite(value));
  const setpointValues = samples.map((sample) => sample[selected.setpointKey]).filter((value) => Number.isFinite(value));
  const values = [...actualValues, ...setpointValues];

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

  drawChartSeries(ctx, samples, selected.setpointKey, selected.setpointColor, min, range, width, height, padLeft, padRight, padTop, padBottom, nowMs, {
    lineWidth: 2.8,
  });
  drawChartSeries(ctx, samples, selected.key, selected.color, min, range, width, height, padLeft, padRight, padTop, padBottom, nowMs, {
    dashed: false,
    lineWidth: 4,
  });
}

function drawChartSeries(ctx, samples, key, color, min, range, width, height, padLeft, padRight, padTop, padBottom, nowMs, options = {}) {
  ctx.beginPath();
  let lineStarted = false;
  samples.forEach((sample) => {
    const value = sample[key];
    if (!Number.isFinite(value)) return;
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
  if (!lineStarted) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = options.lineWidth || 4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.setLineDash([]);
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
  const azimuthDeg = toNumber(azimuth?.absolute_position_deg ?? azimuth?.position_deg);
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
      valueElement.textContent = `${formatSignedNumber(values[name])} ${config.unit}`;
    }
  });
}

function renderMotionStatus(element, axis) {
  if (!element) return;
  const state = axisMotionState(axis);
  const value = element.querySelector("em");
  if (value) value.textContent = state.label;
  element.title = state.detail;
  element.classList.remove("is-moving", "is-settling", "is-reached");
  if (state.className) element.classList.add(state.className);
}

function axisMotionState(axis) {
  if (!axis || !axis.available) {
    return { label: "--", className: "", detail: "Axis is not available." };
  }
  if (!axis.is_armed) {
    return { label: "Idle", className: "", detail: "Axis is not in closed loop." };
  }

  const sineTest = axis.sine_velocity_test;
  if (sineTest && sineTest.active === true) {
    const command = Math.abs(toNumber(sineTest.command_velocity_deg_per_sec) ?? 0);
    const amplitude = toNumber(sineTest.amplitude_deg_per_sec);
    const period = toNumber(sineTest.period_sec);
    return {
      label: "Sine Test",
      className: "is-moving",
      detail: `Random sine velocity test. Command ${formatNumber(command)} Deg/Sec, amplitude ${formatNumber(amplitude)} Deg/Sec, period ${formatNumber(period)} Sec.`,
    };
  }

  const velocity = Math.abs(toNumber(axis.velocity_deg_per_sec) ?? 0);
  const commandVelocity = Math.abs(toNumber(axis.input_vel) ?? 0);
  const setpointVelocity = Math.abs(toNumber(axis.vel_setpoint) ?? 0);
  const velocityMode = Number(axis.control_mode) === 2;
  const softwarePosition = axis.software_position;
  if (softwarePosition && typeof softwarePosition === "object") {
    const phase = softwarePosition.phase || "";
    const target = toNumber(softwarePosition.target_deg);
    const error = Math.abs(toNumber(softwarePosition.error_deg) ?? 0);
    if (softwarePosition.active === true || phase === "moving") {
      const softwareCommandVelocity = Math.abs(toNumber(softwarePosition.command_velocity_deg_per_sec) ?? 0);
      return {
        label: "Slewing",
        className: "is-moving",
        detail: `Python position loop to ${formatNumber(target)} Deg. Error ${formatNumber(error)} Deg, command ${formatNumber(softwareCommandVelocity)} Deg/Sec.`,
      };
    }
    if (phase === "reached") {
      return {
        label: "Reached",
        className: "is-reached",
        detail: `Python position loop reached target. Error ${formatNumber(error)} Deg.`,
      };
    }
    if (phase === "timeout") {
      return {
        label: "Settling",
        className: "is-settling",
        detail: `Python position loop timed out before reaching ${formatNumber(target)} Deg. Error ${formatNumber(error)} Deg.`,
      };
    }
  }

  if (velocityMode) {
    if (
      commandVelocity > VELOCITY_REACHED_TOLERANCE_DEG_PER_SEC
      || setpointVelocity > VELOCITY_REACHED_TOLERANCE_DEG_PER_SEC
      || velocity > VELOCITY_REACHED_TOLERANCE_DEG_PER_SEC
    ) {
      return {
        label: "Slewing",
        className: "is-moving",
        detail: `Velocity mode active. Command ${formatNumber(commandVelocity)} Deg/Sec, setpoint ${formatNumber(setpointVelocity)} Deg/Sec, actual ${formatNumber(velocity)} Deg/Sec.`,
      };
    }
    return {
      label: "Ready",
      className: "",
      detail: "Velocity mode is enabled and no motion command is active.",
    };
  }

  const position = toNumber(axis.position_deg);
  const rawTarget = toNumber(axis.input_pos);
  const offset = toNumber(axis.position_offset_deg) ?? 0;
  const target = rawTarget === null
    ? null
    : axis.label === "Azimuth"
      ? rawTarget + offset
      : normalizeDegrees(rawTarget + offset);
  const trajectoryDone = axis.trajectory_done === true;
  const hasTarget = target !== null && position !== null;
  const error = hasTarget
    ? axis.label === "Azimuth"
      ? Math.abs(target - position)
      : Math.abs(signedDegreeDelta(target, position))
    : null;
  const inPosition = error !== null && error <= POSITION_REACHED_TOLERANCE_DEG;
  const slow = velocity <= VELOCITY_REACHED_TOLERANCE_DEG_PER_SEC;

  if (trajectoryDone && inPosition && slow) {
    return {
      label: "Reached",
      className: "is-reached",
      detail: `Target reached: error ${formatNumber(error)} Deg, velocity ${formatNumber(velocity)} Deg/Sec.`,
    };
  }
  if (trajectoryDone) {
    const errorText = error === null ? "--" : `${formatNumber(error)} Deg`;
    return {
      label: "Settling",
      className: "is-settling",
      detail: `Trajectory done; waiting for position/velocity settle. Error ${errorText}, velocity ${formatNumber(velocity)} Deg/Sec.`,
    };
  }
  if (hasTarget) {
    return {
      label: "Moving",
      className: "is-moving",
      detail: `Moving to ${formatNumber(target)} Deg. Error ${formatNumber(error)} Deg, velocity ${formatNumber(velocity)} Deg/Sec.`,
    };
  }
  return { label: "Ready", className: "", detail: "Axis is enabled." };
}

function signedDegreeDelta(target, current) {
  return ((target - current + 540) % 360) - 180;
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
  activeViewMode = ["axis", "sky", "pointing"].includes(mode) ? mode : "axis";
  document.body.classList.toggle("is-pointing-view", activeViewMode === "pointing");
  if (fields.axisView) fields.axisView.hidden = activeViewMode !== "axis";
  if (fields.skyView) fields.skyView.hidden = activeViewMode !== "sky";
  if (fields.pointingView) fields.pointingView.hidden = activeViewMode !== "pointing";

  document.querySelectorAll("[data-view-mode]").forEach((button) => {
    const active = button.dataset.viewMode === activeViewMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });

  if (persist) {
    storeViewMode(activeViewMode);
    const label = activeViewMode === "sky" ? "Horizon View" : activeViewMode === "pointing" ? "Pointing Model" : "Axis View";
    addLog("message", `Dashboard view changed to ${label}`);
  }
  if (activeViewMode === "sky") {
    renderSkySphere(latestStatus);
  } else if (activeViewMode === "pointing") {
    loadPointingModel();
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

function formatSignedNumber(value) {
  const number = toNumber(value);
  if (number === null) return "--";
  const sign = number < 0 ? "-" : "+";
  return `${sign}${Math.abs(number).toFixed(3)}`;
}

function setTuningInputs(label, axis) {
  const pendingTuning = pendingAutoTuneTuning[label];
  tuningBindings.forEach(([uiKey, axisKey]) => {
    const value = pendingTuning && Object.prototype.hasOwnProperty.call(pendingTuning, axisKey)
      ? pendingTuning[axisKey]
      : axis?.[axisKey];
    setTuningFieldValue(label, uiKey, axisKey, value);
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
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  const roundedToMicrounit = Math.round(number * 1000000) / 1000000;
  const roundedToMilliunit = Math.round(number * 1000) / 1000;
  const cleaned = Math.abs(roundedToMicrounit - roundedToMilliunit) < 0.00001
    ? roundedToMilliunit
    : roundedToMicrounit;
  const formatted = cleaned.toFixed(6).replace(/\.?0+$/, "");
  return formatted === "-0" || formatted === "" ? "0" : formatted;
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

    const autoTuneButton = document.createElement("button");
    autoTuneButton.className = "tuning-auto";
    autoTuneButton.type = "button";
    autoTuneButton.dataset.autoTune = label;
    autoTuneButton.textContent = "Run Auto Tune";

    const saveButton = document.createElement("button");
    saveButton.className = "tuning-save";
    saveButton.type = "button";
    saveButton.dataset.saveTuning = label;
    saveButton.textContent = "Save to Drive";

    const message = document.createElement("p");
    message.className = "tuning-message";
    message.dataset.tuningMessage = label;

    fragment.append(autoTuneButton, applyButton, saveButton, message);
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
    pendingAutoTuneTuning[label] = null;
    addLog("message", options.successMessage || `${label} tuning applied`);
    setTuningMessage(ui, options.successMessage || "Tuning applied", "is-ok");
    return true;
  } catch (error) {
    addLog("error", `${label} tuning failed: ${error.message}`);
    setTuningMessage(ui, error.message, "is-error");
    return false;
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveTuning(label, button) {
  const ui = axisFields[label];
  const form = tuningFormsForAxis(label).find((candidate) => !candidate.dataset.floatingTuningForm) || tuningFormsForAxis(label)[0];
  addLog("warning", "Stopping motion and disabling both axes before flashing configuration");
  button.disabled = true;
  try {
    if (form) {
      const applied = await applyTuningPayload(label, tuningPayloadFromForm(form), {
        pendingMessage: "Applying tuning before flash...",
        successMessage: "Tuning applied before flash",
      });
      if (!applied) throw new Error("Could not apply tuning before flash.");
    }
    addLog("message", `Flashing ${label} configuration to drive`);
    setTuningMessage(ui, "Flashing configuration to drive...", "");
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

function autoTuneUi(label) {
  const prefix = label === "Azimuth" ? "azimuth" : "altitude";
  return {
    panel: fields[`${prefix}AutoTunePanel`],
    close: fields[`${prefix}AutoTuneClose`],
    form: fields[`${prefix}AutoTuneForm`],
    min: fields[`${prefix}AutoTuneMin`],
    max: fields[`${prefix}AutoTuneMax`],
    minSpeed: fields[`${prefix}AutoTuneMinSpeed`],
    maxSpeed: fields[`${prefix}AutoTuneMaxSpeed`],
    cycles: fields[`${prefix}AutoTuneCycles`],
    settleError: fields[`${prefix}AutoTuneSettleError`],
    settleVelocity: fields[`${prefix}AutoTuneSettleVelocity`],
    minStepTime: fields[`${prefix}AutoTuneMinStepTime`],
    minTravel: fields[`${prefix}AutoTuneMinTravel`],
    maxProfiles: fields[`${prefix}AutoTuneMaxProfiles`],
    failLimit: fields[`${prefix}AutoTuneFailLimit`],
    start: fields[`${prefix}AutoTuneStart`],
    message: fields[`${prefix}AutoTuneMessage`],
    progress: fields[`${prefix}AutoTuneProgress`],
    progressBar: fields[`${prefix}AutoTuneProgressBar`],
    resultBody: fields[`${prefix}AutoTuneResultBody`],
    stepLogEntries: fields[`${prefix}AutoTuneStepLogEntries`],
  };
}

function autoTuneStorageKey(label) {
  return `${autoTuneStoragePrefix}${label}`;
}

function autoTuneSettingInputs(autoUi) {
  return [
    ["min_position_deg", autoUi.min],
    ["max_position_deg", autoUi.max],
    ["min_speed_deg_per_sec", autoUi.minSpeed],
    ["max_speed_deg_per_sec", autoUi.maxSpeed],
    ["cycles", autoUi.cycles],
    ["settle_position_deg", autoUi.settleError],
    ["settle_velocity_deg_per_sec", autoUi.settleVelocity],
    ["min_step_time_sec", autoUi.minStepTime],
    ["min_travel_deg", autoUi.minTravel],
    ["max_candidates", autoUi.maxProfiles],
    ["max_failed_steps", autoUi.failLimit],
  ];
}

function loadAutoTuneSettings(label) {
  const autoUi = autoTuneUi(label);
  try {
    const raw = localStorage.getItem(autoTuneStorageKey(label));
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== "object") return;
    autoTuneSettingInputs(autoUi).forEach(([key, input]) => {
      if (!input || saved[key] === undefined || saved[key] === null) return;
      input.value = String(saved[key]);
    });
  } catch (error) {
    addLog("warning", `${label} auto tune saved settings could not be loaded.`);
  }
}

function saveAutoTuneSettings(label) {
  const autoUi = autoTuneUi(label);
  const saved = {};
  autoTuneSettingInputs(autoUi).forEach(([key, input]) => {
    if (!input) return;
    saved[key] = input.value;
  });
  try {
    localStorage.setItem(autoTuneStorageKey(label), JSON.stringify(saved));
  } catch (error) {
    addLog("warning", `${label} auto tune settings could not be saved.`);
  }
}

function setAutoTuneProgress(autoUi, value, state = "running") {
  const progress = autoUi?.progress;
  const bar = autoUi?.progressBar;
  if (!progress || !bar) return;
  progress.hidden = false;
  progress.classList.remove("is-running", "is-ok", "is-error");
  if (state) progress.classList.add(`is-${state}`);
  bar.style.width = `${Math.max(0, Math.min(100, value))}%`;
}

function startAutoTuneProgress(label, payload, autoUi) {
  setAutoTuneProgress(autoUi, 0, "running");
  renderAutoTuneResult(label, null);
  if (autoUi?.stepLogEntries) autoUi.stepLogEntries.dataset.eventSignature = "";
  renderAutoTuneStepEventList(label, []);
  setTuningMessage(
    { tuningMessage: autoUi?.message },
    `Waiting for ${label} auto tune step 1...`,
    "",
  );
}

function finishAutoTuneProgress(autoUi, ok) {
  setAutoTuneProgress(autoUi, ok ? 100 : 100, ok ? "ok" : "error");
}

function renderAutoTuneProgress(progress) {
  if (!progress?.axis) return;
  const autoUi = autoTuneUi(progress.axis);
  if (!autoUi?.progress || autoUi.panel?.hidden) return;
  const percent = Number(progress.percent);
  setAutoTuneProgress(autoUi, Number.isFinite(percent) ? percent : 0, progress.running ? "running" : progress.phase === "complete" ? "ok" : "error");
  const current = Number(progress.current_step || progress.completed_steps || 0);
  const total = Number(progress.total_steps || 0);
  const moveIndex = Number(progress.move_index || 0);
  const moveTotal = Number(progress.move_total || 0);
  const candidateIndex = Number(progress.candidate_index || 0);
  const candidateTotal = Number(progress.candidate_total || 0);
  const prefixParts = [];
  if (total > 0) prefixParts.push(`Overall ${Math.max(1, current)}/${total}`);
  if (candidateTotal > 0) prefixParts.push(`Candidate ${candidateIndex}/${candidateTotal}`);
  if (moveTotal > 0) prefixParts.push(`Step ${moveIndex}/${moveTotal}`);
  const prefix = prefixParts.length ? prefixParts.join(" | ") : "Step";
  const message = progress.message || `${progress.axis} auto tune ${progress.phase || "running"}.`;
  setTuningMessage({ tuningMessage: autoUi.message }, `${prefix}: ${message}`, progress.running ? "" : progress.phase === "complete" ? "is-ok" : "is-error");
}

function renderAutoTuneStepEvents(events) {
  if (!Array.isArray(events)) {
    ["Azimuth", "Altitude"].forEach((label) => renderAutoTuneStepEventList(label, []));
    return;
  }
  ["Azimuth", "Altitude"].forEach((label) => {
    const axisEvents = events
      .filter((event) => event?.axis === label)
      .sort((a, b) => Number(a.id || 0) - Number(b.id || 0));
    renderAutoTuneStepEventList(label, axisEvents);
  });
}

function renderAutoTuneStepEventList(label, events) {
  const autoUi = autoTuneUi(label);
  const container = autoUi?.stepLogEntries;
  if (!container) return;
  const signature = events.map((event) => `${event.id || ""}:${event.status || ""}:${event.duration_sec || ""}`).join("|");
  if (container.dataset.eventSignature === signature) return;
  const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
  const shouldFollow = !container.dataset.eventSignature || distanceFromBottom < 28;
  container.dataset.eventSignature = signature;
  container.replaceChildren();
  if (!events.length) {
    const empty = document.createElement("div");
    empty.className = "auto-tune-step-empty";
    empty.textContent = "Step results will appear here.";
    container.append(empty);
    return;
  }
  events.slice(-80).forEach((event) => container.append(autoTuneStepEntry(event)));
  if (shouldFollow) container.scrollTop = container.scrollHeight;
}

function autoTuneStepEntry(event) {
  const entry = document.createElement("article");
  const status = String(event.status || "unknown");
  entry.className = `auto-tune-step-entry is-${status}`;

  const title = document.createElement("strong");
  const candidateText = Number(event.candidate_total) > 0
    ? `Candidate ${event.candidate_index}/${event.candidate_total} | `
    : "";
  title.textContent = `${candidateText}Step ${event.step}/${event.total_steps} - ${formatAutoTuneStepStatus(status)}`;

  const command = document.createElement("p");
  command.textContent = `${event.candidate || "--"} | cycle ${event.cycle || "--"} | ${formatNumber(event.speed_deg_per_sec)} Deg/Sec -> ${formatNumber(event.target_deg)} Deg${event.adapted_target ? " | adjusted target" : ""}`;

  const result = document.createElement("p");
  result.textContent = `end ${formatNumber(event.end_deg)} Deg | error ${formatNumber(event.final_error_deg)} Deg | ${formatNumber(event.duration_sec)}s / timeout ${formatNumber(event.timeout_limit_sec)}s`;

  const load = document.createElement("p");
  load.textContent = `command ${formatNumber(event.speed_deg_per_sec)} Deg/Sec | final position velocity ${formatNumber(event.final_position_velocity_deg_s)} Deg/Sec | peak drive velocity ${formatNumber(event.peak_abs_velocity_deg_s)} Deg/Sec | peak position velocity ${formatNumber(event.peak_abs_position_velocity_deg_s)} Deg/Sec | peak current ${formatNumber(event.peak_abs_current_a)} Amp`;

  entry.append(title, command, result, load);
  if (Number(event.active_errors) > 0 || Number(event.disarm_reason) > 0) {
    const faults = document.createElement("p");
    faults.textContent = `drive errors active=${valueOrDash(event.active_errors)} disarm=${valueOrDash(event.disarm_reason)}`;
    entry.append(faults);
  }
  return entry;
}

function formatAutoTuneStepStatus(status) {
  return {
    settled: "Settled",
    stalled: "No movement",
    timeout: "Timeout",
    drive_error: "Drive error",
    not_settled: "Not settled",
  }[status] || status;
}

function setAutoTuneButtonRunning(button, running) {
  if (!button) return;
  button.disabled = false;
  button.textContent = running ? "Stop" : "Run Auto Tune";
  button.classList.toggle("is-running", running);
  button.classList.toggle("is-stopping", autoTuneRunState.stopping);
}

async function stopAutoTune(label = "Altitude") {
  if (!autoTuneRunState.running || autoTuneRunState.stopping) return;
  const currentLabel = autoTuneRunState.label || label;
  const currentUi = autoTuneUi(currentLabel);
  autoTuneRunState.stopping = true;
  setAutoTuneButtonRunning(currentUi.start, true);
  setTuningMessage({ tuningMessage: currentUi.message }, "Stopping auto tune after current sample...", "");
  addLog("warning", `${currentLabel} auto tune stop requested`);
  try {
    const response = await fetch(`/api/tuning/${encodeURIComponent(currentLabel)}/auto/stop`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Could not stop auto tune.");
    }
  } catch (error) {
    addLog("error", `${currentLabel} auto tune stop failed: ${error.message}`);
    setTuningMessage({ tuningMessage: currentUi.message }, error.message, "is-error");
  }
}

async function runAutoTune(label, button, options = {}) {
  if (autoTuneRunState.running && autoTuneRunState.label === label) {
    stopAutoTune(label);
    return;
  }
  const ui = axisFields[label];
  const payload = options.payload || null;
  const messageTarget = options.messageTarget || ui?.tuningMessage;
  const progressUi = options.autoTuneUi || autoTuneUi(label);
  const useProgress = options.progress === true;
  addLog("warning", `${label} auto tune will move the axis through multiple long sweeps.`);
  if (payload) {
    addLog("message", `${label} auto tune range ${payload.min_position_deg} Deg to ${payload.max_position_deg} Deg, speeds ${payload.min_speed_deg_per_sec} to ${payload.max_speed_deg_per_sec} Deg/Sec, ${payload.cycles} rounds`);
  }
  addLog("message", `Running ${label} auto tune...`);
  setTuningMessage(ui, "Running auto tune. Axis will move through multiple sweeps...", "");
  setTuningMessage({ tuningMessage: messageTarget }, "Running auto tune. Axis will move through configured sweeps...", "");
  if (useProgress) startAutoTuneProgress(label, payload, progressUi);
  autoTuneRunState = { running: true, stopping: false, label };
  if (useProgress) setAutoTuneButtonRunning(button, true);
  else button.disabled = true;
  try {
    const response = await fetch(`/api/tuning/${encodeURIComponent(label)}/auto`, {
      method: "POST",
      headers: payload ? { "Content-Type": "application/json" } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Auto tune failed.");
    }
    const tuning = data.result?.recommended_tuning || data.result?.original_tuning || {};
    const saved = data.result?.flash?.saved !== false && data.result?.save_recommended !== false;
    pendingAutoTuneTuning[label] = saved ? null : tuning;
    applyAutoTuneResultToFields(label, tuning);
    renderAutoTuneResult(label, data.result);
    if (data.result?.flash?.warning) addLog("warning", data.result.flash.warning);
    const finalMessage = saved
      ? `${label} auto tune saved to drive and synced to Tuning tab (${data.result?.best_candidate || "complete"})`
      : `${label} candidate copied to Tuning tab; press Save to Drive to apply and flash.`;
    addLog(saved ? "success" : "warning", saved
      ? `${label} auto tune saved to drive and updated Tuning tab. Best profile: ${data.result?.best_candidate || "--"}`
      : `${label} auto tune candidate copied to Tuning tab but not flashed.`);
    setTuningMessage(ui, finalMessage, saved ? "is-ok" : "is-warning");
    setTuningMessage({ tuningMessage: messageTarget }, finalMessage, saved ? "is-ok" : "is-warning");
    if (data.result?.speed_profile_deg_per_sec?.length) {
      addLog("message", `${label} auto tune speed profile: ${data.result.speed_profile_deg_per_sec.join(", ")} Deg/Sec`);
    }
    if (useProgress) finishAutoTuneProgress(progressUi, saved);
    setTimeout(refreshStatus, 3000);
  } catch (error) {
    addLog("error", `${label} auto tune failed: ${error.message}`);
    setTuningMessage(ui, error.message, "is-error");
    setTuningMessage({ tuningMessage: messageTarget }, error.message, "is-error");
    if (useProgress) finishAutoTuneProgress(progressUi, false);
  } finally {
    autoTuneRunState = { running: false, stopping: false };
    if (useProgress) setAutoTuneButtonRunning(button, false);
    else button.disabled = false;
  }
}

function renderAutoTuneResult(label, result) {
  const autoUi = autoTuneUi(label);
  const container = autoUi?.resultBody;
  if (!container) return;
  container.replaceChildren();
  if (!result) {
    const empty = document.createElement("p");
    empty.className = "auto-tune-result-empty";
    empty.textContent = "Completed tuning changes will appear here.";
    container.append(empty);
    return;
  }
  const original = result.original_tuning || {};
  const recommended = result.recommended_tuning || {};
  const rows = autoTuneResultRows(original, recommended);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "auto-tune-result-empty";
    empty.textContent = `Best profile: ${result.best_candidate || "complete"}; no numeric tuning differences reported.`;
    container.append(empty);
    return;
  }
  const header = document.createElement("div");
  header.className = `auto-tune-result-row ${result.save_recommended === false ? "is-warning" : "is-changed"}`;
  const title = document.createElement("strong");
  title.textContent = "Best Profile";
  const value = document.createElement("span");
  value.textContent = result.save_recommended === false
    ? `${result.best_candidate || "--"} | copied to Tuning tab, not flashed`
    : `${result.best_candidate || "--"} | saved to drive`;
  header.append(title, value);
  container.append(header);
  rows.forEach((row) => container.append(autoTuneResultRow(row)));
}

function autoTuneResultRows(original, recommended) {
  const fieldsToShow = [
    ["position_gain", "Position Gain"],
    ["velocity_gain", "Velocity Gain"],
    ["velocity_integrator_gain", "Velocity I Gain"],
    ["velocity_integrator_limit", "Velocity I Limit"],
    ["velocity_limit", "Velocity Limit"],
    ["velocity_ramp_rate", "Velocity Ramp Rate"],
    ["torque_ramp_rate", "Torque Ramp Rate"],
    ["spinout_electrical_power_threshold", "Spinout Elec Threshold"],
    ["spinout_mechanical_power_threshold", "Spinout Mech Threshold"],
    ["spinout_electrical_power_bandwidth", "Spinout Elec Bandwidth"],
    ["spinout_mechanical_power_bandwidth", "Spinout Mech Bandwidth"],
    ["input_filter_bandwidth", "Input Filter Bandwidth"],
    ["trap_velocity_limit", "Trap Velocity Limit"],
    ["trap_accel_limit", "Trap Accel Limit"],
    ["trap_decel_limit", "Trap Decel Limit"],
  ];
  return fieldsToShow.flatMap(([key, label]) => {
    const before = toNumber(original[key]);
    const after = toNumber(recommended[key]);
    if (before === null && after === null) return [];
    const changed = before === null || after === null || Math.abs(before - after) >= 0.0005;
    return [{ key, label, before, after, changed }];
  });
}

function autoTuneResultRow(row) {
  const element = document.createElement("div");
  element.className = `auto-tune-result-row ${row.changed ? "is-changed" : "is-same"}`;
  const label = document.createElement("strong");
  label.textContent = row.label;
  const value = document.createElement("span");
  const before = row.before === null ? "--" : formatGain(row.before);
  const after = row.after === null ? "--" : formatGain(row.after);
  value.append(document.createTextNode(`${before} -> `));
  const afterElement = document.createElement("em");
  afterElement.textContent = after;
  value.append(afterElement);
  if (!row.changed) {
    const same = document.createElement("small");
    same.textContent = "same";
    value.append(document.createTextNode(" "));
    value.append(same);
  }
  element.append(label, value);
  return element;
}

function applyAutoTuneResultToFields(label, tuning) {
  const mapping = {
    position_gain: tuning.position_gain,
    velocity_gain: tuning.velocity_gain,
    velocity_integrator_gain: tuning.velocity_integrator_gain,
    velocity_integrator_limit: tuning.velocity_integrator_limit,
    velocity_limit: tuning.velocity_limit,
    velocity_ramp_rate: tuning.velocity_ramp_rate,
    torque_ramp_rate: tuning.torque_ramp_rate,
    spinout_electrical_power_threshold: tuning.spinout_electrical_power_threshold,
    spinout_mechanical_power_threshold: tuning.spinout_mechanical_power_threshold,
    spinout_electrical_power_bandwidth: tuning.spinout_electrical_power_bandwidth,
    spinout_mechanical_power_bandwidth: tuning.spinout_mechanical_power_bandwidth,
    input_filter_bandwidth: tuning.input_filter_bandwidth,
    trap_velocity_limit: tuning.trap_velocity_limit,
    trap_accel_limit: tuning.trap_accel_limit,
    trap_decel_limit: tuning.trap_decel_limit,
  };
  Object.entries(mapping).forEach(([fieldName, value]) => {
    tuningFormsForAxis(label).forEach((form) => {
      const input = form.elements[fieldName];
      if (!input) return;
      input.value = toNumber(value) === null ? "" : formatGain(value);
    });
  });
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

async function sendAxisSineVelocityCommand(axis, action, form) {
  const payload = action === "start" ? sineVelocityPayloadFromForm(form) : null;
  const guardPayload = { [axis]: payload?.max_speed_deg_per_sec || 0 };
  const guardResult = motionCommandGuard.validate("velocity", guardPayload);
  if (!guardResult.ok) {
    setAxisControlMessage(form, guardResult.message, "is-warning");
    addLog("warning", guardResult.message);
    return;
  }
  if (payload) {
    const velocityLimitResult = validateMaxVelocity("velocity", guardPayload);
    if (!velocityLimitResult.ok) {
      setAxisControlMessage(form, velocityLimitResult.message, "is-warning");
      addLog("warning", velocityLimitResult.message);
      return;
    }
  }

  motorCommandInFlight = true;
  const actionLabel = action === "start" ? "Starting random sine velocity test" : "Stopping random sine velocity test";
  setAxisControlMessage(form, `${axis} ${actionLabel.toLowerCase()}...`);
  addLog("message", `${axis} ${actionLabel}...`);
  renderMotorControls(latestStatus);
  renderAxisControls(latestStatus);
  try {
    const options = { method: "POST" };
    if (payload) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(`/api/motors/sine-velocity/${encodeURIComponent(axis)}/${action}`, options);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Sine velocity command failed.");
    }
    renderStatus(data.status);
    setAxisControlMessage(form, `${axis} random sine velocity ${action === "start" ? "started" : "stopped"}`, "is-ok");
  } catch (error) {
    addLog("error", `${axis} sine velocity test failed: ${error.message}`);
    setAxisControlMessage(form, error.message, "is-error");
  } finally {
    motorCommandInFlight = false;
    renderMotorControls(latestStatus);
    renderAxisControls(latestStatus);
  }
}

async function sendAxisJogCommand(axis, velocity, form = null, message = "Jog", options = {}) {
  const payload = axisPayload(axis, String(velocity));
  const guardResult = motionCommandGuard.validate("velocity", payload);
  if (!guardResult.ok) {
    setAxisControlMessage(form, guardResult.message, "is-warning");
    addLog("warning", guardResult.message);
    return false;
  }
  const velocityLimitResult = validateMaxVelocity("velocity", payload);
  if (!velocityLimitResult.ok) {
    setAxisControlMessage(form, velocityLimitResult.message, "is-warning");
    addLog("warning", velocityLimitResult.message);
    return false;
  }

  try {
    const lightweight = options.lightweight === true;
    const response = await fetch(lightweight ? "/api/motors/velocity-command" : "/api/motors/velocity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Jog command failed.");
    }
    if (data.status) renderStatus(data.status);
    setAxisControlMessage(form, message, velocity === 0 ? "is-ok" : "");
    return true;
  } catch (error) {
    setAxisControlMessage(form, error.message, "is-error");
    addLog("error", `${axis} jog failed: ${error.message}`);
    return false;
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

function populateAutoTuneDefaults(label) {
  const autoUi = autoTuneUi(label);
  const limits = appSettings?.motion_limits || {};
  const isAzimuth = label === "Azimuth";
  const lowerKey = isAzimuth ? "azimuth_ccw_limit_deg" : "altitude_lower_limit_deg";
  const upperKey = isAzimuth ? "azimuth_cw_limit_deg" : "altitude_upper_limit_deg";
  let lower = Number.isFinite(Number(limits[lowerKey])) ? Number(limits[lowerKey]) : -60;
  let upper = Number.isFinite(Number(limits[upperKey])) ? Number(limits[upperKey]) : 60;
  const currentPosition = currentAxisPosition(label);
  if (Number.isFinite(currentPosition)) {
    const requestedHalfSpan = Math.min(60, Math.max(10, Math.abs(upper - lower) / 2 || 60));
    const currentLower = currentPosition - requestedHalfSpan;
    const currentUpper = currentPosition + requestedHalfSpan;
    lower = Number.isFinite(Number(limits[lowerKey])) ? Math.max(Number(limits[lowerKey]), currentLower) : currentLower;
    upper = Number.isFinite(Number(limits[upperKey])) ? Math.min(Number(limits[upperKey]), currentUpper) : currentUpper;
  }
  const speed = Number.isFinite(Number(limits.slew_rate_deg_per_sec)) ? Number(limits.slew_rate_deg_per_sec) : 20;
  const hasTemplateRange = autoUi.min?.value === "-60" && autoUi.max?.value === "60";
  if (autoUi.min && (autoUi.min.value === "" || hasTemplateRange)) autoUi.min.value = formatAutoTuneInput(lower);
  if (autoUi.max && (autoUi.max.value === "" || hasTemplateRange)) autoUi.max.value = formatAutoTuneInput(upper);
  if (autoUi.minSpeed && autoUi.minSpeed.value === "") autoUi.minSpeed.value = "0.1";
  if (autoUi.maxSpeed && autoUi.maxSpeed.value === "") autoUi.maxSpeed.value = String(Math.min(Math.max(speed, 1), 20));
  if (autoUi.cycles && autoUi.cycles.value === "") autoUi.cycles.value = "3";
}

function currentAxisPosition(label) {
  const axis = Array.isArray(latestStatus?.axes)
    ? latestStatus.axes.find((item) => item.label === label)
    : null;
  const position = Number(axis?.position_deg);
  return Number.isFinite(position) ? position : null;
}

function formatAutoTuneInput(value) {
  return Number(value).toFixed(3).replace(/\.?0+$/, "");
}

async function openAutoTunePanel(label, event = null) {
  const autoUi = autoTuneUi(label);
  if (!autoUi.panel) return;
  if (!appSettings?.motion_limits || Object.keys(appSettings.motion_limits).length === 0) {
    await loadAppSettings();
  }
  populateAutoTuneDefaults(label);
  loadAutoTuneSettings(label);
  autoUi.panel.hidden = false;
  restoreFloatingWindowPosition(autoUi.panel, event ? { left: event.clientX, top: event.clientY } : null);
  addLog("message", `Opened ${label} auto tune setup`);
  autoUi.min?.focus();
  autoUi.min?.select();
}

function closeAutoTunePanel(label) {
  const autoUi = autoTuneUi(label);
  if (autoUi.panel) autoUi.panel.hidden = true;
}

function autoTunePayload(label) {
  const autoUi = autoTuneUi(label);
  const minPosition = toNumber(autoUi.min?.value);
  const maxPosition = toNumber(autoUi.max?.value);
  const minSpeed = toNumber(autoUi.minSpeed?.value);
  const maxSpeed = toNumber(autoUi.maxSpeed?.value);
  const cycles = Math.round(toNumber(autoUi.cycles?.value));
  const settleError = toNumber(autoUi.settleError?.value);
  const settleVelocity = toNumber(autoUi.settleVelocity?.value);
  const minStepTime = toNumber(autoUi.minStepTime?.value);
  const minTravel = toNumber(autoUi.minTravel?.value);
  const maxProfiles = Math.round(toNumber(autoUi.maxProfiles?.value));
  const failLimit = Math.round(toNumber(autoUi.failLimit?.value));
  if (!Number.isFinite(minPosition) || !Number.isFinite(maxPosition)) {
    throw new Error("Minimum and maximum positions are required.");
  }
  if (minPosition >= maxPosition) {
    throw new Error("Minimum position must be less than maximum position.");
  }
  if (!Number.isFinite(minSpeed) || minSpeed <= 0 || !Number.isFinite(maxSpeed) || maxSpeed <= 0) {
    throw new Error("Minimum and maximum speed must be greater than 0.");
  }
  if (minSpeed > maxSpeed) {
    throw new Error("Minimum speed must be less than or equal to maximum speed.");
  }
  if (!Number.isFinite(cycles) || cycles < 1) {
    throw new Error("Sweep cycles must be at least 1.");
  }
  if (!Number.isFinite(settleError) || settleError <= 0) {
    throw new Error("Settle error must be greater than 0.");
  }
  if (!Number.isFinite(settleVelocity) || settleVelocity <= 0) {
    throw new Error("Settle velocity must be greater than 0.");
  }
  if (!Number.isFinite(minStepTime) || minStepTime < 0) {
    throw new Error("Minimum step time must be 0 or greater.");
  }
  if (!Number.isFinite(minTravel) || minTravel < 0) {
    throw new Error("Minimum travel must be 0 or greater.");
  }
  if (!Number.isFinite(maxProfiles) || maxProfiles < 1 || maxProfiles > 8) {
    throw new Error("Max profiles must be between 1 and 8.");
  }
  if (!Number.isFinite(failLimit) || failLimit < 1 || failLimit > 16) {
    throw new Error("Fail limit must be between 1 and 16.");
  }
  saveAutoTuneSettings(label);
  return {
    min_position_deg: minPosition,
    max_position_deg: maxPosition,
    min_speed_deg_per_sec: minSpeed,
    max_speed_deg_per_sec: maxSpeed,
    cycles,
    settle_position_deg: settleError,
    settle_velocity_deg_per_sec: settleVelocity,
    min_step_time_sec: minStepTime,
    min_travel_deg: minTravel,
    max_candidates: maxProfiles,
    max_failed_steps: failLimit,
  };
}

async function openSettingsPanel() {
  if (!fields.settingsPanel) return;
  await loadAppSettings();
  await loadSystemInfo({ quiet: true });
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
  setInputNumber(fields.settingsStationElevation, station.elevation_above_ground_m ?? 0);
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
  const updater = appSettings.updater || {};
  if (fields.settingsDeviceId) fields.settingsDeviceId.value = updater.device_id || "";
  if (fields.settingsUpdateInterval) fields.settingsUpdateInterval.value = updater.check_interval_minutes || 15;
  if (fields.settingsUpdateChannel) fields.settingsUpdateChannel.value = updater.channel || "main";
  if (fields.settingsAutoUpdate) fields.settingsAutoUpdate.value = updater.enabled === false ? "false" : "true";
}

function updatePageTitle() {
  const stationName = String(appSettings.station?.name || "").trim();
  const title = "Narit Fire Detector Mount";
  if (fields.pageTitle) fields.pageTitle.textContent = title;
  if (fields.stationTitle) fields.stationTitle.textContent = stationName || "NARIT#1 Mount Station";
  document.title = stationName ? `${title} - ${stationName}` : title;
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

async function loadSystemInfo(options = {}) {
  try {
    const response = await fetch("/api/system/info", { cache: "no-store" });
    const data = await response.json();
    renderSystemInfo(data, options);
    return data;
  } catch (error) {
    renderSystemInfo(null, options);
    if (!options.quiet) addLog("error", `System info unavailable: ${error.message}`);
    return null;
  }
}

function renderSystemInfo(data, options = {}) {
  const firmware = data?.firmware_version || "--";
  const branch = data?.branch || "--";
  const state = data?.update_state || {};
  if (fields.settingsFirmwareVersionView) {
    fields.settingsFirmwareVersionView.textContent = firmware;
    fields.settingsFirmwareVersionView.title = firmware;
  }
  if (fields.systemFirmwareVersion) fields.systemFirmwareVersion.textContent = firmware;
  if (fields.systemGitBranch) fields.systemGitBranch.textContent = branch;
  if (fields.systemLastUpdateCheck) fields.systemLastUpdateCheck.textContent = formatUpdateTimestamp(state.checked_at);
  if (fields.systemUpdateStatus) {
    const status = state.status || (data?.auto_update_enabled === false ? "disabled" : "waiting");
    fields.systemUpdateStatus.textContent = updateStatusLabel(status);
    fields.systemUpdateStatus.title = state.message || "";
  }
  if (data?.device_id && fields.settingsDeviceId && !fields.settingsDeviceId.value) {
    fields.settingsDeviceId.value = data.device_id;
  }
  renderUpdateProgress(state, options);
}

function updateStatusLabel(status) {
  return String(status || "waiting")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatUpdateTimestamp(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString();
}

function renderUpdateProgress(state = {}, options = {}) {
  const status = state.status || "waiting";
  const message = state.message || "";
  const active = ["queued", "checking", "updating"].includes(status);
  if (fields.updateProgress) fields.updateProgress.hidden = !active;
  if (!active) return;
  const progress = updateProgressForStatus(status);
  if (fields.updateProgressTitle) fields.updateProgressTitle.textContent = progress.title;
  if (fields.updateProgressDetail) fields.updateProgressDetail.textContent = message || progress.detail;
  if (fields.updateProgressBar) fields.updateProgressBar.style.width = progress.width;
}

function updateProgressForStatus(status) {
  const map = {
    queued: ["Queued", "Waiting for updater...", "12%"],
    checking: ["Checking for updates", "Contacting GitHub...", "36%"],
    updating: ["Installing update", "Applying new firmware...", "72%"],
    current: ["Already up to date", "This firmware is the latest version.", "100%"],
    updated: ["Update complete", "Firmware updated successfully.", "100%"],
    failed: ["Update failed", "Check the log for details.", "100%"],
    rolled_back: ["Rolled back", "Update failed and previous firmware was restored.", "100%"],
    rollback_failed: ["Update failed", "Rollback could not complete.", "100%"],
    disabled: ["Auto update disabled", "Updater is disabled.", "100%"],
  };
  const [title, detail, width] = map[status] || ["Update status", "Waiting", "0%"];
  return { title, detail, width };
}

function logUpdateState(state = {}, options = {}) {
  const status = state.status || "waiting";
  const key = `${status}:${state.checked_at || ""}:${state.message || ""}`;
  if (!options.force && key === lastUpdateStatusKey) return;
  lastUpdateStatusKey = key;
  const message = state.message || updateProgressForStatus(status).detail;
  if (status === "current") {
    addLog("success", "Firmware is already up to date.");
  } else if (status === "updated") {
    addLog("success", message || "Firmware update completed.");
  } else if (["failed", "rolled_back", "rollback_failed"].includes(status)) {
    addLog("error", `Firmware update ${updateStatusLabel(status).toLowerCase()}: ${message}`);
  } else if (["queued", "checking", "updating"].includes(status)) {
    addLog("message", message || updateProgressForStatus(status).detail);
  } else if (status === "disabled") {
    addLog("warning", message || "Automatic updates are disabled.");
  }
}

function updateCheckMessageForState(state = {}) {
  const status = state.status || "waiting";
  const message = state.message || "";
  if (status === "current") {
    setSystemUpdateMessage("Firmware is already up to date.", "is-ok");
  } else if (status === "updated") {
    setSystemUpdateMessage(message || "Firmware update completed.", "is-ok");
  } else if (["failed", "rolled_back", "rollback_failed"].includes(status)) {
    setSystemUpdateMessage(message || `Firmware update ${updateStatusLabel(status).toLowerCase()}.`, "is-error");
  } else if (status === "disabled") {
    setSystemUpdateMessage(message || "Automatic updates are disabled.", "is-error");
  }
}

function startUpdateStatusPolling() {
  if (updatePollTimer) clearInterval(updatePollTimer);
  updatePollTimer = setInterval(async () => {
    const data = await loadSystemInfo({ quiet: true });
    const state = data?.update_state || {};
    logUpdateState(state);
    if (!["queued", "checking", "updating"].includes(state.status)) {
      clearInterval(updatePollTimer);
      updatePollTimer = null;
      if (fields.systemUpdateCheck) fields.systemUpdateCheck.disabled = false;
      renderUpdateProgress(state);
      updateCheckMessageForState(state);
    }
  }, 1200);
}

function settingsPayloadFromForm() {
  return {
    flash_drives: activeSettingsTab() !== "system",
    station: {
      name: fields.settingsStationName?.value || "",
      latitude: fields.settingsLatitude?.value || null,
      longitude: fields.settingsLongitude?.value || null,
      elevation_above_ground_m: fields.settingsStationElevation?.value || 0,
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
    updater: {
      device_id: fields.settingsDeviceId?.value || null,
      check_interval_minutes: fields.settingsUpdateInterval?.value || 15,
      channel: fields.settingsUpdateChannel?.value || "main",
      enabled: fields.settingsAutoUpdate?.value !== "false",
    },
  };
}

function activeSettingsTab() {
  return document.querySelector("[data-settings-tab].active")?.dataset.settingsTab || "general";
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
  if (activeSettingsTab() !== "system") {
    addLog("warning", "Stopping motion and disabling both axes before saving settings");
  }
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
    await loadSystemInfo({ quiet: true });
    if (activeViewMode === "pointing") await loadPointingModel({ force: true });
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

async function requestUpdateCheck() {
  if (fields.systemUpdateCheck) fields.systemUpdateCheck.disabled = true;
  setSystemUpdateMessage("Checking for updates...", "");
  showManualUpdateProgress("Checking for updates", "Starting updater...", "10%");
  addLog("message", "Checking GitHub for firmware updates.");
  try {
    const response = await fetch("/api/system/update-check", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Update check failed.");
    }
    setSystemUpdateMessage("Update check running...", "is-ok");
    startUpdateStatusPolling();
    setTimeout(async () => {
      const info = await loadSystemInfo({ quiet: true });
      const state = info?.update_state || {};
      logUpdateState(state, { force: true });
      if (!["queued", "checking", "updating"].includes(state.status)) {
        updateCheckMessageForState(state);
      }
    }, 900);
  } catch (error) {
    addLog("error", `Update check failed: ${error.message}`);
    setSystemUpdateMessage(error.message, "is-error");
    hideUpdateProgress();
    if (fields.systemUpdateCheck) fields.systemUpdateCheck.disabled = false;
  }
}

function showManualUpdateProgress(title, detail, width) {
  if (fields.updateProgress) fields.updateProgress.hidden = false;
  if (fields.updateProgressTitle) fields.updateProgressTitle.textContent = title;
  if (fields.updateProgressDetail) fields.updateProgressDetail.textContent = detail;
  if (fields.updateProgressBar) fields.updateProgressBar.style.width = width;
}

function hideUpdateProgress() {
  if (fields.updateProgress) fields.updateProgress.hidden = true;
  if (fields.updateProgressTitle) fields.updateProgressTitle.textContent = "";
  if (fields.updateProgressDetail) fields.updateProgressDetail.textContent = "";
  if (fields.updateProgressBar) fields.updateProgressBar.style.width = "0%";
}

function setSystemUpdateMessage(message, className) {
  if (!fields.systemUpdateMessage) return;
  fields.systemUpdateMessage.classList.remove("is-ok", "is-error");
  if (className) fields.systemUpdateMessage.classList.add(className);
  fields.systemUpdateMessage.textContent = message;
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

async function loadPointingModel({ force = false } = {}) {
  if (pointingModelLoading) return;
  if (pointingModel && !force) {
    renderPointingModel();
    return;
  }
  pointingModelLoading = true;
  setPointingProgress(true, "Building terrain map", "Generating 30 m grid from DEM...");
  drawPointingPlaceholder("Building 30 m terrain grid...");
  try {
    const response = await fetch("/api/pointing/model?resolution_m=30", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Pointing model unavailable.");
    }
    pointingModel = data;
    pointingRasterImages.clear();
    selectedPointingSample = null;
    setPointingProgress(true, data.cached ? "Loading cached terrain map" : "Loading terrain map", data.cached ? "Using cached 30 m raster from disk..." : "Preparing generated 30 m raster...");
    updatePointingReadouts();
    renderPointingModel();
    if (data.station?.source === "dem_center") {
      addLog("warning", "Pointing Model is using DEM center because station latitude/longitude is not configured.");
    }
  } catch (error) {
    addLog("error", `Pointing Model failed: ${error.message}`);
    drawPointingPlaceholder(error.message);
    setPointingProgress(false);
  } finally {
    pointingModelLoading = false;
  }
}

function setPointingProgress(visible, title = "", detail = "") {
  if (!fields.pointingMapProgress) return;
  fields.pointingMapProgress.hidden = !visible;
  if (fields.pointingProgressTitle && title) fields.pointingProgressTitle.textContent = title;
  if (fields.pointingProgressDetail && detail) fields.pointingProgressDetail.textContent = detail;
}

function updatePointingReadouts() {
  if (!pointingModel) return;
  const station = pointingModel.station || {};
  const dem = pointingModel.dem || {};
  if (fields.pointingStationValue) {
    fields.pointingStationValue.textContent = `${formatCoordinate(station.latitude)}, ${formatCoordinate(station.longitude)}`;
    fields.pointingStationValue.title = station.source === "dem_center" ? "Using DEM center; configure station Latitude/Longitude for final pointing." : "";
  }
  if (fields.pointingRangeValue) fields.pointingRangeValue.textContent = `${formatNumber(pointingModel.radius_km)} km`;
  if (fields.pointingDemValue) {
    const resolution = toNumber(pointingModel.grid_resolution_m);
    const suffix = resolution === null ? "" : ` @ ${formatCompactNumber(resolution)} m`;
    fields.pointingDemValue.textContent = dem.elevation_min_m === null ? "--" : `${formatCompactNumber(dem.elevation_min_m)}-${formatCompactNumber(dem.elevation_max_m)} m${suffix}`;
  }
  if (fields.pointingMapSubtitle) {
    const source = station.source === "dem_center" ? "DEM center fallback" : "station setting";
    fields.pointingMapSubtitle.textContent = `20 km terrain model around ${source}`;
  }
  if (fields.pointingImageryAttribution) {
    fields.pointingImageryAttribution.textContent = pointingModel.imagery?.available ? pointingModel.imagery.attribution || "" : "";
  }
  updatePointingSelectionReadouts(selectedPointingSample);
}

function renderPointingModel() {
  const canvas = fields.pointingMapCanvas;
  if (!canvas || !pointingModel) return;
  const rect = canvas.parentElement?.getBoundingClientRect() || canvas.getBoundingClientRect();
  const cssWidth = Math.max(640, Math.floor(rect.width || 1000));
  const cssHeight = Math.max(480, Math.floor(rect.height || 620));
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  drawPointingTerrain(ctx, cssWidth, cssHeight);
}

function drawPointingTerrain(ctx, width, height) {
  if (pointingModel.raster?.src) {
    drawPointingRasterTerrain(ctx, width, height);
    return;
  }
  const gridSize = pointingModel.grid_size;
  const values = pointingModel.elevations || [];
  const visibility = pointingModel.visibility || [];
  const dem = pointingModel.dem || {};
  const minElevation = toNumber(dem.elevation_min_m);
  const maxElevation = toNumber(dem.elevation_max_m);
  const radius = Math.min(width, height) * 0.44;
  const center = pointingMapCenter(width, height, radius);
  const cx = center.x;
  const cy = center.y;
  ctx.clearRect(0, 0, width, height);
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.clip();
  const cellSize = (radius * 2) / gridSize;
  const left = cx - radius;
  const top = cy - radius;
  for (let row = 0; row < gridSize; row += 1) {
    for (let col = 0; col < gridSize; col += 1) {
      const elevation = values[row * gridSize + col];
      if (elevation === null || elevation === undefined) continue;
      ctx.fillStyle = terrainColor(elevation, minElevation, maxElevation);
      ctx.fillRect(left + col * cellSize, top + row * cellSize, Math.ceil(cellSize) + 0.5, Math.ceil(cellSize) + 0.5);
      const isVisible = visibility[row * gridSize + col];
      if (isVisible === true) {
        ctx.fillStyle = "rgba(255, 246, 198, 0.13)";
        ctx.fillRect(left + col * cellSize, top + row * cellSize, Math.ceil(cellSize) + 0.5, Math.ceil(cellSize) + 0.5);
      } else if (isVisible === false) {
        ctx.fillStyle = "rgba(3, 7, 14, 0.34)";
        ctx.fillRect(left + col * cellSize, top + row * cellSize, Math.ceil(cellSize) + 0.5, Math.ceil(cellSize) + 0.5);
      }
    }
  }
  ctx.restore();
  drawPointingOverlay(ctx, cx, cy, radius);
}

function drawPointingRasterTerrain(ctx, width, height) {
  const raster = pointingModel.raster || {};
  const layers = pointingLayerState();
  const sources = [
    layers.satellite ? raster.satellite_src : null,
    layers.terrain ? (raster.terrain_src || raster.src) : null,
    layers.visibility ? raster.visibility_src : null,
  ].filter(Boolean);
  const missingSource = sources.find((src) => !loadedPointingRasterImage(src));
  if (missingSource) {
    loadPointingRasterImage(missingSource);
    setPointingProgress(true, "Loading map layer", "Reading cached map raster from disk...");
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "rgba(244, 246, 255, 0.68)";
    ctx.font = "15px Segoe UI";
    ctx.textAlign = "center";
    ctx.fillText("Loading map layer...", width / 2, height / 2);
    return;
  }
  setPointingProgress(false);
  const radius = Math.min(width, height) * 0.44;
  const center = pointingMapCenter(width, height, radius);
  const cx = center.x;
  const cy = center.y;
  ctx.clearRect(0, 0, width, height);
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.clip();
  ctx.imageSmoothingEnabled = false;
  sources.forEach((src) => {
    const image = loadedPointingRasterImage(src);
    if (image) ctx.drawImage(image, cx - radius, cy - radius, radius * 2, radius * 2);
  });
  ctx.restore();
  if (layers.grid) drawPointingOverlay(ctx, cx, cy, radius);
  else {
    drawPointingStation(ctx, cx, cy);
    drawPointingSelection(ctx, cx, cy, radius);
  }
}

function pointingLayerState() {
  return {
    satellite: fields.pointingLayerSatellite?.checked !== false,
    terrain: fields.pointingLayerTerrain?.checked !== false,
    visibility: fields.pointingLayerVisibility?.checked !== false,
    grid: fields.pointingLayerGrid?.checked !== false,
  };
}

function loadedPointingRasterImage(src) {
  const image = pointingRasterImages.get(src);
  return image?.complete && image.naturalWidth > 0 ? image : null;
}

function loadPointingRasterImage(src) {
  if (pointingRasterImages.has(src)) return;
  const image = new Image();
  image.onload = () => renderPointingModel();
  image.onerror = () => setPointingProgress(false);
  pointingRasterImages.set(src, image);
  image.src = src;
}

function drawPointingOverlay(ctx, cx, cy, radius) {
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(255, 193, 112, 0.44)";
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.stroke();
  [0.25, 0.5, 0.75].forEach((ratio) => {
    ctx.strokeStyle = "rgba(255, 193, 112, 0.24)";
    ctx.beginPath();
    ctx.arc(cx, cy, radius * ratio, 0, Math.PI * 2);
    ctx.stroke();
  });
  for (let azimuth = 0; azimuth < 360; azimuth += 45) {
    const angle = (azimuth * Math.PI) / 180;
    ctx.strokeStyle = azimuth % 90 === 0 ? "rgba(255, 193, 112, 0.36)" : "rgba(255, 193, 112, 0.16)";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.sin(angle) * radius, cy - Math.cos(angle) * radius);
    ctx.stroke();
  }
  drawPointingLabels(ctx, cx, cy, radius);
  drawPointingStation(ctx, cx, cy);
  drawPointingSelection(ctx, cx, cy, radius);
}

function pointingMapCenter(width, height, radius) {
  const rightPanelWidth = 320;
  const rightGutter = 34;
  const maximumShift = Math.max(0, width - rightPanelWidth - rightGutter - radius - width / 2);
  const preferredShift = Math.min(150, Math.max(70, width * 0.07));
  return {
    x: width / 2 + Math.min(preferredShift, maximumShift),
    y: height / 2,
  };
}

function drawPointingLabels(ctx, cx, cy, radius) {
  ctx.font = "12px Segoe UI";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  [["N", 0, -1], ["E", 1, 0], ["S", 0, 1], ["W", -1, 0]].forEach(([label, x, y]) => {
    drawPointingLabelText(ctx, label, cx + x * (radius + 18), cy + y * (radius + 18), "rgba(255, 218, 158, 0.90)");
  });
  [5, 10, 15, 20].forEach((km) => {
    const ringRadius = radius * (km / pointingModel.radius_km);
    drawPointingLabelText(ctx, `${km} km`, cx + 8, cy - ringRadius + 12, "rgba(255, 218, 158, 0.78)");
  });
}

function drawPointingLabelText(ctx, text, x, y, color) {
  ctx.lineWidth = 3;
  ctx.strokeStyle = "rgba(4, 7, 14, 0.82)";
  ctx.strokeText(text, x, y);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

function drawPointingStation(ctx, cx, cy) {
  ctx.fillStyle = "#ffb470";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.86)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(cx, cy, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function drawPointingSelection(ctx, cx, cy, radius) {
  if (!selectedPointingSample || !pointingModel) return;
  const position = pointingCanvasPositionForSample(selectedPointingSample, cx, cy, radius);
  if (!position) return;
  ctx.strokeStyle = "rgba(255, 180, 112, 0.86)";
  ctx.fillStyle = "rgba(255, 180, 112, 0.26)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(position.x, position.y, 10, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(position.x, position.y);
  ctx.stroke();
}

function pointingCanvasPositionForSample(sample, cx, cy, radius) {
  const distanceKm = toNumber(sample.distance_km);
  const azimuth = toNumber(sample.azimuth_deg);
  if (distanceKm === null || azimuth === null) return null;
  const distanceRatio = distanceKm / pointingModel.radius_km;
  const angle = (azimuth * Math.PI) / 180;
  return {
    x: cx + Math.sin(angle) * radius * distanceRatio,
    y: cy - Math.cos(angle) * radius * distanceRatio,
  };
}

function terrainColor(elevation, minElevation, maxElevation) {
  if (minElevation === null || maxElevation === null || minElevation === maxElevation) return "#376f68";
  const ratio = Math.max(0, Math.min(1, (elevation - minElevation) / (maxElevation - minElevation)));
  const stops = [
    [30, 83, 79],
    [63, 139, 91],
    [169, 146, 83],
    [142, 104, 87],
    [226, 222, 205],
  ];
  const scaled = ratio * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(scaled));
  const t = scaled - index;
  const color = stops[index].map((channel, channelIndex) => Math.round(channel + (stops[index + 1][channelIndex] - channel) * t));
  return `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
}

function drawPointingPlaceholder(message) {
  const canvas = fields.pointingMapCanvas;
  if (!canvas) return;
  const rect = canvas.parentElement?.getBoundingClientRect() || canvas.getBoundingClientRect();
  const width = Math.max(640, Math.floor(rect.width || 1000));
  const height = Math.max(480, Math.floor(rect.height || 620));
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(244, 246, 255, 0.72)";
  ctx.font = "15px Segoe UI";
  ctx.textAlign = "center";
  ctx.fillText(message || "Pointing Model unavailable", width / 2, height / 2);
}

async function selectPointingMapPoint(event) {
  const target = pointingTargetFromPointerEvent(event);
  if (!target) return;
  try {
    const url = `/api/pointing/sample?lat=${encodeURIComponent(target.latitude)}&lon=${encodeURIComponent(target.longitude)}`;
    const response = await fetch(url, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Point sample failed.");
    }
    selectedPointingSample = data.sample;
    updatePointingSelectionReadouts(selectedPointingSample);
    renderPointingModel();
  } catch (error) {
    addLog("error", `Pointing sample failed: ${error.message}`);
  }
}

function pointingTargetFromPointerEvent(event) {
  const canvas = fields.pointingMapCanvas;
  if (!canvas || !pointingModel) return null;
  const rect = canvas.getBoundingClientRect();
  const radius = Math.min(rect.width, rect.height) * 0.44;
  const center = pointingMapCenter(rect.width, rect.height, radius);
  const cx = rect.left + center.x;
  const cy = rect.top + center.y;
  const dx = event.clientX - cx;
  const dy = event.clientY - cy;
  if (Math.hypot(dx, dy) > radius) return null;
  const radiusM = pointingModel.radius_km * 1000;
  const eastM = (dx / radius) * radiusM;
  const northM = (-dy / radius) * radiusM;
  return offsetLatLon(pointingModel.station.latitude, pointingModel.station.longitude, eastM, northM);
}

function offsetLatLon(latitude, longitude, eastM, northM) {
  const earthRadiusM = 6371008.8;
  const latRad = (latitude * Math.PI) / 180;
  const newLat = latitude + (northM / earthRadiusM) * (180 / Math.PI);
  const newLon = longitude + (eastM / (earthRadiusM * Math.max(0.01, Math.cos(latRad)))) * (180 / Math.PI);
  return { latitude: newLat, longitude: newLon };
}

function updatePointingSelectionReadouts(sample) {
  if (!sample) {
    if (fields.pointingSelectionTitle) fields.pointingSelectionTitle.textContent = "Select a terrain point";
    if (fields.pointingDistanceValue) fields.pointingDistanceValue.textContent = "--";
    if (fields.pointingAzimuthValue) fields.pointingAzimuthValue.textContent = "--";
    if (fields.pointingElevationValue) fields.pointingElevationValue.textContent = "--";
    if (fields.pointingAltitudeValue) fields.pointingAltitudeValue.textContent = "--";
    if (fields.pointingVisibilityValue) fields.pointingVisibilityValue.textContent = "--";
    if (fields.pointingBlockerValue) fields.pointingBlockerValue.textContent = "--";
    if (fields.pointingCoordinateValue) fields.pointingCoordinateValue.textContent = "Click inside the 20 km circle.";
    return;
  }
  if (fields.pointingSelectionTitle) fields.pointingSelectionTitle.textContent = sample.inside_radius ? "Selected terrain point" : "Point outside radius";
  if (fields.pointingDistanceValue) fields.pointingDistanceValue.textContent = `${formatNumber(sample.distance_km)} km`;
  if (fields.pointingAzimuthValue) fields.pointingAzimuthValue.textContent = `${formatNumber(sample.azimuth_deg)} Deg`;
  if (fields.pointingElevationValue) fields.pointingElevationValue.textContent = sample.elevation_m === null ? "No DEM data" : `${formatCompactNumber(sample.elevation_m)} m`;
  if (fields.pointingAltitudeValue) fields.pointingAltitudeValue.textContent = sample.altitude_deg === null ? "--" : `${formatNumber(sample.altitude_deg)} Deg`;
  if (fields.pointingVisibilityValue) {
    fields.pointingVisibilityValue.textContent = sample.visible === null ? "--" : sample.visible ? "Visible" : "Blocked";
  }
  if (fields.pointingBlockerValue) {
    fields.pointingBlockerValue.textContent = sample.blocker
      ? `${formatNumber(sample.blocker.distance_km)} km / ${formatCompactNumber(sample.blocker.elevation_m)} m`
      : "--";
    fields.pointingBlockerValue.title = sample.blocker
      ? `${formatCoordinate(sample.blocker.latitude)}, ${formatCoordinate(sample.blocker.longitude)} at ${formatNumber(sample.blocker.altitude_deg)} Deg`
      : "";
  }
  if (fields.pointingCoordinateValue) {
    fields.pointingCoordinateValue.textContent = `${formatCoordinate(sample.latitude)}, ${formatCoordinate(sample.longitude)}`;
  }
}

function formatCoordinate(value) {
  const number = toNumber(value);
  if (number === null) return "--";
  return number.toFixed(6);
}

function formatCompactNumber(value) {
  const number = toNumber(value);
  if (number === null) return "--";
  return Math.round(number).toLocaleString();
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
  input.value = number === null ? "" : formatGain(number);
}

function normalizeNumberInput(input) {
  if (!input || input.value === "") return;
  const number = toNumber(input.value);
  if (number === null) return;
  input.value = formatGain(number);
}

function disableNativeValidationBubbles() {
  document.querySelectorAll("form").forEach((form) => {
    form.noValidate = true;
    form.setAttribute("novalidate", "novalidate");
  });

  document.querySelectorAll("input[type='number']").forEach((input) => {
    input.addEventListener("invalid", (event) => {
      event.preventDefault();
    });
    input.addEventListener("blur", () => normalizeNumberInput(input));
  });
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

function axisGotoPositionPayload(axis, form, value) {
  const payload = axisPayload(axis, value);
  const velocityTarget = axisFormValue(form, "position_velocity_target");
  if (velocityTarget !== "") {
    payload.velocity_target_deg_per_sec = velocityTarget;
  }
  return payload;
}

function sineVelocityPayloadFromForm(form) {
  return {
    min_speed_deg_per_sec: axisFormValue(form, "sine_min_speed"),
    max_speed_deg_per_sec: axisFormValue(form, "sine_max_speed"),
    min_period_sec: axisFormValue(form, "sine_min_period"),
    max_period_sec: axisFormValue(form, "sine_max_period"),
  };
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

function axisJogKey(axis, direction) {
  return `${axis}:${direction}`;
}

function stopAxisJog(axis, form = null) {
  clearAxisJogState(axis);
  return sendAxisJogCommand(axis, 0, form, `${axis} jog stopped`, { lightweight: true });
}

function clearAxisJogState(axis) {
  [...activeAxisJogs.keys()]
    .filter((key) => key.startsWith(`${axis}:`))
    .forEach((key) => {
      const state = activeAxisJogs.get(key);
      if (state?.timer) clearInterval(state.timer);
      state?.button?.classList.remove("is-pressed");
      activeAxisJogs.delete(key);
    });
}

function startAxisJog(axis, form, button, event) {
  const direction = button.dataset.axisJog;
  if (direction === "stop") {
    stopAxisJog(axis, form);
    return;
  }

  let velocity;
  try {
    velocity = axisJogVelocity(form, direction);
  } catch (error) {
    setAxisControlMessage(form, error.message, "is-error");
    return;
  }

  const key = axisJogKey(axis, direction);
  if (activeAxisJogs.has(key)) return;
  clearAxisJogState(axis);
  const repeatCommand = () => {
    const state = activeAxisJogs.get(key);
    if (!state || state.inFlight) return;
    state.inFlight = true;
    const lightweight = state.started === true;
    state.started = true;
    sendAxisJogCommand(axis, velocity, form, `${axis} jog ${direction}`, { lightweight })
      .finally(() => {
        const latestState = activeAxisJogs.get(key);
        if (latestState) latestState.inFlight = false;
      });
  };
  activeAxisJogs.set(key, { timer: null, velocity, button, inFlight: false, started: false });
  const timer = setInterval(repeatCommand, JOG_COMMAND_INTERVAL_MS);
  activeAxisJogs.get(key).timer = timer;
  button.classList.add("is-pressed");
  button.setPointerCapture?.(event.pointerId);
  repeatCommand();

  const stop = () => {
    if (!activeAxisJogs.has(key)) return;
    const state = activeAxisJogs.get(key);
    if (state?.timer) clearInterval(state.timer);
    activeAxisJogs.delete(key);
    button.classList.remove("is-pressed");
    if (button.hasPointerCapture?.(event.pointerId)) {
      button.releasePointerCapture(event.pointerId);
    }
    sendAxisJogCommand(axis, 0, form, `${axis} jog stopped`, { lightweight: true });
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    window.removeEventListener("blur", stop);
  };

  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
  window.addEventListener("blur", stop);
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
    element.classList.remove("is-ok", "is-error", "is-warning");
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
      station: { name: "", latitude: null, longitude: null, elevation_above_ground_m: 0 },
      motion_limits: {},
      updater: { device_id: "", enabled: true, check_interval_minutes: 15, channel: "main" },
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
disableNativeValidationBubbles();

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
  form.noValidate = true;
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
      const axis = form.dataset.tuningForm;
      if (pendingAutoTuneTuning[axis] && input.name) {
        pendingAutoTuneTuning[axis][input.name] = input.value;
      }
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

document.querySelectorAll("[data-auto-tune]").forEach((button) => {
  button.addEventListener("click", (event) => {
    openAutoTunePanel(button.dataset.autoTune, event);
  });
});

fields.tuningStepInput?.addEventListener("input", updateActiveStep);
fields.tuningStepInput?.addEventListener("change", updateActiveStep);
fields.tuningStepClose?.addEventListener("click", closeStepPanel);
["Azimuth", "Altitude"].forEach((label) => {
  const autoUi = autoTuneUi(label);
  autoUi.close?.addEventListener("click", () => closeAutoTunePanel(label));
  autoTuneSettingInputs(autoUi).forEach(([, input]) => {
    input?.addEventListener("change", () => saveAutoTuneSettings(label));
  });
  autoUi.form?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (autoTuneRunState.running) {
      stopAutoTune(label);
      return;
    }
    try {
      const payload = autoTunePayload(label);
      runAutoTune(label, autoUi.start, {
        payload,
        messageTarget: autoUi.message,
        autoTuneUi: autoUi,
        progress: true,
      });
    } catch (error) {
      addLog("error", `${label} auto tune setup failed: ${error.message}`);
      setTuningMessage({ tuningMessage: autoUi.message }, error.message, "is-error");
    }
  });
});
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
fields.pointingMapCanvas?.addEventListener("click", selectPointingMapPoint);
[fields.pointingLayerSatellite, fields.pointingLayerTerrain, fields.pointingLayerVisibility, fields.pointingLayerGrid].forEach((input) => {
  input?.addEventListener("change", renderPointingModel);
});
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
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      startAxisJog(axis, form, button, event);
    });
    button.addEventListener("click", (event) => {
      event.preventDefault();
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
      const payload = mode === "position" ? axisGotoPositionPayload(axis, form, value) : axisPayload(axis, value);
      sendAxisMotorCommand(axis, mode === "position" ? "goto" : "velocity", payload, form);
    });
  });

  form.querySelectorAll("[data-axis-sine]").forEach((button) => {
    button.addEventListener("click", () => {
      sendAxisSineVelocityCommand(axis, button.dataset.axisSine, form);
    });
  });
});

document.querySelectorAll("[data-settings-tab]").forEach((button) => {
  button.addEventListener("click", () => activateSettingsTab(button.dataset.settingsTab));
});

fields.settingsClose?.addEventListener("click", closeSettingsPanel);
fields.settingsReloadSerials?.addEventListener("click", resetMountServer);
fields.settingsAzimuthSerial?.addEventListener("change", updateSerialMapPreview);
fields.systemUpdateCheck?.addEventListener("click", requestUpdateCheck);
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
  if (activeViewMode === "pointing") renderPointingModel();
});

initializeFloatingWindows();
setViewMode(activeViewMode, { persist: false });
loadAppSettings();
loadSystemInfo({ quiet: true });
addLog("message", "Page loaded successfully. Fire Detector dashboard is ready.");
connectStatusStream();
