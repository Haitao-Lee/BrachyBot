# BrachyBot 完整功能规格与实现状态

> 最后更新: 2026-06-22
> 本文档覆盖项目所有功能模块、交互期望、已修复 bug、API 端点。

---

## 目录

- [一、功能模块总览](#一功能模块总览)
  - [1. LLM 聊天系统](#1-llm-聊天系统)
  - [2. CTV 靶区分割](#2-ctv-靶区分割)
  - [3. OAR 危及器官分割](#3-oar-危及器官分割)
  - [4. 规划流水线](#4-规划流水线)
  - [5. 剂量评估](#5-剂量评估)
  - [6. 2D 影像查看器](#6-2d-影像查看器)
  - [7. 3D 可视化](#7-3d-可视化)
  - [8. Data Tree 数据树](#8-data-tree-数据树)
  - [9. DVH 剂量体积直方图](#9-dvh-剂量体积直方图)
  - [10. 报告面板](#10-报告面板)
  - [11. Todo 执行进度](#11-todo-执行进度)
  - [12. Thinking Chain 思考链](#12-thinking-chain-思考链)
  - [13. 多语言系统](#13-多语言系统)
  - [14. 面板布局与拖拽](#14-面板布局与拖拽)
  - [15. 会话管理](#15-会话管理)
  - [16. 联网搜索](#16-联网搜索)
  - [17. Quality Review 质量审核](#17-quality-review-质量审核)
- [二、交互流程与期望效果](#二交互流程与期望效果)
  - [1. 规划主流程](#1-规划主流程)
  - [2. 聊天交互](#2-聊天交互)
  - [3. 2D 查看器交互](#3-2d-查看器交互)
  - [4. 3D 查看器交互](#4-3d-查看器交互)
  - [5. Data Tree 交互](#5-data-tree-交互)
  - [6. DVH 交互](#6-dvh-交互)
  - [7. 报告面板交互](#7-报告面板交互)
  - [8. 面板切换交互](#8-面板切换交互)
  - [9. 全局控件交互](#9-全局控件交互)
- [三、规划流水线详解](#三规划流水线详解)
  - [1. 流程总览](#1-流程总览)
  - [2. SSE 事件流](#2-sse-事件流)
  - [3. step_callback 机制](#3-step_callback-机制)
  - [4. 自动 OAR 触发](#4-自动-oar-触发)
  - [5. 前端响应链](#5-前端响应链)
  - [6. 规划结果 API](#6-规划结果-api)
  - [7. 3D 网格数据](#7-3d-网格数据)
  - [8. 剂量评估详情](#8-剂量评估详情)
- [四、报告面板详解](#四报告面板详解)
  - [1. 面板布局](#1-面板布局)
  - [2. 数据来源](#2-数据来源)
  - [3. 截图系统](#3-截图系统)
  - [4. 语言系统](#4-语言系统)
  - [5. 版本管理](#5-版本管理)
  - [6. 模态框系统](#6-模态框系统)
  - [7. PDF 导出](#7-pdf-导出)
  - [8. BrachyBot 自动填充](#8-brachybot-自动填充)
- [五、已修复 Bug 清单](#五已修复-bug-清单)
  - [1. Report 语言问题](#1-report-语言问题)
  - [2. 3D 查看器空白](#2-3d-查看器空白)
  - [3. DVH Tooltip 溢出](#3-dvh-tooltip-溢出)
  - [4. CTV 颜色修改无效](#4-ctv-颜色修改无效)
  - [5. Report 自动截图缺失](#5-report-自动截图缺失)
  - [6. 二级界面样式问题](#6-二级界面样式问题)
  - [7. Quality Review 重试](#7-quality-review-重试)
  - [8. Todo 合并逻辑](#8-todo-合并逻辑)
  - [9. Todo 最终回复计数](#9-todo-最终回复计数)
  - [10. 标题排版](#10-标题排版)
- [六、API 端点清单](#六api-端点清单)
- [七、技术栈](#七技术栈)

---

# 一、功能模块总览

## 1. LLM 聊天系统

### 1.1 聊天发送

| 项目 | 说明 |
|------|------|
| **期望效果** | 用户输入消息 → 发送到 `/api/chat` → SSE 流式返回 → 实时显示回复 |
| **输入方式** | 文本框 + Enter 发送 / 按钮点击 |
| **流式传输** | SSE (Server-Sent Events), `stream: true` |
| **停止功能** | 发送中再次点击按钮 → AbortController 中断 |
| **实现状态** | ✅ 已实现 |

### 1.2 工具调用显示

| 项目 | 说明 |
|------|------|
| **期望效果** | LLM 调用工具时，Thinking Chain 中显示工具名、参数、结果 |
| **步骤状态** | pending → done / error，带对应图标 (⚙/✓/✕) |
| **工具进度** | 工具执行中显示进度条和百分比 |
| **实现状态** | ✅ 已实现 |

### 1.3 AI 回复渲染

| 项目 | 说明 |
|------|------|
| **期望效果** | Markdown 渲染：标题、表格、列表、代码块、链接 |
| **标题样式** | ChatGPT 风格：H2 底部分割线，无左侧竖线，无 emoji 图标 |
| **表格样式** | 深色主题表格，带 `.md-table` 类名 |
| **链接** | 新窗口打开 (`target="_blank"`) |
| **实现状态** | ✅ 已实现 (2026-06-22 修复) |

### 1.4 回复 Footer

| 项目 | 说明 |
|------|------|
| **期望效果** | 回复底部显示：耗时 / 输入 token / 输出 token / 工具调用次数 |
| **多语言** | 根据全局语言显示中文/英文标签 |
| **实现状态** | ✅ 已实现 |

---

## 2. CTV 靶区分割

| 项目 | 说明 |
|------|------|
| **期望效果** | 上传 CT → 调用 nnUNet 分割模型 → 返回 CTV 标签图 |
| **输入** | CT NIfTI 文件路径 + 肿瘤类型 (`nnunet_pancreatic` 等) |
| **输出** | 多标签分割结果: label 1=tumor, 2=artery, 3=vein, 4=pancreas 等 |
| **后处理** | 存储 `ctv_array`, `ctv_label_names`, `labelColorLUT` 到内存 |
| **自动触发** | 规划流水线检测到无 CTV 时自动调用 |
| **Data Tree** | CTV 节点下显示 tumor 子标签，每个有独立颜色和 3D 重建按钮 |
| **实现状态** | ✅ 已实现 |

---

## 3. OAR 危及器官分割

| 项目 | 说明 |
|------|------|
| **期望效果** | 基于 CT 调用 TotalSegmentator → 返回 57+ 器官标签 |
| **输出** | `organ_names` 字典: {label_id: organ_name} |
| **分类** | Non-traversable (血管、骨骼) / Traversable (软组织器官) |
| **自动触发** | CTV 分割后自动检测 OAR 数量，<5 时自动调用 |
| **CTV 标签排除** | OAR 加载时排除已属于 CTV 的 label ID (如 artery=2, vein=3) |
| **实现状态** | ✅ 已实现 |

---

## 4. 规划流水线

### 4.1 总体流程

```
CTV 分割 → OAR 分割 → planning_pipeline(step="full") → 剂量评估
```

| 步骤 | 子步骤 | 说明 | 实现状态 |
|------|--------|------|----------|
| `ctv_segmentation` | — | CTV 靶区分割 | ✅ |
| `oar_segmentation` | — | OAR 危及器官分割 (自动/手动) | ✅ |
| `planning_pipeline` | `trajectory_init` | 轨迹初始化 (130 条候选) | ✅ |
| | `trajectory_refine` | 轨迹细化 | ✅ |
| | `seed_planning` | 粒子位置优化 (14 颗) | ✅ |
| | `dose_calc` | 剂量计算 | ✅ |
| | `dose_eval` | 剂量学评估 | ✅ |

### 4.2 step_callback 机制

| 项目 | 说明 |
|------|------|
| **期望效果** | 每个子步骤通过 `step_callback` 发送 pending/done SSE 事件 |
| **Todo 联动** | Todo 列表实时显示每个子步骤的呼吸动画 |
| **DRAIN 机制** | DRAIN-1 (tool 执行后) + DRAIN-2 (store 后) 确保事件不丢失 |
| **实现状态** | ✅ 已实现 |

### 4.3 自动 OAR

| 项目 | 说明 |
|------|------|
| **触发条件** | CTV 分割完成后，OAR map 中器官数 < 5 |
| **效果** | 自动调用 `oar_segmentation`，合并到 CTV 的 Todo 项 |
| **SSE 事件** | `oar_segmentation pending` → `oar_segmentation done` |
| **Todo 显示** | 合并为 "CTV + OAR segmentation" 一项 |
| **实现状态** | ✅ 已实现 (2026-06-22 修复合并逻辑) |

### 4.4 规划结果指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| V100 | 靶区覆盖率 | ≥ 90% |
| D90 | 90% 靶区接受的最低剂量 | ≥ 100 Gy |
| V150/V200 | 高剂量体积比 | ≤ 50% / ≤ 20% |
| CI | 适形指数 | ≥ 0.6 |
| HI | 均匀指数 | ≤ 0.35 |
| Score | 综合评分 (0-100) | ≥ 80 |
| Seeds | 粒子数量 | — |
| Trajectories | 针道数量 | — |

---

## 5. 剂量评估

| 项目 | 说明 |
|------|------|
| **期望效果** | 计算 CTV 和所有 OAR 的剂量指标 |
| **CTV 指标** | Dmax, Dmin, Dmean, D98, D90, D2, V100, V150, V200, CI, HI |
| **OAR 指标** | D2cc, D1cc, D0.1cc, Max dose |
| **输出** | 存储到 `dose_metrics` / `metrics` 内存 |
| **实现状态** | ✅ 已实现 |

---

## 6. 2D 影像查看器

### 6.1 三视图

| 视图 | 说明 | 实现状态 |
|------|------|----------|
| Axial | 轴位 (默认) | ✅ |
| Sagittal | 矢状位 | ✅ |
| Coronal | 冠状位 | ✅ |

### 6.2 切片拖拽

| 项目 | 说明 |
|------|------|
| **期望效果** | 拖拽滑块 → 切换切片 → 重新渲染 CT + overlay |
| **鼠标滚轮** | 滚轮切换切片 |
| **实现状态** | ✅ 已实现 |

### 6.3 标签 Overlay

| 项目 | 说明 |
|------|------|
| **期望效果** | CTV/OAR 标签以半透明颜色叠加在 CT 切片上 |
| **颜色** | 来自 `labelColorLUT`，每个 label 有独立 RGB |
| **可切换** | 通过 Data Tree 可见性控制 |
| **实现状态** | ✅ 已实现 |

### 6.4 剂量 Overlay

| 项目 | 说明 |
|------|------|
| **期望效果** | 剂量分布以热力图形式叠加在 CT 切片上 |
| **颜色映射** | 暖色=高剂量，冷色=低剂量 |
| **处方线** | 120 Gy 等剂量线 |
| **切换** | Dose overlay 开关 |
| **实现状态** | ✅ 已实现 |

---

## 7. 3D 可视化

### 7.1 初始化

| 项目 | 说明 |
|------|------|
| **期望效果** | 首次切换到 Viewers 面板时初始化 Three.js 场景 |
| **相机** | PerspectiveCamera, 初始位置 (0,0,300) |
| **光源** | AmbientLight (0.6) + 3 个 DirectionalLight |
| **控制器** | OrbitControls: 左键旋转, 右键平移, 滚轮缩放 |
| **背景** | 透明 (黑色 CSS 背景) |
| **preserveDrawingBuffer** | `true` (确保截图可用) |
| **实现状态** | ✅ 已实现 (2026-06-22 修复) |

### 7.2 网格加载

| 网格类型 | organ_id 格式 | 来源 | 实现状态 |
|----------|--------------|------|----------|
| CTV tumor | `ctv_1` | CTV 分割 label 1 | ✅ |
| CTV artery | `ctv_2` | CTV 分割 label 2 | ✅ |
| CTV vein | `ctv_3` | CTV 分割 label 3 | ✅ |
| CTV pancreas | `ctv_4` | CTV 分割 label 4 | ✅ |
| OAR non-traversable | `organ_{labelId}` | OAR 分割 (排除 CTV labels) | ✅ |
| OAR traversable | `organ_{labelId}` | OAR 分割 | ✅ |
| Seeds | `seed_{idx}` | 规划结果 | ✅ |
| Needles | `needle_{idx}` | 规划结果 | ✅ |
| Dose isosurfaces | `dose_iso_{threshold}` | 剂量计算 | ✅ |

### 7.3 自动加载与重建一致性

| 项目 | 说明 |
|------|------|
| **期望效果** | 自动加载 = 右键 3D Reconstruction = Data Tree 控件 |
| **organ_id 统一** | CTV: `ctv_{lid}`, OAR: `organ_{lid}` |
| **颜色来源** | `labelColorLUT` / `dataTreeState` |
| **重复防护** | CTV label IDs 从 non-traversable OAR 加载中排除 |
| **相机适配** | `fitCameraToScene()` 自动调整相机到网格包围盒 |
| **面板切换** | 切换到 Viewers 面板时 `forceRender3DViewer()` 重新初始化 |
| **实现状态** | ✅ 已实现 (2026-06-22 修复面板切换) |

### 7.4 方向轴

| 项目 | 说明 |
|------|------|
| **期望效果** | 左下角显示 R/A/S 方向轴，跟随主相机旋转 |
| **实现状态** | ✅ 已实现 |

---

## 8. Data Tree 数据树

### 8.1 结构

```
Segmentation
├── CTV
│   └── pancreatic tumor (ctv_1)
│   └── artery (ctv_2)
│   └── vein (ctv_3)
│   └── pancreas (ctv_4)
├── OAR (57)
│   ├── Non-traversable
│   │   ├── aorta (organ_X)
│   │   └── vertebrae_* (organ_X)
│   └── Traversable
│       ├── stomach (organ_X)
│       └── liver (organ_X)
Planning
├── Seeds (seed_0, seed_1, ...)
├── Needles (needle_0, needle_1, ...)
└── Dose Isosurfaces (dose_iso_120, dose_iso_180, ...)
```

### 8.2 右键菜单

| 菜单项 | 适用对象 | 功能 | 实现状态 |
|--------|---------|------|----------|
| 3D Reconstruct | 器官/CTV | 3D 重建单个器官 | ✅ |
| 3D Reconstruct All | 多选 | 批量 3D 重建 | ✅ |
| Change Color | 单个器官/CTV/粒子/针道 | 打开颜色选择器 | ✅ (2026-06-22 修复 CTV) |
| Move to Category | OAR 器官 | 移动到 traversable/non-traversable | ✅ |
| Show Selected | 多选 | 显示选中项 | ✅ |
| Hide Selected | 多选 | 隐藏选中项 | ✅ |
| Solo Selected | 多选 | 只显示选中项 | ✅ |
| Opacity | 多选 | 设置透明度 (100/75/50/25%) | ✅ |
| Show All | 全部 | 显示所有器官 | ✅ |

### 8.3 颜色选择器

| 项目 | 说明 |
|------|------|
| **期望效果** | HSV 滑块 + 预设色块 + 实时预览 |
| **2D 联动** | 修改后更新 `labelColorLUT` → 2D overlay 重绘 |
| **3D 联动** | 修改后更新 `mesh.material.color` → 3D 网格即时变色 |
| **支持对象** | organ_* , ctv_* , seed_* , needle_* , dose_iso_* |
| **实现状态** | ✅ 已实现 (2026-06-22 修复 CTV + 3D 联动) |

### 8.4 可见性控制

| 项目 | 说明 |
|------|------|
| **眼睛图标** | 点击切换单个器官可见性 |
| **Group 开关** | CTV/OAR/Planning 组级开关 |
| **3D 联动** | 可见性变化同步到 3D 网格 |
| **实现状态** | ✅ 已实现 |

---

## 9. DVH 剂量体积直方图

### 9.1 渲染

| 项目 | 说明 |
|------|------|
| **期望效果** | Plotly.js 渲染 CTV + 所有 OAR 的剂量-体积曲线 |
| **X 轴** | 剂量 (Gy) |
| **Y 轴** | 体积 (%) |
| **曲线数** | 1 (CTV) + N (OARs) |
| **处方线** | 120 Gy 垂直虚线 |
| **实现状态** | ✅ 已实现 |

### 9.2 Tooltip

| 项目 | 说明 |
|------|------|
| **期望效果** | 鼠标悬停显示器官名 + 剂量值 + 体积值 |
| **样式** | 深色背景 (`rgba(15,23,42,0.95)`) + 亮色文字 |
| **溢出防护** | SVG viewBox 坐标 clamp，tooltip 不超出图表区域 |
| **CJK 字体** | Microsoft YaHei / PingFang SC / Noto Sans CJK SC |
| **实现状态** | ✅ 已实现 (2026-06-22 修复 clamp) |

### 9.3 点击拾取

| 项目 | 说明 |
|------|------|
| **期望效果** | 单击曲线 → 在该点放置标记 (剂量, 体积, 器官名) |
| **实现状态** | ✅ 已实现 |

---

## 10. 报告面板

### 10.1 编辑器

| 项目 | 说明 |
|------|------|
| **期望效果** | 分区编辑：患者信息 / 影像 / 规划 / 剂量 / OAR / 解读 / 参考文献 |
| **自动填充** | 从 server 端 `/api/report/auto-fill` 拉取数据 |
| **实时预览** | 右侧 PDF 预览实时更新 |
| **实现状态** | ✅ 已实现 |

### 10.2 语言

| 项目 | 说明 |
|------|------|
| **期望效果** | 跟随全局 EN/中 按钮，不从用户输入语言推断 |
| **修复** | `refreshFinalReport` / `reportAutoFill` 优先使用 `window._i18nLang` |
| **实现状态** | ✅ 已修复 (2026-06-22) |

### 10.3 截图自动捕获

| 截图 | 来源 | 实现状态 |
|------|------|----------|
| CTV/OAR 分割叠加 | 2D viewer canvas (axial) | ✅ |
| 剂量分布热图 | 2D viewer canvas (如 dose overlay 开启) | ✅ |
| 3D 规划方案 | Three.js canvas (`preserveDrawingBuffer`) | ✅ (2026-06-22 修复) |
| DVH 曲线 | `Plotly.toImage()` | ✅ |

**触发时机**:
1. `refreshPlanningUI` 完成后 (规划完成)
2. 打开 Report 面板时
3. 点击 Auto-fill 时
4. 导出 PDF 时

### 10.4 PDF 导出

| 项目 | 说明 |
|------|------|
| **期望效果** | html2canvas 渲染报告页面 → 生成 PDF |
| **语言** | 跟随 `reportForm.language` |
| **实现状态** | ✅ 已实现 |

### 10.5 版本快照

| 项目 | 说明 |
|------|------|
| **保存** | 📸 Snapshot → localStorage 存储当前表单 |
| **恢复** | 📜 History → 列出历史快照 → Restore |
| **实现状态** | ✅ 已实现 |

### 10.6 审计日志

| 项目 | 说明 |
|------|------|
| **期望效果** | 🔍 Audit → 显示所有编辑操作的时间戳和详情 |
| **实现状态** | ✅ 已实现 |

### 10.7 字段校验

| 项目 | 说明 |
|------|------|
| **期望效果** | ✅ Validate → 检查必填字段和剂量范围 |
| **校验项** | 患者姓名/性别/ID, 诊断, D90 范围, V100 范围, CI 范围 |
| **实现状态** | ✅ 已实现 |

---

## 11. Todo 执行进度

### 11.1 显示

| 项目 | 说明 |
|------|------|
| **期望效果** | 底部 Dock 显示当前工作流步骤和完成状态 |
| **预填充** | 规划请求时预填充 3 步: CTV → OAR → Planning |
| **状态** | 预测 (空心) → 活动 (呼吸动画) → 完成 (✓) → 错误 (✕) |
| **计数** | Header 显示 "(done/total)" |
| **GPU 状态** | 活动步骤旁显示 GPU 使用信息 |
| **实现状态** | ✅ 已实现 |

### 11.2 合并逻辑

| 项目 | 说明 |
|------|------|
| **CTV + OAR 合并** | 自动 OAR 合并到 CTV 项，label 变为 "CTV + OAR segmentation" |
| **完成条件** | CTV 和 OAR 都 done 后才标记完成 |
| **dedup 路径** | dedup 找到合并项时也走 `_mergedDone` 逻辑 |
| **实现状态** | ✅ 已修复 (2026-06-22) |

### 11.3 折叠与隐藏

| 项目 | 说明 |
|------|------|
| **自动折叠** | AI 回复完成后折叠为 header |
| **自动隐藏** | 折叠 4 秒后淡出隐藏 |
| **手动展开** | 点击 header 展开查看详细 |
| **新消息清除** | 每次新消息开始时清除旧 todo |
| **实现状态** | ✅ 已实现 |

---

## 12. Thinking Chain 思考链

| 项目 | 说明 |
|------|------|
| **期望效果** | 显示 LLM 调用链：用户输入 → LLM 思考 → 工具调用 → 结果 → 回复 |
| **实时更新** | SSE 事件实时追加步骤 |
| **折叠/展开** | 点击 header 折叠/展开 |
| **步骤详情** | 点击单个步骤展开查看参数和结果 |
| **计时** | Header 显示总耗时 |
| **自动折叠** | AI 回复后自动折叠 |
| **实现状态** | ✅ 已实现 |

---

## 13. 多语言系统

### 13.1 全局语言

| 项目 | 说明 |
|------|------|
| **切换** | 右上角 EN/中 芯片按钮 |
| **存储** | `window._i18nLang` + localStorage |
| **影响范围** | Todo 标签 / 工具进度 / 报告 / 状态消息 |
| **实现状态** | ✅ 已实现 |

### 13.2 LLM 回复语言

| 项目 | 说明 |
|------|------|
| **期望效果** | LLM 回复语言与用户输入语言一致 |
| **实现** | `memory/language.py` 检测输入语言 → 注入 system prompt 子句 |
| **实现状态** | ✅ 已实现 |

### 13.3 报告语言

| 项目 | 说明 |
|------|------|
| **期望效果** | 跟随全局语言按钮，不从用户输入推断 |
| **修复** | `refreshFinalReport` / `reportAutoFill` 优先 `window._i18nLang` |
| **实现状态** | ✅ 已修复 (2026-06-22) |

---

## 14. 面板布局与拖拽

### 14.1 面板切换

| 面板 | Tab 名 | 内容 | 实现状态 |
|------|--------|------|----------|
| Input | 📁 Input | CT 上传 + 肿瘤类型选择 | ✅ |
| Metrics | 📊 Metrics | 规划指标 + DVH + OAR 表 | ✅ |
| Viewers | 🖼️ Viewers | 2D 三视图 + 3D 可视化 | ✅ |
| Report | 📋 Report | 报告编辑器 + PDF 预览 | ✅ |

### 14.2 拖拽分割线

| 项目 | 说明 |
|------|------|
| **期望效果** | 三列布局 (左/中/右) 可通过分割线拖拽调整宽度 |
| **持久化** | 宽度保存到 localStorage |
| **光标** | 拖拽时显示 `col-resize` |
| **实现状态** | ✅ 已实现 |

---

## 15. 会话管理

| 项目 | 说明 |
|------|------|
| **自动创建** | 首次发送消息时自动创建 "New chat" 会话 |
| **持久化** | 会话保存到 localStorage，刷新后恢复 |
| **切换** | 左侧会话列表点击切换 |
| **清除** | "Clear" 按钮清除当前会话 |
| **实现状态** | ✅ 已实现 |

---

## 16. 联网搜索

| 项目 | 说明 |
|------|------|
| **期望效果** | LLM 判断需要联网时调用 `web_search` 工具 |
| **搜索源** | DuckDuckGo / Wikipedia / arXiv 等 |
| **结果显示** | 摘要 + 来源链接 |
| **实现状态** | ✅ 已实现 |

---

## 17. Quality Review 质量审核

| 项目 | 说明 |
|------|------|
| **期望效果** | 多 Agent (PlanReviewer + FactChecker + SafetyGuardian) 审核规划结果 |
| **审核结果** | PASS / CONDITIONAL / REJECT / ESCALATE |
| **当前状态** | ⚠️ 已禁用 (2026-06-22) |
| **禁用原因** | 审核后触发神秘 "Review Feedback" 重试，生成英文 stub 覆盖中文报告 |
| **后续计划** | 定位重试来源后重新启用 |

---

# 二、交互流程与期望效果

## 1. 规划主流程

```
用户输入: "请执行放射性粒子植入规划"
         ↓
sendChat() → POST /api/chat (stream: true)
         ↓
SSE 事件流:
  1. start (language detection)
  2. step: Crystallized Skill (记忆匹配)
  3. step: Experience Recall (经验召回)
  4. step: LLM Call 1 (路由决策)
  5. step: ctv_segmentation pending → done
  6. step: oar_segmentation pending → done (自动触发)
  7. step: LLM Call 2 (决定调用 planning_pipeline)
  8. step: planning_pipeline pending
     8a. step: trajectory_init pending → done
     8b. step: trajectory_refine pending → done
     8c. step: seed_planning pending → done
     8d. step: dose_calc pending → done
     8e. step: dose_eval pending → done
  9. step: planning_pipeline done
  10. step: LLM Call 3 (生成回复)
  11. text_chunk: 流式回复文本
  12. step: AI Response done
  13. response: 最终回复
  14. done
```

**期望效果**:
- Todo 列表实时更新每个步骤状态
- Thinking Chain 显示完整调用链
- 最终回复是完整的中文规划报告
- Metrics 面板自动更新指标
- DVH 自动绘制
- 3D 网格自动加载
- Report 自动截图

**当前状态**: ✅ 已正确实现

---

## 2. 聊天交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| Enter | 发送消息 | ✅ |
| 点击发送按钮 | 发送消息 | ✅ |
| Shift+Enter | 换行不发送 | ✅ |
| 发送中再次点击 | 中断当前请求 | ✅ |
| 上/下箭头 | 浏览历史消息 | ✅ |
| 首个 step 事件 | 替换为 Thinking Chain | ✅ |
| text_chunk | 流式追加到回复气泡 | ✅ |
| AI Response done | 渲染 Markdown，折叠 Thinking Chain | ✅ |
| done | 显示 Footer (耗时/token/工具数) | ✅ |
| Todo pending | 呼吸动画，计时开始 | ✅ |
| Todo done | ✓ 标记，显示耗时 | ✅ |
| AI Response done | 所有未完成项标记 done，折叠 | ✅ (2026-06-22 修复) |
| 折叠 4s | 淡出隐藏 | ✅ |
| 新消息 | 清除旧 Todo | ✅ |

---

## 3. 2D 查看器交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| 拖拽滑块 | 切换切片，实时渲染 | ✅ |
| 鼠标滚轮 | 切换切片 | ✅ |
| 键盘 ←/→ | 上/下一切片 | ✅ |
| Window 输入 | 调整窗宽 | ✅ |
| Level 输入 | 调整窗位 | ✅ |
| 鼠标拖拽 (左键) | 调整窗宽窗位 | ✅ |
| 滚轮 | 缩放 | ✅ |
| 右键拖拽 | 平移 | ✅ |
| 双击 | 重置缩放 | ✅ |
| Label overlay 开关 | 显示/隐藏 CTV/OAR 轮廓 | ✅ |
| Dose overlay 开关 | 显示/隐藏剂量热力图 | ✅ |
| 剂量阈值滑块 | 调整剂量显示阈值 | ✅ |

---

## 4. 3D 查看器交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| 左键拖拽 | 旋转 | ✅ |
| 右键拖拽 | 平移 | ✅ |
| 滚轮 | 缩放 | ✅ |
| 3D.fit 按钮 | 重置相机到网格包围盒 | ✅ |
| Opacity 滑块 | 调整所有网格透明度 | ✅ |
| Wireframe 开关 | 切换线框模式 | ✅ |
| Skin 开关 | 显示/隐藏 CT 皮肤 | ✅ |

---

## 5. Data Tree 交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| 单击 | 选中项 | ✅ |
| Ctrl+单击 | 多选/取消 | ✅ |
| Shift+单击 | 范围选择 (同组内) | ✅ |
| 点击眼睛图标 | 切换单项可见性 | ✅ |
| Group 眼睛图标 | 切换整组可见性 | ✅ |
| 右键 3D Reconstruct | 3D 重建选中器官 | ✅ |
| 右键 Change Color | 打开颜色选择器 | ✅ (2026-06-22 修复 CTV) |
| 右键 Show/Hide Selected | 显示/隐藏选中项 | ✅ |
| 右键 Solo Selected | 只显示选中项 | ✅ |
| 右键 Opacity | 设置透明度 | ✅ |

---

## 6. DVH 交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| 鼠标悬停曲线 | 显示 tooltip (器官名 + 剂量 + 体积) | ✅ |
| tooltip 不超出图表 | SVG viewBox 坐标 clamp | ✅ (2026-06-22 修复) |
| 单击曲线 | 放置标记 (剂量, 体积, 器官名) | ✅ |
| 单击标记 | 移除标记 | ✅ |
| 滚轮/拖拽 | 缩放/平移 | ✅ |
| 双击 | 重置 | ✅ |

---

## 7. 报告面板交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| 点击字段 | 编辑模式 | ✅ |
| 输入内容 | 实时更新预览 | ✅ |
| Auto-fill | 从 server 自动填充 | ✅ |
| 📷 Capture 2D/3D/DVH | 捕获截图 | ✅ |
| Upload | 上传自定义图片 | ✅ |
| 📸 Snapshot | 保存当前版本 | ✅ |
| 📜 History | 查看/恢复历史版本 | ✅ |
| 📋 Audit | 查看编辑历史 | ✅ |
| ✅ Validate | 校验必填字段 | ✅ |
| Export PDF | 生成 PDF | ✅ |

---

## 8. 面板切换交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| 点击 Input tab | 显示输入面板 | ✅ |
| 点击 Metrics tab | 显示指标面板 + DVH | ✅ |
| 点击 Viewers tab | 显示 2D/3D 查看器，3D 重新初始化 | ✅ (2026-06-22 修复) |
| 点击 Report tab | 显示报告编辑器，首次自动截图 | ✅ |

---

## 9. 全局控件交互

| 操作 | 期望效果 | 状态 |
|------|---------|------|
| 点击 EN/中 | 切换全局语言 | ✅ |
| 切换后 Todo | 标签更新为新语言 | ✅ |
| 切换后 Report | 报告语言更新 | ✅ (2026-06-22 修复) |
| 切换后 Footer | Footer 标签更新 | ✅ |
| 拖拽分割线 | 调整面板宽度，保存到 localStorage | ✅ |
| Clear 按钮 | 清除当前会话 | ✅ |
| 刷新页面 | 恢复上次会话 | ✅ |

---

# 三、规划流水线详解

## 1. 流程总览

```
用户: "请执行放射性粒子植入规划"
    │
    ├─→ [1] CTV 分割 (ctv_segmentation)
    │       ├─ nnUNet 推理
    │       ├─ 返回多标签 mask (tumor/artery/vein/pancreas)
    │       └─ 存储 ctv_array, ctv_label_names, labelColorLUT
    │
    ├─→ [2] OAR 分割 (oar_segmentation) [自动触发]
    │       ├─ TotalSegmentator 推理
    │       ├─ 返回 57+ 器官标签
    │       └─ 存储 oar_array, organ_names
    │
    ├─→ [3] 规划流水线 (planning_pipeline, step="full")
    │       ├─ 3a. 轨迹初始化 (trajectory_init) → 130 条候选
    │       ├─ 3b. 轨迹细化 (trajectory_refine) → 筛选最优
    │       ├─ 3c. 粒子规划 (seed_planning) → 14 颗种子
    │       ├─ 3d. 剂量计算 (dose_calc) → 3D 剂量分布
    │       └─ 3e. 剂量评估 (dose_eval) → V100/D90/CI/HI
    │
    └─→ [4] LLM 生成最终回复
            └─ 10 段结构化报告 (中文/英文)
```

---

## 2. SSE 事件流

### 2.1 事件类型

| 事件 | 格式 | 说明 |
|------|------|------|
| `start` | `{language: {code: "zh"/"en"}}` | 会话开始，包含检测到的语言 |
| `step` | `{id, type, title, content, status, tool, params, result}` | 步骤事件 |
| `text_chunk` | `{text: "..."}` | LLM 回复文本流 |
| `response` | `{response: "...", llm_meta: {...}}` | 最终回复 |
| `done` | `{context: {...}}` | 流结束 |
| `error` | `{message: "..."}` | 错误 |

### 2.2 完整事件序列

```
event: start
data: {"language": {"code": "zh"}}

event: step
data: {"id": 1, "type": "user", "title": "User Input", "status": "done"}

event: step
data: {"id": 2, "type": "memory", "title": "Crystallized Skill", "status": "done"}

event: step
data: {"id": 3, "type": "thinking", "title": "LLM Call 1", "status": "done"}

event: step
data: {"id": 4, "type": "tool", "tool": "ctv_segmentation", "status": "pending"}

event: step
data: {"id": 4, "type": "tool", "tool": "ctv_segmentation", "status": "done",
       "result": "CTV segmentation completed. Volume: 26197.3 mm3"}

event: step
data: {"id": 5, "type": "tool", "tool": "oar_segmentation", "status": "pending",
       "parent_tool": "ctv_segmentation"}

event: step
data: {"id": 5, "type": "tool", "tool": "oar_segmentation", "status": "done",
       "result": "57 organs", "parent_tool": "ctv_segmentation"}

event: step
data: {"id": 6, "type": "tool", "tool": "planning_pipeline", "status": "pending"}

event: step
data: {"id": 7, "type": "tool", "tool": "trajectory_init", "status": "pending",
       "parent_tool": "planning_pipeline"}

event: step
data: {"id": 7, "type": "tool", "tool": "trajectory_init", "status": "done",
       "result": "130 trajectories", "parent_tool": "planning_pipeline"}

... (trajectory_refine, seed_planning, dose_calc, dose_eval 同上)

event: step
data: {"id": 6, "type": "tool", "tool": "planning_pipeline", "status": "done",
       "result": "Planning completed: 14 seeds. V100=91.0%..."}

event: step
data: {"id": 12, "type": "thinking", "title": "LLM Call 3", "status": "done"}

event: text_chunk
data: {"text": "## 1. 流程总结\n\n已完成放射性粒子植入规划全流程..."}

event: step
data: {"id": 13, "type": "assistant", "title": "AI Response", "status": "done"}

event: response
data: {"response": "## 1. 流程总结\n\n...", "llm_meta": {...}}

event: done
data: {"context": {...}}
```

---

## 3. step_callback 机制

### 3.1 目的

将 `planning_pipeline` 内部的 5 个子步骤暴露为独立的 SSE step 事件，使 Todo 列表能实时显示每个子步骤的进度。

### 3.2 实现

```python
# 工具内部调用:
step_callback("trajectory_init", "pending", "Generating candidate trajectories")
# ... 执行 ...
step_callback("trajectory_init", "done", "130 trajectories")
```

### 3.3 DRAIN 时机

| DRAIN | 位置 | 目的 |
|-------|------|------|
| DRAIN-1 | `_execute_tool_with_memory` 返回后 | 刷新工具执行期间的子步骤事件 |
| DRAIN-2 | `_store_tool_result` 返回后 | 刷新 auto-OAR 等触发的事件 |

---

## 4. 自动 OAR 触发

### 4.1 触发条件

CTV 分割完成后，OAR map 中器官数 < 5 时自动调用 `oar_segmentation`。

### 4.2 Todo 合并

```javascript
if (step.tool === 'oar_segmentation' && step.parent_tool === 'ctv_segmentation') {
    ctvItem.label = 'CTV + OAR segmentation';
    ctvItem._mergedOAR = true;
    // 删除预测的 OAR 项
}
```

### 4.3 完成条件

```javascript
if (item._mergedOAR) {
    item._mergedDone[step.tool] = true;
    if (item._mergedDone['ctv_segmentation']
        && item._mergedDone['oar_segmentation']) {
        todo.markDone(item);
    }
}
```

---

## 5. 前端响应链

### 5.1 refreshPlanningUI 执行顺序

```
1. fetch /api/planning/results
2. updateMetrics (指标卡片)
3. drawDVH (DVH 曲线)
4. updateImageAnalysis (影像分析)
5. loadCTVAndObstacleMeshes (CTV + OAR 3D 网格)
6. loadSeeds3D (粒子 3D)
7. loadAllIsoSurfaces (等剂量面)
8. reportAutoFill (报告自动填充)
9. await Promise.all (等待所有 mesh 加载)
10. forceRender3DViewer (3D 重新渲染)
11. updateClinicalEvaluation (临床评估)
12. autoCaptureReportFigures (报告截图)
```

---

## 6. 规划结果 API

### GET /api/planning/results

```json
{
    "success": true,
    "metrics": {
        "v100": 91.0, "d90": 123.22, "v150": 80.7, "v200": 69.0,
        "ci": 0.828, "hi": 93.638, "plan_score": 73,
        "oar_metrics": {
            "stomach": {"d2cc": 92.68, "d1cc": 108.19},
            "liver": {"d2cc": 25.16, "d1cc": 38.37}
        }
    },
    "dvh": {
        "CTV": {"dose": [...], "volume": [...]},
        "stomach": {"dose": [...], "volume": [...]}
    },
    "seeds": [{"x": 1.2, "y": 3.4, "z": 5.6}],
    "needles": [{"start": [...], "end": [...]}],
    "total_seeds": 14,
    "num_trajectories": 2,
    "has_dose": true
}
```

---

## 7. 3D 网格数据

### GET /api/viewer/3d_mask

```json
{
    "success": true,
    "vertices": [[x, y, z], ...],
    "faces": [[i, j, k], ...],
    "color": [255, 0, 0],
    "label_name": "pancreatic tumor",
    "label_id": 1
}
```

---

## 8. 剂量评估详情

### OAR 剂量限制 (胰腺癌)

| 器官 | D2cc 限制 | 来源 |
|------|----------|------|
| stomach | < 90 Gy | GEC-ESTRO |
| duodenum | < 90 Gy | GEC-ESTRO |
| small_bowel | < 90 Gy | GEC-ESTRO |
| kidney | < 50 Gy | GEC-ESTRO |
| spinal cord | < 50 Gy | GEC-ESTRO |
| liver | < 60 Gy | GEC-ESTRO |

---

# 四、报告面板详解

## 1. 面板布局

```
┌─────────────────────────────────────────────────────────────┐
│  Report Toolbar                                              │
│  📷 Capture | ✨ Auto-fill | 📸 Snapshot | 📜 History       │
│  🔍 Audit | ✅ Validate | 📤 Export PDF | EN/中 | Zoom      │
│                                                              │
│  ┌──────────────────────────┐ ┌────────────────────────────┐│
│  │  Editor (top)            │ │  Preview (bottom)          ││
│  │  [Patient] [Imaging]     │ │  [PDF Preview]             ││
│  │  [Planning] [Dose]       │ │  [DVH Figure]              ││
│  │  [OAR] [Interpretation]  │ │  [3D Figure]               ││
│  │  [References] [Figures]  │ │                            ││
│  └──────────────────────────┘ └────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 数据来源

| 字段 | 来源 | API |
|------|------|-----|
| 患者 ID | CT 文件名 | — |
| 影像模态 | DICOM tags | `/api/header/info` |
| 切片数/间距/层厚 | CT shape/spacing | `/api/header/info` |
| CTV 体积 | CTV 分割结果 | `/api/report/auto-fill` |
| OAR 数量 | Data Tree | `/api/report/auto-fill` |
| 总粒子数 | planning results | `/api/report/auto-fill` |
| V100/D90/CI/HI | dose_metrics | `/api/report/auto-fill` |
| OAR D2cc/D1cc | oar_metrics | `/api/report/auto-fill` |

---

## 3. 截图系统

### 3.1 截图类型

| 类型 | 来源 | 标题 (EN) | 标题 (ZH) |
|------|------|-----------|-----------|
| Segmentation | 2D viewer (axial) | CTV and OAR segmentation overlay | 靶区与危及器官分割重建 |
| Dose | 2D viewer (dose overlay) | Dose distribution heatmap | 剂量分布热图 |
| 3D Plan | Three.js canvas | 3D treatment plan | 三维规划方案 |
| DVH | Plotly.toImage | DVH — Dose Volume Histogram | DVH 剂量体积直方图 |

### 3.2 3D 截图特殊处理

```javascript
// preserveDrawingBuffer: true 确保 hidden canvas 可截图
scene3D.renderer.render(scene3D.scene, scene3D.camera);  // 显式 render
const dataUrl = canvas3d.toDataURL('image/png');
if (dataUrl.length > 1000) { ... }  // 检查非空白
```

### 3.3 去重逻辑

```javascript
const _lastPlan = window.state.lastPlanTimestamp;
if (_lastPlan) {
    figures = figures.filter(f => {
        if (f.type === 'upload') return true;  // 保留用户上传
        return f.capturedAt >= _lastPlan;       // 丢弃旧截图
    });
}
if (figures.length > 0) return;  // 只在无截图时捕获
```

---

## 4. 语言系统

### 4.1 语言来源优先级

```
1. window._i18nLang (全局 EN/中 按钮)
2. window.reportForm.language (从 localStorage 恢复)
3. 'en' (硬编码默认)
```

### 4.2 语言切换流程

```
用户点击 EN/中
    ↓
window._i18nLang = 'en'
    ↓
reportForm.language = 'en'
    ↓
_autoFillInterpretation()    // 重新生成解读
renderReportEditor()          // 重渲染编辑器
_updateReportPreview()        // 重渲染预览
    ↓
清除旧截图 (保留用户上传)
autoCaptureReportFigures()    // 重新截图，新语言标题
```

---

## 5. 版本管理

### 5.1 快照 (Snapshot)

```javascript
Report.snapshots.save(label)     // 保存到 localStorage
Report.snapshots.restore(idx)    // 恢复指定版本
Report.snapshots.list()          // 列出所有快照
```

### 5.2 校验规则

```javascript
const THRESHOLDS = {
    'metrics.v100':  { ok: v => v >= 90,  warn: v => v >= 80 },
    'metrics.d90':   { ok: v => v >= 100, warn: v => v >= 85 },
    'metrics.v150':  { ok: v => v <= 50,  warn: v => v <= 70 },
    'metrics.v200':  { ok: v => v <= 20,  warn: v => v <= 30 },
    'metrics.ci':    { ok: v => v >= 0.6, warn: v => v >= 0.4 },
    'metrics.hi':    { ok: v => v <= 0.35, warn: v => v <= 0.5 },
    'metrics.score': { ok: v => v >= 80,  warn: v => v >= 60 },
};
```

---

## 6. 模态框系统

```javascript
function _showModal(title, body) {
    // 暗色主题样式 (2026-06-22 修复)
    overlay: position:fixed; inset:0; background:rgba(15,23,42,0.6);
    dialog: background:var(--bg-2,#1e293b); border:1px solid var(--card-border,#334155);
    text: color:var(--text,#e2e8f0);
}
```

---

## 7. PDF 导出

```javascript
async function exportReportPDF() {
    await autoCaptureReportFigures();  // 1. 自动截图
    _updateReportPreview();             // 2. 重渲染预览
    await new Promise(r => setTimeout(r, 200));  // 3. 等待 DOM
    // 4. html2canvas 渲染每页
    // 5. 保存 PDF: BrachyPlan_Report_{患者ID}_{日期}.pdf
}
```

---

## 8. BrachyBot 自动填充

### 填充范围

| scope | 填充内容 |
|-------|---------|
| `all` | 全部字段 |
| `patient` | 患者信息 |
| `metrics` | 规划指标 |
| `oar` | OAR 剂量表 |
| `interpretation` | 临床解读 |
| `safety` | 安全警告 |

---

# 五、已修复 Bug 清单

## 1. Report 语言问题

**用户反馈**: 全局按钮是英文，规划完后 report PDF 自动切换为中文。

**根因**: `refreshFinalReport()` 和 `reportAutoFill()` 中，`_detectLanguageFromText(window._lastUserMessage)` 检测到中文输入就覆盖 `reportForm.language = 'zh'`，忽略全局英文设置。

**修复**: 两处都改为优先使用 `window._i18nLang`。

```javascript
// Before (broken):
const detected = _detectLanguageFromText(window._lastUserMessage);
if (detected) window.reportForm.language = detected;

// After (fixed):
if (typeof window._i18nLang === 'string') {
    window.reportForm.language = window._i18nLang;
} else if (window._lastUserMessage) {
    const detected = _detectLanguageFromText(window._lastUserMessage);
    if (detected) window.reportForm.language = detected;
}
```

**状态**: ✅ 已修复

---

## 2. 3D 查看器空白

**用户反馈**: 规划完后 3D 窗口黑漆漆一片。

**根因**: 三重问题叠加:
1. WebGLRenderer 无 `preserveDrawingBuffer`，hidden canvas 的 `toDataURL` 返回空白
2. 切换到 Viewers 面板时未调用 `forceRender3DViewer()`
3. 截图捕获时未强制 render 一帧

**修复**:
- `preserveDrawingBuffer: true`
- `switchPanel('viewers')` 中调用 `forceRender3DViewer()`
- 截图前显式 `renderer.render()`

**状态**: ✅ 已修复

---

## 3. DVH Tooltip 溢出

**用户反馈**: DVH 曲线 tooltip 文字飘到图表正上方。

**根因**: `_clampDvhTooltip` 在 Plotly 定位之前执行，且使用 screen 坐标与 SVG 坐标混用。

**修复**: 使用 `requestAnimationFrame` 延迟执行，使用 SVG `viewBox` 坐标系进行 clamp。

```javascript
function _clampDvhTooltip() {
    requestAnimationFrame(() => {
        const mainSvg = dvhEl.querySelector('.main-svg');
        const vb = mainSvg.viewBox.baseVal;
        const svgW = vb.width || mainSvg.clientWidth;
        // ... clamp x,y 在 [0, svgW-tw] 范围内
    });
}
```

**状态**: ✅ 已修复

---

## 4. CTV 颜色修改无效

**用户反馈**: Data Tree 中右键 CTV mask 点击 Change Color 无反应。

**根因**: `openColorPicker()` 不处理 `ctv_*` ID。`applyColor()` 末尾有未定义的 `input.click()` 抛出 ReferenceError。

**修复**:
- 添加 `ctv_*` 条件从 `dataTreeState.ctvLabels` 获取状态
- `applyColor()` 添加 3D mesh 颜色更新
- 移除 `input.click()`

**状态**: ✅ 已修复

---

## 5. Report 自动截图缺失

**用户反馈**: 规划完后 Report 中不自动放 DVH/3D 截图。

**根因**: `autoCaptureReportFigures` 不在 `refreshPlanningUI` 完成后调用。

**修复**: 在 `refreshPlanningUI` 末尾添加 `await autoCaptureReportFigures()`。

**时序**: drawDVH → await meshes → forceRender3DViewer → autoCaptureReportFigures

**状态**: ✅ 已修复

---

## 6. 二级界面样式问题

**用户反馈**: History/Audit/Validate 等二级界面字体是浅色配浅色背景，看不清。

**根因**: `_showModal()` 使用 `background:#fff` (白色背景)，内容用暗色主题颜色。

**修复**: 所有模态框改为暗色主题 (`var(--bg-2)`)，内容使用 CSS 变量 + fallback。

**状态**: ✅ 已修复

---

## 7. Quality Review 重试

**用户反馈**: 回答完后又冒出来一个新的敷衍的英文回答。

**根因**: Quality Review REJECT 后触发 "Review Feedback" 重试，LLM 生成简短英文 stub 覆盖中文报告。

**修复**: 禁用所有 3 处 Quality Review 调用。

**状态**: ⚠️ 已禁用 (需定位重试来源后重新启用)

---

## 8. Todo 合并逻辑

**用户反馈**: Todo 显示 "CTV segmentation running → OAR segmentation completed"，缺少 CTV completed。

**根因**: dedup 路径直接调用 `markDone(existing)`，绕过 `_mergedDone` 跟踪。

**修复**: dedup 路径中添加合并检查，只有 CTV 和 OAR 都完成才标记 done。

**状态**: ✅ 已修复

---

## 9. Todo 最终回复计数

**用户反馈**: 回答完成后 todo 显示 "1/2"，联网搜索还在转圈。

**根因**: `fold()` 只折叠 UI，不把 pending 项标记为 done。

**修复**: `fold()` 先把所有未完成项标记为 done，再折叠。

**状态**: ✅ 已修复

---

## 10. 标题排版

**用户反馈**: 每个标题左边都有一竖，标题图标都是 📌，不够美观。

**根因**: CSS `border-left: 3px solid` + marked renderer 注入 📌 图标。

**修复**: H2 改为 `border-bottom` 分割线，H3 移除 `border-left`，renderer 移除图标注入。

**状态**: ✅ 已修复

---

# 六、API 端点清单

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | LLM 聊天 (SSE 流) |
| `/api/upload` | POST | 上传 CT 文件 |
| `/api/segmentation` | POST | CTV/OAR 分割 |
| `/api/planning/results` | GET | 获取规划结果 |
| `/api/planning/seeds_3d` | GET | 获取 3D 粒子/针道数据 |
| `/api/planning/clear` | POST | 清除规划结果 |
| `/api/planning/show_step` | POST | 显示规划步骤 |
| `/api/viewer/image` | GET | 获取 2D 切片图像 |
| `/api/viewer/overlay` | POST | 获取标签 overlay |
| `/api/viewer/3d_mask` | POST | 获取 3D 网格数据 |
| `/api/viewer/3d_skin` | POST | 获取 CT 皮肤网格 |
| `/api/viewer/load` | POST | 加载 CT 文件 |
| `/api/viewer/slice` | POST | 获取切片数据 |
| `/api/viewer/volume` | GET | 获取 volume 数据 |
| `/api/viewer/label_volume` | GET | 获取标签 volume |
| `/api/viewer/organs` | GET | 获取器官列表 |
| `/api/viewer/threshold` | POST | 设置阈值 |
| `/api/viewer/hu` | POST | 设置 HU 窗宽窗位 |
| `/api/header/info` | POST | 获取 DICOM 元数据 |
| `/api/report/auto-fill` | POST | 报告自动填充 |
| `/api/device/status` | GET | GPU 状态 |

---

# 七、技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python / Flask |
| LLM | OpenAI-compatible API (MiMo v2.5) |
| 前端 | Vanilla JS / HTML / CSS |
| 2D 渲染 | Canvas 2D |
| 3D 渲染 | Three.js + OrbitControls |
| DVH 图表 | Plotly.js |
| PDF 生成 | html2canvas + jsPDF |
| 医学影像 | SimpleITK / NiBabel |
| 分割模型 | nnUNet / TotalSegmentator |
| GPU 调度 | device_manager.py |
| 多 Agent | PlanReviewer + FactChecker + SafetyGuardian |
| 记忆系统 | 5 层分层记忆 + 经验学习 |
