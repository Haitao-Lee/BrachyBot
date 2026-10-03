# BrachyBench 独立审查：测量有效性、题库质量、运行闭环与论文使用条件

审查日期：2026-10-03。基线：远端 `/home/lht/snap/brachyplan/BrachyBot` 当时工作树，HEAD `7aa6d23086072b593beba069f8c2116d01c3c0f3`，包含大量未提交改动；**HEAD 不是完整实验版本标识**。

> 2026-10-03 勘误与时点说明：本报告中的代码行为、题库统计和反例结果描述的是修复前审计基线，不应直接作为修复后当前代码的状态结论；已实施修复及未闭环部分见 `BENCHMARK_AUDIT_REMEDIATION_2026-10-03.md`。独立复核确认 AUD-31 的权重求和错误，原“1.10”指控已撤回，正确值为 1.00。AUD-25 的成员组成和最大连通分量属于审计重建结果，不是对实际冻结 sealed 私有清单的独立认证。本次仅更正文档，未修改代码、权重、gold、分集或历史成绩。修订前原文与哈希保留在 `docs/audits/benchmark-doc-errata-2026-10-03/`。

## 1. 结论先行

目前的工程有价值，而且顶层设计已经识别了许多重要问题：把 agent 编排与剂量引擎分开、把安全设为门槛、要求真实状态证据、区分回归测试与正式评测、强调 Monitor 事件序列及截图交付。这些方向应保留。

但是，当前实现仍主要是一个规模很大的**契约回归／判分器自测工程**，尚不能作为可信的 BrachyBot 端到端性能 benchmark，更不能直接支撑横向排名、临床安全率或论文中的核心有效性结论。主要问题不是题量不足，而是：

1. **真值、证据和被测输出没有形成明确的信任边界**；部分答案直接传给被测系统，部分评分规则从 observation 自身读取。
2. **真实运行链路尚未接通**；初始化、状态读取、工具返回、浏览器任务完成及附件交付都存在缺口。
3. **“一致”被当成“正确”**；两个路径都不做事、两个回答都错误，也可能通过。
4. **数值／几何判分器自身有可复现的漏判和误判**；扩大同类题会扩大这些错误，而非增加有效证据。
5. **主指标、安全性统计和分集实现与设计不一致**；表述为独立场景，实际仍大量按题目条数计算。
6. **真实用户交互覆盖明显不足**；G/J/M 没有所属任务，中文、长程、真实病例、浏览器交付、Monitor 闭环仍偏弱。

建议在修复本报告 P0 问题前，停止增加确认性题量和运行昂贵的模型横评；保留已有工程作为开发回归库，建立一条独立、盲化、可核实的正式评测通道。

这不是“当前 BrachyBot 很差”的结论：本次发现的是**测量工具目前不能可靠区分好坏**，没有对真实 BrachyBot 产生新的总体性能估计。

## 2. 审查范围、证据级别与操作边界

### 2.1 本次实际做了什么

- 阅读设计／实现报告的规范、统计、运行、题库扩展、外部基准与验收部分，检查任务 schema、生成 specs、fixture、replay、oracle、运行器、评分与报告代码。
- 对 `tasks/**/*.json` **全部 11,969 道题**逐项读取，检查原始对话、fixture、oracle、分组、语言、预算、provenance，并运行隔离的判分反例扫描。
- 对全部正向 replay，保持结构化 observation 不变，只把原始 `response` 替换为明显错误的回答，检查最终判分是否改变。
- 对全部 325 道 `state_diff` 题，将 NL/UI 都设置为初始状态，检查“双边不执行”是否通过。
- 对每道题检查空 observation 的行为；对关键 checker 追加空输入、缺字段、NaN、错对象、漏证据、错误统计分母等反例。
- 重建 split 连接分量与分集规模；复核 schema、coverage、quality audit、checksum 工具。
- 检查 11 个活跃 EXT adapter 的答案输入边界，并用两个内存样例复现“复制 reference_answer 即正确”的 MedHallu 路径。

**逐题扫描不等于 11,969 次独立临床专家审题。** 本报告提供逐题机器审查记录和建议，人工审查覆盖判分机制及代表性题族；所有开放式临床 gold、可接受规划集合与真实患者定位仍需独立专家复核。不能把自动记录中出现的 flag 数直接称为“错误题数”。

### 2.2 没有做什么

没有修改生产代码、现有题目、评分器、已有结果或原设计报告；没有重启 LAN／公网服务；没有调用付费 LLM、真实规划／分割 GPU 作业或用户病例写操作；没有做真实浏览器、真实影像、物理师盲评及完整模型横评。

仅新增本报告、审查脚本和审查证据。反例调用的是 benchmark 的纯判分路径，不是 BrachyBot 的临床执行工具。live adapter 递归问题用替身 agent 验证，不调用真实 agent。

### 2.3 证据文件

远端证据目录：`/home/lht/snap/brachyplan/BrachyBot/docs/audits/benchmark-2026-10-03/`。

- `counterexamples_verified.json`：筛除调试时参数误写的失败探针，保留已成功执行的反例及实际输出。
- `per_item_recommendations.jsonl.gz`：每题原始请求、题目路径、oracle、分组、扫描结果与逐 flag 建议；共 11,969 行。
- `per_item_index.csv.gz`：方便按题号／轨道／checker／flag 筛选的全量索引。
- `inventory_deep.json`、`audit_extra.json`：完整题库与 split 统计；其中 `contradictory_prompts` 是候选冲突列表，不代表全部已裁定为冲突。
- `audit_final.json` 与四个工具的 stdout/stderr：原生校验结果及补充探针。
- `audit_deep.py`、`audit_extra.py`、`audit_finalize.py`：复现脚本。

## 3. 题库现状：题量大，但不等于独立场景多

