// Production logging is quiet by default. Enable detailed UI diagnostics from
// the browser console with `window.BRACHYBOT_DEBUG_UI = true`.
function uiDebugLog(...args) {
    if (window.BRACHYBOT_DEBUG_UI) console.debug(...args);
}

function effectiveUiLanguage() {
    return window._i18nLang || 'en';
}
window.effectiveUiLanguage = effectiveUiLanguage;

function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/******** SESSION MANAGEMENT ********/
const SESSIONS_KEY = 'brachybot_sessions';
const ACTIVE_KEY = 'brachybot_active_session';

let sessions = {};
let activeSessionId = null;

function caseStorageKey(base, sessionId = activeSessionId) {
    const safeId = String(sessionId || 'web').replace(/[^a-zA-Z0-9_.-]/g, '_');
    return `${base}:${safeId}`;
}
window.caseStorageKey = caseStorageKey;

function removeSessionScopedLocalState(sessionId) {
    const bases = [
        'brachybot_manual_state',
        'brachyplan_reportForm',
        'brachyplan_report_audit',
        'brachyplan_report_snapshots',
    ];
    for (const base of bases) {
        try { localStorage.removeItem(caseStorageKey(base, sessionId)); } catch (_) {}
    }
}

function loadSessions() {
    // The durable workspace bridge is loaded after this legacy script.  A
    // direct call to this top-level function must still reach the server
    // implementation; assigning window.loadSessions alone does not replace
    // this script's global binding in all browsers.
    if (window.__serverWorkspaceReady && typeof window.loadServerSessions === 'function') {
        return window.loadServerSessions();
    }
    // PERSISTENT + AUTO-NEW (2026-06-15): the user wants two
    // apparently-opposite things:
    //   (a) fresh page load should NOT show stale conversations
    //       from a previous browser session
    //   (b) sessions must NOT be wiped on refresh — only manual
    //       delete should remove them
    // The fix: always restore previous sessions from localStorage
    // (so refresh preserves them), and if no session is currently
    // active, create ONE new "New chat" session as the default
    // landing target. The chat area then shows the welcome message
    // (because the new session is empty), but the user can click
    // any prior session in the sidebar to switch back.
    try {
        const data = localStorage.getItem(SESSIONS_KEY);
        sessions = data ? JSON.parse(data) : {};
        uiDebugLog(`[Session] Loaded ${Object.keys(sessions).length} sessions from localStorage`);
    } catch {
        sessions = {};
    }
    // Try to restore the previously-active session id. If it still
    // exists, keep it active (so refresh preserves the chat the
    // user was looking at). If it no longer exists (e.g. user
    // cleared data on another tab), create a fresh "New chat".
    let savedActive = null;
    try { savedActive = localStorage.getItem(ACTIVE_KEY); } catch (_) {}
    if (savedActive && sessions[savedActive]) {
        activeSessionId = savedActive;
    } else {
        // No active session — reuse an existing empty "New chat" if
        // one exists, otherwise create a fresh one. This prevents
        // accumulating empty sessions on every page refresh.
        const existingNew = Object.values(sessions).find(
            s => s.title === 'New chat' && (!s.messages || s.messages.length === 0)
        );
        if (existingNew) {
            activeSessionId = existingNew.id;
        } else {
            const id = generateSessionId();
            sessions[id] = {
                id,
                title: 'New chat',
                messages: [],
                created: Date.now(),
            };
            activeSessionId = id;
        }
        saveSessions();
    }
}

// Called by sendChat() right before sending the user's first
// message. Creates a fresh "New chat" session IF there isn't one
// already pending. The session's id is persisted in localStorage
// so the user can find it again next time.
function ensurePendingSession() {
    if (activeSessionId && sessions[activeSessionId]) return;
    const id = generateSessionId();
    sessions[id] = {
        id,
        title: 'New chat',
        messages: [],
        created: Date.now(),
        // Mark this session as "in progress" so the UI shows the
        // typing indicator (the welcome message gets cleared when
        // the LLM's first response arrives).
        pending: true,
    };
    activeSessionId = id;
    saveSessions();
    // Re-render the session list so the new session appears
    // immediately in the sidebar.
    if (typeof renderSessionList === 'function') renderSessionList();
}

function saveSessions() {
    // Clinical session state is server-owned.  Keep this legacy function as
    // a compatibility shim for older call sites, but never write a second,
    // divergent browser-local session store once the workspace bridge is up.
    if (window.__serverWorkspaceReady && typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('chat.changed');
        return;
    }
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
    localStorage.setItem(ACTIVE_KEY, activeSessionId);
    uiDebugLog(`[Session] Saved ${Object.keys(sessions).length} sessions, active=${activeSessionId}`);
}

function generateSessionId() {
    return 'sess_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// Wipe ALL locally-stored chat data: sessions, active-session
// pointer, report form, layout preferences (column widths).
// Server-side state (CT load, planning results) is NOT touched
// — that's owned by the agent's per-session memory and the user
// would have to actively clear it via the "Clear" button in the
// Input panel. The user asked for clean data isolation between
// page loads; this is the manual way to enforce it if the
// auto-clear-on-page-load behavior isn't enough.
async function clearLocalChatData(options = {}) {
    const message = 'Clear only locally stored browser display data?\n' +
        'This will remove legacy chat caches, report form caches, and layout preferences.\n\n' +
        'Case CT, planning, and server workspace data will be retained.';
    const ok = options.skipConfirm === true || (
        typeof window._confirmAction === 'function'
            ? await window._confirmAction(
                '清除浏览器本地显示缓存？病例 CT、规划和服务端工作区数据不会删除。',
                message,
            )
            : false
    );
    if (!ok) return { success: false, cancelled: true };
    try {
        // Chat sessions + active-session pointer
        localStorage.removeItem('brachybot_sessions');
        localStorage.removeItem('brachybot_active_session');
        // Report form (saved data)
        localStorage.removeItem('brachyplan_reportForm');
        localStorage.removeItem('brachybot_manual_state');
        localStorage.removeItem('brachyplan_report_audit');
        localStorage.removeItem('brachyplan_report_snapshots');
        // Report auto-save data
        try { localStorage.removeItem('brachybot_report_autosave'); } catch (_) {}
        // Layout preferences (column widths) — but keep the
        // user's last-typed values for the form fields
        ['layout.sidebar.width', 'layout.right.width'].forEach(k => {
            try { localStorage.removeItem(k); } catch (_) {}
        });
        const scopedPrefixes = [
            'brachybot_manual_state:',
            'brachyplan_reportForm:',
            'brachyplan_report_audit:',
            'brachyplan_report_snapshots:',
        ];
        for (let index = localStorage.length - 1; index >= 0; index -= 1) {
            const key = localStorage.key(index);
            if (key && scopedPrefixes.some(prefix => key.startsWith(prefix))) {
                localStorage.removeItem(key);
            }
        }
    } catch (e) {
        console.warn('clearLocalChatData: partial failure', e);
    }
    // Reload the page so the cleared state takes effect everywhere
    // (sidebar re-renders, report panel resets, etc).
    try { location.reload(); } catch (_) {}
    return { success: true, scope: 'browser_cache', reloading: true };
}

function toggleSessionSidebar() {
    const sidebar = document.getElementById('sessionSidebar');
    if (!sidebar) return;
    if (window.matchMedia && window.matchMedia('(max-width: 900px)').matches) {
        sidebar.style.display = '';
        sidebar.classList.toggle('mobile-open');
        return;
    }
    if (sidebar.style.display === 'none') {
        sidebar.style.display = '';
    } else {
        sidebar.style.display = 'none';
    }
}

function closeSessionSidebar() {
    const sidebar = document.getElementById('sessionSidebar');
    if (!sidebar) return;
    sidebar.classList.remove('mobile-open');
    if (!(window.matchMedia && window.matchMedia('(max-width: 900px)').matches)) {
        sidebar.style.display = 'none';
    }
}

function _canChangeChatSession() {
    const activeStream = (typeof window._chatStreaming === 'boolean' && window._chatStreaming)
        || (typeof isStreaming !== 'undefined' && isStreaming);
    if (!activeStream) return true;
    if (typeof addChat === 'function') {
        addChat('system', 'Stop the current response before changing sessions.');
    }
    return false;
}

async function newChat() {
    if (window.__serverWorkspaceReady && typeof window.newChat === 'function' && window.newChat !== newChat) {
        return window.newChat();
    }
    if (!_canChangeChatSession()) return;
    if (typeof flushActiveReportState === 'function') flushActiveReportState();
    const id = generateSessionId();
    sessions[id] = { id, title: 'New chat', messages: [], created: Date.now() };
    activeSessionId = id;
    saveSessions();
    renderSessionList();
    loadSessionChat(id);

    // The request wrapper attaches the newly selected session ID, so this
    // cannot clear another chat's case data.
    try { await fetch(API + '/clear_all', { method: 'POST' }); } catch (_) {}
    if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
}

async function switchSession(id) {
    if (window.__serverWorkspaceReady && typeof window.switchSession === 'function' && window.switchSession !== switchSession) {
        return window.switchSession(id);
    }
    document.getElementById('sessionSidebar')?.classList.remove('mobile-open');
    if (id === activeSessionId || !sessions[id] || !_canChangeChatSession()) return;
    if (typeof flushActiveReportState === 'function') flushActiveReportState();
    activeSessionId = id;
    saveSessions();
    renderSessionList();
    loadSessionChat(id);
    if (typeof restoreActiveSessionWorkspace === 'function') {
        try { await restoreActiveSessionWorkspace({ clearReport: true }); }
        catch (error) { console.warn('Session workspace restore failed:', error); }
    }
}

async function deleteSession(id, options = {}) {
    if (window.__serverWorkspaceReady && typeof window.deleteSession === 'function' && window.deleteSession !== deleteSession) {
        return window.deleteSession(id, options);
    }
    if (Object.keys(sessions).length <= 1 || !sessions[id] || !_canChangeChatSession()) return;
    if (options.skipConfirm !== true) {
        const prompt = `Delete session "${sessions[id].title || id}"? This cannot be undone.`;
        const confirmed = typeof window._confirmAction === 'function'
            ? await window._confirmAction(prompt, prompt)
            : false;
        if (!confirmed) return;
    }
    const wasActive = activeSessionId === id;
    if (wasActive && typeof flushActiveReportState === 'function') flushActiveReportState();
    delete sessions[id];
    removeSessionScopedLocalState(id);
    if (wasActive) {
        activeSessionId = Object.keys(sessions)[0];
    }
    saveSessions();
    renderSessionList();
    if (wasActive) loadSessionChat(activeSessionId);

    // Reset the deleted backend agent explicitly; its ID differs from the
    // now-active session and therefore cannot rely on the implicit header.
    try {
        await fetch(API + '/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: id }),
        });
    } catch (_) {}
    if (wasActive && typeof restoreActiveSessionWorkspace === 'function') {
        try { await restoreActiveSessionWorkspace({ clearReport: true }); }
        catch (error) { console.warn('Session workspace restore failed:', error); }
    }
}

async function clearCurrentChatHistory(options = {}) {
    if (!activeSessionId || !sessions[activeSessionId] || !_canChangeChatSession()) return false;
    if (options.skipConfirm !== true) {
        const prompt = 'Clear the current conversation history? Planning and image data will be retained.';
        const confirmed = typeof window._confirmAction === 'function'
            ? await window._confirmAction(prompt, prompt)
            : false;
        if (!confirmed) return false;
    }
    sessions[activeSessionId].messages = [];
    sessions[activeSessionId].pending = false;
    saveSessions();
    loadSessionChat(activeSessionId);
    try {
        await fetch(API + '/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clear_context: true, stream: false, session_id: activeSessionId }),
        });
    } catch (error) {
        console.warn('Backend conversation clear failed:', error);
    }
    return true;
}

