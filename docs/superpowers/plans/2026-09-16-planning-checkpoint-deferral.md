# Planning Checkpoint Deferral Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重计算（规划/导板/分割）运行期间把全量 workspace checkpoint 延后到有限的陈旧上限内，回收被持久化占用的规划墙钟，同时保证最终结果与现有持久化语义完全不变。

**Architecture:** 在 `WorkspaceStore` 注入一个只读的"病例忙"探针（复用现有 `_case_has_running_chat_task`），调度定时器在真正落盘前判断：忙且距上次成功落盘 < 60s 就重排一个 3s 定时器；否则照常落盘并刷新时间戳。`flush_agent_checkpoint` 与全部 patch 路径不经过该判断，任务结束仍同步落盘。

**Tech Stack:** Python 3.12、Flask、threading.Timer、pytest、`~/.conda/envs/brachytherapy/bin/python`。

**Spec:** `docs/superpowers/specs/2026-09-16-planning-checkpoint-deferral-design.md`

**运行约定:** 所有 pytest 命令都在仓库根 `<workspace>/BrachyBot` 执行，解释器用 `~/.conda/envs/brachytherapy/bin/python`。新测试文件按惯例把 `tests/` 加入导入路径（见 `tests/conftest.py`，无需自己处理）。

**约束:** 不改 `plans/*`、`tool_factory/seed_plan/*`、快照 schema、revision/租约语义；未注入 probe 时行为与现状一致；一键回退 `BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=0`。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `web/workspace_store.py`（修改） | 探针注入、陈旧上限、完成时间戳、延后决策、定时器集成 |
| `web/server.py`（修改，约 `:320`） | 把 `_case_has_running_chat_task` 接成 store 的探针 |
| `tests/test_workspace_checkpoint_deferral.py`（新建） | 决策函数/定时器/接线/回退测试 |

---

### Task 1: WorkspaceStore 延后决策组件

**Files:**
- Modify: `web/workspace_store.py`（构造函数约 `:1647`；`_snapshot_agent_locked` 约 `:2661` 的 `return result` 之前）
- Test: `tests/test_workspace_checkpoint_deferral.py`（新建）

- [ ] **Step 1: Write the failing tests**

新建 `tests/test_workspace_checkpoint_deferral.py`：

```python
"""Heavy-task checkpoint deferral tests for planning latency."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from web.workspace_store import WorkspaceStore


class _Memory:
    def __init__(self):
        self._lock = threading.RLock()
        self.planning_results = {"dose_metrics": {"v100": 90.0}}
        self._planning_versions = {key: 1 for key in self.planning_results}
        self.patient_data = {"site": "pancreas"}
        self.conversation = [{"role": "user", "content": "plan this case"}]
        self.tool_results = [{"tool": "ctv_segmentation", "success": True}]
        self.context_summary = "summary"
        self.compaction_count = 1
        self.current_phase = SimpleNamespace(value="planning")
        self.conversation_state = {"ctv_segmented": True}
        self.user_lang = "en"
        self._ui_state = {}

    def get_ui_state(self):
        return self._ui_state

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)


class _Agent:
    def __init__(self):
        self.config = {"mode": "rule_based"}
        self.memory = _Memory()


def _case(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("defer_user", "hash")
    case = store.create_session(user["id"], "Deferral case")
    return store, user, case, _Agent()


def test_should_not_defer_without_probe(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_should_not_defer_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS", "0")
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store.checkpoint_max_staleness_seconds == 0.0
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_should_not_defer_without_completed_checkpoint(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_defers_while_busy_and_fresh(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store._should_defer_checkpoint(user["id"], case.id) is True


def test_does_not_defer_when_stale(tmp_path):
    store, user, case, _agent = _case(tmp_path)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[(user["id"], case.id)] = (
        time.monotonic() - store.checkpoint_max_staleness_seconds - 5.0
    )
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_probe_failure_does_not_defer(tmp_path):
    store, user, case, _agent = _case(tmp_path)

    def _broken(_u, _s):
        raise RuntimeError("registry unavailable")

    store.set_heavy_task_probe(_broken)
    store._checkpoint_completed_at[(user["id"], case.id)] = time.monotonic()
    assert store._should_defer_checkpoint(user["id"], case.id) is False


def test_successful_checkpoint_records_completion_time(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    assert key not in store._checkpoint_completed_at
    store.snapshot_agent(user["id"], case.id, agent, reason="seed")
    assert key in store._checkpoint_completed_at
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
```

