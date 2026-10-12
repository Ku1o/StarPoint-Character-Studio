'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/audio-workbench.js'),'utf8');
function harness(project={assets:{},voices:[],sounds:[]}){
  const nodes=new Map(),sections=new Map(),calls=[],undo=[];
  const element=()=>({value:'',checked:false,dataset:{},textContent:'',innerHTML:'',selectedOptions:[],close(){this.closed=true;},insertAdjacentHTML(_,html){this.html=(this.html||'')+html;}});
  const node=key=>{if(!nodes.has(key))nodes.set(key,element());return nodes.get(key);};
  node('#modal');node('#content');
  const context={structuredClone,console,S:{p:structuredClone(project),dirty:false,generation:0,undo},clone:structuredClone,
    esc:value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
    $:selector=>nodes.get(selector)||null,$$:selector=>selector==='[data-audio-profile]'?[...nodes.values()].filter(value=>value.dataset.audioProfile):[],
    snapshot(){undo.push(structuredClone(context.S.p));},mutate(fn){context.snapshot();fn();context.S.dirty=true;},
    async saveNow(){},async busy(_,fn){return fn();},toast(){},assetUrl:id=>'/asset/'+id,
    modal(html){context.lastModal=html;for(const match of html.matchAll(/id="([^"]+)"/g))node('#'+match[1]);},
    async api(endpoint,data){calls.push({endpoint,data:structuredClone(data)});return context.respond(endpoint,data);},
    render(){context.rendered=true;},respond(){throw Error('Unexpected API');}
  };
  vm.createContext(context);vm.runInContext(source,context);
  vm.runInContext('renderVoices=()=>{};',context);
  for(const voice of project.voices||[]){
    const section=element(),children=new Map();
    section.querySelector=selector=>{if(!children.has(selector))children.set(selector,element());return children.get(selector);};
    nodes.set('[data-audio-name="'+voice.id+'"]',{closest:()=>section});sections.set(voice.id,section);
  }
  return {context,nodes,node,sections,calls,undo};
}
const values={targetLufs:'-23',truePeakCeilingDbtp:'-2',toleranceLu:'1',paddingToleranceSeconds:'0.08'};
test('numeric author settings preserve unknown fields and the other audio kind',()=>{
  const {context:c}=harness(),prior={producer:{note:'keep'},voice:{unknown:{offset:[1,2]}},sfx:{targetLufs:-18,custom:true}};
  const result=c.audioProfileUpdate(prior,'voice',values,['named-reference']);
  assert.deepEqual(JSON.parse(JSON.stringify(result)),{producer:{note:'keep'},voice:{unknown:{offset:[1,2]},targetLufs:-23,truePeakCeilingDbtp:-2,toleranceLu:1,paddingToleranceSeconds:.08,referenceAssetIds:['named-reference']},sfx:{targetLufs:-18,custom:true}});
  assert.deepEqual(prior.voice,{unknown:{offset:[1,2]}});
  assert.equal(c.audioProfileUpdate(undefined,'voice',{...values,targetLufs:'',truePeakCeilingDbtp:''},[]).voice.targetLufs,null);
});
test('invalid profile shapes, finite ranges and excess references cannot be repaired silently',()=>{
  const {context:c}=harness();
  for(const prior of [null,[],false,'bad',{voice:null},{voice:[]},{voice:true}])assert.throws(()=>c.audioProfileUpdate(prior,'voice',values,[]));
  for(const [key,bad] of [['targetLufs','Infinity'],['targetLufs','1'],['targetLufs','-71'],['truePeakCeilingDbtp','-31'],['toleranceLu',''],['toleranceLu','21'],['paddingToleranceSeconds','1.01'],['targetLufs',true]])assert.throws(()=>c.audioProfileUpdate({},'voice',{...values,[key]:bad},[]));
  assert.throws(()=>c.audioProfileUpdate({},'voice',values,Array.from({length:31},(_,i)=>String(i))));
  assert.throws(()=>c.audioProfileUpdate({},'voice',values,[true]));
  assert.throws(()=>c.audioProfileUpdate({},'music',values,[]));
});
test('named reference selection saves through the unchanged API and enables undo',async()=>{
  const h=harness({id:'p',assets:{},voices:[],sounds:[],audioProfile:{voice:{custom:'keep'},sfx:{custom:'other-kind'}}}),c=h.context;
  h.node('#audio-review-open');h.node('#audio-profile-save');h.node('#undo').disabled=true;h.node('#redo');
  for(const [key,value] of Object.entries(values)){const input=h.node('#test-'+key);input.dataset.audioProfile=key;input.value=value;}
  h.node('#audio-profile-references').selectedOptions=[{value:'chosen-by-name'}];
  c.respond=(endpoint,data)=>{assert.equal(endpoint,'/api/save');return data;};
  c.bindAudioUpgrade();await h.node('#audio-profile-save').onclick();
  assert.equal(c.S.p.audioProfile.voice.referenceAssetIds[0],'chosen-by-name');assert.equal(c.S.p.audioProfile.voice.custom,'keep');assert.equal(c.S.p.audioProfile.sfx.custom,'other-kind');
  assert.equal(h.undo.at(-1).audioProfile.voice.targetLufs,undefined);assert.equal(h.node('#undo').disabled,false);assert.equal(c.S.dirty,false);
});
test('silent and absent measurements stay pending; author report is escaped readable text',()=>{
  const {context:c}=harness();
  const empty=c.audioMeasureMarkup({integratedLufs:null,truePeakDbtp:null,clippedSamples:0,fullDecode:true,measurementChannels:1});
  assert.match(empty,/待测/);assert.doesNotMatch(empty,/0\.00 LUFS/);
  const report=c.audioReportMarkup({rows:[{name:'<script>bad</script>',status:'handoff_only',original:{integratedLufs:-23},pathStatus:'needs_native_registration'}]});
  assert.match(report,/&lt;script&gt;/);assert.match(report,/封装待核/);assert.match(report,/待登记核验/);assert.doesNotMatch(report,/<pre|<script>/);
});
test('full acquisition draft uses retained source or author brief without changing it',()=>{
  const {context:c}=harness();
  const project={productionBrief:{voices:[{id:'acquisition',textJapanese:'完整台词\n最后一句。'}]}};
  assert.equal(c.entryOriginalText({productionId:'acquisition'},project),'完整台词\n最后一句。');
  assert.equal(c.entryOriginalText({text:'voice full draft'},project),'voice full draft');
  assert.equal(c.entryOriginalText({text:'new',entryLayout:{original:'retained'}},project),'retained');
  assert.equal(c.entryOriginalText({text:'new',entryLayout:{original:''}},project),'');
  assert.equal(project.productionBrief.voices[0].textJapanese,'完整台词\n最后一句。');
});
test('word deletions, replacements and line breaks are readable and escaped',()=>{
  const {context:c}=harness();
  const result=c.entryChangesMarkup([{operation:'delete',original:'完整\n',candidate:''},{operation:'replace',original:'<old>',candidate:'新 字'},{operation:'insert',original:'',candidate:'末句'}]);
  assert.match(result,/删除/);assert.match(result,/替换/);assert.match(result,/增加/);assert.match(result,/［换行］/);assert.match(result,/［空格］/);assert.match(result,/&lt;old&gt;/);assert.doesNotMatch(result,/originalRange|<old>/);
});
test('candidate generation keeps original binding until explicit apply and has undo snapshots',async()=>{
  const project={id:'project',revision:3,assets:{original:{id:'original',name:'原录音.wav',mime:'audio/wav'}},voices:[{id:'voice',asset:'original',text:'完整原文',usage:'join',entry:'ally'}],sounds:[],productionBrief:{voices:[]}},h=harness(project),c=h.context;
  h.node('#audio-review-open');h.node('#audio-profile-save');
  c.respond=(endpoint,data)=>{assert.equal(endpoint,'/api/audio-candidate');assert.equal(data.asset,'original');const next=structuredClone(c.S.p);next.revision++;next.assets.candidate={id:'candidate',name:'候选.mp3',mime:'audio/mpeg'};return {project:next,candidate:{originalAsset:'original',candidateAsset:'candidate',before:{integratedLufs:-30},postEncodeDecode:{integratedLufs:-23,truePeakDbtp:-3,clippedSamples:0},durationDeltaSeconds:.02,profile:{targetLufs:-23,truePeakCeilingDbtp:-2,toleranceLu:1,paddingToleranceSeconds:.08}}};};
  c.bindAudioUpgrade();await h.sections.get('voice').querySelector('[data-audio-candidate]').onclick();
  assert.equal(c.S.p.voices[0].asset,'original');assert.match(c.lastModal,/候选尚未应用/);assert.match(c.lastModal,/\/asset\/original/);assert.match(c.lastModal,/\/asset\/candidate/);assert.match(c.lastModal,/封装仍待核/);
  h.node('#candidate-apply').onclick();assert.equal(c.S.p.voices[0].asset,'candidate');assert.equal(c.S.p.voices[0].candidateOf,'original');assert.equal(c.S.p.voiceDeclarations[0].asset,'candidate');
  assert.equal(h.undo.at(-1).voices[0].asset,'original');assert.ok(c.S.p.assets.original);
});
test('missing full draft offers assistance and cannot become a completed layout',()=>{
  const h=harness({voices:[{id:'v',text:'',usage:'join'}],assets:{},sounds:[]});h.context.openEntryLayout(h.context.S.p.voices[0]);
  assert.match(h.context.lastModal,/全文尚未提供/);assert.match(h.context.lastModal,/作者填写包/);assert.equal(h.nodes.has('#entry-layout-save'),false);assert.equal(h.context.S.p.voices[0].entryLayout,undefined);
});
test('editing candidate clears approval and saves only candidate with unknown fields intact',async()=>{
  const h=harness({voices:[{id:'v',text:'完整原文\n末句',usage:'join',entry:'ally',entryLayout:{original:'完整原文\n末句',candidate:'完整原文末句',authorConfirmed:true,custom:'retain'}}],assets:{},sounds:[]}),c=h.context;
  c.respond=()=>({originalCharacters:8,candidateCharacters:7,lineCount:1,overflow:false,wordingChanged:false,lines:['完整原文末句'],changes:[{operation:'delete',original:'\n',candidate:''}]});
  c.openEntryLayout(c.S.p.voices[0]);h.node('#entry-candidate').value='完整原文末句';h.node('#entry-author-confirmed').checked=true;
  h.node('#entry-candidate').value='原文末句';h.node('#entry-candidate').oninput();assert.equal(h.node('#entry-author-confirmed').checked,false);
  h.node('#entry-layout-save').onclick();assert.equal(c.S.p.voices[0].text,'完整原文\n末句');assert.equal(c.S.p.voices[0].entryLayout.original,'完整原文\n末句');assert.equal(c.S.p.voices[0].entryLayout.custom,'retain');assert.equal(c.S.p.voices[0].entryLayout.candidate,'原文末句');assert.equal(c.S.p.voices[0].entryLayout.authorConfirmed,false);
});

function declarationProject(){
  return {id:'project',revision:3,assets:{original:{id:'original',name:'原录音.mp3',mime:'audio/mpeg'},replacement:{id:'replacement',name:'新录音.mp3',mime:'audio/mpeg'}},
    voices:[{id:'voice',productionId:'acquisition',asset:'original',name:'获取录音',text:'旧声音表台词',usage:'home',entry:'home'}],sounds:[],
    voiceDeclarations:[{asset:'original',file:'原录音.mp3',text:'已确认的完整台词',usage:'join',entry:'ally',reused:true,unknown:{offset:[1,2]}}],
    productionBrief:{voices:[{id:'acquisition',label:'获取语音',assetId:'original',textJapanese:'旧制作包台词',entry:'home'}],sounds:[]}};
}
function loadBindingIntegration(h){
  h.context.uid=()=> 'new-voice';
  for(const file of ['author-declarations.js','production-brief.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/'+file),'utf8'),h.context);
  return h.context;
}
for(const entry of ['pbBindAssets','pbAudioRecord'])test(entry+' migrates asset/file-only declarations without replacing the confirmed explanation',()=>{
  const h=harness(declarationProject()),c=loadBindingIntegration(h),declaration=c.S.p.voiceDeclarations[0];
  if(entry==='pbBindAssets')c.pbBindAssets('voices.0',['replacement']);
  else {c.S.p.productionBrief.voices[0].assetId='replacement';c.pbAudioRecord('voices.0');}
  assert.equal(c.S.p.voiceDeclarations.length,1);assert.equal(c.S.p.voiceDeclarations[0],declaration);
  assert.equal(declaration.asset,'replacement');assert.equal(declaration.file,'新录音.mp3');assert.equal(declaration.reused,true);
  assert.deepEqual(JSON.parse(JSON.stringify(declaration.unknown)),{offset:[1,2]});
  for(const key of ['text','usage','entry'])assert.equal(c.S.p.voices[0][key],declaration[key]);
  assert.equal(declaration.text,'已确认的完整台词');assert.equal(declaration.usage,'join');assert.equal(declaration.entry,'ally');
  assert.equal(c.S.p.productionBrief.voices[0].textJapanese,declaration.text);assert.equal(c.S.p.productionBrief.voices[0].entry,'ally');
  assert.ok(c.S.p.assets.original);
});
test('production form edits and clears exactly the chosen voice field while retaining the declaration and recording',()=>{
  const h=harness(declarationProject()),c=loadBindingIntegration(h),declaration=c.S.p.voiceDeclarations[0];
  const text={dataset:{pbPath:'voices.0.textJapanese'},value:'作者修改后的全文'},entry={dataset:{pbPath:'voices.0.entry'},value:'battle'};
  c.$$=selector=>selector==='[data-pb-path]'?[text,entry]:[];
  for(const id of ['#production-export','#production-download','#production-project','#production-run-check'])h.node(id);
  c.pbRefreshFeedback=()=>{};c.bindProductionBrief();
  text.onchange();assert.equal(declaration.text,'作者修改后的全文');assert.equal(declaration.entry,'ally');assert.equal(declaration.usage,'join');
  text.value='';text.onchange();assert.equal(declaration.text,'');assert.equal(c.S.p.voices[0].text,'');assert.equal(c.S.p.productionBrief.voices[0].textJapanese,'');
  entry.onchange();assert.equal(declaration.entry,'battle');assert.equal(declaration.text,'');assert.equal(c.S.p.voices[0].entry,'battle');
  entry.value='';entry.onchange();assert.equal(declaration.entry,'');assert.equal(c.S.p.voices[0].entry,'');assert.equal(declaration.reused,true);
  assert.equal(c.S.p.voiceDeclarations.length,1);assert.equal(c.S.p.voiceDeclarations[0],declaration);assert.equal(declaration.asset,'original');
  assert.deepEqual(JSON.parse(JSON.stringify(declaration.unknown)),{offset:[1,2]});
});
test('production binding creates a voice from the authored brief and keeps sound-only notes when changing recordings',()=>{
  const project=declarationProject();project.voices=[];project.voiceDeclarations=[];project.productionBrief.voices[0].textJapanese='首次提供的全文';project.productionBrief.voices[0].entry='ally';
  project.sounds=[{id:'sound',productionId:'skill_sfx',asset:'original',text:'既有音效说明',usage:'skill_sfx',custom:'preserve'}];
  project.productionBrief.sounds=[{id:'skill_sfx',label:'技能音效',assetId:'original',textJapanese:'旧制作包说明'}];
  const h=harness(project),c=loadBindingIntegration(h);c.pbBindAssets('voices.0',['replacement']);
  assert.equal(c.S.p.voices.length,1);assert.equal(c.S.p.voices[0].text,'首次提供的全文');assert.equal(c.S.p.voices[0].entry,'ally');assert.equal(c.S.p.voiceDeclarations[0].text,'首次提供的全文');
  c.pbBindAssets('sounds.0',['replacement']);assert.equal(c.S.p.sounds[0].text,'既有音效说明');assert.equal(c.S.p.sounds[0].custom,'preserve');assert.equal(c.S.p.voiceDeclarations.length,1);
});
test('candidate apply migrates an asset/file-only declaration and preserves its confirmed script',async()=>{
  const h=harness(declarationProject()),c=loadBindingIntegration(h),declaration=c.S.p.voiceDeclarations[0];
  h.node('#audio-review-open');h.node('#audio-profile-save');
  c.respond=(endpoint,data)=>{assert.equal(endpoint,'/api/audio-candidate');assert.equal(data.asset,'original');const next=structuredClone(c.S.p);next.revision++;return {project:next,candidate:{originalAsset:'original',candidateAsset:'replacement',before:{integratedLufs:-30},postEncodeDecode:{integratedLufs:-23,truePeakDbtp:-3,clippedSamples:0},durationDeltaSeconds:.02,profile:{targetLufs:-23,truePeakCeilingDbtp:-2,toleranceLu:1,paddingToleranceSeconds:.08}}};};
  c.bindAudioUpgrade();await h.sections.get('voice').querySelector('[data-audio-candidate]').onclick();
  assert.equal(c.S.p.voices[0].asset,'original');assert.equal(c.S.p.voiceDeclarations[0].asset,'original');
  h.node('#candidate-apply').onclick();const d=c.S.p.voiceDeclarations[0];
  assert.equal(c.S.p.voiceDeclarations.length,1);assert.equal(d.asset,'replacement');assert.equal(d.file,'新录音.mp3');assert.equal(d.text,declaration.text);assert.equal(d.entry,'ally');assert.equal(d.usage,'join');assert.equal(d.reused,true);
  assert.deepEqual(JSON.parse(JSON.stringify(d.unknown)),{offset:[1,2]});assert.equal(c.S.p.productionBrief.voices[0].assetId,'replacement');assert.equal(h.undo.at(-1).voices[0].asset,'original');
});

