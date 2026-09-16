# 忙时检查点合并 + UI 桥侧车持久化 + 规划归因 设计

- 日期：2026-09-16
- 状态：待评审
- 涉及：`web/workspace_store.py`、`web/routes/planning_routes.py`、`web/server.py`、`plans/performance.py` + 测试
- 硬约束：不破坏现有功能；默认行为在无重任务、无新文件时与现状一致；可回退。

## 1. 背景与证据（2026-09-16 实测）

1. 规划期间检查点延后已生效（17:51 窗口 20 → 2 次，均完成）。
2. 新发现的浪费：**导板阶段（同一 chat 任务仍在跑）21 次检查点启动、0 次完成、20 次被取消**。原因：UI 持续 POST → `after_request` 每次调用 `schedule_agent_checkpoint` → 每次 bump generation → 正在准备的快照被判 stale 丢弃；30MB 重写全部白做，并让 UI 请求 5–18s、浏览器出现"连接中断"（任务日志可重连，数据不丢，但体验差）。
3. `POST /api/workspace/state` 每次都会经 `_flush_ui_bridge_checkpoint` → `save_snapshot_patch` **整份重写 snapshot.json（约 30MB）并 bump revision**（日志出现 7.6s → 409 冲突）。
4. 规划绝对墙钟受机器竞争影响 2–3x（独立回放 51s vs 服务器内 177s），当前日志无法直接归因（缺少 loadavg / CPU 时间）。

## 2. 目标 / 非目标

目标：
1. **不让新的常规调度取消"在飞"的快照**；被跳过的变更以"合并跟进"方式补一次，保证最终持久化不丢、不重复风暴。
2. **UI 桥状态改为小侧车文件**（原子写），不再为 UI 事件重写 30MB；读取端保持向后兼容（旧工作区无侧车时回退快照内容）。
3. `[planning_latency]` 增加机器竞争归因字段（loadavg、进程 CPU 时间、平均并行度、活动线程数）。

非目标：
- 不改 `snapshot.json` schema；不改 revision/租约语义；不改规划算法；不做增量快照（后续可评估）。
- 不改 `flush_agent_checkpoint`（任务结束/控制面必须同步）。

## 3. 设计

### A. 检查点合并（`web/workspace_store.py`）

新增（`__init__`，均受 `self._lock` 保护）：
- `_checkpoint_inflight: Dict[Tuple[str, str], int]`（值=在飞快照启动时的代际）
- `_checkpoint_dirty: Dict[Tuple[str, str], Dict[str, Any]]`（值=最新一次被合并的调度载荷）

`schedule_agent_checkpoint`：
- 在现有 `with self._lock:` 内先判断：`_checkpoint_inflight[key]` 存在（值为在飞快照启动时的代际）**且当前代际与之相等** → 合并：`_checkpoint_dirty[key] = {"agent", "reason", "operation"}`（保留最新一次调度的载荷），`logger.debug("workspace checkpoint coalesced ...")`，**直接返回**（不 bump generation、不动定时器）。
- 一旦有外部写入者 bump 了代际（如 `save_agent_results_patch` 等部分写入者、flush、discard），说明在飞快照已失效：后续调度**回到原有路径**（取消旧定时器、bump 代际、按载荷排新定时器），与改动前语义一致，避免吞掉调用方显式排队的全量检查点。
- 在飞快照收尾时（`finally`，持锁）：若存在合并载荷且代际未变 → 重放该载荷（`reason` 只追加一次 `.coalesced`，使用捕获的 agent/operation，异常只记 warning 不掩盖原异常）；若代际已变 → 丢弃更旧的载荷并记 debug（由更新的写入者负责持久化）。重放与代际检查在同一临界区内完成。

`_snapshot_agent_locked`（wrapper，原主体改名为 `_snapshot_agent_locked_inner`）：
- 在开头代际早退分支之后，`with self._lock:` 记 `generation_at_entry` 并标记 `_checkpoint_inflight[key] = generation_at_entry`；
- 外层 `try/finally` 包裹 inner 调用：`finally` 中在同一临界区内清 inflight、弹出合并载荷，若代际未变则重放（用捕获的 agent/operation，`reason` 只追加一次 `.coalesced`，排程异常只记 warning）；代际已变则丢弃更旧载荷并记 debug。
- 现有 `_CheckpointSuperseded` / 丢弃语义保持不变（flush/discard 仍 bump generation 并可取消在飞快照）。

`flush_agent_checkpoint` / `discard_agent_checkpoint`：
- 在各自 `with self._lock:` 内 `_checkpoint_dirty.pop(key, None)`（flush 是权威写入，无需跟进；discard 是删除）。
- inflight 不手动清理，由运行中的任务在 finally 清理。

语义：
- 在飞期间所有常规触发（`request.completed`、`memory.store:*`、`operation.checkpoint`、UI patch 等）被合并为"1 次跟进"；任务结束的 flush 仍同步落盘且不再触发多余跟进。
- 崩溃最坏丢失窗口不变（≤ 陈旧上限/任务结束 flush）。

### B. UI 桥侧车（`workspace_store.py` + `planning_routes.py` + `server.py`）

