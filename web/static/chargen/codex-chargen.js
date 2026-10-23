// codex-chargen.js — The Crimson Codex Character Generator
// CSRF_TOKEN and editCharacterId must be set before this script loads
//
// Expected globals:
//   CSRF_TOKEN  — Django CSRF token string
//   editCharacterId — character id (int) or null for new characters

// ============================================================
// TAB CONFIGURATION
// ============================================================

const TAB_CONFIG = [
    { id: 'tab-identity',    label: 'Identity',    numeral: 'I' },
    { id: 'tab-attributes',  label: 'Attributes',  numeral: 'II' },
    { id: 'tab-skills',      label: 'Skills',      numeral: 'III' },
    { id: 'tab-disciplines', label: 'Disciplines',  numeral: 'IV' },
    { id: 'tab-advantages',  label: 'Advantages',  numeral: 'V' },
    { id: 'tab-flaws',       label: 'Flaws',       numeral: 'VI' },
    { id: 'tab-chronicle',   label: 'Submit',      numeral: 'VII' }
];

let currentTab = 0;

// ============================================================
// CLAN DATA
// ============================================================

const CLANS = {
    "Banu Haqim": {
        disciplines: ["Blood Sorcery", "Celerity", "Obfuscate"],
        bane: "Judgment: Lose Humanity for witnessing corruption without acting"
    },
    "Brujah": {
        disciplines: ["Celerity", "Potence", "Presence"],
        bane: "Violent Temper: Difficulty +2 to resist fury frenzy"
    },
    "Gangrel": {
        disciplines: ["Animalism", "Fortitude", "Protean"],
        bane: "Bestial Features: Animal features emerge when Hunger 4+"
    },
    "Hecata": {
        disciplines: ["Auspex", "Fortitude", "Oblivion"],
        bane: "Painful Kiss: Feeding causes intense pain to victim"
    },
    "Lasombra": {
        disciplines: ["Dominate", "Oblivion", "Potence"],
        bane: "Callous: Cannot gain Humanity from Remorse"
    },
    "Malkavian": {
        disciplines: ["Auspex", "Dominate", "Obfuscate"],
        bane: "Fractured Perspective: Must have at least one mental derangement"
    },
    "Ministry": {
        disciplines: ["Obfuscate", "Presence", "Protean"],
        bane: "Abhors the Light: Additional damage from sunlight"
    },
    "Nosferatu": {
        disciplines: ["Animalism", "Obfuscate", "Potence"],
        bane: "Repulsive: Appearance 0, automatic fail on Persuasion/Performance vs mortals"
    },
    "Ravnos": {
        disciplines: ["Animalism", "Obfuscate", "Presence"],
        bane: "Doomed: Cannot rest in same place twice in 7 nights"
    },
    "Salubri": {
        disciplines: ["Auspex", "Dominate", "Fortitude"],
        bane: "Third Eye: Visible third eye when using Disciplines"
    },
    "Toreador": {
        disciplines: ["Auspex", "Celerity", "Presence"],
        bane: "Aesthetic Fixation: May become entranced by beauty"
    },
    "Tremere": {
        disciplines: ["Auspex", "Blood Sorcery", "Dominate"],
        bane: "Deficient Blood: Blood bonds form one step stronger"
    },
    "Tzimisce": {
        disciplines: ["Animalism", "Dominate", "Protean"],
        bane: "Grounded: Must rest with homeland soil"
    },
    "Ventrue": {
        disciplines: ["Dominate", "Fortitude", "Presence"],
        bane: "Rarefied Taste: Can only feed from specific type of mortal"
    },
    "Caitiff": {
        disciplines: [],
        bane: "Suspect Blood: Ostracized by Camarilla"
    }
};

// ============================================================
// SKILL LISTS (constant arrays)
// ============================================================

const PHYSICAL_SKILLS = ['athletics', 'brawl', 'craft', 'drive', 'firearms', 'melee', 'larceny', 'stealth', 'survival'];
const SOCIAL_SKILLS = ['animal_ken', 'etiquette', 'insight', 'intimidation', 'leadership', 'performance', 'persuasion', 'streetwise', 'subterfuge'];
const MENTAL_SKILLS = ['academics', 'awareness', 'finance', 'investigation', 'medicine', 'occult', 'politics', 'science', 'technology'];

// ============================================================
// STATE
// ============================================================

const traitValues = {};
const disciplineValues = {};
const advantageValues = {};
const flawValues = {};

const attributePriorities = { primary: null, secondary: null, tertiary: null };
const skillPriorities = { primary: null, secondary: null, tertiary: null };

let disciplinesData = [];
let advantagesData = [];
let flawsData = [];

let isEditMode = false;
let editLoadError = null;
let predatorDisciplineChoice = null;
let retainedSelections = { specialties: {}, discipline_powers: [] };

const PREDATOR_TYPES = {
    "Alleycat": ["Celerity", "Potence"],
    "Bagger": ["Blood Sorcery", "Obfuscate"],
    "Blood Leech": ["Celerity", "Protean"],
    "Cleaver": ["Animalism", "Dominate"],
    "Consensualist": ["Auspex", "Fortitude"],
    "Farmer": ["Animalism", "Protean"],
    "Osiris": ["Blood Sorcery", "Presence"],
    "Sandman": ["Auspex", "Obfuscate"],
    "Scene Queen": ["Dominate", "Presence"],
    "Siren": ["Fortitude", "Presence"]
};

// ============================================================
// DOT CLASS HELPERS
// Support both old (.dot) and new (.blood-pip) class names
// ============================================================

/** CSS class used when creating new dot elements */
const DOT_CLASS = 'blood-pip';
/** Selector that matches both old and new dot elements */
const DOT_SELECTOR = '.dot, .blood-pip';

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', async function () {
    isEditMode = !!editCharacterId;
    if (isEditMode) editLoadError = 'Character data is loading.';
    initializeDots();
    setupClanSelector();
    setupPredatorTypeSelector();
    setupFormSubmit();
    const traitsLoaded = loadTraitData();
    setupPrioritySelectors();
    initTabs();

    // Dynamic detail inputs must exist before restoring saved character data.
    const ready = await traitsLoaded;
    if (isEditMode && !ready) {
        editLoadError = 'Trait data could not be loaded. Reload this page before editing.';
        validateForm();
        return;
    }

    // Draft system: offer to resume saved draft (only for new characters)
    if (!editCharacterId) {
        loadDraft();
    }

    // Edit mode: load character data for editing after rejection
    if (editCharacterId) {
        await loadCharacterForEdit(editCharacterId);
    }

    // Auto-save draft every 30 seconds
    setInterval(saveDraft, 30000);

    // Save draft on blur of key text fields
    ['full_name', 'concept', 'sire', 'ambition', 'desire', 'background'].forEach(function (fieldId) {
        const el = document.getElementById(fieldId);
        if (el) {
            el.addEventListener('blur', saveDraft);
        }
    });
});

// ============================================================
// TAB NAVIGATION
// ============================================================

function initTabs() {
    // Wire up tab clicks
    document.querySelectorAll('.codex-tab').forEach(function (tab, i) {
        tab.addEventListener('click', function () {
            showTab(i);
        });
    });

    // Wire up prev/next buttons
    const prevBtn = document.getElementById('btn-prev');
    const nextBtn = document.getElementById('btn-next');
    if (prevBtn) prevBtn.addEventListener('click', prevTab);
    if (nextBtn) nextBtn.addEventListener('click', nextTab);

    // Show first tab
    showTab(0);
}

function showTab(index) {
    index = Math.max(0, Math.min(index, TAB_CONFIG.length - 1));
    currentTab = index;

    // Hide all tab panels, show selected
    document.querySelectorAll('.codex-tab-panel').forEach(function (panel, i) {
        panel.style.display = i === index ? 'block' : 'none';
    });

    // Update tab indicators
    document.querySelectorAll('.codex-tab').forEach(function (tab, i) {
        tab.classList.toggle('active', i === index);
    });

    // Update prev/next buttons
    const prevBtn = document.getElementById('btn-prev');
    const nextBtn = document.getElementById('btn-next');
    if (prevBtn) prevBtn.style.visibility = index === 0 ? 'hidden' : 'visible';
    if (nextBtn) {
        nextBtn.style.visibility = index === TAB_CONFIG.length - 1 ? 'hidden' : 'visible';
    }

    // Scroll to top of content
    const main = document.querySelector('.chargen-main');
    if (main) main.scrollTo(0, 0);
    window.scrollTo(0, 0);

    // If showing chronicle/submit tab, render summary
    if (index === TAB_CONFIG.length - 1) {
        renderChronicSummary();
    }
}