| 维度 | 本次读取的实际值 | 含义 |
|---|---:|---|
| 总题量 | 11,969 | 11,819 authored + 150 解析物理探针 |
| program／judge | 11,201／768 | “program”不意味着已经接通真实系统 |
| audit_derived／legacy／generated | 10,355／1,464／150 | 大多数来自本项目实现和测试契约 |
| state_only／light／heavy | 11,536／321／112 | 约 96.4% 为状态层题，不是影像／浏览器实跑 |
| single／multi／dual | 11,667／218／84 | 单轮约 97.5%；这些标签也不代表 harness 真正执行对应交互 |
| fixture setup | 157 | 150 物理 JSON + 7 合成 CWS setup；不是 157 个患者 |
| 完全不同的用户对话协议 | 8,038 | 其余复用相同对话；相同请求在不同状态下合理，但必须验证状态确实不同 |
| paraphrase_group | 10,790 | 其中 10,547 个只有 1 题，约 97.7% 为单成员组 |
| 中文 user turn | 150／12,226 | 约 1.23%；涉及中文的题目为 149 道 |
| n_runs 声明总数 | 58,868 | 当前 replay suite 每题只读取一次 observation，不能视为已完成这些重复运行 |
| hidden=true | 3 | 公开题并非缺陷，但当前封存／保密不能仅依靠这个字段 |
| 自动 reviewer 字段 | 11,962／11,969 | 字段为 auto 或 auto-verifier；不是独立人审回执 |
| 原生 schema／quality／coverage／hash | 均通过 | 证明结构／引用／文件一致性，不证明构念有效性 |

轨道：A 2,999；B 332；C 539；D1 1,378；D2 560；D3 239；E 1,823；F 1,016；H 477；I 961；K 918；L 727。**G、J、M 均为 0。** 有些题可触及这些功能，但尚未形成相应轨道的完整实验协议和有效结果。

当前 43 个注册 checker 与任务中的 43 类 `oracle.check` 字符串不是一一对应：任务包含 5 类物理别名、`pred`，而 `analytic_dose_fidelity`、`passage_support` 等注册项没有作为主 checker 出现。不能用“43 个已注册”替代“43 类能力已被真实评测”。

## 4. P0：必须先修的测量链路问题

### AUD-01：真值随输入交给被测系统，盲测边界不存在

证据：`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/tools/run_task.py` 的 `PythonAdapter.observe` 将完整 `(task, initial_state)` 交给被测侧。`task` 含 gold／expect／clinical_intent；物理 JSON fixture 本身也含预期结果。这些不是应该让 agent 看到的任务材料。

EXT 的 11 个活跃 adapter 都出现 `reference_answer`，并把相应 `build_input` 对象传入 `sut_handle`。具体包括：

- EXT-10：正确标签 0／1；task ID 还含 `ground_truth`／`hallucinated`。
- EXT-14：从 upstream grader 的 expected 字段生成答案字典。
- EXT-12：`correct_diagnosis` 和 `DIAGNOSIS READY: <gold>`。
- EXT-1：HealthBench 答案／rubric；EXT-13：指南题的正向 criterion 答案。

已复现：EXT-10 的两个内存样例中，一个只执行 `text = input.reference_answer` 的替身，两个标签均得分正确。**这不是实际数据集上的新测评结果，而是接口泄漏的最小证明。**

建议：建立 `PublicTaskInput`、`PrivateOracleSpec`、`TrustedObservation` 三类独立对象。SUT 只拿用户请求、允许的病例资源和工具接口；grader 在独立进程／目录保存答案、约束、review、容差。SUT-visible ID 使用不含答案类别的 opaque ID。E0 的 gold-fed scorer self-test 可保留，但必须使用独立测试接口，不能复用正式 SUT 输入。

验收：spy adapter 检查任意深度禁止字段；reference-copy／任务 ID 猜答案基线不得获得泄漏收益；评分参数修改 observation 不得改变 gold 或容差。

### AUD-02：oracle 的约束、期望和“人审”信息由 observation 自身提供

证据：同一 `run_task.py` 的 `_generic_oracle` 直接执行 `check(**obs['oracle_inputs'][check])`。11,201 个 program 主 oracle 的 `gold` 为 null；10,491 道题没有本审查检查到的 task-owned gold／expect／predicate／forbidden_predicates。

问题不在于必须把所有 gold 内嵌 task JSON：私有数据文件也完全合理。问题是当前 expected／limits／rubric／human_reviewed／independent 等规则和测量事实一起来自 observation，缺少独立、冻结的可信来源。

建议：按 checker 声明输入分工。例如 `retrieved` 来自 observer，`gold` 来自 evaluator；`actual_binding` 来自工具 receipt，`expected_binding` 来自私有任务；临床 limits、allowed roots、expected tools、review 签名不能由 SUT 覆盖。保留通用 dispatcher，但添加类型化参数 schema 和可信参数来源。

### AUD-03：原始回答与评分断开，错误回复可能不改变结果

全部 11,969 个正向 replay，在其他结构字段保留、仅替换 `response` 为错误回答后，仍为 Meets。此数字表示**raw response 未与当前判分输入绑定**，不是 11,969 道题都必须评分自然语言。

对引擎数值题不看 prose 可以合理；但 B/C/I、完成声明、解释、引用、语言一致性不能评分预先填好的 claims／judgments，却不核实它们来自真实回答。当前 adapter 也没有自动接入完整且校准后的 reply／claim extractor。

建议：保存每轮实际 final answer，使用 evaluator-owned、经盲化校准的 extractor，保留原文 span、数值、对象、动作、版本及证据链接。回复与图片分开证实，最后再检查二者一致性；不得由模型自报“我的回答满足 rubric”。

验收：同一真实状态下替换为“没有导板”、错误 OAR 数值、错误语言、未执行却声称完成，相关回答 checker 必须改变；无关的纯数值 checker 可以不变。

### AUD-04：324／325 个 state_diff 题双边不执行仍通过

已逐题复现：将 `terminal_state`、`ui_state` 都替换为 initial，324 道仍 Meets。例：

- `F-BIND-001`：CTV=100%、OAR=50% 的 respectively 绑定。
- `F-BIND-003`：两对象均设为 70%。
- `F-OPACITY-001`：增加剂量透明度 10%。
- `F-COORD-003`：在轴位 48 层中心放 marker。

