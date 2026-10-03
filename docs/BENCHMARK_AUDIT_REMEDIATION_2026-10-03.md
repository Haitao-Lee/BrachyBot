# BrachyBench 独立审计修复：已实施内容、验证与剩余阻塞

日期：2026-10-03。对应冻结审计：`docs/BENCHMARK_INDEPENDENT_AUDIT_2026-10-03.md`，AUD-01 至 AUD-32。

2026-10-03 文档勘误：原审计现已显式修订 AUD-31 的权重错误和 AUD-25 的证据等级，并增加基线时点说明；修订前冻结版本、SHA256 与本次文档修订记录保留于 `docs/audits/benchmark-doc-errata-2026-10-03/`。本次文档勘误不改变上轮代码部署或测试结果。

## 1. 结论与适用边界

本次实施的是 **benchmark 测量与运行基础设施的修复**，不是在线 BrachyBot 规划算法或 UI 的修改。优先修复答案泄漏、被测侧控制评分、no-op 假完成、缺证据假通过、错误几何与统计、结果记录丢失等共性问题。

已经新增 public/private 输入边界、独立采集/回答/本轮完成验证接口，并修改现有 checker、runner、汇总与外部 adapter 公共层。没有批量修改历史任务、gold、replay、sealed assignment 或历史成绩，也没有因旧断言失败而放宽阈值。

**不能据此声称 benchmark 已完全修复或可以支撑论文主实验。** 当前库仍缺 G/J/M 实际场景、独立场景身份和可靠私有 sealed；部分历史 fixture 与修正后的测量不一致；真实病例、浏览器交付、独立物理参考、临床人审与外部原环境保真尚未闭环。这些不是多写几个通过标志可以解决的问题。

## 2. 基线与隔离

- 仓库：`/home/lht/snap/brachyplan/BrachyBot`。
- 本轮起始 HEAD：`7aa6d23086072b593beba069f8c2116d01c3c0f3`；工作树已有大量用户未提交修改，因此不能用 HEAD 单独代表实验版本。
- 每个实际修改文件记录原始/修改后 SHA256；发布前逐文件验证原始内容，拒绝覆盖期间发生变化的文件。
- 验证在 `/tmp/brachybench-remediation-20261003-baseline` 与 `...-workspace-v4` 中进行，不使用生产 benchmark 的 results 目录。
- pytest/pypdf 安装在独立临时 venv；未更改生产依赖、未调用收费模型或 GPU 推理。
- 首轮压缩源快照缺少一些 provenance 引用文件，造成基线的一项 grounding 失败。随后从真实仓库复制这 30 个源依赖到两边快照，记录哈希；没有用空文件伪造引用。
- 没有重启 8080，也没有修改病例、账户、模型、在线 UI、LAN/public-release 服务或 writable runtime。

## 3. 新执行契约

### 3.1 三种输入不得混在一起

`tools/evaluator_contract.py` 定义：

1. SUT-visible：opaque task ID、实际用户 turns/events、预算、允许看到的初始世界状态。
2. Evaluator-private：gold、期望状态、授权对象—动作—参数、物理参考、限值、rubric、来源场景 ID、实验身份。
3. Independently observed：实际状态、工具/副作用审计、导出文件、最终交付文字与附件。

PythonAdapter 不再把完整 task JSON 交给 SUT。嵌套 initial state 也去除 gold/expect/reference 等字段。外部 adapter 公共边界同样隔离 reference answer、诊断 gold、rubric、criteria 与自报 gradings。

**这是一条 Python API 信任契约，不是操作系统沙箱。** 不受信任的第三方 agent 不能与私有 gold 共用可读文件系统；正式横评仍需要进程/容器/挂载/网络权限隔离，并审计其实际执行路径。不能把 redaction 函数当作抗恶意读取的充分证明。

### 3.2 缺独立证据时 fail closed

真实 adapter 默认进入 formal 模式，但没有独立 collector 不得获得可信成功。正式 generic oracle 的测量字段必须列入 `observed_keys`；策略/参考来自 private `inputs`，不能由 observation 替换。

state_diff 除双路径一致外，还要求 evaluator-owned expected outcome；两边都不执行不再证明任务完成。没有本轮 terminal observation 时，不再拿 initial fixture 顶替。