function nextTab() { showTab(currentTab + 1); }
function prevTab() { showTab(currentTab - 1); }

// ============================================================
// TAB COMPLETION
// ============================================================

function updateTabCompletion() {
    TAB_CONFIG.forEach(function (config, index) {
        const tabEl = document.querySelector('.codex-tab[data-tab="' + index + '"]');
        if (!tabEl) return;
        const isComplete = checkTabComplete(index);
        tabEl.classList.toggle('complete', isComplete);
    });
}

function checkTabComplete(tabIndex) {
    switch (tabIndex) {
        case 0: // Identity
            return !!(
                document.getElementById('full_name').value.trim() &&
                document.getElementById('concept').value.trim() &&
                document.getElementById('clan').value
            );

        case 1: { // Attributes
            if (!attributePriorities.primary || !attributePriorities.secondary || !attributePriorities.tertiary) {
                return false;
            }
            const physSpent = ['strength', 'dexterity', 'stamina']
                .reduce(function (s, t) { return s + traitValues[t]; }, 0) - 3;
            const socSpent = ['charisma', 'manipulation', 'composure']
                .reduce(function (s, t) { return s + traitValues[t]; }, 0) - 3;
            const menSpent = ['intelligence', 'wits', 'resolve']
                .reduce(function (s, t) { return s + traitValues[t]; }, 0) - 3;
            return (
                physSpent === getAttributePoolForCategory('physical') &&
                socSpent === getAttributePoolForCategory('social') &&
                menSpent === getAttributePoolForCategory('mental')
            );
        }

        case 2: { // Skills
            if (!skillPriorities.primary || !skillPriorities.secondary || !skillPriorities.tertiary) {
                return false;
            }
            const pSkill = PHYSICAL_SKILLS.reduce(function (s, t) { return s + (traitValues[t] || 0); }, 0);
            const sSkill = SOCIAL_SKILLS.reduce(function (s, t) { return s + (traitValues[t] || 0); }, 0);
            const mSkill = MENTAL_SKILLS.reduce(function (s, t) { return s + (traitValues[t] || 0); }, 0);
            return (
                pSkill === getSkillPoolForCategory('physical') &&
                sSkill === getSkillPoolForCategory('social') &&
                mSkill === getSkillPoolForCategory('mental')
            );
        }

        case 3: { // Disciplines
            const discSpent = Object.values(disciplineValues).reduce(function (s, v) { return s + v; }, 0);
            if (discSpent !== 3) return false;
            const selectedClan = document.getElementById('clan').value;
            if (selectedClan && CLANS[selectedClan] && CLANS[selectedClan].disciplines.length > 0) {
                // Non-Caitiff: enforce 2+1 pattern, all in-clan
                const activeDiscs = Object.entries(disciplineValues).filter(function (e) { return e[1] > 0; });
                if (activeDiscs.length !== 2) return false;
                const values = activeDiscs.map(function (e) { return e[1]; }).sort();
                if (values[0] !== 1 || values[1] !== 2) return false;
                const inClanDiscs = CLANS[selectedClan].disciplines;
                var allInClan = activeDiscs.every(function (e) { return inClanDiscs.includes(e[0]); });
                if (!allInClan) return false;
            } else if (selectedClan === 'Caitiff') {
                // Caitiff: 3 total, at least 2 different disciplines
                const caitiffActive = Object.entries(disciplineValues).filter(function (e) { return e[1] > 0; });
                if (caitiffActive.length < 2) return false;
            }
            // Predator discipline choice required if predator type is selected
            var predType = document.getElementById('predator_type').value;
            if (predType && PREDATOR_TYPES[predType] && !predatorDisciplineChoice) return false;
            return true;
        }

        case 4: { // Advantages
            const advSpent = Object.values(advantageValues).reduce(function (s, a) { return s + a.value; }, 0);
            return advSpent === 7;
        }

        case 5: { // Flaws
            const flawSpent = Object.values(flawValues).reduce(function (s, f) { return s + f.value; }, 0);
            return flawSpent <= 2; // flaws are optional, 0 is valid
        }

        case 6: // Chronicle/Submit — complete when all other tabs are complete
            for (let i = 0; i < TAB_CONFIG.length - 1; i++) {
                if (!checkTabComplete(i)) return false;
            }
            return true;

        default:
            return false;
    }
}

// ============================================================
// CHRONICLE SUMMARY (Tab VII)
// ============================================================

function renderChronicSummary() {
    const container = document.getElementById('chronicle-summary');
    if (!container) return;

    const clanVal = document.getElementById('clan').value || '(none)';
    const nameVal = document.getElementById('full_name').value || '(unnamed)';
    const conceptVal = document.getElementById('concept').value || '(none)';
    const sireVal = document.getElementById('sire').value || '(none)';
    const genVal = document.getElementById('generation').value || '(none)';
    const predVal = document.getElementById('predator_type').value || '(none)';
    const ambitionVal = document.getElementById('ambition').value || '(none)';
    const desireVal = document.getElementById('desire').value || '(none)';

    let html = '<div class="chronicle-review">';

    // Identity
    html += '<h4 class="chronicle-heading">I. Identity</h4>';
    html += '<div class="chronicle-block">';
    html += '<p><strong>Name:</strong> ' + escapeHtml(nameVal) + '</p>';
    html += '<p><strong>Concept:</strong> ' + escapeHtml(conceptVal) + '</p>';
    html += '<p><strong>Clan:</strong> ' + escapeHtml(clanVal) + '</p>';
    html += '<p><strong>Sire:</strong> ' + escapeHtml(sireVal) + '</p>';
    html += '<p><strong>Generation:</strong> ' + escapeHtml(genVal) + '</p>';
    html += '<p><strong>Predator Type:</strong> ' + escapeHtml(predVal) + '</p>';
    html += '<p><strong>Ambition:</strong> ' + escapeHtml(ambitionVal) + '</p>';
    html += '<p><strong>Desire:</strong> ' + escapeHtml(desireVal) + '</p>';
    html += '</div>';

    // Attributes
    html += '<h4 class="chronicle-heading">II. Attributes</h4>';
    html += '<div class="chronicle-block">';
    html += renderSummaryTraits('Physical', ['strength', 'dexterity', 'stamina']);
    html += renderSummaryTraits('Social', ['charisma', 'manipulation', 'composure']);
    html += renderSummaryTraits('Mental', ['intelligence', 'wits', 'resolve']);
    html += '</div>';

    // Skills
    html += '<h4 class="chronicle-heading">III. Skills</h4>';
    html += '<div class="chronicle-block">';
    html += renderSummaryTraits('Physical', PHYSICAL_SKILLS);
    html += renderSummaryTraits('Social', SOCIAL_SKILLS);
    html += renderSummaryTraits('Mental', MENTAL_SKILLS);
    html += '</div>';

    // Disciplines (combined in-clan + predator bonus)
    html += '<h4 class="chronicle-heading">IV. Disciplines</h4>';
    html += '<div class="chronicle-block">';
    var combinedDiscs = {};
    Object.entries(disciplineValues).forEach(function (e) {
        if (e[1] > 0) combinedDiscs[e[0]] = e[1];
    });
    if (predatorDisciplineChoice) {
        combinedDiscs[predatorDisciplineChoice] = (combinedDiscs[predatorDisciplineChoice] || 0) + 1;
    }
    var combinedEntries = Object.entries(combinedDiscs);
    if (combinedEntries.length === 0) {
        html += '<p class="chronicle-empty">(none selected)</p>';
    } else {
        combinedEntries.forEach(function (e) {
            var annotation = '';
            if (predatorDisciplineChoice === e[0]) {
                annotation = ' <span style="color:var(--blood-primary);font-size:12px;">(includes +1 Predator)</span>';
            }
            html += '<p>' + escapeHtml(e[0]) + ': ' + renderPipString(e[1], 5) + annotation + '</p>';
        });
    }
    html += '</div>';

    // Advantages
    html += '<h4 class="chronicle-heading">V. Advantages</h4>';
    html += '<div class="chronicle-block">';
    const activeAdvs = Object.entries(advantageValues).filter(function (e) { return e[1].value > 0; });
    if (activeAdvs.length === 0) {
        html += '<p class="chronicle-empty">(none selected)</p>';
    } else {
        activeAdvs.forEach(function (e) {
            html += '<p>' + escapeHtml(e[0]) + ': ' + renderPipString(e[1].value, 5) + '</p>';
        });
    }
    html += '</div>';

    // Flaws
    html += '<h4 class="chronicle-heading">VI. Flaws</h4>';
    html += '<div class="chronicle-block">';
    const activeFlaws = Object.entries(flawValues).filter(function (e) { return e[1].value > 0; });
    if (activeFlaws.length === 0) {
        html += '<p class="chronicle-empty">(none taken)</p>';
    } else {
        activeFlaws.forEach(function (e) {
            html += '<p>' + escapeHtml(e[0]) + ': ' + renderPipString(e[1].value, 5) + '</p>';
        });
    }
    html += '</div>';

    html += '</div>';
    container.innerHTML = html;
}

