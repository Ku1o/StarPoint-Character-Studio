'use strict';
async function openTemplateLibrary(){
  busy('读取本地角色模板库',async()=>{
    const library=await api('/api/templates');
    modal(`<h2>基于角色模板</h2><p>${library.installed?`${esc(library.name)} · 官方资源 ${esc(library.version)} · ${library.entries.length} 个条目`:'配套离线模板库尚未放入工具目录。'}</p>
      <div class="template-install"><span>将完整角色资源包中的 <b>templates</b> 和 <b>definitions</b> 两个文件夹解压到${S.host==='mod'?' tools/character-studio/ 目录':' EXE 旁边'}，即可选用素材与能力。${library.installed?'每个模板会复制为独立创作工程。':''}</span><button id="template-import-file">导入单角色参考包</button></div>
      ${library.installed?`<div class="template-search"><input id="template-search" placeholder="搜索角色名、称号、代号或编号" aria-label="搜索角色模板"><select id="template-element"><option value="">全部属性</option>${['火','水','雷','风','光','暗'].map(v=>`<option>${v}</option>`).join('')}</select><select id="template-rarity"><option value="">全部稀有度</option>${[5,4,3,2,1].map(v=>`<option value="${v}">${v} 星</option>`).join('')}</select></div><p id="template-count" class="hint"></p><div id="template-cards" class="template-cards"></div><div id="template-detail"></div>`:''}`);
    $('#template-import-file').onclick=()=>{$('#modal').close();openImport();};
    if(!library.installed)return;
    let templateLimit=80;
    function show(){const query=$('#template-search').value.trim().toLowerCase(),element=$('#template-element').value,rarity=$('#template-rarity').value;const entries=library.entries.filter(e=>(!query||[e.name,e.title,e.code,e.id].join(' ').toLowerCase().includes(query))&&(!element||e.element===element)&&(!rarity||String(e.rarity)===rarity));
      $('#template-count').textContent=`匹配 ${entries.length} 个 · 逐项区分素材缺失、预览限制和原始条目说明`;
      $('#template-cards').innerHTML=entries.slice(0,templateLimit).map(e=>`<button class="template-card" data-template="${e.id}">${e.thumbnail?`<img loading="lazy" src="/api/template-thumbnail?id=${e.id}" alt="">`:'<span class="template-placeholder">✦</span>'}<strong>${esc(e.name)}</strong><small>${esc(e.element)} · ${e.rarity} 星 · ${e.id}</small><span>${!e.available?'模板文件未安装':({ready:'素材已收录',source_notes:'特殊条目说明',preview_limited:'预览受限',missing_assets:'资源缺失',partial:'查看素材说明'}[e.status]||'查看说明')}</span></button>`).join('')+(entries.length>templateLimit?`<button id="template-more">继续显示（已显示 ${templateLimit} / ${entries.length}）</button>`:'');
      if($('#template-more'))$('#template-more').onclick=()=>{templateLimit+=80;show();};
      $$('[data-template]').forEach(button=>button.onclick=()=>detail(library.entries.find(e=>e.id===button.dataset.template)));
    }
    function detail(e){const count=e.counts||{};$('#template-detail').innerHTML=`<section class="template-detail"><h3>${esc(e.name)} · ${esc(e.title)}</h3><p>${esc(e.code)} · ${esc(e.category)} · 官方 ${esc(e.version)}</p><div class="summary-row"><span>${count.portraits||0} 份立绘</span><span>${count.actions||0} 个动作</span><span>${count.effects||0} 段特效</span><span>${count.voices||0} 条语音</span><span>${count.sounds||0} 个音效</span></div>${e.warnings.length?`<details open><summary>素材与预览说明（${e.warnings.length}）</summary><div class="hint">${e.diagnostics?.length?e.diagnostics.map(d=>`<p><b>${{source:'原始资源说明',preview:'工具预览限制',missing:'资源未收录'}[d.category]||'说明'}</b> · ${esc(d.text)}</p>`).join(''):e.warnings.map(esc).join('<br>')}</div></details>`:''}<p class="hint">素材已收录表示已通过模板导入和依赖检查。特殊条目可能没有普通角色的完整立绘或动作；不会把这类原始差异记成创作者漏交。</p><button id="template-create" class="primary" ${e.available?'':'disabled'}>以此模板新建角色</button></section>`;$('#template-create').onclick=()=>{$('#modal').close();busy('复制模板并建立独立角色工程',async()=>{await saveNow();setProject(await api('/api/template-create',{id:e.id}));toast('模板已复制，可以替换素材开始创作');});};$('#template-detail').scrollIntoView({block:'nearest',behavior:'smooth'});}
    const filter=()=>{templateLimit=80;show();};$('#template-search').oninput=filter;$('#template-element').onchange=filter;$('#template-rarity').onchange=filter;show();
  });
}
$('#import-template').onclick=openTemplateLibrary;