新增 store 方法：
- `save_ui_bridge(user_id, session_id, bridge, *, reason="ui.bridge") -> None`
  - `get_session` 校验所有权；路径 `workspace_root(user_id, session_id)/ui_bridge.json`；内容 `{**bridge, "reason": ..., "saved_at": time.time()}`；用现有 `_atomic_json` 原子写；失败抛 `WorkspaceError`（调用方按现状记 warning）。
  - 不 bump revision、不遍历数组、不动 snapshot.json。
- `load_ui_bridge(user_id, session_id) -> Dict[str, Any]`
  - 文件不存在/解析失败/非 Mapping → `{}`；否则返回 dict（含 `saved_at`）。

`_flush_ui_bridge_checkpoint`（planning_routes.py:1030）：
- `save_snapshot_patch({"ui": {"bridge": bridge}})` → `store.save_ui_bridge(user_id, selected, bridge, reason=reason)`；异常处理保持。

读取端（唯一读取点在 `web/server.py:583`）：
- 启动/恢复时：`snapshot_bridge = snapshot.ui.bridge or {}`；`sidecar = store.load_ui_bridge(...)`；
- 选 `saved_at` 更新者（缺失视为最旧）；`sidecar.saved_at > snapshot_bridge.updated_at` 时用 sidecar，否则用 snapshot。旧工作区无侧车行为不变。

清理：侧车位于病例目录，随病例删除/回收站一起处理，无需额外逻辑（实现时用现有 `_safe_workspace_child` 校验路径）。

### C. 规划归因（`plans/performance.py`）

`collect_planning_latency` 内：
- 开始记录：`os.getloadavg()`、`time.process_time()`、`threading.active_count()`；
- 结束记录同样值，写入 `metadata['latency_profile']['contention']`：
  ```python
  {
    "loadavg_1m_start": float, "loadavg_1m_end": float,
    "process_cpu_seconds": float,    # process_time 差
    "wall_seconds": float,
    "avg_parallelism": float,        # cpu/wall，>1 表示多核忙
    "threads_start": int, "threads_end": int,
  }
  ```
- `[planning_latency]` 日志追加 `wall=... cpu=... parallelism=... load=...`，保持原有 `total_seconds/nested_timings` 不变。
- 纯观测，不改任何计算/返回。

## 4. 兼容性与回退

1. A：无在飞快照时行为与现状一致；generation 仍由 flush/discard 推进；现有测试（含 superseded/discard/orphan 用例）应保持通过。
2. B：旧工作区（无侧车）读取回退快照；写入端只改一个调用点；快照中的 `ui.bridge` 可能停留在切换前最后一次，但读取以较新者为准，语义不变。
3. C：仅日志/metadata 增字段；现有 `test_planning_latency_profile.py` 断言需保持通过。
4. 回退：A/B 可独立回滚（B 改回 `save_snapshot_patch` 一行）；C 无副作用。

## 5. 测试计划

A（`tests/test_workspace_checkpoint_deferral.py` 或新文件）：
- 在飞期间 `schedule_agent_checkpoint` 不 bump generation、不替换定时器、置 dirty；
- 快照完成后 dirty 触发一次合并跟进（monkeypatch `_snapshot_agent_locked` 计数）；
- `flush_agent_checkpoint` 清理 dirty 且不产生跟进；
- 现有 superseded/cancelled 用例仍通过。

B（`tests/test_workspace_store.py` 或新文件 + 路由测试）：
- `save_ui_bridge`/`load_ui_bridge` 往返、缺失回退 `{}`、非法 JSON 回退 `{}`、原子写不产生临时残留；
- 恢复优先级：侧车新于快照 → 用侧车；侧车旧/无 → 用快照（可用 `create_app` + 恢复路径或直接单测选择函数，若抽成小函数）；
- `_flush_ui_bridge_checkpoint` 走侧车（集成：monkeypatch store 断言调用）。

C（`tests/test_planning_latency_profile.py`）：
- `contention` 字段存在且为数值；不影响 `nested_timings`/返回值/异常语义。

回归：`tests/test_workspace_store.py`、`test_workspace_frontend.py`、`test_workspace_checkpoint_deferral.py`、`test_chat_tasks.py`、`test_workspace_auth.py`、`test_public_deployment.py`。

## 6. 验收

1. 服务器内规划：导板/长任务阶段的 `checkpoint started` 不再出现"连续启动-取消"风暴（`cancelled stale` 显著下降），checkpoint 能完成；
2. UI 请求（`/api/workspace/state`）不再出现 5–9s 级别（可对比 Slow request 日志）；
3. `[planning_latency]` 新增归因字段可读：安静窗口 `avg_parallelism` 高、load 低；繁忙窗口 load 高可解释墙钟；
4. 结果 hashes/指标不变；重启后 UI 桥状态恢复正确（打开旧病例、新病例、删除病例各验证一次）。

## 7. 风险

| 风险 | 缓解 |
|---|---|
| dirty 跟进丢失（进程崩溃） | 任务结束 flush + 陈旧上限仍兜底；跟进只是减少丢失窗口 |
| 侧车与快照桥数据不一致 | 读取按 `saved_at/updated_at` 取新；旧数据回退兼容 |
| 侧车被误清理 | 放在病例目录、用 `_safe_workspace_child`；随病例生命周期管理 |
| `_snapshot_agent_locked` 结构改动引入回归 | 外层 try/finally 最小化改动 + 现有全套检查点测试回归 |
