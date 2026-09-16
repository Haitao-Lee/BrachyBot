# 规划期间工作区检查点延后（Checkpoint Deferral）设计

- 日期：2026-09-16
- 状态：待评审
- 涉及：`web/workspace_store.py`、`web/server.py`、新增 `tests/test_workspace_checkpoint_deferral.py`
- 硬约束：**不破坏任何现有已正常工作的功能**；默认行为与现状一致；可一键回退。

## 1. 背景与证据

规划（`seed_planning`）在服务器内实测 160.1s（16:37:41.811 → 16:40:21.893），其中：

- `rule_based_optimizer` 143.9s + `coverage_repair` 13.6s（真实计算）；
- 同窗口内完成 **20 次全量 workspace checkpoint**（17 次 `reason=request.completed`，3 次规划自身的 `memory.store:*`），日志完成耗时合计 **78.2s**，其中 `artifacts encoded` 17.1s、`snapshot written` 16.3s；
- 每次检查点要遍历 442 个数组、重写约 30MB 快照，单次 3–6s。

同代码在独立回放中 `seed_planning` 仅 **70.8s**（今天、同机、同负载），证明差距来自进程内的持久化竞争，而非算法退化。

现状触发源：

- `after_request` 兜底钩子：任何非只读 POST/PUT/PATCH/DELETE 都排一次全量检查点（`web/server.py:991-1023`，reason=`request.completed`）；
- `memory` 持久化回调：`memory.store/<tool/message/ui_state>` 等（`web/server.py:587` → `agent_runtime/core.py:276-307`）。

已有的安全网（本设计依赖且不改动）：

- UI 状态有 250ms 防抖的 bridge writer（`save_snapshot_patch`）；
- 聊天记录走 `/api/sessions/*/messages` 的 patch 持久化；
- 任务结束由 `flush_agent_checkpoint("chat.task.finalized.background")` **同步**全量落盘（`web/routes/planning_routes.py:2625-2650`）；
- "病例有重计算在跑"的现成信号：`_case_has_running_chat_task()`（`web/server.py:181`），缓存维护已在用；
- 忙时跳过先例：hydration 期间钩子 defer（`web/server.py:1010`）；
- 调度自带 0.75s 防抖、代际淘汰、非阻塞重试（`web/workspace_store.py:3590-3678`）。

## 2. 目标与非目标

目标：

1. 重计算运行期间不再连续做全量检查点，回收被持久化占用的墙钟（预期 160s 窗口内 20 → 2~3 次，节省约 50–60s）；
2. 所有触发源（`request.completed`、`memory.store:*`、`operation.checkpoint`）统一受益；
3. 保证最终结果与现有持久化语义不变（结束必 flush；空闲行为不变）。

非目标（二期再议）：

- 增量快照 / 只写变更键；
- 空闲期"无变更不落盘"的 dirty 检查（可消除空闲 ~6 次/分钟空转，但需汇总 conversation/tool_results/ui_state revision，风险更高）；
- 修改规划算法、参数、快照 schema、revision/租约语义。

## 3. 设计

### 3.1 组件

`WorkspaceStore` 新增：

1. `heavy_task_probe: Optional[Callable[[str, str], bool]]`
   - 由 server 注入；签名 `(user_id, session_id) -> bool`；未注入时为 `None`。
2. `checkpoint_max_staleness_seconds: float`
   - 默认 60，读取环境变量 `BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS`；非法值回退默认并记 `warning`；`<=0` 表示关闭延后（完全恢复现状）。
3. `_checkpoint_completed_at: Dict[Tuple[str, str], float]`
   - 每个 (user, session) 最近一次**成功完成全量检查点**的 `time.monotonic()`；在 `_snapshot_agent_locked` 成功提交（非 discard）后更新；`flush_agent_checkpoint` 走同一路径，同样更新；读写均在 `self._lock` 下。
4. `_should_defer_checkpoint(user_id, session_id) -> bool`（可单独测试）
   - `probe is None` → `False`（保持现状）；
   - `staleness <= 0` → `False`；
   - 无 `_checkpoint_completed_at` 记录 → `False`（保证"从未落盘"时先落一次，再开始延后）；
   - `probe(user, session)` 为真且 `now - completed_at < staleness` → `True`；否则 `False`；
   - probe 抛异常 → 记 `debug` 日志并返回 `False`（失败开放，不影响持久化）。

### 3.2 调度集成

在 `_checkpoint_timer`（`web/workspace_store.py:3631`）的代际校验之后、尝试获取 `work_lock` 之前插入：

```text
if self._should_defer_checkpoint(user_id, session_id):
    logger.debug("workspace checkpoint deferred session=%s reason=%s", ...)
    # 以“最新代际”重新排一个短定时器，避免复活过期工作
    with self._lock:
        latest_generation = self._checkpoint_generations.get(key, 0)
        self._checkpoint_timers[key] = threading.Timer(DEFER_RETRY_SECONDS,
            self._checkpoint_timer,
            args=(user_id, session_id, agent, reason, operation, latest_generation))
        ...start...
    return
```

- `DEFER_RETRY_SECONDS = 3.0` 常量，不新增环境变量；
- 严格遵守"最新代际"规则（与现有 retry 分支一致），过期代际仍会被丢弃；
- 超陈旧上限后（即使任务仍在跑）照常落一次并刷新 `_checkpoint_completed_at`，因此最坏丢失窗口 ≤ staleness。