/** Render a group of traits for the chronicle summary */
function renderSummaryTraits(groupLabel, traitList) {
    let html = '<p class="chronicle-group-label"><strong>' + groupLabel + '</strong></p>';
    traitList.forEach(function (trait) {
        const val = traitValues[trait] || 0;
        if (val > 0) {
            const label = trait.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
            html += '<p class="chronicle-trait">' + label + ': ' + renderPipString(val, 5) + '</p>';
        }
    });
    return html;
}

/** Render filled/empty pip symbols for summary display */
function renderPipString(value, max) {
    let s = '';
    for (let i = 0; i < max; i++) {
        s += i < value ? '\u25CF' : '\u25CB'; // filled circle / empty circle
    }
    return s;
}

// ============================================================
// DOT INITIALIZATION (Attributes & Skills)
// Fixed Bug 1: dot deselection via toggle
// ============================================================

function initializeDots() {
    // Match both old (.trait-dots) and new (.pip-row) containers
    document.querySelectorAll('.trait-dots, .pip-row').forEach(function (container) {
        const trait = container.dataset.trait;
        const category = container.dataset.category;
        const maxDots = 5;

        // Initialize trait value: attributes start at 1, skills start at 0
        traitValues[trait] = category.startsWith('skills') ? 0 : 1;

        // Create dot elements
        for (let i = 1; i <= maxDots; i++) {
            const dot = document.createElement('div');
            dot.classList.add(DOT_CLASS);
            // Also add legacy class for transition compatibility
            dot.classList.add('dot');
            if (i <= traitValues[trait]) {
                dot.classList.add('filled');
            }
            dot.dataset.value = i;

            dot.addEventListener('click', function () {
                const clickedValue = parseInt(this.dataset.value);
                const currentValue = traitValues[trait];
                const minValue = category.startsWith('skills') ? 0 : 1;

                // Toggle: clicking the current value resets to min
                if (clickedValue === currentValue) {
                    traitValues[trait] = minValue;
                    updateDots(container, minValue);
                } else {
                    traitValues[trait] = clickedValue;
                    updateDots(container, clickedValue);
                }
                updatePointsDisplay();
                validateForm();
            });

            container.appendChild(dot);
        }
    });

    updatePointsDisplay();
}

function updateDots(container, value) {
    container.querySelectorAll(DOT_SELECTOR).forEach(function (dot) {
        const dotValue = parseInt(dot.dataset.value);
        if (dotValue <= value) {
            dot.classList.add('filled');
        } else {
            dot.classList.remove('filled');
        }
    });
}

// ============================================================
// POINTS DISPLAY
// Fixed Bug 2: pool display emoji accumulation
// ============================================================

function updatePointsDisplay() {
    // Attributes (start at 1, so subtract base of 3 for 3 traits)
    const physicalSpent = ['strength', 'dexterity', 'stamina']
        .reduce(function (sum, trait) { return sum + traitValues[trait]; }, 0) - 3;
    const socialSpent = ['charisma', 'manipulation', 'composure']
        .reduce(function (sum, trait) { return sum + traitValues[trait]; }, 0) - 3;
    const mentalSpent = ['intelligence', 'wits', 'resolve']
        .reduce(function (sum, trait) { return sum + traitValues[trait]; }, 0) - 3;

    // Update attribute pool displays (clean rewrite — no innerHTML.replace)
    updatePoolDisplay('attr', 'physical', physicalSpent, getAttributePoolForCategory('physical'));
    updatePoolDisplay('attr', 'social', socialSpent, getAttributePoolForCategory('social'));
    updatePoolDisplay('attr', 'mental', mentalSpent, getAttributePoolForCategory('mental'));

    // Skills
    const physicalSkillsSpent = PHYSICAL_SKILLS.reduce(function (sum, trait) { return sum + (traitValues[trait] || 0); }, 0);
    const socialSkillsSpent = SOCIAL_SKILLS.reduce(function (sum, trait) { return sum + (traitValues[trait] || 0); }, 0);
    const mentalSkillsSpent = MENTAL_SKILLS.reduce(function (sum, trait) { return sum + (traitValues[trait] || 0); }, 0);

    // Update skill pool displays
    updatePoolDisplay('skill', 'physical', physicalSkillsSpent, getSkillPoolForCategory('physical'));
    updatePoolDisplay('skill', 'social', socialSkillsSpent, getSkillPoolForCategory('social'));
    updatePoolDisplay('skill', 'mental', mentalSkillsSpent, getSkillPoolForCategory('mental'));

    // Disciplines
    const disciplinesSpent = Object.values(disciplineValues).reduce(function (sum, val) { return sum + val; }, 0);
    const elDisc = document.getElementById('points-disciplines');
    if (elDisc) elDisc.textContent = disciplinesSpent;

    // Advantages
    const advantagesSpent = Object.values(advantageValues).reduce(function (sum, adv) { return sum + adv.value; }, 0);
    const elAdv = document.getElementById('points-advantages');
    if (elAdv) elAdv.textContent = advantagesSpent;

    // Flaws
    const flawsSpent = Object.values(flawValues).reduce(function (sum, flaw) { return sum + flaw.value; }, 0);
    const elFlaw = document.getElementById('points-flaws');
    if (elFlaw) elFlaw.textContent = flawsSpent;
}

/**
 * Set pool tracker innerHTML cleanly — fixes emoji accumulation bug.
 * Rewrites the entire content each call instead of using innerHTML.replace().
 */
function updatePoolDisplay(type, category, spent, max) {
    const trackerId = 'tracker-' + type + '-' + category;
    const tracker = document.getElementById(trackerId);
    if (!tracker) return;

    if (max === null) {
        tracker.className = '';
        return;
    }

    const label = category.charAt(0).toUpperCase() + category.slice(1);
    const isValid = spent === max;
    const indicator = isValid ? ' \u2713' : ' \u2717';
    tracker.className = isValid ? 'validation-success' : 'validation-error';

    // Build stable IDs for the spent/max spans
    var spentId, maxId;
    if (type === 'attr') {
        spentId = 'points-' + category;
        maxId = type + '-' + category + '-max';
    } else {
        spentId = 'points-skills-' + category;
        maxId = 'skill-' + category + '-max';
    }

    tracker.innerHTML = label + ':' + indicator +
        ' <span id="' + spentId + '">' + spent + '</span>' +
        '/<span id="' + maxId + '">' + max + '</span>';
}

// ============================================================
// PRIORITY SELECTORS
// ============================================================

function setupPrioritySelectors() {
    ['primary', 'secondary', 'tertiary'].forEach(function (level) {
        document.getElementById('attr-priority-' + level).addEventListener('change', function () {
            handleAttributePriorityChange(level, this.value);
        });
        document.getElementById('skill-priority-' + level).addEventListener('change', function () {
            handleSkillPriorityChange(level, this.value);
        });
    });
}

function handleAttributePriorityChange(level, category) {
    attributePriorities[level] = category || null;
    validatePrioritySelections('attr');
    updateAttributeMaxValues();
    updatePointsDisplay();
    validateForm();
}

function handleSkillPriorityChange(level, category) {
    skillPriorities[level] = category || null;
    validatePrioritySelections('skill');
    updateSkillMaxValues();
    updatePointsDisplay();
    validateForm();
}

function validatePrioritySelections(type) {
    const priorities = type === 'attr' ? attributePriorities : skillPriorities;
    const prefix = type === 'attr' ? 'attr' : 'skill';
    const selected = Object.values(priorities).filter(function (v) { return v !== null; });

    ['primary', 'secondary', 'tertiary'].forEach(function (level) {
        const select = document.getElementById(prefix + '-priority-' + level);
        const currentValue = priorities[level];

        Array.from(select.options).forEach(function (option) {
            if (option.value && option.value !== currentValue) {
                option.disabled = selected.includes(option.value);
            }
        });
    });
}

function getAttributePoolForCategory(category) {
    if (attributePriorities.primary === category) return 7;
    if (attributePriorities.secondary === category) return 5;
    if (attributePriorities.tertiary === category) return 3;
    return null;
}

function getSkillPoolForCategory(category) {
    if (skillPriorities.primary === category) return 13;
    if (skillPriorities.secondary === category) return 9;
    if (skillPriorities.tertiary === category) return 5;
    return null;
}