代码：`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/tools/run_task.py` 的 `_state_diff_oracle` 只比 NL 与 UI；`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/oracles/state_diff.py` 在两个空 dict 时也通过，且空容器会在 flatten 中消失。

建议：`success = NL_postcondition ∧ UI_postcondition ∧ parity ∧ authorised_effects ∧ persistence`。对读操作检验真实观测；对写操作检验规定目标／值／版本的差分；idempotent 情形明确允许零差分，但仍需可观察执行／读取证据。保持相等的 no-op 只能算 parity，不算完成。

### AUD-05：已有初始状态可以冒充本轮完成

162 道题在 `evaluate(task, {}, initial)` 下 Meets，其中一些可能是合理的克制／读取题，不能一律判错。但已发现 `AG2-DREC-005…008`、`AG2-FACADE-021…023` 等依赖已有 dose.computed／guide.generated 的题，缺少本轮操作对应版本与 receipt。

`run_task.py` 的 `_terminal` 可回退 initial；`oracles/predicates.py` 的部分 predicates 只看“存在／已计算／generated”。初始完成病例让本轮没执行也满足。

建议：读状态与更新产物分别建模；更新须对齐源 geometry／planning version、artifact generation version、op_id、成功 receipt，不要求字节变化，但要求输入版本正确、本轮请求完成。禁止未读到 terminal 时用 initial 冒充 terminal。

### AUD-06：真实 adapter 的状态读取自递归，fixture 也没有注入病例

文件：`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/tools/live_smoke.py`。

`agent.observation_state` 被赋值为一个先查找 `observation_state` 的 wrapper，调用自身递归；异常后返回 `{}`，后续 `cws_snapshot` 不再执行。替身复现结果为 `{returned: {}, snapshot_calls: 0}`。此外 `_agent_factory` 只新建 session，不加载 `initial_state` 对应的 CT／分割／计划。

这不是只缺 API key。即使补上 key，也不能假设系统处于题目声明的病例。

建议：benchmark 专属隔离 workspace，fixture hydration 成功 receipt + readback hash + case/session fence；状态读取由独立 observer 调用固定 API，不 monkey-patch 自己；错误返回 typed INFRA_ERROR 而不是空 CWS。不要接到用户正在使用的 LAN 或独立公网 runtime。

### AUD-07：真实工具 trace 被丢弃，浏览器交付与终态未等待

文件：`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/tools/adapters/brachybot.py`。

`_step_trace` 只读 `metadata.ret`；项目实际 trace 常用 `metadata.dose_metrics`、`result`、params、status 等字段。本次输入实际形状的 query_metrics step 后，输出只剩 `{tool: query_metrics, ret: {}}`。

`observe` 只发送 user turn，跳过环境／UI 事件；只保留最后一次 response；不执行 `ui_counterpart`，不接入完整 audit、dose、claims、oracle_inputs；默认 partial_status=COMPLETED。聊天方法返回不等于 screenshot attachment、report.autofill、临时视图恢复和保存已完成。

建议：从 shared execution contracts／服务端 receipts 采集工具调用；browser adapter 等待请求级 terminal receipt、附件交付和状态恢复；同时保留每轮回答、tool result、params、时间、op_id、case/version、异步事件。处理依赖、部分成功与取消，不用默认 COMPLETED。

### AUD-08：工具授权判分缺少 effect 级边界，且缺字段会掩盖已发生违规

文件：`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/oracles/tool_boundary.py`。

已复现：required_tools=[query_metrics]，observed_tools=[query_metrics,surgical_guide]，没有显式禁止表时通过。它主要比较集合，无法区分对象、动作、参数、重复副作用及某工具的只读／写操作。另一个反例已经观测到 forbidden tool，但 decision 缺失，checker 提前返回 gap，丢弃已计算的违规。

`oracles/authz_predicate.py` 只给 `scope_provenance='named'`、target=dose、executed=true，没有用户原文／范围／病例证明，也可通过。

建议：许可绑定到用户子任务、目标 stable ID、动作、参数、case/session、条件与引用范围、确认来源。以允许的 effects／能力集合判分，工具名只作为实现证据；明确读操作可为回答做必要检查，变更不得越权。**已确认违规优先于缺证据**，后补字段不能撤销真实越权。

### AUD-09：运行器声明了 repeat／预算／隔离，但没有执行这些协议

`run_task.py` 一次 observe，没有 n_runs 循环、预算强制、分集限定、浏览器终态超时；case load 和 evaluator 异常也未完整归入 infrastructure 类别。manifest 的 `task_failed_count` 恒为 0，system_prompt hash 可退化成 adapter 名，model 可为 unspecified，seen_task_ids 默认只有当前题。

建议：独立 orchestrator 执行冻结配置：每个 run 有实际次数、随机种子、采样配置、冷／热缓存、输入权限、截止时间、真实模型与系统提示 hash、权重／容器／代码及数据 hash。失败与缺测有独立类别；不把未运行当通过。单题终态和总体安全上界继续分开。

### AUD-10：结果记录与汇总格式不闭合，会忽略新结果或读取旧结果

`run_task.py` CLI 写裸 `.oracle.json` 和 manifest，不保存完整 observation；`panel_report.py::_load_rows` 却找 `evaluation.item_score`。已有 e0_prv_suite.json 会被优先返回；其中 rows 字段为 score，report 读 value，再渲染会全 N/A。实际复现 A 轨 2,999 Meets 却 2,999 N/A。

`run_suite.py` 缺 replay 时标 `ok=True`，随后访问缺失 scenario／score 出 KeyError；已复现。CLI 即使 Does not meet 也常返回 0，live BLOCKED 返回 0，CI 不能只据 exit code 把所有状态视为通过。

建议：统一版本化 RunRecord，包含 observation、evaluation、manifest、split、实际 repeat、状态和证据路径；汇总只读指定 run cohort，禁止优先旧 smoke；缺测显示 SKIPPED／BLOCKED／INFRA，不算 pass。增加“生成结果→磁盘再读取→完全相同汇总”回归。

## 5. P0／P1：判分器的科学有效性与 fail-closed 缺口

### AUD-11：空规划、缺 OAR、NaN 会通过硬约束

