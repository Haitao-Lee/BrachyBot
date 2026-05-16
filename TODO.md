# BrachyBot 框架完善计划

## 一、核心集成 (Brain-System Integration)

### 1.1 BrachyAgent 接入 Brain 系统
**文件**: `AgenticSys.py`

```python
# 现状: BrachyAgent 使用自己的 ToolRegistry
# 目标: 接入 BrainToolBridge 实现 LLM 驱动决策

class BrachyAgent:
    def __init__(self, session_id, config):
        # 现有...
        self.brain_bridge = initialize_brain_integration()
        self.router = LLMRouter(config.get("llm_config", {}))
        self.case_executor = CaseExecutor(self.brain_bridge)

    def _llm_driven_plan(self, task: str, context: Dict) -> List[Dict]:
        """使用 PlannerDecider 生成执行计划"""
        planner = PlannerDecider(self.router.default_llm, self.tool_registry)
        rag_context = get_rag().query(task)
        return planner.decide(task, context, rag_text=rag_context)

    def _llm_evaluate(self, plan_result: Dict, context: Dict) -> Dict:
        """使用 QualityDecider 评估计划"""
        quality = QualityDecider(self.router.default_llm)
        return quality.decide(plan_result, context)
```

### 1.2 Chat 模式 LLM 驱动
**文件**: `AgenticSys.py` - `chat()` 方法

```python
def chat(self, message: str) -> str:
    """真正的 LLM 驱动对话"""
    # 1. LLM 理解用户意图
    intent = self._understand_intent(message)

    # 2. LLM 生成执行计划
    if intent["type"] == "planning":
        plan = self._llm_driven_plan(intent["task"], intent["context"])
        result = self.case_executor.execute(plan, intent["context"])
        return self._format_result(result)

    # 3. LLM 回答问题
    elif intent["type"] == "query":
        rag_context = get_rag().query(message)
        response = self.router.chat(message, system=CLINICAL_CONTEXT, rag_text=rag_context)
        return response.content
```

---

## 二、Web 界面完善

### 2.1 后端 API (web/server.py)
```python
# 需要实现:
- /api/plan/preoperative  - 术前规划接口
- /api/plan/intraoperative - 术中重规划接口
- /api/chat               - 对话接口
- /api/status             - 状态查询
- /api/export/dicom      - DICOM 导出
- WebSocket 支持实时进度推送
```

### 2.2 前端界面
**目录**: `web/app/` (新建)
```
web/
├── server.py
├── app/
│   ├── index.html       # 主界面
│   ├── static/
│   │   ├── css/style.css
│   │   ├── js/app.js    # Vue/React 前端
│   │   └── js/ viewer.js # 3D 查看器
│   └── components/
│       ├── ImageViewer.vue
│       ├── PlanEditor.vue
│       └── ChatPanel.vue
```

---

## 三、工具工厂补全

### 3.1 缺失工具
| 工具 | 路径 | 状态 |
|------|------|------|
| `report_generator` | `output/report_generator.py` | ❌ 缺失 |
| `plan_refinement` | `plan_quality/plan_refinement.py` | ⚠️ 待完善 |
| `dicom_rt_exporter` | `output/dicom_rt_exporter.py` | ⚠️ 部分实现 |

### 3.2 实现模板
```python
# output/report_generator.py (待实现)

class ReportGeneratorTool:
    @property
    def name(self) -> str:
        return "report_generator"

    @property
    def description(self) -> str:
        return "生成治疗计划报告(JSON/HTML/Markdown)"

    def _execute(self, plan_data: Dict, template: str = "standard", **kwargs) -> ToolResult:
        # 1. 收集计划数据
        # 2. 填充模板
        # 3. 导出报告
        pass
```

---

## 四、端到端测试

### 4.1 集成测试脚本
**目录**: `tests/` (新建)
```
tests/
├── __init__.py
├── test_preoperative.py    # 术前规划测试
├── test_intraoperative.py  # 术中重规划测试
├── test_chat.py           # 对话系统测试
├── test_brain_system.py   # Brain 系统测试
├── conftest.py            # pytest 配置
└── fixtures/
    ├── sample_ct.nii.gz
    └── expected_results.json
```

### 4.2 示例数据
**目录**: `examples/` (新建)
```
examples/
├── pancreas_plan.py       # 胰腺癌规划示例
├── prostate_plan.py       # 前列腺癌规划示例
└── config.yaml            # 配置文件
```

---

## 五、文档完善

### 5.1 需补充文档
- `docs/API.md` - 完整 API 文档
- `docs/ARCHITECTURE.md` - 系统架构详解
- `docs/DEVELOPMENT.md` - 开发指南
- `docs/DEPLOYMENT.md` - 部署文档

### 5.2 示例notebook
**目录**: `notebooks/` (新建)
```
notebooks/
├── 01_getting_started.ipynb
├── 02_preoperative_planning.ipynb
├── 03_intraoperative_replanning.ipynb
└── 04_llm_chat_interface.ipynb
```

---

## 六、优先级排序

### P0 (阻塞性问题)
1. ✅ Brain-Decider 集成到 BrachyAgent
2. ✅ 补全 `dicom_rt_exporter`
3. ✅ 端到端测试可运行

### P1 (重要功能)
4. Web 服务完整实现
5. Chat 模式 LLM 驱动
6. `report_generator` 实现

### P2 (体验优化)
7. 前端 UI 开发
8. 文档完善
9. 示例 notebook

---

## 七、预计工作量

| 任务 | 优先级 | 估计工时 |
|------|--------|----------|
| Brain-Agent 集成 | P0 | 4-6h |
| DICOM 导出修复 | P0 | 2-3h |
| 端到端测试 | P0 | 3-4h |
| Web 服务完善 | P1 | 6-8h |
| Chat LLM 驱动 | P1 | 4-6h |
| Report 生成器 | P1 | 3-4h |
| 前端 UI | P2 | 8-12h |

---

*计划制定时间: 2026-05-14*