function startRenameSession(id, event) {
    event.stopPropagation();
    const titleEl = document.getElementById('session-title-' + id);
    if (!titleEl) return;

    const session = sessions[id];
    const currentTitle = session.title;

    // Replace title with input
    titleEl.innerHTML = `<input class="session-item-rename-input" id="rename-input-${id}" value="${escHtml(currentTitle)}" />`;
    const input = document.getElementById('rename-input-' + id);
    input.focus();
    input.select();

    // Handle save on Enter or blur
    const saveRename = async () => {
        const newTitle = input.value.trim() || 'Untitled';
        try {
            if (typeof renameServerSession === 'function') await renameServerSession(id, newTitle);
            else {
                // Legacy localStorage mode has no server metadata to confirm.
                session.title = newTitle;
                saveSessions();
            }
        } catch (error) {
            // Do not retain an optimistic title when the durable repository
            // rejects the write because another browser owns the edit lease.
            session.title = currentTitle;
            renderSessionList();
            console.warn('Case rename failed:', error);
            return;
        }
        renderSessionList();
        if (id === activeSessionId) {
            document.getElementById('chatSessionTitle').textContent = session.title || newTitle;
        }
    };

    input.onkeydown = (e) => {
        if (e.key === 'Enter') saveRename();
        if (e.key === 'Escape') renderSessionList(); // Cancel
    };
    input.onblur = saveRename;
}

function renderSessionList() {
    const list = document.getElementById('sessionList');
    const sorted = Object.values(sessions).sort((a, b) => b.created - a.created);
    const locale = effectiveUiLanguage() === 'zh' ? 'zh-CN' : 'en-US';
    list.innerHTML = sorted.map(s => {
        const time = new Date(s.created).toLocaleDateString(locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        const active = s.id === activeSessionId ? ' active' : '';
        return `<div class="session-item${active}" onclick="switchSession('${s.id}')">
            <div class="session-item-info">
                <div class="session-item-title" id="session-title-${s.id}">${escHtml(s.title)}</div>
                <div class="session-item-time">${time}</div>
            </div>
            <div class="session-item-actions">
                <button class="session-item-btn" onclick="startRenameSession('${s.id}', event)" title="Rename">&#9998;</button>
                <button class="session-item-btn delete" onclick="event.stopPropagation();deleteSession('${s.id}')" title="Delete">&#10005;</button>
            </div>
        </div>`;
    }).join('');
}

function loadSessionChat(id) {
    const session = sessions[id];
    if (!session) return;
    // Rebuild terminal-style command history from this case before drawing
    // the transcript.  This prevents stale input from another session from
    // surviving a fast case switch or server reconnect.
    if (typeof syncChatHistoryForSession === 'function') {
        syncChatHistoryForSession(id, session.messages);
    }
    const input = document.getElementById('chatInput');
    if (input) {
        // The composer belongs to the selected case. Clearing it on every
        // case render prevents a stale draft or command from another case
        // being mistaken for this case's most recent prompt.
        input.value = '';
        input.dataset.historySession = String(id);
    }
    const lastUserMessage = [...(session.messages || [])]
        .reverse()
        .find(message => message && message.type === 'user' && typeof message.content === 'string');
    window._lastUserMessage = lastUserMessage?.content || '';
    const container = document.getElementById('chatMessages');
    container.innerHTML = '';
    if (session.messages.length === 0) {
        const welcome = window._t
            ? window._t(
                '欢迎使用 BrachyBot。请描述你的近距离治疗病例——肿瘤位置、类型、患者情况——我会帮助你生成治疗计划。也可以直接在右侧的输入面板加载 CT 数据。',
                'Welcome to BrachyBot. Describe your brachytherapy case — tumor location, type, patient condition — and I will help you generate a treatment plan. You can also load CT data directly from the Input panel.'
            )
            : 'Welcome to BrachyBot. Describe your brachytherapy case or load CT data from the Input panel.';
        container.innerHTML = '<div class="chat-msg system">' + escHtml(welcome) + '</div>';
    } else {
        // DEDUP ON RENDER (2026-06-15): the user had a bug where on
        // page refresh, the same chat message was rendered 2-4
        // times. Root cause: sendChat retried on network error
        // (the catch block in sendChat calls addChat('error', ...))
        // and each retry also called saveSessionMessage, producing
        // an array like [user, error, user, error, ...]. On refresh
        // the array was replayed verbatim.
        //
        // Repair only the historical duplicate pattern, without deleting
        // legitimate repeated questions or answers elsewhere in the case
        // transcript. After transient send failures are dropped, accidental
        // retry duplicates become adjacent. Non-adjacent equal text is a
        // real part of a clinical conversation and must be preserved.
        const msgs = session.messages;
        const deduped = [];
        const canonicalType = message => message?.type === 'bot-response' ? 'bot' : message?.type;
        for (let i = 0; i < msgs.length; i++) {
            const m = msgs[i];
            // Skip transient error messages — they're for live
            // debugging, not for the persistent transcript.
            if (m.type === 'error' && typeof m.content === 'string'
                && /^Send failed/i.test(m.content)) {
                continue;
            }
            const previous = deduped[deduped.length - 1];
            const sameAdjacentMessage = previous
                && canonicalType(previous) === canonicalType(m)
                && String(previous.content || '') === String(m.content || '');
            if (sameAdjacentMessage) continue;
            deduped.push(m);
        }
        deduped.forEach(msg => {
            if (msg.type === 'thinking') {
                renderThinkingChain(msg.steps);
            } else {
                // fromSession=true tells addChat NOT to call
                // saveSessionMessage again — the message is already
                // in the session, we are just re-rendering it.
                addChat(msg.type, msg.content, false, msg.timestamp || null, true);
            }
        });
    }
    const title = session.messages.length > 0 ? session.title : 'New conversation';
    document.getElementById('chatSessionTitle').textContent = title;
    container.scrollTop = container.scrollHeight;
}

function saveSessionMessage(type, content, steps, timestamp, sessionId = activeSessionId) {
    const ownerSessionId = String(sessionId || '');
    const session = sessions[ownerSessionId];
    if (!session) return;
    // DEDUP ON SAVE (2026-06-15): if the most recent message has
    // the same type+content, skip the new one. This prevents the
    // page-refresh bug where a network error or double-Enter sent
    // the user's message multiple times in a row, all of which
    // got persisted to localStorage and re-rendered on every
    // refresh. The user saw 2-4 copies of the same message stacked
    // in the chat. With this dedup, only the FIRST save wins and
    // subsequent duplicates are silently dropped. (The visual UI
    // is still updated by the caller's separate addChat call —
    // this only affects persistence.)
    const _last = session.messages[session.messages.length - 1];
    if (_last && _last.type === type && _last.content === content) {
        return;
    }
    // Store the timestamp so session restore shows the time the
    // message was originally sent, not the time of page refresh.
    // addChat() passes Date.now() when persisting live messages.
    const _ts = (typeof timestamp === 'number' && timestamp > 0) ? timestamp : Date.now();
    session.messages.push({ type, content, steps: steps || null, timestamp: _ts });
    if (type === 'user' && typeof _rememberChatCommand === 'function') {
        _rememberChatCommand(content);
    }
    if (session.messages.length === 1 && type === 'user') {
        session.title = content.slice(0, 40) + (content.length > 40 ? '...' : '');
        if (ownerSessionId === String(activeSessionId || '')) {
            document.getElementById('chatSessionTitle').textContent = session.title;
            renderSessionList();
        }
    }
    saveSessions();
    // Persist the transcript through the durable case workspace even when a
    // legacy caller reaches the old saveSessions binding directly.
    if (ownerSessionId === String(activeSessionId || '')
        && window.__serverWorkspaceReady
        && typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('chat.message');
    }
}

// ----- Chat message rendering -----
// `addChat` is called from 40+ sites in this file (CT load progress,
// planning step results, errors, system notices, …) but was never
// defined. We provide a minimal, safe implementation that:
//   - For user / bot messages: wraps in a .chat-row with a .chat-avatar
//     on the side (the design system expects this DOM shape; without
//     the wrapper, avatars were never rendered even though the CSS
//     .chat-avatar { … } exists).
//   - For system / error messages: renders a compact timestamped timeline row
//     so repeated UI events remain readable without looking like bot answers.
//   - preserves newlines (becomes <br>)
//   - autoscrolls to the bottom
//   - tolerates missing container, missing type, undefined content
//   - silently no-ops in non-browser contexts (e.g. unit tests)
// SVG icons for user vs bot avatars (restored from upstream)
const CHAT_AVATAR_SVGS = {
    user:  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    // BUG FIX 2026-06-17: bot avatar now uses the unified BrachyBot
    // logo (the same one shown in the Report cover page) so the
    // BUG FIX 2026-06-17 (BrachyBot logo v2): the user designed a
    // proper BrachyBot logo (B + head silhouette + circuit +
    // needle + radioactive seed) and saved it as a 1254x1254 PNG.
    // The chat bot avatar now uses the smaller 256x256 version
    // (_assets/brachybot-avatar.png) for performance. The brand
    // is consistent across the chat panel and the report.
    bot:   '<img src="_assets/brachybot-avatar.png" alt="BrachyBot" style="width:100%;height:100%;display:block;object-fit:contain;border-radius:50%;"/>',
};

// Language-aware labels for the usage-bar footer. The footer is
// one of the few UI elements whose labels are user-facing text
// (not class names / IDs), so it needs to follow the same
// explicit interface language as the todo list. Server-detected response
// language affects the LLM reply only and must not silently switch controls.
//
// Key mapping mirrors memory/language.py server-side detection:
//   zh → Chinese, en → English, ja → Japanese, ko → Korean,
//   ru → Russian, ar → Arabic.
const FOOTER_I18N = {
    zh: {
        time:  '耗时',
        tokens:'Tokens',
        input: '输入',
        output:'输出',
        tools: '工具',
        unit_s:'秒',
        unit_times:'次',
    },
    en: {
        time:  'Time',
        tokens:'Tokens',
        input: 'Input',
        output:'Output',
        tools: 'Tools',
        unit_s:'s',
        unit_times:'×',
    },
    ja: {
        time:  '時間',
        tokens:'トークン',
        input: '入力',
        output:'出力',
        tools: 'ツール',
        unit_s:'秒',
        unit_times:'回',
    },
    ko: {
        time:  '시간',
        tokens:'토큰',
        input: '입력',
        output:'출력',
        tools: '도구',
        unit_s:'초',
        unit_times:'회',
    },
    ru: {
        time:  'Время',
        tokens:'Токенов',
        input: 'Вход',
        output:'Выход',
        tools: 'Инструментов',
        unit_s:'с',
        unit_times:'раз',
    },
    ar: {
        time:  'الوقت',
        tokens:'الرموز',
        input: 'إدخال',
        output:'إخراج',
        tools: 'الأدوات',
        unit_s:'ث',
        unit_times:'مرات',
    },
};
function _footerI18n() {
    const code = effectiveUiLanguage();
    return FOOTER_I18N[code] || FOOTER_I18N.en;
}

// Build the small footer that sits below the bot's response bubble.
// The footer is a single horizontal row with: response time (left),
// then token counts, then tool call count. All in monospace numerals
// and a dimmed text color so the footer doesn't compete with the
// actual reply text for attention. The data comes from
// `llm_meta` (server) plus client-side elapsed time.
//   llm_meta = {
//       usage: {prompt_tokens, completion_tokens, total_tokens},
//       latency_ms: number,  // server-side LLM time
//       llm_calls: number,   // how many LLM round-trips
//   }
function _buildResponseFooter(llmMeta) {
    const footer = document.createElement('div');
    footer.className = 'usage-bar';
    // We compute elapsed time client-side from when the SSE 'start'
    // event arrived. If for some reason _chatTurnStartTime isn't
    // set, fall back to the server-reported latency.
    const clientMs = (window._chatTurnStartTime)
        ? (Date.now() - window._chatTurnStartTime)
        : 0;
    const serverMs = (llmMeta && llmMeta.latency_ms) ? llmMeta.latency_ms : 0;
    // Prefer the larger of the two — usually the client-measured
    // time (includes network overhead too) is what the user perceives.
    const totalMs = Math.max(clientMs, serverMs);
    const totalSec = (totalMs / 1000).toFixed(1);

    const usage = (llmMeta && llmMeta.usage) || {};
    const promptT = usage.prompt_tokens || 0;
    const compT = usage.completion_tokens || 0;
    const totalT = usage.total_tokens || 0;
    const toolCalls = (window._todoTurnToolCount !== undefined)
        ? window._todoTurnToolCount
        : ((llmMeta && llmMeta.llm_calls) || 0);

    // Build the items in a single flex row. Each item is label + value.
    // Keep the label light (var(--text-dim)) and the value bolder so
    // the numbers are the focal point. Numbers use a tabular-nums
    // font-feature so multi-digit counts don't jiggle horizontally
    // as they tick up during streaming.
    const makeItem = (label, value, unit) => {
        const item = document.createElement('span');
        item.className = 'usage-item';
        const lbl = document.createElement('span');
        lbl.className = 'usage-label';
        lbl.textContent = label;
        const val = document.createElement('span');
        val.className = 'usage-value';
        val.textContent = value + (unit || '');
        item.appendChild(lbl);
        item.appendChild(val);
        return item;
    };
    const sep = () => {
        const s = document.createElement('span');
        s.className = 'usage-sep';
        return s;
    };

    const t = _footerI18n();

    // Build footer items in a fixed order:
    //   Time  Tokens (Input/Output)  Tools
    // The Input/Output breakdown is split into TWO separate
    // items (e.g. "Input 800" and "Output 434") so the user can
    // see the breakdown at a glance — the old "↑↓ 800/434" was
    // visually compact but hard to read.
    footer.appendChild(makeItem(t.time, totalSec, t.unit_s));
    footer.appendChild(sep());
    if (totalT > 0) {
        footer.appendChild(makeItem(t.tokens, totalT.toLocaleString(), ''));
        footer.appendChild(sep());
        if (promptT > 0) {
            footer.appendChild(makeItem(t.input, promptT.toLocaleString(), ''));
            footer.appendChild(sep());
        }
        if (compT > 0) {
            footer.appendChild(makeItem(t.output, compT.toLocaleString(), ''));
            footer.appendChild(sep());
        }
    }
    footer.appendChild(makeItem(t.tools, toolCalls.toString(), t.unit_times));

    // Reset the per-turn counters so the next turn starts fresh.
    window._chatTurnStartTime = null;
    window._todoTurnToolCount = 0;
    return footer;
}

function addChat(type, content, scroll, timestamp, fromSession, sessionId = activeSessionId) {
    try {
        const ownerSessionId = String(sessionId || activeSessionId || '');
        // Delayed task callbacks belong to the case that started the task. If
        // that case is no longer visible, persist the event there without
        // painting it into the newly selected case.
        if (fromSession !== true
            && ownerSessionId
            && ownerSessionId !== String(activeSessionId || '')) {
            if (typeof saveSessionMessage === 'function') {
                saveSessionMessage(type, String(content == null ? '' : content), null, timestamp || Date.now(), ownerSessionId);
            }
            return;
        }
        const container = document.getElementById('chatMessages');
        if (!container) return;
        const t = (type || 'system').toString();
        const c = (content == null ? '' : content).toString();
        // Accept legacy aliases: 'bot-response' → 'bot' for visual treatment,
        // 'thinking' → 'bot' (the thinking chain uses its own renderer).
        // CRITICAL (2026-06-15): if we don't remap 'bot-response' to 'bot',
        // the message falls through to 'system' which has
        // text-align: center / align-self: center — so on session restore,
        // old saved messages render CENTERED (the user's "layout broke and centered"
        // bug). The remap below fixes that.
        let safeType = ['user', 'bot', 'system', 'error'].includes(t) ? t : 'system';
        if (safeType === 'system' && (t === 'bot-response' || t === 'bot' || t === 'thinking')) {
            safeType = 'bot';
        }
        if (safeType === 'thinking') safeType = 'bot';

        if (safeType === 'user' || safeType === 'bot') {
            // Wrapped layout: .chat-row > [.chat-avatar, .chat-msg-wrapper > .chat-msg, .chat-timestamp]
            const row = document.createElement('div');
            row.className = 'chat-row ' + safeType;
            if (safeType === 'bot' && !fromSession && _hasBotMessageSinceLastUser(container)) {
                row.classList.add('bot-continuation');
            }

            const avatar = document.createElement('div');
            avatar.className = 'chat-avatar ' + (safeType === 'bot' ? 'bot-avatar' : 'user-avatar');
            avatar.innerHTML = CHAT_AVATAR_SVGS[safeType] || '';

            const wrapper = document.createElement('div');
            wrapper.className = 'chat-msg-wrapper ' + safeType;

            // Copy action (only for user / bot / bot-response messages)
            const actions = document.createElement('div');
            actions.className = 'chat-msg-actions';
            const copyBtn = document.createElement('button');
            copyBtn.className = 'chat-msg-action-btn';
            copyBtn.innerHTML = '&#128203;';
            copyBtn.title = 'Copy';
            copyBtn.onclick = () => {
                const fallbackCopy = (text) => {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;';
                    document.body.appendChild(ta); ta.focus(); ta.select();
                    try { document.execCommand('copy'); } catch (_) {}
                    document.body.removeChild(ta);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(c).then(() => {
                        copyBtn.innerHTML = '&#9989;';
                        setTimeout(() => { copyBtn.innerHTML = '&#128203;'; }, 1500);
                    }).catch(() => fallbackCopy(c));
                } else {
                    fallbackCopy(c);
                }
            };
            actions.appendChild(copyBtn);
            wrapper.appendChild(actions);

            // The message bubble
            const div = document.createElement('div');
            div.className = 'chat-msg ' + safeType;
            // Render markdown for bot responses (matches upstream), plain escape for user/system
            if (safeType === 'bot' && typeof renderMarkdown === 'function') {
                div.innerHTML = renderMarkdown(c);
            } else {
                div.innerHTML = c
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/\n/g, '<br>');
            }
            wrapper.appendChild(div);

            // Timestamp — prefer the saved timestamp (if this message
            // is being re-rendered from a session) so it shows the
            // time the message was originally sent, not the time of
            // the page refresh. Falls back to "now" for live messages.
            const ts = document.createElement('div');
            ts.className = 'chat-timestamp';
            try {
                const tsSrc = (typeof timestamp === 'number' && timestamp > 0)
                    ? new Date(timestamp)
                    : new Date();
                ts.textContent = tsSrc.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } catch (_) { ts.textContent = ''; }
            wrapper.appendChild(ts);

            row.appendChild(avatar);
            row.appendChild(wrapper);
            container.appendChild(row);
        } else {
            // System and error events use a compact left-aligned timeline row.
            // These are user-action/status records, not assistant messages, so
            // they should not look like repeated centered answer bubbles.
            const row = document.createElement('div');
            row.className = 'chat-event-row ' + safeType;
            const icon = document.createElement('span');
            icon.className = 'chat-event-icon';
            icon.textContent = safeType === 'error' ? '!' : 'i';
            const body = document.createElement('div');
            body.className = 'chat-event-content';
            const message = document.createElement('span');
            message.className = 'chat-event-text';
            message.textContent = c;
            const ts = document.createElement('time');
            ts.className = 'chat-event-timestamp';
            try {
                const tsSrc = (typeof timestamp === 'number' && timestamp > 0)
                    ? new Date(timestamp)
                    : new Date();
                ts.textContent = tsSrc.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            } catch (_) { ts.textContent = ''; }
            body.appendChild(message);
            body.appendChild(ts);
            row.appendChild(icon);
            row.appendChild(body);
            container.appendChild(row);
        }

        if (scroll !== false) {
            container.scrollTop = container.scrollHeight;
        }
        // Also persist into the active session so a refresh keeps it.
        // SKIP when re-rendering from a saved session (the message
        // is already in the session, saving it again causes the
        // page-refresh duplication bug the user reported on
        // 2026-06-16 — each refresh would re-persist the same
        // message and the array would grow by 2 with every reload).
        if (fromSession !== true && typeof saveSessionMessage === 'function') {
            try { saveSessionMessage(safeType, c, null, Date.now(), ownerSessionId); } catch (_) { /* sessions may not be ready yet */ }
        }
    } catch (e) {
        // Never let chat rendering break the caller (CT load, plan, etc.)
        console.warn('addChat failed:', e);
    }
}