Expected: `FAILED`（`AttributeError: 'WorkspaceStore' object has no attribute 'set_heavy_task_probe'` 等）。

- [ ] **Step 3: Implement the store components**

在 `web/workspace_store.py` 模块常量区（`TRANSIENT_COLLECTION_LIMIT` 等常量附近）新增：

```python
def _checkpoint_max_staleness_seconds() -> float:
    """Bound how long a busy case may defer its scheduled full checkpoint.

    ``0`` disables deferral entirely and restores the pre-deferral timing.
    Invalid values fall back to the default instead of disabling durability.
    """
    default = 60.0
    raw = os.environ.get("BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS")
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=%r; using %.0f",
            raw,
            default,
        )
        return default
    return max(0.0, value)


DEFER_RETRY_SECONDS = 3.0
```

在 `WorkspaceStore.__init__`（`self._checkpoint_generations` 初始化附近）新增：

```python
        # A busy case may defer its debounced full checkpoint for a bounded
        # window so planning does not compete with 30MB snapshot rewrites.
        # Without an injected probe the timer runs exactly as before.
        self._heavy_task_probe: Optional[Callable[[str, str], bool]] = None
        self._checkpoint_completed_at: Dict[Tuple[str, str], float] = {}
        self.checkpoint_max_staleness_seconds = _checkpoint_max_staleness_seconds()
```

在 `WorkspaceStore` 的 `schedule_agent_checkpoint` 之前新增两个方法：

```python
    def set_heavy_task_probe(
        self, probe: Optional[Callable[[str, str], bool]],
    ) -> None:
        """Install the per-case heavy-task query used to defer checkpoints.

        The probe is query-only and must stay cheap: it is called for every
        scheduled checkpoint of an active case.
        """
        self._heavy_task_probe = probe

    def _should_defer_checkpoint(self, user_id: str, session_id: str) -> bool:
        """Return whether a scheduled checkpoint should wait for a busy case.

        Deferral is opt-in: without an injected probe, a positive staleness
        window, or one already completed checkpoint, the timer runs now.
        """
        if self.checkpoint_max_staleness_seconds <= 0:
            return False
        probe = self._heavy_task_probe
        if probe is None:
            return False
        key = (str(user_id), str(session_id))
        with self._lock:
            completed_at = self._checkpoint_completed_at.get(key)
        if completed_at is None:
            return False
        try:
            busy = bool(probe(key[0], key[1]))
        except Exception:
            logger.debug(
                "Heavy task probe failed; checkpoint will run now", exc_info=True,
            )
            return False
        if not busy:
            return False
        return (time.monotonic() - completed_at) < self.checkpoint_max_staleness_seconds
```

在 `_snapshot_agent_locked` 的成功返回前记录时间戳（现有代码：

```python
            logger.info(
                "workspace checkpoint completed session=%s reason=%s duration_ms=%.1f commit_ms=%.1f discarded=%s",
                session_id, reason, (time.perf_counter() - started) * 1000.0,
                (time.perf_counter() - commit_started) * 1000.0, not bool(result),
            )
            return result
```

改为在 `return result` 之前插入）：

```python
            if result:
                with self._lock:
                    self._checkpoint_completed_at[
                        (str(user_id), str(session_id))
                    ] = time.monotonic()
            return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_store.py -q
```

Expected: 新文件全部 PASS；`test_workspace_store.py` 全绿（行为未变）。

- [ ] **Step 5: Commit**

```bash
git add web/workspace_store.py tests/test_workspace_checkpoint_deferral.py
git commit -m "perf(workspace): add heavy-task checkpoint deferral decision"
```

---

### Task 2: 定时器延后与重排

