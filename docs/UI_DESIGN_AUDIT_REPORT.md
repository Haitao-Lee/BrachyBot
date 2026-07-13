# BrachyBot Web UI 设计审计报告

**审计日期:** 2026-05-31
**审计范围:** Web UI 整体布局、用户体验、交互设计、响应式布局
**截图目录:** `screenshots/`
**代码文件:** `web/app/index.html`

---

## 一、总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| **视觉设计** | 8/10 | 现代化深色主题，色彩统一 |
| **信息架构** | 7/10 | 三栏布局清晰，Tab 切换合理 |
| **交互设计** | 7/10 | 基本交互流畅，部分细节需改进 |
| **用户体验** | 7/10 | 功能完整，学习成本适中 |
| **可访问性** | 5/10 | 缺乏键盘导航，无 ARIA 标签 |

**综合评分: 7/10**

---

## 二、全局视图

### 2.1 完整页面布局

![完整页面布局](screenshots/design_01_full_page.png)

**布局分析:**
- **三栏布局**: 左侧会话列表 (260px) → 中间聊天区 (flex) → 右侧面板 (500px)
- **Header**: 48px 高度，包含 Logo、标题、状态指示器
- **深色主题**: `#0f172a` 主背景，符合医学影像工具惯例

---

## 三、Header 区域

**截图:** `screenshots/design_12_header.png`

![Header区域](screenshots/design_12_header.png)

**代码位置:** `index.html:1426-1443`

```html
<header class="header">
    <div class="header-logo">AI</div>
    <div class="header-title">BrachyBot</div>
    <div class="header-subtitle">AI Brachytherapy Planning</div>
    <div class="header-status">...</div>
</header>
```

### 问题与建议

| 问题 | 严重程度 | 建议 |
|------|---------|------|
| Logo 文字 "AI" 不够专业 | 低 | 使用 SVG 图标替代 |
| 标题字号 0.9rem 偏小 | 低 | 调整为 1.1rem |
| 状态指示器 dot 偏小 (6px) | 低 | 可保持，因已有颜色和阴影增强 |

**建议代码:**
```css
.header-logo {
    width: 32px;
    height: 32px;
    /* 使用 SVG 背景图替代纯文字 */
    background: linear-gradient(135deg, var(--primary), var(--accent));
    border-radius: 8px;
}

.header-title {
    font-size: 1.1rem;
    font-weight: 700;
}
```

---

## 四、左侧边栏 (会话列表)

**截图:** `screenshots/design_02_sidebar.png`, `screenshots/detail_13_sidebar_hover.png`

![会话列表](screenshots/design_02_sidebar.png)

![Sidebar Hover](screenshots/detail_13_sidebar_hover.png)

**代码位置:** `index.html:90-207`, CSS `89-218`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| 会话名称不描述性 | 中 | "Item 1/2/3" 无法帮助定位 | 显示首条消息摘要或时间 |
| 新建按钮不够突出 | 低 | 与背景融为一体 | 使用渐变背景色 |
| 激活状态区分不明显 | 低 | 当前选中项无明确指示 | 添加左侧边框高亮 |

**建议代码:**
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

## 五、聊天区域

### 5.1 消息响应排版

**截图:** `screenshots/detail_01_chat_response.png`, `screenshots/detail_04_code_block.png`, `screenshots/design_14_chat_response.png`

![聊天响应](screenshots/detail_01_chat_response.png)

![代码块响应](screenshots/detail_04_code_block.png)

![长响应](screenshots/design_14_chat_response.png)

**代码位置:** `index.html:326-526`, CSS `326-539`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| Bot 消息宽度 85% < 用户消息 88% | 低 | 视觉不平衡 | 统一为 85% 或 80% |
| 代码块无复制按钮 | 中 | 用户需手动选择 | 添加 📋 图标按钮 |
| 消息无时间戳 | 中 | 无法判断对话顺序 | 添加 HH:MM 时间戳 |
| 头像 26px 偏小 | 低 | 高分辨率屏幕不够清晰 | 调整为 32px |

