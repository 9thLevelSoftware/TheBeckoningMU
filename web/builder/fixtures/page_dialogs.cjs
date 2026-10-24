const assert = require('assert'), fs = require('fs'), vm = require('vm');
const createDialogs = require(process.argv[2]);
const nodes = new Map();
const document = {activeElement: null, modal: null, getElementById: id => nodes.get(id), querySelector() { return this.modal; }};
class Element {
    constructor(id) { this.id = id; this.listeners = {}; this.isConnected = true; this.value = ''; this.hidden = false; }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    dispatch(type) { const event = {preventDefault() {this.prevented = true;}}; this.listeners[type]?.(event); return event; }
    appendChild(child) { child.parentNode = this; }
    focus() { if (!this.disabled) document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatch('close'); }
    set innerHTML(_value) { throw Error('Dialog must never render HTML'); }
}
for (const id of ['page-dialog', 'page-dialog-form', 'page-dialog-message', 'page-dialog-title', 'page-dialog-input',
                  'page-dialog-input-group', 'page-dialog-cancel', 'page-dialog-continue', 'page-feedback']) nodes.set(id, new Element(id));
const get = id => nodes.get('page-dialog' + id), parent = new Element('body'), trigger = new Element('trigger');
parent.appendChild(get('')); parent.appendChild(nodes.get('page-feedback')); trigger.focus();
const dialogs = createDialogs(document);
(async () => {
    const malicious = '<img src=x onerror=attack()> & "';
    let result = dialogs.confirm(malicious);
    assert.equal(get('-message').textContent, malicious); assert.equal(get('-cancel'), document.activeElement);
    assert.equal(await dialogs.confirm('Other operation'), false); // cannot cross-confirm
    assert.equal(get('-message').textContent, malicious);
    get('-cancel').dispatch('click'); assert.equal(await result, false); assert.equal(document.activeElement, trigger);
    trigger.disabled = true;
    document.activeElement = parent; // browsers may blur a disabled trigger
    result = (async () => { const accepted = await dialogs.confirm('Busy caller', trigger); trigger.disabled = false; return accepted; })();
    get('-cancel').dispatch('click'); assert.equal(await result, false); assert.equal(document.activeElement, trigger);
    result = dialogs.confirm('Proceed?'); get('-form').dispatch('submit'); assert.equal(await result, true);
    result = dialogs.prompt('Reason?'); assert.equal(document.activeElement, get('-input')); assert(get('-input').required);
    get('-input').value = '   '; get('-form').dispatch('submit'); assert(get('').open);
    get('-input').value = malicious; get('-form').dispatch('submit'); assert.equal(await result, malicious);
    result = dialogs.prompt('Cancel reason'); assert.equal(await dialogs.prompt('Concurrent reason'), null);
    assert(get('').dispatch('cancel').prevented); assert.equal(await result, null); assert.equal(document.activeElement, trigger);
    result = dialogs.confirm('Escape'); get('').dispatch('cancel'); assert.equal(await result, false);
    result = dialogs.confirm('Next operation'); get('').dispatch('close'); assert(get('').open); // delayed previous event
    let stopped = false;
    get('').listeners.keydown({key: 'Escape', stopPropagation() {stopped = true;}}); assert(stopped);
    get('-cancel').dispatch('click'); assert.equal(await result, false);
    const modal = new Element('bootstrap-modal'); document.modal = modal;
    result = dialogs.confirm('Nested'); assert.equal(get('').parentNode, modal);
    get('-cancel').dispatch('click'); await result; assert.equal(get('').parentNode, parent);
    dialogs.alert(malicious); assert.equal(nodes.get('page-feedback').textContent, malicious); assert(!nodes.get('page-feedback').hidden);
    assert.equal(nodes.get('page-feedback').parentNode, modal);
    // Exercise production async editor deletion, including stale target and
    // read-only changes occurring while its dialog is open.
    const template = fs.readFileSync(process.argv[3], 'utf8');
    const source = template.slice(template.indexOf('    async function deleteSelectedExit()'), template.indexOf('    function startDrag('));
    let resolveDialog, draws = 0;
    const context = vm.createContext({document: {getElementById: () => ({style: {}})},
        BuilderDialogs: {confirm: () => new Promise(resolve => {resolveDialog = resolve;})},
        drawExitLines() {draws++;}, updateStatusBar() {}, markDirty() {}});
    vm.runInContext(`let canEdit = true, selectedExitId = 'a'; let mapData = {exits: {a: {}, b: {}}};
        ${source}
        globalThis.api = {remove: deleteSelectedExit, data: () => mapData, select: id => {selectedExitId=id;}, readonly: () => {canEdit=false;}};`, context);
    let pending = context.api.remove(); resolveDialog(false); await pending; assert(context.api.data().exits.a);
    pending = context.api.remove(); context.api.select('b'); resolveDialog(true); await pending;
    assert(context.api.data().exits.a); assert(context.api.data().exits.b); assert.equal(draws, 0);
    pending = context.api.remove(); resolveDialog(true); await pending; assert(!context.api.data().exits.b); assert.equal(draws, 1);
    context.api.select('a'); pending = context.api.remove(); context.api.readonly(); resolveDialog(true); await pending;
    assert(context.api.data().exits.a); assert.equal(draws, 1);
    // Every affected template uses the helper; preserve JS syntax after Django
    // substitutions, including async inline handlers.
    for (const path of process.argv.slice(3)) {
        const text = fs.readFileSync(path, 'utf8');
        assert(!/(?<![\w.])(alert|confirm|prompt)\(/.test(text), path);
        for (const match of text.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
            let script = match[1].replace(/\{\{[\s\S]*?\}\}/g, 'null').replace(/\{%[\s\S]*?%\}/g, '');
            if (script.trim()) new vm.Script(script, {filename: path});
        }
    }
    console.log('page dialogs and async continuation contract OK');
})().catch(error => {console.error(error); process.exitCode = 1;});
