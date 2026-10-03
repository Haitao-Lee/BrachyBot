# BrachyBot Web UI Design Audit Report

**Audit Date:** 2026-05-31
**Audit Scope:** Web UI overall layout, user experience, interaction design, responsive layout
**Screenshot Directory:** `screenshots/`
**Code File:** `web/app/index.html`

---

## 1. Overall Assessment

| Dimension | Score | Notes |
|------|------|------|
| **Visual Design** | 8/10 | Modern dark theme, consistent color palette |
| **Information Architecture** | 7/10 | Clear three-column layout, sensible Tab switching |
| **Interaction Design** | 7/10 | Basic interactions are smooth, some details need improvement |
| **User Experience** | 7/10 | Feature-complete, moderate learning curve |
| **Accessibility** | 5/10 | Lacks keyboard navigation, no ARIA labels |

**Overall Score: 7/10**

---

## 2. Global View

### 2.1 Full Page Layout

![Full Page Layout](screenshots/design_01_full_page.png)

**Layout Analysis:**
- **Three-column layout**: left session list (260px) → center chat area (flex) → right panel (500px)
- **Header**: 48px in height, containing Logo, title, status indicator
- **Dark theme**: `#0f172a` main background, consistent with medical imaging tool conventions

---

## 3. Header Area

**Screenshots:** `screenshots/design_12_header.png`

![Header Area](screenshots/design_12_header.png)

**Code Location:** `index.html:1426-1443`

```html
<header class="header">
    <div class="header-logo">AI</div>
    <div class="header-title">BrachyBot</div>
    <div class="header-subtitle">AI Brachytherapy Planning</div>
    <div class="header-status">...</div>
</header>
```

### Issues and Recommendations

| Issue | Severity | Recommendation |
|------|---------|------|
| Logo text "AI" is not professional enough | Low | Replace with an SVG icon |
| Title font size 0.9rem is too small | Low | Change to 1.1rem |
| Status indicator dot is too small (6px) | Low | Can keep, since color and shadow already enhance it |

**Suggested Code:**
```css
.header-logo {
    width: 32px;
    height: 32px;
    /* Use SVG background image instead of plain text */
    background: linear-gradient(135deg, var(--primary), var(--accent));
    border-radius: 8px;
}

.header-title {
    font-size: 1.1rem;
    font-weight: 700;
}
```

---

## 4. Left Sidebar (Session List)

**Screenshots:** `screenshots/design_02_sidebar.png`, `screenshots/detail_13_sidebar_hover.png`

![Session List](screenshots/design_02_sidebar.png)

![Sidebar Hover](screenshots/detail_13_sidebar_hover.png)

**Code Location:** `index.html:90-207`, CSS `89-218`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Session names are not descriptive | Medium | "Item 1/2/3" does not help locate sessions | Show a summary of the first message or a timestamp |
| New button is not prominent enough | Low | Blends into the background | Use a gradient background color |
| Active state is not clearly distinguished | Low | No clear indication of the currently selected item | Add a left border highlight |

**Suggested Code:**
```css
.session-item.active {
    background: rgba(14, 165, 233, 0.12);
    border-left: 3px solid var(--primary);
}

.new-chat-btn {
    background: linear-gradient(135deg, var(--primary), var(--accent));
    color: white;
    font-weight: 600;
    border: none;
}

.new-chat-btn:hover {
    filter: brightness(1.1);
    transform: translateY(-1px);
}
```

---

## 5. Chat Area

### 5.1 Message Response Typography

**Screenshots:** `screenshots/detail_01_chat_response.png`, `screenshots/detail_04_code_block.png`, `screenshots/design_14_chat_response.png`

![Chat Response](screenshots/detail_01_chat_response.png)

![Code Block Response](screenshots/detail_04_code_block.png)

![Long Response](screenshots/design_14_chat_response.png)

**Code Location:** `index.html:326-526`, CSS `326-539`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Bot message width 85% < user message 88% | Low | Visually unbalanced | Unify to 85% or 80% |
| Code blocks have no copy button | Medium | Users must select manually | Add a 📋 icon button |
| Messages have no timestamp | Medium | Cannot determine conversation order | Add an HH:MM timestamp |
| Avatar 26px is too small | Low | Not clear enough on high-resolution screens | Change to 32px |

