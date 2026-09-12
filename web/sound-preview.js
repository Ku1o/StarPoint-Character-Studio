'use strict';
// Decode before the visual clock starts; schedule every sound on one audio clock.
let previewAudioContext=null;
const decodedSounds=new Map();
async function prepareSoundPlayback(specs){
  if(!specs.length)return {start(){},stop(){}};
  previewAudioContext??=new AudioContext();
  await previewAudioContext.resume();
  const context=previewAudioContext;
  const decoded=await Promise.all(specs.map(async spec=>{
    let pending=decodedSounds.get(spec.url);
    if(!pending){
      const bytes=spec.url.startsWith('data:audio/')
        ? Promise.resolve(Uint8Array.from(atob(spec.url.split(',')[1]),c=>c.charCodeAt(0)).buffer)
        : fetch(spec.url).then(r=>{if(!r.ok)throw Error('声音文件无法读取');return r.arrayBuffer();});
      pending=bytes.then(b=>context.decodeAudioData(b));
      decodedSounds.set(spec.url,pending);
      pending.catch(()=>decodedSounds.delete(spec.url));
      if(decodedSounds.size>48)decodedSounds.delete(decodedSounds.keys().next().value);
    }
    try{return {...spec,buffer:await pending};}
    catch{throw Error('声音无法解码，请检查 WAV、MP3 或 OGG 文件');}
  }));
  let sources=[];
  return {
    start(fromSeconds=0){
      this.stop();
      const start=context.currentTime;
      for(const spec of decoded){
        let offset=Math.max(0,fromSeconds-spec.seconds)*spec.rate;
        const looping=spec.loop===-1||spec.loop>1;
        const end=Math.min(spec.endSeconds??Infinity,looping?(spec.loop===-1?Infinity:spec.seconds+spec.buffer.duration*spec.loop/spec.rate):spec.seconds+spec.buffer.duration/spec.rate);
        if(fromSeconds>=end)continue;
        if(looping)offset%=spec.buffer.duration;
        const node=context.createBufferSource(),gain=context.createGain();
        node.buffer=spec.buffer;node.playbackRate.value=spec.rate;
        node.loop=looping;
        gain.gain.value=Math.min(1,Math.max(0,spec.volume));
        node.connect(gain);gain.connect(context.destination);sources.push(node);
        node.onended=()=>{node.disconnect();gain.disconnect();sources=sources.filter(n=>n!==node);};
        node.start(start+Math.max(0,spec.seconds-fromSeconds),offset);
        if(Number.isFinite(end))node.stop(start+Math.max(0,end-fromSeconds));
      }
    },
    stop(){for(const node of sources){try{node.stop();}catch{}node.disconnect();}sources=[];}
  };
}
function animationSoundSpecs(anim,start=0,trackSpeed=1,volume=1){
  const rate=S.speed*trackSpeed*(anim.runtimeSpeed||1);
  return (anim.soundEvents||[]).filter(ev=>ev.enabled!==false&&ev.asset&&(anim.kind!=='stop'||ev.start===0)).map(ev=>({url:assetUrl(ev.asset),seconds:start/60/S.speed+ev.start/60/rate,endSeconds:ev.end>=0?start/60/S.speed+ev.end/60/rate:undefined,loop:ev.loop??1,rate,volume:(ev.volume??1)*volume}));
}
function editorSoundSpecs(){
  if(S.page!=='scene')return animationSoundSpecs(current());
  return S.p.scene.tracks.flatMap(t=>{
    if(t.visible===false||t.start>=S.p.scene.duration)return [];
    const until=Math.min(S.p.scene.duration,t.end>=0?t.end:S.p.scene.duration),endSeconds=until/60/S.speed;
    if(t.type==='audio')return [{url:assetUrl(t.ref),seconds:t.start/60/S.speed,endSeconds,rate:S.speed*(t.speed||1),volume:t.volume??1}];
    const original=(t.type==='actor'?S.p.animations:S.p.effects).find(a=>a.id===t.ref);
    if(!original)return [];
    const anim={...original,kind:t.playMode||original.kind};
    const length=duration(anim)/((t.speed||1)*(anim.runtimeSpeed||1)),loops=(t.playMode||anim.kind)==='loop'?Math.ceil((until-t.start)/length):1;
    return Array.from({length:Math.max(0,loops)},(_,i)=>animationSoundSpecs(anim,t.start+i*length,t.speed||1,t.volume??1)).flat().filter(s=>s.seconds<endSeconds).map(s=>({...s,endSeconds:Math.min(s.endSeconds??Infinity,endSeconds)}));
  });
}
