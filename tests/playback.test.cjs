/* Offline regression tests for actual production playback/library functions. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
function playback() {
  const handlers = {}, revoked = [], messages = [];
  const play = { urls: ['chunk0','chunk1','chunk2'], index: 0, active: true, total: 3, waiting: false, spans: [], chunkRatios: [] };
  const preview = { hidden: true, appendChild() {} };
  const player = { src:'chunk0', duration:10, currentTime:9, pause(){}, play:async()=>{}, addEventListener:(type, fn)=>handlers[type]=fn };
  const context = vm.createContext({ play, player, preview, karaokeEnabled:true, isFinite,
    document:{createElement:()=>({classList:{toggle(){},add(){}},dataset:{},scrollIntoView(){}})},
    say:(...args)=>messages.push(args), URL:{revokeObjectURL:url=>revoked.push(url)},
    currentRun:null, lastText:'old transcript', truncatedEl:{hidden:false}, result:{hidden:true},
    toggleText:{setAttribute(){}}, setDownload:(...args)=>context.download=args, setShare:id=>context.share=id,
  });
  vm.runInContext(section('  function renderChunks(', '  toggleText.onclick =') + '\n' +
    section('  function playSavedAudio(', '  // ---------------------------------------------------------------- Histórico'), context);
  context.renderChunks(['one','two','three']);
  return { context, handlers, play, player, revoked, messages };
}
test('streaming timeupdate cannot change queue index or skip next chunk', () => {
  const h=playback(); h.handlers.timeupdate(); assert.equal(h.play.index,0);
  h.handlers.ended(); assert.equal(h.player.src,'chunk1'); assert.equal(h.play.index,1);
});
test('clicking transcript while streaming selects correct chunk, not relative seek', () => {
  const h=playback(); h.play.spans[2].onclick(); assert.equal(h.player.src,'chunk2'); assert.equal(h.play.index,2);
});
test('last streamed chunk exposes full M4B for replay once download exists', () => {
  const h=playback(); h.play.index=2; h.play.finalUrl='blob:full-m4b'; h.handlers.ended();
  assert.equal(h.play.active,false); assert.equal(h.player.src,'blob:full-m4b');
});
test('saved library audio resets stale transcript, share, download and stream state', () => {
  const h=playback(); h.play.finalUrl='blob:old'; h.play.waiting=true;
  assert.equal(h.context.playSavedAudio({url:'/library/new/audio',filename:'new.m4b'}),true);
  assert.equal(h.play.active,false); assert.equal(h.play.waiting,false); assert.equal(h.play.urls.length,0);
  assert.equal(h.context.lastText,''); assert.equal(h.context.share,null);
  assert.deepEqual(h.context.download,['/library/new/audio','new.m4b']);
  assert.equal(h.context.preview.hidden,true); assert.deepEqual(h.revoked,['blob:old']);
  h.handlers.ended(); assert.equal(h.player.src,'/library/new/audio');
});
test('saved playback cannot hijack active generation', () => {
  const h=playback(); h.context.currentRun={};
  assert.equal(h.context.playSavedAudio({url:'/other',filename:'other.mp3'}),false);
  assert.equal(h.player.src,'chunk0'); assert.equal(h.messages.length,1);
});
test('unsupported saved audio reports useful download fallback', async () => {
  const h=playback(); h.player.play=async()=>{throw Error('unsupported')};
  h.context.playSavedAudio({url:'/book',filename:'book.m4b'}); await Promise.resolve();
  assert.match(h.messages[0][0], /Baixar/);
});
function library(api) {
  const cards=[], playButton={dataset:{url:'/saved/audio',filename:'saved.m4b'}}, deleteButton={dataset:{uuid:'saved-id'}};
  const libraryList={innerHTML:'',appendChild:card=>cards.push(card),querySelectorAll:cls=>cls==='.play-doc'?[playButton]:[deleteButton]};
  const alerts=[], context=vm.createContext({libraryList, libraryCount:{},libraryModal:{hidden:false},
    api, document:{createElement:()=>({})}, Date, String, encodeURIComponent,
    confirm:()=>true,alert:message=>alerts.push(message),playSavedAudio:()=>true});
  vm.runInContext(section('  function escapeHtml(', '  if (libraryBtn && libraryModal)'),context);
  return {context,cards,playButton,deleteButton,alerts};
}
test('library errors are reported, not mistaken for disabled persistence',async()=>{
  const h=library(async()=>{throw Error('Erro HTTP 401.')}); await h.context.loadLibrary();
  assert.match(h.context.libraryList.innerHTML,/401/);
});
test('library escapes metadata and surfaces failed deletion with retry enabled',async()=>{
  const h=library(async(path,opts)=>opts ? {json:async()=>({success:false})} : {json:async()=>({enabled:true,documents:[
    {title:'Title',audio_url:'/audio?x=" onmouseover="bad',job_uuid:'saved-id',format:'m4b',created_at:'2026-01-01'}]})});
  await h.context.loadLibrary(); assert.match(h.cards[0].innerHTML,/&quot;/);
  assert.doesNotMatch(h.cards[0].innerHTML,/x=" onmouseover="bad/);
  await h.deleteButton.onclick(); assert.match(h.alerts[0],/não confirmou/); assert.equal(h.deleteButton.disabled,false);
});
test('advertised format capabilities disable unsupported M4B',async()=>{
  const formatEl={value:'m4b', options:[{value:'mp3'},{value:'m4b'},{value:'wav'}]};
  const context=vm.createContext({formatEl,waitToPoll:async()=>{},readResponse:async()=>({formats:['wav']}),renderVoices(){},localStorage:{getItem(){}},langEl:{},Array});
  vm.runInContext(section('  async function loadVoices()', '  checkHealth();'),context);
  await context.loadVoices(); assert.equal(formatEl.value,'wav'); assert.equal(formatEl.options[1].disabled,true);
});