**Suggested Code:**
```css
/* Unify message width */
.chat-row {
    max-width: 85%;
}

.chat-msg.bot {
    max-width: 85%;  /* Consistent with user messages */
}

/* Enlarge avatar */
.chat-avatar {
    width: 32px;
    height: 32px;
    font-size: 0.75rem;
}

/* Add copy button to code blocks */
.md-code-block {
    position: relative;
    padding-right: 2.5rem;
}

.code-copy-btn {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    background: var(--bg-3);
    border: 1px solid var(--card-border);
    border-radius: 4px;
    padding: 0.25rem 0.5rem;
    font-size: 0.7rem;
    cursor: pointer;
    opacity: 0.7;
    transition: opacity 0.2s;
}

.code-copy-btn:hover {
    opacity: 1;
    background: var(--primary);
    color: white;
}

/* Add timestamp to messages */
.chat-msg .timestamp {
    font-size: 0.6rem;
    color: var(--text-dim);
    margin-top: 0.25rem;
    opacity: 0.7;
}
```

### 5.2 Message Action Buttons

**Screenshot:** `screenshots/detail_11_msg_hover.png`

![Message Hover](screenshots/detail_11_msg_hover.png)

**Code Location:** `index.html:454-477`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Action button position shifts on hover | Low | Button is outside the message | Keep it inside the top-right corner of the message |
| Button styles are not intuitive | Low | Icon only, no text | Add tooltips |

**Suggested Code:**
```css
.chat-msg-actions {
    top: 0;
    right: 0;
    background: transparent;
    border: none;
    padding: 0.25rem;
}

.chat-msg-action-btn {
    background: var(--bg-2);
    border: 1px solid var(--card-border);
    padding: 0.3rem 0.4rem;
    font-size: 0.7rem;
}

.chat-msg-action-btn:hover {
    background: var(--primary);
    color: white;
    border-color: var(--primary);
}
```

---

## 6. Input Area

**Screenshot:** `screenshots/design_05_input_area.png`

![Input Area](screenshots/design_05_input_area.png)

**Code Location:** `index.html:751-818`, CSS `751-818`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Send button 40px is too small | Low | Touch target too small | Change to 44px (minimum touch standard) |
| Missing shortcut command hints | Medium | New users do not know the available commands | Add 💡 hint text |
| Placeholder is not guiding enough | Low | "Type a message..." has no concrete example | Provide a concrete example |

**Suggested Code:**
```css
.chat-send {
    width: 44px;
    height: 44px;
}

.chat-hint {
    font-size: 0.65rem;
    color: var(--text-dim);
    margin-top: 0.4rem;
    display: flex;
    align-items: center;
    gap: 0.3rem;
}

.chat-hint span {
    background: var(--bg-3);
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
}

.chat-hint span:hover {
    background: var(--primary);
    color: white;
}
```

---

## 7. Right Panel

### 7.1 Panel Switching Tabs

**Screenshots:** `screenshots/design_06_right_panel.png`, `screenshots/design_07_panel_tabs.png`

![Right Panel](screenshots/design_06_right_panel.png)

![Tab Switching](screenshots/design_07_panel_tabs.png)

**Code Location:** `index.html:848-867`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Tabs have no icons | Medium | Text-only is slow to scan | Add simple icons |
| Click target is too small | Low | padding is only 0.6rem | Increase appropriately |

**Suggested Code:**
```css
.panel-tab {
    padding: 0.75rem 0.5rem;
    font-size: 0.72rem;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
}

.panel-tab svg {
    width: 14px;
    height: 14px;
    stroke: currentColor;
    fill: none;
    stroke-width: 2;
}
```

### 7.2 Input Form

**Screenshots:** `screenshots/design_08_input_form.png`, `screenshots/detail_10_input_form_full.png`

![Input Form](screenshots/design_08_input_form.png)

![Full Form](screenshots/detail_10_input_form_full.png)

**Code Location:** `index.html:869-926`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| File selection button is not prominent enough | Low | dashed border could be more obvious | Increase border width and background color |
| Section divider is too thin | Low | Grouping is not obvious enough | Use a gradient divider |
| Missing required-field indicators | Low | Field importance is unclear | Add a * indicator |