function updateAttributeMaxValues() {
    var el;
    el = document.getElementById('attr-physical-max');
    if (el) el.textContent = getAttributePoolForCategory('physical') ?? '?';
    el = document.getElementById('attr-social-max');
    if (el) el.textContent = getAttributePoolForCategory('social') ?? '?';
    el = document.getElementById('attr-mental-max');
    if (el) el.textContent = getAttributePoolForCategory('mental') ?? '?';

    var physPool = getAttributePoolForCategory('physical');
    var socPool = getAttributePoolForCategory('social');
    var menPool = getAttributePoolForCategory('mental');

    el = document.getElementById('attr-physical-pool');
    if (el) el.textContent = physPool ? '(' + physPool + ' dots)' : '';
    el = document.getElementById('attr-social-pool');
    if (el) el.textContent = socPool ? '(' + socPool + ' dots)' : '';
    el = document.getElementById('attr-mental-pool');
    if (el) el.textContent = menPool ? '(' + menPool + ' dots)' : '';
}

function updateSkillMaxValues() {
    var el;
    el = document.getElementById('skill-physical-max');
    if (el) el.textContent = getSkillPoolForCategory('physical') ?? '?';
    el = document.getElementById('skill-social-max');
    if (el) el.textContent = getSkillPoolForCategory('social') ?? '?';
    el = document.getElementById('skill-mental-max');
    if (el) el.textContent = getSkillPoolForCategory('mental') ?? '?';

    var physPool = getSkillPoolForCategory('physical');
    var socPool = getSkillPoolForCategory('social');
    var menPool = getSkillPoolForCategory('mental');

    el = document.getElementById('skill-physical-pool');
    if (el) el.textContent = physPool ? '(' + physPool + ' dots)' : '';
    el = document.getElementById('skill-social-pool');
    if (el) el.textContent = socPool ? '(' + socPool + ' dots)' : '';
    el = document.getElementById('skill-mental-pool');
    if (el) el.textContent = menPool ? '(' + menPool + ' dots)' : '';
}

// ============================================================
// CLAN SELECTOR
// ============================================================

function setupClanSelector() {
    document.getElementById('clan').addEventListener('change', function () {
        const clanInfo = document.getElementById('clan-info');
        const selectedClan = this.value;

        if (selectedClan && CLANS[selectedClan]) {
            const clan = CLANS[selectedClan];
            let html = '<strong>' + escapeHtml(selectedClan) + '</strong><br>';
            if (clan.disciplines.length > 0) {
                html += '<strong>Disciplines:</strong> ' + clan.disciplines.join(', ') + '<br>';
            } else {
                html += '<strong>Disciplines:</strong> Choose any 2 disciplines at character creation<br>';
            }
            html += '<strong>Bane:</strong> ' + escapeHtml(clan.bane);
            clanInfo.innerHTML = html;
            clanInfo.style.display = 'block';

            // Reset discipline allocations on clan change
            const hasAllocatedDots = Object.values(disciplineValues).some(function (v) { return v > 0; });
            if (hasAllocatedDots) {
                if (confirm('Changing clans will reset your discipline allocations. Continue?')) {
                    Object.keys(disciplineValues).forEach(function (k) { delete disciplineValues[k]; });
                } else {
                    // Revert clan selection — find previous clan from disciplineValues
                    return;
                }
            }

            // Re-render disciplines if they're already loaded
            if (disciplinesData.length > 0) {
                renderDisciplines();
            }
        } else {
            clanInfo.style.display = 'none';
        }
    });
}

// ============================================================
// PREDATOR TYPE SELECTOR
// ============================================================

function setupPredatorTypeSelector() {
    var predatorSelect = document.getElementById('predator_type');
    var choiceDiv = document.getElementById('predator-discipline-choice');
    var optionsDiv = document.getElementById('predator-discipline-options');

    predatorSelect.addEventListener('change', function () {
        var predatorType = this.value;
        if (!predatorType || !PREDATOR_TYPES[predatorType]) {
            choiceDiv.style.display = 'none';
            predatorDisciplineChoice = null;
            optionsDiv.innerHTML = '';
            renderDisciplines();
            validateForm();
            return;
        }

        var disciplines = PREDATOR_TYPES[predatorType];
        predatorDisciplineChoice = null;
        var html = '';
        disciplines.forEach(function (disc) {
            html += '<label style="display:inline-flex;align-items:center;gap:6px;margin-right:16px;cursor:pointer;' +
                'font-family:var(--font-ui);font-size:14px;color:var(--text-primary);">' +
                '<input type="radio" name="predator-disc" value="' + escapeHtml(disc) + '" ' +
                'style="accent-color:var(--blood-primary);width:16px;height:16px;">' +
                escapeHtml(disc) + '</label>';
        });
        optionsDiv.innerHTML = html;
        choiceDiv.style.display = 'block';

        optionsDiv.querySelectorAll('input[name="predator-disc"]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                predatorDisciplineChoice = this.value;
                renderDisciplines();
                validateForm();
            });
        });

        renderDisciplines();
        validateForm();
    });
}

// ============================================================
// TRAIT DATA LOADING (API)
// ============================================================

async function loadTraitData() {
    try {
        const [disciplinesResponse, advantagesResponse, flawsResponse] = await Promise.all([
            fetch('/api/traits/?category=disciplines'),
            fetch('/api/traits/?category=advantages'),
            fetch('/api/traits/?category=flaws')
        ]);

        if (!disciplinesResponse.ok || !advantagesResponse.ok || !flawsResponse.ok) {
            throw new Error('Failed to load trait data');
        }

        const disciplinesJson = await disciplinesResponse.json();
        const advantagesJson = await advantagesResponse.json();
        const flawsJson = await flawsResponse.json();

        disciplinesData = disciplinesJson.traits;
        advantagesData = advantagesJson.traits;
        flawsData = flawsJson.traits;

        renderDisciplines();
        renderAdvantages();
        renderFlaws();
        return true;

    } catch (error) {
        console.error('Error loading trait data:', error);
        showToast('Error loading trait data: ' + error.message, 'danger');
        return false;
    }
}

// ============================================================
// RENDER DISCIPLINES
// V5 rules: in-clan only (2+1), predator bonus shown separately
// ============================================================

function renderDisciplines() {
    const container = document.getElementById('disciplines-container');
    const selectedClan = document.getElementById('clan').value;
    const inClanDisciplines = selectedClan && CLANS[selectedClan] ? CLANS[selectedClan].disciplines : [];
    const isCaitiff = selectedClan === 'Caitiff';

    // Clear discipline values for disciplines no longer in-clan (unless Caitiff)
    if (!isCaitiff && inClanDisciplines.length > 0) {
        Object.keys(disciplineValues).forEach(function (k) {
            if (!inClanDisciplines.includes(k) && disciplineValues[k] > 0) {
                disciplineValues[k] = 0;
            }
        });
    }

    // Determine which disciplines to show
    var visibleDisciplines;
    if (isCaitiff || !selectedClan || !CLANS[selectedClan]) {
        // Caitiff or no clan: show all disciplines
        visibleDisciplines = disciplinesData;
    } else {
        // Non-Caitiff: show only in-clan disciplines
        visibleDisciplines = disciplinesData.filter(function (d) {
            return inClanDisciplines.includes(d.name);
        });
    }

    // Check if predator discipline is out-of-clan
    var predatorIsOutOfClan = false;
    if (predatorDisciplineChoice && !isCaitiff && inClanDisciplines.length > 0) {
        predatorIsOutOfClan = !inClanDisciplines.includes(predatorDisciplineChoice);
    }

    let html = '<div class="trait-group">';

    visibleDisciplines.forEach(function (discipline) {
        var isPredatorBonus = predatorDisciplineChoice === discipline.name;
        var labelExtra = '';
        if (isPredatorBonus && !predatorIsOutOfClan) {
            labelExtra = ' <span style="color:var(--blood-primary);font-size:12px;">(+1 from Predator Type)</span>';
        }

        html += '<div class="trait-row">' +
            '<span class="trait-label in-clan">' + escapeHtml(discipline.name) + ' \u2605' + labelExtra + '</span>' +
            '<div class="pip-row trait-dots" data-trait="' + escapeHtml(discipline.name) + '" data-category="disciplines"></div>' +
            '</div>';
    });

    // Out-of-clan predator discipline: read-only row
    if (predatorIsOutOfClan && predatorDisciplineChoice) {
        html += '<div class="trait-row" style="opacity:0.8;">' +
            '<span class="trait-label" style="color:var(--blood-primary);">' +
            escapeHtml(predatorDisciplineChoice) + ' <span style="font-size:12px;">(Predator Type)</span></span>' +
            '<div class="pip-row" data-category="predator-readonly">';
        // 1 filled dot + 2 empty dots (read-only)
        for (var p = 1; p <= 3; p++) {
            html += '<div class="' + DOT_CLASS + ' dot' + (p <= 1 ? ' filled' : '') + '" style="pointer-events:none;"></div>';
        }
        html += '</div></div>';
    }

    html += '</div>';
    container.innerHTML = html;

    // Initialize interactive discipline dots
    container.querySelectorAll('.pip-row[data-category="disciplines"]').forEach(function (dotsContainer) {
        const trait = dotsContainer.dataset.trait;
        disciplineValues[trait] = disciplineValues[trait] || 0;

        for (let i = 1; i <= 3; i++) {
            const dot = document.createElement('div');
            dot.classList.add(DOT_CLASS);
            dot.classList.add('dot');
            if (i <= disciplineValues[trait]) {
                dot.classList.add('filled');
            }
            dot.dataset.value = i;

            dot.addEventListener('click', function () {
                const clickedValue = parseInt(this.dataset.value);
                const currentValue = disciplineValues[trait];

                // Toggle: clicking the current value resets to 0
                if (clickedValue === currentValue) {
                    disciplineValues[trait] = 0;
                    updateDots(dotsContainer, 0);
                } else {
                    disciplineValues[trait] = clickedValue;
                    updateDots(dotsContainer, clickedValue);
                }
                updatePointsDisplay();
                validateForm();
            });

            dotsContainer.appendChild(dot);
        }
    });

    updatePointsDisplay();
}

