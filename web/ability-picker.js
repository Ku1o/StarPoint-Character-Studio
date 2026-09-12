'use strict';
async function openAbilityLibrary(slot,options={}){
  const pid=S.p.id,kind=slot==='leader'?'leader_ability':'ability',label=slot==='leader'?'队长技':'能力 '+slot;
  let offset=0,serial=0,selected=null,timer;
  modal(`${options.onBack?'<button class="ability-library-back" id="ability-library-back">← 返回组件组合</button>':''}<h2>${options.component?'取用组件 · '+esc(options.component):'从词条库取材 · '+label}</h2><p>${options.component?'选择来源条目，只取用这一块，组合中的其他内容保留。':'按角色名、描述或编号搜索，可单独选取一条或多条效果。'}</p>${field('搜索现成词条','ability-library-search','')}<p id="ability-library-source" class="hint"></p><div class="ability-picker"><div><div id="ability-library-results" class="ability-results"></div><div class="ability-pagination"><button id="ability-library-prev" disabled>上一页</button><span id="ability-library-page"></span><button id="ability-library-next" disabled>下一页</button></div></div><section id="ability-library-detail" class="ability-detail"><p class="hint">选择左侧词条，选择其中的效果条目。</p></section></div>`);
  const dialog=$('#modal'),input=$('#ability-library-search');
  if($('#ability-library-back'))$('#ability-library-back').onclick=options.onBack;
  const active=()=>dialog.open&&S.p?.id===pid&&$('#ability-library-search')===input;
  dialog.addEventListener('close',()=>clearTimeout(timer),{once:true});
  function error(e){if(active()){$('#ability-library-detail').innerHTML=`<p class="notice">${esc(e.message)}</p>`;}}
  async function load(){
    const request=++serial;selected=null;
    $('#ability-library-results').innerHTML='<p class="hint">读取词条库…</p>';
    $('#ability-library-detail').innerHTML='<p class="hint">选择左侧词条，选择其中的效果条目。</p>';
    $('#ability-library-prev').disabled=$('#ability-library-next').disabled=true;
    try{
      const data=await api(`/api/ability-library?kind=${kind}&q=${encodeURIComponent(input.value)}&offset=${offset}`);
      if(!active()||request!==serial)return;
      $('#ability-library-source').textContent=data.source+' · 匹配 '+data.total+' 组';
      $('#ability-library-page').textContent=data.total?`${offset+1}–${offset+data.entries.length} / ${data.total}`:'0';
      $('#ability-library-prev').disabled=offset===0;$('#ability-library-next').disabled=offset+40>=data.total;
      $('#ability-library-results').innerHTML=data.entries.map(e=>`<button data-library-key="${esc(e.key)}"><strong>${esc(e.owner||e.sourceKey)} · ${e.kind==='leader_ability'?'队长技':'能力 '+esc(e.slot)}</strong><small>${esc(e.description||'原始词条')}<br>${e.lines} 条效果 · 来源 ${esc(e.sourceKey)}${e.character?' · 角色 '+esc(e.character):''}</small></button>`).join('')||'<p class="empty">没有匹配词条，试试角色名或“攻击力”。</p>';
      $$('[data-library-key]').forEach(b=>b.onclick=()=>detail(b.dataset.libraryKey));
    }catch(e){if(request===serial)error(e);}
  }
  async function detail(key){
    const request=++serial;selected=null;
    $$('[data-library-key]').forEach(b=>b.classList.toggle('selected',b.dataset.libraryKey===key));
    $('#ability-library-detail').innerHTML='<p class="hint">读取整组效果…</p>';
    try{
      const data=await api(`/api/ability-library?kind=${kind}&key=${encodeURIComponent(key)}`);
      if(!active()||request!==serial)return;
      selected=data.entry;const entry=selected;
      const block=options.componentBlock,mode=block?.startsWith('instant_')?'0':block?.startsWith('during_')?'1':block==='opening'?'2':null;
      const compatible=row=>mode===null||row[abilityEditorMeta.kinds[entry.kind].trigger_col]===mode;
      $('#ability-library-detail').innerHTML=`<h3>${esc(entry.owner)} · ${entry.kind==='leader_ability'?'队长技':'能力 '+esc(entry.slot)}</h3><p class="hint">${options.component?'只会取用所选条目的“'+esc(options.component)+'”。':'勾选需要的条目，追加后可逐块调整。'}</p>${entry.rows.map((row,i)=>`<label class="ability-row-choice"><input type="${options.onChoose?'radio':'checkbox'}" name="ability-library-row" value="${i}" ${!compatible(row)||(!options.onChoose&&entry.rowIssues[i].length)?'disabled':options.onChoose?'':'checked'}><span>${i+1}. ${esc(entry.rowDescriptions[i]||'原始条目')}${!compatible(row)?'<br>此条目的生效方式与所取组件不符':''}${entry.rowIssues[i].length?'<br>校验提示：'+entry.rowIssues[i].map(esc).join('；'):''}</span></label>`).join('')}<details><summary>查看原始数据</summary><pre>${esc(JSON.stringify(entry.rows,null,2))}</pre></details><div class="modal-actions"><button id="ability-library-use" class="primary">${options.onChoose?'取用这一块':'追加所选效果'}</button></div>`;
      const inputs=()=>$$('[name="ability-library-row"]');
      if(options.onChoose){const first=inputs().find(e=>!e.disabled);if(first)first.checked=true;}
      const indices=()=>inputs().filter(e=>e.checked&&!e.disabled).map(e=>Number(e.value));
      const update=()=>$('#ability-library-use').disabled=!indices().length;inputs().forEach(e=>e.onchange=update);update();
      $('#ability-library-use').onclick=()=>{
        const chosen=indices();if(!chosen.length||!active()||selected!==entry)return;
        if(options.onChoose){options.onChoose(entry,clone(entry.rows[chosen[0]]));return;}
        busy('选用并保存能力效果',async()=>{
          await saveNow();if(!active())return;
          const previous=clone(S.p),p=await api('/api/ability-library-append',{id:pid,revision:S.p.revision,slot,key:entry.key,fingerprint:entry.fingerprint,indices:chosen});
          S.undo.push(previous);S.redo=[];S.p=p;S.generation++;S.dirty=false;dialog.close();render();toast(`已追加 ${chosen.length} 条效果，可继续拆解组合`);
        });
      };
    }catch(e){if(request===serial)error(e);}
  }
  input.oninput=()=>{clearTimeout(timer);++serial;selected=null;$('#ability-library-use')?.setAttribute('disabled','');offset=0;timer=setTimeout(load,200);};
  $('#ability-library-prev').onclick=()=>{offset=Math.max(0,offset-40);load();};
  $('#ability-library-next').onclick=()=>{offset+=40;load();};
  await load();
}
