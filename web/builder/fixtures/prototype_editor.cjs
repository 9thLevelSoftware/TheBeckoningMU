// Exercise the production fixture controls; their output crosses an actual server save/reload.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const start = html.indexOf('// Fixture editor start');
const end = html.indexOf('// Fixture editor end');
assert(start >= 0 && end > start, 'production fixture editor functions must exist');
const inputs = {};
for (const id of ['fixture-catalog', 'room-fixtures', 'fixture-name', 'fixture-description', 'fixture-feedback']) {
    inputs[id] = {value: '', disabled: false, textContent: '', options: [], add(option) {this.options.push(option)}, replaceChildren() {this.options=[]}};
}
const context = vm.createContext({document: {getElementById: id => inputs[id]},
    Option: function(text, value) {this.text=text;this.value=value}, alert: msg => {throw Error(msg)},
    canEdit: true, selectedRoomId: 'r1', mapData: {rooms: {r1: {name:'Hall'}}, exits: {}, objects: {}}, markDirty: () => {}});
vm.runInContext(html.slice(start, end), context);
inputs['fixture-catalog'].value = 'wooden_chair@1';
inputs['fixture-name'].value = 'Review chair';
inputs['fixture-description'].value = 'Carved backrest.';
vm.runInContext('placeFixture()', context);
assert.equal(context.mapData.objects.f1.prototype_id, 'wooden_chair');
inputs['room-fixtures'].value = 'f1';
inputs['fixture-name'].value = 'Edited chair';
vm.runInContext('updateFixture()', context);
assert.equal(context.mapData.objects.f1.name, 'Edited chair');
inputs['fixture-catalog'].value = 'wooden_table@1';
vm.runInContext('placeFixture()', context);
inputs['room-fixtures'].value = 'f2';
vm.runInContext('deleteFixture()', context);
assert(!context.mapData.objects.f2);
context.canEdit = false;
vm.runInContext('placeFixture(); deleteFixture(); updateFixture()', context);
assert.equal(Object.keys(context.mapData.objects).length, 1, 'readonly guards preserve the map');
process.stdout.write(JSON.stringify(context.mapData));
