import * as THREE from "../../vendor/three/three.module.min.js";
import { OrbitControls } from "../../vendor/three/addons/controls/OrbitControls.js";

class PointingTerrain3D {
  constructor() {
    this.canvas = null;
    this.model = null;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this.controls = null;
    this.terrain = null;
    this.satelliteDetail = null;
    this.satellitePrecision = null;
    this.satelliteFocus = null;
    this.satelliteFocusTexture = null;
    this.satelliteFocusKey = "";
    this.satelliteFocusRequest = 0;
    this.satelliteFocusTimer = 0;
    this.focusFeatherTexture = null;
    this.detailHeightTextures = [];
    this.visibility = null;
    this.grid = null;
    this.station = null;
    this.scanCoverage = null;
    this.northIndicator = null;
    this.northLabel = null;
    this.northLabelTexture = null;
    this.mountDirectionIndicator = null;
    this.mountAzimuthDeg = null;
    this.alignmentMarkers = null;
    this.activeAlignmentPointId = "";
    this.focusAnimation = null;
    this.selection = null;
    this.lineOfSight = null;
    this.stationDeviceY = null;
    this.stationGroundY = null;
    this.stationHeightM = 0;
    this.selectionLabel = null;
    this.selectionLabelGrid = null;
    this.selectionLabelLatitude = null;
    this.selectionLabelLongitude = null;
    this.selectionLabelAzimuth = null;
    this.selectionLabelAltitude = null;
    this.selectionLabelGoto = null;
    this.selectionLabelAddModel = null;
    this.selectionLabelClose = null;
    this.dismissedSelectionLabelKey = "";
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.animationFrame = 0;
    this.textureLoader = new THREE.TextureLoader();
    this.earthHandlers = null;
    this.navigationPointer = null;
    this.suppressSelectionUntil = 0;
    this.satelliteEnabled = true;
    this.terrainHeightSampler = null;
    // Match the closest OrbitControls dolly distance. Collision should stop
    // the camera at the DEM surface, not create a visible safety gap above it.
    this.terrainCollisionClearanceM = 0.05;
    this.terrainCollisionLiftM = 0;
  }

