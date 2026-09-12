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
