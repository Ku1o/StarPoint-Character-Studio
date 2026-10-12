'use strict';
// Separate read-only dialog keeps the reference selector and original scene intact.
let referencePreviewGeneration=0,referencePreviewDispose=null;
function closeReferencePreview(){referencePreviewGeneration++;referencePreviewDispose?.();referencePreviewDispose=null;}
async function openReferencePreview(option,pid,revision,callbacks={}){
  closeReferencePreview();
  const generation=referencePreviewGeneration;
  const currentProject=()=>S.p?.id===pid&&S.p?.revision===revision;
  if(!currentProject())return toast('工程已变化，请重新打开参考选择器',true);
  const digest=option?.identity?.sha256;
  if(!digest)return toast('请先检查参考身份',true);
  if(typeof stop==='function')stop();
  let result;
  try{result=await api('/api/author-reference-preview',{id:pid,revision,choice:option.id,digest});}
  catch(error){if(generation===referencePreviewGeneration)toast(error.message,true);return;}
  if(generation!==referencePreviewGeneration||!currentProject())return;
  const dialog=document.createElement('dialog');dialog.id='reference-preview-dialog';
  dialog.style.width='min(920px,94vw)';
  const visual=result.mode==='animation'&&result.frames?.length;
  dialog.innerHTML=`<div style="padding:24px"><h2>参考试看 · ${esc(result.name)}</h2><p class="hint">已保存的原声画 · 查看后关闭，继续选择参考</p>
    ${result.issues?.length?`<details class="skill-coverage" ${result.mode==='pending'?'open':''}><summary>参考范围与待核项</summary>${result.issues.map(esc).join('<br>')}</details>`:''}
    ${result.mode==='sound'?'<audio id="reference-preview-audio" controls preload="metadata" style="width:100%" aria-label="原声音参考"></audio><button id="reference-preview-stop">停止试听</button>':''}
    ${visual?`<div class="stage-wrap"><canvas id="reference-preview-stage" aria-label="原声画参考"></canvas><span class="stage-label">只读参考</span></div>
      <div class="preview-toolbar"><button id="reference-preview-play">▶ 播放</button><button id="reference-preview-prev">‹</button><button id="reference-preview-next">›</button>
      <label>观看速度 <select id="reference-preview-speed">${[.25,.5,1,2].map(v=>`<option value="${v}" ${v===1?'selected':''}>${v}×</option>`).join('')}</select></label>
      <button id="reference-preview-fit">完整显示</button><label>放大 <select id="reference-preview-zoom">${[.5,1,2,4].map(v=>`<option value="${v}" ${v===1?'selected':''}>${v}×</option>`).join('')}</select></label></div>
      <input id="reference-preview-scrub" type="range" min="0" max="${result.frames.length-1}" value="0" style="width:100%"><p id="reference-preview-time"></p>`:''}
    <p class="footer-note">素材和有限演出仅供制作参考。完整技能、目标、跟随、召唤与实际游戏行为由制作方核对。</p>
    <div class="modal-actions">${callbacks.choose?'<button id="reference-use" class="primary">选用这个参考</button>':''}<button id="reference-back">返回参考列表</button><button id="reference-preview-close">关闭试看</button></div></div>`;
  document.body.append(dialog);dialog.showModal();
  const find=s=>dialog.querySelector(s),images=new Map();
  const parentDialog=document.querySelector('#modal');
  const parentWasOpen=Boolean(parentDialog?.open);
  let disposed=false,tick=0,playing=false,handle=0,speed=1,zoom=1,last=0,fraction=0,audioPlayer=null,audioGeneration=0,audioLoading=false;
  const sound=find('#reference-preview-audio');
  function valid(){return !disposed&&generation===referencePreviewGeneration&&currentProject()&&dialog.open&&(!parentWasOpen||parentDialog.open);}
  function pause(){audioGeneration++;audioLoading=false;playing=false;audioPlayer?.stop();audioPlayer=null;cancelAnimationFrame(handle);sound?.pause();const button=find('#reference-preview-play');if(button)button.textContent='▶ 播放';}
  function dispose(){if(disposed)return;disposed=true;pause();clearInterval(invalidation);window.removeEventListener('resize',paint);window.removeEventListener('pagehide',dispose);document.removeEventListener('visibilitychange',visibility);parentDialog?.removeEventListener('close',dispose);parentObserver?.disconnect();if(sound){sound.removeAttribute('src');sound.load();}if(dialog.open)dialog.close();dialog.remove();images.clear();if(referencePreviewDispose===dispose)referencePreviewDispose=null;}
  function visibility(){if(document.hidden)pause();}
  const invalidation=setInterval(()=>{if(!valid())dispose();},250);
  const parentContent=document.querySelector('#modal-content');
  const parentObserver=parentWasOpen&&parentContent?new MutationObserver(()=>dispose()):null;
  parentObserver?.observe(parentContent,{childList:true});
  referencePreviewDispose=dispose;
  dialog.addEventListener('close',dispose,{once:true});
  find('#reference-preview-close').onclick=dispose;
  async function returnTo(action){if(!valid()){dispose();return;}dispose();try{await action?.();}catch(error){toast(error.message,true);}}
  find('#reference-back').onclick=()=>returnTo(callbacks.back);
  if(callbacks.choose)find('#reference-use').onclick=()=>returnTo(callbacks.choose);
  if(find('#reference-preview-stop'))find('#reference-preview-stop').onclick=()=>{pause();sound.currentTime=0;};
  parentDialog?.addEventListener('close',dispose);
  document.addEventListener('visibilitychange',visibility);window.addEventListener('pagehide',dispose);
  if(sound){sound.src=result.audio[0].url;sound.addEventListener('play',()=>{if(!valid())dispose();});sound.addEventListener('error',()=>{if(valid())toast('原声音无法解码，请由制作方核对素材格式',true);});}
  let bounds=PreviewLayout.empty();
  function paint(){
    const canvas=find('#reference-preview-stage');if(!canvas||disposed)return;
    const rect=canvas.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2),w=rect.width,h=rect.height;
    canvas.width=w*ratio;canvas.height=h*ratio;const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.fillStyle='#151a22';ctx.fillRect(0,0,w,h);ctx.imageSmoothingEnabled=false;
    const view=PreviewLayout.fit(bounds,w,h,zoom);
    for(const command of result.frames[result.kind==='stop'?0:tick]||[]){const image=images.get(command.asset);if(!image)continue;ctx.save();ctx.globalAlpha=Math.max(0,Math.min(1,command.alpha??1));ctx.translate(view.x,view.y);ctx.scale(view.scale*result.scale,view.scale*result.scale);ctx.transform(...command.matrix);ctx.drawImage(previewImage(image,command),-(command.fx||0),-(command.fy||0));ctx.restore();}
    find('#reference-preview-scrub').value=String(tick);find('#reference-preview-time').textContent=`第 ${tick+1} / ${result.frames.length} 帧 · ${(tick/60/(result.runtimeSpeed||1)).toFixed(2)} 秒`;
  }
  function update(now){
    if(!valid()){dispose();return;}if(!playing)return;
    fraction+=(now-last)*.06*speed*(result.runtimeSpeed||1);last=now;const count=Math.floor(fraction);fraction-=count;tick+=count;
    if(tick>=result.frames.length){if(result.kind==='loop'){tick%=result.frames.length;audioPlayer?.start(tick/60/speed/(result.runtimeSpeed||1));}else{tick=result.frames.length-1;pause();paint();return;}}
    paint();handle=requestAnimationFrame(update);
  }
  if(!visual)return;
  const play=find('#reference-preview-play');play.disabled=true;
  try{await Promise.all(Object.entries(result.assets).map(([id,url])=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>{if(!disposed)images.set(id,image);resolve();};image.onerror=()=>reject(Error('参考图片无法读取'));image.src=url;})));}
  catch(error){if(valid())toast(error.message,true);dispose();return;}
  if(!valid()){dispose();return;}
  bounds=PreviewLayout.commands(PreviewLayout.empty(),result.frames,Object.fromEntries(images),result.scale);
  play.disabled=false;
  play.onclick=async()=>{
    if(playing||audioLoading){pause();return;}
    if(!valid()){dispose();return;}
    const audioToken=++audioGeneration;audioLoading=true;play.textContent='加载声音…';const rate=speed*(result.runtimeSpeed||1);
    try{const player=await prepareSoundPlayback((result.audio||[]).filter(a=>result.kind!=='stop'||a.start===0).map(a=>({url:a.url,seconds:a.start/60/rate,endSeconds:a.end>=0?a.end/60/rate:undefined,loop:a.loop??1,rate:rate*(a.rate||1),volume:a.volume})));if(audioToken!==audioGeneration||!valid()){player.stop();return;}audioPlayer=player;}
    catch(error){if(audioToken===audioGeneration&&valid()){pause();toast(error.message,true);}return;}
    audioLoading=false;if(tick>=result.frames.length-1)tick=0;playing=true;last=performance.now();fraction=0;audioPlayer.start(tick/60/rate);play.textContent='Ⅱ 暂停';handle=requestAnimationFrame(update);
  };
  find('#reference-preview-prev').onclick=()=>{pause();tick=Math.max(0,tick-1);paint();};
  find('#reference-preview-next').onclick=()=>{pause();tick=Math.min(result.frames.length-1,tick+1);paint();};
  find('#reference-preview-scrub').oninput=e=>{pause();tick=Number(e.target.value);paint();};
  find('#reference-preview-speed').onchange=e=>{pause();speed=Number(e.target.value);};
  find('#reference-preview-fit').onclick=()=>{zoom=1;find('#reference-preview-zoom').value='1';paint();};
  find('#reference-preview-zoom').onchange=e=>{zoom=Number(e.target.value);paint();};
  window.addEventListener('resize',paint);paint();
}
