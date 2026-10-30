const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.handlers={};this.dataset={};this.disabled=false;this.checked=false;this.textContent='';this.value='';}
  append(...items){this.children.push(...items);}
  appendChild(item){this.append(item);}
  replaceChildren(...items){this.children=items;}
  addEventListener(event,fn){this.handlers[event]=fn;}
  setAttribute(){}
  removeAttribute(){}
  querySelectorAll(selector){const found=[];for(const item of this.children){if(item.tagName==='input'&&(!selector.includes(':checked')||item.checked))found.push(item);found.push(...item.querySelectorAll(selector));}return found;}
}
const elements=new Map();
const calls=[];
const document={getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement(tag){return new Element(tag);}};
const eel={get_runtime_status:()=>async()=>({python_ready:true,ocr_ready:true}),redact_pdf:(...args)=>async()=>{calls.push(args);return{success:true,output_path:'synthetic_output.pdf'};}};
const context=vm.createContext({window:{eel},document,console});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/main.js'),'utf8'),context);
(async()=>{
  await new Promise(setImmediate);
  vm.runInContext('state.filePath="synthetic.pdf";state.analysisReady=true;state.entities=[{text:"Kovács Ágnes",category:"name_or_city",occurrences:2},{text:"123,45 EUR",category:"amount",occurrences:1}];renderEntities(state.entities);setBusy(false)',context);
  const boxes=elements.get('entity-list').querySelectorAll('input[type=checkbox]');
  assert.equal(boxes.length,2);
  assert.equal(boxes.filter(x=>x.checked).length,0);
  assert.equal(elements.get('redact-button').disabled,true);
  boxes[0].checked=true;boxes[0].handlers.change();
  assert.equal(elements.get('redact-button').disabled,false);
  await elements.get('redact-button').handlers.click();
  assert.equal(calls.length,1);
  assert.deepEqual(Array.from(calls[0][1]),['Kovács Ágnes']);
  assert.equal(elements.get('status-message').dataset.state,'success');
  elements.get('custom-entity').value='  kimaradt   személy  ';
  elements.get('add-entity-button').handlers.click();
  const updated=elements.get('entity-list').querySelectorAll('input[type=checkbox]');
  assert.equal(updated.length,3);
  assert.equal(updated[0].checked,true);
  assert.equal(updated[2].value,'kimaradt személy');
  assert.equal(updated[2].checked,false);
  elements.get('custom-entity').value='KIMARADT SZEMÉLY';elements.get('add-entity-button').handlers.click();
  assert.equal(elements.get('entity-list').children.length,3);
  assert.equal(elements.get('status-message').dataset.state,'error');
  updated[2].checked=true;await elements.get('redact-button').handlers.click();
  assert.deepEqual(Array.from(calls[1][1]),['Kovács Ágnes','kimaradt személy']);
  vm.runInContext('setBusy(true)',context);
  assert.equal(elements.get('custom-entity').disabled,true);
  assert.equal(updated.every(x=>x.disabled),true);
  vm.runInContext('setBusy(false);state.analysisReady=false;setBusy(false)',context);
  assert.equal(elements.get('add-entity-button').disabled,true);
  console.log('FRONTEND_PASS 17 checks; actual main.js; DOM and backend MOCKED; actual Eel bridge tested separately');
})().catch(error=>{console.error(error);process.exitCode=1;});