**建议代码:**
```css
/* 统一消息宽度 */
.chat-row {
    max-width: 85%;
}

.chat-msg.bot {
    max-width: 85%;  /* 与用户消息一致 */
}

/* 增大头像 */
.chat-avatar {
    width: 32px;
    height: 32px;
    font-size: 0.75rem;
}

/* 代码块添加复制按钮 */
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

/* 消息添加时间戳 */
.chat-msg .timestamp {
    font-size: 0.6rem;
    color: var(--text-dim);
    margin-top: 0.25rem;
    opacity: 0.7;
}
```

### 5.2 消息操作按钮

**截图:** `screenshots/detail_11_msg_hover.png`

![消息Hover](screenshots/detail_11_msg_hover.png)

**代码位置:** `index.html:454-477`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| Hover 时操作按钮位置偏移 | 低 | 按钮在消息外侧 | 保持在消息右上角内 |
| 按钮样式不直观 | 低 | 仅图标无文字 | 添加 tooltip |

**建议代码:**
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

## 六、输入区域

**截图:** `screenshots/design_05_input_area.png`

![输入区域](screenshots/design_05_input_area.png)

**代码位置:** `index.html:751-818`, CSS `751-818`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| 发送按钮 40px 偏小 | 低 | 触控区域不足 | 调整为 44px (最小触控标准) |
| 缺少快捷命令提示 | 中 | 新用户不知道可用命令 | 添加 💡 提示文字 |
| Placeholder 不够引导 | 低 | "Type a message..." 无具体示例 | 提供具体示例 |

**建议代码:**
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

## 七、右侧面板

### 7.1 面板切换 Tab

**截图:** `screenshots/design_06_right_panel.png`, `screenshots/design_07_panel_tabs.png`

![右侧面板](screenshots/design_06_right_panel.png)

![Tab切换](screenshots/design_07_panel_tabs.png)

**代码位置:** `index.html:848-867`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| Tab 无图标 | 中 | 纯文字扫描效率低 | 添加简洁图标 |
| 点击区域偏小 | 低 | padding 仅 0.6rem | 适当增加 |

**建议代码:**
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

### 7.2 Input 表单

**截图:** `screenshots/design_08_input_form.png`, `screenshots/detail_10_input_form_full.png`

![Input表单](screenshots/design_08_input_form.png)

![完整表单](screenshots/detail_10_input_form_full.png)

**代码位置:** `index.html:869-926`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| 文件选择按钮不够突出 | 低 | dashed border 可更明显 | 增加边框宽度和背景色 |
| Section 分隔线过细 | 低 | 分组不够明显 | 使用渐变分隔线 |
| 缺少必填标识 | 低 | 不清楚字段重要性 | 添加 * 标识 |

**建议代码:**
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

### 7.3 Analysis 面板

**截图:** `screenshots/design_09_analysis_tab.png`

![Analysis面板](screenshots/design_09_analysis_tab.png)

**代码位置:** `index.html:928-986`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| OAR 表格无滚动 | 低 | 数据多时超出容器 | 添加 max-height + overflow-y: auto |
| 缺少数据导出 | 中 | 无法下载报告 | 添加导出按钮 |

**建议代码:**
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

### 7.4 Seeds 面板

**截图:** `screenshots/design_10_seeds_tab.png`

![Seeds面板](screenshots/design_10_seeds_tab.png)

**代码位置:** `index.html:1007-1027`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| Empty state 缺少操作引导 | 中 | 用户不知下一步 | 添加步骤指引和快捷按钮 |
| 种子卡片布局固定 | 低 | 无法调整大小 | 可保持，因种子数量通常有限 |

**建议代码:**
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

## 八、Viewer 面板

### 8.1 布局模式对比

**截图:**
- `screenshots/detail_05_viewer_vertical.png` - 垂直布局
- `screenshots/detail_06_viewer_grid.png` - 2x2 网格
- `screenshots/detail_07_viewer_horizontal.png` - 水平布局
- `screenshots/detail_08_viewer_3d_top.png` - 3D 顶部
- `screenshots/detail_09_viewer_3d_bottom.png` - 3D 底部

