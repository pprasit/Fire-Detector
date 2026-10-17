import test from 'node:test';
import assert from 'node:assert/strict';
import {mountDirection, geographicDirection, geographicAngles, geographicToMount, geographicFovCorners, thermalFov, footprint, angularWindow, scrollWindow, panoramaTrackWidth, panoramaZoomAnchor, includeCameraAltitude, thermalFrameFov, chartAngularScale} from '../web/static/desktop/js/mission_terrain_math.mjs';

const close = (actual, expected) => actual.forEach((value, i) => assert.ok(Math.abs(value - expected[i]) < 1e-9));
test('mount directions use scene east/up/south and station north offset', () => {
  close(mountDirection(0,0), [0,0,-1]);
  close(mountDirection(90,0), [1,0,0]);
  close(mountDirection(0,90), [0,1,0]);
  close(mountDirection(0,0,{},90), [-1,0,0]);
});
test('geographic chart directions always use true north, east, south and west', () => {
  close(geographicDirection(0,0),[0,0,-1]);
  close(geographicDirection(90,0),[1,0,0]);
  close(geographicDirection(180,0),[0,0,1]);
  close(geographicDirection(270,0),[-1,0,0]);
});
test('camera marker converts mount bearing through alignment and station offset', () => {
  const result=geographicAngles(mountDirection(90,0,{},90));
  assert.ok(Math.abs(result.az)<1e-9);assert.ok(Math.abs(result.alt)<1e-9);
  const west=geographicAngles(mountDirection(0,0,{},90));
  assert.ok(Math.abs(west.az-270)<1e-9);
});
test('geographic sightline round trips through rigid and single-point models', () => {
  const models=[{}, {active:true,mode:'single_point_offset',azimuth_offset_deg:2,altitude_offset_deg:-1},
    {active:true,rotation_matrix:[[0,-1,0],[1,0,0],[0,0,1]]}];
  for(const model of models)for(const az of [0,35,90,180,270,359])for(const alt of [-15,0,10]) {
    const mount=geographicToMount(az,alt,model,90);
    close(mountDirection(mount.az,mount.alt,model,90),geographicDirection(az,alt));
  }
});
test('FOV corners stay continuous across true north and retain roll correction', () => {
  const corners=geographicFovCorners({az:0,alt:0},10,8,{},90);
  assert.ok(corners[0].az<0 && corners[1].az>0);
  assert.ok(corners.every(p=>Math.abs(p.az)<6&&Math.abs(p.alt)<5));
  const roll=Math.PI/6,model={active:true,rotation_matrix:[[Math.cos(roll),0,Math.sin(roll)],[0,1,0],[-Math.sin(roll),0,Math.cos(roll)]]};
  const rolled=geographicFovCorners({az:0,alt:0},10,8,model,0);
  assert.ok(Math.abs(rolled[0].alt-rolled[1].alt)>1);
});
test('single-point model agrees with renderer geographic sightlines', () => {
  close(mountDirection(10,2,{active:true,mode:'single_point_offset',azimuth_offset_deg:1,altitude_offset_deg:-3},90),mountDirection(9,5,{},90));
});
test('rigid rotation maps mount east onto device north', () => {
  close(mountDirection(90,0,{active:true,rotation_matrix:[[0,-1,0],[1,0,0],[0,0,1]]}),[0,0,-1]);
});
test('zoom narrows the FOV while footprint scales with target slant range', () => {
  close(thermalFov(0,14.2,11.4),[14.2,11.4]);
  const planned=thermalFov(10,14.2,11.4);
  assert.ok(Math.abs(planned[0]-10.17)<.02);
  assert.ok(Math.abs(planned[1]-8.16)<.02);
  assert.ok(Math.abs(thermalFov(100,14.2,11.4)[0]-2.85)<.02);
  assert.ok(thermalFov(100,14.2,11.4)[0] < thermalFov(10,14.2,11.4)[0]);
  close(footprint(100,90,90),[200,200]);
  const fov=thermalFov(10,14.2,11.4);
  close(footprint(200,...fov),footprint(100,...fov).map(v=>v*2));
});
test('detail view stays inside scan bounds at both extremes', () => {
  const bounds={azMin:0,azMax:360,altMin:-15,altMax:10};
  assert.deepEqual(angularWindow(bounds,4,{az:359,alt:10}),{azMin:270,azMax:360,altMin:3.75,altMax:10});
  assert.deepEqual(angularWindow(bounds,4,{az:-200,alt:-100}),{azMin:0,azMax:90,altMin:-15,altMax:-8.75});
  assert.deepEqual(angularWindow(bounds,1,{az:330,alt:8}),bounds);
});
test('scrolling spans the whole panorama without changing the altitude axis', () => {
  const b={azMin:0,azMax:360,altMin:-15,altMax:10};
  assert.deepEqual(scrollWindow(b,7200,1200,0),{...b,azMin:0,azMax:60});
  assert.deepEqual(scrollWindow(b,7200,1200,3000),{...b,azMin:150,azMax:210});
  assert.deepEqual(scrollWindow(b,7200,1200,6000),{...b,azMin:300,azMax:360});
  assert.deepEqual(scrollWindow(b,7200,1200,9000),{...b,azMin:300,azMax:360});
  assert.deepEqual(scrollWindow(b,1000,1200,0),b);
});
test('camera below the default true horizon window is included at its real angle',()=>{
  const b={altMin:-15,altMax:10};
  assert.deepEqual(includeCameraAltitude(b,-15.8),{altMin:-20,altMax:10});
  assert.deepEqual(includeCameraAltitude(b,13),{altMin:-15,altMax:15});
  assert.deepEqual(includeCameraAltitude(b,-5),b);
  assert.equal(includeCameraAltitude(b,-89.9).altMin,-90);
  assert.equal(includeCameraAltitude(b,89.9).altMax,90);
  assert.deepEqual(includeCameraAltitude(b,NaN),b);
});

