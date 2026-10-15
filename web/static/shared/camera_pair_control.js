(function cameraPairControl(global){
  "use strict";
  const SELECTORS=[".camera-live-grid",".cameras",".camera-monitor-feeds",".pointing-alignment-cameras",".pointing-camera-body",".camera-calibration-previews"];
  function inferLayout(element){
    if(element.dataset.cameraLayout)return element.dataset.cameraLayout;
    if(element.classList.contains("cameras")||element.classList.contains("pointing-camera-body"))return "vertical";
    return "horizontal";
  }
  function normalizeResolutionLabels(root){
    for(const element of root.querySelectorAll("header span,.cam-head small,.camera-monitor-feed header em")){
      if(/1920\s*[×x]\s*1080/.test(element.textContent||""))element.textContent=element.textContent.replace(/1920\s*[×x]\s*1080/g,"1280 × 720");
    }
  }
  function upgrade(element,layout){
    if(!element)return null;
    element.classList.add("narit-camera-pair");
    element.dataset.layout=layout||inferLayout(element);
    normalizeResolutionLabels(element);
    return element;
  }
  function upgradeAll(root=document){
    for(const selector of SELECTORS)for(const element of root.querySelectorAll(selector))upgrade(element);
  }
  const api={upgrade,upgradeAll,setLayout(element,layout){return upgrade(element,layout==="vertical"?"vertical":"horizontal")}};
  global.NaritCameraPair=api;
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>upgradeAll());else upgradeAll();
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)if(node.nodeType===1){for(const selector of SELECTORS){if(node.matches?.(selector))upgrade(node);for(const child of node.querySelectorAll?.(selector)||[])upgrade(child)}}}).observe(document.documentElement,{childList:true,subtree:true});
})(window);
