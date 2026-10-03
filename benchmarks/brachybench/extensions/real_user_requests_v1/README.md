# Real User Requests v1 — quality-first authoring extension

## 当前阶段：已补齐可执行的开发版 benchmark

2026-10-03 后续建设已加入 `contracts.py / fixtures_runtime.py / event_driver.py / environment.py / oracle_runtime.py / prepare.py / runner.py / review_cli.py`，以及 `compiled/` 的 **82 份 task 包装、82 份完整 fixture、82 份私有契约、82 份事件脚本、82 张逐题意义/复核卡**。它们不再只是待实现的文字建议。

入口及全部接口见 [PROTOCOL.md](PROTOCOL.md)，建设记录见 `docs/BENCHMARK_REAL_USER_REQUEST_RUNTIME_2026-10-03.md`。在 `benchmarks/brachybench` 下执行 `python -m extensions.real_user_requests_v1.prepare --check` 验证构建；`python -m extensions.real_user_requests_v1.runner` 默认仍只检查。只有明确 `--execute` 才启动被测系统，本次没有执行。

源码 `catalog.py/candidate_pack.json` 保留原 authoring-only 状态，是人工编写依据；可执行投影在 `compiled/`。运行能力已实现不等于独立语义/临床审查已完成，所有投影仍是 **development/exploratory，不进入主实验排名**。没有将组件自测包装成 BrachyBot 测评结果。246 个原始负控规格仍须逐项语义审查，不等于本文新增组件反例的数量。

当前默认是 alpha/beta **合成决策环境**，不是生产医疗引擎或真实 BrachyBot 浏览器 gamma。真实产品验证须由实际浏览器/独立产物采集支撑，不能因镜像状态/组件 green 就称生产 UI 正确。

日期：2026-10-03。对应完整审查报告：`docs/BENCHMARK_REAL_USER_REQUEST_COVERAGE_2026-10-03.md`。

这是 **40 个场景族、82 份逐题编写的候选契约**，不是新增 82 个已验证、可排名的正式 task。RUR-03 有四种局部否定/引用/条件分支，其余族各两种不同情境。246 项负对照是待实现的故障规格，不是 246 次已执行成功的负控实验。

## 为什么独立放置

现有 `tasks/` 的 11,969 个任务、gold、replay、MANIFEST、split、历史结果均不改变。扩充的重点是开放自然需求背后的目标、范围、时序、依赖、实际交付和诚实回答，不是让被测模型复述固定工具名。

每题保留：

- 合成初始状态、稳定对象身份和病例/会话/版本。
- 真实用户表达或 Monitor 事件，以及条件触发的环境事件；不依赖固定 sleep。
- 按语义效果定义的授权集合、默认禁止的额外持久写。
- 独立状态、实际副作用、用户收到的回答/附件等验收证据。
- 具体结果标准、三个不同错误处理的负对照规格。
- 执行/观察前置条件、预算策略和同族 split 身份。
- 诚实的 `AUTHORING_ONLY / formal_eligible=false / pending_independent_review / live_validation=not_run`。

本文件夹的 `initial_state` 是**fixture 设计契约**，不是已能装载到生产 BrachyBot 的 CWS。诸如 `camera-original`、`rows_source`、demo 协议和事件 trigger 均需要隔离 fixture/driver 具体实现，不能填一个通过标志就认为完成。

## 文件

| 文件 | 用途 |
|---|---|
| `catalog.py` | 手工编写的场景、意图效果和验收契约；不导入 SUT parser/policy/oracle |
| `candidate_pack.json` | 上述内容的确定性机器可读投影；含私有评测答案，不能整份交给 SUT |
| `quality_gate.py` | 结构/出处分组/负控规格/缺证据状态检查，不是语义 scorer |
| `authoring_quality.json` | 编写检查结果，明确 `semantic_validity=NOT_ESTABLISHED` |
| `build.py` | 重建或检查投影漂移；不执行模型、不运行规划 |
| `test_authoring_contract.py` | 编写基础设施自测；不代表 BrachyBot 做题成功 |
| `evidence/current_inventory.json` | 现有题库实测统计；关键词筛选数不是语义覆盖率 |

## 使用

```bash
cd /home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/extensions/real_user_requests_v1
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python build.py --check
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -p no:cacheprovider test_authoring_contract.py
```

`build.py --check` 返回 0 **只代表候选投影未漂移**。输出同时给出 `formal_ready=false`。不得将该返回码或 pytest green 当作生产 SUT、正式 benchmark 或临床验证成功。

## 升格门槛

1. 由独立审查者确认每题真实意义、意图/授权和可接受行为集合；临床含义由适当专家审查。
2. 对需要的 fixture、环境故障、真实历史、条件事件和浏览器交付编写隔离驱动。
3. 对回复、视觉和临床判断建立独立人工/参考证据并校准；不能复制 SUT 结论作 gold。
4. 逐题实际执行正向控制、全部声明的负对照和合法替代路径；缺采集器是缺证据，不是成功。
5. 通过真实 SUT smoke 后，版本化映射到现有 task schema + evaluator-private context，按同族/fixture/来源连通分组隔离 dev/pilot/sealed。
6. 新冻结实验另建 manifest；不回写旧 split/旧结果，也不将 candidate 或 component self-test 混入主实验分母。

这里没有已经升格主实验的 formal suite。开发版 `runner.py` 已实现隔离 JSONL worker、事件屏障、独立采集及认证 recording；`review_cli.py` 复用现有三态 evaluator。不要把 `catalog.py` 的 `PACK` 或完整 JSON 直接传给 `agent_factory`。只发送实际用户输入和允许观察的世界；金标准、故障时序和断言留在 evaluator。

## 语义约定与限制

- 示例 `Opacity` 指 UI 的不透明度滑块，0 透明、1 不透明。明确使用滑块名避免把日常“透明度 30%”的歧义硬编码成错误 gold；真实自然表达中的反向含义还需人审对照。
- `BASE` 数字只是合成观测，非患者数据、临床限值或疗效证据。RUR-34 的 8 Gy 是明确的 demo 协议值，绝不能作为实际头颈临床推荐。
- 同名对象、上一个编辑、屏幕方向、当前/旧病例均以可核实状态为准，不要求固定词面或固定工具调用路径。
- 允许受支持的等价工具路径、合法并行/串行调度；只约束必需依赖、目标结果、权限和实际证据。
- 教学有效性、任意需求都能理解、真实剂量最优移动方向，不能由这些合成契约证明。