function _hasBotMessageSinceLastUser(container) {
    if (!container) return false;
    for (let i = container.children.length - 1; i >= 0; i--) {
        const el = container.children[i];
        if (!el || !el.classList) continue;
        if (el.classList.contains('user')) return false;
        if (el.classList.contains('bot')) return true;
    }
    return false;
}

// ----- Thinking chain + streaming helpers (restored from upstream) -----
// These power the live "execution trace" UI: the bot shows a chain of
// step blocks (User Input, LLM Brain, Tool calls, etc.) that updates in
// real time as the SSE stream from /api/chat progresses, then auto-
// collapses once the response is complete.

const STEP_ICONS = {
    user:      '&#128100;',   // 👤 person
    thinking:  '&#129504;',   // 🧠 brain
    tool:      '&#9881;',     // ⚙ gear
    result:    '&#9989;',     // ✅ check
    error:     '&#10060;',    // ❌ cross
    assistant: '&#129302;',   // 🤖 robot
    memory:    '&#128218;',   // 📚 books
    review:    '&#128269;',   // 🔍 magnifier
};

// i18n for thinking chain labels — matches _TODO_I18N pattern.
// Used by appendStepToChain, createLiveThinkingChain, updateChainHeader.
const _CHAIN_I18N = {
    en: {
        header: 'Execution Trace',
        thinking: 'Thinking',
        steps_suffix: ' steps',
        llm_call: 'LLM Call',
        calling: 'Calling',
        user_input: 'User Input',
        response_synthesis: 'Response Synthesis',
        final_response: 'Final Response',
        pending: 'pending',
        done: 'done',
        error: 'error',
        stopped: 'stopped',
    },
    zh: {
        header: '执行追踪',
        thinking: '思考中',
        steps_suffix: ' 步',
        llm_call: 'LLM 调用',
        calling: '调用',
        user_input: '用户输入',
        pending: '等待中',
        done: '完成',
        error: '错误',
    },
};
function _chainI18n(key) {
    const lang = effectiveUiLanguage();
    return (_CHAIN_I18N[lang] || _CHAIN_I18N.en)[key] || (_CHAIN_I18N.en[key] || key);
}
// Localize a step title: "LLM Call 1" → "LLM 调用 1", "Calling foo" → "调用 foo"
function _localizeStepTitle(title) {
    if (!title) return '';
    const lang = effectiveUiLanguage();
    if (lang === 'en') return title;
    // "LLM Call N" → "LLM 调用 N"
    title = title.replace(/^LLM Call (\d+)/, _chainI18n('llm_call') + ' $1');
    // "Calling tool_name" → "调用 tool_name"
    title = title.replace(/^Calling /, _chainI18n('calling') + ' ');
    // "User Input" → "用户输入"
    title = title.replace(/^User Input$/, _chainI18n('user_input'));
    title = title.replace(/^Response Synthesis$/, _chainI18n('response_synthesis'));
    title = title.replace(/^Final Response$/, _chainI18n('final_response'));
    return title;
}
// Localize step status: "pending" → "等待中", "done" → "完成"
function _localizeStepStatus(status) {
    if (!status) return '';
    return _chainI18n(status) || status;
}

// Safe markdown renderer — uses the global `marked` (loaded from CDN) if
// available, with a plain-escape fallback otherwise.

