/* Embedded browsers cannot reliably operate native JS dialogs. Use ordinary
 * page controls, without replacing any browser API. Concurrent requests fail
 * closed: accepting one dialog can never authorize another pending action. */
(function (root) {
    'use strict';
    function createDialogs(document) {
        const dialog = document.getElementById('page-dialog');
        const form = document.getElementById('page-dialog-form');
        const message = document.getElementById('page-dialog-message');
        const title = document.getElementById('page-dialog-title');
        const input = document.getElementById('page-dialog-input');
        const group = document.getElementById('page-dialog-input-group');
        const cancel = document.getElementById('page-dialog-cancel');
        const feedback = document.getElementById('page-feedback');
        const feedbackParent = feedback.parentNode;
        let active = null;
        function finish(accepted) {
            if (!active) return;
            const current = active;
            active = null;
            const value = accepted ? (current.prompt ? input.value : true) : (current.prompt ? null : false);
            dialog.close();
            current.parent.appendChild(dialog);
            current.resolve(value);
            // Callers may disable their action while awaiting confirmation.
            // Let their cancellation continuation re-enable it before focus
            // restoration; do not alter any caller-owned disabled/busy gate.
            Promise.resolve().then(function () {
                if (!active && current.focus && current.focus.isConnected) current.focus.focus();
            });
        }
        form.addEventListener('submit', function (event) {
            event.preventDefault();
            if (active && (!active.prompt || input.value.trim())) finish(true);
        });
        cancel.addEventListener('click', function () { finish(false); });
        dialog.addEventListener('cancel', function (event) { event.preventDefault(); finish(false); });
        // Native close events are queued. A previous close must not cancel a
        // newly opened request which has already acquired this same element.
        dialog.addEventListener('close', function () { if (active && !dialog.open) finish(false); });
        dialog.addEventListener('keydown', function (event) {
            // Escape belongs to this top-layer dialog, not an underlying
            // Bootstrap modal's dismiss listener. Native cancel still fires.
            if (event.key === 'Escape') event.stopPropagation();
        });
        function request(text, prompt, returnFocus) {
            if (active) return Promise.resolve(prompt ? null : false);
            return new Promise(function (resolve) {
                const focus = returnFocus || document.activeElement;
                active = {resolve: resolve, prompt: prompt, focus: focus, parent: dialog.parentNode};
                // Keep Bootstrap's existing focus trap satisfied when this
                // confirmation belongs to a modal already open on the page.
                const modal = document.querySelector('.modal.show');
                if (modal) modal.appendChild(dialog);
                title.textContent = prompt ? 'Reason required' : 'Confirm action';
                message.textContent = String(text);
                group.hidden = !prompt;
                input.required = prompt;
                input.value = '';
                try {
                    dialog.showModal();
                    (prompt ? input : cancel).focus();
                } catch (_error) { finish(false); }
            });
        }
        return {
            confirm: function (text, returnFocus) { return request(text, false, returnFocus); },
            prompt: function (text, returnFocus) { return request(text, true, returnFocus); },
            alert: function (text) {
                (document.querySelector('.modal.show') || feedbackParent).appendChild(feedback);
                feedback.textContent = String(text);
                feedback.hidden = false;
            }
        };
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = createDialogs;
    if (root.document) root.BuilderDialogs = createDialogs(root.document);
})(typeof window !== 'undefined' ? window : globalThis);
