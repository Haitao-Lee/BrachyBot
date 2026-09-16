# Checkpoint Coalescing + UI Bridge Sidecar + Planning Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ①在飞快照不再被常规调度取消（忙时合并为一次跟进）；②UI 桥状态改为小侧车文件，不再为 UI 事件重写 30MB 快照；③规划延迟日志加入 loadavg/CPU 时间归因。

**Architecture:** A. `WorkspaceStore` 增加 `_checkpoint_inflight/_checkpoint_dirty`，`schedule_agent_checkpoint` 在飞期间只置 dirty，快照收尾时补一次合并跟进；B. 新增 `save_ui_bridge/load_ui_bridge` 侧车 + 恢复时按时间取新；C. `plans/performance.py` 记录并输出竞争上下文。

**Tech Stack:** Python 3.12、Flask、pytest、`~/.conda/envs/brachytherapy/bin/python`。

**Spec:** `docs/superpowers/specs/2026-09-16-checkpoint-coalescing-ui-bridge-design.md`

**运行约定:** pytest 在仓库根 `<workspace>/BrachyBot` 执行；dirty 工作树中有大量无关 WIP，实施者只改本任务文件、不要回滚任何现有修改、不要执行任何 git 写命令（提交由控制者选择性拣选）。

**回退:** A/B 可独立回滚（B 改回 `save_snapshot_patch` 一行）；C 仅日志。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `web/workspace_store.py`（修改） | inflight/dirty、合并跟进、侧车读写 |
| `web/routes/planning_routes.py`（修改） | `_flush_ui_bridge_checkpoint` 改走侧车 |
| `web/server.py`（修改） | 恢复时按时间选择快照桥/侧车桥（新增模块级 helper） |
| `plans/performance.py`（修改） | contention 归因字段 |
| `tests/test_workspace_checkpoint_deferral.py`（追加） | A 的测试 |
| `tests/test_ui_bridge_sidecar.py`（新建） | B 的测试 |
| `tests/test_planning_latency_profile.py`（追加） | C 的测试 |

---

### Task 1: 检查点合并（不取消在飞快照）