// CONSISTENT ICON INJECTION (2026-06-16).
// The user wants icons back in chat output, but used judiciously:
// headings should always have a level-mapped icon (single source of
// truth, not whatever the LLM felt like writing), and inline content
// should get a soft semantic icon ONLY when the user has opted in via
// the `window._chatIconsEnabled` switch (default ON; set to false to
// disable all auto-icon injection in chat output).
//
// Where icons are appropriate:
//   1. Headings  — level → icon map (this is the only place icons
//                  are mandatory when enabled).
//   2. Soft / subjective lines    — sentences starting with "建议",
//                                    "小贴士", "经验上", "一般来说"
//                                    get a 💡 prefix.
//   3. Success lines              — "成功", "完成", "通过", "达标"
//                                    get a ✅ prefix.
//   4. Warning lines              — "警告", "注意", "风险", "不符合"
//                                    get a ⚠️ prefix.
//   5. Data source lines          — "数据来源", "source:", "from:"
//                                    get a 📊 prefix.
//   6. Time / duration mentions   — "约 90 秒", "耗时", "用了 ... 秒"
//                                    get a 🕐 prefix.
//
// Where icons are NOT injected (intentional restraint):
//   - Inside table cells (too dense, breaks scanning)
//   - Code blocks / inline code
//   - Strict medical / regulatory wording
//   - Numeric metrics inside a sentence (e.g. "V100 = 97.6%")
// Heading icons removed (2026-06-22) — clean text-only headings.
// const _HEADING_ICONS = { 1:'🎯', 2:'📌', 3:'🔹', 4:'🔸', 5:'🔻', 6:'🔻' };
// function _headingIcon(level) { return _HEADING_ICONS[level] || ''; }

// Strip any leading emoji characters from text (so the LLM's own
// leading emoji doesn't fight the level-mapped icon we inject).
const _LEADING_EMOJI_RE = /^[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{2700}-\u{27BF}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}️\s]+/u;
function _stripLeadingEmoji(s) {
    return String(s).replace(_LEADING_EMOJI_RE, '').trim();
}

// Pattern → icon map for soft / subjective / status lines. The
// regexes are deliberately simple Chinese-prefixed and English-prefixed
// variants so the icon matches the way the LLM naturally phrases things.
const _INLINE_ICON_RULES = [
    { re: /^(建议|小贴士|Tip|Advice|Recommendation|经验上|一般来说|通常情况下|Pro tip)/u, icon: '💡' },
    { re: /(成功|已完成|已经完成|规划完成|计算完成|执行完毕|\bDone\b|\bCompleted\b|\bFinished\b|\bSucceeded\b|\bPassed\b|达标|符合|满足要求)/u, icon: '✅' },
    { re: /^(注意|警告|⚠|风险|不符合|异常|失败|\bWarning\b|\bFailed\b|\bError\b|\bCaution\b|\bRisk\b)/u, icon: '⚠️' },
    { re: /^(数据来源|来源|source|from|根据|引用)/iu, icon: '📊' },
    { re: /(耗时|用了.*?秒|约\s*\d+\s*秒|耗时约|用了大约|duration|elapsed)/iu, icon: '🕐' },
];

// Run on a single block of text (paragraph, list item body, etc.).
// Returns the text with a single leading icon prepended IF a rule
// matches AND the text doesn't already start with an emoji. Idempotent.
function _injectInlineIcon(text) {
    if (!text) return text;
    if (window._chatIconsEnabled === false) return text;  // opt-out
    if (_LEADING_EMOJI_RE.test(text)) return text;        // LLM already gave one
    for (const rule of _INLINE_ICON_RULES) {
        if (rule.re.test(text)) {
            return rule.icon + ' ' + text;
        }
    }
    return text;
}

// Variant used by Renderer hooks — returns just the matched icon
// string (no leading space) so the caller can choose how to splice
// it into the surrounding HTML. Returns '' if no rule matches.
function _firstMatchingIcon(text) {
    if (!text || window._chatIconsEnabled === false) return '';
    if (_LEADING_EMOJI_RE.test(text)) return '';
    for (const rule of _INLINE_ICON_RULES) {
        if (rule.re.test(text)) return rule.icon;
    }
    return '';
}

function _sanitizeHtml(html) {
    if (!html) return '';
    if (typeof document === 'undefined') {
        return String(html)
            .replace(/<\s*(script|iframe|object|embed|form|style|link|meta|base|svg|math)\b[\s\S]*?>[\s\S]*?<\s*\/\s*\1\s*>/gi, '')
            .replace(/\s+on\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
            .replace(/\s(href|src|xlink:href)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, ' $1="#"');
    }

    const allowedTags = new Set([
        'A', 'P', 'BR', 'HR', 'STRONG', 'B', 'EM', 'I', 'U', 'S',
        'CODE', 'PRE', 'BLOCKQUOTE', 'UL', 'OL', 'LI',
        'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR', 'TH', 'TD',
        'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'SPAN', 'DIV', 'IMG',
    ]);
    const allowedAttrs = new Set(['href', 'src', 'alt', 'title', 'class', 'target', 'rel']);
    const allowedClass = /^(md-|chat-|hljs|language-|token|contains-task-list|task-list-item)/;
    const safeUrl = (value, allowDataImage = false) => {
        const raw = String(value || '').trim().replace(/[\u0000-\u001F\u007F\s]+/g, '');
        if (!raw) return false;
        if (/^(javascript|vbscript|file):/i.test(raw)) return false;
        if (/^data:/i.test(raw)) return allowDataImage && /^data:image\/(png|jpeg|jpg|webp|gif);base64,/i.test(raw);
        return /^(https?:|mailto:|\/|\.\/|\.\.\/|#|_assets\/)/i.test(raw);
    };

    const template = document.createElement('template');
    template.innerHTML = String(html);

    const walk = (node) => {
        for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === Node.COMMENT_NODE) {
                child.remove();
                continue;
            }
            if (child.nodeType !== Node.ELEMENT_NODE) {
                continue;
            }
            if (!allowedTags.has(child.tagName)) {
                child.replaceWith(document.createTextNode(child.textContent || ''));
                continue;
            }

            for (const attr of Array.from(child.attributes)) {
                const name = attr.name.toLowerCase();
                const value = attr.value || '';
                if (name.startsWith('on') || name === 'style' || name === 'srcdoc') {
                    child.removeAttribute(attr.name);
                    continue;
                }
                if (!allowedAttrs.has(name)) {
                    child.removeAttribute(attr.name);
                    continue;
                }
                if (name === 'href' && !safeUrl(value, false)) {
                    child.setAttribute('href', '#');
                    continue;
                }
                if (name === 'src' && !safeUrl(value, child.tagName === 'IMG')) {
                    child.removeAttribute('src');
                    continue;
                }
                if (name === 'class') {
                    const safeClasses = value.split(/\s+/).filter(c => allowedClass.test(c));
                    if (safeClasses.length) child.setAttribute('class', safeClasses.join(' '));
                    else child.removeAttribute('class');
                    continue;
                }
                if (name === 'target') child.setAttribute('target', '_blank');
                if (name === 'rel') child.setAttribute('rel', 'noopener noreferrer');
            }
            if (child.tagName === 'A') {
                child.setAttribute('target', '_blank');
                child.setAttribute('rel', 'noopener noreferrer');
            }
            walk(child);
        }
    };

    walk(template.content);
    return template.innerHTML;
}

function renderMarkdown(text) {
    if (!text) return '';
    try {
        if (typeof marked !== 'undefined' && marked && marked.parse) {
            // marked@4.x; we customize the renderer so the output
            // carries the .md-* class names the chat CSS expects
            // (otherwise the default marked output is bare <table>,
            // <h1>, <ul> etc and gets browser-default styling). The
            // customization is idempotent — if we've already wrapped
            // the renderer once, leave it alone.
            if (!renderMarkdown._renderer_installed) {
                const R = new marked.Renderer();
                const _table = R.table.bind(R);
                R.table = function(...args) {
                    const html = _table(...args);
                    return html.replace(/^<table>/, '<table class="md-table">');
                };
                const _h1 = R.heading.bind(R);
                R.heading = function(text, level, raw, slugger) {
                    // CLEAN HEADINGS (2026-06-22): strip any leading
                    // emoji the LLM may have added, but do NOT inject
                    // any icon. Clean text-only headings look more
                    // professional (ChatGPT style). Hierarchy is
                    // communicated through font size/weight/color.
                    const cleaned = String(text).replace(/^[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}\u{2700}-\u{27BF}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}]+\s*/u, '').trim();
                    const html = _h1(cleaned, level, raw, slugger);
                    return html.replace(/^<(h[1-6])(\s)/, '<$1 class="md-$1"$2').replace(/^<(h[1-6]) class="md-(h[1-6])"(\s)/, '<$1 class="md-$2"$3');
                };
                const _ul = R.list.bind(R);
                R.list = function(body, ordered) {
                    const cls = ordered ? 'md-ordered-list' : 'md-list';
                    const html = _ul(body, ordered);
                    return html.replace(/^<(ul|ol)>/, '<$1 class="' + cls + '">');
                };
                const _li = R.listitem.bind(R);
                R.listitem = function(text) {
                    // Inject a soft semantic icon (💡/✅/⚠️/📊/🕐) at
                    // the start of the list item IF the visible text
                    // matches an inline rule. We do it here on the
                    // inner HTML (which is already escaped) by finding
                    // the first <…> tag and prepending into it. For
                    // simple text-only items the inner is just text.
                    let processed = text;
                    if (window._chatIconsEnabled !== false) {
                        // Extract the visible text: strip tags.
                        const visible = text.replace(/<[^>]+>/g, '').trim();
                        const icon = _firstMatchingIcon(visible);
                        if (icon && !_LEADING_EMOJI_RE.test(visible)) {
                            // Prepend a <span class="md-li-icon"> right
                            // after the opening <li>.
                            processed = _li(icon + ' ' + text).replace(/^<li>/, '<li class="md-list-item">');
                        } else {
                            processed = _li(text).replace(/^<li>/, '<li class="md-list-item">');
                        }
                    } else {
                        processed = _li(text).replace(/^<li>/, '<li class="md-list-item">');
                    }
                    return processed;
                };
                const _p = R.paragraph.bind(R);
                R.paragraph = function(text) {
                    // Same inline-icon logic for paragraph blocks.
                    let processed = text;
                    if (window._chatIconsEnabled !== false) {
                        const visible = text.replace(/<[^>]+>/g, '').trim();
                        const icon = _firstMatchingIcon(visible);
                        if (icon && !_LEADING_EMOJI_RE.test(visible)) {
                            processed = '<p class="md-paragraph">' + icon + ' ' + text + '</p>';
                        } else {
                            processed = '<p class="md-paragraph">' + text + '</p>';
                        }
                    } else {
                        processed = '<p class="md-paragraph">' + text + '</p>';
                    }
                    return processed;
                };
                const _hr = R.hr.bind(R);
                R.hr = function() { return '<hr class="md-hr">'; };
                // Links open in new tab with security attrs
                const _link = R.link.bind(R);
                R.link = function(href, title, text) {
                    const html = _link(href, title, text);
                    return html.replace(/^<a /, '<a target="_blank" rel="noopener noreferrer" ');
                };
                marked.setOptions({ renderer: R, gfm: true, breaks: false });
                renderMarkdown._renderer_installed = true;
            }
            return _sanitizeHtml(marked.parse(text));
        }
    } catch (e) { console.warn('renderMarkdown:', e); /* fall through */ }
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

/* ====================================================================
   GLOBAL I18N SYSTEM (2026-06-16)
   --------------------------------------------------------------------
   The user requested a global EN/中 toggle placed in the top-right
   header (next to "Connected" / "Brain online"). This affects ALL UI
   labels — header, tab names, button text, status text, placeholders,
   tooltips, panel titles — but NOT LLM input/output language
   detection (which is server-side, based on the user's typed text and
   is intentionally independent of UI display language so a user with
   a Chinese UI can still ask the agent in English and vice versa).

   Architecture:
     - `window._I18N` is a flat key→{zh,en} dictionary, grouped by
       panel/section. New keys can be added inline at the call site
       via `_t(zh, en)` (auto-registers) without touching the dict.
     - `window._t(zh, en)` returns the right side for the current
       language AND lazily registers the pair into _I18N so a later
       `applyI18n()` can re-render dynamic content.
     - `applyI18n()` walks the DOM for elements with `data-i18n`
       attributes and replaces their text content. It also fires a
       `i18nchange` CustomEvent so dynamic renderers (Report panel,
       Analysis panel) can re-render their strings.

   Defaults:
     - First load: 'en' (English). The user explicitly asked for
       English to be the default; the Chinese option is for users who
       need a Chinese UI but still want the agent to reply in their
       input language.
     - Persisted to localStorage as 'brachybot_ui_lang'.
   ==================================================================== */
