const fs = require('fs'), vm = require('vm'), assert = require('assert');
const input = JSON.parse(fs.readFileSync(0, 'utf8')), schemas = input.actions;
const nodes = new Map();
class Element {
    constructor() { this.value = ''; this.style = {}; this.dataset = {}; this.children = []; }
    set innerHTML(value) {
        this.children = []; this.value = '';
        for (const match of value.matchAll(/id="([^"]+)"/g)) {
            const child = new Element(); child.id = match[1]; nodes.set(child.id, child); this.append(child);
        }
    }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); }
    add(child) { this.append(child); if (child.selected) this.value = child.value; }
    replaceChildren() { this.children = []; }
    querySelector(selector) {
        if (selector.startsWith('#')) return nodes.get(selector.slice(1));
        return this.children.find(x => x.id && x.id.endsWith('_type'));
    }
    querySelectorAll() {
        const all = this.children.flatMap(x => [x, ...(x.querySelectorAll ? x.querySelectorAll() : [])]);
        return all.filter(x => x.dataset && x.dataset.param);
    }
}
const document = {
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); },
    createElement() { return new Element(); },
    querySelectorAll(selector) { return selector === '.action-param' ? document.getElementById('action-parameters').children.filter(x => x.dataset.param) : document.getElementById('conditions-container').children; }
};
Element.prototype.getAttribute = function(name) { return this.dataset[name.replace('data-', '')]; };
const context = vm.createContext({document, console, Option: function(text, value, defaultSelected, selected) { this.value = value; this.selected = selected; },
    bootstrap: {Modal: Object.assign(function() { this.show = () => {}; }, {getInstance: () => ({hide() {}})})},
    BuilderDialogs: {confirm: async () => true, alert: message => { throw Error(message); }}, markDirty() {}, markClean() {},
    setTimeout() {}, fetch: async () => ({json: async () => input.saveResponses.shift()}), updateTriggersDisplay() {}});
const template = fs.readFileSync(process.argv[2], 'utf8');
const source = template.slice(template.indexOf('    let actionParameters'), template.indexOf('    // Initialize trigger metadata'));
vm.runInContext(`let selectedRoomId = 'r1', editingTriggerId = null;
let mapData = {rooms: {r1: {triggers: []}}}, canEdit = true, projectId = 1, projectVersion = 1;
let triggerMetadata = {actions: ${JSON.stringify(Object.fromEntries(Object.entries(schemas).map(([k,v]) => [k,{parameters:v}])) )}, conditions: {test: {parameters: {amount: {type: 'number'}}}, character_clan: {parameters: {clan: {type: 'select', options: ['brujah']}}}}};
${source}
${template.slice(template.indexOf('    async function saveProject()'), template.indexOf('    function updateStatusBanner()'))}
globalThis.api = {addTrigger, editTrigger, saveTrigger, deleteTrigger, onTriggerActionChange, saveProject,
 editable: value => {canEdit = value;},
 data: () => mapData, reload: () => {mapData = JSON.parse(JSON.stringify(mapData));}};`, context);
const api = context.api, get = id => document.getElementById(id);
function field(key, value) { const input = get('action-parameters').children.find(x => x.dataset.param === key); assert(input, key); input.value = value; }
(async () => {
    api.addTrigger(); assert.equal(get('btn-delete-trigger').style.display, 'none');
    get('trigger-action').value = 'send_message'; api.onTriggerActionChange(); field('message', '<cold>'); await api.saveTrigger();
    api.reload(); const id = api.data().rooms.r1.triggers[0].id;
    api.data().rooms.r1.triggers[0].conditions = [{type: 'test', parameters: {amount: 2, future: true}}];
    api.editTrigger(id); assert.equal(get('btn-delete-trigger').style.display, '');
    const row = get('conditions-container').children[0];
    row.querySelectorAll('.condition-param')[0].value = '3';
    await api.saveTrigger(); assert.equal(api.data().rooms.r1.triggers[0].parameters.message, '<cold>');
    assert.equal(api.data().rooms.r1.triggers[0].conditions[0].parameters.amount, 3);
    assert.equal(api.data().rooms.r1.triggers[0].conditions[0].parameters.future, true);
    api.data().rooms.r1.triggers[0].conditions = [{type: 'character_clan', parameters: {clan: 'thin_blood'}}];
    api.editTrigger(id); field('message', 'Changed message'); await api.saveTrigger(); api.reload();
    assert.equal(api.data().rooms.r1.triggers[0].conditions[0].parameters.clan, 'thin_blood');
    get('trigger-action').value = 'emit_message'; api.onTriggerActionChange(); await api.saveTrigger();
    assert.equal(api.data().rooms.r1.triggers[0].parameters.message, 'Changed message');
    for (const value of [true, 42.5, null, 'text']) {
        api.editTrigger(id); get('trigger-action').value = 'set_attribute'; api.onTriggerActionChange();
        field('attr_name', 'trigger_flag_test'); field('value', JSON.stringify(value)); await api.saveTrigger();
        api.reload(); api.editTrigger(id); await api.saveTrigger();
        assert.equal(JSON.stringify(api.data().rooms.r1.triggers[0].parameters.value), JSON.stringify(value));
        assert(!('message' in api.data().rooms.r1.triggers[0].parameters));
    }
    api.data().rooms.r1.triggers[0].parameters.future = true;
    api.editTrigger(id); await api.saveTrigger(); assert.equal(api.data().rooms.r1.triggers[0].parameters.future, true);
    const retained = JSON.stringify(api.data());
    await api.saveProject(); assert(get('save-status').textContent.includes('message')); assert.equal(JSON.stringify(api.data()), retained);
    await api.saveProject(); assert(get('save-status').textContent.includes('Unknown parameters')); assert.equal(JSON.stringify(api.data()), retained);
    api.data().rooms.r1.triggers.push({id: 'other'}); await api.deleteTrigger();
    assert.equal(JSON.stringify(api.data().rooms.r1.triggers), '[{"id":"other"}]');
    api.editable(false);
    const readOnlyData = JSON.stringify(api.data()), oldId = get('trigger-id').value;
    api.addTrigger(); api.editTrigger('other'); await api.saveTrigger(); await api.deleteTrigger();
    assert.equal(JSON.stringify(api.data()), readOnlyData); assert.equal(get('trigger-id').value, oldId);
    console.log('modal contract OK');
})().catch(error => {console.error(error); process.exitCode = 1;});
