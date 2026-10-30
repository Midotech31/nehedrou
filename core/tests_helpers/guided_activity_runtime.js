/* Execute the shipped guided controller against the actual server DOM tree.
 * Only the DOM APIs used by that controller are emulated; no implementation copy.
 */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
let active=null,audioStops=0,speechStops=0,reportedValidity=0;
class DOMEvent {
  constructor(type,options={}) {this.type=type;this.bubbles=Boolean(options.bubbles);this.defaultPrevented=false;}
  preventDefault(){this.defaultPrevented=true;}
}
class Element {
  constructor(tree,parent=null) {
    this.tag=tree.tag;this.attrs=tree.attrs||{};this.parentElement=parent;this.handlers={};
    this.children=(tree.children||[]).map(child=>typeof child==='string'?child:new Element(child,this));
    this.dataset={};
    for(const [name,value] of Object.entries(this.attrs)) if(name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=value;
    this.hidden=Object.hasOwn(this.attrs,'hidden');this.checked=Object.hasOwn(this.attrs,'checked');this.customValidity='';
    this.id=this.attrs.id||'';this.name=this.attrs.name||'';this.required=Object.hasOwn(this.attrs,'required');
    if(this.tag==='textarea') this.value=this.textContent.replace(/^\r?\n/,'');
    else if(this.tag==='select') {const options=this.querySelectorAll('option');this.value=(options.find(option=>Object.hasOwn(option.attrs,'selected'))||options[0])?.attrs.value||'';}
    else this.value=this.attrs.value||'';
  }
  get textContent(){return this.children.map(child=>typeof child==='string'?child:child.textContent).join('');}
  set textContent(value){this.children=[String(value)];}
  all(){return this.children.flatMap(child=>typeof child==='string'?[]:[child,...child.all()]);}
  matches(selector){
    if(selector.endsWith(':not([hidden])')) return !this.hidden && this.matches(selector.slice(0,-14));
    if(selector.startsWith('#')) return this.id===selector.slice(1);
    if(selector.startsWith('.')) return (this.attrs.class||'').split(/\s+/).includes(selector.slice(1));
    const match=selector.match(/^([a-z]+)?\[([^=\]]+)(?:=['"]?([^'"\]]+)['"]?)?\]$/);
    if(match) return (!match[1]||this.tag===match[1]) && (match[2]==='hidden'?this.hidden:Object.hasOwn(this.attrs,match[2])) && (match[3]===undefined||this.attrs[match[2]]===match[3]);
    return this.tag===selector;
  }
  querySelectorAll(selector){return this.all().filter(element=>element.matches(selector));}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  closest(selector){return this.matches(selector)?this:this.parentElement?.closest(selector)||null;}
  setAttribute(name,value){this.attrs[name]=String(value);}
  removeAttribute(name){delete this.attrs[name];}
  addEventListener(name,handler){(this.handlers[name]||=[]).push(handler);}
  dispatchEvent(event){event.target||=this;for(const handler of this.handlers[event.type]||[])handler(event);if(event.bubbles&&this.parentElement)this.parentElement.dispatchEvent(event);return !event.defaultPrevented;}
  click(){this.dispatchEvent(new DOMEvent('click'));}
  focus(){active=this;}
  pause(){audioStops++;}
  setCustomValidity(message){this.customValidity=message;}
  get invalid(){return Boolean(this.customValidity)||(this.required&&!this.value)||(this.attrs.maxlength&&this.value.length>Number(this.attrs.maxlength));}
  checkValidity(){return !this.all().some(element=>element.invalid);}
  reportValidity(){reportedValidity++;const first=this.all().find(element=>element.invalid);if(first)first.focus();return !first;}
}
const document=new Element(input.tree);
const form=document.querySelector('[data-guided-activity]');
assert(form,'The actual response needs a guided form');
form.elements={};
for(const element of form.all()) if(element.name)form.elements[element.name]=element;
const window={speechSynthesis:{cancel(){speechStops++;}}};
vm.runInNewContext(fs.readFileSync('static/activity.js','utf8'),{document,window,Event:DOMEvent});
const sections=form.querySelectorAll('[data-activity-step]');
const next=form.querySelector('[data-step-next]'),back=form.querySelector('[data-step-back]');
const pause=form.querySelector('[data-step-pause]'),resume=form.querySelector('[data-step-resume]'),stop=form.querySelector('[data-stop-activity]');
const panel=form.querySelector('[data-pause-panel]'),error=form.querySelector('[data-answer-error]'),group=form.querySelector('#id_answer');
const radios=form.querySelectorAll('input[name=answer]'),counter=document.querySelector('[data-step-counter]');
const at=index=>{assert.strictEqual(sections[index].hidden,false);sections.forEach((section,i)=>assert.strictEqual(section.hidden,i!==index));assert.strictEqual(counter.textContent,`${index+1} / 3`);};
const savedValues=()=>Object.fromEntries(Object.entries(form.elements).filter(([name])=>name!=='answer').map(([name,element])=>[name,element.value]));
if(input.scenario==='missing-choice') {
  next.click();at(1);
  form.elements.parent_report.value='help';form.elements.completion.value='completed';
  next.click();at(1);
  assert.strictEqual(error.hidden,false);assert.strictEqual(group.attrs['aria-invalid'],'true');assert.strictEqual(active,radios[0]);assert(radios[0].customValidity);
  assert.strictEqual(form.elements.parent_report.value,'help');
  radios[1].checked=true;radios[1].dispatchEvent(new DOMEvent('change'));
  next.click();at(2);assert.strictEqual(error.hidden,true);assert.strictEqual(group.attrs['aria-invalid'],undefined);assert.strictEqual(radios[0].customValidity,'');
} else if(input.scenario==='stop-without-choice') {
  next.click();next.click();at(1);assert.strictEqual(error.hidden,false);
  stop.click();at(2);assert.strictEqual(form.elements.completion.value,'stopped');assert(radios.every(radio=>!radio.checked));assert.strictEqual(error.hidden,true);assert.strictEqual(active,form.elements.parent_report);
  form.elements.parent_report.value='help';
  const event=new DOMEvent('submit');form.dispatchEvent(event);assert.strictEqual(event.defaultPrevented,false);
} else if(input.scenario==='pause-resume') {
  next.click();at(1);radios[1].checked=true;
  form.elements.completion.value='completed';form.elements.parent_report.value='difficult';
  if(form.elements.comment)form.elements.comment.value='Fictional feedback retained across pause.';
  if(form.elements.support_used)form.elements.support_used.value='gesture';
  const before=savedValues();const audioBefore=speechStops;
  pause.click();assert(sections.every(section=>section.hidden));assert.strictEqual(panel.hidden,false);assert.strictEqual(active,resume);assert.strictEqual(next.hidden,true);assert.strictEqual(back.hidden,true);assert(speechStops>audioBefore);
  resume.click();at(1);assert.strictEqual(panel.hidden,true);assert.strictEqual(active,sections[1].querySelector('h2'));assert.strictEqual(radios[1].checked,true);assert.deepStrictEqual(savedValues(),before);
  back.click();at(0);next.click();at(1);next.click();at(2);assert.deepStrictEqual(savedValues(),before);assert.strictEqual(radios[1].checked,true);
  pause.click();stop.click();at(2);assert.strictEqual(panel.hidden,true);assert.strictEqual(form.elements.completion.value,'stopped');assert.strictEqual(form.elements.parent_report.value,'difficult');
  if(form.elements.comment)assert.strictEqual(form.elements.comment.value,before.comment);
} else if(input.scenario==='server-answer-error') {
  at(1);assert.strictEqual(error.hidden,false);assert.strictEqual(active,radios[0]);
  for(const [name,value]of Object.entries(input.expected))assert.strictEqual(form.elements[name].value,value,name);
} else if(input.scenario==='server-feedback-error') {
  at(2);assert.strictEqual(error.hidden,true);
  for(const [name,value]of Object.entries(input.expected))assert.strictEqual(form.elements[name].value,value,name);
  assert.strictEqual(radios.find(radio=>radio.value==='b').checked,true);
} else if(input.scenario==='observation') {
  assert.strictEqual(radios.length,0);next.click();at(1);next.click();at(2);
} else throw new Error('Unknown scenario');
console.log(JSON.stringify({scenario:input.scenario,status:'passed',speechStops,audioStops}));
