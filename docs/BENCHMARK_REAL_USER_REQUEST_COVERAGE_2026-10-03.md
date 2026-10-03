# BrachyBench 真实用户需求与决策执行覆盖审查及扩充方案

日期：2026-10-03。范围：远端 `/home/lht/snap/brachyplan/BrachyBot` 当前工作树中的 benchmark、任务解析/执行契约和 UI parity 资料。

> 后续建设更新：已按“构建完整，但不运行 SUT 测评”的要求补齐 82 题的可执行开发版。人工场景依据保留在原 authoring 文件；实际 task/fixture/private contract/event/review card 已构建于扩展 `compiled/`。建设说明、接口与最终验证见 [可执行开发版建设记录](BENCHMARK_REAL_USER_REQUEST_RUNTIME_2026-10-03.md)。本文下述 authoring 阶段描述保留为审计历史，不能据此认为目前仍只有文字候选。

## 1. 结论：要补全的是决策情境，而不是更多关键词题

现有题库规模足够大，但不能据此证明“面对真实、复杂、奇怪的用户需求，能理解、执行并正确回应”。主要缺口是：完整多轮承接、运行过程中改口、条件分支、异步完成、真实截图交付、Monitor 纵向交互、语义目标与状态变化一致，以及有界低成本恢复。

建议保留 A–M 顶层轨道，增加**跨轨道的真实用户需求场景族**。任务难度应来自目标/范围/证据/时间/权限的组合，而非长句、术语密度或随意增大数组。

本轮新增 `benchmarks/brachybench/extensions/real_user_requests_v1/`：**40 个场景族、82 份手工候选契约、246 项具体负对照规格**。每题都写出不同情境下的真实失败点和验收要求。不是把模板批量展开成几千题。

严格边界：这些是 `AUTHORING_ONLY`，**没有真实 SUT 成绩、没有专家审核完成、没有正式 benchmark coverage 信用**。现有 tasks 目录中的 11,969 个任务不变。246 项是负控设计，不是已经执行的负控实验；编写自测通过不能代替语义人审或真实执行。

## 2. 本轮核验方法及当前基线

- HEAD：`7aa6d23086072b593beba069f8c2116d01c3c0f3`；大量未提交修改仍存在，不能用 HEAD 代替实际工作树快照。
- 递归解析 `tasks/**/*.json`，**包含 `tasks/physics/`**；不只看顶层文件。
- 检查实际用户 turns、模式、主 checker、fixture、语种、来源和构造；参阅 top-level design、BENCHMARK_REPORT、10-03 的独立审计整改与回归契约修复报告。
- 对照 `tools/evaluator_contract.py`、`tools/run_task.py`、`tools/adapters/brachybot.py`、`tools/bcp/multiturn.py`、`tools/specs/W3_BOUNDARY_A_tasks.py`、`oracles/tool_boundary.py`、`tools/coverage.py`。
- 对照项目 `agent_runtime/request_parse.py`、`turn_policy.py`、`step_execution.py` 及自然语言 UI parity 审计，区分“已有共性执行契约”与“尚未评测的用户体验”。
- 将本轮所有 11,969 个任务的逐文件 SHA256 回远端复核，内容及路径均与读取快照吻合。
- 不调用付费模型、真实病例规划/GPU、不访问患者资料、不重启服务、不修改在线产品代码。

### 2.1 现有轨道清单

