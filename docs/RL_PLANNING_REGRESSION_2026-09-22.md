# 强化学习规划回归原因报告

- 日期：2026-09-22
- 病例：`CTzhouqun_20260912_130651.nii`（session `69cfb439e0f643ca890f9df74a86a505`，CTV 体积 238.17 cm³ / 142,533 体素）
- 触发提交：`7df40b5a7 fix(plans): align the RL search with a real objective; batched dose cache; reproducible greedy incumbent`（2026-09-22 18:52，RL 重写，`plans/reinforcement.py` 改动 1334 行）
- 结论一句话：**这次运行用了 `mode=rl`，而本病例历史上能成功的方案是 `mode=rule_based`；同时这次 RL 重写新增的"贪心热启动"在真正学习之前就耗尽了墙钟预算，还重复做了一遍剂量推理，导致 RL 0 回合、结果比规则优化大幅退化。**

---

## 1. 现象

用户反馈："之前这个 case 可以成功规划，现在规划十分钟都没成功，而且大幅减弱"。

| 项 | 之前成功方案 | 本次（2026-09-22 22:13） |
|---|---|---|
| 规划模式 | `rule_based` | **`rl`** |
| 针数 / 粒子数 | 24 针 / **181 粒子** | 24 针 / **57 粒子** |
| V100 | **≈90.3%**（达标） | 11.3% |
| D90 | — | 27.20 Gy |
| 计划评分 | — | 35/100 |
| RL 执行 | 不涉及 | 已中断（`wall_clock_budget`），**回合数 0/0/0，动作数 0** |
| 耗时 | 规划阶段约 16 min | `seed_planning` 614 s，整轮 988 s |

本次 RL 诊断（工具返回）：

```
执行状态: 已中断 (interrupted)
停止原因: 达到墙钟时间预算 (wall_clock_budget)
目标覆盖率 / 最佳覆盖率: 90.0% / 7.2%
最佳奖励: 0.0711
回合数（总 / 高层 / 低层）: 0 / 0 / 0
动作数 / 密集针道 / 密集粒子候选: 0 / 20 / 70
耗时 / 剂量缓存命中 / 未命中: 614.145 s / 80 / 70
```

---

## 2. 关键证据（日志）

日志位置：内测 `BrachyBot/.runtime/logs/server.log`（约 28k 行，覆盖 2026-09-16 起）、实时日志 `/tmp/brachybot_server.log`。

### 2.1 成功的 181 粒子方案全部来自 `rule_based`

```
server.log:14273  2026-09-18 19:25:05  Running seed planning (mode=rule_based)...
server.log:14445  2026-09-18 19:40:58  [optimal_plan] Final seed distribution: needles=24 ... max_seeds_per_needle=13
server.log:14451  2026-09-18 19:41:01  [seed_planning] Stored ... seed_plan=24 entries, total_seeds=181
server.log:15507  2026-09-18 21:57:58  (同上, 181)
server.log:16257  2026-09-19 16:02:16  (同上, 181)
```

### 2.2 全量日志里 `mode=rl` 只跑过两次，且都没成功

```
server.log:12366  2026-09-18 17:27:35  Running seed planning (mode=rl)...
server.log:27995  2026-09-22 22:13:55  Running seed planning (mode=rl)...   ← 本次
```

- 09-18 那次（旧 RL 代码）：密集评估撞墙钟只保留 14/20 条、56 个种子；层级扩展 depth 2 撞墙；基线评分撞墙 → RL 覆盖 **0.0000**，规则兜底 0.0302。
- 2026-09-21（"昨天"）**没有任何 RL 运行记录**。

### 2.3 本次运行的时间线与预算去向

| 时刻 | 事件 | 说明 |
|---|---|---|
| 22:13:55.8 | 加载模型，`Running seed planning (mode=rl)` | `max_wall_seconds=300` 起点 |
| 22:14:39.9 | 密集评估完成：20 轨迹 / 70 种子 | `:28029`，耗时约 44 s |
| 22:18:56.3 | **高层 episode 循环撞墙钟** | `:28095`，说明进入循环前 300 s 已耗尽 |
| 22:19:00.9 | 低层 episode 循环撞墙钟 | `:28096` |
| 22:19:01.6 | 触发规则兜底（RL 覆盖 0.0716 < 0.9） | `:28098` |
| 22:21:03.9 | 兜底完成，覆盖 0.0571，**未超过 RL，保留 RL 结果** | `:28137`（兜底 120 s 跑满） |
| 22:24:10.2 | 覆盖修复完成，0.0716 → 0.1132 | `:28166`（修复 186 s，自适应扩到 180 s） |

