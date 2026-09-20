function _setActiveTodoLang(code) {
    if (!code || !_TODO_I18N[code]) return;
    if (_activeTodoLang === code) return;
    _activeTodoLang = code;
    // Re-render any visible todo list's labels in the new language.
    // We only update the LABEL TEXT — status dots (✓/✕), elapsed
    // times, and the count badge remain unchanged. The header
    // text and per-step tool names are recomputed from _TODO_I18N.
    try {
        const dock = document.getElementById('chatTodoDock');
        if (!dock) return;
        const headerSpan = dock.querySelector('.chat-todo-header > .chat-todo-toggle > span:nth-child(2)');
        if (headerSpan) headerSpan.textContent = _TODO_I18N[code].header;
        // Update each item's label text from its stored step.
        dock.querySelectorAll('.chat-todo-item').forEach(li => {
            const lbl = li.querySelector('.chat-todo-label');
            if (!lbl) return;
            const item = (window._activeTodoApi && window._activeTodoApi.items || []).find(it => it.node === li);
            if (item && item.step) {
                lbl.textContent = _todoLabelForStep(item.step);
            }
        });
    } catch (_) { /* best-effort */ }
}
function _todoI18n() {
    return _TODO_I18N[_activeTodoLang] || _TODO_I18N.en;
}

// A single browser-side clock is shared by the chat todo dock and the
// lightweight progress cards rendered for manual actions.  Previously each
// surface called Date.now() independently: a background guide restore could
// create a top card and the later chat tool could create a second bottom row,
// making the two elapsed values look like one operation with contradictory
// timings.  Keep the clock keyed by case + canonical operation so both
// surfaces either join the same operation or start their own clean instance.
const _BRACHY_OPERATION_ALIASES = Object.freeze({
    surgical_guide_generate: 'surgical_guide',
});
const _BRACHY_OPERATION_CLOCKS = window.__brachyOperationClocks
    || (window.__brachyOperationClocks = Object.create(null));

function _brachyOperationName(operation) {
    const raw = String(operation || '').trim();
    return _BRACHY_OPERATION_ALIASES[raw] || raw;
}

function _brachyOperationSession(sessionId) {
    if (sessionId != null && String(sessionId).trim()) return String(sessionId);
    try {
        if (typeof activeSessionId !== 'undefined' && activeSessionId != null) {
            return String(activeSessionId);
        }
    } catch (_) { /* the page-level binding may not exist during startup */ }
    return String(window.activeSessionId || '');
}

function _brachyOperationTimestamp(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return null;
    // Backend timestamps are seconds; DOM timestamps are milliseconds.
    return numeric < 1e12 ? numeric * 1000 : numeric;
}

function _brachyOperationClock(operation, sessionId) {
    const name = _brachyOperationName(operation);
    if (!name) return null;
    const sid = _brachyOperationSession(sessionId);
    const key = `${sid}::${name}`;
    let clock = _BRACHY_OPERATION_CLOCKS[key];
    if (!clock) {
        clock = { key, name, sessionId: sid, startedAt: null, endedAt: null };
        _BRACHY_OPERATION_CLOCKS[key] = clock;
    }
    return clock;
}

window._brachyOperationName = _brachyOperationName;
window._brachyOperationClock = _brachyOperationClock;
window._brachyOperationStart = function _brachyOperationStart(
    operation, sessionId, startedAt, options = {},
) {
    const clock = _brachyOperationClock(operation, sessionId);
    if (!clock) return null;
    const incoming = _brachyOperationTimestamp(startedAt);
    const reset = options && options.reset === true;
    const restore = options && options.restore === true;
    if (reset || restore || clock.endedAt != null || !_brachyOperationTimestamp(clock.startedAt)) {
        clock.startedAt = incoming || Date.now();
        clock.endedAt = null;
    }
    // When the first authoritative event arrives from the server, retain its
    // timestamp only if this operation had not already started in the UI.
    // Never move an active clock forward because an SSE packet arrived late.
    if (incoming && !clock.endedAt && !reset && !restore
        && clock.startedAt == null) {
        clock.startedAt = incoming;
    }
    return clock;
};
window._brachyOperationFinish = function _brachyOperationFinish(
    operation, sessionId, endedAt,
) {
    const clock = _brachyOperationClock(operation, sessionId);
    if (!clock) return null;
    if (!_brachyOperationTimestamp(clock.startedAt)) clock.startedAt = Date.now();
    clock.endedAt = _brachyOperationTimestamp(endedAt) || Date.now();
    return clock;
};

function _todoStepStartedAt(step) {
    if (!step || typeof step !== 'object') return null;
    return _brachyOperationTimestamp(step.started_at ?? step.startedAt);
}

function _todoLabelForStep(step) {
    // Pick labels from the explicit workstation language preference.
    const i18n = _todoI18n();
    if (step.type === 'tool' && step.tool) {
        // Keep the internal evidence phase readable even when an older
        // localized dictionary does not yet contain the tool name.
        if (step.tool === 'fact_checker') {
            return _activeTodoLang === 'zh' ? '\u6765\u6e90\u6838\u9a8c' : 'Source verification';
        }
        return i18n.tools[step.tool] || (i18n.call_prefix + step.tool);
    }
    if (step.type === 'thinking') {
        // Persisted traces from older sessions may contain English titles.
        // Localize only their presentation; the stable step ID remains intact.
        const title = String(step.title || '');
        if (_activeTodoLang === 'zh') {
            if (title === 'Multi-Agent Router') return '\u591a\u667a\u80fd\u4f53\u8def\u7531';
            if (title === 'Local Intent') return '\u672c\u5730\u610f\u56fe\u8bc6\u522b';
            if (/^LLM Call\s*(\d+)?$/i.test(title)) {
                const suffix = title.replace(/^LLM Call\s*/i, '');
                return `\u6a21\u578b\u8c03\u7528${suffix ? ` ${suffix}` : ''}`;
            }
        }
        if (title) return title;
        return i18n.thinking;
    }
    if (step.type === 'memory') {
        return step.title || i18n.memory;
    }
    // Prefer the step's own title for assistant milestones. Every assistant
    // step used to fall through to the generic ``i18n.assistant`` label, so
    // "Response Synthesis" and "Final Response" both rendered as "Final
    // response" and looked like two identical tasks in the Progress dock.
    if (step.type === 'assistant' && step.title) {
        return String(step.title);
    }
    return i18n[step.type] || (step.title || i18n.default_processing);
}

// UI-controller actions are applied in the browser after the server emits
// the validated action list. Keep them in the same live trace and todo stream
// so the user sees one truthful, sequential progress surface.
if (!window._brachyUiTraceListenerReady) {
    window._brachyUiTraceListenerReady = true;
    document.addEventListener('brachy:ui-action-progress', (event) => {
        const step = event && event.detail;
        if (!step?.id) return;
        const owners = window._brachyUIActionOwners ||= new Map();
        let owner = owners.get(step.id);
        if (owner && ((step.request_id && step.request_id !== owner.trace.requestId)
            || (step.session_id && step.session_id !== owner.trace.sessionId))) return;
        if (owner && !['pending', 'active', 'running'].includes(owner.step.status)
            && ['pending', 'active', 'running'].includes(step.status)) return;
        if (!owner) {
            const candidate = window._brachyLiveTrace;
            if (!candidate || (step.session_id && step.session_id !== candidate.sessionId)
                || (step.request_id && step.request_id !== candidate.requestId)) return;
            owner = { trace: candidate, step };
            owners.set(step.id, owner);
        }
        owner.step = step;
        const trace = owner.trace;
        // Keep the owner captured at dispatch, even after a new turn/case.
        // Persist late results there; never append them to the new trace.
        if (!trace) return;
        let index = trace.steps.findIndex(row => row.id === step.id && !!step.id);
        if (index < 0) {
            index = trace.steps.length;
            trace.steps.push(step);
        } else {
            trace.steps[index] = { ...trace.steps[index], ...step };
        }
        const visibleOwner = trace.sessionId === activeSessionId;
        if (visibleOwner && typeof appendStepToChain === 'function') {
            appendStepToChain(trace.stepsDiv, step, index);
        }
        if (visibleOwner && typeof updateChainHeader === 'function') {
            updateChainHeader(trace.headerEl, trace.steps);
        }
        const activeTodo = visibleOwner && trace === window._brachyLiveTrace
            && typeof trace.getTodo === 'function' ? trace.getTodo() : null;
        if (activeTodo && typeof _todoUpdateFromStep === 'function') {
            _todoUpdateFromStep(activeTodo, step);
        }
        if (trace.requestId && typeof saveSessionMessage === 'function') {
            saveSessionMessage('thinking', '', trace.steps, Date.now(), trace.sessionId, {
                requestId: trace.requestId, messageId: `trace-${trace.requestId}`,
                messageKind: 'execution_trace', turnSequence: 1,
                responseLanguage: trace.responseLanguage, traceLanguage: trace.responseLanguage,
            });
        }
        // Bound retained terminal owners; never evict an in-flight action.
        if (owners.size > 256) for (const [key, value] of owners) {
            if (!['pending', 'active', 'running'].includes(value.step.status)) owners.delete(key);
            if (owners.size <= 256) break;
        }
    });
}

function _todoCreate() {
    // Build an empty todo container. Returns the DOM node and an `update` fn
    // the caller can use to push state changes.
    const root = document.createElement('div');
    root.className = 'chat-todo';

    const header = document.createElement('div');
    header.className = 'chat-todo-header';
    const toggle = document.createElement('span');
    toggle.className = 'chat-todo-toggle';
    toggle.innerHTML = '<span class="chat-todo-caret">▼</span> <span>' + _todoI18n().header + '</span> <span class="chat-todo-count"></span>';
    // Track the active todo API globally so _setActiveTodoLang()
    // can re-render labels when the user flips the global
    // EN/Chinese language toggle mid-task. There is only ever one
    // todo visible at a time per chat (sendChat wipes the dock at
    // start), so a
    // single global ref is enough.
    // Replacing the single visible Progress dock supersedes the previous
    // turn's presentation. Cancel it explicitly so an orphaned active row
    // cannot keep its elapsed timer running behind the new task.
    try { window._activeTodoApi?.cancel?.('Stopped'); } catch (_) {}
    window._activeTodoApi = null; // will be set after api is built
    toggle.onclick = () => {
        root.classList.toggle('folded');
        const collapsed = root.querySelector('.chat-todo-list').classList.toggle('collapsed');
        root.querySelector('.chat-todo-caret').textContent = collapsed ? '▶' : '▼';
        // BUG FIX 2026-06-16: cancel any pending auto-hide so the
        // user's click on the header doesn't get overridden by the
        // 4s timer. Also reset opacity if the fade had started.
        if (root._hideTimer) {
            clearTimeout(root._hideTimer);
            root._hideTimer = null;
        }
        root.style.opacity = '';
        root.style.transition = '';
        // If user re-expanded, ensure dock is visible.
        if (!collapsed) {
            const dock = document.getElementById('chatTodoDock');
            if (dock) dock.style.display = '';
        }
    };
    header.appendChild(toggle);
    root.appendChild(header);

    const ul = document.createElement('ul');
    ul.className = 'chat-todo-list';
    root.appendChild(ul);

    const api = {
        root,
        items: [],          // [{id, label, status, startedAt, endedAt, node}]
        addPending(step) {
            // New step arrives → add a pending entry; mark any currently-
            // active entry as done (or rather: keep it in 'done' state and
            // let the new entry be 'active').
            const milestoneKey = _todoStepIdentity(step);
            // A logical milestone must never be listed twice (client-synth +
            // server replay + restored snapshot all share one identity).
            if (milestoneKey) {
                const existing = api.items.find(i => i.milestoneKey === milestoneKey);
                if (existing) return existing;
            }
            const id = (step.id != null && step.id !== '')
                ? String(step.id)
                : (milestoneKey
                    ? 'milestone-' + milestoneKey.replace(/[^A-Za-z0-9_.:-]/g, '_')
                    : ('s' + (api.items.length + 1)));
            const label = _todoLabelForStep(step);
            const li = document.createElement('li');
            li.className = 'chat-todo-item pending';
            li.dataset.todoId = id;
            const dot = document.createElement('span'); dot.className = 'chat-todo-dot';
            const lbl = document.createElement('span'); lbl.className = 'chat-todo-label'; lbl.textContent = label;
            const time = document.createElement('span'); time.className = 'chat-todo-time';
            li.appendChild(dot); li.appendChild(lbl); li.appendChild(time);
            ul.appendChild(li);
            // Store toolName directly on item for reliable dedup
            // (labels may be translated to Chinese, so label-based
            // matching fails for English tool names like "trajectory_init").
            const operationName = _brachyOperationName(step.tool || '');
            const operationClock = operationName && _isInFlightToolStatus(step.status)
                ? window._brachyOperationStart(
                    operationName,
                    api._sessionId,
                    _todoStepStartedAt(step),
                )
                : null;
            const item = {
                id,
                label,
                toolName: step.tool || null,
                milestoneKey: milestoneKey || null,
                status: 'pending',
                startedAt: operationClock?.startedAt || _todoStepStartedAt(step) || Date.now(),
                endedAt: null,
                node: li,
                step,
                _operationName: operationName || null,
                _seededReady: false,
            };
            api.items.push(item);
            _todoUpdateCount();
            return item;
        },
        markActive(item) {
            // Never reactivate a completed or errored step — the LLM
            // may emit events out of order (e.g. re-emit an old step
            // as 'pending' while a newer step is already done).
            if (item.status === 'done' || item.status === 'error') return;
            // Keep every unfinished step active. Planning may run several
            // independent tasks in parallel, so demoting the previous row
            // would incorrectly stop its breathing animation and timer.
            if (item.status === 'active') {
                _todoUpdateCount();
                return;
            }
            item.status = 'active';
            // BUG FIX 2026-06-16: the user reported that after CTV
            // finished, OAR's row went directly from "predicted" →
            // "done" without any visible "active" breathing state.
            // Root cause: SSE `pending` + `done` events for the
            // auto-fired OAR arrive in the SAME flush batch (both
            // appended to _pending_callback_events and drained
            // together after the CTV tool returns). The browser
            // processes them in the same JS task and never paints
            // an intermediate "active" frame. We work around this
            // client-side by enforcing a minimum display time:
            // when a predicted item goes active, we record
            // `_activatedAt`; if a `done` event arrives within 1s
            // of activation, defer the done transition by the
            // remaining time so the user sees the breathing state.
            item._activatedAt = Date.now();
            const operationName = item._operationName
                || _brachyOperationName(item.toolName || item.step?.tool || '');
            if (operationName) {
                const operationClock = window._brachyOperationStart(
                    operationName,
                    api._sessionId,
                    _todoStepStartedAt(item.step),
                );
                item._operationName = operationName;
                if (operationClock?.startedAt) item.startedAt = operationClock.startedAt;
            }
            // GUARD against bad startedAt values (2026-06-16 bug: the
            // OAR step showed "781586106.x seconds" because startedAt
            // had been clobbered to 0 somewhere upstream, and the
            // `|| Date.now()` check didn't catch it because 0 is
            // falsy but Date.now() is way larger so the diff was
            // ~1.7e9). Only treat null/undefined as "not started";
            // accept any positive ms timestamp.
            if (item.startedAt == null || item.startedAt <= 0
                    || item.startedAt > Date.now() + 60000) {
                item.startedAt = Date.now();
            }
            // Clear ALL transitional classes so the breathing animation
            // actually starts. Without removing 'predicted', the
            // predicted styling (opacity 0.55, no animation) would
            // win and the user would see no breathing.
            item.node.classList.remove('pending', 'predicted');
            item.node.classList.add('active');
            _todoUpdateCount();
            _todoStartTimer(item);
            _todoStartGpuBadge(item);
            if (item._animationGuard) clearInterval(item._animationGuard);
            // Keep the active class and animation running while the backend
            // is still working. This protects against late SSE redraws that
            // replace a row's classes without changing its logical status.
            item._animationGuard = setInterval(() => {
                if (item.status !== 'active') {
                    clearInterval(item._animationGuard);
                    item._animationGuard = null;
                    item.node.style.animationPlayState = '';
                    return;
                }
                item.node.classList.add('active');
                item.node.style.animationPlayState = 'running';
            }, 500);
        },
        // A predicted row may be marked done during seeding when the
        // current Data Tree already contains a reusable CTV/OAR result.
        // That is only an optimistic readiness hint, not evidence that
        // this turn cannot execute the same tool again. If the server later
        // emits the real in-flight event, reopen that row before marking it
        // active so the bottom Progress surface agrees with the trace.
        reopenSeeded(item) {
            if (!item || item._seededReady !== true) return false;
            if (item._timer) { clearInterval(item._timer); item._timer = null; }
            if (item._animationGuard) {
                clearInterval(item._animationGuard);
                item._animationGuard = null;
            }
            _todoStopGpuBadge(item);
            item._seededReady = false;
            item._activatedAt = null;
            item.startedAt = null;
            item.endedAt = null;
            item._realElapsedMs = null;
            item.status = 'pending';
            item.node.classList.remove('done', 'error', 'predicted', 'active');
            item.node.classList.add('pending');
            const dot = item.node.querySelector('.chat-todo-dot');
            if (dot) dot.textContent = '';
            this.markActive(item);
            return true;
        },
        markDone(item, errMsg) {
            // Always ensure at least one browser paint frame shows the
            // "active" breathing state before transitioning to done.
            // When pending+done arrive in the same SSE batch (e.g. OAR
            // auto-fire), sinceActive ≈ 0 and the old code skipped the
            // defer — the user saw "CTV executing + OAR completed"
            // instead of "CTV done → OAR executing → OAR done".
            // A later terminal event supersedes an optimistic readiness
            // hint; stale pending packets must not reopen this row again.
            if (item._seededReady) item._seededReady = false;
            const sinceActive = item._activatedAt ? (Date.now() - item._activatedAt) : 9999;
            if (item.status === 'active') {
                // Minimum 120ms visible active state (~2 frames at 60fps).
                // If already visible for longer, transition immediately.
                const delay = Math.max(0, 120 - sinceActive);
                if (delay > 0) {
                    setTimeout(() => {
                        if (item.status === 'active') this.markDone(item, errMsg);
                    }, delay);
                    return;
                }
            }
            if (item._timer) { clearInterval(item._timer); item._timer = null; }
            if (item._animationGuard) { clearInterval(item._animationGuard); item._animationGuard = null; }
            item.node.style.animationPlayState = '';
            _todoStopGpuBadge(item);
            item.status = errMsg ? 'error' : 'done';
            item.endedAt = Date.now();
            if (item._operationName) {
                const operationClock = window._brachyOperationFinish(
                    item._operationName,
                    api._sessionId,
                    item.endedAt,
                );
                if (operationClock?.startedAt) item.startedAt = operationClock.startedAt;
            }
            // GUARD: if startedAt is still null/bad by the time we
            // mark done (predicted item that was promoted but the
            // upstream never sent a pending event for it), fall
            // back to endedAt so the displayed duration is "0.0s"
            // instead of "1.7e9s". Same threshold as markActive.
            if (item.startedAt == null || item.startedAt <= 0
                    || item.startedAt > Date.now() + 60000) {
                item.startedAt = item.endedAt;
            }
            // Clear all transitional classes; only the final
            // status remains. Same reason as markActive: if we
            // leave 'predicted' in, the dimmed ghost styling sticks.
            item.node.classList.remove('pending', 'active', 'predicted');
            item.node.classList.add(item.status);
            // Insert the status glyph into the dot (✓ done, ✕ error).
            // This is the Claude Code CLI style: a small icon inside
            // the colored circle, not a separate icon next to it.
            const dot = item.node.querySelector('.chat-todo-dot');
            if (dot) {
                dot.textContent = errMsg ? '✕' : '✓';
            }
            const t = item.node.querySelector('.chat-todo-time');
            if (t) {
                // Use real execution time from backend if available.
                // _realElapsedMs is set from "elapsed_ms=XXXX" in the
                // done event content. This gives the ACTUAL wall-clock
                // time the operation took, not the network delay.
                const dur = item._realElapsedMs != null
                    ? item._realElapsedMs / 1000
                    : (item.endedAt - item.startedAt) / 1000;
                // Final defensive clamp: never display a duration
                // larger than 24h (the user can see something has
                // gone wrong; we just refuse to show "1.7e9s").
                if (!isFinite(dur) || dur < 0 || dur > 86400) {
                    t.textContent = '—';
                } else {
                    t.textContent = dur.toFixed(1) + 's';
                }
            }
            _todoUpdateCount();
        },
        cancel(reason) {
            // Abort is a terminal UI state. Do not leave active rows, elapsed
            // timers, GPU polling, or breathing guards alive after the user
            // presses Stop while the SSE stream is being torn down.
            const message = reason || 'Stopped';
            for (const it of api.items) {
                if (it.status !== 'pending' && it.status !== 'active' && it.status !== 'predicted') continue;
                if (it._timer) { clearInterval(it._timer); it._timer = null; }
                if (it._animationGuard) { clearInterval(it._animationGuard); it._animationGuard = null; }
                it.node.style.animationPlayState = '';
                _todoStopGpuBadge(it);
                it.status = 'error';
                it._seededReady = false;
                it.endedAt = Date.now();
                if (it.startedAt == null || it.startedAt <= 0 || it.startedAt > Date.now() + 60000) {
                    it.startedAt = it.endedAt;
                }
                it.node.classList.remove('pending', 'active', 'predicted', 'done');
                it.node.classList.add('error');
                const dot = it.node.querySelector('.chat-todo-dot');
                if (dot) dot.textContent = 'x';
                const time = it.node.querySelector('.chat-todo-time');
                if (time) time.textContent = message;
            }
            _todoUpdateCount();
            // Keep the stopped summary briefly readable, but never leave a
            // live progress row expanded after cancellation.
            this.fold();
        },
        dispose() {
            // Presentation-only teardown for a case switch.  This must not
            // mark rows as failed or call the server: the case-owned task
            // continues in the background and will be rebuilt on return.
            for (const it of api.items) {
                if (it._timer) { clearInterval(it._timer); it._timer = null; }
                if (it._animationGuard) { clearInterval(it._animationGuard); it._animationGuard = null; }
                it.node?.style && (it.node.style.animationPlayState = '');
                _todoStopGpuBadge(it);
            }
            if (root._hideTimer) { clearTimeout(root._hideTimer); root._hideTimer = null; }
            if (root.parentNode) root.parentNode.removeChild(root);
        },
        fold() {
            // Final assistant response arrived — mark all remaining
            // pending/active items as done so the count is accurate.
            // Without this, items like web_search stay "spinning" in
            // the dock even after the response is fully generated.
            for (const it of api.items) {
                if (it.status === 'pending' || it.status === 'active' || it.status === 'predicted') {
                    if (it._timer) { clearInterval(it._timer); it._timer = null; }
                    if (it._animationGuard) { clearInterval(it._animationGuard); it._animationGuard = null; }
                    it.node.style.animationPlayState = '';
                    _todoStopGpuBadge(it);
                    it.status = 'done';
                    it._seededReady = false;
                    it.endedAt = Date.now();
                    if (it.startedAt == null || it.startedAt <= 0 || it.startedAt > Date.now() + 60000) {
                        it.startedAt = it.endedAt;
                    }
                    it.node.classList.remove('pending', 'active', 'predicted');
                    it.node.classList.add('done');
                    const dot = it.node.querySelector('.chat-todo-dot');
                    if (dot) dot.textContent = '✓';
                    const t = it.node.querySelector('.chat-todo-time');
                    if (t) {
                        const dur = (it.endedAt - it.startedAt) / 1000;
                        t.textContent = (!isFinite(dur) || dur < 0 || dur > 86400) ? '—' : dur.toFixed(1) + 's';
                    }
                }
            }
            _todoUpdateCount();
            // Collapse to header only but keep it visible (so the user can re-expand).
            root.classList.add('folded');
            const list = root.querySelector('.chat-todo-list');
            list.classList.add('collapsed');
            root.querySelector('.chat-todo-caret').textContent = '▶';
            // BUG FIX 2026-06-16 (todo accumulation): previously the
            // folded todo lingered in the dock forever, so after 3-4
            // turns the user saw stacked "Progress (11/17)" headers.
            // After the response finishes, auto-hide the dock after
            // 4s (long enough to read the count + click re-expand).
            // We cancel any prior hide timer first, so a fresh fold
            // resets the clock.
            try {
                if (root._hideTimer) clearTimeout(root._hideTimer);
                root._hideTimer = setTimeout(() => {
                    const dock = document.getElementById('chatTodoDock');
                    if (dock && root.parentNode === dock) {
                        // Soft fade: 200ms opacity → 0, then display:none.
                        root.style.transition = 'opacity 0.2s ease';
                        root.style.opacity = '0';
                        setTimeout(() => {
                            // Only hide if the user hasn't re-expanded
                            // (i.e. dock still contains exactly this
                            // root and it's still folded).
                            if (root.parentNode === dock && root.classList.contains('folded')) {
                                dock.style.display = 'none';
                            }
                            root.style.opacity = '';
                            root.style.transition = '';
                        }, 220);
                    }
                }, 4000);
            } catch (_) {}
        },
    };

    function _todoUpdateCount() {
        const done = api.items.filter(i => i.status === 'done' || i.status === 'error').length;
        const total = api.items.length;
        const cnt = root.querySelector('.chat-todo-count');
        if (cnt) cnt.textContent = '(' + done + '/' + total + ')';
    }
    // The seed is called BEFORE the first SSE event, so the count
    // needs to be updated then too. We override _todoUpdateCount via
    // a public call after seeding.

    function _todoStartTimer(item) {
        if (item._timer) clearInterval(item._timer);
        const t = item.node.querySelector('.chat-todo-time');
        // If we already know the real elapsed time (from backend),
        // use it as the starting display value.
        if (item._realElapsedMs != null && t) {
            t.textContent = (item._realElapsedMs / 1000).toFixed(1) + 's';
        }
        item._timer = setInterval(() => {
            if (!t) return;
            const elapsed = ((Date.now() - item.startedAt) / 1000);
            // Defensive: clamp displayed elapsed to 24h max.
            if (!isFinite(elapsed) || elapsed < 0 || elapsed > 86400) {
                t.textContent = '—';
            } else {
                t.textContent = elapsed.toFixed(1) + 's';
            }
        }, 100);
    }

    // GPU STATUS BADGE (2026-06-16): the user complained that they
    // couldn't tell if a running step was actually using a GPU or
    // stuck on CPU. The server already exposes /api/device/status
    // (powered by plans/device_manager.DeviceManager), so we poll it
    // while an item is active and show "🎮 cuda:1 (12.3GB free, 87%)"
    // next to the elapsed time. The badge disappears on markDone.
    // Polling stops automatically when status changes away from active.
    function _todoStartGpuBadge(item) {
        if (item._gpuTimer) clearInterval(item._gpuTimer);
        // Find or create a badge node inside the active item.
        let badge = item.node.querySelector('.chat-todo-gpu');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'chat-todo-gpu';
            // Place badge to the LEFT of the elapsed time. We insert
            // before the .chat-todo-time element (which is the last
            // child of li, added in addPending).
            const time = item.node.querySelector('.chat-todo-time');
            if (time && time.parentNode === item.node) {
                item.node.insertBefore(badge, time);
            } else {
                item.node.appendChild(badge);
            }
        }
        // Render helper: take the JSON from /api/device/status and
        // pick the GPU with the most free memory. This is most likely
        // the GPU that device_manager selected for the current tool.
        // Don't try to guess based on memory usage, as other processes
        // (like training) may be using GPUs and give misleading signals.
        const render = (s) => {
            if (!s || !s.cuda_available) {
                badge.textContent = '🎮 CPU';
                badge.classList.add('cpu');
                return;
            }
            // Pick the GPU with the most free memory (what device_manager likely selected)
            const devs = (s.devices || []).filter(d => d.is_available !== false);
            const target = devs.length ? devs.reduce((a, b) => (a.free_mem_mb > b.free_mem_mb ? a : b)) : null;
            if (!target) {
                badge.textContent = '';
                return;
            }
            const freeGB = (target.free_mem_mb / 1024).toFixed(1);
            const util = (target.utilization_pct >= 0) ? `, ${target.utilization_pct}%` : '';
            const shortName = (target.name || '').replace(/NVIDIA\s+GeForce\s+/i, '').replace(/^RTX\s+/, 'RTX ');
            badge.textContent = `🎮 cuda:${target.index} · ${freeGB}GB free${util}`;
            badge.classList.remove('cpu');
            badge.title = `GPU ${target.index}: ${target.name}\n` +
                          `Memory: ${(target.used_mem_mb/1024).toFixed(1)}/${(target.total_mem_mb/1024).toFixed(1)} GB used\n` +
                          `Active leases on this server: ${s.active_leases}`;
        };
        // Use AbortController so we can cancel the in-flight request
        // when markDone fires.
        item._gpuAbort = new AbortController();
        item._gpuRequestAbort = null;
        let gpuStatusFailures = 0;
        const fetchOnce = async () => {
            // A delayed device query must not accumulate behind the next
            // 2-second poll while the server is busy with planning/I/O.
            if (item._gpuRequestAbort) {
                try { item._gpuRequestAbort.abort(); } catch (_) {}
            }
            const requestAbort = new AbortController();
            item._gpuRequestAbort = requestAbort;
            const timeout = setTimeout(() => {
                try { requestAbort.abort(); } catch (_) {}
            }, 3500);
            const cancelWithItem = () => {
                try { requestAbort.abort(); } catch (_) {}
            };
            item._gpuAbort.signal.addEventListener('abort', cancelWithItem, { once: true });
            try {
                const r = await fetch('/api/device/status', { signal: requestAbort.signal });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const s = await r.json();
                gpuStatusFailures = 0;
                render(s);
            } catch (e) {
                if (e.name !== 'AbortError' && !item._gpuAbort.signal.aborted) {
                    gpuStatusFailures += 1;
                    // One delayed status response is expected during a long
                    // planner checkpoint. Only show '?' after consecutive
                    // failures so the device badge does not amplify a
                    // transient control-plane stall into a false fault.
                    if (gpuStatusFailures >= 3) {
                        badge.textContent = '🎮 ?';
                    }
                }
            } finally {
                clearTimeout(timeout);
                item._gpuAbort.signal.removeEventListener('abort', cancelWithItem);
                if (item._gpuRequestAbort === requestAbort) {
                    item._gpuRequestAbort = null;
                }
            }
        };
        fetchOnce();
        item._gpuTimer = setInterval(fetchOnce, 2000);
    }
    function _todoStopGpuBadge(item) {
        if (item._gpuTimer) { clearInterval(item._gpuTimer); item._gpuTimer = null; }
        if (item._gpuAbort) { try { item._gpuAbort.abort(); } catch (_) {} item._gpuAbort = null; }
        if (item._gpuRequestAbort) { try { item._gpuRequestAbort.abort(); } catch (_) {} item._gpuRequestAbort = null; }
        const badge = item.node && item.node.querySelector && item.node.querySelector('.chat-todo-gpu');
        if (badge) {
            // Don't remove the DOM node — just clear its text. The
            // step is still in the list, and the user might want to
            // see which GPU was used.
            badge.textContent = '';
        }
    }

    // Register this todo as the currently active one so the global
    // EN/Chinese language toggle can re-render its labels in the new
    // language (see _setActiveTodoLang above).
    window._activeTodoApi = api;
    // Stamp the owning session so clearCaseScopedProgressPresentation
    // can persist the items under the correct key even after
    // paintSessionShell has already updated activeSessionId.
    api._sessionId = typeof activeSessionId !== 'undefined' ? String(activeSessionId) : '';

    return api;
}

window.clearCaseScopedProgressPresentation = function clearCaseScopedProgressPresentation() {
    // A browser has one visible chat column, but each case has an independent
    // task.  Removing this display state prevents an old task's timer/Progress
    // dock from leaking into a fresh case without changing any server task.
    const todo = window._activeTodoApi;
    // Persist the todo-state snapshot keyed by the session that OWNS the
    // todo (not the current activeSessionId, which paintSessionShell may
    // have already advanced to the new case).  The timer then shows the true
    // elapsed wall-clock time — including the interval spent on another
    // case — rather than restarting from zero.
    const sid = todo?._sessionId
        || (typeof activeSessionId !== 'undefined' ? String(activeSessionId) : '');
    if (todo && sid && todo.items && todo.items.length) {
        window._caseTodos = window._caseTodos || {};
        window._caseTodos[sid] = todo.items.map(item => ({
            id: item.id,
            label: item.label,
            toolName: item.toolName || null,
            milestoneKey: item.milestoneKey || null,
            status: item.status,
            startedAt: item.startedAt,
            endedAt: item.endedAt,
            predicted: !!item.predicted,
            predictedTool: item.predictedTool || null,
            _realElapsedMs: item._realElapsedMs,
        }));
    }
    try { todo?.dispose?.(); } catch (_) {}
    window._activeTodoApi = null;
    window._brachyLiveTrace = null;
    window._toolProgressEls = [];
    const dock = document.getElementById('chatTodoDock');
    if (dock) {
        dock.replaceChildren();
        dock.style.display = 'none';
    }
};