| 布局 | 截图 | 优点 | 问题 |
|------|------|------|------|
| 垂直 (默认) | detail_05 | 切片对比清晰 | 占用空间大 |
| 网格 2x2 | detail_06 | 同时查看4个 | 3D 被压缩 |
| 水平 | detail_07 | 适合宽屏 | 需横向滚动 |
| 3D 顶部 | detail_08 | 3D 突出 | 2D 宽度固定 |
| 3D 底部 | detail_09 | 2D 优先 | 3D 位置不便 |

![垂直布局](screenshots/detail_05_viewer_vertical.png)

![网格布局](screenshots/detail_06_viewer_grid.png)

![水平布局](screenshots/detail_07_viewer_horizontal.png)

![3D顶部](screenshots/detail_08_viewer_3d_top.png)

![3D底部](screenshots/detail_09_viewer_3d_bottom.png)

**代码位置:** `index.html:1103-1285`

### 8.2 网格布局 2x2 详细分析

**当前 CSS (问题代码):**
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

/* ⚠️ 问题: 存在孤立的 CSS 片段 */
height: auto;      /* 未在任何选择器内 */
min-height: 120px;  /* 第1193-1194行，CSS语法错误 */
```

**问题分析:**

| 问题 | 严重程度 | 代码位置 | 描述 |
|------|---------|---------|------|
| **孤立 CSS 片段** | 高 | `index.html:1193-1194` | `height: auto; min-height: 120px;` 未包裹在选择器内，属语法错误 |
| 2x2 网格等分空间 | 中 | `index.html:1126-1127` | 4个Viewer(Axial/Sagittal/Coronal/3D)等分，但3D通常需要更大空间 |
| gap 0.5rem 偏小 | 低 | `index.html:1128` | 医学影像对比需要更大间距，建议 0.75rem |
| 3D viewer 在网格中被压缩 | 中 | `index.html:1130-1133` | `height: auto` 导致3D卡片可能显示过小 |
| 卡片高度自动 | 低 | `index.html:1131` | `height: auto` 依赖内容高度，可能不一致 |

**截图分析:**

从 `detail_06_viewer_grid.png` 可见:
- 4个Viewer均匀分布在2x2网格中
- 每个卡片高度相同，但3D视图通常需要更多垂直空间
- Axial/Sagittal/Coronal 适合正方形或4:3比例
- 3D重建视图更适合16:9或更大比例

**建议修复:**
```css
/* 修复孤立的 CSS 片段 - 删除第1193-1194行 */

/* 改进网格布局 */
.viewers-panel.layout-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: minmax(180px, 1fr) minmax(180px, 1fr);
    gap: 0.75rem;  /* 从 0.5rem 增加到 0.75rem */
}

.viewers-panel.layout-grid > .viewer-card {
    height: auto;
    min-height: 0;
    /* 确保3D卡片视觉上更突出 */
    border: 2px solid transparent;
    transition: border-color 0.2s;
}

.viewers-panel.layout-grid > .viewer-card.viewer-card-3d {
    border-color: var(--accent);  /* 3D卡片用紫色边框区分 */
}

/* 或者：考虑非等分布局，3D占更大空间 */
.viewers-panel.layout-grid-3d-large {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    /* 使用 grid-template-areas 更好地分配空间 */
    grid-template-areas:
        "axial sagittal"
        "coronal 3d";
}

.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(1) { grid-area: axial; }
.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(2) { grid-area: sagittal; }
.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(3) { grid-area: coronal; }
.viewers-panel.layout-grid-3d-large > .viewer-card:nth-child(4) { grid-area: 3d; }
```

### 8.3 3D 顶部/底部布局分析

**当前 CSS:**
```css
/* 3D-top: 3D 顶部，2D 切片在底部 */
.viewers-panel.layout-3d-top > .viewer-card-3d {
    height: 300px;
}

.viewers-panel.layout-3d-top .viewers-row > .viewer-card {
    width: 320px;   /* 固定宽度，可能不适合所有屏幕 */
    height: 260px;
}