关键行：

```
server.log:28095  WARNING plans.reinforcement  [rl] Hierarchical RL episode loop reached its wall-clock budget
server.log:28096  WARNING plans.reinforcement  [rl] Low-level RL episode loop reached its wall-clock budget
           :28097  INFO  plans.reinforcement  [rl] seed-dose cache: 80 hits, 70 model evaluations, 182.13s uncached inference
```

密集评估结束后（22:14:39）到 RL 撞墙（22:18:56）共约 **257 s**；其中 `model_inference_seconds = 182.13 s`，对应 **70 次 DoseUNet 推理**。本次 RL **0 回合、0 动作**，因此这 70 次推理只能来自**贪心热启动的整组预取**。

---

## 3. 根因分析

### 3.1 直接原因：新增的"贪心热启动"耗尽 RL 预算，RL 一回合都没跑

`plans/reinforcement.py`（`7df40b5a7` 新增，旧代码不存在）：

- `reinforcement.py:1390-1394`：`greedy_enabled = rf_params.get("greedy_warm_start", True)`，默认开启；在进入 REINFORCE episode 循环**之前**调用 `_greedy_incumbent(best_group_idx, ...)`。
- `reinforcement.py:1348-1388`：`_greedy_incumbent` → `env.run_greedy(group_idx, device)`。
- `reinforcement.py:915-932`：`run_greedy` 默认 `restarts=3`，即做 3 遍贪心。
- `reinforcement.py:730-751`：`activate_group` 对所选组的**全部候选位置**调用 `prefetch_positions`。
- `reinforcement.py:269-302`：`prefetch_positions` 一次性批量跑 DoseUNet，写满 `seed_cache`。
- `reinforcement.py:934-986`：`_greedy_pass` 每放一个种子前，对掩码内**每个候选**调用 `evaluate_action_marginal`（`reinforcement.py:896-913` / `390-419`），每次都对全量体素做 `float32→float64` 转换与 DVH 计算。

这一整套（整组预取 + 3 遍贪心 × 每步遍历全部候选）全部发生在 episode 循环之前，不受任何预算约束。当 `max_wall_seconds=300` 被耗尽后，`reinforcement.py:1421-1428` 的高层循环墙钟检查立即触发，`actions_taken` 仍为 0 → **0 回合**，直接返回弱基线。

对比 `plans/utilizations.py`：`max_wall_seconds` 默认 300（`utilizations.py:4448-4456`），`candidate_limit=20`、`dense_seed_limit=40`、`max_hierarchy_depth=8`、`max_actions_per_episode=40`（`config/default_params.json`）。

### 3.2 时间膨胀：贪心预取**重复计算**了密集评估已有的剂量图

- 密集评估阶段：`utilizations.py:4565` 对每条轨迹的密集种子调用 `batch_seed_dose_calculation_dl`，把每颗种子的剂量图存进该轨迹的 `traj[2]/traj[3]`（结构见 `utilizations.py:4586`）。本次共 70 张。
- 贪心预取阶段：`prefetch_positions` **只查扁平的 `self.seed_cache`**（`reinforcement.py:277-282`），不会去复用 `traj[2]/traj[3]` 里已算好的密集剂量图——那条路径只有 `_lookup_seed_dose`（`reinforcement.py:242-267`）会走。
- 结果：本次密集评估算过的 70 张图在预取时又被算了一遍——**未命中数恰为 70，与密集种子总数一致**，`model_inference_seconds=182.13s`。密集段 70 张约 45 s，预取段 70 张约 182 s（后者还叠加了同期 workspace checkpoint / `/api/workspace/state` 的 GPU 争用）。

即：时间变长的直接来源是 **+182 s 的重复 DoseUNet 推理**，以及 3 遍贪心边际打分。

### 3.3 结构性原因：该病例需要 ~24 针，RL 的候选层上限远低于此

