/* Input actions own their initiating case, decoded image and request lifetime.
 * A late result can remain saved on the server without repainting another case. */
(function () {
    'use strict';
    const pending = new Map();
    const session = () => String(typeof _activeApiSessionId === 'function' ? _activeApiSessionId() || '' : '');
    const t = (zh, en) => typeof window._t === 'function' ? window._t(zh, en) : en;
    window.beginInputAction = function (key, options = {}) {
        const sid = session();
        if (!sid) throw new Error(t('请等待病例工作区就绪。', 'Wait for the case workspace to be ready.'));
        const lock = `${sid}:${options.mutation ? 'mutation' : key}`;
        if (pending.has(lock) || (options.mutation && window.manualStepRequestPending?.())) {
            throw new Error(t('当前操作仍在执行，请等待完成。', 'An operation is still running; wait for it to finish.'));
        }
        const generation = window.__viewerRenderGeneration || 0;
        const path = String(document.getElementById('ctPath')?.value || '').trim();
        if (options.image && (!path || state.ctLoaded !== true || String(state.ctPath || '') !== path)) {
            throw new Error(t('请先加载所选影像并等待就绪。', 'Load the selected image and wait until it is ready.'));
        }
        const token = {sessionId: sid, ctPath: path, key,
            current: () => sid === session() && generation === (window.__viewerRenderGeneration || 0),
            headers: {'Content-Type': 'application/json', 'X-BrachyBot-Session': sid},
            finish: () => { if (pending.get(lock) === token) pending.delete(lock); window._refreshManualStepUI?.(); },
        };
        pending.set(lock, token);
        window._refreshManualStepUI?.();
        return token;
    };
    window.inputMutationPending = () => pending.has(`${session()}:mutation`);
    window.fetchInputJson = async function (token, path, body) {
        if (!token.current()) return null;
        const response = await fetch(API + path, {method: 'POST', headers: token.headers, body: JSON.stringify(body || {})});
        const data = await response.json().catch(() => null);
        if (!token.current()) return null;
        if (!response.ok || !data || data.success === false || data.error) {
            throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
        }
        if (response.status === 202) throw new Error(t('病例资源仍在加载，请稍后重试。', 'Case resources are still loading; retry when ready.'));
        return data;
    };
    window.presentInputDownloads = function (token, urls, label) {
        if (!token.current()) return;
        const safe = [...new Set((urls || []).filter(url => typeof url === 'string'
            && url.startsWith(`/api/sessions/${token.sessionId}/artifacts/`)))];
        if (!safe.length) throw new Error(t('文件已生成，但没有有效的病例下载地址。', 'Files were generated without a valid case-owned download URL.'));
        // Keep authenticated links available without triggering dozens of automatic downloads.
        addChat('bot-response', `${label}\n\n` + safe.map((url, i) => `- [${t('下载', 'Download')} ${i + 1}](${url})`).join('\n'));
    };
    document.addEventListener('DOMContentLoaded', () => {
        // A fixed trained model is not retrained by the Input panel. Likewise,
        // clinical label semantics cannot be changed by legacy numeric labels.
        const unsupported = ['seedCountMin', 'seedCountMax', 'seedAvgDose', 'targetValue', 'obstacleValue', 'backgroundValue',
            'direcResCone', 'direcResStep', 'direcResRings', 'dlLR', 'dlLRDecay', 'dlEpochs', 'dlPatience',
            'dlSearchRegion', 'dlDVHMargin', 'inferSizeX', 'inferSizeY', 'inferSizeZ'];
        unsupported.forEach(id => {
            const input = document.getElementById(id);
            if (!input) return;
            input.disabled = true;
            const zh = '只读：该字段不属于当前规划器可调整的参数。标签由结构集决定，模型设置已固定。';
            const en = 'Read-only: not adjustable by the current planner. Labels are Structure Set-owned; trained model settings are fixed.';
            input.setAttribute('data-i18n-title-zh', zh);
            input.setAttribute('data-i18n-title-en', en);
            input.title = t(zh, en);
        });
        for (const id of ['iterRate', 'intervalRate']) {
            const input = document.getElementById(id);
            if (input) { input.min = '1'; input.step = '1'; }
        }
    });
})();
