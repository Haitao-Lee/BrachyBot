/*
 * Small, keyboard-accessible step buttons for native range controls.
 *
 * Native range inputs remain the source of truth. The buttons only move the
 * same input by its declared step and dispatch the normal input/change events,
 * so existing viewer, Data Tree, persistence, and UI-bridge handlers keep
 * their original path.
 */
(function installRangeStepper(window, document) {
    'use strict';

    if (!window || !document) return;

    const WINDOW_RANGE_SELECTOR = 'input[type="range"][data-ct-window-level]';
    const RANGE_SELECTOR = 'input[type="range"]';
    const STEP_BUTTON_SELECTOR = '[data-range-step-target][data-range-step]';

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function decimalPlaces(value) {
        const text = String(value);
        if (!text.includes('.')) return 0;
        return Math.min(8, text.split('.')[1].length);
    }

    function rangeBounds(input) {
        const min = finite(input.min, 0);
        const max = finite(input.max, 100);
        return {
            min: Math.min(min, max),
            max: Math.max(min, max),
        };
    }

    function rangeStep(input) {
        const step = Number(input.step);
        return Number.isFinite(step) && step > 0 ? step : 1;
    }

    function clampAndRound(input, value) {
        const bounds = rangeBounds(input);
        const step = rangeStep(input);
        const precision = Math.min(
            8,
            Math.max(decimalPlaces(step), decimalPlaces(bounds.min)),
        );
        const factor = 10 ** precision;
        const rounded = Math.round((value + Number.EPSILON) * factor) / factor;
        return Math.max(bounds.min, Math.min(bounds.max, rounded));
    }

    function rangeLabel(input) {
        return input.getAttribute('aria-label')
            || input.getAttribute('title')
            || input.id
            || 'range value';
    }

    function targetButtons(input) {
        if (!input?.id) return [];
        return Array.from(document.querySelectorAll(STEP_BUTTON_SELECTOR))
            .filter(button => button.dataset.rangeStepTarget === input.id);
    }

    function syncButtonState(input) {
        if (!input) return;
        const bounds = rangeBounds(input);
        const value = finite(input.value, bounds.min);
        const wrapper = input.closest?.('.range-stepper');
        const buttons = wrapper
            ? wrapper.querySelectorAll('.range-stepper-btn')
            : targetButtons(input);
        buttons.forEach(button => {
            const direction = Number(
                button.dataset.rangeStepDirection || button.dataset.rangeStep || 0,
            );
            button.disabled = input.disabled
                || (direction < 0 && value <= bounds.min)
                || (direction > 0 && value >= bounds.max);
        });
    }

    function dispatchRangeChange(input) {
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function stepRange(input, direction) {
        if (!input || input.disabled) return false;
        const delta = Number(direction);
        if (!Number.isFinite(delta) || delta === 0) return false;

        const bounds = rangeBounds(input);
        const current = finite(input.value, bounds.min);
        const next = clampAndRound(
            input,
            current + (rangeStep(input) * Math.sign(delta)),
        );
        input.value = String(next);
        try {
            input.focus({ preventScroll: true });
        } catch (_) {
            try { input.focus(); } catch (_) {}
        }
        dispatchRangeChange(input);
        syncButtonState(input);
        return true;
    }

    function button(label, direction) {
        const control = document.createElement('button');
        control.type = 'button';
        control.className = [
            'range-stepper-btn',
            direction < 0
                ? 'range-stepper-btn--decrease'
                : 'range-stepper-btn--increase',
        ].join(' ');
        control.dataset.rangeStepDirection = String(direction);
        control.setAttribute(
            'aria-label',
            (direction < 0 ? 'Decrease ' : 'Increase ')
                + label
                + ' by one step',
        );
        control.title = (direction < 0 ? 'Decrease ' : 'Increase ')
            + label
            + ' by one step';
        return control;
    }

    function enhanceRangeControl(input) {
        if (!input || input.matches(WINDOW_RANGE_SELECTOR)) return false;
        if (input.dataset.rangeStepperEnhanced === '1') return false;
        if (input.closest('.range-stepper')) return false;
        if (!input.parentNode) return false;

        const wrapper = document.createElement('span');
        wrapper.className = 'range-stepper';
        wrapper.dataset.rangeStepperFor = input.id || 'range';

        const inlineWidth = input.style?.width || '';
        if (inlineWidth) {
            // Keep the original slider track width and add room for the two
            // buttons. This matters for compact controls such as Mesh Op and
            // Label Op, where shrinking the track would make dragging harder.
            wrapper.style.width = 'calc(' + inlineWidth + ' + 26px)';
            input.style.width = 'auto';
            input.style.flex = '1 1 auto';
            input.style.minWidth = '0';
        } else if (input.closest('.viewer-card-ctrl')) {
            // Slice and full-width viewer controls used to grow through the
            // viewer-card-ctrl flex rule. Move that growth to the wrapper.
            wrapper.classList.add('range-stepper--fill');
        }

        input.dataset.rangeStepperEnhanced = '1';
        const label = rangeLabel(input);
        const decrease = button(label, -1);
        const increase = button(label, 1);

        decrease.addEventListener('pointerdown', event => {
            event.stopPropagation();
        });
        increase.addEventListener('pointerdown', event => {
            event.stopPropagation();
        });
        decrease.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            stepRange(input, -1);
        });
        increase.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            stepRange(input, 1);
        });
        input.addEventListener('input', () => syncButtonState(input));
        input.addEventListener('change', () => syncButtonState(input));

        input.parentNode.insertBefore(wrapper, input);
        wrapper.append(decrease, input, increase);
        syncButtonState(input);
        return true;
    }

    function stepTargetButton(buttonElement) {
        const targetId = buttonElement?.dataset?.rangeStepTarget;
        const input = targetId ? document.getElementById(targetId) : null;
        if (!input) return false;
        return stepRange(input, Number(buttonElement.dataset.rangeStep));
    }

    function enhanceRangeControls(root) {
        const scope = root && root.querySelectorAll ? root : document;
        scope.querySelectorAll(RANGE_SELECTOR).forEach(enhanceRangeControl);
        scope.querySelectorAll(STEP_BUTTON_SELECTOR).forEach(buttonElement => {
            const targetId = buttonElement.dataset.rangeStepTarget;
            const input = targetId ? document.getElementById(targetId) : null;
            if (input) syncButtonState(input);
        });
    }

    document.addEventListener('click', event => {
        const target = event.target?.closest?.(STEP_BUTTON_SELECTOR);
        if (!target) return;
        event.preventDefault();
        event.stopPropagation();
        stepTargetButton(target);
    }, true);

    window.stepRangeControl = stepRange;
    window.enhanceRangeControls = enhanceRangeControls;

    enhanceRangeControls(document);

    if (window.MutationObserver && document.body) {
        let queued = false;
        const observer = new MutationObserver(() => {
            if (queued) return;
            queued = true;
            const run = () => {
                queued = false;
                enhanceRangeControls(document);
            };
            if (typeof window.queueMicrotask === 'function') {
                window.queueMicrotask(run);
            } else {
                window.setTimeout(run, 0);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }
})(window, document);