- 该 CTV 238 cm³，成功方案为 24 针 / 181 粒子（约 7.5 粒子/针）。
- RL 只能在该病例的层级候选池里放种子。最终 24 针中，覆盖修复新增了 19 针、21 粒子（`:640`：`added_needles=19, added_seeds=21`），可反推 **RL 返回的计划仅约 5 针**——RL 根本放不出足够的针/粒子，覆盖上限天然远低于 90%。
- `7df40b5a7` 新增的 `select_hierarchy_level`（`utilizations.py:4299-4329`）用 `coverage - 0.01 × 针数` 打分选层，会**在覆盖尚未达标时就偏向更少针数**的浅层组合。旧代码直接取最深一层（`hierarchical[-1]`）。这进一步压低了 RL 可用的针数/覆盖上限（在覆盖已接近目标时，用针数惩罚做取舍是合理的；但在未达标时应当以覆盖优先）。

### 3.4 触发因素：这次被路由到 `mode=rl`

- 工具默认是 `rule_based`（`tool_factory/seed_plan/seed_planning.py:65`），运行期还会提示 `Use mode='rule_based' (NOT 'rl')`（`agent_runtime/llm_runtime.py:1595-1597`）。
- 但本次 `planning_pipeline` 的入参是 `mode:"rl"`。需要单独排查是用户主动要求、还是"重新执行"复用了 09-18 那次失败 RL 遗留的 `plan_config.mode=rl`。
- 结论：**本病例用 RL 达不到目标，用 rule_based 可以**。这次"规划得这么烂"第一位是选了 RL。

### 3.5 下游兜底/修复不足以补救

- 规则兜底覆盖 0.0571 < RL 0.0716，被丢弃（`planning_pipeline.py` 的 `rule_based_fallback_is_strictly_better`）。
- 覆盖修复从 0.0716 只拉到 0.1132，且因为起点太差触发了自适应延长（60 s → 180 s），`added_needles=19/added_seeds=21`（平均约 1 粒子/针，效率极低），并额外增加约 120 s 耗时。

---

## 4. 新旧版本对照

| 维度 | 旧代码 `ccddd71c2`（09-21 及以前） | 新代码 `7df40b5a7`（09-22 18:52） |
|---|---|---|
| 贪心热启动 `greedy_warm_start` | **无** | 有，**默认开启** |
| 整组剂量预取 `prefetch_positions` | **无** | 有（对所选组全部候选） |
| `evaluate_action_marginal` 全量体素打分 | **无** | 有（3 restart × 每步全部候选） |
| 层级选择 | `hierarchical[-1]`（最深一层，覆盖优先） | `select_hierarchy_level`（`coverage - 0.01×针数`，偏向少针） |
| RL 预算是如何用的 | 密集评估后**直接进 episode**，剩余预算用于放种子 | 预算先被贪心预取/打分吃掉 → **0 回合** |
| 本次对应耗时结构 | RL 300 s + 兜底 120 s + 修复 62 s（未触发延长） | RL 257 s 空烧 + 兜底 122 s + 修复 186 s |

值得注意：仅比较"RL vs RL"，新代码（覆盖 0.0716 / 最终 0.1132）甚至略优于 09-18 的旧 RL（0.0000 / 0.0343）——但两者都远达不到 rule_based 的 0.903。因此**"变弱"主要是算法/模式变化造成，而非同一个 RL 被改差**；新 RL 的问题是"贵且无效"，且把失败暴露得更明显。

---

## 5. 修复建议

按优先级：

1. **恢复本病例的正确路径（立即可用）**：规划改用 `mode:"rule_based"`，可复现 24 针 / 181 粒子 / V100≈90%。同时排查为什么本次被路由到 `rl`（"重新执行"是否复用了旧的 rl 参数），必要时在 rerun 路径上强制/提示使用 rule_based。

2. **让剂量预取复用密集评估结果（省 ~182 s）**：在 `SeedPlacementReward.prefetch_positions` 命中缓存前，先对每颗候选调用 `_lookup_seed_dose(traj, ...)`，命中各轨迹已存的 `traj[2]/traj[3]` 密集剂量图；或在进入 `reinforcement_planning` 前，把密集剂量图预灌入 `seed_cache`。