// ============================================================
// RENDER ADVANTAGES
// Fixed Bug 1: dot toggle deselection for advantages
// ============================================================

function renderAdvantages() {
    const container = document.getElementById('advantages-container');

    let html = '<div class="trait-group">';

    advantagesData.forEach(function (advantage) {
        const needsInstance = advantage.is_instanced || false;
        const needsSpecialty = advantage.has_specialties || false;

        html += '<div class="trait-row-with-input">' +
            '<span class="trait-label">' + escapeHtml(advantage.name) + '</span>' +
            '<div class="pip-row trait-dots" data-trait="' + escapeHtml(advantage.name) + '" data-category="advantages"></div>';

        if (needsInstance) {
            html += '<input type="text" class="codex-input trait-instance-input"' +
                ' id="advantage-instance-' + advantage.name.replace(/\s+/g, '_') + '"' +
                ' placeholder="Specify instance...">';
        } else if (needsSpecialty) {
            html += '<input type="text" class="codex-input trait-specialty-input"' +
                ' id="advantage-specialty-' + advantage.name.replace(/\s+/g, '_') + '"' +
                ' placeholder="Specify specialty...">';
        }

        html += '</div>';
    });

    html += '</div>';
    container.innerHTML = html;

    // Initialize advantage dots
    container.querySelectorAll('.pip-row, .trait-dots').forEach(function (dotsContainer) {
        const trait = dotsContainer.dataset.trait;
        if (dotsContainer.dataset.category !== 'advantages') return;
        advantageValues[trait] = advantageValues[trait] || { value: 0 };

        for (let i = 1; i <= 5; i++) {
            const dot = document.createElement('div');
            dot.classList.add(DOT_CLASS);
            dot.classList.add('dot');
            if (i <= advantageValues[trait].value) {
                dot.classList.add('filled');
            }
            dot.dataset.value = i;

            dot.addEventListener('click', function () {
                const clickedValue = parseInt(this.dataset.value);
                const currentValue = advantageValues[trait].value;

                // Toggle: clicking the current value resets to 0
                if (clickedValue === currentValue) {
                    advantageValues[trait].value = 0;
                    updateDots(dotsContainer, 0);
                } else {
                    advantageValues[trait].value = clickedValue;
                    updateDots(dotsContainer, clickedValue);
                }
                updatePointsDisplay();
                validateForm();
            });

            dotsContainer.appendChild(dot);
        }
    });

    restoreTraitDetails('advantage', advantageValues);
    updatePointsDisplay();
}

// ============================================================
// RENDER FLAWS
// Fixed Bug 1: dot toggle deselection for flaws
// ============================================================

function renderFlaws() {
    const container = document.getElementById('flaws-container');

    let html = '<div class="trait-group">';

    flawsData.forEach(function (flaw) {
        const needsInstance = flaw.is_instanced || false;
        const needsSpecialty = flaw.has_specialties || false;

        html += '<div class="trait-row-with-input">' +
            '<span class="trait-label">' + escapeHtml(flaw.name) + '</span>' +
            '<div class="pip-row trait-dots" data-trait="' + escapeHtml(flaw.name) + '" data-category="flaws"></div>';

        if (needsInstance) {
            html += '<input type="text" class="codex-input trait-instance-input"' +
                ' id="flaw-instance-' + flaw.name.replace(/\s+/g, '_') + '"' +
                ' placeholder="Specify instance...">';
        } else if (needsSpecialty) {
            html += '<input type="text" class="codex-input trait-specialty-input"' +
                ' id="flaw-specialty-' + flaw.name.replace(/\s+/g, '_') + '"' +
                ' placeholder="Specify specialty...">';
        }

        html += '</div>';
    });

    html += '</div>';
    container.innerHTML = html;

    // Initialize flaw dots
    container.querySelectorAll('.pip-row, .trait-dots').forEach(function (dotsContainer) {
        const trait = dotsContainer.dataset.trait;
        if (dotsContainer.dataset.category !== 'flaws') return;
        flawValues[trait] = flawValues[trait] || { value: 0 };

        for (let i = 1; i <= 5; i++) {
            const dot = document.createElement('div');
            dot.classList.add(DOT_CLASS);
            dot.classList.add('dot');
            if (i <= flawValues[trait].value) {
                dot.classList.add('filled');
            }
            dot.dataset.value = i;

            dot.addEventListener('click', function () {
                const clickedValue = parseInt(this.dataset.value);
                const currentValue = flawValues[trait].value;

                // Toggle: clicking the current value resets to 0
                if (clickedValue === currentValue) {
                    flawValues[trait].value = 0;
                    updateDots(dotsContainer, 0);
                } else {
                    flawValues[trait].value = clickedValue;
                    updateDots(dotsContainer, clickedValue);
                }
                updatePointsDisplay();
                validateForm();
            });

            dotsContainer.appendChild(dot);
        }
    });

    restoreTraitDetails('flaw', flawValues);
    updatePointsDisplay();
}

function restoreTraitDetails(prefix, values) {
    Object.entries(values).forEach(function ([name, data]) {
        ['instance', 'specialty'].forEach(function (field) {
            const input = document.getElementById(prefix + '-' + field + '-' + name.replace(/\s+/g, '_'));
            if (!input) return;
            input.value = data[field] || '';
            input.addEventListener('input', function () { values[name][field] = this.value; });
        });
    });
}

// ============================================================
// FORM VALIDATION
// Fixed Bug 3: tracker innerHTML accumulation
// ============================================================

