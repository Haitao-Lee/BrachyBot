/* Account bootstrap and authenticated API request wrapper. */
(function () {
    const state = { user: null, csrfToken: null, booted: false };
    const editorKey = 'brachybot_editor_token';
    const AUTH_REQUEST_TIMEOUT_MS = 12000;
    const LEASE_RELEASE_TIMEOUT_MS = 4000;
    let editorToken = sessionStorage.getItem(editorKey);
    if (!editorToken) {
        editorToken = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, '');
        sessionStorage.setItem(editorKey, editorToken);
    }

    function setStatus(message, error) {
        const target = document.getElementById('authStatus');
        if (!target) return;
        target.textContent = message || '';
        target.classList.toggle('error', !!error);
    }

    function setVisible(visible) {
        const overlay = document.getElementById('authOverlay');
        if (overlay) overlay.hidden = !visible;
    }

    function setPasswordVisible(visible) {
        const overlay = document.getElementById('passwordOverlay');
        if (overlay) overlay.hidden = !visible;
        if (visible) document.getElementById('currentPassword')?.focus();
    }

    function setPasswordStatus(message, error) {
        const target = document.getElementById('passwordStatus');
        if (!target) return;
        target.textContent = message || '';
        target.classList.toggle('error', !!error);
    }

    function setDeploymentAccessKey(value) {
        const key = String(value || '').trim();
        if (typeof window.setBrachyBotApiKey === 'function') {
            window.setBrachyBotApiKey(key);
        } else {
            // The UI API wrapper normally provides this helper. Keep the
            // login shell usable when static assets are temporarily cached
            // out of order, without persisting the credential to a case.
            window.BRACHYBOT_API_KEY = key;
            if (key) sessionStorage.setItem('BRACHYBOT_API_KEY', key);
            else sessionStorage.removeItem('BRACHYBOT_API_KEY');
        }
    }

    function revealDeploymentKeyHelp(message) {
        const details = document.getElementById('authAccessKeyDetails');
        const input = document.getElementById('authDeploymentKey');
        if (details) details.open = true;
        if (input) input.focus();
        setStatus(message || 'This server requires its deployment access key before you can sign in or create an account.', true);
    }

    function renderAccount() {
        const host = document.getElementById('accountStatus');
        const name = document.getElementById('accountName');
        if (host) host.hidden = !state.user;
        if (name) name.textContent = state.user?.username || '';
    }

    let workspaceLockDismissedKey = '';

    function workspaceLockKey() {
        const session = document.getElementById('sessionDisplay');
        return `brachybot:lock-notice:${String(session?.textContent || 'current').trim()}`;
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
                throw new Error('The BrachyBot server did not respond. Check that the server is running.');
            }
            throw error;
        } finally {
            if (timer) clearTimeout(timer);
        }
    }

    async function request(path, body) {
        const response = await authFetch(path, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', ...(state.csrfToken ? { 'X-CSRF-Token': state.csrfToken } : {}) },
            body: JSON.stringify(body || {}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    }

    async function acquireLease() {
        if (!state.user) return { editable: false };
        try {
            const result = await request('/api/workspace/lease', { editor_token: editorToken, ttl_seconds: 75 });
            return applyLeaseResult(result);
        } catch (error) {
            return applyLeaseResult({ editable: false, error: error.message });
        }
    }

    function applyLeaseResult(result) {
        const editable = !!result?.editable;
        document.body.classList.toggle('workspace-readonly', !editable);
        renderWorkspaceLock(!editable);
        return result || { editable };
    }

    async function refreshLease() {
        if (state.user && !document.hidden) await acquireLease();
    }

    async function releaseLease() {
        if (!state.user) return;
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
                body: JSON.stringify({ editor_token: editorToken }),
            }, LEASE_RELEASE_TIMEOUT_MS);
        } catch (_) {
            // A short lease expiry is the fallback when the browser is offline.
        }
    }

    async function authenticated() {
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
            await acquireLease();
            return true;
        } catch (_) {
            return false;
        }
    }

    async function submit(mode) {
        const username = document.getElementById('authUsername')?.value.trim();
        const password = document.getElementById('authPassword')?.value || '';
        const deploymentKey = document.getElementById('authDeploymentKey')?.value || '';
        if (deploymentKey.trim()) setDeploymentAccessKey(deploymentKey);
        try {
            setStatus(mode === 'register' ? 'Creating account...' : 'Signing in...');
            const data = await request(`/api/auth/${mode}`, { username, password });
            state.user = data.user;
            state.csrfToken = data.csrf_token;
            setVisible(false);
            renderAccount();
            await acquireLease();
            if (typeof window.startBrachyBotApplication === 'function') {
                window.startBrachyBotApplication();
            }
        } catch (error) {
            if (/api key/i.test(String(error.message || ''))) revealDeploymentKeyHelp(String(error.message));
            else setStatus(error.message, true);
        }
    }

    async function changePassword() {
        const currentPassword = document.getElementById('currentPassword')?.value || '';
        const newPassword = document.getElementById('newPassword')?.value || '';
        try {
            setPasswordStatus('Updating password...');
            await request('/api/auth/password', { current_password: currentPassword, new_password: newPassword });
            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            setPasswordVisible(false);
        } catch (error) {
            setPasswordStatus(error.message, true);
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
        next.headers = headers;
        return nativeFetch(input, next);
    };

    const api = {
        get user() { return state.user; },
        get csrfToken() { return state.csrfToken; },
        get editorToken() { return editorToken; },
        renderWorkspaceLock,
        dismissWorkspaceLockNotice,
        authenticated,
        acquireLease,
        applyLeaseResult,
        refreshLease,
        releaseLease,
        async logout() {
            await releaseLease();
            await request('/api/auth/logout');
            state.user = null;
            state.csrfToken = null;
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
                });
                imported.push({ legacyId, session: created.session });
            }
            localStorage.removeItem('brachybot_sessions');
            localStorage.removeItem('brachybot_active_session');
            const selected = imported.find(item => item.legacyId === legacyActive) || imported[0];
            return { sessions: imported.map(item => item.session), session: selected?.session || null };
        },
    };
    window.brachybotAuth = api;

    document.addEventListener('DOMContentLoaded', async () => {
        document.getElementById('authLogin')?.addEventListener('click', () => submit('login'));
        document.getElementById('authRegister')?.addEventListener('click', () => submit('register'));
        document.getElementById('authPassword')?.addEventListener('keydown', event => {
            if (event.key === 'Enter') submit('login');
        });
        document.getElementById('authDeploymentKey')?.addEventListener('keydown', event => {
            if (event.key === 'Enter') submit('login');
        });
        document.getElementById('accountLogout')?.addEventListener('click', () => api.logout());
        document.getElementById('accountPassword')?.addEventListener('click', () => {
            setPasswordStatus('');
            setPasswordVisible(true);
        });
        document.getElementById('passwordCancel')?.addEventListener('click', () => setPasswordVisible(false));
        document.getElementById('passwordSave')?.addEventListener('click', changePassword);
        document.getElementById('newPassword')?.addEventListener('keydown', event => {
            if (event.key === 'Enter') changePassword();
        });
        document.getElementById('importLegacyWorkspace')?.addEventListener('click', async () => {
            try {
                const result = await api.importLegacyBrowserData();
                if (typeof window.loadServerSessions === 'function') await window.loadServerSessions();
                if (result.session && typeof window.switchSession === 'function') await window.switchSession(result.session.id);
            } catch (error) { setStatus(error.message, true); }
        });
        const valid = await authenticated();
        if (!valid) setVisible(true);
        setInterval(refreshLease, 25000);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshLease(); });
        window.addEventListener('pagehide', () => {
            if (!state.user) return;
            fetch('/api/workspace/lease', { method: 'DELETE', keepalive: true, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrfToken, 'X-BrachyBot-Editor': editorToken }, body: JSON.stringify({ editor_token: editorToken }) });
        });
    });
})();
