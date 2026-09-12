'use strict';
function showCompiledPreview(){
  busy('编译资源并回读播放数据',async()=>{
    await saveNow();
    const result=await api('/api/compiled-preview',{id:S.p.id,group:S.page==='scene'?'scene':group(),animation:S.page==='scene'?'':current().id});
    const images=new Map();
    await Promise.all(Object.entries(result.assets).map(([id,url])=>new Promise((resolve,reject)=>{
      const image=new Image();image.onload=()=>{images.set(id,image);resolve();};image.onerror=()=>reject(Error('回读图片加载失败'));image.src=url;
    })));
    modal(`<h2>编译后预览 · ${esc(result.name)}</h2><p>读取本次实际生成的图集与时间轴 · 工程版本 ${result.sourceRevision}</p>
      ${result.issues.length?`<details class="skill-coverage"><summary>当前预览范围与待校准项（${result.issues.length}）</summary>${result.issues.map(esc).join('<br>')}</details>`:''}
      <div class="stage-wrap"><canvas id="readback-stage" aria-label="编译后动画"></canvas><span class="stage-label">导出数据回读</span></div>
      <div class="preview-toolbar"><button id="readback-play">▶ 播放</button><button id="readback-prev">‹</button><button id="readback-next">›</button>
      <label>观看速度 <select id="readback-speed"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label>
      <button id="readback-fit">完整显示</button><label>相对完整画面 <select id="readback-zoom">${[.25,.5,1,2,3,4].map(v=>`<option value="${v}" ${v===S.zoom?'selected':''}>${v}×</option>`).join('')}</select></label></div>
      <input id="readback-scrub" type="range" min="0" max="${result.frames.length-1}" value="0" style="width:100%"><p id="readback-time"></p>
      <details><summary>本次编译文件校验</summary><div class="hint" style="overflow-wrap:anywhere">${result.files.map(f=>`<p>${esc(f.path)}<br>SHA-256 ${esc(f.sha256)}</p>`).join('')}</div></details>
      <p class="footer-note">用于检查导出后的图块、位置与时序。游戏镜头、场景和命中行为仍需接入验证。</p>`);
    const bounds=PreviewLayout.commands(PreviewLayout.empty(),result.frames,Object.fromEntries(images),result.scale);
    let tick=0,playing=false,handle=0,speed=1,zoom=S.zoom,last=0,fraction=0,audioPlayer=null,audioGeneration=0,audioLoading=false;
    function paint(){
      const canvas=$('#readback-stage');if(!canvas)return;
      const rect=canvas.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2),w=rect.width,h=rect.height;
      canvas.width=w*ratio;canvas.height=h*ratio;const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
      ctx.fillStyle='#151a22';ctx.fillRect(0,0,w,h);ctx.imageSmoothingEnabled=false;
      const view=PreviewLayout.fit(bounds,w,h,zoom),ox=view.x,oy=view.y;ctx.strokeStyle='#465063';ctx.beginPath();ctx.moveTo(20,oy);ctx.lineTo(w-20,oy);ctx.stroke();
      for(const cmd of result.frames[result.kind==='stop'?0:tick]||[]){const im=images.get(cmd.asset);if(!im)continue;ctx.save();ctx.globalAlpha=Math.max(0,Math.min(1,cmd.alpha));ctx.translate(ox,oy);ctx.scale(view.scale*result.scale,view.scale*result.scale);ctx.transform(...cmd.matrix);ctx.drawImage(previewImage(im,cmd),-(cmd.fx||0),-(cmd.fy||0));ctx.restore();}
      $('#readback-scrub').value=String(tick);$('#readback-time').textContent=`第 ${tick+1} / ${result.frames.length} 帧 · ${(tick/60/(result.runtimeSpeed||1)).toFixed(2)} 秒`;
    }
    function pause(){audioGeneration++;audioLoading=false;playing=false;audioPlayer?.stop();audioPlayer=null;cancelAnimationFrame(handle);if($('#readback-play'))$('#readback-play').textContent='▶ 播放';}
    function update(now){if(!playing||!$('#modal').open)return;fraction+=(now-last)*.06*speed*(result.runtimeSpeed||1);last=now;const count=Math.floor(fraction);fraction-=count;tick+=count;
      if(tick>=result.frames.length){if(result.kind==='loop'){tick%=result.frames.length;audioPlayer.start(tick/60/speed/(result.runtimeSpeed||1));}else{tick=result.frames.length-1;pause();paint();return;}}
      paint();handle=requestAnimationFrame(update);
    }
    $('#readback-play').onclick=async()=>{
      if(playing||audioLoading)return pause();
      const generation=++audioGeneration;audioLoading=true;$('#readback-play').textContent='加载声音…';
      const rate=speed*(result.runtimeSpeed||1);
      try{const player=await prepareSoundPlayback((result.audio||[]).filter(a=>result.kind!=='stop'||a.start===0).map(a=>({url:a.url,seconds:a.start/60/rate,endSeconds:a.end>=0?a.end/60/rate:undefined,loop:a.loop??1,rate:rate*(a.rate||1),volume:a.volume})));if(audioGeneration!==generation||!$('#modal').open)return;audioPlayer=player;}
      catch(e){if(audioGeneration===generation){pause();toast(e.message,true);}return;}
      audioLoading=false;if(tick>=result.frames.length-1)tick=0;playing=true;last=performance.now();fraction=0;
      audioPlayer.start(tick/60/rate);$('#readback-play').textContent='Ⅱ 暂停';handle=requestAnimationFrame(update);
    };
    $('#readback-prev').onclick=()=>{pause();tick=Math.max(0,tick-1);paint();};
    $('#readback-next').onclick=()=>{pause();tick=Math.min(result.frames.length-1,tick+1);paint();};
    $('#readback-scrub').oninput=e=>{pause();tick=Number(e.target.value);paint();};
    $('#readback-speed').onchange=e=>{pause();speed=Number(e.target.value);};
    $('#readback-fit').onclick=()=>{zoom=1;$('#readback-zoom').value='1';paint();};
    $('#readback-zoom').onchange=e=>{zoom=Number(e.target.value);paint();};
    $('#modal').addEventListener('close',()=>{pause();window.removeEventListener('resize',paint);},{once:true});
    window.addEventListener('resize',paint);paint();
  });
}