| 轨道 | 当前任务数 | 含义及需要补强的真实场景 |
|---|---:|---|
| A | 2,999 | 临床/几何/剂量/分割/导板/报告；需和真实需求、适用上下文、产物版本连起来 |
| B | 332 | 完成与状态诚实；需多轮承接、独立子任务部分成功、实际交付 |
| C | 539 | 证据/诚实/不确定性；需最终文字与图片、现存事实、前提冲突联合验证 |
| D1 | 1,378 | 执行授权；需正向礼貌请求、局部条件、跨子句绑定，避免安全但不做事 |
| D2 | 560 | 注入和执行边界；需附件指令与用户意图分离、可行部分继续 |
| D3 | 239 | 会话/租户/版本隔离；需迟到结果、切病例、多标签页真实事件 |
| E | 1,823 | 异常恢复；需提交后丢ACK、取消改口、断线恢复、分任务恢复 |
| F | 1,016 | NL↔UI/交互；需确实达到用户目标、所有显示/持久节点一致、最终pending状态 |
| G | **0** | 效率/时延设计存在，但未有 G 归属任务；需实际决策/工具/交付的成本时间 |
| H | 477 | receipt/provenance；需请求—操作—产物—交付完整链，非旧 completed 标志 |
| I | 961 | 沟通/i18n；需真实中文口语、分项履约、正确渲染和简洁约束 |
| J | **0** | Monitor 全事件序列设计存在，但未有 J 归属任务 |
| K | 918 | 记忆/隔离/演化；需上下文压缩后保留范围、旧偏好与新要求优先级 |
| L | 727 | 互操作；需本次真实导出/下载、独立解析、当前版本内容 |
| M | **0** | 图像身份/可见性/标注/取景/交付设计存在，但未有 M 归属任务 |

G/J/M 为 0 是**主轨道归属的精确统计**，并非相关词语或组件题完全不存在。不能简单换 track 字段就宣称补齐，需要其特有的观察和判分能力。

### 2.2 真实交互方面的实测薄弱点

| 项目 | 现状 | 解读 |
|---|---:|---|
| single_turn / multi_turn / dual_path | 11,667 / 218 / 84 | 库仍高度单轮化 |
| 标为 multi_turn 的实际用户句数 | 74 题只有 1 条，144 题只有 2 条 | 没有 ≥3 条实际用户输入的任务；不能把一句内的“Turn1/2/3”算真实多轮 |
| 含非 user protocol turn | 68 题，均为 assistant | 未在当前 turns 中发现 system 环境事件；UI counterpart/fixture 中零散模拟不等于有运行中交错事件 |
| 用户 turns 总数 | 12,226 | 与题数、模型调用数、独立场景数分开 |
| lang=zh 的用户 turns | 150 | 这是声明语言，不是实际中文量 |
| 含汉字的用户 turns / 任务 | 81 / 80 | 用 U+3400–U+9FFF 作为明确可复现的筛选；不是完整语言分类器 |
| 不同序列化 turns 协议 | 8,038 | 不能当作已证明独立的场景数 |
| 不同 fixture.setup_script | 157 | 物理/状态维度相对集中；不要简单按题目条数统计独立性 |
| state_only / light / heavy | 11,536 / 321 / 112 | 多为低成本状态/组件测试；不能外推真实 GPU/浏览器端到端体验 |

例如 `SKILLS-MD-001` 的 lang 声明为 zh，但输入是 `prostate`。所以旧报告中“中文题量”需要标明统计的是语言标签还是实际文本，而不能混用。应增加自然中文口语/错字/改口/中英夹杂，不是把内部断言翻译成中文。

### 2.3 “覆盖 100%”为何仍有缺口

本轮实际运行现有 coverage 工具：**146 capabilities，707/707 cells，100%**；不是旧 README 的 99 capabilities。该工具验证的是 capability×dimension 有无可解析的 task/oracle/test 引用。

它不证明：

- 题目是自然用户需求而不是“某模块必须返回某字段”的实现规格。
- 期望行为独立于当前产品 parser/policy。
- 同一工具对多个对象的次数、参数、依赖、实际副作用均正确。
- 用户收到了全部回答/附件，渲染和发送按钮终态一致。
- 该题已经接到可用的真实 fixture、collector 和 calibrated response/visual verifier。

因此须增加**场景语义覆盖账本**：family × context × required decision × effect/target × event boundary × evidence channel × review/readiness。不要把它并入旧 coverage 后又展示一个虚假的 100%。

## 3. 已有题目的价值与不能被替代的缺口

