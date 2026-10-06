/* Preserve the view while changing an item in the same project and module. */
'use strict';
function editorViewKey(){return S.p?S.p.id+':'+S.page:'';}
function captureEditorScroll(){
  const content=$('#content');
  if(content.dataset.viewKey!==editorViewKey())return null;
  return {key:editorViewKey(),x:window.scrollX,y:window.scrollY,top:content.scrollTop,left:content.scrollLeft,
    lists:[...content.querySelectorAll('.library-list')].map(el=>({top:el.scrollTop,left:el.scrollLeft}))};
}
function restoreEditorScroll(saved){
  const content=$('#content');content.dataset.viewKey=editorViewKey();
  if(!saved||saved.key!==editorViewKey())return;
  [...content.querySelectorAll('.library-list')].forEach((el,i)=>{if(saved.lists[i]){el.scrollTop=saved.lists[i].top;el.scrollLeft=saved.lists[i].left;}});
  content.scrollTop=saved.top;content.scrollLeft=saved.left;
  window.scrollTo({left:saved.x,top:saved.y,behavior:'instant'});
}

// 动作卡「来源与声明」字段（2026-10-06 凉月复盘）。app.js 的 renderInspector
// 保持原样，这里在 DOMContentLoaded 之后包裹它，为像素动作注入
// 用途说明 / 是否包含召唤物 / 附属物说明，为特效注入来源与说明。
document.addEventListener('DOMContentLoaded',()=>{
  if(typeof renderInspector!=='function'||typeof mutate!=='function')return;
  const baseRenderInspector=renderInspector;
  renderInspector=function(anim){
    baseRenderInspector(anim);
    const panel=document.querySelector('#inspector');
    if(!panel||!anim||anim.native)return;
    const page=typeof S!=='undefined'?S.page:'';
    if(page==='animations'){
      panel.insertAdjacentHTML('beforeend',
        '<hr class="divider"><h3>来源与声明</h3>'
        +field('用途说明','decl-purpose',anim.purpose||'')
        +selectField('是否包含召唤物/附属物','decl-companion',anim.includesCompanion===true?'yes':anim.includesCompanion===false?'no':'',[['','未标注'],['yes','是'],['no','否']])
        +field('附属物说明','decl-companion-note',anim.companionNote||''));
      bindValue('#decl-purpose',v=>anim.purpose=v);
      const companion=$('#decl-companion');
      if(companion)companion.onchange=()=>mutate(()=>{anim.includesCompanion=companion.value===''?'':companion.value==='yes';},false);
      bindValue('#decl-companion-note',v=>anim.companionNote=v);
    }
    if(page==='effects'){
      panel.insertAdjacentHTML('beforeend',
        '<hr class="divider"><h3>来源与声明</h3>'
        +selectField('特效来源','decl-origin',anim.origin||'',[['','未标注'],['reuse','复用（某角色）'],['reskin','重皮（模板+配色）'],['original','完全原创（四件套）']])
        +field('来源说明','decl-origin-note',anim.originNote||''));
      bindValue('#decl-origin',v=>anim.origin=v);
      bindValue('#decl-origin-note',v=>anim.originNote=v);
    }
  };
});
