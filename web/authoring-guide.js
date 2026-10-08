'use strict';
function requirementsPanel(anim,effect){
  const rules=S.rules||{pixelEdge:1022,effectEdge:2046};
  const clips=anim?.clips||[];const sizes=[...new Set(clips.map(c=>{const a=S.p.assets[c.asset];return a?`${a.width}×${a.height}`:'';}))].filter(Boolean);
  const selected=clips[S.clip],asset=selected?S.p.assets[selected.asset]:null;
  const limits=effect?rules.effectEdge:rules.pixelEdge;
  const native=!!anim?.native;
  const next=native?(effect?'先选时间轴中的通道，参照右侧图片尺寸换图；旧工程若显示“载入可编辑通道”，先点击它。':'先选右侧图层，参照该层的原图尺寸替换贴图。'):(effect?'先选择或新建一个序列特效，再在时间轴下添加透明 PNG，排列顺序并调整停留时间。':'选左侧动作 → “导入动作图片” → 确认目标动作 → 预览后导入。');
  return `<section class="requirements" aria-label="素材制作要求"><div class="requirements-top"><strong>${effect?'特效素材怎么准备':'像素动作素材怎么准备'}</strong><span>${native?'模板原生素材 · 按图层或通道换图':'透明 PNG · 每张图一个姿势'+(effect?' / 特效阶段':'')}</span></div>
    <p><b>现在做什么：</b>${next}${native?'这是按图层组合播放的模板，不是每帧一张整图；不要把逐帧图片直接当作某一层替换。':''}</p>
    ${effect?'<p class="hint">这里只检查特效素材的画面与节奏。“技能制作 → 技能预览”可检查动作、特效与声音配合；两者都不是实际战斗，不能验证命中、伤害、目标或技能范围。</p>':'<p class="hint"><b>三种大小别混用：</b>原图＝PNG 宽高（含透明留白）；游戏显示倍率＝动作显示比例；观看放大＝只看大，不改变导出。用“场地比例”比较大小，用“素材放大”看细节。</p>'}
    <details class="requirements-explainer"><summary>查看准备方法与编译限制（${native?'模板另有原生约束':'变换后单图宽高各 ≤ '+limits+' px'}）</summary><div class="requirements-grid"><div><b>格式与背景</b><p>导入普通静态 PNG，建议 RGBA 透明背景。JPG、PSD、GIF、APNG 和视频需要先导出为逐帧 PNG；棋盘格应来自编辑器背景，不能画进图片。</p></div>
    <div><b>尺寸怎么定</b><p>${effect?'特效没有统一的官方宽高。替换模板图层时优先沿用原贴图尺寸；原创序列可用 128×128 或 256×256 起步，再按效果范围调整。':'优先参照所选模板的实际画稿尺寸。原创可用 32×32 或 64×64 起步；这是建议，不是强制规格。不要把打包图集当作一张动作画稿导入。'}</p></div>
    <div><b>${native?'模板素材怎么换':'一组逐帧素材怎么交'}</b><p>${native?'先导出要改的那一层原图，保留画布尺寸和透明留白，画好后换回对应图层或通道。换图保留模板的组合方式；一层不是一整帧。要制作整张逐帧动画，请另建序列动作或序列特效，不要混用两种结构。':'每个姿势一张图，如 attack_001.png、attack_002.png。建议同一动作保持画布尺寸与脚下位置一致；批量导入按文件名中的数字排序，之后仍可手动调整。每段停留帧数可单独修改；60 播放帧 = 1 秒。'}</p></div></div>
    <details><summary>查看尺寸限制与制作提示</summary><p>单张文件 ≤ 64 MiB；${native?'以下为逐帧素材的限制，不代替模板原生结构检查。':''}当前${effect?'序列特效':'像素动作'}编译要求变换后的单图宽高各 ≤ ${limits} 像素。${effect?'序列特效图集上限为 2048×4096。':'像素图集上限为 1024×4096；一张图集容纳整组动作。'}单个动作最多 4096 播放帧，多张大图仍可能超出图集容量。</p><p>${effect?'柔光和渐隐可保留半透明像素。画稿的颜色混合方式与游戏最终效果有关，特殊混合需要额外校准。':'按原始像素绘制，建议关闭平滑缩放，不要先把小人放大六倍再导入。画稿尺寸、游戏显示倍率与观看放大是三个不同设置。'}自动裁掉各帧不同的透明边缘可能导致定位变化，导入后需检查偏移。${native?'模板请按层换图，不需要逐帧导出整段动画。':effect?'序列特效请提供逐帧 PNG。':'像素精灵图可在“导入动作图片”中启用网格切分，先预览再写入动作。'}</p></details>
    </details><div class="requirement-current"><span id="asset-current-info">${anim?.native?'模板原生素材：原图宽高请看右侧图层或通道；换图沿用该层画布，不是整段动画尺寸。':asset?`当前原图 <b>${asset.width}×${asset.height}</b> · ${asset.alpha?'有透明像素':'未检测到透明像素'} · 本动作 ${sizes.length} 种尺寸${sizes.length>1?'（逐帧检查脚下位置）':''}`:'尚未选中画稿；导入后点时间轴图片，查看原图宽高与透明情况。'}</span><button id="asset-guide-open" class="quiet">制作示例与检查 →</button></div></section>`;
}
function bindRequirements(anim,effect){
  $('#asset-guide-open').onclick=()=>modal(`<h2>${effect?'技能特效':'像素动作'}：准备、定位与检查</h2>
    ${anim?.native?'<p><b>当前是模板原生素材：</b>先导出要改的图层或通道原图，保留尺寸和透明留白，修改后换回同一层；播放整段检查组合是否错位。下方逐帧示例只适用于另建的序列动作或序列特效。</p>':''}
    <div class="guide-example"><code>${effect?'skill_flash':'attack'}_001.png<br>${effect?'skill_flash':'attack'}_002.png<br>${effect?'skill_flash':'attack'}_003.png</code><p><b>逐帧示例：</b>三张不同画稿分别停留 6、12、6 帧，共 24 帧（0.4 秒）。想让姿势多停一会儿，改停留帧数即可，不必复制相同 PNG。</p></div>
    <p><b>脚下与锚点怎么理解：</b>把“锚点”当成摆放图片的固定参照点，不是必须画在 PNG 上的标记。逐帧图片添加时默认将画布底边中点放在预览参考位置；有透明留白时，这里不一定就是人物脚底。同一动作各帧应让脚底相对画布的位置一致，避免播放时忽上忽下；浮空、跳跃则按设计保留变化。X 偏移正数向右，Y 偏移正数向下；模板原生素材沿用模板定位，不要套用逐帧底边规则。</p>
    ${effect?'<p>特效也需要固定参照位置，但不一定有“脚”：请在交接说明中写清它应贴着角色、目标还是固定地点出现。预览位置不是命中范围，也不会自动变成跟随目标的逻辑。</p>':'<p><b>原图、游戏倍率、观看放大：</b>例如 32×32 PNG 在游戏显示倍率 6、单张画稿缩放 1 时，动作画布按 192×192 的比例参与显示；原 PNG 仍是 32×32。透明边也在画布内，不等于小人本体有 192 像素高。“场地比例”按同一参考场地比较大小，“素材放大”适配整段动作；“观看放大”2× 只在当前视图上放大，不是把 PNG 变成 64×64。“画稿缩放”则会改变当前片段的变换，不要拿它代替观看放大。要改变角色大小，用“统一整组角色的显示倍率”一次更新全部像素动作（包括空槽位），不要只改单个动作；源 PNG、画稿缩放、偏移和技能特效不变。</p>'}
    <p><b>更直观地定位：</b>选中当前画稿，可拖动它或定位十字；点一下画布后用方向键微调。用“点选脚底 / 中心”指定定位位置，或用“可见底边对齐”“可见中心对齐”。对齐只改当前画稿、不裁原图；底边可能是武器或影子，不一定是脚底。模板原生素材保留自身定位，不套用这些逐帧操作。</p>
    <p><b>交接定位：</b>用“导出定位参考图”输出当前画面的参考 PNG；图上注明“非实战截图”。比较比例先选“场地比例”，导出的“素材放大”画面不能当游戏显示尺寸。参考图不是透明源素材，也不能代替可编辑工程或战斗验收。</p>
    <p><b>下一步：</b>播放整段，检查原图尺寸、脚下或特效参照位置、顺序、停留时间；再点“编译后预览”核对实际输出。遇到报错按提示修正，不要仅凭编辑器能播放就判定通过。</p>
    <div class="notice">${effect?'技能画面、角色喊声和技能音效分别制作，再到“技能制作 → 技能预览”检查配合；编排作为预览与交接数据保存。素材播放和编译回读都不能证明移动、命中、伤害、目标选择、镜头或条件分支正确，仍需制作方接入游戏验证。':'模板完整定位画布与裁出的小人图块不是同一种尺寸，宽高以当前原图为准。预览参考线不是已核实的战斗场地边界；观看窗口大小也不是实际游戏场地大小。编译回读通过后，仍需制作方在游戏中检查比例、定位与遮挡。'}</div>`);
}

function refreshRequirements(anim){const node=$('#asset-current-info');if(!node||anim.native)return;const c=anim.clips?.[S.clip],a=c?S.p.assets[c.asset]:null;const sizes=new Set((anim.clips||[]).map(c=>{const a=S.p.assets[c.asset];return a?`${a.width}x${a.height}`:'';}));if(a)node.textContent=`当前原图 ${a.width}×${a.height} · ${a.alpha?'有透明像素':'未检测到透明像素'} · 本动作 ${sizes.size} 种尺寸${sizes.size>1?'（逐帧检查脚下位置）':''}`;}