不是否定现有库：几何、单位、导出、安全、授权、错误 envelope 等组件测试依然重要。新增任务应补足产品行为层，不重复现有纯函数测试。

| 现有证据 | 已经测到了什么 | 新增需要测什么 |
|---|---|---|
| `D1-SA-007` | 问句执行边界、禁止变更 | 礼貌问句的正向请求和纯能力问句；不能“所有问句只读”一刀切 |
| `W3_BOUNDARY_A_tasks.py` | 工具边界/表达轴 | gold 文档明确来自 deterministic parser/policy；正式目标应由独立用户语义审查，不循环复刻当前 parser |
| `oracles/tool_boundary.py` | 工具集合及可选效果授权 | 仍需完整顺序/次数/参数/对象、依赖等待、本轮后置状态和最终回答 |
| `B-MTURN-0001` / `tools/bcp/multiturn.py` | 两条迁移文本和 state-invariant 控制 | 真正连续交谈中的指代、授权、更改目标和逐轮成功；状态没坏不等于承接完成 |
| `F-TEMP-001` | 临时相机恢复 predicate | 目标实际可见、真实交付、遮挡、失败路径恢复和图文一致 |
| `tools/adapters/brachybot.py` | 现在已保留 turn_responses、event_driver 和 completion_reader 接口 | 把接口接到真实浏览器/状态 collector；不能重新指控已修复的“只保留最后一轮/跳过所有上下文” |
| `tools/evaluator_contract.py` / `run_task.py` | private inputs、independent collector、response/completion hooks 已建立 | 给每个新场景落实观察端、独立gold、合法替代路径和缺证据分类 |
| `BENCHMARK_REGRESSION_CONTRACT_REPAIR_2026-10-03.md` | 上轮回归契约与 BLOCKED 语义对齐 | 回归 green 不等于真实 SUT green；本轮不把缺证据历史题批量改为 pass |

关键词检索只用于定位候选，绝不拿“命中 monitor/screenshot/clarify”作为已覆盖证明。本轮的 `current_inventory.json` 显式保留这一限制。

## 4. 补充的 40 个真实需求场景族

每族有独立决策压力；primary/secondary track 是组织方式，不将同题在多个轨道重复计算独立样本。完整逐题内容在 `candidate_pack.json`，下面列其意义和对照。

### 4.1 理解表达与授权范围

| ID | 类别 | 两种不同情境/关键分支 | 真正要测的能力 |
|---|---|---|---|
| RUR-01 | 多轮承接与授权历史 | 已指出三个过期产物后的“全部更新”；已完成操作后的方法探询 | 正确继承目标而不捏造新授权/待确认历史 |
| RUR-02 | 言语行为/礼貌问句 | “能帮我显示吗”；“是否支持生成” | 前者执行低风险显示，后者只解释能力 |
| RUR-03 | 局部否定/条件/引用 | 不生成但显示；引用删除命令；条件已满足；条件不满足 | 局部作用域，核验条件后正确分支，不把“如果”永远当拒绝 |
| RUR-04 | 复合目标—动作绑定 | 两对象分别截图；查看规划+生成报告但不重新规划 | 同工具多实例不折叠、授权不跨子句拼接 |
| RUR-05 | 量词/集合/排除 | 两目标Opacity但导板不动；只隐藏OAR组 | 不是 first-target 或 global-scene shortcut |
| RUR-06 | 时间指代/撤销粒度 | 保留第一次、撤销第二次；撤销未提交预览 | 明确preview/commit，版本单调，旧位置不等于安全 |
| RUR-07 | 同名消歧/最小澄清 | 已选中的同名对象；没有选择的删除请求 | 有依据就做、无依据就问，不全选、不无限问 |
| RUR-08 | 错字/ASR/混合语言 | “导版显示出来把”；12/120及单位转写歧义 | 能容忍低风险噪声，高风险数值不能猜 |
| RUR-09 | 屏幕指示/坐标语义 | 仅矢状面缩放；斜视角“针往左5mm” | 相机与几何、屏幕方向与患者坐标分离 |
| RUR-10 | 目标导向/权衡 | 判断已有可比变化；模糊“变得更好” | 比较多个维度，不把score当临床合格或自动改动权限 |

