(function () {
    'use strict';

    var localHosts = ['localhost', '127.0.0.1', '[::1]'];

    function chargenUrl() {
        var raw = (window.PUBLIC_GAME_BASE_URL || '').trim();
        if (!raw) {
            return null;
        }

        var url;
        try {
            url = new URL(raw);
        } catch (error) {
            return null;
        }

        var isLocalDev = url.protocol === 'http:' && localHosts.indexOf(url.hostname) !== -1;
        if ((url.protocol !== 'https:' && !isLocalDev) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
            return null;
        }

        return new URL('/character-creation/', url.origin).href;
    }

    function showUnavailable() {
        var notice = document.getElementById('chargen-unavailable');
        if (notice) {
            notice.hidden = false;
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var target = chargenUrl();
        var links = document.querySelectorAll('[data-game-chargen-link]');
        for (var i = 0; i < links.length; i++) {
            if (target) {
                links[i].href = target;
            }
        }

        if (document.body.hasAttribute('data-retired-chargen')) {
            if (target) {
                window.location.replace(target);
            } else {
                showUnavailable();
            }
        }
    });
})();