function validateForm() {
    const errors = [];
    if (editLoadError) errors.push(editLoadError);

    // Validate attribute priorities
    if (!attributePriorities.primary || !attributePriorities.secondary || !attributePriorities.tertiary) {
        errors.push('You must assign all attribute priorities (Primary, Secondary, Tertiary)');
    } else {
        const physicalSpent = ['strength', 'dexterity', 'stamina']
            .reduce(function (sum, trait) { return sum + traitValues[trait]; }, 0) - 3;
        const socialSpent = ['charisma', 'manipulation', 'composure']
            .reduce(function (sum, trait) { return sum + traitValues[trait]; }, 0) - 3;
        const mentalSpent = ['intelligence', 'wits', 'resolve']
            .reduce(function (sum, trait) { return sum + traitValues[trait]; }, 0) - 3;

        const physicalMax = getAttributePoolForCategory('physical');
        const socialMax = getAttributePoolForCategory('social');
        const mentalMax = getAttributePoolForCategory('mental');

        if (physicalSpent !== physicalMax) {
            errors.push('Physical Attributes: Must spend exactly ' + physicalMax + ' dots (currently ' + physicalSpent + ')');
        }
        if (socialSpent !== socialMax) {
            errors.push('Social Attributes: Must spend exactly ' + socialMax + ' dots (currently ' + socialSpent + ')');
        }
        if (mentalSpent !== mentalMax) {
            errors.push('Mental Attributes: Must spend exactly ' + mentalMax + ' dots (currently ' + mentalSpent + ')');
        }
    }

    // Validate skill priorities
    if (!skillPriorities.primary || !skillPriorities.secondary || !skillPriorities.tertiary) {
        errors.push('You must assign all skill priorities (Primary, Secondary, Tertiary)');
    } else {
        const physicalSkillsSpent = PHYSICAL_SKILLS.reduce(function (sum, trait) { return sum + (traitValues[trait] || 0); }, 0);
        const socialSkillsSpent = SOCIAL_SKILLS.reduce(function (sum, trait) { return sum + (traitValues[trait] || 0); }, 0);
        const mentalSkillsSpent = MENTAL_SKILLS.reduce(function (sum, trait) { return sum + (traitValues[trait] || 0); }, 0);

        const physicalSkillMax = getSkillPoolForCategory('physical');
        const socialSkillMax = getSkillPoolForCategory('social');
        const mentalSkillMax = getSkillPoolForCategory('mental');

        if (physicalSkillsSpent !== physicalSkillMax) {
            errors.push('Physical Skills: Must spend exactly ' + physicalSkillMax + ' dots (currently ' + physicalSkillsSpent + ')');
        }
        if (socialSkillsSpent !== socialSkillMax) {
            errors.push('Social Skills: Must spend exactly ' + socialSkillMax + ' dots (currently ' + socialSkillsSpent + ')');
        }
        if (mentalSkillsSpent !== mentalSkillMax) {
            errors.push('Mental Skills: Must spend exactly ' + mentalSkillMax + ' dots (currently ' + mentalSkillsSpent + ')');
        }
    }

    // Validate disciplines
    const selectedClan = document.getElementById('clan').value;
    const disciplinesSpent = Object.values(disciplineValues).reduce(function (sum, val) { return sum + val; }, 0);

    if (disciplinesSpent !== 3) {
        errors.push('Disciplines: Must spend exactly 3 dots (currently ' + disciplinesSpent + ')');
    } else if (selectedClan && CLANS[selectedClan]) {
        const inClanDisciplines = CLANS[selectedClan].disciplines;
        if (inClanDisciplines.length > 0) {
            // Non-Caitiff: enforce 2+1 pattern, all in-clan
            const activeDiscs = Object.entries(disciplineValues).filter(function (e) { return e[1] > 0; });
            if (activeDiscs.length !== 2) {
                errors.push('Disciplines: Must allocate dots in exactly 2 in-clan disciplines (2 dots in one, 1 in another)');
            } else {
                const values = activeDiscs.map(function (e) { return e[1]; }).sort();
                if (values[0] !== 1 || values[1] !== 2) {
                    errors.push('Disciplines: Must allocate 2 dots in one discipline and 1 dot in another');
                }
                var allInClan = activeDiscs.every(function (e) { return inClanDisciplines.includes(e[0]); });
                if (!allInClan) {
                    errors.push('Disciplines: All allocated dots must be in in-clan disciplines');
                }
            }
        } else if (selectedClan === 'Caitiff') {
            // Caitiff: 3 total, at least 2 different disciplines
            const caitiffActive = Object.entries(disciplineValues).filter(function (e) { return e[1] > 0; });
            if (caitiffActive.length < 2) {
                errors.push('Disciplines: Must allocate dots across at least 2 different disciplines');
            }
        }
    }

    // Validate predator discipline choice
    var predType = document.getElementById('predator_type').value;
    if (predType && PREDATOR_TYPES[predType] && !predatorDisciplineChoice) {
        errors.push('Disciplines: Must choose a predator discipline bonus (in the Identity tab)');
    }

    // Validate advantages
    const advantagesSpent = Object.values(advantageValues).reduce(function (sum, adv) { return sum + adv.value; }, 0);
    if (advantagesSpent !== 7) {
        errors.push('Advantages: Must spend exactly 7 points (currently ' + advantagesSpent + ')');
    }

    // Validate flaws
    const flawsSpent = Object.values(flawValues).reduce(function (sum, flaw) { return sum + flaw.value; }, 0);
    if (flawsSpent > 2) {
        errors.push('Flaws: Cannot exceed 2 points (currently ' + flawsSpent + ')');
    }

    // -- Fixed Bug 3: rewrite tracker innerHTML cleanly instead of replace --

    // Disciplines tracker
    const trackerDisc = document.getElementById('tracker-disciplines');
    if (trackerDisc) {
        const discValid = disciplinesSpent === 3;
        var predIndicator = '';
        if (predatorDisciplineChoice) {
            predIndicator = ' + 1 ' + escapeHtml(predatorDisciplineChoice);
        }
        trackerDisc.className = discValid ? 'validation-success' : 'validation-error';
        trackerDisc.innerHTML = '<span id="points-disciplines">' + disciplinesSpent + '</span>/3 in-clan' +
            ' <span id="predator-disc-indicator">' + predIndicator + '</span> ' + (discValid ? '\u2713' : '\u2717');
    }

    // Advantages tracker
    const trackerAdv = document.getElementById('tracker-advantages');
    if (trackerAdv) {
        const advValid = advantagesSpent === 7;
        trackerAdv.className = advValid ? 'validation-success' : 'validation-error';
        trackerAdv.innerHTML = '<span id="points-advantages">' + advantagesSpent + '</span>/7 points ' + (advValid ? '\u2713' : '\u2717');
    }

    // Flaws tracker
    const trackerFlaws = document.getElementById('tracker-flaws');
    if (trackerFlaws) {
        const flawValid = flawsSpent <= 2;
        trackerFlaws.className = flawValid ? 'validation-success' : 'validation-error';
        trackerFlaws.innerHTML = '<span id="points-flaws">' + flawsSpent + '</span>/2 points ' + (flawValid ? '\u2713' : '\u2717');
    }

    // Display errors or hide error section
    const errorSection = document.getElementById('validation-errors');
    const errorList = document.getElementById('error-list-items');
    const submitButton = document.getElementById('submit-button');

    if (errors.length > 0) {
        if (errorList) errorList.innerHTML = errors.map(function (err) { return '<li>' + escapeHtml(err) + '</li>'; }).join('');
        if (errorSection) errorSection.style.display = 'block';
        if (submitButton) submitButton.disabled = true;
    } else {
        if (errorSection) errorSection.style.display = 'none';
        if (submitButton) submitButton.disabled = false;
    }

    // Update tab completion indicators
    updateTabCompletion();

    return errors.length === 0;
}

// ============================================================
// FORM SUBMISSION
// ============================================================

function setupFormSubmit() {
    document.getElementById('character-form').addEventListener('submit', async function (e) {
        e.preventDefault();

        if (!validateForm()) {
            showToast('Please fix all validation errors before submitting', 'danger');
            return;
        }

        // Build character data
        const character_data = {
            name: document.getElementById('full_name').value,
            concept: document.getElementById('concept').value,
            clan: document.getElementById('clan').value,
            sire: document.getElementById('sire').value,
            generation: parseInt(document.getElementById('generation').value) || null,
            predator_type: document.getElementById('predator_type').value,
            ambition: document.getElementById('ambition').value,
            desire: document.getElementById('desire').value,
            background: document.getElementById('background').value,
            splat: 'vampire'
        };

        // Add basic traits (attributes and skills)
        for (const [trait, value] of Object.entries(traitValues)) {
            character_data[trait] = value;
        }

        // Add disciplines (merge in-clan allocations + predator bonus)
        const disciplines = {};
        for (const [discipline, value] of Object.entries(disciplineValues)) {
            if (value > 0) {
                disciplines[discipline] = value;
            }
        }
        // Merge predator discipline bonus
        if (predatorDisciplineChoice) {
            disciplines[predatorDisciplineChoice] = (disciplines[predatorDisciplineChoice] || 0) + 1;
            character_data.predator_discipline = predatorDisciplineChoice;
        }
        character_data.disciplines = disciplines;
        // These saved selections have no editor in this form. Preserve them
        // explicitly; the backend checks them against any changed trait levels.
        character_data.specialties = JSON.parse(JSON.stringify(retainedSelections.specialties));
        character_data.discipline_powers = retainedSelections.discipline_powers.slice();

        // Add advantages with instance/specialty data
        const advantages = {};
        for (const [advantage, data] of Object.entries(advantageValues)) {
            if (data.value > 0) {
                const advantageData = { value: data.value };

                const instanceInput = document.getElementById('advantage-instance-' + advantage.replace(/\s+/g, '_'));
                const instance = instanceInput ? instanceInput.value : data.instance;
                if (instance) {
                    advantageData.instance = instance;
                }

                const specialtyInput = document.getElementById('advantage-specialty-' + advantage.replace(/\s+/g, '_'));
                const specialty = specialtyInput ? specialtyInput.value : data.specialty;
                if (specialty) {
                    advantageData.specialty = specialty;
                }

                advantages[advantage] = advantageData;
            }
        }
        character_data.advantages = advantages;

        // Add flaws with instance/specialty data
        const flaws = {};
        for (const [flaw, data] of Object.entries(flawValues)) {
            if (data.value > 0) {
                const flawData = { value: data.value };

                const instanceInput = document.getElementById('flaw-instance-' + flaw.replace(/\s+/g, '_'));
                const instance = instanceInput ? instanceInput.value : data.instance;
                if (instance) {
                    flawData.instance = instance;
                }

                const specialtyInput = document.getElementById('flaw-specialty-' + flaw.replace(/\s+/g, '_'));
                const specialty = specialtyInput ? specialtyInput.value : data.specialty;
                if (specialty) {
                    flawData.specialty = specialty;
                }

                flaws[flaw] = flawData;
            }
        }
        character_data.flaws = flaws;

        const payload = { character_data: character_data };

        try {
            let url, successMsg;

            if (isEditMode && editCharacterId) {
                url = '/api/traits/character/' + editCharacterId + '/resubmit/';
                successMsg = 'Character resubmitted for approval!';
            } else {
                url = '/api/traits/character/create/';
                successMsg = 'Character submitted for approval!';
            }

            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRF_TOKEN
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(function () { return {}; });
                throw new Error(errorData.error || 'Failed to submit character');
            }

            await response.json();

            clearDraft();
            showToast(successMsg, 'success');

            setTimeout(function () {
                window.location.href = '/';
            }, 2000);

        } catch (error) {
            console.error('Error submitting character:', error);
            showToast('Error: ' + error.message, 'danger');
        }
    });
}