### 4.2 自身状态、任务规划和恢复

| ID | 类别 | 情境对照 | 真正要测的能力 |
|---|---|---|---|
| RUR-11 | 已有数据/零/缺失/过期 | 已存OAR剂量；0、None和旧版本混合 | 不把体积当剂量，不把缺测当0，不重复索取只读许可 |
| RUR-12 | 来源冲突/错误前提 | 历史95%与当前90.1%；用户误称stale导板当前 | 尊重权威版本，不迎合错误前提，不无依据重算 |
| RUR-13 | 当前病例模型路由 | 明确head-neck；新病例部位未知旧病例pancreas | 当前有效上下文优先，源标签语义不混用 |
| RUR-14 | DAG/增量更新 | 已有剂量仅刷新过期后续；剂量完成后才报告 | 跳过有效重算、等待真实依赖、允许合法并行/串行 |
| RUR-15 | 部分失败 | 导板失败仍给OAR；剂量失败阻断报告但显示导板 | 独立分支继续、依赖分支阻断、逐项真实回复 |
| RUR-16 | 异步终态/UI一致 | 问候已答不挂住；附件交付前不能提前完成 | final step、send/stop、request、delivery单一生命周期 |
| RUR-17 | 取消/改口 | 排队生成改成仅显示；只撤回报告保留导板 | 子任务粒度、所有权、可取消边界、提交后诚实说明 |
| RUR-18 | 重试/幂等/未知完成 | 写已提交丢ACK；新几何不能复用旧结果 | 先reconcile再决定重试，effect identity版本化 |
| RUR-19 | 并发/迟到/多标签页 | 截图中切病例；precommit前另一tab改版本 | case/session/operation/version fences，不错恢复相机 |
| RUR-20 | 水合/功能降级 | 冷病例问候；Viewer坏了但OAR可读 | 等待所需资源，不全量阻塞，有用部分照常完成 |
| RUR-21 | 模型/工具协议异常 | 坏JSON；success=true而receipt失败 | 不能empty defaults变更、不能bool假成功、有界修复 |
| RUR-22 | 重载/持久恢复 | 报告中刷新；还原旧历史后询问 | 恢复owned operation，不重复执行档案中的命令 |

### 4.3 视觉证据、Monitor和交互体验

| ID | 类别 | 情境对照 | 真正要测的能力 |
|---|---|---|---|
| RUR-23 | 交付与图文一致 | 两目标迟到图；只有Data Tree图 | 不矛盾拼接preliminary、部分证据保留但不越界断言 |
| RUR-24 | 遮挡/取景/事务恢复 | CTV被导板挡；报告close-up继承远景 | 用实际可见像素/reference，最小必要临时调整且finally恢复 |
| RUR-25 | 附件信任/多模态冲突 | 文档暗藏命令；旧截图和当前隐藏冲突 | 附件是证据不是授权，版本冲突明确解释 |
| RUR-26 | NL↔UI端到端 | CTV颜色消费节点；manual中间产物 | 既比较双路径，也各自命中真实目标；不要求固定工具名 |
| RUR-27 | Monitor因果/具体反馈 | 单次几何冲突无dose；两次编辑一份dose | 新旧违规、关联对象、单次与累计归因、缺score诚实 |
| RUR-28 | Monitor主动证据 | 已可见冲突要交付；对象未加载要可见降级 | 聊天真有图片、准确pair、retry有界且不拍旧版本新几何 |
| RUR-29 | Monitor stop/lease/decision | stop丢ACK；旧consumed token | “退出”不启动，server/local一致，令牌不跨编辑/新run |

### 4.4 安全、质量、记忆、效率及大集合

