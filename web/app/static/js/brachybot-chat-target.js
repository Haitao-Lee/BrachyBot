/* Immutable submission context shared by direct, queued, retried and child turns.
 * No language parsing and no task execution. The server validates all identity.
 */
(function installChatTargetCapture() {
    'use strict';
    const scopes = new Map();
    function capture(options = {}) {
        const saved = options.timepointScope;
        const supplied = saved || window.BrachyBotTimepoints?.captureSubmission?.() || {
            sessionId: String(window.activeSessionId || ''), timepointId: null, legacyDefault: true,
            uiLanguage: window._i18nLang === 'zh' ? 'zh' : 'en'
        };
        const scope = { sessionId: String(supplied.sessionId || ''), timepointId: supplied.timepointId || null,
            generation: supplied.generation, legacyDefault: supplied.legacyDefault === true,
            uiLanguage: supplied.uiLanguage === 'zh' ? 'zh' : 'en' };
        if (scope.timepointId !== null && !/^[0-9a-f]{32}$/.test(scope.timepointId)) throw Error('invalid_timepoint_scope');
        return Object.freeze(scope);
    }
    function headers(scope, base = {}) {
        const result = new Headers(base);
        result.set('X-BrachyBot-Session', scope.sessionId);
        // An empty header is intentional for an older default-only capture.
        // It prevents a generic fetch wrapper from injecting a later tab ID.
        result.set('X-BrachyBot-Timepoint', scope.timepointId || '');
        result.set('X-BrachyBot-Language', scope.uiLanguage);
        return result;
    }
    function isMounted(scope) {
        if (!scope) return true; // Compatibility with unscoped standalone UI.
        return window.BrachyBotTimepoints?.isSubmissionCurrent?.(scope)
            ?? (scope.legacyDefault && scope.sessionId === String(window.activeSessionId || ''));
    }
    function remember(requestId, scope) {
        if (!requestId || !scope) return;
        const key = JSON.stringify([scope.sessionId, String(requestId)]);
        scopes.set(key, capture({ timepointScope: scope }));
        while (scopes.size > 256) scopes.delete(scopes.keys().next().value);
    }
    const parent = (sessionId, requestId) => scopes.get(JSON.stringify([String(sessionId), String(requestId)])) || null;
    window.BrachyBotChatTargets = Object.freeze({ capture, headers, isMounted, remember, parent });
})();
