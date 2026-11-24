/* Built-in Node browser mock. Synthetic PCM only; no microphone or network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const {File} = require('node:buffer');

class Target {
  constructor() { this.handlers = new Map(); this.attrs = {}; this.childNodes = []; this.hidden = false; this.disabled = false; this._text = ''; }
  addEventListener(name, callback) { const list = this.handlers.get(name) || []; list.push(callback); this.handlers.set(name, list); }
  async fire(name, extra={}) {
    const event = {type:name, defaultPrevented:false, preventDefault(){this.defaultPrevented=true;}, ...extra};
    for (const fn of this.handlers.get(name) || []) await fn(event);
    return event;
  }
  dispatchEvent(event) { for (const fn of this.handlers.get(event.type) || []) fn(event); return true; }
  setAttribute(key,value) { this.attrs[key]=String(value); }
  removeAttribute(key) { delete this.attrs[key]; if (key==='href') this.href=undefined; }
  replaceChildren(...nodes) { this.childNodes=[...nodes];this._text=''; }
  appendChild(node) { this.childNodes.push(node);return node; }
  get textContent() { return this._text+this.childNodes.map(node=>node.textContent).join(''); }
  set textContent(value) { this._text=String(value);this.childNodes=[]; }
  focus() { this.focused=true; }
  pause() {} load() {}
}

function environment({fetchSupported=true}={}) {
  const form = new Target();form.action='https://software.example/en/editorial/upload/?draft=fixture';
  const fields={};
  for (const name of ['file','kind','audio_text','audio_source','audio_variety','csrfmiddlewaretoken','guided_context','draft','audio_side','rights','rights_status']) {
    fields[name]=new Target();fields[name].name=name;fields[name].value='fixture-'+name;
  }
  fields.kind.value='audio';fields.audio_text.value='دار';fields.audio_source.value='';fields.file.files=[];
  Object.defineProperty(fields.file,'value',{get(){return this.files.length?'fakepath':'';},set(value){if(value==='')this.files=[];}});
  fields.namedItem=name=>fields[name]||null;form.elements=fields;
  const recNames=['start','stop','cancel','use','preview','download','progress','status','consent'];
  const rec={};for(const name of recNames)rec[name]=new Target();
  rec.stop.disabled=rec.cancel.disabled=true;rec.preview.hidden=rec.use.hidden=rec.download.hidden=true;
  const retention={status:new Target(),errors:new Target(),result:new Target()};retention.errors.hidden=retention.result.hidden=true;
  const recorderBlock=new Target();recorderBlock.closest=()=>form;
  recorderBlock.querySelector=selector=>rec[selector.match(/data-record-(.*)\]/)[1]];
  recorderBlock.dataset=Object.fromEntries(['unsupported','ready','permission','recording','processing','preview','failed','cancelled','attached','download','consent','empty'].map(k=>[k,k.toUpperCase()]));
  const retentionBlock=new Target();retentionBlock.closest=()=>form;
  retentionBlock.querySelector=selector=>retention[selector.match(/data-retention-(.*)\]/)[1]];
  retentionBlock.dataset=Object.fromEntries(['retained','fallback','saving','invalid','uncertain','conflict','unavailable','saved'].map(k=>[k,k.toUpperCase()]));
  const controls=[...Object.values(fields).filter(x=>x instanceof Target),...Object.values(rec).filter(x=>x instanceof Target)];
  form.querySelectorAll=selector=>selector==='[data-retention-invalid]'?controls.filter(x=>'data-retention-invalid'in x.attrs):controls;
  const document=new Target();document.hidden=false;
  document.querySelector=selector=>selector==='[data-audio-recorder]'?recorderBlock:selector==='[data-record-retention]'?retentionBlock:null;
  document.createElement=()=>new Target();
  const window=new Target();window.isSecureContext=true;window.crypto=crypto.webcrypto;
  window.location={href:form.action,origin:'https://software.example',destinations:[],assign(url){this.destinations.push(url);}};
  const urls=new Map();let serial=0,microphoneCalls=0,trackStops=0;
  class LocalURL extends URL {static createObjectURL(blob){const value='blob:software/'+(++serial);urls.set(value,blob);return value;}static revokeObjectURL(value){urls.delete(value);}}
  class Engine {
    resume(){return Promise.resolve();}close(){return Promise.resolve();}
    decodeAudioData(){const data=Float32Array.from({length:800},(_,i)=>.2*Math.sin(2*Math.PI*220*i/8000));return Promise.resolve({length:800,numberOfChannels:1,duration:.1,sampleRate:8000,getChannelData:()=>data});}
  }
  let latestRecorder;
  class Recorder extends Target {
    static isTypeSupported(){return true;}
    constructor(){super();this.state='inactive';this.mimeType='audio/webm';latestRecorder=this;}
    start(){this.state='recording';}
    stop(){this.state='inactive';this.pending=(async()=>{await this.fire('dataavailable',{data:new Blob(['synthetic codec fixture'])});await this.fire('stop');})();}
  }
  const navigator={mediaDevices:{async getUserMedia(){microphoneCalls++;return{getTracks:()=>[{stop(){trackStops++;}}]};}}};
  window.AudioContext=Engine;window.MediaRecorder=Recorder;
  class Transfer {constructor(){const files=[];this.items={add(file){files.push(file);}};this.files=files;}}
  class FormDataMock {
    constructor(current){this.values=new Map(Object.entries(fields).filter(([,field])=>field instanceof Target).map(([key,field])=>[key,key==='file'?field.files[0]:field.value]));}
    set(key,value){this.values.set(key,value);}get(key){return this.values.get(key);}
  }
  window.FormData=FormDataMock;
  const timeouts=new Map();let timeoutNumber=0;
  window.setTimeout=(fn,delay)=>{const id=++timeoutNumber;timeouts.set(id,{fn,delay});return id;};
  window.clearTimeout=id=>timeouts.delete(id);window.AbortController=AbortController;
  const queue=[],calls=[];
  if(fetchSupported)window.fetch=async(url,options)=>{calls.push({url,options});assert.ok(queue.length,'Every fetch must follow an explicit test action');return await queue.shift()(url,options);};
  const context=vm.createContext({window,document,navigator,Blob,File,DataTransfer:Transfer,FormData:FormDataMock,
    CustomEvent:class{constructor(type,options={}){this.type=type;this.detail=options.detail;}},URL:LocalURL,
    AudioContext:Engine,MediaRecorder:Recorder,ArrayBuffer,DataView,Uint8Array,Float32Array,
    setInterval(){return 1;},clearInterval(){},Date,console});
  for(const name of ['audio-recorder.js','recording-retention.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',name),'utf8'),context,{filename:name});
  const response=(status,data,type='application/json')=>({status,ok:status>=200&&status<300,headers:{get:()=>type},async json(){return data;}});
  async function take(){rec.consent.checked=true;await rec.start.fire('click');await rec.stop.fire('click');await latestRecorder.pending;await rec.use.fire('click');assert.equal(calls.length,0,'Recording/Use must never upload');const file=fields.file.files[0];assert.ok(file);assert.equal(Buffer.from(await file.arrayBuffer()).subarray(0,4).toString(),'RIFF');return file;}
  async function submit(){return form.fire('submit');}
  function add(status,data){queue.push(async()=>response(status,{schema:'nehdrou-recording-upload-v1',...data}));}
  return{form,fields,rec,retention,window,urls,calls,queue,response,take,submit,add,timeouts,
    get microphoneCalls(){return microphoneCalls;},get trackStops(){return trackStops;}};
}

async function main(){
  let checks=0;
  {
    const e=environment();await e.rec.start.fire('click');assert.equal(e.microphoneCalls,0);
    const file=await e.take(),sha=crypto.createHash('sha256').update(Buffer.from(await file.arrayBuffer())).digest('hex');
    e.add(422,{status:'invalid',errors:[{field:'audio_text',label:'Word',messages:['<script>not executable</script>']} ]});
    assert.equal((await e.submit()).defaultPrevented,true);
    assert.equal(e.fields.file.files[0],file);assert.equal(e.urls.size,1);assert.equal(e.rec.preview.hidden,false);
    assert.equal(e.retention.status.textContent,'INVALID');assert.ok(e.retention.errors.textContent.includes('<script>not executable</script>'));
    assert.equal((await e.window.fire('beforeunload')).defaultPrevented,true);
    const first=e.calls[0].options.body;e.fields.audio_text.value='corrected';
    e.add(200,{status:'saved',result_url:'/en/editorial/uploads/receipt/'});await e.submit();
    assert.equal(first.get('upload_attempt'),e.calls[1].options.body.get('upload_attempt'),'422 keeps the unsaved attempt');
    assert.equal(first.get('file'),e.calls[1].options.body.get('file'));
    assert.equal(crypto.createHash('sha256').update(Buffer.from(await file.arrayBuffer())).digest('hex'),sha);
    assert.equal(e.calls[1].options.body.get('csrfmiddlewaretoken'),'fixture-csrfmiddlewaretoken');
    assert.equal(e.calls[1].options.redirect,'manual');assert.equal(e.calls[1].options.credentials,'same-origin');
    assert.equal(e.window.location.destinations.length,1);assert.equal((await e.window.fire('beforeunload')).defaultPrevented,false);
    checks++;
  }
  {
    const e=environment(),file=await e.take();e.add(503,{status:'retry',errors:[]});await e.submit();
    assert.equal(e.fields.file.files[0],file);assert.equal(e.retention.status.textContent,'INVALID');
    e.add(200,{status:'saved',result_url:'/en/editorial/uploads/receipt/'});await e.submit();
    assert.equal(e.calls.length,2);assert.equal(e.calls[0].options.body.get('upload_attempt'),e.calls[1].options.body.get('upload_attempt'));checks++;
  }
  {
    const e=environment(),file=await e.take();e.queue.push(async()=>{throw new Error('lost response');});await e.submit();
    assert.equal(e.retention.status.textContent,'UNCERTAIN');assert.equal(e.calls.length,1);
    e.queue.push(async()=>e.response(302,{},'text/html'));await e.submit();
    assert.equal(e.retention.status.textContent,'UNCERTAIN');assert.equal(e.fields.file.files[0],file);assert.equal(e.window.location.destinations.length,0);
    e.add(200,{status:'saved',replayed:true,result_url:'/en/editorial/uploads/same-receipt/'});await e.submit();
    assert.ok(e.calls.every(call=>call.options.body.get('upload_attempt')===e.calls[0].options.body.get('upload_attempt')));checks++;
  }
  {
    const e=environment();await e.take();let resolve;e.queue.push(()=>new Promise(done=>{resolve=done;}));
    const first=e.submit();await Promise.resolve();assert.equal((await e.submit()).defaultPrevented,true);assert.equal(e.calls.length,1);
    resolve(e.response(200,{schema:'nehdrou-recording-upload-v1',status:'saved',result_url:'/en/editorial/uploads/receipt/'}));await first;checks++;
  }
  {
    const e=environment(),file=await e.take();e.queue.push(()=>new Promise(()=>{}));
    const pending=e.submit();await Promise.resolve();
    const deadline=[...e.timeouts.values()][0];assert.equal(deadline.delay,60000);deadline.fn();await pending;
    assert.equal(e.retention.status.textContent,'UNCERTAIN');assert.equal(e.fields.file.disabled,false);
    assert.equal(e.fields.file.files[0],file);assert.equal(e.calls[0].options.signal.aborted,true);
    e.add(200,{status:'saved',replayed:true,result_url:'/en/editorial/uploads/receipt/'});await e.submit();
    assert.equal(e.calls[0].options.body.get('upload_attempt'),e.calls[1].options.body.get('upload_attempt'));checks++;
  }
  {
    const e=environment();await e.take();e.add(200,{status:'saved',result_url:'https://foreign.example/receipt/'});await e.submit();
    assert.equal(e.window.location.destinations.length,0);assert.equal(e.retention.status.textContent,'UNCERTAIN');
    e.add(409,{status:'conflict',result_url:'/en/editorial/uploads/own-receipt/'});await e.submit();
    assert.equal(e.retention.status.textContent,'CONFLICT');assert.equal(e.retention.result.hidden,false);
    assert.equal(e.window.location.destinations.length,0);assert.equal((await e.window.fire('beforeunload')).defaultPrevented,true);checks++;
  }
  {
    const e=environment(),file=await e.take();e.add(409,{status:'unavailable',result_url:'/en/editorial/uploads/own-receipt/'});await e.submit();
    assert.equal(e.retention.status.textContent,'UNAVAILABLE');assert.equal(e.fields.file.files[0],file);
    assert.equal(e.window.location.destinations.length,0);assert.equal((await e.window.fire('beforeunload')).defaultPrevented,true);checks++;
  }
  {
    const e=environment();await e.take();e.add(422,{status:'invalid',errors:[]});await e.submit();const old=e.calls[0].options.body.get('upload_attempt');
    await e.rec.start.fire('click');await e.rec.stop.fire('click');
    await new Promise(done=>setImmediate(done));await e.rec.use.fire('click');
    e.add(422,{status:'invalid',errors:[]});await e.submit();assert.notEqual(e.calls[1].options.body.get('upload_attempt'),old,'replacement clears the previous attempt');checks++;
  }
  {
    const e=environment();await e.take();const imported=new File(['manual fixture'],'manual.wav',{type:'audio/wav'});
    e.fields.file.files=[imported];await e.fields.file.fire('change');
    assert.equal((await e.submit()).defaultPrevented,false);assert.equal(e.calls.length,0);assert.equal(e.fields.file.files[0],imported);checks++;
  }
  {
    const e=environment({fetchSupported:false});await e.take();assert.equal(e.retention.status.textContent,'FALLBACK');
    assert.equal((await e.submit()).defaultPrevented,false);checks++;
  }
  {
    const e=environment();await e.take();await e.rec.cancel.fire('click');
    assert.equal(e.fields.file.files.length,0);assert.equal(e.urls.size,0);assert.equal((await e.window.fire('beforeunload')).defaultPrevented,false);checks++;
  }
  console.log(JSON.stringify({checks,passed:checks,real_microphone:false,network:false,synthetic_wav:true,
    verified:['422 retains exact WAV','explicit storage retry','uncertain response uses same attempt','double submit blocked','60-second bounded wait','same-origin result only','unavailable receipt never confirms','replacement resets key','manual import unchanged','normal fallback','cancel clears local take']}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