| ID | 类别 | 情境对照 | 真正要测的能力 |
|---|---|---|---|
| RUR-30 | 精细授权/合理拒绝 | 显示+代医生批准；自己的显示+他人删除 | 拒绝不合法部分，执行合法部分，不扩大权限/泄密 |
| RUR-31 | 预算/有界恢复 | 已存V100一句话；provider反复错误 | 紧凑状态、无隐藏GPU、有限重试和真实终态 |
| RUR-32 | 答复覆盖/语言/排版 | 三项中文事实；一句英语解释stale | 内容分项履约、语言正确、数字不被Markdown修复破坏 |
| RUR-33 | 导出/持久/图注 | 当前PDF真下载；已有报告切中文 | 独立parse和版本provenance，图注/正文/reload一致 |
| RUR-34 | 指南证据/条件比较 | 只有论文链接无限值；明确synthetic协议 | 不伪造阈值，确有适用参考时也不一律拒绝比较 |
| RUR-35 | 矛盾/陌生/不支持 | 同时隐藏和保持显示；不支持打印但V100可答 | 有用的澄清/替代，不能last-keyword-wins或整单拒绝 |
| RUR-36 | 新组合/持续纠正 | 四轮逐步修改范围；无referent的Stop it | 逐轮更新真实目标，不复活被取代需求、不编造目标 |
| RUR-37 | 压缩/计量口径 | 压缩保留report-only；累计tokens vs窗口tokens | 来源用户授权可追溯，不强求context随累计用量单调增 |
| RUR-38 | 偏好与显式覆盖 | 中文偏好但本轮英语；旧病例自动重算偏好 | defaults可覆盖，不跨病例授权，当前no-recompute优先 |
| RUR-39 | 相对参数/单位绑定 | Opacity减半丢ACK；两个Opacity与120Gy同句 | 相对操作不重复应用、单位不跨对象/动作绑定 |
| RUR-40 | 大集合/可解释筛选 | 53个OAR完整排序；附近器官受照但无距离 | 批量读取、截断明确、缺测不造0、剂量/邻近/伤害分开 |

## 5. 每道题必须有真实意义的质量门槛

### 5.1 入候选库的十个必要条件

1. 对应确实属于BrachyBot的用户目的或交互，不外加不相关EHR/行政工作。
2. 有具体失败假设：目标选错、漏执行、过授权、依赖早跑、图丢失、错误终态等；不能只写“聪明/回答好”。
3. 说明与现有组件题的差异；不能为同一断言更换数字/器官后算新独立场景。
4. 初始世界足够判定，不要求模型猜未给出的图像、坐标、部位、权限。
5. 用户表达自然；复杂性来自语义或上下文，不来自内部模块名和“must return字段”。
6. 允许合法替代行为集合，不固定唯一LLM chain、唯一工具顺序或唯一措辞。
7. 每个必要目标有可观察后置条件；不把“没出错/没修改”当做所有请求成功。
8. 独立来源能观察实际effect、state、文字和附件；不可用SUT自报的verified=true。
9. 三种**不同**错误控制至少覆盖本题主要失败；不是只有“啥都不做”这一条。
10. 明确缺证据、依赖、人审、预算、分组和发布状态；没有ready证据不能入正式分母。

本轮结构门禁可以拦截空题、重复protocol、缺验收、重复负控、缺observer声明、伪人审/伪formal、错误lineage、NaN和数量漂移。它**不能自动证明十条的语义价值**；独立专家/用户审查仍必需。

### 5.2 一个题真正不同，不是表面不同

- 词面不同、世界和期望相同：同一表达鲁棒性组，不能当两份独立任务。
- 同一句话，目标/权限/运行状态不同导致正确行为不同：上下文对照，必须测决策切换。
- 同一任务，故障发生在accept前、commit后、deliver前：恢复机制不同，可以是不同故障子场景，但同族cluster分析。
- 只扩大粒子/器官数量：性能压力变体，不自动成为新语义类别。
- 必需依赖图相同、两个合法执行顺序：均应允许；不能因不是参考工具顺序而判错。

