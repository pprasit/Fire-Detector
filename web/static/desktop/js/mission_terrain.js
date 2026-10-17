import * as THREE from '../../vendor/three/three.module.min.js';
import { OrbitControls } from '../../vendor/three/addons/controls/OrbitControls.js';
import { mountDirection, geographicDirection, geographicAngles, geographicFovCorners, thermalFov, angularWindow, scrollWindow, panoramaTrackWidth, panoramaZoomAnchor, includeCameraAltitude, thermalFrameFov, chartAngularScale } from './mission_terrain_math.mjs?v=6';

const element = id => document.getElementById(id);
const viewport = element('gridViewport');
const header = viewport.previousElementSibling;
const telemetry = header.querySelector('.mount-telemetry');
const state = document.createElement('span');
state.className = 'terrain-state';
state.setAttribute('role', 'status');
state.textContent = 'Loading 3D terrain';
header.insertBefore(state, telemetry);
header.insertBefore(telemetry, state);
telemetry.querySelector('#actualAltVel').parentElement.firstChild.textContent = 'VEL ALT ';
telemetry.title='Actual positions, velocities and targets are calibrated mount coordinates. The panorama and its camera marker use true geographic bearing.';
telemetry.querySelector('#actualAz').parentElement.firstChild.textContent='MOUNT AZ ';
telemetry.querySelector('#actualAlt').parentElement.firstChild.textContent='ALT ';
const summaryLabel=document.querySelector('.compact-summary .metric:first-child small');
if(summaryLabel)summaryLabel.textContent='/ True north';
const renderRangeBase=renderScanRange;
renderScanRange=()=>{renderRangeBase();element('rangeValue').textContent='SCAN · MOUNT '+element('rangeValue').textContent;};
renderScanRange();
header.querySelector('.panel-actions').hidden = true;
const chart = document.createElement('div');
chart.className = 'terrain-chart';
chart.innerHTML = `<div class="terrain-toolbar">
  <div class="terrain-mode" role="group" aria-label="Terrain view">
    <button type="button" id="terrainPanorama" aria-pressed="true">360° panorama</button>
    <button type="button" id="terrainOrbit" aria-pressed="false">3D orbit</button></div>
  <label>View <select id="terrainZoom" aria-label="Display zoom, independent of camera zoom">
    <option value="1">Full range</option><option value="2">2× detail</option><option value="4">4× detail</option><option value="8">8× detail</option>
  </select></label><button type="button" id="terrainCenter">Camera direction</button>
  <button type="button" id="terrainReset">Reset view</button>
  <label>Quality <select id="terrainQuality" aria-label="3D terrain rendering quality"><option value="balanced">Balanced</option><option value="high" selected>High</option><option value="ultra">Ultra · native DEM</option></select></label>
  <span class="terrain-frame">LIVE WEBGL · TRUE NORTH</span></div>
  <div class="terrain-plot"><svg class="terrain-y-axis" id="terrainYAxis" aria-label="Altitude in degrees"></svg>
  <div class="terrain-scroll" id="terrainScroll" tabindex="0" role="region" aria-label="Scrollable 360 degree DEM panorama">
  <div class="terrain-track"><div class="terrain-stage"><canvas class="terrain-canvas" id="missionTerrainCanvas" tabindex="0" aria-label="Interactive DEM 3D terrain: drag horizontally to scroll, wheel to zoom"></canvas>
  <svg class="terrain-overlay" id="terrainAxes" aria-label="True geographic bearing clockwise from north; altitude above the true horizon"></svg>
  <div class="terrain-message" id="terrainMessage" role="status">Building 3D terrain from DEM…</div></div></div></div></div>`;
viewport.hidden = true;
viewport.after(chart);
element('createDemPanorama').textContent = 'Reload 3D terrain';
element('createDemPanorama').title = 'Reload the current station DEM and Pointing Model';
const opticalReadout = document.querySelector('.dem-key');
opticalReadout.id = 'thermalLiveFov';
opticalReadout.textContent = 'THERMAL OPTICAL FOV · waiting for zoom readback';
const chartScaleReadout = document.createElement('span');
chartScaleReadout.id = 'thermalChartScale';
element('status').before(chartScaleReadout);
element('status').textContent = '';
let terrain = null;
// The capture planner keeps its own state; drawing it must not replace WebGL.
draw = () => terrain?.drawOverlay();
drawActualMarker = () => terrain?.drawOverlay();
sizeScanGrid = () => terrain?.resize();