**Files:** Modify `web/workspace_store.py`（`__init__`、`schedule_agent_checkpoint`、`_snapshot_agent_locked` 拆分 + wrapper、`flush_agent_checkpoint`、`discard_agent_checkpoint`）；Append tests `tests/test_workspace_checkpoint_deferral.py`。

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workspace_checkpoint_deferral.py`:

```python
def test_schedule_during_inflight_coalesces(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    store._checkpoint_inflight[key] = True
    generation_before = store._checkpoint_generations.get(key, 0)
    store.schedule_agent_checkpoint(user["id"], case.id, agent, "test.inflight")
    assert store._checkpoint_generations.get(key, 0) == generation_before
    assert key not in store._checkpoint_timers
    assert store._checkpoint_dirty.get(key) is True


def test_inflight_completion_schedules_coalesced_followup(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)

    def _inner(*args, **kwargs):
        store.schedule_agent_checkpoint(user["id"], case.id, agent, "test.during")
        return {}

    store._snapshot_agent_locked_inner = _inner
    try:
        store._snapshot_agent_locked(user["id"], case.id, agent, reason="test.run")
        assert key not in store._checkpoint_inflight
        assert key not in store._checkpoint_dirty
        assert key in store._checkpoint_timers
        timer = store._checkpoint_timers[key]
        assert timer.args[3] == "test.run.coalesced"
    finally:
        _cancel_timers(store, key)
        store._snapshot_agent_locked_inner = None


def test_flush_clears_dirty(tmp_path):
    store, user, case, agent = _case(tmp_path)
    key = (user["id"], case.id)
    store._checkpoint_dirty[key] = True
    store._snapshot_agent_locked_inner = lambda *a, **k: {}
    try:
        store.flush_agent_checkpoint(user["id"], case.id, agent, "test.flush")
        assert key not in store._checkpoint_dirty
    finally:
        store._snapshot_agent_locked_inner = None
        _cancel_timers(store, key)
```

（`timer.args` 是 `threading.Timer` 的构造参数元组：`(user_id, session_id, agent, reason, operation, generation)`。）

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py -q
```
Expected: 3 个新用例 FAIL（`_checkpoint_inflight` 不存在 / `_snapshot_agent_locked_inner` 不存在 / dirty 未清）。

- [ ] **Step 3: Implement**

`__init__`（紧跟 `_checkpoint_completed_at` 初始化之后）新增：

```python
        # Coalesce checkpoint scheduling while a full snapshot is in flight:
        # a new schedule must not cancel the running write, and the skipped
        # mutation is replayed once as a follow-up after it completes.
        self._checkpoint_inflight: Dict[Tuple[str, str], bool] = {}
        self._checkpoint_dirty: Dict[Tuple[str, str], bool] = {}
```

`schedule_agent_checkpoint` 的 `with self._lock:` 块开头（`existing = ...` 之前）插入：

```python
            if self._checkpoint_inflight.get(key):
                self._checkpoint_dirty[key] = True
                logger.debug(
                    "workspace checkpoint coalesced session=%s reason=%s",
                    session_id, reason,
                )
                return
```

把现有 `_snapshot_agent_locked` 整体改名为 `_snapshot_agent_locked_inner`（内容不动），并新增 wrapper：

```python
    def _snapshot_agent_locked(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        *,
        reason: str = "agent.checkpoint",
        operation: Optional[Mapping[str, Any]] = None,
        checkpoint_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run one full snapshot and replay coalesced schedules afterwards."""
        if checkpoint_generation is not None:
            with self._lock:
                current_generation = self._checkpoint_generations.get(
                    (user_id, session_id), 0
                )
            if int(checkpoint_generation) != int(current_generation):
                logger.debug(
                    "workspace checkpoint skipped stale session=%s reason=%s generation=%s current_generation=%s",
                    session_id, reason, checkpoint_generation, current_generation,
                )
                return {}
        key = (str(user_id), str(session_id))
        with self._lock:
            self._checkpoint_inflight[key] = True
        try:
            return self._snapshot_agent_locked_inner(
                user_id,
                session_id,
                agent,
                reason=reason,
                operation=operation,
                checkpoint_generation=checkpoint_generation,
            )
        finally:
            with self._lock:
                self._checkpoint_inflight.pop(key, None)
                dirty = self._checkpoint_dirty.pop(key, None)
            if dirty:
                logger.info(
                    "workspace checkpoint coalesced follow-up session=%s reason=%s",
                    session_id, reason,
                )
                self.schedule_agent_checkpoint(
                    user_id, session_id, agent, f"{reason}.coalesced",
                )
```

`flush_agent_checkpoint` 的 `with self._lock:` 内、`generation = ...` 之前加：

```python
            self._checkpoint_dirty.pop(key, None)
```

`discard_agent_checkpoint` 的 `with self._lock:` 内同样加：

```python
            self._checkpoint_dirty.pop(key, None)
```

- [ ] **Step 4: Run tests**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_workspace_checkpoint_deferral.py tests/test_workspace_store.py tests/test_workspace_frontend.py -q
```
Expected: 全绿（含既有 superseded/discard/orphan 用例）。

- [ ] **Step 5 (do NOT do): Commit — controller handles it.**

---

### Task 2: UI 桥侧车持久化

**Files:** Modify `web/workspace_store.py`（新增两个方法）、`web/routes/planning_routes.py`（`_flush_ui_bridge_checkpoint`）、`web/server.py`（新增 helper + 恢复处调用）；Create `tests/test_ui_bridge_sidecar.py`。

- [ ] **Step 1: Write the failing tests**

新建 `tests/test_ui_bridge_sidecar.py`：

```python
"""UI bridge sidecar persistence tests (no full-snapshot rewrites)."""

from __future__ import annotations

from web.server import _select_case_bridge
from web.workspace_store import WorkspaceStore


def _store(tmp_path):
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("bridge_user", "hash")
    case = store.create_session(user["id"], "Bridge case")
    return store, user, case


def test_ui_bridge_roundtrip(tmp_path):
    store, user, case = _store(tmp_path)
    store.save_ui_bridge(
        user["id"],
        case.id,
        {"state": {"viewer": {"axial": 12}}, "events": [{"type": "x"}],
         "training": {}, "updated_at": 123.0},
        reason="ui.state_saved",
    )
    loaded = store.load_ui_bridge(user["id"], case.id)
    assert loaded["state"] == {"viewer": {"axial": 12}}
    assert loaded["events"] == [{"type": "x"}]
    assert loaded["reason"] == "ui.state_saved"
    assert float(loaded["saved_at"]) > 0


def test_ui_bridge_missing_returns_empty(tmp_path):
    store, user, case = _store(tmp_path)
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_ui_bridge_invalid_json_returns_empty(tmp_path):
    store, user, case = _store(tmp_path)
    root = store.workspace_root(user["id"], case.id, create=True)
    (root / "ui_bridge.json").write_text("{not json", encoding="utf-8")
    assert store.load_ui_bridge(user["id"], case.id) == {}


def test_select_case_bridge_prefers_newer_sidecar():
    snapshot = {"state": {"a": 1}, "updated_at": 100.0}
    sidecar = {"state": {"a": 2}, "saved_at": 200.0}
    assert _select_case_bridge(snapshot, sidecar)["state"] == {"a": 2}


def test_select_case_bridge_falls_back_to_snapshot():
    snapshot = {"state": {"a": 1}, "updated_at": 300.0}
    sidecar = {"state": {"a": 2}, "saved_at": 200.0}
    assert _select_case_bridge(snapshot, sidecar)["state"] == {"a": 1}
    assert _select_case_bridge(snapshot, {})["state"] == {"a": 1}
    assert _select_case_bridge({}, {}) == {}


def test_flush_ui_bridge_uses_sidecar_writer(tmp_path):
    from web.routes import planning_routes

    calls = []

    class _Store:
        def save_ui_bridge(self, user_id, session_id, bridge, *, reason=""):
            calls.append((user_id, session_id, dict(bridge), reason))

        def save_snapshot_patch(self, *args, **kwargs):
            raise AssertionError("bridge flush must not rewrite the full snapshot")

    key = ("user-1", "case-1")
    planning_routes._UI_BRIDGE_CHECKPOINT_PENDING[key] = (
        _Store(), "user-1", "case-1", {"state": {"a": 1}}, "ui.state_saved",
    )
    try:
        planning_routes._flush_ui_bridge_checkpoint(key)
    finally:
        planning_routes._UI_BRIDGE_CHECKPOINT_PENDING.pop(key, None)
        planning_routes._UI_BRIDGE_CHECKPOINT_TIMERS.pop(key, None)
    assert calls == [("user-1", "case-1", {"state": {"a": 1}}, "ui.state_saved")]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_ui_bridge_sidecar.py -q
```
Expected: FAIL（`ImportError: _select_case_bridge` / `AttributeError: save_ui_bridge`）。

- [ ] **Step 3: Implement**

`web/workspace_store.py` 在 `set_heavy_task_probe` 之前新增：

```python
    def save_ui_bridge(
        self,
        user_id: str,
        session_id: str,
        bridge: Mapping[str, Any],
        *,
        reason: str = "ui.bridge",
    ) -> None:
        """Persist UI bridge telemetry without rewriting the case snapshot.

        High-frequency UI events (sliders, monitor status) belong to a small
        sidecar so a 30MB snapshot rewrite is not paid per event. The snapshot
        keeps its last bridge copy as a read-only fallback for older cases.
        """
        self.get_session(user_id, session_id)
        payload = dict(bridge) if isinstance(bridge, Mapping) else {}
        payload["reason"] = str(reason)
        payload["saved_at"] = time.time()
        root = self.workspace_root(user_id, session_id, create=True)
        _atomic_json(_safe_workspace_child(root, "ui_bridge.json"), payload)

    def load_ui_bridge(self, user_id: str, session_id: str) -> Dict[str, Any]:
        """Return persisted sidecar bridge state, or {} when absent/invalid."""
        try:
            self.get_session(user_id, session_id)
            root = self.workspace_root(user_id, session_id)
            path = _safe_workspace_child(root, "ui_bridge.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (WorkspaceError, OSError, ValueError, TypeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}
```

`web/routes/planning_routes.py` 的 `_flush_ui_bridge_checkpoint` 内：

```python
    store, user_id, selected, bridge, reason = item
    try:
        store.save_ui_bridge(user_id, selected, bridge, reason=reason)
    except WorkspaceNotFound:
        ...
```

（替换原来的 `store.save_snapshot_patch(...)` 调用；异常处理分支保持原样。）

`web/server.py` 模块级新增 helper（放在 `_case_has_running_chat_task` 附近）：

```python
def _select_case_bridge(snapshot_bridge: Any, sidecar_bridge: Any) -> dict:
    """Prefer the newest persisted UI bridge between snapshot and sidecar."""
    snapshot = snapshot_bridge if isinstance(snapshot_bridge, Mapping) else {}
    sidecar = sidecar_bridge if isinstance(sidecar_bridge, Mapping) else {}

    def _stamp(payload: Mapping[str, Any], field: str) -> float:
        try:
            return float(payload.get(field) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    if _stamp(sidecar, "saved_at") > _stamp(snapshot, "updated_at"):
        return dict(sidecar)
    return dict(snapshot)
```

`web/server.py:583` 处替换为：

```python
            bridge = _select_case_bridge(
                (hydrated_snapshot.get("ui") or {}).get("bridge") or {},
                workspace_store.load_ui_bridge(user["id"], resolved_session_id),
            )
```

（后续 `if isinstance(bridge, dict):` 块不变。`Mapping` 已在 server.py 导入；若未导入需补。）

- [ ] **Step 4: Run tests**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_ui_bridge_sidecar.py tests/test_workspace_store.py tests/test_workspace_frontend.py tests/test_workspace_server_recovery_indicator.py -q
```
Expected: 全绿。

- [ ] **Step 5 (do NOT do): Commit — controller handles it.**

---

### Task 3: 规划竞争归因

**Files:** Modify `plans/performance.py`；Append tests `tests/test_planning_latency_profile.py`。

- [ ] **Step 1: Write the failing test**

Append 到 `tests/test_planning_latency_profile.py`：

```python
def test_profile_records_contention_context():
    result = SimpleNamespace(success=True, metadata={})

    @collect_planning_latency
    def request():
        return result

    assert request() is result
    contention = result.metadata['latency_profile']['contention']
    for field in (
        'loadavg_1m_start', 'loadavg_1m_end', 'process_cpu_seconds',
        'wall_seconds', 'avg_parallelism', 'threads_start', 'threads_end',
    ):
        assert isinstance(contention[field], (int, float)), field
    assert contention['wall_seconds'] >= 0.0
    assert contention['avg_parallelism'] >= 0.0
    assert contention['threads_end'] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_planning_latency_profile.py -q
```
Expected: 新用例 FAIL（`KeyError: 'contention'`），其余通过。

- [ ] **Step 3: Implement**

`plans/performance.py`：

- 顶部 import 增加 `import os`、`import threading`；
- 新增 helper：

```python
def _loadavg_1m() -> float:
    try:
        return float(os.getloadavg()[0])
    except (OSError, AttributeError, ValueError):
        return 0.0
```

- `collect_planning_latency` 改为：

```python
def collect_planning_latency(function):
    @wraps(function)
    def run(*args, **kwargs):
        profile = {}
        token = _profile.set(profile)
        started = time.perf_counter()
        cpu_started = time.process_time()
        threads_started = threading.active_count()
        load_started = _loadavg_1m()
        try:
            result = function(*args, **kwargs)
            metadata = getattr(result, 'metadata', None)
            if isinstance(metadata, dict):
                wall = time.perf_counter() - started
                cpu = time.process_time() - cpu_started
                metadata['latency_profile'] = {
                    'total_seconds': wall,
                    'nested_timings': profile,
                    'contention': {
                        'loadavg_1m_start': load_started,
                        'loadavg_1m_end': _loadavg_1m(),
                        'process_cpu_seconds': cpu,
                        'wall_seconds': wall,
                        'avg_parallelism': (cpu / wall) if wall > 0 else 0.0,
                        'threads_start': threads_started,
                        'threads_end': threading.active_count(),
                    },
                }
            return result
        finally:
            wall = time.perf_counter() - started
            cpu = time.process_time() - cpu_started
            parallelism = (cpu / wall) if wall > 0 else 0.0
            logger.info(
                '[planning_latency] total_seconds=%.3f cpu_seconds=%.3f '
                'parallelism=%.2f load1=%.2f nested_timings=%s',
                wall, cpu, parallelism, _loadavg_1m(), profile,
            )
            _profile.reset(token)
    return run
```

- [ ] **Step 4: Run tests**

```bash
~/.conda/envs/brachytherapy/bin/python -m pytest tests/test_planning_latency_profile.py tests/test_planning_latency_equivalence.py -q
```
Expected: 全绿（既有并发隔离/异常恢复用例不受影响）。

- [ ] **Step 5 (do NOT do): Commit — controller handles it.**

---

### Task 4: 回归 + 端到端验收

- [ ] **Step 1: 回归集**

```bash
env -u BRACHYBOT_API_KEY ~/.conda/envs/brachytherapy/bin/python -m pytest \
  tests/test_workspace_checkpoint_deferral.py tests/test_ui_bridge_sidecar.py \
  tests/test_planning_latency_profile.py tests/test_planning_latency_equivalence.py \
  tests/test_workspace_store.py tests/test_workspace_frontend.py \
  tests/test_chat_tasks.py tests/test_chat_case_resources_wait.py \
  tests/test_workspace_lease_ux.py tests/test_workspace_server_recovery_indicator.py \
  tests/test_workspace_auth.py tests/test_public_deployment.py -q
```

- [ ] **Step 2: 服务器验收（用户执行）**

重启服务器（加载新代码）→ 重跑一次规划 + 导板，检查：

1. 长任务阶段不再出现连续 `checkpoint cancelled stale`；`checkpoint started` 能 `completed`；
2. `Slow request` 中不再出现 5–9s 的 `POST /api/workspace/state`（侧车生效）；
3. `[planning_latency]` 新字段可解释墙钟：安静窗口 `load1` 低；繁忙窗口 `load1` 高、`parallelism` 高；
4. 结果指标不变；打开旧病例/新病例/删除病例后 UI 桥状态恢复正常。

---

## Self-Review

- **Spec 覆盖**：§3A → Task 1；§3B → Task 2；§3C → Task 3；§5 测试 → 各任务；§6 验收 → Task 4；§4 兼容/回退 → 测试（无在飞时行为不变、旧工作区回退快照、C 仅增字段）+ 提交说明。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整代码与命令。
- **类型一致性**：`_checkpoint_inflight`/`_checkpoint_dirty`（Dict 键为 `(str, str)`）、`save_ui_bridge/load_ui_bridge`、`_select_case_bridge`、`contention` 字段命名在任务与测试间一致；`_snapshot_agent_locked` wrapper 保留原签名，`_snapshot_agent_locked_inner` 仅改名。
- **既有测试兼容**：wrapper 保留 stale-generation 早退语义（测试 `test_superseded_checkpoint_does_not_record_completion` 依赖）；`_checkpoint_timer`/defer 逻辑未动。
