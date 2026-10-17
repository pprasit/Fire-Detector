/**
 * Integrated Fire Surveillance & PTZ Sentry Web Client
 */

document.addEventListener("DOMContentLoaded", () => {
    // Elements
    const systemTime = document.getElementById("system-time");
    const statusBanner = document.getElementById("status-banner");
    const bannerIcon = document.getElementById("banner-icon");
    const bannerText = document.getElementById("banner-text");

    const aiLatencyTag = document.getElementById("ai-latency-tag");

    const valMissionState = document.getElementById("val-mission-state");
    const valAz = document.getElementById("val-az");
    const valAlt = document.getElementById("val-alt");
    const valLockedPos = document.getElementById("val-locked-pos");
    const valConfirmedCount = document.getElementById("val-confirmed-count");

    const compassNeedle = document.getElementById("compass-needle");
    const compassAzTxt = document.getElementById("compass-az-txt");
    const compassAltTxt = document.getElementById("compass-alt-txt");

    const btnStartSentry = document.getElementById("btn-start-sentry");
    const btnStopSentry = document.getElementById("btn-stop-sentry");
    const btnZoomIn = document.getElementById("btn-zoom-in");
    const btnZoomOut = document.getElementById("btn-zoom-out");

    // Scan Mode & Calculation Selectors State
    let currentScanMode = "CONTINUOUS";
    let currentStepCalc = "DEGREE";

    // Hotspot Incident Comparison State
    let hotspotCompareMode = "INITIAL"; // "INITIAL" or "PREVIOUS"
    let currentIncidentData = null;

    // =========================================================================
    // Mount Polar Plot & Waypoint Trajectory Engine
    // =========================================================================
    const polarCanvas = document.getElementById("polar-canvas");
    const polarCtx = polarCanvas ? polarCanvas.getContext("2d") : null;

    let polarLiveAz = 0.0;
    let polarLiveAlt = 0.0;
    let polarLockedAz = null;
    let polarLockedAlt = null;
    let polarCurrentPlan = null;

    const polarDispAz = document.getElementById("polar-disp-az");
    const polarDispAlt = document.getElementById("polar-disp-alt");
    const polarDispScanRange = document.getElementById("polar-disp-scan-range");
    const polarDispAiStep = document.getElementById("polar-disp-ai-step");

    function altToRadius(alt, maxR) {
        // Alt scale: -20° (ground ring) to +90° (zenith center)
        const minAltScale = -20.0;
        const maxAltScale = 90.0;
        const clamped = Math.max(minAltScale, Math.min(maxAltScale, alt));
        const norm = (maxAltScale - clamped) / (maxAltScale - minAltScale);
        return maxR * norm;
    }

    function altAzToCanvas(az, alt, cx, cy, maxR) {
        const r = altToRadius(alt, maxR);
        const rad = (az - 90) * (Math.PI / 180.0);
        return {
            x: cx + r * Math.cos(rad),
            y: cy + r * Math.sin(rad)
        };
    }

    function drawPolarPlot() {
        if (!polarCanvas || !polarCtx) return;
        const width = polarCanvas.width;
        const height = polarCanvas.height;
        const cx = width / 2;
        const cy = height / 2;
        const maxR = cx - 32;

        polarCtx.clearRect(0, 0, width, height);

        // 1. Draw Altitude Reference Rings
        const altRings = [-20, 0, 30, 60, 90];
        polarCtx.textAlign = "center";
        polarCtx.textBaseline = "middle";
        polarCtx.font = "bold 10px 'JetBrains Mono', monospace";

        altRings.forEach(alt => {
            const r = altToRadius(alt, maxR);
            polarCtx.beginPath();
            if (alt === 0) {
                polarCtx.strokeStyle = "rgba(6, 182, 212, 0.45)"; // Cyan Horizon 0°
                polarCtx.lineWidth = 1.5;
            } else if (alt < 0) {
                polarCtx.strokeStyle = "rgba(239, 68, 68, 0.35)"; // Red Ground -20°
                polarCtx.lineWidth = 1;
            } else {
                polarCtx.strokeStyle = "rgba(255, 255, 255, 0.08)";
                polarCtx.lineWidth = 1;
            }
            polarCtx.arc(cx, cy, r, 0, 2 * Math.PI);
            polarCtx.stroke();

            if (alt < 90) {
                polarCtx.fillStyle = alt === 0 ? "rgba(6, 182, 212, 0.9)" : (alt < 0 ? "rgba(239, 68, 68, 0.85)" : "rgba(255, 255, 255, 0.4)");
                polarCtx.fillText(`${alt}°`, cx + 4, cy - r - 5);
            }
        });

        // 2. Draw Azimuth Radial Axes (8 Directions)
        const azAngles = [0, 45, 90, 135, 180, 225, 270, 315];
        const azLabels = ['N 0°', 'NE', 'E 90°', 'SE', 'S 180°', 'SW', 'W 270°', 'NW'];

        azAngles.forEach((deg, idx) => {
            const rad = (deg - 90) * (Math.PI / 180.0);
            const x = cx + maxR * Math.cos(rad);
            const y = cy + maxR * Math.sin(rad);

            polarCtx.beginPath();
            polarCtx.strokeStyle = "rgba(255, 255, 255, 0.08)";
            polarCtx.moveTo(cx, cy);
            polarCtx.lineTo(x, y);
            polarCtx.stroke();

            const lx = cx + (maxR + 18) * Math.cos(rad);
            const ly = cy + (maxR + 18) * Math.sin(rad);
            polarCtx.fillStyle = (deg % 90 === 0) ? "#38bdf8" : "rgba(255, 255, 255, 0.45)";
            polarCtx.fillText(azLabels[idx], lx, ly);
        });

        // 3. Draw Scan Trajectory Lines & Waypoint Points
        if (polarCurrentPlan && polarCurrentPlan.rows) {
            polarCtx.beginPath();
            polarCtx.strokeStyle = "#a855f7"; // Purple trajectory
            polarCtx.lineWidth = 2;
            polarCtx.setLineDash([4, 4]);

            let first = true;
            polarCurrentPlan.rows.forEach(row => {
                row.points.forEach(pt => {
                    const p = altAzToCanvas(pt.az, pt.alt, cx, cy, maxR);
                    if (first) {
                        polarCtx.moveTo(p.x, p.y);
                        first = false;
                    } else {
                        polarCtx.lineTo(p.x, p.y);
                    }
                });
            });
            polarCtx.stroke();
            polarCtx.setLineDash([]);

            // Waypoints
            polarCtx.fillStyle = "#f59e0b"; // Amber waypoint dot
            polarCurrentPlan.rows.forEach(row => {
                row.points.forEach(pt => {
                    const p = altAzToCanvas(pt.az, pt.alt, cx, cy, maxR);
                    polarCtx.beginPath();
                    polarCtx.arc(p.x, p.y, 3, 0, 2 * Math.PI);
                    polarCtx.fill();
                });
            });
        }

        // 4. Target Locked Fire Indicator (If Active)
        if (polarLockedAz !== null && polarLockedAlt !== null) {
            const lockP = altAzToCanvas(polarLockedAz, polarLockedAlt, cx, cy, maxR);
            polarCtx.beginPath();
            polarCtx.arc(lockP.x, lockP.y, 12, 0, 2 * Math.PI);
            polarCtx.fillStyle = "rgba(239, 68, 68, 0.35)";
            polarCtx.fill();

            polarCtx.beginPath();
            polarCtx.arc(lockP.x, lockP.y, 5, 0, 2 * Math.PI);
            polarCtx.fillStyle = "#ef4444";
            polarCtx.shadowColor = "#ef4444";
            polarCtx.shadowBlur = 14;
            polarCtx.fill();
            polarCtx.shadowBlur = 0;
        }

        // 5. Live PTZ Mount Position Indicator
        const liveP = altAzToCanvas(polarLiveAz, polarLiveAlt, cx, cy, maxR);

        polarCtx.beginPath();
        polarCtx.arc(liveP.x, liveP.y, 11, 0, 2 * Math.PI);
        polarCtx.fillStyle = "rgba(0, 242, 254, 0.25)";
        polarCtx.fill();

        polarCtx.beginPath();
        polarCtx.arc(liveP.x, liveP.y, 5, 0, 2 * Math.PI);
        polarCtx.fillStyle = "#00f2fe";
        polarCtx.shadowColor = "#00f2fe";
        polarCtx.shadowBlur = 12;
        polarCtx.fill();
        polarCtx.shadowBlur = 0;

        polarCtx.beginPath();
        polarCtx.arc(liveP.x, liveP.y, 15, 0, 2 * Math.PI);
        polarCtx.strokeStyle = "#00f2fe";
        polarCtx.lineWidth = 1.5;
        polarCtx.stroke();
    }

    function buildAxisValues(start, end, desiredStep) {
        const rng = Math.abs(end - start);
        if (rng === 0 || desiredStep <= 0) return [start];
        const intervals = rng / desiredStep;
        const pointCount = Math.max(2, Math.round(intervals) + 1);
        const adjustedStep = (end - start) / (pointCount - 1);
        const values = [];
        for (let i = 0; i < pointCount; i++) {
            values.push(Math.round((start + i * adjustedStep) * 100) / 100);
        }
        values[values.length - 1] = Math.round(end * 100) / 100;
        return values;
    }

    function calculateThermalFOV(focalMm) {
        const focal = Math.max(10.0, parseFloat(focalMm) || 31.0);
        const sensorW = 2.0 * 31.0 * Math.tan((14.2 * Math.PI) / 360.0);
        const sensorH = 2.0 * 31.0 * Math.tan((11.4 * Math.PI) / 360.0);
        const hFov = (2.0 * Math.atan(sensorW / (2.0 * focal)) * 180.0) / Math.PI;
        const vFov = (2.0 * Math.atan(sensorH / (2.0 * focal)) * 180.0) / Math.PI;
        return { hFov: Math.round(hFov * 100) / 100, vFov: Math.round(vFov * 100) / 100 };
    }

    function calculateScanPlan() {
        const mode = currentScanMode || "CONTINUOUS";
        const az_start = parseFloat(document.getElementById("input-az-start")?.value || -90);
        const az_end = parseFloat(document.getElementById("input-az-end")?.value || 90);
        const alt_start = parseFloat(document.getElementById("input-alt-start")?.value || -15);
        const alt_end = parseFloat(document.getElementById("input-alt-end")?.value || 5);
        const sweep_speed = Math.max(0.1, parseFloat(document.getElementById("input-scan-speed")?.value || 1.0));
        const focal_len = parseFloat(document.getElementById("input-focal-length")?.value || 31.0);
        const overlap_pct = parseFloat(document.getElementById("input-fov-overlap")?.value || 20.0);
        const goto_speed = Math.max(1.0, parseFloat(document.getElementById("input-max-goto-speed")?.value || 10.0));
        const settle_sec = Math.max(0.1, parseFloat(document.getElementById("input-settle-sec")?.value || 0.5));

        const fov = calculateThermalFOV(focal_len);
        const overlapRatio = Math.max(0.0, Math.min(0.85, overlap_pct / 100.0));

        let az_step = Math.max(0.5, Math.round(fov.hFov * (1.0 - overlapRatio) * 100) / 100);
        let alt_step = Math.max(0.5, Math.round(fov.vFov * (1.0 - overlapRatio) * 100) / 100);

        if (mode === "STEP_SWEEP") {
            if (currentStepCalc === "DEGREE") {
                az_step = Math.max(1.0, parseFloat(document.getElementById("input-step-az")?.value || 12.0));
            }
        }

        // Build Altitude Layers
        const altLayers = [];
        const rng_alt = Math.abs(alt_end - alt_start);
        if (rng_alt < 0.1) {
            altLayers.push(Math.round(alt_start * 100) / 100);
        } else {
            const layersCount = Math.max(2, Math.round(rng_alt / alt_step) + 1);
            const actualAltStep = (alt_end - alt_start) / (layersCount - 1);
            for (let i = 0; i < layersCount; i++) {
                altLayers.push(Math.round((alt_start + i * actualAltStep) * 100) / 100);
            }
            altLayers[altLayers.length - 1] = Math.round(alt_end * 100) / 100;
        }

        // Build Snake Grid Rows
        const azValues = buildAxisValues(az_start, az_end, az_step);
        const rows = [];
        altLayers.forEach((alt, rIdx) => {
            const forward = (rIdx % 2 === 0);
            const rowAz = forward ? azValues : [...azValues].reverse();
            const pts = rowAz.map(az => ({ az, alt }));
            rows.push({ alt: alt, points: pts });
        });

        polarCurrentPlan = { mode: mode, rows: rows };

        if (polarDispScanRange) {
            polarDispScanRange.textContent = `${az_start}° to ${az_end}° (${alt_start}°..${alt_end}°)`;
        }
        if (polarDispAiStep) {
            polarDispAiStep.textContent = `${az_step.toFixed(1)}° (${mode === 'STEP_SWEEP' ? (currentStepCalc === 'FOV_AUTO' ? 'Auto FOV' : 'Step Az') : 'Continuous FOV Step'})`;
        }

        // Update Dashboard Trajectory Ribbon
        const dashLayers = document.getElementById("dash-disp-layers");
        const dashTime = document.getElementById("dash-disp-time");
        if (dashLayers) {
            dashLayers.textContent = `${altLayers.length} Layers (${fov.hFov}°×${fov.vFov}°)`;
        }
        if (dashTime) {
            const azRange = Math.abs(az_end - az_start);
            const totalPanTime = altLayers.length * (azRange / sweep_speed);
            const transitionTime = (altLayers.length - 1) * ((alt_step / goto_speed) + settle_sec);
            const estTotalSec = Math.round(totalPanTime + transitionTime);
            const min = (estTotalSec / 60).toFixed(1);
            dashTime.textContent = `~${estTotalSec}s (${min}m/pass)`;
        }

        drawPolarPlot();
    }

    // Attach listeners on sentry inputs for real-time trajectory recalculation
    ["input-az-start", "input-az-end", "input-alt-start", "input-alt-end", "input-scan-speed", "input-focal-length", "input-fov-overlap", "input-max-goto-speed", "input-settle-sec", "input-step-az", "input-step-dwell"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener("input", calculateScanPlan);
            el.addEventListener("change", calculateScanPlan);
        }
    });

    calculateScanPlan();

    // Clock
    function updateClock() {
        const now = new Date();
        systemTime.textContent = now.toTimeString().split(" ")[0];
    }
    setInterval(updateClock, 1000);
    updateClock();

    // Telemetry Polling (Every 200ms)
    async function fetchTelemetry() {
        try {
            const res = await fetch("/api/telemetry");
            if (!res.ok) return;
            const data = await res.json();

            // 1. Update Latency
            if (aiLatencyTag) aiLatencyTag.textContent = `${data.latency_ms.toFixed(0)} ms`;

            // 2. Update Mission & PTZ Coordinates
            valMissionState.textContent = data.mission.mission_state;
            const azStr = `${data.ptz.az.toFixed(1)}°`;
            const altStr = `${data.ptz.alt.toFixed(1)}°`;

            valAz.textContent = azStr;
            valAlt.textContent = altStr;

            // Update Video Feed Badges & Overlays
            const thAz = document.getElementById("th-az-badge");
            const thAlt = document.getElementById("th-alt-badge");
            const visAz = document.getElementById("vis-az-badge");
            const visAlt = document.getElementById("vis-alt-badge");
            const hudAzmVal = document.getElementById("hud-azm-val");
            const hudAltVal = document.getElementById("hud-alt-val");
            const hudVisAzm = document.getElementById("hud-vis-azm");
            const hudVisAlt = document.getElementById("hud-vis-alt");

            if (thAz) thAz.textContent = azStr;
            if (thAlt) thAlt.textContent = altStr;
            if (visAz) visAz.textContent = azStr;
            if (visAlt) visAlt.textContent = altStr;
            if (hudAzmVal) hudAzmVal.textContent = azStr;
            if (hudAltVal) hudAltVal.textContent = altStr;
            if (hudVisAzm) hudVisAzm.textContent = azStr;
            if (hudVisAlt) hudVisAlt.textContent = altStr;

            if (valLockedPos) {
                if (data.ptz.locked_az > 0 || data.fire_detected) {
                    valLockedPos.textContent = `Az: ${data.ptz.locked_az.toFixed(1)}° / Alt: ${data.ptz.locked_alt.toFixed(1)}°`;
                } else {
                    valLockedPos.textContent = "NONE";
                }
            }
            if (valConfirmedCount) {
                valConfirmedCount.textContent = data.confirmed_count;
            }
            const valMinHits = document.getElementById("val-min-hits");
            if (valMinHits && data.min_hits !== undefined) {
                valMinHits.textContent = `${data.min_hits} Consecutive Cycles`;
            }

            // 3. Update Zoom Telemetry Badges
            const thZoomBadge = document.getElementById("th-zoom-badge");
            const visZoomBadge = document.getElementById("vis-zoom-badge");

            if (thZoomBadge && data.thermal_zoom) {
                thZoomBadge.textContent = `${data.thermal_zoom.focal_mm.toFixed(1)}mm (${data.thermal_zoom.zoom_x.toFixed(1)}x | ${data.thermal_zoom.fov_h.toFixed(1)}°)`;
            }
            if (visZoomBadge && data.visible_zoom) {
                visZoomBadge.textContent = `${data.visible_zoom.focal_mm.toFixed(1)}mm (${data.visible_zoom.zoom_x.toFixed(1)}x | ${data.visible_zoom.fov_h.toFixed(1)}°)`;
            }

            // 4. Update Compass Needle & Polar Plot Live Telemetry
            if (compassNeedle) compassNeedle.style.transform = `rotate(${data.ptz.az}deg)`;
            if (compassAzTxt) compassAzTxt.textContent = `${data.ptz.az.toFixed(1)}°`;
            if (compassAltTxt) compassAltTxt.textContent = `${data.ptz.alt.toFixed(1)}°`;

            polarLiveAz = data.ptz.az;
            polarLiveAlt = data.ptz.alt;
            if (data.ptz.locked_az || data.fire_detected) {
                polarLockedAz = data.ptz.locked_az;
                polarLockedAlt = data.ptz.locked_alt;
            } else {
                polarLockedAz = null;
                polarLockedAlt = null;
            }

            if (polarDispAz) polarDispAz.textContent = azStr;
            if (polarDispAlt) polarDispAlt.textContent = altStr;
            if (polarDispAiStep && data.trigger_mode !== undefined) {
                if (data.trigger_mode === "FIXED_INTERVAL") {
                    const intMs = Math.round((data.infer_interval_sec || 0.2) * 1000);
                    polarDispAiStep.textContent = `${intMs}ms (Continuous AI)`;
                } else {
                    polarDispAiStep.textContent = `${(data.capture_az_step || 5.0).toFixed(1)}° (Az Step)`;
                }
            }

            drawPolarPlot();

            // 5. Update Scan Mode & Waypoint Telemetry
            const valScanMode = document.getElementById("val-scan-mode");
            const itemWaypointProgress = document.getElementById("item-waypoint-progress");
            const valWaypointProgress = document.getElementById("val-waypoint-progress");

            const scanMode = data.mission.scan_mode || "CONTINUOUS";
            if (valScanMode) valScanMode.textContent = scanMode;

            if (itemWaypointProgress && valWaypointProgress) {
                if (scanMode === "STEP_SWEEP" && data.mission.total_waypoints > 0) {
                    itemWaypointProgress.style.display = "flex";
                    valWaypointProgress.textContent = `${data.mission.current_waypoint}/${data.mission.total_waypoints} (L${data.mission.current_layer}/${data.mission.total_layers})`;
                } else {
                    itemWaypointProgress.style.display = "none";
                }
            }

            // 6. Update Motor Arm Status Badge
            const motorArmedBadge = document.getElementById("motor-armed-badge");
            if (motorArmedBadge && data.ptz) {
                if (data.ptz.is_armed) {
                    motorArmedBadge.textContent = " ARMED";
                    motorArmedBadge.style.background = "rgba(16, 185, 129, 0.25)";
                    motorArmedBadge.style.borderColor = "#10b981";
                    motorArmedBadge.style.color = "#34d399";
                } else {
                    motorArmedBadge.textContent = " DISARMED";
                    motorArmedBadge.style.background = "rgba(239, 68, 68, 0.2)";
                    motorArmedBadge.style.borderColor = "#ef4444";
                    motorArmedBadge.style.color = "#f87171";
                }
            }

            // 7. Update Alarm Banner State Machine
            const mState = data.mission.mission_state;
            if (mState === "ALARM_ACTIVE" || data.fire_detected) {
                statusBanner.className = "status-banner banner-alert";
                bannerIcon.textContent = "🚨";
                const inc = data.latest_incident || (data.mission && data.mission.latest_incident);
                const growthInfo = (inc && inc.scan_rounds > 1) ? ` [${inc.growth_trend_label}]` : "";
                bannerText.textContent = `CONFIRMED HOTSPOT DETECTED — TARGET LOCKED @ ${data.ptz.az.toFixed(1)}°${growthInfo}`;
            } else if (mState === "TARGET_CENTERING") {
                statusBanner.className = "status-banner banner-verifying";
                bannerIcon.textContent = "🎯";
                bannerText.textContent = `TARGET CENTERING — ALIGNING PTZ OPTICAL AXIS`;
            } else if (mState === "ZOOMING_IN" || mState === "DEEP_CONFIRMATION") {
                statusBanner.className = "status-banner banner-verifying";
                bannerIcon.textContent = "🔭";
                bannerText.textContent = `TARGET VERIFICATION IN PROGRESS — OPTICAL ZOOM ENGAGED`;
            } else if (mState === "PREPARING_OPTICS") {
                statusBanner.className = "status-banner banner-verifying";
                bannerIcon.textContent = "🔭";
                bannerText.textContent = `PREPARING OPTICS — ADJUSTING ZOOM & AUTO-FOCUS BEFORE SCAN`;
            } else if (mState === "VERIFYING_FOCUS") {
                statusBanner.className = "status-banner banner-verifying";
                bannerIcon.textContent = "🎯";
                bannerText.textContent = `OPTICAL FOCUS STABILIZATION — WAITING FOR SHARP IMAGE`;
            } else if (mState === "ZOOMING_OUT") {
                statusBanner.className = "status-banner banner-verifying";
                bannerIcon.textContent = "🔎";
                bannerText.textContent = `ZOOMING OUT — RETURNING TO WIDE-ANGLE PATROL`;
            } else if (mState === "STEP_MOVING") {
                statusBanner.className = "status-banner banner-normal";
                bannerIcon.textContent = "🔄";
                bannerText.textContent = `STEP SWEEP — MOVING TO WAYPOINT ${data.mission.current_waypoint}/${data.mission.total_waypoints} (${data.ptz.az.toFixed(1)}°, ${data.ptz.alt.toFixed(1)}°)`;
            } else if (mState === "STEP_DWELLING") {
                statusBanner.className = "status-banner banner-verifying";
                bannerIcon.textContent = "🪜";
                bannerText.textContent = `STEP SWEEP — STARE & AI ANALYZING WAYPOINT ${data.mission.current_waypoint}/${data.mission.total_waypoints}`;
            } else if (mState === "PAUSED") {
                statusBanner.className = "status-banner banner-verifying";
                bannerIcon.textContent = "⏸️";
                bannerText.textContent = "AUTONOMOUS SENTRY PAUSED — PRESS START TO RESUME";
            } else if (mState === "IDLE") {
                statusBanner.className = "status-banner banner-normal";
                bannerIcon.textContent = "🛡️";
                bannerText.textContent = "AUTONOMOUS SENTRY STOPPED / STANDBY";
            } else {
                // SEARCH_SWEEP / Continuous Scan
                if (data.verifying_count > 0) {
                    statusBanner.className = "status-banner banner-verifying";
                    bannerIcon.textContent = "🔍";
                    bannerText.textContent = `AUTONOMOUS SENTRY SCANNING — TRACKING CANDIDATES (${data.verifying_count})`;
                } else {
                    statusBanner.className = "status-banner banner-normal";
                    bannerIcon.textContent = "🛡️";
                    bannerText.textContent = scanMode === "STEP_SWEEP"
                        ? "AUTONOMOUS SENTRY ACTIVE — STEP SWEEP MODE"
                        : "AUTONOMOUS SENTRY ACTIVE — CONTINUOUS SWEEP SCAN";
                }
            }

            // 7. Update Fire Incident & Growth Monitor
            const incidentCard = document.getElementById("incident-monitor-card");
            const inc = data.latest_incident || (data.mission && data.mission.latest_incident);

            if (incidentCard && inc) {
                currentIncidentData = inc;
                incidentCard.style.display = "block";
                renderIncidentMonitor(inc);
            }

        } catch (err) {
            console.error("Telemetry error:", err);
        }
    }

    // Incident Growth Timeline Rendering Engine (Renders ALL Historical Rounds)
    let currentLightboxIncident = null;
    let currentLightboxIndex = 0;

    function renderIncidentMonitor(inc) {
        if (!inc) return;

        const incTrendBadge = document.getElementById("inc-trend-badge");
        const incValId = document.getElementById("inc-val-id");
        const incValPos = document.getElementById("inc-val-pos");
        const incValGrowth = document.getElementById("inc-val-growth");
        const incValSlope = document.getElementById("inc-val-slope");
        const incValRounds = document.getElementById("inc-val-rounds");
        const incValTime = document.getElementById("inc-val-time");
        const timelineTrack = document.getElementById("incident-timeline-track");

        const historyList = (inc.history && inc.history.length > 0)
            ? inc.history
            : [{
                timestamp: inc.first_detected,
                area_px: inc.initial_area_px || 0,
                thermal_snapshot: inc.initial_thermal_snapshot,
                azimuth: inc.azimuth,
                altitude: inc.altitude
            }];

        const totalRounds = inc.scan_rounds || historyList.length;
        const initArea = inc.initial_area_px || historyList[0].area_px || 0;
        const currArea = inc.current_area_px || historyList[historyList.length - 1].area_px || 0;
        const totalPct = (inc.total_growth_pct !== undefined && inc.total_growth_pct !== null)
            ? inc.total_growth_pct
            : (initArea > 0 ? parseFloat((((currArea - initArea) / initArea) * 100.0).toFixed(1)) : 0.0);

        let slope = (inc.trend_slope_pct !== undefined && inc.trend_slope_pct !== null) ? inc.trend_slope_pct : null;
        if ((slope === null || (slope === 0.0 && totalRounds >= 2)) && historyList.length >= 2) {
            const n = historyList.length;
            const areas = historyList.map(h => (h.area_px !== undefined ? h.area_px : 0));
            const meanY = areas.reduce((a, b) => a + b, 0) / n;
            const meanX = (n - 1) / 2.0;
            let num = 0.0;
            let den = 0.0;
            for (let i = 0; i < n; i++) {
                num += (i - meanX) * (areas[i] - meanY);
                den += Math.pow(i - meanX, 2);
            }
            const m = den > 0 ? (num / den) : 0.0;
            slope = parseFloat(((m / Math.max(1.0, meanY)) * 100.0).toFixed(1));
        } else if (slope === null) {
            slope = 0.0;
        }

        let trend = inc.growth_trend;
        if (!trend || (trend === "NEW_DETECTION" && totalRounds > 1)) {
            if (slope > 3.0 || (slope > 0 && totalPct > 15.0)) {
                trend = "EXPANDING";
            } else if (slope < -3.0 || (slope < 0 && totalPct < -15.0)) {
                trend = "SHRINKING";
            } else {
                trend = "STABLE";
            }
        }

        if (incValId) incValId.textContent = inc.id || "-";
        if (incValPos) incValPos.textContent = `Az: ${(inc.azimuth || 0).toFixed(1)}° / Alt: ${(inc.altitude || 0).toFixed(1)}°`;
        if (incValRounds) incValRounds.textContent = `${totalRounds} Round${totalRounds > 1 ? 's' : ''}`;
        if (incValTime) incValTime.textContent = inc.last_updated || "-";

        if (incValGrowth) {
            const sign = totalPct > 0 ? "+" : "";
            incValGrowth.textContent = `${initArea} px² → ${currArea} px² (${sign}${totalPct}%)`;
            if (totalPct > 15.0) {
                incValGrowth.className = "stat-val font-mono text-red";
            } else if (totalPct < -15.0) {
                incValGrowth.className = "stat-val font-mono text-emerald";
            } else {
                incValGrowth.className = "stat-val font-mono text-orange";
            }
        }

        if (incValSlope) {
            if (totalRounds > 1) {
                const slopeSign = slope > 0 ? "+" : "";
                incValSlope.textContent = `Slope: ${slopeSign}${slope.toFixed(1)}%/rnd (Across ${totalRounds} Rounds)`;
                if (slope > 3.0) {
                    incValSlope.className = "stat-val font-mono text-red";
                } else if (slope < -3.0) {
                    incValSlope.className = "stat-val font-mono text-emerald";
                } else {
                    incValSlope.className = "stat-val font-mono text-cyan";
                }
            } else {
                incValSlope.textContent = "Baseline Initial Scan (1 Round)";
                incValSlope.className = "stat-val font-mono text-muted";
            }
        }

        if (incTrendBadge) {
            let badgeText = "";
            let badgeClass = "";

            if (totalRounds <= 1) {
                badgeText = "NEW DETECTION";
                badgeClass = "badge-trend badge-trend-new";
            } else if (trend === "EXPANDING") {
                badgeText = `EXPANDING (${slope >= 0 ? '+' : ''}${slope.toFixed(1)}%/rnd)`;
                badgeClass = "badge-trend badge-trend-expanding";
            } else if (trend === "SHRINKING") {
                badgeText = `SHRINKING (${slope.toFixed(1)}%/rnd)`;
                badgeClass = "badge-trend badge-trend-shrinking";
            } else {
                badgeText = `STABLE (${slope >= 0 ? '+' : ''}${slope.toFixed(1)}%/rnd)`;
                badgeClass = "badge-trend badge-trend-stable";
            }

            incTrendBadge.textContent = badgeText;
            incTrendBadge.className = badgeClass;
        }

        // Render Multi-Round Scrollable Thumbnail Cards
        if (timelineTrack) {
            let cardsHtml = "";
            historyList.forEach((item, idx) => {
                const roundNum = idx + 1;
                const isLatest = (idx === historyList.length - 1);
                const isFirst = (idx === 0);
                const tag = isLatest ? `LATEST (R${roundNum})` : (isFirst ? `INIT (R1)` : `ROUND ${roundNum}`);
                const area = item.area_px || 0;
                const imgUrl = item.thermal_snapshot || inc.latest_thermal_snapshot || "";
                const timeOnly = item.timestamp ? (item.timestamp.split(" ")[1] || item.timestamp) : "";
                const cardClass = isLatest ? "timeline-card active-latest" : "timeline-card";

                cardsHtml += `
                    <div class="${cardClass}" data-idx="${idx}" title="Click to view Round ${roundNum} full image">
                        <span class="timeline-tag">${tag}</span>
                        <div class="timeline-thumb-wrap">
                            <img src="${imgUrl}" alt="Round ${roundNum}" class="timeline-thumb" />
                            <span class="timeline-zoom-icon">🔍</span>
                        </div>
                        <span class="timeline-sub font-mono">${area} px²</span>
                        <span class="timeline-time">${timeOnly}</span>
                    </div>
                `;
            });

            timelineTrack.innerHTML = cardsHtml;
            timelineTrack.querySelectorAll(".timeline-card").forEach(card => {
                card.addEventListener("click", () => {
                    const idx = parseInt(card.dataset.idx || "0", 10);
                    openLightboxRound(inc, idx);
                });
            });
        }
    }

    // Timeline Scroll Buttons
    const btnTimelineLeft = document.getElementById("btn-timeline-left");
    const btnTimelineRight = document.getElementById("btn-timeline-right");
    const timelineTrackElem = document.getElementById("incident-timeline-track");

    if (btnTimelineLeft && timelineTrackElem) {
        btnTimelineLeft.addEventListener("click", () => {
            timelineTrackElem.scrollBy({ left: -160, behavior: "smooth" });
        });
    }
    if (btnTimelineRight && timelineTrackElem) {
        btnTimelineRight.addEventListener("click", () => {
            timelineTrackElem.scrollBy({ left: 160, behavior: "smooth" });
        });
    }

    // =========================================================================
    // Image Lightbox / Modal Popup Engine with Interactive Slider Navigation
    // =========================================================================
    const imageModal = document.getElementById("image-modal");
    const imageModalImg = document.getElementById("image-modal-img");
    const imageModalTitle = document.getElementById("image-modal-title");
    const imageModalInfo = document.getElementById("image-modal-info");
    const imageModalCounter = document.getElementById("image-modal-counter");
    const imageModalDownload = document.getElementById("image-modal-download");
    const imageModalClose = document.getElementById("image-modal-close");
    const imageModalBackdrop = document.getElementById("image-modal-backdrop");
    const modalBtnPrev = document.getElementById("modal-btn-prev");
    const modalBtnNext = document.getElementById("modal-btn-next");

    function openLightboxRound(inc, idx) {
        if (!inc) return;
        currentLightboxIncident = inc;
        const historyList = (inc.history && inc.history.length > 0)
            ? inc.history
            : [{
                timestamp: inc.first_detected,
                area_px: inc.initial_area_px || 0,
                thermal_snapshot: inc.initial_thermal_snapshot,
                azimuth: inc.azimuth,
                altitude: inc.altitude
            }];

        const totalRounds = historyList.length;
        if (idx < 0) idx = 0;
        if (idx >= totalRounds) idx = totalRounds - 1;
        currentLightboxIndex = idx;

        const item = historyList[idx];
        const roundNum = idx + 1;
        const imgSrc = item.thermal_snapshot || inc.latest_thermal_snapshot || "";

        if (imageModalImg) {
            imageModalImg.src = imgSrc;
        }
        if (imageModalTitle) {
            imageModalTitle.textContent = `HOTSPOT SNAPSHOT — ROUND ${roundNum} OF ${totalRounds} (${inc.id || 'INCIDENT'})`;
        }
        if (imageModalInfo) {
            const az = (item.azimuth !== undefined ? item.azimuth : (inc.azimuth || 0)).toFixed(1);
            const alt = (item.altitude !== undefined ? item.altitude : (inc.altitude || 0)).toFixed(1);
            imageModalInfo.textContent = `Target: ${item.area_px || 0} px² | Time: ${item.timestamp || '-'} | Az: ${az}°, Alt: ${alt}°`;
        }
        if (imageModalCounter) {
            imageModalCounter.textContent = `${roundNum} / ${totalRounds}`;
        }
        if (imageModalDownload) {
            imageModalDownload.href = imgSrc;
            imageModalDownload.setAttribute("download", `${(inc.id || 'fire')}_Round_${roundNum}.jpg`);
        }

        if (modalBtnPrev) modalBtnPrev.disabled = (idx === 0);
        if (modalBtnNext) modalBtnNext.disabled = (idx === totalRounds - 1);

        if (imageModal) imageModal.style.display = "flex";
    }

    function closeImageModal() {
        if (imageModal) imageModal.style.display = "none";
    }

    if (modalBtnPrev) {
        modalBtnPrev.addEventListener("click", () => {
            if (currentLightboxIncident && currentLightboxIndex > 0) {
                openLightboxRound(currentLightboxIncident, currentLightboxIndex - 1);
            }
        });
    }

    if (modalBtnNext) {
        modalBtnNext.addEventListener("click", () => {
            if (currentLightboxIncident) {
                const hist = currentLightboxIncident.history || [];
                if (currentLightboxIndex < hist.length - 1) {
                    openLightboxRound(currentLightboxIncident, currentLightboxIndex + 1);
                }
            }
        });
    }

    if (imageModalClose) imageModalClose.addEventListener("click", closeImageModal);
    if (imageModalBackdrop) imageModalBackdrop.addEventListener("click", closeImageModal);

    document.addEventListener("keydown", (e) => {
        if (!imageModal || imageModal.style.display !== "flex") return;
        if (e.key === "Escape") {
            closeImageModal();
        } else if (e.key === "ArrowLeft") {
            if (currentLightboxIncident && currentLightboxIndex > 0) {
                openLightboxRound(currentLightboxIncident, currentLightboxIndex - 1);
            }
        } else if (e.key === "ArrowRight") {
            if (currentLightboxIncident) {
                const hist = currentLightboxIncident.history || [];
                if (currentLightboxIndex < hist.length - 1) {
                    openLightboxRound(currentLightboxIncident, currentLightboxIndex + 1);
                }
            }
        }
    });

    setInterval(fetchTelemetry, 200);
    fetchTelemetry();

    // Scan Mode & Calculation Selector Listeners
    const btnModeContinuous = document.getElementById("btn-mode-continuous");
    const btnModeStep = document.getElementById("btn-mode-step");
    const continuousParamsBlock = document.getElementById("continuous-params-block");
    const stepParamsBlock = document.getElementById("step-params-block");

    const btnCalcDeg = document.getElementById("btn-calc-deg");
    const btnCalcFov = document.getElementById("btn-calc-fov");
    const groupStepAz = document.getElementById("group-step-az");
    const groupStepOverlap = document.getElementById("group-step-overlap");

    if (btnModeContinuous && btnModeStep) {
        btnModeContinuous.addEventListener("click", () => {
            currentScanMode = "CONTINUOUS";
            btnModeContinuous.classList.add("active");
            btnModeStep.classList.remove("active");
            if (continuousParamsBlock) continuousParamsBlock.style.display = "flex";
            if (stepParamsBlock) stepParamsBlock.style.display = "none";
            calculateScanPlan();
        });

        btnModeStep.addEventListener("click", () => {
            currentScanMode = "STEP_SWEEP";
            btnModeStep.classList.add("active");
            btnModeContinuous.classList.remove("active");
            if (continuousParamsBlock) continuousParamsBlock.style.display = "none";
            if (stepParamsBlock) stepParamsBlock.style.display = "flex";
            calculateScanPlan();
        });
    }

    if (btnCalcDeg && btnCalcFov) {
        btnCalcDeg.addEventListener("click", () => {
            currentStepCalc = "DEGREE";
            btnCalcDeg.classList.add("active");
            btnCalcFov.classList.remove("active");
            if (groupStepAz) groupStepAz.style.display = "flex";
            if (groupStepOverlap) groupStepOverlap.style.display = "none";
            calculateScanPlan();
        });

        btnCalcFov.addEventListener("click", () => {
            currentStepCalc = "FOV_AUTO";
            btnCalcFov.classList.add("active");
            btnCalcDeg.classList.remove("active");
            if (groupStepAz) groupStepAz.style.display = "none";
            if (groupStepOverlap) groupStepOverlap.style.display = "flex";
            calculateScanPlan();
        });
    }

    // Control Handlers
    async function sendPTZAction(payload) {
        try {
            await fetch("/api/ptz/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } catch (e) {
            console.error("PTZ Control failed:", e);
        }
    }

    if (btnStartSentry) {
        btnStartSentry.addEventListener("click", () => {
            const azStart = parseFloat(document.getElementById("input-az-start")?.value || -90.0);
            const azEnd = parseFloat(document.getElementById("input-az-end")?.value || 90.0);
            const altStart = parseFloat(document.getElementById("input-alt-start")?.value || -15.0);
            const altEnd = parseFloat(document.getElementById("input-alt-end")?.value || 5.0);
            const speed = parseFloat(document.getElementById("input-scan-speed")?.value || 1.0);
            const focalLength = parseFloat(document.getElementById("input-focal-length")?.value || 31.0);
            const fovOverlap = parseFloat(document.getElementById("input-fov-overlap")?.value || 20.0);
            const maxGotoSpeed = parseFloat(document.getElementById("input-max-goto-speed")?.value || 10.0);
            const settleSec = parseFloat(document.getElementById("input-settle-sec")?.value || 0.5);

            const stepAz = parseFloat(document.getElementById("input-step-az")?.value || 12.0);
            const stepDwell = parseFloat(document.getElementById("input-step-dwell")?.value || 1.5);

            sendPTZAction({
                action: "start_sentry",
                scan_mode: currentScanMode,
                step_calc_mode: currentStepCalc,
                az_start: azStart,
                az_end: azEnd,
                alt_start: altStart,
                alt_end: altEnd,
                alt: altStart,
                speed: speed,
                focal_length_mm: focalLength,
                fov_overlap_pct: fovOverlap,
                max_goto_speed: maxGotoSpeed,
                settle_sec: settleSec,
                step_az_deg: stepAz,
                step_overlap_pct: fovOverlap,
                step_dwell_sec: stepDwell,
                step_goto_speed: maxGotoSpeed
            });
        });
    }

    const btnPauseSentry = document.getElementById("btn-pause-sentry");
    if (btnPauseSentry) {
        btnPauseSentry.addEventListener("click", () => {
            console.log("Pausing Sentry...");
            sendPTZAction({ action: "pause_sentry" });
        });
    }

    if (btnStopSentry) {
        btnStopSentry.addEventListener("click", () => {
            console.log("Stopping Sentry & PTZ...");
            sendPTZAction({ action: "stop_sentry" });
        });
    }

    // Motor Arm / Disarm Handlers on Main Dashboard
    document.getElementById("btn-arm-motors-main")?.addEventListener("click", () => {
        sendPTZAction({ action: "enable" });
    });
    document.getElementById("btn-disarm-motors-main")?.addEventListener("click", () => {
        sendPTZAction({ action: "disable" });
    });

    // Zoom Hold Handlers (Press and Hold -> Zoom, Release -> Stop)
    function setupHoldZoom(btn, camId, direction) {
        if (!btn) return;
        let isPressing = false;

        const startZoom = (e) => {
            e.preventDefault();
            if (isPressing) return;
            isPressing = true;
            btn.classList.add("active");
            sendPTZAction({
                action: "zoom_start",
                cam_id: camId,
                direction: direction,
                speed: 0.8
            });
        };

        const stopZoom = (e) => {
            if (!isPressing) return;
            isPressing = false;
            btn.classList.remove("active");
            sendPTZAction({
                action: "zoom_stop",
                cam_id: camId
            });
        };

        btn.addEventListener("mousedown", startZoom);
        btn.addEventListener("mouseup", stopZoom);
        btn.addEventListener("mouseleave", stopZoom);

        btn.addEventListener("touchstart", startZoom, { passive: false });
        btn.addEventListener("touchend", stopZoom);
        btn.addEventListener("touchcancel", stopZoom);
    }

    const btnThZoomIn = document.getElementById("btn-th-zoom-in");
    const btnThZoomOut = document.getElementById("btn-th-zoom-out");
    const btnVisZoomIn = document.getElementById("btn-vis-zoom-in");
    const btnVisZoomOut = document.getElementById("btn-vis-zoom-out");

    setupHoldZoom(btnThZoomIn, "thermal", "in");
    setupHoldZoom(btnThZoomOut, "thermal", "out");
    setupHoldZoom(btnVisZoomIn, "visible", "in");
    setupHoldZoom(btnVisZoomOut, "visible", "out");

    // Focus Handlers
    const btnThFocusNear = document.getElementById("btn-th-focus-near");
    const btnThFocusFar = document.getElementById("btn-th-focus-far");
    const btnVisFocusNear = document.getElementById("btn-vis-focus-near");
    const btnVisFocusFar = document.getElementById("btn-vis-focus-far");

    if (btnThFocusNear) btnThFocusNear.addEventListener("click", () => sendPTZAction({ action: "focus_near", cam_id: "thermal" }));
    if (btnThFocusFar) btnThFocusFar.addEventListener("click", () => sendPTZAction({ action: "focus_far", cam_id: "thermal" }));

    if (btnVisFocusNear) btnVisFocusNear.addEventListener("click", () => sendPTZAction({ action: "focus_near", cam_id: "visible" }));
    if (btnVisFocusFar) btnVisFocusFar.addEventListener("click", () => sendPTZAction({ action: "focus_far", cam_id: "visible" }));

    // =========================================================================
    // Focal Length mm Preset & Slider Controls
    // =========================================================================
    async function sendZoomFocalMM(camId, focalMM) {
        try {
            console.log(`[Zoom] Sending ${camId} -> ${focalMM} mm`);
            const res = await fetch("/api/camera/zoom_mm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ cam_id: camId, focal_mm: parseFloat(focalMM) })
            });
            const data = await res.json();
            console.log(`[Zoom] Response:`, data);
        } catch (e) {
            console.error("Zoom MM failed:", e);
        }
    }

    // Thermal Presets & Slider
    const thPresetBtns = document.querySelectorAll("#th-presets .btn-preset");
    const thSlider = document.getElementById("th-zoom-slider");
    const thSliderVal = document.getElementById("th-slider-val");
    const btnThApplySlider = document.getElementById("btn-th-apply-slider");

    thPresetBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            thPresetBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const mm = parseFloat(btn.dataset.mm);
            if (thSlider) thSlider.value = mm;
            if (thSliderVal) thSliderVal.textContent = mm.toFixed(0);
            sendZoomFocalMM("thermal", mm);
        });
    });

    if (thSlider && thSliderVal) {
        thSlider.addEventListener("input", (e) => {
            thSliderVal.textContent = parseFloat(e.target.value).toFixed(0);
        });
        thSlider.addEventListener("change", (e) => {
            const mm = parseFloat(e.target.value);
            sendZoomFocalMM("thermal", mm);
        });
    }
    if (btnThApplySlider && thSlider) {
        btnThApplySlider.addEventListener("click", () => {
            const mm = parseFloat(thSlider.value);
            sendZoomFocalMM("thermal", mm);
        });
    }

    // Visible Presets & Slider
    const visPresetBtns = document.querySelectorAll("#vis-presets .btn-preset");
    const visSlider = document.getElementById("vis-zoom-slider");
    const visSliderVal = document.getElementById("vis-slider-val");
    const btnVisApplySlider = document.getElementById("btn-vis-apply-slider");

    visPresetBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            visPresetBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const mm = parseFloat(btn.dataset.mm);
            if (visSlider) visSlider.value = mm;
            if (visSliderVal) visSliderVal.textContent = mm.toFixed(1);
            sendZoomFocalMM("visible", mm);
        });
    });

    if (visSlider && visSliderVal) {
        visSlider.addEventListener("input", (e) => {
            visSliderVal.textContent = parseFloat(e.target.value).toFixed(1);
        });
        visSlider.addEventListener("change", (e) => {
            const mm = parseFloat(e.target.value);
            sendZoomFocalMM("visible", mm);
        });
    }
    if (btnVisApplySlider && visSlider) {
        btnVisApplySlider.addEventListener("click", () => {
            const mm = parseFloat(visSlider.value);
            sendZoomFocalMM("visible", mm);
        });
    }


    // =========================================================================
    // Stream Bandwidth Mode Selector (Tailscale / 4G VPN Optimization)
    // =========================================================================
    const bandwidthSelect = document.getElementById("bandwidth-mode-select");
    const thermalImg = document.getElementById("thermal-img");
    const visibleImg = document.getElementById("visible-img");

    // Camera metadata panel: right-click either live frame to inspect its metadata.
    const metadataPanel = document.getElementById("camera-metadata-panel");
    const metadataTitle = document.getElementById("camera-metadata-title");
    const metadataBody = document.getElementById("camera-metadata-body");
    const metadataClose = document.getElementById("camera-metadata-close");
    let metadataRequestId = 0;

    const metadataGroups = [
        {
            title: "FRAME IDENTITY",
            fields: ["captured_at", "camera_id", "width", "height", "producer_sequence", "capture_sequence"]
        },
        {
            title: "OPTICS & FIELD OF VIEW",
            fields: ["focal_length_mm", "zoom_ratio", "zoom_pct", "zoom_x", "fov_h_deg", "fov_v_deg", "fov_d_deg", "is_zooming"]
        },
        {
            title: "MOUNT & MISSION",
            fields: ["azimuth_deg", "altitude_deg", "mission_state", "scan_mode", "is_paused", "current_waypoint", "total_waypoints", "current_layer", "total_layers"]
        },
        {
            title: "DETECTION",
            fields: ["fire_detected"]
        }
    ];

    function closeMetadataPanel() {
        metadataRequestId += 1;
        if (metadataPanel) metadataPanel.hidden = true;
    }

    function placeMetadataPanel(clientX, clientY) {
        if (!metadataPanel) return;
        const margin = 12;
        const offset = 10;
        const panelWidth = metadataPanel.offsetWidth;
        const panelHeight = metadataPanel.offsetHeight;
        let left = clientX + offset;
        let top = clientY + offset;

        if (left + panelWidth + margin > window.innerWidth) {
            left = clientX - panelWidth - offset;
        }
        if (top + panelHeight + margin > window.innerHeight) {
            top = clientY - panelHeight - offset;
        }

        metadataPanel.style.left = `${Math.max(margin, Math.min(left, window.innerWidth - panelWidth - margin))}px`;
        metadataPanel.style.top = `${Math.max(margin, Math.min(top, window.innerHeight - panelHeight - margin))}px`;
    }

    function formatMetadataValue(key, value) {
        if (value === null || value === undefined || value === "") return "—";
        if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
        if (key === "width" || key === "height") return `${value} px`;
        if (key === "focal_length_mm") return `${Number(value).toFixed(1)} mm`;
        if (key === "zoom_ratio") return Number(value).toFixed(3);
        if (key === "zoom_pct") return `${Number(value).toFixed(1)} %`;
        if (key === "zoom_x") return `${Number(value).toFixed(2)} x`;
        if (key.endsWith("_deg")) return `${Number(value).toFixed(2)}°`;
        return String(value);
    }

    function renderMetadata(metadata) {
        if (!metadataBody) return;
        const fragment = document.createDocumentFragment();

        metadataGroups.forEach((group) => {
            const groupTitle = document.createElement("div");
            groupTitle.className = "camera-metadata-group-title";
            groupTitle.textContent = group.title;
            fragment.appendChild(groupTitle);

            group.fields.forEach((key) => {
                const value = metadata[key];
                const row = document.createElement("div");
                row.className = "camera-metadata-row";

                const keyElement = document.createElement("span");
                keyElement.className = "camera-metadata-key";
                keyElement.textContent = key;
                keyElement.title = key;

                const valueElement = document.createElement("span");
                valueElement.className = "camera-metadata-value";
                if (typeof value === "boolean") {
                    valueElement.classList.add(value ? "is-true" : "is-false");
                }
                valueElement.textContent = formatMetadataValue(key, value);

                row.append(keyElement, valueElement);
                fragment.appendChild(row);
            });
        });

        metadataBody.replaceChildren(fragment);
    }

    async function openMetadataPanel(cameraId, clientX, clientY) {
        if (!metadataPanel || !metadataBody || !metadataTitle) return;
        const requestId = ++metadataRequestId;
        const label = cameraId === "thermal" ? "THERMAL" : "VISIBLE";

        metadataPanel.classList.toggle("camera-metadata-thermal", cameraId === "thermal");
        metadataTitle.textContent = `${label} FRAME METADATA`;
        metadataBody.replaceChildren();
        const loading = document.createElement("div");
        loading.className = "camera-metadata-loading";
        loading.textContent = "Loading frame metadata...";
        metadataBody.appendChild(loading);
        metadataPanel.hidden = false;
        requestAnimationFrame(() => placeMetadataPanel(clientX, clientY));

        try {
            const response = await fetch(`/api/camera/metadata/${cameraId}`, { cache: "no-store" });
            const payload = await response.json();
            if (requestId !== metadataRequestId || metadataPanel.hidden) return;
            if (!response.ok || !payload.metadata) {
                throw new Error(payload.message || "Metadata is not available yet");
            }
            renderMetadata(payload.metadata);
            requestAnimationFrame(() => placeMetadataPanel(clientX, clientY));
        } catch (error) {
            if (requestId !== metadataRequestId || metadataPanel.hidden) return;
            const errorElement = document.createElement("div");
            errorElement.className = "camera-metadata-error";
            errorElement.textContent = error.message || "Unable to load frame metadata";
            metadataBody.replaceChildren(errorElement);
            requestAnimationFrame(() => placeMetadataPanel(clientX, clientY));
        }
    }

    [
        [document.querySelector(".stream-thermal .video-frame"), "thermal"],
        [document.querySelector(".stream-visible .video-frame"), "visible"]
    ].forEach(([frameElement, cameraId]) => {
        if (!frameElement) return;
        frameElement.addEventListener("contextmenu", (event) => {
            event.preventDefault();
            openMetadataPanel(cameraId, event.clientX, event.clientY);
        });
    });

    if (metadataClose) metadataClose.addEventListener("click", closeMetadataPanel);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && metadataPanel && !metadataPanel.hidden) {
            closeMetadataPanel();
        }
    });
    document.addEventListener("pointerdown", (event) => {
        if (!metadataPanel || metadataPanel.hidden || metadataPanel.contains(event.target)) return;
        if (event.target.closest && event.target.closest(".video-frame")) return;
        closeMetadataPanel();
    });

    function setStreamMode(mode) {
        if (!mode) mode = "4g";
        localStorage.setItem("stream_bandwidth_mode", mode);
        if (bandwidthSelect) bandwidthSelect.value = mode;

        const ts = Date.now();
        if (thermalImg) {
            thermalImg.src = `/thermal_feed?mode=${mode}&_t=${ts}`;
        }
        if (visibleImg) {
            visibleImg.src = `/visible_feed?mode=${mode}&_t=${ts}`;
        }
    }

    if (bandwidthSelect) {
        const savedMode = localStorage.getItem("stream_bandwidth_mode") || "4g";
        setStreamMode(savedMode);

        bandwidthSelect.addEventListener("change", (e) => {
            setStreamMode(e.target.value);
        });
    }

    // =========================================================================
    // PTZ Manual & Direct Positioning Controls
    // =========================================================================
    const ptzActiveBadge = document.getElementById("ptz-active-badge");
    const manualGotoAz = document.getElementById("manual-goto-az");
    const manualGotoAlt = document.getElementById("manual-goto-alt");
    const manualGotoSpeed = document.getElementById("manual-goto-speed");
    const btnManualGotoExec = document.getElementById("btn-manual-goto-exec");
    const btnCopyCurPos = document.getElementById("btn-copy-cur-pos");
    const manualStepSizeSelect = document.getElementById("manual-step-size");
    const btnManualStop = document.getElementById("btn-manual-stop");

    function setPtzBadge(text, color = "#38bdf8") {
        if (ptzActiveBadge) {
            ptzActiveBadge.textContent = text;
            ptzActiveBadge.style.color = color;
            ptzActiveBadge.style.borderColor = color;
            ptzActiveBadge.style.background = color === "#ef4444" ? "rgba(239,68,68,0.2)" : (color === "#10b981" ? "rgba(16,185,129,0.2)" : "rgba(56,189,248,0.15)");
        }
    }

    // 1. Copy Live Position
    if (btnCopyCurPos) {
        btnCopyCurPos.addEventListener("click", () => {
            if (manualGotoAz) manualGotoAz.value = polarLiveAz.toFixed(1);
            if (manualGotoAlt) manualGotoAlt.value = polarLiveAlt.toFixed(1);
            setPtzBadge("COPIED", "#10b981");
            setTimeout(() => setPtzBadge("READY"), 2000);
        });
    }

    // 2. Preset Buttons
    document.querySelectorAll(".btn-ptz-preset").forEach(btn => {
        btn.addEventListener("click", () => {
            const az = btn.dataset.az;
            const alt = btn.dataset.alt;
            if (manualGotoAz && az !== undefined) manualGotoAz.value = parseFloat(az).toFixed(1);
            if (manualGotoAlt && alt !== undefined) manualGotoAlt.value = parseFloat(alt).toFixed(1);
        });
    });

    // 3. Absolute GOTO Execution
    if (btnManualGotoExec) {
        btnManualGotoExec.addEventListener("click", async () => {
            const az = parseFloat(manualGotoAz?.value || 0.0);
            const alt = parseFloat(manualGotoAlt?.value || 0.0);
            const speed = parseFloat(manualGotoSpeed?.value || 10.0);

            setPtzBadge("SLEWING...", "#f59e0b");
            try {
                const res = await fetch("/api/ptz/control", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        action: "goto",
                        az: az,
                        alt: alt,
                        speed: speed
                    })
                });
                if (res.ok) {
                    setPtzBadge("MOVING", "#38bdf8");
                    setTimeout(() => setPtzBadge("READY"), 3500);
                } else {
                    setPtzBadge("ERROR", "#ef4444");
                }
            } catch (err) {
                console.error("GOTO error:", err);
                setPtzBadge("FAILED", "#ef4444");
            }
        });
    }

    // 4. Incremental Step Move
    async function execStepMove(daz, dalt) {
        const rawStep = parseFloat(manualStepSizeSelect?.value || 5.0);
        const stepSize = Math.max(0.1, Math.min(10.0, isNaN(rawStep) ? 5.0 : rawStep));
        const speed = parseFloat(manualGotoSpeed?.value || 10.0);
        const deltaAz = daz * stepSize;
        const deltaAlt = dalt * stepSize;

        let badgeLabel = "STEP";
        if (deltaAz !== 0 && deltaAlt !== 0) {
            badgeLabel = `STEP ${deltaAz > 0 ? '+' : ''}${deltaAz.toFixed(1)}° / ${deltaAlt > 0 ? '+' : ''}${deltaAlt.toFixed(1)}°`;
        } else if (deltaAz !== 0) {
            badgeLabel = `STEP ${deltaAz > 0 ? '+' : ''}${deltaAz.toFixed(1)}°`;
        } else if (deltaAlt !== 0) {
            badgeLabel = `STEP ${deltaAlt > 0 ? '+' : ''}${deltaAlt.toFixed(1)}°`;
        }
        setPtzBadge(badgeLabel, "#34d399");

        try {
            const res = await fetch("/api/ptz/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action: "step_move",
                    d_az: deltaAz,
                    d_alt: deltaAlt,
                    speed: speed
                })
            });
            if (res.ok) {
                setTimeout(() => setPtzBadge("READY"), 1500);
            } else {
                setPtzBadge("ERROR", "#ef4444");
            }
        } catch (err) {
            console.error("Step move error:", err);
            setPtzBadge("FAILED", "#ef4444");
        }
    }

    document.querySelectorAll(".btn-step-dir").forEach(btn => {
        btn.addEventListener("click", () => {
            const daz = parseFloat(btn.dataset.daz || 0);
            const dalt = parseFloat(btn.dataset.dalt || 0);
            execStepMove(daz, dalt);
        });
    });

    document.querySelectorAll(".btn-quick-step").forEach(btn => {
        btn.addEventListener("click", () => {
            const daz = parseFloat(btn.dataset.daz || 0);
            const dalt = parseFloat(btn.dataset.dalt || 0);
            const speed = parseFloat(manualGotoSpeed?.value || 10.0);

            setPtzBadge(`MICRO ${daz !== 0 ? (daz > 0 ? '+' : '') + daz + '°' : (dalt > 0 ? '+' : '') + dalt + '°'}`, "#34d399");

            fetch("/api/ptz/control", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action: "step_move",
                    d_az: daz,
                    d_alt: dalt,
                    speed: speed
                })
            }).then(() => setTimeout(() => setPtzBadge("READY"), 1200));
        });
    });

    // 5. Emergency Stop
    if (btnManualStop) {
        btnManualStop.addEventListener("click", async () => {
            setPtzBadge("STOPPING", "#ef4444");
            try {
                await fetch("/api/ptz/control", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action: "stop_move" })
                });
                setPtzBadge("STOPPED", "#ef4444");
                setTimeout(() => setPtzBadge("READY"), 2000);
            } catch (err) {
                console.error("Stop error:", err);
            }
        });
    }
});