(function() {
    // Central dictionary. Group by section. Anything not in here will
    // fall through to the _t(zh, en) call's explicit pair.
    const I18N = {
        // Header / status
        'header.connected':           { zh: '已连接', en: 'Connected' },
        'header.connecting':          { zh: '连接中', en: 'Connecting' },
        'header.disconnected':        { zh: '已断开', en: 'Disconnected' },
        'header.brain_online':        { zh: '在线', en: 'Online' },
        'header.brain_offline':       { zh: '离线', en: 'Offline' },
        'header.brain_busy':          { zh: '工作中', en: 'Busy' },
        'header.session':             { zh: '会话', en: 'Session' },
        'header.lang_toggle_tooltip': { zh: '切换界面语言 / Switch UI language', en: 'Switch UI language' },
        // Tab bar
        'tab.input':                  { zh: '输入',   en: 'Input' },
        'tab.analysis':               { zh: '分析',   en: 'Analysis' },
        'tab.viewers':                { zh: '视图',   en: 'Viewers' },
        'tab.report':                 { zh: '报告',   en: 'Report' },
        // Sidebar
        'sidebar.chats':              { zh: '对话',   en: 'Chats' },
        'sidebar.new_chat':           { zh: '+ 新建', en: '+ New' },
        'sidebar.connect':            { zh: '连接服务器', en: 'Connect' },
        'sidebar.disconnect':         { zh: '断开',   en: 'Disconnect' },
        'sidebar.clear':              { zh: '清空',   en: 'Clear' },
        // Chat panel
        'chat.welcome':               { zh: '欢迎使用 BrachyBot。请描述你的近距离治疗病例——肿瘤位置、类型、患者情况——我会帮你生成最佳治疗计划。也可以直接在右侧的「输入」面板加载 CT 数据。', en: 'Welcome to BrachyBot. Describe your brachytherapy case — tumor location, type, patient condition — and I will help you generate an optimal treatment plan. You can also load CT data directly via the Input panel on the right.' },
        'chat.input_placeholder':     { zh: '描述你的病例或输入 / 查看命令...', en: 'Describe your case or type / for commands...' },
        'chat.send':                  { zh: '发送', en: 'Send' },
        'chat.stop':                  { zh: '停止', en: 'Stop' },
        'chat.copy':                  { zh: '复制', en: 'Copy' },
        'chat.thinking':              { zh: '正在思考...', en: 'Thinking…' },
        // Viewers panel
        'viewers.axial':              { zh: '轴状位', en: 'Axial' },
        'viewers.sagittal':           { zh: '矢状位', en: 'Sagittal' },
        'viewers.coronal':            { zh: '冠状位', en: 'Coronal' },
        'viewers.3d':                 { zh: '三维视图', en: '3D View' },
        'viewers.slice':              { zh: '切片',   en: 'Slice' },
        'viewers.window':             { zh: '窗位/窗宽', en: 'W/L' },
        'viewers.reset':              { zh: '重置',   en: 'Reset' },
        // Input panel
        'input.section_image':        { zh: '影像数据',   en: 'Image Data' },
        'input.section_ct':           { zh: 'CT 图像',   en: 'CT Image' },
        'input.section_ctv':          { zh: 'CTV 掩膜',   en: 'CTV Mask' },
        'input.section_oar':          { zh: 'OAR 掩膜',   en: 'OAR Mask' },
        'input.section_hyper':        { zh: '超参数',     en: 'Hyperparameters' },
        'input.section_pipeline':     { zh: '完整规划流程', en: 'Full Pipeline' },
        'input.section_results':      { zh: '规划结果',   en: 'View Results' },
        'input.section_export':       { zh: '导出',       en: 'Export' },
        'input.browse':               { zh: '浏览',   en: 'Browse' },
        'input.browse_ct':            { zh: '点击或拖入 CT (.nii / .nii.gz / DICOM)', en: 'Click or drop CT (.nii / .nii.gz / DICOM)' },
        'input.browse_ctv':           { zh: '点击或拖入 CTV 标签 (.nii.gz, optional)', en: 'Click or drop CTV label (.nii.gz, optional)' },
        'input.browse_oar':           { zh: '点击或拖入 OAR 标签 (.nii.gz, optional)', en: 'Click or drop OAR label (.nii.gz, optional)' },
        'input.start_plan':           { zh: '▶ 开始规划', en: '▶ Start Plan' },
        'input.stop':                 { zh: '■ 停止',   en: '■ Stop' },
        'input.reset':                { zh: '↺ 重置',   en: '↺ Reset' },
        'input.show_all':             { zh: '显示全部', en: 'Show All' },
        'input.traj':                 { zh: '轨迹',     en: 'Trajectories' },
        'input.refine':               { zh: '细化',     en: 'Refine' },
        'input.seeds':                { zh: '粒子',     en: 'Seeds' },
        'input.dose':                 { zh: '剂量',     en: 'Dose' },
        'input.eval':                 { zh: '评估',     en: 'Evaluate' },
        'input.dicom_rt':             { zh: 'DICOM-RT', en: 'DICOM-RT' },
        'input.stl':                  { zh: 'STL',      en: 'STL' },
        // Analysis panel
        'analysis.section_image':     { zh: '影像分析',   en: 'Image Analysis' },
        'analysis.geometry':          { zh: '📐 图像几何', en: '📐 Image Geometry' },
        'analysis.dicom_meta':        { zh: '🏥 DICOM 元数据', en: '🏥 DICOM Metadata' },
        'analysis.source':            { zh: '📁 数据来源', en: '📁 Source' },
        'analysis.seg_plan':          { zh: '🧬 分割 & 计划', en: '🧬 Segmentation & Plan' },
        'analysis.target':            { zh: '靶区覆盖率',   en: 'Target Coverage' },
        'analysis.dvh':               { zh: '剂量体积直方图', en: 'Dose-Volume Histogram' },
        'analysis.oar':               { zh: '危及器官剂量指标 (Gy)', en: 'OAR Dose Metrics (Gy)' },
        'analysis.metric':            { zh: '指标',     en: 'Metric' },
        'analysis.value':             { zh: '数值',     en: 'Value' },
        'analysis.target_voxels':     { zh: '体素 (X × Y × Z)', en: 'Voxels (X × Y × Z)' },
        'analysis.target_slices':     { zh: '总切片数', en: 'Total slices' },
        'analysis.target_spacing':    { zh: '像素间距 (mm)', en: 'Pixel spacing (mm)' },
        'analysis.target_volume':     { zh: '物理体积', en: 'Physical volume' },
        'analysis.hu_range':          { zh: 'HU 范围', en: 'HU range' },
        'analysis.hu_peak':           { zh: 'HU 峰值', en: 'HU peak (mode)' },
        'analysis.window_level':      { zh: '窗位 / 窗宽', en: 'Window / Level' },
        'analysis.source_label':      { zh: '数据来源', en: 'Source' },
        'analysis.nifti_vol':         { zh: 'NIfTI / 体积文件', en: 'NIfTI / volume file' },
        'analysis.dicom_file':        { zh: 'DICOM 单文件', en: 'DICOM single file' },
        'analysis.dicom_series':      { zh: 'DICOM 序列', en: 'DICOM series' },
        'analysis.ctv_labels':        { zh: 'CTV 标签数', en: 'CTV labels' },
        'analysis.ctv_vox_vol':       { zh: 'CTV 体素 / 体积', en: 'CTV voxels / volume' },
        'analysis.oar_labels':        { zh: 'OAR 标签数', en: 'OAR labels' },
        'analysis.oar_vox_vol':       { zh: 'OAR 总体素 / 体积', en: 'OAR total voxels / volume' },
        'analysis.d90':               { zh: 'D90 (CTV 覆盖)', en: 'D90 (CTV coverage)' },
        'analysis.v100':              { zh: 'V100 (CTV 覆盖)', en: 'V100 (CTV coverage)' },
        'analysis.v150':              { zh: 'V150', en: 'V150' },
        'analysis.d2':                { zh: 'D2 (最高剂量)', en: 'D2 (max dose)' },
        'analysis.dmean':             { zh: 'Dmean', en: 'Dmean' },
        'analysis.plan_score':        { zh: '计划评分', en: 'Plan score' },
        'analysis.seeds_traj':        { zh: '粒子数 / 路径数', en: 'Seeds / Trajectories' },
        // Todo list dock
        'todo.header':                { zh: '执行进度', en: 'Progress' },
        'todo.ctv':                   { zh: 'CTV 靶区分割',   en: 'CTV Segmentation' },
        'todo.oar':                   { zh: 'OAR 危及器官分割', en: 'OAR Segmentation' },
        'todo.planning':              { zh: '粒子植入规划 (5 步流水线)', en: 'Particle Implantation (5-step Pipeline)' },
        'todo.traj_init':             { zh: '轨迹初始化',     en: 'Trajectory Init' },
        'todo.traj_refine':           { zh: '轨迹细化',       en: 'Trajectory Refine' },
        'todo.seed_planning':         { zh: '种子位置优化',   en: 'Seed Placement' },
        'todo.dose_calc':             { zh: '剂量计算',       en: 'Dose Calculation' },
        'todo.dose_eval':             { zh: '剂量学评估',     en: 'Dose Evaluation' },
        'todo.response':              { zh: '生成最终回复',   en: 'Final Response' },
        // Report panel
        'report.title':               { zh: '📄 治疗计划报告', en: '📄 Treatment Plan Report' },
        'report.how_to_use':          { zh: '使用流程 / How to use', en: 'How to use' },
        'report.autofill':            { zh: '✨ 自动填充', en: '✨ Auto-fill' },
        'report.template':            { zh: '— 模板 —', en: '— Template —' },
        'report.lang_zh':             { zh: '中文', en: '中文' },
        'report.lang_en':             { zh: 'EN',   en: 'EN' },
        'report.pdf':                 { zh: '🖨️ PDF', en: '🖨️ PDF' },
        'report.snapshot':            { zh: '📸 快照', en: '📸 Snapshot' },
        'report.history':             { zh: '📜 历史', en: '📜 History' },
        'report.audit':               { zh: '🔍 审计', en: '🔍 Audit' },
        'report.validate':            { zh: '✅ 校验', en: '✅ Validate' },
        'report.two_col':             { zh: '2 列',   en: '2-col' },
        'report.reset':               { zh: '↺ 重置', en: '↺ Reset' },
        // Common
        'common.loading':             { zh: '加载中…',     en: 'Loading…' },
        'common.ready':               { zh: '就绪',       en: 'Ready' },
        'common.error':               { zh: '错误',       en: 'Error' },
        'common.cancel':              { zh: '取消',       en: 'Cancel' },
        'common.confirm':             { zh: '确认',       en: 'Confirm' },
        'common.save':                { zh: '保存',       en: 'Save' },
        'common.close':               { zh: '关闭',       en: 'Close' },
        'common.yes':                 { zh: '是',         en: 'Yes' },
        'common.no':                  { zh: '否',         en: 'No' },
    };

    // Active language: 'en' (default) or 'zh'. Persisted to localStorage
    // so the user's choice survives a page refresh. We DO NOT couple
    // this to the server's LLM language detection — those are two
    // independent things.
    function getInitialLang() {
        try {
            const stored = localStorage.getItem('brachybot_ui_lang');
            if (stored === 'zh' || stored === 'en') return stored;
        } catch (_) {}
        return 'en';  // user explicitly asked for English default
    }
    window._i18nLang = getInitialLang();
    window._I18N = I18N;
    // Sync the todo list's active language to the global UI lang
    // at boot. The todo `_TODO_I18N` dict is defined later in the
    // file (line ~6965). Defer with requestAnimationFrame so we
    // run AFTER the file's bottom-of-file IIFE/const definitions
    // have completed. Re-attempt every frame until _TODO_I18N is
    // available, with a safety cap of 200 frames (~3s).
    (function _syncTodoLangAtBoot() {
        let frames = 0;
        const trySync = () => {
            frames++;
            try {
                if (typeof _setActiveTodoLang === 'function' && typeof _TODO_I18N !== 'undefined') {
                    _setActiveTodoLang(window._i18nLang);
                    return true;
                }
            } catch (_) {}
            return false;
        };
        if (!trySync()) {
            const tick = () => {
                if (trySync() || frames > 200) return;
                requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        }
    })();

    // Lazy-register a (zh, en) pair so applyI18n() can re-render
    // dynamic content later. The key is auto-generated from a hash
    // of the pair so identical pairs collapse.
    let _autoKeyCounter = 0;
    function _autoKey(zh, en) {
        return 'auto_' + (zh + '||' + en).split('').reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0).toString(36) + '_' + (_autoKeyCounter++);
    }
    function _registerPair(zh, en) {
        // Find an existing key with the same pair to keep call sites
        // stable.
        for (const k in I18N) {
            if (I18N[k].zh === zh && I18N[k].en === en) return k;
        }
        const k = _autoKey(zh, en);
        I18N[k] = { zh, en };
        return k;
    }

    // The translation function. Always returns a string, never throws.
    // Use this everywhere we have a hardcoded zh/en pair.
    window._t = function(zh, en) {
        const lang = window._i18nLang;
        const k = _registerPair(zh, en);
        return lang === 'zh' ? zh : en;
    };

    // Apply the current language to the DOM. Walks every element
    // with [data-i18n] and replaces its text. Also walks every
    // [data-i18n-placeholder] / [data-i18n-title] / [data-i18n-aria-label]
    // for the corresponding HTML attributes. Then fires a custom
    // event so dynamic renderers can re-render.
    function applyI18n() {
        const lang = window._i18nLang;
        const lookup = (zh, en) => lang === 'zh' ? zh : en;
        // text content — match elements that have BOTH attributes
        // (so the same querySelector that finds them also has the
        // strings it needs to swap in).
        document.querySelectorAll('[data-i18n-zh][data-i18n-en]').forEach(el => {
            const zh = el.getAttribute('data-i18n-zh');
            const en = el.getAttribute('data-i18n-en');
            el.textContent = lookup(zh, en);
        });
        // attributes: placeholder, title, aria-label
        ['placeholder', 'title', 'aria-label'].forEach(attr => {
            const sel = '[data-i18n-' + attr + '-zh][data-i18n-' + attr + '-en]';
            document.querySelectorAll(sel).forEach(el => {
                const zh = el.getAttribute('data-i18n-' + attr + '-zh');
                const en = el.getAttribute('data-i18n-' + attr + '-en');
                el.setAttribute(attr, lookup(zh, en));
            });
        });
        // Fire a custom event so dynamic renderers (Report form,
        // Analysis panel, todo dock) can re-render with the new
        // language. The detail object carries the new lang code.
        try {
            window.dispatchEvent(new CustomEvent('i18nchange', { detail: { lang } }));
        } catch (_) {}
    }
    window.applyI18n = applyI18n;

    // Set the active language and re-apply. Persists to localStorage.
    window.setUiLanguage = function(lang) {
        if (lang !== 'zh' && lang !== 'en') return;
        window._i18nLang = lang;
        try { localStorage.setItem('brachybot_ui_lang', lang); } catch (_) {}
        applyI18n();
        // Update the toggle button label/active state.
        const btns = document.querySelectorAll('[data-lang-btn]');
        btns.forEach(b => {
            const isActive = b.getAttribute('data-lang-btn') === lang;
            b.classList.toggle('lang-active', isActive);
            b.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
        // BUG FIX 2026-06-16 (todo list i18n): the user reported that
        // todo list labels (e.g. "执行进度" / "Progress") did NOT
        // switch when the global EN/中 toggle was flipped. Previously
        // todo lang was driven by server-side user-input language
        // detection only. Now the global toggle wins — if the user
        // explicitly switched UI lang, override whatever the SSE
        // start event set.
        try {
            if (typeof _setActiveTodoLang === 'function') {
                _setActiveTodoLang(lang);
            }
        } catch (_) {}
        // BUG FIX 2026-06-16 (report bilingual + global i18n): when
        // the global UI language flips, the Report panel must follow.
        // Previously the Report kept its own per-panel language and
        // was NOT synced with the global toggle, so the user saw a
        // Chinese report preview with an English UI. We:
        //   1. Update window.reportForm.language
        //   2. Re-interpret the report (so AI-generated text switches
        //      language, but only if the user hasn't edited it)
        //   3. Re-capture screenshots so figure captions match
        //   4. Re-render the editor + preview
        try {
            if (window.reportForm && window.reportForm.language !== lang) {
                window.reportForm.language = lang;
                if (!window.reportForm.editedFields.has('interpretation')
                        && typeof _autoFillInterpretation === 'function') {
                    try { _autoFillInterpretation(); } catch (_) {}
                }
                // Clear existing auto-captured figures so the next
                // panel open re-captures with the new language's
                // captions. User-uploaded figures are kept.
                if (Array.isArray(window.reportForm.figures)) {
                    window.reportForm.figures = window.reportForm.figures.filter(
                        f => f && f.type === 'upload'
                    );
                }
                if (typeof renderReportEditor === 'function') renderReportEditor();
                if (typeof _updateReportPreview === 'function') _updateReportPreview();
                if (typeof _scheduleReportAutoSave === 'function') _scheduleReportAutoSave();
            }
        } catch (_) { /* best-effort */ }
    };
})();

function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    if (container) container.scrollTop = container.scrollHeight;
}

function setStreamingState(streaming) {
    const btn = document.getElementById('chatSendBtn');
    if (!btn) return;
    if (streaming) {
        btn.classList.add('streaming');
        btn.innerHTML = '&#9632;';   // stop glyph
        btn.title = 'Stop streaming';
    } else {
        btn.classList.remove('streaming');
        btn.innerHTML = '&#10148;';  // send glyph
        btn.title = 'Send';
    }
}

// Stop any progress surfaces that may have outlived the local sendChat
// closure. This is a defensive UI boundary for browser races: an aborted
// fetch can reject before the closure receives the final SSE event, while a
// timer stored on a DOM node would otherwise keep updating the screen.
function cancelVisibleChatProgress(reason) {
    const message = reason || 'Stopped';
    try {
        if (window._activeTodoApi && typeof window._activeTodoApi.cancel === 'function') {
            window._activeTodoApi.cancel(message);
        }
    } catch (_) {}
    try {
        document.querySelectorAll('#thinkingRow').forEach(row => {
            removeThinkingIndicator(row);
        });
    } catch (_) {}
    try {
        document.querySelectorAll('#liveThinkingChain').forEach(chain => {
            const header = chain.querySelector('.thinking-header');
            cancelThinkingChain(chain, header);
        });
    } catch (_) {}
    try {
        if (window._toolProgressEls && window._toolProgressEls.length) {
            window._toolProgressEls.forEach(el => {
                try { el.remove(); } catch (_) { try { el.style.display = 'none'; } catch (_) {} }
            });
            window._toolProgressEls = [];
        }
    } catch (_) {}
}

window.cancelVisibleChatProgress = cancelVisibleChatProgress;

function toggleThinkingChain(wrapper, _steps) {
    const toggle = wrapper.querySelector('.thinking-toggle');
    const stepsDiv = wrapper.querySelector('.thinking-steps');
    const timeEl = wrapper.querySelector('.thinking-time');
    if (!toggle || !stepsDiv) return;
    const isExpanded = toggle.classList.contains('expanded');
    toggle.classList.toggle('expanded');
    stepsDiv.classList.toggle('expanded');
    if (timeEl) timeEl.style.display = isExpanded ? 'none' : '';
    // Expand/collapse all step bodies too
    stepsDiv.querySelectorAll('.step-body').forEach(b => {
        b.classList.toggle('expanded', !isExpanded);
    });
}

function toggleStep(bodyId) {
    const body = document.getElementById(bodyId);
    if (body) body.classList.toggle('expanded');
}

// Static renderer used by loadSessionChat() to redraw a saved chain.
function renderThinkingChain(steps) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    const totalSteps = steps ? steps.length : 0;
    const doneSteps = steps ? steps.filter(s => s.status === 'done').length : 0;

    const row = document.createElement('div');
    row.className = 'chat-row bot';

    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar bot-avatar';
    avatar.innerHTML = CHAT_AVATAR_SVGS.bot;

    const wrapper = document.createElement('div');
    wrapper.className = 'thinking-chain';

    const header = document.createElement('div');
    header.className = 'thinking-header';
    header.onclick = () => toggleThinkingChain(wrapper, steps);
    header.innerHTML = `
        <span class="thinking-toggle" id="tt_${Date.now()}">&#9654;</span>
        <span class="thinking-label">${escHtml(_chainI18n('header'))}</span>
        <span class="thinking-count">${doneSteps}/${totalSteps}${escHtml(_chainI18n('steps_suffix'))}</span>
    `;
    wrapper.appendChild(header);

    const stepsDiv = document.createElement('div');
    stepsDiv.className = 'thinking-steps';

    if (steps && steps.length > 0) {
        // DEDUP: remove duplicate steps by (type + tool) key, keeping
        // the LAST occurrence (most recent status wins).
        const _seenSteps = new Map();
        const _uniqueSteps = [];
        for (const s of steps) {
            const key = (s.type || '') + '|' + (s.tool || '') + '|' + (s.parent_tool || '');
            if (_seenSteps.has(key)) {
                // Replace previous with this one (latest status wins)
                const prevIdx = _seenSteps.get(key);
                _uniqueSteps[prevIdx] = s;
            } else {
                _seenSteps.set(key, _uniqueSteps.length);
                _uniqueSteps.push(s);
            }
        }
        _uniqueSteps.forEach((step, idx) => {
            const block = document.createElement('div');
            block.className = 'step-block';
            block.id = 'step_' + idx;
            const icon = STEP_ICONS[step.type] || '&#9679;';
            const toolName = step.tool ? '<div class="step-tool-name">' + escHtml(step.tool) + '</div>' : '';
            const params = step.params ? '<div class="step-params">' + Object.entries(step.params).map(([k, v]) => escHtml(k) + ': ' + escHtml(JSON.stringify(v))).join(', ') + '</div>' : '';
            const resultHtml = step.result ? '<div class="step-result">&#8594; ' + escHtml(step.result) + '</div>' : '';
            const contentHtml = step.content ? '<div class="step-content">' + escHtml(step.content) + '</div>' : '';
            block.innerHTML =
                '<div class="step-header" onclick="toggleStep(\'step_body_' + idx + '\')">' +
                    '<span class="step-icon ' + escHtml(step.type || '') + '">' + icon + '</span>' +
                    '<span class="step-title">' + escHtml(_localizeStepTitle(step.title || '')) + '</span>' +
                    '<span class="step-status ' + escHtml(step.status || '') + '">' + escHtml(_localizeStepStatus(step.status || '')) + '</span>' +
                '</div>' +
                '<div class="step-body" id="step_body_' + idx + '">' +
                    toolName + params + contentHtml + resultHtml +
                '</div>';
            stepsDiv.appendChild(block);
        });
    } else {
        stepsDiv.innerHTML = '<div style="color:var(--text-dim);font-size:0.72rem;padding:0.25rem 0.5rem;">No execution steps</div>';
    }

    wrapper.appendChild(stepsDiv);
    row.appendChild(avatar);
    row.appendChild(wrapper);
    container.appendChild(row);
    scrollToBottom();
}

