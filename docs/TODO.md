# BrachyBot 框架完善计划

## 一、核心集成 (Brain-System Integration) ✅

### 1.1 BrachyAgent 接入 Brain 系统 ✅
**文件**: `AgenticSys.py`
- BrainToolBridge 已集成
- LLMRouter 支持 14+ 提供商
- CaseExecutor 支持依赖解析

### 1.2 Chat 模式 LLM 驱动 ✅
- 流式输出支持 (text_chunk events)
- 工具执行进度系统
- 自主工具创建能力

---

## 二、Web 界面完善 ✅

### 2.1 后端 API (web/server.py) ✅
```
- /api/plan/preoperative  - 术前规划接口 ✅
- /api/plan/intraoperative - 术中重规划接口 ✅
- /api/chat               - 对话接口 (SSE流式) ✅
- /api/status             - 状态查询 ✅
- /api/export/dicom      - DICOM 导出 ✅
- /api/viewer/*          - CT查看器API ✅
- /api/tasks/*           - 任务进度API ✅
```

### 2.2 前端界面 ✅
- 实时CT切片查看器 (3D Slicer级别)
- 流式对话输出
- 工具执行进度显示
- Slash命令支持
- 键盘快捷键

---

## 三、工具工厂补全 ✅

### 3.1 工具状态
| 工具 | 路径 | 状态 |
|------|------|------|
| `report_generator` | `output/report_generator.py` | ✅ 已实现 |
| `plan_refinement` | `plan_quality/plan_refinement.py` | ✅ 已实现 |
| `dicom_rt_exporter` | `output/dicom_rt_exporter.py` | ✅ 已实现 |

### 3.2 自主工具创建 ✅
- ToolCodeWriter 已集成
- LLM 可自主创建新工具
- 工具自动注册到注册表

---

## 四、Skills 系统重构 ✅

### 4.1 Markdown 技能格式 ✅
- 参考 Claude Code SKILL.md 模式
- YAML frontmatter 定义元数据
- 支持触发词匹配

### 4.2 技能文件
```
skills/markdown/
├── standard_planning.md
├── rl_planning.md
├── pancreas_segmentation.md
├── prostate_segmentation.md
├── generic_segmentation.md
├── dose_evaluation.md
├── viewer_control.md
├── dicom_export.md
├── report_generation.md
└── intraop_replan.md
```

---

## 五、交互体验优化 ✅

### 5.1 流式输出 ✅
- SSE headers 禁用缓冲
- text_chunk 实时推送
- 进度事件实时更新

### 5.2 工具执行进度 ✅
- 进度回调系统
- 实时进度条显示
- 状态文本更新

### 5.3 Slash 命令 ✅
- `/help` - 显示帮助
- `/plan` - 开始治疗计划
- `/segment` - 分割CT图像
- `/evaluate` - 评估剂量计划
- `/export` - 导出DICOM
- `/viewer` - 控制查看器
- `/clear` - 清除聊天历史

### 5.4 键盘快捷键 ✅
- `Ctrl+L` - 清除聊天
- `Ctrl+K` - 聚焦输入框
- `Escape` - 关闭命令菜单

---

## 六、代码质量优化 ✅

### 6.1 删除不必要文件 ✅
- 备份文件 (.bak)
- 修复脚本 (fix_*.py)
- __pycache__ 目录

### 6.2 性能优化 ✅
- 体积渲染内存优化
- 预分配缓冲区
- 复用 ImageData

---

## 七、后续工作

### P1 (重要功能)
1. 双ToolRegistry统一验证
2. 端到端测试
3. 完善文档

### P2 (体验优化)
4. 更多Slash命令
5. 命令历史记录
6. 自动补全增强

---

## 八、预计工作量

| 任务 | 优先级 | 状态 |
|------|--------|------|
| Skills系统重构 | P0 | ✅ 完成 |
| 流式输出优化 | P0 | ✅ 完成 |
| 工具执行进度 | P0 | ✅ 完成 |
| Slash命令 | P1 | ✅ 完成 |
| Viewer实时交互 | P0 | ✅ 完成 |
| 系统提示词优化 | P1 | ✅ 完成 |
| ToolRegistry统一 | P2 | ✅ 完成 |
| 性能优化 | P2 | ✅ 完成 |

---

*最后更新: 2026-05-25*
