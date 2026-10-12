'use strict';
function dependencyAuthorRows(rows,empty){
  const readable=(rows||[]).filter(row=>row.resourceOwner!=='game-common-ui').map(row=>{
    const source=String(row.definitionEvidence?.logical||row.sourceIdentity?.logical||row.logical||'');
    if(!/\.(?:ui\.(?:json|amf3\.deflate)|html(?:\.deflate)?)$/.test(source)&&!['ui-consumer','html-consumer'].includes(row.origin))return row;
    const raw=row.reason||'';
    let reason='角色界面的图片、文字或子资源还有待核部分，制作方会继续检查。作者只需说明希望的表现或复用参考。';
    if(/UI文字/.test(raw))reason='这里的文字由游戏运行时填入，制作方还需核对角色相关的显示内容和图标。';
    else if(/dummy/.test(raw))reason='这是留给游戏运行时填图的位置，制作方还需核对实际图片。作者可复用现有素材或申请协助。';
    else if(/内嵌.*时间轴/.test(raw))reason='这个界面的动画步骤和声音仍需制作方核对；原有播放顺序与声音继续保留。';
    else if(/固定引用不在/.test(raw))reason='这张界面图片尚未取得对应素材证据，请制作方核对公共图集。作者可以复用或申请协助。';
    else if(/解析待核|未解码|读取格式/.test(raw))reason='界面文件暂时不能完整读取，请制作方核对格式和来源；原文件保留。';
    return {...row,label:'角色界面素材',reason};
  });
  return creatorRows(readable,empty);
}
function addAtlasWorkflowControls(){
  if(S.page!=='checks'||!S.p||$('#atlas-workflow-panel'))return;
  $('#content').insertAdjacentHTML('beforeend',`<section class="form-card" id="atlas-workflow-panel"><h3>自动整理图片与检查素材</h3><p>工具自动检查已保存的图片、动作和声音。适合整理的图集会先核对每个图块和播放步骤，原画、时序与声音继续保留。</p><p>后续资源整理：${S.p.atlasOptimization?.enabled?'已开启无损整理':'使用原有排布'}</p><button id="atlas-optimize-preview">查看无损整理效果</button><button id="dependency-closure-open">检查用到的素材</button><button id="atlas-optimization-disable">恢复原有排布</button></section>`);
  $('#atlas-optimize-preview').onclick=()=>busy('对比图片排布和播放结果',openAtlasOptimization);
  $('#dependency-closure-open').onclick=()=>busy('检查当前工程引用的素材',openDependencyClosure);
  $('#atlas-optimization-disable').onclick=()=>busy('保存原排布设置',()=>setAtlasOptimizationEnabled(false));
}
async function setAtlasOptimizationEnabled(enabled){
  mutate(()=>{S.p.atlasOptimization={...(S.p.atlasOptimization||{}),enabled};},false);
  await saveNow();if($('#modal').open)$('#modal').close();render();toast(enabled?'已开启后续图片无损整理；原稿保留':'已恢复原有排布；原稿保留');
}
function atlasKeepReason(reason){
  if(/no dimension\/area/.test(reason))return '当前排布已合适，没有更小且完全相同的候选';
  if(/budget|bounded|exhausted/.test(reason))return '超过本次自动检查量，安全保留原有排布';
  if(/unsupported JSON\/UI/.test(reason))return '这类界面图集暂不自动整理，原文件保留';
  if(/paired PNG|missing/.test(reason))return '所需配套文件不完整，等待接入方确认';
  return '暂时不能证明整理后完全相同，保留原有排布';
}
async function openAtlasOptimization(){
  await saveNow();const result=await api('/api/atlas-optimization',{id:S.p.id}),report=result.atlasOptimization;
  modal(`<h2>图片无损整理效果</h2><p>本次只做对比，尚未更改工程设置。只有图片内容、变换和每个播放步骤核对一致的候选才会采用。</p><p id="atlas-optimization-summary">可整理 ${report.optimizedBundles} 套，保留 ${report.skippedBundles} 套；图片占用面积减少 ${report.savedPaddedArea.toLocaleString()} 平方像素。</p><div id="atlas-optimization-result" class="creator-report-list">${report.bundles.map(row=>`<section class="notice"><strong>${esc(row.png||row.atlas)}</strong><p>${row.accepted?'逐图块与播放核对通过，可使用更紧凑的排布':esc(atlasKeepReason(row.reason))}</p>${row.before?`<p>整理前 ${row.before.width}×${row.before.height}${row.after?` → 整理后 ${row.after.width}×${row.after.height}`:''}</p>`:''}</section>`).join('')||'<p>当前工程没有可自动整理的图集。</p>'}</div><p>减少面积不保证压缩包更小。游戏里的装箱、技能行为和播放仍待接入方验收。</p><div class="modal-actions"><button id="atlas-optimization-enable" class="primary">后续资源整理使用此功能</button><button id="atlas-report-download">下载完整核验记录</button></div>`);
  $('#atlas-optimization-enable').onclick=()=>busy('保存无损整理设置',()=>setAtlasOptimizationEnabled(true));
  $('#atlas-report-download').onclick=()=>downloadStudioReport('图片无损整理核验记录.json',result);
}
async function openDependencyClosure(){
  await saveNow();const result=await api('/api/dependency-closure',{id:S.p.id}),closure=result.dependencyClosure;
  const gaps=[...(closure.scopeGaps||[]),...(closure.characterSemanticGaps||[]),...(closure.sourceDefinitionProblems||[]),...(closure.referenceReadErrors||[])].filter(row=>row.resourceOwner!=='game-common-ui');
  const counts=closure.authorCounts||closure.counts;
  const referenceOnly=closure.compiledCoverage?.status==='unavailable';
  modal(`<h2>用到的素材是否齐全</h2><p>${referenceOnly?'当前草稿暂时不能编译：本次仅追踪已保留的参考资源，未覆盖新编辑的图片、动作和声音。请先保存说明交接，以下数量不能代表当前角色素材已检查齐全。':'工具从当前已保存的动作、特效、技能参考和声音中自动追踪素材；不需要填写技术路径或范围声明。'}</p><p id="dependency-closure-summary">找到 ${counts.resolved} 项依赖；明确缺失 ${counts.missing} 项；需要接入方确认 ${counts.dynamic+counts.unsupported+gaps.length} 项。</p><div id="dependency-closure-result"><section class="form-card"><h3>明确缺失的素材</h3>${dependencyAuthorRows(closure.missingReferences,'在本次可解析范围内，没有发现明确缺失的引用。')}</section><section class="form-card"><h3>仍需要确认的引用</h3>${dependencyAuthorRows([...(closure.unresolvedDynamic||[]),...(closure.unsupported||[])])}</section><details class="form-card"><summary>接入范围与参考数据待核</summary>${dependencyAuthorRows(gaps)}${closure.compiledCoverage?.status==='unavailable'?`<p>草稿资源暂未编译：${esc(closure.compiledCoverage.reason)}</p>`:''}</details></div><p class="hint">只检查到了已知范围。${closure.closure.characterSemanticClosure?'当前声明的语义范围已闭合，仍需游戏内验证。':'整角色的游戏依赖尚未全部核验，不能据此认定角色已可上线。'}</p><p class="hint">游戏通用界面的核验保留在制作方技术报告中，不计入稿主的素材缺项。</p><div class="modal-actions"><button id="dependency-explain">说明缺项或请求协助</button><button id="dependency-report-download">下载制作方技术报告</button></div>`);
  const coverage=closure.nativeDefinitionCoverage,domainNames={skill:'主动技能',pixelart:'普通小人',special:'特殊小人',ability:'能力与队长效果',summon:'召唤物',powerFlip:'强化弹射',shared:'角色复用的公共素材',ui:'战斗界面',cutin:'独立技能切入图'};
  const domainHints={skill:'追踪保留的技能版本及技能切换，文件是否存在见缺失列表。',pixelart:'检查主位及队长需要的小人动作。',special:'按角色定义检查特殊小人动作。',ability:'已追踪能够确认的能力素材，其他特殊能力和额外能力仍需制作方核对。',summon:'已追踪能够确认的引用，召唤物与跟随物的完整动作、技能和图标仍需核对。',powerFlip:'按真实职业定义检查三个等级的强化弹射。',shared:'检查角色使用的通用特效、状态图标和战斗条件；现有素材可复用，实际触发仍需制作方核对。',ui:'检查战斗头像、状态栏和控制栏等图片。',cutin:'检查基础与进化形态的技能切入图。'};
  if(coverage){
    const effectSummary=coverage.abilityConversionSummary;
    if(effectSummary)$('#dependency-closure-result').insertAdjacentHTML('beforeend',`<section class="form-card" id="native-effect-conversion-summary"><h3>已保存的能力效果</h3><p>已解析 ${effectSummary.mappedEffectBlocks} 个效果分支，${effectSummary.pendingEffectBlocks} 个分支仍待制作方核对；能力条目另有 ${effectSummary.reportedAbilityProblems||0} 项检查提示。</p><p class="hint">这里检查已有能力引用的素材；额外能力和实际触发是否正确仍需单独验证，作者不用填写技术条目。</p></section>`);
    $('#dependency-closure-result').insertAdjacentHTML('beforeend',`<section class="form-card" id="character-shared-materials"><h3>角色需要的共用素材</h3><p>命中特效、状态图标等已有素材可以复用。只需说明这个角色希望的表现或参考角色，缺少素材时可以申请协助；游戏公共条件的详细检查保留在制作方技术报告中。</p></section>`);
    $('#dependency-closure-result').insertAdjacentHTML('afterbegin',`<section class="form-card" id="native-definition-coverage"><h3>从真实角色定义自动展开的范围</h3><p>同时核对主位、副位、队长及保留的技能版本和形态。这里只表示作者素材的检查范围，实际一场战斗使用的资源仍需单独核验。</p>${Object.entries(coverage.domains||{}).map(([name,domain])=>`<section class="notice" data-native-domain="${esc(name)}"><strong>${esc(domainNames[name]||name)}：${domain.status==='included'?'已展开引用':domain.status==='not-applicable'?'此角色不适用':'仍需核对'}</strong><p>${esc(!coverage.sourceIdentity?"尚缺完整、有效的角色玩法参考，请制作方补充。":domain.status==="not-applicable"?"按真实角色定义，此项不适用。":domainHints[name]||"仍需制作方核对。")}</p><p class="hint">本次已提取 ${domain.authorRootCount??domain.roots.length} 个起始入口，继续追踪找到 ${domain.authorGraphResolved??domain.graphResolved??0} 项现有资源；这不代表完整性已核验。</p></section>`).join('')}</section>`);
    if(referenceOnly)$('#modal p').textContent='当前草稿暂时不能编译：本次追踪真实角色定义和已保留的参考资源，未覆盖无法编译的新图片、动作和声音。请先保存说明交接，以下数量不能代表整个角色已检查齐全。';
  }
  $('#dependency-explain').onclick=()=>{$('#modal').close();creatorNavigate('production');};
  appendAssistanceControls(closure.assistance,'#dependency-closure-result');
  $('#dependency-report-download').onclick=()=>downloadStudioReport('角色素材追踪记录.json',result);
}
