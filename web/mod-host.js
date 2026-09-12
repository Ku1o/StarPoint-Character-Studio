'use strict';
(async()=>{
  try{
    const session=await api('/api/session');
    if(session.host!=='mod')return;
    const parentOrigin=session.parentOrigin;
    $('#shutdown').title='保存并返回 MOD';
    $('#shutdown').onclick=()=>saveForParent('return');
    async function saveForParent(requestId){
      try{
        if($('#busy')&&!$('#busy').hidden)throw Error('正在导入或编译，请完成后再返回');
        if(document.activeElement?.blur)document.activeElement.blur();
        await saveNow();stop();
        parent.postMessage({type:'character-studio-saved',requestId,ok:true},parentOrigin);
      }catch(e){toast(e.message,true);parent.postMessage({type:'character-studio-saved',requestId,ok:false,error:e.message},parentOrigin);}
    }
    window.addEventListener('message',event=>{
      if(event.origin!==parentOrigin||event.source!==parent)return;
      if(event.data?.type==='character-studio-save')saveForParent(event.data.requestId);
    });
    parent.postMessage({type:'character-studio-ready'},parentOrigin);
  }catch(e){toast(e.message,true);}
})();
