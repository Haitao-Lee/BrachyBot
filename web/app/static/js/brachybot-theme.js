/* BrachyBot global appearance switch.
   Keep this as a small classic script because the rest of the workspace still
   exposes a window-level UI API. The HTML bootstrap applies the saved theme
   before paint; this file owns interaction, persistence, and labels. */
(function () {
    'use strict';

    var STORAGE_KEY = 'brachybot_ui_theme';
    var COPY = {
        dark: {
            en: 'Switch to light theme',
            zh: '\u5207\u6362\u5230\u6d45\u8272\u4e3b\u9898'
        },
        light: {
            en: 'Switch to dark theme',
            zh: '\u5207\u6362\u5230\u6df1\u8272\u4e3b\u9898'
        }
    };

    function normalizeTheme(value) {
        return value === 'light' ? 'light' : 'dark';
    }

    function readStoredTheme() {
        try {
            return normalizeTheme(window.localStorage.getItem(STORAGE_KEY));
        } catch (error) {
            return 'dark';
        }
    }

    function currentLanguage() {
        return window._i18nLang === 'zh' ? 'zh' : 'en';
    }

    function updateButton(theme) {
        var button = document.querySelector('[data-theme-toggle]');
        if (!button) return;

        var language = currentLanguage();
        var label = COPY[theme][language];
        button.setAttribute('aria-pressed', theme === 'light' ? 'true' : 'false');
        button.setAttribute('aria-label', label);
        button.setAttribute('title', label);
        button.dataset.theme = theme;

        var moon = button.querySelector('[data-theme-icon="moon"]');
        var sun = button.querySelector('[data-theme-icon="sun"]');
        if (moon) moon.hidden = theme === 'light';
        if (sun) sun.hidden = theme !== 'light';
    }

    function applyTheme(value, options) {
        var theme = normalizeTheme(value);
        var settings = options || {};
        document.documentElement.setAttribute('data-theme', theme);
        document.documentElement.style.colorScheme = theme;
        updateButton(theme);

        if (settings.persist !== false) {
            try {
                window.localStorage.setItem(STORAGE_KEY, theme);
            } catch (error) {
                /* Private browsing or disabled storage must not break the UI. */
            }
        }

        window.dispatchEvent(new CustomEvent('themechange', {
            detail: { theme: theme }
        }));
        return theme;
    }

    function getCurrentTheme() {
        return normalizeTheme(document.documentElement.getAttribute('data-theme'));
    }

    function toggleTheme() {
        return applyTheme(getCurrentTheme() === 'dark' ? 'light' : 'dark');
    }

    function bindThemeControl() {
        var button = document.querySelector('[data-theme-toggle]');
        if (!button || button.dataset.themeBound === 'true') return;
        button.dataset.themeBound = 'true';
        button.addEventListener('click', toggleTheme);
        applyTheme(readStoredTheme(), { persist: false });
    }

    window.getUiTheme = getCurrentTheme;
    window.setUiTheme = applyTheme;
    window.toggleUiTheme = toggleTheme;

    window.addEventListener('i18nchange', function () {
        updateButton(getCurrentTheme());
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindThemeControl, { once: true });
    } else {
        bindThemeControl();
    }
}());
