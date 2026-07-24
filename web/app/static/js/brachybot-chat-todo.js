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

function _todoLabelForStep(step) {
    // Pick labels from the explicit workstation language preference.
    const i18n = _todoI18n();
    if (step.type === 'tool' && step.tool) {
        // Keep the internal evidence phase readable even when an older
        // localized dictionary does not yet contain the tool name.
        if (step.tool === 'fact_checker') {
            return _activeTodoLang === 'zh' ? 'Source verification' : 'Source verification';
        }
        return i18n.tools[step.tool] || (i18n.call_prefix + step.tool);
    }
    if (step.type === 'thinking') {
        // Use the step title (e.g. "Multi-Agent Router", "LLM Call 1")
        if (step.title) return step.title;
        return i18n.thinking;
    }
    if (step.type === 'memory') {
        return step.title || i18n.memory;
    }
    return i18n[step.type] || (step.title || i18n.default_processing);
}

// UI-controller actions are applied in the browser after the server emits
// the validated action list. Keep them in the same live trace and todo stream
// so the user sees one truthful, sequential progress surface.
if (!window._brachyUiTraceListenerReady) {
    window._brachyUiTraceListenerReady = true;
    document.addEventListener('brachy:ui-action-progress', (event) => {
        const trace = window._brachyLiveTrace;
        const step = event && event.detail;
        // UI-controller actions are emitted asynchronously.  A case switch
        // may happen between the server emitting the action and the browser
        // receiving it, so never append an old case's progress to the newly
        // selected case.
        if (!trace || !step || trace.sessionId !== activeSessionId
            || (step.session_id && String(step.session_id) !== String(activeSessionId || ''))) return;
        const index = trace.steps.length;
        trace.steps.push(step);
        if (typeof appendStepToChain === 'function') {
            appendStepToChain(trace.stepsDiv, step, index);
        }
        if (typeof updateChainHeader === 'function') {
            updateChainHeader(trace.headerEl, trace.steps);
        }
        const activeTodo = typeof trace.getTodo === 'function' ? trace.getTodo() : null;
        if (activeTodo && typeof _todoUpdateFromStep === 'function') {
            _todoUpdateFromStep(activeTodo, step);
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
    // can re-render labels when the user flips the global EN/中
    // toggle mid-task. There is only ever one todo visible at a
    // time per chat (sendChat wipes the dock at start), so a
    // single global ref is enough.
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
            const id = (step.id != null) ? String(step.id) : ('s' + (api.items.length + 1));
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
            const item = { id, label, toolName: step.tool || null, status: 'pending', startedAt: Date.now(), endedAt: null, node: li, step };
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
        markDone(item, errMsg) {
            // Always ensure at least one browser paint frame shows the
            // "active" breathing state before transitioning to done.
            // When pending+done arrive in the same SSE batch (e.g. OAR
            // auto-fire), sinceActive ≈ 0 and the old code skipped the
            // defer — the user saw "CTV executing + OAR completed"
            // instead of "CTV done → OAR executing → OAR done".
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
        const fetchOnce = async () => {
            try {
                const r = await fetch('/api/device/status', { signal: item._gpuAbort.signal });
                if (!r.ok) return;
                const s = await r.json();
                render(s);
            } catch (e) {
                if (e.name !== 'AbortError') {
                    badge.textContent = '🎮 ?';
                }
            }
        };
        fetchOnce();
        item._gpuTimer = setInterval(fetchOnce, 2000);
    }
    function _todoStopGpuBadge(item) {
        if (item._gpuTimer) { clearInterval(item._gpuTimer); item._gpuTimer = null; }
        if (item._gpuAbort) { try { item._gpuAbort.abort(); } catch (_) {} item._gpuAbort = null; }
        const badge = item.node && item.node.querySelector && item.node.querySelector('.chat-todo-gpu');
        if (badge) {
            // Don't remove the DOM node — just clear its text. The
            // step is still in the list, and the user might want to
            // see which GPU was used.
            badge.textContent = '';
        }
    }

    // Register this todo as the currently active one so the global
    // EN/中 toggle can re-render its labels in the new language
    // (see _setActiveTodoLang above).
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
function _todoUpdateFromStep(todo, step) {
    if (!todo || !step) return;
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
    // "接收用户请求 / Multi-Agent Router / Crystallized Skill / Experience
    // Recall / LLM Call 1" — all internal LLM runtime — cluttered the
    // todo list. These are already shown in the (folded) thinking chain,
    // which is the right home for them. The todo list should only show
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
            if (step.status === 'done') {
                todo.markDone(existing);
            } else if (step.status === 'pending') {
                todo.markActive(existing);
            } else if (step.status === 'error') {
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
    // Extract real execution time from backend content.
    // The backend includes "elapsed_ms=1234" in done event content so
    // the frontend can display the ACTUAL wall-clock time instead of
    // measuring network delay between SSE events.
    if (step.content && step.status === 'done') {
        const emMatch = step.content.match(/elapsed_ms=(\d+)/);
        if (emMatch) item._realElapsedMs = parseInt(emMatch[1]);
    }
    if (step.status === 'pending') {
        todo.markActive(item);
    } else if (step.status === 'done') {
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
    } else if (step.status === 'error') {
        todo.markDone(item, step.requires_input ? 'User input required' : (step.error || 'failed'));
    }
    return item;
}

// Pre-populate the todo with predicted workflow steps BEFORE the SSE
// stream starts emitting events. The user complained "我都不知道后面
// 要发生什么" — without this, the list grows incrementally as events
// arrive and the user has no idea what's coming. We seed a known
// 5-step planning pipeline (from the upstream opencode CLI todo list
// style). As real step events arrive, _todoUpdateFromStep finds the
// matching predicted entry (by tool name) and updates its status. New
// events that don't match any prediction are appended as they come.
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
    // bug: "11 步 9 完成, 中间两个没完成但后面的都完成了").
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
        // This is a single-line command box (Shift+Enter is the multiline
        // escape hatch), so Up/Down are dedicated history navigation keys.
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
        input.setSelectionRange(input.value.length, input.value.length);
    }
}

// Stub `handleChatInput` — referenced from oninput=, prevents ReferenceError
function handleChatInput(el) {
    // Reserved for future autosize / command-palette hooks.
    if (el && el.style) { /* autosize hook */ }
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
const CHAT_IDLE_TIMEOUT_MS = 90000;
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
window._explicitChatStopSessions = window._explicitChatStopSessions || {};
window._sessionPlanningRefreshTimers = window._sessionPlanningRefreshTimers || {};

function _setCaseTaskState(sessionId, status, taskId = undefined) {
    const key = String(sessionId || '');
    if (!key) return;
    window._sessionChatTaskStatuses[key] = status || 'idle';
    if (taskId !== undefined) {
        if (taskId) window._sessionChatTaskIds[key] = taskId;
        else delete window._sessionChatTaskIds[key];
    }
}

function _scheduleCasePlanningRefresh(sessionId, delay = 250) {
    const key = String(sessionId || '');
    if (!key || typeof refreshPlanningUI !== 'function') return false;
    if (window._sessionPlanningRefreshTimers[key]) return false;
    window._sessionPlanningRefreshTimers[key] = setTimeout(async () => {
        delete window._sessionPlanningRefreshTimers[key];
        if (String(activeSessionId || '') !== key) return;
        try {
            await refreshPlanningUI({ sessionId: key });
        } catch (error) {
            console.error('[SSE] refreshPlanningUI failed:', error);
        }
    }, Math.max(0, Number(delay) || 0));
    return true;
}

function _sessionChatQueue(sessionId) {
    const key = String(sessionId || '');
    if (!key) return [];
    if (!Array.isArray(window._sessionChatQueues[key])) window._sessionChatQueues[key] = [];
    return window._sessionChatQueues[key];
}

function _queueChatTurn(sessionId, message) {
    const text = String(message || '').trim();
    if (!sessionId || !text) return false;
    _sessionChatQueue(sessionId).push({ text, queuedAt: Date.now() });
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
    if (typeof window.scheduleWorkspaceSave === 'function') window.scheduleWorkspaceSave('chat.turn_dequeued');
    _queuedChatFlushRunning = true;
    try {
        await sendChat(next.text, {
            hiddenUserMessage: true,
            preserveLastUserMessage: true,
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

function _isMonitorStartRequest(text) {
    return /(?:monitor|training|coach|guide|supervise|watch|observe|培训|训练|监测|监督|指导|教我|带我)/i.test(text || '')
        && !/(?:stop|finish|end|停止|结束|关闭)/i.test(text || '');
}

function _isMonitorStopRequest(text) {
    return /(?:stop|finish|end|summary|停止|结束|关闭|总结|完成监测|停止监测)/i.test(text || '')
        && /(?:monitor|training|coach|培训|训练|监测|监督|指导)/i.test(text || '');
}

function _isAdviceRequest(text) {
    const value = String(text || '').trim();
    const explicitAdvice = /\b(?:advice|suggest(?:ion)?s?|recommend(?:ation)?s?|improve|optimi[sz]e|assessment)\b|(?:优化|建议|评价|哪里需要|怎么调|如何调整|详细建议|规划评价)/i.test(value);
    const explicitReview = /\b(?:review|evaluate|assess)\s+(?:(?:my|the|this|current)\s+)?(?:plan|planning|dose|seed|needle|ctv|oar)\b|\b(?:plan|planning|dose)\s+(?:review|assessment)\b/i.test(value);
    const planningContext = /\b(?:plan|planning|dose|seed|needle|ctv|oar)\b|(?:规划|剂量|粒子|穿刺针|靶区|危及器官)/i.test(value);
    return (explicitAdvice || explicitReview) && planningContext;
}

window._pendingHiddenChats = window._pendingHiddenChats || [];
window._hiddenChatFlushRunning = false;

function _buildScreenshotFollowUpMessage(question, screenshotUrl) {
    const prompt = (question || 'Please analyze this screenshot and answer the user directly.').trim();
    return `[Screenshot captured: ${screenshotUrl}]\n${prompt}\n\nUse the screenshot as the visual context. Do not call ui_screenshot again unless this image is unusable.`;
}

function _isScreenshotAckResponse(text, steps) {
    const safeText = String(text || '').trim();
    if (!safeText || !Array.isArray(steps) || !steps.length) return false;
    const toolSteps = steps.filter(step => step && step.type === 'tool' && step.tool);
    if (!toolSteps.length) return false;
    if (toolSteps.some(step => step.tool !== 'ui_screenshot')) return false;
    if (toolSteps.some(step => step.status === 'error')) return false;
    return /^(Requested screenshot:|The requested screenshot is the )/i.test(safeText);
}

function _isVisualAnalysisRequest(text) {
    const value = String(text || '').trim();
    // Keep the detector ASCII-safe because some legacy bundles were saved
    // with a mismatched console encoding. Unicode escapes still match the
    // actual Chinese user input in the browser.
    if (/(?:\u4ecb\u7ecd|\u5206\u6790|\u89e3\u8bfb|\u8bf4\u660e|\u63cf\u8ff0|\u770b\u5230\u4e86\u4ec0\u4e48|\u770b\u5230\u4ec0\u4e48|\u8bc4\u4ef7|\u8bc4\u4f30|\u5224\u65ad|\u7ed3\u679c\u5982\u4f55|\u6709\u4ec0\u4e48\u95ee\u9898)/.test(value)) return true;
    return /\b(?:analy[sz]e|describe|interpret|assess|evaluate|what do you see|explain|findings?)\b/i.test(value)
        || /(?:介绍|分析|解读|说明|描述|看到了什么|看到什么|评价|评估|判断|结果如何|有什么问题)/.test(value);
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
    window._pendingHiddenChats.push({
        message: safeMessage,
        options: options || {},
        sessionId: activeSessionId,
    });
    setTimeout(() => { try { _flushHiddenChatQueue(); } catch (_) {} }, 0);
}

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
    window._hiddenChatFlushRunning = true;
    try {
        await sendChat(next.message, Object.assign({
            hiddenUserMessage: true,
            skipIntentShortcuts: true,
            preserveLastUserMessage: true,
        }, next.options || {}));
    } finally {
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
    if (Array.isArray(window._pendingHiddenChats)) {
        window._pendingHiddenChats = window._pendingHiddenChats.filter(item => item?.sessionId !== activeSessionId);
    }
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
    const isBusy = !!window._chatTurnActive || !!window._chatStreaming;

    // Enter is a submit action, not a cancellation action.  Preserve the
    // current task and queue the new turn under the selected case.  The
    // queued user bubble is rendered immediately; the request itself is sent
    // only after the active task reaches a terminal SSE event.
    if (isBusy && opts.queueIfBusy) {
        const queuedText = (prefill != null ? prefill : (input ? input.value : '')).trim();
        if (!queuedText || !activeSessionId) return false;
        if (input) input.value = '';
        if (typeof addChat === 'function') addChat('user', queuedText, true, Date.now(), false, activeSessionId);
        window._lastUserMessage = queuedText;
        _queueChatTurn(activeSessionId, queuedText);
        if (typeof addChat === 'function') {
            addChat('system', 'Queued for this case; the current task will finish first.', true, Date.now(), false, activeSessionId);
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
        if (stopSessionId) window._explicitChatStopSessions[stopSessionId] = true;
        try {
            if (typeof window._chatTurnCancelUi === 'function') window._chatTurnCancelUi('Stopped');
        } catch (_) {}
        try {
            if (typeof window.cancelVisibleChatProgress === 'function') {
                window.cancelVisibleChatProgress('Stopped');
            }
        } catch (_) {}
        try { chatAbortController.abort(); } catch (_) {}
        window._chatTurnActive = false;
        window._chatStreaming = false;
        setStreamingState(false);
        try {
            // Session changes await this branch. Confirm that the server has
            // cancelled the old case before its signed-cookie selection can
            // move to another workspace.
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
        } catch (_) {
            // The local abort and progress cleanup have already completed.
            // A disconnected browser is still protected by the turn token.
        } finally {
            if (window._activeChatTaskSessionId === stopSessionId) {
                window._activeChatTaskId = null;
                window._activeChatTaskSessionId = null;
            }
            delete window._explicitChatStopSessions[stopSessionId];
        }
        return;
    }

    let text = isResumingTask
        ? String(opts.resumeMessage || '')
        : (prefill != null ? prefill : (input ? input.value : '')).trim();
    if (!text && !isResumingTask) return;
    if (input && !opts.hiddenUserMessage && !isResumingTask) input.value = '';
    if (!opts.hiddenUserMessage && !isResumingTask && typeof addChat === 'function') {
        addChat('user', text, true, Date.now(), false, activeSessionId);
    }
    if (!opts.preserveLastUserMessage) {
        window._lastUserMessage = text;
    }

    // EPHEMERAL START: lazily create a "New chat" session on the
    // first message send. Until the user actually sends something,
    // no session is active and the chat area shows the welcome
    // message. This avoids leaking the previous session into a
    // fresh page load.
    try { if (!isResumingTask && typeof ensurePendingSession === 'function') ensurePendingSession(); } catch (_) {}
    const turnSessionId = String(activeSessionId || '');
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
    if (!opts.skipIntentShortcuts && _isAdviceRequest(text) && !/截图|screenshot|capture/i.test(text)) {
        await requestPlanningAdvice();
        return;
    }

    window._activeChatTaskSessionId = turnSessionId;
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
        if (dock) { dock.appendChild(todo.root); dock.style.display = ''; }
        for (const si of savedItems) {
            const stubStep = {
                type: 'tool',
                tool: si.toolName || '',
                title: si.label || '',
                id: si.id || '',
                status: si.status,
            };
            const item = todo.addPending(stubStep);
            item.startedAt = si.startedAt;
            item.endedAt = si.endedAt;
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
    let turnCompleted = false;
    let turnCancelled = false;
    let turnFailed = false;
    let progressEl = null;
    let lastToolName = '';
    const steps = [];
    const screenshotTasks = [];
    const screenshotResults = [];
    const screenshotTaskKeys = new Set();
    const uiActionTasks = [];
    // Group screenshots emitted during one assistant turn into one gallery.
    const screenshotGallery = {};
    const uiState = (typeof collectUIState === 'function') ? collectUIState() : {};
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

    try {
        chatAbortController = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        turnAbortController = chatAbortController;
        setStreamingState(true);
        thinkingEl = (typeof showThinkingIndicator === 'function') ? showThinkingIndicator() : null;
        // Snapshot the turn start time here, before the SSE connection
        // opens.  On task resume the saved timestamp is fed to
        // createLiveThinkingChain so the header clock shows the real
        // background elapsed time rather than restarting from 0.0 s.
        window._caseChainStartedAt = window._caseChainStartedAt || {};
        if (!isResumingTask && turnSessionId) {
            window._caseChainStartedAt[turnSessionId] = Date.now();
        }

        const connectTimer = turnAbortController
            ? setTimeout(() => turnAbortController.abort(), CHAT_CONNECT_TIMEOUT_MS)
            : null;
        let resp;
        try {
            if (isResumingTask) {
                const afterSeq = Number(opts.afterSeq || 0);
                resp = await fetch(
                    API + '/chat/tasks/' + encodeURIComponent(opts.resumeTaskId)
                    + '/stream?after_seq=' + encodeURIComponent(String(afterSeq)),
                    {
                        headers: { 'X-BrachyBot-Session': turnSessionId },
                        signal: turnAbortController ? turnAbortController.signal : undefined,
                    },
                );
            } else {
                resp = await fetch(API + '/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-BrachyBot-Session': turnSessionId,
                    },
                    body: JSON.stringify({ message: text, ui_state: uiState, stream: true, clear_context: false }),
                    signal: turnAbortController ? turnAbortController.signal : undefined,
                });
            }
        } finally {
            if (connectTimer) clearTimeout(connectTimer);
        }

        if (!resp.ok) {
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
            let errText = 'Chat failed: HTTP ' + resp.status;
            try {
                const errBody = await resp.json();
                if (errBody && errBody.error) errText = 'Chat failed: ' + errBody.error;
            } catch (_) { /* non-JSON error body */ }
            if (typeof addChat === 'function') addChat('error', errText, true, Date.now(), false, turnSessionId);
            setStreamingState(false);
            return;
        }

        const ctype = resp.headers.get('content-type') || '';
        if (ctype.indexOf('text/event-stream') === -1) {
            // Server didn't stream — fall back to plain JSON
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
            const data = await resp.json().catch(() => null);
            const reply = (data && (data.response || data.reply || data.message || data.content)) || '(no reply)';
            if (typeof addChat === 'function') addChat('bot-response', reply, true, Date.now(), false, turnSessionId);
            setStreamingState(false);
            return;
        }

        // Real SSE — read stream
        if (!resp.body || !resp.body.getReader) {
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
            const txt = await resp.text();
            if (typeof addChat === 'function') addChat('bot-response', txt, true, Date.now(), false, turnSessionId);
            setStreamingState(false);
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
            // 90 s idle window.  Extend the read timeout to the planning-level
            // 15 min whenever any step or todo item is still in-flight.
            const hasActiveWork = (todo && todo.items && todo.items.some(
                i => i.status === 'active' || i.status === 'pending',
            )) || steps.some(s => s.status === 'active' || s.status === 'pending');
            const timeoutMs = hasActiveWork
                ? CHAT_PLANNING_IDLE_TIMEOUT_MS : CHAT_IDLE_TIMEOUT_MS;
            const { done, value } = await readChatChunk(
                reader, timeoutMs,
                () => {
                try { turnAbortController.abort(); } catch (_) {}
            });
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                // Detach is deliberately non-destructive.  Stop rendering an
                // old case immediately if an already-buffered SSE chunk races
                // with the selection change; the worker/event journal remains
                // alive and the selected case can replay it later.
                if (activeSessionId !== turnSessionId) {
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

                    if (currentEvent === 'task_meta' && data) {
                        if (data.task_id && data.session_id) {
                            turnTaskId = String(data.task_id);
                            window._sessionChatTaskIds[data.session_id] = data.task_id;
                            _setCaseTaskState(data.session_id, 'running', data.task_id);
                            if (data.session_id === turnSessionId) {
                                window._activeChatTaskId = data.task_id;
                                window._activeChatTaskSessionId = turnSessionId;
                            }
                        }
                        if (!text && data.message) text = String(data.message);
                    }
                    if (currentEvent === 'start' && data) {
                        // The server detected the input language and
                        // sent it in the start event. The frontend
                        // uses this for the todo list labels,
                        // status messages, and any other UI text.
                        // Without this, the user would see English
                        // user input → Chinese todo entries → Chinese
                        // LLM reply, which is a "顶层问题"
                        // (top-level consistency bug).
                        if (data.language && data.language.code) {
                            window._responseLanguage = data.language.code;
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
                        steps.push(data);
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
                            const r = createLiveThinkingChain(resumeStart);
                            chainEl = r.chainEl; stepsDiv = r.stepsDiv; headerEl = r.headerEl;
                            // Save the chain start time so a session-resume
                            // rebuild uses the original clock, not Date.now().
                            if (!isResumingTask && turnSessionId) {
                                window._caseChainStartedAt = window._caseChainStartedAt || {};
                                window._caseChainStartedAt[turnSessionId] = Date.now();
                            }
                            window._brachyLiveTrace = {
                                sessionId: turnSessionId, steps, chainEl, stepsDiv, headerEl,
                                getTodo: () => todo,
                            };
                        }
                        if (typeof appendStepToChain === 'function') {
                            appendStepToChain(stepsDiv, data, steps.length - 1);
                        }
                        if (typeof updateChainHeader === 'function') {
                            updateChainHeader(headerEl, steps);
                        }
                        // Persistent todo — but ONLY create it when
                        // the LLM actually starts a multi-step workflow.
                        // The user's complaint: trivial Q&A (e.g. "你好")
                        // was showing the "执行进度" todo list with
                        // weird numbers like "27.6s" — there was no
                        // actual workflow to track. The LLM signals
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
                                    dock.appendChild(todo.root);
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
                                _todoUpdateFromStep(todo, data);
                                // Fold the todo when the final assistant
                                // step arrives. The response bubble will
                                // be rendered just above the todo (in the
                                // same wrapper), so the user sees the
                                // fold → "11/17 steps" header.
                                if (data.type === 'assistant' && data.status === 'done') {
                                    todo.fold();
                                    // Also fold the thinking chain RIGHT
                                    // NOW (not 500ms later) so the chain
                                    // doesn't visually compete with the
                                    // final reply bubble. Without this,
                                    // the user sees the 11 unrolled tool
                                    // calls for ~500ms before auto-fold.
                                    if (chainEl) {
                                        const _t = chainEl.querySelector('.thinking-toggle');
                                        const _s = chainEl.querySelector('.thinking-steps');
                                        if (_t) _t.classList.remove('expanded');
                                        if (_s) {
                                            _s.classList.remove('expanded');
                                            _s.querySelectorAll('.step-body').forEach(b => b.classList.remove('expanded'));
                                        }
                                    }
                                }
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
                        // Show tool progress (pending / done)
                        if (data.type === 'tool' && data.status === 'pending') {
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
                        } else if (data.type === 'tool' && (data.status === 'done' || data.status === 'error')) {
                            if (progressEl && typeof updateToolProgress === 'function') {
                                updateToolProgress(progressEl, lastToolName, data.status, data.result);
                            }
                            // Execute UI controller actions
                            // Actions live in data.metadata.actions (from ToolResult.metadata),
                            // NOT in data.result (which is the human-readable message string).
                            if (data.status === 'done' && data.tool === 'ui_controller') {
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
                                        uiDebugLog('[SSE-UI] Executing', actions.length, 'UI actions');
                                        if (typeof _executeUIActionsWithProgress === 'function') {
                                            uiActionTasks.push(_executeUIActionsWithProgress(actions, {
                                                sessionId: turnSessionId,
                                            }));
                                        } else {
                                            uiActionTasks.push(Promise.all(actions.map(a => _executeUIAction(a, {
                                                sessionId: turnSessionId,
                                            }))));
                                        }
                                    }
                                } catch (e) { console.warn('[SSE-UI] Failed to parse ui_controller result:', e); }
                            }
                            // Intercept ui_screenshot: capture the target element,
                            // upload to server, and display in chat.
                            if (data.status === 'done' && data.tool === 'ui_screenshot' && data.metadata) {
                                const _ssCmd = data.metadata.screenshot_command || data.metadata;
                                const _ssTarget = _normalizeScreenshotRequestTarget(_ssCmd.target || 'full', _ssCmd.question || '');
                                const _ssQuestion = _ssCmd.question || '';
                                const _ssKey = String(data.id || `${_ssTarget}|${_ssQuestion}`);
                                if (screenshotTaskKeys.has(_ssKey)) {
                                    uiDebugLog('[SSE-STEP] Ignoring duplicate screenshot completion:', _ssKey);
                                } else {
                                    screenshotTaskKeys.add(_ssKey);
                                uiDebugLog('[SSE-STEP] Intercepting ui_screenshot, target:', _ssTarget);
                                try {
                                    screenshotTasks.push(Promise.resolve(
                                        _interceptScreenshot(_ssTarget, _ssQuestion, screenshotGallery, {
                                            sessionId: turnSessionId,
                                        })
                                    ).then(result => {
                                        if (result && result.success && result.url) screenshotResults.push(result);
                                        return result;
                                    }));
                                } catch (e) {
                                    console.warn('[SSE-STEP] Screenshot interception failed:', e);
                                }
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
                            const FINAL_PLANNING_TOOLS = ['planning_pipeline', 'dose_evaluation', 'dose_eval'];
                            const SEG_TOOLS = ['ctv_segmentation', 'oar_segmentation'];
                            uiDebugLog('[SSE-STEP]', 'type:', data.type, 'tool:', data.tool, 'status:', data.status, 'in FINAL:', FINAL_PLANNING_TOOLS.includes(data.tool));
                            if (data.status === 'done' && data.tool && FINAL_PLANNING_TOOLS.includes(data.tool)) {
                                uiDebugLog('[SSE-STEP] FINAL tool done:', data.tool, '- scheduling refreshPlanningUI');
                                _scheduleCasePlanningRefresh(turnSessionId, 250);
                            }
                            // SEGMENTATION TOOLS: after CTV/OAR seg completes,
                            // load label volumes so masks appear in viewer + data tree.
                            // Without this, masks are stored server-side but never
                            // fetched by the frontend.
                            if (data.status === 'done' && data.tool && SEG_TOOLS.includes(data.tool)) {
                                uiDebugLog('[SSE-STEP] Segmentation done:', data.tool, '- loading label volumes');
                                if (typeof loadLabelVolumes === 'function') {
                                    loadLabelVolumes().then(() => {
                                        if (String(activeSessionId || '') !== turnSessionId) return;
                                        if (typeof renderDataTree === 'function') renderDataTree();
                                        if (typeof startSegmentationMeshPrewarm === 'function') {
                                            startSegmentationMeshPrewarm(data.tool === 'ctv_segmentation' ? 'ctv' : 'oar');
                                        }
                                    }).catch(e => console.warn('[SSE-STEP] loadLabelVolumes failed:', e));
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
                            if (!responseEl && typeof createStreamingResponse === 'function') {
                                if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
                                responseEl = createStreamingResponse();
                                if (todo && responseEl.parentElement) responseEl.parentElement.appendChild(todo.root);
                            }
                        }
                        responseText += String(data.text);
                        if (responseEl && typeof updateStreamingResponse === 'function') {
                            responseEl.classList.add('is-streaming');
                            responseEl.setAttribute('aria-busy', 'true');
                            updateStreamingResponse(responseEl, responseText);
                        }
                        scrollToBottom();
                    } else if (currentEvent === 'response' && data && data.response) {
                        // The final response event is emitted only after the
                        // required review gate. Create the answer bubble here,
                        // rather than on the first draft chunk.
                        if (!finalResponseReceived) {
                            finalResponseReceived = true;
                        } else {
                            continue;
                        }
                        responseText = data.response;
                        if (!responseEl && typeof createStreamingResponse === 'function') {
                            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
                            responseEl = createStreamingResponse();
                            if (todo && responseEl.parentElement) responseEl.parentElement.appendChild(todo.root);
                        }
                        if (responseEl && typeof updateStreamingResponse === 'function') {
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
                        }
                    } else if (currentEvent === 'error' && data && data.message) {
                        turnFailed = true;
                        _setCaseTaskState(turnSessionId, 'failed', null);
                        if (typeof addChat === 'function') {
                            addChat('error', 'AI error: ' + data.message, true, Date.now(), false, turnSessionId);
                        }
                    } else if (currentEvent === 'done') {
                        // Server says stream is complete
                        turnCompleted = true;
                        turnCancelled = Boolean(data?.cancelled);
                        const terminalStatus = turnCancelled ? 'cancelled' : (turnFailed ? 'failed' : 'completed');
                        _setCaseTaskState(turnSessionId, terminalStatus, null);
                        delete window._detachedChatTasks[turnSessionId];
                        if (turnCancelled) {
                            // A replaying browser can receive the terminal
                            // cancellation event without having initiated the
                            // Stop click itself. Do not manufacture a blank
                            // assistant answer from that terminal state.
                            cancelTurnUi('Stopped');
                            break readLoop;
                        }
                        // BUG FIX 2026-06-17: stamp a plan-completion
                        // timestamp so autoCaptureReportFigures can
                        // detect and discard stale auto-captured
                        // figures when the user re-runs planning.
                        try {
                            if (window.state && window.state.metrics && window.state.metrics.plan_score != null) {
                                window.state.lastPlanTimestamp = new Date().toISOString();
                            }
                        } catch (_) {}
                        // FALLBACK: if planning tools ran but
                        // refreshPlanningUI was never triggered (e.g.
                        // the FINAL_PLANNING_TOOLS check didn't fire
                        // because the step event format changed),
                        // trigger a refresh now on stream completion.
                        const _planningToolsInSteps = steps.filter(s => s.type === 'tool' && s.status === 'done'
                            && ['planning_pipeline', 'dose_evaluation', 'dose_eval', 'seed_planning'].includes(s.tool));
                        uiDebugLog('[SSE-done] planning tools in steps:', _planningToolsInSteps.map(s => s.tool));
                        if (_planningToolsInSteps.length > 0) {
                            uiDebugLog('[SSE-done] Triggering fallback refreshPlanningUI');
                            _scheduleCasePlanningRefresh(turnSessionId, 500);
                        }
                        // Do not wait for a post-terminal chunk.  Flask may
                        // keep the HTTP connection reusable, but the chat
                        // turn is complete at this protocol boundary.
                        break readLoop;
                    }
                }
            }
        }

        // A case selection detached this browser stream. Do not run terminal
        // screenshot/final-response work against the newly visible case; the
        // owning server task and its event journal remain available when the
        // user returns to that case.
        if (activeSessionId !== turnSessionId) return;

        if (turnCancelled) return;

        // Keep screenshot capture/upload inside the same logical turn. This
        // guarantees that the hidden multimodal follow-up is queued before the
        // stream transitions to idle and starts flushing follow-up requests.
        if (screenshotTasks.length) {
            await Promise.allSettled(screenshotTasks);
        }
        if (uiActionTasks.length) {
            await Promise.allSettled(uiActionTasks);
        }
        if (String(activeSessionId || '') !== turnSessionId) return;

        // A screenshot requested for explanation is visual context, not the
        // final answer. Send exactly one hidden multimodal follow-up after all
        // captures have uploaded. The hidden request is intentionally not a
        // new screenshot command, so the model must analyze the image and the
        // completeness checker can validate the actual user request.
        if (screenshotResults.length && _isVisualAnalysisRequest(text)) {
            const uniqueUrls = [...new Set(screenshotResults.map(item => item.url).filter(Boolean))].slice(0, 4);
            if (uniqueUrls.length) {
                const visualContext = uniqueUrls.map(url => `[Screenshot captured: ${url}]`).join('\n');
                _enqueueHiddenChat(
                    `${visualContext}\n\nUser request: ${text}\nAnalyze the supplied screenshot(s) and answer the user's request directly. Do not request another screenshot. Mention uncertainty instead of inventing details.`,
                    { visualFollowUp: true }
                );
            }
        }

        // No steps arrived — clean up the thinking indicator
        if (!chainEl) {
            if (thinkingEl && typeof removeThinkingIndicator === 'function') removeThinkingIndicator(thinkingEl);
        } else {
            if (typeof finalizeThinkingChain === 'function') {
                finalizeThinkingChain(chainEl, headerEl, steps);
            }
            try { saveSessionMessage('thinking', '', steps, Date.now(), turnSessionId); } catch (_) {}
        }

        // SAFETY: fold the todo when the stream ends, even if the
        // server never sent the final 'assistant' event (e.g.
        // network drop, timeout, crash). Without this, the todo
        // stays unfolded with timers running forever.
        if (todo && typeof todo.fold === 'function') {
            try { todo.fold(); } catch (_) {}
        }

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
        const finalText = finalResponseReceived
            ? (responseText || '(no reply)')
            : '(No validated response was returned. Please retry.)';
        // For an analysis request the acknowledgement is only an internal
        // capture phase; keep the chat clean and show the later multimodal
        // answer instead. For a pure screenshot request the gallery itself is
        // the answer, matching the existing UI behavior.
        const suppressScreenshotAck = _isScreenshotAckResponse(finalText, steps);
        if (suppressScreenshotAck && responseEl) {
            try {
                const staleRow = responseEl.closest('.chat-row');
                if (staleRow) staleRow.remove();
            } catch (_) {}
            responseEl = null;
        }
        if (!suppressScreenshotAck && responseEl && typeof finalizeStreamingResponse === 'function') {
            finalizeStreamingResponse(responseEl, finalText, turnSessionId);
        } else if (!suppressScreenshotAck && !responseEl && !window._chatFallbackUsed) {
            window._chatFallbackUsed = true;
            if (typeof addChat === 'function') {
                addChat('bot-response', finalText, true, Date.now(), false, turnSessionId);
            }
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
                    if (footer) wrapper.appendChild(footer);
                }
            } catch (_) { /* footer is best-effort */ }
        }
    } catch (e) {
        const detached = window._chatDetachRequestedFor === turnSessionId
            || String(activeSessionId || '') !== turnSessionId;
        if (detached) return;

        const taskStatus = window._sessionChatTaskStatuses?.[turnSessionId];
        const explicitlyStopped = !!window._explicitChatStopSessions?.[turnSessionId]
            || taskStatus === 'cancelled';
        const interruptedStream = e?.name === 'AbortError'
            || /abort|timed out|network|fetch/i.test(String(e?.message || ''));

        if (explicitlyStopped) {
            cancelTurnUi('Stopped');
            _setCaseTaskState(turnSessionId, 'cancelled', null);
            if (typeof addChat === 'function') {
                addChat('system', 'Stopped.', true, Date.now(), false, turnSessionId);
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
                if (typeof addChat === 'function') {
                    addChat('system', 'Connection interrupted; restoring live progress...', true, Date.now(), false, turnSessionId);
                }
            } else {
                turnFailed = true;
                _setCaseTaskState(turnSessionId, 'failed', null);
                if (typeof addChat === 'function') {
                    addChat('error', 'Send failed: ' + (e?.message || e), true, Date.now(), false, turnSessionId);
                }
            }
        } else {
            turnFailed = true;
            _setCaseTaskState(turnSessionId, 'failed', null);
            if (typeof addChat === 'function') {
                addChat('error', 'Send failed: ' + (e?.message || e), true, Date.now(), false, turnSessionId);
            } else {
                console.error('sendChat failed and addChat missing:', e);
            }
        }
    } finally {
        const isCurrentTurn = window._chatTurnCancelUi === cancelTurnUi;
        if (isCurrentTurn) {
            window._chatTurnActive = false;
            window._chatTurnCancelUi = null;
        }
        if (chatAbortController === turnAbortController) chatAbortController = null;
        if (window._activeChatTaskSessionId === turnSessionId
            && (turnCompleted || turnFailed || !reconnectNeeded)) {
            window._activeChatTaskId = null;
            window._activeChatTaskSessionId = null;
        }
        if (isCurrentTurn) {
            window._chatStreaming = false;
            setStreamingState(false);
            setTimeout(() => { try { _flushHiddenChatQueue(); } catch (_) {} }, 0);
            if (turnCompleted) {
                setTimeout(() => { try { _flushQueuedChatTurns(); } catch (_) {} }, 0);
            }
        }
        if (reconnectNeeded && activeSessionId === turnSessionId) {
            setTimeout(() => {
                try { window.resumeSessionChatTask?.(); } catch (_) {}
            }, 350);
        }
    }
}

window.resumeSessionChatTask = async function resumeSessionChatTask() {
    const sessionId = activeSessionId;
    if (!sessionId || window._chatTurnActive || window._chatStreaming) return false;
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
        if (!response.ok) return false;
        const payload = await response.json();
        // A newer switch can happen while the task status request is in
        // flight. Do not attach this replay to another case's chat shell.
        if (activeSessionId !== sessionId) return false;
        const task = payload?.task;
        // The server owns task identity. Browser memory and a workspace
        // checkpoint are only hints because either can be stale after a
        // refresh, a case switch, or a fast task finalization race.
        if (!task || task.status !== 'running') {
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
            }
            if (typeof window.flushQueuedChatTurns === 'function') {
                setTimeout(() => window.flushQueuedChatTurns(), 0);
            }
            return false;
        }
        const taskId = task.task_id;
        window._sessionChatTaskIds[sessionId] = taskId;
        window._sessionChatTaskStatuses = window._sessionChatTaskStatuses || {};
        window._sessionChatTaskStatuses[sessionId] = 'running';
        delete window._detachedChatTasks[sessionId];
        // Two snapshot applications can race on a cold restore. Re-check
        // after the status request so the second one cannot enter sendChat()
        // and accidentally stop the first replay stream.
        if (window._chatTurnActive || window._chatStreaming || activeSessionId !== sessionId) return false;
        await sendChat(null, {
            resumeTaskId: taskId,
            resumeMessage: task.message || '',
            skipIntentShortcuts: true,
            preserveLastUserMessage: true,
        });
        return true;
    } catch (error) {
        console.warn('[chat] task resume deferred:', error);
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