单独的状态 predicate 不能证明本轮生成/更新了产物：正式 predicate 路径还必须接独立 completion checker，检查本 execution 的 receipt、版本、产物与请求范围。复用已经存在的 completed=true 不够。

如果任务需要回答，或者 collector 给出了实际 response，必须接独立 response checker 评估已交付的文字；SUT 自报 claims、reply flags、preliminary response 不能替代真实最终答复。

### 3.3 运行接口

新增 CLI 配置：

```text
--evaluator-config /private/evaluator.json
--collector evaluator_module:collect
--response-checker evaluator_module:assess_delivered_response
--completion-checker evaluator_module:assess_execution_completion
```

collector 的兼容形式：`collect(output)`；推荐形式：`collect(output, *, context)`。context 包含 private task、initial state 与唯一 execution_id，可用于关联真实数据库/文件/浏览器事件；不得转发给 SUT。

`EvaluatorContext.inputs[checker]` 是 private 策略/参考；`observed_keys[checker]` 是独立 collector 可提供的测量 kwargs。重叠字段始终由 private 输入覆盖。并非配置一个 `independent=true` 就算实现了独立采集；CLI 只有安装 collector 才设置 independently_observed。

可比较身份要求包含私有 scenario_id、sut_id、source_sha256 与完整 audit。新 run_manifest 可记录 evaluator_identity、evaluation_mode、comparable_sut_result。未知模型/系统提示仍会显示 unspecified 或占位值，**不应据此发布公平横评**；需要 harness 绑定真实模型版本、提示、工具 schema、环境、缓存与权限哈希。

## 4. 已完成的基础修复

### 4.1 工具、状态与副作用

- 工具授权可同时检查 allowed_tools 和同一子任务的 target/action/parameters；不能跨子句拼授权。
- 已知禁止工具/副作用优先报告，即使 decision 缺失，也不能被缺证据掩盖。
- StateInvariant 不再无条件忽略 version_fence/receipts；合法变动需私有显式声明。
- Receipt 检测重复 op_id；SideEffectAudit 按多重集合检查缺失、额外/重复记录，返回 exactly_once。
- predicate 的本轮完成证明和原始回答评估分开，避免“世界里原来有”冒充“这轮做了”。

### 4.2 几何、图像、坐标与产物

- 空规划、空种子/导板、缺 OAR 指标、非有限值、重复对象身份、无效网格 spacing 等不再按有效输入通过。
- HD95 改为两侧表面距离的合并 95 分位，保留相同表面的零距离；不是只对差异体素求距离。多标签 mask 不默默转成二值。
- 导板孔按稳定 ID 或一对一空间匹配比较，避免孔顺序变化误失败；检查 axis、entry、diameter/thickness 的有限性。
- 干涉改用最近距离、胶囊半径和表面间隙，不再把最近点在内部等同于碰撞，也不把端点接触天然视为安全。处理退化 segment；未知类别不默认算正确。
- formal interference 的物理几何来自 private geometry，SUT 只能提交分类，不能自己把参考半径改为零来获得通过。
- 坐标检查支持独立 physical reference；单纯自身 inverse round-trip 只能作为组件自洽，不是 patient-space 正确性的证明。
- PDF 必须被独立 PDF parser 真正读取；有 header、EOF、`/Type /Page` 字符串不够。独立 parser 缺失属于证据不足。
- IndependentParser 拒绝空解析结果，支持注入 STL backend；默认 PDF backend 也不再靠正则数页。
- roundtrip 拒绝空独立结果、截断坐标、非有限剂量，并比较独立 decoded dose；合法量化使用声明的 DoseGridScaling 半步容差。
- STL 不把正常 remesh 引起的 vertex/normal count 变化作为失败；仍需实际网格 parser 与空间比较，不是一个 watertight=true 字段即可认证。
- DICOM UID normalisation 保留引用图的等价关系，不再删除所有 UID 后忽视错误引用。跨多个文件的引用必须在整个 bundle 中共同验证，单文件归一化不足以保证跨文件正确。

### 4.3 安全、检索、人审与一致性

