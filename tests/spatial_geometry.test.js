'use strict';
const fs=require('node:fs');
const assert=require('node:assert/strict');
const G=require('../web/spatial-geometry.js');
const L=require('../web/preview-layout.js');
function close(a,b){assert(Math.abs(a-b)<1e-8,`${a} != ${b}`);}
const c={x:-16,y:-40,scale:2,rotation:33,flip:true};
const m=G.clipMatrix(c,32,40),inv=G.inverse(m),p=G.point(m,8,12),original=G.point(inv,p.x,p.y);close(original.x,8);close(original.y,12);
const anchor=G.anchor(c,32,40,16,36),aligned=G.point(G.clipMatrix({...c,...anchor},32,40),16,36);close(aligned.x,0);close(aligned.y,0);
const native={native:{},frameScale:2,nativeFrames:[[{asset:'a',matrix:[0,1,-1,0,70,90],fx:12,fy:-20,alpha:1}]],layers:{a:{asset:'a',x:30,y:-15,visible:true}}};
assert.deepEqual(L.animation(L.empty(),native,{a:{width:80,height:140}}),{minX:-150,minY:216,maxX:130,maxY:376});
const field={width:1000,height:1600,originX:500,originY:1200};
for(const [w,h]of [[280,340],[700,420],[1400,900]]){const view=G.fitField(field,w,h);const origin=G.screenToLocal(view,view.x,view.y);close(origin.x,0);close(origin.y,0);assert(view.scale>0);const left=view.x-field.originX*view.scale,top=view.y-field.originY*view.scale;assert(left>=41.999);assert(top>=37.999);assert(left+field.width*view.scale<=w-41.999);assert(top+field.height*view.scale<=h-37.999);}
const pixels=new Uint8ClampedArray(6*8*4);pixels[(2*6+1)*4+3]=255;pixels[(5*6+4)*4+3]=1;assert.deepEqual(G.alphaBounds(pixels,6,8),{x:1,y:2,width:4,height:4});assert.equal(G.alphaBounds(new Uint8ClampedArray(16),2,2),null);
const box=G.bounds(G.clipMatrix({x:-3,y:-2,scale:2},6,8),{x:1,y:2,width:4,height:4});assert.deepEqual(box,{minX:-1,minY:2,maxX:7,maxY:10});
assert(!G.outside({minX:-500,maxX:500,minY:-1200,maxY:400},field));assert(G.outside({minX:-501,maxX:0,minY:0,maxY:1},field));
console.log('Spatial transforms, anchor inverse, alpha bounds, native trim and fixed field fit passed.');
