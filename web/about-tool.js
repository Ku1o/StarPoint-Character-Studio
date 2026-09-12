'use strict';

function initStudioAbout(session) {
  const info = session.app;
  if (!info) return;
  const button = document.querySelector('#app-version');
  button.textContent = `v${info.version}`;
  button.title = `${info.name} ${info.channel} · 使用说明与来源`;
  button.setAttribute('aria-label', `${info.name} v${info.version}，使用说明与来源`);
  button.hidden = false;
  document.title = `${info.name} v${info.version} · ${info.channel}`;
  button.onclick = () => {
    modal(`<div class="about-heading"><span class="about-mark">✦</span><div><h2>${esc(info.name)}</h2><p>v${esc(info.version)} · ${esc(info.channel)}</p></div></div>
      <p>面向角色创作者的本地工作台。制作立绘、像素动作、技能特效、声音与能力草稿。</p>
      <h3>从这里开始</h3>
      <ol class="about-steps"><li><b>建立工程。</b>选择原创角色，或安装独立资源包后选择官方模板。</li>
      <li><b>准备形象。</b>在「立绘与界面」替换用途图片、从大立绘裁剪，或导出单张 PNG 修改。</li>
      <li><b>制作动作与特效。</b>批量导入 PNG、切分精灵图、调整时长与图层，再播放整段动画。</li>
      <li><b>补齐声音与能力。</b>绑定技能音效、角色语音；从词条库取材或拆解组合条件与效果。</li>
      <li><b>检查并交付。</b>保存可编辑工程，查看编译后预览，再导出供接入方继续处理。</li></ol>
      <p class="hint">当前为制作预览版。完整战斗技能还原、正式游戏 ID 与平台资源接入仍需后续完成；详细支持范围见使用说明。</p>
      <div class="about-origin"><h3>来源与许可</h3><p>基于 <a href="${esc(info.upstream)}" target="_blank" rel="noopener noreferrer">startpoint-cn-mod-tools（原 MOD 修改器）</a> 开发，复用并扩展资源编码、动画预览与能力编辑模块。</p>
      <p>工具源码：<a href="${esc(info.repository)}" target="_blank" rel="noopener noreferrer">StarPoint-Character-Studio</a> · ${esc(info.license)}。官方素材包单独提供，素材不适用本工具的软件许可。</p></div>
      <div class="modal-actions"><a class="about-guide" href="/api/user-guide" download="星点角色工坊-使用说明.md">保存完整使用说明 ↓</a><button id="about-close" class="primary">返回创作</button></div>`);
    document.querySelector('#about-close').onclick = () => document.querySelector('#modal').close();
  };
}
