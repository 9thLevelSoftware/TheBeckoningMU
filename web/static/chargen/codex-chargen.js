// codex-chargen.js: The Beckoning's character creation form (V5 core rules).
//
// The rules (Attribute spread, Skill distributions, clans, predator types,
// disciplines and powers, advantages, flaws, Sea of Time ages) come from
// GET /api/traits/rules/, which is built from world/v5_data.py. The form
// only guides the player; the server validates every submission again
// (world/rules_chargen.py) and is the authority.
//
// The page posts buildPayload(state) to /api/traits/character/create/ (or
// .../<id>/resubmit/). Its keys are exactly the server's submission schema.
//
// Globals set by the template: CSRF_TOKEN, editCharacterId (int or null).

'use strict';

// ============================================================
// PURE CORE (no DOM; also loaded by tests under Node)
// ============================================================

const ChargenCore = (function () {
    const TEXT_KEYS = ['name', 'concept', 'sire', 'ambition', 'desire', 'background'];

    function storageKey(name) {
        return String(name).trim().toLowerCase().replace(/[\s-]+/g, '_');
    }

    function newState(rules) {
        const state = {
            name: '', concept: '', clan: '', age: '', generation: null, predator_type: null,
            sire: '', ambition: '', desire: '', background: '',
            attributes: {}, skills: {}, specialties: [], disciplines: {}, powers: [],
            advantages: [], flaws: [], convictions: [], rituals: [], formulas: []
        };
        if (rules) {
            Object.values(rules.attributes).forEach(function (names) {
                names.forEach(function (n) { state.attributes[storageKey(n)] = 1; });
            });
            Object.values(rules.skills).forEach(function (names) {
                names.forEach(function (n) { state.skills[storageKey(n)] = 0; });
            });
        }
        return state;
    }

    function item(entry) {
        const out = { name: String(entry.name || '').trim(), dots: Number(entry.dots) };
        const note = String(entry.note || '').trim();
        if (note) out.note = note;
        if (entry.source === 'predator') out.source = 'predator';
        return out;
    }

    // The JSON the server accepts (world.rules_chargen schema): fixed keys only.
    function buildPayload(state) {
        const payload = {};
        TEXT_KEYS.forEach(function (key) { payload[key] = String(state[key] || '').trim(); });
        payload.clan = state.clan;
        payload.age = state.age;
        payload.generation = state.generation === null || state.generation === '' ? null : Number(state.generation);
        payload.predator_type = state.predator_type ? state.predator_type : null;
        payload.attributes = Object.assign({}, state.attributes);
        payload.skills = Object.assign({}, state.skills);
        payload.specialties = state.specialties
            .filter(function (s) { return s.skill && String(s.name || '').trim(); })
            .map(function (s) { return { skill: s.skill, name: String(s.name).trim() }; });
        payload.disciplines = {};
        Object.keys(state.disciplines).forEach(function (name) {
            if (state.disciplines[name] > 0) payload.disciplines[name] = Number(state.disciplines[name]);
        });
        payload.discipline_powers = state.powers.slice();
        payload.advantages = state.advantages.filter(function (a) { return a.name; }).map(item);
        payload.flaws = state.flaws.filter(function (f) { return f.name; }).map(item);
        payload.convictions = state.convictions
            .filter(function (c) { return String(c.conviction || '').trim() || String(c.touchstone || '').trim(); })
            .map(function (c) {
                return {
                    conviction: String(c.conviction || '').trim(),
                    touchstone: String(c.touchstone || '').trim(),
                    touchstone_description: String(c.touchstone_description || '').trim()
                };
            });
        payload.rituals = state.rituals.slice();
        payload.formulas = state.formulas.slice();
        return payload;
    }

    // The reverse: a stored submission (for-edit) back into form state.
    function stateFromSubmission(rules, sub) {
        const state = newState(rules);
        TEXT_KEYS.forEach(function (key) { state[key] = sub[key] || ''; });
        state.clan = sub.clan || '';
        state.age = sub.age || '';
        state.generation = sub.generation || null;
        state.predator_type = sub.predator_type || null;
        Object.assign(state.attributes, sub.attributes || {});
        Object.assign(state.skills, sub.skills || {});
        state.specialties = (sub.specialties || []).map(function (s) { return { skill: s.skill, name: s.name }; });
        state.disciplines = Object.assign({}, sub.disciplines || {});
        state.powers = (sub.discipline_powers || []).slice();
        state.advantages = (sub.advantages || []).map(function (a) { return Object.assign({ note: '', source: null }, a); });
        state.flaws = (sub.flaws || []).map(function (f) { return Object.assign({ note: '', source: null }, f); });
        state.convictions = (sub.convictions || []).map(function (c) { return Object.assign({ touchstone_description: '' }, c); });
        state.rituals = (sub.rituals || []).slice();
        state.formulas = (sub.formulas || []).slice();
        return state;
    }

    function counts(values) {
        const c = {};
        values.forEach(function (v) { if (v) c[v] = (c[v] || 0) + 1; });
        return c;
    }

    function sameCounts(a, b) {
        const keys = new Set(Object.keys(a).concat(Object.keys(b)));
        for (const k of keys) { if ((a[k] || 0) !== (b[k] || 0)) return false; }
        return true;
    }

    function skillDistribution(rules, skills) {
        const have = counts(Object.values(skills));
        for (const name of Object.keys(rules.skill_distributions)) {
            if (sameCounts(have, rules.skill_distributions[name])) return name;
        }
        return null;
    }

    function ageOption(rules, state) {
        const age = rules.ages[state.age];
        if (!age) return null;
        return age.options.find(function (o) { return o.generations.indexOf(Number(state.generation)) !== -1; }) || null;
    }

    // Thin-bloods take no predator type; for Childer it is optional.
    function takesPredator(state) {
        return state.clan !== 'Thin-Blood';
    }

    function advantageKind(rules, name) {
        if (rules.backgrounds[name]) return 'background';
        if (rules.merits[name]) return 'merit';
        return null;
    }

    // Live guidance for the sidebar: [label, current, target, ok].
    function tallies(rules, state) {
        const out = [];
        const spread = rules.attribute_spread.slice().sort().join(',');
        const attrs = Object.values(state.attributes).slice().sort().join(',');
        out.push(['Attributes', attrs === spread ? 'done' : 'not yet', rules.attribute_spread.join('/'), attrs === spread]);

        const dist = skillDistribution(rules, state.skills);
        out.push(['Skills', dist || 'no distribution', 'one distribution', !!dist]);

        const free = rules.free_specialty_skills.filter(function (s) { return state.skills[storageKey(s)] > 0; }).length;
        const wantSpecs = free + rules.extra_free_specialties + (takesPredator(state) && state.predator_type ? 1 : 0);
        const haveSpecs = state.specialties.filter(function (s) { return s.skill && String(s.name || '').trim(); }).length;
        out.push(['Specialties', haveSpecs, wantSpecs, haveSpecs === wantSpecs]);

        const discDots = Object.values(state.disciplines).reduce(function (s, v) { return s + Number(v || 0); }, 0);
        let wantDisc = rules.discipline_dots.reduce(function (s, v) { return s + v; }, 0);
        if (state.clan === 'Thin-Blood') wantDisc = 0;
        else if (takesPredator(state) && state.predator_type) wantDisc += 1;
        out.push(['Discipline dots', discDots, wantDisc, state.clan === 'Thin-Blood' ? discDots <= 2 : discDots === wantDisc]);
        out.push(['Powers', state.powers.length, discDots - (state.disciplines['Thin-Blood Alchemy'] || 0),
                  state.powers.length === discDots - (state.disciplines['Thin-Blood Alchemy'] || 0)]);

        const age = rules.ages[state.age] || {};
        let advSpent = 0;
        let flawSpent = 0;
        state.advantages.forEach(function (a) {
            const thin = rules.merits[a.name] && rules.merits[a.name].thin_blood;
            if (a.name && !thin && a.source !== 'predator') advSpent += Number(a.dots || 0);
        });
        state.flaws.forEach(function (f) {
            const thin = rules.flaws[f.name] && rules.flaws[f.name].thin_blood;
            if (f.name && !thin && f.source !== 'predator') flawSpent += Number(f.dots || 0);
        });
        const advBudget = rules.advantage_dots + (age.extra_advantage_dots || 0);
        const flawBudget = rules.flaw_dots + (age.extra_flaw_dots || 0);
        out.push(['Advantage dots', advSpent, 'at most ' + advBudget, advSpent <= advBudget]);
        out.push(['Flaw dots', flawSpent, flawBudget, flawSpent === flawBudget]);
        return out;
    }

    return {
        storageKey: storageKey, newState: newState, buildPayload: buildPayload,
        stateFromSubmission: stateFromSubmission, skillDistribution: skillDistribution,
        ageOption: ageOption, takesPredator: takesPredator, advantageKind: advantageKind, tallies: tallies
    };
})();

