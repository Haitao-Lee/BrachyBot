# BrachyBot Web UI — New Dark Theme ("NightShift Indigo") Design Spec

Date: 2026-07-24
Status: Approved (方案 A)

## Goal

Replace the current dark "Quiet Glass v2" theme with a brand-new dark theme.
DOM structure, class names, and all JavaScript behavior remain untouched —
this is a pure visual-layer (CSS) reskin.

## Direction

Radiology-console inspired dark UI:
- Near-black slate canvas with subtle blue-tinted elevation tiers
- Electric indigo accent for primary actions, focus rings, and active states
- Hairline borders with indigo luminous glow on interactive elements
- Status colors lifted for WCAG AA contrast on dark backgrounds

## Token Specification

| Token group | Value |
|---|---|
| Canvas | `#0a0f1c` |
| Surface 1 (panel) | `#0f1526` |
| Surface 2 (elevated) | `#141b30` |
| Sunken well | `#0c1220` |
| Accent (primary) | `#4f7cff`, hover `#6b8fff`, ink `#c7d5ff` |
| Accent soft bg | `rgba(79,124,255,0.12)` |
| Hairline border | `rgba(120,140,200,0.10)`, strong `rgba(120,140,200,0.16)` |
| Text | `#e8edf7` / secondary `#9aa7c4` / dim `#5d6a8a` |
| Success | `#34d399` |
| Warning | `#fbbf24` |
| Danger | `#fb7185` |
| Info | `#38bdf8` |
| Focus ring | `0 0 0 3px rgba(79,124,255,0.28)` |
| Radii | xs 6 / sm 10 / md 14 / lg 18 / xl 24 (unchanged scale) |
| Fonts | Space Grotesk (display, letter-spacing -0.02em), Inter (body), JetBrains Mono (code) — unchanged |

## Signature details

1. Indigo glow on focused inputs (`--control-focus-ring`)
2. Status pills with colored leading dot
3. Slim custom scrollbars tinted with the slate palette
4. Chat bubbles: user = indigo-tinted glass, assistant = elevated slate
5. Todo/Progress dock: unified indigo/cyan accent, breathing animation kept
6. Shadows: deeper ambient + indigo ring on floating elements

## Scope

| File | Action |
|---|---|
| `static/css/brachybot-theme-layout.css` | Rewrite `:root` + `[data-theme="dark"]` token blocks; refresh layout-level styles |
| `static/css/brachybot-panels-viewers.css` | Replace hardcoded colors with tokens; polish panels, data tree, viewers |
| `static/css/brachybot-chat-status.css` | Polish chat bubbles, thinking chain, todo dock, markdown blocks |
| `static/css/brachybot-report-controls.css` | Polish report/editor controls |
| `static/css/brachybot-responsive.css` | Verify no color regressions on mobile breakpoints |
| `static/css/brachybot-auth.css` | Align auth overlay with new theme |
| `web/app/index.html` | Bump CSS cache-busting query (`?v=N+1`) |

## Non-goals

- No DOM structure changes, no class renames, no JS changes
- No new dependencies or fonts
- Light theme not re-designed (dark stays default)

## Verification

- Playwright screenshot of main UI before/after
- `git diff --check` passes
- Manual check: chat, panels, data tree, todo dock, report editor, auth overlay
