// Dependency-free DOM/VM integration checks for the canonical chargen script.
// Run: node --test tests/js/chargen.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const script = fs.readFileSync(path.join(root, 'web/static/chargen/codex-chargen.js'), 'utf8');
const template = fs.readFileSync(path.join(root, 'web/templates/character_creation.html'), 'utf8');
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const decode = value => value.replaceAll('&quot;', '"').replaceAll('&#39;', "'").replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&');

// Only the DOM surface used by chargen is implemented. The actual HTML template
// supplies static fields; script-generated rows use the same parser and handlers.
class Element {
    constructor(tag = 'div', attributes = {}) {
        this.tagName = tag.toUpperCase();
        this.attributes = attributes;
        this.children = [];
        this.parentElement = null;
        this.dataset = {};
        this.style = {};
        this.listeners = {};
        this.id = attributes.id || '';
        this.className = attributes.class || '';
        this.value = attributes.value || '';
        this.checked = false;
        this.disabled = false;
        for (const [key, value] of Object.entries(attributes)) {
            if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
        }
        this.classList = {
            contains: value => this.className.split(/\s+/).includes(value),
            add: (...values) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...values])].join(' '); },
            remove: value => { this.className = this.className.split(/\s+/).filter(item => item !== value).join(' '); },
            toggle: (value, on) => {
                on ??= !this.classList.contains(value);
                if (on) this.classList.add(value); else this.classList.remove(value);
            }
        };
    }
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
    insertBefore(child, before) {
        child.parentElement = this;
        const index = this.children.indexOf(before);
        this.children.splice(index < 0 ? this.children.length : index, 0, child);
    }
    remove() { this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
    get firstChild() { return this.children[0] || null; }
    get options() { return this.children.filter(child => child.tagName === 'OPTION'); }
    addEventListener(type, listener) { (this.listeners[type] ??= []).push(listener); }
    dispatchEvent(event) { return Promise.all((this.listeners[event.type] || []).map(listener => listener.call(this, event))); }
    scrollTo() {}
    set textContent(value) { this.children = []; this._html = escape(value); }
    get textContent() { return decode((this._html || '').replace(/<[^>]*>/g, '')); }
    get innerHTML() { return this._html || ''; }
    set innerHTML(html) {
        this._html = html;
        this.children = [];
        const stack = [this];
        for (const token of html.matchAll(/<!--[\s\S]*?-->|<\/?([\w-]+)\b([^>]*)>/g)) {
            if (!token[1]) continue;
            const tag = token[1].toLowerCase();
            if (token[0].startsWith('</')) {
                while (stack.length > 1) { if (stack.pop().tagName.toLowerCase() === tag) break; }
                continue;
            }
            const attributes = {};
            for (const attribute of token[2].matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
                attributes[attribute[1]] = decode(attribute[2] ?? attribute[3] ?? attribute[4] ?? '');
            }
            const child = stack.at(-1).appendChild(new Element(tag, attributes));
            if (!['input', 'img', 'br', 'hr', 'meta', 'link'].includes(tag)) stack.push(child);
        }
    }
    querySelectorAll(selector) {
        const elements = [];
        const visit = node => { for (const child of node.children) { elements.push(child); visit(child); } };
        visit(this);
        return elements.filter(element => selector.split(',').some(choice => {
            const parts = choice.trim().match(/(?:[^\s"']|"[^"]*"|'[^']*')+/g);
            let node = element;
            for (let index = parts.length - 1; index >= 0; index--) {
                if (index === parts.length - 1) { if (!matches(node, parts[index])) return false; }
                else {
                    do { node = node.parentElement; } while (node && !matches(node, parts[index]));
                    if (!node) return false;
                }
            }
            return true;
        }));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function matches(element, selector) {
    const tag = selector.match(/^[\w-]+/);
    if (tag && element.tagName !== tag[0].toUpperCase()) return false;
    const id = selector.match(/#([\w-]+)/);
    if (id && element.id !== id[1]) return false;
    for (const item of selector.matchAll(/\.([\w-]+)/g)) if (!element.classList.contains(item[1])) return false;
    for (const item of selector.matchAll(/\[([\w-]+)="([^"]*)"\]/g)) {
        if (element.attributes[item[1]] !== item[2]) return false;
    }
    return true;
}

function exportedCharacter(predator = 'Potence') {
    return {
        full_name: 'Rejected Kindred', concept: 'Investigator', clan: 'Brujah', sire: 'A sire', generation: 13,
        predator_type: predator === 'Potence' ? 'Alleycat' : 'Farmer', predator_discipline: predator,
        ambition: 'Learn the truth', desire: 'Find a lead', background: 'PRIVATE_BIO_DO_NOT_LOG',
        attributes: { strength: 4, dexterity: 3, stamina: 3, charisma: 3, manipulation: 3, composure: 2, intelligence: 2, wits: 2, resolve: 2 },
        skills: { athletics: 5, brawl: 4, craft: 4, animal_ken: 4, etiquette: 5, academics: 5 },
        disciplines: predator === 'Potence' ? { Potence: 3, Celerity: 1 } : { Potence: 2, Celerity: 1, Animalism: 1 },
        advantages: { Contacts: { value: 3, instance: 'Police' }, 'Special Merit': { value: 4, specialty: 'Research' } },
        flaws: { Enemy: { value: 1, instance: 'Old rival' }, 'Prey Exclusion': { value: 1, specialty: 'Children' } }
    };
}

function harness(character, { editId = 42, metadataGate = Promise.resolve(), failMetadata = false, failEdit = false } = {}) {
    const document = new Element('document');
    document.innerHTML = template.replace(/<script\b[\s\S]*?<\/script>/g, '');
    document.getElementById = id => document.querySelectorAll('*').find(element => element.id === id) || null;
    document.createElement = tag => new Element(tag);
    const requests = [], alerts = [], logs = [], removedDrafts = [], drafts = new Map();
    const metadata = {
        disciplines: ['Celerity', 'Potence', 'Presence', 'Animalism'].map(name => ({ name })),
        advantages: [{ name: 'Contacts', is_instanced: true }, { name: 'Special Merit', has_specialties: true }],
        flaws: [{ name: 'Enemy', is_instanced: true }, { name: 'Prey Exclusion', has_specialties: true }]
    };
    const context = vm.createContext({
        document, CSRF_TOKEN: 'local-csrf-fixture', editCharacterId: editId,
        window: { scrollTo() {}, location: { href: '' } },
        localStorage: {
            getItem(key) { return drafts.get(key) || null; },
            setItem(key, value) { drafts.set(key, value); },
            removeItem(key) { removedDrafts.push(key); drafts.delete(key); }
        },
        Event: class { constructor(type) { this.type = type; } preventDefault() {} },
        setInterval() {}, setTimeout() {}, confirm() { return true; }, alert(value) { alerts.push(value); },
        bootstrap: { Toast: class { show() {} } },
        console: Object.fromEntries(['log', 'warn', 'error'].map(level => [level, (...values) => logs.push([level, ...values])])),
        async fetch(url, options = {}) {
            requests.push({ url, options });
            if (url.startsWith('/api/traits/?')) {
                await metadataGate;
                return { ok: !failMetadata, json: async () => ({ traits: metadata[url.split('=')[1]] }) };
            }
            if (url.endsWith('/for-edit/')) {
                return { ok: !failEdit, json: async () => failEdit ? { error: 'Access denied' } : ({ character_data: character, rejection_notes: 'Please revise.', rejection_count: 1 }) };
            }
            assert.equal(options.method, 'POST');
            return { ok: true, json: async () => ({ character_id: editId || 99 }) };
        }
    });
    vm.runInContext(script, context, { filename: 'codex-chargen.js' });
    return {
        context, document, requests, alerts, logs, removedDrafts, drafts,
        initialize: () => document.dispatchEvent(new context.Event('DOMContentLoaded')),
        submit: () => document.getElementById('character-form').dispatchEvent(new context.Event('submit')),
        posts: () => requests.filter(request => request.options.method === 'POST')
    };
}

function assertRestored(app, original) {
    const field = id => app.document.getElementById(id);
    assert.equal(field('submit-button').disabled, false, field('error-list-items').innerHTML);
    for (const prefix of ['attr', 'skill']) {
        assert.deepEqual(['primary', 'secondary', 'tertiary'].map(level => field(prefix + '-priority-' + level).value), ['physical', 'social', 'mental']);
    }
    for (const [prefix, category] of [['advantage', 'advantages'], ['flaw', 'flaws']]) {
        for (const [name, details] of Object.entries(original[category])) {
            const data = Array.isArray(details) ? details[0] : details;
            for (const key of ['instance', 'specialty']) if (data[key]) assert.equal(field(prefix + '-' + key + '-' + name.replace(/\s+/g, '_')).value, data[key]);
        }
    }
    const radio = app.document.querySelector('input[name="predator-disc"][value="' + original.predator_discipline + '"]');
    assert.equal(radio.checked, true);
}

for (const predator of ['Potence', 'Animalism']) {
    test(`edit resubmit preserves ${predator} predator bonus, priorities and structured details`, async () => {
        const original = exportedCharacter(predator);
        if (predator === 'Animalism') { original.skills['Animal Ken'] = original.skills.animal_ken; delete original.skills.animal_ken; }
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        const app = harness(original, { metadataGate: gate });
        const ready = app.initialize();
        assert.equal(app.requests.filter(request => request.url.endsWith('/for-edit/')).length, 0);
        release();
        await ready;
        assertRestored(app, original);
        // Details changed by the player survive a subsequent real section render.
        const instance = app.document.getElementById('advantage-instance-Contacts');
        instance.value = 'Police detectives';
        await instance.dispatchEvent(new app.context.Event('input'));
        app.context.renderAdvantages();
        assert.equal(app.document.getElementById('advantage-instance-Contacts').value, 'Police detectives');
        await app.submit();
        assert.equal(app.posts().length, 1);
        const { url, options } = app.posts()[0];
        assert.equal(url, '/api/traits/character/42/resubmit/');
        assert.equal(options.headers['X-CSRFToken'], 'local-csrf-fixture');
        const data = JSON.parse(options.body).character_data;
        assert.equal(data.name, original.full_name);
        assert.equal(data.background, original.background);
        assert.equal(data.predator_discipline, original.predator_discipline);
        assert.deepEqual(data.disciplines, original.disciplines);
        assert.equal(data.animal_ken, 4);
        for (const [name, value] of Object.entries(original.attributes)) assert.equal(data[name], value);
        assert.deepEqual(data.advantages, { ...original.advantages, Contacts: { value: 3, instance: 'Police detectives' } });
        assert.deepEqual(data.flaws, original.flaws);
        assert.deepEqual(app.removedDrafts, ['chargen_draft_42']);
        assert.equal(JSON.stringify(app.logs).includes(original.background), false);
        assert.deepEqual(app.alerts, []);
    });
}

test('single-entry legacy instance lists are restored without losing details', async () => {
    const original = exportedCharacter();
    original.advantages.Contacts = [original.advantages.Contacts];
    const app = harness(original);
    await app.initialize();
    assertRestored(app, original);
    await app.submit();
    assert.deepEqual(JSON.parse(app.posts()[0].options.body).character_data.advantages.Contacts, { value: 3, instance: 'Police' });
});

test('multiple legacy instances block editing and programmatic submission with staff-help guidance', async () => {
    for (const category of ['advantages', 'flaws']) {
        const original = exportedCharacter();
        const name = category === 'advantages' ? 'Contacts' : 'Enemy';
        original[category][name] = [{ value: 1, instance: 'First' }, { value: 1, instance: 'Second' }];
        const app = harness(original);
        await app.initialize();
        assert.match(app.alerts[0], /multiple saved instances.*contact staff/i);
        assert.equal(app.document.getElementById('submit-button').disabled, true);
        // Even a complete form cannot bypass the persistent load failure guard.
        app.context.populateFormFromCharacterData(exportedCharacter());
        await app.submit();
        assert.equal(app.posts().length, 0);
    }
});

test('trait or edit-fetch failure keeps edit submission disabled', async () => {
    for (const flags of [{ failMetadata: true }, { failEdit: true }]) {
        const app = harness(exportedCharacter(), flags);
        await app.initialize();
        app.context.populateFormFromCharacterData(exportedCharacter());
        await app.submit();
        assert.equal(app.document.getElementById('submit-button').disabled, true);
        assert.equal(app.posts().length, 0);
    }
});

test('new-character submit keeps its creation endpoint and CSRF contract', async () => {
    const app = harness(exportedCharacter(), { editId: null });
    await app.initialize();
    app.context.populateFormFromCharacterData(exportedCharacter());
    await app.submit();
    assert.equal(app.posts().length, 1);
    assert.equal(app.posts()[0].url, '/api/traits/character/create/');
    assert.equal(app.posts()[0].options.headers['X-CSRFToken'], 'local-csrf-fixture');
});

function characterWithSelections() {
    return {
        ...exportedCharacter(),
        specialties: { animal_ken: { 'Urban wildlife': 1 }, academics: { History: 1 } },
        discipline_powers: ['Prowess', "Cat's Grace"]
    };
}

test('retained edit selections roundtrip through actual load and submit despite changed traits', async () => {
    const original = characterWithSelections();
    const app = harness(original);
    await app.initialize();
    // Remove a specialty's base skill while keeping the overall skill pool valid.
    // The form must send the saved specialty so the backend can reject the change,
    // rather than silently deleting that specialty from the atomic snapshot.
    const dot = (trait, value) => app.document.querySelector('.pip-row[data-trait="' + trait + '"]').children.find(child => child.dataset.value === value);
    await dot('animal_ken', 4).dispatchEvent(new app.context.Event('click'));
    await dot('streetwise', 4).dispatchEvent(new app.context.Event('click'));
    await dot('Potence', 2).dispatchEvent(new app.context.Event('click'));
    await dot('Presence', 2).dispatchEvent(new app.context.Event('click'));
    assert.equal(app.document.getElementById('submit-button').disabled, false);
    await app.submit();
    assert.equal(app.posts().length, 1);
    const data = JSON.parse(app.posts()[0].options.body).character_data;
    assert.equal(data.animal_ken, 0);
    assert.equal(data.disciplines.Potence, 1);
    assert.deepEqual(data.specialties, original.specialties);
    assert.deepEqual(data.discipline_powers, original.discipline_powers);
});

test('retained edit selections reset on the next loaded character snapshot', async () => {
    const original = characterWithSelections();
    const app = harness(original);
    await app.initialize();
    delete original.specialties;
    delete original.discipline_powers;
    await app.context.loadCharacterForEdit(42);
    await app.submit();
    assert.equal(app.posts().length, 1);
    const data = JSON.parse(app.posts()[0].options.body).character_data;
    assert.deepEqual(data.specialties, {});
    assert.deepEqual(data.discipline_powers, []);
});

test('retained edit selections survive draft save and resume without losing trait details', async () => {
    const original = characterWithSelections();
    const app = harness(original);
    await app.initialize();
    app.context.saveDraft();
    const draft = JSON.parse(app.drafts.get('chargen_draft_42'));
    assert.deepEqual(draft.specialties, original.specialties);
    assert.deepEqual(draft.discipline_powers, original.discipline_powers);
    const resumed = harness(original, { editId: null });
    await resumed.initialize();
    resumed.context.applyDraftToForm(draft);
    await resumed.submit();
    const data = JSON.parse(resumed.posts()[0].options.body).character_data;
    assert.deepEqual(data.specialties, original.specialties);
    assert.deepEqual(data.discipline_powers, original.discipline_powers);
    assert.deepEqual(data.advantages, original.advantages);
    assert.deepEqual(data.flaws, original.flaws);
});

test('retained edit selections reject malformed saved shapes without submitting a replacement snapshot', async () => {
    for (const selections of [
        { specialties: [] },
        { specialties: { animal_ken: ['Urban wildlife'] } },
        { specialties: { animal_ken: { 'Urban wildlife': '1' } } },
        { discipline_powers: [42] }
    ]) {
        const app = harness({ ...characterWithSelections(), ...selections });
        await app.initialize();
        assert.match(app.alerts[0], /cannot be safely restored.*contact staff/i);
        await app.submit();
        assert.equal(app.posts().length, 0);
    }
});