if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChargenCore;
}

// ============================================================
// PAGE (DOM)
// ============================================================

if (typeof document !== 'undefined') {
    (function () {
        const C = ChargenCore;
        let rules = null;
        let state = null;
        let currentTab = 0;
        const DRAFT_KEY = editCharacterId ? 'chargen_draft_' + editCharacterId : 'chargen_draft_new';

        // ---------- small DOM helpers (textContent only; no HTML strings from data) ----------
        function el(tag, attrs, children) {
            const node = document.createElement(tag);
            Object.entries(attrs || {}).forEach(function (kv) {
                if (kv[0] === 'text') node.textContent = kv[1];
                else if (kv[0] === 'class') node.className = kv[1];
                else node.setAttribute(kv[0], kv[1]);
            });
            (children || []).forEach(function (c) { if (c) node.appendChild(c); });
            return node;
        }

        function option(value, label, selected) {
            const o = el('option', { value: value, text: label });
            if (selected) o.selected = true;
            return o;
        }

        function select(values, current, onChange, placeholder) {
            const s = el('select', { class: 'codex-select' });
            if (placeholder !== undefined) s.appendChild(option('', placeholder, current === '' || current === null));
            values.forEach(function (v) {
                const pair = Array.isArray(v) ? v : [v, v];
                s.appendChild(option(pair[0], pair[1], String(pair[0]) === String(current)));
            });
            s.addEventListener('change', function () { onChange(s.value); });
            return s;
        }

        function range(lo, hi) {
            const out = [];
            for (let i = lo; i <= hi; i++) out.push(i);
            return out;
        }

        function byId(id) { return document.getElementById(id); }

        function changed() {
            renderSidebar();
            saveDraft();
        }

        // ---------- Identity ----------
        function renderIdentity() {
            ['name', 'concept', 'sire', 'ambition', 'desire', 'background'].forEach(function (key) {
                const input = byId('field-' + key);
                input.value = state[key] || '';
                input.oninput = function () { state[key] = input.value; changed(); };
            });

            const clanBox = byId('clan-box');
            clanBox.replaceChildren(select(Object.keys(rules.clans), state.clan, function (v) {
                state.clan = v;
                if (v === 'Thin-Blood') { state.age = 'Childer'; state.predator_type = null; }
                renderAll();
            }, 'Select a clan...'));
            const clan = rules.clans[state.clan];
            const info = byId('clan-info');
            info.replaceChildren();
            if (clan) {
                info.appendChild(el('p', { text: 'In-clan Disciplines: ' + (clan.disciplines.join(', ') || 'none') }));
                if (clan.bane) info.appendChild(el('p', { text: 'Bane: ' + clan.bane }));
                if (clan.compulsion) info.appendChild(el('p', { text: 'Compulsion: ' + clan.compulsion }));
                (clan.required_flaws || []).forEach(function (f) {
                    info.appendChild(el('p', { text: 'Your clan takes the ' + f.name + ' flaw (' + f.dots + ' dots); it is added for you.' }));
                });
            }

            byId('age-box').replaceChildren(select(Object.keys(rules.ages), state.age, function (v) {
                state.age = v;
                state.generation = null;
                if (!C.takesPredator(state)) state.predator_type = null;
                renderAll();
            }, 'Select an age...'));
            const age = rules.ages[state.age];
            byId('age-info').textContent = age
                ? age.embraced + '. ' + (age.xp ? age.xp + ' XP to spend after approval. ' : '')
                  + (age.extra_advantage_dots ? '+' + age.extra_advantage_dots + ' advantage and +' + age.extra_flaw_dots + ' flaw dots. ' : '')
                  + (age.humanity_change ? 'Humanity ' + age.humanity_change + '.' : '')
                : '';

            const gens = [];
            if (age) {
                age.options.forEach(function (o) {
                    if (o.thin_blood === (state.clan === 'Thin-Blood')) {
                        o.generations.forEach(function (g) { gens.push([g, g + 'th generation (Blood Potency ' + o.blood_potency + ')']); });
                    }
                });
            }
            byId('generation-box').replaceChildren(select(gens, state.generation, function (v) {
                state.generation = v ? Number(v) : null;
                changed();
            }, gens.length ? 'Select a generation...' : 'Choose a clan and age first'));

            const predatorBox = byId('predator-box');
            const predatorInfo = byId('predator-info');
            predatorInfo.replaceChildren();
            if (!C.takesPredator(state)) {
                predatorBox.replaceChildren(el('p', { class: 'codex-hint', text: 'Thin-bloods take no predator type.' }));
                return;
            }
            predatorBox.replaceChildren(select(Object.keys(rules.predator_types), state.predator_type || '', function (v) {
                state.predator_type = v || null;
                renderAll();
            }, state.age === 'Childer' ? 'None (optional for Childer)' : 'Select a predator type...'));
            const pred = rules.predator_types[state.predator_type];
            if (pred) {
                predatorInfo.appendChild(el('p', { text: pred.description }));
                predatorInfo.appendChild(el('p', { text: 'Specialty (take one): ' + pred.specialties.map(function (s) { return s[0] + ' (' + s[1] + ')'; }).join(', ') }));
                predatorInfo.appendChild(el('p', { text: 'Discipline dot (take one): ' + pred.disciplines.join(', ') }));
                const grants = [];
                (pred.backgrounds || []).concat(pred.merits || [], pred.flaws || []).forEach(function (g) {
                    grants.push(g.name + ' ' + g.dots + (g.note ? ' (' + g.note + ')' : ''));
                });
                if (grants.length) predatorInfo.appendChild(el('p', { text: 'Added for you: ' + grants.join(', ') }));
                (pred.advantage_choices || []).concat(pred.flaw_choices || []).forEach(function (choice) {
                    const from = (choice.from || []).concat((choice.from_categories || []).map(function (c) { return 'any ' + c + ' flaw'; }));
                    predatorInfo.appendChild(el('p', { text: 'Choose ' + choice.dots + ' dots among ' + from.join(', ') + ' (mark them "predator choice" on the Advantages tab).' }));
                });
                if (pred.humanity) predatorInfo.appendChild(el('p', { text: 'Humanity ' + (pred.humanity > 0 ? '+' : '') + pred.humanity }));
                if (pred.blood_potency) predatorInfo.appendChild(el('p', { text: 'Blood Potency +' + pred.blood_potency }));
                if (pred.note) predatorInfo.appendChild(el('p', { text: pred.note }));
            }
        }

        function renderConvictions() {
            const list = byId('convictions-list');
            list.replaceChildren();
            state.convictions.forEach(function (c, index) {
                function input(key, placeholder, max) {
                    const i = el('input', { type: 'text', class: 'codex-input', maxlength: String(max), placeholder: placeholder });
                    i.value = c[key] || '';
                    i.oninput = function () { c[key] = i.value; changed(); };
                    return i;
                }
                const remove = el('button', { type: 'button', class: 'btn-codex-ghost', text: 'Remove' });
                remove.addEventListener('click', function () { state.convictions.splice(index, 1); renderConvictions(); changed(); });
                list.appendChild(el('div', { class: 'codex-trait-row' }, [
                    input('conviction', 'Conviction', 200), input('touchstone', 'Touchstone (who)', 100),
                    input('touchstone_description', 'Who they are to you', 500), remove
                ]));
            });
            byId('add-conviction').disabled = state.convictions.length >= rules.conviction_range[1];
        }

        // ---------- Attributes and Skills ----------
        function ratingGrid(containerId, groups, values, lo, hi) {
            const container = byId(containerId);
            container.replaceChildren();
            Object.keys(groups).forEach(function (group) {
                const column = el('div', { class: 'codex-trait-group' }, [el('h5', { text: group })]);
                groups[group].forEach(function (name) {
                    const key = C.storageKey(name);
                    const row = el('div', { class: 'codex-trait-row' }, [el('label', { text: name })]);
                    row.appendChild(select(range(lo, hi), values[key], function (v) {
                        values[key] = Number(v);
                        if (containerId === 'skills-grid') renderSpecialties();
                        changed();
                    }));
                    column.appendChild(row);
                });
                container.appendChild(column);
            });
        }

        function renderAttributes() {
            ratingGrid('attributes-grid', rules.attributes, state.attributes, 1, 5);
            byId('attribute-rule').textContent = 'Rate one Attribute 4, three 3, four 2 and one 1 ('
                + rules.attribute_spread.join('/') + ').';
        }

        function renderSkills() {
            ratingGrid('skills-grid', rules.skills, state.skills, 0, 5);
            const lines = Object.keys(rules.skill_distributions).map(function (name) {
                const d = rules.skill_distributions[name];
                return name + ': ' + Object.keys(d).sort().reverse().map(function (r) { return d[r] + ' at ' + r; }).join(', ');
            });
            byId('skill-rule').textContent = 'Use one distribution. ' + lines.join('; ') + '. Every other Skill is 0.';
            renderSpecialties();
        }

        function skillOptions() {
            const out = [];
            Object.values(rules.skills).forEach(function (names) {
                names.forEach(function (n) { out.push([C.storageKey(n), n]); });
            });
            return out;
        }

        function renderSpecialties() {
            const list = byId('specialties-list');
            list.replaceChildren();
            state.specialties.forEach(function (spec, index) {
                const name = el('input', { type: 'text', class: 'codex-input', maxlength: '50', placeholder: 'Specialty' });
                name.value = spec.name || '';
                name.oninput = function () { spec.name = name.value; changed(); };
                const remove = el('button', { type: 'button', class: 'btn-codex-ghost', text: 'Remove' });
                remove.addEventListener('click', function () { state.specialties.splice(index, 1); renderSpecialties(); changed(); });
                list.appendChild(el('div', { class: 'codex-trait-row' }, [
                    select(skillOptions(), spec.skill, function (v) { spec.skill = v; changed(); }, 'Skill...'), name, remove
                ]));
            });
            const free = rules.free_specialty_skills.filter(function (s) { return state.skills[C.storageKey(s)] > 0; });
            let hint = 'Take a free specialty in each of ' + rules.free_specialty_skills.join(', ')
                + ' you have dots in' + (free.length ? ' (you need: ' + free.join(', ') + ')' : '')
                + ', plus ' + rules.extra_free_specialties + ' more';
            const pred = C.takesPredator(state) && rules.predator_types[state.predator_type];
            if (pred) hint += ', plus one from ' + state.predator_type + ': ' + pred.specialties.map(function (s) { return s[0] + ' (' + s[1] + ')'; }).join(' or ');
            byId('specialty-rule').textContent = hint + '. A specialty needs at least one dot in its Skill.';
        }

        // ---------- Disciplines and powers ----------
        function renderDisciplines() {
            const container = byId('disciplines-grid');
            container.replaceChildren();
            const clan = rules.clans[state.clan] || { disciplines: [] };
            const pred = C.takesPredator(state) ? rules.predator_types[state.predator_type] : null;
            let hint;
            if (state.clan === 'Thin-Blood') {
                hint = 'Thin-bloods start with no Disciplines. The Thin-blood Alchemist merit gives Thin-Blood Alchemy 1; Discipline Affinity gives one dot in one Discipline.';
            } else if (state.clan === 'Caitiff') {
                hint = 'Caitiff: put 2 dots in any Discipline and 1 in another.';
            } else {
                hint = 'Put 2 dots in one in-clan Discipline (' + (clan.disciplines.join(', ') || 'choose a clan') + ') and 1 in another.';
            }
            if (pred) hint += ' ' + state.predator_type + ' adds 1 dot in one of: ' + pred.disciplines.join(', ') + '.';
            hint += ' Then pick one power per dot, each at or below the Discipline\'s rating.';
            byId('discipline-rule').textContent = hint;

            Object.keys(rules.disciplines).forEach(function (name) {
                const dots = state.disciplines[name] || 0;
                const label = name + (clan.disciplines.indexOf(name) !== -1 ? ' (in-clan)' : '');
                const block = el('div', { class: 'codex-discipline' }, [
                    el('div', { class: 'codex-trait-row' }, [el('label', { text: label }), select(range(0, 5), dots, function (v) {
                        state.disciplines[name] = Number(v);
                        const allowed = new Set(powersFor(name, Number(v)).map(function (p) { return p.name; }));
                        state.powers = state.powers.filter(function (p) { return powerDiscipline(p) !== name || allowed.has(p); });
                        renderDisciplines();
                        changed();
                    })])
                ]);
                if (dots > 0) {
                    const powers = powersFor(name, dots);
                    if (!powers.length) block.appendChild(el('p', { class: 'codex-hint', text: 'No powers to pick; choose your formula below.' }));
                    powers.forEach(function (power) {
                        const box = el('input', { type: 'checkbox' });
                        box.checked = state.powers.indexOf(power.name) !== -1;
                        box.addEventListener('change', function () {
                            if (box.checked) state.powers.push(power.name);
                            else state.powers = state.powers.filter(function (p) { return p !== power.name; });
                            changed();
                        });
                        const text = 'Level ' + power.level + ': ' + power.name + (power.amalgam ? ' (needs ' + power.amalgam + ')' : '');
                        block.appendChild(el('label', { class: 'codex-power', title: power.description || '' }, [box, document.createTextNode(' ' + text)]));
                    });
                }
                container.appendChild(block);
            });
            renderRitualAndFormula(container);
        }

        function renderRitualAndFormula(container) {
            if ((state.disciplines['Blood Sorcery'] || 0) > 0) {
                const firsts = rules.rituals.filter(function (r) { return r.level === 1; }).map(function (r) { return r.name; });
                container.appendChild(el('div', { class: 'codex-trait-row' }, [
                    el('label', { text: 'Free ritual (level 1)' }),
                    select(firsts, state.rituals[0] || '', function (v) { state.rituals = v ? [v] : []; changed(); }, 'Choose a ritual...')
                ]));
            } else {
                state.rituals = [];
            }
            const alchemist = state.advantages.some(function (a) { return a.name === 'Thin-blood Alchemist'; });
            if (alchemist) {
                const level = state.disciplines['Thin-Blood Alchemy'] || 1;
                const names = rules.formulas.filter(function (f) { return f.level <= level; }).map(function (f) { return f.name; });
                container.appendChild(el('div', { class: 'codex-trait-row' }, [
                    el('label', { text: 'Free formula (Thin-blood Alchemist)' }),
                    select(names, state.formulas[0] || '', function (v) { state.formulas = v ? [v] : []; changed(); }, 'Choose a formula...')
                ]));
            } else {
                state.formulas = [];
            }
        }

        function powersFor(discipline, dots) {
            return (rules.disciplines[discipline].powers || []).filter(function (p) { return p.level <= dots; });
        }

        function powerDiscipline(powerName) {
            for (const name of Object.keys(rules.disciplines)) {
                if ((rules.disciplines[name].powers || []).some(function (p) { return p.name === powerName; })) return name;
            }
            return null;
        }

        // ---------- Advantages and flaws ----------
        function advantageSelect(kind, entry, onChange) {
            const s = el('select', { class: 'codex-select' });
            s.appendChild(option('', 'Choose...', !entry.name));
            const groups = kind === 'advantages'
                ? [['Backgrounds', rules.backgrounds], ['Merits', rules.merits]]
                : [['Flaws', rules.flaws]];
            groups.forEach(function (g) {
                const optgroup = el('optgroup', { label: g[0] });
                Object.keys(g[1]).forEach(function (name) {
                    const data = g[1][name];
                    const label = name + (data.thin_blood ? ' (thin-blood, free)' : '') + (data.group ? ' [' + data.group + ']' : '');
                    optgroup.appendChild(option(name, label, entry.name === name));
                });
                s.appendChild(optgroup);
            });
            s.addEventListener('change', function () { onChange(s.value); });
            return s;
        }

        function allowedDots(kind, name) {
            if (kind === 'advantages' && rules.backgrounds[name]) return range(1, rules.backgrounds[name].max_dots);
            const table = kind === 'advantages' ? rules.merits : rules.flaws;
            return table[name] ? table[name].dots : [];
        }

        function renderItems(kind) {
            const list = byId(kind + '-list');
            list.replaceChildren();
            const pred = C.takesPredator(state) ? rules.predator_types[state.predator_type] : null;
            const hasChoices = pred && ((kind === 'advantages' ? pred.advantage_choices : pred.flaw_choices) || []).length;
            state[kind].forEach(function (entry, index) {
                const dots = allowedDots(kind, entry.name);
                if (dots.length && dots.indexOf(Number(entry.dots)) === -1) entry.dots = dots[0];
                const note = el('input', { type: 'text', class: 'codex-input', maxlength: '100', placeholder: 'Note (who or what)' });
                note.value = entry.note || '';
                note.oninput = function () { entry.note = note.value; changed(); };
                const row = el('div', { class: 'codex-trait-row' }, [
                    advantageSelect(kind, entry, function (v) { entry.name = v; renderItems(kind); changed(); }),
                    select(dots, entry.dots, function (v) { entry.dots = Number(v); changed(); }),
                    note
                ]);
                if (hasChoices) {
                    const box = el('input', { type: 'checkbox' });
                    box.checked = entry.source === 'predator';
                    box.addEventListener('change', function () { entry.source = box.checked ? 'predator' : null; changed(); });
                    row.appendChild(el('label', { class: 'codex-hint' }, [box, document.createTextNode(' predator choice')]));
                } else if (entry.source === 'predator') {
                    entry.source = null;
                }
                const remove = el('button', { type: 'button', class: 'btn-codex-ghost', text: 'Remove' });
                remove.addEventListener('click', function () { state[kind].splice(index, 1); renderItems(kind); changed(); });
                row.appendChild(remove);
                list.appendChild(row);
            });
            const age = rules.ages[state.age] || {};
            byId('advantage-rule').textContent = 'Spend up to ' + (rules.advantage_dots + (age.extra_advantage_dots || 0))
                + ' dots on backgrounds and merits and take exactly ' + (rules.flaw_dots + (age.extra_flaw_dots || 0))
                + ' dots of flaws. Instanced backgrounds (Allies, Contacts, ...) need a note.'
                + (state.clan === 'Thin-Blood' ? ' Thin-bloods also take 1-3 thin-blood merits and the same number of thin-blood flaws, which cost nothing.' : '');
        }

        // ---------- Sidebar and summary ----------
        function renderSidebar() {
            const box = byId('tracker-lines');
            box.replaceChildren();
            C.tallies(rules, state).forEach(function (t) {
                box.appendChild(el('div', { class: 'tracker-line ' + (t[3] ? 'valid' : 'invalid') }, [
                    el('span', { text: t[0] + ': ' + t[1] + ' / ' + t[2] })
                ]));
            });
        }

        function showErrors(errors) {
            const box = byId('validation-errors');
            const list = byId('error-list-items');
            list.replaceChildren();
            errors.forEach(function (e) { list.appendChild(el('li', { text: e })); });
            box.style.display = errors.length ? 'block' : 'none';
        }

        async function checkWithServer() {
            const response = await postJSON('/api/traits/character/validate/', C.buildPayload(state));
            const data = await response.json().catch(function () { return {}; });
            const errors = data.errors || (data.error ? [data.error] : []);
            showErrors(errors);
            byId('submit-button').disabled = errors.length > 0 || !response.ok;
            byId('check-result').textContent = errors.length ? '' : 'Everything checks out. You can submit.';
        }

        function renderAll() {
            renderIdentity();
            renderConvictions();
            renderAttributes();
            renderSkills();
            renderDisciplines();
            renderItems('advantages');
            renderItems('flaws');
            renderSidebar();
            saveDraft();
        }

        // ---------- Tabs ----------
        function showTab(index) {
            const panels = document.querySelectorAll('.codex-tab-panel');
            currentTab = Math.max(0, Math.min(index, panels.length - 1));
            panels.forEach(function (p, i) { p.style.display = i === currentTab ? 'block' : 'none'; });
            document.querySelectorAll('.codex-tab').forEach(function (t, i) { t.classList.toggle('active', i === currentTab); });
            byId('btn-prev').style.visibility = currentTab === 0 ? 'hidden' : 'visible';
            byId('btn-next').style.visibility = currentTab === panels.length - 1 ? 'hidden' : 'visible';
            if (currentTab === panels.length - 1) checkWithServer();
            window.scrollTo(0, 0);
        }

        // ---------- Server I/O ----------
        function postJSON(url, body) {
            return fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
                body: JSON.stringify(body)
            });
        }

        async function submit(event) {
            event.preventDefault();
            const url = editCharacterId
                ? '/api/traits/character/' + editCharacterId + '/resubmit/'
                : '/api/traits/character/create/';
            const button = byId('submit-button');
            if (button.disabled) return;
            button.disabled = true;  // no double submissions while the request is in flight
            const response = await postJSON(url, C.buildPayload(state)).catch(function () { return null; });
            const data = response ? await response.json().catch(function () { return {}; }) : {};
            if (!response || !response.ok) {
                button.disabled = false;
                showErrors(data.errors || [data.error || 'The server refused the character']);
                toast('Not submitted: see the list of problems', 'danger');
                return;
            }
            clearDraft();
            toast(editCharacterId ? 'Character resubmitted for approval.' : 'Character submitted for approval.', 'success');
            setTimeout(function () { window.location.href = '/'; }, 2000);
        }

        function saveDraft() {
            try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ savedAt: Date.now(), state: state })); } catch (e) { /* storage off */ }
        }

        function clearDraft() {
            try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* storage off */ }
        }

        function loadDraft() {
            try {
                const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
                if (!saved || !saved.state || Date.now() - saved.savedAt > 7 * 24 * 3600 * 1000) return null;
                if (!window.confirm('Resume your saved draft from ' + new Date(saved.savedAt).toLocaleString() + '?')) {
                    clearDraft();
                    return null;
                }
                return Object.assign(C.newState(rules), saved.state);
            } catch (e) {
                return null;
            }
        }

        function toast(message, type) {
            const container = byId('toast-container');
            const node = el('div', { class: 'toast align-items-center text-white bg-' + (type || 'info') + ' border-0', role: 'alert' }, [
                el('div', { class: 'd-flex' }, [el('div', { class: 'toast-body', text: message })])
            ]);
            container.appendChild(node);
            if (window.bootstrap) new window.bootstrap.Toast(node, { delay: 4000 }).show();
            setTimeout(function () { node.remove(); }, 5000);
        }

        async function init() {
            const rulesResponse = await fetch('/api/traits/rules/');
            rules = await rulesResponse.json();
            state = C.newState(rules);
            if (editCharacterId) {
                const response = await fetch('/api/traits/character/' + editCharacterId + '/for-edit/');
                const data = await response.json().catch(function () { return {}; });
                if (!response.ok) {
                    toast('Cannot edit: ' + (data.error || response.status), 'danger');
                } else if (data.mode === 'revoked') {
                    revokedMode(data);
                    return;
                } else {
                    state = C.stateFromSubmission(rules, data.character_data || {});
                    if (data.rejection_notes) {
                        byId('rejection-banner').style.display = 'block';
                        byId('rejection-notes').textContent = data.rejection_notes;
                    }
                    byId('page-title').textContent = 'Edit & Resubmit Character';
                    byId('submit-button').textContent = 'Resubmit Character';
                }
            } else {
                state = loadDraft() || state;
            }
            document.querySelectorAll('.codex-tab').forEach(function (tab, i) { tab.addEventListener('click', function () { showTab(i); }); });
            byId('btn-prev').addEventListener('click', function () { showTab(currentTab - 1); });
            byId('btn-next').addEventListener('click', function () { showTab(currentTab + 1); });
            byId('add-conviction').addEventListener('click', function () {
                state.convictions.push({ conviction: '', touchstone: '', touchstone_description: '' });
                renderConvictions();
                changed();
            });
            byId('add-specialty').addEventListener('click', function () { state.specialties.push({ skill: '', name: '' }); renderSpecialties(); changed(); });
            byId('add-advantage').addEventListener('click', function () { state.advantages.push({ name: '', dots: 1, note: '', source: null }); renderItems('advantages'); changed(); });
            byId('add-flaw').addEventListener('click', function () { state.flaws.push({ name: '', dots: 1, note: '', source: null }); renderItems('flaws'); changed(); });
            byId('check-button').addEventListener('click', checkWithServer);
            byId('character-form').addEventListener('submit', submit);
            renderAll();
            showTab(0);
        }

        // A revoked character keeps its played sheet: resubmitting only sends it
        // back for review, with optional changes to the narrative.
        function revokedMode(data) {
            byId('page-title').textContent = 'Resubmit Character for Review';
            byId('rejection-banner').style.display = 'block';
            byId('rejection-notes').textContent = (data.rejection_notes || '')
                + '\n\nYour current sheet (traits, XP and everything bought in play) is kept and sent back to staff as it stands.';
            document.querySelectorAll('.codex-tab-panel, .codex-tabs, .codex-nav-arrows, .codex-tracker').forEach(function (n) { n.style.display = 'none'; });
            const panel = document.querySelector('.codex-tab-panel[data-tab="0"]');
            panel.style.display = 'block';
            ['name', 'concept', 'sire', 'ambition', 'desire', 'background'].forEach(function (key) {
                byId('field-' + key).value = (data.narrative || {})[key] || '';
            });
            byId('field-name').disabled = true;
            ['clan-box', 'age-box', 'generation-box', 'predator-box', 'convictions-list', 'add-conviction'].forEach(function (id) {
                const node = byId(id);
                if (node) node.closest('.codex-field').style.display = 'none';
            });
            const button = el('button', { type: 'button', class: 'btn-codex', text: 'Resubmit for Review' });
            button.addEventListener('click', async function () {
                const body = {};
                ['concept', 'sire', 'ambition', 'desire', 'background'].forEach(function (key) { body[key] = byId('field-' + key).value; });
                const response = await postJSON('/api/traits/character/' + editCharacterId + '/resubmit/', body);
                const result = await response.json().catch(function () { return {}; });
                if (!response.ok) { toast('Not resubmitted: ' + (result.error || response.status), 'danger'); return; }
                toast('Character resubmitted for review.', 'success');
                setTimeout(function () { window.location.href = '/'; }, 2000);
            });
            panel.appendChild(button);
        }

        document.addEventListener('DOMContentLoaded', init);
    })();
}
