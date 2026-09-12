'use strict';
// Pure geometry shared by the editor and the compiled-data player.
const PreviewLayout=(()=>{
  const identity=[1,0,0,1,0,0];
  function multiply(a,b){return [a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],a[1]*b[2]+a[3]*b[3],a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]];}
  function transform(x=0,y=0,scale=1,degrees=0){const r=degrees*Math.PI/180,c=Math.cos(r)*scale,s=Math.sin(r)*scale;return [c,s,-s,c,x,y];}
  function box(bounds,m,x,y,w,h){for(const [px,py] of [[x,y],[x+w,y],[x,y+h],[x+w,y+h]]){const xx=m[0]*px+m[2]*py+m[4],yy=m[1]*px+m[3]*py+m[5];bounds.minX=Math.min(bounds.minX,xx);bounds.minY=Math.min(bounds.minY,yy);bounds.maxX=Math.max(bounds.maxX,xx);bounds.maxY=Math.max(bounds.maxY,yy);}return bounds;}
  const empty=()=>({minX:Infinity,minY:Infinity,maxX:-Infinity,maxY:-Infinity});
  function dimensions(a){return [a?.width||a?.naturalWidth||0,a?.height||a?.naturalHeight||0];}
  function commands(bounds,frames,assets,scale=1,parent=identity,layers={}){const world=multiply(parent,transform(0,0,scale));for(const frame of frames||[])for(const c of frame){const l=layers[c.asset];if(l?.visible===false||c.alpha===0)continue;const [w,h]=dimensions(assets[l?.asset||c.asset]);if(w&&h)box(bounds,multiply(world,c.matrix),-(c.fx||0)+(l?.x||0),-(c.fy||0)+(l?.y||0),w,h);}return bounds;}
  function animation(bounds,a,assets,parent=identity){if(!a)return bounds;if(a.native)return commands(bounds,typeof effectFrames==='function'?effectFrames(a):a.nativeFrames,assets,a.frameScale||1,parent,a.channels?{}:a.layers);const world=multiply(parent,transform(0,0,a.frameScale||1));for(const c of a.clips||[]){if(c.opacity===0)continue;const [w,h]=dimensions(assets[c.asset]);if(!w||!h)continue;let m=multiply(world,transform(c.x||0,c.y||0,c.scale||1));m=multiply(m,transform(w/2,h/2,1,c.rotation||0));m=multiply(m,[c.flip?-1:1,0,0,1,0,0]);box(bounds,m,-w/2,-h/2,w,h);}return bounds;}
  function scene(p){const bounds=empty();for(const t of p.scene.tracks){if(t.type==='audio'||t.visible===false||t.opacity===0||t.start>=p.scene.duration)continue;const a=(t.type==='actor'?p.animations:p.effects).find(a=>a.id===t.ref);animation(bounds,a,p.assets,transform(t.x||0,t.y||0,t.scale||1,t.rotation||0));}return bounds;}
  function fit(bounds,w,h,zoom=1,padding=32){if(!Number.isFinite(bounds.minX))bounds={minX:-32,minY:-64,maxX:32,maxY:0};const scale=Math.max(.00001,Math.min(Math.max(1,w-padding*2)/Math.max(1,bounds.maxX-bounds.minX),Math.max(1,h-padding*2)/Math.max(1,bounds.maxY-bounds.minY)))*zoom;return {x:w/2-(bounds.minX+bounds.maxX)/2*scale,y:h/2-(bounds.minY+bounds.maxY)/2*scale,scale,bounds};}
  return {empty,multiply,transform,box,commands,animation,scene,fit};
})();
if(typeof module!=='undefined')module.exports=PreviewLayout;

const coloredImages=new WeakMap();
function previewImage(image,command){
  const packed=(command.color??0x64000000)>>>0;
  const color=command.colorTransform||[(packed>>>24)/100,(packed>>>16)&255,(packed>>>8)&255,packed&255];
  if(color[0]===1&&color.slice(1).every(v=>v===0))return image;
  let cache=coloredImages.get(image);if(!cache){cache=new Map();coloredImages.set(image,cache);}
  const key=color.join(',');if(cache.has(key))return cache.get(key);
  const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
  const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0);
  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),data=pixels.data;
  for(let i=0;i<data.length;i+=4)for(let c=0;c<3;c++)data[i+c]=Math.min(255,Math.max(0,data[i+c]*color[0]+color[c+1]));
  ctx.putImageData(pixels,0,0);cache.set(key,canvas);if(cache.size>32)cache.delete(cache.keys().next().value);return canvas;
}