**Suggested Code:**
```css
.file-btn {
    border: 2px dashed var(--primary);
    background: rgba(14, 165, 233, 0.08);
    color: var(--primary);
    font-weight: 500;
}

.file-btn:hover {
    background: rgba(14, 165, 233, 0.15);
    border-style: solid;
}

.form-section-title::after {
    content: '';
    flex: 1;
    height: 1px;
    background: linear-gradient(to right, var(--card-border), transparent);
    margin-left: 0.5rem;
}

.form-label.required::after {
    content: ' *';
    color: var(--danger);
    font-weight: normal;
}
```

### 7.3 Analysis Panel

**Screenshot:** `screenshots/design_09_analysis_tab.png`

![Analysis Panel](screenshots/design_09_analysis_tab.png)

**Code Location:** `index.html:928-986`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| OAR table does not scroll | Low | Overflows the container when there is a lot of data | Add max-height + overflow-y: auto |
| Missing data export | Medium | Cannot download the report | Add an export button |

**Suggested Code:**
```css
.oar-table-wrapper {
    max-height: 180px;
    overflow-y: auto;
    margin-top: 0.5rem;
}

.oar-table {
    width: 100%;
    border-collapse: collapse;
}

.export-btn {
    background: var(--bg-3);
    border: 1px solid var(--card-border);
    border-radius: 6px;
    padding: 0.35rem 0.6rem;
    font-size: 0.7rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.3rem;
}

.export-btn:hover {
    background: var(--primary);
    color: white;
    border-color: var(--primary);
}
```

### 7.4 Seeds Panel

**Screenshot:** `screenshots/design_10_seeds_tab.png`

![Seeds Panel](screenshots/design_10_seeds_tab.png)

**Code Location:** `index.html:1007-1027`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Empty state lacks action guidance | Medium | Users do not know the next step | Add step-by-step guidance and shortcut buttons |
| Seed card layout is fixed | Low | Cannot be resized | Can keep, since the number of seeds is usually limited |

**Suggested Code:**
```html
<div class="empty-state">
    <div class="empty-state-icon">🎯</div>
    <div style="font-weight: 600; margin-top: 0.5rem;">No Seeds Planned</div>
    <div style="font-size: 0.7rem; color: var(--text-dim); margin-top: 0.75rem; line-height: 1.6;">
        Complete these steps to generate seeds:<br/>
        1. 📤 Load CT scan<br/>
        2. 🎯 Generate CTV/OAR segmentation<br/>
        3. 📐 Run trajectory planning
    </div>
    <button class="btn btn-primary" style="margin-top: 1rem;">
        Start Planning
    </button>
</div>
```

---

## 8. Viewer Panel

### 8.1 Layout Mode Comparison

**Screenshots:**
- `screenshots/detail_05_viewer_vertical.png` - Vertical layout
- `screenshots/detail_06_viewer_grid.png` - 2x2 grid
- `screenshots/detail_07_viewer_horizontal.png` - Horizontal layout
- `screenshots/detail_08_viewer_3d_top.png` - 3D top
- `screenshots/detail_09_viewer_3d_bottom.png` - 3D bottom

| Layout | Screenshot | Pros | Cons |
|------|------|------|------|
| Vertical (default) | detail_05 | Clear slice comparison | Takes up a lot of space |
| Grid 2x2 | detail_06 | View 4 at once | 3D is compressed |
| Horizontal | detail_07 | Suited to wide screens | Requires horizontal scrolling |
| 3D top | detail_08 | 3D stands out | 2D width is fixed |
| 3D bottom | detail_09 | 2D takes priority | 3D position is inconvenient |

![Vertical Layout](screenshots/detail_05_viewer_vertical.png)

![Grid Layout](screenshots/detail_06_viewer_grid.png)

![Horizontal Layout](screenshots/detail_07_viewer_horizontal.png)

![3D Top](screenshots/detail_08_viewer_3d_top.png)

![3D Bottom](screenshots/detail_09_viewer_3d_bottom.png)

**Code Location:** `index.html:1103-1285`

### 8.2 Grid Layout 2x2 Detailed Analysis

