'use strict';
function requirementsPanel(anim,effect){
  const rules=S.rules||{pixelEdge:1022,effectEdge:2046};
  const clips=anim?.clips||[];const sizes=[...new Set(clips.map(c=>{const a=S.p.assets[c.asset];return a?`${a.width}×${a.height}`:'';}))].filter(Boolean);
  const selected=clips[S.clip],asset=selected?S.p.assets[selected.asset]:null;
  const limits=effect?rules.effectEdge:rules.pixelEdge;
  return `<section class="requirements" aria-label="素材制作要求"><div class="requirements-top"><strong>${effect?'特效素材怎么准备':'像素动作素材怎么准备'}</strong><span>透明 PNG · 每张图一个姿势${effect?' / 特效阶段':''}</span></div>
    <details class="requirements-explainer"><summary>查看素材规格、尺寸与逐帧制作方法（单图 ≤ ${limits} px）</summary><div class="requirements-grid"><div><b>格式与背景</b><p>导入普通静态 PNG，建议 RGBA 透明背景。JPG、PSD、GIF、APNG 和视频需要先导出为逐帧 PNG；棋盘格应来自编辑器背景，不能画进图片。</p></div>
    <div><b>尺寸怎么定</b><p>${effect?'特效没有统一的官方宽高。替换模板图层时优先沿用原贴图尺寸；原创序列可用 128×128 或 256×256 起步，再按效果范围调整。':'优先参照所选模板的实际画稿尺寸。原创可用 32×32 或 64×64 起步；这是建议，不是强制规格。不要把打包图集当作一张动作画稿导入。'}</p></div>
    <div><b>一组动作怎么交</b><p>每个姿势一张图，如 attack_001.png、attack_002.png。建议同一动作保持画布尺寸与定位点一致；数量由动作决定。批量导入按文件名中的数字排序，之后仍可手动调整，每段停留帧数可单独修改；60 播放帧 = 1 秒。</p></div></div>
    <details><summary>查看尺寸限制与制作提示</summary><p>单张文件 ≤ 64 MiB；当前${effect?'序列特效':'像素动作'}编译要求变换后的单图宽高各 ≤ ${limits} 像素。${effect?'序列特效图集上限为 2048×4096。':'像素图集上限为 1024×4096；一张图集容纳整组动作。'}单个动作最多 4096 播放帧，多张大图仍可能超出图集容量。</p><p>${effect?'柔光和渐隐可保留半透明像素。画稿的颜色混合方式与游戏最终效果有关，特殊混合需要额外校准。':'按原始像素绘制，建议关闭平滑缩放，不要先把小人放大六倍再导入。画稿尺寸、游戏显示倍率与观看放大是三个不同设置。'}自动裁掉各帧不同的透明边缘可能导致定位变化，导入后需检查偏移。${effect?'序列特效请提供逐帧 PNG。':'像素精灵图可在“导入动作图片”中启用网格切分，先预览再写入动作。'}</p></details>
    </details><div class="requirement-current"><span id="asset-current-info">${anim?.native?'模板骨架：右侧每一层分别显示原贴图宽高，换图时参照该层。':asset?`当前画稿 <b>${asset.width}×${asset.height}</b> · ${asset.alpha?'有透明像素':'未检测到透明像素'} · 本动作 ${sizes.length} 种尺寸${sizes.length>1?'（请检查定位是否一致）':''}`:'添加画稿后，这里会显示实际宽高、透明情况和尺寸差异。'}</span><button id="asset-guide-open" class="quiet">制作示例与检查 →</button></div></section>`;
}
function bindRequirements(anim,effect){
  $('#asset-guide-open').onclick=()=>modal(`<h2>${effect?'技能特效':'像素动作'}交付示例</h2><div class="guide-example"><code>${effect?'skill_flash':'attack'}_001.png<br>${effect?'skill_flash':'attack'}_002.png<br>${effect?'skill_flash':'attack'}_003.png</code><p>三张不同的画稿，可以分别停留 6、12、6 帧，组成 24 帧（0.4 秒）的成品动画；不需要为了延长停留时间复制很多相同 PNG。</p></div><p>导入前：导出逐帧 PNG，保持透明背景和定位点。<br>导入后：检查宽高、实际位置、帧序、停留时间，再用“编译后预览”检查输出。</p><div class="notice">${effect?'技能画面、角色喊声和技能音效分别制作。在“技能制作 → 技能预览”中检查它们的配合；编排当前作为预览与交接数据保存。':'模板中的 256×256 等完整定位画布与裁出的实际小人图块不同。小人图块可能只有十几到几十像素，宽高以当前素材显示值为准。'}</div>`);
}

function refreshRequirements(anim){const node=$('#asset-current-info');if(!node||anim.native)return;const c=anim.clips?.[S.clip],a=c?S.p.assets[c.asset]:null;const sizes=new Set((anim.clips||[]).map(c=>{const a=S.p.assets[c.asset];return a?`${a.width}x${a.height}`:'';}));if(a)node.textContent=`当前画稿 ${a.width}×${a.height} · ${a.alpha?'有透明像素':'未检测到透明像素'} · 本动作 ${sizes.size} 种尺寸${sizes.size>1?'（请检查定位是否一致）':''}`;}