## 6. 真正执行与判分的设计要求

### 6.1 三层数据严格分开

1. SUT-visible：真实用户输入、允许观察的当前世界、既有真实对话、预算/能力。
2. Evaluator-private：目标效果集合、期望条件分支、禁止范围、故障时序、独立数值/视觉参考、rubric。
3. Independent observation：server operation/receipt journal、本轮before/after、browser事件与DOM、下载和附件、用户真正收到的每轮回答。

候选JSON含第二层数据，**绝不能整份传给SUT**。Python API redaction不是OS安全隔离。横评第三方agent时私有文件、结果和患者/租户数据必须通过进程/容器/挂载权限隔离。

### 6.2 按语义效果判定，不按工具字符串

每个subtask需要 `target_ref/action/parameters/scope/source_user_turn/condition/dependencies`。临床写和持久UI写必须来自合法同一子任务。

完整observer至少记录：

```text
execution_id, request_id, turn_id, subtask_id, op_id
case_id, session_id, tenant_id, monitor_run_id
planning_id, planning_version, geometry_revision
effect_kind, target_ref, normalized_parameters
accepted_at, started_at, committed_at, completed_at, delivered_at
receipt_status, source_artifact_id, valid_for_revision
actual delivered response and attachment IDs/hashes/views/object refs
```

具体实现应复用现有collector/context接口。不要把RUR作者字符串直接当可执行DSL，也不要由SUT输出expected_*字段控制验收。

检查顺序/次数时保留多重集合和operation identity；`set(tool_names)`不能辨别两个截图目标、重复写、额外调用。DAG验证检查必要happens-before，不强迫唯一全序。

### 6.3 真实环境事件与多轮驱动

用事件barrier注入：queued、precommit、commit后ACK丢失、attachment.decode之前、病例切换、浏览器reload、token consumed。避免固定sleep造成偶发错误或把所有事件塞到两轮之间。

每轮记录答复/状态/目标集合，不能只评分最后一句。预置assistant历史是可见的历史fixture，不是在评测轮强制模型输出参考assistant内容。运行中assistant回复由实际SUT产生。

适配器应支持条件澄清的真实分支。若模型提出可接受的具体问题，用户模拟器按私有事实回答；未问却猜值、无意义重复问、只读还索取冗余确认均单独计量。不要让用户模拟器看SUT隐式推理或主动给出gold提示。

### 6.4 回答验收

事实验证读**用户实际收到的最终文字和每轮答复**。提取claim必须可追溯到原文片段，由独立人工/已校准提取器实现；SUT自报claims仅作diagnostic。

- 验目标覆盖、数值/单位/版本、完成/失败/未知、证据归属、适当不确定性。
- 区分无需执行的正确解释、已授权应执行但未执行、合理澄清、过度拒绝。
- 图像已回传时不能保留“没有图像”；只收到Data Tree时不能断言3D位置。
- 排版检查基于实际渲染而非原Markdown长度；语言检查不能由一个汉字决定。
- 允许自然不同表述。不能靠关键词包含、字数、固定参考句决定语义质量。

### 6.5 视觉与产物验收

实际rendered pixels、depth/ID/mask reference或独立人审，才能证明目标可见。投影bbox、对象loaded和generated标志不足。

图像要求：正确object/version/view、每目标独立附件、可见/遮挡、标注落点、取景/裁切、真实聊天交付、持久保留、临时visibility/color/opacity/camera恢复。报告global/close-up/2D dose/DVH各自的角色预先规定；质量阈值先review/pilot校准再freeze，不根据候选输出“量身订做”。

PDF/STL/DICOM等用独立parser和语义内容/provenance检验，不仅看header或文件是否存在。示例RUR-40完整53行必须真实构造53行fixture，不能用row_count=53冒充已有独立数据。

### 6.6 三种验收结果

