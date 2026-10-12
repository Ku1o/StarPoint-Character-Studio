'use strict';
// Every pending author intent stays in the brief and handoff.
function appendAuthorIntegrationControls(){
  if(!S.p||S.page!=='gameplay'||$('#author-integration-controls'))return;
  $('#content').insertAdjacentHTML('beforeend',`<section class="form-card" id="author-integration-controls"><h3>把中文方案接到游戏条目</h3><p>先选择真实玩法参考，再预览工具能够实现的卡片。只有明确勾选并应用的部分会加入当前工程；已有条目、原始参考和其余想法会保留。</p><button id="author-integration-preview">查看可接入的卡片</button><button id="author-integration-undo">撤回最近一次卡片接入</button><p class="hint">应用会生成可编译的实际条目，游戏内的触发、效果和完整素材仍需验证。</p></section>`);
  $('#author-integration-preview').onclick=()=>busy('核对中文卡片与实际游戏条目',openAuthorGameplayPreview);
  $('#author-integration-undo').onclick=()=>busy('撤回最近一次卡片接入',async()=>{
    await saveNow();const previous=clone(S.p);
    const p=await api('/api/author-gameplay-undo',{id:S.p.id,revision:S.p.revision});
    S.undo.push(previous);S.redo=[];S.p=p;S.generation++;S.dirty=false;render();
    toast('已撤回最近一次卡片接入；作者方案保留');
  });
}
function mechanicsTodoRows(plan,report){
  const states=Object.entries(report.todoStates||{});
  return `<div class="mechanics-todo-list">${plan.makerSteps.map(step=>{const base=`todo-${plan.cardId}-${step.id}`;return `<section class="mechanics-todo-row" data-todo-card="${esc(plan.cardId)}" data-todo-step="${esc(step.id)}"><div><strong>${esc(step.title)}</strong><p>${esc(step.action)}</p>${step.stale?'<p class="notice">方案或参考已变化，旧进度保留在记录中；这一步需要重新核对。</p>':''}</div>${selectField('进度',base+'-state',step.workflowState||'pending',states)}<div class="mechanics-todo-note">${textField('进度说明：已准备什么、缺什么或交给谁',''+base+'-note',step.note||'')}<button data-todo-save="${esc(base)}" data-todo-card="${esc(plan.cardId)}" data-todo-step="${esc(step.id)}">保存这一步</button></div></section>`;}).join('')}</div>`;
}

