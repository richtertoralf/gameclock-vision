// Run with node tools/test_segment_ui.cjs (no browser or npm dependencies).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: id === 'editMode' ? 'segment' : '', checked: false,
    handlers: {}, addEventListener(n, cb) { this.handlers[n] = cb; },
    setAttribute() {}, focus(options) { this.focusOptions = options; }, setPointerCapture() {},
    getBoundingClientRect() { return {left:0,top:0,width:672,height:232}; }
  });
  return elements.get(id);
}
const images = [];
class MockImage { constructor() { images.push(this); } }
const context = vm.createContext({
  Image: MockImage, images,
  document: {getElementById:element}, window: {addEventListener() {}},
  setTimeout() { return 1; }, setInterval() {}, clearTimeout() {}, assert,
});
const html = fs.readFileSync(path.join(__dirname,'../tafeluhr/static/index.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(script.slice(0,script.indexOf('loadConfig().then(')),context);
vm.runInContext(`
  cfg = {debug_size:[672,232], segment_rects:Array.from({length:28},(_,i)=>[20+i*2,30,25+i*2,45]), segment_overrides:null, quad:[[0,0],[100,0],[100,100],[0,100]]};
  const original = cfg.segment_rects.map(r=>[...r]), quad = JSON.stringify(cfg.quad);
  const event = (x,y,resize=false) => ({clientX:x,clientY:y,pointerId:1,preventDefault(){},target:{dataset:resize?{resize:'1'}:{},closest(){return {dataset:{i:'8'}};}}});
  segmentSvg.handlers.pointerdown(event(40,35));
  segmentSvg.handlers.pointermove(event(47,39));
  segmentSvg.handlers.pointerup();
  assert.equal(JSON.stringify(cfg.segment_rects[8]),JSON.stringify([43,34,48,49]));
  assert.equal(cfg.segment_overrides.filter(Boolean).length,1);
  assert.equal(JSON.stringify(cfg.segment_rects[7]),JSON.stringify(original[7]));
  assert.equal(JSON.stringify(cfg.quad),quad);
  segmentSvg.handlers.pointerdown(event(48,49,true));
  segmentSvg.handlers.pointermove(event(58,59));
  segmentSvg.handlers.pointerup();
  assert.equal(JSON.stringify(cfg.segment_rects[8]),JSON.stringify([43,34,58,59]));
  $('editMode').value='digit';
  const beforeGroup = cfg.segment_rects.map(r=>[...r]);
  segmentSvg.handlers.pointerdown(event(45,36));
  segmentSvg.handlers.pointermove(event(50,40));
  segmentSvg.handlers.pointerup();
  for(let i=7;i<14;i++) assert.equal(cfg.segment_rects[i][0],beforeGroup[i][0]+5);
  assert.equal(JSON.stringify(cfg.segment_rects[14]),JSON.stringify(original[14]));
  segmentSvg.handlers.keydown({key:'ArrowLeft',shiftKey:true,preventDefault(){}});
  assert.equal(cfg.segment_rects[8][0],beforeGroup[8][0]);
  const beforeCancel=JSON.stringify(cfg.segment_rects);
  segmentSvg.handlers.pointerdown(event(45,36));
  segmentSvg.handlers.pointermove(event(60,40));
  segmentSvg.handlers.pointercancel();
  assert.equal(JSON.stringify(cfg.segment_rects),beforeCancel);
  moveSegments(cfg.segment_rects.map(r=>[...r]),segmentIndices(8),9999,9999);
  for(const i of segmentIndices(8)) {
    assert.ok(cfg.segment_rects[i][2]<=672); assert.ok(cfg.segment_rects[i][3]<=232);
  }
`,context);
console.log('OK: segment drag, resize, group move, keyboard, cancel, bounds; outer frame unchanged');
vm.runInContext(`
  cfg.segment_rects=original.map(r=>[...r]); cfg.segment_overrides=null;
  cfg.quad=[[40,25],[620,15],[580,210],[60,200]];
  view={x:0,y:0,w:672,h:232};
  const fixedQuad=JSON.stringify(cfg.quad);
  for (const [j,p] of [[16,16],[656,16],[656,216],[16,216]].entries()) {
    const actual=normToImage(p);
    assert.ok(Math.abs(actual[0]-cfg.quad[j][0])<1e-8);
    assert.ok(Math.abs(actual[1]-cfg.quad[j][1])<1e-8);
  }
  for (const p of [[30,40],[150,80],[600,190]]) {
    const actual=imageToNorm(normToImage(p));
    assert.ok(Math.abs(actual[0]-p[0])<1e-8);
    assert.ok(Math.abs(actual[1]-p[1])<1e-8);
  }
  const upperEvent = (p) => ({clientX:p[0],clientY:p[1],pointerId:1,preventDefault(){},target:{closest(){return {dataset:{digit:'2'}};}}});
  ov.handlers.pointerdown(upperEvent(normToImage([60,40])));
  ov.handlers.pointermove(upperEvent(normToImage([72,46])));
  ov.handlers.pointerup();
  for(let i=14;i<21;i++) {
    assert.equal(cfg.segment_rects[i][0],original[i][0]+12);
    assert.equal(cfg.segment_rects[i][1],original[i][1]+6);
  }
  assert.equal(JSON.stringify(cfg.segment_rects[0]),JSON.stringify(original[0]));
  assert.equal(JSON.stringify(cfg.quad),fixedQuad);
  assert.equal(cfg.segment_overrides.filter(Boolean).length,7);
  const savedUpper=JSON.stringify(cfg.segment_rects);
  ov.handlers.pointerdown(upperEvent(normToImage([72,46])));
  ov.handlers.pointermove(upperEvent(normToImage([80,48])));
  ov.handlers.pointercancel();
  assert.equal(JSON.stringify(cfg.segment_rects),savedUpper);
  assert.ok(ov.innerHTML.includes('data-digit="2"'));
`,context);
console.log('OK: yellow digit drag, saved fields, cancel, projective mapping; outer quad unchanged');

vm.runInContext(`
  assert.equal(segmentSvg.focusOptions.preventScroll,true);
  refreshDebug(); const oldDebug=images.at(-1);
  refreshDebug(); const newDebug=images.at(-1);
  assert.ok(newDebug.src.includes('plain=true'));
  newDebug.src='new-debug'; newDebug.onload();
  oldDebug.src='old-debug'; oldDebug.onload();
  assert.equal($('debug').src,'new-debug');
  refreshDebug(); const duringDrag=images.at(-1);
  imageEpoch++; duringDrag.onload();
  assert.equal($('debug').src,'new-debug');
  refreshDebug(); const duringPause=images.at(-1);
  $('pause').checked=true; duringPause.onload();
  assert.equal($('debug').src,'new-debug'); $('pause').checked=false;
  frameSize=[1920,1080]; zoomMode=false;
  const previousView=JSON.stringify(view);
  refreshSnap(); const oldSnap=images.at(-1);
  assert.equal(JSON.stringify(view),previousView);
  zoomMode=true; refreshSnap(); const newSnap=images.at(-1);
  newSnap.onload(); const acceptedView=JSON.stringify(view), acceptedSrc=snap.src;
  oldSnap.onload();
  assert.equal(JSON.stringify(view),acceptedView); assert.equal(snap.src,acceptedSrc);
`,context);
console.log('OK: no focus scroll, clean background, late images rejected, crop and snapshot synchronized');