- 路径 allowed roots 按并集判断；合法子目录 parent resolution 不被误报。
- SSRF 识别实际 private/link-local IP 和 IPv4-mapped IPv6；相似公开域名不是 private IP。
- 缺 actor/owner 或 memory ownership 是证据不足，不是 None==None 或 unknown==safe。
- rubric 的字符串 "false" 不再被 truthiness 当作 true；人审明确拒绝不能被模型评分覆盖。
- retrieval precision 去重，重复相同文献不能膨胀命中率。
- 未注册的 guideline clause、无 resolver 的引用不再假通过。
- 空 semantic outputs 不证明一致；NaN 数值不被视为相等。
- 一致性与正确性分开；相同的错误答案仍可能一致，必须配合 correctness/response assessor。

### 4.4 运行与记录

- live_smoke 状态读取保存原 reader，避免递归；没有真实 fixture installer 时阻塞，不评测无关的当前病例。
- 工具 trace 保留 ret/result、参数与来源 artifact；未提供终态时默认 PARTIAL，不默认 COMPLETED。
- 非普通用户事件需要 event driver；浏览器完成需要 completion reader/collector，不静默跳过。
- CLI 实际执行声明的 n_runs，使用唯一 execution_id，为每次运行保存完整 record；infra failure 同样保存，不从分母静默消失。
- 遗留 bare oracle 结果可读取；有 full records 时避免把 oracle/observation/record 重复计数，不再优先忽略新结果而读旧 E0。
- 缺声明的 repeat 在 SSR 和安全分母中不能算作完整成功场景。
- 预算采用计时与调用边界检查；**尚不是强制杀死任意阻塞调用的进程级 watchdog**。硬超时/取消与会话清理由真实隔离 executor 补齐，不能宣称本轮已全部实现。
- 外部公共层保存候选 final_state/artifacts、计时与 SUT 调用次数；工具次数无法独立验证时记 unknown，不写假 0。旧 replay 保留为 component self-test，而非伪造真实调用。

## 5. 统计与得分修复

### 5.1 SSR 与不确定性

primary pass_rate 改为每个独立 scenario 等权、该场景所有已声明 member/repeat 成功才成功；item_pass_rate 单独保留诊断用途。`score_report` 的旧 item-weighted 汇总明确不是 SSR_scenario。

情景平均分的 bootstrap 按场景等权。Bernoulli SSR 采用双侧 exact binomial interval，避免全正向 replay 的 `[1,1]` 被解释为总体确定性成功。完整的 private 场景/member roster 仍由实验协议提供，否则缺整场景或整 member 不能仅从 observed records 推断。

### 5.2 安全门槛

- 只有独立、audit 完整、可判、无证据缺口的完整场景才进入安全率分母。
- Insufficient/infra/missing audit 不冒充零违规。
- 已确认 invariant breach 按场景汇总，不把所有普通任务 DNM 都当成安全违规。
- 非零事件使用单侧 Clopper–Pearson 上界，不再把零事件 rule-of-three 套到非零失败。
- 40/400 的上界与 `scipy.stats.beta.ppf(.95, 41, 360)` 对照；约为 0.128，不是原先约 0.00746。
- 已确认安全违规优先于 uncalibrated/N/A/普通 infra，不用缺证据掩盖已观察到的违规。

K 轨仍须逐机制定义 postcondition/回归安全否决，不能只用 invariant 汇总替代 K5 的能力回归判定。

### 5.3 其他统计

- 合法 oracle.score 保留部分 credit，不改变 gate；非有限分数拒绝；预算/效率处罚只属于 owner G，不在其他轨重复扣。
- 状态相同但没有达到 private expected outcome 的 completion credit 为 0。
- Rasch infit 改为 sum(residual²)/sum(p(1-p))；平衡 2×2 对照为 1；输入必须为 binary/NaN，并标 exploratory。
- Kendall sensitivity 使用 SUT×dimension 矩阵，所有 SUT 使用相同的维度权重，并处理 ties；一维的错误接口不再接受。
- 平铺数据不能识别 scenario/member/run 三层方差；ICC 的不可识别分量返回 None，不编造分解。
- power helper 尊重 alpha，明确是 paired normal approximation；**没有冒充包含真实随机效应、重复、缺测和实际分析模型的 GLMM power simulation**。