// ============================================================
// EDIT MODE (rejection resubmission)
// ============================================================

async function loadCharacterForEdit(charId) {
    retainedSelections = { specialties: {}, discipline_powers: [] };
    editLoadError = 'Character data is loading.';
    validateForm();
    try {
        const response = await fetch('/api/traits/character/' + charId + '/for-edit/', {
            headers: {
                'X-CSRFToken': CSRF_TOKEN
            }
        });
        if (!response.ok) {
            const err = await response.json().catch(function () { return {}; });
            throw new Error('Cannot edit: ' + (err.error || 'Unknown error'));
        }
        const data = await response.json();

        if (data.rejection_notes) {
            showRejectionBanner(data.rejection_notes, data.rejection_count);
        }

        populateFormFromCharacterData(data.character_data);
        editLoadError = null;
        validateForm();

        const submitBtn = document.getElementById('submit-button');
        if (submitBtn) {
            submitBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Resubmit Character';
        }

        const titleEl = document.getElementById('page-title');
        if (titleEl) {
            titleEl.innerHTML = '<i class="bi bi-pencil-square" style="color: var(--builder-accent-light);"></i> Edit & Resubmit Character';
        }
    } catch (err) {
        console.error('Error loading character for edit:', err);
        editLoadError = err.message || 'Failed to load character data. Reload this page before editing.';
        validateForm();
        alert(editLoadError);
    }
}

function showRejectionBanner(notes, count) {
    const banner = document.createElement('div');
    banner.className = 'alert alert-danger mb-4';
    banner.id = 'rejection-banner';
    banner.innerHTML =
        '<h5 class="alert-heading">Character Requires Revisions</h5>' +
        '<p><strong>Staff feedback:</strong></p>' +
        '<p style="white-space: pre-wrap;">' + escapeHtml(notes) + '</p>' +
        '<hr>' +
        '<small>This character has been rejected ' + count + ' time(s). Please address the feedback and resubmit.</small>';
    const form = document.getElementById('character-form');
    if (form) {
        form.insertBefore(banner, form.firstChild);
    }
}

function populateFormFromCharacterData(data) {
    const selections = validatedSavedSelections(data);
    // The canonical form has one row per trait. Refuse to collapse legacy
    // multiple-instance records into that row and silently lose saved data.
    const details = {};
    ['advantages', 'flaws'].forEach(function (category) {
        details[category] = {};
        Object.entries(data[category] || {}).forEach(function ([name, saved]) {
            if (Array.isArray(saved)) {
                if (saved.length !== 1) {
                    throw new Error('This character has multiple saved instances of ' + name +
                        '. Please contact staff for help editing it without losing data.');
                }
                saved = saved[0];
            }
            details[category][name] = typeof saved === 'number' ? { value: saved } : Object.assign({}, saved);
        });
    });
    [disciplineValues, advantageValues, flawValues].forEach(function (values) {
        Object.keys(values).forEach(function (name) { delete values[name]; });
    });
    retainedSelections = selections;
    // Set simple bio fields
    if (data.full_name) document.getElementById('full_name').value = data.full_name;
    if (data.concept) document.getElementById('concept').value = data.concept;
    if (data.ambition) document.getElementById('ambition').value = data.ambition;
    if (data.desire) document.getElementById('desire').value = data.desire;
    if (data.background) document.getElementById('background').value = data.background;
    if (data.sire) document.getElementById('sire').value = data.sire;

    // Set select fields
    if (data.clan) {
        document.getElementById('clan').value = data.clan;
        document.getElementById('clan').dispatchEvent(new Event('change'));
    }
    if (data.generation) {
        document.getElementById('generation').value = String(data.generation);
    }
    if (data.predator_type) {
        document.getElementById('predator_type').value = data.predator_type;
        document.getElementById('predator_type').dispatchEvent(new Event('change'));
    }
    predatorDisciplineChoice = data.predator_discipline || null;
    if (predatorDisciplineChoice) {
        const radio = document.querySelector('input[name="predator-disc"][value="' + predatorDisciplineChoice + '"]');
        if (radio) radio.checked = true;
    }

    // Set attributes
    const attrMap = data.attributes || {};
    for (const [traitName, rating] of Object.entries(attrMap)) {
        const lowerName = traitName.trim().toLowerCase().replace(/\s+/g, '_');
        if (traitValues.hasOwnProperty(lowerName)) {
            traitValues[lowerName] = rating;
            const dotsContainer = document.querySelector('.trait-dots[data-trait="' + lowerName + '"], .pip-row[data-trait="' + lowerName + '"]');
            if (dotsContainer) {
                updateDots(dotsContainer, rating);
            }
        }
    }

    // Set skills
    const skillMap = data.skills || {};
    for (const [traitName, rating] of Object.entries(skillMap)) {
        const lowerName = traitName.trim().toLowerCase().replace(/\s+/g, '_');
        if (traitValues.hasOwnProperty(lowerName)) {
            traitValues[lowerName] = rating;
            const dotsContainer = document.querySelector('.trait-dots[data-trait="' + lowerName + '"], .pip-row[data-trait="' + lowerName + '"]');
            if (dotsContainer) {
                updateDots(dotsContainer, rating);
            }
        }
    }

    // Set disciplines
    const discMap = data.disciplines || {};
    for (const [discName, rating] of Object.entries(discMap)) {
        disciplineValues[discName] = rating - (discName === predatorDisciplineChoice ? 1 : 0);
    }

    // Set advantages
    Object.assign(advantageValues, details.advantages);

    // Set flaws
    Object.assign(flawValues, details.flaws);

    restorePrioritiesFromTotals('attr', {
        physical: ['strength', 'dexterity', 'stamina'],
        social: ['charisma', 'manipulation', 'composure'],
        mental: ['intelligence', 'wits', 'resolve']
    }, [7, 5, 3], 3);
    restorePrioritiesFromTotals('skill', {
        physical: PHYSICAL_SKILLS, social: SOCIAL_SKILLS, mental: MENTAL_SKILLS
    }, [13, 9, 5], 0);

    renderDisciplines();
    renderAdvantages();
    renderFlaws();

    // Re-render dynamic sections so dots update
    document.querySelectorAll('#disciplines-container .trait-dots, #disciplines-container .pip-row').forEach(function (dotsContainer) {
        const trait = dotsContainer.dataset.trait;
        if (disciplineValues[trait]) {
            updateDots(dotsContainer, disciplineValues[trait]);
        }
    });
    document.querySelectorAll('#advantages-container .trait-dots, #advantages-container .pip-row').forEach(function (dotsContainer) {
        const trait = dotsContainer.dataset.trait;
        if (advantageValues[trait]) {
            updateDots(dotsContainer, advantageValues[trait].value);
        }
    });
    document.querySelectorAll('#flaws-container .trait-dots, #flaws-container .pip-row').forEach(function (dotsContainer) {
        const trait = dotsContainer.dataset.trait;
        if (flawValues[trait]) {
            updateDots(dotsContainer, flawValues[trait].value);
        }
    });

    updatePointsDisplay();
    validateForm();
}

