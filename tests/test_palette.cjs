// Exercise the palette against a fake Fusion transport; no browser or account.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor() { this.style={}; this.scrollHeight=20; this.children=[]; this.textContent=''; this.value=''; this.hidden=false; this.classList={add(){},remove(){}}; }
  append(...els){ for(const el of els){el.parentElement=this;this.children.push(el);} }
  replaceChildren(...els){this.children=[];this.append(...els);}
  get firstChild(){return this.children[0];} get lastChild(){return this.children.at(-1);}
  setAttribute(name,value){this[name]=value;}
  focus(){} click(){}
}
const els = new Map(); const calls=[];
const context = {
  console, Map, Promise, JSON, Array, Error,
  setTimeout(){},
  document:{getElementById(id){if(!els.has(id))els.set(id,new Element());return els.get(id);},createElement(){return new Element();},querySelectorAll(){return [];},addEventListener(){},body:new Element()},
  window:{getComputedStyle(){return {lineHeight:'20px'};},addEventListener(){},adsk:{async fusionSendData(action,data){calls.push({action,data:JSON.parse(data)});return JSON.stringify(action==='poll'?{events:[]}:{ok:true});}}}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('fusion_addin/CadBot/palette/chat.js','utf8'),context);
const run = code=>vm.runInContext(code,context);
(async()=>{
  await Promise.resolve();
  run("event({kind:'ready',signed_in:true})");
  assert.equal(els.get('send').disabled,false);
  run("event({kind:'models',models:[{id:'test-model',name:'Test Model',default:true}]})");
  assert.equal(els.get('model').value,'test-model');
  els.get('input').value='Make a bracket';
  await run('send()');
  assert.equal(calls.find(x=>x.action==='send').data.text,'Make a bracket');
  assert.equal(calls.find(x=>x.action==='send').data.model,'test-model');
  assert.equal(els.get('model').disabled,true);
  assert.equal(els.get('send').disabled,false);
  assert.equal(els.get('send').textContent,'■');
  run("event({kind:'delta',id:'a',text:'Hello '});event({kind:'delta',id:'a',text:'world'});");
  assert.equal(run("messages.get('a').textContent"),'Hello world');
  run("event({kind:'message',id:'a',text:'Hello world!'});");
  assert.equal(run('messages.size'),1);
  run("event({kind:'tool',id:'t',phase:'started',item:{tool:'extrude',arguments:{distance_mm:20},status:'inProgress'}})");
  run("event({kind:'tool',id:'t',phase:'completed',item:{tool:'extrude',status:'failed',error:{message:'No sketch'}}})");
  assert.equal(run('tools.size'),1);
  assert.match(run("tools.get('t').firstChild.textContent"),/✕ extrude/);
  assert.match(run("tools.get('t').lastChild.textContent"),/No sketch/);
  run("event({kind:'tool',id:'cli',phase:'started',item:{tool:'fusion',arguments:{command:'fusion bodies list'},status:'inProgress'}})");
  run("event({kind:'tool',id:'cli',phase:'completed',item:{tool:'fusion',status:'completed'}})");
  assert.match(run("tools.get('cli').firstChild.textContent"),/fusion bodies list/);
  await els.get('send').onclick();
  assert.ok(calls.some(x=>x.action==='cancel'));
  run("event({kind:'idle'})");
  assert.equal(els.get('send').disabled,false);
  run("event({kind:'user',id:'checkpoint-one',text:'First edit'})");
  assert.equal(run('restoreButtons.length'),3);
  assert.equal(run('restoreButtons[0].disabled'),true);
  assert.equal(run('restoreButtons[1].disabled'),false);
  assert.match(run('restoreReasons[0].element.textContent'), /Design undo unavailable/);
  run("event({kind:'checkpoints',available:['checkpoint-one'],reason:null})");
  assert.equal(run('restoreButtons[0].disabled'),false);
  assert.equal(run('restoreReasons[0].element.hidden'),true);
  await run('restoreButtons[2].onclick()');
  assert.deepEqual(calls.find(x=>x.action==='restore').data,{id:'checkpoint-one',mode:'both'});
  assert.equal(els.get('send').disabled,true);
  run("event({kind:'idle'})");
  run("event({kind:'disconnected'})");
  assert.equal(els.get('send').disabled,true);
  run("event({kind:'reset'})");
  assert.equal(run('messages.size'),0);
  console.log('PASS: send, streaming, tool updates/errors, cancellation, disconnection, new chat');
})().catch(err=>{console.error(err);process.exitCode=1;});
