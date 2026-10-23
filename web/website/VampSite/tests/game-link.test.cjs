const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const site = path.resolve(__dirname, '..');
const routingScripts = ['assets/js/site-config.js', 'assets/js/game-link.js'];
const legacyPages = ['character-creation.html', 'character-creation-new.html'];

function loadPage(filename, origin) {
    const html = fs.readFileSync(path.join(site, filename), 'utf8');
    const scripts = [...html.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi)].map(match => match[1]);
    const links = [...html.matchAll(/<a\b(?=[^>]*\bdata-game-chargen-link)([^>]*)>/gi)].map(match => ({
        href: /\bhref=["']([^"']*)["']/i.exec(match[1])[1]
    }));
    const bodyAttributes = /<body\b([^>]*)>/i.exec(html)[1];
    const noticeTag = /<[^>]*\bid=["']chargen-unavailable["'][^>]*>/i.exec(html);
    const notice = noticeTag ? {hidden: /\bhidden\b/i.test(noticeTag[0])} : null;
    const redirects = [];
    const ready = [];
    const window = {
        location: {replace: target => redirects.push(target)},
        localStorage: new Proxy({}, {get() {throw new Error('Chargen routing must never access localStorage');}})
    };
    const document = {
        body: {hasAttribute: name => new RegExp(`\\b${name}\\b`).test(bodyAttributes)},
        querySelectorAll: selector => {
            assert.equal(selector, '[data-game-chargen-link]');
            return links;
        },
        getElementById: id => id === 'chargen-unavailable' ? notice : null,
        addEventListener: (event, callback) => {
            assert.equal(event, 'DOMContentLoaded');
            ready.push(callback);
        }
    };
    const context = vm.createContext({window, document, URL});
    for (const script of scripts.filter(script => routingScripts.includes(script))) {
        vm.runInContext(fs.readFileSync(path.join(site, script), 'utf8'), context, {filename: script});
        if (script === routingScripts[0] && origin !== undefined) {
            window.PUBLIC_GAME_BASE_URL = origin;
        }
    }
    assert.deepEqual(scripts.filter(script => routingScripts.includes(script)), routingScripts);
    for (const callback of ready) callback();
    return {links, notice, redirects, scripts, origin: window.PUBLIC_GAME_BASE_URL};
}

test('the checked-in blank config keeps the public CTA on its unavailable entry point', () => {
    const page = loadPage('index.html');
    assert.equal(page.origin, '');
    assert.equal(page.links.length, 1);
    assert.equal(page.links[0].href, 'character-creation-new.html');
    assert.deepEqual(page.redirects, []);
});

test('the homepage CTA uses the configured canonical Django chargen route', () => {
    const page = loadPage('index.html', 'https://game.example:8443/');
    assert.equal(page.links[0].href, 'https://game.example:8443/character-creation/');
    assert.deepEqual(page.redirects, []);
});

test('both actual retired entry pages redirect once and load only the routing scripts', () => {
    for (const filename of legacyPages) {
        const page = loadPage(filename, 'https://game.example');
        assert.deepEqual(page.scripts, routingScripts);
        assert.deepEqual(page.redirects, ['https://game.example/character-creation/']);
        assert.equal(page.notice.hidden, true);
    }
});

test('blank or unsafe origins cannot redirect either retired entry or rewrite the public CTA', () => {
    const invalid = ['', ' ', 'http://game.example', 'https://user:password@game.example',
        'https://game.example/private', 'https://game.example/?token=1', 'https://game.example/#fragment',
        'javascript:alert(1)', 'not a URL'];
    for (const origin of invalid) {
        const homepage = loadPage('index.html', origin);
        assert.equal(homepage.links[0].href, 'character-creation-new.html');
        for (const filename of legacyPages) {
            const page = loadPage(filename, origin);
            assert.deepEqual(page.redirects, []);
            assert.equal(page.notice.hidden, false);
        }
    }
});

test('explicit local development origins work through the same CTA and redirect code', () => {
    for (const origin of ['http://localhost:6665', 'http://127.0.0.1:6665', 'http://[::1]:6665']) {
        const expected = `${origin}/character-creation/`;
        assert.equal(loadPage('index.html', origin).links[0].href, expected);
        for (const filename of legacyPages) {
            assert.deepEqual(loadPage(filename, origin).redirects, [expected]);
        }
    }
});