function createLiveThinkingChain(resumeStartTime) {
    const container = document.getElementById('chatMessages');
    if (!container) return { chainEl: null, stepsDiv: null, headerEl: null };

    // Remove any previous live thinking chain before building a new one.
    // A detached task (session switch mid-planning) leaves a live chain
    // in the DOM.  Resume creates a second one, causing the duplicate
    // "Execution Trace" / Progress dock the user reported.
    const oldChain = document.getElementById('liveThinkingChain');
    if (oldChain) {
        try {
            const oldHeader = oldChain.querySelector('.thinking-header');
            if (oldHeader && oldHeader._timer) {
                clearInterval(oldHeader._timer);
                oldHeader._timer = null;
            }
        } catch (_) {}
        oldChain.remove();
    }

    const row = document.createElement('div');
    row.className = 'chat-row bot';

    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar bot-avatar';
    avatar.innerHTML = CHAT_AVATAR_SVGS.bot;

    const wrapper = document.createElement('div');
    wrapper.className = 'thinking-chain';
    wrapper.id = 'liveThinkingChain';

    const startTime = Number(resumeStartTime) || Date.now();

    const header = document.createElement('div');
    header.className = 'thinking-header';
    // The elapsed-time indicator (`.thinking-time`) shows the
    // wall-clock seconds since the chain was created. It updates
    // live (timer below) so the user can see how long the LLM
    // is taking. The final value is also captured in the
    // usage-bar footer at the end of the response.
    header.innerHTML =
        '<span class="thinking-toggle expanded">&#9654;</span>' +
        '<span class="thinking-label">' + escHtml(_chainI18n('thinking')) + '</span>' +
        '<span class="thinking-count">0' + escHtml(_chainI18n('steps_suffix')) + '</span>' +
        '<span class="thinking-time" style="margin-left:auto;font-size:0.62rem;color:var(--text-dim);font-variant-numeric:tabular-nums;">0.0s</span>';
    header.onclick = () => toggleThinkingChain(wrapper, []);
    wrapper.appendChild(header);

    // Live timer — updates the `.thinking-time` span every 100ms.
    // We keep the timer reference on the header so finalizeThinkingChain
    // can clearInterval it when the chain collapses.
    const timer = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        const timeEl = header.querySelector('.thinking-time');
        if (timeEl) timeEl.textContent = elapsed + 's';
    }, 100);
    header._timer = timer;

    const stepsDiv = document.createElement('div');
    stepsDiv.className = 'thinking-steps expanded';
    wrapper.appendChild(stepsDiv);

    row.appendChild(avatar);
    row.appendChild(wrapper);
    container.appendChild(row);

    return { chainEl: wrapper, stepsDiv, headerEl: header };
}