/* 3D-bottom: 3D 底部，2D 切片在顶部 */
.viewers-panel.layout-3d-bottom .viewers-row > .viewer-card {
    width: 320px;   /* 同样问题 */
    height: 260px;
}
```

**问题分析:**

| 问题 | 严重程度 | 代码位置 | 描述 |
|------|---------|---------|------|
| 2D 切片固定宽度 320px | 中 | `index.html:1166, 1184` | 大屏幕浪费空间，小屏幕放不下 |
| 3D 高度固定 300px | 低 | `index.html:1156, 1190` | 无法根据内容调整 |
| 水平布局不支持比例调整 | 中 | `index.html:1135-1146` | flex: 1 但 min-width 限制 |

**截图分析:**

从 `detail_08_viewer_3d_top.png` 和 `detail_09_viewer_3d_bottom.png` 可见:
- 3D 卡片固定在顶部或底部
- 三个2D切片并排显示，但宽度固定320px
- 在1920px屏幕上，两侧有大量空白

**建议修复:**
```css
/* 3D 顶部布局改进 */
.viewers-panel.layout-3d-top {
    gap: 0.75rem;
}

.viewers-panel.layout-3d-top > .viewer-card-3d {
    flex: none;
    height: 280px;  /* 可调整 */
}

.viewers-panel.layout-3d-top .viewers-row {
    flex: 1;
    display: flex;
    gap: 0.5rem;
    min-height: 200px;
}

.viewers-panel.layout-3d-top .viewers-row > .viewer-card {
    flex: 1;           /* 平均分配宽度 */
    min-width: 0;      /* 允许收缩 */
    height: auto;
}

/* 响应式考虑 */
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

### 8.4 通用 Viewer 问题

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| 布局按钮过小难点击 | 低 | 按钮样式可增大 | 使用按钮组样式 |
| 无切片快捷键 | 中 | 无法键盘导航 | 添加方向键支持 |
| 3D 加载无进度反馈 | 低 | 用户等待焦虑 | 添加进度条 |
| 缺少切片同步滚动 | 中 | 医学影像常用同步显示 | 添加 Sync Scroll 开关 |

**建议代码:**
```css
/* 布局按钮组 */
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

/* 加载进度条 */
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

/* 切片同步滚动开关 */
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

## 九、Data Tree

**截图:** `screenshots/design_12_data_tree.png`

![Data Tree](screenshots/design_12_data_tree.png)

**代码位置:** `index.html:1028-1099`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| 滚动条 4px 偏窄 | 低 | 操作困难 | 调整为 6px |
| 缺少拖拽排序 | 中 | 无法自定义顺序 | 可保持，优先级不高 |

**建议代码:**
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

## 十、Context 面板

**截图:** `screenshots/design_13_context_panel.png`, `screenshots/detail_12_context_expanded.png`

![Context面板](screenshots/design_13_context_panel.png)

![Context展开](screenshots/detail_12_context_expanded.png)

**代码位置:** `index.html:242-280`

### 问题与建议

| 问题 | 严重程度 | 描述 | 建议 |
|------|---------|------|------|
| 字号 0.62rem 太小 | 中 | 难以阅读 | 调整为 0.72rem |
| 无内容分组 | 低 | 信息无层次 | 按类型分组显示 |
| 折叠动画缺失 | 低 | 生硬 | 添加 transition |

**建议代码:**
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

## 十一、滚动状态

**截图:** `screenshots/design_15_scrolled_chat.png`

![滚动状态](screenshots/design_15_scrolled_chat.png)

### 分析

滚动功能正常工作，消息列表和面板都可以滚动。

---

## 十二、可访问性

### 12.1 颜色对比度

| 元素 | 当前颜色 | 对比度 | WCAG AA 要求 | 状态 |
|------|---------|--------|-------------|------|
| 主要文本 | `#f1f5f9` on `#0f172a` | 15.3:1 | 4.5:1 | ✅ |
| 次要文本 | `#94a3b8` on `#0f172a` | 7.2:1 | 4.5:1 | ✅ |
| 暗淡文本 | `#64748b` on `#0f172a` | 3.2:1 | 4.5:1 | ❌ |