// Maps a raw SSE step event to a todo item (creates one if the step.id
// is new) and updates its status (pending → active → done/error).
// First tries to find a predicted item by tool name; only falls back to
// creating a new item if no match.
function _todoStepIdentity(step) {
    // Stable logical identity for a Progress row. The Execution Trace merges
    // the final-response milestone by phase/title, but the dock only matched
    // by server id. A client-synthesised row, a replayed SSE event and a
    // restored snapshot can carry different ids for the same milestone, which
    // produced two "Final response" rows. Key milestones by phase instead.
    if (!step || typeof step !== 'object') return '';
    if (typeof _isFinalResponseTraceStep === 'function' && _isFinalResponseTraceStep(step)) {
        return 'phase:final_response';
    }
    const phase = String(step.phase || step.metadata?.phase || '')
        .trim().toLowerCase().replace(/[\s-]+/g, '_');
    if (phase) return 'phase:' + phase;
    if (step.tool) return 'tool:' + String(step.tool);
    if (step.id != null && step.id !== '') return 'id:' + String(step.id);
    return '';
}

function _todoUpdateFromStep(todo, step) {
    if (!todo || !step) return;
    // Normalize provider terminal labels before updating the visual todo.
    // The stream may say completed while the local todo model uses done.
    const rawStepStatus = String(step.status || '').trim().toLowerCase();
    const stepStatus = _isTerminalToolStatus(rawStepStatus)
        ? 'done'
        : _isFailedToolStatus(rawStepStatus)
            ? 'error'
            : _isInFlightToolStatus(rawStepStatus)
                ? 'pending'
                : rawStepStatus;
    // UNFOLD: if the todo was folded (e.g. by a previous response)
    // and a new tool step arrives (e.g. quality review retry),
    // unfold it so the user can see the retry progress.
    if (step.type === 'tool' && todo.root && todo.root.classList.contains('folded')) {
        todo.root.classList.remove('folded');
        const list = todo.root.querySelector('.chat-todo-list');
        if (list) list.classList.remove('collapsed');
        todo.root.querySelector('.chat-todo-caret').textContent = '▼';
        // Cancel any pending hide timer
        if (todo.root._hideTimer) { clearTimeout(todo.root._hideTimer); todo.root._hideTimer = null; }
        // Re-show the dock
        const dock = document.getElementById('chatTodoDock');
        if (dock) { dock.style.display = ''; todo.root.style.opacity = ''; }
    }
    // FILTER: skip runtime plumbing steps. The user complained that
    // internal LLM runtime trace rows ("receive user request /
    // Multi-Agent Router / Crystallized Skill / Experience Recall /
    // LLM Call 1") cluttered the todo list. These are already shown
    // in the (folded) thinking chain, which is the right home for
    // them. The todo list should only show
    // REAL business workflow steps (ctv_segmentation, oar_segmentation,
    // planning_pipeline, etc.) so the user sees a clean "what's happening
    // in the workflow" view, not a stream of every internal agent call.
    const isBusinessStep = (
        (step.type === 'tool' && step.tool) ||
        // Specific assistant-level events that ARE workflow milestones:
        step.type === 'assistant'
    );
    if (!isBusinessStep) return null;
    if (!step.title && !step.tool) return null;

    // 1. Try to match a pre-seeded item by tool name (for tool steps).
    //    We try the predicted slot FIRST so the new event updates the
    //    predicted <li> in place (not appending a new line to the
    //    bottom). _todoFindPredicted matches status === 'predicted' —
    //    once a predicted item has been activated, we fall through
    //    to the dedup check below to find the same item by tool name.
    // 0. CTV+OAR are kept as SEPARATE todo items (no merge).
    //    Merging caused timing issues when CTV done + OAR pending
    //    arrived in the same SSE batch — the merged item would show
    //    incorrect states. Separate items give clear per-tool status.

    let item = _todoFindPredicted(todo, step);
    // 2. Try by id (for re-emission of the same step)
    if (!item && step.id != null) {
        item = todo.items.find(i => i.id === String(step.id));
    }
    // 2b. Stable milestone identity (scoped to this turn's dock, so different
    //     requests never merge). The server step, the client-synthesised
    //     final row, a replayed event and a restored snapshot can carry
    //     different ids but the same phase; update one row instead of
    //     appending a duplicate.
    if (!item && !step.tool) {
        const milestoneKey = _todoStepIdentity(step);
        if (milestoneKey) {
            item = todo.items.find(i => i.milestoneKey === milestoneKey);
        }
    }

    // 3. DEDUP BY TOOL NAME: if this tool is already represented in
    //    the todo (predicted, active, or done), update it in place.
    if (!item && step.tool) {
        const existing = todo.items.find(i => {
            if (i.predicted && i.predictedTool === step.tool) return true;
            if (i.step && i.step.tool === step.tool) return true;
            if (i.toolName && i.toolName === step.tool) return true;
            return false;
        });
        if (existing) {
            // Keep the latest server step attached to the row. This is
            // important for a seeded-ready placeholder: its pre-completed
            // state came from the old viewer snapshot, while this event is
            // the authoritative state for the current turn.
            existing.step = step;
            existing.toolName = existing.toolName || step.tool;
            existing._operationName = existing._operationName || _brachyOperationName(step.tool);
            if (stepStatus === 'pending' && existing._seededReady) {
                todo.reopenSeeded(existing);
                return existing;
            }
            if (stepStatus === 'done') {
                todo.markDone(existing);
            } else if (stepStatus === 'pending') {
                todo.markActive(existing);
            } else if (stepStatus === 'error') {
                // Predicted items are commonly matched here. An error or
                // clarification event must terminate their active timer;
                // otherwise the row keeps breathing forever after the
                // backend has already stopped the workflow.
                todo.markDone(existing, step.requires_input ? 'User input required' : (step.error || 'failed'));
            }
            return existing;
        }
    }
    // 4. Create a new item if no match
    if (!item) {
        item = todo.addPending(step);
    }
    if (item && step.tool) {
        item.step = step;
        item.toolName = item.toolName || step.tool;
        item._operationName = item._operationName || _brachyOperationName(step.tool);
    }
    if (item && !step.tool) {
        if (!item.milestoneKey) item.milestoneKey = _todoStepIdentity(step) || null;
        // Keep the milestone label in sync with the authoritative step (the
        // server localizes the final-response title after the client row).
        const nextLabel = _todoLabelForStep(step);
        if (nextLabel && nextLabel !== item.label && item.node) {
            item.label = nextLabel;
            const labelEl = item.node.querySelector && item.node.querySelector('.chat-todo-label');
            if (labelEl) labelEl.textContent = nextLabel;
        }
    }
    if (item && stepStatus === 'pending' && item._seededReady) {
        todo.reopenSeeded(item);
        return item;
    }
    // Extract real execution time from backend content.
    // The backend includes "elapsed_ms=1234" in done event content so
    // the frontend can display the ACTUAL wall-clock time instead of
    // measuring network delay between SSE events.
    if (step.content && stepStatus === 'done') {
        const emMatch = step.content.match(/elapsed_ms=(\d+)/);
        if (emMatch) item._realElapsedMs = parseInt(emMatch[1]);
    }
    if (stepStatus === 'pending') {
        todo.markActive(item);
    } else if (stepStatus === 'done') {
        // If item is still 'predicted' (never went through 'pending'),
        // force it through 'active' first so the user sees the breathing
        // animation before the ✓ appears. Without this, predicted→done
        // happens in one frame and the user sees "CTV executing + OAR done"
        // because OAR never visually became "active".
        if (item.status === 'predicted') {
            todo.markActive(item);
            // Minimum 250ms visible active state before marking done
            setTimeout(() => {
                if (item.status === 'active') todo.markDone(item);
            }, 250);
        } else {
            todo.markDone(item);
        }
    } else if (stepStatus === 'error') {
        todo.markDone(item, step.requires_input ? 'User input required' : (step.error || 'failed'));
    }
    return item;
}

// Pre-populate the todo with predicted workflow steps BEFORE the SSE
// stream starts emitting events. The user complained they "had no idea
// what was going to happen next" — without this, the list grows
// incrementally as events arrive and the user has no idea what's
// coming. We seed a known 5-step planning pipeline up front. As real
// step events arrive, _todoUpdateFromStep finds the matching predicted
// entry (by tool name) and updates its status. New events that don't
// match any prediction
// are appended as they come.
//
// Order matches the agent's documented workflow in
// config/prompts/system_prompt.md §"Phase 4: ACT".
// The 5-step predicted pipeline. Labels are language-aware — we
// read them from _TODO_I18n().tools at seed time. The
// `tool` field is the canonical key (matches the SSE step.tool);
// the `label` field is a fallback used only if the i18n dict
// is missing the tool entry.
function _planningTemplates() {
    const i18n = _todoI18n();
    // THREE core steps only. The 5 sub-steps of planning_pipeline
    // (trajectory_init/refine/seed_planning/dose_calc/dose_eval) are
    // emitted by the server via the step_callback side-channel and
    // appear in the dock as live events. We deliberately do NOT
    // predict `dose_evaluation` or `report_auto_fill` here: the LLM
    // does not call them as separate tools in the standard planning
    // flow (planning_pipeline's step=full covers dose_eval internally,
    // and report_auto_fill is only invoked when the user explicitly
    // asks for a report). Predicting them caused the user to see
    // them stuck in "predicted" forever in the dock (2026-06-16
    // bug: "11 steps, 9 done — the middle two never completed while
    // the later ones did").
    return [
        { tool: 'ctv_segmentation',  label: i18n.tools.ctv_segmentation,  predicted: true },
        { tool: 'oar_segmentation',  label: i18n.tools.oar_segmentation,  predicted: true },
        { tool: 'planning_pipeline', label: i18n.tools.planning_pipeline, predicted: true },
    ];
}
const PLANNING_PIPELINE_TEMPLATES = _planningTemplates();

function _todoSeed(todo, userMessage) {
    if (!todo) return;
    const text = (userMessage || '').toLowerCase();
    // Detect "full planning" requests
    const asksToExecute = /(?:请|帮我|立即|现在)?(?:执行|开始|运行|生成|制定|做一次|重新规划)|\b(?:run|execute|perform|generate|create|start|replan|plan)\b/i.test(text);
    const hasPlanningSubject = /放射性|粒子|植入|近距离|brachy|seed|tumou?r|planning|规划|胰|pancrea|前列|prostate|肝|liver|肺|lung|头颈|head|neck|妇科|gyne/i.test(text);
    const knowledgeOnly = /介绍|解释|好处|为什么|区别|比较|科普|原理|\b(?:what is|explain|benefit|why|compare|difference)\b/i.test(text);
    // A case description may mention a tumor site while the requested
    // action is only CTV/OAR segmentation. Do not let that site mention
    // create a fake pending planning stage in the Progress dock.
    const asksSegmentation = /\b(?:ctv|oar|segmentation|segment|mask)\b|[\u5206\u5272\u52fe\u753b\u63cf\u8ff0]/i.test(text);
    const asksPlanningAction = /\b(?:planning|plan|replan|brachytherapy|seed(?:s)?\s+implant|dose\s+plan|trajectory|needle)\b|[\u89c4\u5212\u7c92\u5b50\u690d\u5165\u8ba1\u5212\u5e03\u6e90\u9488\u9053\u5242\u91cf]/i.test(text);
    const segmentationOnly = asksSegmentation && !asksPlanningAction;
    const isFullPlan = asksToExecute && hasPlanningSubject && !knowledgeOnly && !segmentationOnly;
    if (isFullPlan) {
        // Re-read the templates on every seed call so the language
        // switch (zh → en mid-session) takes effect for the next
        // user message's todo list, not just the first one.
        for (const t of _planningTemplates()) {
            // Do not seed predicted items that already exist in the
            // todo list (e.g. restored from a previous session via
            // _caseTodos during task resume).  Duplicate predictions
            // produce the double "PROGRESS" dock the user reported.
            if (todo.items.some(i => i.toolName === t.tool || i.predictedTool === t.tool)) continue;
            // Add a placeholder item, marked as predicted (the LLM
            // may add the same tool later, in which case _todoUpdateFromStep
            // will find it by tool-name and update it).
            const li = document.createElement('li');
            li.className = 'chat-todo-item predicted';
            li.dataset.predictedTool = t.tool;
            const dot = document.createElement('span'); dot.className = 'chat-todo-dot';
            const lbl = document.createElement('span'); lbl.className = 'chat-todo-label'; lbl.textContent = t.label;
            const time = document.createElement('span'); time.className = 'chat-todo-time';
            li.appendChild(dot); li.appendChild(lbl); li.appendChild(time);
            todo.root.querySelector('.chat-todo-list').appendChild(li);
            const item = { id: 'pred-' + t.tool, label: t.label, status: 'predicted', startedAt: null, endedAt: null, node: li, predictedTool: t.tool, predicted: true };
            todo.items.push(item);
            // A replan reuses completed segmentation. Reflect that state in
            // the TODO list instead of pretending that CTV/OAR will run again.
            let uiSnapshot = {};
            try { uiSnapshot = (typeof collectUIState === 'function') ? collectUIState() : {}; } catch (_) {}
            const treeSnapshot = uiSnapshot.data_tree || {};
            const ctvReady = !!treeSnapshot.ctv_loaded;
            const oarReady = Number(treeSnapshot.oar_count || 0) > 0;
            if ((t.tool === 'ctv_segmentation' && ctvReady) ||
                (t.tool === 'oar_segmentation' && oarReady)) {
                todo.markDone(item);
                // This is a reusable-result hint only. A real pending event
                // for the current turn is allowed to reopen the row.
                item._seededReady = true;
            }
        }
        // Update count display
        const cnt = todo.root.querySelector('.chat-todo-count');
        if (cnt) cnt.textContent = '(0/' + todo.items.length + ')';
    }
}

// Find a predicted item by its tool name. Used by _todoUpdateFromStep
// to match incoming SSE step events to the pre-seeded list. We only
// match items that are still in 'predicted' status — once a predicted
// item has been activated, future events with the same tool name are
// internal sub-steps (e.g. planning_pipeline emits 5 sub-events) and
// should NOT create duplicate todo entries.
function _todoFindPredicted(todo, step) {
    if (!todo || !step) return null;
    const tool = (step.tool || '').toString();
    if (!tool) return null;
    const match = todo.items.find(i => i.predicted && i.predictedTool === tool && i.status === 'predicted');
    return match || null;
}

// Enter-to-send handler for #chatInput
// Command history for up/down arrow cycling (like a terminal)
let _chatHistory = [];
const _CHAT_HISTORY_LIMIT = 100;
let _chatHistoryIdx = -1;
let _chatHistoryDraft = '';
let _chatHistoryBrowsing = false;
const _chatHistoryBySession = Object.create(null);

// The composer is a textarea so that a prompt can contain multiple lines,
// but its height must follow the actual rendered content. The CSS values are
// the source of truth in the browser; the fallbacks keep this helper safe in
// lightweight DOM harnesses that do not implement getComputedStyle.
const CHAT_INPUT_MIN_HEIGHT_FALLBACK = 36;
const CHAT_INPUT_MAX_HEIGHT_FALLBACK = 136;

function _chatInputComputedPixels(input, property, fallback) {
    try {
        const getter = window && window.getComputedStyle;
        const style = typeof getter === 'function' ? getter(input) : null;
        const value = Number.parseFloat(style?.[property] || '');
        return Number.isFinite(value) && value > 0 ? value : fallback;
    } catch (_) {
        return fallback;
    }
}

function resizeChatInput(input) {
    const el = input || document.getElementById('chatInput');
    if (!el || !el.style) return 0;

    const minHeight = _chatInputComputedPixels(
        el,
        'minHeight',
        CHAT_INPUT_MIN_HEIGHT_FALLBACK,
    );
    const maxHeight = Math.max(
        minHeight,
        _chatInputComputedPixels(
            el,
            'maxHeight',
            CHAT_INPUT_MAX_HEIGHT_FALLBACK,
        ),
    );

    // Reset before measuring so deleting text immediately shrinks the
    // composer instead of retaining the previous long-prompt height.
    el.style.height = 'auto';
    el.style.overflowY = 'hidden';
    const naturalHeight = Math.max(Number(el.scrollHeight) || 0, minHeight);
    const targetHeight = Math.min(naturalHeight, maxHeight);
    el.style.height = targetHeight + 'px';
    el.style.overflowY = naturalHeight > maxHeight ? 'auto' : 'hidden';
    return targetHeight;
}

window.resizeChatInput = resizeChatInput;

function _initializeChatInputLayout() {
    try {
        resizeChatInput(document.getElementById('chatInput'));
    } catch (error) {
        console.debug('[chat] composer sizing deferred:', error);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initializeChatInputLayout, { once: true });
} else {
    _initializeChatInputLayout();
}

// Chat history is case-scoped.  The transcript is the durable source of
// truth, while this small cache only makes keyboard navigation responsive.
// Keeping it outside localStorage prevents a command from another case (or a
// stale browser tab) from appearing in the active case's input box.
function syncChatHistoryForSession(sessionId, messages) {
    const id = String(sessionId || '');
    if (!id) return;
    const entries = Array.isArray(messages)
        ? messages
            .filter(m => m && m.type === 'user' && typeof m.content === 'string')
            .map(m => m.content.trim())
            .filter(Boolean)
        : [];
    const unique = [];
    entries.forEach(value => {
        if (unique[unique.length - 1] !== value) unique.push(value);
    });
    _chatHistoryBySession[id] = unique.slice(-_CHAT_HISTORY_LIMIT);
    _chatHistory = _chatHistoryBySession[id].slice();
    _chatHistoryIdx = _chatHistory.length;
    _chatHistoryDraft = '';
    _chatHistoryBrowsing = false;
}

function _activeChatHistory() {
    const id = String(window.activeSessionId || activeSessionId || '');
    const session = (typeof sessions !== 'undefined' && id) ? sessions[id] : null;
    if (id && !_chatHistoryBySession[id]) syncChatHistoryForSession(id, session?.messages);
    return id ? (_chatHistoryBySession[id] || []) : _chatHistory;
}

function _rememberChatCommand(text) {
    const value = String(text || '').trim();
    if (!value) return;
    const id = String(window.activeSessionId || activeSessionId || '');
    const history = id ? (_chatHistoryBySession[id] || []) : _chatHistory;
    // Avoid duplicate adjacent entries, but preserve intentional repeated
    // questions separated by another command.
    if (history[history.length - 1] !== value) history.push(value);
    while (history.length > _CHAT_HISTORY_LIMIT) history.shift();
    if (id) _chatHistoryBySession[id] = history;
    _chatHistory = history.slice();
    _chatHistoryIdx = _chatHistory.length;
    _chatHistoryDraft = '';
    _chatHistoryBrowsing = false;
}

function handleChatKeypress(ev) {
    if (!ev) return;
    const input = document.getElementById('chatInput');
    if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        const text = (input ? input.value : '').trim();
        if (text) _rememberChatCommand(text);
        // Enter submits a new turn.  It must never share the Stop action:
        // while a task is active, the turn is queued for this case and the
        // explicit stop button remains the only user cancellation path.
        if (typeof sendChat === 'function') sendChat(undefined, { queueIfBusy: true });
    } else if (ev.key === 'ArrowUp' && input && !ev.altKey && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey) {
        // The composer can contain multiple lines; Up/Down remain dedicated
        // history navigation keys when no modifier is held.
        // Preserve a partially typed draft and restore it when moving past
        // the newest command, matching terminal-style agent UIs.
        ev.preventDefault();
        const history = _activeChatHistory();
        if (!_chatHistoryBrowsing) {
            _chatHistoryDraft = input.value;
            _chatHistoryIdx = history.length;
            _chatHistoryBrowsing = true;
        }
        if (_chatHistoryIdx > 0) {
            _chatHistoryIdx--;
            input.value = history[_chatHistoryIdx] || '';
        }
        resizeChatInput(input);
        input.setSelectionRange(input.value.length, input.value.length);
    } else if (ev.key === 'ArrowDown' && input && !ev.altKey && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey) {
        ev.preventDefault();
        const history = _activeChatHistory();
        if (!_chatHistoryBrowsing) {
            _chatHistoryIdx = history.length;
            _chatHistoryDraft = input.value;
            _chatHistoryBrowsing = true;
        }
        if (_chatHistoryIdx < history.length - 1) {
            _chatHistoryIdx++;
            input.value = history[_chatHistoryIdx] || '';
        } else {
            _chatHistoryIdx = history.length;
            input.value = _chatHistoryDraft;
            _chatHistoryBrowsing = false;
        }
        resizeChatInput(input);
        input.setSelectionRange(input.value.length, input.value.length);
    }
}

// Handle every user edit (typing, paste, IME composition commit, and newline
// insertion) through the same sizing path.
function handleChatInput(el) {
    const input = el || document.getElementById('chatInput');
    resizeChatInput(input);
    window.markChatInputDraft?.(input);
}

// `sendChat` is the user → /api/chat entry point. Previous versions of
// this file referenced it from onclick="sendChat()" but the function
// was missing. Minimal implementation:
//   1. Read & clear #chatInput
//   2. Echo the user message into the chat
//   3. POST to /api/chat (the agent loop) — IMPORTANT: we send
//      `stream: false` so the server returns plain JSON; otherwise it
//      streams SSE (`event: ... \ndata: ...`) and resp.json() throws
//      "Unexpected token 'e', 'event: sta'...".
//   4. Render the bot reply (the server returns the final text under
//      `response`; the legacy client also accepts `reply` / `message`).
// `sendChat` is the user → /api/chat entry point.
//
// Default behavior: stream SSE so the bot can render an *execution trace*
// (thinking chain) live as the agent works through tools, plus stream the
// final text response token-by-token. This is the same UX as upstream.
//
// If streaming isn't supported (server doesn't return text/event-stream,
// or `ReadableStream` API is missing), fall back to a single JSON call
// and render the final response.
const CHAT_CONNECT_TIMEOUT_MS = 30000;
// A report regeneration keeps capturing figures and flushing its durable save
// after the report itself is already on screen. The report UI owns that
// progress; the chat turn may wait only a bounded window for it before
// releasing the final reply.
// A server stream ending acknowledges dispatch, not browser-side completion.
async function _awaitChatUIActions(tasks, signal) {
    if (signal?.aborted) throw new DOMException('Stopped', 'AbortError');
    let abort;
    try {
        return await Promise.race([
            Promise.allSettled(tasks),
            new Promise((_, reject) => {
                abort = () => reject(new DOMException('Stopped', 'AbortError'));
                signal?.addEventListener('abort', abort, { once: true });
            }),
        ]);
    } finally {
        if (abort) signal?.removeEventListener('abort', abort);
    }
}
const CHAT_IDLE_TIMEOUT_MS = 90000;
// A known server-owned task is replayable and receives protocol heartbeats.
// Keep a long transport budget while the server still owns the task; a brief
// UI-state gap must not turn a live long-running tool into a false disconnect.
const CHAT_TASK_IDLE_TIMEOUT_MS = 1800000; // 30 min
const CHAT_PLANNING_IDLE_TIMEOUT_MS = 900000; // 15 min — medical planning tools can run 5-10 min
const CHAT_ABORT_TIMEOUT_MS = 4000;

// A browser may display a different case while this turn continues on the
// server.  Keep task ownership explicit so a later session switch can resume
// the correct event journal instead of treating the task as cancelled.
window._sessionChatTaskIds = window._sessionChatTaskIds || {};
window._sessionChatTaskStatuses = window._sessionChatTaskStatuses || {};
window._detachedChatTasks = window._detachedChatTasks || {};
window._sessionChatQueues = window._sessionChatQueues || {};
window._activeChatTaskSessionId = window._activeChatTaskSessionId || null;
window._activeChatInternalFollowup = !!window._activeChatInternalFollowup;
window._explicitChatStopSessions = window._explicitChatStopSessions || {};
// Stop has two phases: aborting this tab's SSE stream and receiving the
// server acknowledgement that the case-owned task is terminal. Keep that
// acknowledgement per case so a new user turn cannot inherit an old aborted
// controller while its cleanup is still in flight.
window._sessionChatStopPromises = window._sessionChatStopPromises || {};
window._sessionChatRecoveryTimers = window._sessionChatRecoveryTimers || {};
window._sessionChatRecoveryNotices = window._sessionChatRecoveryNotices || {};
window._chatTurnGeneration = Number(window._chatTurnGeneration || 0);
window._activeChatTurnGeneration = Number(window._activeChatTurnGeneration || 0);
window._sessionPlanningRefreshTimers = window._sessionPlanningRefreshTimers || {};
window._chatSessionReadinessSubmission = window._chatSessionReadinessSubmission || null;

function _setChatSessionReadinessUi(active, language = '') {
    const input = document.getElementById('chatInput');
    const button = document.getElementById('chatSendBtn');
    const zh = language === 'zh'
        || (typeof detectConversationLanguage === 'function'
            && detectConversationLanguage(input?.value || '') === 'zh');
    document.body.classList.toggle('chat-session-awaiting', !!active);
    if (input) {
        if (active) {
            input.dataset.readinessReadonly = input.readOnly ? '1' : '0';
            input.dataset.readinessPlaceholder = input.placeholder || '';
            input.readOnly = true;
            input.placeholder = zh ? '正在创建会话…' : 'Creating case...';
        } else {
            input.readOnly = input.dataset.readinessReadonly === '1';
            if (Object.prototype.hasOwnProperty.call(input.dataset, 'readinessPlaceholder')) {
                input.placeholder = input.dataset.readinessPlaceholder;
            }
            delete input.dataset.readinessReadonly;
            delete input.dataset.readinessPlaceholder;
        }
    }
    if (button) {
        // The send control can be replaced while the chat panel is restored.
        // Keep the readiness state on whichever concrete element is active,
        // while also supporting lightweight DOM implementations used by the
        // runtime regression harness.
        const buttonState = button.dataset || (button.dataset = {});
        if (active) {
            if (!Object.prototype.hasOwnProperty.call(buttonState, 'readinessDisabled')) {
                buttonState.readinessDisabled = button.disabled ? '1' : '0';
            }
            button.disabled = true;
        } else {
            button.disabled = buttonState.readinessDisabled === '1';
            delete buttonState.readinessDisabled;
        }
        button.classList.toggle('session-awaiting', !!active);
        if (active) button.title = zh ? '正在创建会话' : 'Creating case';
        else if (!button.classList.contains('streaming')) button.title = zh ? '发送' : 'Send';
    }
}

async function _submitWhenSessionReady(text, opts, input) {
    const normalized = String(text || '').trim();
    if (!normalized) return false;
    const existing = window._chatSessionReadinessSubmission;
    if (existing) {
        // Repeated Enter/click events during the same transition represent
        // one user intent. Reuse the existing promise instead of creating a
        // second user bubble, request ID, task, or pending Execution Trace.
        return existing.promise;
    }
    const language = typeof detectConversationLanguage === 'function'
        ? detectConversationLanguage(normalized)
        : '';
    if (input) {
        input.value = '';
        resizeChatInput(input);
    }
    _setChatSessionReadinessUi(true, language);
    const record = { text: normalized, promise: null };
    record.promise = (async () => {
        try {
            const sessionId = await window.awaitActiveSessionReady();
            if (!sessionId) throw new Error('No active case is available.');
        } catch (error) {
            if (input && !input.value) {
                input.value = normalized;
                resizeChatInput(input);
            }
            const zh = language === 'zh';
            const message = zh
                ? `新会话尚未创建成功，消息未发送：${error?.message || '未知错误'}`
                : `The new case could not be created, so the message was not sent: ${error?.message || 'Unknown error'}`;
            if (typeof addChat === 'function' && activeSessionId && sessions?.[activeSessionId]) {
                addChat('error', message, true, Date.now(), false, activeSessionId);
            }
            return false;
        } finally {
            if (window._chatSessionReadinessSubmission === record) {
                window._chatSessionReadinessSubmission = null;
                _setChatSessionReadinessUi(false, language);
            }
        }
        return sendChat(normalized, Object.assign({}, opts, {
            sessionReadinessResolved: true,
        }));
    })();
    window._chatSessionReadinessSubmission = record;
    return record.promise;
}

function _setCaseTaskState(sessionId, status, taskId = undefined) {
    const key = String(sessionId || '');
    if (!key) return;
    window._sessionChatTaskStatuses[key] = status || 'idle';
    if (taskId !== undefined) {
        if (taskId) window._sessionChatTaskIds[key] = taskId;
        else delete window._sessionChatTaskIds[key];
    }
}

// True when the browser tracked an actually-in-flight task for this case.
// The status map is restored from the workspace snapshot (chat.task_status),
// so after a server restart it reflects the last persisted task state rather
// than assuming every old task was running.
function _hadInFlightTask(sessionId) {
    const key = String(sessionId || '');
    if (window._sessionChatTaskStatuses?.[key] === 'running') return true;
    // Fall back to the workspace snapshot status when present.
    const saved = window._activeWorkspaceSnapshot?.chat?.task_status;
    if (saved === 'running') return true;
    return false;
}

function _isContinuationRequest(value) {
    const text = String(value || '').trim().toLowerCase();
    if (!text) return false;
    return /^(?:\u7ee7\u7eed|\u7ee7\u7eed\u6267\u884c|\u7ee7\u7eed\u89c4\u5212|\u6062\u590d\u4efb\u52a1|\u6062\u590d\u89c4\u5212|continue|resume|resume task|resume planning|continue planning)$/.test(text);
}

function _taskContinuationMessage(sessionId, key) {
    const chinese = _chatLanguageForSession(sessionId) === 'zh';
    const messages = {
        reconnecting: chinese
            ? '\u6b63\u5728\u6062\u590d\u4e0a\u4e00\u4e2a\u672a\u5b8c\u6210\u7684\u4efb\u52a1\uff0c\u5c06\u7ee7\u7eed\u663e\u793a\u539f\u6709\u6267\u884c\u8fdb\u5ea6\u3002'
            : 'The previous unfinished task is being resumed. Its original progress will continue here.',
        completed: chinese
            ? '\u4e0a\u4e00\u4e2a\u4efb\u52a1\u5df2\u5b8c\u6210\uff0c\u6211\u5df2\u52a0\u8f7d\u6700\u65b0\u7ed3\u679c\u3002'
            : 'The previous task has already completed. The latest saved results have been loaded.',
        unavailable: chinese
            ? '\u4e0a\u4e00\u4e2a\u4efb\u52a1\u5df2\u4e0d\u5728\u670d\u52a1\u5668\u4e2d\u8fd0\u884c\uff08\u4f8b\u5982\u670d\u52a1\u5668\u91cd\u542f\u540e\uff09\u3002\u5df2\u4fdd\u7559\u5df2\u4fdd\u5b58\u7684\u75c5\u4f8b\u6570\u636e\uff0c\u8bf7\u91cd\u65b0\u6267\u884c\u672a\u5b8c\u6210\u7684\u6b65\u9aa4\u3002'
            : 'The previous task is no longer running on the server, possibly after a restart. Saved case data is retained; rerun the unfinished step.',
        running: chinese
            ? '\u4e0a\u4e00\u4e2a\u4efb\u52a1\u4ecd\u5728\u8fd0\u884c\u4e2d\uff0c\u6b63\u5728\u6062\u590d\u5176\u5b9e\u65f6\u8fdb\u5ea6\u3002'
            : 'The previous task is still running. Its live progress is being restored.',
        none: chinese
            ? '\u5f53\u524d\u6ca1\u6709\u53ef\u6062\u590d\u7684\u672a\u5b8c\u6210\u4efb\u52a1\u3002'
            : 'There is no unfinished task available to resume for this case.',
    };
    return messages[key] || messages.none;
}

window._isContinuationRequest = _isContinuationRequest;

function _chatLanguageForSession(sessionId) {
    return (typeof conversationLanguageForSession === 'function'
        ? conversationLanguageForSession(sessionId)
        : window._i18nLang) === 'zh' ? 'zh' : 'en';
}