## 6. Split 与正式实验准入

新 split commitment 绑定 task ID + canonical task content，不只 hash 位置索引。排序扫描目录；重复/空 ID 拒绝。未知 fault mechanism 不用每道题的 ID 伪造独立机制。已有 assignment 原样保留；新格式必须使用单独目录/version，不能原地重新冻结已曝光的 sealed。

生成 commitment 不等于提供 secrecy，字段明确 `secrecy_verified=false`。不再先写出 sealed 明文 membership 再覆盖掉。旧 index-only manifest 的 check 返回 BLOCKED，要求保留历史证据并版本化迁移。

`tools/audit_readiness.py` 是只读 inventory，不是自动临床认证器。本轮读到：11,969 道题，G/J/M 各 0；source scenario_id 为 0；已有 split 为 legacy index-only，且缺 private membership/secrecy 证明，因此输出 BLOCKED。

它不会因为数量、schema 或 coverage 全绿而声称正式实验就绪。需要独立专家、source grouping、未曝光 private task、真实 executor 与观察证据；当前库不具备这些证明。

## 7. 验证结果与旧断言差异

定向：`test_independent_audit_remediation.py` + `test_ext_adapter.py`，**73 passed**（70 个新正/负对照 + 3 个既有外部 replay 契约测试）。包含有效 PDF、合法路径并集、孔重排、合法剂量量化与改 UID 引用图的正对照，也包括 no-op、wrong reply、NaN、空 parser、缺 repeat、重复 receipt、漏 infra 记录与假 calibration 等负对照。

完整隔离基线：**24,131 passed**，3 个已有 SWIG DeprecationWarnings。

最终完整修复版：**23,986 passed、215 failed**，3 个 warnings，139.09 秒；不把定向通过替代全量通过。总计 24,201 条收集项，等于基线 24,131 加 70 个新增测试；两次使用同一隔离 venv 与完整源依赖。语法 compileall 与补丁 whitespace/check 均通过。

215 条旧断言包含 204 个 parameterized replay case 与 11 个单元/批量断言。旧断言涉及伪 PDF、空独立解析、自动忽略 receipt、删除 UID 关系、错误 ICC/Kendall 输入、item-weighted 平均、安全缺审计默认通过、非 owner 跨轨扣分，以及依赖旧几何/缺失数据的历史正负 fixture。

**不应把 215 个失败全部自动归为“旧题错了”，也不应把它们自动归为产品回归。** 每个改变需要独立参考重新裁决。`tools/audit_replay_changes.py` 输出 assertion、task hash、旧正/负角色、新 verdict、violation/evidence-gap codes；未改 gold，也未使用 xfail/skip 隐藏差异。某些负 fixture 在新物理定义下通过，应复核其究竟还有什么独立缺陷，而不是强行恢复旧分类。

当前不宣称“既有回归无新增失败”。旧套件必须经独立 fixture 复核、版本化迁移并给出合法正/负替代之后，才能作为正式 release gate。

## 8. AUD-01…32 逐项实施状态

“基础修复”表示通用机制已实现并有负对照，不等于全量任务与真实实验已验收；“部分”表示还需要数据、harness、独立 gold 或科学设计。