const SKY = 0x95bdd0;
const vertexShader = `varying vec2 screenUv;
void main(){screenUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}`;
const fragmentShader = `
uniform samplerCube panorama;
uniform vec4 bounds;
varying vec2 screenUv;
void main(){
  float az=radians(mix(bounds.x,bounds.y,screenUv.x));
  float alt=radians(mix(bounds.z,bounds.w,screenUv.y));
  vec3 direction=vec3(cos(alt)*sin(az),sin(alt),-cos(alt)*cos(az));
  gl_FragColor=textureCube(panorama,normalize(direction));
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

class MissionTerrain {
  constructor(canvas) {
    this.canvas = canvas;
    this.scroll = element('terrainScroll');
    this.track = this.scroll.querySelector('.terrain-track');
    this.renderer = new THREE.WebGLRenderer({canvas, antialias:true});
    const gl=this.renderer.getContext(), debug=gl.getExtension('WEBGL_debug_renderer_info');
    const gpuName=debug ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : '';
    this.softwareRenderer=/swiftshader|llvmpipe|softpipe|software/i.test(gpuName);
    this.renderer.setPixelRatio(Math.min(Math.max(devicePixelRatio || 1, 1.5), 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    // Satellite imagery already contains sunlight and shadow. Neutral output
    // and soft additional lighting preserve its photographic colours.
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(SKY);
    this.scene.fog = new THREE.FogExp2(0xbdced8, .000025);
    this.scene.add(new THREE.HemisphereLight(0xf1f5fa, 0xb9bebc, 2.1));
    const sun = new THREE.DirectionalLight(0xfff7ec, .65);
    sun.position.set(-5000, 12000, 7000);
    this.scene.add(sun);
    this.sky = new THREE.Mesh(new THREE.SphereGeometry(80000,32,16),new THREE.ShaderMaterial({
      side:THREE.BackSide,depthWrite:false,
      uniforms:{zenith:{value:new THREE.Color(0x779bbd)},horizon:{value:new THREE.Color(0xbdced8)}},
      vertexShader:'varying vec3 skyDirection; void main(){skyDirection=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
      fragmentShader:`uniform vec3 zenith;uniform vec3 horizon;varying vec3 skyDirection;
        void main(){float t=pow(max(0.,normalize(skyDirection).y),.45);gl_FragColor=vec4(mix(horizon,zenith,t),1.);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
        }`,
    }));
    this.scene.add(this.sky);
    this.camera = new THREE.PerspectiveCamera(50, 1, .5, 100000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enabled = false;
    this.controls.minDistance = 30;
    this.controls.maxDistance = 60000;
    this.controls.maxPolarAngle = Math.PI * .48;
    this.controls.addEventListener('change', () => this.schedule());
    this.mode = 'panorama';
    this.zoom = 1;
    this.center = {az:180, alt:-2.5};
    this.altitudeRange={altMin:-15,altMax:10};
    this.initialCameraCentered=false;
    this.assets = [];
    this.pointer = null;
    this.frame = 0;
    this.visible = true;
    this.ready = false;
    this.liveThermalFov=null;
    this.thermalPollClosed=false;
    this.installEvents();
    this.pollThermalFov();
  }

  async pollThermalFov() {
    if(this.thermalPollClosed||this.thermalPollBusy)return;
    clearTimeout(this.thermalPollTimer);
    if(!this.visible||document.hidden){
      this.thermalPollTimer=setTimeout(()=>this.pollThermalFov(),1000);return;
    }
    this.thermalPollBusy=true;
    try{
      const response=await fetch('/api/camera-stream/metadata/live/thermal',{cache:'no-store',signal:AbortSignal.timeout(3000)});
      if(!response.ok)throw Error('Thermal zoom readback unavailable');
      const result=await response.json();
      this.liveThermalFov=thermalFrameFov(result);
      this.thermalFrameAge=result.age_ms;
      this.thermalReceivedAt=performance.now();
    }catch(_){this.liveThermalFov=null;}
    finally{
      this.thermalPollBusy=false;
      if(!this.thermalPollClosed){this.drawOverlay();this.thermalPollTimer=setTimeout(()=>this.pollThermalFov(),500);}
    }
  }

  freshThermalFov() {
    return this.liveThermalFov&&this.thermalFrameAge+performance.now()-this.thermalReceivedAt<=2000
      ? this.liveThermalFov:null;
  }

  async load() {
    this.ready = false;
    const generation = this.generation = (this.generation || 0) + 1;
    const message = element('terrainMessage');
    message.hidden = false;
    message.textContent = 'Loading DEM mesh and satellite textures…';
    state.textContent = 'Loading 3D terrain';
    delete state.dataset.error;
    const fetchJson = async url => {
      const response = await fetch(url, {cache:'no-store', signal:AbortSignal.timeout(90000)});
      if (!response.ok) throw Error(`Terrain request failed (HTTP ${response.status})`);
      const result = await response.json();
      if (result.ok === false) throw Error(result.error || 'DEM is unavailable');
      return result;
    };
    const [model, settings] = await Promise.all([
      fetchJson('/api/pointing/model?resolution_m=30'), fetchJson('/api/settings'),
    ]);
    if (generation !== this.generation) return;
    this.model = model;
    this.pointingModel = settings.pointing_alignment?.model || {};
    let heightInfo = null;
    try {
      heightInfo = await fetchJson(`/api/pointing/cache/pointing_${model.cache_key}_height_hq_v1.json`);
      if (heightInfo.encoding !== 'rg16') heightInfo = null;
    } catch (_) { /* Older stations can still render their reduced height map. */ }
    if (generation !== this.generation) return;
    const quality = element('terrainQuality').value;
    const desiredPixelRatio=quality==='ultra' ? 2 : quality==='high' ? Math.min(Math.max(devicePixelRatio||1,1.5),2) : Math.min(devicePixelRatio||1,1.5);
    this.renderer.setPixelRatio(Math.min(desiredPixelRatio,this.softwareRenderer?1.5:2));
    const loader = new THREE.TextureLoader();
    const texture = async (src, color = false) => {
      if (!src) return null;
      const loaded = await loader.loadAsync(src);
      loaded.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      loaded.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      return loaded;
    };
    const r = model.raster;
    if (!r?.height_src) throw Error('DEM elevation data is unavailable');
    const loadedAssets = await Promise.allSettled([
      texture(heightInfo?.src || r.height_src), texture(r.satellite_high_resolution_src || r.satellite_src || r.terrain_src, true),
      texture(r.satellite_detail_src, true), texture(r.satellite_precision_src, true),
    ]);
    const assets = loadedAssets.map(result => result.status === 'fulfilled' ? result.value : null);
    if (generation !== this.generation) { assets.forEach(asset => asset?.dispose()); return; }
    const [heightTexture, overview, detail, precision] = assets;
    if (!heightTexture || !overview) {
      assets.forEach(asset => asset?.dispose());
      throw Error('Could not load DEM elevation or terrain texture. Refresh Mission Design to retry.');
    }
    this.clearTerrain();
    this.assets = assets;
    const image = heightTexture.image;
    const readback = document.createElement('canvas');
    readback.width = image.width;
    readback.height = image.height;
    const context = readback.getContext('2d', {willReadFrequently:true});
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, image.width, image.height).data;
    const widthM = Number(r.width_m), depthM = Number(r.depth_m);
    const elevationMin = Number(heightInfo?.elevation_min_m ?? r.elevation_min_m), elevationRange = Number(heightInfo?.elevation_max_m ?? r.elevation_max_m) - elevationMin;
    const segments = Math.min(quality==='ultra' ? 1536 : quality==='high' ? 1024 : 512, image.width - 1);
    const geometry = new THREE.PlaneGeometry(widthM, depthM, segments, segments);
    geometry.rotateX(-Math.PI / 2);
    const positions = geometry.attributes.position;
    const sample = (u, v) => {
      const x = Math.max(0, Math.min(image.width - 1, u * (image.width - 1)));
      const y = Math.max(0, Math.min(image.height - 1, v * (image.height - 1)));
      const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.min(image.width - 1, x0 + 1), y1 = Math.min(image.height - 1, y0 + 1);
      const p = (a, b) => {
        const index=(b * image.width + a) * 4;
        return heightInfo ? (pixels[index]*256+pixels[index+1])/65535 : pixels[index]/255;
      };
      const top = THREE.MathUtils.lerp(p(x0,y0), p(x1,y0), x-x0);
      const bottom = THREE.MathUtils.lerp(p(x0,y1), p(x1,y1), x-x0);
      return elevationMin + THREE.MathUtils.lerp(top,bottom,y-y0) * elevationRange;
    };
    // Anchor the rendered surface to the configured station ground elevation.
    const ground = Number(model.station.ground_elevation_m);
    const correction = ground - sample(.5, .5);
    const refraction = Number(model.curvature?.refraction_coefficient ?? .13);
    for (let i = 0; i < positions.count; i++) {
      const east = positions.getX(i), south = positions.getZ(i);
      const curvature = model.curvature?.enabled ? (east*east + south*south) / (2 * 6371000) * (1-refraction) : 0;
      positions.setY(i, sample(east / widthM + .5, south / depthM + .5) + correction - curvature);
    }
    // Cells outside the DEM radius are nodata, not low-elevation terrain.
    const radiusM = Number(model.radius_km) * 1000;
    const indices = geometry.index.array, validIndices = new Uint32Array(indices.length);
    const validVertices = new Uint8Array(positions.count);
    for (let i=0;i<positions.count;i++) {
      const east=positions.getX(i),south=positions.getZ(i);
      const col=Math.round((east/widthM+.5)*(image.width-1));
      const row=Math.round((south/depthM+.5)*(image.height-1));
      validVertices[i]=Math.hypot(east,south)<=radiusM && (!heightInfo || pixels[(row*image.width+col)*4+3]>0) ? 1 : 0;
    }
    let validCount=0;
    for (let i = 0; i < indices.length; i += 3) {
      const a=indices[i],b=indices[i+1],c=indices[i+2];
      if(validVertices[a]&&validVertices[b]&&validVertices[c]) {
        validIndices[validCount++]=a;validIndices[validCount++]=b;validIndices[validCount++]=c;
      }
    }
    geometry.setIndex(new THREE.BufferAttribute(validIndices.subarray(0,validCount),1));
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({map:overview, side:THREE.DoubleSide, roughness:1, metalness:0});
    // Nested imagery is selected on the same mesh, so it cannot z-fight or
    // create elevated terrain layers around the observer.
    material.onBeforeCompile = shader => {
      shader.uniforms.detailMap = {value:detail || overview};
      shader.uniforms.precisionMap = {value:precision || detail || overview};
      shader.uniforms.detailRatio = {value:detail ? widthM / (2 * Number(model.imagery?.detail_radius_m || 5000)) : 1};
      shader.uniforms.precisionRatio = {value:precision ? widthM / (2 * Number(model.imagery?.precision_radius_m || 1000)) : 1};
      shader.fragmentShader = `uniform sampler2D detailMap; uniform sampler2D precisionMap; uniform float detailRatio; uniform float precisionRatio;\n${shader.fragmentShader}`;
      shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
        vec4 texel = texture2D(map, vMapUv, -.35);
        vec2 detailUv = (vMapUv - .5) * detailRatio + .5;
        vec2 precisionUv = (vMapUv - .5) * precisionRatio + .5;
        if(detailRatio > 1. && all(greaterThanEqual(detailUv, vec2(0.))) && all(lessThanEqual(detailUv,vec2(1.)))) texel = mix(texel,texture2D(detailMap,detailUv,-.35),1.-smoothstep(.43,.5,max(abs(detailUv.x-.5),abs(detailUv.y-.5))));
        if(precisionRatio > 1. && all(greaterThanEqual(precisionUv,vec2(0.))) && all(lessThanEqual(precisionUv,vec2(1.)))) texel = mix(texel,texture2D(precisionMap,precisionUv,-.35),1.-smoothstep(.43,.5,max(abs(precisionUv.x-.5),abs(precisionUv.y-.5))));
        // A restrained colour grade keeps vegetation from looking neon under
        // the renderer's daylight, without manufacturing surface detail.
        float photographicLuma = dot(texel.rgb, vec3(.2126, .7152, .0722));
        texel.rgb = mix(vec3(photographicLuma), texel.rgb, .88);
        diffuseColor *= texel;`);
      // Use actual sightline distance for atmospheric extinction. Camera-Z
      // depth changes between cube faces and can leave visible haze seams.
      shader.fragmentShader = shader.fragmentShader.replace('#include <fog_fragment>', `
        #ifdef USE_FOG
          float aerialPerspective = 1. - exp(-fogDensity * length(vViewPosition));
          gl_FragColor.rgb = mix(gl_FragColor.rgb, fogColor, aerialPerspective);
        #endif`);
    };
    // Tile geometry for ray picking: testing a whole million-triangle mesh on
    // every pointer move would freeze the planning UI. Tiles share attributes.
    this.terrainGeometry=geometry;
    this.terrainMaterial=material;
    this.mesh = new THREE.Group();
    const stride=segments+1;
    for(let row=0;row<segments;row+=128) for(let col=0;col<segments;col+=128) {
      const endRow=Math.min(segments,row+128),endCol=Math.min(segments,col+128);
      const tileIndices=new Uint32Array((endRow-row)*(endCol-col)*6);
      let count=0;
      for(let y=row;y<endRow;y++) for(let x=col;x<endCol;x++) {
        const a=y*stride+x,b=a+stride,c=b+1,d=a+1;
        if(validVertices[a]&&validVertices[b]&&validVertices[d]){tileIndices[count++]=a;tileIndices[count++]=b;tileIndices[count++]=d;}
        if(validVertices[b]&&validVertices[c]&&validVertices[d]){tileIndices[count++]=b;tileIndices[count++]=c;tileIndices[count++]=d;}
      }
      if(!count)continue;
      const tileGeometry=new THREE.BufferGeometry();
      for(const name of ['position','normal','uv'])tileGeometry.setAttribute(name,geometry.attributes[name]);
      tileGeometry.setIndex(new THREE.BufferAttribute(tileIndices.subarray(0,count),1));
      tileGeometry.boundingBox=new THREE.Box3(
        new THREE.Vector3(-widthM/2+col/segments*widthM,elevationMin-100,-depthM/2+row/segments*depthM),
        new THREE.Vector3(-widthM/2+endCol/segments*widthM,elevationMin+elevationRange+100,-depthM/2+endRow/segments*depthM));
      tileGeometry.boundingSphere=tileGeometry.boundingBox.getBoundingSphere(new THREE.Sphere());
      this.mesh.add(new THREE.Mesh(tileGeometry,material));
    }
    this.scene.add(this.mesh);
    this.observer = new THREE.Vector3(0, ground + Number(model.station.elevation_above_ground_m || 0), 0);
    const marker = new THREE.Mesh(new THREE.SphereGeometry(35, 16, 12), new THREE.MeshBasicMaterial({color:0x5de3aa}));
    marker.position.copy(this.observer);
    this.stationMarker = marker;
    this.scene.add(marker);
    const cubeSize = Math.min(quality==='ultra' ? 4096 : quality==='high' ? 2048 : 1024, this.softwareRenderer?2048:4096, this.renderer.capabilities.maxCubemapSize);
    // Keep linear HDR colour until the final panorama pass. An 8-bit cube
    // clips bright terrain before tone mapping can retain its detail.
    const cubeType = this.renderer.extensions.has('EXT_color_buffer_float')
      ? THREE.HalfFloatType : THREE.UnsignedByteType;
    this.cubeTarget = new THREE.WebGLCubeRenderTarget(cubeSize, {type:cubeType, generateMipmaps:true, minFilter:THREE.LinearMipmapLinearFilter});
    this.cubeCamera = new THREE.CubeCamera(.5, Math.max(100000,Number(model.radius_km) * 2500), this.cubeTarget);
    this.cubeCamera.position.copy(this.observer);
    marker.visible = false;
    this.cubeCamera.update(this.renderer, this.scene);
    marker.visible = true;
    this.panoMaterial = new THREE.ShaderMaterial({vertexShader, fragmentShader, uniforms:{
      panorama:{value:this.cubeTarget.texture}, bounds:{value:new THREE.Vector4(0,360,-15,10)},
    }});
    this.panoScene = new THREE.Scene();
    this.panoQuad = new THREE.Mesh(new THREE.PlaneGeometry(2,2), this.panoMaterial);
    this.panoScene.add(this.panoQuad);
    this.panoCamera = new THREE.Camera();
    this.resetOrbit();
    this.ready = true;
    message.hidden = true;
    state.textContent = '3D terrain ready';
    state.title = `${heightInfo ? '16-bit' : '8-bit fallback'} · mesh ≈${Math.round(widthM / segments)} m · ${quality.toUpperCase()}. Source DEM ${model.grid_resolution_m} m; radius ${model.radius_km} km; AGL ${model.station.elevation_above_ground_m} m. Render resolution ${cubeSize}px per cube face.`;
    element('status').textContent = model.imagery?.attribution || '';
    this.resize();
  }

  clearTerrain() {
    if(this.mesh){
      this.scene.remove(this.mesh);
      this.mesh.traverse(object=>object.geometry?.dispose());
      this.terrainGeometry?.dispose();this.terrainMaterial?.dispose();
    }
    if(this.stationMarker){
      this.scene.remove(this.stationMarker);this.stationMarker.geometry.dispose();this.stationMarker.material.dispose();
    }
    this.assets.forEach(asset => asset?.dispose());
    this.cubeTarget?.dispose(); this.panoQuad?.geometry.dispose(); this.panoMaterial?.dispose();
  }

  resetOrbit() {
    if (!this.observer) return;
    this.controls.target.copy(this.observer);
    this.camera.position.set(6000, this.observer.y + 6500, 8000);
    this.controls.update();
  }

  fullBounds() {
    // Display coordinates are geographic and independent of mount scan limits.
    const b = {azMin:0,azMax:360,...this.altitudeRange};
    const view = angularWindow(b, this.zoom, this.center);
    return {...view,azMin:b.azMin,azMax:b.azMax};
  }

  bounds() {
    const b = this.fullBounds();
    if (this.mode !== 'panorama' || !this.trackWidth) return b;
    return scrollWindow(b,this.trackWidth,this.scroll.clientWidth,this.scroll.scrollLeft);
  }

  setDisplayZoom(value, x=.5, y=.5) {
    const zoom=Math.max(1,Math.min(8,Number(value)));
    if(!Number.isFinite(zoom)||zoom===this.zoom)return;
    const anchor=panoramaZoomAnchor(this.bounds(),this.altitudeRange,zoom,x,y);
    this.zoom=zoom;
    this.center.alt=anchor.alt;
    this.pointer=null;
    const select=element('terrainZoom');
    select.querySelector('[data-custom-zoom]')?.remove();
    if(![1,2,4,8].includes(zoom)){
      const option=new Option(`${zoom.toFixed(2)}× detail`,String(zoom));
      option.dataset.customZoom='true';select.add(option);
    }
    select.value=String(zoom);
    // Rebuild the horizontal track too, not just the altitude window.
    this.resize();
    this.scroll.scrollLeft=anchor.az/360*this.trackWidth-anchor.x*this.scroll.clientWidth;
    this.drawOverlay();
  }

  cameraDirection() {
    if(!this.model||!Number.isFinite(actualMountAz)||!Number.isFinite(actualMountAlt))return null;
    return geographicAngles(mountDirection(actualMountAz,actualMountAlt,this.pointingModel,Number(this.model.station.azimuth_north_offset_deg||0)));
  }

  focusCamera() {
    const actual=this.cameraDirection();
    if(!actual)return;
    this.initialCameraCentered=true;
    this.altitudeRange=includeCameraAltitude(this.altitudeRange,actual.alt);
    const live=this.freshThermalFov();
    if(live){
      const corners=geographicFovCorners(actual,live.horizontalDeg,live.verticalDeg,this.pointingModel,Number(this.model.station.azimuth_north_offset_deg||0));
      for(const corner of corners)this.altitudeRange=includeCameraAltitude(this.altitudeRange,corner.alt,.3);
    }
    this.zoom=1;element('terrainZoom').value='1';
    this.center={az:180,alt:(this.altitudeRange.altMin+this.altitudeRange.altMax)/2};
    this.pointer=null;
    this.resize();
    this.scroll.scrollLeft=actual.az/360*this.trackWidth-this.scroll.clientWidth/2;
    this.drawOverlay();
  }

  resize() {
    const stage = this.canvas.parentElement;
    if (!this.scroll.clientWidth || !this.scroll.clientHeight) return;
    const plotHeight = Math.max(40,this.scroll.clientHeight-44);
    const b = this.fullBounds();
    // Equal pixels per degree on both axes. The track can be wider than the
    // panel, while WebGL renders only its visible window, not a giant buffer.
    this.trackWidth = this.mode === 'panorama'
      ? panoramaTrackWidth(b,this.scroll.clientWidth,plotHeight)
      : this.scroll.clientWidth;
    this.track.style.width = `${this.trackWidth}px`;
    this.track.style.height = `${this.scroll.clientHeight}px`;
    stage.style.width = `${this.scroll.clientWidth}px`;
    stage.style.height = `${plotHeight}px`;
    this.renderer.setSize(stage.clientWidth,stage.clientHeight,false);
    this.camera.aspect = stage.clientWidth / stage.clientHeight;
    this.camera.updateProjectionMatrix();
    this.drawOverlay();
    this.schedule();
  }

  schedule() {
    if (this.frame || !this.ready || !this.visible || document.hidden) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      if (!this.ready || !this.visible || document.hidden) return;
      if (this.mode === 'panorama') {
        const b = this.bounds();
        this.panoMaterial.uniforms.bounds.value.set(b.azMin,b.azMax,b.altMin,b.altMax);
        this.renderer.render(this.panoScene, this.panoCamera);
      } else this.renderer.render(this.scene, this.camera);
    });
  }

  drawOverlay() {
    const overlay = element('terrainAxes');
    const width = this.canvas.clientWidth, height = this.canvas.clientHeight;
    if (!width || !height) return;
    if(this.ready&&!this.initialCameraCentered&&this.cameraDirection()) {
      this.focusCamera();
      return;
    }
    overlay.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const b = this.bounds(), azSpan = b.azMax-b.azMin, altSpan = b.altMax-b.altMin;
    let svg = '';
    const minimumStep = azSpan / Math.max(2, Math.floor(width/100));
    const step = [1,2,5,10,15,30,45,90,180].find(value => value >= minimumStep) || 180;
    const azimuthTicks = [b.azMin];
    for (let az=Math.ceil(b.azMin/step)*step;az<b.azMax;az+=step) {
      if (az-b.azMin>step*.55 && b.azMax-az>step*.55) azimuthTicks.push(az);
    }
    azimuthTicks.push(b.azMax);
    for (let i=0; i<azimuthTicks.length; i++) {
      const az=azimuthTicks[i], x=(az-b.azMin)/azSpan*width;
      const cardinal=({0:'N',90:'E',180:'S',270:'W',360:'N'})[Number(az.toFixed(5))]||'';
      svg += `<path class="terrain-grid" d="M${x} 0V${height}"/><text class="terrain-axis-text" x="${x}" y="${height+19}" text-anchor="${i===0?'start':i===azimuthTicks.length-1?'end':'middle'}">${Number(az.toFixed(1))}°${cardinal?' '+cardinal:''}</text>`;
    }
    let yLabels='';
    const altStep=[1,2,5,10,15,30,45].find(step=>step>=altSpan/Math.max(3,Math.floor(height/65)))||45;
    const altitudeTicks=[b.altMax];
    for(let alt=Math.floor(b.altMax/altStep)*altStep;alt>b.altMin;alt-=altStep) {
      if(b.altMax-alt>altStep*.55&&alt-b.altMin>altStep*.55)altitudeTicks.push(alt);
    }
    altitudeTicks.push(b.altMin);
    for (const alt of altitudeTicks) {
      const y = (b.altMax-alt)/altSpan*height;
      svg += `<path class="terrain-grid" d="M0 ${y}H${width}"/>`;
      yLabels += `<text class="terrain-axis-text" x="56" y="${Math.max(10,y+4)}" text-anchor="end">${alt>0?'+':''}${Number(alt.toFixed(1))}°</text>`;
    }
    const yAxis=element('terrainYAxis');
    yAxis.setAttribute('viewBox',`0 0 66 ${this.scroll.clientHeight}`);
    yAxis.style.height=`${this.scroll.clientHeight}px`;
    yAxis.innerHTML=yLabels+`<text class="terrain-axis-name" transform="translate(14 ${height/2}) rotate(-90)" text-anchor="middle">ALTITUDE</text>`;
    if (b.altMin<0 && b.altMax>0) svg += `<path class="terrain-grid terrain-zero" d="M0 ${b.altMax/altSpan*height}H${width}"/>`;
    svg += `<text class="terrain-axis-name" x="${width/2}" y="${height+35}" text-anchor="middle">TRUE AZIMUTH · 0° N / 90° E / 180° S / 270° W</text>`;
    const actual=this.cameraDirection();
    const liveFov=this.freshThermalFov();
    let liveBoxSize=null;
    if(actual&&liveFov&&this.mode==='panorama'){
      const corners=geographicFovCorners(actual,liveFov.horizontalDeg,liveFov.verticalDeg,this.pointingModel,Number(this.model.station.azimuth_north_offset_deg||0));
      const xs=corners.map(p=>(p.az-b.azMin)/azSpan*width),ys=corners.map(p=>(b.altMax-p.alt)/altSpan*height);
      liveBoxSize={width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};
      const polygons=[-360,0,360].map(shift=>`<polygon class="thermal-live-fov" data-hfov="${liveFov.horizontalDeg}" data-vfov="${liveFov.verticalDeg}" points="${corners.map(p=>`${(p.az+shift-b.azMin)/azSpan*width},${(b.altMax-p.alt)/altSpan*height}`).join(' ')}"><title>Estimated thermal optical FOV · ${liveFov.horizontalDeg.toFixed(2)}° × ${liveFov.verticalDeg.toFixed(2)}° · 640 × 512 native detector pixels; digital crop not reported</title></polygon>`).join('');
      svg+=`<svg width="${width}" height="${height}" overflow="hidden">${polygons}</svg>`;
    }
    if (actual) {
      const midpoint=(b.azMin+b.azMax)/2;
      const plotAz=[actual.az-360,actual.az,actual.az+360].reduce((best,az)=>Math.abs(az-midpoint)<Math.abs(best-midpoint)?az:best,actual.az);
      const x = (plotAz-b.azMin)/azSpan*width, y = (b.altMax-actual.alt)/altSpan*height;
      if(x>=0&&x<=width&&y>=0&&y<=height) {
        svg += `<g class="true-camera-marker" data-azimuth="${actual.az}" data-altitude="${actual.alt}" transform="translate(${x} ${y})"><path d="M-10 0h20M0-10v20" fill="none" stroke="#a3edff" stroke-width="1.5"/><title>Camera true bearing ${actual.az.toFixed(2)}° · altitude ${actual.alt.toFixed(2)}°</title></g>`;
      } else {
        const edgeX=Math.max(18,Math.min(width-18,x)),edgeY=Math.max(20,Math.min(height-20,y));
        const right=edgeX>width/2,labelX=right?-216:18,labelY=edgeY>height/2?-48:12;
        const angle=Math.atan2(y-edgeY,x-edgeX)*180/Math.PI;
        svg += `<g class="camera-edge-indicator" role="button" tabindex="0" aria-label="Camera outside this view; show camera position" data-azimuth="${actual.az}" data-altitude="${actual.alt}" transform="translate(${edgeX} ${edgeY})"><circle r="13" fill="#0a2535ed" stroke="#8be7ff" stroke-width="2"/><path d="M-5-6L6 0L-5 6" transform="rotate(${angle})" fill="none" stroke="#b1efff" stroke-width="2"/><rect x="${labelX}" y="${labelY}" width="198" height="38" rx="6" fill="#0a2535ed" stroke="#5a9ab4"/><text class="terrain-camera-hint" x="${labelX+10}" y="${labelY+14}">CAMERA OUTSIDE VIEW · CLICK</text><text class="terrain-camera-hint" x="${labelX+10}" y="${labelY+29}">TRUE AZ ${actual.az.toFixed(1)}° · ALT ${actual.alt.toFixed(1)}°</text><title>Click to show the actual camera direction</title></g>`;
      }
    }
    if (this.pointer && this.mode==='panorama') {
      const fov=this.currentFov();
      const corners=geographicFovCorners(this.pointer,...fov,this.pointingModel,Number(this.model?.station.azimuth_north_offset_deg||0));
      const polygons=[-360,0,360].map(shift=>`<polygon class="terrain-fov" points="${corners.map(p=>`${(p.az+shift-b.azMin)/azSpan*width},${(b.altMax-p.alt)/altSpan*height}`).join(' ')}"/>`).join('');
      svg += `<svg width="${width}" height="${height}" overflow="hidden">${polygons}</svg>`;
    }
    const scale=chartAngularScale(b,width,height);
    const setText=(id,text)=>{if(element(id).textContent!==text)element(id).textContent=text;};
    if(liveFov){
      setText('thermalLiveFov',`THERMAL OPTICAL · ${liveFov.horizontalDeg.toFixed(2)}° × ${liveFov.verticalDeg.toFixed(2)}°${liveFov.focalMm===null?'':` · ${liveFov.focalMm.toFixed(1)} mm`}${liveFov.zoomPct===null?'':` · ${liveFov.zoomPct.toFixed(1)}%`}`);
    }else{
      setText('thermalLiveFov','THERMAL OPTICAL FOV · zoom readback unavailable');
    }
    setText('thermalChartScale',`Chart ${scale.arcsecPerCssPixelX.toFixed(1)}″ × ${scale.arcsecPerCssPixelY.toFixed(1)}″ / CSS px${liveBoxSize?` · FOV box ≈ ${Math.round(liveBoxSize.width)} × ${Math.round(liveBoxSize.height)} px`:''}`);
    element('thermalLiveFov').title='Estimated from optical zoom readback and lens specifications. Digital zoom/crop is not reported, so this frame shows optical coverage only.';
    // Avoid unnecessary DOM work from the 10 Hz telemetry refresh.
    if (this.lastOverlay !== svg) { overlay.innerHTML = svg; this.lastOverlay = svg; }
    const renderBounds = [this.mode,width,height,b.azMin,b.azMax,b.altMin,b.altMax].join(':');
    if (renderBounds !== this.lastRenderBounds) {
      this.lastRenderBounds = renderBounds;
      this.schedule();
    }
  }

  currentFov() {
    return thermalFov(Number(element('scanZoomPct').value), Number(element('panoHFov').value)||14.2, Number(element('panoVFov').value)||11.4);
  }

  inspect(event) {
    if (!this.ready || this.drag) return;
    if (performance.now() - (this.lastInspect || 0) < 40) return;
    this.lastInspect = performance.now();
    const rect = this.canvas.getBoundingClientRect();
    const u=(event.clientX-rect.left)/rect.width, v=(event.clientY-rect.top)/rect.height;
    if (this.mode === 'panorama') {
      const b = this.bounds();
      this.pointer = {az:b.azMin+u*(b.azMax-b.azMin),alt:b.altMax-v*(b.altMax-b.altMin)};
    } else {
      this.pointer = null;
    }
    this.drawOverlay();
  }

  installEvents() {
    const canvas = this.canvas;
    const setMode = mode => {
      this.mode=mode; this.pointer=null; this.controls.enabled=mode==='orbit';
      canvas.parentElement.classList.toggle('is-orbit',mode==='orbit');
      element('terrainPanorama').setAttribute('aria-pressed',String(mode==='panorama'));
      element('terrainOrbit').setAttribute('aria-pressed',String(mode==='orbit'));
      element('terrainZoom').disabled=mode==='orbit';
      this.resize();
    };
    element('terrainPanorama').onclick=()=>setMode('panorama');
    element('terrainOrbit').onclick=()=>setMode('orbit');
    element('terrainZoom').onchange=event=>this.setDisplayZoom(event.target.value);
    element('terrainReset').onclick=()=>{this.setDisplayZoom(1);this.center.alt=(this.altitudeRange.altMin+this.altitudeRange.altMax)/2;this.resetOrbit();this.resize();};
    element('terrainQuality').onchange=reloadTerrain;
    this.scroll.addEventListener('scroll',()=>this.drawOverlay(),{passive:true});
    element('terrainCenter').onclick=()=>{
      if(!this.cameraDirection()){toast('Waiting for live camera position.');return;}
      setMode('panorama');this.focusCamera();
    };
    const overlay=element('terrainAxes');
    overlay.addEventListener('pointerdown',event=>{if(event.target.closest('.camera-edge-indicator')){event.preventDefault();this.focusCamera();}});
    overlay.addEventListener('click',event=>{if(event.target.closest('.camera-edge-indicator'))this.focusCamera();});
    overlay.addEventListener('keydown',event=>{if(event.target.closest('.camera-edge-indicator')&&['Enter',' '].includes(event.key)){event.preventDefault();this.focusCamera();}});
    canvas.addEventListener('pointerdown',event=>{
      canvas.focus();if(this.mode!=='panorama')return;
      canvas.setPointerCapture(event.pointerId);this.drag={id:event.pointerId,x:event.clientX,y:event.clientY,scrollLeft:this.scroll.scrollLeft,center:{...this.center},bounds:this.bounds()};
    });
    canvas.addEventListener('pointermove',event=>{
      if(this.drag&&this.mode==='panorama'){
        const d=this.drag,b=d.bounds;
        this.scroll.scrollLeft=d.scrollLeft-(event.clientX-d.x);
        this.center={az:d.center.az,alt:d.center.alt+(event.clientY-d.y)/canvas.clientHeight*(b.altMax-b.altMin)};
        const bounded=this.fullBounds();this.center={az:(bounded.azMin+bounded.azMax)/2,alt:(bounded.altMin+bounded.altMax)/2};this.drawOverlay();
      }else this.inspect(event);
    });
    canvas.addEventListener('pointerup',()=>{this.drag=null;});
    canvas.addEventListener('pointercancel',()=>{this.drag=null;});
    canvas.addEventListener('pointerleave',()=>{if(!this.drag){this.pointer=null;this.drawOverlay();}});
    canvas.addEventListener('wheel',event=>{
      if(this.mode!=='panorama')return;
      if(event.shiftKey||Math.abs(event.deltaX)>Math.abs(event.deltaY))return;
      event.preventDefault();
      const rect=canvas.getBoundingClientRect();
      const unit=event.deltaMode===1?16:event.deltaMode===2?canvas.clientHeight:1;
      const delta=Math.max(-240,Math.min(240,event.deltaY*unit));
      this.setDisplayZoom(this.zoom*Math.exp(-delta*.002),
        (event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height);
    },{passive:false});
    canvas.addEventListener('keydown',event=>{
      if(this.mode!=='panorama')return;
      const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,1],ArrowDown:[0,-1]}[event.key];
      if(!delta)return;event.preventDefault();const b=this.bounds();
      this.scroll.scrollLeft+=delta[0]*this.scroll.clientWidth*.15;
      this.center.alt+=delta[1]*(b.altMax-b.altMin)*.1;this.drawOverlay();
    });
    canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();this.ready=false;this.fail(Error('3D graphics context was lost. Refresh Mission Design to retry.'));});
    canvas.addEventListener('webglcontextrestored',()=>this.load().catch(error=>this.fail(error)));
    window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===parent&&event.data?.type==='mission-visibility'){this.visible=event.data.visible===true;if(this.visible)this.resize();}});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)this.schedule();});
    new ResizeObserver(()=>this.resize()).observe(this.scroll);
    window.addEventListener('pagehide',()=>{this.thermalPollClosed=true;clearTimeout(this.thermalPollTimer);cancelAnimationFrame(this.frame);this.controls.dispose();this.clearTerrain();this.sky.geometry.dispose();this.sky.material.dispose();this.renderer.dispose();},{once:true});
  }

  fail(error) {
    state.textContent='3D terrain unavailable';state.dataset.error='true';
    element('terrainMessage').hidden=false;
    element('terrainMessage').textContent=error.message;
    element('status').textContent=error.message;
    console.error('Mission terrain:',error);
  }
}

async function reloadTerrain() {
  const button=element('createDemPanorama');button.disabled=true;
  try {
    terrain ||= new MissionTerrain(element('missionTerrainCanvas'));
    await terrain.load();
  } catch(error) {
    if(terrain)terrain.fail(error);
    else {state.textContent='WebGL unavailable';state.dataset.error='true';element('terrainMessage').textContent='This browser could not start 3D graphics. Enable hardware acceleration and reload.';}
  } finally {button.disabled=false;button.textContent='Reload 3D terrain';}
}
element('createDemPanorama').onclick=reloadTerrain;
reloadTerrain();