3. **让贪心热启动预算感知（恢复 RL 有效学习）**：
   - 进入 `run_greedy` 前检查剩余预算，不足阈值直接跳过；
   - `_greedy_pass` 在每个候选打分、每次 restart 前检查 `deadline`（当前只在每放一个种子后检查，`reinforcement.py:960`）；
   - `restarts` 由 3 收敛到 1（或按剩余预算自适应）；
   - 更稳妥的做法：默认 `greedy_warm_start=False`（交互式路径），研究用再显式开启。

4. **修正选层策略**：`select_hierarchy_level` 的针数惩罚**仅在覆盖达标后**生效；未达标时应最大化覆盖（等价于旧的最深层优先），避免 RL 在达标前就自我限制针数。

5. **兜底/修复效率**：覆盖修复当前平均 ~1 粒子/针（`added_seeds=21 / added_needles=19`），需检查为什么加了针却几乎不放粒子（疑似针道候选/几何约束导致每针只能落 1 颗），否则延长预算也难补覆盖。

---

## 附录 A：关键代码位置

| 文件 | 位置 | 说明 |
|---|---|---|
| `plans/reinforcement.py` | `1390-1394` | `greedy_warm_start` 默认开启，在 episode 循环前调用 |
| `plans/reinforcement.py` | `1348-1388` | `_greedy_incumbent` |
| `plans/reinforcement.py` | `915-986` | `run_greedy`（restarts=3）/ `_greedy_pass` |
| `plans/reinforcement.py` | `730-751` | `activate_group` 整组预取 |
| `plans/reinforcement.py` | `269-302` | `prefetch_positions`（只查 `seed_cache`，不复用密集图） |
| `plans/reinforcement.py` | `242-267` | `_lookup_seed_dose`（可复用 `traj[2]/traj[3]`） |
| `plans/reinforcement.py` | `896-913` / `390-419` | `evaluate_action_marginal` / `evaluate_marginal` 全量体素打分 |
| `plans/reinforcement.py` | `1421-1428` | 高层循环墙钟检查 → `wall_clock_budget` |
| `plans/utilizations.py` | `4299-4329` | 新增 `select_hierarchy_level`（针数惩罚选层） |
| `plans/utilizations.py` | `4448-4456` | `max_wall_seconds` 截止时间 |
| `plans/utilizations.py` | `4563-4602` | 密集评估 + 剂量图入 `traj` |
| `tool_factory/seed_plan/planning_pipeline.py` | `4305-4440` | rl 分支、规则兜底、覆盖修复 |
| `config/default_params.json` | `rf_params` | `max_wall_seconds=300`、`fallback_max_wall_seconds=120`、`coverage_repair_seconds=60/扩展120/上限180` |

## 附录 B：原始日志摘录

```
# 密集评估
:502  [rl] interactive budget: wall=300.0s, candidates=20, dense-seeds-per-trajectory=40, actions-per-episode=40
:533  Dense evaluation retained 20 trajectories and 70 seed candidates
# RL 0 回合
:570  WARNING [rl] Hierarchical RL episode loop reached its wall-clock budget
:571  WARNING [rl] Low-level RL episode loop reached its wall-clock budget
:572  INFO  [rl] seed-dose cache: 80 hits, 70 model evaluations, 182.13s uncached inference
# 下游
:612  [rl] Rule-based fallback coverage 0.0571 did not strictly improve RL coverage 0.0716; retaining the RL result
:640  [coverage_repair] initial_coverage=0.0716 final_coverage=0.1132 added_needles=19 added_seeds=21 elapsed=186.13s
# 历史成功（rule_based）
:14445 [optimal_plan] Final seed distribution: needles=24 ... max_seeds_per_needle=13
:14451 [seed_planning] Stored ... seed_plan=24 entries, total_seeds=181
```

---

## 附注

- 本报告的代码引用基于内测仓库 `7df40b5a7` 及其当前工作树；该提交已于第 20 轮同步到本公测仓库，故公测同样存在该回归。
- 本报告只是一份分析文档，未修改任何生产代码。修复前建议先做"关闭 `greedy_warm_start` + 复用密集剂量图"的对照实验，再决定是否调整 `select_hierarchy_level`。
