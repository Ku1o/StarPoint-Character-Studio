'use strict';
// Authoring coordinates, not device pixels. The display zoom never enters saved transforms.
const SpatialGeometry=(()=>{
  const point=(m,x,y)=>({x:m[0]*x+m[2]*y+m[4],y:m[1]*x+m[3]*y+m[5]});
  function inverse(m){const d=m[0]*m[3]-m[1]*m[2];if(!Number.isFinite(d)||Math.abs(d)<1e-12)return null;return [m[3]/d,-m[1]/d,-m[2]/d,m[0]/d,(m[2]*m[5]-m[3]*m[4])/d,(m[1]*m[4]-m[0]*m[5])/d];}
  function clipMatrix(c,w,h){
    const s=c.scale??1,r=(c.rotation||0)*Math.PI/180,cs=Math.cos(r)*s,sn=Math.sin(r)*s,f=c.flip?-1:1;
    return [cs*f,sn*f,-sn,cs,(c.x||0)+w*s/2-cs*f*w/2+sn*h/2,(c.y||0)+h*s/2-sn*f*w/2-cs*h/2];
  }
  function bounds(m,b){const ps=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>point(m,x,y));return {minX:Math.min(...ps.map(p=>p.x)),maxX:Math.max(...ps.map(p=>p.x)),minY:Math.min(...ps.map(p=>p.y)),maxY:Math.max(...ps.map(p=>p.y))};}
  function anchor(c,w,h,x,y){const p=point(clipMatrix(c,w,h),x,y);return {x:(c.x||0)-p.x,y:(c.y||0)-p.y};}
  function alphaBounds(data,w,h){let x0=w,y0=h,x1=-1,y1=-1;for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(data[(y*w+x)*4+3]>0){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);}return x1<0?null:{x:x0,y:y0,width:x1-x0+1,height:y1-y0+1};}
  function fitField(field,w,h,zoom=1){const scale=Math.max(.00001,Math.min(Math.max(1,w-84)/field.width,Math.max(1,h-76)/field.height))*zoom;return {scale,x:w/2+(field.originX-field.width/2)*scale,y:h/2+(field.originY-field.height/2)*scale};}
  const screenToLocal=(view,x,y)=>({x:(x-view.x)/view.scale,y:(y-view.y)/view.scale});
  const round=n=>Math.round(n*1000)/1000;
  const outside=(b,f)=>!!b&&(b.minX+f.originX<0||b.maxX+f.originX>f.width||b.minY+f.originY<0||b.maxY+f.originY>f.height);
  return {point,inverse,clipMatrix,bounds,anchor,alphaBounds,fitField,screenToLocal,round,outside};
})();
if(typeof module!=='undefined')module.exports=SpatialGeometry;
