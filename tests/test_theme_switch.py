"""Regression checks for the global light/dark appearance switch."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_theme_switch_is_globally_wired_and_defaults_to_dark():
    index = read("web/app/index.html")
    theme_js = read("web/app/static/js/brachybot-theme.js")
    theme_css = read("web/app/static/css/brachybot-theme-layout.css")
    light_css = read("web/app/static/css/brachybot-theme-light.css")

    assert '<html lang="en" data-theme="dark">' in index
    assert "brachybot_ui_theme" in index
    assert 'data-theme-toggle' in index
    assert 'brachybot-theme-light.css?v=1' in index
    assert 'brachybot-theme.js?v=1' in index
    assert "window.setUiTheme = applyTheme" in theme_js
    assert "window.localStorage.setItem(STORAGE_KEY, theme)" in theme_js
    assert 'document.documentElement.setAttribute(\'data-theme\', theme)' in theme_js
    assert "window.addEventListener('i18nchange'" in theme_js
    assert '--control-scheme: dark' in theme_css
    assert '[data-theme="light"]' in light_css


def test_light_theme_covers_legacy_dark_only_chat_and_viewer_surfaces():
    light_css = read("web/app/static/css/brachybot-theme-light.css")

    for selector in (
        ".chat-msg.bot",
        ".md-table",
        ".viewers-panel.layout-grid",
        ".viewers-panel.layout-grid .data-tree-container",
        ".guide-parameters",
    ):
        assert selector in light_css