| 审计项 | 状态 | 本轮处理与仍需完成 |
|---|---|---|
| AUD-01 | 基础修复/部分 | public/private 输入与 EXT redaction；仍需 OS 级隔离和 exposure 审计 |
| AUD-02 | 基础修复 | private oracle policy/reference + observed_keys；真实 collector 需按 checker 部署 |
| AUD-03 | 基础修复/部分 | 实际 response assessor 接口与缺证据 gate；专家/独立评分器未全量接入 |
| AUD-04 | 基础修复/部分 | parity + private expected outcome，no-op 不再完成；325 题 private outcome 仍需独立标注 |
| AUD-05 | 基础修复/部分 | 初始状态不顶替 terminal；predicate 要本轮 completion checker；逐产物 receipt/version 契约需真实 collector |
| AUD-06 | 基础修复/部分 | reader 递归修复，缺 installer 则阻塞；病例 fixture installer 未完成真实验证 |
| AUD-07 | 基础修复/部分 | ret/参数保留、event/completion hook；浏览器交付和恢复仍需实跑 |
| AUD-08 | 基础修复 | effect 级局部授权、缺字段不掩盖 confirmed breach |
| AUD-09 | 部分 | repeats/唯一 execution/记录/预算检查；硬超时、强隔离与清理尚缺 |
| AUD-10 | 基础修复 | full record、legacy compatibility、去重、infra 分母与 repeat completeness |
| AUD-11 | 基础修复/部分 | empty/NaN/missing OAR fail closed；实际物理限值与几何独立计算需专业参考 |
| AUD-12 | 基础修复 | 表面 HD95、spacing/mask 校验与共享表面负对照 |
| AUD-13 | 基础修复/部分 | seed/guide 有限性、身份/孔匹配；制造学和真正网格独立 QA 未全部实现 |
| AUD-14 | 基础修复/部分 | distance/capsule/private geometry；历史物理 gold 需重新裁决 |
| AUD-15 | 部分 | 支持 private patient-space reference，拒绝空自洽；真实异方参考覆盖未完成 |
| AUD-16 | 基础修复/部分 | 真实 PDF parser、拒绝空 independent、dose/geometry/reference graph；真实 DICOM/STL bundle roundtrip 未全面验收 |
| AUD-17 | 基础修复/部分 | roots/IP/ownership 漏误判修复；DNS rebinding、系统调用级/跨租户真实拒绝需执行器测试 |
| AUD-18 | 基础修复/部分 | 严格布尔与拒绝优先；真实 reviewer 身份、校准和独立人审没有伪造 |
| AUD-19 | 基础修复/部分 | retrieval 去重、引用缺证据、receipt 重复；完整来源与实际应用状态仍靠 collector |
| AUD-20 | 基础修复/部分 | 空一致性不通过、正确性和一致性分开；每项 consistency 仍应配正确性判定 |
| AUD-21 | 尚需独立数据工作 | 没有继续从产品 parser 批量生成 gold；现有 parser-derived gold 需要专家重标 |
| AUD-22 | 尚需真实场景工作 | 没有将组件任务冒充真实用户场景；新增纵切任务必须有可执行环境 |
| AUD-23 | 部分 | source grouping/readiness 显式不足；不以改名/增 ID 伪造独立 n |
| AUD-24 | 尚需逐题裁决 | 原文/工具 gold/跨语言/长程矛盾保留待审，未批量机械改答案 |
| AUD-25 | 部分 | content commitment、保守 grouping、secrecy/legacy gate；未曝光新 sealed 需重新设计 |
| AUD-26 | 基础修复/部分 | scenario 等权/all-members success；private 场景/member roster 仍缺 |
| AUD-27 | 基础修复 | complete audited denominator、exact nonzero UCB、confirmed violation 优先 |
| AUD-28 | 基础修复 | exact Bernoulli interval，replay 不作总体有效性证据 |
| AUD-29 | 基础修复/部分 | partial credit、confirmed breach/N/A/owner 顺序；真实 judge calibration 身份需外部材料 |
| AUD-30 | 基础修复/部分 | infit/Kendall/alpha 修复，不可识别 ICC 和近似 power 明示；真正 mixed-model simulation 未实现 |
| AUD-31 | 数值指控撤回；版本建议部分完成 | 权重之和正确为 1.00，无需修改或归一化；原审计已勘误，版本/措辞及 normative protocol 仍需统一 |
| AUD-32 | 基础修复/部分 | EXT 边界、候选结果/计时、禁自评分、replay 标记；上游环境和官方 scorer 保真需逐 adapter 实验 |

## 9. 原审计勘误与证据边界

### 9.1 合成权重与分集证据勘误

原 AUD-31 的“权重相加为 1.10”错误；设计 §10.3 和实现报告 §8.6 的 13 项权重之和为 **1.00**。撤回该数值指控，不改正确的权重，不重算历史成绩。保留版本一致性、acquisition 表述时点和确定性执行措辞的建议，但不将其当作已证实的权重错误。

