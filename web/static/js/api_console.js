(() => {
  document.querySelectorAll("select").forEach((select) => select.classList.add("mc-select"));

  function installIndustrialApiLayout() {
    document.documentElement.classList.add("api-console-page");
    document.body.classList.add("industrial-api-layout");

    const sidebar = document.querySelector(".mission-sidebar");
    if (sidebar) {
      sidebar.innerHTML = `
        <div class="industrial-sidebar-brand">
          <img src="/static/img/narit-smart-wildfire-mark.png" alt="NARIT Fire Detector">
          <span><strong>NARIT</strong><small>FIRE DETECTOR</small></span>
        </div>
        <section class="industrial-active-mount" aria-label="Active mount">
          <small>ACTIVE MOUNT</small>
          <strong>NARIT #1</strong>
          <span><i></i> ONLINE</span>
        </section>
        <nav class="industrial-sidebar-nav" aria-label="Primary navigation">
          <small>VIEWS</small>
          <a href="/?view=axis"><i aria-hidden="true"><svg><use href="/static/img/mission-nav-icons.svg#dashboard"></use></svg></i><span>Dashboard</span><kbd>01</kbd></a>
          <a href="/?view=sky"><i aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"></circle><path d="M4 12h16M7 15c2-2 8-2 10 0"></path></svg></i><span>Horizon View</span><kbd>02</kbd></a>
          <a href="/?view=pointing"><i aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"></circle><circle cx="12" cy="12" r="3"></circle><path d="M12 2v3M12 19v3M2 12h3M19 12h3"></path></svg></i><span>Pointing Model</span><kbd>03</kbd></a>
          <a class="active" href="/api-console" aria-current="page"><i aria-hidden="true"><svg><use href="/static/img/mission-nav-icons.svg#api"></use></svg></i><span>API</span><kbd>04</kbd></a>
          <a href="/?view=camera"><i aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="13" height="12" rx="2"></rect><path d="m16 10 5-3v10l-5-3z"></path></svg></i><span>Camera View</span><kbd>05</kbd></a>
          <small>INSIGHTS</small>
          <a href="/#event-log"><i aria-hidden="true"><svg><use href="/static/img/mission-nav-icons.svg#reports"></use></svg></i><span>Reports</span><kbd>06</kbd></a>
          <a href="/?open=settings"><i aria-hidden="true"><svg><use href="/static/img/mission-nav-icons.svg#settings"></use></svg></i><span>Settings</span><kbd>07</kbd></a>
        </nav>
        <div class="industrial-sidebar-health">
          <small>SYSTEM HEALTH</small>
          <div><i></i><span><strong>All systems nominal</strong><em>API agent monitored live</em></span></div>
        </div>`;
    }

    const header = document.querySelector(".api-console-header");
    if (header) {
      header.innerHTML = `
        <div class="api-console-title">
          <small>MOUNT CONTROL /</small>
          <strong>API CONSOLE</strong>
          <p>Local Control Interface · Protocol 1.0</p>
        </div>
        <div class="api-header-actions">
          <span class="api-connection-state" id="connectionState"><i></i> Checking Agent</span>
          <a class="api-header-button" href="/API-Doc/Mount-Agent-API-Guide-TH.pdf" target="_blank" rel="noopener">คู่มือ API</a>
          <a class="api-header-button primary" href="/?view=axis">Dashboard</a>
        </div>`;
    }
  }

  installIndustrialApiLayout();

  function randomToken() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID().replaceAll("-", "");
    if (globalThis.crypto?.getRandomValues) {
      const bytes = new Uint8Array(16);
      globalThis.crypto.getRandomValues(bytes);
      return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    }
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
  }

  const sessionId = sessionStorage.getItem("mountApiSession") || randomToken();
  sessionStorage.setItem("mountApiSession", sessionId);
  let leaseId = "";
  let leaseExpiresAt = 0;
  let telemetryBusy = false;
  let latestSnapshot = null;
  let velocityTimer = null;
  let commandMonitorRevision = 0;
  let commandMonitorEvents = [];
  let commandMonitorBusy = false;
  let commandMonitorRunning = 0;

  const $ = (id) => document.getElementById(id);
  const responseOutput = $("responseOutput");
  const pythonOutput = $("pythonOutput");
  const leaseState = $("leaseState");
  const connectionState = $("connectionState");
  const cameraExamples = {
    curl: `# Thermal; เปลี่ยน thermal เป็น visible สำหรับกล้อง Visible
curl -X POST "http://192.168.1.105:8000/api/camera-stream/frame/thermal?source=live" \\
  -H "Content-Type: image/jpeg" \\
  -H 'X-Camera-Metadata: {"captured_at":"2026-08-11T10:30:00.000Z","width":640,"height":512,"producer_sequence":1}' \\
  --data-binary @thermal-frame.jpg`,
    python: `# Binary message: [4-byte JSON header length][JSON header][JPEG/PNG bytes]
import hashlib, json, struct, time
from websockets.sync.client import connect

URL = "ws://192.168.1.105:8000/ws/camera-stream?role=producer&source=live"
payload = open("thermal-frame.jpg", "rb").read()

with connect(URL, max_size=None, compression=None) as socket:
    next_frame = time.monotonic()
    for sequence in range(1, 1000000):
        header = json.dumps({
            "camera": "thermal",
            "mime_type": "image/jpeg",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "metadata": {"producer_sequence": sequence},
        }, separators=(",", ":")).encode()
        socket.send(struct.pack(">I", len(header)) + header + payload)
        next_frame += 1 / 60
        time.sleep(max(0, next_frame - time.monotonic()))`,
    response: `HTTP/1.1 202 Accepted
Content-Type: application/json

{
  "ok": true,
  "camera": "thermal",
  "source": "live",
  "sequence": 1234
}

# Status
GET /api/camera-stream`,
  };
  let selectedCameraExample = "curl";

  function uniqueId(prefix = "web") {
    return `${prefix}-${randomToken()}`;
  }

  function commandMonitorTime(timestamp) {
    const value = new Date(timestamp);
    if (Number.isNaN(value.getTime())) return "--:--:--.---";
    return value.toLocaleTimeString([], {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      fractionalSecondDigits: 3,
    });
  }

  function commandTimingValue(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(number >= 100 ? 1 : 2) : "--";
  }

  function renderCommandMonitor() {
    const list = $("commandMonitorList");
    if (!list) return;
    const includePolls = $("showStatusPolls").checked;
    const visible = commandMonitorEvents.slice().reverse();
    list.replaceChildren();
    $("commandMonitorCount").textContent = String(visible.length);
    $("commandMonitorRunning").textContent = String(commandMonitorRunning);
    const latest = visible[0];
    $("commandMonitorLatency").textContent = latest ? commandTimingValue(latest.total_ms) : "--";
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.className = "command-monitor-empty";
      empty.textContent = includePolls ? "Waiting for API commands…" : "Waiting for commands (automatic status polls hidden)…";
      list.append(empty);
      return;
    }

    for (const event of visible) {
      const item = document.createElement("article");
      const total = Number(event.total_ms);
      const latencyClass = Number.isFinite(total) && total >= 250
        ? " is-slow"
        : Number.isFinite(total) && total >= 100 ? " is-warning" : "";
      item.className = `command-trace is-${event.state || "running"}${latencyClass}`;

      const header = document.createElement("div");
      header.className = "command-trace-header";
      const identity = document.createElement("div");
      const time = document.createElement("time");
      time.dateTime = event.received_at || "";
      time.title = event.received_at || "";
      time.textContent = commandMonitorTime(event.received_at);
      const action = document.createElement("strong");
      action.textContent = event.action || "<missing action>";
      identity.append(time, action);
      const totalLabel = document.createElement("b");
      totalLabel.textContent = event.state === "running" ? "RUNNING" : `${commandTimingValue(event.total_ms)} ms`;
      header.append(identity, totalLabel);

      const meta = document.createElement("p");
      meta.className = "command-trace-meta";
      meta.textContent = `${event.source || "unknown"} · ${event.message_id || "no message id"}`;

      const timing = document.createElement("div");
      timing.className = "command-trace-timing";
      for (const [label, value] of [
        ["Policy", event.policy_ms],
        ["Queue", event.queue_wait_ms],
        ["Exec", event.execution_ms],
        ["Total", event.total_ms],
      ]) {
        const chip = document.createElement("span");
        chip.textContent = `${label} ${commandTimingValue(value)} ms`;
        timing.append(chip);
      }

      const params = document.createElement("pre");
      params.className = "command-trace-params";
      params.textContent = JSON.stringify(event.params || {}, null, 2);

      item.append(header, meta, timing, params);
      if (event.error_code || event.error_message) {
        const error = document.createElement("p");
        error.className = "command-trace-error";
        error.textContent = `${event.error_code || "ERROR"}: ${event.error_message || "Command failed"}`;
        item.append(error);
      }
      list.append(item);
    }
  }

  async function pollCommandMonitor() {
    if (commandMonitorBusy || document.hidden) return;
    commandMonitorBusy = true;
    try {
      const includeAutomatic = $("showStatusPolls").checked ? "true" : "false";
      const response = await fetch(`/api/console/command-monitor?after_revision=${commandMonitorRevision}&limit=100&include_automatic=${includeAutomatic}`, {
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      commandMonitorRevision = Number(data.revision) || 0;
      if (data.changed && Array.isArray(data.events)) commandMonitorEvents = data.events;
      commandMonitorRunning = Number(data.running) || 0;
      renderCommandMonitor();
      $("commandMonitorState").classList.remove("offline");
    } catch {
      $("commandMonitorState").classList.add("offline");
    } finally {
      commandMonitorBusy = false;
    }
  }

  const leaseExemptActions = new Set([
    "system.hello", "system.ping", "system.get_info", "system.get_health",
    "system.get_capabilities", "mount.get_status", "mount.stop", "mount.disable",
    "axis.stop", "axis.disable", "control.acquire", "control.renew",
    "control.release", "subscribe", "unsubscribe",
  ]);

  function requiresLease(action) {
    return /^(mount|axis|pointing|calibration|tuning)\./.test(action)
      && !leaseExemptActions.has(action);
  }

  function standalonePython(message) {
    const example = JSON.parse(JSON.stringify(message));
    example.message_id = "python-command";
    delete example.control_lease_id;
    const serialized = JSON.stringify(example, null, 2);
    const messageLiteral = JSON.stringify(serialized);
    const protectedCommand = requiresLease(example.action);
    const acquireBlock = `        lease_response = send_command(stream, {
            "version": "1.0",
            "type": "command",
            "action": "control.acquire",
            "params": {"lease_ms": 30000},
        })
        lease_id = lease_response["result"]["lease_id"]`;
    let executionBlock = "        response = send_command(stream, message)";
    if (example.action === "control.renew") {
      executionBlock = `${acquireBlock}
        message["params"]["lease_id"] = lease_id
        response = send_command(stream, message)
        send_command(stream, {
            "version": "1.0", "type": "command",
            "action": "control.release", "params": {"lease_id": lease_id},
        })`;
    } else if (example.action === "control.release") {
      executionBlock = `${acquireBlock}
        message["params"]["lease_id"] = lease_id
        response = send_command(stream, message)`;
    } else if (protectedCommand) {
      executionBlock = `${acquireBlock}
        message["control_lease_id"] = lease_id
        try:
            response = send_command(stream, message)
        finally:
            send_command(stream, {
                "version": "1.0", "type": "command",
                "action": "control.release", "params": {"lease_id": lease_id},
            })`;
    }
    return `#!/usr/bin/env python3
"""Mount Agent API example: ${example.action}."""

import json
import socket
import uuid

SOCKET_PATH = "/run/fire-detector/mount-agent.sock"


def send_command(stream, message):
    message["message_id"] = str(uuid.uuid4())
    wire = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\\n"
    stream.write(wire)
    stream.flush()
    response_line = stream.readline()
    if not response_line:
        raise ConnectionError("Mount Agent closed the connection.")
    response = json.loads(response_line)
    if not response.get("ok"):
        raise RuntimeError(response.get("error", response))
    return response


message = json.loads(${messageLiteral})

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.connect(SOCKET_PATH)
    with client.makefile("rwb") as stream:
${executionBlock}
print("Action:", message["action"])
print("Response:")
print(json.dumps(response, indent=2, ensure_ascii=False))
`;
  }

  function showCommandExample(message) {
    const example = JSON.parse(JSON.stringify(message));
    $("jsonEditor").value = JSON.stringify(example, null, 2);
    $("pythonEditor").value = standalonePython(example);
    pythonOutput.textContent = `Generated a complete Python example for ${example.action}.`;
  }

  async function post(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...payload, session_id: sessionId}),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || `HTTP ${response.status}`);
    return body;
  }

  async function sendMessage(message, {quiet = false} = {}) {
    message.message_id = !message.message_id || message.message_id === "browser-command"
      ? uniqueId() : message.message_id;
    if (leaseId && !message.control_lease_id) message.control_lease_id = leaseId;
    const result = await post("/api/console/command", {message});
    connectionState.className = "api-connection-state online";
    connectionState.lastChild.textContent = " Agent Online";
    if (!quiet) responseOutput.textContent = JSON.stringify(result, null, 2);
    const errorCode = result.error?.code || "";
    if (errorCode === "CONTROL_LEASE_REQUIRED" || errorCode === "CONTROL_LEASE_INVALID") {
      setLease("", 0);
    }
    updateSnapshot(result.result);
    return result;
  }

  async function quickAction(action, params = {}) {
    const message = {
      version: "1.0", type: "command", message_id: uniqueId(),
      action, params,
    };
    if (leaseId) message.control_lease_id = leaseId;
    showCommandExample(message);
    try {
      return await sendMessage(message);
    } catch (error) {
      responseOutput.textContent = `ERROR\n${error.message}`;
      throw error;
    }
  }

  function updateSnapshot(snapshot) {
    if (!snapshot || !Array.isArray(snapshot.axes)) return;
    latestSnapshot = snapshot;
    for (const axis of snapshot.axes) {
      const position = Number(axis.position_deg);
      if (axis.label === "Azimuth") $("azimuthApiPosition").textContent = Number.isFinite(position) ? position.toFixed(3) : "--";
      if (axis.label === "Altitude") $("altitudeApiPosition").textContent = Number.isFinite(position) ? position.toFixed(3) : "--";
    }
    $("driveApiState").textContent = snapshot.connected ? "Online" : "Offline";
    updateMotionReadiness();
  }

  function setLease(id, durationMs) {
    leaseId = id || "";
    leaseExpiresAt = leaseId ? Date.now() + durationMs : 0;
    if (!leaseId) stopVelocityRefresh();
    updateLeaseDisplay();
    updateMotionReadiness();
  }

  function updateLeaseDisplay() {
    const remaining = Math.max(0, Math.ceil((leaseExpiresAt - Date.now()) / 1000));
    if (!leaseId || remaining <= 0) {
      leaseState.textContent = leaseId ? "Lease renewing…" : "No control lease";
      leaseState.classList.toggle("active", Boolean(leaseId));
      return;
    }
    leaseState.textContent = `Lease ${leaseId.slice(0, 8)}… · ${remaining}s`;
    leaseState.classList.add("active");
  }

  function selectedAxisArmed() {
    const selected = $("axisSelect").value.toLowerCase();
    return Boolean(latestSnapshot?.axes?.find(
      (axis) => String(axis.label || "").toLowerCase() === selected && axis.is_armed,
    ));
  }

  function updateMotionReadiness() {
    $("leaseReadyState").classList.toggle("ready", Boolean(leaseId));
    $("axisArmedState").classList.toggle("ready", selectedAxisArmed());
  }

  document.querySelectorAll("[data-quick-action]").forEach((button) => {
    button.addEventListener("click", () => quickAction(button.dataset.quickAction));
  });

  document.querySelectorAll("[data-control-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.controlAction;
      try {
        if (action === "acquire") {
          const response = await quickAction("control.acquire", {lease_ms: 30000});
          if (response.ok) setLease(response.result?.lease_id || "", response.result?.lease_ms || 30000);
        } else if (action === "renew") {
          if (!leaseId) throw new Error("Acquire a control lease first.");
          const response = await quickAction("control.renew", {lease_id: leaseId});
          if (response.ok) setLease(leaseId, response.result?.lease_ms || 30000);
        } else {
          if (!leaseId) throw new Error("There is no active lease.");
          const response = await quickAction("control.release", {lease_id: leaseId});
          if (response.ok) setLease("", 0);
        }
      } catch (error) {
        responseOutput.textContent = `ERROR\n${error.message}`;
      }
    });
  });

  function stopVelocityRefresh() {
    if (velocityTimer) clearInterval(velocityTimer);
    velocityTimer = null;
    $("axisVelocityStart").textContent = "Start Velocity";
  }

  $("emergencyStop").addEventListener("click", () => {
    stopVelocityRefresh();
    quickAction("mount.stop");
  });
  $("axisSelect").addEventListener("change", updateMotionReadiness);
  $("axisGoto").addEventListener("click", async () => {
    const params = {
      axis: $("axisSelect").value,
      position_deg: Number($("positionInput").value),
      max_velocity_deg_per_sec: Number($("speedInput").value),
    };
    if (!leaseId) {
      responseOutput.textContent = "ERROR\nAcquire a control lease before sending Goto.";
      return;
    }
    if (!selectedAxisArmed()) {
      responseOutput.textContent = `NOT READY\n${$("axisSelect").value} is not armed. Press Enable Mount, wait for the Armed indicator, then send Goto.`;
      return;
    }
    await quickAction("axis.goto", params);
  });
  $("axisVelocityStart").addEventListener("click", async () => {
    const axis = $("velocityAxisSelect").value;
    const matchingAxis = latestSnapshot?.axes?.find(
      (item) => String(item.label || "").toLowerCase() === axis,
    );
    if (!leaseId) {
      responseOutput.textContent = "NOT READY\nAcquire a control lease before sending Velocity.";
      return;
    }
    if (!matchingAxis?.is_armed) {
      responseOutput.textContent = `NOT READY\n${axis} is not armed. Press Enable Mount first.`;
      return;
    }
    const params = {
      axis,
      velocity_deg_per_sec: Number($("velocityInput").value),
      command_timeout_ms: Number($("watchdogInput").value),
    };
    const firstResponse = await quickAction("axis.set_velocity", params);
    if (!firstResponse.ok) return;
    stopVelocityRefresh();
    $("axisVelocityStart").textContent = "Velocity Running";
    const refreshMs = Math.max(50, Math.floor(params.command_timeout_ms * 0.5));
    velocityTimer = setInterval(async () => {
      try {
        const response = await sendMessage({
          version:"1.0", type:"command", message_id:uniqueId("velocity"),
          action:"axis.set_velocity", params,
        }, {quiet:true});
        if (!response.ok) stopVelocityRefresh();
      } catch {
        stopVelocityRefresh();
      }
    }, refreshMs);
  });
  $("axisVelocityStop").addEventListener("click", () => {
    stopVelocityRefresh();
    quickAction("axis.stop", {axis: $("velocityAxisSelect").value});
  });
  $("velocityAxisSelect").addEventListener("change", stopVelocityRefresh);

  $("formatJson").addEventListener("click", () => {
    try { $("jsonEditor").value = JSON.stringify(JSON.parse($("jsonEditor").value), null, 2); }
    catch (error) { responseOutput.textContent = `INVALID JSON\n${error.message}`; }
  });
  $("sendJson").addEventListener("click", async () => {
    try {
      const message = JSON.parse($("jsonEditor").value);
      showCommandExample(message);
      await sendMessage(message);
    }
    catch (error) { responseOutput.textContent = `ERROR\n${error.message}`; }
  });
  $("jsonEditor").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault(); $("sendJson").click();
    }
  });
  $("clearOutput").addEventListener("click", () => { responseOutput.textContent = ""; });

  $("resetPython").addEventListener("click", () => {
    try {
      showCommandExample(JSON.parse($("jsonEditor").value));
    } catch (error) {
      pythonOutput.textContent = `INVALID JSON\n${error.message}`;
    }
  });
  $("copyPython").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("pythonEditor").value);
      pythonOutput.textContent = "Full Python example copied to the clipboard.";
    } catch {
      $("pythonEditor").focus();
      $("pythonEditor").select();
      pythonOutput.textContent = "Select-all is ready. Press Ctrl/Cmd+C to copy.";
    }
  });

  function showCameraExample(name) {
    selectedCameraExample = cameraExamples[name] ? name : "curl";
    $("cameraApiExample").textContent = cameraExamples[selectedCameraExample];
    document.querySelectorAll("[data-camera-example]").forEach((button) => {
      const active = button.dataset.cameraExample === selectedCameraExample;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  async function refreshCameraStatus() {
    try {
      const response = await fetch("/api/camera-stream", {cache: "no-store"});
      const result = await response.json();
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const live = result.sources?.live || {};
      $("cameraApiState").textContent = live.connected ? "Live producer active" : "Waiting for producer";
      $("cameraApiState").classList.toggle("online", live.connected === true);
      $("cameraTestOutput").textContent = JSON.stringify(result, null, 2);
    } catch (error) {
      $("cameraApiState").textContent = "Receiver unavailable";
      $("cameraApiState").classList.remove("online");
      $("cameraTestOutput").textContent = `ERROR\n${error.message}`;
    }
  }

  document.querySelectorAll("[data-camera-example]").forEach((button) => {
    button.addEventListener("click", () => showCameraExample(button.dataset.cameraExample));
  });
  $("copyCameraExample").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(cameraExamples[selectedCameraExample]);
      $("cameraTestOutput").textContent = "คัดลอกตัวอย่างแล้ว";
    } catch {
      $("cameraTestOutput").textContent = "ไม่สามารถใช้ clipboard ได้ กรุณาเลือกข้อความจากกล่องตัวอย่างแล้วคัดลอก";
    }
  });
  $("refreshCameraStatus").addEventListener("click", refreshCameraStatus);
  $("sendCameraFrame").addEventListener("click", async () => {
    const file = $("cameraUploadFile").files?.[0];
    const camera = $("cameraUploadType").value;
    if (!file) {
      $("cameraTestOutput").textContent = "กรุณาเลือกไฟล์ JPEG หรือ PNG ก่อน";
      return;
    }
    if (!["image/jpeg", "image/png"].includes(file.type)) {
      $("cameraTestOutput").textContent = "รองรับเฉพาะ image/jpeg และ image/png";
      return;
    }
    $("sendCameraFrame").disabled = true;
    $("cameraTestOutput").textContent = `กำลังส่ง ${file.name}…`;
    try {
      const response = await fetch(`/api/camera-stream/frame/${camera}?source=live`, {
        method: "POST",
        headers: {
          "Content-Type": file.type,
          "X-Camera-Metadata": JSON.stringify({source: "api-console", filename: file.name, captured_at: new Date().toISOString()}),
        },
        body: file,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      $("cameraTestOutput").textContent = JSON.stringify(result, null, 2);
      await refreshCameraStatus();
    } catch (error) {
      $("cameraTestOutput").textContent = `ERROR\n${error.message}`;
    } finally {
      $("sendCameraFrame").disabled = false;
    }
  });
  $("runPython").addEventListener("click", async () => {
    pythonOutput.textContent = "Running the equivalent protected API command...";
    try {
      const message = JSON.parse($("jsonEditor").value);
      const result = await sendMessage(message);
      pythonOutput.textContent = JSON.stringify(result, null, 2);
    } catch (error) {
      pythonOutput.textContent = `ERROR\n${error.message}`;
    }
  });

  $("showStatusPolls").addEventListener("change", () => {
    commandMonitorRevision = -1;
    pollCommandMonitor();
  });
  $("clearCommandMonitor").addEventListener("click", async () => {
    $("clearCommandMonitor").disabled = true;
    try {
      const response = await fetch("/api/console/command-monitor/clear", {method: "POST"});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      commandMonitorEvents = [];
      commandMonitorRunning = 0;
      commandMonitorRevision = Number(data.revision) || 0;
      renderCommandMonitor();
    } catch (error) {
      responseOutput.textContent = `COMMAND MONITOR ERROR\n${error.message}`;
    } finally {
      $("clearCommandMonitor").disabled = false;
    }
  });

  async function pollStatus() {
    if (!$("telemetryToggle").checked || telemetryBusy) return;
    telemetryBusy = true;
    try {
      const result = await sendMessage({
        version:"1.0", type:"command", message_id:uniqueId("poll"),
        action:"mount.get_status", params:{},
      }, {quiet:true});
      updateSnapshot(result.result);
    } catch {
      connectionState.className = "api-connection-state offline";
      connectionState.lastChild.textContent = " Agent Offline";
    } finally { telemetryBusy = false; }
  }

  showCommandExample(JSON.parse($("jsonEditor").value));
  showCameraExample("curl");
  refreshCameraStatus();
  pollStatus();
  pollCommandMonitor();
  setInterval(pollStatus, 1000);
  setInterval(pollCommandMonitor, 500);
  setInterval(updateLeaseDisplay, 1000);
  setInterval(async () => {
    if (!leaseId || leaseExpiresAt - Date.now() > 15000) return;
    const renewingLease = leaseId;
    try {
      const response = await sendMessage({
        version:"1.0", type:"command", message_id:uniqueId("renew"),
        action:"control.renew", params:{lease_id:renewingLease},
      }, {quiet:true});
      if (response.ok && leaseId === renewingLease) {
        setLease(renewingLease, response.result?.lease_ms || 30000);
      }
    } catch {
      if (leaseId === renewingLease) setLease("", 0);
    }
  }, 5000);
  window.addEventListener("pagehide", stopVelocityRefresh);
})();
