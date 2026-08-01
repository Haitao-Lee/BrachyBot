/* Account bootstrap and authenticated API request wrapper. */
(function () {
    'use strict';

    const state = { user: null, csrfToken: null, booted: false };
    const editorKey = 'brachybot_editor_token';
    const rememberKey = 'brachybot_remember_user';
    const AUTH_REQUEST_TIMEOUT_MS = 12000;
    const LEASE_RELEASE_TIMEOUT_MS = 4000;
    let authenticationPromise = null;

    // Keep the editor identity stable across page reloads. A sessionStorage
    // token made the same browser look like a different editor after reload.
    let editorToken = null;
    try { editorToken = localStorage.getItem(editorKey) || sessionStorage.getItem(editorKey); } catch (_) {}
    if (!editorToken) {
        editorToken = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, '');
    }
    try {
        localStorage.setItem(editorKey, editorToken);
        sessionStorage.setItem(editorKey, editorToken);
    } catch (_) {}

    // =========================================================================
    // I18N — every user-visible string goes through this table, indexed by
    // the same keys registered in brachybot-chat-core.js I18N. The active
    // language is the same `window._i18nLang` global used everywhere else.
    // =========================================================================
    function lang() { return (window._i18nLang === 'zh') ? 'zh' : 'en'; }
    function t(zh, en) { return lang() === 'zh' ? zh : en; }
    function authT(key, fallback) {
        if (window._I18N && window._I18N[key] && window._I18N[key][lang()]) {
            return window._I18N[key][lang()];
        }
        return t(fallback.zh, fallback.en);
    }
    function resolveText(zh, en) {
        if (typeof zh === 'object' && zh && 'zh' in zh && 'en' in zh) return t(zh.zh, zh.en);
        return t(zh, en);
    }
    function setFieldError(field, message) {
        const errorEl = document.getElementById(field === 'username' ? 'authUsernameError' : 'authPasswordError');
        const input = document.getElementById(field === 'username' ? 'authUsername' : 'authPassword');
        if (errorEl) errorEl.textContent = message || '';
        if (input) {
            input.setAttribute('aria-invalid', message ? 'true' : 'false');
        }
    }
    function clearAllFieldErrors() {
        setFieldError('username', '');
        setFieldError('password', '');
    }

    // Map an HTTP error response + network failure to a localized message.
    // Order of detection: server-provided message → status code → generic.
    function mapAuthError(rawMessage, statusCode) {
        const text = String(rawMessage || '').trim();
        const lower = text.toLowerCase();
        // Specific server-side signals come first so we don't lose context.
        if (lower.includes('invalid username or password')
            || lower.includes('invalid credentials')
            || lower.includes('authentication failed')) {
            return authT('auth.status.invalid_credentials',
                { zh: '用户名或密码错误，请重试。', en: 'Invalid username or password. Please try again.' });
        }
        if (lower.includes('disabled') || lower.includes('locked') || lower.includes('banned')) {
            return authT('auth.status.disabled',
                { zh: '该账号已被禁用，请联系系统管理员。', en: 'This account has been disabled. Please contact your administrator.' });
        }
        if (lower.includes('already exists') || lower.includes('already taken') || lower.includes('duplicate')) {
            return authT('auth.status.taken',
                { zh: '该用户名已被占用。', en: 'This username is already taken.' });
        }
        if (lower.includes('password must be')
            || lower.includes('password is too short')
            || lower.includes('at least 12')) {
            return authT('auth.status.weak_password',
                { zh: '密码长度至少 12 个字符。', en: 'Password must be at least 12 characters long.' });
        }
        if (lower.includes('username must')
            || lower.includes('invalid username')
            || lower.includes('username may only')) {
            return authT('auth.status.bad_username',
                { zh: '用户名只能包含字母、数字、_、.、-，长度 3-64。',
                   en: 'Username may only contain letters, digits, "_", ".", "-", and must be 3–64 characters long.' });
        }
        if (lower.includes('api key') || lower.includes('access key') || lower.includes('brachybot_api_key')) {
            return authT('auth.status.api_key_invalid',
                { zh: '部署访问密钥无效。', en: 'The deployment access key is invalid.' });
        }
        if (lower.includes('csrf')) {
            return authT('auth.status.csrf',
                { zh: '会话已过期，请刷新页面后重试。',
                   en: 'Your session has expired. Please reload the page and try again.' });
        }
        if (statusCode === 0 || /failed to fetch|networkerror|network request failed|aborted/i.test(text)) {
            return authT('auth.status.network',
                { zh: '无法连接到 BrachyBot 服务器。请检查网络或服务状态。',
                   en: 'Cannot reach the BrachyBot server. Please check your network or service status.' });
        }
        if (statusCode === 408 || /timeout|timed out|abort/i.test(text)) {
            return authT('auth.status.timeout',
                { zh: '请求超时。服务器响应过慢，请稍后重试。',
                   en: 'Request timed out. The server is responding too slowly. Please try again.' });
        }
        if (statusCode === 503 || statusCode === 502 || statusCode === 504 || /service unavailable|service is temporarily/i.test(text)) {
            return authT('auth.status.service',
                { zh: '登录服务暂时不可用，请稍后重试。',
                   en: 'The authentication service is temporarily unavailable. Please try again later.' });
        }
        // Fall through to the original server message (also localized) so
        // we never leak raw English if the page is in Chinese.
        if (text) {
            // Strip trailing newlines / very long traceback fragments.
            const cleaned = text.replace(/\s+/g, ' ').slice(0, 200);
            return cleaned;
        }
        return authT('auth.status.unknown',
            { zh: '登录失败，请稍后重试。', en: 'Sign-in failed. Please try again later.' });
    }

    function setStatus(message, error) {
        const target = document.getElementById('authStatus');
        if (!target) return;
        target.textContent = message || '';
        target.classList.toggle('error', !!error);
        target.classList.toggle('success', !!(message && !error));
    }

    function setStatusKey(key, error) {
        const map = {
            'signing_in': { zh: '正在登录…', en: 'Signing in…' },
            'creating': { zh: '正在创建账号…', en: 'Creating account…' },
            'signed_in': { zh: '已登录，正在初始化工作区…', en: 'Signed in. Initializing workspace…' },
        };
        const pair = map[key];
        if (!pair) return setStatus('', false);
        setStatus(t(pair.zh, pair.en), !!error);
    }

    function setVisible(visible) {
        const overlay = document.getElementById('authOverlay');
        if (overlay) overlay.hidden = !visible;
        if (visible) {
            // Restore the previously remembered username (if any) so the user
            // can sign in with a single click after the first session.
            try {
                const remembered = localStorage.getItem(rememberKey);
                const userEl = document.getElementById('authUsername');
                const remEl = document.getElementById('authRemember');
                if (userEl && !userEl.value && remembered) userEl.value = remembered;
                if (remEl && remembered) remEl.checked = true;
            } catch (_) {}
            // Auto-fill the deployment access key from any key the browser
            // already holds (set via ?api_key=, a previous sign-in, or the
            // session/local storage copy). The operator should only need to
            // enter username and password on a protected deployment.
            try {
                const keyInput = document.getElementById('authDeploymentKey');
                if (keyInput && !keyInput.value) {
                    const storedKey = window.BRACHYBOT_API_KEY
                        || sessionStorage.getItem('BRACHYBOT_API_KEY')
                        || localStorage.getItem('BRACHYBOT_API_KEY')
                        || '';
                    if (storedKey) keyInput.value = storedKey;
                }
            } catch (_) {}
            // Focus management — first field gets focus so Enter submits the form.
            const first = document.getElementById('authUsername');
            if (first) {
                setTimeout(() => first.focus({ preventScroll: true }), 30);
            }
        }
    }

    function setPasswordVisible(visible) {
        const overlay = document.getElementById('passwordOverlay');
        if (overlay) overlay.hidden = !visible;
        if (visible) {
            const cur = document.getElementById('currentPassword');
            if (cur) setTimeout(() => cur.focus({ preventScroll: true }), 30);
        }
    }

    function setPasswordStatus(message, error) {
        const target = document.getElementById('passwordStatus');
        if (!target) return;
        target.textContent = message || '';
        target.classList.toggle('error', !!error);
        target.classList.toggle('success', !!(message && !error));
    }

    function setPasswordStatusKey(key, error) {
        const map = {
            'updating': { zh: '正在更新密码…', en: 'Updating password…' },
        };
        const pair = map[key];
        if (!pair) return setPasswordStatus('', false);
        setPasswordStatus(t(pair.zh, pair.en), !!error);
    }

    function setButtonLoading(button, loading) {
        if (!button) return;
        button.disabled = !!loading;
        button.setAttribute('data-loading', loading ? 'true' : 'false');
        button.setAttribute('aria-busy', loading ? 'true' : 'false');
    }

    function setDeploymentAccessKey(value) {
        const key = String(value || '').trim();
        if (typeof window.setBrachyBotApiKey === 'function') {
            window.setBrachyBotApiKey(key);
        } else {
            // The UI API wrapper normally provides this helper. Keep the
            // login shell usable when static assets are temporarily cached
            // out of order. Persist to localStorage so the remembered key
            // survives reloads and tab closings.
            window.BRACHYBOT_API_KEY = key;
            if (key) localStorage.setItem('BRACHYBOT_API_KEY', key);
            else localStorage.removeItem('BRACHYBOT_API_KEY');
        }
    }

    function revealDeploymentKeyHelp(message) {
        const details = document.getElementById('authAccessKeyDetails');
        const input = document.getElementById('authDeploymentKey');
        if (details) details.open = true;
        if (input) input.focus();
        const localized = message
            ? mapAuthError(message, 0)
            : authT('auth.status.api_key',
                { zh: '此服务器需要部署访问密钥。', en: 'This server requires a deployment access key.' });
        setStatus(localized, true);
    }

    function renderAccount() {
        const host = document.getElementById('accountStatus');
        const name = document.getElementById('accountName');
        if (host) host.hidden = !state.user;
        if (name) name.textContent = state.user?.username || '';
    }

    function currentLeaseSessionId() {
        if (window.activeSessionId) return String(window.activeSessionId);
        try {
            if (typeof activeSessionId !== 'undefined' && activeSessionId) return String(activeSessionId);
        } catch (_) {
            // The chat module may still be evaluating during the first boot.
        }
        return String(document.getElementById('sessionDisplay')?.textContent || '').trim();
    }

    let workspaceLockDismissedKey = '';

    function workspaceLockKey() {
        const session = document.getElementById('sessionDisplay');
        const id = typeof activeSessionId !== 'undefined' && activeSessionId
            ? activeSessionId
            : String(session?.textContent || 'current').trim();
        return `brachybot:lock-notice:${String(id)}`;
    }

    function dismissWorkspaceLockNotice() {
        // Dismissing this banner hides presentation only; the lease remains
        // read-only until the server grants edit ownership.
        workspaceLockDismissedKey = workspaceLockKey();
        const notice = document.getElementById('workspaceLockNotice');
        if (notice) notice.hidden = true;
    }

    function renderWorkspaceLock(locked) {
        const notice = document.getElementById('workspaceLockNotice');
        if (!notice) return;
        const takeover = document.getElementById('workspaceLockTakeover');
        if (takeover && !takeover.dataset.bound) {
            takeover.dataset.bound = 'true';
            takeover.addEventListener('click', async () => {
                takeover.disabled = true;
                takeover.setAttribute('aria-busy', 'true');
                const original = takeover.textContent;
                takeover.textContent = typeof window._t === 'function'
                    ? window._t('正在接管...', 'Taking over...')
                    : 'Taking over...';
                try {
                    await takeoverLease();
                } catch (error) {
                    window.showBrachyBotNotice?.(error.message || 'Unable to take over editing.', 'error', 7000);
                } finally {
                    takeover.disabled = false;
                    takeover.removeAttribute('aria-busy');
                    takeover.textContent = original;
                }
            });
        }
        if (!locked) {
            workspaceLockDismissedKey = '';
            notice.hidden = true;
            return;
        }
        notice.hidden = workspaceLockDismissedKey === workspaceLockKey();
    }

    async function authFetch(input, init = {}, timeoutMs = AUTH_REQUEST_TIMEOUT_MS) {
        const controller = typeof AbortController === 'function' ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
        try {
            const options = Object.assign({}, init);
            if (controller) options.signal = controller.signal;
            return await fetch(input, options);
        } catch (error) {
            if (error?.name === 'AbortError') {
                const error2 = new Error('TIMEOUT');
                error2.isTimeout = true;
                throw error2;
            }
            throw error;
        } finally {
            if (timer) clearTimeout(timer);
        }
    }

    async function request(path, body, allowAnonymous = true) {
        // The CSRF token is only valid after a session exists. The auth
        // routes themselves skip CSRF, so we omit the header pre-login.
        const headers = { 'Content-Type': 'application/json' };
        if (state.csrfToken && !allowAnonymous) {
            headers['X-CSRF-Token'] = state.csrfToken;
        }
        let response;
        try {
            response = await authFetch(path, {
                method: 'POST',
                credentials: 'same-origin',
                headers,
                body: JSON.stringify(body || {}),
            });
        } catch (error) {
            if (error && error.isTimeout) {
                const e = new Error('TIMEOUT');
                e.status = 408;
                throw e;
            }
            const e = new Error('NETWORK');
            e.status = 0;
            e.originalError = error;
            throw e;
        }
        let data = {};
        try { data = await response.json(); } catch (_) { /* non-JSON body */ }
        if (!response.ok) {
            const error = new Error(data.error || `HTTP ${response.status}`);
            error.code = data.code;
            error.status = response.status;
            error.serverMessage = data.error;
            throw error;
        }
        return data;
    }

    function normalizedCaseId(value) {
        const text = String(value || '').trim();
        return /^[a-f0-9]{32}$/.test(text) ? text : '';
    }

    async function acquireLease(sessionId = currentLeaseSessionId()) {
        if (!state.user) return { editable: false };
        const ownerSessionId = normalizedCaseId(sessionId);
        if (!ownerSessionId) return { editable: false, code: 'workspace_unavailable' };
        try {
            const result = await request('/api/workspace/lease', {
                editor_token: editorToken,
                session_id: ownerSessionId,
                ttl_seconds: 75,
            }, false);
            return applyLeaseResult(result);
        } catch (error) {
            return applyLeaseResult({
                editable: false,
                code: error.code,
                locked: error.code === 'workspace_locked',
                error: error.message,
            });
        }
    }

    async function takeoverLease(sessionId = currentLeaseSessionId()) {
        if (!state.user) return { editable: false };
        const ownerSessionId = normalizedCaseId(sessionId);
        if (!ownerSessionId) return { editable: false, code: 'workspace_unavailable' };
        const result = await request('/api/workspace/lease', {
            editor_token: editorToken,
            session_id: ownerSessionId,
            ttl_seconds: 75,
            takeover: true,
        }, false);
        return applyLeaseResult(result);
    }

    function applyLeaseResult(result) {
        const editable = !!result?.editable;
        document.body.classList.toggle('workspace-readonly', !editable);
        // A failed heartbeat is not proof that another browser owns the case.
        // Only an authenticated workspace_locked response may show the lock
        // takeover banner; network/server errors use the normal connection UI.
        renderWorkspaceLock(result?.locked === true || result?.code === 'workspace_locked');
        return result || { editable };
    }

    async function refreshLease() {
        if (state.user && !document.hidden) await acquireLease();
    }

    async function releaseLease(sessionId = currentLeaseSessionId()) {
        if (!state.user) return;
        const ownerSessionId = normalizedCaseId(sessionId);
        if (!ownerSessionId) return;
        try {
            await authFetch('/api/workspace/lease', {
                method: 'DELETE',
                credentials: 'same-origin',
                // Keep this request self-contained. It is also called while
                // changing cases, before the global fetch wrapper can be
                // relied on after a cache refresh or script-order change.
                headers: {
                    'Content-Type': 'application/json',
                    ...(state.csrfToken ? { 'X-CSRF-Token': state.csrfToken } : {}),
                    'X-BrachyBot-Editor': editorToken,
                },
                body: JSON.stringify({ editor_token: editorToken, session_id: ownerSessionId }),
            }, LEASE_RELEASE_TIMEOUT_MS);
        } catch (_) {
            // A short lease expiry is the fallback when the browser is offline.
        }
    }

    // =========================================================================
    // Password show / hide toggle. Two toggles exist (login + change-pw).
    // =========================================================================
    function bindPasswordToggle(toggleId, inputId) {
        const toggle = document.getElementById(toggleId);
        const input = document.getElementById(inputId);
        if (!toggle || !input) return;
        toggle.addEventListener('click', () => {
            const isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            toggle.setAttribute('aria-pressed', isHidden ? 'true' : 'false');
            toggle.setAttribute('aria-label',
                isHidden ? t('隐藏密码', 'Hide password') : t('显示密码', 'Show password'));
            toggle.setAttribute('title',
                isHidden ? t('隐藏密码', 'Hide password') : t('显示密码', 'Show password'));
        });
    }

    // =========================================================================
    // I18N — apply data-i18n-* attributes to the auth overlay only.
    // The global applyI18n() in brachybot-chat-core.js handles everything
    // outside the auth surface; this is a focused re-render that:
    //   1. Runs even before chat-core.js boot is complete (auth shows first).
    //   2. Also updates the <html lang> attribute.
    //   3. Re-renders authStatus / passwordStatus if they hold a
    //      pre-localized string, by looking up the i18n key they were set
    //      from. (Status text is set by key whenever possible.)
    // =========================================================================
    function renderAuthI18n() {
        const code = lang();
        // <html lang> must follow the active language so screen readers
        // and the browser spell-checker pick the correct locale.
        try { document.documentElement.setAttribute('lang', code === 'zh' ? 'zh-CN' : 'en'); } catch (_) {}
        // All [data-i18n-*] attributes are handled by the global applyI18n
        // scanner, but we also update the password toggle's accessible name
        // to mirror the current language when the field is revealed.
        document.querySelectorAll('#authPasswordToggle, #newPasswordToggle').forEach(btn => {
            if (btn.getAttribute('aria-pressed') === 'true') {
                btn.setAttribute('aria-label', t('隐藏密码', 'Hide password'));
                btn.setAttribute('title', t('隐藏密码', 'Hide password'));
            } else {
                btn.setAttribute('aria-label', t('显示密码', 'Show password'));
                btn.setAttribute('title', t('显示密码', 'Show password'));
            }
        });
    }

    function setAuthLangToggleState() {
        const code = lang();
        document.querySelectorAll('#authLangToggle [data-lang-btn]').forEach(btn => {
            const isActive = btn.getAttribute('data-lang-btn') === code;
            btn.classList.toggle('lang-active', isActive);
            btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
    }

    function bindAuthLangToggle() {
        const container = document.getElementById('authLangToggle');
        if (!container) return;
        container.querySelectorAll('[data-lang-btn]').forEach(btn => {
            btn.addEventListener('click', (ev) => {
                ev.preventDefault();
                const code = btn.getAttribute('data-lang-btn');
                if (typeof window.setUiLanguage === 'function') {
                    window.setUiLanguage(code);
                } else {
                    window._i18nLang = code;
                    try { localStorage.setItem('brachybot_ui_lang', code); } catch (_) {}
                    renderAuthI18n();
                    setAuthLangToggleState();
                }
            });
        });
    }

    // =========================================================================
    // Form submission
    // =========================================================================
    function readRememberFlag() {
        return !!document.getElementById('authRemember')?.checked;
    }

    function persistRememberFlag(username) {
        try {
            if (readRememberFlag() && username) {
                localStorage.setItem(rememberKey, username);
            } else {
                localStorage.removeItem(rememberKey);
            }
        } catch (_) {}
    }

    function clientValidate(username, password) {
        if (!username || username.length < 3 || username.length > 64) {
            setFieldError('username', t('请输入 3-64 个字符的用户名。', 'Please enter a username of 3–64 characters.'));
            return false;
        }
        if (!/^[A-Za-z0-9_.-]+$/.test(username)) {
            setFieldError('username', authT('auth.status.bad_username',
                { zh: '用户名只能包含字母、数字、_、.、-，长度 3-64。',
                   en: 'Username may only contain letters, digits, "_", ".", "-", and must be 3–64 characters long.' }));
            return false;
        }
        if (!password || password.length < 12) {
            setFieldError('password', authT('auth.status.weak_password',
                { zh: '密码长度至少 12 个字符。', en: 'Password must be at least 12 characters long.' }));
            return false;
        }
        return true;
    }

    async function submit(mode) {
        const username = document.getElementById('authUsername')?.value.trim() || '';
        const password = document.getElementById('authPassword')?.value || '';
        const deploymentKey = document.getElementById('authDeploymentKey')?.value || '';
        const loginBtn = document.getElementById('authLogin');
        const registerBtn = document.getElementById('authRegister');
        clearAllFieldErrors();

        if (deploymentKey.trim()) setDeploymentAccessKey(deploymentKey);

        if (!clientValidate(username, password)) {
            return;
        }

        // Disable both buttons to prevent double-submit; spinner inside
        // the primary button remains inline so the button never resizes.
        setButtonLoading(loginBtn, true);
        if (registerBtn) registerBtn.disabled = true;
        setStatusKey(mode === 'register' ? 'creating' : 'signing_in', false);

        try {
            const data = await request(`/api/auth/${mode}`, { username, password }, true);
            state.user = data.user;
            state.csrfToken = data.csrf_token;
            persistRememberFlag(username);
            setStatusKey('signed_in', false);
            setVisible(false);
            renderAccount();
            await acquireLease();
            if (typeof window.startBrachyBotApplication === 'function') {
                window.startBrachyBotApplication();
            }
        } catch (error) {
            const localized = mapAuthError(error.serverMessage || error.message, error.status || 0);
            if (/api key/i.test(localized)) {
                revealDeploymentKeyHelp(localized);
            } else {
                setStatus(localized, true);
            }
            // If the server tells us a specific field is wrong, surface
            // the message next to that field for fast correction.
            if (error.status === 401) {
                setFieldError('password', localized);
            }
        } finally {
            setButtonLoading(loginBtn, false);
            if (registerBtn) registerBtn.disabled = false;
        }
    }

    async function changePassword() {
        const currentPassword = document.getElementById('currentPassword')?.value || '';
        const newPassword = document.getElementById('newPassword')?.value || '';
        const saveBtn = document.getElementById('passwordSave');
        const cancelBtn = document.getElementById('passwordCancel');
        setPasswordStatus('', false);
        if (!currentPassword) {
            setPasswordStatus(t('请输入当前密码。', 'Please enter your current password.'), true);
            return;
        }
        if (newPassword.length < 12) {
            setPasswordStatus(authT('auth.status.weak_password',
                { zh: '密码长度至少 12 个字符。', en: 'Password must be at least 12 characters long.' }), true);
            return;
        }
        setButtonLoading(saveBtn, true);
        if (cancelBtn) cancelBtn.disabled = true;
        setPasswordStatusKey('updating', false);
        try {
            await request('/api/auth/password', { current_password: currentPassword, new_password: newPassword }, false);
            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            setPasswordStatus(t('密码已更新。', 'Password updated.'), false);
            setTimeout(() => setPasswordVisible(false), 800);
        } catch (error) {
            setPasswordStatus(mapAuthError(error.serverMessage || error.message, error.status || 0), true);
        } finally {
            setButtonLoading(saveBtn, false);
            if (cancelBtn) cancelBtn.disabled = false;
        }
    }

    const nativeFetch = window.fetch.bind(window);
    window.fetch = function authenticatedFetch(input, init) {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const isApi = /^\/api\//.test(url) || (() => {
            try { return new URL(url, location.href).origin === location.origin && new URL(url, location.href).pathname.startsWith('/api/'); }
            catch (_) { return false; }
        })();
        if (!isApi) return nativeFetch(input, init);
        const next = Object.assign({ credentials: 'same-origin' }, init || {});
        const headers = new Headers(next.headers || (input && input.headers) || {});
        const method = String(next.method || (input && input.method) || 'GET').toUpperCase();
        if (state.csrfToken && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && !headers.has('X-CSRF-Token')) {
            headers.set('X-CSRF-Token', state.csrfToken);
        }
        if (editorToken && !headers.has('X-BrachyBot-Editor')) headers.set('X-BrachyBot-Editor', editorToken);
        const pathname = (() => {
            try { return new URL(url, location.href).pathname; }
            catch (_) { return ''; }
        })();
        const requestCaseId = normalizedCaseId(currentLeaseSessionId());
        const controlPlaneRequest = pathname.startsWith('/api/auth/')
            || pathname === '/api/workspace/lease'
            || pathname === '/api/sessions'
            || pathname.startsWith('/api/sessions/');
        // Freeze the selected case when a data-plane request is created.
        // Delayed responses are then still routed to their originating case,
        // even if the user selects another case before the server handles it.
        if (requestCaseId && !controlPlaneRequest && !headers.has('X-BrachyBot-Session')) {
            headers.set('X-BrachyBot-Session', requestCaseId);
        }
        next.headers = headers;
        return nativeFetch(input, next);
    };

    async function authenticated() {
        if (state.user && state.csrfToken) return true;
        if (authenticationPromise) return authenticationPromise;
        authenticationPromise = (async () => {
        try {
            const response = await authFetch('/api/auth/me', { credentials: 'same-origin' });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                if (response.status === 401 && /api key/i.test(String(data.error || ''))) {
                    revealDeploymentKeyHelp();
                }
                return false;
            }
            const data = await response.json();
            state.user = data.user;
            state.csrfToken = data.csrf_token;
            window.brachybotAuth = api;
            setVisible(false);
            renderAccount();
            // Identity is needed before the first server-backed session list;
            // an edit lease is not. Do not make the sidebar wait for a slow
            // lease response, and let the workspace refresh it in parallel.
            void acquireLease().catch(error => console.debug('[auth] initial lease refresh deferred:', error));
            return true;
        } catch (_) {
            return false;
        }
        })();
        try {
            return await authenticationPromise;
        } finally {
            authenticationPromise = null;
        }
    }

    const api = {
        get user() { return state.user; },
        get csrfToken() { return state.csrfToken; },
        get editorToken() { return editorToken; },
        renderWorkspaceLock,
        dismissWorkspaceLockNotice,
        authenticated,
        acquireLease,
        takeoverLease,
        applyLeaseResult,
        refreshLease,
        releaseLease,
        renderAuthI18n,
        setAuthLangToggleState,
        async logout() {
            await releaseLease();
            try { await request('/api/auth/logout', {}, false); } catch (_) {}
            state.user = null;
            state.csrfToken = null;
            // Clear the remembered username so the next sign-in starts blank.
            try { localStorage.removeItem(rememberKey); } catch (_) {}
            location.reload();
        },
        async importLegacyBrowserData() {
            let legacySessions = {};
            try { legacySessions = JSON.parse(localStorage.getItem('brachybot_sessions') || '{}'); } catch (_) {}
            const legacyActive = localStorage.getItem('brachybot_active_session') || '';
            const sources = Object.values(legacySessions || {});
            if (!sources.length) throw new Error('No legacy browser session was found');
            const imported = [];
            for (const source of sources) {
                const legacyId = source.id || legacyActive || 'web';
                let report = {};
                let manual = {};
                try { report.form = JSON.parse(localStorage.getItem(`brachyplan_reportForm:${legacyId}`) || '{}'); } catch (_) {}
                try { manual = JSON.parse(localStorage.getItem(`brachybot_manual_state:${legacyId}`) || '{}'); } catch (_) {}
                const created = await request('/api/workspace/import-client', {
                    title: source.title || 'Imported browser case',
                    chat: { messages: source.messages || [] },
                    report,
                    ui: { manual },
                }, false);
                imported.push({ legacyId, session: created.session });
            }
            localStorage.removeItem('brachybot_sessions');
            localStorage.removeItem('brachybot_active_session');
            const selected = imported.find(item => item.legacyId === legacyActive) || imported[0];
            return { sessions: imported.map(item => item.session), session: selected?.session || null };
        },
    };
    window.brachybotAuth = api;

    // =========================================================================
    // Wire up the auth surface as soon as the DOM is ready.
    // =========================================================================
    function initAuthSurface() {
        // The lang toggle mirrors the global header toggle; clicks call the
        // same setUiLanguage so language state stays single-sourced.
        bindAuthLangToggle();
        setAuthLangToggleState();
        renderAuthI18n();
        window.addEventListener('i18nchange', () => {
            renderAuthI18n();
            setAuthLangToggleState();
        });

        // Password show/hide toggles.
        bindPasswordToggle('authPasswordToggle', 'authPassword');
        bindPasswordToggle('newPasswordToggle', 'newPassword');

        // Submit / register buttons + form submit.
        const form = document.getElementById('authForm');
        if (form) {
            form.addEventListener('submit', (ev) => {
                ev.preventDefault();
                submit('login');
            });
        }
        const loginBtn = document.getElementById('authLogin');
        const registerBtn = document.getElementById('authRegister');
        if (loginBtn) loginBtn.addEventListener('click', () => submit('login'));
        if (registerBtn) registerBtn.addEventListener('click', () => submit('register'));
        // Clear the field-level error as soon as the user starts typing.
        ['authUsername', 'authPassword'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('input', () => {
                const field = id === 'authUsername' ? 'username' : 'password';
                setFieldError(field, '');
                setStatus('', false);
            });
        });

        // Deployment-key Enter submits; standalone input fields.
        const depKey = document.getElementById('authDeploymentKey');
        if (depKey) depKey.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') { event.preventDefault(); submit('login'); }
        });

        // Account actions in the main header.
        document.getElementById('accountLogout')?.addEventListener('click', () => api.logout());
        document.getElementById('accountPassword')?.addEventListener('click', () => {
            setPasswordStatus('', false);
            setPasswordVisible(true);
        });
        document.getElementById('passwordCancel')?.addEventListener('click', () => setPasswordVisible(false));
        const pwForm = document.getElementById('passwordForm');
        if (pwForm) pwForm.addEventListener('submit', (ev) => {
            ev.preventDefault();
            changePassword();
        });
        const newPw = document.getElementById('newPassword');
        if (newPw) newPw.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') { event.preventDefault(); changePassword(); }
        });

        // Legacy import.
        document.getElementById('importLegacyWorkspace')?.addEventListener('click', async () => {
            try {
                const result = await api.importLegacyBrowserData();
                if (typeof window.loadServerSessions === 'function') await window.loadServerSessions();
                if (result.session && typeof window.switchSession === 'function') await window.switchSession(result.session.id);
            } catch (error) { setStatus(mapAuthError(error.serverMessage || error.message, error.status || 0), true); }
        });
    }

    document.addEventListener('DOMContentLoaded', async () => {
        try { initAuthSurface(); } catch (error) { console.error('[AUTH] init failed:', error); }
        state.booted = true;
        const valid = await authenticated();
        if (!valid) setVisible(true);
        setInterval(refreshLease, 25000);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshLease(); });
        window.addEventListener('pagehide', () => {
            if (!state.user) return;
            fetch('/api/workspace/lease', { method: 'DELETE', keepalive: true, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrfToken, 'X-BrachyBot-Editor': editorToken }, body: JSON.stringify({ editor_token: editorToken, session_id: currentLeaseSessionId() }) });
        });
    });
})();