function appendStepToChain(stepsDiv, step, idx) {
    if (!stepsDiv) return;
    // BUG FIX 2026-06-16 (LLM Call pending hang): the user's trace
    // showed rows like "oar_segmentation — pending done" appearing
    // TWICE and "LLM Call N" rows lingering in 'pending' even after
    // the response finalized. Two root causes:
    //   (a) The server sometimes emits the SAME step under different
    //       ids when the tool loops back (e.g. CTV's auto-OAR inside
    //       ctv_segmentation creates a separate pending event whose
    //       id was incremented independently from the planning
    //       pipeline's later oar_segmentation run). The frontend's
    //       dedup-by-id misses these.
    //   (b) When the SSE pump re-emits a step with the SAME id, the
    //       existing block is updated in place — but if the status
    //       goes from pending -> done on a step that previously
    //       already showed done, the .step-status class doesn't
    //       refresh. So even though the data updated, the user sees
    //       the stale 'pending' pill.
    // Fix: do a TWO-PASS dedup. First by step.id; if no match, also
    // check (type + tool + parent_tool) so cross-id duplicates are
    // caught. Then ALWAYS re-render the .step-status class on update
    // so stale "pending" classes get cleared.
    let existingBlock = stepsDiv.querySelector('[data-step-id="' + step.id + '"]');
    if (!existingBlock && step.tool) {
        // Fallback dedup: match a block with the same (type, tool,
        // parent_tool) regardless of id. This catches the case
        // where the server emits the same logical step under
        // different ids (e.g. CTV's auto-OAR inside ctv_segmentation
        // emits pending with id=N, planning_pipeline re-emits the
        // same oar_segmentation with id=M).
        //
        // Match priority:
        //   1. Any 'pending' block for the same (type, tool, parent)
        //      — promote it to the new status (most common case).
        //   2. If new step is 'pending' AND existing is also 'pending'
        //      — drop the new one (duplicate re-emission).
        //   3. If new step is 'done' AND existing is 'done' (no
        //      pending anywhere) — update the FIRST occurrence.
        const blocks = Array.from(stepsDiv.querySelectorAll('.step-block'));
        let sameToolDoneBlock = null;
        let sameToolAnyBlock = null;
        for (const b of blocks) {
            const bTool = b.dataset.stepTool || '';
            const bParent = b.dataset.stepParent || '';
            const bType = b.dataset.stepType || '';
            const bStatus = b.querySelector('.step-status')?.textContent || '';
            // PASS 1: exact match (type + tool + parent)
            if (bType === step.type && bTool === step.tool && bParent === (step.parent_tool || '')) {
                if (bStatus === 'pending') {
                    step.id = b.dataset.stepId;
                    existingBlock = b;
                    break;
                }
                if (step.status === 'pending' && !existingBlock) {
                    step.id = b.dataset.stepId;
                    existingBlock = b;
                }
                if (!sameToolDoneBlock) sameToolDoneBlock = b;
            }
            // PASS 2: tool-name-only match (catch auto-fired vs explicit
            // duplicates where parent differs, e.g. oar_segmentation
            // auto-fired inside ctv_segmentation vs LLM explicit call)
            if (bType === step.type && bTool === step.tool && !sameToolAnyBlock) {
                sameToolAnyBlock = b;
            }
        }
        // If still no match, reuse a same-tool block (ignore parent)
        if (!existingBlock && sameToolAnyBlock) {
            step.id = sameToolAnyBlock.dataset.stepId;
            existingBlock = sameToolAnyBlock;
        } else if (!existingBlock && sameToolDoneBlock && step.status === 'done') {
            step.id = sameToolDoneBlock.dataset.stepId;
            existingBlock = sameToolDoneBlock;
        }
    }
    const icon = STEP_ICONS[step.type] || '&#9679;';
    const toolName = step.tool ? '<div class="step-tool-name">' + escHtml(step.tool) + '</div>' : '';
    const params = step.params ? '<div class="step-params">' + Object.entries(step.params).map(([k, v]) => escHtml(k) + ': ' + escHtml(JSON.stringify(v))).join(', ') + '</div>' : '';
    const resultHtml = step.result ? '<div class="step-result">&#8594; ' + escHtml(step.result) + '</div>' : '';
    const contentHtml = step.content ? '<div class="step-content">' + escHtml(step.content) + '</div>' : '';

    // Don't add .expanded to new steps if the chain is already
    // finalized — the user has the final response and shouldn't
    // see the chain re-expand with late-arriving steps.
    const chainFinalized = stepsDiv.closest('[data-finalized]');
    const bodyExpanded = chainFinalized ? '' : ' expanded';
    const bodyHtml =
        '<div class="step-header" onclick="toggleStep(\'step_body_' + idx + '\')">' +
            '<span class="step-icon ' + escHtml(step.type || '') + '">' + icon + '</span>' +
            '<span class="step-title">' + escHtml(_localizeStepTitle(step.title || '')) + '</span>' +
            '<span class="step-status ' + escHtml(step.status || '') + '">' + escHtml(_localizeStepStatus(step.status || '')) + '</span>' +
        '</div>' +
        '<div class="step-body' + bodyExpanded + '" id="step_body_' + idx + '">' +
            toolName + params + contentHtml + resultHtml +
        '</div>';

    if (existingBlock) {
        existingBlock.innerHTML = bodyHtml;
        // Re-stamp the dedup attributes so subsequent fallback dedup
        // can still find this block by (type, tool, parent_tool).
        existingBlock.dataset.stepId = step.id;
        existingBlock.dataset.stepTool = step.tool || '';
        existingBlock.dataset.stepParent = step.parent_tool || '';
        existingBlock.dataset.stepType = step.type || '';
        try { existingBlock.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (_) {}
        return;
    }

    const block = document.createElement('div');
    block.className = 'step-block';
    block.id = 'step_' + idx;
    block.dataset.stepId = step.id;
    block.dataset.stepTool = step.tool || '';
    block.dataset.stepParent = step.parent_tool || '';
    block.dataset.stepType = step.type || '';
    block.innerHTML = bodyHtml;
    stepsDiv.appendChild(block);
}

function updateChainHeader(headerEl, steps) {
    if (!headerEl) return;
    const countEl = headerEl.querySelector('.thinking-count');
    // The backend emits several SSE events for one logical step (pending,
    // heartbeat/progress, then done). The trace renderer already deduplicates
    // those events, but the old counter used the raw event array and showed
    // inflated values such as 18/115. Count the same logical latest states
    // that the trace displays.
    const unique = new Map();
    (Array.isArray(steps) ? steps : []).forEach((step, index) => {
        if (!step) return;
        const key = step.id != null
            ? `id:${step.id}`
            : `fallback:${step.type || ''}:${step.tool || ''}:${step.parent_tool || ''}:${step.title || index}`;
        unique.set(key, step);
    });
    const logicalSteps = Array.from(unique.values());
    const doneSteps = logicalSteps.filter(s => s.status === 'done').length;
    if (countEl) countEl.textContent = doneSteps + '/' + logicalSteps.length + _chainI18n('steps_suffix');
}

function finalizeThinkingChain(chainEl, headerEl, steps) {
    if (!chainEl) return;
    // Mark as finalized so late SSE events (text_chunk, step) cannot
    // re-expand the chain. Without this flag, the text_chunk handler
    // adds .expanded back and the user sees the tool history covering
    // the final response.
    chainEl.dataset.finalized = '1';
    chainEl.removeAttribute('id');
    const labelEl = headerEl && headerEl.querySelector('.thinking-label');
    if (labelEl) labelEl.textContent = _chainI18n('header');
    updateChainHeader(headerEl, steps);
    if (headerEl && headerEl._timer) {
        clearInterval(headerEl._timer);
        headerEl._timer = null;
    }
    // Auto-collapse: hide the steps panel AND the time elapser so the
    // user sees a single collapsed header (▶ Execution Trace 11/17 steps)
    // immediately. Without this, the chain stays expanded and the
    // intermediate tool calls cover the final AI response.
    // Do the collapse in BOTH a setTimeout (the original 500ms path) AND
    // synchronously (in case the setTimeout is delayed by an event-loop
    // back-pressure from the SSE pump).
    const _collapse = () => {
        const toggle = chainEl.querySelector('.thinking-toggle');
        const stepsDiv = chainEl.querySelector('.thinking-steps');
        const timeEl = chainEl.querySelector('.thinking-time');
        if (toggle) toggle.classList.remove('expanded');
        if (stepsDiv) {
            stepsDiv.classList.remove('expanded');
            // Also collapse every individual step body so even if the
            // outer container's display is overridden, each step's body
            // (params, tool name, result) is hidden.
            stepsDiv.querySelectorAll('.step-body').forEach(b => b.classList.remove('expanded'));
        }
        if (timeEl) timeEl.style.display = 'none';
    };
    // Synchronous first (immediate visual feedback)
    try { _collapse(); } catch (_) {}
    // Then again after a delay (covers cases where late SSE events re-added
    // the .expanded class after the sync call).
    setTimeout(_collapse, 300);
    setTimeout(_collapse, 800);
}

function cancelThinkingChain(chainEl, headerEl) {
    if (!chainEl) return;
    chainEl.dataset.finalized = '1';
    chainEl.dataset.cancelled = '1';
    if (headerEl && headerEl._timer) {
        clearInterval(headerEl._timer);
        headerEl._timer = null;
    }
    const labelEl = headerEl && headerEl.querySelector('.thinking-label');
    const countEl = headerEl && headerEl.querySelector('.thinking-count');
    if (labelEl) labelEl.textContent = _chainI18n('header');
    if (countEl) countEl.textContent = _chainI18n('stopped');
    // Pending step pills and their parent glow are the remaining animated
    // parts of the trace. Turn them into terminal error states before
    // collapsing the trace so expanding it later cannot restart motion.
    const stoppedText = _chainI18n('stopped');
    chainEl.querySelectorAll('.step-status.pending').forEach(status => {
        status.classList.remove('pending');
        status.classList.add('error');
        status.textContent = stoppedText;
    });
    const toggle = chainEl.querySelector('.thinking-toggle');
    const stepsDiv = chainEl.querySelector('.thinking-steps');
    const timeEl = chainEl.querySelector('.thinking-time');
    if (toggle) toggle.classList.remove('expanded');
    if (stepsDiv) {
        stepsDiv.classList.remove('expanded');
        stepsDiv.querySelectorAll('.step-body').forEach(body => body.classList.remove('expanded'));
    }
    if (timeEl) timeEl.style.display = 'none';
}

function createStreamingResponse() {
    const container = document.getElementById('chatMessages');
    const row = document.createElement('div');
    row.className = 'chat-row bot';
    if (_hasBotMessageSinceLastUser(container)) {
        row.classList.add('bot-continuation');
    }

    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar bot-avatar';
    avatar.innerHTML = CHAT_AVATAR_SVGS.bot;

    const wrapper = document.createElement('div');
    wrapper.className = 'chat-msg-wrapper bot';

    const div = document.createElement('div');
    div.className = 'chat-msg bot-response';
    div.id = 'streamingResponse';
    div.style.userSelect = 'text';
    div.style.webkitUserSelect = 'text';
    div.style.mozUserSelect = 'text';
    div.style.msUserSelect = 'text';

    wrapper.appendChild(div);
    row.appendChild(avatar);
    row.appendChild(wrapper);
    container.appendChild(row);
    return div;
}

function updateStreamingResponse(el, text) {
    if (!el) return;
    // Render markdown during streaming so bold/italic/lists display
    // correctly (not as raw **asterisks**).
    try { el.innerHTML = renderMarkdown(text); } catch (_) {
        el.innerHTML = escHtml(text).replace(/\n/g, '<br>');
    }
}

function finalizeStreamingResponse(el, text, sessionId = activeSessionId) {
    if (!el) return;
    el.removeAttribute('id');
    el.classList.remove('is-streaming');
    el.removeAttribute('aria-busy');
    el.innerHTML = renderMarkdown(text);
    try {
        const ownerSessionId = String(sessionId || '');
        saveSessionMessage('bot-response', text, null, Date.now(), ownerSessionId);
        // A final assistant response is a durable case event, not merely a
        // browser rendering update. Flush this boundary explicitly so closing
        // the tab immediately after a long planning turn cannot lose the
        // completed reply while the normal 700 ms workspace debounce is still
        // pending. The server-side ChatTask finalizer remains the authoritative
        // fallback when the browser stream is disconnected.
        if (ownerSessionId === String(activeSessionId || '')
            && window.__serverWorkspaceReady
            && typeof window.persistWorkspace === 'function') {
            void window.persistWorkspace('chat.response.finalized');
        }
    } catch (_) {}
}

function showThinkingIndicator() {
    const container = document.getElementById('chatMessages');
    const row = document.createElement('div');
    row.className = 'chat-row bot';
    row.id = 'thinkingRow';

    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar bot-avatar';
    avatar.innerHTML = CHAT_AVATAR_SVGS.bot;

    const wrapper = document.createElement('div');
    wrapper.className = 'thinking-indicator';
    wrapper.id = 'thinkingIndicator';

    const startTime = Date.now();
    const dots = document.createElement('div');
    dots.className = 'thinking-dots';
    dots.innerHTML = '<div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div>';

    const text = document.createElement('div');
    text.className = 'thinking-text';
    text.textContent = window._t ? window._t('正在思考', 'Thinking') : 'Thinking';

    const timeEl = document.createElement('div');
    timeEl.className = 'thinking-time';
    timeEl.textContent = '0.0s';

    wrapper.appendChild(dots);
    wrapper.appendChild(text);
    wrapper.appendChild(timeEl);

    row.appendChild(avatar);
    row.appendChild(wrapper);
    container.appendChild(row);
    scrollToBottom();

    const timer = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        timeEl.textContent = elapsed + 's';
    }, 100);
    wrapper._timer = timer;
    return row;
}

