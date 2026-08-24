import * as THREE from "../vendor/three/three.module.min.js";
import { OrbitControls } from "../vendor/three/addons/controls/OrbitControls.js";

class PointingTerrain3D {
  constructor() {
    this.canvas = null;
    this.model = null;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this.controls = null;
    this.terrain = null;
    this.visibility = null;
    this.grid = null;
    this.station = null;
    this.selection = null;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.animationFrame = 0;
    this.textureLoader = new THREE.TextureLoader();
  }

  async load(canvas, model, layers) {
    if (!canvas || !model?.raster?.height_src) return false;
    this.dispose();
    this.canvas = canvas;
    this.model = model;
    const raster = model.raster;
    const [heightTexture, terrainTexture, satelliteTexture, visibilityTexture] = await Promise.all([
      this.loadTexture(raster.height_src, true),
      this.loadTexture(raster.terrain_src || raster.src),
      raster.satellite_src ? this.loadTexture(raster.satellite_src).catch(() => null) : null,
      raster.visibility_src ? this.loadTexture(raster.visibility_src).catch(() => null) : null,
    ]);

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      logarithmicDepthBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x04070e, 1);
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x07101a, 0.000018);

    const widthM = Number(raster.width_m) || Number(model.radius_km) * 2000;
    const depthM = Number(raster.depth_m) || Number(model.radius_km) * 2000;
    const widthSegments = Math.max(1, Math.min(383, Number(raster.height_width || 256) - 1));
    const heightSegments = Math.max(1, Math.min(383, Number(raster.height_height || 256) - 1));
    const elevationMin = Number(raster.elevation_min_m ?? model.dem?.elevation_min_m ?? 0);
    const elevationMax = Number(raster.elevation_max_m ?? model.dem?.elevation_max_m ?? elevationMin + 1);
    const geometry = new THREE.PlaneGeometry(widthM, depthM, widthSegments, heightSegments);
    geometry.rotateX(-Math.PI / 2);

    this.maps = { terrain: terrainTexture, satellite: satelliteTexture };
    const verticalExaggeration = 3.0;
    this.verticalExaggeration = verticalExaggeration;
    this.elevationMin = elevationMin;
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

    if (visibilityTexture) {
      this.visibilityMaterial = new THREE.MeshStandardMaterial({
        map: visibilityTexture,
        displacementMap: heightTexture,
        displacementScale: Math.max(0.001, elevationMax - elevationMin) * verticalExaggeration,
        displacementBias: elevationMin,
        emissive: 0x000000,
        roughness: 1,
        metalness: 0,
        transparent: true,
        opacity: layers?.visibility === false ? 0 : 1,
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
    const stationGround = elevationMin + (rawStationGround - elevationMin) * verticalExaggeration;
    const rawStationTop = Number(model.station?.elevation_m ?? rawStationGround);
    const stationTop = elevationMin + (rawStationTop - elevationMin) * verticalExaggeration;
    const markerHeight = Math.max(80, stationTop - stationGround);
    const markerGeometry = new THREE.CylinderGeometry(32, 32, markerHeight, 16);
    const markerMaterial = new THREE.MeshBasicMaterial({ color: 0xffdf45 });
    this.station = new THREE.Mesh(markerGeometry, markerMaterial);
    this.station.position.set(0, stationGround + markerHeight / 2 + 8, 0);
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
    const beaconShaft = new THREE.Mesh(
      new THREE.CylinderGeometry(18, 18, beaconHeight, 12),
      new THREE.MeshBasicMaterial({ color: 0xffe35a, depthTest: false }),
    );
    beaconShaft.position.set(0, stationGround + beaconHeight / 2, 0);
    beaconShaft.renderOrder = 20;
    this.scene.add(beaconShaft);

    const beaconTip = new THREE.Mesh(
      new THREE.ConeGeometry(130, 320, 20),
      new THREE.MeshBasicMaterial({ color: 0xffec70, depthTest: false }),
    );
    beaconTip.position.set(0, stationGround + beaconHeight, 0);
    beaconTip.rotation.x = Math.PI;
    beaconTip.renderOrder = 21;
    this.scene.add(beaconTip);

    const stationRing = new THREE.Mesh(
      new THREE.RingGeometry(150, 230, 48),
      new THREE.MeshBasicMaterial({
        color: 0xffdf45,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.92,
        depthTest: false,
      }),
    );
    stationRing.rotation.x = -Math.PI / 2;
    stationRing.position.set(0, stationGround + 25, 0);
    stationRing.renderOrder = 21;
    this.scene.add(stationRing);

    const glow = new THREE.PointLight(0xffdf45, 3.2, 6000);
    glow.position.set(0, stationTop + 250, 0);
    this.scene.add(glow);

    this.scene.add(new THREE.HemisphereLight(0xd8ecff, 0x172112, 2.1));
    const sunlight = new THREE.DirectionalLight(0xfff1d2, 2.3);
    sunlight.position.set(-16000, 24000, -16000);
    this.scene.add(sunlight);

    this.camera = new THREE.PerspectiveCamera(48, 1, 10, 160000);
    this.camera.position.set(widthM * 0.48, Math.max(6200, widthM * 0.21), depthM * 0.62);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(0, elevationMin + (elevationMax - elevationMin) * 0.8, -depthM * 0.08);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.045;
    this.controls.minDistance = 400;
    this.controls.maxDistance = 70000;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.update();
    this.resize();
    this.applyLayers(layers);
    this.animate();
    return true;
  }

  loadTexture(src, nearest = false) {
    return new Promise((resolve, reject) => {
      this.textureLoader.load(src, (texture) => {
        texture.colorSpace = nearest ? THREE.NoColorSpace : THREE.SRGBColorSpace;
        texture.minFilter = nearest ? THREE.LinearFilter : THREE.LinearMipmapLinearFilter;
        texture.magFilter = THREE.LinearFilter;
        texture.anisotropy = this.renderer?.capabilities?.getMaxAnisotropy?.() || 4;
        resolve(texture);
      }, undefined, reject);
    });
  }

  applyLayers(layers = {}) {
    if (!this.material) return;
    const preferred = layers.satellite && this.maps.satellite ? this.maps.satellite : this.maps.terrain;
    this.material.map = layers.terrain === false && layers.satellite === false ? null : preferred;
    this.material.color.set(this.material.map ? 0xffffff : 0x315348);
    this.material.needsUpdate = true;
    if (this.visibilityMaterial) this.visibilityMaterial.opacity = layers.visibility === false ? 0 : 1;
    if (this.gridMaterial) this.gridMaterial.opacity = layers.grid === false ? 0 : 0.08;
  }

  pick(event) {
    if (!this.terrain || !this.camera || !this.canvas) return null;
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObject(this.terrain, false)[0];
    if (!hit) return null;
    const radiusM = Number(this.model.radius_km) * 1000;
    if (Math.hypot(hit.point.x, hit.point.z) > radiusM) return null;
    return this.offsetLatLon(hit.point.x, -hit.point.z);
  }

  showSelection(sample) {
    if (!this.scene) return;
    if (this.selection) {
      this.scene.remove(this.selection);
      this.selection.geometry.dispose();
      this.selection.material.dispose();
      this.selection = null;
    }
    const distanceM = Number(sample?.distance_m);
    const azimuth = Number(sample?.azimuth_deg);
    const elevation = Number(sample?.elevation_m);
    if (!Number.isFinite(distanceM) || !Number.isFinite(azimuth) || !Number.isFinite(elevation)) return;
    const angle = THREE.MathUtils.degToRad(azimuth);
    this.selection = new THREE.Mesh(
      new THREE.SphereGeometry(80, 18, 12),
      new THREE.MeshBasicMaterial({ color: 0xffb470 }),
    );
    const displayElevation = this.elevationMin + (elevation - this.elevationMin) * this.verticalExaggeration;
    this.selection.position.set(Math.sin(angle) * distanceM, displayElevation + 90, -Math.cos(angle) * distanceM);
    this.scene.add(this.selection);
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
    this.resize();
    this.controls?.update();
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
    this.animationFrame = 0;
    this.controls?.dispose();
    this.renderer?.dispose();
    this.scene?.traverse((object) => {
      object.geometry?.dispose?.();
      if (Array.isArray(object.material)) object.material.forEach((material) => material.dispose?.());
      else object.material?.dispose?.();
    });
    Object.values(this.maps || {}).forEach((texture) => texture?.dispose?.());
    this.renderer = null;
    this.scene = null;
    this.terrain = null;
  }
}

window.pointingTerrain3D = new PointingTerrain3D();
window.dispatchEvent(new CustomEvent("pointing-terrain-3d-ready"));
