'use strict';
// Main quest 1-2-1, zone 1 BOUNDS: art (46,0,180,320), world (276,0,1080,1920).
// This reference is normalized to its top-left. Actor/target markers are editorial, not spawn points.
const SPATIAL_REFERENCE={version:1,profile:'reference',width:1080,height:1920,originX:540,originY:1440,targetX:540,targetY:576};
const SPATIAL_REFERENCE_LABEL='主线 1-2-1 · 第 2 区域实尺参考';
const SPATIAL_REFERENCE_DESCRIPTION='内置参考取自主线 1-2-1「追蘑菇1」第 2 区域（zone 1）的地图边界：1080 × 1920 世界单位，即 180 × 320 美术单位。不是手机分辨率，也不代表所有关卡。地图左上世界坐标 (276,0) 在本预览中归为 (0,0)；角色与目标点是人工摆放的参考点，不是官方出生点。';
// Optional authoring aids. No camera/physics/target-following is simulated here.
const spatialState={project:null,mode:'field',guides:true,pick:false,view:null,drag:null};
const spatialAlphaCache=new WeakMap();
function spatialDefaults(){return {...SPATIAL_REFERENCE};}
function spatialField(){return S.p.previewStage||spatialDefaults();}
function spatialResetProject(){if(spatialState.project!==S.p.id){spatialState.project=S.p.id;spatialState.mode='field';spatialState.pick=false;spatialState.drag=null;} }
function spatialEnabled(){return ['animations','effects','scene'].includes(S.page);}
function spatialView(w,h){if(!spatialEnabled())return null;spatialResetProject();if(spatialState.mode!=='field')return null;return SpatialGeometry.fitField(spatialField(),w,h,S.zoom);}
function spatialPanel(){
  if(!spatialEnabled())return '';spatialResetProject();
  return `<section class="spatial-panel" aria-label="尺寸与场地定位"><div class="spatial-heading"><strong>尺寸与场地定位</strong><span class="spatial-modes" role="group" aria-label="预览比例"><button data-spatial-mode="field" aria-pressed="${spatialState.mode==='field'}">场地比例</button><button data-spatial-mode="fit" aria-pressed="${spatialState.mode==='fit'}">素材放大</button></span></div><div class="spatial-subline"><span id="spatial-profile-label"></span><span><button id="spatial-export" class="quiet">导出定位参考图</button><button id="spatial-settings" class="quiet">场地设置</button></span></div><div class="spatial-reading" id="spatial-size">导入画稿后，可查看真实像素范围</div><p id="spatial-hint" class="spatial-help"></p></section>`;
}
function spatialImageBounds(asset){
  const im=getImage(asset);if(!im?.complete||!im.naturalWidth)return null;
  if(!spatialAlphaCache.has(im)){
    const c=document.createElement('canvas');c.width=im.naturalWidth;c.height=im.naturalHeight;
    const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(im,0,0);
    spatialAlphaCache.set(im,SpatialGeometry.alphaBounds(ctx.getImageData(0,0,c.width,c.height).data,c.width,c.height));
  }
  return spatialAlphaCache.get(im);
}
function spatialSelection(){
  if(S.page==='scene'){
    const t=S.p.scene.tracks.find(t=>t.id===S.selected);if(!t||t.type==='audio')return null;
    const a=(t.type==='actor'?S.p.animations:S.p.effects).find(a=>a.id===t.ref);if(!a)return null;
    const tick=S.tick<t.start?-1:t.freezeFrame??Math.floor((S.tick-t.start)*(t.speed||1)*(a.runtimeSpeed||1));
    return {item:t,anim:a,tick,scale:1,track:true,active:t.visible!==false&&S.tick>=t.start&&(t.end<0||t.end==null||S.tick<t.end)};
  }
  const a=current();if(!a)return null;
  return {item:a.native?null:a.clips[S.clip],anim:a,tick:S.tick,scale:a.frameScale||1,track:false,active:true};
}
function spatialAtTick(a,tick){
  if(tick<0)return null;const len=duration(a);if(a.kind==='stop')tick=0;else if(tick>=len){if(a.kind==='loop')tick%=len;else if(a.kind==='once')tick=len-1;else return null;}
  return a.native?{...a,nativeFrames:[effectFrames(a)[tick]||[]],channels:undefined,channelDuration:undefined}:{...a,clips:a.clips.length?[a.clips[clipIndex(a,tick)]]:[]};
}
function spatialBounds(selection,visible=true){
  const {anim:a,item,tick,track}=selection;const frame=spatialAtTick(track&&item.playMode?{...a,kind:item.playMode}:a,tick);
  if(!frame||!selection.active||(track&&item.opacity===0))return null;
  if(!a.native){
    const c=frame.clips[0],asset=c&&S.p.assets[c.asset];if(!asset||c.opacity===0)return null;
    const b=visible?spatialImageBounds(c.asset):{x:0,y:0,width:asset.width,height:asset.height};if(!b)return null;
    let m=PreviewLayout.multiply(PreviewLayout.transform(0,0,a.frameScale||1),SpatialGeometry.clipMatrix(c,asset.width,asset.height));
    if(track)m=PreviewLayout.multiply(PreviewLayout.transform(item.x||0,item.y||0,item.scale||1,item.rotation||0),m);
    return SpatialGeometry.bounds(m,b);
  }
  // Native commands retain their own pivot, trim and layer matrices. Do not recenter them.
  const frames=effectFrames(a),len=frames.length;let nt=tick;
  if((item?.playMode||a.kind)==='stop')nt=0;else if(nt>=len)nt=(item?.playMode||a.kind)==='loop'?nt%len:len-1;
  const parent=track?PreviewLayout.transform(item.x||0,item.y||0,item.scale||1,item.rotation||0):[1,0,0,1,0,0];
  const b=PreviewLayout.commands(PreviewLayout.empty(),[frames[nt]||[]],S.p.assets,a.frameScale||1,parent,a.channels?{}:a.layers);
  return Number.isFinite(b.minX)?b:null;
}
function spatialNumber(n){return Number.isInteger(n)?String(n):Number(n.toFixed(2)).toString();}
function spatialUpdateReading(view){
  const node=$('#spatial-size');if(!node)return;
  const f=spatialField(),sel=spatialSelection(),b=sel&&spatialBounds(sel),isReference=f.profile==='reference'&&f.width===SPATIAL_REFERENCE.width&&f.height===SPATIAL_REFERENCE.height;
  $('#spatial-profile-label').textContent=`${isReference?SPATIAL_REFERENCE_LABEL:'自定义参考场地'} · ${f.width} × ${f.height} 世界单位`;
  const parts=[];
  if(sel&&!sel.anim.native&&!sel.track&&sel.item){const shown=sel.anim.clips[clipIndex(sel.anim,S.tick)]||sel.item,a=S.p.assets[shown.asset],v=spatialImageBounds(shown.asset);parts.push(`原图 ${a.width} × ${a.height} px（含透明边）`);parts.push(v?`可见画稿 ${v.width} × ${v.height} px`:'这张画稿完全透明');parts.push(`游戏显示倍率 ${sel.anim.frameScale||1}× · 画稿缩放 ${shown.scale||1}×`);}
  if(b){const bw=b.maxX-b.minX,bh=b.maxY-b.minY;parts.push(`${sel.anim.native?'本帧图层范围':'本帧可见范围'} ${spatialNumber(bw)} × ${spatialNumber(bh)} 场地单位`);parts.push(`占场宽 ${spatialNumber(bw/f.width*100)}% · 高 ${spatialNumber(bh/f.height*100)}%`);if(SpatialGeometry.outside(b,f))parts.push('超出参考场地边界（不是错误，可继续调整）');}
  if(sel?.track&&sel.item){parts.push(`锚点 X ${spatialNumber(f.originX+(sel.item.x||0))} / Y ${spatialNumber(f.originY+(sel.item.y||0))}`);if(!sel.active)parts.push('当前播放帧尚未出现或已结束，定位十字仍可调整');}
  node.textContent=parts.join('　·　')||'选择已有画稿或技能内容，查看尺寸与位置';
  node.classList.toggle('spatial-warning',!!b&&SpatialGeometry.outside(b,f));
  const edit=sel?.item&&!sel.anim.native||sel?.track;
  $('#spatial-hint').textContent=spatialState.pick?'请点画稿上的脚底或中心；此点会移到紫色十字。Esc 取消。':`${spatialState.mode==='field'?'场地不会随素材大小自动缩放':'仅放大看细节，不代表游戏中的大小'}。${edit?'拖动选中画面或十字调整位置；方向键微调，Shift 加速。':'原生骨架保留原有定位，请在技能预览中摆放整个特效。'} 1 美术单位 = 6 世界单位；不含碰撞和镜头。`;
  if($('#spatial-coordinate-x')&&sel?.item){const px=sel.track?f.originX+(sel.item.x||0):sel.item.x||0,py=sel.track?f.originY+(sel.item.y||0):sel.item.y||0;if(document.activeElement!==$('#spatial-coordinate-x'))$('#spatial-coordinate-x').value=String(SpatialGeometry.round(px));if(document.activeElement!==$('#spatial-coordinate-y'))$('#spatial-coordinate-y').value=String(SpatialGeometry.round(py));}
}
function spatialDrawField(ctx,w,h,view,force=false){
  if(!spatialEnabled()||(!force&&spatialState.mode!=='field'))return;
  const f=spatialField(),s=view.scale,left=view.x-f.originX*s,top=view.y-f.originY*s,right=left+f.width*s,bottom=top+f.height*s;
  ctx.save();ctx.fillStyle='#16232c';ctx.fillRect(left,top,f.width*s,f.height*s);
  if(spatialState.guides){ctx.strokeStyle='#29404a';ctx.lineWidth=1;const step=f.width>2000?200:100;ctx.beginPath();for(let x=0;x<=f.width;x+=step){ctx.moveTo(left+x*s,top);ctx.lineTo(left+x*s,bottom);}for(let y=0;y<=f.height;y+=step){ctx.moveTo(left,top+y*s);ctx.lineTo(right,top+y*s);}ctx.stroke();}
  ctx.strokeStyle='#6b99a5';ctx.lineWidth=1.5;ctx.strokeRect(left,top,f.width*s,f.height*s);
  ctx.fillStyle='#a9c4d1';ctx.font='11px "Microsoft YaHei",sans-serif';ctx.textAlign='center';ctx.fillText(`X →  ${f.width} 场地单位`,(left+right)/2,top-12);ctx.textAlign='left';ctx.fillText('0,0',left,top+14);ctx.fillText('Y ↓',left+6,bottom-8);
  // Markers are editorial references only; there is intentionally no fictitious wall/flipper geometry.
  spatialCross(ctx,view.x,view.y,'#c5acff',S.page==='scene'?'角色参考点':'');
  spatialCross(ctx,left+f.targetX*s,top+f.targetY*s,'#f5bf77','目标参考点');
  const bar=100*s;ctx.strokeStyle='#bbd5df';ctx.beginPath();ctx.moveTo(left,bottom+16);ctx.lineTo(left+bar,bottom+16);ctx.stroke();ctx.fillStyle='#a9c4d1';ctx.fillText('100 单位',left,bottom+31);ctx.restore();
}
function spatialCross(ctx,x,y,color,label){ctx.save();ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x-7,y);ctx.lineTo(x+7,y);ctx.moveTo(x,y-7);ctx.lineTo(x,y+7);ctx.stroke();ctx.font='11px "Microsoft YaHei",sans-serif';ctx.textAlign='left';if(label)ctx.fillText(label,x+10,y+4);ctx.restore();}
function spatialOverlay(ctx,w,h,view){
  if(!spatialEnabled())return;spatialState.view=view;const sel=spatialSelection(),b=sel&&spatialBounds(sel);
  if(spatialState.guides){
    if(b){ctx.save();ctx.strokeStyle='#83d7c2';ctx.lineWidth=1;ctx.setLineDash([4,4]);ctx.strokeRect(view.x+b.minX*view.scale,view.y+b.minY*view.scale,(b.maxX-b.minX)*view.scale,(b.maxY-b.minY)*view.scale);ctx.restore();}
    const t=sel?.track?sel.item:null;spatialCross(ctx,view.x+(t?.x||0)*view.scale,view.y+(t?.y||0)*view.scale,'#c5acff','定位点');
  }
  spatialUpdateReading(view);
}
function spatialEditPanel(){
  const sel=spatialSelection();if(!sel?.item||(!sel.track&&sel.anim.native))return;
  const mount=sel.track?$('#track-inspector'):$('#inspector');if(!mount)return;
  mount.querySelector('.spatial-edit')?.remove();const f=spatialField(),x=sel.track?f.originX+(sel.item.x||0):sel.item.x||0,y=sel.track?f.originY+(sel.item.y||0):sel.item.y||0;
  const div=document.createElement('section');div.className='spatial-edit';
  div.innerHTML=`<h3>${sel.track?'在场地上摆放':'把画稿对准定位点'}</h3><p class="hint">${sel.track?'位置随技能编排保存，尚不绑定实战目标。':'紫色十字是游戏使用的定位点；可见底边不一定是脚底（例如武器或影子）。'}</p><div class="field-row">${field(sel.track?'场地 X（向右）':'画稿 X（向右）','spatial-coordinate-x',SpatialGeometry.round(x),'number','step="1"')}${field(sel.track?'场地 Y（向下）':'画稿 Y（向下）','spatial-coordinate-y',SpatialGeometry.round(y),'number','step="1"')}</div><div class="spatial-actions">${sel.track?'<button data-spatial-place="actor">放在角色点</button><button data-spatial-place="target">放在目标点</button><button data-spatial-place="center">放在场中央</button>':'<button id="spatial-pick">点选脚底 / 中心</button><button data-spatial-align="feet">可见底边对齐</button><button data-spatial-align="center">可见中心对齐</button>'}</div>${sel.track?'':'<p class="hint">只改当前画稿，原图不裁切。逐帧检查后，再用“编译后预览”核对输出。</p>'}`;
  mount.prepend(div);if(!sel.track&&S.page==='animations'){const button=document.createElement('button');button.id='spatial-unify-scale';button.textContent='统一整组角色的显示倍率';button.onclick=spatialUnifyScale;div.append(button);}
  for(const k of ['x','y'])$('#spatial-coordinate-'+k).onchange=e=>{const n=Number(e.target.value),value=n-(sel.track?f[k==='x'?'originX':'originY']:0);if(e.target.value.trim()===''||!Number.isFinite(value)||Math.abs(value)>4096){toast('位置需为 -4096 至 4096 范围内的有效偏移',true);draw();return;}mutate(()=>{if(!sel.track)S.tick=clipStart(sel.anim,S.clip);sel.item[k]=SpatialGeometry.round(value);S.p.previewStage??=spatialDefaults();});};
  div.querySelectorAll('[data-spatial-place]').forEach(button=>button.onclick=()=>{const p=button.dataset.spatialPlace;spatialMoveTo(sel,p==='actor'?0:p==='target'?f.targetX-f.originX:f.width/2-f.originX,p==='actor'?0:p==='target'?f.targetY-f.originY:f.height/2-f.originY);});
  div.querySelectorAll('[data-spatial-align]').forEach(button=>button.onclick=()=>{const c=sel.item,a=S.p.assets[c.asset],b=spatialImageBounds(c.asset);if(!b)return toast('当前画稿没有可见像素',true);const xy=SpatialGeometry.anchor(c,a.width,a.height,b.x+b.width/2,b.y+(button.dataset.spatialAlign==='feet'?b.height:b.height/2));spatialMoveTo(sel,xy.x,xy.y);});
  if($('#spatial-pick'))$('#spatial-pick').onclick=()=>{stop();S.tick=clipStart(sel.anim,S.clip);spatialState.pick=!spatialState.pick;draw();$('#stage').focus({preventScroll:true});};
}
function spatialMoveTo(sel,x,y){if(!sel?.item)return;if(!Number.isFinite(x)||!Number.isFinite(y)||Math.abs(x)>4096||Math.abs(y)>4096)return toast('该位置超出可保存的偏移范围，请降低缩放或调整场地参考点',true);mutate(()=>{if(!sel.track)S.tick=clipStart(sel.anim,S.clip);sel.item.x=SpatialGeometry.round(x);sel.item.y=SpatialGeometry.round(y);S.p.previewStage??=spatialDefaults();});}
function spatialSettings(){
  const f=spatialField();modal(`<h2>场地比例与参考点</h2><p>${esc(SPATIAL_REFERENCE_DESCRIPTION)}</p><p class="hint">场地左上角是 (0,0)，向右为 X 正向、向下为 Y 正向。紫色点是预览编排的原点；橙色点仅作目标参照。更换参考点不会重写画稿偏移或技能轨道。</p><div class="field-row">${field('场地宽（世界单位）','spatial-width',f.width,'number','min="1" max="8192"')}${field('场地高（世界单位）','spatial-height',f.height,'number','min="1" max="8192"')}</div><div class="field-row">${field('角色参考点 X','spatial-originX',f.originX,'number')}${field('角色参考点 Y','spatial-originY',f.originY,'number')}</div><div class="field-row">${field('目标参考点 X','spatial-targetX',f.targetX,'number')}${field('目标参考点 Y','spatial-targetY',f.targetY,'number')}</div><p id="spatial-settings-error" class="spatial-warning" role="alert"></p><div class="modal-actions"><button id="spatial-reference">恢复参考场地</button><button id="spatial-settings-save" class="primary">保存到工程</button></div><p class="hint">修改宽高后会标记为自定义，不会冒充游戏实测。设置随可编辑工程交接，不会生成碰撞、追踪或伤害范围。</p>`);
  $('#spatial-reference').onclick=()=>{for(const k of ['width','height','originX','originY','targetX','targetY'])$('#spatial-'+k).value=String(SPATIAL_REFERENCE[k]);};
  $('#spatial-settings-save').onclick=()=>{const next={version:1,profile:'custom'};for(const k of ['width','height','originX','originY','targetX','targetY']){if(!$('#spatial-'+k).value.trim()){$('#spatial-settings-error').textContent='请填写所有尺寸与参考点';return;}next[k]=Number($('#spatial-'+k).value);}if(!Object.values(next).filter(v=>typeof v==='number').every(Number.isFinite)||next.width<1||next.width>8192||next.height<1||next.height>8192||['originX','targetX'].some(k=>next[k]<0||next[k]>next.width)||['originY','targetY'].some(k=>next[k]<0||next[k]>next.height)){$('#spatial-settings-error').textContent='场地宽高需在 1–8192 之间，参考点需在场地内。';return;}if(next.width===SPATIAL_REFERENCE.width&&next.height===SPATIAL_REFERENCE.height&&next.originX===SPATIAL_REFERENCE.originX&&next.originY===SPATIAL_REFERENCE.originY&&next.targetX===SPATIAL_REFERENCE.targetX&&next.targetY===SPATIAL_REFERENCE.targetY)next.profile='reference';$('#modal').close();mutate(()=>S.p.previewStage=next);toast('场地设置已记录；素材与技能轨道未改动');};
}
function bindSpatialPreview(){
  if(!spatialEnabled()||!$('#spatial-size'))return;spatialResetProject();spatialState.pick=false;spatialEditPanel();
  $$('[data-spatial-mode]').forEach(b=>b.onclick=()=>{stop();spatialState.mode=b.dataset.spatialMode;S.zoom=1;render();});
  $('#spatial-settings').onclick=spatialSettings;$('#spatial-export').onclick=spatialExport;
  const canvas=$('#stage');canvas.tabIndex=0;canvas.setAttribute('aria-label','定位画布：拖动选中画稿或定位十字，方向键微调');
  canvas.onpointerdown=e=>{
    if(e.button!==0)return;const sel=spatialSelection();if(!sel?.item||(!sel.track&&sel.anim.native))return;
    if(S.savePromise)return toast('正在保存，请稍后再拖动');stop();const r=canvas.getBoundingClientRect(),v=editorView(r.width,r.height),p=SpatialGeometry.screenToLocal(v,e.clientX-r.left,e.clientY-r.top);
    if(spatialState.pick&&!sel.track){const a=S.p.assets[sel.item.asset],m=SpatialGeometry.clipMatrix(sel.item,a.width,a.height),inv=SpatialGeometry.inverse(m),point=inv&&SpatialGeometry.point(inv,p.x/sel.scale,p.y/sel.scale);if(!point||point.x<0||point.y<0||point.x>a.width||point.y>a.height)return toast('请点在当前画稿范围内');const xy=SpatialGeometry.anchor(sel.item,a.width,a.height,point.x,point.y);spatialState.pick=false;spatialMoveTo(sel,xy.x,xy.y);return;}
    if(!sel.track){S.clip=clipIndex(sel.anim,S.tick);sel.item=sel.anim.clips[S.clip];}
    const b=spatialBounds(sel),tx=sel.track?sel.item.x||0:0,ty=sel.track?sel.item.y||0:0,near=Math.hypot((p.x-tx)*v.scale,(p.y-ty)*v.scale)<16;
    if(!near&&(!b||p.x<b.minX||p.x>b.maxX||p.y<b.minY||p.y>b.maxY))return;
    canvas.focus({preventScroll:true});canvas.setPointerCapture(e.pointerId);e.preventDefault();
    clearTimeout(S.saveTimer);spatialState.drag={sel,view:v,start:p,x:sel.item.x||0,y:sel.item.y||0,moved:false,id:e.pointerId,ownX:Object.hasOwn(sel.item,'x'),ownY:Object.hasOwn(sel.item,'y'),before:clone(S.p),canvas};
  };
  canvas.onpointermove=e=>{const d=spatialState.drag;if(!d||d.id!==e.pointerId)return;const r=canvas.getBoundingClientRect(),p=SpatialGeometry.screenToLocal(d.view,e.clientX-r.left,e.clientY-r.top),dx=(p.x-d.start.x)/d.sel.scale,dy=(p.y-d.start.y)/d.sel.scale;if(!d.moved&&Math.hypot(dx,dy)*d.view.scale*d.sel.scale<2)return;d.moved=true;d.sel.item.x=SpatialGeometry.round(Math.max(-4096,Math.min(4096,d.x+dx)));d.sel.item.y=SpatialGeometry.round(Math.max(-4096,Math.min(4096,d.y+dy)));draw();};
  function finish(commit){const d=spatialState.drag;if(!d)return;spatialState.drag=null;if(canvas.hasPointerCapture(d.id))canvas.releasePointerCapture(d.id);if(d.moved){if(commit){S.undo.push(d.before);if(S.undo.length>30)S.undo.shift();S.redo=[];S.p.previewStage??=spatialDefaults();changed();}else{spatialRestoreDrag(d);}render();}if(S.dirty&&!S.savePromise){clearTimeout(S.saveTimer);S.saveTimer=setTimeout(()=>saveNow().catch(e=>toast(e.message,true)),1100);} }
  canvas.onpointerup=()=>finish(true);canvas.onpointercancel=()=>finish(false);canvas.onlostpointercapture=()=>finish(false);
  canvas.onkeydown=e=>{if(e.key==='Escape'){spatialState.pick=false;finish(false);draw();return;}const d={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(!d)return;e.preventDefault();const sel=spatialSelection();if(!sel?.item)return;stop();if(!sel.track)S.tick=clipStart(sel.anim,S.clip);const step=e.shiftKey?10:1;spatialMoveTo(sel,(sel.item.x||0)+d[0]*step,(sel.item.y||0)+d[1]*step);$('#stage')?.focus({preventScroll:true});};
}


const spatialOriginalInspector=renderInspector;
renderInspector=function(anim){spatialOriginalInspector(anim);if(spatialEnabled())spatialEditPanel();};

function spatialUnifyScale(){
  const a=current();if(!a)return;
  modal(`<h2>统一角色的游戏显示倍率</h2><p>整组像素动作共用一个游戏显示倍率。这个设置会改变导出后的角色大小，不是观看放大。</p>${field('整组角色显示倍率','spatial-global-scale',a.frameScale||6,'number','min="0.05" max="20" step="0.05"')}<p class="hint">将更新 ${S.p.animations.length} 个动作，包括空槽位；不改源 PNG、画稿缩放、偏移和技能特效。通常从模板的 6× 开始比较。</p><p id="spatial-scale-error" class="spatial-warning" role="alert"></p><div class="modal-actions"><button id="spatial-scale-cancel">取消</button><button id="spatial-scale-apply" class="primary">应用到整组动作</button></div>`);
  $('#spatial-scale-cancel').onclick=()=>$('#modal').close();
  $('#spatial-scale-apply').onclick=()=>{const value=Number($('#spatial-global-scale').value);if(!Number.isFinite(value)||value<.05||value>20){$('#spatial-scale-error').textContent='倍率需在 0.05–20 之间';return;}$('#modal').close();mutate(()=>S.p.animations.forEach(a=>a.frameScale=value));toast('整组角色倍率已统一，可以撤销');};
}
function spatialExport(){
  stop();draw();const stage=$('#stage');if(!stage)return;
  const f=spatialField(),canvas=document.createElement('canvas'),width=Math.max(900,stage.width),extra=160;
  canvas.width=width;canvas.height=Math.ceil(stage.height*width/stage.width)+extra;
  const ctx=canvas.getContext('2d');ctx.fillStyle='#151a22';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(stage,0,0,width,canvas.height-extra);
  ctx.fillStyle='#d8e4ed';ctx.font='20px "Microsoft YaHei",sans-serif';
  const lines=[`${S.p.name} · 定位参考（非实战截图）`,`${spatialState.mode==='field'?'场地比例':'素材放大，非游戏显示尺寸'} · 场地 ${f.width} × ${f.height} · 第 ${S.tick+1} 帧`,$('#spatial-profile-label').textContent,'工程保留可编辑坐标；参考点、目标跟随、镜头与伤害仍需接入验证。'];
  lines.forEach((line,i)=>ctx.fillText(line,20,canvas.height-extra+32+i*32,width-40));
  const a=document.createElement('a');a.download=(S.p.name||'角色').replace(/[\\/:*?"<>|]/g,'_')+'-定位参考.png';a.href=canvas.toDataURL('image/png');a.click();
}

function spatialRestoreDrag(d){
  if(d.ownX)d.sel.item.x=d.x;else delete d.sel.item.x;
  if(d.ownY)d.sel.item.y=d.y;else delete d.sel.item.y;
}
function spatialCancelDrag(){
  const d=spatialState.drag;if(!d)return;
  spatialState.drag=null;spatialRestoreDrag(d);
  if(d.canvas.hasPointerCapture(d.id))d.canvas.releasePointerCapture(d.id);
  // Save, navigation and undo must see the pre-drag project, never an in-flight position.
  draw();
}
