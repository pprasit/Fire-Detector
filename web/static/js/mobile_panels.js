(() => {
  "use strict";

  if (!document.documentElement.classList.contains("mobile-browser")) {
    return;
  }

  const storageKey = "narit.dashboard.mobile-panels.v1";
  const definitions = [
    [".status-card.azimuth", ".status-card-header", "azimuth-status"],
    [".chart-panel.azimuth-chart", ".chart-panel-header", "azimuth-chart"],
    [".status-card.altitude", ".status-card-header", "altitude-status"],
    [".chart-panel.altitude-chart", ".chart-panel-header", "altitude-chart"],
    [".system-log-panel", ".system-log-header", "system-log"],
  ];

  const loadState = () => {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return value && typeof value === "object" ? value : {};
    } catch {
      return {};
    }
  };

  const state = loadState();

  const abbreviateTelemetryLabels = () => {
    const labels = [
      [".actual-readout.position strong", "ACT-POS", "Position Actual"],
      [".actual-readout.velocity strong", "ACT-VEL", "Velocity Actual"],
      [".actual-readout.current strong", "ACT-CUR", "Current Actual"],
    ];
    labels.forEach(([selector, shortLabel, fullLabel]) => {
      document.querySelectorAll(selector).forEach((label) => {
        label.textContent = shortLabel;
        label.title = fullLabel;
        label.setAttribute("aria-label", fullLabel);
      });
    });
  };

  const setupStatusAccordions = () => {
    document.querySelectorAll(".status-card[data-axis-card]").forEach((card) => {
      const axis = card.dataset.axisCard;
      const tabList = card.querySelector(":scope > .tab-list");
      if (!axis || !tabList || card.classList.contains("mobile-status-accordion")) {
        return;
      }

      const accordionList = document.createElement("div");
      accordionList.className = "mobile-accordion-list";
      accordionList.setAttribute("aria-label", `${axis} controls`);

      [...tabList.querySelectorAll(":scope > .tab-button")].forEach((button) => {
        const target = button.dataset.tabTarget;
        const panel = card.querySelector(
          `:scope > .tab-panel[data-tab-name="${target}"]`
        );
        if (!target || !panel) {
          return;
        }

        const section = document.createElement("section");
        const stateKey = `accordion-${axis}-${target}`;
        const panelId = `mobile-accordion-${axis.toLowerCase()}-${target}`;
        const defaultExpanded = target === "axis";
        section.className = "mobile-accordion-section";
        section.dataset.mobileAccordionId = stateKey;
        panel.id ||= panelId;

        button.setAttribute("role", "button");
        button.setAttribute("aria-controls", panel.id);
        section.append(button, panel);
        accordionList.append(section);

        const setExpanded = (expanded, persist = true) => {
          section.classList.toggle("is-expanded", expanded);
          button.setAttribute("aria-expanded", String(expanded));
          state[stateKey] = expanded;
          if (persist) {
            saveState();
          }
          announceLayoutChange();
        };

        button.addEventListener("click", () => {
          setExpanded(!section.classList.contains("is-expanded"));
        });

        const savedValue = state[stateKey];
        setExpanded(
          typeof savedValue === "boolean" ? savedValue : defaultExpanded,
          false
        );
      });

      tabList.after(accordionList);
      card.classList.add("mobile-status-accordion");
    });
  };

  const setupMobileTuningGroups = () => {
    const groupDefinitions = [
      {
        id: "control-loop",
        title: "Control Loop",
        fields: [
          "position_gain",
          "velocity_gain",
          "velocity_integrator_gain",
          "velocity_integrator_limit",
          "velocity_integrator_decay_gain",
          "velocity_limit",
          "velocity_limit_tolerance",
          "velocity_ramp_rate",
        ],
      },
      {
        id: "torque-protection",
        title: "Torque & Protection",
        fields: [
          "torque_ramp_rate",
          "torque_soft_min",
          "torque_soft_max",
          "spinout_electrical_power_threshold",
          "spinout_mechanical_power_threshold",
          "spinout_electrical_power_bandwidth",
          "spinout_mechanical_power_bandwidth",
        ],
      },
      {
        id: "filters-model",
        title: "Filters & Model",
        fields: ["encoder_bandwidth", "input_filter_bandwidth", "inertia"],
      },
      {
        id: "trajectory-limits",
        title: "Trajectory Limits",
        fields: ["trap_velocity_limit", "trap_accel_limit", "trap_decel_limit"],
      },
    ];

    document.querySelectorAll(
      ".status-card[data-axis-card] .mobile-accordion-section .tuning-form"
    ).forEach((form) => {
      if (form.classList.contains("mobile-tuning-form")) {
        return;
      }

      const axis = form.dataset.tuningForm || "axis";
      const groups = document.createElement("div");
      groups.className = "mobile-tuning-groups";

      groupDefinitions.forEach((definition, groupIndex) => {
        const labels = definition.fields
          .map((name) => form.querySelector(`:scope > label:has(input[name="${name}"])`))
          .filter(Boolean);
        if (!labels.length) {
          return;
        }

        const section = document.createElement("section");
        const toggle = document.createElement("button");
        const fields = document.createElement("div");
        const stateKey = `tuning-${axis}-${definition.id}`;
        const fieldsId = `mobile-tuning-${axis.toLowerCase()}-${definition.id}`;
        const savedValue = state[stateKey];
        const defaultExpanded = groupIndex === 0;

        section.className = "mobile-tuning-group";
        toggle.className = "mobile-tuning-group-toggle";
        toggle.type = "button";
        toggle.textContent = definition.title;
        toggle.setAttribute("aria-controls", fieldsId);
        fields.className = "mobile-tuning-group-fields";
        fields.id = fieldsId;
        fields.append(...labels);
        section.append(toggle, fields);
        groups.append(section);

        const setExpanded = (expanded, persist = true) => {
          section.classList.toggle("is-expanded", expanded);
          toggle.setAttribute("aria-expanded", String(expanded));
          state[stateKey] = expanded;
          if (persist) {
            saveState();
          }
          announceLayoutChange();
        };

        toggle.addEventListener("click", () => {
          setExpanded(!section.classList.contains("is-expanded"));
        });

        setExpanded(
          typeof savedValue === "boolean" ? savedValue : defaultExpanded,
          false
        );
      });

      form.prepend(groups);
      form.classList.add("mobile-tuning-form");
    });
  };

  const saveState = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(state));
    } catch {
      // The dashboard still works when private browsing blocks localStorage.
    }
  };

  const announceLayoutChange = () => {
    requestAnimationFrame(() => {
      window.dispatchEvent(new Event("resize"));
    });
  };

  const setupMainViewAccordion = () => {
    const buttons = [...document.querySelectorAll("[data-view-mode]")];
    if (!buttons.length || typeof setViewMode !== "function") return;

    const views = {
      axis: document.getElementById("axisView"),
      sky: document.getElementById("skyView"),
      pointing: document.getElementById("pointingView"),
    };
    const shell = document.querySelector(".monitor-shell");
    const header = document.querySelector(".monitor-header");
    const originalToggle = document.querySelector(".view-mode-toggle");
    const cameraToggle = document.getElementById("cameraLiveOpen");
    const cameraWindow = document.getElementById("cameraLiveWindow");
    const systemLog = document.querySelector(".system-log-panel");
    if (!shell || !header || !originalToggle || Object.values(views).some((view) => !view)) return;

    const accordion = document.createElement("div");
    accordion.className = "mobile-main-view-accordion";
    const groups = {};

    buttons.forEach((button) => {
      const mode = button.dataset.viewMode;
      const group = document.createElement("section");
      const content = document.createElement("div");
      group.className = `mobile-main-view-group mobile-main-view-${mode}`;
      content.className = "mobile-main-view-content";
      button.classList.add("mobile-main-view-toggle");
      button.setAttribute("role", "button");
      content.append(views[mode]);
      group.append(button, content);
      accordion.append(group);
      groups[mode] = { group, content };
    });

    let cameraGroup = null;
    let cameraContent = null;
    if (cameraToggle && cameraWindow) {
      cameraGroup = document.createElement("section");
      cameraContent = document.createElement("div");
      cameraGroup.className = "mobile-main-view-group mobile-main-view-camera";
      cameraContent.className = "mobile-main-view-content mobile-camera-control-content";
      cameraToggle.classList.add("mobile-main-view-toggle", "mobile-main-view-camera-toggle");
      cameraToggle.removeAttribute("aria-haspopup");
      cameraToggle.setAttribute("role", "button");
      cameraToggle.setAttribute("aria-controls", "cameraLiveWindow");
      cameraContent.append(cameraWindow);
      cameraGroup.append(cameraToggle, cameraContent);
      accordion.append(cameraGroup);
    }

    header.after(accordion);
    if (systemLog) {
      systemLog.classList.add("mobile-global-system-log");
      accordion.append(systemLog);
    }
    originalToggle.remove();

    const setExpanded = (mode, expanded, persist = true) => {
      buttons.forEach((button) => {
        const isCurrent = button.dataset.viewMode === mode;
        button.setAttribute("aria-expanded", String(isCurrent && expanded));
      });
      Object.entries(groups).forEach(([groupMode, elements]) => {
        elements.group.classList.toggle("is-active", groupMode === mode);
        elements.content.hidden = groupMode !== mode || !expanded;
      });
      document.body.classList.toggle("mobile-main-view-collapsed", !expanded);
      if (!expanded) views[mode].hidden = true;
      state.mainViewExpanded = expanded;
      if (persist) saveState();
      announceLayoutChange();
    };

    const setCameraExpanded = (expanded, persist = true) => {
      if (!cameraGroup || !cameraContent || !cameraWindow || !cameraToggle) return;
      cameraGroup.classList.toggle("is-active", expanded);
      cameraToggle.classList.toggle("active", expanded);
      cameraToggle.setAttribute("aria-expanded", String(expanded));
      cameraContent.hidden = !expanded;
      if (expanded) {
        if (typeof openCameraLiveWindow === "function") openCameraLiveWindow();
        else cameraWindow.hidden = false;
      } else if (typeof closeCameraLiveWindow === "function") {
        closeCameraLiveWindow();
      } else {
        cameraWindow.hidden = true;
      }
      state.cameraControlExpanded = expanded;
      if (persist) saveState();
      announceLayoutChange();
    };

    buttons.forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const mode = button.dataset.viewMode;
        const isOpen = button.classList.contains("active")
          && !document.body.classList.contains("mobile-main-view-collapsed");
        if (isOpen) {
          setExpanded(mode, false);
          return;
        }
        setCameraExpanded(false);
        setViewMode(mode);
        setExpanded(mode, true);
      }, { capture: true });
    });

    cameraToggle?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const expanded = cameraToggle.getAttribute("aria-expanded") === "true";
      if (!expanded) {
        const activeMode = buttons.find((button) => button.classList.contains("active"))?.dataset.viewMode;
        if (activeMode) setExpanded(activeMode, false);
      }
      setCameraExpanded(!expanded);
    }, { capture: true });

    const activeButton = buttons.find((button) => button.classList.contains("active")) || buttons[0];
    if (state.cameraControlExpanded) {
      setExpanded(activeButton.dataset.viewMode, false, false);
      setCameraExpanded(true, false);
    } else {
      setExpanded(activeButton.dataset.viewMode, state.mainViewExpanded !== false, false);
      setCameraExpanded(false, false);
    }
  };

  const setupPointingStaticPanels = () => {
    const pointingView = document.getElementById("pointingView");
    const mapStage = pointingView?.querySelector(".pointing-map-stage");
    const mapSummary = pointingView?.querySelector(".pointing-map-summary");
    const layerControls = pointingView?.querySelector(".pointing-layer-controls");
    const selectionPanel = document.getElementById("pointingSelectionCard");
    const targetPanel = document.getElementById("pointingTargetPanel");
    if (!pointingView || !mapStage) return;

    const panels = document.createElement("div");
    panels.className = "pointing-static-panels";
    panels.setAttribute("aria-label", "Pointing Model details and controls");
    if (mapSummary || layerControls) {
      const mapControlsPanel = document.createElement("section");
      mapControlsPanel.className = "pointing-static-panel pointing-map-controls-panel";
      mapControlsPanel.setAttribute("aria-label", "Pointing Model map settings");
      if (mapSummary) mapControlsPanel.append(mapSummary);
      if (layerControls) mapControlsPanel.append(layerControls);
      panels.append(mapControlsPanel);
    }
    if (selectionPanel) {
      selectionPanel.classList.add("pointing-static-panel");
      panels.append(selectionPanel);
    }
    if (targetPanel) {
      targetPanel.classList.add("pointing-static-panel");
      panels.append(targetPanel);
    }
    mapStage.after(panels);
  };

  const setupPanel = ([panelSelector, headerSelector, panelId]) => {
    const panel = document.querySelector(panelSelector);
    const header = panel?.querySelector(headerSelector);
    if (!panel || !header) {
      return;
    }

    const contentId = `mobile-panel-${panelId}`;
    panel.classList.add("mobile-collapsible");
    panel.dataset.mobilePanelId = panelId;
    header.setAttribute("role", "button");
    header.setAttribute("tabindex", "0");
    header.setAttribute("aria-controls", contentId);

    const toggle = document.createElement("button");
    toggle.className = "mobile-panel-toggle";
    toggle.type = "button";
    toggle.tabIndex = -1;
    toggle.setAttribute("aria-label", "Collapse panel");
    header.append(toggle);

    const contentNodes = [...panel.children].filter((child) => child !== header);
    contentNodes.forEach((node, index) => {
      if (index === 0 && !node.id) {
        node.id = contentId;
      }
    });

    const setCollapsed = (collapsed, persist = true) => {
      panel.classList.toggle("is-mobile-collapsed", collapsed);
      header.setAttribute("aria-expanded", String(!collapsed));
      toggle.setAttribute("aria-label", collapsed ? "Expand panel" : "Collapse panel");
      state[panelId] = collapsed;
      if (persist) {
        saveState();
      }
      announceLayoutChange();
    };

    const togglePanel = () => {
      setCollapsed(!panel.classList.contains("is-mobile-collapsed"));
    };

    header.addEventListener("click", (event) => {
      const interactive = event.target.closest(
        "button, a, input, select, textarea, label"
      );
      if (interactive && interactive !== toggle) {
        return;
      }
      togglePanel();
    });

    header.addEventListener("keydown", (event) => {
      if (event.target !== header || (event.key !== "Enter" && event.key !== " ")) {
        return;
      }
      event.preventDefault();
      togglePanel();
    });

    setCollapsed(Boolean(state[panelId]), false);
  };

  const init = () => {
    abbreviateTelemetryLabels();
    setupMainViewAccordion();
    setupPointingStaticPanels();
    setupStatusAccordions();
    setupMobileTuningGroups();
    definitions.forEach(setupPanel);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