function _chatUserVisibleFailure(sessionId, kind = 'request', code = '') {
    // Server error payloads can contain internal tool output, file paths, or
    // upstream provider text. Keep those details in the browser console and
    // show the user one concise, request-language explanation instead.
    const zh = _chatLanguageForSession(sessionId) === 'zh';
    // Server failures are classified. Explain the real cause instead of
    // blaming "session still loading" for every failed turn.
    const codeMessages = {
        workspace_hydration_failed: [
            '病例资源加载失败。请重新打开该病例后重试；如反复失败，请检查服务端日志。',
            'Case resources failed to load. Reopen the case and retry; if it keeps failing, check the server log.',
        ],
        workspace_hydration_timeout: [
            '病例资源加载时间过长，本次请求已暂停。资源可能仍在后台加载，请稍后重试。',
            'Case resources are taking too long to load, so this request was paused. They may still be loading in the background; retry shortly.',
        ],
        workspace_hydration_cancelled: [
            '病例资源加载被中断（病例可能已切换或更新）。请重试。',
            'Case resource loading was interrupted (the case may have switched or refreshed). Please retry.',
        ],
        commit_failed: [
            '回答已生成，但保存到病例失败。请重试。',
            'The answer was generated but could not be saved to the case. Please retry.',
        ],
        chat_task_running: [
            '当前病例已有请求正在执行。请等待完成，或点击停止后重试。',
            'Another request is already running for this case. Wait for it to finish, or stop it and retry.',
        ],
    };
    if (code && codeMessages[code]) {
        const pair = codeMessages[code];
        return zh ? pair[0] : pair[1];
    }
    const messages = {
        request: [
            '本次请求暂时无法完成。请稍后重试；如果刚切换或加载 Session，请等待加载完成后再试。',
            'This request could not be completed right now. Retry shortly; if the Session was just switched or loaded, wait for loading to finish first.',
        ],
        content: [
            '当前 Session 中的请求内容暂时无法呈现。请确认该 Session 已完成加载后重试。',
            'The requested content cannot be presented from the current Session yet. Confirm that the Session has finished loading, then retry.',
        ],
        response: [
            '本次请求未获得可验证的回复。请稍后重试。',
            'No verified response was returned for this request. Please retry shortly.',
        ],
    };
    const pair = messages[kind] || messages.request;
    return zh ? pair[0] : pair[1];
}

function _chatWorkspaceLockedMessage(sessionId) {
    // A workspace lease conflict is a different failure from a timeout or a
    // broken provider. Explaining it lets the operator close the other
    // browser or use the takeover action instead of retrying blindly.
    const zh = _chatLanguageForSession(sessionId) === 'zh';
    return zh
        ? '该病例正在另一个浏览器中编辑。请关闭另一个浏览器中的这个病例，或使用页面上的「接管编辑权」后重试。'
        : 'This case is being edited in another browser. Close it in the other browser, or use the on-page "Take over editing" action, then retry.';
}

function _visualAnalysisUnavailableMessage(sessionId, responseLanguage = '') {
    const language = String(responseLanguage || _chatLanguageForSession(sessionId) || '').toLowerCase();
    return language.startsWith('zh')
        ? '截图已生成，但当前图像解读暂时不可用；图片仍保留在原回复中。'
        : 'The screenshot was captured, but visual analysis is temporarily unavailable. The image remains attached to the original reply.';
}

