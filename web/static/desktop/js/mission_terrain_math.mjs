// Shared numerical conventions: mount = east/north/up, scene = east/up/south.
export function mountDirection(azimuth, altitude, model = {}, northOffset = 0) {
  const az = azimuth * Math.PI / 180, alt = altitude * Math.PI / 180;
  if (model.active === true && model.mode === 'single_point_offset') {
    return mountDirection(azimuth - Number(model.azimuth_offset_deg || 0),
      altitude - Number(model.altitude_offset_deg || 0), {}, northOffset);
  }
  let vector = [Math.cos(alt) * Math.sin(az), Math.cos(alt) * Math.cos(az), Math.sin(alt)];
  if (model.active === true && Array.isArray(model.rotation_matrix)) {
    vector = model.rotation_matrix.map(row => row.reduce((sum, value, i) => sum + value * vector[i], 0));
  }
  const offset = northOffset * Math.PI / 180;
  const [e, n, u] = vector;
  const result = [e * Math.cos(offset) - n * Math.sin(offset), u,
    -(n * Math.cos(offset) + e * Math.sin(offset))];
  const length = Math.hypot(...result);
  return result.map(value => value / length);
}

// Geographic bearing is clockwise from true north; scene north is -Z.
export function geographicDirection(azimuth, altitude) {
  const az=azimuth*Math.PI/180, alt=altitude*Math.PI/180;
  return [Math.cos(alt)*Math.sin(az),Math.sin(alt),-Math.cos(alt)*Math.cos(az)];
}

export function geographicAngles([east,up,south]) {
  const length=Math.hypot(east,up,south);
  return {az:(Math.atan2(east,-south)*180/Math.PI+360)%360,
    alt:Math.asin(Math.max(-1,Math.min(1,up/length)))*180/Math.PI};
}

export function geographicToMount(azimuth,altitude,model={},northOffset=0) {
  const trueAz=(azimuth+northOffset)*Math.PI/180, alt=altitude*Math.PI/180;
  let vector=[Math.cos(alt)*Math.sin(trueAz),Math.cos(alt)*Math.cos(trueAz),Math.sin(alt)];
  if(model.active===true&&model.mode==='single_point_offset') {
    return {az:(azimuth+northOffset+Number(model.azimuth_offset_deg||0)+360)%360,
      alt:altitude+Number(model.altitude_offset_deg||0)};
  }
  if(model.active===true&&Array.isArray(model.rotation_matrix)) {
    const matrix=model.rotation_matrix;
    vector=[0,1,2].map(col=>matrix.reduce((sum,row,i)=>sum+row[col]*vector[i],0));
  }
  const [east,north,up]=vector,length=Math.hypot(...vector);
  return {az:(Math.atan2(east,north)*180/Math.PI+360)%360,
    alt:Math.asin(Math.max(-1,Math.min(1,up/length)))*180/Math.PI};
}

export function geographicFovCorners(center,horizontalFov,verticalFov,model={},northOffset=0) {
  const mount=geographicToMount(center.az,center.alt,model,northOffset);
  const az=mount.az*Math.PI/180, alt=mount.alt*Math.PI/180;
  const forward=[Math.cos(alt)*Math.sin(az),Math.cos(alt)*Math.cos(az),Math.sin(alt)];
  const right=[Math.cos(az),-Math.sin(az),0];
  const up=[-Math.sin(alt)*Math.sin(az),-Math.sin(alt)*Math.cos(az),Math.cos(alt)];
  const tx=Math.tan(horizontalFov*Math.PI/360),ty=Math.tan(verticalFov*Math.PI/360);
  return [[-1,1],[1,1],[1,-1],[-1,-1]].map(([x,y])=>{
    const v=forward.map((value,i)=>value+right[i]*tx*x+up[i]*ty*y),length=Math.hypot(...v);
    const mountAz=Math.atan2(v[0],v[1])*180/Math.PI,mountAlt=Math.asin(v[2]/length)*180/Math.PI;
    const result=geographicAngles(mountDirection(mountAz,mountAlt,model,northOffset));
    return {...result,az:center.az+((result.az-center.az+540)%360)-180};
  });
}

export function thermalFov(percent, horizontalWide, verticalWide) {
  const ratio = (31 + 124 * Math.max(0, Math.min(100, percent)) / 100) / 31;
  return [horizontalWide, verticalWide].map(fov =>
    2 * Math.atan(Math.tan(fov * Math.PI / 360) / ratio) * 180 / Math.PI);
}