**Current CSS (Problematic Code):**
```css
/* Grid: 2x2 with fixed row heights */
.viewers-panel.layout-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: minmax(200px, 1fr) minmax(200px, 1fr);
    gap: 0.5rem;
}
.viewers-panel.layout-grid > .viewer-card {
    height: auto;
    min-height: 0;
}

/* ⚠️ Issue: orphaned CSS fragment */
height: auto;      /* not inside any selector */
min-height: 120px;  /* lines 1193-1194, CSS syntax error */
```

**Issue Analysis:**

| Issue | Severity | Code Location | Description |
|------|---------|---------|------|
| **Orphaned CSS fragment** | High | `index.html:1193-1194` | `height: auto; min-height: 120px;` is not wrapped in a selector, a syntax error |
| 2x2 grid divides space equally | Medium | `index.html:1126-1127` | 4 Viewers (Axial/Sagittal/Coronal/3D) share space equally, but 3D usually needs more space |
| gap 0.5rem is too small | Low | `index.html:1128` | Medical image comparison needs more spacing, 0.75rem recommended |
| 3D viewer is compressed in the grid | Medium | `index.html:1130-1133` | `height: auto` may cause the 3D card to display too small |
| Card height is automatic | Low | `index.html:1131` | `height: auto` depends on content height, may be inconsistent |

**Screenshot Analysis:**

As seen in `detail_06_viewer_grid.png`:
- 4 Viewers are evenly distributed in a 2x2 grid
- Each card has the same height, but the 3D view usually needs more vertical space
- Axial/Sagittal/Coronal are suited to a square or 4:3 ratio
- The 3D reconstruction view is better suited to 16:9 or a larger ratio

**Suggested Fix:**
```css
/* Fix the orphaned CSS fragment - delete lines 1193-1194 */

/* Improve grid layout */
.viewers-panel.layout-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: minmax(180px, 1fr) minmax(180px, 1fr);
    gap: 0.75rem;  /* increase from 0.5rem to 0.75rem */
}

.viewers-panel.layout-grid > .viewer-card {
    height: auto;
    min-height: 0;
    /* Make the 3D card visually stand out more */
    border: 2px solid transparent;
    transition: border-color 0.2s;
}

.viewers-panel.layout-grid > .viewer-card.viewer-card-3d {
    border-color: var(--accent);  /* Distinguish the 3D card with a purple border */
}

/* Alternatively: consider a non-equal layout where 3D takes more space */
.viewers-panel.layout-grid-3d-large {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    /* Use grid-template-areas to allocate space better */
    grid-template-areas:
        "axial sagittal"
        "coronal 3d";
}

.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(1) { grid-area: axial; }
.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(2) { grid-area: sagittal; }
.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(3) { grid-area: coronal; }
.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(4) { grid-area: 3d; }
```

### 8.3 3D Top/Bottom Layout Analysis

**Current CSS:**
```css
/* 3D-top: 3D on top, 2D slices at the bottom */
.viewers-panel.layout-3d-top > .viewer-card-3d {
    height: 300px;
}

.viewers-panel.layout-3d-top .viewers-row > .viewer-card {
    width: 320px;   /* fixed width, may not fit all screens */
    height: 260px;
}

/* 3D-bottom: 3D at the bottom, 2D slices on top */
.viewers-panel.layout-3d-bottom .viewers-row > .viewer-card {
    width: 320px;   /* same problem */
    height: 260px;
}
```

**Issue Analysis:**

| Issue | Severity | Code Location | Description |
|------|---------|---------|------|
| 2D slices have a fixed width of 320px | Medium | `index.html:1166, 1184` | Wastes space on large screens, does not fit on small screens |
| 3D height is fixed at 300px | Low | `index.html:1156, 1190` | Cannot adjust based on content |
| Horizontal layout does not support ratio adjustment | Medium | `index.html:1135-1146` | flex: 1 but limited by min-width |

**Screenshot Analysis:**

As seen in `detail_08_viewer_3d_top.png` and `detail_09_viewer_3d_bottom.png`:
- The 3D card is fixed at the top or bottom
- Three 2D slices are displayed side by side, but with a fixed width of 320px
- On a 1920px screen, there is a lot of empty space on both sides