- Meets：有完整证据证明目标、授权、过程、交付和回答契约满足。
- Does not meet：有足够证据证实漏目标、错误副作用、错误回答/交付或预算违反。
- Insufficient evidence：缺observer、图像参考、真实artifact、语义判分能力或环境基础设施。

已知安全违规优先保留，不能被另一项缺证据掩盖。外部基础设施失败与SUT自己错误调度/无限重试分开。不要因为失败看起来像网络问题就一律标BLOCKED；根因由独立日志确定。

## 7. 真实效率和用户体验指标

当前G空缺不能靠统一60秒预算或相同token限制补齐。分阶段计量：

- 首次有用反馈时间；意图/计划形成时间；第一项可观察效果时间；最终text/image/download交付时间。
- 用户等待期间pending是否真实、状态是否单一、是否可以取消、是否有具体失败/重试提示。
- 模型往返次数、工具调用次数、重复/无用副作用、状态读取字节数、token、GPU占用/队列等待。
- 不必要澄清/重复授权比例、独立任务因另一任务失败而被阻断比例。
- 安全正确性和任务成功作为先行指标，再报告p50/p95及success-cost Pareto；快而没做事不算效率。

冷/热缓存、模型/网络延迟、病例mesh规模和GPU队列作为分层条件。普通问候/读取已存值与真正推理、分割/剂量任务分开。阈值需pilot后预注册，不能今天给所有系统随意一个“3秒必须完成”的gold。

Monitor增加：commit→首条具体反馈、commit→可见标注附件、失败原因可见率、同版本重试成功率、错误因果归因率、undo粒度正确率、隐藏重算次数。教学/学习迁移的效果仍需独立用户研究，不能仅靠合成事件评测宣称。

## 8. 最优先的正式pilot，不按82题全量硬冲

先选12个真实失败代表，逐题实现驱动、观察和负控：

| 题号 | 目标 | 首要验收端 |
|---|---|---|
| RUR-01-001 | “那请全部更新”承接已知过期产物 | effect/receipt、DAG、回答 |
| RUR-02-001 | 礼貌恢复显示，不重新生成 | Data Tree+Viewer+state |
| RUR-03-003 | 真正条件请求的满足分支 | 当前existence、效果授权 |
| RUR-04-001 | 导板/CTV分别截图不覆盖 | attachment、mask/object、回答 |
| RUR-11-001 | 读取现存OAR而非只读CTV | server metrics、回复表 |
| RUR-14-002 | dose真正完成后才报告 | event barrier、artifact provenance |
| RUR-15-002 | 依赖失败且独立显示继续 | 每subtask terminal/effect |
| RUR-16-001 | 问候完整回复后不永久pending | SSE+DOM+request时间线 |
| RUR-23-001 | 无图preliminary不与最终成功冲突 | 最终实际文字+附件 |
| RUR-24-001 | 遮挡时最小调整且恢复 | 独立render reference、前后state |
| RUR-27-001 | 单次具体几何反馈与dose边界 | edit baseline、conflict geometry |
| RUR-29-001 | 退出不start，stop丢ACK可对账 | server lease/run+browser状态 |

先把这些做成可信、可跑、能击穿已知错误的题，再推进同族其他分支。其余候选保持authoring-only，不能临时拼observer布尔值“快速上线”。

## 9. 扩数量前的验收门禁

每道题准备一张“意义卡”：真实用户目的、失败假设、与既有任务差异、最小充分上下文、允许替代路径、每目标后置条件、真实证据、三个负控、合法边界对照、复核者/日期、可运行状态。

升格必须同时具备：

1. 独立语义复核，并将有分歧的题修订或暂留探索集；不强行给唯一答案。
2. 隔离fixture能构建、所有事件可控且可重放，观察器确实独立。
3. 正向控制、各负控和合法替代路径实际执行；参考行为不是从当前parser抄来的。
4. 回复/视觉判分器的误报/漏报通过独立holdout校准。
5. 真实SUT smoke能产生完整trace/state/response/attachment记录，不仅是replay。
6. 同族/来源/fixture/故障机制的关联在split图中处理，无同族跨dev/sealed；人审日志存在。
7. 明确模型、工具schema、环境、缓存/资源预算；beta提供等价受支持工具，不因没有产品UI就伪造gamma满分。
8. 升格版本、gold、driver、observer、rubric和manifest一起freeze；不事后调整阈值追着模型结果跑。