function _visualEvidenceTargetTerms(attachment) {
    const metadata = attachment?.view_metadata || attachment?.viewMetadata || {};
    const manifest = metadata.grounding_manifest || metadata.groundingManifest
        || attachment?.grounding_manifest || attachment?.groundingManifest || {};
    const targets = Array.isArray(manifest.targets) ? manifest.targets : [];
    const values = [
        attachment?.title,
        attachment?.label,
        metadata.title,
        metadata.label,
        attachment?.target,
        attachment?.semantic_target,
        ...(Array.isArray(attachment?.semantic_targets) ? attachment.semantic_targets : []),
        attachment?.target_query,
        metadata.semantic_target,
        ...(Array.isArray(metadata.semantic_targets) ? metadata.semantic_targets : []),
        metadata.target_query,
        ...targets.flatMap(target => [
            target?.label,
            target?.target_ref || target?.targetRef,
        ]),
    ].map(value => String(value || '').trim().toLowerCase()).filter(Boolean);
    const terms = new Set();
    values.forEach(value => {
        terms.add(value);
        value.split(/[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+/i)
            .filter(term => term.length >= 2)
            .forEach(term => terms.add(term));
        // A localized label may be longer than the phrase used by the model
        // (for example "手术导板位置" vs "手术导板"). Generate only
        // short CJK n-grams from the live manifest, never a user-phrase list.
        const cjkRuns = value.match(/[\u3400-\u4dbf\u4e00-\u9fff]{2,}/g) || [];
        cjkRuns.forEach(run => {
            const chars = [...run];
            for (let width = 2; width <= Math.min(6, chars.length); width += 1) {
                for (let start = 0; start + width <= chars.length; start += 1) {
                    terms.add(chars.slice(start, start + width).join(''));
                }
            }
        });
    });
    return [...terms].filter(term => term.length >= 2);
}

function _visualResponseHasGroundedLocationClaim(value, evidence = []) {
    const clean = String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    if (!clean) return false;
    // View names such as "Viewer/Data Tree" are capture metadata, not a
    // location claim. Require a spatial/lifecycle assertion and a term that
    // refers to one of the targets in this capture manifest. This catches
    // provider acknowledgements without maintaining a brittle canned-reply
    // blacklist.
    const spatialSignal = /(?:位置|定位|位于|标注|圈出|框出|方框|箭头|指向|显示在|可见于|隐藏|加载|生成|过期|左侧|右侧|上方|下方|中央|节点|按钮|对象|导板|location|located|marked|annotat(?:ed|ion)|boxed|box|arrow|point(?:s|ing)?|visible|hidden|loaded|generated|stale|left|right|above|below|inside|under|row|node|button|object|target)/i.test(clean);
    if (!spatialSignal) return false;
    const terms = (Array.isArray(evidence) ? evidence : [])
        .flatMap(item => _visualEvidenceTargetTerms(item))
        .filter(term => term.length >= 2);
    return terms.some(term => clean.includes(term));
}

// Build a useful, state-grounded answer when a visual child returns no
// protocol envelope (for example after a provider timeout or an older
// deployment returns plain text).  This is deliberately derived from the
// capture manifest and the server state carried by each attachment; it is not
// a list of recognized user phrases or a guessed pixel location.
function _visualEvidenceFallbackResponse(evidence, sessionId, responseLanguage = '', userText = '', preliminaryResponse = '') {
    const language = String(
        responseLanguage || _chatLanguageForSession(sessionId) || window._responseLanguage || ''
    ).toLowerCase();
    const zh = language.startsWith('zh');
    const appendPreliminary = answer => {
        const raw = String(preliminaryResponse || '').trim();
        if (!raw) return answer;
        const visualHeading = /(?:对象截图\s*[\/／]\s*位置|截图位置|对象定位|object screenshot|screenshot location)/i;
        const placeholder = /(?:没有建立与该目标对应的截图任务|本轮没有取得.*截图|没有取得.*对应截图|no screenshot task|did not receive.*screenshot|could not establish.*screenshot)/i;
        // Model prose may use Markdown headings, bold headings, or plain paragraphs.
        // Filter visual-only blocks and stale placeholder sentences independent of style.
        const blocks = raw.split(/\n\s*\n+/);
        const retained = [];
        blocks.forEach(block => {
            if (visualHeading.test(block)) return;
            block.split(/(?<=[。！？!?])\s*|(?<=\.)\s+|\r?\n/)
                .map(sentence => sentence.trim())
                .filter(sentence => sentence && !placeholder.test(sentence))
                .forEach(sentence => retained.push(sentence));
        });
        const retainedText = retained.join('\n').trim();
        return retainedText ? retainedText + '\n\n' + answer : answer;
    };
    const items = (Array.isArray(evidence) ? evidence : [])
        .filter(item => item && item.url)
        .slice(0, 4);
    if (!items.length) return _visualAnalysisUnavailableMessage(sessionId, responseLanguage);

    const targetLabel = target => {
        const key = String(target || '').toLowerCase();
        return ({
            'viewer-3d': zh ? '3D Viewer' : '3D Viewer',
            'viewer-axial': zh ? '轴位 Viewer' : 'axial Viewer',
            'viewer-sagittal': zh ? '矢状位 Viewer' : 'sagittal Viewer',
            'viewer-coronal': zh ? '冠状位 Viewer' : 'coronal Viewer',
            'data-tree': zh ? 'Data Tree' : 'Data Tree',
            'overlay-controls': zh ? 'Viewer 工具栏' : 'Viewer toolbar',
            'dvh': zh ? 'DVH 查看器' : 'DVH viewer',
        }[key] || (zh ? '当前界面' : 'current interface'));
    };
    const semanticLabel = value => {
        const key = String(value || '').toLowerCase();
        return ({
            surgical_guide: zh ? '手术导板' : 'surgical guide',
            ctv: zh ? '肿瘤（CTV）' : 'tumor (CTV)',
            oar: zh ? '危及器官' : 'OAR',
            seeds: zh ? '粒子' : 'seeds',
            needles: zh ? '针道' : 'needles',
            trajectories: zh ? '针道轨迹' : 'trajectories',
        }[key] || (zh ? '目标对象' : 'target object'));
    };
    const groups = new Map();
    const looseRows = [];
    items.forEach((attachment, attachmentIndex) => {
        const metadata = attachment.view_metadata || attachment.viewMetadata || {};
        const manifest = metadata.grounding_manifest || metadata.groundingManifest
            || attachment.grounding_manifest || attachment.groundingManifest || {};
        const targets = Array.isArray(manifest.targets) ? manifest.targets : [];
        const annotationRefs = new Set((Array.isArray(attachment.annotation?.marks)
            ? attachment.annotation.marks : [])
            .map(mark => String(mark?.target_ref || mark?.targetRef || '').trim())
            .filter(Boolean));
        const view = String(attachment.target || metadata.target || '').toLowerCase();
        const viewName = targetLabel(view);
        if (!targets.length) {
            looseRows.push(zh
                ? viewName + '：截图已附，但当前证据没有解析出可对应的目标对象。'
                : viewName + ': the screenshot is attached, but its evidence does not identify a matching target.');
            return;
        }
        targets.forEach((target, targetIndex) => {
            const ref = String(target?.target_ref || target?.targetRef || '').trim();
            const label = String(target?.label || metadata.title || attachment.title || '')
                .replace(/\s+/g, ' ').trim()
                || semanticLabel(metadata.semantic_target || metadata.semanticTarget);
            const key = ref || ('unbound:' + String(attachment.id || attachmentIndex) + ':' + targetIndex);
            if (!groups.has(key)) {
                groups.set(key, {
                    ref,
                    label,
                    views: new Map(),
                    stale: false,
                    temporaryReveal: false,
                    temporaryCamera: false,
                    appearancePreserved: false,
                    treeHidden: false,
                    treeVisibilityUnknown: false,
                });
            }
            const group = groups.get(key);
            if (!group.label || group.label === '目标对象') group.label = label;
            const inView = target?.in_view === true || target?.inView === true;
            const isTree = view === 'data-tree';
            const is3D = view === 'viewer-3d' || view === 'viewer';
            const valid = target?.visible === true && inView && target?.annotatable === true
                && (!is3D || (target?.scene_visible === true
                    && target?.data_tree_visible === true && target?.loaded !== false));
            const onlyTarget = targets.length === 1;
            const annotated = (ref && annotationRefs.has(ref))
                || (onlyTarget && !!(attachment.annotated_url || attachment.annotatedUrl
                    || attachment.annotation?.count > 0));
            const row = {
                view,
                viewName,
                valid: !!valid,
                annotated: !!annotated,
                status: String(target?.status || '').toLowerCase(),
                sceneVisible: target?.scene_visible,
                sceneVisibilityKnown: target?.scene_visibility_known === true
                    || target?.sceneVisibilityKnown === true,
                reason: String(target?.reason || '').toLowerCase(),
            };
            const previous = group.views.get(view);
            if (!previous || (!previous.annotated && row.annotated) || (!previous.valid && row.valid)) {
                group.views.set(view, row);
            }
            if (row.status === 'stale' || row.status === 'expired' || row.status === 'outdated') {
                group.stale = true;
            }
            group.temporaryReveal = group.temporaryReveal || metadata.temporary_reveal === true;
            group.temporaryCamera = group.temporaryCamera
                || metadata.temporary_camera_reframe === true;
            group.appearancePreserved = group.appearancePreserved
                || metadata.appearance_preserved === true;
            if (isTree && target?.scene_visible === false) {
                if (row.sceneVisibilityKnown) group.treeHidden = true;
                else group.treeVisibilityUnknown = true;
            }
        });
    });

    const rows = [];
    let markedCount = 0;
    const labels = [];
    groups.forEach(group => {
        const label = group.label || semanticLabel('');
        if (!labels.includes(label)) labels.push(label);
        const entries = [...group.views.values()];
        const viewerEntries = entries.filter(item => item.view.startsWith('viewer'));
        const treeEntry = group.views.get('data-tree');
        const annotatedViewer = viewerEntries.some(item => item.valid && item.annotated);
        if (annotatedViewer) markedCount += 1;

        if (treeEntry) {
            rows.push(treeEntry.valid
                ? (zh ? 'Data Tree：已核验到“' + label + '”对应的数据树节点。'
                    : 'Data Tree: verified the row for “' + label + '”.')
                : (zh ? 'Data Tree：截图已附，但未能核验“' + label + '”对应的可见节点。'
                    : 'Data Tree: the screenshot is attached, but the row for “' + label + '” was not verified.'));
        }
        if (viewerEntries.length) {
            viewerEntries.forEach(item => {
                if (item.valid && item.annotated) {
                    rows.push(zh
                        ? item.viewName + '：对应截图已核验，并已标出“' + label + '”的位置。'
                        : item.viewName + ': the corresponding screenshot verifies and marks “' + label + '”.');
                } else if (item.valid) {
                    rows.push(zh
                        ? item.viewName + '：截图中核验到“' + label + '”，但标注未确认；我不据此猜测具体位置。'
                        : item.viewName + ': “' + label + '” is verified in the screenshot, but a mark was not confirmed, so I will not guess its exact location.');
                } else {
                    rows.push(zh
                        ? item.viewName + '：本次截图未能核验“' + label + '”的位置，因此不作位置推断。'
                        : item.viewName + ': this capture did not verify the location of “' + label + '”, so no location is inferred.');
                }
            });
        } else if (treeEntry) {
            rows.push(zh
                ? '3D Viewer：本轮没有取得同一对象可核验的截图，不能据此说明三维位置。'
                : '3D Viewer: no verifiable screenshot of the same object was obtained, so its 3D location cannot be stated.');
        }
        if (group.treeHidden) {
            rows.push(group.temporaryReveal && viewerEntries.some(item => item.valid)
                ? (zh ? 'Data Tree 截图时该对象原处于隐藏状态；为本次 Viewer 截图临时显示，完成后已恢复。'
                    : 'The object was hidden in the Data Tree capture, then temporarily shown for the Viewer capture and restored afterwards.')
                : (zh ? 'Data Tree 截图时该对象的三维显示处于隐藏状态。'
                    : 'The object’s 3D presentation was hidden when the Data Tree was captured.'));
        } else if (group.treeVisibilityUnknown && treeEntry) {
            rows.push(zh
                ? '仅凭 Data Tree 截图无法核验该对象当时的三维显示状态。'
                : 'The Data Tree capture alone could not verify the object’s 3D visibility state.');
        } else if (group.temporaryReveal) {
            rows.push(zh ? '为本次截图临时显示了目标对象，截图完成后已恢复。'
                : 'The target was temporarily shown for this capture and restored afterwards.');
        }
        if (group.temporaryCamera) {
            rows.push(zh ? '为使目标完整入镜，临时调整了相机取景，截图后已恢复原视角。'
                : 'The camera was temporarily reframed to fit the target and restored after capture.');
        }
        if (group.stale) {
            rows.push(zh ? '该对象状态标记为过期（stale）；截图只能证明当前画面中的对象，不能代表最新规划结果。'
                : 'This object is marked stale; the capture shows the current displayed object, not necessarily the latest plan.');
        }
        if (group.appearancePreserved && !group.temporaryReveal && !group.temporaryCamera) {
            rows.push(zh ? '截图沿用了 Viewer 当时的显示内容和配色，没有为定位单独隐藏周边对象或改色。'
                : 'The screenshot preserves the Viewer’s displayed scene and colors; surrounding objects were not hidden or recolored for locating.');
        }
    });

    const requestHint = String(userText || '').trim();
    const subject = labels.length ? labels.join(zh ? '、' : ', ')
        : (requestHint ? (zh ? '所请求的对象' : 'the requested object') : (zh ? '当前界面' : 'the current interface'));
    const intro = zh
        ? '我按你的要求分别核对了' + subject + '，对应截图已附在下方；下面只说明截图中能够核实的内容。'
        : 'I checked ' + subject + ' separately as requested. The corresponding screenshots are attached below; I only describe what they verify.';
    const body = intro + (rows.length || looseRows.length
        ? '\n\n' + [...rows, ...looseRows].map(row => '- ' + row).join('\n')
        : '');
    const locate = items.some(item => String(
        item.visual_purpose || item.visualPurpose
        || item.view_metadata?.visual_purpose || item.viewMetadata?.visualPurpose || ''
    ).toLowerCase() === 'locate');
    const safeBody = locate && markedCount === 0 && rows.length === 0
        ? (zh ? '本轮截图没有提供可核验的目标位置，我不会根据不对应的画面作判断。'
            : 'These captures do not verify the requested location, so I will not infer it from unrelated imagery.')
            + (looseRows.length ? '\n\n' + looseRows.map(row => '- ' + row).join('\n') : '')
        : body;
    return appendPreliminary(safeBody);
}
function _visualResponseNeedsGroundedFallback(value, evidence = []) {
    // Location is a verifiable identity/state question, not an invitation to
    // improvise anatomy from similarly colored pixels. Use the grounded
    // renderer even when plausible model prose happens to mention the label.
    if ((Array.isArray(evidence) ? evidence : []).some(item => {
        const meta = item?.view_metadata || item?.viewMetadata || {};
        const purpose = item?.visual_purpose || meta.visual_purpose;
        const manifest = item?.grounding_manifest || meta.grounding_manifest || {};
        return purpose === 'locate' || (manifest.targets || []).some(target =>
            target.visible === false || target.annotatable === false);
    })) return true;
    const clean = String(value || '').replace(/\s+/g, ' ').trim();
    if (!clean || /^(?:\(no reply\)|\(No validated response\)|Tools executed\. Check the execution trace above for results\.)$/i.test(clean)) {
        return true;
    }
    // A response that only acknowledges capture/attachment has no answer for
    // the user. Detect this by semantic information content (capture terms
    // without a view, target, state, or spatial claim), not by matching one
    // exact canned sentence.
    const captureOnly = /(?:截图|证据|附件|screenshot|evidence|attached|image)/i.test(clean)
        && !/(?:位置|定位|标注|方框|箭头|可见|隐藏|加载|导板|数据树|查看器|对象|显示|图中|where|located|marked|visible|hidden|loaded|viewer|data tree|object|target|shows)/i.test(clean);
    if (captureOnly) return true;
    const locateEvidence = (Array.isArray(evidence) ? evidence : []).some(item => String(
        item?.visual_purpose || item?.visualPurpose
        || item?.view_metadata?.visual_purpose || item?.viewMetadata?.visualPurpose || ''
    ).toLowerCase() === 'locate');
    if (locateEvidence && !_visualResponseHasGroundedLocationClaim(clean, evidence)) {
        return true;
    }
    if (clean.length < 48 && Array.isArray(evidence) && evidence.length
        && !/(?:位置|定位|标注|方框|箭头|可见|隐藏|加载|显示|图中|where|location|located|marked|visible|hidden|loaded|viewer|data tree|object|target|shows|contains|curve|dose|剂量|曲线)/i.test(clean)) {
        return true;
    }
    return false;
}

async function _presentJsonSessionContent(steps, sessionId, turnIdentity) {
    const commands = (Array.isArray(steps) ? steps : [])
        .filter(step => step && step.tool === 'ui_content')
        .map(step => ({
            id: String(step.id || ''),
            command: step.metadata?.content_command || step.content_command || null,
        }))
        .filter(item => item.command && typeof item.command === 'object');
    if (!commands.length) return { attachments: [], userMessage: '' };

    const gallery = {
        sessionId: String(sessionId || ''),
        requestId: String(turnIdentity?.requestId || ''),
        messageId: String(turnIdentity?.messageId || ''),
        responseLanguage: String(turnIdentity?.responseLanguage || _chatLanguageForSession(sessionId)),
        mode: 'chat',
        layout: 'auto',
        items: [],
        keys: new Set(),
    };
    const seen = new Set();
    const attachments = [];
    const messages = [];
    for (const item of commands) {
        const commandKey = item.id || JSON.stringify([
            item.command.target,
            item.command.planning_id,
            item.command.presentation,
            item.command.object_ids || [],
        ]);
        if (seen.has(commandKey)) continue;
        seen.add(commandKey);
        let result;
        try {
            result = typeof window.presentSessionContent === 'function'
                ? await window.presentSessionContent(item.command, gallery, {
                    sessionId,
                    requestId: gallery.requestId,
                    messageId: gallery.messageId,
                    responseLanguage: gallery.responseLanguage,
                })
                : {
                    success: false,
                    userMessage: _chatUserVisibleFailure(sessionId, 'content'),
                    attachments: [],
                };
        } catch (error) {
            console.warn('[chat] JSON Session content presentation failed', error);
            result = {
                success: false,
                userMessage: _chatUserVisibleFailure(sessionId, 'content'),
                attachments: [],
            };
        }
        if (Array.isArray(result?.attachments)) {
            attachments.push(...result.attachments.map(attachment => Object.assign({}, attachment, {
                // ``analysis`` belongs to the structured ui_content
                // contract. Preserve it on every attachment instead of
                // relying on a transport-specific capture flag.
                visual_analysis: attachment?.visual_analysis === true || result.analysis === true,
            })));
        }
        if (result?.userMessage) messages.push(String(result.userMessage));
    }
    return {
        attachments,
        userMessage: messages.filter(Boolean).slice(-1)[0] || '',
    };
}

async function _captureJsonScreenshotSteps(steps, question, turnIdentity, sessionId) {
    const commands = (Array.isArray(steps) ? steps : [])
        .filter(step => step && step.tool === 'ui_screenshot'
            && _isTerminalToolStatus(step.status))
        .map(step => {
            const metadata = step.metadata || step.data?.metadata || {};
            const command = metadata.screenshot_command || metadata;
            const plan = metadata.screenshot_plan || command.plan || null;
            return { step, command, plan };
        })
        .filter(item => item.plan || item.command);
    if (!commands.length) return { attachments: [], userMessage: '' };

    const gallery = {
        sessionId: String(sessionId || ''),
        requestId: String(turnIdentity?.requestId || ''),
        messageId: String(turnIdentity?.messageId || ''),
        responseLanguage: String(turnIdentity?.responseLanguage || _chatLanguageForSession(sessionId)),
        mode: 'chat',
        layout: 'auto',
        items: [],
        keys: new Set(),
    };
    const attachments = [];
    const messages = [];
    const seen = new Set();
    for (const item of commands) {
        const plan = item.plan || {};
        const command = item.command || {};
        const requestText = String(plan.question || command.question || question || '');
        const target = String(
            plan.views?.[0]?.target
            || command.target
            || _normalizeScreenshotRequestTarget('full', requestText)
        );
        const key = String(item.step.id || JSON.stringify([target, requestText, plan.views || []]));
        if (seen.has(key)) continue;
        seen.add(key);
        try {
            const result = await _interceptScreenshot(
                target,
                requestText,
                gallery,
                {
                    sessionId,
                    requestId: gallery.requestId,
                    messageId: gallery.messageId,
                    responseLanguage: gallery.responseLanguage,
                    mode: plan.mode || 'chat',
                    plan: Object.assign({ mode: 'chat', question: requestText }, plan),
                },
            );
            if (Array.isArray(result?.attachments)) attachments.push(...result.attachments);
            else if (result?.success && result?.url) attachments.push(result);
            if (result?.userMessage) messages.push(String(result.userMessage));
        } catch (error) {
            console.warn('[chat] JSON screenshot capture failed', error);
            messages.push(_chatUserVisibleFailure(sessionId, 'screenshot'));
        }
    }
    return {
        attachments,
        userMessage: messages.filter(Boolean).slice(-1)[0] || '',
    };
}

async function _executeJsonUIActions(steps, sessionId) {
    const actionGroups = (Array.isArray(steps) ? steps : [])
        .filter(step => step && step.tool === 'ui_controller' && _isTerminalToolStatus(step.status))
        .map(step => step.metadata?.actions || step.data?.actions || [])
        .filter(actions => Array.isArray(actions) && actions.length > 0);
    const results = [];
    for (const actions of actionGroups) {
        const group = typeof _executeUIActionsWithProgress === 'function'
            ? await _executeUIActionsWithProgress(actions, { sessionId })
            : await Promise.all(actions.map(action => _executeUIAction(action, { sessionId })));
        results.push(...(Array.isArray(group) ? group : [group]));
    }
    return {
        executed: results.length,
        failed: results.some(result => result === false
            || result?.success === false
            || result?.stale === true),
    };
}

function _hasReportGenerationAction(steps) {
    return (Array.isArray(steps) ? steps : []).some(step => {
        if (!step || step.tool !== 'ui_controller') return false;
        const actions = step.metadata?.actions || step.data?.actions || [];
        return Array.isArray(actions)
            && actions.some(action => String(action?.target || '') === 'report.autofill');
    });
}

function _reportGenerationFailureMessage(sessionId, failure = null) {
    const chinese = _chatLanguageForSession(sessionId) === 'zh';
    const stage = String(failure?.stage || '').trim();
    if (stage === 'report_scene_not_ready'
        || stage === 'report_catalog_not_ready'
        || stage === 'workspace_visual_restore_incomplete'
        || stage === 'report_validation_failed') {
        return chinese
            ? '报告截图未完成：当前病例的 Viewer 或剂量证据尚未准备好，原有报告图片已保留；请确认规划、剂量和 DVH 加载完成后重试。'
            : 'Report screenshots were not completed because the current Viewer or dose evidence is not ready. Previous report figures were retained; retry after planning, dose, and DVH finish loading.';
    }
    if (stage === 'report_planning_in_progress') {
        return chinese
            ? '报告未重新生成：当前规划仍在计算，系统没有开始截图，原有报告图片已保留；请等待规划完成后重试。'
            : 'Report regeneration did not start because the active Planning is still running. Previous report figures were retained; retry after planning finishes.';
    }
    if (stage === 'report_planning_changed') {
        return chinese
            ? '报告未重新生成：操作期间当前规划版本发生变化，原有报告图片已保留；请保持当前病例和规划不变后重试。'
            : 'Report regeneration was stopped because the active Planning changed during the operation. Previous report figures were retained; keep the case and Planning unchanged and retry.';
    }
    return chinese
        ? '报告重新生成未完成。浏览器中的报告内容可能已经更新，但系统没有确认它已保存到当前 Session，因此不能把本次操作报告为成功。当前病例显示内容已保留；请保持该病例不变，确认规划、剂量和 DVH 已加载后重试。'
        : 'Report regeneration was not confirmed. The report may have been updated in the browser, but it was not confirmed as saved to the current Session, so this operation cannot be reported as successful. The visible case was preserved; keep it selected and retry after planning, dose, and DVH are loaded.';
}

function _addTaskRecoveryNotice(sessionId, taskId, state) {
    const key = `${String(sessionId || '')}:${String(taskId || '')}:${state}`;
    if (!key || window._sessionChatRecoveryNotices[key]) return;
    window._sessionChatRecoveryNotices[key] = true;
    const chinese = _chatLanguageForSession(sessionId) === 'zh';
    const messages = {
        reconnecting: chinese
            ? '连接中断，正在重连并恢复这个任务的实时进度…'
            : 'Connection interrupted. Reconnecting to restore this task\'s live progress...',
        unavailable: chinese
            ? '服务端不再运行该任务（可能是服务重启或任务已终止）。已保存的病例数据会保留，请重新运行未完成的步骤。'
            : 'The server is no longer running this task, possibly after a server restart or task termination. Saved case data is retained; please rerun the unfinished step.',
    };
    if (typeof addChat === 'function') {
        const messageId = `task-recovery-${String(taskId || 'unknown')}-${String(state || 'notice')}`;
        const existing = sessions?.[String(sessionId || '')]?.messages;
        const alreadyPersisted = Array.isArray(existing)
            && existing.some(message => String(message?.id || '') === messageId
                || (message?.meta?.recoveryNotice === true
                    && String(message?.meta?.recoveryTaskId || '') === String(taskId || '')
                    && String(message?.meta?.recoveryState || '') === String(state || '')));
        if (!alreadyPersisted) {
            addChat(state === 'unavailable' ? 'error' : 'system', messages[state], true, Date.now(), false, sessionId, {
                messageId,
                messageKind: 'task_recovery_notice',
                recoveryNotice: true,
                recoveryTaskId: String(taskId || ''),
                recoveryState: String(state || ''),
            });
        }
        // The transcript is the durable/actionable surface for a chat task;
        // close the separate recovery fallback immediately. This does not
        // touch the case-resource hydration notice.
        window.hideWorkspaceRecoveryNotice?.({
            sessionId,
            persist: true,
            reason: 'chat_task_recovery_message',
        });
    }
}

function _scheduleCasePlanningRefresh(sessionId, delay = 250) {
    const key = String(sessionId || '');
    if (!key || typeof refreshPlanningUI !== 'function') return false;
    if (window._sessionPlanningRefreshTimers[key]) return false;
    window._sessionPlanningRefreshAttempts = window._sessionPlanningRefreshAttempts || {};
    window._sessionPlanningRefreshTimers[key] = setTimeout(async () => {
        delete window._sessionPlanningRefreshTimers[key];
        if (String(activeSessionId || '') !== key) return;
        let outcome = null;
        try {
            // This is the single terminal planning refresh. Intermediate
            // dose events use a separate viewer-only refresh and are never
            // allowed to enter report capture.
            outcome = await refreshPlanningUI({
                sessionId: key,
                autoGenerateGuide: true,
                retryPending: true,
                requireCompletedPlanning: true,
                captureReportFigures: true,
            });
        } catch (error) {
            console.error('[SSE] refreshPlanningUI failed:', error);
            outcome = {
                success: false,
                stage: 'refresh_exception',
                planningStatus: '',
                reportCaptureReady: false,
            };
        }
        if (String(activeSessionId || '') !== key) return;
        const planningStatus = String(outcome?.planningStatus || '').trim().toLowerCase();
        const attempt = Number(window._sessionPlanningRefreshAttempts[key] || 0);
        const terminalReady = planningStatus === 'completed'
            && outcome?.reportCaptureReady === true;
        const retryable = (
            !planningStatus
            || planningStatus === 'running'
            || planningStatus === 'pending'
            || planningStatus === 'queued'
            || planningStatus === 'draft'
            || planningStatus === 'in_progress'
            || outcome?.stage === 'planning_in_progress'
            || outcome?.stage === 'planning_results_http'
            || outcome?.stage === 'refresh_exception'
            || (planningStatus === 'completed' && !terminalReady)
        );
        if (terminalReady) {
            delete window._sessionPlanningRefreshAttempts[key];
            try {
                if (window.state) window.state.lastPlanTimestamp = new Date().toISOString();
            } catch (_) {}
            window.dispatchEvent(new CustomEvent('brachybot:planning-run-finished', {
                detail: {
                    sessionId: key,
                    planningId: outcome?.planningId || null,
                    requestId: window.__brachybotReportPlanningLifecycle?.requestId || '',
                    planningStatus,
                    reportCaptureReady: true,
                },
            }));
            return;
        }
        // Planning runs in this environment regularly publish dose and DVH
        // many minutes after the run starts. The old ~2.5 minute budget
        // expired first, the capture gate never saw a ready planning, and
        // reports silently shipped without figures. Keep retrying for a
        // realistic window; the request itself is a cheap control-plane GET.
        if (retryable && attempt < 400) {
            window._sessionPlanningRefreshAttempts[key] = attempt + 1;
            _scheduleCasePlanningRefresh(
                key,
                Math.min(2500, 250 + (attempt + 1) * 25),
            );
            return;
        }
        // A failed/cancelled run must release the lifecycle lock too, but it
        // must never be treated as a valid report-capture boundary.
        delete window._sessionPlanningRefreshAttempts[key];
        window.dispatchEvent(new CustomEvent('brachybot:planning-run-finished', {
            detail: {
                sessionId: key,
                planningId: outcome?.planningId || null,
                requestId: window.__brachybotReportPlanningLifecycle?.requestId || '',
                planningStatus: planningStatus || null,
                reportCaptureReady: false,
                incomplete: true,
                stage: outcome?.stage || 'planning_refresh_incomplete',
            },
        }));
    }, Math.max(0, Number(delay) || 0));
    return true;
}

// A surgical guide is a persisted planning artifact, not a new Planning run.
// Keep its browser hydration separate from the planning refresh above: the
// latter deliberately invalidates dose presentation when a new run starts,
// while generating a guide must leave the already-validated dose untouched.
// The chat tool path also bypasses the manual HTTP button, so without this
// case-owned fetch the server can truthfully report a generated guide while
// the Data Tree and Viewer continue to show the previous scene.
function _scheduleCaseSurgicalGuideRefresh(sessionId, delay = 0) {
    const key = String(sessionId || '');
    if (!key || String(activeSessionId || '') !== key) return false;
    if (typeof window.loadSurgicalGuideMesh !== 'function'
        && typeof refreshPlanningUI !== 'function') return false;
    window._sessionSurgicalGuideRefreshTimers = window._sessionSurgicalGuideRefreshTimers || {};
    if (window._sessionSurgicalGuideRefreshTimers[key]) return false;
    window._sessionSurgicalGuideRefreshTimers[key] = setTimeout(async () => {
        delete window._sessionSurgicalGuideRefreshTimers[key];
        if (String(activeSessionId || '') !== key) return;
        try {
            let loaded = false;
            // `/surgical-guides/mesh` is the authoritative mesh transport. It
            // also applies the guide metadata and registers the Data Tree node;
            // do not send the potentially very large vertex array through the
            // chat trace itself.
            if (typeof window.loadSurgicalGuideMesh === 'function') {
                loaded = await window.loadSurgicalGuideMesh({
                    sessionId: key,
                    userInitiated: false,
                    reconcileProgress: true,
                });
            }
            // A short publication race can make the mesh request observe the
            // old alias even though the tool has already yielded its terminal
            // event. A bounded case refresh retries the same durable source
            // without auto-generating a second guide or touching report state.
            if (!loaded && typeof refreshPlanningUI === 'function'
                && String(activeSessionId || '') === key) {
                await refreshPlanningUI({
                    sessionId: key,
                    retryPending: true,
                    autoGenerateGuide: false,
                    preserveViewerState: true,
                    switchToViewers: false,
                    preserveReport: true,
                    reason: 'surgical-guide-tool-complete',
                });
                // Some restore paths apply the guide mesh inside
                // refreshPlanningUI rather than returning it from the direct
                // mesh request.  Reconcile only when the authoritative scene
                // or Data Tree now contains the guide; never manufacture a
                // completion row for a failed/missing result.
                const guidePresent = Boolean(
                    window.scene3D?.meshes?.patient_specific_puncture_guide
                    || window.dataTreeState?.planning?.meshes?.some(item =>
                        String(item?.id || '') === 'patient_specific_puncture_guide'),
                );
                if (guidePresent && typeof window.reconcileManualWorkflowProgress === 'function') {
                    window.reconcileManualWorkflowProgress(
                        'surgical_guide_generate',
                        'done',
                        typeof window._t === 'function'
                            ? window._t('导板已加载', 'Guide loaded')
                            : 'Guide loaded',
                        key,
                    );
                }
            }
        } catch (error) {
            console.error('[SSE] surgical guide hydration failed:', error);
        }
    }, Math.max(0, Number(delay) || 0));
    return true;
}

function _waitForFinalReplyPaint() {
    return new Promise(resolve => {
        let settled = false;
        let fallbackTimer = null;
        let visibilityHandler = null;
        const finish = () => {
            if (settled) return;
            settled = true;
            if (fallbackTimer !== null) clearTimeout(fallbackTimer);
            if (visibilityHandler && typeof document !== 'undefined'
                && typeof document.removeEventListener === 'function') {
                document.removeEventListener('visibilitychange', visibilityHandler);
            }
            resolve();
        };

        // requestAnimationFrame can be suspended indefinitely in a hidden or
        // throttled tab. Painting is only a presentation hint, never part of
        // the turn's completion contract, so release the lifecycle immediately
        // when the page is hidden.
        if (typeof document !== 'undefined') {
            if (document.visibilityState === 'hidden') {
                finish();
                return;
            }
            if (typeof document.addEventListener === 'function') {
                visibilityHandler = () => {
                    if (document.visibilityState === 'hidden') finish();
                };
                document.addEventListener('visibilitychange', visibilityHandler);
            }
        }
        if (typeof requestAnimationFrame !== 'function') {
            finish();
            return;
        }

        // A missed animation frame must not keep the send button, turn lock,
        // or Final Response trace pending forever. Keep the normal paint path
        // when available, with a short hard deadline as a safety boundary.
        fallbackTimer = setTimeout(finish, 750);
        try {
            requestAnimationFrame(() => {
                if (typeof document !== 'undefined'
                    && document.visibilityState === 'hidden') {
                    finish();
                    return;
                }
                setTimeout(finish, 0);
            });
        } catch (_) {
            finish();
        }
    });
}

function _sessionChatQueue(sessionId) {
    const key = String(sessionId || '');
    if (!key) return [];
    window._sessionChatQueues = window._sessionChatQueues || {};
    if (!Array.isArray(window._sessionChatQueues[key])) window._sessionChatQueues[key] = [];
    return window._sessionChatQueues[key];
}

// Queued turns are a transport/UI state, not yet part of the conversation.
// Keep them in their own bottom dock until the active turn reaches a terminal
// event.  Rendering a queued prompt into #chatMessages used to insert a new
// user bubble in front of the live trace, overwrite _lastUserMessage, and
// make the progress animation appear to jump backwards.
function _renderQueuedChatTurns(sessionId = activeSessionId) {
    if (typeof document === 'undefined') return;
    const dock = document.getElementById('chatQueueDock');
    if (!dock) return;
    const owner = String(sessionId || '');
    const selected = owner && owner === String(activeSessionId || '');
    const queue = selected ? _sessionChatQueue(owner) : [];
    if (!queue.length) {
        dock.hidden = true;
        dock.style.display = 'none';
        dock.replaceChildren?.();
        return;
    }
    const zh = String(window._i18nLang || '').toLowerCase().startsWith('zh');
    const escape = value => typeof escHtml === 'function'
        ? escHtml(value)
        : String(value || '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    const countLabel = zh ? `排队中 · ${queue.length}` : `Queued · ${queue.length}`;
    const waitLabel = zh ? '等待当前请求完成' : 'Waiting for the current request to finish';
    const rows = queue.map((item, index) => {
        const text = String(item?.text || '');
        const ordinal = index + 1;
        return `<div class="chat-queue-item" data-queue-id="${escape(item?.id || '')}">
            <span class="chat-queue-spinner" aria-hidden="true"></span>
            <span class="chat-queue-index">${ordinal}</span>
            <span class="chat-queue-text" title="${escape(text)}">${escape(text)}</span>
            <span class="chat-queue-state">${escape(waitLabel)}</span>
        </div>`;
    }).join('');
    dock.hidden = false;
    dock.style.display = '';
    dock.innerHTML = `<div class="chat-queue-header"><span>${escape(countLabel)}</span><span class="chat-queue-hint">${escape(zh ? '发送顺序保持不变' : 'Order is preserved')}</span></div>${rows}`;
}
window.renderQueuedChatTurns = _renderQueuedChatTurns;

function _queueChatTurn(sessionId, message) {
    const text = String(message || '').trim();
    if (!sessionId || !text) return false;
    _sessionChatQueue(sessionId).push({
        id: `queued-${String(sessionId)}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        text,
        queuedAt: Date.now(),
    });
    _renderQueuedChatTurns(sessionId);
    if (typeof window.scheduleWorkspaceSave === 'function') window.scheduleWorkspaceSave('chat.turn_queued');
    return true;
}

let _queuedChatFlushRunning = false;
async function _flushQueuedChatTurns() {
    const sessionId = activeSessionId;
    if (!sessionId || _queuedChatFlushRunning || window._chatTurnActive || window._chatStreaming) return;
    const queue = _sessionChatQueue(sessionId);
    if (!queue.length) return;
    const next = queue.shift();
    // A session switch can happen between the idle check and this dispatch.
    // Never send a queued prompt into the newly selected case; put it back and
    // let the session painter render that case's own queue.
    if (String(activeSessionId || '') !== String(sessionId)) {
        queue.unshift(next);
        _renderQueuedChatTurns(activeSessionId);
        return;
    }
    _renderQueuedChatTurns(sessionId);
    if (typeof window.scheduleWorkspaceSave === 'function') window.scheduleWorkspaceSave('chat.turn_dequeued');
    _queuedChatFlushRunning = true;
    try {
        await sendChat(next.text, {
            queuedTurn: true,
        });
    } finally {
        _queuedChatFlushRunning = false;
        if (activeSessionId === sessionId && _sessionChatQueue(sessionId).length) {
            setTimeout(() => { try { _flushQueuedChatTurns(); } catch (_) {} }, 0);
        }
    }
}
window.flushQueuedChatTurns = _flushQueuedChatTurns;

function _buildTurnMeta(identity = {}) {
    const llmMeta = window._lastLLMMeta || null;
    const toolCount = (window._todoTurnToolCount !== undefined)
        ? window._todoTurnToolCount
        : ((llmMeta && llmMeta.llm_calls) || 0);
    const startTime = window._chatTurnStartTime || null;
    // Calculate elapsed time client-side — this is the real wall-clock
    // time from the "Send" click to the response delivery.  For session
    // restore the persisted value lets the footer show the original time.
    const elapsedMs = startTime ? (Date.now() - startTime) : 0;
    const elapsedSec = elapsedMs > 0 ? (elapsedMs / 1000).toFixed(1) : null;
    return {
        llmMeta: llmMeta ? {
            usage: llmMeta.usage || {},
            latency_ms: llmMeta.latency_ms || 0,
            llm_calls: llmMeta.llm_calls || 0,
        } : null,
        toolCount,
        elapsedSec,
        savedAt: Date.now(),
        requestId: String(identity.requestId || identity.request_id || ''),
        messageId: String(identity.messageId || identity.message_id || ''),
        messageKind: String(identity.messageKind || identity.message_kind || 'assistant_final'),
        // Persist the semantic position inside a turn. This is the primary
        // ordering contract for refresh/reconnect; the renderer does not need
        // to infer Trace placement from write timing or title whitelists.
        turnSequence: Number.isFinite(Number(identity.turnSequence ?? identity.turn_sequence))
            ? Number(identity.turnSequence ?? identity.turn_sequence)
            : (String(identity.messageKind || identity.message_kind || 'assistant_final') === 'execution_trace' ? 1 : 2),
        replyToMessageId: String(identity.replyToMessageId || identity.reply_to_message_id || ''),
        attachments: Array.isArray(identity.attachments) ? identity.attachments : [],
        screenshotLayout: identity.screenshotLayout || identity.layout || 'auto',
        responseLanguage: identity.responseLanguage || window._responseLanguage || '',
        traceLanguage: identity.traceLanguage
            || identity.trace_language
            || identity.responseLanguage
            || window._responseLanguage
            || '',
    };
}

function readChatChunk(reader, timeoutMs = CHAT_IDLE_TIMEOUT_MS, onTimeout = null) {
    let timer = null;
    return new Promise((resolve, reject) => {
        timer = setTimeout(() => {
            // Close the underlying request as well as the local read promise.
            // Otherwise a stalled SSE stream could keep a server-side planning
            // task alive after the UI has already shown an error.
            try { if (typeof onTimeout === 'function') onTimeout(); } catch (_) {}
            reject(new Error('Chat stream timed out while waiting for the next event.'));
        }, timeoutMs);
        reader.read().then(resolve, reject).finally(() => clearTimeout(timer));
    });
}

function _isCurrentTurnSession(turnSessionId) {
    if (activeSessionId !== turnSessionId) return;
    return true;
}

function _isMonitorStartRequest(text) {
    return /(?:monitor|training|coach|guide|supervise|watch|observe|培训|训练|监测|监督|指导|教我|带我)/i.test(text || '')
        && !/(?:stop|finish|end|停止|结束|关闭)/i.test(text || '');
}

function _isMonitorStopRequest(text) {
    return /(?:stop|finish|end|summary|停止|结束|关闭|总结|完成监测|停止监测)/i.test(text || '')
        && /(?:monitor|training|coach|培训|训练|监测|监督|指导)/i.test(text || '');
}

// Tool providers use both "done" and "completed" for the same terminal
// event. UI tools are browser-side effects, so treating the latter as a
// non-terminal event silently drops the real action while the model can still
// produce a plausible acknowledgement. Keep this protocol normalization in
// one place and use it for every browser-side tool completion boundary.
function _isTerminalToolStatus(status) {
    return new Set(['done', 'completed', 'success', 'succeeded', 'ready'])
        .has(String(status || '').trim().toLowerCase());
}

function _isFailedToolStatus(status) {
    return new Set(['error', 'failed', 'failure', 'cancelled', 'canceled', 'stopped'])
        .has(String(status || '').trim().toLowerCase());
}

// Different providers and server paths use slightly different labels for
// an operation that has not reached a terminal state yet. The execution
// trace may display these as "pending"/"waiting"; the todo dock must treat
// all of them as active work rather than silently leaving a pre-completed
// row crossed out.
const _IN_FLIGHT_TOOL_STATUSES = new Set([
    'pending', 'active', 'queued', 'running', 'waiting',
    'processing', 'in_progress', 'optimizing', 'generating',
    'loading', 'restoring',
]);
function _isInFlightToolStatus(status) {
    return _IN_FLIGHT_TOOL_STATUSES.has(String(status || '').trim().toLowerCase());
}

window._pendingHiddenChats = window._pendingHiddenChats || [];
window._hiddenChatFlushRunning = false;

function _isFinalResponseTraceStep(step) {
    if (!step || typeof step !== 'object') return false;
    const phase = String(step.phase || step.metadata?.phase || '')
        .trim().toLowerCase().replace(/[\s-]+/g, '_');
    if (phase === 'final_response') return true;
    const title = String(step.title || '').trim().toLowerCase();
    return title === 'final response'
        || title === 'final answer'
        || title === '最终回复'
        || title === '最终响应';
}

function _finalResponseTraceContent(status, language = '', supplied = '') {
    if (supplied) return String(supplied);
    const zh = String(language || '').toLowerCase().startsWith('zh');
    if (status === 'pending') {
        return zh ? '等待最终回复完成' : 'Waiting for the final response to finish';
    }
    if (status === 'done') return zh ? '回复已完成' : 'Response delivered';
    if (status === 'cancelled') return zh ? '最终回复已取消' : 'Final response cancelled';
    return zh ? '最终回复未能完成' : 'Final response did not complete';
}

function _setFinalResponseTraceStep(step, status, language = '', content = '') {
    if (!step || typeof step !== 'object') return false;
    step.phase = 'final_response';
    step.status = status;
    step.content = _finalResponseTraceContent(status, language, content);
    return true;
}

function _ensureFinalResponseTraceStep(
    steps,
    deferredSteps,
    requestId,
    language = '',
    stepsDiv = null,
    headerEl = null,
    reportPending = false,
) {
    if (!Array.isArray(steps)) return null;
    let step = null;
    for (let index = steps.length - 1; index >= 0; index -= 1) {
        if (_isFinalResponseTraceStep(steps[index])) {
            step = steps[index];
            break;
        }
    }
    if (!step) {
        step = {
            id: 'client-final-response-' + String(requestId || Date.now()),
            type: 'assistant',
            phase: 'final_response',
            title: 'Final Response',
            status: 'pending',
        };
        steps.push(step);
    }
    if (Array.isArray(deferredSteps)
        && !deferredSteps.some(item => item === step || (
            item && step.id && String(item.id) === String(step.id)
        ))) {
        deferredSteps.push(step);
    }
    const waiting = reportPending
        ? (String(language || '').toLowerCase().startsWith('zh')
            ? '等待报告截图、显示恢复和保存完成'
            : 'Waiting for report capture, viewer restore and save')
        : '';
    _setFinalResponseTraceStep(step, 'pending', language, waiting);
    const index = steps.indexOf(step);
    if (stepsDiv && typeof appendStepToChain === 'function') {
        appendStepToChain(stepsDiv, step, Math.max(0, index));
    }
    if (headerEl && typeof updateChainHeader === 'function') {
        updateChainHeader(headerEl, steps);
    }
    const liveTrace = window._brachyLiveTrace;
    if (liveTrace?.steps === steps && typeof liveTrace.getTodo === 'function') {
        const todo = liveTrace.getTodo();
        if (todo && typeof _todoUpdateFromStep === 'function') {
            _todoUpdateFromStep(todo, step);
        }
    }
    return step;
}

function _pendingVisualFinalResponseMap() {
    const map = window._pendingVisualFinalResponses;
    if (!map || typeof map.get !== 'function' || typeof map.set !== 'function') {
        window._pendingVisualFinalResponses = new Map();
    }
    return window._pendingVisualFinalResponses;
}

function _visualFinalResponseKey(sessionId, requestId) {
    return JSON.stringify([String(sessionId || ''), String(requestId || '')]);
}

function _registerPendingVisualFinalResponse(record) {
    if (!record || !record.sessionId || !record.requestId || !record.step) return false;
    const key = _visualFinalResponseKey(record.sessionId, record.requestId);
    _setFinalResponseTraceStep(
        record.step,
        'pending',
        record.responseLanguage,
        String(record.responseLanguage || '').toLowerCase().startsWith('zh')
            ? '等待截图分析完成'
            : 'Waiting for screenshot analysis',
    );
    _pendingVisualFinalResponseMap().set(key, Object.assign({}, record, { key }));
    _refreshFinalResponseTrace(record, false);
    return true;
}

function _refreshFinalResponseTrace(record, persist = false) {
    if (!record || !record.step) return;
    const steps = Array.isArray(record.steps) ? record.steps : [];
    const stepIndex = steps.indexOf(record.step);
    if (String(activeSessionId || '') === String(record.sessionId || '')
        && record.stepsDiv && stepIndex >= 0
        && typeof appendStepToChain === 'function') {
        appendStepToChain(record.stepsDiv, record.step, stepIndex);
        if (record.headerEl && typeof updateChainHeader === 'function') {
            updateChainHeader(record.headerEl, steps);
        }
    }
    if (record.todo && typeof _todoUpdateFromStep === 'function') {
        _todoUpdateFromStep(record.todo, record.step);
    }
    if (persist && typeof saveSessionMessage === 'function') {
        saveSessionMessage('thinking', '', steps, Date.now(), record.sessionId, {
            requestId: record.requestId,
            messageId: 'trace-' + record.requestId,
            messageKind: 'execution_trace',
            turnSequence: 1,
            replyToMessageId: record.assistantMessageId,
            responseLanguage: record.responseLanguage,
            traceLanguage: record.responseLanguage,
        });
    }
}

function _settlePendingVisualFinalResponse(sessionId, requestId, status, content = '') {
    const key = _visualFinalResponseKey(sessionId, requestId);
    const registry = _pendingVisualFinalResponseMap();
    const record = registry.get(key);
    if (!record) return false;
    const terminalStatus = ['done', 'error', 'cancelled'].includes(String(status || ''))
        ? String(status) : 'error';
    _setFinalResponseTraceStep(
        record.step,
        terminalStatus,
        record.responseLanguage,
        content,
    );
    _refreshFinalResponseTrace(record, true);
    registry.delete(key);
    return true;
}

function _finishFinalResponseTraceSteps(
    steps,
    deferredSteps,
    status,
    language,
    content,
    stepsDiv = null,
    headerEl = null,
    sessionId = '',
) {
    const targets = Array.isArray(deferredSteps) ? deferredSteps : [];
    targets.forEach(step => _setFinalResponseTraceStep(step, status, language, content));
    const liveTrace = window._brachyLiveTrace;
    if (liveTrace?.steps === steps && typeof liveTrace.getTodo === 'function') {
        const todo = liveTrace.getTodo();
        if (todo && typeof _todoUpdateFromStep === 'function') {
            targets.forEach(step => _todoUpdateFromStep(todo, step));
        }
    }
    if ((!sessionId || String(activeSessionId || '') === String(sessionId))
        && stepsDiv && typeof appendStepToChain === 'function') {
        targets.forEach(step => {
            const index = Array.isArray(steps) ? steps.indexOf(step) : -1;
            if (index >= 0) appendStepToChain(stepsDiv, step, index);
        });
        if (headerEl && typeof updateChainHeader === 'function') {
            updateChainHeader(headerEl, steps);
        }
    }
}


function _isScreenshotAckResponse(
    text,
    steps,
    visualContentResults = [],
    responseContract = null,
    userRequest = '',
) {
    if (!Array.isArray(steps) || !steps.length) return false;
    const toolSteps = steps.filter(step => step && step.type === 'tool' && step.tool);
    if (!toolSteps.length) return false;
    if (toolSteps.some(step => !['ui_screenshot', 'ui_content'].includes(step.tool))) return false;
    if (toolSteps.some(step => step.status === 'error')) return false;
    // The server attaches a turn-level contract to the authoritative response
    // event. A visible question/mixed request must never be reduced to an
    // attachment-only message, even when the browser also starts a hidden
    // visual-analysis continuation.
    if (responseContract && responseContract.text_required === true) return false;
    const normalized = String(text || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const transportOnly = !normalized || /^(?:requested screenshot|the screenshot plan|screenshot requested|tools executed|requested ui content|截图计划|已请求截图|已准备截图|正在生成截图)/i.test(normalized);
    if (!transportOnly) return false;
    // Legacy responses may not carry a contract. Preserve explanatory text
    // for a question-shaped request rather than relying on an answer phrase
    // whitelist. Commands can still use the historical attachment-only UX.
    if (!responseContract && /(?:[?？]\s*$|(?:吗|呢|是不是|是否|为什么|为何|哪里|哪儿|怎么|如何|什么|哪个|哪些|多少)|\b(?:what|which|where|when|why|who|how|whether|can|could|is|are)\b)/i.test(String(userRequest || '').trim())) {
        return false;
    }
    // A persisted visual attachment follows the same two-stage protocol as a
    // live screenshot: the first response only confirms that evidence was
    // collected, and the hidden child supplies the actual interpretation.
    // Never hide a substantive answer from a mixed clinical/tool turn.
    return toolSteps.some(step => step.tool === 'ui_screenshot')
        || (Array.isArray(visualContentResults) && visualContentResults.length > 0);
}

function _normalizeScreenshotRequestTarget(target, question) {
    const rawTarget = String(target || 'full');
    const text = String(question || '').toLowerCase();
    const genericDoseZh = /(?:\u5242\u91cf\u5206\u5e03|\u5242\u91cf\u4e91\u56fe)/i.test(text)
        && !/(?:\u4ec5\u8f74\u5411|\u53ea\u770b\u8f74\u5411|\u8f74\u5411\u89c6\u56fe)/i.test(text);
    if (rawTarget === 'viewer-axial' && genericDoseZh) return 'dose-overview';
    const genericDose = rawTarget === 'viewer-axial'
        && /(?:dose distribution|dose map|dose cloud|剂量分布|剂量云图)/i.test(text)
        && !/(?:axial only|only axial|仅轴向|只看轴向|轴向视图)/i.test(text);
    return genericDose ? 'dose-overview' : rawTarget;
}

function _enqueueHiddenChat(message, options) {
    const safeMessage = String(message || '').trim();
    if (!safeMessage) return;
    if (!Array.isArray(window._pendingHiddenChats)) window._pendingHiddenChats = [];
    const opts = options || {};
    const followupKey = String(opts.followupKey || '');
    if (followupKey) {
        if (!window._visualFollowupStates) window._visualFollowupStates = new Map();
        const state = window._visualFollowupStates.get(followupKey);
        if (state === 'queued' || state === 'running' || state === 'done') return;
        window._visualFollowupStates.set(followupKey, 'queued');
    }
    window._pendingHiddenChats.push({
        message: safeMessage,
        options: opts,
        // The parent turn owns this child even if the user changes the
        // visible Session between capture completion and queue flushing.
        sessionId: opts.sessionId || activeSessionId,
        followupKey,
    });
    setTimeout(() => { try { _flushHiddenChatQueue(); } catch (_) {} }, 0);
}

// Cancel only the hidden visual-analysis children owned by one parent turn.
// A later user message must never inherit a queued screenshot prompt, while a
// normal user turn in another Session remains untouched.
function _cancelVisualFollowups(sessionId, parentRequestId) {
    const sid = String(sessionId || '');
    const parent = String(parentRequestId || '');
    if (!window._cancelledVisualFollowups) window._cancelledVisualFollowups = new Set();
    if (!window._visualFollowupStates) window._visualFollowupStates = new Map();
    const pending = Array.isArray(window._pendingHiddenChats) ? window._pendingHiddenChats : [];
    window._pendingHiddenChats = pending.filter(item => {
        const opts = item?.options || {};
        const sameSession = !sid || String(item?.sessionId || '') === sid;
        const sameParent = !parent || String(opts.parentRequestId || '') === parent;
        if (!sameSession || !sameParent || !item?.followupKey) return true;
        window._cancelledVisualFollowups.add(item.followupKey);
        window._visualFollowupStates.set(item.followupKey, 'cancelled');
        window._settlePendingVisualFinalResponse?.(item.sessionId || sid, opts.parentRequestId, 'cancelled');
        return false;
    });
    // A running child is stopped by the normal case-scoped /chat/abort path;
    // mark it here as well so a buffered client response cannot be rendered
    // if the provider flushes after cancellation.
    for (const [key, state] of window._visualFollowupStates.entries()) {
        if (state !== 'running') continue;
        const prefix = parent ? `${sid}|${parent}|` : `${sid}|`;
        if (key.startsWith(prefix)) {
            window._cancelledVisualFollowups.add(key);
            window._visualFollowupStates.set(key, 'cancelled');
        }
    }
}
window._cancelVisualFollowups = _cancelVisualFollowups;

// Queue one multimodal follow-up for visual evidence produced by either the
// SSE or JSON chat transport.  Keeping this at the transport boundary avoids
// making the server response format decide whether a chart is actually
// analyzed.  The URLs are resolved and converted to image blocks by the
// server-side LLM runtime, while this browser layer keeps the follow-up hidden
// from the ordinary chat stream and preserves the owning reply identity.
function _visualTurnRequiresExplanation(responseContract) {
    if (!responseContract || responseContract.text_required !== true) return false;
    const act = String(responseContract.act || '').trim().toLowerCase();
    return act === 'question' || act === 'mixed'
        || responseContract.evidence_supplemental === true;
}

function _visualEvidenceDescriptor(item, index = 0, includeAll = false, forceAnalysis = false) {
    if (!item || !item.url) return null;
    const metadata = item.view_metadata || item.viewMetadata || {};
    const annotationPolicy = String(
        item.annotation_policy || item.annotationPolicy
        || metadata.annotation_policy || metadata.annotationPolicy || 'auto'
    ).toLowerCase();
    const visualPurpose = String(
        item.visual_purpose || item.visualPurpose
        || metadata.visual_purpose || metadata.visualPurpose || 'explain'
    ).toLowerCase();
    const explicitAnalysis = item.analysis_required ?? item.analysisRequired
        ?? metadata.analysis_required ?? metadata.analysisRequired;
    const analysisRequired = explicitAnalysis === true
        || forceAnalysis === true
        || (explicitAnalysis !== false && (item.visual_analysis === true || includeAll))
        // Required locate evidence has a user-facing state explanation and a
        // deterministic annotation fallback even if it came from an older
        // screenshot payload that omitted analysis_required.
        || (annotationPolicy === 'required' && visualPurpose === 'locate');
    if (!analysisRequired) return null;
    const manifest = metadata.grounding_manifest || metadata.groundingManifest
        || item.grounding_manifest || item.groundingManifest || { version: 1, targets: [] };
    const authoritativeCaseState = metadata.authoritative_case_state
        || metadata.authoritativeCaseState
        || item.authoritative_case_state
        || item.authoritativeCaseState
        || null;
    const semanticTarget = String(
        item.semantic_target || item.semanticTarget
        || metadata.semantic_target || metadata.semanticTarget || ''
    ).trim().toLowerCase();
    const semanticTargets = [...new Set([
        ...(Array.isArray(item.semantic_targets) ? item.semantic_targets : []),
        ...(Array.isArray(item.semanticTargets) ? item.semanticTargets : []),
        ...(Array.isArray(metadata.semantic_targets) ? metadata.semantic_targets : []),
        ...(Array.isArray(metadata.semanticTargets) ? metadata.semanticTargets : []),
        semanticTarget,
    ].map(value => String(value || '').trim().toLowerCase()).filter(Boolean))].slice(0, 32);
    const manifestTargets = Array.isArray(manifest?.targets) ? manifest.targets : [];
    const annotation = item.annotation || item.visual_annotation
        || metadata.annotation || metadata.visual_annotation || {};
    const annotationTargetRefs = [...new Set((Array.isArray(annotation.marks) ? annotation.marks : [])
        .map(mark => String(mark?.target_ref || mark?.targetRef || '').trim())
        .filter(Boolean))].slice(0, 32);
    const annotatableCount = manifestTargets.filter(target => target?.annotatable === true).length;
    const score = (annotationPolicy === 'required' ? 100 : annotationPolicy === 'auto' ? 20 : 0)
        + (visualPurpose === 'locate' ? 60 : visualPurpose === 'explain' ? 35 : 10)
        + Math.min(20, annotatableCount * 5);
    return {
        source: item,
        index,
        score,
        attachment_id: String(item.id || item.attachment_id || item.attachmentId || `evidence-${index}`),
        url: String(item.url || ''),
        target: String(item.target || metadata.target || ''),
        title: String(item.title || item.label || metadata.title || metadata.label || ''),
        annotation_policy: ['none', 'auto', 'required'].includes(annotationPolicy)
            ? annotationPolicy : 'auto',
        visual_purpose: ['overview', 'locate', 'explain', 'compare', 'verify', 'document'].includes(visualPurpose)
            ? visualPurpose : 'explain',
        analysis_required: true,
        planning_id: String(item.planning_id || item.planningId || metadata.planning_id || metadata.planningId || ''),
        data_version: String(item.data_version || item.dataVersion || metadata.data_version || metadata.dataVersion || ''),
        grounding_manifest: manifest,
        annotation_target_refs: annotationTargetRefs,
        annotation_present: annotationTargetRefs.length > 0 || !!(item.annotated_url
            || item.annotatedUrl || annotation.count > 0),
        temporary_reveal: (item.temporary_reveal ?? metadata.temporary_reveal) === true,
        temporary_camera_reframe: (item.temporary_camera_reframe
            ?? metadata.temporary_camera_reframe) === true,
        appearance_preserved: (item.appearance_preserved ?? metadata.appearance_preserved) === true,
        authoritative_case_state: authoritativeCaseState,
        semantic_target: semanticTarget,
        semantic_targets: semanticTargets,
        target_query: String(
            item.target_query || item.targetQuery
            || metadata.target_query || metadata.targetQuery || ''
        ).trim().slice(0, 8000),
        target_source: String(
            item.target_source || item.targetSource
            || metadata.target_source || metadata.targetSource || ''
        ).trim().slice(0, 80),
    };
}

function _visualAttachmentRequiresAnalysis(item) {
    return !!_visualEvidenceDescriptor(item, 0, false);
}

function _queueVisualAnalysisFollowUp(attachments, userText, turnIdentity, options = {}) {
    const candidates = (Array.isArray(attachments) ? attachments : [])
        .map((item, index) => _visualEvidenceDescriptor(
            item, index, options.includeAll === true, options.forceAnalysis === true,
        ))
        .filter(Boolean);
    const byUrl = new Map();
    candidates.forEach(candidate => {
        const current = byUrl.get(candidate.url);
        if (!current || candidate.score > current.score) byUrl.set(candidate.url, candidate);
    });
    const selectedEvidence = [...byUrl.values()]
        .sort((left, right) => right.score - left.score || left.index - right.index)
        .slice(0, 4);
    const uniqueUrls = selectedEvidence.map(item => item.url);
    const reportFollowupState = (state, followupKey = '', sessionId = '') => {
        try {
            if (typeof options.onFollowupState === 'function') {
                options.onFollowupState(state, { followupKey, sessionId });
            }
        } catch (_) {}
    };
    if (!selectedEvidence.length) {
        reportFollowupState('unavailable');
        return false;
    }
    const visualEvidence = selectedEvidence.map(item => item.source);
    const visualAttachmentLabels = [...new Set(visualEvidence.flatMap(item => {
        const metadata = item.view_metadata || item.viewMetadata || {};
        const target = String(item.target || metadata.target || '').toLowerCase();
        const labels = [item.title, item.label, metadata.title, metadata.label]
            .map(value => String(value || '').trim())
            .filter(Boolean);
        const targetLabel = {
            'viewer-axial': '轴位',
            'viewer-sagittal': '矢状位',
            'viewer-coronal': '冠状位',
            'dvh': 'DVH曲线',
            'dose-overview': '剂量分布',
        }[target];
        if (targetLabel) labels.push(targetLabel);
        return labels;
    }))];
    const parentRequestId = String(turnIdentity?.requestId || '');
    const parentUserMessageId = String(turnIdentity?.userMessageId || '');
    const parentAssistantMessageId = String(turnIdentity?.messageId || '');
    const ownerAttachment = visualEvidence.find(item => item?.session_id || item?.sessionId);
    const ownerSessionId = String(
        options.sessionId
        || turnIdentity?.sessionId
        || ownerAttachment?.session_id
        || ownerAttachment?.sessionId
        || activeSessionId
        || '',
    );
    const followupKey = [
        ownerSessionId,
        parentRequestId,
        ...uniqueUrls.sort(),
    ].join('|');
    if (!window._visualFollowupStates) window._visualFollowupStates = new Map();
    const existingState = window._visualFollowupStates.get(followupKey);
    if (existingState === 'queued' || existingState === 'running' || existingState === 'done') {
        reportFollowupState(existingState, followupKey, ownerSessionId);
        uiDebugLog('[visual-followup] duplicate suppressed:', followupKey);
        return false;
    }
    // Do not serialize the evidence URLs, parent request, and transport
    // instructions into a fake chat message.  That used to make a visual
    // child indistinguishable from a normal user turn after compaction or a
    // delayed task replay.  The API now receives a typed, parent-bound
    // visual context and reconstructs an ephemeral multimodal prompt only
    // inside the child worker.
    const visualContext = {
        version: 2,
        evidence: selectedEvidence.map(({ source, index, score, ...descriptor }) => descriptor),
        evidence_urls: uniqueUrls,
        parent_request: String(userText || '').trim(),
        preliminary_response: String(options.preliminaryResponse || '').trim().slice(0, 8000),
        attachment_labels: visualAttachmentLabels,
        omitted_count: Math.max(0, byUrl.size - selectedEvidence.length),
    };
    const followupRequestId = typeof createChatIdentity === 'function'
        ? createChatIdentity('visual-followup')
        : `visual-followup-${Date.now()}`;
    _enqueueHiddenChat(
        'Visual evidence analysis follow-up.',
        {
            visualFollowUp: true,
            internalFollowup: true,
            hiddenUserMessage: true,
            preserveLastUserMessage: true,
            // Execution identity is unique. Reusing the parent request ID
            // makes ChatTaskManager return the completed parent task and is
            // the root of stale screenshots leaking into later questions.
            requestId: followupRequestId,
            userMessageId: `user-${followupRequestId}`,
            assistantMessageId: `assistant-${followupRequestId}`,
            parentRequestId,
            parentUserMessageId,
            parentAssistantMessageId,
            followupKey,
            responseLanguage: turnIdentity?.responseLanguage || '',
            screenshotMode: options.screenshotMode || 'chat',
            multiIntentQuery: options.multiIntentQuery === true,
            visualAttachmentLabels,
            visualEvidence,
            visualContext,
            sessionId: ownerSessionId,
        },
    );
    reportFollowupState('queued', followupKey, ownerSessionId);
    return true;
}

// A screenshot attachment already renders its localized title/caption in the
// original assistant bubble.  Some multimodal providers echo those labels as
// separate lines (for example "轴位" twice) instead of writing analysis.
// Remove only exact standalone labels from the hidden child's final prose;
// sentences that discuss an axial/sagittal/coronal view remain untouched.
function _stripVisualAttachmentEchoes(text, labels = []) {
    const known = new Set([
        '轴位', '矢状位', '冠状位', 'DVH曲线', '剂量分布',
        'Axial', 'Sagittal', 'Coronal', 'DVH', 'Dose distribution',
        ...(Array.isArray(labels) ? labels : []),
    ].map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
    if (!known.size) return String(text || '');
    return String(text || '')
        .split(/\r?\n/)
        .filter(line => !known.has(String(line || '').trim().toLowerCase()))
        .join('\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}
window._stripVisualAttachmentEchoes = _stripVisualAttachmentEchoes;

async function _flushHiddenChatQueue() {
    if (window._chatStreaming || window._hiddenChatFlushRunning) return;
    if (!Array.isArray(window._pendingHiddenChats) || !window._pendingHiddenChats.length) return;
    const currentSession = activeSessionId;
    const index = window._pendingHiddenChats.findIndex(item =>
        !item?.sessionId || item.sessionId === currentSession
    );
    if (index < 0) return;
    const next = window._pendingHiddenChats.splice(index, 1)[0];
    if (!next || !next.message) return;
    const followupKey = String(next.followupKey || '');
    if (followupKey && window._cancelledVisualFollowups?.has(followupKey)) {
        if (window._visualFollowupStates) window._visualFollowupStates.set(followupKey, 'cancelled');
        const opts = next.options || {};
        window._settlePendingVisualFinalResponse?.(
            next.sessionId || opts.sessionId, opts.parentRequestId, 'cancelled',
        );
        return _flushHiddenChatQueue();
    }
    if (followupKey && window._visualFollowupStates) {
        window._visualFollowupStates.set(followupKey, 'running');
    }
    window._hiddenChatFlushRunning = true;
    try {
        await sendChat(next.message, Object.assign({
            hiddenUserMessage: true,
            skipIntentShortcuts: true,
            preserveLastUserMessage: true,
        }, next.options || {}));
    } catch (error) {
        const opts = next.options || {};
        const parentSessionId = next.sessionId || opts.sessionId;
        if (followupKey && window._visualFollowupStates) {
            window._visualFollowupStates.set(followupKey, 'error');
        }
        window._settlePendingVisualFinalResponse?.(
            parentSessionId, opts.parentRequestId, 'error',
        );
        console.warn('[visual-followup] child turn failed unexpectedly:', error);
    } finally {
        if (followupKey && window._visualFollowupStates) {
            const cancelled = window._cancelledVisualFollowups?.has(followupKey);
            const opts = next.options || {};
            const parentSessionId = next.sessionId || opts.sessionId;
            if (cancelled) {
                window._visualFollowupStates.set(followupKey, 'cancelled');
                window._settlePendingVisualFinalResponse?.(
                    parentSessionId, opts.parentRequestId, 'cancelled',
                );
            }
        }
        window._hiddenChatFlushRunning = false;
        if (Array.isArray(window._pendingHiddenChats) && window._pendingHiddenChats.length) {
            setTimeout(() => { try { _flushHiddenChatQueue(); } catch (_) {} }, 0);
        }
    }
}

// Explicit Stop still cancels the Agent. Session switching uses the detach
// path below: it closes only the browser subscription and leaves the
// case-owned task alive for replay after the user returns.
window.detachActiveChatTurn = function detachActiveChatTurn(reason) {
    if (!window._chatTurnActive && !window._chatStreaming) return null;
    const sessionId = String(activeSessionId || '');
    const taskId = window._activeChatTaskSessionId === sessionId
        ? window._activeChatTaskId
        : (window._sessionChatTaskIds[sessionId] || null);
    if (taskId) window._detachedChatTasks[sessionId] = taskId;
    _setCaseTaskState(sessionId, 'running', taskId);
    window._chatDetachRequestedFor = sessionId;
    // Do not call cancelTurnUi: the old trace is a live case-owned task, not
    // an error. The next workspace snapshot will clear this case's DOM and a
    // replay stream will rebuild it when the case is selected again.
    try { if (chatAbortController) chatAbortController.abort(); } catch (_) {}
    window._chatTurnActive = false;
    window._chatStreaming = false;
    window._chatTurnCancelUi = null;
    // This flag is process-wide UI state, not a Session property. Clear it
    // during detach so a newly selected Session cannot mistake its first
    // ordinary message for the old Session's hidden visual child.
    window._activeChatInternalFollowup = false;
    if (window._activeChatTaskSessionId === sessionId) {
        window._activeChatTaskId = null;
        window._activeChatTaskSessionId = null;
    }
    if (typeof setStreamingState === 'function') setStreamingState(false);
    return { sessionId, taskId, reason: reason || 'Session changed' };
};

window.cancelActiveChatTurn = async function cancelActiveChatTurn() {
    // Do not let a screenshot-analysis follow-up queued by the previous case
    // run after the user switches to another case.
    _cancelVisualFollowups(
        activeSessionId,
        '',
    );
    if (!window._chatTurnActive && !window._chatStreaming
        && !(typeof isStreaming !== 'undefined' && isStreaming)) return true;
    if (typeof sendChat === 'function') {
        await sendChat();
        return true;
    }
    return false;
};

async function sendChat(prefill, options) {
    const opts = options || {};
    const input = document.getElementById('chatInput');
    const isResumingTask = !!opts.resumeTaskId;
    const isInternalFollowup = !!opts.internalFollowup || !!opts.visualFollowUp;
    if (!isInternalFollowup) window._lastLLMMeta = null;
    // Manual context compression is a control-plane command, never an LLM turn.
    if (!isInternalFollowup && typeof window.isContextCommand === 'function') {
        const candidate = (typeof prefill === 'string' && prefill) ? prefill : (input ? input.value : '');
        if (window.isContextCommand(candidate)) {
            if (input) {
                input.value = '';
                if (typeof window.resizeChatInput === 'function') window.resizeChatInput(input);
            }
            if (typeof window.compressContextNow === 'function') await window.compressContextNow();
            return;
        }
    }
    const parentRequestId = String(opts.parentRequestId || opts.parent_request_id || '');
    const parentUserMessageId = String(opts.parentUserMessageId || opts.parent_user_message_id || '');
    const parentAssistantMessageId = String(opts.parentAssistantMessageId || opts.parent_assistant_message_id || '');
    // A hidden screenshot-analysis child is subordinate to the preceding
    // visible reply. Any new ordinary user turn invalidates that child,
    // including a child that is still queued and therefore not yet covered by
    // the active-stream Stop branch below.
    if (!isInternalFollowup && !isResumingTask) {
        _cancelVisualFollowups(activeSessionId, '');
    }
    // Stop acknowledgement is a per-session barrier. Without it, an
    // immediate follow-up request can race the prior /chat/abort cleanup and
    // receive the old turn's already-aborted signal.
    const pendingStopSessionId = String(activeSessionId || '');
    const pendingStop = pendingStopSessionId
        ? window._sessionChatStopPromises[pendingStopSessionId]
        : null;
    if (pendingStop && !isResumingTask) {
        try { await pendingStop; } catch (_) {}
        if (String(activeSessionId || '') !== pendingStopSessionId) return false;
    }
    const isBusy = !!window._chatTurnActive || !!window._chatStreaming;

    // Enter is a submit action, not a cancellation action. Preserve the
    // current task and queue the new turn under the selected case. The prompt
    // is rendered only in the dedicated bottom queue dock; it enters the main
    // transcript when it is actually dispatched after the active task ends.
    if (isBusy && opts.queueIfBusy) {
        const queuedText = (prefill != null ? prefill : (input ? input.value : '')).trim();
        if (!queuedText || !activeSessionId) return false;
        if (input) {
            input.value = '';
            resizeChatInput(input);
        }
        _queueChatTurn(activeSessionId, queuedText);
        // A hidden screenshot-analysis child is subordinate to the previous
        // reply. A new explicit user message supersedes it immediately, so
        // cancel that child without putting the queued prompt into the main
        // transcript before its turn is actually dispatched.
        const replacingInternalFollowup = window._activeChatInternalFollowup
            && !opts.hiddenUserMessage
            && !opts.internalFollowup;
        if (replacingInternalFollowup) {
            await sendChat(undefined, { suppressStopNotice: true });
            if (String(activeSessionId || '') === String(window._activeChatTaskSessionId || activeSessionId)) {
                setTimeout(() => { try { _flushQueuedChatTurns(); } catch (_) {} }, 0);
            }
        }
        return true;
    }

    // If user already has an active stream, treat this explicit send-button
    // invocation as STOP.  The keypress path above always sets queueIfBusy,
    // so pressing Enter can never enter this cancellation branch.
    // This must run before reading/validating the input box; during streaming
    // the input is usually empty, and the old ordering returned early before
    // aborting anything.
    if (isBusy) {
        const stopSessionId = String(window._activeChatTaskSessionId || activeSessionId || '');
        const stopTurnGeneration = Number(window._activeChatTurnGeneration || 0);
        const stopTurnAbortController = chatAbortController;
        _cancelVisualFollowups(stopSessionId, '');
        if (stopSessionId) window._explicitChatStopSessions[stopSessionId] = true;
        try {
            if (!opts.suppressStopNotice && typeof window._chatTurnCancelUi === 'function') window._chatTurnCancelUi('Stopped');
        } catch (_) {}
        try {
            if (typeof window.cancelVisibleChatProgress === 'function') {
                window.cancelVisibleChatProgress('Stopped');
            }
        } catch (_) {}
        // Defensive: the visible Progress dock is a single global surface.
        // Cancel it directly as well, so a task whose closure never owned a
        // todo instance cannot leave an active row ticking after Stop.
        try {
            window._activeTodoApi?.cancel?.('Stopped');
        } catch (_) {}
        try {
            if (stopTurnAbortController) {
                // The old stream must recognise this as an intentional stop
                // even after a later turn changes the case task status.
                stopTurnAbortController.__brachybotExplicitStop = true;
                stopTurnAbortController.abort();
            }
        } catch (_) {}
        if (chatAbortController === stopTurnAbortController) chatAbortController = null;
        window._chatTurnActive = false;
        window._chatStreaming = false;
        setStreamingState(false);
        const stopPromise = (async () => {
            // Confirm that the server has cancelled the old case before a
            // later user instruction is allowed to begin in this same case.
            const abortController = (typeof AbortController !== 'undefined') ? new AbortController() : null;
            const abortTimer = abortController ? setTimeout(() => abortController.abort(), CHAT_ABORT_TIMEOUT_MS) : null;
            let response;
            try {
                response = await fetch(API + '/chat/abort', {
                    method: 'POST',
                    headers: { 'X-BrachyBot-Session': stopSessionId },
                    signal: abortController ? abortController.signal : undefined,
                });
            } finally {
                if (abortTimer) clearTimeout(abortTimer);
            }
            if (!response.ok) console.warn('Chat abort was not acknowledged:', response.status);
            _setCaseTaskState(stopSessionId, 'cancelled', null);
            delete window._detachedChatTasks[stopSessionId];
        })();
        if (stopSessionId) window._sessionChatStopPromises[stopSessionId] = stopPromise;
        try {
            await stopPromise;
        } catch (_) {
            // The local abort and progress cleanup have already completed.
            // A disconnected browser is still protected by the turn token.
        } finally {
            // A same-session follow-up is a different turn. Never let the
            // old stop cleanup clear its task identifiers.
            if (window._activeChatTaskSessionId === stopSessionId
                && Number(window._activeChatTurnGeneration || 0) === stopTurnGeneration) {
                window._activeChatTaskId = null;
                window._activeChatTaskSessionId = null;
            }
            if (window._sessionChatStopPromises[stopSessionId] === stopPromise) {
                delete window._sessionChatStopPromises[stopSessionId];
                delete window._explicitChatStopSessions[stopSessionId];
            }
        }
        // A user message entered while the previous task was active is a
        // legitimate next turn, not a reason to leave the input queue stuck
        // forever.  The server-side task barrier has completed here, so it is
        // now safe to dispatch that queued message under the same Session.
        if (stopSessionId === String(activeSessionId || '')) {
            setTimeout(() => {
                try { _flushQueuedChatTurns(); } catch (_) {}
            }, 0);
        }
        return;
    }

    let text = isResumingTask
        ? String(opts.resumeMessage || '')
        : (prefill != null ? prefill : (input ? input.value : '')).trim();
    if (!text && !isResumingTask) return;

    // Session creation/switching is a control-plane transaction. Never make
    // an optimistic browser shell a clinical request owner. The first submit
    // waits for the durable ID; repeated submits share that same promise.
    if (!isResumingTask && !opts.sessionReadinessResolved
        && typeof window.awaitActiveSessionReady === 'function') {
        const readiness = typeof window.activeSessionReadiness === 'function'
            ? window.activeSessionReadiness()
            : null;
        if (!readiness?.ready) {
            return _submitWhenSessionReady(text, opts, input);
        }
    }

    // "Continue" is a case-control command, not a clinical knowledge
    // question. Resolve it against the server-owned task first, even when
    // this browser lost its SSE subscription during a case switch.
    if (!isResumingTask && !opts.skipContinuationRecovery
        && !opts.hiddenUserMessage && !opts.queuedTurn
        && _isContinuationRequest(text)) {
        const continuationSessionId = String(activeSessionId || '');
        if (input) {
            input.value = '';
            resizeChatInput(input);
        }
        if (continuationSessionId && typeof addChat === 'function') {
            addChat('user', text, true, Date.now(), false, continuationSessionId);
        }
        const resumed = typeof window.resumeSessionChatTask === 'function'
            ? await window.resumeSessionChatTask({ userInitiated: true })
            : false;
        const rawResumeState = window._lastChatTaskResumeState?.[continuationSessionId]?.status || 'none';
        const resumeState = (rawResumeState === 'failed' || rawResumeState === 'cancelled')
            ? 'unavailable'
            : rawResumeState;
        if (typeof addChat === 'function') {
            addChat(
                resumed ? 'system' : (resumeState === 'unavailable' ? 'error' : 'system'),
                _taskContinuationMessage(continuationSessionId, resumed ? 'reconnecting' : resumeState),
                true,
                Date.now(),
                false,
                continuationSessionId,
            );
        }
        return !!resumed;
    }
    if (input && !opts.hiddenUserMessage && !isResumingTask) {
        input.value = '';
        resizeChatInput(input);
    }

    // EPHEMERAL START: lazily create a "New chat" session on the
    // first message send. Until the user actually sends something,
    // no session is active and the chat area shows the welcome
    // message. This avoids leaking the previous session into a
    // fresh page load.
    // The durable workspace bridge owns Session allocation. Keep the legacy
    // local helper only for standalone builds that do not expose that bridge.
    try {
        if (!isResumingTask && !window.__serverWorkspaceReady
            && typeof ensurePendingSession === 'function') ensurePendingSession();
    } catch (_) {}
    const turnSessionId = String(activeSessionId || '');
    const turnRequestId = String(
        opts.requestId
        || opts.request_id
        || (isResumingTask ? opts.resumeRequestId : '')
        || (typeof createChatIdentity === 'function' ? createChatIdentity('request') : `request-${Date.now()}`)
    );
    const turnUserMessageId = String(
        opts.userMessageId || opts.user_message_id || `user-${turnRequestId}`
    );
    const turnAssistantMessageId = String(
        opts.assistantMessageId || opts.assistant_message_id || `assistant-${turnRequestId}`
    );
    const detectedTurnLanguage = typeof detectConversationLanguage === 'function'
        ? detectConversationLanguage(text)
        : '';
    const conversationFallbackLanguage = typeof conversationLanguageForSession === 'function'
        ? conversationLanguageForSession(turnSessionId)
        : '';
    // A visible user's latest language-bearing text wins over every persisted
    // or UI hint. Hidden visual children are the exception: their text is an
    // internal generated prompt and must keep the parent's language.
    const turnResponseLanguage = isInternalFollowup
        ? (opts.responseLanguage || conversationFallbackLanguage || effectiveUiLanguage() || '')
        : (detectedTurnLanguage
            || opts.responseLanguage
            || conversationFallbackLanguage
            || effectiveUiLanguage()
            || '');
    const displayRequestId = isInternalFollowup && parentRequestId
        ? parentRequestId : turnRequestId;
    const displayUserMessageId = isInternalFollowup && parentUserMessageId
        ? parentUserMessageId : turnUserMessageId;
    const displayAssistantMessageId = isInternalFollowup && parentAssistantMessageId
        ? parentAssistantMessageId : turnAssistantMessageId;
    const turnIdentity = {
        // The parent identity is used only for visible rendering and durable
        // transcript merging. The request sent to the server remains the
        // unique child identity above.
        requestId: displayRequestId,
        userMessageId: displayUserMessageId,
        messageId: displayAssistantMessageId,
        sessionId: turnSessionId,
        responseLanguage: turnResponseLanguage,
    };
    if (!isInternalFollowup && !opts.hiddenUserMessage && !isResumingTask && typeof addChat === 'function') {
        addChat('user', text, true, Date.now(), false, turnSessionId, {
            requestId: turnRequestId,
            messageId: turnUserMessageId,
            messageKind: 'user_message',
            turnSequence: 0,
            responseLanguage: turnIdentity.responseLanguage,
            traceLanguage: turnIdentity.responseLanguage,
        });
    }
    if (!opts.preserveLastUserMessage) {
        window._lastUserMessage = text;
    }
    let turnTaskId = isResumingTask ? String(opts.resumeTaskId || '') : '';
    if (!isResumingTask) window._activeChatTaskId = null;
    if (isResumingTask && window._chatDetachRequestedFor === turnSessionId) {
        window._chatDetachRequestedFor = null;
    }

    if (!opts.skipIntentShortcuts && _isMonitorStartRequest(text)) {
        await startTrainingMode(text);
        return;
    }
    if (!opts.skipIntentShortcuts && _isMonitorStopRequest(text) && trainingMonitorState.active) {
        await stopTrainingMode();
        return;
    }
    // Natural-language planning questions must continue through the normal
    // chat workflow. The server-side local-read classifier already routes
    // them to a grounded planning_assessment_query answer. Do not redirect
    // them to requestPlanningAdvice(): that endpoint belongs to the explicit
    // monitor toolbar action and would incorrectly show the monitor progress
    // animation plus its fixed checklist in an ordinary conversation.

    const turnGeneration = Number(window._chatTurnGeneration || 0) + 1;
    window._chatTurnGeneration = turnGeneration;
    window._activeChatTurnGeneration = turnGeneration;
    window._activeChatTaskSessionId = turnSessionId;
    window._activeChatRequestId = turnRequestId;
    window._activeChatParentRequestId = parentRequestId || turnRequestId;
    window._activeChatInternalFollowup = isInternalFollowup;
    _setCaseTaskState(turnSessionId, 'connecting', turnTaskId || undefined);
    window._chatStreaming = false;

    // Wipe the dock for a fresh turn.  For a task resume we do NOT clear
    // — the saved per-session state (window._caseTodos) is restored below
    // with the original startedAt timestamps so the timer shows the real
    // background elapsed time.
    if (!isResumingTask) {
        try { window.clearCaseScopedProgressPresentation?.(); } catch (_) {}
    }

    let thinkingEl = null;
    let chainEl = null, stepsDiv = null, headerEl = null;
    let responseEl = null;
    // Persistent todo list at the bottom of the bot's chat row.  When
    // resuming a detached task, rebuild from the saved state so the
    // operator sees completed steps and the real elapsed clock.
    let todo = null;
    const savedItems = isResumingTask ? (window._caseTodos || {})[turnSessionId] : null;
    if (savedItems && savedItems.length && typeof _todoCreate === 'function') {
        todo = _todoCreate();
        const dock = document.getElementById('chatTodoDock');
        if (dock) { dock.replaceChildren(todo.root); dock.style.display = ''; }
        for (const si of savedItems) {
            // Rebuild the dedup anchors lost in the previous restore path.
            // Predicted items were born with toolName=null but carry
            // predictedTool; replay events match on (predicted, predictedTool)
            // and on toolName. Without restoring these, the replayed
            // ctv/oar done events fail every match and append duplicate rows.
            const anchorTool = si.toolName || si.predictedTool || '';
            const stubStep = {
                type: 'tool',
                tool: anchorTool,
                title: si.label || '',
                id: si.id || '',
                status: si.status,
            };
            // Restore the same milestone identity so a replayed Final Response
            // event merges into the saved row instead of adding a second one.
            const milestoneKey = si.milestoneKey || _todoStepIdentity(stubStep);
            if (milestoneKey && todo.items.some(i => i.milestoneKey === milestoneKey)) {
                continue;
            }
            const item = todo.addPending(stubStep);
            if (milestoneKey) item.milestoneKey = milestoneKey;
            item.startedAt = si.startedAt;
            item.endedAt = si.endedAt;
            // Restore the fields _todoUpdateFromStep / _todoFindPredicted use.
            item.predicted = !!si.predicted;
            item.predictedTool = si.predictedTool || null;
            item.toolName = anchorTool || null;
            if (si._realElapsedMs) item._realElapsedMs = si._realElapsedMs;
            if (si.status === 'done' || si.status === 'error') {
                todo.markDone(item, si.status === 'error' ? 'failed' : undefined);
            } else if (si.status === 'active') {
                todo.markActive(item);
            }
            // pending / predicted items stay in their saved status;
            // the SSE stream will promote them to active / done as new
            // events arrive.
        }
    }
    let responseText = '';
    // Provider draft chunks belong to the execution trace. The server emits
    // `final_text_chunk` only after the completeness/quality gate; those
    // chunks are safe to render progressively in the final answer bubble.
    let finalResponseReceived = false;
    let finalTextStreamStarted = false;
    let finalReplyCommitted = false;
    let finalResponsePaintWaited = false;
    let visualFinalResponsePending = false;
    let visualFollowupState = '';
    let visualFollowupKey = '';
    let finalResponseStep = null;
    let turnCompleted = false;
    let turnCancelled = false;
    let turnFailed = false;
    let progressEl = null;
    let lastToolName = '';
    const steps = [];
    const optimisticTraceStepIds = {
        user: `client-user-input-${turnRequestId}`,
        router: `client-router-${turnRequestId}`,
    };
    const isChineseTurn = () => {
        const requestLanguage = typeof detectConversationLanguage === 'function'
            ? detectConversationLanguage(text)
            : '';
        if (requestLanguage === 'zh') return true;
        return (typeof conversationLanguageForSession === 'function'
            ? conversationLanguageForSession(turnSessionId)
            : window._i18nLang) === 'zh';
    };
// Structural reconciliation: the optimistic "router" row is just a
    // placeholder for "the first real server step in this turn", whatever the
    // server labels it (multi-agent router, local intent, or any future
    // classification phase). We merge exactly one server step into the
    // optimistic row per turn and mark it consumed; subsequent server steps
    // append normally. This avoids any whitelist of step titles or types and
    // stays correct if the backend adds a new classification phase later.
    // Per UX preference, the row keeps the optimistic routing title (the
    // localized "multi-agent router" label) so users see a single routing
    // entry whether the backend used the remote router or the local-policy
    // short-circuit.
    let _optimisticRouterConsumed = false;
    const reconcileOptimisticTraceStep = step => {
        if (!step || typeof step !== 'object') return { step, index: -1 };
        const optimisticId = step.type === 'user'
            ? optimisticTraceStepIds.user
            : (_optimisticRouterConsumed ? '' : optimisticTraceStepIds.router);
        let index = optimisticId ? steps.findIndex(item => item.id === optimisticId) : -1;
        // A server step may be re-emitted after the optimistic router row was
        // already consumed (the backend updates the same step from pending to
        // done and yields it twice). Match by server id so the second event
        // updates the row in place instead of appending a duplicate.
        if (index < 0 && step.id != null) {
            // A server step that appended directly (without consuming the
            // optimistic row) must still update in place when the same logical
            // step is re-emitted — for example hydration progress heartbeats.
            index = steps.findIndex(item => item._serverId === step.id || item.id === step.id);
        }
        if (index < 0) return { step, index: -1 };
        // Keep the DOM identity created on click-send. This turns the
        // immediate pending row into the server-confirmed row in place and
        // prevents the first SSE event from creating a duplicate trace. The
        // row keeps its optimistic DOM id so appendStepToChain can still find
        // the existing block; the server id is recorded separately so later
        // re-emissions of the same logical step resolve to this row.
        const placeholder = steps[index];
        // Deferred final delivery and the live trace hold this same object.
        // Replacing it leaves the deferred list pointing at an obsolete row.
        const previousTitle = placeholder.title;
        const merged = Object.assign(placeholder, step, {
            id: optimisticId || placeholder.id,
            _serverId: (step.id != null) ? step.id : placeholder._serverId,
        });
        // Preserve the user-facing routing title; only status/content come
        // from the server. This keeps the routing row label stable whether
        // the server emitted a multi-agent-router or the local-intent
        // short-circuit step.
        if (step.type !== 'user' && previousTitle) merged.title = previousTitle;
        steps[index] = merged;
        if (step.type !== 'user') _optimisticRouterConsumed = true;
        return { step: merged, index };
    };
    // Do not infer planning completion from the rendered trace shape. The
    // server may emit a top-level tool event, a pipeline sub-step with
    // parent_tool, or a compact event without type:"tool". All of those are
    // legitimate representations of the same turn and must drive the same
    // case-owned UI refresh.
    const PLANNING_EVENT_TOOLS = new Set([
        'planning_pipeline', 'dose_evaluation', 'trajectory_init',
        'trajectory_refine', 'seed_planning', 'dose_calc', 'dose_eval',
        'manual_planning', 'intraoperative_replan',
    ]);
    const GUIDE_EVENT_TOOLS = new Set(['surgical_guide']);
    const GUIDE_TERMINAL_STATUSES = new Set(['done', 'completed', 'ready']);
    let turnSawPlanningWork = false;
    let turnSawSurgicalGuideWork = false;
    let turnPlanningRunStarted = false;
    const turnDoseEvents = new Set();
    const isCompletedGuideEvent = eventData => {
        if (!eventData || typeof eventData !== 'object') return false;
        const tool = String(
            eventData.tool || eventData.tool_name || eventData.function_name
            || eventData.function || eventData.name || eventData.parent_tool
            || eventData.parentTool || '',
        ).trim();
        const status = String(
            eventData.status || eventData.state || eventData.phase
            || eventData.result?.status || eventData.metadata?.status || '',
        ).trim().toLowerCase();
        return GUIDE_EVENT_TOOLS.has(tool) && GUIDE_TERMINAL_STATUSES.has(status);
    };
    const markPlanningEvent = (eventData) => {
        if (!eventData || typeof eventData !== 'object') return false;
        // Different server generations use tool, tool_name, function_name,
        // or parent_tool for the same streamed event. Normalize those forms
        // here so an in-progress planning run cannot lose its invalidation or
        // dose refresh merely because the event envelope changed.
        const tool = String(
            eventData.tool || eventData.tool_name || eventData.function_name
            || eventData.function || eventData.name || '',
        ).trim();
        const parentTool = String(
            eventData.parent_tool || eventData.parentTool || eventData.parent || '',
        ).trim();
        const matched = PLANNING_EVENT_TOOLS.has(tool) || PLANNING_EVENT_TOOLS.has(parentTool);
        if (!matched) return false;
        turnSawPlanningWork = true;

        // Planning results are mutable aliases in the legacy viewer API, but
        // the server reserves an immutable Planning run before the first
        // stage writes.  Tell the viewer to remove the old dose presentation
        // immediately; otherwise a long-running replan leaves the previous
        // slice overlay looking current until the final response arrives.
        const status = String(
            eventData.status || eventData.state || eventData.phase || eventData.result?.status || '',
        ).trim().toLowerCase();
        const terminal = new Set(['done', 'completed', 'error', 'failed', 'cancelled', 'stopped']);
        const eventSessionId = String(eventData.session_id || eventData.sessionId || '').trim();
        const sessionMatches = !eventSessionId || eventSessionId === String(turnSessionId || '');
        const metadata = eventData.metadata && typeof eventData.metadata === 'object'
            ? eventData.metadata : {};
        const planningId = eventData.planning_id
            || eventData.planningId
            || metadata.planning_id
            || metadata.planningId
            || eventData.result?.planning_id
            || eventData.result?.planningId
            || eventData.result?.metadata?.planning_id
            || null;
        // A compact stream may send only the terminal tool result. It still
        // represents the start of a new immutable Planning run from the
        // viewer's perspective, so invalidate the previous dose before the
        // terminal payload is rendered.
        if (sessionMatches && !turnPlanningRunStarted) {
            turnPlanningRunStarted = true;
            window.dispatchEvent(new CustomEvent('brachybot:planning-run-started', {
                detail: {
                    sessionId: turnSessionId,
                    requestId: turnRequestId,
                    messageId: turnAssistantMessageId,
                    planningId,
                    tool: tool || parentTool,
                },
            }));
        }
        const doseTool = ['dose_calc', 'dose_eval', 'dose_evaluation'].includes(tool)
            || ['dose_calc', 'dose_eval', 'dose_evaluation'].includes(parentTool);
        const resultPayload = eventData.result && typeof eventData.result === 'object'
            ? eventData.result : {};
        const metadataPayload = resultPayload.metadata && typeof resultPayload.metadata === 'object'
            ? resultPayload.metadata : {};
        // Tool progress may arrive in several valid wire shapes.  The
        // planning pipeline publishes the early dose grid as a compact
        // ``content: "... | dose_ready=true"`` event in some streams, while
        // other providers preserve it as structured metadata.  Normalize
        // both here so an in-progress slice refresh does not depend on the
        // LLM/provider's event serialization details.
        const doseReadyText = [
            eventData.content,
            eventData.message,
            eventData.detail,
            typeof eventData.result === 'string' ? eventData.result : '',
            resultPayload.content,
            resultPayload.message,
            metadata.content,
            metadata.message,
            metadataPayload.content,
            metadataPayload.message,
        ].filter(value => typeof value === 'string').join('\n');
        const hasDosePayload = !!(
            eventData.has_dose || metadata.has_dose || metadataPayload.has_dose
            || eventData.dose_distribution || eventData.dose_distribution_gy
            || eventData.dose_overlay || eventData.dose_metrics
            || resultPayload.dose_distribution || resultPayload.dose_distribution_gy
            || resultPayload.dose_overlay || resultPayload.dose_metrics
            || metadata.dose_distribution || metadata.dose_distribution_gy
            || metadataPayload.dose_distribution || metadataPayload.dose_distribution_gy
        );
        const doseReady = eventData.dose_ready === true
            || eventData.doseReady === true
            || metadata.dose_ready === true
            || metadataPayload.dose_ready === true
            || /["']?dose[_\s-]?ready["']?\s*[:=]\s*(?:"?true"?|done|1)\b/i.test(doseReadyText);
        const planningPipelineTool = tool === 'planning_pipeline' || parentTool === 'planning_pipeline';
        const doseOperation = doseTool || (planningPipelineTool && (hasDosePayload || doseReady));
        const rejectedDoseStatus = new Set(['error', 'failed', 'cancelled', 'stopped']);
        // A dose grid can be published by dose_calc before the enclosing
        // planning_pipeline emits its terminal event.  The presence of a real
        // dose payload is therefore sufficient to refresh the Viewer; waiting
        // for the final planning response is what caused frozen slices during
        // long-running jobs.
        const doseEventEligible = !rejectedDoseStatus.has(status)
            && (terminal.has(status) || hasDosePayload || doseReady);
        if (sessionMatches && doseOperation && doseEventEligible) {
            const doseGeneration = eventData.dose_generation
                || eventData.doseGeneration
                || metadata.dose_generation
                || metadata.doseGeneration
                || metadataPayload.dose_generation
                || metadataPayload.doseGeneration
                || resultPayload.dose_generation
                || resultPayload.doseGeneration
                || '';
            const eventKey = `${turnRequestId}|${tool}|${parentTool}|${planningId || ''}|${status}|${doseGeneration}|${hasDosePayload || doseReady ? 'payload' : 'terminal'}`;
            if (!turnDoseEvents.has(eventKey)) {
                turnDoseEvents.add(eventKey);
                window.dispatchEvent(new CustomEvent('brachybot:dose-result-updated', {
                    detail: {
                        sessionId: turnSessionId,
                        requestId: turnRequestId,
                        messageId: turnAssistantMessageId,
                        planningId,
                        tool: tool || parentTool,
                        doseGeneration: doseGeneration || null,
                        hasDosePayload: hasDosePayload || doseReady,
                    },
                }));
            }
        }
        return matched;
    };
    const screenshotTasks = [];
    const screenshotResults = [];
    const screenshotTaskKeys = new Set();
    // Screenshot plans temporarily change Viewer focus/visibility. Serialize
    // their browser transactions within this turn so one target is restored
    // before the next target is framed and captured.
    let screenshotCaptureQueue = Promise.resolve();
    // Persisted Session content uses the same reply identity as screenshots,
    // but it reads existing artifacts/data instead of capturing a live DOM
    // canvas. Keep its lifecycle separate so capture failures cannot replace
    // or erase the assistant response for this turn.
    const sessionContentTasks = [];
    const sessionContentResults = [];
    const sessionContentTaskKeys = new Set();
    const presentationMessages = [];
    const uiActionTasks = [];
    const uiActionResults = [];
    const deferredFinalSteps = [];
    // The final-response trace row is a client-owned delivery boundary: a
    // server terminal step only means its SSE task finished, not that pending
    // browser captures/actions or visual analysis have reached the user.
    // Keep an explicit marker in addition to inspecting the reconstructed
    // step list. Some replayed SSE streams expose the UI action metadata only
    // on the tool event; the final response must still be held back until the
    // browser reports whether report.autofill actually succeeded.
    let reportUiActionRequested = false;
    // Group screenshots emitted during one assistant turn into one gallery.
    const screenshotGallery = {
        sessionId: turnSessionId,
        requestId: turnRequestId,
        messageId: turnAssistantMessageId,
        responseLanguage: turnIdentity.responseLanguage,
        mode: opts.screenshotMode || (trainingMonitorState.active ? 'monitor' : 'chat'),
        layout: 'auto',
    };
    // UI state is useful planning context, but it is not a prerequisite for
    // sending the user's message. A rendering extension must never make the
    // chat appear to accept a message while preventing the network request.
    let uiState = {};
    try {
        uiState = (typeof collectUIState === 'function') ? (collectUIState() || {}) : {};
    } catch (error) {
        console.error('[chat] Optional UI state capture failed; sending request without it:', error);
    }
    const cancelTurnUi = (reason) => {
        if (thinkingEl && typeof removeThinkingIndicator === 'function') {
            removeThinkingIndicator(thinkingEl);
        }
        if (todo && typeof todo.cancel === 'function') {
            todo.cancel(reason || 'Stopped');
        }
        if (chainEl && typeof cancelThinkingChain === 'function') {
            cancelThinkingChain(chainEl, headerEl);
        }
        if (window._toolProgressEls && window._toolProgressEls.length) {
            window._toolProgressEls.forEach(el => {
                try { el.style.display = 'none'; } catch (_) {}
            });
            window._toolProgressEls = [];
        }
    };
    window._chatTurnCancelUi = cancelTurnUi;
    window._chatTurnActive = true;
    let turnAbortController = null;
    let reconnectNeeded = false;
    let turnDetached = false;

    try {
        chatAbortController = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        turnAbortController = chatAbortController;
        setStreamingState(true);
        thinkingEl = (!isInternalFollowup && typeof showThinkingIndicator === 'function')
            ? showThinkingIndicator() : null;
        // Snapshot the turn start time here, before the SSE connection
        // opens.  On task resume the saved timestamp is fed to
        // createLiveThinkingChain so the header clock shows the real
        // background elapsed time rather than restarting from 0.0 s.
        window._caseChainStartedAt = window._caseChainStartedAt || {};
        if (!isResumingTask && turnSessionId) {
            window._caseChainStartedAt[turnSessionId] = Date.now();
        }
        // Do not wait for the network/SSE handshake to show that the request
        // has entered the agent pipeline. The two entries below are local UI
        // state only; their stable ids are reconciled with the first genuine
        // server trace events instead of being retained as fake history.
        //
        // A resumed task is different: its first journal event may already
        // have been consumed by the previous browser connection.  Waiting for
        // a new `step` event then leaves the independent Progress dock visible
        // with no Execution Trace at all.  Create the trace immediately for
        // resumed visible tasks and seed it from the durable trace when one is
        // available; subsequent replayed events still reconcile in place.
        if (!isInternalFollowup && typeof createLiveThinkingChain === 'function') {
            if (thinkingEl && typeof removeThinkingIndicator === 'function') {
                removeThinkingIndicator(thinkingEl);
                thinkingEl = null;
            }
            const r = createLiveThinkingChain(
                window._caseChainStartedAt[turnSessionId],
                turnRequestId,
                turnIdentity.responseLanguage,
            );
            chainEl = r.chainEl; stepsDiv = r.stepsDiv; headerEl = r.headerEl;
            const restoredTrace = isResumingTask
                && typeof window.findSessionMessageByIdentity === 'function'
                ? window.findSessionMessageByIdentity(
                    turnSessionId,
                    '',
                    turnRequestId,
                    'thinking',
                )
                : null;
            const restoredSteps = Array.isArray(restoredTrace?.steps)
                ? restoredTrace.steps
                    .map(step => typeof window._traceStepForDisplay === 'function'
                        ? window._traceStepForDisplay(step, turnSessionId, turnIdentity.responseLanguage)
                        : step)
                    .filter(Boolean)
                : [];
            if (restoredSteps.length) {
                steps.push(...restoredSteps);
            } else {
                const zh = isChineseTurn();
                steps.push(
                    {
                        id: optimisticTraceStepIds.user,
                        type: 'user',
                        title: zh ? '\u7528\u6237\u8bf7\u6c42' : 'User input',
                        status: 'done',
                        content: text,
                    },
                    {
                        id: optimisticTraceStepIds.router,
                        type: 'thinking',
                        // This row is a client-side connection placeholder. It
                        // covers the time the request spends connecting and
                        // queuing before the server publishes the real local
                        // intent step; it must not claim that analysis is
                        // running while the browser is only waiting for the
                        // task handshake.
                        title: zh ? '\u8fde\u63a5\u4e0e\u51c6\u5907' : 'Connecting & preparing',
                        status: 'pending',
                        content: zh ? '\u6b63\u5728\u8fde\u63a5\u670d\u52a1\u7aef\u2026' : 'Connecting to the server...',
                    },
                );
            }
            steps.forEach((step, index) => appendStepToChain?.(stepsDiv, step, index));
            updateChainHeader?.(headerEl, steps);
            window._brachyLiveTrace = {
                sessionId: turnSessionId, steps, chainEl, stepsDiv, headerEl,
                requestId: turnRequestId, responseLanguage: turnIdentity.responseLanguage,
                getTodo: () => todo,
            };
        }

        // A proxy can drop an idle keep-alive connection exactly when the
        // turn starts, losing the POST before the server ever sees it. The
        // request id is an idempotency key on the server (a duplicate returns
        // the same task), so one clean retry on a fresh connection can only
        // join the same turn instead of duplicating it.
        const turnRequestBody = isResumingTask ? null : JSON.stringify({
                        message: text,
                        ui_state: uiState,
                        stream: true,
                        clear_context: false,
                        // Global UI locale is only the backend fallback for a
                        // new/ambiguous turn. It never overrides the latest
                        // language-bearing user message.
                        ui_language: effectiveUiLanguage(),
                        request_id: turnRequestId,
                        user_message_id: turnUserMessageId,
                        assistant_message_id: turnAssistantMessageId,
                        parent_request_id: parentRequestId || undefined,
                        parent_user_message_id: parentUserMessageId || undefined,
                        parent_assistant_message_id: parentAssistantMessageId || undefined,
                        internal_followup: isInternalFollowup,
                        // Typed evidence belongs only to a linked hidden
                        // visual child. Ordinary user text never carries
                        // prior attachments or a parent request implicitly.
                        visual_context: isInternalFollowup && opts.visualContext
                            ? opts.visualContext
                            : undefined,
                        response_language: turnIdentity.responseLanguage
                            || window._responseLanguage
                            || window._i18nLang
                            || '',
                    });

        const performHandshake = async (controller) => {
            const signal = controller ? controller.signal : undefined;
            if (isResumingTask) {
                const afterSeq = Number(opts.afterSeq || 0);
                return await fetch(
                    API + '/chat/tasks/' + encodeURIComponent(opts.resumeTaskId)
                    + '/stream?after_seq=' + encodeURIComponent(String(afterSeq)),
                    {
                        headers: { 'X-BrachyBot-Session': turnSessionId },
                        signal,
                    },
                );
            }
            return await fetch(API + '/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-BrachyBot-Session': turnSessionId,
                },
                body: turnRequestBody,
                signal,
            });
        };

        const handshakeAttempts = 2;
        let resp = null;
        let handshakeFailure = null;
        for (let attempt = 0; attempt < handshakeAttempts; attempt += 1) {
            const attemptController = attempt === 0
                ? turnAbortController
                : ((typeof AbortController !== 'undefined') ? new AbortController() : null);
            if (attempt > 0) {
                // Keep Stop bound to the live attempt, not to the aborted one.
                chatAbortController = attemptController;
                turnAbortController = attemptController;
                console.warn('[chat] stream handshake was lost; retrying with the same request id');
            }
            const connectTimer = attemptController
                ? setTimeout(() => attemptController.abort(), CHAT_CONNECT_TIMEOUT_MS)
                : null;
            try {
                resp = await performHandshake(attemptController);
                handshakeFailure = null;
                break;
            } catch (handshakeError) {
                handshakeFailure = handshakeError;
                const interrupted = handshakeError?.name === 'AbortError';
                const explicitStop = !!attemptController?.__brachybotExplicitStop;
                // A case switch detaches the turn by aborting it; the user is
                // no longer looking at this case, so the turn must not be
                // re-sent behind their back.
                const detached = window._chatDetachRequestedFor === turnSessionId
                    || String(activeSessionId || '') !== turnSessionId;
                if (!interrupted || explicitStop || detached
                    || attempt + 1 >= handshakeAttempts) break;
            } finally {
                if (connectTimer) clearTimeout(connectTimer);
            }
        }
        if (handshakeFailure) throw handshakeFailure;

        if (!resp.ok) {
            turnFailed = true;
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
            let serverError = '';
            let serverCode = '';
            try {
                const errBody = await resp.json();
                serverError = String(errBody?.error || errBody?.message || '');
                serverCode = String(errBody?.code || '');
            } catch (_) { /* non-JSON error body */ }
            console.warn('[chat] HTTP request failed', {
                status: resp.status,
                serverError,
                serverCode,
                sessionId: turnSessionId,
            });
            if (resp.status === 409 && serverCode === 'workspace_locked') {
                // The case edit lease belongs to another browser. Surface the
                // existing takeover flow with a precise explanation instead
                // of the generic "request could not be completed" message.
                try { void window.brachybotAuth?.acquireLease?.(turnSessionId); } catch (_) {}
                if (typeof addChat === 'function') {
                    addChat(
                        'error',
                        _chatWorkspaceLockedMessage(turnSessionId),
                        true,
                        Date.now(),
                        false,
                        turnSessionId,
                        turnIdentity,
                    );
                }
                return false;
            }
            if (typeof addChat === 'function') {
                addChat(
                    isInternalFollowup ? 'bot-response' : 'error',
                    isInternalFollowup
                        ? _visualEvidenceFallbackResponse(
                            opts.visualEvidence || [],
                            turnSessionId,
                            turnIdentity.responseLanguage,
                            text,
                        )
                        : _chatUserVisibleFailure(turnSessionId, 'request', serverCode),
                    true,
                    Date.now(),
                    false,
                    turnSessionId,
                    turnIdentity,
                );
            }
            // Resume callers must be able to distinguish an HTTP failure
            // from a successfully opened stream. A bare return is
            // indistinguishable from success to resumeSessionChatTask().
            return false;
        }

        const ctype = resp.headers.get('content-type') || '';
        if (ctype.indexOf('text/event-stream') === -1) {
            // Server didn't stream — fall back to plain JSON
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
            const data = await resp.json().catch(() => null);
            if (data && Object.prototype.hasOwnProperty.call(data, 'brain_available')) {
                window.updateBrainStatusIndicator?.(data.brain_available, 'chat-response');
            }
            const presentation = await _presentJsonSessionContent(data?.steps, turnSessionId, turnIdentity);
            const screenshotPresentation = await _captureJsonScreenshotSteps(
                data?.steps, text, turnIdentity, turnSessionId,
            );
            const presentedAttachments = [
                ...(presentation.attachments || []),
                ...(screenshotPresentation.attachments || []),
            ];
            const uiActions = await _executeJsonUIActions(data?.steps, turnSessionId);
            const uiFailure = uiActions.failed
                ? (_hasReportGenerationAction(data?.steps)
                    ? _reportGenerationFailureMessage(turnSessionId)
                    : _chatUserVisibleFailure(turnSessionId, 'request'))
                : '';
            const responseContract = data?.llm_meta?.response_contract || null;
            const forceVisualAnalysis = _visualTurnRequiresExplanation(responseContract);
            const visualAttachments = presentedAttachments.filter(item =>
                item && item.url && (
                    _visualAttachmentRequiresAnalysis(item) || forceVisualAnalysis
                )
            );
            const visualAnalysisContinuation = !isInternalFollowup && visualAttachments.length > 0;
            const responseBody = String(data?.response || data?.reply || data?.content || '');
            const screenshotFailure = String(screenshotPresentation.userMessage || '').trim();
            const failureAndReadResults = screenshotFailure
                ? [
                    screenshotFailure,
                    data?.llm_meta?.multi_intent_query ? responseBody : '',
                ].filter(Boolean).join('\n\n')
                : '';
            const reply = uiFailure
                || failureAndReadResults
                || (visualAnalysisContinuation ? '' : presentation.userMessage)
                || (visualAnalysisContinuation && !data?.llm_meta?.multi_intent_query
                    ? '' : responseBody)
                || (visualAnalysisContinuation ? '' : _chatUserVisibleFailure(turnSessionId, 'response'));
            if (reply && typeof addChat === 'function') {
                addChat('bot-response', reply, true, Date.now(), false, turnSessionId, Object.assign(
                    {},
                    turnIdentity,
                    {
                        attachments: presentedAttachments,
                        screenshotLayout: 'auto',
                    },
                ));
                finalReplyCommitted = true;
            } else if (!visualAnalysisContinuation && presentedAttachments.length) {
                // The screenshot/content presenter already mounted these
                // attachment-only results under the assistant reply identity.
                finalReplyCommitted = true;
            }
            if (visualAttachments.length) {
                _queueVisualAnalysisFollowUp(
                    visualAttachments,
                    text,
                    turnIdentity,
                    {
                        sessionId: turnSessionId,
                        screenshotMode: 'chat',
                        includeAll: true,
                        forceAnalysis: forceVisualAnalysis,
                        preliminaryResponse: [
                            data?.llm_meta?.multi_intent_query ? responseBody : '',
                            screenshotPresentation.userMessage || '',
                        ].filter(Boolean).join('\n\n'),
                    },
                );
            }
            turnCompleted = true;
            turnFailed = uiActions.failed || !data;
            finalResponseReceived = true;
            responseText = reply;
            return;
        }

        // Real SSE — read stream
        if (!resp.body || !resp.body.getReader) {
            turnFailed = true;
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
            const txt = await resp.text();
            console.warn('[chat] SSE response body was unavailable', {
                sessionId: turnSessionId,
                preview: String(txt || '').slice(0, 240),
            });
            if (typeof addChat === 'function') {
                addChat('bot-response', _chatUserVisibleFailure(turnSessionId, 'response'), true,
                    Date.now(), false, turnSessionId, turnIdentity);
            }
            return;
        }
        window._chatStreaming = true;
        window._toolProgressEls = [];
        window._chatFallbackUsed = false;

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let currentEvent = null;
        // `done` is the server's terminal SSE event.  The old reader handled
        // its side effects but continued waiting for another chunk, so a
        // successful planning turn later looked like a timeout/error.
        readLoop: while (true) {
            // LLM thinking phases (without tool calls) can exceed the default
            // 90 s idle window.  A server-owned task is replayable and emits
            // protocol heartbeats, so trust the task journal even if the
            // optimistic todo/trace state has not caught up with a tool call.
            const hasKnownServerTask = Boolean(
                turnTaskId
                || window._sessionChatTaskIds?.[turnSessionId]
                || window._detachedChatTasks?.[turnSessionId]
                || window._sessionChatTaskStatuses?.[turnSessionId] === 'running'
            );
            const hasActiveWork = hasKnownServerTask || ((todo && todo.items && todo.items.some(
                i => i.status === 'active' || i.status === 'pending',
            )) || steps.some(s => _isInFlightToolStatus(s.status)));
            const onReadTimeout = () => {
                try { turnAbortController.abort(); } catch (_) {}
            };
            const readTimeoutMs = hasKnownServerTask
                ? CHAT_TASK_IDLE_TIMEOUT_MS
                : hasActiveWork
                    ? CHAT_PLANNING_IDLE_TIMEOUT_MS
                    : CHAT_IDLE_TIMEOUT_MS;
            const { done, value } = await readChatChunk(reader, readTimeoutMs, onReadTimeout);
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                // Detach is deliberately non-destructive.  Stop rendering an
                // old case immediately if an already-buffered SSE chunk races
                // with the selection change; the worker/event journal remains
                // alive and the selected case can replay it later.
                if (!_isCurrentTurnSession(turnSessionId)) {
                    try { reader.cancel(); } catch (_) {}
                    break readLoop;
                }
                if (line.startsWith('event: ')) {
                    currentEvent = line.slice(7).trim();
                } else if (line.startsWith('data: ')) {
                    const dataStr = line.slice(6).trim();
                    if (!dataStr) continue;
                    let data = null;
                    try { data = JSON.parse(dataStr); } catch (_) { continue; }

                    // Heartbeats are transport liveness only. They must reset
                    // the reader timeout but never become a trace step,
                    // planning event, or visible assistant content.
                    if (currentEvent === 'heartbeat') continue;

                    if (currentEvent === 'planning_preview' && data) {
                        // Preview frames are a separate, read-only Viewer
                        // transport. They never become trace steps, chat text,
                        // Data Tree rows, or planning-refresh triggers.
                        if (typeof window.handlePlanningPreviewEvent === 'function') {
                            window.handlePlanningPreviewEvent({
                                ...data,
                                session_id: data.session_id || turnSessionId,
                                request_id: turnRequestId,
                            });
                        }
                        continue;
                    }

                    // Providers may label the same tool progress as step,
                    // tool, or a compact response event. Record the planning
                    // family before branching on the event name so every
                    // representation reaches the same refresh path.
                    if (data && typeof data === 'object') {
                        markPlanningEvent(data);
                        // Guide completion is deliberately handled outside
                        // the `step` branch as well. Providers may emit the
                        // terminal tool envelope as `tool`, `progress`, or a
                        // compact event without a trace step; all of them
                        // must hydrate the persisted mesh.
                        if (isCompletedGuideEvent(data)) {
                            turnSawSurgicalGuideWork = true;
                            _scheduleCaseSurgicalGuideRefresh(turnSessionId, 0);
                        }
                    }

                    if (currentEvent === 'task_meta' && data) {
                        if (Object.prototype.hasOwnProperty.call(data, 'brain_available')) {
                            window.updateBrainStatusIndicator?.(data.brain_available, 'chat-task');
                        }
                        if (data.task_id && data.session_id) {
                            turnTaskId = String(data.task_id);
                            window._sessionChatTaskIds[data.session_id] = data.task_id;
                            _setCaseTaskState(data.session_id, 'running', data.task_id);
                            if (data.session_id === turnSessionId) {
                                window._activeChatTaskId = data.task_id;
                                window._activeChatTaskSessionId = turnSessionId;
                            }
                        }
                        // Connection confirmed: the turn is accepted but the
                        // local intent step is still queued behind case-context
                        // preparation. Show the real wait instead of letting
                        // "analysis" absorb the queueing time.
                        const pendingRouterStep = steps.find(s => s && s.id === optimisticTraceStepIds.router
                            && (s.status === 'pending' || s.status === 'active'));
                        if (pendingRouterStep) {
                            const routerZh = _chatLanguageForSession(turnSessionId) === 'zh';
                            pendingRouterStep.content = routerZh
                                ? '\u5df2\u8fde\u63a5\uff0c\u6b63\u5728\u51c6\u5907\u75c5\u4f8b\u4e0a\u4e0b\u6587\u2026'
                                : 'Connected; preparing the case context...';
                            if (typeof appendStepToChain === 'function') {
                                appendStepToChain(stepsDiv, pendingRouterStep, steps.indexOf(pendingRouterStep));
                            }
                        }
                        if (!text && data.message) text = String(data.message);
                    }
                    if (currentEvent === 'brain_status' && data) {
                        const available = Object.prototype.hasOwnProperty.call(data, 'available')
                            ? data.available : data.brain_available;
                        window.updateBrainStatusIndicator?.(available, data.source || 'agent');
                        continue;
                    }
                    if (currentEvent === 'start' && data) {
                        // The start event carries the dialogue language for
                        // this turn. Keep it on the chat/trace identity only;
                        // the persistent todo dock and every non-dialogue
                        // panel continue to follow the global EN/中 selector.
                        if (data.language && data.language.code) {
                            window._responseLanguage = data.language.code;
                            turnIdentity.responseLanguage = data.language.code;
                            turnIdentity.traceLanguage = data.language.code;
                            if (chainEl) {
                                chainEl.dataset.traceLanguage = data.language.code;
                            }
                            if (typeof _setActiveTodoLang === 'function') {
                                _setActiveTodoLang(effectiveUiLanguage());
                            }
                        }
                        // Start-of-turn clock for the response-time
                        // display in the usage-bar footer. The footer
                        // is rendered when the response is finalized,
                        // so this is the "click send" baseline.
                        window._chatTurnStartTime = Date.now();
                        window._todoTurnToolCount = 0;
                    }
                    if (currentEvent === 'step' && data) {
                        if (data.code === 'llm_unavailable'
                            && typeof window.updateBrainStatusIndicator === 'function') {
                            // The turn fell back to a local answer because the
                            // provider rejected the call; the Brain chip must
                            // stop claiming the model is online.
                            window.updateBrainStatusIndicator(false, 'llm-unavailable');
                        }
                        if (isInternalFollowup) {
                            // Hidden visual-analysis children have no
                            // independent Execution Trace in the chat. The
                            // server persists a sanitized summary into the
                            // parent reply; keeping these steps out of the
                            // DOM prevents screenshot prompts/tool payloads
                            // from escaping into the normal chat stream.
                            steps.push(_traceStepForDisplay(data, turnSessionId, turnIdentity.responseLanguage));
                            continue;
                        }
                        const traced = reconcileOptimisticTraceStep(
                            _traceStepForDisplay(data, turnSessionId, turnIdentity.responseLanguage),
                        );
                        let displayStep = traced.step;
                        let displayStepIndex = traced.index;
                        // A legacy/replayed stream may omit the explicit
                        // phase on the first pending event. If we already made
                        // a client-side final row at the response boundary,
                        // merge the later server row into that same entry.
                        if (_isFinalResponseTraceStep(displayStep) && displayStepIndex < 0) {
                            const existingFinalIndex = steps.findIndex(_isFinalResponseTraceStep);
                            if (existingFinalIndex >= 0) {
                                const existingFinalStep = steps[existingFinalIndex];
                                const retainedId = existingFinalStep.id;
                                Object.assign(existingFinalStep, displayStep);
                                if (retainedId) existingFinalStep.id = retainedId;
                                displayStep = existingFinalStep;
                                displayStepIndex = existingFinalIndex;
                            }
                        }
                        if (_isFinalResponseTraceStep(displayStep)) {
                            if (!deferredFinalSteps.some(step => step === displayStep
                                || (step?.id && String(step.id) === String(displayStep.id)))) {
                                deferredFinalSteps.push(displayStep);
                            }
                            const reportPending = reportUiActionRequested
                                || _hasReportGenerationAction(steps);
                            const waiting = reportPending
                                ? (turnIdentity.responseLanguage === 'zh'
                                    ? '等待报告截图、显示恢复和保存完成'
                                    : 'Waiting for report capture, viewer restore and save')
                                : '';
                            _setFinalResponseTraceStep(
                                displayStep, 'pending', turnIdentity.responseLanguage, waiting,
                            );
                        }
                        const stepIndex = displayStepIndex >= 0 ? displayStepIndex : steps.length;
                        if (displayStepIndex < 0) steps.push(displayStep);
                        if (data.tool === 'ctv_segmentation' && typeof updateTumorTypeSelector === 'function') {
                            const candidate = data.params?.tumor_type
                                || data.arguments?.tumor_type
                                || data.metadata?.tumor_type_used;
                            if (candidate) updateTumorTypeSelector(candidate);
                        }
                        // First step: replace thinking indicator with the live chain
                        if (!chainEl && typeof createLiveThinkingChain === 'function') {
                            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
                            const resumeStart = isResumingTask
                                ? (window._caseChainStartedAt || {})[turnSessionId] : null;
                            const r = createLiveThinkingChain(resumeStart, turnRequestId, turnIdentity.responseLanguage);
                            chainEl = r.chainEl; stepsDiv = r.stepsDiv; headerEl = r.headerEl;
                            // Save the chain start time so a session-resume
                            // rebuild uses the original clock, not Date.now().
                            if (!isResumingTask && turnSessionId) {
                                window._caseChainStartedAt = window._caseChainStartedAt || {};
                                window._caseChainStartedAt[turnSessionId] = Date.now();
                            }
                            window._brachyLiveTrace = {
                                sessionId: turnSessionId, steps, chainEl, stepsDiv, headerEl,
                                requestId: turnRequestId, responseLanguage: turnIdentity.responseLanguage,
                                getTodo: () => todo,
                            };
                        }
                        if (typeof appendStepToChain === 'function') {
                            appendStepToChain(stepsDiv, displayStep, stepIndex);
                        }
                        if (typeof updateChainHeader === 'function') {
                            updateChainHeader(headerEl, steps);
                        }
                        // Persistent todo — but ONLY create it when
                        // the LLM actually starts a multi-step workflow.
                        // The user's complaint: trivial Q&A (e.g. a
                        // casual greeting) was showing the execution
                        // progress todo list with weird numbers like
                        // "27.6s" — there was no actual workflow to
                        // track. The LLM signals
                        // "I need multiple steps" by emitting a step
                        // event with type === 'tool'. Until then, no
                        // todo list appears. This makes the todo
                        // genuinely LLM-driven: the LLM "decides" by
                        // calling tools.
                        if (typeof _todoCreate === 'function') {
                            if (!todo && chainEl && data.type === 'tool' && data.tool) {
                                todo = _todoCreate();
                                // BOTTOM-OF-CHAT (2026-06-15): the user
                                // complained the todo list was "in the
                                // side" of a chat message. Move it to a
                                // fixed/sticky panel at the bottom of
                                // the chat column, just above the input
                                // area. This is a single global
                                // workflow indicator, not a per-message
                                // widget. The DOM target is
                                // #chatTodoDock (defined in HTML next to
                                // #chatInput).
                                const dock = document.getElementById('chatTodoDock');
                                if (dock) {
                                    // Single-owner dock: drop any previous
                                    // turn's root before attaching this one.
                                    dock.replaceChildren(todo.root);
                                    dock.style.display = '';
                                } else {
                                    // Fallback: append to the message
                                    // wrapper (old behavior).
                                    const wrapper = chainEl.parentElement;
                                    if (wrapper) wrapper.appendChild(todo.root);
                                }
                                // Pre-populate with the predicted workflow
                                // (ctv → oar → planning → eval → report)
                                // so the user can see "what's coming"
                                // before events arrive.
                                try { _todoSeed(todo, window._lastUserMessage || ''); } catch (_) {}
                                scrollToBottom();
                            }
                            if (todo) {
                                const todoStep = _isFinalResponseTraceStep(displayStep)
                                    ? Object.assign({}, data, {
                                        id: displayStep.id,
                                        phase: 'final_response',
                                        status: 'pending',
                                        content: displayStep.content,
                                    })
                                    : data;
                                _todoUpdateFromStep(todo, todoStep);
                                // `Final Response` is a protocol milestone,
                                // not proof that the user can already see the
                                // answer. Keep its progress row active until
                                // the final response lifecycle settles it.
                            }
                            // MARK FOR RETRY: just record that a
                            // Quality Review reject happened. We do NOT
                            // wipe the response bubble here — wiping
                            // eagerly is risky because if the LLM retry
                            // produces no text, the user loses the
                            // first response. Instead, the actual wipe
                            // happens LAZILY in the text_chunk handler:
                            // when the FIRST text_chunk arrives after
                            // the retry marker, we know the LLM is
                            // actually regenerating text, and we wipe
                            // the previous response at that point.
                            if (data.type === 'review' && data.status === 'warning') {
                                window._pendingReviewRetry = true;
                            }
                            if (data.type === 'thinking' && data.title === 'Review Feedback') {
                                window._pendingReviewRetry = true;
                            }
                        }
                        // Show tool progress (pending / terminal)
                        const toolCompleted = _isTerminalToolStatus(data.status);
                        const toolFailed = _isFailedToolStatus(data.status);
                        if (data.type === 'tool' && _isInFlightToolStatus(data.status)) {
                            // If this is the SAME tool already showing progress,
                            // just update its content — don't create a new row.
                            if (progressEl && progressEl.parentNode && lastToolName === (data.tool || 'unknown')) {
                                const existingText = progressEl.querySelector('.tool-progress-text');
                                if (existingText && data.content) {
                                    existingText.textContent = data.content;
                                }
                            } else {
                                if (progressEl && progressEl.parentNode) {
                                    progressEl.style.opacity = '0.3';
                                    progressEl.style.transform = 'scale(0.98)';
                                }
                                lastToolName = data.tool || 'unknown';
                                // Execution Trace and the persistent todo list
                                // are the single progress surface for tools.
                                progressEl = null;
                            }
                        } else if (data.type === 'tool' && (toolCompleted || toolFailed)) {
                            if (progressEl && typeof updateToolProgress === 'function') {
                                updateToolProgress(progressEl, lastToolName, data.status, data.result);
                            }
                            // Execute UI controller actions
                            // Actions live in data.metadata.actions (from ToolResult.metadata),
                            // NOT in data.result (which is the human-readable message string).
                            if (toolCompleted && data.tool === 'ui_controller') {
                                try {
                                    let actions = null;
                                    const md = data.metadata || {};
                                    if (Array.isArray(md.actions)) {
                                        actions = md.actions;
                                    } else if (typeof data.result === 'string') {
                                        // Fallback: try parsing result as JSON
                                        const parsed = JSON.parse(data.result);
                                        if (Array.isArray(parsed.actions)) actions = parsed.actions;
                                    } else if (data.result && Array.isArray(data.result.actions)) {
                                        actions = data.result.actions;
                                    }
                                    if (Array.isArray(actions) && actions.length > 0) {
                                        if (actions.some(action => String(action?.target || '') === 'report.autofill')) {
                                            reportUiActionRequested = true;
                                        }
                                        uiDebugLog('[SSE-UI] Executing', actions.length, 'UI actions');
                                        if (typeof _executeUIActionsWithProgress === 'function') {
                                            const actionTask = _executeUIActionsWithProgress(actions, {
                                                sessionId: turnSessionId,
                                                requestId: turnRequestId,
                                            });
                                            uiActionTasks.push(Promise.resolve(actionTask).then(group => {
                                                uiActionResults.push(...(Array.isArray(group) ? group : [group]));
                                                return group;
                                            }));
                                        } else {
                                            const actionTask = Promise.all(actions.map(a => _executeUIAction(a, {
                                                sessionId: turnSessionId,
                                            })));
                                            uiActionTasks.push(actionTask.then(group => {
                                                uiActionResults.push(...group);
                                                return group;
                                            }));
                                        }
                                    }
                                } catch (e) { console.warn('[SSE-UI] Failed to parse ui_controller result:', e); }
                            }
                            // Intercept ui_screenshot: capture the target element,
                            // upload to server, and display in chat.
                            if (toolCompleted && data.tool === 'ui_screenshot' && data.metadata) {
                                const _ssCmd = data.metadata.screenshot_command || data.metadata;
                                const _ssPlan = data.metadata.screenshot_plan
                                    || _ssCmd.plan
                                    || {
                                        mode: 'chat',
                                        views: [{
                                            target: _normalizeScreenshotRequestTarget(
                                                _ssCmd.target || 'full',
                                                _ssCmd.question || '',
                                            ),
                                        }],
                                        question: _ssCmd.question || '',
                                    };
                                const _ssQuestion = _ssPlan.question || _ssCmd.question || '';
                                const _ssTarget = _ssPlan.views?.[0]?.target
                                    || _normalizeScreenshotRequestTarget(_ssCmd.target || 'full', _ssQuestion);
                                // Providers may emit the same completed tool
                                // step more than once with different event IDs
                                // (tool result + replay + review pass). Dedupe
                                // by the semantic capture plan, not by the
                                // transport step ID, otherwise one request
                                // creates repeated report/chat figures.
                                const _ssFingerprint = JSON.stringify({
                                    mode: _ssPlan.mode || 'chat',
                                    layout: _ssPlan.layout || 'auto',
                                    target: _ssPlan.target || _ssTarget,
                                    question: _ssQuestion,
                                    views: (Array.isArray(_ssPlan.views) ? _ssPlan.views : []).map(view => {
                                        if (typeof view === 'string') return view;
                                        const item = view || {};
                                        return {
                                            target: item.target || item.viewer || '',
                                            viewer: item.viewer || '',
                                            slice: item.slice ?? item.slice_index ?? null,
                                            camera: item.camera || item.camera_direction || '',
                                            focus: item.focus || item.object_id || '',
                                        };
                                    }),
                                    object_ids: _ssPlan.object_ids || [],
                                    data_tree_node_ids: _ssPlan.data_tree_node_ids || [],
                                    focus: _ssPlan.focus || {},
                                    request_intent: _ssPlan.request_intent || _ssPlan.requestIntent || '',
                                    semantic_target: _ssPlan.semantic_target || _ssPlan.semanticTarget || '',
                                    semantic_targets: _ssPlan.semantic_targets || _ssPlan.semanticTargets || [],
                                    target_query: _ssPlan.target_query || _ssPlan.targetQuery || '',
                                    target_source: _ssPlan.target_source || _ssPlan.targetSource || '',
                                    preserve_current_view: _ssPlan.preserve_current_view === true
                                        || _ssPlan.preserveCurrentView === true,
                                    visual_purpose: _ssPlan.visual_purpose || _ssPlan.visualPurpose || '',
                                    annotation_policy: _ssPlan.annotation_policy || _ssPlan.annotationPolicy || '',
                                });
                                const _ssKey = `${turnRequestId}|${_ssFingerprint}`;
                                if (screenshotTaskKeys.has(_ssKey)) {
                                    uiDebugLog('[SSE-STEP] Ignoring duplicate screenshot completion:', _ssKey);
                                } else {
                                    screenshotTaskKeys.add(_ssKey);
                                uiDebugLog('[SSE-STEP] Intercepting ui_screenshot, target:', _ssTarget);
                                try {
                                    const captureTask = screenshotCaptureQueue.then(() =>
                                        _interceptScreenshot(_ssTarget, _ssQuestion, screenshotGallery, {
                                            sessionId: turnSessionId,
                                            requestId: turnRequestId,
                                            messageId: turnAssistantMessageId,
                                            responseLanguage: turnIdentity.responseLanguage,
                                            mode: _ssPlan.mode || screenshotGallery.mode || 'chat',
                                            plan: _ssPlan,
                                        })
                                    );
                                    screenshotCaptureQueue = captureTask.then(
                                        () => undefined,
                                        () => undefined,
                                    );
                                    screenshotTasks.push(captureTask.then(result => {
                                        if (Array.isArray(result?.attachments)) {
                                            // Preserve a verified Data Tree screenshot if a later Viewer
                                            // capture fails. Its partial-evidence status is explained by
                                            // the linked child; it is never upgraded into a Viewer claim.
                                            screenshotResults.push(...result.attachments);
                                        } else if (result?.success && result.url) {
                                            screenshotResults.push(result);
                                        }
                                        if (result?.userMessage) {
                                            presentationMessages.push(String(result.userMessage));
                                        }
                                        return result;
                                    }));
                                } catch (e) {
                                    console.warn('[SSE-STEP] Screenshot interception failed:', e);
                                }
                                }
                            }
                            // ``ui_content`` presents durable Session-owned
                            // data (report figures, planning/DVH, Data Tree,
                            // chat history, etc.) in the same reply. It is not
                            // a screenshot capture and must not be routed to a
                            // browser canvas or emitted as a standalone log.
                            if (toolCompleted && data.tool === 'ui_content' && data.metadata) {
                                const _contentCmd = data.metadata.content_command || data.metadata;
                                // Replay/reconnect can assign a new transport
                                // event id to the same semantic request. The
                                // content itself, not that event id, owns the
                                // dedupe key; otherwise a completed+done pair
                                // can render two attachments or two panels.
                                const _contentKey = JSON.stringify({
                                    request: turnRequestId,
                                    target: _contentCmd.target || 'session_summary',
                                    planning_id: _contentCmd.planning_id || '',
                                    presentation: _contentCmd.presentation || 'auto',
                                    selection: _contentCmd.selection || null,
                                });
                                if (sessionContentTaskKeys.has(_contentKey)) {
                                    uiDebugLog('[SSE-STEP] Ignoring duplicate Session content completion:', _contentKey);
                                } else {
                                    sessionContentTaskKeys.add(_contentKey);
                                    const _fallbackLanguage = String(turnIdentity.responseLanguage || '').toLowerCase().startsWith('zh')
                                        ? '当前 Session 中暂时没有可呈现的对应数据。'
                                        : 'The requested content is not currently available in this Session.';
                                    sessionContentTasks.push(Promise.resolve(
                                        typeof window.presentSessionContent === 'function'
                                            ? window.presentSessionContent(_contentCmd, screenshotGallery, {
                                                sessionId: turnSessionId,
                                                requestId: turnRequestId,
                                                messageId: turnAssistantMessageId,
                                                responseLanguage: turnIdentity.responseLanguage,
                                            })
                                            : {
                                                success: false,
                                                error: 'session_content_bridge_unavailable',
                                                userMessage: _fallbackLanguage,
                                                attachments: [],
                                            },
                                    ).then(result => {
                                        if (result?.success && Array.isArray(result.attachments)) {
                                            // Persist the structured visual-analysis request
                                            // with the attachment. A reply attachment may be
                                            // a durable image from an earlier turn and does
                                            // not otherwise carry a capture-specific flag.
                                            sessionContentResults.push(...result.attachments.map(attachment => Object.assign(
                                                {},
                                                attachment,
                                                {
                                                    visual_analysis: attachment?.visual_analysis === true
                                                        || result.analysis === true,
                                                },
                                            )));
                                        }
                                        if (result?.userMessage) {
                                            presentationMessages.push(String(result.userMessage));
                                        }
                                        return result;
                                    }).catch(error => {
                                        console.warn('[SSE-STEP] Session content presentation failed:', error);
                                        presentationMessages.push(_fallbackLanguage);
                                        return { success: false, error: 'session_content_unavailable' };
                                    }));
                                }
                            }
                            // Count completed tool calls for the usage-bar
                            // footer. We count BOTH done and error because
                            // an errored call is still a call the user
                            // spent tokens on. (success vs failure is
                            // already visible in the thinking chain.)
                            if (window._todoTurnToolCount === undefined) {
                                window._todoTurnToolCount = 0;
                            }
                            window._todoTurnToolCount += 1;
                            // When a planning tool finishes, pull the latest
                            // plan summary from the server and re-render the
                            // metrics panel, DVH chart, OAR table, data tree,
                            // 3D meshes, and dose overlay. Without this, the
                            // server-side pipeline runs successfully but the
                            // user sees no metrics, no DVH, no 3D seeds.
                            //
                            // CRITICAL: only fire this ONCE per turn, on the
                            // LAST planning tool. The SSE stream emits 5-10
                            // step events for ctv_segmentation / oar_segmentation
                            // / planning_pipeline (each sub-step of the
                            // pipeline is a separate "step" event). If we
                            // called refreshPlanningUI for each one, the DVH
                            // would re-render every 200ms and the 3D viewer
                            // would re-init constantly — visible as the DVH
                            // flashing and the "Metrics panel sinking".
                            // Only trigger refreshPlanningUI on the FINAL
                            // planning tool — not on every sub-step.
                            // The planning_pipeline with step:full runs
                            // CTV→OAR→trajectory→seed→dose internally.
                            // Triggering on ctv_segmentation done (the
                            // first to complete) would refresh before
                            // dose data exists. We wait for the LAST
                            // tool in the chain: planning_pipeline done
                            // (which fires AFTER all sub-steps drain).
                            const FINAL_PLANNING_TOOLS = ['planning_pipeline', 'dose_evaluation'];
                            // Sub-steps of planning_pipeline carry parent_tool
                            // (e.g. dose_eval done carries tool:"dose_eval",
                            // parent_tool:"planning_pipeline"). These are the
                            // actual terminal events; matching on parent_tool
                            // ensures refreshPlanningUI fires even when the
                            // top-level planning_pipeline done event is missing.
                            const LAST_PLANNING_SUBSTEPS = ['dose_eval', 'dose_calc'];
                            const SEG_TOOLS = [
                                'ctv_segmentation',
                                'oar_segmentation',
                                'biomedparse_segmentation',
                            ];
                            const isPlanDone = toolCompleted && (
                                FINAL_PLANNING_TOOLS.includes(data.tool) ||
                                FINAL_PLANNING_TOOLS.includes(data.parent_tool || '') ||
                                LAST_PLANNING_SUBSTEPS.includes(data.tool || '')
                            );
                            uiDebugLog('[SSE-STEP]', 'type:', data.type, 'tool:', data.tool, 'parent_tool:', data.parent_tool, 'status:', data.status, 'planDone:', isPlanDone);
                            if (isPlanDone) {
                                uiDebugLog('[SSE-STEP] Planning tool/substep done:', data.tool, 'parent_tool:', data.parent_tool, '- scheduling refreshPlanningUI');
                                _scheduleCasePlanningRefresh(turnSessionId, 300);
                            }
                            // Chat-driven guide generation does not emit a new
                            // Planning run. Hydrate its persisted mesh
                            // explicitly so a successful tool result is also
                            // visible in the Data Tree, 3D Viewer, and MPR
                            // projection. Keep this out of isPlanDone: a guide
                            // refresh must not invalidate the dose overlay or
                            // start a second guide generation.
                            // SEGMENTATION TOOLS: after CTV/OAR seg completes,
                            // load label volumes so masks appear in viewer + data tree.
                            // Without this, masks are stored server-side but never
                            // fetched by the frontend.
                            // Different SSE producers use tool, tool_name,
                            // function_name, or parent_tool for the same
                            // terminal event.  Accept all canonical forms so
                            // an OAR completion can never lose its immediate
                            // viewer hydration solely because of its envelope.
                            const completedSegmentationTool = String(
                                data.tool || data.tool_name || data.function_name
                                || data.function || data.parent_tool || data.parentTool || '',
                            ).trim().toLowerCase();
                            if (toolCompleted && SEG_TOOLS.includes(completedSegmentationTool)) {
                                if (completedSegmentationTool === 'biomedparse_segmentation') {
                                    // Open-ended masks are not part of the CTV/OAR
                                    // label-volume payload.  Hydrate their own
                                    // persisted catalogue immediately so a chat
                                    // request such as "segment the pancreas" has
                                    // the same Data Tree/2D/3D delivery contract
                                    // as a model CTV or OAR result.
                                    const genericScope = typeof window._captureViewerDataScope === 'function'
                                        ? window._captureViewerDataScope(turnSessionId)
                                        : { sessionId: turnSessionId, dataGeneration: null };
                                    if (typeof window.hydrateGenericMasksFromServer === 'function') {
                                        void window.hydrateGenericMasksFromServer(genericScope)
                                            .then(() => {
                                                if (String(activeSessionId || '') !== String(turnSessionId || '')) return;
                                                window.renderDataTree?.();
                                                window.loadAllSlices?.();
                                                window.requestViewerVisualRefresh?.('generic-segmentation-complete');
                                            })
                                            .catch(error => console.warn(
                                                '[SSE-STEP] generic segmentation hydration failed:',
                                                error,
                                            ));
                                    }
                                    scrollToBottom();
                                } else {
                                    const segmentationKind = completedSegmentationTool === 'oar_segmentation' ? 'oar' : 'ctv';
                                    uiDebugLog('[SSE-STEP] Segmentation done:', completedSegmentationTool, '- hydrating viewer artifacts');
                                    // The workspace may publish the tool result before the
                                    // label endpoint and 3D mesh service are ready. This
                                    // session-bound job retries the short publication race,
                                    // paints 2D/Data Tree first, then builds true meshes in
                                    // the background without extending the chat task.
                                    if (typeof window.hydrateCompletedSegmentationArtifacts === 'function') {
                                        void window.hydrateCompletedSegmentationArtifacts({
                                            sessionId: turnSessionId,
                                            kind: segmentationKind,
                                            reason: 'chat-segmentation-complete',
                                        }).then(() => {
                                            // The label endpoint and mesh worker can
                                            // complete in separate turns. Reconcile
                                            // once more after both have published so a
                                            // cold session cannot leave the Data Tree
                                            // or MPR overlays one event behind.
                                            if (String(activeSessionId || '') !== String(turnSessionId || '')) return;
                                            window.reconcileSegmentationViewerState?.({
                                                sessionId: turnSessionId,
                                                reason: 'chat-segmentation-hydrated',
                                            });
                                        }).catch(error => console.warn('[SSE-STEP] segmentation artifact hydration failed:', error));
                                    } else if (typeof loadLabelVolumes === 'function') {
                                        loadLabelVolumes({
                                            sessionId: turnSessionId,
                                            forceFresh: true,
                                            preserveViewerState: true,
                                            resetPresentation: true,
                                        }).then(() => {
                                            if (String(activeSessionId || '') !== String(turnSessionId || '')) return;
                                            window.reconcileSegmentationViewerState?.({
                                                sessionId: turnSessionId,
                                                reason: 'chat-labels-hydrated',
                                            });
                                        }).catch(error => console.warn('[SSE-STEP] fallback label load failed:', error));
                                    }
                                }
                            }
                        }
                        scrollToBottom();
                    } else if (currentEvent === 'text_chunk' && data && data.text) {
                        responseText += data.text;
                        // Keep model draft chunks out of the answer. They can
                        // precede tool calls or a review retry and are not yet
                        // an approved user-facing response.
                    } else if (currentEvent === 'final_text_chunk' && data && data.text) {
                        // This event is emitted after all required review work.
                        // Render it in one stable bubble so the user sees
                        // genuine incremental progress without duplicate
                        // assistant messages.
                        if (!finalTextStreamStarted) {
                            finalTextStreamStarted = true;
                            responseText = '';
                            if (!isInternalFollowup
                                && !_hasReportGenerationAction(steps)
                                && !responseEl && typeof createStreamingResponse === 'function') {
                                if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
                                responseEl = createStreamingResponse(turnRequestId, turnAssistantMessageId);
                            }
                        }
                        responseText += String(data.text);
                        if (!isInternalFollowup && !_hasReportGenerationAction(steps)
                            && responseEl && typeof updateStreamingResponse === 'function') {
                            responseEl.classList.add('is-streaming');
                            responseEl.setAttribute('aria-busy', 'true');
                            updateStreamingResponse(responseEl, responseText);
                        }
                        scrollToBottom();
                    } else if (currentEvent === 'response' && data
                        && Object.prototype.hasOwnProperty.call(data, 'response')) {
                        // The final response event is emitted only after the
                        // required review gate. Create the answer bubble here,
                        // rather than on the first draft chunk.
                        if (!finalResponseReceived) {
                            finalResponseReceived = true;
                        } else {
                            continue;
                        }
                        responseText = data.response;
                        if (!isInternalFollowup) {
                            finalResponseStep = _ensureFinalResponseTraceStep(
                                steps,
                                deferredFinalSteps,
                                turnRequestId,
                                turnIdentity.responseLanguage,
                                stepsDiv,
                                headerEl,
                                reportUiActionRequested || _hasReportGenerationAction(steps),
                            );
                        }
                        const deferUntilUIActionsFinish = reportUiActionRequested
                            || _hasReportGenerationAction(steps);
                        if (!isInternalFollowup && !deferUntilUIActionsFinish
                            && !responseEl && typeof createStreamingResponse === 'function') {
                            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
                            responseEl = createStreamingResponse(turnRequestId, turnAssistantMessageId);
                        }
                        if (!isInternalFollowup && !deferUntilUIActionsFinish
                            && responseEl && typeof updateStreamingResponse === 'function') {
                            updateStreamingResponse(responseEl, responseText);
                        }
                        if (responseEl) {
                            responseEl.classList.remove('is-streaming');
                            responseEl.removeAttribute('aria-busy');
                        }
                        window._lastResponseText = null;
                        // usage-bar footer (token counts, latency, tool
                        // call count) once the response is finalized.
                        // The server already emits this in the response
                        // event; we just stash it for later rendering.
                        if (data.llm_meta) {
                            window._lastLLMMeta = data.llm_meta;
                            if (Number(data.llm_meta.llm_calls || 0) > 0
                                && typeof window.updateBrainStatusIndicator === 'function') {
                                // A real model call succeeded; recover the chip
                                // from a previous offline state.
                                window.updateBrainStatusIndicator(true, 'llm-response');
                            }
                        }
                        // Some providers close the stream immediately after
                        // the final response and do not emit a separate
                        // terminal step for the pipeline. The response is
                        // already gated by the server, so it is a safe second
                        // completion boundary. The refresh itself remains
                        // case-owned and retries HTTP 202 while arrays are
                        // being committed.
                        if (turnSawPlanningWork) {
                            uiDebugLog('[SSE-response] Planning work detected; scheduling result refresh');
                            _scheduleCasePlanningRefresh(turnSessionId, 350);
                        }
                        if (turnSawSurgicalGuideWork) {
                            // The tool completion event normally schedules
                            // this already. Re-arming at the response boundary
                            // covers a replay/publication race without
                            // issuing duplicate requests while the first
                            // case-owned load is still pending.
                            _scheduleCaseSurgicalGuideRefresh(turnSessionId, 0);
                        }
                    } else if (currentEvent === 'error' && data && data.message) {
                        turnFailed = true;
                        if (turnPlanningRunStarted) {
                            window.dispatchEvent(new CustomEvent('brachybot:planning-run-finished', {
                                detail: {
                                    sessionId: turnSessionId,
                                    requestId: turnRequestId,
                                    incomplete: true,
                                    stage: 'stream_error',
                                },
                            }));
                        }
                        try { window.clearPlanningPreview?.('stream-error'); } catch (_) {}
                        _setCaseTaskState(turnSessionId, 'failed', null);
                        const failureCode = String(data.code || '');
                        console.warn('[chat] SSE request failed', {
                            sessionId: turnSessionId,
                            message: data.message,
                            code: failureCode,
                        });
                        // Keep an SSE error within the owning response lifecycle.
                        // Raw provider/tool text is intentionally not rendered in
                        // normal chat; it remains available to developers in the
                        // console and through the server-side log correlation.
                        if (!responseText) {
                            responseText = isInternalFollowup
                                ? _visualEvidenceFallbackResponse(
                                    opts.visualEvidence || [],
                                    turnSessionId,
                                    turnIdentity.responseLanguage,
                                    text,
                                )
                                : _chatUserVisibleFailure(turnSessionId, 'request', failureCode);
                            finalResponseReceived = true;
                            // A failed turn must not leave a "done / Response
                            // delivered" row in the visible trace while the
                            // reply bubble shows an error.
                            for (let index = steps.length - 1; index >= 0; index -= 1) {
                                const row = steps[index];
                                if (!row || String(row.type || '') !== 'assistant') continue;
                                if (_isTerminalToolStatus(row.status)) {
                                    row.status = 'error';
                                    row.content = responseText;
                                    if (typeof appendStepToChain === 'function' && stepsDiv) {
                                        appendStepToChain(stepsDiv, row, index);
                                    }
                                }
                                break;
                            }
                        }
                    } else if (currentEvent === 'done') {
                        // Server says stream is complete
                        turnCompleted = true;
                        turnCancelled = Boolean(data?.cancelled);
                        const terminalStatus = turnCancelled ? 'cancelled' : (turnFailed ? 'failed' : 'completed');
                        if (turnCancelled || !uiActionTasks.length) {
                            _setCaseTaskState(turnSessionId, terminalStatus, null);
                        }
                        delete window._detachedChatTasks[turnSessionId];
                        try { window.clearPlanningPreview?.('stream-complete'); } catch (_) {}
                        if (turnCancelled) {
                            if (turnPlanningRunStarted) {
                                window.dispatchEvent(new CustomEvent('brachybot:planning-run-finished', {
                                    detail: {
                                        sessionId: turnSessionId,
                                        requestId: turnRequestId,
                                        incomplete: true,
                                        stage: 'cancelled',
                                    },
                                }));
                            }
                            // A replaying browser can receive the terminal
                            // cancellation event without having initiated the
                            // Stop click itself. Do not manufacture a blank
                            // assistant answer from that terminal state.
                            cancelTurnUi('Stopped');
                            break readLoop;
                        }
                        // FALLBACK: if planning tools ran but
                        // refreshPlanningUI was never triggered (e.g.
                        // the FINAL_PLANNING_TOOLS check didn't fire
                        // because the step event format changed),
                        // trigger a refresh now on stream completion.
                        const _planningToolsInSteps = steps.filter(s => _isTerminalToolStatus(s.status)
                            && PLANNING_EVENT_TOOLS.has(String(s.tool || '')));
                        uiDebugLog('[SSE-done] planning tools in steps:', _planningToolsInSteps.map(s => s.tool), 'sawPlanningWork:', turnSawPlanningWork);
                        if (_planningToolsInSteps.length > 0 || turnSawPlanningWork) {
                            uiDebugLog('[SSE-done] Triggering fallback refreshPlanningUI');
                            _scheduleCasePlanningRefresh(turnSessionId, 500);
                        }
                        const _guideToolsInSteps = steps.filter(isCompletedGuideEvent);
                        if (_guideToolsInSteps.length > 0 || turnSawSurgicalGuideWork) {
                            _scheduleCaseSurgicalGuideRefresh(turnSessionId, 0);
                        }
                        // Do not wait for a post-terminal chunk.  Flask may
                        // keep the HTTP connection reusable, but the chat
                        // turn is complete at this protocol boundary.
                        break readLoop;
                    }
                }
            }
        }

        // A case selection detached this browser stream.  Save the completed
        // response and thinking chain into the owning session's messages array
        // so the user sees the full transcript when they return.  Do not run
        // terminal screenshot/final-response against the newly visible case.
        if (activeSessionId !== turnSessionId) {
            const detachedResponse = responseText
                || (finalResponseReceived ? _chatUserVisibleFailure(turnSessionId, 'response') : null);
            if (detachedResponse && typeof saveSessionMessage === 'function') {
                saveSessionMessage('bot-response', detachedResponse, null, Date.now(), turnSessionId, _buildTurnMeta(turnIdentity));
            }
            try {
                saveSessionMessage('thinking', '', steps, Date.now(), turnSessionId, {
                    requestId: turnRequestId,
                    messageId: `trace-${turnRequestId}`,
                    messageKind: 'execution_trace',
                    turnSequence: 1,
                    replyToMessageId: turnAssistantMessageId,
                    responseLanguage: turnIdentity.responseLanguage,
                    traceLanguage: turnIdentity.responseLanguage,
                });
            } catch (_) {}
            return;
        }

        if (turnCancelled) return;

        // Keep screenshot capture/upload inside the same logical turn. This
        // guarantees that the hidden multimodal follow-up is queued before the
        // stream transitions to idle and starts flushing follow-up requests.
        if (screenshotTasks.length) {
            await Promise.allSettled(screenshotTasks);
        }
        if (sessionContentTasks.length) {
            await Promise.allSettled(sessionContentTasks);
        }
        if (uiActionTasks.length) {
            const settled = await _awaitChatUIActions(uiActionTasks, turnAbortController?.signal);
            if (settled.some(result => result.status === 'rejected')) {
                uiActionResults.push({ success: false });
            }
        }
        if (reportUiActionRequested || _hasReportGenerationAction(steps)) {
            const reportActionFailed = (uiActionResults.length === 0
                    || uiActionResults.some(result => result === false
                        || result?.success === false
                        || result?.stale === true));
            if (reportActionFailed) {
                turnFailed = true;
                const failedAction = uiActionResults.find(result => result?.success === false);
                responseText = failedAction?.stage === 'report_capture'
                    && typeof reportCaptureFailureMessage === 'function'
                    ? reportCaptureFailureMessage(failedAction.captureFailure, turnIdentity.responseLanguage)
                    : _reportGenerationFailureMessage(turnSessionId, failedAction);
                finalResponseReceived = true;
            } else {
                responseText = turnIdentity.responseLanguage === 'zh'
                    ? '报告已重新生成：正文、表格和标准图件已更新并保存到当前 Session，截图时的临时显示设置已恢复。'
                    : 'The report was regenerated: text, tables and canonical figures were updated and saved to the current Session, and temporary capture display settings were restored.';
                finalResponseReceived = true;
            }
        }
        if (String(activeSessionId || '') !== turnSessionId) return;
        if (!isInternalFollowup) {
            finalResponseStep = _ensureFinalResponseTraceStep(
                steps,
                deferredFinalSteps,
                turnRequestId,
                turnIdentity.responseLanguage,
                stepsDiv,
                headerEl,
                reportUiActionRequested || _hasReportGenerationAction(steps),
            );
        }
        if (uiActionTasks.length) {
            _setCaseTaskState(turnSessionId, turnFailed ? 'failed' : 'completed', null);
        }
        // Screenshot/tool events may be replayed after a reconnect with new
        // event or attachment ids.  Preserve one durable artifact per URL in
        // the assistant reply; otherwise the same image is rendered and
        // persisted repeatedly with identical captions.
        const presentationAttachments = [];
        const presentationAttachmentKeys = new Set();
        const presentationAttachmentUrls = new Set();
        const presentationSemanticKeys = new Set();
        [...screenshotResults, ...sessionContentResults].forEach(item => {
            if (!item || typeof item !== 'object') return;
            // Attachment IDs are stable across a replay; URLs can be freshly
            // minted for the same artifact. Track both without letting a new
            // URL conceal an already-seen attachment identity.
            const key = String(item.id || item.attachment_id || item.url || '').trim();
            const urlKey = String(item.url || '').trim();
            const metadata = item.view_metadata || item.viewMetadata || {};
            const semanticKey = typeof window.chatAttachmentSemanticKey === 'function'
                ? window.chatAttachmentSemanticKey(item)
                : [
                    String(item.mode || screenshotGallery.mode || 'chat'),
                    String(item.planning_id || item.planningId || ''),
                    String(metadata.figure_group || metadata.figureGroup || ''),
                    String(metadata.figure_number || metadata.figureNumber || ''),
                    String(metadata.subfigure || ''),
                    String(metadata.capture_role || metadata.captureRole || ''),
                    String(metadata.index ?? ''),
                    String(item.request_id || turnIdentity?.requestId || ''),
                    String(item.target || ''),
                ].join('|');
            if (!key || presentationAttachmentKeys.has(key)
                || (urlKey && presentationAttachmentUrls.has(urlKey))
                || (semanticKey && presentationSemanticKeys.has(semanticKey))) return;
            presentationAttachmentKeys.add(key);
            if (urlKey) presentationAttachmentUrls.add(urlKey);
            if (semanticKey) presentationSemanticKeys.add(semanticKey);
            presentationAttachments.push(item);
        });
        const responseContract = window._lastLLMMeta?.response_contract || null;
        const forceVisualAnalysis = _visualTurnRequiresExplanation(responseContract);
        const visualContentResults = sessionContentResults.filter(item =>
            item && item.url && (
                _visualAttachmentRequiresAnalysis(item) || forceVisualAnalysis
            )
        );

        // A screenshot requested for explanation is visual context, not the
        // final answer. Send exactly one hidden multimodal follow-up after all
        // captures have uploaded. The hidden request is intentionally not a
        // new screenshot command, so the model must analyze the image and the
        // completeness checker can validate the actual user request.
        const allVisualEvidence = screenshotResults.concat(visualContentResults);
        // The screenshot tool's semantic contract decides whether the image
        // needs interpretation. Do not infer that decision from a phrase
        // whitelist in the user's text: the same question can be phrased in
        // any language, and an imperative capture can explicitly opt out.
        const shouldAnalyzeVisualEvidence = !isInternalFollowup
            && allVisualEvidence.some(item => item && item.url && (
                _visualAttachmentRequiresAnalysis(item) || forceVisualAnalysis
            ));
        const visualAnalysisQueued = shouldAnalyzeVisualEvidence && _queueVisualAnalysisFollowUp(
            allVisualEvidence,
            text,
            turnIdentity,
            {
                sessionId: turnSessionId,
                screenshotMode: screenshotGallery.mode || 'chat',
                includeAll: true,
                forceAnalysis: forceVisualAnalysis,
                preliminaryResponse: [
                    window._lastLLMMeta?.multi_intent_query ? responseText : '',
                    presentationMessages.filter(Boolean).slice(-1)[0] || '',
                ].filter(Boolean).join('\n\n'),
                multiIntentQuery: window._lastLLMMeta?.multi_intent_query === true,
                onFollowupState: (state, info = {}) => {
                    visualFollowupState = String(state || '');
                    visualFollowupKey = String(info.followupKey || '');
                },
            },
        );
        // The parent presentation turn owns the images, while the linked
        // child owns their interpretation. Keep that two-stage contract even
        // if the child was already queued by an SSE replay; otherwise an
        // acknowledgement can overwrite the eventual analysis in the same
        // assistant reply.
        const visualAnalysisContinuation = shouldAnalyzeVisualEvidence;
        visualFinalResponsePending = shouldAnalyzeVisualEvidence
            && ['queued', 'running'].includes(visualFollowupState);
        if (!isInternalFollowup) {
            finalResponseStep = _ensureFinalResponseTraceStep(
                steps,
                deferredFinalSteps,
                turnRequestId,
                turnIdentity.responseLanguage,
                stepsDiv,
                headerEl,
                reportUiActionRequested || _hasReportGenerationAction(steps),
            );
            if (visualFinalResponsePending && finalResponseStep) {
                visualFinalResponsePending = _registerPendingVisualFinalResponse({
                    sessionId: turnSessionId,
                    requestId: turnRequestId,
                    assistantMessageId: turnAssistantMessageId,
                    responseLanguage: turnIdentity.responseLanguage,
                    steps,
                    step: finalResponseStep,
                    stepsDiv,
                    headerEl,
                    followupKey: visualFollowupKey,
                    todo,
                });
            } else if (visualFollowupState === 'done') {
                // A replay of an already-completed child should not leave the
                // parent row spinning when the visible answer is already in
                // this transcript.
                finalReplyCommitted = true;
            }
        }
        if (visualAnalysisQueued) {
            uiDebugLog('[visual-followup] queued for parent request:', turnIdentity?.requestId || '');
        }

        // No steps arrived — clean up the thinking indicator
        if (!chainEl) {
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
        }

        // Do not fold here. This block runs before the final response bubble
        // and its usage footer are committed to the DOM. The terminal stream
        // boundary alone is not a user-visible reply boundary; the fold is
        // performed after the response/footer below (and on the terminal
        // error path in finally).

        // BUG FIX 2026-06-16 (todo accumulation): if the LLM never
        // called any tool, no todo was created for this turn. Hide
        // the dock so the user doesn't see a stale "Progress"
        // header from a previous turn. We already wiped the dock
        // at the START of sendChat, but if a todo was created and
        // then folded, it lingers until next turn; we leave that
        // folded one alone (user can re-expand).
        if (!todo) {
            try {
                const _dock = document.getElementById('chatTodoDock');
                if (_dock) {
                    _dock.innerHTML = '';
                    _dock.style.display = 'none';
                }
            } catch (_) {}
        }

        // Hide standalone tool progress messages ("ctv_segmentation
        // completed", "planning_pipeline completed", etc.) — they're
        // redundant with the Execution Trace and clutter the final
        // response area. The thinking chain already shows all steps.
        if (window._toolProgressEls && window._toolProgressEls.length) {
            window._toolProgressEls.forEach(el => {
                try { el.style.display = 'none'; } catch (_) {}
            });
            window._toolProgressEls = [];
        }

        // Finalize response element (markdown render) or fall back to a static bubble.
        // Guard against duplicates: if responseEl exists, finalize it; only create
        // a new bubble if there's NO response element AND no prior addChat fallback
        // was used during streaming.
        const genericFinalResponse = /^(?:Tools executed\. Check the execution trace above for results\.|\(no reply\)|\(No validated response)/i;
        const finalText = finalResponseReceived ? (responseText || '') : '';
        let renderedFinalText = finalText;
        const presentationMessage = presentationMessages.filter(Boolean).slice(-1)[0] || '';
        const presentationTools = steps.filter(step => step && step.type === 'tool' && step.tool);
        const isPresentationOnlyTurn = presentationTools.length > 0
            && presentationTools.every(step => ['ui_screenshot', 'ui_content'].includes(step.tool));
        // For an analysis request the acknowledgement is only an internal
        // capture phase; keep the chat clean and show the later multimodal
        // answer instead. For a pure screenshot request the gallery itself is
        // the answer, matching the existing UI behavior.
        const hasScreenshotEvidence = screenshotResults.length + visualContentResults.length > 0;
        const suppressScreenshotAck = visualAnalysisContinuation || (
            hasScreenshotEvidence && _isScreenshotAckResponse(
                renderedFinalText,
                steps,
                visualContentResults,
                responseContract,
                text,
            )
        );
        const screenshotCaptureUnavailableForQuestion =
            _visualTurnRequiresExplanation(responseContract)
            && presentationTools.some(step => step.tool === 'ui_screenshot')
            && !hasScreenshotEvidence;
        if (!visualAnalysisContinuation && presentationMessage
            && (isPresentationOnlyTurn || window._lastLLMMeta?.multi_intent_query
                || screenshotCaptureUnavailableForQuestion)) {
            if (window._lastLLMMeta?.multi_intent_query && renderedFinalText.trim()) {
                renderedFinalText = renderedFinalText.trim() + '\n\n' + presentationMessage;
            } else {
                renderedFinalText = presentationMessage;
            }
            finalResponseReceived = true;
        }
        if (suppressScreenshotAck && responseEl) {
            try {
                responseEl.textContent = '';
                responseEl.hidden = true;
                responseEl.classList.remove('is-streaming');
                responseEl.removeAttribute('aria-busy');
            } catch (_) {}
            responseEl = null;
        }
        if (isInternalFollowup) {
            const visualEnvelope = typeof window.parseVisualResponseEnvelope === 'function'
                ? window.parseVisualResponseEnvelope(renderedFinalText)
                : null;
            let annotationResult = null;
            if (typeof window.applyVisualResponseAnnotations === 'function') {
                try {
                    // This also handles a missing/malformed envelope for
                    // required locate evidence. The browser has a complete
                    // capture manifest and can draw only verified bounds.
                    annotationResult = await window.applyVisualResponseAnnotations(
                        visualEnvelope,
                        opts.visualEvidence || [],
                        {
                            sessionId: turnSessionId,
                            requestId: turnIdentity.requestId,
                            messageId: turnIdentity.messageId,
                            responseLanguage: turnIdentity.responseLanguage,
                        },
                    );
                } catch (error) {
                    // Annotation is state-checked independently from prose. A
                    // failed draw/upload must never invent a location.
                    console.warn('[visual annotation] follow-up rendering failed:', error);
                }
            }
            if (visualEnvelope) {
                renderedFinalText = String(visualEnvelope.answer_text || renderedFinalText || '');
            }
            renderedFinalText = _stripVisualAttachmentEchoes(
                renderedFinalText,
                opts.visualAttachmentLabels || [],
            );
            let usedGroundedFallback = false;
            if (_visualResponseNeedsGroundedFallback(renderedFinalText, opts.visualEvidence || [])) {
                const multiTurnContext = opts.multiIntentQuery === true
                    ? String(opts.visualContext?.preliminary_response || '').trim() : '';
                renderedFinalText = _visualEvidenceFallbackResponse(
                    opts.visualEvidence || [],
                    turnSessionId,
                    turnIdentity.responseLanguage,
                    text,
                    multiTurnContext,
                );
                usedGroundedFallback = true;
            }
            if (annotationResult?.notice && !usedGroundedFallback) {
                renderedFinalText = `${renderedFinalText.trim()}\n\n${annotationResult.notice}`.trim();
            }
            // Merge the child answer into the original screenshot reply. The
            // child has its own server task/request ID, but no visible user
            // bubble, Trace, footer, or standalone assistant message.
            if (renderedFinalText.trim() && typeof addChat === 'function') {
                addChat('bot-response', renderedFinalText, true, Date.now(), false, turnSessionId, Object.assign(
                    {},
                    turnIdentity,
                    {
                        attachments: [],
                        screenshotLayout: screenshotGallery.layout || 'auto',
                    },
                ));
                finalReplyCommitted = true;
            }
            responseEl = null;
        } else if (!suppressScreenshotAck && responseEl && typeof finalizeStreamingResponse === 'function') {
            const meta = _buildTurnMeta(Object.assign({}, turnIdentity, {
                attachments: presentationAttachments,
                screenshotLayout: screenshotGallery.layout || 'auto',
            }));
            finalizeStreamingResponse(responseEl, renderedFinalText, turnSessionId, meta);
            finalReplyCommitted = Boolean(String(renderedFinalText || '').trim()
                || presentationAttachments.length);
        } else if (!suppressScreenshotAck && !responseEl && !window._chatFallbackUsed) {
            window._chatFallbackUsed = true;
            if (typeof addChat === 'function') {
                // The owner-case contract remains equivalent to the original
                // finalText path; renderedFinalText only adds a real metrics
                // answer for tool-only turns.
                // addChat('bot-response', finalText, true, Date.now(), false, turnSessionId)
                addChat('bot-response', renderedFinalText, true, Date.now(), false, turnSessionId, Object.assign(
                    {},
                    turnIdentity,
                    {
                        attachments: presentationAttachments,
                        screenshotLayout: screenshotGallery.layout || 'auto',
                    },
                ));
                finalReplyCommitted = Boolean(String(renderedFinalText || '').trim()
                    || presentationAttachments.length);
            }
        }

        // A pure screenshot command is answered by the gallery itself. The
        // capture helper has already mounted each attachment under this
        // assistant identity, so it is a committed response when no analysis
        // continuation is expected.
        if (!isInternalFollowup && suppressScreenshotAck && hasScreenshotEvidence
            && !visualFinalResponsePending
            && (!visualAnalysisContinuation || visualFollowupState === 'done')) {
            finalReplyCommitted = true;
        }

        // Append a usage-bar footer BELOW the response bubble so the
        // user can see response time + token counts + tool call count
        // for this turn. The footer lives inside the same chat-msg-wrapper
        // as the response bubble, so it sits directly under the LLM's
        // reply (matching the layout the user remembers from the original
        // implementation). The data comes from the server's
        // `llm_meta` field in the `response` SSE event, captured in
        // window._lastLLMMeta above. Client-side elapsed time is
        // computed from _chatTurnStartTime which the start handler set.
        if (!suppressScreenshotAck && responseEl && typeof responseEl.appendChild === 'function') {
            try {
                const wrapper = responseEl.parentElement;
                if (wrapper) {
                    const footer = _buildResponseFooter(window._lastLLMMeta);
                    if (footer) {
                        wrapper.appendChild(footer);
                        if (typeof requestChatScrollToBottom === 'function') requestChatScrollToBottom();
                    }
                }
            } catch (_) { /* footer is best-effort */ }
        }

        // Leave the final-response row pending through the end of this try
        // block. The terminal status is committed in finally, alongside the
        // send-button/turn-state cleanup, so the browser cannot paint a green
        // final row while this request still owns the active send state.
    } catch (e) {
        const detached = window._chatDetachRequestedFor === turnSessionId
            || String(activeSessionId || '') !== turnSessionId;
        if (detached) {
            turnDetached = true;
            // The browser abandoned this stream (session switch).  Persist
            // whatever response text and thinking trace arrived so that the
            // transcript is complete when the user opens this case again.
            const detachedResponse = responseText
                || (finalResponseReceived ? _chatUserVisibleFailure(turnSessionId, 'response') : null);
            if (detachedResponse && typeof saveSessionMessage === 'function') {
                saveSessionMessage('bot-response', detachedResponse, null, Date.now(), turnSessionId, _buildTurnMeta(turnIdentity));
            }
            if (!isInternalFollowup) {
                try {
                    saveSessionMessage('thinking', '', steps, Date.now(), turnSessionId, {
                        requestId: turnRequestId,
                        messageId: `trace-${turnRequestId}`,
                        messageKind: 'execution_trace',
                        turnSequence: 1,
                        replyToMessageId: turnAssistantMessageId,
                        responseLanguage: turnIdentity.responseLanguage,
                        traceLanguage: turnIdentity.responseLanguage,
                    });
                } catch (_) {}
            }
            return;
        }

        const taskStatus = window._sessionChatTaskStatuses?.[turnSessionId];
        const explicitlyStopped = !!window._explicitChatStopSessions?.[turnSessionId]
            || taskStatus === 'cancelled'
            || !!turnAbortController?.__brachybotExplicitStop;
        const interruptedStream = e?.name === 'AbortError'
            || /abort|timed out|network|fetch/i.test(String(e?.message || ''));

        if (explicitlyStopped) {
            turnCancelled = true;
            try { window.clearPlanningPreview?.('explicit-stop'); } catch (_) {}
            cancelTurnUi('Stopped');
            _setCaseTaskState(turnSessionId, 'cancelled', null);
            if (!isInternalFollowup && typeof addChat === 'function') {
                addChat('system', _chatLanguageForSession(turnSessionId) === 'zh' ? '已停止。' : 'Stopped.',
                    true, Date.now(), false, turnSessionId);
            }
        } else if (interruptedStream && !turnCompleted && !turnFailed) {
            // A browser stream interruption is not a task cancellation. The
            // server continues the case-scoped task and journals its events,
            // so reconnect from that journal instead of showing a false stop.
            // Prefer the turn-level task_id from the `task_meta` SSE event;
            // fall back to the session-level id stored on the last known task.
            const effectiveTaskId = turnTaskId
                || window._sessionChatTaskIds?.[turnSessionId]
                || null;
            if (effectiveTaskId) {
                reconnectNeeded = true;
                window._detachedChatTasks[turnSessionId] = effectiveTaskId;
                _setCaseTaskState(turnSessionId, 'running', effectiveTaskId);
                _addTaskRecoveryNotice(turnSessionId, effectiveTaskId, 'reconnecting');
            } else {
                turnFailed = true;
                try { window.clearPlanningPreview?.('stream-recovery-failed'); } catch (_) {}
                _setCaseTaskState(turnSessionId, 'failed', null);
                console.warn('[chat] Stream recovery could not locate a task', e);
                if (typeof addChat === 'function') {
                    addChat('error', _chatUserVisibleFailure(turnSessionId, 'request'), true,
                        Date.now(), false, turnSessionId, turnIdentity);
                }
            }
        } else {
            turnFailed = true;
            try { window.clearPlanningPreview?.('request-failed'); } catch (_) {}
            _setCaseTaskState(turnSessionId, 'failed', null);
            console.warn('[chat] Send failed', e);
            if (typeof addChat === 'function') {
                const visualFailure = isInternalFollowup
                    ? _visualEvidenceFallbackResponse(
                        opts.visualEvidence || [],
                        turnSessionId,
                        turnIdentity.responseLanguage,
                        text,
                    )
                    : _chatUserVisibleFailure(turnSessionId, 'request');
                addChat(isInternalFollowup ? 'bot-response' : 'error', visualFailure, true,
                    Date.now(), false, turnSessionId, turnIdentity);
                if (isInternalFollowup && String(visualFailure || '').trim()) {
                    finalReplyCommitted = true;
                }
            } else {
                console.error('sendChat failed and addChat missing:', e);
            }
        }
    } finally {
        // Presentation callbacks must not prevent the owning turn releasing
        // its transport and send control, even if a renderer fails.
        try {
        if (isInternalFollowup) {
            const visualParentRequestId = parentRequestId || turnIdentity.requestId;
            const finalStatus = turnCancelled
                ? 'cancelled'
                : (turnFailed || !finalReplyCommitted ? 'error' : 'done');
            if (turnDetached || reconnectNeeded) {
                // The server task is still alive. Keep the parent's final
                // row pending until the resumed child really mounts an answer.
                const followupStates = window._visualFollowupStates;
                if (opts.followupKey && followupStates) {
                    followupStates.set(String(opts.followupKey), 'running');
                }
            } else {
                if (finalStatus === 'done') await _waitForFinalReplyPaint();
                const followupStates = window._visualFollowupStates;
                const followupState = finalStatus === 'done' ? 'done'
                    : finalStatus === 'cancelled' ? 'cancelled' : 'error';
                const visualParentKey = _visualFinalResponseKey(
                    turnSessionId, visualParentRequestId,
                );
                const visualParentRecord = _pendingVisualFinalResponseMap().get(visualParentKey);
                if (opts.followupKey && followupStates) {
                    followupStates.set(String(opts.followupKey), followupState);
                } else if (followupStates && visualParentRequestId) {
                    const prefix = `${turnSessionId}|${visualParentRequestId}|`;
                    for (const key of followupStates.keys()) {
                        if (String(key).startsWith(prefix)) followupStates.set(key, followupState);
                    }
                }
                _settlePendingVisualFinalResponse(
                    turnSessionId,
                    visualParentRequestId,
                    finalStatus,
                );
                if (finalStatus === 'done'
                    && String(activeSessionId || '') === turnSessionId
                    && visualParentRecord?.todo
                    && typeof visualParentRecord.todo.fold === 'function') {
                    try { visualParentRecord.todo.fold(); } catch (_) {}
                }
            }
        } else if (!turnDetached && !reconnectNeeded
            && (turnCompleted || turnFailed || turnCancelled)
            && (steps.length > 0 || chainEl)) {
            if (!finalResponseStep) {
                finalResponseStep = _ensureFinalResponseTraceStep(
                    steps,
                    deferredFinalSteps,
                    turnRequestId,
                    turnIdentity.responseLanguage,
                    stepsDiv,
                    headerEl,
                    reportUiActionRequested || _hasReportGenerationAction(steps),
                );
            }
            const unresolved = deferredFinalSteps.filter(step =>
                step && (step.status === 'pending' || step.status === 'active')
            );
            if (!visualFinalResponsePending && unresolved.length) {
                const finalStatus = turnCancelled
                    ? 'cancelled'
                    : (turnFailed || !turnCompleted || !finalReplyCommitted ? 'error' : 'done');
                if (finalStatus === 'done' && !finalResponsePaintWaited) {
                    await _waitForFinalReplyPaint();
                    finalResponsePaintWaited = true;
                }
                _finishFinalResponseTraceSteps(
                    steps,
                    unresolved,
                    finalStatus,
                    turnIdentity.responseLanguage,
                    finalStatus === 'error' ? responseText : '',
                    stepsDiv,
                    headerEl,
                    turnSessionId,
                );
                if (finalStatus === 'done'
                    && typeof window.notifyAssistantFinalResponseMounted === 'function') {
                    window.notifyAssistantFinalResponseMounted(turnRequestId, turnAssistantMessageId);
                }
                // The Progress dock shares the same delivery boundary as the
                // trace: do not fold it until the final response is terminal.
                if (finalStatus === 'done' && turnCompleted
                    && todo && typeof todo.fold === 'function'
                    && String(activeSessionId || '') === turnSessionId) {
                    try { todo.fold(); } catch (_) {}
                }
            }
        }
        } catch (finalizationError) {
            console.warn('[chat] final response presentation failed:', finalizationError);
        }
        const isCurrentTurn = window._chatTurnCancelUi === cancelTurnUi;
        if (isCurrentTurn) {
            window._chatTurnActive = false;
            window._chatTurnCancelUi = null;
        }
        if (chatAbortController === turnAbortController) chatAbortController = null;
        if (window._activeChatTaskSessionId === turnSessionId
            && Number(window._activeChatTurnGeneration || 0) === turnGeneration
            && (turnCompleted || turnFailed || !reconnectNeeded)) {
            window._activeChatTaskId = null;
            window._activeChatTaskSessionId = null;
            window._activeChatRequestId = null;
            window._activeChatParentRequestId = null;
            window._activeChatInternalFollowup = false;
            // The turn is over. Never let its explicit-stop flag survive into
            // the next turn, where a failed abort acknowledgement would make a
            // fresh request render as "Stopped".
            try {
                if (turnSessionId && window._explicitChatStopSessions) {
                    delete window._explicitChatStopSessions[turnSessionId];
                }
            } catch (_) {}
        }
        if (isCurrentTurn) {
            try {
            if (!isInternalFollowup) {
                // Safety net: if the server never emitted a routing/local-intent
                // step that reconcileOptimisticTraceStep could merge into, the
                // optimistic routing row stays pending forever. Force any leftover
                // client-router-* / client-user-* pending row to done before the
                // chain folds so the trace cannot show a stuck "Analyzing request"
                // state after the response has already been delivered.
                for (const s of steps) {
                    if (s && typeof s.id === 'string'
                        && (s.id === optimisticTraceStepIds.router
                            || s.id === optimisticTraceStepIds.user)
                        && (s.status === 'pending' || s.status === 'active')) {
                        s.status = 'done';
                    }
                }
                // Collapse only after a terminal response/error. A reconnect
                // is still an active server task: leave its trace expanded so
                // the user can see that recovery is in progress.
                const traceTerminal = !reconnectNeeded
                    && (turnCompleted || turnFailed || turnCancelled);
                if (traceTerminal && chainEl) {
                    if (turnCancelled
                        && typeof cancelThinkingChain === 'function') {
                        cancelThinkingChain(chainEl, headerEl);
                    } else if (typeof finalizeThinkingChain === 'function') {
                        finalizeThinkingChain(chainEl, headerEl, steps);
                    }
                }
                if (traceTerminal && (turnFailed || turnCancelled)
                    && todo && typeof todo.fold === 'function') {
                    try { todo.fold(); } catch (_) {}
                }
                try {
                    saveSessionMessage('thinking', '', steps, Date.now(), turnSessionId, {
                        requestId: turnRequestId,
                        messageId: `trace-${turnRequestId}`,
                        messageKind: 'execution_trace',
                        turnSequence: 1,
                        replyToMessageId: turnAssistantMessageId,
                        responseLanguage: turnIdentity.responseLanguage,
                        traceLanguage: turnIdentity.responseLanguage,
                    });
                } catch (_) {}
            }
            } finally {
            window._chatStreaming = false;
            setStreamingState(false);
            // The turn changed the provider context; refresh the indicator now
            // instead of waiting for the next polling interval.
            try { window.refreshContextStatus?.(); } catch (_) {}
            setTimeout(() => { try { _flushHiddenChatQueue(); } catch (_) {} }, 0);
            if (turnCompleted || turnFailed || turnCancelled) {
                setTimeout(() => { try { _flushQueuedChatTurns(); } catch (_) {} }, 0);
            }
            }
        }
        if (reconnectNeeded && activeSessionId === turnSessionId) {
            setTimeout(() => {
                try { window.resumeSessionChatTask?.(); } catch (_) {}
            }, 350);
        }
    }
}

function _traceStepForDisplay(step, sessionId, turnLanguage = '') {
    if (!step || typeof step !== 'object') return step;
    if (!['ui_screenshot', 'ui_content'].includes(step.tool)) return step;
    const language = (
        turnLanguage
        || step.trace_language
        || step.response_language
        || (typeof conversationLanguageForSession === 'function'
            ? conversationLanguageForSession(sessionId)
            : '')
        || window._responseLanguage
        || window._i18nLang
        || 'en'
    ).toLowerCase().startsWith('zh') ? 'zh' : 'en';
    const metadata = step.metadata || {};
    if (step.tool === 'ui_content') {
        const command = metadata.content_command || {};
        const summaryMap = metadata.trace_summary_i18n || {};
        const target = String(command.target || metadata.content_target || 'session_summary');
        const fallback = language === 'zh'
            ? '\u5df2\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u7684\u5df2\u4fdd\u5b58\u5185\u5bb9\u3002'
            : 'Read persisted content from the current Session.';
        return Object.assign({}, step, {
            title: language === 'zh' ? '\u5448\u73b0 Session \u5185\u5bb9' : 'Present Session content',
            params: {
                target,
                presentation: String(command.presentation || 'auto'),
                mode: String(command.mode || 'chat'),
            },
            content: '',
            result: String(summaryMap[language] || fallback),
            metadata,
        });
    }
    const summaryMap = metadata.trace_summary_i18n
        || metadata.screenshot_plan?.trace_summary_i18n
        || {};
    const plan = metadata.screenshot_plan
        || metadata.screenshot_command?.plan
        || {};
    const views = Array.isArray(plan.views) ? plan.views : [];
    const fallback = language === 'zh'
        ? `已准备${views.length || 1}个截图视图。`
        : `Prepared ${views.length || 1} screenshot view(s).`;
    return Object.assign({}, step, {
        title: language === 'zh' ? '\u751f\u6210\u622a\u56fe' : 'Capture screenshot',
        params: {
            mode: plan.mode || 'chat',
            views: views.map(view => view.target || view.viewer || view),
            layout: plan.layout || 'auto',
        },
        content: '',
        result: String(summaryMap[language] || fallback),
        metadata,
    });
}
window._traceStepForDisplay = _traceStepForDisplay;

async function _buildDoseResultsFallback(userText, sessionId) {
    const text = String(userText || '').trim();
    if (!/(?:dose distribution|dose map|dose cloud|\u5242\u91cf\u5206\u5e03|\u5242\u91cf\u4e91\u56fe|\u5242\u91cf\u7ed3\u679c)/i.test(text)) return '';
    try {
        let response;
        // Planning results can be committed a few moments after the chat
        // task reaches its terminal event. Treat the server's explicit 202
        // as a recoverable state, not as an empty answer, and wait briefly
        // for the authoritative result snapshot.
        for (let attempt = 0; attempt < 20; attempt += 1) {
            response = await fetch('/api/planning/results', {
                headers: { 'X-BrachyBot-Session': String(sessionId || '') },
            });
            if (response.status !== 202 || attempt === 19) break;
            const retryAfter = Number(response.headers.get('Retry-After-Ms') || 250);
            await new Promise(resolve => setTimeout(
                resolve,
                Math.max(100, Math.min(1000, Number.isFinite(retryAfter) ? retryAfter : 250)),
            ));
        }
        if (!response?.ok) return '';
        const data = await response.json();
        const metrics = data?.metrics || {};
        const zh = conversationLanguageForSession(sessionId) === 'zh';
        const percent = (value) => {
            const numeric = Number(value);
            if (!Number.isFinite(numeric)) return null;
            return `${(numeric <= 1.000001 ? numeric * 100 : numeric).toFixed(1)}%`;
        };
        const number = (value, digits = 2) => {
            const numeric = Number(value);
            return Number.isFinite(numeric) ? numeric.toFixed(digits) : null;
        };
        const rows = [
            [zh ? 'V100' : 'V100', percent(metrics.v100)],
            [zh ? 'V150' : 'V150', percent(metrics.v150)],
            [zh ? 'V200' : 'V200', percent(metrics.v200)],
            ['D90', number(metrics.d90)],
            ['Dmean', number(metrics.dmean)],
            ['D2', number(metrics.d2 || metrics.d2_max || metrics.max_dose)],
        ].filter(([, value]) => value !== null);
        if (!rows.length && !data.has_dose) {
            return zh
                ? '当前病例还没有可用的剂量分布数据。请先完成剂量计算。'
                : 'No dose distribution is available for this case yet. Run dose calculation first.';
        }
        const body = rows.map(([label, value]) => `- ${label}: ${value}${['D90', 'Dmean', 'D2'].includes(label) ? ' Gy' : ''}`).join('\n');
        return zh
            ? `当前剂量分布结果如下：\n\n${body || '- 剂量网格已加载，但指标尚未生成。'}\n\n可在 Analysis 面板查看完整 DVH 和 OAR 剂量。`
            : `Current dose distribution results:\n\n${body || '- The dose grid is loaded, but summary metrics are not available yet.'}\n\nOpen Analysis to inspect the full DVH and OAR dose.`;
    } catch (error) {
        console.debug('[chat] dose fallback unavailable:', error);
        return '';
    }
}

window.resumeSessionChatTask = async function resumeSessionChatTask(options = {}) {
    const sessionId = activeSessionId;
    // This status probe is a snapshot, not the owner of a later user turn.
    // Validate after every asynchronous boundary before applying its result.
    const probeGeneration = Number(window._chatTurnGeneration || 0);
    const probeIsCurrent = () => activeSessionId === sessionId
        && Number(window._chatTurnGeneration || 0) === probeGeneration
        && !window._chatTurnActive && !window._chatStreaming;
    window._lastChatTaskResumeState = window._lastChatTaskResumeState || {};
    const setResumeState = (status, details = {}) => {
        if (!sessionId) return;
        window._lastChatTaskResumeState[sessionId] = {
            status: String(status || 'none'),
            ...details,
            at: Date.now(),
        };
    };
    if (!sessionId) return false;
    if (window._chatTurnActive || window._chatStreaming) {
        setResumeState('running', { reason: 'local_stream_active' });
        return false;
    }
    window._sessionChatResumePromises = window._sessionChatResumePromises || {};
    if (window._sessionChatResumePromises[sessionId]) {
        return window._sessionChatResumePromises[sessionId];
    }
    const resume = (async () => {
    try {
        const response = await fetch(API + '/chat/task', {
            cache: 'no-store',
            headers: { 'X-BrachyBot-Session': sessionId },
        });
        if (!probeIsCurrent()) return false;
        if (!response.ok) {
            const staleTaskId = window._sessionChatTaskIds?.[sessionId]
                || window._detachedChatTasks?.[sessionId]
                || null;
            const hadInFlight = !!staleTaskId && _hadInFlightTask(sessionId);
            delete window._detachedChatTasks[sessionId];
            delete window._sessionChatTaskIds[sessionId];
            _setCaseTaskState(sessionId, 'failed', null);
            // Only warn the operator when the browser actually tracked an
            // in-flight task for this case. After a server restart the browser
            // reloads; a completed or failed history task is not an actionable
            // loss and must not produce the "no longer running" notice.
            setResumeState('unavailable', { taskId: staleTaskId, reason: 'status_http_error' });
            if (hadInFlight) _addTaskRecoveryNotice(sessionId, staleTaskId, 'unavailable');
            else window.hideWorkspaceRecoveryNotice?.({ sessionId, persist: true, reason: 'no_task' });
            return false;
        }
        const payload = await response.json();
        // A newer switch can happen while the task status request is in
        // flight. Do not attach this replay to another case's chat shell.
        if (!probeIsCurrent()) return false;
        const task = payload?.task;
        if (task && Object.prototype.hasOwnProperty.call(task, 'brain_available')) {
            window.updateBrainStatusIndicator?.(task.brain_available, 'task-resume');
        }
        // The server owns task identity. Browser memory and a workspace
        // checkpoint are only hints because either can be stale after a
        // refresh, a case switch, or a fast task finalization race.
        if (!task || task.status !== 'running') {
            const staleTaskId = window._sessionChatTaskIds?.[sessionId]
                || window._detachedChatTasks?.[sessionId]
                || payload?.persisted?.task_id
                || payload?.persisted?.last_task_id
                || null;
            const hadInFlight = !!staleTaskId && (
                _hadInFlightTask(sessionId)
                || String(payload?.persisted?.status || '') === 'running'
                || String(payload?.persisted?.operation_state || '') === 'running'
            );
            delete window._detachedChatTasks[sessionId];
            delete window._sessionChatTaskIds[sessionId];
            if (window._sessionChatTaskStatuses) window._sessionChatTaskStatuses[sessionId] = task?.status || 'idle';
            if (window._activeChatTaskSessionId === sessionId) {
                window._activeChatTaskId = null;
                window._activeChatTaskSessionId = null;
                window._chatTurnActive = false;
                window._chatStreaming = false;
                setStreamingState(false);
            }
            if (task?.status === 'completed'
                && typeof window.refreshSessionAfterTaskCompletion === 'function') {
                try {
                    await window.refreshSessionAfterTaskCompletion(sessionId);
                } catch (error) {
                    console.warn('[chat] completed case refresh deferred:', error);
                }
                if (!probeIsCurrent()) return false;
            }
            window.hideWorkspaceRecoveryNotice?.({ sessionId, persist: true, reason: 'task_terminal' });
            window._lastChatTaskResumeState = window._lastChatTaskResumeState || {};
            window._lastChatTaskResumeState[sessionId] = {
                status: task?.status || (hadInFlight ? 'unavailable' : 'none'),
                taskId: staleTaskId,
                at: Date.now(),
            };
            if (!task || task?.status === 'failed' || task?.status === 'cancelled') {
                // Only warn when the browser actually had an in-flight task.
                // A completed/failed history task on a freshly loaded page
                // (e.g. after a server restart) is not an actionable loss.
                if (hadInFlight) _addTaskRecoveryNotice(sessionId, staleTaskId, 'unavailable');
            }
            if (typeof window.flushQueuedChatTurns === 'function') {
                setTimeout(() => window.flushQueuedChatTurns(), 0);
            }
            return false;
        }
        const taskId = task.task_id;
        window.hideWorkspaceRecoveryNotice?.({ sessionId, persist: true, reason: 'task_running' });
        // Preserve the original wall-clock baseline when a detached task is
        // replayed. Otherwise the restored trace looks as if it just started
        // after a case switch even though the worker has been running longer.
        if (Number.isFinite(Number(task.created_at)) && Number(task.created_at) > 0) {
            window._caseChainStartedAt = window._caseChainStartedAt || {};
            window._caseChainStartedAt[sessionId] = Number(task.created_at) * 1000;
        }
        window._lastChatTaskResumeState = window._lastChatTaskResumeState || {};
        window._lastChatTaskResumeState[sessionId] = {
            status: 'running',
            taskId,
            at: Date.now(),
        };
        window._sessionChatTaskIds[sessionId] = taskId;
        window._sessionChatTaskStatuses = window._sessionChatTaskStatuses || {};
        window._sessionChatTaskStatuses[sessionId] = 'running';
        delete window._detachedChatTasks[sessionId];
        // Two snapshot applications can race on a cold restore. Re-check
        // after the status request so the second one cannot enter sendChat()
        // and accidentally stop the first replay stream.
        if (window._chatTurnActive || window._chatStreaming || activeSessionId !== sessionId) return false;
        const replayResult = await sendChat(null, {
            resumeTaskId: taskId,
            resumeRequestId: task.request_id || taskId,
            requestId: task.request_id || taskId,
            userMessageId: task.user_message_id || `user-${task.request_id || taskId}`,
            assistantMessageId: task.assistant_message_id || `assistant-${task.request_id || taskId}`,
            parentRequestId: task.parent_request_id || '',
            parentUserMessageId: task.parent_user_message_id || '',
            parentAssistantMessageId: task.parent_assistant_message_id || '',
            internalFollowup: !!task.internal_followup,
            visualFollowUp: !!task.internal_followup,
            responseLanguage: task.response_language || '',
            resumeMessage: task.message || '',
            skipIntentShortcuts: true,
            preserveLastUserMessage: true,
        });
        if (replayResult === false) {
            setResumeState('unavailable', { taskId, reason: 'replay_http_error' });
            if (_hadInFlightTask(sessionId)) {
                _addTaskRecoveryNotice(sessionId, taskId, 'unavailable');
            }
            return false;
        }
        return true;
    } catch (error) {
        if (!probeIsCurrent()) return false;
        console.warn('[chat] task resume deferred:', error);
        window.hideWorkspaceRecoveryNotice?.({ sessionId, reason: 'resume_status_unavailable' });
        setResumeState('unavailable', { reason: 'status_request_failed' });
        return false;
    } finally {
        delete window._sessionChatResumePromises[sessionId];
    }
    })();
    window._sessionChatResumePromises[sessionId] = resume;
    return resume;
};

/******** STATE ********/
// Collect current UI state so the chat agent can know what's loaded and
// what the user is looking at. Mirrors the upstream `collectUIState` helper.