**Suggested Fix:**
```css
/* 3D top layout improvements */
.viewers-panel.layout-3d-top {
    gap: 0.75rem;
}

.viewers-panel.layout-3d-top > .viewer-card-3d {
    flex: none;
    height: 280px;  /* adjustable */
}

.viewers-panel.layout-3d-top .viewers-row {
    flex: 1;
    display: flex;
    gap: 0.5rem;
    min-height: 200px;
}

.viewers-panel.layout-3d-top .viewers-row > .viewer-card {
    flex: 1;           /* distribute width evenly */
    min-width: 0;      /* allow shrinking */
    height: auto;
}

/* Responsive considerations */
@media (max-width: 1400px) {
    .viewers-panel.layout-3d-top .viewers-row {
        flex-wrap: wrap;
    }
    .viewers-panel.layout-3d-top .viewers-row > .viewer-card {
        flex: none;
        width: calc(50% - 0.25rem);
    }
}
```

### 8.4 General Viewer Issues

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Layout buttons are too small and hard to click | Low | Button style can be enlarged | Use a button group style |
| No slice keyboard shortcuts | Medium | No keyboard navigation | Add arrow key support |
| No progress feedback when 3D loads | Low | Users feel anxious while waiting | Add a progress bar |
| Missing synchronized slice scrolling | Medium | Synchronized display is common in medical imaging | Add a Sync Scroll toggle |

**Suggested Code:**
```css
/* Layout button group */
.layout-btn-group {
    display: inline-flex;
    gap: 2px;
    background: var(--bg-3);
    padding: 3px;
    border-radius: 8px;
    border: 1px solid var(--card-border);
}

.layout-btn {
    padding: 0.4rem 0.6rem;
    font-size: 0.68rem;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    border-radius: 5px;
    cursor: pointer;
    transition: all 0.15s;
}

.layout-btn:hover {
    background: var(--bg-2);
    color: var(--text);
}

.layout-btn.active {
    background: var(--primary);
    color: white;
}

/* Loading progress bar */
.loading-progress {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--bg-3);
}

.loading-progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), var(--accent));
    transition: width 0.3s;
}

/* Slice sync scroll toggle */
.sync-scroll-toggle {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.65rem;
    color: var(--text-dim);
    cursor: pointer;
}

.sync-scroll-toggle input {
    accent-color: var(--primary);
}
```

---

## 9. Data Tree

**Screenshot:** `screenshots/design_12_data_tree.png`

![Data Tree](screenshots/design_12_data_tree.png)

**Code Location:** `index.html:1028-1099`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Scrollbar 4px is too narrow | Low | Difficult to operate | Change to 6px |
| Missing drag-and-drop reordering | Medium | Cannot customize the order | Can keep, not a high priority |

**Suggested Code:**
```css
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}

::-webkit-scrollbar-track {
    background: var(--bg-2);
}

::-webkit-scrollbar-thumb {
    background: var(--bg-3);
    border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--text-dim);
}
```

---

## 10. Context Panel

**Screenshots:** `screenshots/design_13_context_panel.png`, `screenshots/detail_12_context_expanded.png`

![Context Panel](screenshots/design_13_context_panel.png)

![Context Expanded](screenshots/detail_12_context_expanded.png)

**Code Location:** `index.html:242-280`

### Issues and Recommendations

| Issue | Severity | Description | Recommendation |
|------|---------|------|------|
| Font size 0.62rem is too small | Medium | Hard to read | Change to 0.72rem |
| No content grouping | Low | Information has no hierarchy | Display grouped by type |
| Missing collapse animation | Low | Abrupt | Add a transition |

**Suggested Code:**
```css
.context-panel-body {
    font-size: 0.72rem;
    line-height: 1.6;
    padding: 0.6rem;
}

.context-item {
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--card-border);
}

.context-item:last-child {
    border-bottom: none;
}

.context-label {
    font-size: 0.6rem;
    color: var(--primary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.2rem;
}

.context-value {
    color: var(--text);
}

.context-panel {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.25s ease;
}
```

---

## 11. Scrolling State

**Screenshot:** `screenshots/design_15_scrolled_chat.png`

![Scrolling State](screenshots/design_15_scrolled_chat.png)

### Analysis

Scrolling works normally; both the message list and the panels can scroll.

---

## 12. Accessibility

### 12.1 Color Contrast

