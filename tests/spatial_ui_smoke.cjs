'use strict';
// Run against a Studio server with a disposable --projects directory.
// node tests/spatial_ui_smoke.cjs <local-url> <absolute-output-directory>
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const [url,out]=process.argv.slice(2);if(!url||!out||!path.isAbsolute(out))throw Error('Usage: spatial_ui_smoke.cjs <local-url> <absolute-output-directory>');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(url);await page.waitForFunction(()=>typeof S!=='undefined'&&S.token);
  await page.evaluate(async()=>{
   setProject(await api('/api/new',{name:'空间定位自动验收',kind:'original'}));
   const canvas=document.createElement('canvas');canvas.width=40;canvas.height=48;const c=canvas.getContext('2d');c.fillStyle='#a99dff';c.fillRect(8,4,24,40);c.fillStyle='#effaff';c.fillRect(12,10,6,6);
   const upload=await api('/api/upload',{id:S.p.id,files:[{name:'待机_001.png',category:'pixel',data:canvas.toDataURL().split(',')[1]}]});S.p=upload.project;
   S.p.animations[0].clips=[{asset:upload.ids[0],x:-20,y:-44,hold:30,scale:1,rotation:0,opacity:1,flip:false},{asset:upload.ids[0],x:-20,y:-44,hold:30,scale:1,rotation:0,opacity:1,flip:false}];
   S.p.effects=[{id:'spatialfx',name:'定位特效',kind:'loop',fps:60,frameScale:6,clips:[{asset:upload.ids[0],x:-20,y:-24,hold:120,scale:3,rotation:0,opacity:1,flip:false}]}];
   S.p.scene={duration:120,tracks:[{id:'actor',type:'actor',ref:S.p.animations[0].id,start:0,end:-1,x:0,y:0,scale:1,rotation:0,opacity:1,speed:1,visible:true},{id:'effect',type:'effect',ref:'spatialfx',start:0,end:-1,x:0,y:-300,scale:1,rotation:0,opacity:1,speed:1,visible:true}]};changed();await saveNow();S.page='animations';S.selected=S.p.animations[0].id;render();
  });
  await page.waitForFunction(()=>document.querySelector('#spatial-size')?.textContent.includes('24 × 40'));
  const baseline=await page.evaluate(()=>JSON.stringify(S.p.animations));
  const scale1=await page.evaluate(()=>{const r=$('#stage').getBoundingClientRect();return editorView(r.width,r.height).scale;});
  await page.locator('#zoom').selectOption('2');assert.equal(await page.evaluate(()=>JSON.stringify(S.p.animations)),baseline);assert.equal(await page.evaluate(()=>Object.hasOwn(S.p,'previewStage')),false);
  const scale2=await page.evaluate(()=>{const r=$('#stage').getBoundingClientRect();return editorView(r.width,r.height).scale;});assert(Math.abs(scale2-scale1*2)<1e-9);
  await page.locator('[data-spatial-mode="fit"]').click();await page.locator('[data-spatial-mode="field"]').click();assert.equal(await page.evaluate(()=>JSON.stringify(S.p.animations)),baseline);
  await page.locator('#spatial-coordinate-x').fill('-12');await page.locator('#spatial-coordinate-x').press('Tab');assert.equal(await page.evaluate(()=>current().clips[0].x),-12);await page.locator('#undo').click();assert.equal(await page.evaluate(()=>current().clips[0].x),-20);
  await page.evaluate(async()=>{await saveNow();});
  await page.locator('#stage').scrollIntoViewIfNeeded();
  const drag=await page.evaluate(()=>{const r=$('#stage').getBoundingClientRect(),v=editorView(r.width,r.height);return {x:r.left+v.x,y:r.top+v.y-20*6*v.scale,dx:8*6*v.scale,undo:S.undo.length};});
  await page.mouse.move(drag.x,drag.y);await page.mouse.down();await page.mouse.move(drag.x+drag.dx,drag.y,{steps:4});await page.mouse.up();
  assert(Math.abs(await page.evaluate(()=>current().clips[0].x)-(-12))<.03);assert.equal(await page.evaluate(()=>S.undo.length),drag.undo+1);await page.locator('#undo').click();assert.equal(await page.evaluate(()=>current().clips[0].x),-20);
  // Timeline inspector refresh preserves direct positioning controls.
  await page.locator('.frame-tile').nth(1).click();assert.equal(await page.locator('#spatial-coordinate-x').count(),1);await page.locator('[data-spatial-align="feet"]').click();assert.equal(await page.evaluate(()=>current().clips[1].y),-44);
  await page.locator('#stage').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.evaluate(()=>current().clips[1].x),-19);await page.locator('#undo').click();
  await page.evaluate(()=>{const c=current().clips[S.clip];c.rotation=90;c.flip=true;c.scale=1.5;changed();render();});
  await page.locator('[data-spatial-align="feet"]').click();assert(await page.evaluate(()=>{const c=current().clips[S.clip],p=SpatialGeometry.point(SpatialGeometry.clipMatrix(c,40,48),20,44);return Math.abs(p.x)<.002&&Math.abs(p.y)<.002;}));
  await page.evaluate(()=>{const c=current().clips[S.clip];c.rotation=0;c.flip=false;c.scale=1;changed();render();});await page.locator('[data-spatial-align="feet"]').click();
  // New visual controls keep undo atomic, including anchor pick and canceled drags.
  await page.locator('[data-spatial-mode="fit"]').click();await page.locator('#spatial-pick').click();await page.locator('#stage').scrollIntoViewIfNeeded();
  const pick=await page.evaluate(()=>{const c=current().clips[S.clip],r=$('#stage').getBoundingClientRect(),v=editorView(r.width,r.height),p=SpatialGeometry.point(SpatialGeometry.clipMatrix(c,40,48),20,24);return {x:r.left+v.x+p.x*current().frameScale*v.scale,y:r.top+v.y+p.y*current().frameScale*v.scale};});await page.mouse.click(pick.x,pick.y);assert(await page.evaluate(()=>{const c=current().clips[S.clip],p=SpatialGeometry.point(SpatialGeometry.clipMatrix(c,40,48),20,24);return Math.abs(p.x)<.02&&Math.abs(p.y)<.02;}));await page.locator('#undo').click();
  await page.locator('[data-spatial-mode="field"]').click();await page.evaluate(async()=>{await saveNow();});await page.locator('#stage').scrollIntoViewIfNeeded();
  const cancelDrag=await page.evaluate(()=>{const r=$('#stage').getBoundingClientRect(),v=editorView(r.width,r.height);return {x:r.left+v.x,y:r.top+v.y-20*6*v.scale,undo:S.undo.length,clip:JSON.stringify(current().clips[S.clip])};});await page.mouse.move(cancelDrag.x,cancelDrag.y);await page.mouse.down();await page.mouse.move(cancelDrag.x+20,cancelDrag.y);await page.locator('#stage').dispatchEvent('pointercancel',{pointerId:1});await page.mouse.up();assert.equal(await page.evaluate(()=>JSON.stringify(current().clips[S.clip])),cancelDrag.clip);assert.equal(await page.evaluate(()=>S.undo.length),cancelDrag.undo);
  await page.locator('#spatial-unify-scale').click();await page.locator('#spatial-global-scale').fill('5');await page.locator('#spatial-scale-apply').click();assert(await page.evaluate(()=>S.p.animations.every(a=>a.frameScale===5)));await page.locator('#undo').click();assert(await page.evaluate(()=>S.p.animations.every(a=>a.frameScale===6)));
  const downloadPromise=page.waitForEvent('download');await page.locator('#spatial-export').click();const download=await downloadPromise;await download.saveAs(path.join(out,'position-reference.png'));assert(fs.statSync(path.join(out,'position-reference.png')).size>1000);
  await page.locator('#compiled-preview').click();await page.locator('#readback-stage').waitFor();assert.equal(await page.locator('#readback-mode').inputValue(),'field');await page.locator('#readback-mode').selectOption('fit');await page.locator('#readback-mode').selectOption('field');await page.screenshot({path:path.join(out,'compiled-field.png'),fullPage:true});await page.locator('.modal-close').click();
  await page.locator('#stage').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'pixel-field.png'),fullPage:true});
  await page.locator('[data-page="effects"]').click();await page.locator('[data-skill-tab="scene"]').click();await page.locator('[data-track-select="effect"]').click();await page.locator('[data-spatial-place="target"]').click();
  assert(await page.evaluate(()=>{const t=S.p.scene.tracks.find(t=>t.id==='effect'),f=spatialField();return t.x===f.targetX-f.originX&&t.y===f.targetY-f.originY;}));assert.equal(await page.evaluate(()=>S.p.scene.tracks[0].x),0);
  // Canceling a drag preserves absent default coordinate keys and never persists a transient edit.
  await page.evaluate(async()=>{const t=S.p.scene.tracks.find(t=>t.id==='effect');delete t.x;delete t.y;changed();await saveNow();render();});await page.locator('#stage').scrollIntoViewIfNeeded();
  async function beginTrackDrag(){const p=await page.evaluate(()=>{const r=$('#stage').getBoundingClientRect(),v=editorView(r.width,r.height);return {x:r.left+v.x,y:r.top+v.y};});await page.mouse.move(p.x,p.y);await page.mouse.down();await page.mouse.move(p.x+30,p.y,{steps:3});assert(await page.evaluate(()=>!!spatialState.drag?.moved));}
  const beforeCancel=await page.evaluate(()=>JSON.stringify(S.p.scene));await beginTrackDrag();await page.locator('#stage').dispatchEvent('pointercancel',{pointerId:1});await page.mouse.up();assert.equal(await page.evaluate(()=>JSON.stringify(S.p.scene)),beforeCancel);
  await page.evaluate(()=>{S.p.name+=' · save race';changed();});await beginTrackDrag();await page.evaluate(async()=>{await saveNow();});await page.locator('#stage').dispatchEvent('pointercancel',{pointerId:1});await page.mouse.up();assert.equal(await page.evaluate(()=>JSON.stringify(S.p.scene)),beforeCancel);assert(await page.evaluate(async()=>{const p=await api('/api/project?id='+S.p.id);return JSON.stringify(p.scene)===JSON.stringify(S.p.scene)&&!Object.hasOwn(p.scene.tracks.find(t=>t.id==='effect'),'x');}));
  // Preview calibration saves separately from art and scene transforms.
  const sceneBefore=await page.evaluate(()=>JSON.stringify(S.p.scene));
  await page.locator('#spatial-settings').click();await page.locator('#spatial-width').fill('1800');await page.locator('#spatial-height').fill('2400');await page.locator('#spatial-originX').fill('900');await page.locator('#spatial-originY').fill('1800');await page.locator('#spatial-targetX').fill('900');await page.locator('#spatial-targetY').fill('700');await page.locator('#spatial-settings-save').click();assert.equal(await page.evaluate(()=>JSON.stringify(S.p.scene)),sceneBefore);
  await page.evaluate(async()=>{await saveNow();const p=await api('/api/project?id='+S.p.id);setProject(p);S.page='scene';S.selected='effect';render();});assert.equal(await page.evaluate(()=>S.p.previewStage.width),1800);assert.equal(await page.evaluate(()=>S.p.previewStage.profile),'custom');
  await page.locator('#spatial-settings').click();await page.locator('#spatial-width').fill('0');await page.locator('#spatial-settings-save').click();assert(await page.locator('#modal').evaluate(e=>e.open));assert((await page.locator('#spatial-settings-error').textContent()).includes('1–8192'));await page.locator('.modal-close').click();
  await page.locator('#stage').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'skill-field.png'),fullPage:true});
  for(const [width,height]of [[1280,800],[768,900],[390,844]]){await page.setViewportSize({width,height});await page.evaluate(()=>draw());const sizes=await page.evaluate(()=>({body:document.documentElement.scrollWidth,width:innerWidth,stage:$('#stage').getBoundingClientRect().width}));assert(sizes.stage>100);assert(sizes.body<=sizes.width+2,JSON.stringify(sizes));await page.screenshot({path:path.join(out,`skill-${width}.png`),fullPage:true});}
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:true,checks:['fixed-field-scale','zoom-nondestructive','alpha-bounds','position-undo','drag-single-undo','keyboard','rotated-flipped-anchor','timeline-inspector','compiled-field','track-placement','calibration-save-reload','invalid-calibration','responsive-layout','cancel-absent-coordinate','save-during-drag','anchor-pick','unify-scale-undo','reference-png'],errors},null,2));console.log('Spatial browser regression passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