function restorePrioritiesFromTotals(type, groups, budgets, base) {
    const priorities = type === 'attr' ? attributePriorities : skillPriorities;
    const totals = {};
    Object.entries(groups).forEach(function ([category, traits]) {
        totals[category] = traits.reduce(function (sum, trait) { return sum + (traitValues[trait] || 0); }, 0) - base;
    });
    ['primary', 'secondary', 'tertiary'].forEach(function (level, index) {
        const matches = Object.keys(totals).filter(function (category) { return totals[category] === budgets[index]; });
        priorities[level] = matches.length === 1 ? matches[0] : null;
        document.getElementById(type + '-priority-' + level).value = priorities[level] || '';
    });
    validatePrioritySelections(type);
    if (type === 'attr') updateAttributeMaxValues();
    else updateSkillMaxValues();
}

function validatedSavedSelections(data) {
    const specialties = data.specialties === undefined ? {} : data.specialties;
    const powers = data.discipline_powers === undefined ? [] : data.discipline_powers;
    const objectMap = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    if (!objectMap(specialties) || !Array.isArray(powers) ||
        powers.some(name => typeof name !== 'string' || !name.trim())) {
        throw new Error('Saved specialties or discipline powers cannot be safely restored. Please contact staff for help.');
    }
    for (const [skill, values] of Object.entries(specialties)) {
        if (!skill.trim() || !objectMap(values) || Object.entries(values).some(function ([name, rating]) {
            return !name.trim() || name.length > 100 || !Number.isInteger(rating) || rating < 1 || rating > 5;
        })) {
            throw new Error('Saved specialties cannot be safely restored. Please contact staff for help.');
        }
    }
    return { specialties: JSON.parse(JSON.stringify(specialties)), discipline_powers: powers.slice() };
}

// ============================================================
// DRAFT SAVE / RESUME (localStorage persistence)
// ============================================================

function getDraftKey() {
    return isEditMode ? 'chargen_draft_' + editCharacterId : 'chargen_draft_new';
}

function saveDraft() {
    try {
        const draft = {
            full_name: document.getElementById('full_name').value,
            concept: document.getElementById('concept').value,
            clan: document.getElementById('clan').value,
            sire: document.getElementById('sire').value,
            generation: document.getElementById('generation').value,
            predator_type: document.getElementById('predator_type').value,
            ambition: document.getElementById('ambition').value,
            desire: document.getElementById('desire').value,
            background: document.getElementById('background').value,
            traitValues: Object.assign({}, traitValues),
            disciplineValues: Object.assign({}, disciplineValues),
            advantageValues: JSON.parse(JSON.stringify(advantageValues)),
            flawValues: JSON.parse(JSON.stringify(flawValues)),
            attributePriorities: Object.assign({}, attributePriorities),
            skillPriorities: Object.assign({}, skillPriorities),
            predatorDisciplineChoice: predatorDisciplineChoice,
            specialties: JSON.parse(JSON.stringify(retainedSelections.specialties)),
            discipline_powers: retainedSelections.discipline_powers.slice(),
            savedAt: new Date().toISOString()
        };
        localStorage.setItem(getDraftKey(), JSON.stringify(draft));
    } catch (e) {
        console.warn('Draft save failed:', e);
    }
}

function loadDraft() {
    try {
        const saved = localStorage.getItem(getDraftKey());
        if (!saved) return;
        const draft = JSON.parse(saved);
        const savedDate = new Date(draft.savedAt);
        const ageMinutes = (Date.now() - savedDate.getTime()) / 60000;
        // Don't offer drafts older than 7 days
        if (ageMinutes > 10080) {
            localStorage.removeItem(getDraftKey());
            return;
        }
        if (confirm('Resume draft from ' + savedDate.toLocaleString() + '?')) {
            applyDraftToForm(draft);
        } else {
            localStorage.removeItem(getDraftKey());
        }
    } catch (e) {
        console.warn('Draft load failed:', e);
    }
}

function applyDraftToForm(draft) {
    retainedSelections = validatedSavedSelections(draft);
    // Restore simple form fields
    if (draft.full_name) document.getElementById('full_name').value = draft.full_name;
    if (draft.concept) document.getElementById('concept').value = draft.concept;
    if (draft.sire) document.getElementById('sire').value = draft.sire;
    if (draft.ambition) document.getElementById('ambition').value = draft.ambition;
    if (draft.desire) document.getElementById('desire').value = draft.desire;
    if (draft.background) document.getElementById('background').value = draft.background;

    // Restore selects
    if (draft.clan) {
        document.getElementById('clan').value = draft.clan;
        document.getElementById('clan').dispatchEvent(new Event('change'));
    }
    if (draft.generation) {
        document.getElementById('generation').value = draft.generation;
    }
    if (draft.predator_type) {
        document.getElementById('predator_type').value = draft.predator_type;
        document.getElementById('predator_type').dispatchEvent(new Event('change'));
    }
    // Restore predator discipline choice after predator type change event fires
    if (draft.predatorDisciplineChoice) {
        predatorDisciplineChoice = draft.predatorDisciplineChoice;
        var predRadio = document.querySelector('input[name="predator-disc"][value="' + draft.predatorDisciplineChoice + '"]');
        if (predRadio) predRadio.checked = true;
    }

    // Restore priorities
    if (draft.attributePriorities) {
        ['primary', 'secondary', 'tertiary'].forEach(function (level) {
            if (draft.attributePriorities[level]) {
                attributePriorities[level] = draft.attributePriorities[level];
                document.getElementById('attr-priority-' + level).value = draft.attributePriorities[level];
            }
        });
        validatePrioritySelections('attr');
        updateAttributeMaxValues();
    }
    if (draft.skillPriorities) {
        ['primary', 'secondary', 'tertiary'].forEach(function (level) {
            if (draft.skillPriorities[level]) {
                skillPriorities[level] = draft.skillPriorities[level];
                document.getElementById('skill-priority-' + level).value = draft.skillPriorities[level];
            }
        });
        validatePrioritySelections('skill');
        updateSkillMaxValues();
    }

    // Restore trait values (attributes and skills)
    if (draft.traitValues) {
        for (const [trait, value] of Object.entries(draft.traitValues)) {
            traitValues[trait] = value;
            const dotsContainer = document.querySelector('.trait-dots[data-trait="' + trait + '"], .pip-row[data-trait="' + trait + '"]');
            if (dotsContainer) {
                updateDots(dotsContainer, value);
            }
        }
    }

    // Restore discipline values
    if (draft.disciplineValues) {
        for (const [disc, value] of Object.entries(draft.disciplineValues)) {
            disciplineValues[disc] = value;
        }
        document.querySelectorAll('#disciplines-container .trait-dots, #disciplines-container .pip-row').forEach(function (dotsContainer) {
            const trait = dotsContainer.dataset.trait;
            if (disciplineValues[trait]) {
                updateDots(dotsContainer, disciplineValues[trait]);
            }
        });
    }

    // Restore advantage values
    if (draft.advantageValues) {
        for (const [adv, data] of Object.entries(draft.advantageValues)) {
            advantageValues[adv] = data;
        }
        document.querySelectorAll('#advantages-container .trait-dots, #advantages-container .pip-row').forEach(function (dotsContainer) {
            const trait = dotsContainer.dataset.trait;
            if (advantageValues[trait]) {
                updateDots(dotsContainer, advantageValues[trait].value);
            }
        });
    }

    // Restore flaw values
    if (draft.flawValues) {
        for (const [flaw, data] of Object.entries(draft.flawValues)) {
            flawValues[flaw] = data;
        }
        document.querySelectorAll('#flaws-container .trait-dots, #flaws-container .pip-row').forEach(function (dotsContainer) {
            const trait = dotsContainer.dataset.trait;
            if (flawValues[trait]) {
                updateDots(dotsContainer, flawValues[trait].value);
            }
        });
    }

    restoreTraitDetails('advantage', advantageValues);
    restoreTraitDetails('flaw', flawValues);
    updatePointsDisplay();
    validateForm();
}

function clearDraft() {
    try {
        localStorage.removeItem(getDraftKey());
    } catch (e) {
        console.warn('Draft clear failed:', e);
    }
}

// ============================================================
// UTILITY FUNCTIONS
// ============================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message, type) {
    type = type || 'info';
    const toastHTML =
        '<div class="toast align-items-center text-white bg-' + type + ' border-0" role="alert" aria-live="assertive" aria-atomic="true" data-bs-autohide="true" data-bs-delay="3000">' +
        '<div class="d-flex">' +
        '<div class="toast-body">' + message + '</div>' +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
        '</div></div>';

    const container = document.getElementById('toast-container');
    if (!container) {
        console.error('Toast container not found');
        return;
    }

    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = toastHTML.trim();
    const toastEl = tempDiv.firstChild;
    container.appendChild(toastEl);

    const toast = new bootstrap.Toast(toastEl);
    toast.show();

    toastEl.addEventListener('hidden.bs.toast', function () {
        this.remove();
    });
}