| Element | Current Color | Contrast Ratio | WCAG AA Requirement | Status |
|------|---------|--------|-------------|------|
| Primary text | `#f1f5f9` on `#0f172a` | 15.3:1 | 4.5:1 | ✅ |
| Secondary text | `#94a3b8` on `#0f172a` | 7.2:1 | 4.5:1 | ✅ |
| Dim text | `#64748b` on `#0f172a` | 3.2:1 | 4.5:1 | ❌ |

**Issue:** `--text-dim: #64748b` does not meet WCAG AA

**Fix:**
```css
:root {
    --text-dim: #8b95a5;  /* Adjust to roughly 4.5:1 contrast ratio */
}
```

### 12.2 ARIA Label Recommendations

```html
<!-- Input box -->
<input
    id="chatInput"
    aria-label="Enter chat message"
    role="textbox"
    aria-multiline="false"
    aria-describedby="chatHint"
/>

<!-- Tab list -->
<div class="panel-tabs" role="tablist" aria-label="Content panel">
    <div class="panel-tab active" role="tab" aria-selected="true" tabindex="0">
        <span>Input</span>
    </div>
    <!-- ... -->
</div>

<!-- Message -->
<div class="chat-msg bot" role="log" aria-label="Assistant reply">
```

### 12.3 Keyboard Shortcut Recommendations

| Shortcut | Function |
|--------|------|
| `Enter` | Send message |
| `Shift + Enter` | New line |
| `↑ / ↓` | Switch slices / history messages |
| `Ctrl + N` | New conversation |
| `Esc` | Close fullscreen / cancel |

---

## 13. Prioritized Improvement List

### P0 - Fix Immediately

| Issue | Effort | Reason |
|------|--------|------|
| Color contrast does not meet requirements | 0.5h | Accessibility compliance |
| **Orphaned CSS fragment (index.html:1193-1194)** | 0.25h | Syntax error needs cleanup |

### P1 - Complete This Week

| Issue | Effort | Benefit |
|------|--------|------|
| Add icons to Tabs | 1h | Improve scanning efficiency |
| Message timestamps | 1.5h | Conversation clarity |
| Code block copy button | 1h | Feature completeness |
| Seeds Empty state guidance | 0.5h | Lower learning cost |
| Context panel font size | 0.5h | Improved readability |

### P2 - Complete Next Week

| Issue | Effort | Benefit |
|------|--------|------|
| Layout button group style | 1h | Visual consistency |
| OAR table scrolling | 1h | Support for large data |
| Keyboard shortcuts | 2h | Accessibility + efficiency |
| Scrollbar style | 0.5h | Visual detail |

### Viewer-Specific Fixes

| Issue | Effort | Priority | Description |
|------|--------|--------|------|
| Orphaned CSS fragment | 0.25h | **P0** | Syntax error on lines 1193-1194 |
| 2D slice synchronized scrolling | 2h | P1 | Common feature in medical imaging |
| 3D grid layout optimization | 1.5h | P1 | 3D is compressed in the grid |
| Non-equal grid layout | 2h | P2 | Support grid-template-areas |
| Viewer loading progress bar | 1h | P2 | Reduce waiting anxiety |

---

## 14. Summary

### Design Strengths
- ✅ Dark theme fits medical imaging tool conventions
- ✅ Clear three-column information architecture
- ✅ 5 Viewer layout modes cover different workflows
- ✅ Intuitive color-coded status indicators on metric cards
- ✅ Consistent message bubble styling

### Main Issues
1. **Accessibility**: Some color contrasts do not meet requirements (P0)
2. **User guidance**: Empty state lacks action guidance
3. **Feature completeness**: No copy for code blocks, no timestamps for messages
4. **Viewer layout**: CSS syntax error (orphaned fragment), 3D compressed in the 2x2 grid, missing synchronized scrolling
5. **Visual details**: Tabs have no icons, scrollbar is too narrow

### Improvement Goals

| Stage | Score | Achievement |
|------|------|------|
| Current | 7.0/10 | - |
| After P0 fixes | 7.2/10 | Accessibility compliant |
| After P1 | 8.0/10 | Significantly improved user experience |
| After P2 | 8.5/10 | Professional-grade product |

---

**Report Generated:** 2026-05-31
**Screenshot Count:** 26
**Code Audited:** `web/app/index.html` (1425 lines)