AUD-25 的最大连通分量 10,122、重建 sealed 各轨数量来自审计重建，与实际冻结 sealed 私有成员清单的独立验证不同。公开仓库没有足够成员证据时，只能据此指出设计风险及验证缺口，不能认证实际 sealed 必然具有该组成。需要私有 roster、内容承诺及冻结配置核验，不应公开已封存答案或成员来替代盲化治理。

原审计的代码级问题属于修复前基线。当前已新增 sanitized SUT 输入、EvaluatorContext、独立 collector、response_checker 和 completion_checker 等接口；接口存在不等于真实采集和端到端交付已经接通。修复效果应按当前代码重新运行独立反例验证，不能直接照搬旧行号或把旧漏洞描述当作当前事实。上轮全量结果仍为 23,986 passed / 215 failed；不能将 215 项统一认定为旧 gold 错误，也不能声称全量验收通过。

### 9.2 外部 benchmark 编号

原冻结审计 AUD-32 写“EXT-3 ABRA”，编号不正确。当前代码 **ABRA 是 EXT-1；EXT-3 是 MedSafetyBench；EXT-14 是 MedPhysBench**。本轮在公共边界保存 ABRA 所需的候选 final_state，但这不代表其 OHIF/Orthanc/tool trajectory/outcome 上游评测已经闭环。此处明确勘误，原审计作为历史记录不静默重写。

HealthBench 原 scorer 的独立 gradings、AMEGA 的真实独立 criteria 评估、AgentClinic 的 patient/test 多轮环境，不能通过接受 SUT 自评分或一次静态问答来补齐。wrapper 将非保真运行显式标记，不把它们放入官方等价 leaderboard。

## 10. 下一阶段必须实际完成的工作

1. 在隔离 case/session 下接通一个真实纵切：fixture hydration → actor 执行 → out-of-band state/audit → browser delivery/restore → artifact parser → response/completion assessor；先跑 oracle/null/wrong-case/fabricated-success 对照，再跑真实 BrachyBot。
2. 独立裁决 204 个 replay case 和 11 个单元/批量差异；变更 gold 必须另立版本、来源和审核记录，重新跑整个套件。不要只改 expected verdict 让 CI 变绿。
3. 从真实高价值用户需求建立 30–50 个初始独立场景，覆盖当前/OAR 查询、显示导板、双目标截图、全部更新、Monitor edit→风险→截图→keep/undo、stop/start、报告图件/i18n、断流终态、跨病例隔离。
4. 建立 source scenario/member/repeat roster，按真实患者/数据源/机制/grouping 做分组；重新冻结未曝光 private sealed，主轨 B/D1/L 覆盖和 G/J/M 不再为空。
5. 获取独立物理/临床参考与专家复核；不能把工具跑完、原 parser 输出、旧 gold、软件默认阈值当作临床正确。
6. 明确真实分析模型和 primary estimand 后，执行 paired mixed-model power simulation，冻结缺测/安全/比较协议，再按独立 n 而非扩写题数决定规模。
7. 对每个外部 benchmark 用原任务环境、官方 scorer 和真正模型输出做保真验证；改编协议单列，不声称原榜可比。

以上涉及真实环境、专业标签与实验设计的环节不能在本轮以配置字段代替；本次没有伪造它们完成。

## 11. 发布和证据位置

本次补丁仅涉及 26 个 benchmark 文件和本报告（共 27 个文件）；逐文件原始/新 SHA256 与补丁、完整测试日志、依赖补齐记录、readiness 和逐案例复核队列保存在：

`docs/audits/benchmark-remediation-2026-10-03/`

其中 `baseline-full.log`、`after-full.log`、`targeted.log` 和 `review-queue.json` 可直接核查本报告中的数字和每项失败。`change_manifest.json` 绑定实际补丁内容；原文件备份位于 `/tmp/brachybench-remediation-20261003-before-publish`，同时打包留存在证据目录。没有使用 git reset/checkout、强制覆盖或重启服务。

复现时须使用新的隔离 results 目录；不要在生产 checkout 执行会写入默认 results 的全量 smoke。原版正向 replay 的全绿只说明原组件契约自洽；本次失败记录展示哪些结论仍需重新裁决，两者不能相互替代。