**Files:**
- Modify: `web/workspace_store.py`（`_checkpoint_timer`，约 `:3631-3678`）
- Test: `tests/test_workspace_checkpoint_deferral.py`（追加）

- [ ] **Step 1: Write the failing tests**

在 `tests/test_workspace_checkpoint_deferral.py` 追加：

```python
def _install_counter(store):
    calls = []

    def _fake_snapshot(*args, **kwargs):
        calls.append(kwargs.get("reason"))
        return {}

    store._snapshot_agent_locked = _fake_snapshot
    return calls


def _cancel_timers(store, key):
    timer = store._checkpoint_timers.pop(key, None)
    if timer is not None:
        timer.cancel()


def test_timer_defers_and_rearms_while_busy(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[key] = time.monotonic()
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.defer", generation=0)
        assert calls == []
        assert key in store._checkpoint_timers
    finally:
        _cancel_timers(store, key)


def test_timer_runs_when_stale_even_if_busy(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store.set_heavy_task_probe(lambda _u, _s: True)
    store._checkpoint_completed_at[key] = (
        time.monotonic() - store.checkpoint_max_staleness_seconds - 5.0
    )
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.stale", generation=0)
        assert calls == ["test.stale"]
    finally:
        _cancel_timers(store, key)


def test_timer_runs_when_probe_idle(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    calls = _install_counter(store)
    store.set_heavy_task_probe(lambda _u, _s: False)
    store._checkpoint_completed_at[key] = time.monotonic()
    try:
        store._checkpoint_timer(user["id"], case.id, agent, "test.idle", generation=0)
        assert calls == ["test.idle"]
    finally:
        _cancel_timers(store, key)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
```

Expected: 新增 3 个用例 FAIL（`test_timer_defers_and_rearms_while_busy` 里 `calls == ["test.defer"]`），其余 PASS。

- [ ] **Step 3: Implement the timer integration**

在 `_checkpoint_timer` 的第一个 `with self._lock:` 块之后、`work_lock = self._checkpoint_work_lock(...)` 之前插入：

```python
        if self._should_defer_checkpoint(user_id, session_id):
            with self._lock:
                latest_generation = self._checkpoint_generations.get(key, 0)
                retry = threading.Timer(
                    DEFER_RETRY_SECONDS,
                    self._checkpoint_timer,
                    args=(user_id, session_id, agent, reason, operation, latest_generation),
                )
                retry.daemon = True
                self._checkpoint_timers[key] = retry
                retry.start()
            logger.debug(
                "workspace checkpoint deferred session=%s reason=%s",
                session_id, reason,
            )
            return
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py tests/test_workspace_store.py tests/test_workspace_frontend.py -q
```

Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add web/workspace_store.py tests/test_workspace_checkpoint_deferral.py
git commit -m "perf(workspace): defer scheduled checkpoints while a heavy case task runs"
```

---

### Task 3: server 接线

**Files:**
- Modify: `web/server.py`（`create_app` 内 `workspace_store = WorkspaceStore(...)` 之后，约 `:320`）
- Test: `tests/test_workspace_checkpoint_deferral.py`（追加）

- [ ] **Step 1: Write the failing test**

追加：

```python
def test_create_app_wires_heavy_task_probe(tmp_path):
    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "server-runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    store = app.extensions["brachybot_workspace_store"]
    assert store._heavy_task_probe is not None
    assert store._heavy_task_probe("missing-user", "0" * 32) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py::test_create_app_wires_heavy_task_probe -q