test('DEM zoom rebuilds the scroll track and magnifies X and Y equally',()=>{
  const full={azMin:0,azMax:360,altMin:-20,altMax:10},width=1200,height=600;
  const scales=[1,2,4,8].map(zoom=>{
    const vertical=angularWindow(full,zoom,{az:180,alt:-5});
    const b={...vertical,azMin:0,azMax:360};
    const track=panoramaTrackWidth(b,width,height);
    const view=scrollWindow(b,track,width,0);
    return chartAngularScale(view,width,height);
  });
  scales.forEach((scale,i)=>{
    close([scale.arcsecPerCssPixelX,scale.arcsecPerCssPixelY],[180/2**i,180/2**i]);
  });
});

test('DEM zoom anchors the cursor geographic point and round trips without drift',()=>{
  const range={azMin:0,azMax:360,altMin:-20,altMax:10},width=1200,height=600;
  let b={azMin:100,azMax:160,altMin:-20,altMax:10};
  for(const zoom of [2,4,8,4,2,1]){
    const anchor=panoramaZoomAnchor(b,range,zoom,.3,.6);
    const v=angularWindow(range,zoom,{az:180,alt:anchor.alt});
    const full={...v,azMin:0,azMax:360};
    const track=panoramaTrackWidth(full,width,height);
    const next=scrollWindow(full,track,width,anchor.az/360*track-anchor.x*width);
    close([next.azMin+.3*(next.azMax-next.azMin),next.altMax-.6*(next.altMax-next.altMin)],[118,-8]);
    b=next;
  }
  close([b.azMin,b.azMax,b.altMin,b.altMax],[100,160,-20,10]);
});

test('DEM zoom clamps at the panorama edges without escaping geographic bounds',()=>{
  const range={azMin:0,azMax:360,altMin:-20,altMax:10};
  for(const az of [0,359])for(const alt of [-20,10]){
    const b={azMin:az,azMax:az+1,altMin:alt,altMax:alt+1};
    const anchor=panoramaZoomAnchor(b,range,1,1,0);
    const vertical=angularWindow(range,1,{az:anchor.az,alt:anchor.alt});
    const full={...vertical,azMin:0,azMax:360};
    const track=panoramaTrackWidth(full,1200,600);
    const result=scrollWindow(full,track,1200,anchor.az/360*track-1200);
    assert.ok(result.azMin>=0&&result.azMax<=360);
    assert.equal(result.altMin,-20);assert.equal(result.altMax,10);
  }
});
const freshThermal=(metadata={})=>({ok:true,source:'live',camera:'thermal',age_ms:20,
  metadata:{source_verified:true,simulated:false,fov_h_deg:14.2,fov_v_deg:11.4,focal_length_mm:31,zoom_pct:0,...metadata}});
test('datasheet FOV yields native detector angular sampling, not stream pixel sampling',()=>{
  const wide=thermalFrameFov(freshThermal({width:1920,height:1080}));
  close([wide.arcsecPerPixelX,wide.arcsecPerPixelY],[79.875,80.15625]);
  assert.equal(wide.nativeWidth,640);assert.equal(wide.nativeHeight,512);
  const tele=thermalFrameFov(freshThermal({fov_h_deg:2.8,fov_v_deg:2.3,focal_length_mm:155,zoom_pct:100}));
  close([tele.arcsecPerPixelX,tele.arcsecPerPixelY],[15.75,16.171875]);
  assert.ok(tele.horizontalDeg<wide.horizontalDeg);
  const live=thermalFrameFov(freshThermal({fov_h_deg:7.39,fov_v_deg:5.92,focal_length_mm:59.8,zoom_pct:23.2}));
  close([live.arcsecPerPixelX,live.arcsecPerPixelY],[41.56875,41.625]);
});
test('FOV is not fabricated for stale, simulated or missing thermal readback',()=>{
  assert.equal(thermalFrameFov(null),null);
  assert.equal(thermalFrameFov({...freshThermal(),age_ms:2001}),null);
  assert.equal(thermalFrameFov({...freshThermal(),camera:'visible'}),null);
  assert.equal(thermalFrameFov(freshThermal({simulated:true})),null);
  assert.equal(thermalFrameFov(freshThermal({source_verified:false})),null);
  assert.equal(thermalFrameFov(freshThermal({fov_h_deg:null,fov_v_deg:null,focal_length_mm:null,zoom_pct:null})),null);
  assert.ok(thermalFrameFov(freshThermal({fov_h_deg:null,fov_v_deg:null,focal_length_mm:155,zoom_pct:null})).horizontalDeg<3);
});
test('chart pixel scale changes with display zoom independently of sensor IFOV',()=>{
  const bounds={azMin:0,azMax:60,altMin:-20,altMax:10};
  const scale=chartAngularScale(bounds,1200,600);
  close([scale.arcsecPerCssPixelX,scale.arcsecPerCssPixelY],[180,180]);
  assert.equal(chartAngularScale(bounds,2400,1200).arcsecPerCssPixelX,90);
  assert.equal(thermalFrameFov(freshThermal()).arcsecPerPixelX,79.875);
});