export function footprint(distanceM, horizontalFov, verticalFov) {
  return [horizontalFov, verticalFov].map(fov => 2 * distanceM * Math.tan(fov * Math.PI / 360));
}

export function angularWindow(bounds, zoom, center) {
  const azSpan = (bounds.azMax - bounds.azMin) / zoom;
  const altSpan = (bounds.altMax - bounds.altMin) / zoom;
  const azCenter = Math.max(bounds.azMin + azSpan / 2, Math.min(bounds.azMax - azSpan / 2, center.az));
  const altCenter = Math.max(bounds.altMin + altSpan / 2, Math.min(bounds.altMax - altSpan / 2, center.alt));
  return {azMin:azCenter - azSpan / 2, azMax:azCenter + azSpan / 2,
    altMin:altCenter - altSpan / 2, altMax:altCenter + altSpan / 2};
}

export function scrollWindow(bounds, trackWidth, viewportWidth, scrollLeft) {
  if (trackWidth <= viewportWidth || viewportWidth <= 0) return {...bounds};
  const span = bounds.azMax - bounds.azMin;
  const visibleSpan = span * viewportWidth / trackWidth;
  const progress = Math.max(0,Math.min(1,scrollLeft/(trackWidth-viewportWidth)));
  const start = bounds.azMin + progress*(span-visibleSpan);
  return {...bounds,azMin:start,azMax:start+visibleSpan};
}

export function panoramaTrackWidth(bounds, viewportWidth, plotHeight) {
  return Math.ceil(Math.max(viewportWidth,
    plotHeight*(bounds.azMax-bounds.azMin)/(bounds.altMax-bounds.altMin)));
}

// Preserve the geographic point under the cursor while both axes zoom.
export function panoramaZoomAnchor(bounds, altitudeRange, zoom, x=.5, y=.5) {
  x=Math.max(0,Math.min(1,x));y=Math.max(0,Math.min(1,y));
  const az=bounds.azMin+x*(bounds.azMax-bounds.azMin);
  const alt=bounds.altMax-y*(bounds.altMax-bounds.altMin);
  const span=(altitudeRange.altMax-altitudeRange.altMin)/zoom;
  return {az,alt:alt-(.5-y)*span,x};
}

export function includeCameraAltitude(bounds, altitude, margin=1) {
  if(!Number.isFinite(altitude))return {...bounds};
  return {...bounds,
    altMin:Math.max(-90,Math.min(bounds.altMin,Math.floor((altitude-margin)/5)*5)),
    altMax:Math.min(90,Math.max(bounds.altMax,Math.ceil((altitude+margin)/5)*5))};
}

export function thermalFrameFov(frame) {
  const m=frame?.metadata;
  // Never substitute the planning zoom or the visible camera's linked zoom.
  if(frame?.ok!==true||frame.source!=='live'||frame.camera!=='thermal'||
      !m||m.source_verified!==true||m.simulated!==false||
      !Number.isFinite(frame.age_ms)||frame.age_ms<0||frame.age_ms>2000)return null;
  const positive=value=>typeof value==='number'&&Number.isFinite(value)&&value>0;
  const zoom=typeof m.zoom_pct==='number'&&Number.isFinite(m.zoom_pct)&&m.zoom_pct>=0&&m.zoom_pct<=100?m.zoom_pct:null;
  const focal=positive(m.focal_length_mm)?m.focal_length_mm:zoom===null?null:31+124*zoom/100;
  let h=m.fov_h_deg,v=m.fov_v_deg;
  if(!positive(h)||!positive(v)||h>=180||v>=180){
    if(!positive(focal))return null;
    [h,v]=thermalFov((focal-31)/124*100,14.2,11.4);
  }
  // The PDF specifies the native detector, regardless of encoded stream size.
  return {horizontalDeg:h,verticalDeg:v,focalMm:focal,zoomPct:zoom,
    nativeWidth:640,nativeHeight:512,arcsecPerPixelX:h*3600/640,
    arcsecPerPixelY:v*3600/512,digitalZoomKnown:false};
}

export function chartAngularScale(bounds,width,height) {
  return {arcsecPerCssPixelX:(bounds.azMax-bounds.azMin)*3600/width,
    arcsecPerCssPixelY:(bounds.altMax-bounds.altMin)*3600/height};
}
