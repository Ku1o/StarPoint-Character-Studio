'use strict';

async function showProjectStorage(focusId) {
  await saveNow();
  const session = await api('/api/session');
  const projects = session.projects;
  modal(`<div class="storage-heading"><span class="eyebrow">你的创作，保留在本机</span><h2>工程与升级</h2></div>
    <p>工程位置</p><code class="storage-path">${esc(session.projectDirectory)}</code>
    <div class="storage-grid"><section><h3>从旧版继续制作</h3><p>先在旧版保存并退出，再选择旧工具文件夹。画稿、动作、特效、声音、能力和历史记录会一起复制；旧目录保留。</p>
    <button id="storage-upgrade" class="primary" ${session.desktop?'':'disabled'}>选择旧版文件夹并迁入</button>
    ${session.desktop?'':'<p class="hint">文件夹迁入请使用独立桌面窗口；这里可以导入旧版导出的工程包。</p>'}
    <p class="hint">官方模板库继续独立安装，更新素材库不会替换工程里的创作。</p></section>
    <section><h3>备份与恢复</h3><p>保存前自动保留上一份工程记录；恢复会建立副本，当前工程也会保留。</p>
    <label for="storage-project">选择工程</label><select id="storage-project">${projects.map(p=>`<option value="${esc(p.id)}" ${p.id===(focusId||S.p?.id)?'selected':''}>${esc(p.name)}${p.error?'（需要恢复）':''}</option>`).join('')}</select>
    <div class="storage-actions"><button id="storage-export" ${projects.length?'':'disabled'}>导出所选工程备份</button><button id="storage-import">导入工程备份</button></div>
    <p class="hint">导出包含当前工程及素材。要保留所有历史记录，请另外备份上方完整文件夹。</p></section></div>
    <div id="storage-result" role="status"></div><div id="storage-history"></div>`);
  const select = $('#storage-project');
  const loadHistory = async () => {
    const id = select.value;
    const target = $('#storage-history');
    if (!id) { target.textContent = '还没有工程，可以从旧版迁入或导入备份。'; return; }
    target.innerHTML = '<p>读取历史记录…</p>';
    $('#storage-export').disabled = !!projects.find(p=>p.id===id)?.error;
    const result = await api('/api/project-history?id='+encodeURIComponent(id));
    if (!target.isConnected || select.value !== id) return;
    const error = projects.find(p=>p.id===id)?.error;
    target.innerHTML = `${error?`<p class="notice">${esc(error)}。原目录仍保留。可选择下方记录恢复；没有记录时，请导入以前导出的工程备份。</p>`:''}<h3>保存历史</h3><div class="storage-history-list">${result.records.map(r=>`<div class="storage-history-row"><div><strong>${esc(r.name)}</strong><small>修订 ${r.revision} · ${new Date(r.updated*1000).toLocaleString('zh-CN')}</small></div><button data-recover="${esc(r.file)}">恢复为副本</button></div>`).join('')||'<p class="hint">暂无历史备份。之后修改并保存时会自动保留上一份记录。</p>'}</div>`;
    target.querySelectorAll('[data-recover]').forEach(button=>button.onclick=()=>{button.disabled=true;return busy('校验素材并恢复副本',async()=>{
      const p = await api('/api/project-recover',{id,file:button.dataset.recover});
      $('#modal').close();setProject(p);toast('已打开恢复副本，原工程仍保留');
    }).finally(()=>{button.disabled=false;});});
  };
  select.onchange = () => loadHistory().catch(e=>toast(e.message,true));
  $('#storage-export').onclick=()=>{location.href='/api/export?id='+encodeURIComponent(select.value);};
  $('#storage-import').onclick=()=>{$('#modal').close();$('#import-project').click();};
  $('#storage-upgrade').onclick=()=>{const button=$('#storage-upgrade');button.disabled=true;return busy('选择旧工程并校验迁入',async()=>{
    const result=await api('/api/upgrade-projects',{});
    if(result.cancelled)return;
    const fresh=await api('/api/session');recent(fresh.projects);
    const box=$('#storage-result');
    box.innerHTML=`<p class="notice">已迁入 ${result.copied.length} 个工程，${result.skipped.length} 个已迁入过，${result.failed.length} 个未能迁入。旧版原文件保留。${result.failed.map(p=>`<br>${esc(p.id)}：${esc(p.error)}`).join('')}</p><button id="storage-refresh">查看工程</button>`;
    $('#storage-refresh').onclick=()=>{$('#modal').close();busy('打开工程列表',goHome);};
  }).finally(()=>{button.disabled=false;});};
  await loadHistory();
}

$('#project-storage').onclick=()=>busy('读取工程与备份',()=>showProjectStorage());