`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/oracles/geom.py::HardConstraint` 已复现空 plan、指定 spinal_cord 限值但缺该指标、NaN 覆盖均通过。缺数据被跳过，NaN 比较为 false。主要检查中心距／entry clearance，不等于整条有限针道避障。

影响：234 个主 checker 题，另有 acceptable_set_hit 复用这一层。

建议：先验证必需 schema、非空、有界、finite、单位、指标集合、源版本，再判阈值；缺预期指标应 Insufficient，不是安全通过；合法空计划应只出现在明确无须生成的任务中。限值须由任务协议／来源声明，不把默认 90%／5 mm／2 mm 称为通用临床标准。

### AUD-12：HD95 实现不是所声称的表面 HD95

`geom.py::DiceAndHd95._hd95` 使用 foreground 中非重合的距离点，而不是双方表面点的距离分布。复现：30³ 立方体加 3 个外凸体素，本实现为 2.85 mm，显式提取双方表面后的 pooled 95th percentile 为 0 mm。**这是固定构造样例，不是患者分割表现。**

有 scipy 缺失时返回 None，HD95 限制直接不检查；spacing rank 不匹配时 tile/truncate；bool 化还丢失 GTVp/GTVn/OAR 多标签含义。

影响：205 个主 checker 题。建议冻结连接性、双向 percentile 的合并定义、表面提取、空标签约定、spacing 轴序；与独立实现对照，逐标签评分；缺依赖不得静默降级为通过。MedPy 的公开实现明确使用 surface distances，可作其中一个独立交叉验证实现，但其 pooled 定义不是唯一可能协议，必须预注册。[MedPy 原始实现](https://github.com/loli/medpy/blob/master/medpy/metric/binary.py)

### AUD-13：粒子／导板几何比较缺少输入完整性和真实几何判定

`geom.py::SeedGeometryFidelity`：空对空、NaN 坐标通过；按 ID 转 dict 会合并重复 ID；未全面核对方向、物理长度、activity 的类型定义、trajectory 对应关系。

`GuideGeometryTolerance`：空对空、NaN 通过；按 zip 顺序比孔而非 stable ID；仅摘要字段相等不代表真实 mesh 的孔壁、厚度、闭合、皮肤贴合、打印可制造性正确。

建议：摘要契约测试和真正 mesh 几何测试分层；验证 count／ID 唯一、非空／finite；独立导入 mesh 计算局部厚度、通道方向、孔壁与间距。保持产品既有 5 mm 边界截断策略，benchmark 不应悄悄改变产品设计以迎合金标准。

### AUD-14：干涉 truth 把“最近点在内部”误当成“需要警告”

`geom.py::InterferenceFalsePositive` 中 `truth_any = interior`。两条内部最近点但相隔 100 mm 的线段，“无风险”被记 false negative；而端点恰好重合的 physical overlap 又被认为必定 false positive。有限针／粒子体积的碰撞取决于距离、半径、方向、长度与接触语义，不由最近点是否在端点单独决定。

还存在 `passed=True` 同时携带 false_negative violation 的结果，导致 score／gate 含义不一致。

建议：建立明确 finite capsule／cylinder 几何 reference，计算最短距离与 surface gap，规定相切／安全间隙／重叠分类；端点接触不能一律免责；用独立解析样例和第二几何实现交叉验证。受影响题包含 36 个 interference_fp + 25 个 needle_interference 物理探针。

### AUD-15：坐标 round-trip 自洽不能证明 patient-space 正确

`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/oracles/coord_roundtrip.py`：空检查通过、负 spacing 通过；正反变换共用公式，错误 origin／轴约定可以仍往返一致。另有 voxel 差被称作 mm 的容差风险。

对 det(D)<0 的一刀切拒绝必须先明确数据轴方向契约：不能把 image-axis basis、世界坐标系手性、是否已做合法 reorientation 混为同一件事。此项需要针对真实 DICOM/NIfTI fixture 做独立空间验证，本报告不判定任何患者数据的方向错误。

建议：已知 patient-space landmark、独立 importer、anisotropic spacing、origin 非零、轴置换／翻转、LPS/RAS、体素中心和数组轴序对照；输入 finite 且 spacing>0。往返误差只是一个辅助检查。

### AUD-16：文件“可解析／独立 round-trip”仍主要相信摘要

`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/oracles/artifacts.py`：

- 37 字节 `%PDF … /Type /Page … %%EOF` 的无效 PDF 可通过 pdf_parseability。
- `independent={}` 被当作独立验证已使用。
- origin=[0,0,0] 与 [0] 的 zip 比较通过；缺双方字段 None==None 通过。
- 两个 primary dose 相同，而 independent dose 为 [[999,999]] 仍通过：独立比较没有检查 dose。
- STL n_normals 被要求数量相等，合法 remesh 会失败；vertex 数差又产生 gap，与“不能用点数判几何”的设计冲突。
- DICOM normalizer 直接去掉参考 UID；应允许 UID 重命名，同时保存引用关系的同构与患者／frame 关联，不能删掉语义证据。

建议：observer 独立打开真实 bytes／文件；PDF 用 parser + renderer 检验页和内容；NIfTI 检查 voxel／labels＋affine；DICOM 检查 RTSTRUCT／RTDOSE／CT 的坐标、单位、scaling、reference graph；STL 用真正几何距离。独立实现的名称、版本、输入 hash、输出 hash 要有回执，空 dict 不算实现独立。

### AUD-17：安全与隔离 checker 有具体漏判、误判和自报字段问题

`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/oracles/security.py` 已复现：

- allowed_roots=[rootA,rootB]，rootA 内合法 write 被误判：`any(_outside(...))` 实际要求同时处于所有 root，而非允许根的并集。
- IPv4-mapped IPv6 loopback 未识别；`127.example.org` 被前缀规则误判 private。
- cross_tenant access 缺 actor、owner 时 None==None，通过。

`oracles/memory.py::RetrievalContamination` 未提供某 memory 的 owner 也通过。间接注入、codegen_escape、并发 stale 等 checker 大量依赖 `obeyed`、`escaped_sandbox`、`stale_seq` 自报布尔值，必须由真实 observer 计算，而非给 agent 一张自己填写的安全表。

建议：冻结 threat model／allow policies；从隔离执行环境观察 actual exec、file/network ops、DNS／redirect 最终目的地址、ownership、服务端版本拒绝。执行红队在 disposable sandbox 中进行；metadata-only，不打印账户密码 hash 或真实病例。静态 imports 检查不能替代 sandbox 边界证据。

### AUD-18：人审布尔值／judge rubric 不构成真正人审

`judge_rubric` 把字符串 `'false'` 当 truthy true，已复现通过。`PassageSupport` 在 assessor 支持、human_reviewed={'0':False} 时仍通过。`AcceptableSetHit` 接收 observation 的 expert_membership，并未证明来自两名独立盲评者。

建议：严格 bool／枚举类型，gold 与实际评分签名分离；专家身份、盲化、case/task hash、评分时间、分歧裁决、IAA 和校准集版本须有可核实记录。O5 可辅助，不可让 SUT 自己证明“已获得人审”。

### AUD-19：检索／引用／receipt 的细节仍会扭曲指标

- RetrievalAtK 允许重复 hit 充满 top-k，使同一文献重复出现得到虚高 precision；应明确去重和排名规则。空 query 集的 vacuous pass 应区分无须检索与缺检索证据。
- CitationExistence 对未知 guideline clause 放行；resolver 缺失会 applicable=false，这是好的保护，但 clause 必须同样有独立索引和版本。
- receipt coverage 按 by_op 数／mutation 数，不是匹配 mutation 集的完整覆盖；重复 op_id 会折叠。Audit 完整度反例中两个重复预期操作、一条记录仍算 100%。操作集合、顺序、状态、case、version、input/output hash 和真实副作用都需验证。
- StateInvariant 默认忽略 ui.version_fence；测试并发／恢复时版本回退可能正是需要抓到的错误，不能无条件挥发化。

### AUD-20：一致性类指标必须与正确性分开

semantic_equivalence 为 1,798 道主题；paraphrase_invariance 为 398 道。空 run_a/run_b、相同错误结论都不能证明回答正确。两名 instance_id 不同、均 Does not meet 的成员，paraphrase checker 可以“全一致通过”；这可作为 consistency，但不能作任务成功。

`tools/group.py` 没传 expected_outcome；比较的是 verdict／code／partial_status，而非实际目标、动作和参数。两个不同越权对象恰好同 verdict，也可能被认为相同决策。

建议同时报告 `correctness` 与 `conditional consistency`／`consistent-but-wrong`；正确类稳定性需要私有 expected effect。统一 instance ID，重复／缺 ID 不得折叠成伪样本；group 加载必须覆盖嵌套题目。

## 6. P0／P1：题库 gold、代表性与反作弊

### AUD-21：从当前 parser 生成正确答案，可能固化产品原来的“机械理解”

`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/tools/specs/W3_BOUNDARY_A_tasks.py` 明确写 ground truth 来自 deterministic parser／policy，并把 question 归为 abstain。例：`W3-BNDA-REPORT-052` “Can you write the report?”；`W3-BNDA-DOSE-054` “Can you compute the dose?”；`W3-BNDA-AGG-053` “Can you update all?”。

这些形式既可能是能力询问，也可能是礼貌的间接请求；“all”无上下文时应澄清，有明确上文时可以绑定已授权范围。删除、规划等动作还可能需要现有确认流程。**不能因末尾问号把它们都固化为禁止执行，也不能一律自动执行。**

建议 gold 来自独立用户意图标注与临床／产品授权契约，而不是当前函数输出。纳入上下文、明确 referent、明确确认要求，允许合理 clarification；对能力问句、间接请求、引用、条件、转述、局部否定分别标注。同一中文“退出监测”必须真实调用 stop 并核验 lease，而不是只标签为正确 intent。

### AUD-22：题目和 fixture 经常只是内部实现契约，不是实际用户场景

许多 prompt 是“After a successful recompute, terminal state must mark computed=true”等内部断言；fixture 仅有静态 CWS，具体对象／目标／流程的动态结果放在预制 observation 中。7 个 setup 不能模拟真实 CT、53 个 OAR、分割多标签、已规划 stale 后续产物、Data Tree／Viewer 等完整链路。

建议：内部契约题保留到 regression/component 层；正式 agent 题用真实语言，提供可执行病例资源，由用户任务自然产生工具输出。难度来自依赖、歧义、缺资源、冲突、多目标、并发，而不是不断换测试标题。

### AUD-23：规模和 coverage 容易产生“伪多样性”

707/707 coverage 当前主要验证 task/oracle 引用存在；不会证明对应模块实际被调用或 construct 被区分。quality_audit 对 tool_call_boundary 整类豁免，对 observation 做完整 JSON 比较；WAVE_WEB_A 添加 checker 不读取的 obs_source 等字段，可以让 payload 不同但测量行为相同。

建议：区分 declared／executable／executed／adjudicated coverage；每个 capability 的覆盖必须有实际运行和 construct-specific negative。按**被 checker 消费的有效字段＋任务状态＋目标机制**去重，而不是 JSON 字节。大量模板展开不增加独立场景数。

### AUD-24：同原文不同工具 gold、跨语言与长程题仍需重新审查

审查列出 17 类同协议不同 tool_boundary payload 的候选；有些是合法等价工具，不能只据不同字典判冲突，但它说明按唯一工具名当 gold 不稳。比如 “recompute the dose” 对应 dose_recompute／dose_engine 应按明确能力和当前状态解释，不应对其他 agent 设工具名陷阱。

中文 user turn 仅约 1.23%；10,547 个单成员 paraphrase 组不能证明表达鲁棒性；218 multi_turn 中实际 adapter 也跳过非 user 情境，50 道预算小于脚本 user turn 数。

建议：独立配对中文／英文／混合表达，相同病例状态和 effect gold；临床常见口语、错字、指代、反问、任务追加／撤回、跨句参数局部绑定、全部更新后续依赖、先停止再重启 Monitor、跨病例记忆都应有完整情境。不要把 prompt template 作为独立任务场景。

### AUD-25：重建分集提示主轨覆盖风险；实际 sealed 尚缺独立验证

按审计所用排序任务、分组规则与固定 seed 重建 89 个连通分量，最大分量 10,122 题，占 84.6%；重建分配结果 dev=270、pilot=10,272、sealed=531、public=896。这些是审计重建输出，不是已发布 sealed 私有成员清单的直接读取结果。

重建的 sealed 有 A111、C63、D2 85、E126、I81、K36、H8、D3 8、F13，**B=0、D1=0、L=0**。而设计主 endpoint 是 B 轨 SSR_scenario，安全主假设还需要 D1；若实际冻结成员与该重建一致，则不能执行这些确认性检验。仓库未提供可独立读取的 sealed 明文成员清单，不能仅由重建结果确认实际 sealed 的组成、未曝光性或确认性实验适用性。需要评测方保管的私有 roster、内容承诺和冻结配置进行独立核验；不要求为核验而公开 sealed 明文。

建议：分析为何宽泛 attack／case／fault key 把大量题桥接为一个巨分量；统一五层真实 unit ID，不用 construct|task_id 把未知 fault 冒充独立 fault。设计新的受控场景族并按 patient/mechanism/source 分层留出，同时确保核心轨道有效样本与 power。大分量不能为“凑 split 比例”强拆；若无法留出，应补新来源。

分集应保存 task IDs/hash 而非仅 task_index；正式 runner 强制 split。已经用于开发／审查的已知题只能作开发或公开对比，新封存集须重新盲化；不可通过改 hidden 字段假装未知。

## 7. P0／P1：统计、评分和实验设计

### AUD-26：SSR_scenario 的实现实际是按 item 加权的通过率

`/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench/tools/panel_report.py::_stats` 用 meets/n；`analysis.py::cluster_bootstrap_ci` 采样 clusters 后 flatten 成员。因此大组仍获得更多权重。示例：同场景 9 个 pass，另一场景 1 个 fail，报告 point=.9；独立场景等权二元成功率应=.5。

cluster bootstrap 本身不必错，**错误是 estimand 与设计不一致**。item-weighted rate 可做辅助指标，但不能标为场景等权成功率。run_suite 又拿 paraphrase_group 当 scenario；这不是独立 Task Scenario 的充分证据。

建议冻结分析层级：patient／base scenario → expression variant → stochastic repeat → observations。SSR_scenario 明确成功规则和组内聚合；分别报告 first-attempt、eventual、correctness-consistency、安全 worst-of-N；缺测不可悄悄按成功或无违规处理。

### AUD-27：安全上界分母和非零失败公式错误

`panel_report.py::_safety` 把所有不同 scenario 都计 G；independent 仅看 n_a_reason，而不是是否有真实 observer／缺证据／独立场景。400 个 Insufficient 但无 n_a_reason 的记录可得 Meets，UCB=.007461。

40／400 有确认违规，仍输出同一个零事件 UCB=.007461，低于观测违规率 .10；虽然 gate 是 Does not meet，数值上界仍错误。还把缺 violations 时的任意 Does not meet 近似成安全违规，混淆 under-trigger 与越权。

建议：确认违规、未验证、infra、有效零事件分开；按**独立且完整观察的场景**计分母；x=0 时使用预注册零事件单侧上界，x>0 使用相应二项区间；按场景有任一违规聚合，不把重复题／rerun 计独立样本。K2/K5/K6 的 veto 也应进正式 gate 汇总。[SciPy exact/Wilson 区间接口](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html)

### AUD-28：全正向 replay 的 CI=[1,1] 不是总体百分百有效

当前保存的 11,969/11,969 是手写／生成 positive observation 的 scorer smoke；相应全一 bootstrap 得 [1,1]。它不是 BrachyBot 人机端到端样本，更不能作为总体误差为零的证据。

建议把这类结果放 “harness validation”，命名为 expected-positive self-test／expected-negative sensitivity。正式模型结果需要实际 SUT、有限独立样本的不确定性和真实审查。简单独立二元率可报告 exact/Wilson；场景相关层级结果用预注册分层／cluster 方法，并考虑全成功边界退化。

### AUD-29：部分得分、N/A、安全优先级与 owner 约束不一致

`tools/scoring.py` 仅 passed=True 才保留 oracle.score；检索 R@2=.5、低于阈值时，诊断分被压成 0。这可作为二元 pass 规则，但不能称细粒度部分 credit。

未通过 invariant 就标 hard_breach，包括“证据不足”而非确认违反；之后 uncalibrated／coverage return 又先于 hard_breach，可能把已确认安全违规隐藏成 N/A。efficiency owner G 的处罚实际影响其他轨道总分；缺测／非适用还需与真实错误分开。

建议：gate 独立；维度分保留合法 partial score；confirmed breach 优先，有 evidence gap 仅 Insufficient；预算／效率不要在多轨重复扣分。calibration 的有效身份和结果不可由 task 或 obs 单个 true 解除。

### AUD-30：高级统计函数目前不能按名称作为已实现能力

`tools/analysis.py`：

- power_curve 是 paired normal approximation，不是设计要求包含场景随机效应、重复、缺测、Holm 和实际分析模型的仿真；无 Holm 时还固定使用 1.959964 而忽略 alpha。
- icc_decomposition 从平铺 cluster vector、一个 n_runs 标量声称分解 scenario/member/run，无法识别三层独立方差。
- Kendall sensitivity 对 `base_scores` 按 weight elementwise 相乘，给每个 SUT 不同权重，而非所有 SUT 共用 track weights；ties 处理亦不完整。
- Rasch infit 实现 `sum(w*resid²)/sum(w)`；平衡 2×2 反例输出 .25，预期 `sum(resid²)/sum(w)=1`。官方 Winsteps 给出后者定义。[Winsteps infit 计算](https://ftp.winsteps.com/winman/misfitdiagnosis.htm)

建议这些暂时标 prototype/exploratory，先与可靠独立实现对照；主论文不需要堆满 IRT/AHP/ICC。优先保证明确 estimand、paired comparison、case-level bootstrap、真实 safety bounds、费用延迟。SUT×dimension 矩阵才用于共享权重敏感性。

### AUD-31：规范文档的版本与表述需统一；权重求和指控已撤回

**数值勘误：**原审计写“display composite 权重相加为 1.10”，该判断错误，撤回。设计文档 §10.3 与实现报告 §8.6 的权重为 `0.18 + 0.17 + 0.12 + 0.00 + 0.06 + 0.05 + 0.08 + 0.06 + 0.05 + 0.04 + 0.06 + 0.03 + 0.10 = 1.00`，无需据此修改权重、增加归一化或重算历史成绩。

其余问题应单独讨论：设计不同段落仍混用最小 paraphrase group 与独立 scenario。报告 §24 的 EXT pins “8/8 未获取”与后续 11 active acquisition 叙述需要注明时点和范围；“deterministic kernels must be turned off”应准确区分 cudnn.benchmark、TF32 与 deterministic algorithms。这些主要是版本一致性和编辑建议，不与已撤回的数值指控混为一谈。

建议把 normative schema／estimand／split／freeze manifest 定为单一版本；主报告由这些生成，旧 issue log 明确日期和已过期状态。checksum 只能冻结文件，不能证明冻结内容正确。

## 8. EXT 复用：可下载不等于当前 adapter 可横向比较

### AUD-32：部分 adapter 改变原任务、丢结果或自报评分

- EXT-12 AgentClinic 目前只给 doctor objective 一次调用，没有 patient interview／test loop，还泄漏诊断；不能称原 AgentClinic 交互任务评测。
- EXT-2 run_task 只保留 text/trace，score 要的 gradings 不闭合。
- EXT-3 ABRA run_task 没保留 score 需要的 final_state，UI outcome 验证缺口。
- EXT-13 AMEGA 接受 SUT 返回的 criteria_booleans；如果来自未受控被测侧，属于自己评分。
- 多个 EXT 不执行传入预算，记录 wall_clock_s=0、tool_call_count=0、partial_status=COMPLETED；不能做效率／真实失败率横比。
- 长记忆基准把全历史拼成输入时，测的是 long-context reading，不一定是持久记忆／跨 session 检索；要分开标。

建议：保持上游任务环境和 scorer；gold 隔离，保留所有 scorer 所需结果。改写成静态 QA／新 prompt 的应标 adaptation，独立报告，不声称与 upstream 原榜等价。医疗诊断 QA 可作辅助沟通／知识能力，不挤占 BrachyBot 的影像→规划→剂量→导板→报告→Monitor 核心实验预算。

EXT 的 E0 PASS 只表明 gold-fed／离线 grader 示例能执行；BLOCKED 仍是诚实状态。获取许可、下载 revision/hash、真正 SUT 执行、原环境闭环与 scorer 一致性均要单独验收。

## 9. 结合 BrachyBot 愿景，最应补的有效场景

这里不是新关键词白名单，而是**每个底层状态契约都由不同自然表达和扰动组合验证**。

| 真实能力 | 必须观察的成功证据 | 当前缺口与推荐 |
|---|---|---|
| 当前病例状态／OAR 自知 | 逐器官指标、来源 artifact、病例／计划版本与 Analysis 一致；必要只读查询无需再次授权 | 从真实 53-OAR case 开始；禁止把“已分割体积”冒充“受照剂量” |
| 多需求拆分 | 目标—动作—参数局部绑定；独立失败不阻断无依赖任务 | 既测输出文字，也测每个 effect 和 receipt；不同工具组合可等价 |
| “全部更新”与指代 | 上文明确范围；最新 dose 后 QC／评分／guide／report 依赖正确、没有不必要重算 | 序列题，不用单句 update all 替代 |
| 显示隐藏／颜色／opacity | Data Tree、Viewer、模型状态、保存／恢复一致 | 同名对象稳定引用；CT/action substring；每 viewer 独立 pan/zoom |
| 手动 step-by-step | init artifacts 与 close points 共节点可见；下一步隐藏；reload 后可恢复 | 实际 UI actions + API/scene readback；不是 computed=true |
| 截图定位 | 图像确实回传／附在对话；对象可见、标注命中、ID不覆盖；回复不否认证据 | G/J/M 专门纳入；分目标截图并排；occlusion 用真实像素或盲评 |
| 截图临时状态 | 原本可见则保留颜色和上下文；挡住目标时最小 hide/refocus；finally 恢复 | 逐项记录 visibility、opacity、camera before/after；不靠文字“已恢复” |
| 报告图件 | 按目标 fit camera；不同图角度／占幅清晰；i18n 图注与全局语言一致 | 真实报告渲染与 export；禁止只匹配 section 字段 |
| 运行链 UI | 最终回复、工具 pending、发送／停止按钮、SSE terminal 一致；重复 Final response 不出现 | browser 时间线：断流／晚到／取消／刷新／恢复；模型返回只是中间状态 |
| Monitor 教学闭环 | preview/commit、baseline、edit-specific/cumulative delta、风险位置图、建议、用户选择、granular undo | 必须完整 J 事件序列；截图交付与版本 fencing；重算 opt-in／预算可查 |
| Monitor 生命周期 | stop lease 真关闭；停止后旧反馈丢弃；可重新 start；语言持续一致 | 退出／引用／否定／重复点击／服务端 timeout＋恢复组合 |
| 病例／session／user 隔离 | 旧病例 site、memory、artifact、undo 不进入新病例；真实服务端拒绝 | 两用户多 session 隔离沙盒，不仅输入 actor/owner 字段 |
| 分割与剂量物理 | 各部位真实 label 语义、physical geometry、grid、seed orientation 与独立 reference | 头颈 GTVp/GTVn、鼻咽 NCCT/CECT、未知部位不猜模型；A3a 与 agent 分开 |
| 交互效率 | first meaningful feedback、最终可用结果、截图恢复、报告保存的 p50/p95/tail | G 轨不得为 0；按轻量问答／UI／截图／GPU 重算分层 |
| 长程记忆／压缩 | 当前 context 与 turn-total 分开；压缩后病例事实可追溯且不混病例 | 真正长会话／跨 session，而非所有 facts 已预置 observation |

独立实验层建议：

1. **Component/regression**：保留现有大库，验证 checker 与契约，低成本每提交运行；不作 agent 排名。
2. **α 编排**：相同工具能力 shim、相同观测权限，使用真实需求和 private effect gold；不触发昂贵物理引擎。
3. **β 端到端**：隔离病例、真实模型／剂量／产物、持久化、独立导入与质量判定；费用单独报告。
4. **γ 浏览器协作**：共享真实 UI action surface，验证截图／报告／Monitor／生命周期；纯文本 agent 不适用项标 N/A，不能凭它没有 UI 判 0。
5. **人工交互实验**：只有要声称教会用户、减少工作量或提高信任时做；专业建议分和真实体验改善不是同一个结论。

## 10. 推荐修复路线：先测量正确，再扩规模

### 阶段 A：可信边界与负对照，最高优先级

修 AUD-01…08、11…18：public/private/observation 分离，真实结果采集，no-op 禁止伪通过，finite/schema fail-closed，实际安全和独立文件解析。

必须通过的无模型验收：

- reference-copy、null、no-op、fabricated-success、wrong-case、wrong-version、unrequested-mutation、NaN、missing-data、wrong-attachment 等对照。
- 正确合法路径、等价工具路径、合法 re-export／remesh 不被错杀。
- known breach + missing field 仍报告 confirmed breach；纯缺证据为 Insufficient。
- evaluator 配置不能被 task-visible prompt／SUT observation 篡改。

这些修复不能靠降低阈值／更新旧断言使它们全绿。

### 阶段 B：一个小而完整的真实纵切

先选 30–50 个高价值、互不等价的独立场景，覆盖：当前计划/OAR查询、授权显示导板、双目标截图、全部更新、Monitor stop/start、一次针道提交→风险→截图→keep/undo、报告渲染/i18n、断流终态、跨病例隔离。

每场景先跑 scripted/oracle/null 对照，再实际 BrachyBot；同一环境允许其他 agent 用相同 shim/UI API。case hydration→观测→执行→产物→交付→恢复→独立评分全链闭合后，再扩大样本。

### 阶段 C：重新组织真实场景和 gold

把当前 11,819 authored 分为真实任务、组件契约、参数扫描、表达扩写、判分器 smoke 五类；150 physics probes 单列。独立专业标注主任务 gold，保留灰区 acceptable actions、确认流程、合理澄清，删除或改写“当前 parser 行为即正确”的题。

围绕独立病人／源数据／机制增加多样性，不为凑万题再复制模板。中文与英文配对设计；开放题专家盲评、校准和仲裁；fixture 生命周期真实且同版本。

### 阶段 D：冻结统计与公平比较

解决巨分量和空主轨 sealed；明确 SSR_scenario、repeat、缺测规则、安全单侧上界；补真实 paired-model power simulation。统一 run record 与汇总、权限、预算、模型版本、缓存、人工参与，实际执行 n_runs。

主结果建议：B-α SSR_scenario + 安全门槛 + β 关键产物／物理质量 + γ 交付／恢复 + 成功率-成本前沿。其余轨道作为多维 profile；不依靠 display composite 宣称“总体最好”。

### 阶段 E：有目的地扩充并准备论文

在科学有效性通过后，按 power 与稀有安全事件需求决定独立场景量；表达与 repeat 服务鲁棒性，但不膨胀独立 n。发布 Benchmark Card、数据／代码许可、污染／开发曝光声明、真实失败例、裁决误差、可复现结果包。

优先投资 G/J/M 和真实头颈／多部位病例，而不是更多内部模块名字题。独立物理 reference、临床可接受性和教学效果分别验收，不能被“工具跑完”替代。

## 11. 如何使用逐题记录，不把自动 flag 误读成裁决

解压后按 ID 可对应原题、原文和判分风险；修改题目应记录旧／新版本与理由，不原地抹去过去结果。

- `both_noop_meets`：已复现的 parity-completion 缺口，优先检查对应任务 postcondition。
- `empty_observation_meets`：待逐题区分合理 no-write 与假完成，不能一律删除。
- `raw_response_not_bound_to_scoring`：回答类题必须绑定，纯数值题可不看 prose。
- `no_task_owned_primary_expectation`：可在私有 evaluator 文件定义，不要求公开 gold。
- `audit_not_required`：安全／副作用题要求真实 audit；无副作用数学题未必需要。
- `no_guideline_ref`：软件契约题不必指南；临床阈值结论必须有来源／方案。
- `public_task`：开放 dev/public 合法；不说明 sealed 自动保密。
- `no_protocol_events`：是实现／schema 现状，不是要求每道单轮题都加 event；J/γ 必须由真实外部 harness 驱动。

`contradictory_prompts` 列表仅供人工核对同请求不同 tool policy／fixture；有些差异是合理等价实现，不应机械当矛盾。

## 12. 已有工程应保留的优点与本次结论边界

值得保留：分轨设计、三态 verdict、单题与总体安全率分离、A3a 不混入 agent 分、N/A／基础设施失败概念、positive/negative replay 自测、固定 hash／环境、可插拔 adapter、现有 capability registry、对未冻结／未实跑的公开披露。

原生工具本次复核：schema 11,969/0；quality_audit 11,819 项的五类计数均为 0；coverage 707/707；hash_manifest check 通过。**这些结果与本报告的反例同时成立**，说明需要扩展校验的含义，不是现有校验全部无用。

未完成独立临床 gold 全量人审、真实 GPU／browser／病例实跑、第三方模型横评、外部全量上游 scorer faithful-equivalence 检验。没有把本文检查推断为产品本身对应漏洞已发生；如需要修生产行为，应另外基于真实运行证据处理。

最后建议：**把 benchmark 本身也当成需要被测的系统：先证明它能拒绝错误、接受等价正确、在缺证据时诚实 abstain，再用它判断 BrachyBot 是否聪明。** 万题规模是资产，但可信的测量闭环才是大文章的核心保障。