function removeThinkingIndicator(el) {
    if (el && el.parentNode) {
        const indicator = el.querySelector('#thinkingIndicator');
        if (indicator && indicator._timer) clearInterval(indicator._timer);
        el.remove();
    }
}

function showToolProgress(toolName, params) {
    // Tool lifecycle is rendered by the execution trace and todo list. A
    // second floating row duplicates every long-running tool and can leave
    // stale spinners behind, so this compatibility hook intentionally has no
    // visual side effect.
    return null;
}
/* Legacy floating tool-progress row removed; the execution trace and todo
   list are the single progress surface for a turn. */
/*
     text.className = 'tool-progress-text';
    const _zh = (effectiveUiLanguage() === 'zh');
    // Use i18n tool name if available
    const _toolLabel = (function() {
        try {
            const i18n = _todoI18n();
            return (i18n && i18n.tools && i18n.tools[toolName]) || toolName;
        } catch (_) { return toolName; }
    })();
    text.innerHTML = '<strong>' + escHtml(_toolLabel) + '</strong> ' + (_zh ? '执行中...' : 'running...');

    div.appendChild(spinner);
    div.appendChild(text);
    wrapper.appendChild(div);
    row.appendChild(avatar);
    row.appendChild(wrapper);
    container.appendChild(row);
    scrollToBottom();
    // Track for cleanup at end of turn
    window._toolProgressEls.push(row);
    return div;
}
*/

function updateToolProgress(el, toolName, status, result) {
    if (!el) return;
    const textEl = el.querySelector('.tool-progress-text');
    const spinner = el.querySelector('.spinner-ring');
    const _zh = (effectiveUiLanguage() === 'zh');
    const _toolLabel = (function() {
        try {
            const i18n = _todoI18n();
            return (i18n && i18n.tools && i18n.tools[toolName]) || toolName;
        } catch (_) { return toolName; }
    })();
    if (status === 'done') {
        if (spinner) spinner.remove();
        if (textEl) {
            textEl.innerHTML = '<strong>' + escHtml(_toolLabel) + '</strong> ' + (_zh ? '已完成' : 'completed');
            el.style.background = 'rgba(16,185,129,0.1)';
            el.style.borderColor = 'rgba(16,185,129,0.3)';
            el.style.color = 'var(--success)';
        }
    } else if (status === 'error') {
        if (spinner) spinner.remove();
        if (textEl) {
            textEl.innerHTML = '<strong>' + escHtml(_toolLabel) + '</strong> ' + (_zh ? '失败' : 'failed');
            el.style.background = 'rgba(239,68,68,0.1)';
            el.style.borderColor = 'rgba(239,68,68,0.3)';
            el.style.color = 'var(--danger)';
        }
    }
}

// =============================================================================
// Todo list (persistent at bottom of bot reply, breathes while active)
// =============================================================================
//
// We watch SSE step events from the chat agent and render a todo list at the
// bottom of the LLM's current chat row. Each step (user input, LLM thinking,
// tool call, final assistant reply) becomes a todo entry; the in-flight one
// has a breathing left bar + center dot. When the final assistant response
// arrives, the list folds itself (header only, with a count badge).
//
// State is held in window._chatTodo and rebuilt as the stream progresses.
// We don't keep a singleton — each user message gets a fresh todo list
// attached to that turn's bot row, so multiple in-flight prompts don't
// collide. The 'folded' state is the resting state after the response
// completes; the user can re-expand by clicking the header.

// Language-aware todo labels. The user complained that typing
// English but seeing Chinese todo entries is a "顶层问题" — to
// fix it top-level, the todo list now picks labels from a
// per-language dictionary. The explicit EN/中文 toggle is the single source
// of truth, including for in-flight todo rows.
const _TODO_I18N = {
    zh: {
        header: '执行进度',
        default_processing: '处理中',
        call_prefix: '调用 ',
        user: '接收用户请求',
        thinking: 'LLM 思考 / 路由',
        memory: '记忆检索 / 经验匹配',
        assistant: '生成最终回复',
        error: '出现错误',
        done: '执行完成',
        tools: {
            ctv_segmentation: 'CTV 靶区分割',
            oar_segmentation: 'OAR 危及器官分割',
            trajectory_planning: '轨迹初始化 / 细化',
            planning_pipeline: '粒子植入规划（5 步流水线）',
            // Sub-steps emitted by planning_pipeline step:full.
            // The tool calls back into the agent for each of these
            // and the agent translates to SSE step events so the
            // todo list ticks through 5 items, not just one black
            // box. Without these entries, the labels would fall
            // through to "调用 trajectory_init" which is awkward.
            trajectory_init: '轨迹初始化',
            trajectory_refine: '轨迹细化',
            seed_planning: '种子位置优化',
            dose_engine: '剂量计算',
            dose_calc: '剂量计算',
            dose_eval: '剂量学评估',
            dose_evaluation: '剂量学评估',
            seed_segmentation: '种子区域分割',
            seed_placement: '种子放置',
            report_generator: '报告生成',
            report_auto_fill: '报告自动填充',
            dicom_rt_exporter: 'DICOM-RT 导出',
            case_memory: '调用案例记忆',
            clinical_kb: '查询临床知识库',
            safety_validator: '安全校验',
            plan_comparator: '计划对比',
            code_executor: '执行代码',
            filesystem_browser: '浏览文件系统',
            web_search: '联网搜索',
            web_fetch: '抓取网页',
            ui_screenshot: '截屏',
            ui_controller: 'UI 控制',
            ui_annotate: '图像标注',
            shell_executor: '执行 Shell 命令',
            env_manager: '环境管理',
        },
    },
    en: {
        header: 'Progress',
        default_processing: 'Processing...',
        call_prefix: 'Calling ',
        user: 'User input',
        thinking: 'LLM thinking / routing',
        memory: 'Memory recall',
        assistant: 'Final response',
        error: 'Error',
        done: 'Done',
        tools: {
            ctv_segmentation: 'CTV tumor segmentation',
            oar_segmentation: 'OAR segmentation',
            trajectory_planning: 'Trajectory init / refine',
            planning_pipeline: 'Brachytherapy planning (5-stage pipeline)',
            // Sub-steps emitted by planning_pipeline step:full.
            trajectory_init: 'Trajectory initialization',
            trajectory_refine: 'Trajectory refinement',
            seed_planning: 'Seed position optimization',
            dose_engine: 'Dose calculation',
            dose_evaluation: 'Dose evaluation',
            dose_calc: 'Dose calculation',
            dose_eval: 'Dose evaluation',
            seed_segmentation: 'Seed-region segmentation',
            seed_placement: 'Seed placement',
            report_generator: 'Report generation',
            report_auto_fill: 'Report auto-fill',
            dicom_rt_exporter: 'DICOM-RT export',
            case_memory: 'Case memory lookup',
            clinical_kb: 'Clinical knowledge base',
            safety_validator: 'Safety validation',
            plan_comparator: 'Plan comparison',
            code_executor: 'Code execution',
            filesystem_browser: 'Filesystem browser',
            web_search: 'Web search',
            web_fetch: 'Web fetch',
            ui_screenshot: 'Screenshot',
            ui_controller: 'UI control',
            fact_checker: 'Source verification',
            ui_annotate: 'Image annotation',
            shell_executor: 'Shell command',
            env_manager: 'Environment management',
        },
    },
};

// Active language for todo lists. Updated by:
//   1. The chat SSE handler when /api/chat returns the detected
//      user-input language (server-side detection).
//   2. The global UI language toggle (setUiLanguage) when the user
//      flips EN/中 in the header. Per user feedback (2026-06-16),
//      todo labels must follow the GLOBAL toggle, not just the
//      per-message detected language — otherwise switching EN/中
//      in the header leaves the todo in the wrong language.
// Default 'en' to match the global default.
let _activeTodoLang = 'en';