test('normal brief import changes the existing recording without replacing confirmed text or entry',()=>{
  const h=harness(declarationProject()),c=loadBindingIntegration(h),declaration=c.S.p.voiceDeclarations[0];
  c.upload=(category,callback,accept)=>{assert.equal(category,'voice');assert.equal(accept,'audio/wav,audio/mpeg,audio/ogg');callback(['replacement']);};
  c.importBriefAudio('voices','acquisition');
  assert.equal(c.S.p.voiceDeclarations.length,1);assert.equal(c.S.p.voiceDeclarations[0],declaration);assert.equal(declaration.asset,'replacement');assert.equal(declaration.file,'新录音.mp3');
  assert.equal(declaration.text,'已确认的完整台词');assert.equal(declaration.entry,'ally');assert.equal(declaration.usage,'join');assert.equal(declaration.reused,true);assert.deepEqual(JSON.parse(JSON.stringify(declaration.unknown)),{offset:[1,2]});
  assert.equal(c.S.p.voices[0].text,declaration.text);assert.equal(c.S.p.voices[0].entry,declaration.entry);assert.equal(c.S.p.productionBrief.voices[0].textJapanese,declaration.text);assert.equal(c.S.p.productionBrief.voices[0].assetId,'replacement');assert.equal(c.S.p.productionBrief.voices[0].status,'provided');assert.ok(c.S.p.assets.original);
});
test('first normal brief import uses the authored script and creates one corresponding declaration',()=>{
  const project=declarationProject();project.voices=[];project.voiceDeclarations=[];project.productionBrief.voices[0].textJapanese='作者提供的完整原文';project.productionBrief.voices[0].entry='ally';
  const h=harness(project),c=loadBindingIntegration(h);c.upload=(_,callback)=>callback(['replacement']);c.importBriefAudio('voices','acquisition');
  assert.equal(c.S.p.voices.length,1);assert.equal(c.S.p.voices[0].asset,'replacement');assert.equal(c.S.p.voices[0].text,'作者提供的完整原文');assert.equal(c.S.p.voices[0].usage,'join');assert.equal(c.S.p.voices[0].entry,'ally');
  assert.equal(c.S.p.voiceDeclarations.length,1);assert.equal(c.S.p.voiceDeclarations[0].text,'作者提供的完整原文');assert.equal(c.S.p.voiceDeclarations[0].asset,'replacement');assert.equal(c.S.p.voiceDeclarations[0].entry,'ally');
});