async function openAuthorGameplayPreview(){
  await saveNow();const result=await api('/api/author-gameplay-preview',{id:S.p.id});
  const rows=result.items||[];
  const pendingHtml=`${(result.blockers||[]).map(reason=>`<p class="notice">${esc(reason)}</p>`).join('')}${(result.pending||[]).length?`<section class="form-card"><h3>继续保留的说明和协助申请</h3>${result.pending.map(item=>`<p><strong>${esc(item.planLabel)}</strong>：${esc(item.text)}</p><p class="hint">${esc(item.pendingNextAction)}</p>`).join('')}</section>`:''}`;
  modal(`<h2>中文方案接入预览</h2><p>逐项核对想法和工具将生成的实际效果，再选择应用。未支持的想法仍会随工程交接。</p><div id="author-integration-result">${rows.map(row=>`<section class="notice"><strong>${esc(row.planLabel||'玩法卡片')}</strong><p>${esc(row.text||'')}</p><p>${esc(row.description||row.reason||'仍需核对')}</p>${row.status==='supported'?`<label class="check-row"><input type="checkbox" data-integration-card="${esc(row.id)}">把这一项加入实际游戏条目</label>`:`<p class="hint">${row.status==='applied'?'已经应用；修改方案后需重新核对':'保留为待协助，不会自动应用'}</p>`}</section>`).join('')||'<p>还没有中文卡片。在方案页选择能力或队长技能，再添加卡片；直接填写的特殊要求继续交给制作方。</p>'}</div><div class="creator-report-list">${(result.notes||[]).map(note=>`<p>${esc(note)}</p>`).join('')}</div><p>接入预览不会改动工程。原始条目和技能程序保留；游戏验收仍待完成。</p><div class="modal-actions"><button id="author-integration-apply" class="primary" ${result.canApply?'':'disabled'}>应用勾选的卡片</button><button id="author-integration-report">下载接入核对记录</button><button id="author-integration-help">继续说明或请求协助</button></div>`);
  $('#author-integration-result').insertAdjacentHTML('afterend',pendingHtml);
  const plans=result.integrationPlans?.plans||[];
  if(plans.length)$('#author-integration-result').insertAdjacentHTML('beforeend',`<section class="form-card" id="author-mechanics-plans"><h3>复杂玩法的制作步骤与缺项</h3><p>${esc(result.integrationPlans.note)}</p>${plans.map(plan=>`<section class="notice" data-mechanics-plan="${esc(plan.mechanic)}"><strong>${esc(plan.planLabel)} · ${esc(plan.title)}</strong><p>${esc(plan.text)}</p>${plan.providedDetails.length?`<p>已说明：${plan.providedDetails.map(row=>`${esc(row.label)}：${esc(row.value)}`).join('；')}</p>`:''}<p>还可补充或申请协助：${plan.missingDetails.map(row=>esc(row.label)).join('、')||'目前所列信息已说明，制作方继续核对。'}</p><p>复用参考：${esc(plan.referenceCheck.label||'尚未选择，可以填写参考或请协助')}；${plan.referenceCheck.status==='references_checked'?'已检查固定引用，实际行为仍待核':'来源与接入仍需核对'}</p><p>制作方接续：${plan.makerSteps.map(row=>esc(row.title)).join(' → ')}</p>${mechanicsTodoRows(plan,result.integrationPlans)}</section>`).join('')}</section>`);
  appendAssistanceControls(result.assistance,'#author-integration-result');
  if(plans.length)$('#author-mechanics-plans').insertAdjacentHTML('afterbegin',`<p class="hint">${esc(result.integrationPlans.workflowNote||'进度只说明资料或制作准备情况；准备好待验仍需核验游戏行为。')}</p>`);
  const history=result.integrationPlans?.workflowHistory||[];
  if(history.length&&!$('#author-mechanics-plans'))$('#author-integration-result').insertAdjacentHTML('beforeend','<section class="form-card" id="author-mechanics-plans"><h3>保留的制作待办</h3></section>');
  if(history.length)$('#author-mechanics-plans').insertAdjacentHTML('beforeend',`<details id="mechanics-todo-history"><summary>保留的待办记录（${history.length}）${result.integrationPlans.staleHistoryCount?` · ${result.integrationPlans.staleHistoryCount} 条与当前方案不同`:''}</summary><p>方案或参考变化后，当前步骤重新核对。旧记录继续保留，可下载完整接入核对记录。</p>${history.slice(-20).map(row=>`<p><strong>${esc(result.integrationPlans.todoStates[row.state]||'历史状态')}</strong>：${esc(row.note||'未填写说明')}</p>`).join('')}${history.length>20?'<p>这里显示最近20条，完整历史随工程与报告保留。</p>':''}</details>`);
  $$('[data-todo-save]').forEach(button=>button.onclick=()=>busy('保存复杂方案待办进度',async()=>{
    const base=button.dataset.todoSave;
    const previous=clone(S.p);
    const p=await api('/api/mechanics-todo-update',{id:S.p.id,revision:result.revision,token:result.integrationPlans.todoToken,
      cardId:button.dataset.todoCard,stepId:button.dataset.todoStep,state:$('#'+base+'-state').value,note:$('#'+base+'-note').value});
    S.undo.push(previous);S.redo=[];S.p=p;S.generation++;S.dirty=false;$('#modal').close();render();await openAuthorGameplayPreview();toast('进度已保存；原方案保留，游戏行为仍待验');
  }));
  $('#author-integration-report').onclick=()=>downloadStudioReport('中文方案接入核对记录.json',result);
  $('#author-integration-help').onclick=()=>{$('#modal').close();creatorNavigate('production');};
  $('#author-integration-apply').onclick=()=>busy('生成并校验选中的游戏条目',async()=>{
    const cardIds=$$('[data-integration-card]:checked').map(input=>input.dataset.integrationCard);
    if(!cardIds.length)return toast('请先勾选需要加入的卡片',true);
    const previous=clone(S.p);
    const p=await api('/api/author-gameplay-apply',{id:S.p.id,revision:S.p.revision,token:result.token,cardIds});
    S.undo.push(previous);S.redo=[];S.p=p;S.generation++;S.dirty=false;$('#modal').close();render();
    toast('所选卡片已加入真实条目；其余想法和原始参考保留');
  });
}

function appendAssistanceControls(report,after){
  if(!report?.requests?.length)return;
  $(after).insertAdjacentHTML('afterend',`<section class="form-card" id="dependency-assistance"><h3>可直接保存的协助清单</h3><p>${esc(report.note)}</p>${report.requests.map((item,index)=>`<section class="notice" data-assistance-request="${index}"><strong>${esc(item.title)}</strong>${item.text?`<p>${esc(item.text)}</p>`:''}<p>${esc(item.reason)}</p><p>作者可以说明：${esc(item.authorInput)}</p><p>制作方继续核对：${esc(item.makerAction)}</p><p class="hint">${esc(item.reuse)}</p><button data-assistance-save="${index}">把这一项加入交接说明</button></section>`).join('')}</section>`);
  $$('[data-assistance-save]').forEach(button=>button.onclick=()=>busy('保存具体协助需求',async()=>{
    // Use the existing brief notes. Never replace a hand-written declaration or
    // mark a technical issue resolved merely because a request was saved.
    if(S.p.id!==report.projectIdentity.id||S.p.revision!==report.projectIdentity.revision)throw Error('工程已更新，请重新检查后保存协助清单');
    const request=report.requests[Number(button.dataset.assistanceSave)],block=`【待协助：${request.title}】\n${request.requestText}`;
    const notes=S.p.productionBrief.notes||'';
    if(notes.includes(block)){toast('这项协助说明已经保留');return;}
    const next=[notes,block].filter(Boolean).join('\n\n');
    if(next.length>12000)throw Error('交接说明已较长，请下载完整核对记录，在作者填写包中整理后继续');
    mutate(()=>{S.p.productionBrief.notes=next;},false);await saveNow();
    $('#modal').close();creatorNavigate('production');toast('协助需求已加入交接说明；原说明和素材保留');
  }));
}
