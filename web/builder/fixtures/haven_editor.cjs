const fs = require('fs'), vm = require('vm'), assert = require('assert');
const template = fs.readFileSync(process.argv[2], 'utf8');
const nodes = new Map();
const document = {getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, {value: '', checked: false, style: {}, classList: {add() {}, remove() {}}, setAttribute() {}});
    return nodes.get(id);
}};
let dirty = 0, saved;
const context = vm.createContext({document, console, markDirty() {dirty++;}, markClean() {},
    updateTriggersDisplay() {}, renderFixtureList() {}, showTemplatePreview() {}, BuilderDialogs: {confirm: async () => true}, setTimeout() {},
    fetch: async (_url, options) => {saved = JSON.parse(options.body); return {json: async () => ({status: 'success', id: 4, version: 2})};}});
const selection = template.slice(template.indexOf('    function selectRoom(id)'), template.indexOf('    function toggleSection('));
const saving = template.slice(template.indexOf('    async function saveProject()'), template.indexOf('    function updateStatusBanner()'));
const applying = template.slice(template.indexOf('    async function applyTemplate('), template.indexOf('    // Initialize', template.indexOf('    async function applyTemplate(')));
vm.runInContext(`let canEdit = true, selectedRoomId = null, selectedExitId = null, projectId = 4, projectVersion = 1;
let roomTemplates = {haven: {name: 'Haven', v5: {location_type: 'haven', haven_ratings: {security: 3, size: 1}}}};
let mapData = {rooms: {a: {name: 'Haven A', v5: {location_type: 'haven', haven_ratings: {security: 1, custom: 'preserved'}}}, b: {name: 'Haven B', v5: {location_type: 'haven'}}, c: {name: 'No V5'}}};
${selection}
${saving}
${applying}
globalThis.api = {selectRoom, saveProject, applyTemplate, templates: () => roomTemplates, data: () => mapData, readonly: () => {canEdit=false;}, reload: data => {mapData=JSON.parse(JSON.stringify(data));}};`, context);
const api = context.api, get = id => document.getElementById(id);
(async () => {
    get('project-name').value = 'Haven test';
    api.selectRoom('a');
    for (const [key, value] of Object.entries({security: 2, size: 1, luxury: 3, warding: 4})) {
        const input = get('haven-' + key); input.value = String(value);
        assert.equal(typeof input.onchange, 'function', 'Missing Haven ' + key + ' binding');
        input.onchange({target: input});
    }
    const hidden = get('haven-hidden'); hidden.checked = true; hidden.onchange({target: hidden});
    assert.equal(dirty, 5);
    await api.saveProject();
    assert.deepEqual(saved.map_data.rooms.a.v5.haven_ratings, {security: 2, size: 1, luxury: 3, warding: 4, location_hidden: true, custom: 'preserved'});
    api.reload(saved.map_data); api.selectRoom('a');
    assert.equal(get('haven-security').value, 2); assert.equal(hidden.checked, true);
    api.selectRoom('b');
    for (const key of ['security', 'size', 'luxury', 'warding']) assert.equal(get('haven-' + key).value, 0, 'Stale ' + key);
    assert.equal(hidden.checked, false); assert(!api.data().rooms.b.v5.haven_ratings, 'Selection must not mutate data');
    get('haven-security').value = '5'; get('haven-security').onchange({target: get('haven-security')});
    assert.equal(api.data().rooms.b.v5.haven_ratings.security, 5);
    assert.equal(api.data().rooms.a.v5.haven_ratings.security, 2);
    api.selectRoom('c'); get('haven-size').value = '1'; get('haven-size').onchange({target: get('haven-size')});
    assert.equal(api.data().rooms.c.v5.haven_ratings.size, 1);
    api.selectRoom('a'); await api.applyTemplate('haven');
    get('haven-security').value = '5'; get('haven-security').onchange({target: get('haven-security')});
    assert.equal(api.templates().haven.v5.haven_ratings.security, 3, 'Room edit changed template defaults');
    api.selectRoom('b'); await api.applyTemplate('haven');
    assert.equal(get('haven-security').value, 3, 'Second room inherited first room edit');
    get('haven-security').value = '1'; get('haven-security').onchange({target: get('haven-security')});
    assert.equal(api.data().rooms.a.v5.haven_ratings.security, 5, 'Second room edit changed first room');
    assert.equal(api.templates().haven.v5.haven_ratings.security, 3);
    api.readonly(); const before = JSON.stringify(api.data()); get('haven-size').value = '4'; get('haven-size').onchange({target: get('haven-size')});
    assert.equal(JSON.stringify(api.data()), before);
    console.log('Haven edit/save/reload/room-switch contract OK');
})().catch(error => {console.error(error); process.exitCode = 1;});