### 3.3 server 接线

`web/server.py` 创建 store 处（`:320`）之后，懒查找扩展，避免注册顺序问题：

```python
workspace_store.set_heavy_task_probe(
    lambda user_id, session_id: _case_has_running_chat_task(
        app.extensions.get("brachybot_chat_tasks"), user_id, session_id
    )
)
```

（`brachybot_chat_tasks` 在 `register_planning_routes` 中注册，故必须调用时查找。）

### 3.4 日志与度量

- 延后：每次 `logger.debug`；若本次落盘是被"陈旧上限"强制触发的（probe 仍为忙），记一条 `logger.info` 并带 `staleness_s` 与 `reason`，供端到端验收；
- 现有 `checkpoint started/completed` 日志格式不变，验收用计数对比。

## 4. 兼容性与"不破坏功能"保证

1. **未注入 probe（测试、CLI、独立工具）**：`_should_defer_checkpoint` 恒为 `False`，行为与当前逐条路径一致；
2. **`flush_agent_checkpoint` / `save_snapshot_patch` / `save_agent_results_patch` / `discard_agent_checkpoint` 不经过 `_checkpoint_timer`**，完全不受影响；任务结束的 `chat.task.finalized.background` 同步落盘保持不变；
3. **空闲、切换病例、租约、删除、revision/409、hydration 语义**均不变；缓存淘汰/过期路径已有"运行中任务不淘汰"保护，延后只影响其调度时机，不影响最终落盘；
4. **规划结果零影响**：不触碰 `plans/*`、`tool_factory/seed_plan/*`；结果 hashes/指标应与现状一致；
5. **回滚开关**：`BRACHYBOT_CHECKPOINT_MAX_STALENESS_SECONDS=0` 即恢复现状，无需回滚代码；
6. **控制面调度路径逐条核对**：`agent.cache_evicted`/`cache_expired` 只会发生在"无运行中任务"的病例（已有 `_agent_has_running_task` 保护），probe 为假不延后；`agent.cache_dropped`（切换病例）与 `structures.traversability_changed.full_checkpoint` 等若恰逢重计算，最坏延后 ≤60s，任务仍持有 agent 且结束时 flush；`workspace.hydration.reconciled` 发生在 ready 阶段，正常无任务在跑；
7. 与现有未提交在制品解耦：本改动单独提交，不夹带其他 WIP。

## 5. 测试计划

新增 `tests/test_workspace_checkpoint_deferral.py`：

1. probe 未注入 → 定时器立即执行（与现状一致）；
2. probe 忙 + 已有落盘记录且未超上限 → 不执行，重排定时器；
3. probe 忙但陈旧超过上限 → 执行一次；
4. probe 忙 + 无落盘记录 → 先执行一次；
5. probe 抛异常 → 执行（失败开放）；
6. `flush_agent_checkpoint` 在忙时仍同步完成（不受延后影响）；
7. `MAX_STALENESS=0` → 不延后；
8. 成功后 `_checkpoint_completed_at` 被刷新（再次调度立即执行或按新时间延后）。

实现说明：为避免线程计时抖动，测试直接调用 `_checkpoint_timer`（同步）并断言快照 revision/`_checkpoint_completed_at`，必要时 monkeypatch `_snapshot_agent_locked` 计数。

回归集（必须全绿）：

- `tests/test_workspace_store.py`（检查点主体）
- `tests/test_workspace_frontend.py`（`flush_agent_checkpoint` 契约等）
- `tests/test_chat_tasks.py`、`tests/test_chat_case_resources_wait.py`
- `tests/test_workspace_lease_ux.py`、`tests/test_workspace_server_recovery_indicator.py`
- 服务器接线单测：注入后 `_should_defer_checkpoint` 能命中 `_case_has_running_chat_task`

## 6. 端到端验收（服务器内）

同一病例、同一参数重跑规划，采集：

1. Step 3 墙钟（`Step 3/5` → `Step 4/5` 日志时间差）；
2. 窗口内 `checkpoint started` 计数及 `request.completed` 次数；
3. 结果 hashes（`trajectory_*`、`dose_*`、`seed_plan_serialized`、`verified_needle_geometry`）与 `v100/v150/v200/d90` 与改动前一致；
4. UI 侧正常：规划进度、聊天、切换病例、重启恢复均有正确数据（无缺失）。

通过标准：检查点数显著下降（目标 ≤3 次/160s），Step 3 墙钟下降；所有 hashes/指标不变；回归测试全绿。

## 7. 风险与回退

| 风险 | 缓解 |
|---|---|
| 崩溃时丢失最多 60s 中间态 | 上限可调小；最终 flush 保证结果不丢；`MAX_STALENESS=0` 可关闭 |
| probe 误判（任务已结束仍为忙） | probe 是现有权威信号；probe 异常按"不延后"处理 |
| 延后期间删除/切换病例 | 删除走 `discard_agent_checkpoint`；切换由任务持有 agent 并在 finalize flush |
| 定时器堆积/复现代际 | 复用现有"最新代际 + 0.75s 防抖 + 单 work_lock"规则 |

## 8. 交付物

1. 代码改动（两个文件）+ 新增测试文件；
2. 验收报告：改动前后 Step 3 墙钟、检查点计数、结果 hashes 对照；
3. 与用户既有 WIP 分开的独立提交（署名 Haitao-Lee）。