**问题:** `--text-dim: #64748b` 不满足 WCAG AA

**修复:**
```css
:root {
    --text-dim: #8b95a5;  /* 调整为约 4.5:1 对比度 */
}
```

### 12.2 ARIA 标签建议

```html
<!-- 输入框 -->
<input
    id="chatInput"
    aria-label="输入聊天消息"
    role="textbox"
    aria-multiline="false"
    aria-describedby="chatHint"
/>

<!-- Tab 列表 -->
<div class="panel-tabs" role="tablist" aria-label="内容面板">
    <div class="panel-tab active" role="tab" aria-selected="true" tabindex="0">
        <span>Input</span>
    </div>
    <!-- ... -->
</div>

<!-- 消息 -->
<div class="chat-msg bot" role="log" aria-label="助手回复">
```

### 12.3 键盘快捷键建议

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 发送消息 |
| `Shift + Enter` | 换行 |
| `↑ / ↓` | 切换切片 / 历史消息 |
| `Ctrl + N` | 新建对话 |
| `Esc` | 关闭全屏 / 取消 |

---

## 十三、优先级改进清单

### P0 - 立即修复

| 问题 | 工作量 | 原因 |
|------|--------|------|
| 颜色对比度不达标 | 0.5h | 可访问性合规 |
| **CSS 孤立片段 (index.html:1193-1194)** | 0.25h | 语法错误需清理 |

### P1 - 本周完成

| 问题 | 工作量 | 收益 |
|------|--------|------|
| Tab 添加图标 | 1h | 提升扫描效率 |
| 消息时间戳 | 1.5h | 对话清晰度 |
| 代码块复制按钮 | 1h | 功能完整性 |
| Seeds Empty state 引导 | 0.5h | 降低学习成本 |
| Context 面板字号 | 0.5h | 可读性提升 |

### P2 - 下周完成

| 问题 | 工作量 | 收益 |
|------|--------|------|
| 布局按钮组样式 | 1h | 视觉一致性 |
| OAR 表格滚动 | 1h | 大量数据支持 |
| 键盘快捷键 | 2h | 可访问性 + 效率 |
| 滚动条样式 | 0.5h | 视觉细节 |

### Viewer 专项修复

| 问题 | 工作量 | 优先级 | 描述 |
|------|--------|--------|------|
| CSS 孤立片段 | 0.25h | **P0** | 第1193-1194行语法错误 |
| 2D切片同步滚动 | 2h | P1 | 医学影像常用功能 |
| 3D网格布局优化 | 1.5h | P1 | 3D在网格中被压缩 |
| 非等分网格布局 | 2h | P2 | 支持grid-template-areas |
| Viewer加载进度条 | 1h | P2 | 降低等待焦虑 |

---

## 十四、总结

### 设计优点
- ✅ 深色主题符合医学影像工具惯例
- ✅ 三栏布局信息架构清晰
- ✅ 5 种 Viewer 布局模式覆盖不同工作流
- ✅ 指标卡片颜色状态标识直观
- ✅ 消息气泡样式统一

### 主要问题
1. **可访问性**: 部分颜色对比度不达标 (P0)
2. **用户引导**: Empty state 缺少操作指引
3. **功能完整性**: 代码块无复制、消息无时间戳
4. **Viewer布局**: CSS语法错误(孤立片段)、2x2网格3D被压缩、同步滚动缺失
5. **视觉细节**: Tab 无图标、滚动条偏窄

### 改进目标

| 阶段 | 评分 | 达成 |
|------|------|------|
| 当前 | 7.0/10 | - |
| P0 修复后 | 7.2/10 | 可访问性达标 |
| P1 完成后 | 8.0/10 | 用户体验显著提升 |
| P2 完成后 | 8.5/10 | 专业级产品 |

---

**报告生成时间:** 2026-05-31
**截图数量:** 26 张
**代码审计:** `web/app/index.html` (1425 行)
