'use strict';
const assert=require('node:assert/strict');
const L=require('../web/preview-layout.js');
const assets={a:{width:80,height:140},b:{width:600,height:120}};
const anim={frameScale:6,clips:[{asset:'a',x:-40,y:-140,hold:6},{asset:'b',x:600,y:-280,rotation:135,scale:1.5,flip:true,hold:12}]};
const bounds=L.animation(L.empty(),anim,assets);
assert(bounds.maxX>4000&&bounds.minY<-800);
for(const [w,h] of [[280,300],[760,420],[1400,800]]){
 const fit=L.fit(bounds,w,h);
 for(const [x,y] of [[bounds.minX,bounds.minY],[bounds.maxX,bounds.maxY]]){
  assert(fit.x+x*fit.scale>=31.999&&fit.x+x*fit.scale<=w-31.999);
  assert(fit.y+y*fit.scale>=31.999&&fit.y+y*fit.scale<=h-31.999);
 }
}
const native={native:{},frameScale:2,nativeFrames:[[{asset:'a',matrix:[0,1,-1,0,70,90],fx:12,fy:-20,alpha:1}]],layers:{a:{asset:'a',x:30,y:-15,visible:true}}};
const b=L.animation(L.empty(),native,assets);
assert.deepEqual(b,{minX:-150,minY:216,maxX:130,maxY:376});
const scene=L.scene({assets,animations:[{...anim,id:'a'}],effects:[],scene:{duration:100,tracks:[{type:'actor',ref:'a',start:0,scale:2,rotation:90,x:500,y:-100}]}});
assert(Math.abs(scene.minX-(500-bounds.maxY*2))<1e-8);
assert(Math.abs(scene.maxY-(-100+bounds.maxX*2))<1e-8);
console.log('Full-animation, native pivot, rotated scene and narrow viewport bounds passed.');