```

Expected: FAIL（`assert None is not None`）。

- [ ] **Step 3: Implement the wiring**

在 `web/server.py` 的 `workspace_store = WorkspaceStore(config.get("runtime_dir"))` 之后插入（`_case_has_running_chat_task` 是模块级函数；`brachybot_chat_tasks` 由 `register_planning_routes` 注册，所以必须调用时查找）：

```python
    workspace_store.set_heavy_task_probe(
        lambda user_id, session_id: _case_has_running_chat_task(
            app.extensions.get("brachybot_chat_tasks"), user_id, session_id
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_chat_tasks.py tests/test_workspace_server_recovery_indicator.py tests/test_workspace_lease_ux.py -q
```

Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add web/server.py tests/test_workspace_checkpoint_deferral.py
git commit -m "perf(server): wire chat-task probe into checkpoint deferral"
```

---

### Task 4: 回归与端到端验收

**Files:**
- 无代码改动（除上三个任务外）

- [ ] **Step 1: 运行完整回归集**

```bash
env -u BRACHYBOT_API_KEY ~/.conda/envs/brachytherapy/bin/python -m pytest \
  tests/test_workspace_store.py tests/test_workspace_frontend.py \
  tests/test_chat_tasks.py tests/test_chat_case_resources_wait.py \
  tests/test_workspace_lease_ux.py tests/test_workspace_server_recovery_indicator.py \
  tests/test_workspace_auth.py tests/test_public_deployment.py -q
```

Expected: 全部 PASS（`test_workspace_auth.py` 必须在无 `BRACHYBOT_API_KEY` 的环境下跑，否则是已知的环境性 401）。

- [ ] **Step 2: 重启服务器并复现一次规划**

```bash
ps -eo pid,cmd | grep '[w]eb/server.py'   # 记录旧 pid 后按你的启动方式重启
grep -n 'Step 3/5\|Step 4/5' .runtime/logs/server.log | tail -4
```

在 UI 上用**同一个病例、同一参数**重跑规划；记录 `Step 3/5` 与 `Step 4/5` 的时间戳。

- [ ] **Step 3: 统计窗口内检查点数量并对比**

```bash
~/.conda/envs/brachytherapy/bin/python - <<'PY'
import re
from pathlib import Path
lines = Path('.runtime/logs/server.log').read_text().splitlines()
start = end = None
for i, line in enumerate(lines):
    if 'Step 3/5' in line:
        start = i
    if start is not None and 'Step 4/5' in line:
        end = i
        break
window = lines[start:end] if start is not None else []
started = [l for l in window if 'checkpoint started' in l]
print('steps:', lines[start][:30] if start is not None else 'n/a', '->', lines[end][:30] if end else 'n/a')
print('checkpoints in window:', len(started))
print('request.completed:', sum('request.completed' in l for l in started))
PY
```

Expected（对照 2026-09-16 16:40 基线：Step 3 = 160.1s，20 次检查点 / 17 次 `request.completed`）：窗口检查点 ≤3 次，Step 3 墙钟明显下降。

- [ ] **Step 4: 校验结果与 UI 功能未变**

对照改动前的规划结果（同一病例）：`total_seeds`、`num_trajectories`、`v100/v150/v200/d90` 必须一致；UI 上确认：规划进度正常、聊天正常、切换病例后重新打开数据完整、重启服务器后病例可恢复（无缺失掩膜/剂量/粒子）。

- [ ] **Step 5: 验证回退开关（可选）**

以 `BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=0` 重启服务器，重跑一次规划，检查点数量应回到与基线相近的水平，证明一键回退有效。

---

## Self-Review

- **Spec 覆盖**：3.1 组件 → Task 1；3.2 调度集成 → Task 2；3.3 server 接线 → Task 3；3.4 日志 → Task 2 代码内 `logger.debug` + 现有日志不变；§5 测试计划 → Task 1/2/3；§6 验收 → Task 4；§7 回退 → Task 4 Step 5；§4 兼容性 → Task 1 的 probe None/env=0 用例 + 回归集 + flush 不受影响（flush 不经过 `_checkpoint_timer`，Task 2 未改该路径）。
- **占位符扫描**：无 TBD/TODO；每个代码步骤都给了完整代码与命令。
- **类型一致性**：`set_heavy_task_probe`、`_should_defer_checkpoint`、`_checkpoint_completed_at`、`checkpoint_max_staleness_seconds`、`DEFER_RETRY_SECONDS` 在三个任务中签名与命名一致；`_checkpoint_timer` 参数顺序 `(user_id, session_id, agent, reason, operation, generation)` 与现有实现一致。
