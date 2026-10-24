const fs = require('fs'), vm = require('vm'), assert = require('assert');
const editor = fs.readFileSync(process.argv[2], 'utf8'), dashboard = fs.readFileSync(process.argv[3], 'utf8');
let dirty = 0;
const listeners = {}, room = {grid_x: 1, grid_y: 2}, element = {style: {left: '20px', top: '40px'}};
const document = {getElementById: () => ({getBoundingClientRect: () => ({})}),
    addEventListener(type, handler) {listeners[type] = handler;}, removeEventListener(type) {delete listeners[type];}};
const drag = editor.slice(editor.indexOf('    function startDrag('), editor.indexOf('    function updateStatusBar()'));
const context = vm.createContext({document, markDirty() {dirty++;}, drawExitLines() {}});
vm.runInContext(`const GRID_SIZE=20; let canEdit=true; let mapData={rooms:{r1:globalThis.room}}; ${drag}`, Object.assign(context, {room}));
function start() {context.startDrag({clientX: 100, clientY: 100}, element, 'r1');}
start(); listeners.mouseup(); assert.equal(dirty, 0, 'Room click dirtied unchanged project');
start(); listeners.mousemove({clientX: 105, clientY: 104}); listeners.mouseup(); assert.equal(dirty, 0, 'Sub-grid motion dirtied project');
start(); listeners.mousemove({clientX: 140, clientY: 120}); listeners.mouseup();
assert.equal(dirty, 1); assert.equal(room.grid_x, 3); assert.equal(room.grid_y, 3);
start(); listeners.mousemove({clientX: 120, clientY: 100}); listeners.mousemove({clientX: 100, clientY: 100}); listeners.mouseup();
assert.equal(dirty, 1, 'Returning to original coordinates dirtied project');

const nodes = new Map();
class Element {
    constructor() {this.value=''; this.children=[];}
    set innerHTML(value) {this.children=[...value.matchAll(/<option value="([^"]*)"/g)].map(x => ({value:x[1]})); this.value=this.children[0]?.value || '';}
    appendChild(option) {this.children.push(option); if(this.children.length===1) this.value=String(option.value);}
}
const doc = {getElementById(id) {if(!nodes.has(id)) nodes.set(id,new Element()); return nodes.get(id);}, createElement: () => new Element()};
let rooms = [{id:14,name:'Archive Foyer'}, {id:2,name:'Limbo'}];
const ctx = vm.createContext({document:doc, bootstrap:{Modal:function(){this.show=()=>{};}}, fetch:async()=>({json:async()=>({status:'success',rooms})})});
const submit = dashboard.slice(dashboard.indexOf('let currentProjectId = null;'), dashboard.indexOf("document.getElementById('confirm-submit').addEventListener"));
const load = dashboard.slice(dashboard.indexOf('async function loadConnectionRooms('), dashboard.indexOf('// The editor\'s "Submit for Review"'));
vm.runInContext(`${submit}\n${load}`, ctx);
(async()=>{
    await ctx.submitProject(3,'Replacement','2','w');
    assert.equal(doc.getElementById('submit-connection-room').value,'2','Stored connection was replaced by first live room');
    assert.equal(doc.getElementById('submit-connection-direction').value,'w');
    await ctx.submitProject(4,'Legacy','','');
    assert.equal(doc.getElementById('submit-connection-room').value,'','Legacy project silently chose first live room');
    assert.equal(doc.getElementById('submit-connection-direction').value,'');
    rooms = [{id:14,name:'Archive Foyer'}];
    await ctx.submitProject(3,'Unavailable prior connection','2','w');
    assert.equal(doc.getElementById('submit-connection-room').value,'','Unavailable connection silently changed');
    assert(dashboard.includes('data-connection-room="{{ project.connection_room_id'));
    assert(dashboard.includes('data-connection-direction="{{ project.connection_direction'));
    console.log('Room selection/drag and stored submit connection contract OK');
})().catch(error=>{console.error(error); process.exitCode=1;});
