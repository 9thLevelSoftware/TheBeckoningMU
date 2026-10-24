const fs = require('fs'), vm = require('vm'), assert = require('assert');
const template = fs.readFileSync(process.argv[2], 'utf8');
const calls = [], nodes = new Map();
class Element {
    constructor() {
        this.style = {}; this.children = []; this.attributes = {}; this.listeners = {};
        const classes = new Set();
        this.classList = {contains: name => classes.has(name), add: name => classes.add(name), remove: name => classes.delete(name)};
    }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(type, callback) { this.listeners[type] = callback; }
    appendChild(child) { this.children.push(child); }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    querySelector() { return this.icon; }
    key(key, repeat = false) {
        const event = {key, repeat, prevented: false, preventDefault() { this.prevented = true; }};
        this.listeners.keydown?.(event); return event;
    }
}
const document = {createElement: () => new Element(), getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id);
}};
const context = vm.createContext({document, console, calls,
    selectRoom: id => calls.push(['select', id]), startDrag: () => calls.push(['drag']),
    handleExitClick: id => calls.push(['exit', id]), editTrigger: id => calls.push(['trigger', id])});
const section = (start, end) => template.slice(template.indexOf(start), template.indexOf(end));
vm.runInContext(`let currentMode = 'select', canEdit = true; const GRID_SIZE = 20;
${section('    function activateOnKey(', '    function selectRoom(')}
${section('    function toggleSection(', '    function setMode(')}
${section('    function updateTriggersDisplay(', '    async function loadPrototypes(')}
globalThis.api = {createRoomElement, updateTriggersDisplay, toggleSection,
 mode(value) {currentMode = value;}, editable(value) {canEdit = value;}};`, context);
const api = context.api;
assert.equal(typeof api.createRoomElement, 'function');
api.createRoomElement('r1', {name: '<Hall>', grid_x: 2, grid_y: 3});
const room = document.getElementById('map-canvas').children[0];
assert.equal(room.tabIndex, 0); assert.equal(room.attributes.role, 'button');
assert(room.attributes['aria-label'].includes('<Hall>'));
for (const key of ['Enter', ' ']) {
    const event = room.key(key); assert(event.prevented); assert.deepEqual(calls.pop(), ['select', 'r1']);
}
room.key('ArrowRight'); room.key('Enter', true); assert.equal(calls.length, 0);
api.mode('exit'); room.key('Enter'); assert.deepEqual(calls.pop(), ['exit', 'r1']);
api.editable(false); room.key(' '); assert.equal(calls.length, 0);
api.mode('select'); room.key(' '); assert.deepEqual(calls.pop(), ['select', 'r1']);
room.listeners.mousedown({}); assert.deepEqual(calls.pop(), ['select', 'r1']); assert.equal(calls.length, 0);
api.editable(true); room.listeners.mousedown({}); assert.deepEqual(calls.splice(0), [['select', 'r1'], ['drag']]);

api.updateTriggersDisplay([{id: 't1', type: 'entry', action: '<message>'}]);
const row = document.getElementById('triggers-list').children[0];
assert.equal(row.tabIndex, 0); assert.equal(row.attributes.role, 'button');
for (const key of ['Enter', ' ']) {assert(row.key(key).prevented); assert.deepEqual(calls.pop(), ['trigger', 't1']);}
row.listeners.click(); assert.deepEqual(calls.pop(), ['trigger', 't1']);
api.editable(false); row.key('Enter'); row.listeners.click(); assert.equal(calls.length, 0);
api.updateTriggersDisplay([{id: 't1', type: 'entry'}]);
const disabled = document.getElementById('triggers-list').children[0];
assert.equal(disabled.attributes['aria-disabled'], 'true'); assert.equal(disabled.tabIndex, -1);

const headers = [...template.matchAll(/<div class="prop-section-header"[^\n]*>/g)].map(match => match[0]);
assert.equal(headers.length, 6);
for (const header of headers) {
    for (const attr of ['role="button"', 'tabindex="0"', 'aria-expanded="true"', 'onkeydown="activateOnKey(event, () => toggleSection(this))"']) assert(header.includes(attr), attr);
}
const header = new Element(), content = new Element(); header.nextElementSibling = content; header.icon = new Element();
header.addEventListener('keydown', event => context.activateOnKey(event, () => api.toggleSection(header)));
header.key('Enter'); assert(content.classList.contains('collapsed')); assert.equal(header.attributes['aria-expanded'], 'false');
header.key(' '); assert(!content.classList.contains('collapsed')); assert.equal(header.attributes['aria-expanded'], 'true');
assert.equal(header.icon.textContent, '-');
console.log('builder keyboard contract OK');