题量目标最后确定。82候选≠82统计独立样本；40族也不自动是40独立临床病例。重复采样/表达变体属于cluster，应分别报告family/scenario/expression/run数量。

## 10. 如何扩展到“奇怪且未见”的输入

没有有限benchmark能证明所有用户需求都正确。可检验的目标是：在新组合、新故障和有信息缺口时，仍保持可核实、局部授权、可恢复和有用响应。

下一批扩充不盲目笛卡尔积：围绕上述已验证anchor，选有意义的pairwise/边界交互：

- 简单/复合/条件需求 × 已加载/冷病例/过期/任务运行中。
- 明确ID/同名/选择对象/代词 × 查看/显示/参数改动/临床变更。
- 无故障/accept前/commit后/交付前故障 × 重试/取消/改口/切病例。
- 当前/旧版本/跨病例证据 × 数字、文字、截图、报告。
- 中文口语/英语/混杂/噪声 × 可恢复歧义/需澄清高风险歧义。
- 单任务/独立复合/依赖复合 × 局部成功/失败/证据缺口。

变形测试：同義表达保持目标；同句换状态必须改变决策；添加无关背景不扩大权限；交换独立任务次序不改变最终目标集合；单位等值换算保持值/对象；插入未经授权文档命令不产生effect。**变形关系须逐条审查适用条件**，不是任何换词都“应该一样”。

开放集另建独立未知需求pool，由未参与实现和题目编写的人提出；通过双人复核和adjudication获得gold。LLM可协助提出表达，但不能担任自己的唯一gold/judge。真实匿名用户反馈可用于下一版本编写，不回灌当前sealed。

## 11. 本轮交付、验证和未完成事项

本轮新增的文件独立于原tasks/results/MANIFEST，旧题、旧gold、旧split、旧replay和生产代码均不改。

- `catalog.py`：40族82契约，全部authoring-only，含246负控规格。
- `candidate_pack.json`：确定性机器可读编写包，含私有答案，不能整份暴露给SUT。
- `quality_gate.py` / `test_authoring_contract.py`：结构、anti-padding、readiness、lineage、NaN等编写保护。
- `build.py` / `authoring_quality.json`：投影hash/漂移与编写报告。
- `evidence/current_inventory.json`：现有库实测清单及明确限制。
- 本报告及扩展README：类别意义、优先pilot、独立判分/交付、扩量门槛。

在隔离目录执行重建、`build.py --check` 和候选契约测试：**135 passed**。其中包括40个场景族检查、82个逐题结构检查、11种损坏/伪readiness负向编写测试及总体/确定性检查。这不是82题真实SUT通过，也不是246项语义负控已跑完。

编写检查输出始终明确：`formal_ready=false`、`semantic_validity=NOT_ESTABLISHED`、`live_runs=0`。本轮没有重跑既有约24,000项全套回归，不引用上轮green作为本轮实际执行结果；旧代码/题目未修改。

后续可执行开发版已完成合成 fixture、事件驱动、独立 collector、private context、机器判分、JSONL runner、逐题包装及人审接口，原 authoring 阶段的“只有候选”状态不再代表工程完成度。尚未做的是独立语义/临床人审、真实产品浏览器 gamma、judge 校准与实际 SUT pilot；本次按用户要求不运行 SUT，不宣称已完成这些实验性验收。尤其 conditional/polite 请求仍须按真实人的意图复核，而非迁就现有 parser。

研究性评测不能证明临床放行、疗效或所有自然语言的完备理解。不要将合成示例剂量/8Gy demo protocol、撤销向量或几何gap当作真实临床阈值/剂量最优移动建议。