  async load(canvas, model, layers, alignmentPoints = []) {
    if (!canvas || !model?.raster?.height_src) return false;
    this.dispose();
    this.canvas = canvas;
    this.model = model;
    this.ensureSelectionLabel();
    const raster = model.raster;
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      logarithmicDepthBuffer: true,
    });
    const satelliteSources = [
      raster.satellite_high_resolution_src,
      raster.satellite_src?.replace(/_satellite\.png(?=\?|$)/, "_satellite.jpg"),
      raster.satellite_src,
    ].filter((source, index, sources) => source && sources.indexOf(source) === index);
    const satelliteDetailSources = [
      raster.satellite_detail_src,
      raster.satellite_high_resolution_src?.replace(/_satellite\.jpg(?=\?|$)/, "_satellite_detail.jpg"),
      raster.satellite_src?.replace(/_satellite\.(?:png|jpg)(?=\?|$)/, "_satellite_detail.jpg"),
    ].filter((source, index, sources) => source && sources.indexOf(source) === index);
    const satellitePrecisionSources = [
      raster.satellite_precision_src,
      raster.satellite_high_resolution_src?.replace(/_satellite\.jpg(?=\?|$)/, "_satellite_precision.jpg"),
      raster.satellite_src?.replace(/_satellite\.(?:png|jpg)(?=\?|$)/, "_satellite_precision.jpg"),
    ].filter((source, index, sources) => source && sources.indexOf(source) === index);
    const supportsHighResolutionTexture = this.renderer.capabilities.maxTextureSize >= 4096;
    const [heightTexture, terrainTexture, satelliteTexture, satelliteDetailTexture, satellitePrecisionTexture, visibilityTexture] = await Promise.all([
      this.loadTexture(raster.height_src, true),
      this.loadTexture(raster.terrain_src || raster.src),
      satelliteSources.length
        ? this.loadFirstAvailableTexture(
            supportsHighResolutionTexture ? satelliteSources : satelliteSources.slice(-1),
            true,
          )
        : null,
      supportsHighResolutionTexture && satelliteDetailSources.length
        ? this.loadFirstAvailableTexture(satelliteDetailSources, true)
        : null,
      satellitePrecisionSources.length
        ? this.loadFirstAvailableTexture(satellitePrecisionSources, true)
        : null,
      raster.visibility_src ? this.loadTexture(raster.visibility_src).catch(() => null) : null,
    ]);

    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x04070e, 1);
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x07101a, 0.000018);

    const widthM = Number(raster.width_m) || Number(model.radius_km) * 2000;
    const depthM = Number(raster.depth_m) || Number(model.radius_km) * 2000;
    // 480 is divisible by both local-imagery ratios (1/4 and 1/20), so the
    // overview, 5 km and 1 km meshes sample the same DEM grid vertices. This
    // prevents overlapping surfaces from fighting at imagery boundaries.
    const widthSegments = 480;
    const heightSegments = 480;
    const elevationMin = Number(raster.elevation_min_m ?? model.dem?.elevation_min_m ?? 0);
    const elevationMax = Number(raster.elevation_max_m ?? model.dem?.elevation_max_m ?? elevationMin + 1);
    const geometry = new THREE.PlaneGeometry(widthM, depthM, widthSegments, heightSegments);
    geometry.rotateX(-Math.PI / 2);

    this.maps = {
      terrain: terrainTexture,
      satellite: satelliteTexture,
      satelliteDetail: satelliteDetailTexture,
      satellitePrecision: satellitePrecisionTexture,
    };
    const imageryAttribution = document.getElementById("pointingImageryAttribution");
    if (imageryAttribution && satelliteTexture) {
      const detailLabels = [];
      if (satellitePrecisionTexture) detailLabels.push("1 km precision · 1.0 m/px");
      if (satelliteDetailTexture) detailLabels.push("5 km detail · 2.4 m/px");
      const attribution = model.imagery?.attribution || "Tiles © Esri and imagery providers";
      imageryAttribution.textContent = `${detailLabels.join(" · ")}${detailLabels.length ? " · " : ""}${attribution}`;
    }
    // Keep elevation in the same metre scale as the east/north axes. The old
    // 3x exaggeration made the surrounding mountains look much taller and also
    // stretched the imagery over steep faces, which amplified visible blur.
    const verticalExaggeration = 1.0;
    this.verticalExaggeration = verticalExaggeration;
    this.elevationMin = elevationMin;
    this.initializeTerrainHeightSampler({
      texture: heightTexture,
      widthM,
      depthM,
      elevationMin,
      elevationMax,
      verticalExaggeration,
    });
    this.material = new THREE.MeshStandardMaterial({
      map: layers?.satellite && satelliteTexture ? satelliteTexture : terrainTexture,
      displacementMap: heightTexture,
      displacementScale: Math.max(0.001, elevationMax - elevationMin) * verticalExaggeration,
      displacementBias: elevationMin,
      roughness: 0.92,
      metalness: 0,
      side: THREE.DoubleSide,
    });
    this.terrain = new THREE.Mesh(geometry, this.material);
    this.terrain.name = "dem-terrain";
    this.scene.add(this.terrain);

    this.satelliteDetail = this.createDetailImageryMesh({
      texture: satelliteDetailTexture,
      heightTexture,
      radiusM: Number(model.imagery?.detail_radius_m) || 5000,
      widthM,
      depthM,
      widthSegments,
      heightSegments,
      elevationMin,
      elevationMax,
      verticalExaggeration,
      name: "station-detail-imagery",
      y: 2,
    });
    this.satellitePrecision = this.createDetailImageryMesh({
      texture: satellitePrecisionTexture,
      heightTexture,
      radiusM: Number(model.imagery?.precision_radius_m) || 1000,
      widthM,
      depthM,
      widthSegments,
      heightSegments,
      elevationMin,
      elevationMax,
      verticalExaggeration,
      name: "station-precision-imagery",
      y: 4,
    });

    if (visibilityTexture) {
      this.visibilityMaterial = new THREE.ShaderMaterial({
        uniforms: {
          visibilityMap: { value: visibilityTexture },
          displacementMap: { value: heightTexture },
          displacementScale: { value: Math.max(0.001, elevationMax - elevationMin) * verticalExaggeration },
          displacementBias: { value: elevationMin },
          layerOpacity: { value: layers?.visibility === false ? 0 : 1 },
        },
        vertexShader: `
          varying vec2 vUv;
          uniform sampler2D displacementMap;
          uniform float displacementScale;
          uniform float displacementBias;
          void main() {
            vUv = uv;
            float height = texture2D(displacementMap, uv).r * displacementScale + displacementBias;
            vec3 displaced = position + normal * height;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(displaced, 1.0);
          }
        `,
        fragmentShader: `
          varying vec2 vUv;
          uniform sampler2D visibilityMap;
          uniform float layerOpacity;
          void main() {
            vec4 source = texture2D(visibilityMap, vUv);
            float coverage = smoothstep(0.01, 0.08, source.a);
            float luminance = dot(source.rgb, vec3(0.2126, 0.7152, 0.0722));
            float visibleClass = smoothstep(0.12, 0.52, luminance);
            float boundary = 1.0 - smoothstep(0.0, 0.28, abs(visibleClass - 0.5));
            vec3 blockedColor = vec3(1.0, 0.22, 0.18);
            vec3 visibleColor = vec3(0.14, 0.96, 0.58);
            vec3 color = mix(blockedColor, visibleColor, visibleClass);
            color = mix(color, vec3(0.95, 1.0, 0.96), boundary * 0.30);
            float alpha = (mix(0.14, 0.23, visibleClass) + boundary * 0.16) * coverage * layerOpacity;
            if (alpha < 0.002) discard;
            gl_FragColor = vec4(color, alpha);
          }
        `,
        transparent: true,
        depthWrite: false,
        polygonOffset: true,
        polygonOffsetFactor: -2,
      });
      this.visibility = new THREE.Mesh(geometry.clone(), this.visibilityMaterial);
      this.visibility.position.y = 4;
      this.visibility.renderOrder = 2;
      this.scene.add(this.visibility);
    }

    this.gridMaterial = new THREE.MeshStandardMaterial({
      color: 0xffc070,
      displacementMap: heightTexture,
      displacementScale: Math.max(0.001, elevationMax - elevationMin) * verticalExaggeration,
      displacementBias: elevationMin,
      emissive: 0xff9b45,
      emissiveIntensity: 0.45,
      wireframe: true,
      transparent: true,
      opacity: layers?.grid === false ? 0 : 0.08,
      depthWrite: false,
    });
    this.grid = new THREE.Mesh(geometry.clone(), this.gridMaterial);
    this.grid.position.y = 7;
    this.grid.renderOrder = 3;
    this.scene.add(this.grid);

    const rawStationGround = Number(model.station?.ground_elevation_m ?? elevationMin);
    const renderedStationGround = this.terrainSurfaceHeightAt(0, 0);
    const stationGround = renderedStationGround ?? (
      elevationMin + (rawStationGround - elevationMin) * verticalExaggeration
    );
    const configuredStationHeightM = Number(model.station?.elevation_above_ground_m);
    const rawStationTop = Number(model.station?.elevation_m ?? rawStationGround);
    const stationHeightM = Math.max(
      0.01,
      Number.isFinite(configuredStationHeightM)
        ? configuredStationHeightM * verticalExaggeration
        : (rawStationTop - rawStationGround) * verticalExaggeration,
    );
    const stationTop = stationGround + stationHeightM;
    this.stationGroundY = stationGround;
    this.stationHeightM = stationHeightM;
    this.stationDeviceY = stationTop;
    // Unit radius lets the footprint scale with zoom while Y remains the true
    // configured installation height (10 m for the current station).
    const markerHeight = stationHeightM;
    const markerGeometry = new THREE.CylinderGeometry(1, 1, markerHeight, 48, 1, false);
    const markerMaterial = new THREE.MeshStandardMaterial({
      color: 0xffd84a,
      emissive: 0xffb52e,
      emissiveIntensity: 0.5,
      transparent: true,
      opacity: 0.84,
      roughness: 0.4,
      metalness: 0.05,
      depthWrite: true,
    });
    this.station = new THREE.Mesh(markerGeometry, markerMaterial);
    this.station.position.set(0, stationGround + markerHeight / 2, 0);
    this.station.renderOrder = 20;
    this.scene.add(this.station);

    const beaconHeight = 2400;
    const beaconGeometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, stationGround + 10, 0),
      new THREE.Vector3(0, stationGround + beaconHeight, 0),
    ]);
    const beaconMaterial = new THREE.LineBasicMaterial({
      color: 0xffe35a,
      transparent: true,
      opacity: 0.98,
      depthTest: false,
    });
    this.stationBeacon = new THREE.Line(beaconGeometry, beaconMaterial);
    this.stationBeacon.renderOrder = 20;
    this.scene.add(this.stationBeacon);
    this.beaconShaft = new THREE.Mesh(
      new THREE.CylinderGeometry(18, 18, beaconHeight, 12),
      new THREE.MeshBasicMaterial({ color: 0xffe35a, depthTest: false }),
    );
    this.beaconShaft.position.set(0, stationGround + beaconHeight / 2, 0);
    this.beaconShaft.renderOrder = 20;
    this.scene.add(this.beaconShaft);

    this.beaconTip = new THREE.Mesh(
      new THREE.ConeGeometry(130, 320, 20),
      new THREE.MeshBasicMaterial({ color: 0xffec70, depthTest: false }),
    );
    this.beaconTip.position.set(0, stationGround + beaconHeight, 0);
    this.beaconTip.rotation.x = Math.PI;
    this.beaconTip.renderOrder = 21;
    this.scene.add(this.beaconTip);

    this.stationRing = new THREE.Mesh(
      new THREE.RingGeometry(150, 230, 48),
      new THREE.MeshBasicMaterial({
        color: 0xffdf45,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.92,
        depthTest: false,
      }),
    );
    this.stationRing.rotation.x = -Math.PI / 2;
    this.stationRing.position.set(0, stationGround + 0.35, 0);
    this.stationRing.renderOrder = 21;
    this.scene.add(this.stationRing);

    // Initial scan-area concept: a north-facing 180 degree sector centered on
    // the station. It intentionally uses lines only so the terrain remains
    // readable beneath the operational overlay.
    const scanRadius = Math.min(
      Number(model.radius_km || 20) * 1000 * 0.75,
      Math.min(widthM, depthM) * 0.375,
    );
    const scanY = stationGround + Math.max(120, markerHeight + 70);
    const scanColor = 0x2ee6c4;
    const scanOuterMaterial = new THREE.MeshBasicMaterial({
      color: scanColor,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.92,
      depthTest: false,
      depthWrite: false,
    });
    const scanGuideMaterial = new THREE.MeshBasicMaterial({
      color: scanColor,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.34,
      depthTest: false,
      depthWrite: false,
    });
    const makeArcRibbon = (radius, width, material, renderOrder) => {
      const segments = 96;
      const positions = [];
      const indices = [];
      const innerRadius = Math.max(0, radius - width / 2);
      const outerRadius = radius + width / 2;
      for (let index = 0; index <= segments; index += 1) {
        const azimuth = -Math.PI / 2 + (Math.PI * index) / segments;
        const sin = Math.sin(azimuth);
        const cos = Math.cos(azimuth);
        positions.push(
          sin * innerRadius, scanY, -cos * innerRadius,
          sin * outerRadius, scanY, -cos * outerRadius,
        );
        if (index < segments) {
          const base = index * 2;
          indices.push(base, base + 1, base + 3, base, base + 3, base + 2);
        }
      }
      const arcGeometry = new THREE.BufferGeometry();
      arcGeometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      arcGeometry.setIndex(indices);
      const arc = new THREE.Mesh(arcGeometry, material);
      arc.renderOrder = renderOrder;
      return arc;
    };
    const makeRadialRibbon = (azimuthDeg, startRadius, endRadius, width, material, renderOrder) => {
      const azimuth = THREE.MathUtils.degToRad(azimuthDeg);
      const direction = new THREE.Vector3(Math.sin(azimuth), 0, -Math.cos(azimuth));
      const perpendicular = new THREE.Vector3(-direction.z, 0, direction.x).multiplyScalar(width / 2);
      const start = direction.clone().multiplyScalar(startRadius);
      const end = direction.clone().multiplyScalar(endRadius);
      const radialGeometry = new THREE.BufferGeometry().setFromPoints([
        start.clone().add(perpendicular).setY(scanY),
        start.clone().sub(perpendicular).setY(scanY),
        end.clone().sub(perpendicular).setY(scanY),
        end.clone().add(perpendicular).setY(scanY),
      ]);
      radialGeometry.setIndex([0, 1, 2, 0, 2, 3]);
      const radial = new THREE.Mesh(radialGeometry, material);
      radial.renderOrder = renderOrder;
      return radial;
    };

    this.scanCoverage = new THREE.Group();
    this.scanCoverage.name = "station-scan-coverage";
    this.scanCoverage.add(makeArcRibbon(scanRadius, 125, scanOuterMaterial, 18));
    this.scanCoverage.add(makeRadialRibbon(-90, 230, scanRadius, 105, scanOuterMaterial, 18));
    this.scanCoverage.add(makeRadialRibbon(90, 230, scanRadius, 105, scanOuterMaterial, 18));
    [scanRadius / 3, scanRadius * 2 / 3].forEach((radius) => {
      this.scanCoverage.add(makeArcRibbon(radius, 58, scanGuideMaterial, 17));
    });
    [-60, -30, 0, 30, 60].forEach((azimuth) => {
      this.scanCoverage.add(makeRadialRibbon(azimuth, 230, scanRadius, 42, scanGuideMaterial, 17));
    });
    this.scene.add(this.scanCoverage);

    // North is -Z in the terrain coordinate system (see offsetLatLon/pick).
    // Keep this marker in the 3D scene so it remains geographically correct
    // while the operator rotates or zooms the model.
    const northColor = 0x38a7ff;
    const northLength = Math.min(widthM, depthM) * 0.18;
    const northHeadLength = Math.min(760, northLength * 0.16);
    const northShaftLength = northLength - northHeadLength;
    const northY = stationGround + Math.max(180, markerHeight + 120);
    this.northIndicator = new THREE.Group();
    this.northIndicator.name = "station-north-indicator";

    const northMaterial = new THREE.MeshBasicMaterial({
      color: northColor,
      depthTest: false,
      transparent: true,
      opacity: 0.98,
    });
    const northShaft = new THREE.Mesh(
      new THREE.CylinderGeometry(76, 76, northShaftLength, 16),
      northMaterial,
    );
    northShaft.position.set(0, northY, -northShaftLength / 2);
    northShaft.rotation.x = -Math.PI / 2;
    northShaft.renderOrder = 24;
    this.northIndicator.add(northShaft);

    const northHead = new THREE.Mesh(
      new THREE.ConeGeometry(310, northHeadLength, 20),
      northMaterial,
    );
    northHead.position.set(0, northY, -(northShaftLength + northHeadLength / 2));
    northHead.rotation.x = -Math.PI / 2;
    northHead.renderOrder = 25;
    this.northIndicator.add(northHead);

    const labelCanvas = document.createElement("canvas");
    labelCanvas.width = 256;
    labelCanvas.height = 128;
    const labelContext = labelCanvas.getContext("2d");
    if (labelContext) {
      labelContext.fillStyle = "rgba(4, 15, 28, 0.88)";
      labelContext.beginPath();
      labelContext.roundRect(44, 8, 168, 112, 24);
      labelContext.fill();
      labelContext.strokeStyle = "#38a7ff";
      labelContext.lineWidth = 7;
      labelContext.stroke();
      labelContext.fillStyle = "#dff3ff";
      labelContext.font = "700 78px sans-serif";
      labelContext.textAlign = "center";
      labelContext.textBaseline = "middle";
      labelContext.fillText("N", 128, 67);
      this.northLabelTexture = new THREE.CanvasTexture(labelCanvas);
      this.northLabelTexture.colorSpace = THREE.SRGBColorSpace;
      const northLabel = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.northLabelTexture,
        depthTest: false,
        transparent: true,
      }));
      northLabel.position.set(0, northY + 650, -(northLength + 260));
      northLabel.renderOrder = 26;
      this.northIndicator.add(northLabel);
      this.northLabel = northLabel;
    }
    this.scene.add(this.northIndicator);

    // The live camera/mount direction uses the direct azimuth convention:
    // 0° north, 90° east, 180° south and 270° west.
    const mountColor = 0x62ef9a;
    const mountLength = northLength * 0.58;
    const mountHeadLength = Math.min(560, mountLength * 0.2);
    const mountShaftLength = mountLength - mountHeadLength;
    const mountY = northY + 210;
    const mountMaterial = new THREE.MeshBasicMaterial({
      color: mountColor,
      depthTest: false,
      transparent: true,
      opacity: 0.98,
    });
    this.mountDirectionIndicator = new THREE.Group();
    this.mountDirectionIndicator.name = "mount-azimuth-indicator";

    const mountShaft = new THREE.Mesh(
      new THREE.CylinderGeometry(68, 68, mountShaftLength, 16),
      mountMaterial,
    );
    mountShaft.position.set(0, mountY, -mountShaftLength / 2);
    mountShaft.rotation.x = -Math.PI / 2;
    mountShaft.renderOrder = 27;
    this.mountDirectionIndicator.add(mountShaft);

    const mountHead = new THREE.Mesh(
      new THREE.ConeGeometry(265, mountHeadLength, 20),
      mountMaterial,
    );
    mountHead.position.set(0, mountY, -(mountShaftLength + mountHeadLength / 2));
    mountHead.rotation.x = -Math.PI / 2;
    mountHead.renderOrder = 28;
    this.mountDirectionIndicator.add(mountHead);
    this.scene.add(this.mountDirectionIndicator);
    this.setMountAzimuth(this.mountAzimuthDeg);

    const glow = new THREE.PointLight(0xffdf45, 3.2, 6000);
    glow.position.set(0, stationTop + 250, 0);
    this.scene.add(glow);

    this.scene.add(new THREE.HemisphereLight(0xd8ecff, 0x172112, 2.1));
    const sunlight = new THREE.DirectionalLight(0xfff1d2, 2.3);
    sunlight.position.set(-16000, 24000, -16000);
    this.scene.add(sunlight);

    this.camera = new THREE.PerspectiveCamera(48, 1, 0.005, 160000);
    this.camera.position.set(widthM * 0.48, Math.max(6200, widthM * 0.21), depthM * 0.62);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(0, elevationMin + (elevationMax - elevationMin) * 0.8, -depthM * 0.08);
    this.controls.enableDamping = true;
    // Double the damping rate so the post-drag glide settles in roughly half
    // the previous time while retaining a small amount of smooth momentum.
    this.controls.dampingFactor = 0.09;
    this.controls.minDistance = 0.05;
    this.controls.maxDistance = 120000;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.zoomToCursor = true;
    this.configureEarthControls(canvas);
    this.controls.update();
    this.anchorOrbitTargetToTerrain();
    this.controls.saveState();
    this.controls.addEventListener("end", () => this.scheduleFocusImagery());
    this.setAlignmentPoints(alignmentPoints);
    this.resize();
    this.applyLayers(layers);
    this.scheduleFocusImagery(0);
    this.animate();
    return true;
  }

  ensureSelectionLabel() {
    let label = document.getElementById("pointingHoverLabel");
    if (!label && this.canvas?.parentElement) {
      label = document.createElement("div");
      label.id = "pointingHoverLabel";
      label.className = "pointing-hover-label";
      label.hidden = true;
      label.setAttribute("aria-live", "polite");
      const closeButton = document.createElement("button");
      closeButton.id = "pointingHoverClose";
      closeButton.className = "pointing-hover-close";
      closeButton.type = "button";
      closeButton.setAttribute("aria-label", "Close grid information");
      closeButton.textContent = "×";
      const grid = document.createElement("strong");
      const gridKey = document.createElement("span");
      const gridValue = document.createElement("b");
      gridKey.textContent = "GRID";
      gridValue.id = "pointingHoverGrid";
      grid.append(gridKey, gridValue);
      const coordinateRow = (key, id) => {
        const row = document.createElement("span");
        const rowKey = document.createElement("b");
        const rowValue = document.createElement("em");
        rowKey.textContent = key;
        rowValue.id = id;
        row.append(rowKey, rowValue);
        return row;
      };
      label.append(
        closeButton,
        grid,
        coordinateRow("LAT", "pointingHoverLatitude"),
        coordinateRow("LON", "pointingHoverLongitude"),
        coordinateRow("AZ", "pointingHoverAzimuth"),
        coordinateRow("ALT", "pointingHoverAltitude"),
      );
      const actions = document.createElement("div");
      actions.className = "pointing-hover-actions";
      const gotoButton = document.createElement("button");
      gotoButton.id = "pointingHoverGoto";
      gotoButton.type = "button";
      gotoButton.textContent = "GO TO";
      const addModelButton = document.createElement("button");
      addModelButton.id = "pointingHoverAddModel";
      addModelButton.type = "button";
      addModelButton.textContent = "ADD TO MODEL";
      actions.append(gotoButton, addModelButton);
      label.append(actions);
      this.canvas.parentElement.append(label);
    }
    this.selectionLabel = label;
    this.selectionLabelGrid = document.getElementById("pointingHoverGrid");
    this.selectionLabelLatitude = document.getElementById("pointingHoverLatitude");
    this.selectionLabelLongitude = document.getElementById("pointingHoverLongitude");
    this.selectionLabelAzimuth = document.getElementById("pointingHoverAzimuth");
    this.selectionLabelAltitude = document.getElementById("pointingHoverAltitude");
    this.selectionLabelGoto = document.getElementById("pointingHoverGoto");
    this.selectionLabelAddModel = document.getElementById("pointingHoverAddModel");
    this.selectionLabelClose = document.getElementById("pointingHoverClose");
    if (this.selectionLabelClose && !this.selectionLabelClose.dataset.bound) {
      this.selectionLabelClose.dataset.bound = "true";
      this.selectionLabelClose.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const selectionKey = this.selection?.userData?.selectionKey;
        if (selectionKey) this.dismissedSelectionLabelKey = selectionKey;
        if (this.selection) this.selection.userData.showLabel = false;
        if (this.selectionLabel) this.selectionLabel.hidden = true;
      });
    }
    if (this.selectionLabelGoto && !this.selectionLabelGoto.dataset.bound) {
      this.selectionLabelGoto.dataset.bound = "true";
      this.selectionLabelGoto.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        window.dispatchEvent(new CustomEvent("pointing-map-goto"));
      });
    }
    if (this.selectionLabelAddModel && !this.selectionLabelAddModel.dataset.bound) {
      this.selectionLabelAddModel.dataset.bound = "true";
      this.selectionLabelAddModel.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        window.dispatchEvent(new CustomEvent("pointing-map-add-model"));
      });
    }
  }

  configureEarthControls(canvas) {
    if (!this.controls || !canvas) return;
    // Desktop map navigation: left or middle drag rotates, right drag pans,
    // and the wheel zooms toward the cursor.
    this.controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
    this.controls.mouseButtons.MIDDLE = THREE.MOUSE.ROTATE;
    this.controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    this.controls.screenSpacePanning = true;
    this.controls.panSpeed = 3;
    this.controls.rotateSpeed = 0.72;
    this.controls.zoomSpeed = 1.35;
    this.controls.keyPanSpeed = 32;
    this.controls.keyRotateSpeed = 1.25;
    canvas.tabIndex = 0;
    this.controls.listenToKeyEvents(canvas);

    const pointerDown = (event) => {
      canvas.focus({ preventScroll: true });
      this.navigationPointer = {
        id: event.pointerId,
        button: event.button,
        startX: event.clientX,
        startY: event.clientY,
        moved: false,
      };
    };
    const pointerMove = (event) => {
      const pointer = this.navigationPointer;
      if (!pointer || pointer.id !== event.pointerId) return;
      if (Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY) > 4) {
        pointer.moved = true;
      }
    };
    const pointerUp = (event) => {
      const pointer = this.navigationPointer;
      if (!pointer || pointer.id !== event.pointerId) return;
      // Suppress only the synthetic click emitted by this drag. A longer
      // window also swallowed a deliberate map click made just after panning.
      if (pointer.moved) this.suppressSelectionUntil = performance.now() + 80;
      this.navigationPointer = null;
      this.scheduleFocusImagery();
    };
    const contextMenu = (event) => event.preventDefault();
    const keyDown = (event) => this.handleEarthKey(event);
    canvas.addEventListener("pointerdown", pointerDown, true);
    canvas.addEventListener("pointermove", pointerMove, true);
    canvas.addEventListener("pointerup", pointerUp, true);
    canvas.addEventListener("pointercancel", pointerUp, true);
    canvas.addEventListener("contextmenu", contextMenu);
    canvas.addEventListener("keydown", keyDown);
    this.earthHandlers = { pointerDown, pointerMove, pointerUp, contextMenu, keyDown };
  }

  updateNavigationSensitivity() {
    if (!this.controls) return;
    // Keep navigation independent of terrain position, viewing angle and the
    // accumulated orbit-target distance. OrbitControls already converts pan
    // drag into the correct perspective scale, so additional distance-based
    // compensation makes otherwise identical locations feel inconsistent.
    this.controls.minDistance = 0.05;
    this.controls.panSpeed = 3;
    this.controls.zoomSpeed = 1.35;
  }

  anchorOrbitTargetToTerrain() {
    if (!this.controls || !this.camera || !this.terrainHeightSampler) return;
    const surfaceY = this.terrainSurfaceHeightAt(this.controls.target.x, this.controls.target.z);
    if (surfaceY === null || !Number.isFinite(surfaceY)) return;
    if (Math.abs(this.controls.target.y - surfaceY) < 0.001) return;
    // Pan and zoom-to-cursor can move OrbitControls.target vertically in world
    // space. Reattach only the target to the DEM; moving the camera with it
    // would preserve the stale floating offset and make close zoom appear
    // blocked after several navigation cycles.
    this.controls.target.y = surfaceY;
    this.camera.lookAt(this.controls.target);
    this.camera.updateMatrixWorld();
  }

  initializeTerrainHeightSampler({
    texture,
    widthM,
    depthM,
    elevationMin,
    elevationMax,
    verticalExaggeration,
  }) {
    this.terrainHeightSampler = null;
    const image = texture?.image;
    const imageWidth = Number(image?.naturalWidth || image?.videoWidth || image?.width);
    const imageHeight = Number(image?.naturalHeight || image?.videoHeight || image?.height);
    if (!image || !imageWidth || !imageHeight || !widthM || !depthM) return;
    try {
      const canvas = document.createElement("canvas");
      canvas.width = imageWidth;
      canvas.height = imageHeight;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return;
      context.drawImage(image, 0, 0, imageWidth, imageHeight);
      const pixels = context.getImageData(0, 0, imageWidth, imageHeight).data;
      this.terrainHeightSampler = {
        pixels,
        imageWidth,
        imageHeight,
        widthM,
        depthM,
        elevationMin,
        elevationRange: Math.max(0.001, elevationMax - elevationMin) * verticalExaggeration,
      };
    } catch (error) {
      // The terrain still renders if a browser refuses canvas readback. In
      // normal same-origin use, this sampler follows the exact DEM texture.
      this.terrainHeightSampler = null;
    }
  }

  terrainHeightAt(eastM, southM) {
    const sampler = this.terrainHeightSampler;
    if (!sampler || !Number.isFinite(eastM) || !Number.isFinite(southM)) return null;
    const u = eastM / sampler.widthM + 0.5;
    // Raster row zero is the north edge; Three.js north is negative Z.
    const v = southM / sampler.depthM + 0.5;
    if (u < 0 || u > 1 || v < 0 || v > 1) return null;
    const x = u * (sampler.imageWidth - 1);
    const y = v * (sampler.imageHeight - 1);
    const x0 = Math.floor(x);
    const y0 = Math.floor(y);
    const x1 = Math.min(x0 + 1, sampler.imageWidth - 1);
    const y1 = Math.min(y0 + 1, sampler.imageHeight - 1);
    const tx = x - x0;
    const ty = y - y0;
    const sample = (pixelX, pixelY) => (
      sampler.pixels[(pixelY * sampler.imageWidth + pixelX) * 4] / 255
    );
    const top = THREE.MathUtils.lerp(sample(x0, y0), sample(x1, y0), tx);
    const bottom = THREE.MathUtils.lerp(sample(x0, y1), sample(x1, y1), tx);
    return sampler.elevationMin + THREE.MathUtils.lerp(top, bottom, ty) * sampler.elevationRange;
  }

  terrainSurfaceHeightAt(eastM, southM) {
    const terrainHeight = this.terrainHeightAt(eastM, southM);
    if (terrainHeight === null) return null;
    let imageryOffsetM = 0;
    [this.satelliteDetail, this.satellitePrecision, this.satelliteFocus].forEach((mesh) => {
      if (!mesh?.visible) return;
      const radiusM = Number(mesh.userData.radiusM);
      if (!Number.isFinite(radiusM)) return;
      if (Math.hypot(eastM - mesh.position.x, southM - mesh.position.z) <= radiusM) {
        imageryOffsetM = Math.max(imageryOffsetM, mesh.position.y);
      }
    });
    return terrainHeight + imageryOffsetM;
  }

  terrainNormalAt(eastM, southM) {
    const sampleStepM = Math.max(2, Math.min(30, this.terrainHeightSampler?.widthM / 1024 || 10));
    const west = this.terrainSurfaceHeightAt(eastM - sampleStepM, southM);
    const east = this.terrainSurfaceHeightAt(eastM + sampleStepM, southM);
    const north = this.terrainSurfaceHeightAt(eastM, southM - sampleStepM);
    const south = this.terrainSurfaceHeightAt(eastM, southM + sampleStepM);
    if ([west, east, north, south].some((height) => height === null)) return new THREE.Vector3(0, 1, 0);
    return new THREE.Vector3(west - east, sampleStepM * 2, north - south).normalize();
  }

  enforceTerrainCollision() {
    if (!this.camera || !this.controls || !this.terrainHeightSampler) return;
    const cameraGround = this.terrainSurfaceHeightAt(this.camera.position.x, this.camera.position.z);
    let liftM = 0;
    if (cameraGround !== null) {
      liftM = Math.max(
        liftM,
        cameraGround + this.terrainCollisionClearanceM - this.camera.position.y,
      );
    }
    if (liftM <= 0) {
      this.terrainCollisionLiftM = 0;
      return;
    }
    // Moving both points by the same amount preserves the current orbit angle
    // and distance, preventing a visible snap when the camera meets the DEM.
    this.camera.position.y += liftM;
    this.controls.target.y += liftM;
    this.terrainCollisionLiftM = liftM;
  }

  releaseTerrainCollisionCorrection() {
    const liftM = Number(this.terrainCollisionLiftM) || 0;
    if (liftM > 0 && this.camera && this.controls) {
      this.camera.position.y -= liftM;
      this.controls.target.y -= liftM;
    }
    this.terrainCollisionLiftM = 0;
  }

  handleEarthKey(event) {
    if (!this.controls || !this.camera) return;
    const key = event.key.toLowerCase();
    if (!["n", "u", "r", "+", "=", "-"].includes(key)) return;
    event.preventDefault();
    this.releaseTerrainCollisionCorrection();
    const offset = this.camera.position.clone().sub(this.controls.target);
    const distance = Math.max(this.controls.minDistance, offset.length());
    const horizontal = Math.max(0.01, Math.hypot(offset.x, offset.z));
    if (key === "n") {
      this.camera.position.set(
        this.controls.target.x,
        this.controls.target.y + offset.y,
        this.controls.target.z + horizontal,
      );
    } else if (key === "u") {
      this.camera.position.set(
        this.controls.target.x,
        this.controls.target.y + distance,
        this.controls.target.z + 0.01,
      );
    } else if (key === "r") {
      this.controls.reset();
    } else {
      this.controls._handleMouseWheel({
        clientX: this.canvas.clientWidth / 2,
        clientY: this.canvas.clientHeight / 2,
        deltaY: key === "-" ? 120 : -120,
      });
    }
    this.controls.update();
    this.scheduleFocusImagery();
  }

  consumeNavigationClick() {
    if (performance.now() > this.suppressSelectionUntil) return false;
    this.suppressSelectionUntil = 0;
    return true;
  }

  setMountAzimuth(value) {
    const azimuth = value === null || value === undefined || value === "" ? NaN : Number(value);
    this.mountAzimuthDeg = Number.isFinite(azimuth)
      ? ((azimuth % 360) + 360) % 360
      : null;
    if (!this.mountDirectionIndicator) return;
    this.mountDirectionIndicator.visible = this.mountAzimuthDeg !== null;
    if (this.mountAzimuthDeg !== null) {
      this.mountDirectionIndicator.rotation.y = -THREE.MathUtils.degToRad(this.mountAzimuthDeg);
    }
  }

  clearAlignmentMarkers() {
    if (!this.alignmentMarkers) return;
    this.scene?.remove(this.alignmentMarkers);
    this.alignmentMarkers.traverse((object) => {
      object.geometry?.dispose?.();
      if (Array.isArray(object.material)) object.material.forEach((material) => material.dispose?.());
      else object.material?.dispose?.();
    });
    this.alignmentMarkers = null;
  }

  setAlignmentPoints(points = []) {
    this.clearAlignmentMarkers();
    if (!this.scene || !this.terrainHeightSampler || !Array.isArray(points)) return;

    const markers = new THREE.Group();
    markers.name = "pointing-alignment-markers";
    points.forEach((point, index) => {
      const position = this.localPositionForSample(point);
      if (!position) return;

      const marker = new THREE.Group();
      marker.name = `pointing-alignment-marker-${index + 1}`;
      marker.userData.point = point;
      marker.userData.pointId = String(point?.id || "");

      const purple = 0xa855f7;
      const darkPurple = 0x6d28d9;
      const cone = new THREE.Mesh(
        new THREE.ConeGeometry(1.18, 3.6, 24),
        new THREE.MeshBasicMaterial({ color: darkPurple, depthTest: true }),
      );
      // Turn the cone into a conventional map pin: broad under the head and
      // tapered to the exact saved terrain coordinate.
      cone.rotation.z = Math.PI;
      cone.position.y = 1.8;
      cone.renderOrder = 30;
      marker.add(cone);

      const head = new THREE.Mesh(
        new THREE.SphereGeometry(1.48, 24, 16),
        new THREE.MeshBasicMaterial({ color: purple, depthTest: true }),
      );
      head.position.y = 4.45;
      head.renderOrder = 31;
      marker.add(head);

      const halo = new THREE.Mesh(
        new THREE.RingGeometry(2.0, 2.85, 32),
        new THREE.MeshBasicMaterial({
          color: purple,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.72,
          depthTest: true,
          polygonOffset: true,
          polygonOffsetFactor: -5,
        }),
      );
      halo.rotation.x = -Math.PI / 2;
      halo.position.y = 0.35;
      halo.renderOrder = 29;
      marker.add(halo);

      marker.position.copy(position);
      markers.add(marker);
    });
    this.alignmentMarkers = markers;
    this.scene.add(markers);
    this.updateAlignmentMarkerPresentation();
  }

  updateAlignmentMarkerPresentation() {
    if (!this.alignmentMarkers || !this.camera) return;
    this.alignmentMarkers.children.forEach((marker) => {
      const distance = this.camera.position.distanceTo(marker.position);
      // Follow the zoom level so pins stay readable without covering a large
      // area when the operator pulls back to inspect the whole DEM.
      const emphasis = marker.userData.pointId === this.activeAlignmentPointId ? 1.45 : 1;
      const scale = THREE.MathUtils.clamp(distance * 0.004, 4, 76) * emphasis;
      marker.scale.setScalar(scale);
    });
  }

  focusAlignmentPoint(point) {
    if (!this.camera || !this.controls) return false;
    const target = this.localPositionForSample(point);
    if (!target) return false;
    this.releaseTerrainCollisionCorrection();
    const currentOffset = this.camera.position.clone().sub(this.controls.target);
    if (currentOffset.lengthSq() < 1) currentOffset.set(0.7, 0.55, 0.85);
    const groundDistanceM = Math.hypot(target.x, target.z);
    const viewingDistanceM = THREE.MathUtils.clamp(groundDistanceM * 0.16, 650, 2600);
    currentOffset.normalize().multiplyScalar(viewingDistanceM);
    const minimumCameraLift = viewingDistanceM * 0.32;
    if (currentOffset.y < minimumCameraLift) {
      const horizontalLength = Math.hypot(currentOffset.x, currentOffset.z) || 1;
      const desiredHorizontal = Math.sqrt(Math.max(1, viewingDistanceM ** 2 - minimumCameraLift ** 2));
      currentOffset.x *= desiredHorizontal / horizontalLength;
      currentOffset.z *= desiredHorizontal / horizontalLength;
      currentOffset.y = minimumCameraLift;
    }
    this.activeAlignmentPointId = String(point?.id || "");
    this.focusAnimation = {
      startedAt: performance.now(),
      durationMs: 720,
      startCamera: this.camera.position.clone(),
      startTarget: this.controls.target.clone(),
      endCamera: target.clone().add(currentOffset),
      endTarget: target.clone(),
      controlsWereEnabled: this.controls.enabled,
    };
    this.controls.enabled = false;
    return true;
  }

  updateFocusAnimation(now) {
    const animation = this.focusAnimation;
    if (!animation || !this.camera || !this.controls) return;
    const progress = THREE.MathUtils.clamp((now - animation.startedAt) / animation.durationMs, 0, 1);
    const eased = progress < 0.5
      ? 4 * progress ** 3
      : 1 - ((-2 * progress + 2) ** 3) / 2;
    this.camera.position.lerpVectors(animation.startCamera, animation.endCamera, eased);
    this.controls.target.lerpVectors(animation.startTarget, animation.endTarget, eased);
    this.camera.lookAt(this.controls.target);
    if (progress < 1) return;
    this.controls.enabled = animation.controlsWereEnabled;
    this.focusAnimation = null;
    this.controls.update();
    this.scheduleFocusImagery(0);
  }

  loadTexture(src, nearest = false, preserveDetail = false) {
    return new Promise((resolve, reject) => {
      this.textureLoader.load(src, (texture) => {
        texture.colorSpace = nearest ? THREE.NoColorSpace : THREE.SRGBColorSpace;
        texture.minFilter = nearest || preserveDetail
          ? THREE.LinearFilter
          : THREE.LinearMipmapLinearFilter;
        texture.magFilter = THREE.LinearFilter;
        texture.generateMipmaps = !preserveDetail;
        texture.anisotropy = this.renderer?.capabilities?.getMaxAnisotropy?.() || 4;
        texture.needsUpdate = true;
        resolve(texture);
      }, undefined, reject);
    });
  }

  async loadFirstAvailableTexture(sources, preserveDetail = false) {
    for (const source of sources) {
      try {
        return await this.loadTexture(source, false, preserveDetail);
      } catch (error) {
        // Keep the legacy cached raster as a safe fallback while a 4K image is
        // being generated or when the imagery provider is temporarily offline.
      }
    }
    return null;
  }

  scheduleFocusImagery(delay = 180) {
    clearTimeout(this.satelliteFocusTimer);
    this.satelliteFocusTimer = window.setTimeout(() => this.updateFocusImagery(), delay);
  }

  async updateFocusImagery() {
    if (!this.controls || !this.camera || !this.model || !this.terrain) return;
    const distance = this.camera.position.distanceTo(this.controls.target);
    if (distance > 4200 || !this.satelliteEnabled) {
      if (this.satelliteFocus) this.satelliteFocus.visible = false;
      return;
    }

    const terrainRadiusM = Number(this.model.radius_km || 20) * 1000;
    // Bring in progressively smaller imagery footprints as the camera gets
    // closer. All levels remain 2048 px, so the nearest view reaches roughly
    // 0.18 m/px instead of enlarging the 0.73 m/px focus image.
    const focusRadiusM = distance < 70 ? 30 : distance < 160 ? 75 : distance < 700 ? 180 : distance < 1700 ? 400 : 750;
    const quantizeM = focusRadiusM / 2;
    const maxCenterM = Math.max(0, terrainRadiusM - focusRadiusM);
    let eastM = Math.round(this.controls.target.x / quantizeM) * quantizeM;
    let northM = Math.round(-this.controls.target.z / quantizeM) * quantizeM;
    const centerDistance = Math.hypot(eastM, northM);
    if (centerDistance > maxCenterM && centerDistance > 0) {
      const scale = maxCenterM / centerDistance;
      eastM *= scale;
      northM *= scale;
    }
    const focusKey = `${focusRadiusM}:${Math.round(eastM)}:${Math.round(northM)}`;
    if (focusKey === this.satelliteFocusKey && this.satelliteFocus) {
      this.satelliteFocus.visible = true;
      return;
    }

    const requestId = ++this.satelliteFocusRequest;
    const center = this.offsetLatLon(eastM, northM);
    const bbox = this.webMercatorBbox(center.latitude, center.longitude, focusRadiusM);
    const query = new URLSearchParams({
      bbox: bbox.map((value) => value.toFixed(6)).join(","),
      bboxSR: "3857",
      imageSR: "3857",
      size: "2048,2048",
      format: "jpg",
      compressionQuality: "92",
      transparent: "false",
      f: "image",
    });
    const source = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?${query}`;
    let texture;
    try {
      texture = await this.loadTexture(source, false, true);
    } catch (_error) {
      return;
    }
    if (requestId !== this.satelliteFocusRequest || !this.scene) {
      texture.dispose();
      return;
    }

    this.disposeFocusImagery();
    const raster = this.model.raster || {};
    const widthM = Number(raster.width_m) || terrainRadiusM * 2;
    const depthM = Number(raster.depth_m) || terrainRadiusM * 2;
    this.satelliteFocusTexture = texture;
    this.satelliteFocus = this.createDetailImageryMesh({
      texture,
      heightTexture: this.material.displacementMap,
      radiusM: focusRadiusM,
      widthM,
      depthM,
      widthSegments: 480,
      heightSegments: 480,
      elevationMin: this.elevationMin,
      elevationMax: Number(raster.elevation_max_m ?? this.model.dem?.elevation_max_m ?? this.elevationMin + 1),
      verticalExaggeration: this.verticalExaggeration,
      centerEastM: eastM,
      centerNorthM: northM,
      name: "adaptive-focus-imagery",
      y: 3,
      featherEdges: true,
    });
    this.satelliteFocusKey = focusKey;
  }

  webMercatorBbox(latitude, longitude, radiusM) {
    const earthRadiusM = 6378137;
    const clampedLatitude = THREE.MathUtils.clamp(latitude, -85.05112878, 85.05112878);
    const latitudeRad = THREE.MathUtils.degToRad(clampedLatitude);
    const x = earthRadiusM * THREE.MathUtils.degToRad(longitude);
    const y = earthRadiusM * Math.log(Math.tan(Math.PI / 4 + latitudeRad / 2));
    const projectedRadiusM = radiusM / Math.max(0.01, Math.cos(latitudeRad));
    return [
      x - projectedRadiusM,
      y - projectedRadiusM,
      x + projectedRadiusM,
      y + projectedRadiusM,
    ];
  }

  disposeFocusImagery() {
    if (this.satelliteFocus && this.scene) {
      const heightTexture = this.satelliteFocus.userData.heightTexture;
      this.scene.remove(this.satelliteFocus);
      this.satelliteFocus.geometry.dispose();
      this.satelliteFocus.material.dispose();
      heightTexture?.dispose?.();
      this.detailHeightTextures = this.detailHeightTextures.filter((item) => item !== heightTexture);
    }
    this.satelliteFocusTexture?.dispose?.();
    this.satelliteFocus = null;
    this.satelliteFocusTexture = null;
    this.satelliteFocusKey = "";
  }

  focusAlphaTexture() {
    if (this.focusFeatherTexture) return this.focusFeatherTexture;
    const size = 256;
    const feather = 12;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    const image = context.createImageData(size, size);
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const edge = Math.min(x, y, size - 1 - x, size - 1 - y);
        const amount = THREE.MathUtils.smoothstep(edge, 0, feather);
        const value = Math.round(amount * 255);
        const offset = (y * size + x) * 4;
        image.data[offset] = value;
        image.data[offset + 1] = value;
        image.data[offset + 2] = value;
        image.data[offset + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
    this.focusFeatherTexture = new THREE.CanvasTexture(canvas);
    this.focusFeatherTexture.colorSpace = THREE.NoColorSpace;
    this.focusFeatherTexture.minFilter = THREE.LinearFilter;
    this.focusFeatherTexture.magFilter = THREE.LinearFilter;
    return this.focusFeatherTexture;
  }

  createDetailImageryMesh({
    texture,
    heightTexture,
    radiusM,
    widthM,
    depthM,
    widthSegments,
    heightSegments,
    elevationMin,
    elevationMax,
    verticalExaggeration,
    centerEastM = 0,
    centerNorthM = 0,
    featherEdges = false,
    name,
    y,
  }) {
    if (!texture || !this.scene) return null;
    const safeRadiusM = Math.min(radiusM, widthM / 2, depthM / 2);
    const detailWidthM = safeRadiusM * 2;
    const widthRatio = Math.min(1, detailWidthM / widthM);
    const depthRatio = Math.min(1, detailWidthM / depthM);
    const croppedHeightTexture = heightTexture.clone();
    croppedHeightTexture.repeat.set(widthRatio, depthRatio);
    croppedHeightTexture.offset.set(
      THREE.MathUtils.clamp((centerEastM - safeRadiusM + widthM / 2) / widthM, 0, 1 - widthRatio),
      THREE.MathUtils.clamp((centerNorthM - safeRadiusM + depthM / 2) / depthM, 0, 1 - depthRatio),
    );
    croppedHeightTexture.needsUpdate = true;
    this.detailHeightTextures.push(croppedHeightTexture);
    const geometry = new THREE.PlaneGeometry(
      detailWidthM,
      detailWidthM,
      Math.max(24, Math.round(widthSegments * widthRatio)),
      Math.max(24, Math.round(heightSegments * depthRatio)),
    );
    geometry.rotateX(-Math.PI / 2);
    const material = new THREE.MeshStandardMaterial({
      map: texture,
      displacementMap: croppedHeightTexture,
      displacementScale: Math.max(0.001, elevationMax - elevationMin) * verticalExaggeration,
      displacementBias: elevationMin,
      roughness: 0.92,
      metalness: 0,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      alphaMap: featherEdges ? this.focusAlphaTexture() : null,
      transparent: featherEdges,
      depthWrite: !featherEdges,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = name;
    mesh.position.set(centerEastM, y, -centerNorthM);
    mesh.userData.heightTexture = croppedHeightTexture;
    mesh.userData.radiusM = safeRadiusM;
    mesh.renderOrder = 1;
    this.scene.add(mesh);
    return mesh;
  }

  applyLayers(layers = {}) {
    if (!this.material) return;
    this.satelliteEnabled = layers.satellite !== false;
    const preferred = layers.satellite && this.maps.satellite ? this.maps.satellite : this.maps.terrain;
    this.material.map = layers.terrain === false && layers.satellite === false ? null : preferred;
    this.material.color.set(this.material.map ? 0xffffff : 0x315348);
    this.material.needsUpdate = true;
    if (this.satelliteDetail) this.satelliteDetail.visible = layers.satellite !== false;
    if (this.satellitePrecision) this.satellitePrecision.visible = layers.satellite !== false;
    if (this.satelliteFocus) this.satelliteFocus.visible = layers.satellite !== false;
    if (this.visibilityMaterial?.uniforms?.layerOpacity) {
      this.visibilityMaterial.uniforms.layerOpacity.value = layers.visibility === false ? 0 : 1;
    }
    if (this.gridMaterial) this.gridMaterial.opacity = layers.grid === false ? 0 : 0.08;
    if (this.satelliteEnabled) this.scheduleFocusImagery();
  }

  pick(event) {
    if (!this.terrainHeightSampler || !this.camera || !this.canvas) return null;
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const point = this.intersectTerrainHeightField(this.raycaster.ray);
    if (!point) return null;
    return this.offsetLatLon(point.x, -point.z);
  }

  intersectTerrainHeightField(ray) {
    const radiusM = Number(this.model?.radius_km) * 1000;
    if (!ray || !Number.isFinite(radiusM) || radiusM <= 0) return null;
    const origin = ray.origin;
    const direction = ray.direction;
    const horizontalA = direction.x ** 2 + direction.z ** 2;
    let startT = 0;
    let endT = this.camera?.far || 160000;
    if (horizontalA < 1e-12) {
      if (origin.x ** 2 + origin.z ** 2 > radiusM ** 2) return null;
    } else {
      const horizontalB = 2 * (origin.x * direction.x + origin.z * direction.z);
      const horizontalC = origin.x ** 2 + origin.z ** 2 - radiusM ** 2;
      const discriminant = horizontalB ** 2 - 4 * horizontalA * horizontalC;
      if (discriminant < 0) return null;
      const root = Math.sqrt(discriminant);
      const firstT = (-horizontalB - root) / (2 * horizontalA);
      const secondT = (-horizontalB + root) / (2 * horizontalA);
      startT = Math.max(startT, Math.min(firstT, secondT));
      endT = Math.min(endT, Math.max(firstT, secondT));
    }
    if (endT < startT || endT < 0) return null;
    startT = Math.max(0, startT);
    const horizontalSpanM = (endT - startT) * Math.sqrt(horizontalA);
    const steps = THREE.MathUtils.clamp(Math.ceil(horizontalSpanM / 35), 96, 1400);
    const clearanceAt = (distanceT) => {
      const point = ray.at(distanceT, new THREE.Vector3());
      const surfaceY = this.terrainSurfaceHeightAt(point.x, point.z);
      return surfaceY === null ? null : point.y - surfaceY;
    };
    let previousT = startT;
    let previousClearance = clearanceAt(previousT);
    for (let index = 1; index <= steps; index += 1) {
      const currentT = THREE.MathUtils.lerp(startT, endT, index / steps);
      const currentClearance = clearanceAt(currentT);
      if (
        previousClearance !== null
        && currentClearance !== null
        && previousClearance >= 0
        && currentClearance <= 0
      ) {
        let aboveT = previousT;
        let belowT = currentT;
        for (let iteration = 0; iteration < 18; iteration += 1) {
          const middleT = (aboveT + belowT) / 2;
          const middleClearance = clearanceAt(middleT);
          if (middleClearance === null || middleClearance > 0) aboveT = middleT;
          else belowT = middleT;
        }
        const hit = ray.at((aboveT + belowT) / 2, new THREE.Vector3());
        hit.y = this.terrainSurfaceHeightAt(hit.x, hit.z);
        return hit;
      }
      previousT = currentT;
      previousClearance = currentClearance;
    }
    return null;
  }

  localPositionForSample(sample) {
    const latitude = Number(sample?.latitude);
    const longitude = Number(sample?.longitude);
    const stationLatitude = Number(this.model?.station?.latitude);
    const stationLongitude = Number(this.model?.station?.longitude);
    if (![latitude, longitude, stationLatitude, stationLongitude].every(Number.isFinite)) return null;
    const earthRadiusM = 6371008.8;
    const eastM = THREE.MathUtils.degToRad(longitude - stationLongitude)
      * earthRadiusM * Math.max(0.01, Math.cos(THREE.MathUtils.degToRad(stationLatitude)));
    const northM = THREE.MathUtils.degToRad(latitude - stationLatitude) * earthRadiusM;
    const surfaceY = this.terrainSurfaceHeightAt(eastM, -northM);
    if (surfaceY === null) return null;
    return new THREE.Vector3(eastM, surfaceY, -northM);
  }

  selectionKeyForSample(sample) {
    const latitude = Number(sample?.latitude);
    const longitude = Number(sample?.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return "";
    return `${latitude.toFixed(7)},${longitude.toFixed(7)}`;
  }

  showSelection(sample, options = {}) {
    if (!this.scene) return;
    this.clearLineOfSight();
    if (this.selection) {
      this.scene.remove(this.selection);
      this.selection.geometry.dispose();
      this.selection.material.dispose();
      this.selection = null;
    }
    if (this.selectionLabel) this.selectionLabel.hidden = true;
    const position = this.localPositionForSample(sample);
    if (!position) return;
    this.selection = new THREE.Mesh(
      new THREE.RingGeometry(0.58, 1, 48),
      new THREE.MeshBasicMaterial({
        color: 0xffa84d,
        side: THREE.DoubleSide,
        depthTest: true,
        polygonOffset: true,
        polygonOffsetFactor: -4,
      }),
    );
    const normal = this.terrainNormalAt(position.x, position.z);
    this.selection.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
    this.selection.position.copy(position).addScaledVector(normal, 0.6);
    const selectionKey = this.selectionKeyForSample(sample);
    this.selection.userData.selectionKey = selectionKey;
    this.selection.userData.showLabel = options.showLabel === true
      && selectionKey !== this.dismissedSelectionLabelKey;
    this.scene.add(this.selection);
    this.showLineOfSight(sample, position, options);
    if (this.selection.userData.showLabel && this.selectionLabel) {
      const gridLabel = sample.grid_cell?.id || "30 m terrain cell";
      if (this.selectionLabelGrid) this.selectionLabelGrid.textContent = gridLabel;
      if (this.selectionLabelLatitude) this.selectionLabelLatitude.textContent = Number(sample.latitude).toFixed(6);
      if (this.selectionLabelLongitude) this.selectionLabelLongitude.textContent = Number(sample.longitude).toFixed(6);
      const azimuthSource = sample.corrected_device_azimuth_deg ?? sample.device_azimuth_deg ?? sample.azimuth_deg;
      const altitudeSource = sample.corrected_altitude_deg ?? sample.altitude_deg;
      const azimuth = azimuthSource === null || azimuthSource === undefined
        ? Number.NaN
        : Number(azimuthSource);
      const altitude = altitudeSource === null || altitudeSource === undefined
        ? Number.NaN
        : Number(altitudeSource);
      if (this.selectionLabelAzimuth) this.selectionLabelAzimuth.textContent = Number.isFinite(azimuth) ? `${azimuth.toFixed(3)}°` : "--";
      if (this.selectionLabelAltitude) this.selectionLabelAltitude.textContent = Number.isFinite(altitude) ? `${altitude.toFixed(3)}°` : "--";
      if (this.selectionLabelGoto) this.selectionLabelGoto.disabled = !Number.isFinite(azimuth) || !Number.isFinite(altitude);
      if (this.selectionLabelAddModel) this.selectionLabelAddModel.disabled = !Number.isFinite(azimuth) || !Number.isFinite(altitude);
      this.selectionLabel.hidden = false;
    }
  }

  clearLineOfSight() {
    if (!this.lineOfSight || !this.scene) return;
    this.scene.remove(this.lineOfSight);
    this.lineOfSight.traverse((object) => {
      object.geometry?.dispose?.();
      object.material?.dispose?.();
    });
    this.lineOfSight = null;
  }

  addLineOfSightSegment(group, start, end, color, radiusM) {
    if (start.distanceToSquared(end) < 0.01) return;
    const curve = new THREE.LineCurve3(start, end);
    const glow = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 1, radiusM * 2.8, 10, false),
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.16,
        depthWrite: false,
        depthTest: true,
      }),
    );
    glow.renderOrder = 22;
    group.add(glow);
    const core = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 1, radiusM, 10, false),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.94 }),
    );
    core.renderOrder = 23;
    group.add(core);
  }

  showLineOfSight(sample, targetPosition, options = {}) {
    if (!this.scene || !targetPosition || !Number.isFinite(this.stationDeviceY)) return;
    const targetDistanceM = Number(sample?.distance_m);
    if (!Number.isFinite(targetDistanceM) || targetDistanceM < 1) return;
    // The ray begins at the exact center of the cylinder's top cap: DEM plus
    // the configured station height. This preserves the visual altitude angle.
    const start = new THREE.Vector3(0, this.stationDeviceY, 0);
    const end = targetPosition.clone();
    const radiusM = THREE.MathUtils.clamp(targetDistanceM / 1400, 2.5, 14);
    const group = new THREE.Group();
    group.name = "selected-line-of-sight";
    if (options.pending === true) {
      this.addLineOfSightSegment(group, start, end, 0xffc857, radiusM);
      this.lineOfSight = group;
      this.scene.add(group);
      return;
    }
    const blockerDistanceM = Number(sample?.blocker?.distance_m);
    if (sample?.visible === false && Number.isFinite(blockerDistanceM)) {
      const blockerRatio = THREE.MathUtils.clamp(blockerDistanceM / targetDistanceM, 0.02, 0.98);
      const blockerOnRay = start.clone().lerp(end, blockerRatio);
      this.addLineOfSightSegment(group, start, blockerOnRay, 0x69f0ae, radiusM);
      this.addLineOfSightSegment(group, blockerOnRay, end, 0xff5c4d, radiusM);
      const blockerSurface = this.localPositionForSample(sample.blocker);
      if (blockerSurface) {
        const blockerMarker = new THREE.Mesh(
          new THREE.SphereGeometry(radiusM * 3.2, 18, 12),
          new THREE.MeshBasicMaterial({ color: 0xff704f, depthTest: true }),
        );
        blockerMarker.position.copy(blockerSurface).add(new THREE.Vector3(0, radiusM * 2, 0));
        group.add(blockerMarker);
      }
    } else {
      this.addLineOfSightSegment(group, start, end, 0x69f0ae, radiusM);
    }
    this.lineOfSight = group;
    this.scene.add(group);
  }

  offsetLatLon(eastM, northM) {
    const station = this.model.station;
    const earthRadiusM = 6371008.8;
    const latRad = THREE.MathUtils.degToRad(Number(station.latitude));
    return {
      latitude: Number(station.latitude) + THREE.MathUtils.radToDeg(northM / earthRadiusM),
      longitude: Number(station.longitude) + THREE.MathUtils.radToDeg(eastM / (earthRadiusM * Math.max(0.01, Math.cos(latRad)))),
    };
  }

  updateSelectionPresentation() {
    if (!this.selection || !this.camera || !this.canvas) {
      if (this.selectionLabel) this.selectionLabel.hidden = true;
      return;
    }
    const selectionDistance = this.camera.position.distanceTo(this.selection.position);
    const screenStableSizeM = THREE.MathUtils.clamp(selectionDistance * 0.012, 4, 180);
    this.selection.scale.setScalar(screenStableSizeM);
    if (!this.selection.userData.showLabel || !this.selectionLabel) return;
    const projected = this.selection.position.clone().project(this.camera);
    const onScreen = projected.z >= -1 && projected.z <= 1
      && projected.x >= -1.1 && projected.x <= 1.1
      && projected.y >= -1.1 && projected.y <= 1.1;
    this.selectionLabel.hidden = !onScreen;
    if (!onScreen) return;
    const canvasRect = this.canvas.getBoundingClientRect();
    const stageRect = this.canvas.parentElement?.getBoundingClientRect() || canvasRect;
    this.selectionLabel.style.left = `${canvasRect.left - stageRect.left + (projected.x + 1) * canvasRect.width / 2}px`;
    this.selectionLabel.style.top = `${canvasRect.top - stageRect.top + (1 - projected.y) * canvasRect.height / 2}px`;
  }

  resize() {
    if (!this.renderer || !this.camera || !this.canvas) return;
    const rect = this.canvas.parentElement?.getBoundingClientRect() || this.canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  animate() {
    if (!this.renderer) return;
    this.animationFrame = requestAnimationFrame(() => this.animate());
    // Collision correction is derived from the current frame only. Remove the
    // previous correction before applying controls so travelling across higher
    // ground cannot permanently ratchet the orbit target upward.
    this.releaseTerrainCollisionCorrection();
    this.resize();
    this.updateNavigationSensitivity();
    this.updateFocusAnimation(performance.now());
    this.controls?.update();
    this.anchorOrbitTargetToTerrain();
    this.enforceTerrainCollision();
    if (this.camera && this.controls) {
      const cameraDistance = this.camera.position.distanceTo(this.controls.target);
      const closeDetailView = cameraDistance < 6500;
      const stationDistance = this.camera.position.distanceTo(
        new THREE.Vector3(0, this.stationDeviceY || 0, 0),
      );
      const stationMarkerScale = THREE.MathUtils.clamp(stationDistance / 18000, 0.12, 1);
      this.scanCoverage && (this.scanCoverage.visible = !closeDetailView);
      this.northIndicator && (this.northIndicator.visible = !closeDetailView);
      this.stationBeacon && (this.stationBeacon.visible = !closeDetailView);
      this.mountDirectionIndicator && (
        this.mountDirectionIndicator.visible = !closeDetailView && this.mountAzimuthDeg !== null
      );
      // Keep the cylinder footprint inside the existing yellow station ring
      // while retaining the physical installation height on the Y axis.
      if (this.station) {
        const stationRadiusM = 95 * stationMarkerScale;
        this.station.scale.set(stationRadiusM, 1, stationRadiusM);
      }
      [this.beaconShaft, this.beaconTip, this.stationRing]
        .forEach((object) => object?.scale.setScalar(stationMarkerScale));
    }
    this.updateSelectionPresentation();
    this.updateAlignmentMarkerPresentation();
    if (this.northLabel && this.camera) {
      const labelHeight = THREE.MathUtils.clamp(
        this.camera.position.distanceTo(this.northLabel.position) * 0.035,
        520,
        1800,
      );
      this.northLabel.scale.set(labelHeight * 2, labelHeight, 1);
    }
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
    this.animationFrame = 0;
    clearTimeout(this.satelliteFocusTimer);
    this.satelliteFocusTimer = 0;
    this.satelliteFocusRequest += 1;
    if (this.canvas && this.earthHandlers) {
      this.canvas.removeEventListener("pointerdown", this.earthHandlers.pointerDown, true);
      this.canvas.removeEventListener("pointermove", this.earthHandlers.pointerMove, true);
      this.canvas.removeEventListener("pointerup", this.earthHandlers.pointerUp, true);
      this.canvas.removeEventListener("pointercancel", this.earthHandlers.pointerUp, true);
      this.canvas.removeEventListener("contextmenu", this.earthHandlers.contextMenu);
      this.canvas.removeEventListener("keydown", this.earthHandlers.keyDown);
    }
    this.earthHandlers = null;
    this.navigationPointer = null;
    if (this.selectionLabel) this.selectionLabel.hidden = true;
    this.clearLineOfSight();
    this.clearAlignmentMarkers();
    this.terrainHeightSampler = null;
    this.terrainCollisionLiftM = 0;
    this.controls?.stopListenToKeyEvents?.();
    this.controls?.dispose();
    this.disposeFocusImagery();
    this.renderer?.dispose();
    this.scene?.traverse((object) => {
      object.geometry?.dispose?.();
      if (Array.isArray(object.material)) object.material.forEach((material) => material.dispose?.());
      else object.material?.dispose?.();
    });
    Object.values(this.maps || {}).forEach((texture) => texture?.dispose?.());
    this.detailHeightTextures.forEach((texture) => texture.dispose?.());
    this.northLabelTexture?.dispose?.();
    this.focusFeatherTexture?.dispose?.();
    this.northLabelTexture = null;
    this.focusFeatherTexture = null;
    this.focusAnimation = null;
    this.activeAlignmentPointId = "";
    this.renderer = null;
    this.scene = null;
    this.terrain = null;
    this.satelliteDetail = null;
    this.satellitePrecision = null;
    this.satelliteFocus = null;
    this.satelliteFocusTexture = null;
    this.detailHeightTextures = [];
    this.scanCoverage = null;
    this.northIndicator = null;
    this.northLabel = null;
    this.mountDirectionIndicator = null;
    this.alignmentMarkers = null;
    this.stationDeviceY = null;
    this.stationGroundY = null;
    this.stationHeightM = 0;
  }
}

window.pointingTerrain3D = new PointingTerrain3D();
window.dispatchEvent(new CustomEvent("pointing-terrain-3d-ready"));
