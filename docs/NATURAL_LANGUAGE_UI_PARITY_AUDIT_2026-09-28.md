# BrachyBot 自然语言—前端交互全链路对等性审计与实施交接

日期：2026-09-28  
审计对象：`/home/lht/snap/brachyplan/BrachyBot` 当前 LAN 工作树  
初审基线：`a3aa976844526195756a36beebc2828b165e9c33`

修复后复审：2026-09-28，HEAD `a0aaa2cb4467a7762b37620f53749bf700b360c7`，包含当前9个已跟踪 Monitor 工作区修改。

交付性质：代码审计、隔离探针、实施设计与验收计划；**本次不修改业务代码，不重启服务，不执行临床规划或修改患者数据。**

## 0A. 修复后复审——当前实施状态以本节为准

**已有有效修复，但“7项已修复、WP1完成”不能等同于七类底层契约已经闭环。原始样例多数已通过；新增探针仍复现授权放宽、假完成、错误依赖、错误参数绑定和状态回退。**

本次对照 `NL_UI_PARITY_IMPLEMENTATION_STATUS_2026-09-28.md`、修复提交和最新工作树核验。下文 §0–§11 保留初审证据及设计依据，**原始复现和旧行号不代表当前状态**；本节覆盖旧结论。已有修复和测试应保留，不能因发现残留缺口而推倒重来。此次仅更新报告和审计附件，不修改业务代码、不重启8080、不运行规划或修改患者数据，也不触及 public-release。

### 0A.1 逐项销账表

| 编号 | 当前判断 | 已验证改进 / 仍需完成 |
|---|---|---|
| F01 | **部分修复，仍有P0授权缺口** | 裸“全部更新”不再放行CTV/OAR/新规划；混合条件/引用/问句仍可放行CTV。无来源时仍默认剂量、报告、导板。见R01。 |
| F02 | **部分修复，仍有P0假完成** | 同步/异步失败及简单字面参数handler已正确处理；JobRef及明确completed:false仍被升级为完成，外层进度也未接通终态。见R02。 |
| F03 | **部分修复，仍有P0依赖缺口** | 原始step key、重复工具和provider依赖测试通过；图合并前向引用可能绑错生产者，validate未成为执行前强制门。见R03。 |
| F04 | **未闭环** | 本地解析与expected action签名仍限制语义动作；礼貌请求/指代问题不能靠增白名单解决。 |
| F05 | **部分修复** | 分别30%/70%等数值绑定通过；文字值次序和重复值仍错误。见R04。 |
| F06 | **未修复目录契约** | catalog 4096截断仍存在，未完成对象索引、能力schema及可发现分页；初审258节点规模证据保留，不冒称本次读取真实病例。 |
| F07 | **部分修复，端到端状态不一致** | AgentMemory replace/patch/tombstone、同browser序列和HTTP失败检查通过；冷会话乱序、bucket删除标记、规划版本和持久化仍有缺口。见R05。 |
| F08 | **未修复查询语义** | component仍查源码组件，不是当前导板/mesh资源解析器；state分支已有实时内容，不应说整个工具都没有状态。 |
| F09 | **未完成手势对等** | 通用wheel/drag与真实MPR仍是不同路径，viewport/坐标/修饰键未统一进入业务command。 |
| F10 | **原始三例已修复，边界未闭环** | 空min/max、字符串false、正常当前值的相对opacity通过；缺overlay对象时null→0遮蔽有效fallback。见R06。 |
| F11 | **未闭环权限和消歧** | 执行仍有ID/selector fallback；采集过滤不等于执行时唯一性、时效和权限验证。未进行敏感控件攻击测试。 |
| F12 | **部分修复** | 同批独立失败隔离、同批失败前置阻断、同会话批次串行通过；跨批依赖、未知前置、取消仍有缺口。见R07。 |
| F13 | **未闭环证据契约** | 活动规划和OAR数据能力已存在；D2/D2cc fallback、版本/新鲜度、required outputs仍不能销账。不是“只能查询器官体积”。 |
| F14 | **未闭环持久化回执** | 参数/报告字段DOM applied与workspace persisted仍不同，缺全域保存后置条件。 |
| F15 | **未完成显式能力目录** | Element listener扫描是补漏，不能覆盖全部委托事件和业务语义；本次未做heap profile。 |
| F16 | **浏览器验证扩大，真实病例E2E待验证** | 本次5个Chrome/Playwright脚本全部通过；fixture/WebGL成功不等于自然语言→真实业务→保存→重载已经全产品通过。 |

“部分修复”以原缺陷的完整契约为范围，不表示对应提交无效。应保留 `ffbf741a1 / ec0437906 / 18936f44d / 9799e92f3 / 9c281a2b9 / 8e189cae0` 中已经正确工作的部分。

### 0A.2 新增复现、根因和合理修复边界

S＝最新源码核验；P＝隔离生产函数/Flask test client探针。P不是在线患者病例操作，不推断用户曾实际遭遇全部边界。

#### R01｜P0｜aggregate绕过条件/引用/问句属性（F01，S/P）

位置：`agent_runtime/request_parse.py:1299` 的 `aggregate_scope_targets`、`:1416` 的最终aggregate授权分支。

无历史上下文调用 `mutating_execution_authorized(message, 'ctv_segmentation')`：

| 请求 | 实际结果 | 正确边界 |
|---|---|---|
| 全部更新 | false | 原始裸聚合误授权已修复 |
| 全部更新；如果以后需要，重新分割CTV。 | **true** | 条件性的将来分割不能授权 |
| 全部更新；他说“重新分割CTV”。 | **true** | 引用不能授权 |
| 全部更新，CTV分割了吗？ | **true** | 状态询问不能授权 |

普通授权循环过滤conditional/quoted/attributed/interrogative/ambiguous，但aggregate scope只排除excluded/negated，从其他子句收集target后再次授权，绕过普通循环。此证据证明底层防线有漏洞，**没有证明真实上层请求必然启动分割**。

S级附加缺口：无来源时fallback到dose/report/surgical_guide；计数指代按目标类别切片，未验证足够数量的真实待办，也未绑定结构化offer的case/plan revision。不能把默认产物家族称为有来源scope。

修复方向：scope只能来自肯定可执行子任务、有效待办或当前明确过期产物集合；来源、排除项、风险校验在同一授权契约完成。无明确来源先只读解析/澄清，禁止从条件或引用中借目标；不是一刀切禁用aggregate。

#### R02｜P0｜JobRef/派发成功仍被当作业务完成（F02，S/P）

位置：`brachybot-ui-api.js:2869` 的handlerCompleted、`:7302` 的 `_executeUIActionsWithProgress`；`tool_factory/ui_controller/__init__.py:1195`。

- handler返回 `{success:true,completed:false,status:'running',job_id:'job-1'}`，外层结果却是 **completed:true**，内层receipt仍false。
- 进度执行器收到 `{success:true,completed:false,dispatched:true}`，仍发出 **pending→done**。
- 后端 `executed=len(validated)` 在浏览器执行前赋值；“已执行”不构成业务证据。

根因：`success===true || receipt!=null || job_id!=null` 被用作完成判断；外层主要检查success/stale，不理解真实终态。新增receipt字段不等于回执链已经接通。

修复方向：统一accepted/dispatched/running/waiting_user/completed/failed/cancelled；JobRef只证明接收，完成依赖业务终态及必要的persisted revision。进度、依赖、最终回答消费同一账本，不靠改文案或固定等待秒数掩盖假完成。

#### R03｜P0｜合并前向依赖映射错误，验证未接入执行门（F03，S/P）

位置：`agent_runtime/action_plan.py:200` 的merge、`:274` 的validate；`agent_runtime/llm_runtime.py:1086` 的排序入口。

已有旧生产者A；新图先列消费者C（依赖新A），再列新生产者A。合并把新A改名为dose_recompute#2，却留下C→旧A；排序为 **旧A→C→新A**，validate仍为空。单遍边处理边建立key_map不能正确重映射前向引用。

S级核验：ActionPlan的validate/is_valid尚未成为LLM排序/执行入口的强制检查；ordered_steps为列举保留异常图步骤，不等于允许执行异常图。新增验证单测不能替代生产调用。

修复方向：先为整个子图分配唯一ID，再重写全部依赖边（含placeholder）；不明确重名拒绝。生成、合并、恢复和执行前均验证；消费者等待精确生产者的成功receipt与匹配版本。列举容错API和执行API分开。

#### R04｜P1｜文字值按pattern顺序绑定，重复值丢失（F05，S/P）

位置：`agent_runtime/ui_operations.py:111` 的values_from_text。

- “CTV和OAR分别设为不透明和半透明”实际产生ctv,50和oar,100，应为100和50。
- “CTV和OAR分别设为半透明和半透明”只提取[50]，返回ambiguous、无action。

原因：每种pattern只做一次re.search，丢失原文位置及重复出现；数字分支按文本顺序的修复有效。

修复方向：数字/文字/颜色统一提取为带source span的typed value，保留重复出现，再按子任务和分别关系绑定。补中英逆序、重复值、混合类型、局部否定及同组多个leaf的保留集，不逐词补丁。

#### R05｜P1｜冷会话无序列保护，bucket与内存删除语义分裂（F07，S/P）

位置：`agent_runtime/core.py:616` 的set_ui_state；`planning_routes.py` 的 `/api/ui/state` POST及checkpoint_ui_bridge；`brachybot-ui-api.js:2157`。

隔离Flask route、内存store和空timer复现：

1. 冷Agent：同browser先写seq9，再写seq4，两次均200/accepted，最后变成旧值。序列验证依赖cached Agent，bucket未独立校验。
2. 热Agent：patch+tombstones删除deleted字段，返回200；AgentMemory已删除，bucket和state_keys仍保留deleted:'old'，读出/落盘事实与Agent不同。
3. 同browser从(seq1,plan_revision2)更新到(seq2,plan_revision1)被接受，旧规划状态覆盖新规划。plan_revision只是记录字段，未成为有效围栏。

S级附加缺口：checkpoint只保存state/events/training/updated_at，不保存browser序列围栏；前端读取state.planningRevision，但当前静态JS中未发现其写入，手动规划有效版本来自manualPlanningState.planningVersion。不能因为请求有这个字段就宣称生产版本校验有效。没有进行真实双标签页/进程重启注入。

修复方向：owner/case控制面原子接收器不依赖Agent加载；同一已接受的规范化状态供bucket、Agent和checkpoint使用；持久化/恢复序列，明确规划revision权威、跨tab冲突及前端ack归属。不能为了UI校验启动昂贵的病例hydration。

#### R06｜P1｜相对opacity的null被当有效0（F10，S/P）

位置：`brachybot-ui-api.js:7915` 的_overlayOpacityFraction。

state={doseOpacity:0.6}且缺doseOverlay对象时，increase10实际解析为base0、percent10，应使用有效fallback得到70。Number(null)===0遮蔽了fallback。这是确定的有效fallback误读，不是建议未知值时猜默认值。

修复方向：null/undefined/空白先判missing再转数字；没有有效当前值不得执行相对操作。组内不同当前值应明确统一设定还是逐对象增加，不用第一项无声代替全组。

#### R07｜P1｜串行批次不等于跨批依赖与取消系统（F12，S/P）

位置：`brachybot-ui-api.js:7302` 的_executeUIActionsWithProgress及_queueUIActionBatch。

- 第一批producer失败；第二批consumer显式依赖producer仍执行，因为failedSteps仅在本次调用内。
- 未知前置不在failedSteps就执行，没有要求它已经成功。
- 隔离调用传入已aborted的signal仍执行；此函数只检查session。该证据不意味着所有上层取消入口都会放行，但证明执行器自身无取消门。
- R02的pending receipt也会过早放行依赖。

修复方向：owner/request/step账本跨批保留结果；未知/未完成前置等待或验证失败，不默认成功。入队、出队和业务写入前检查取消及归属；Viewer/workspace用effect锁。保留已实现串行队列，但不把它称为完整DAG和可恢复事务。

### 0A.3 本次实际测试与证据边界

| 层级 | 本次结果 | 不得扩大解释 |
|---|---|---|
| 15个相关Python文件 | **209 passed**，3个SWIG警告 | 原139项＋新增70项，不是全仓库 |
| 3个新增Node契约脚本 | **全部通过** | ui-control-receipt、ui-state-sync、ui-action-dependency；未覆盖上述反例 |
| 5个Playwright/Chrome脚本 | **5/5通过** | manual-step-viewer、monitor-dashboard、monitor-coaching、depth-peeling、report-hidden-viewer；真实浏览器/WebGL＋隔离fixture，不是患者病例E2E |
| 新增反例探针 | **复现R01–R07缺口** | 观察脚本退出0只是成功采集，不是缺陷验收通过 |
| 两个既有Node失败项 | **仍复现** | chat_screenshot_delivery的sandbox缺uiActionTasks；test-report-lifecycle期望captureAllowed=false却为true。未改断言，不能直接据此认定真实截图故障 |
| 全仓库pytest、真实病例、在线LLM | **本次未执行** | 实施记录1971 passed/8 skipped/2 failed属于历史运行，不是此次重新认证 |

环境结论更新：旧“缺Playwright，五个浏览器脚本未能执行”是当时的环境结论；本次使用bundled Node依赖和本机Chrome已经执行并通过五项。不应继续标这五项未运行，也不能据此宣布全产品E2E完成。

### 0A.4 后续实施顺序和工作包状态

1. 先R01授权，再R02/R03终态及依赖身份；不要先扩可执行自然语言范围。
2. 并行完善R05控制面接收器和R07跨批账本，保持冷会话轻量；不增加逐子任务LLM调用、不以固定长等待判断成功。
3. 修R04/R06并扩值类型保留集，再做F04语义fallback。模型理解复杂语言，确定性层校验有来源的权限、参数和版本，而非用本地漏识别永久否决。
4. 继续F06/F08/F11/F15资源能力索引和F13/F14证据持久化；保留已有OAR、活动规划、截图事务和Monitor权威执行器。
5. **WP1应标“部分完成，待闭环”**；WP0测试基础有效；WP2/3/4/5仍有销账表缺口；WP6五项fixture浏览器测试现已通过，真实病例端到端、性能及重启恢复仍待验证。

关闭条件：原回归保持通过；R01–R07改为正确行为断言并通过；生产调用链实际使用新契约；需保存/渲染的动作有真实后置条件；独立失败、依赖等待、取消、断线/冷加载/重载有证据。新增helper、字段或“已修复”文档不能代替集成验收。

### 0A.5 本次附件

`docs/audits/nl-ui-parity-review-20260928/`：

- review_probes.py / review_results.json：解析、授权、图合并、参数绑定、内存版本和隔离Flask冷/热状态。
- review_browser_probes.cjs / review_browser_results.json：真实执行函数的inert VM探针，覆盖receipt、跨批依赖、取消、opacity fallback。
- verification.md：测试命令、范围和工作区保护说明。

Python在项目根目录设置PYTHONPATH=.并用项目环境运行；Node脚本自动定位仓库。JSON为本次观察基线，不能只改JSON假装修复，应在正常测试中加入正确行为断言。

## 0B. R01–R07 独立复核与整改（第三轮）

日期：2026-09-28。本节由实施方独立复核后写入，**不是对 §0A 的转述**：每条给出复核方式、根因认定、改动位置与可复跑证据。§0A 的 R01–R07 **七条全部属实**，本轮已按其修复方向实施；下文同时记录 §0A 中两处无法照单全收的边界判断。

### 0B.1 复核结论（逐条）

复核方法：直接运行 §0A.5 的两个探针脚本，再对照源码定位根因。两个探针的 JSON 输出与 `review_results.json` / `review_browser_results.json` **逐字一致**——观察可复现，不是转录错误。

| 编号 | 复核判断 | 独立复核方式 |
|---|---|---|
| R01 | **属实** | 三句 `mutating_execution_authorized(..., 'ctv_segmentation')` 实测均返回 `True`。根因是两套过滤器：普通授权循环跳过 ambiguous/negated/interrogative/conditional/quoted/attributed，`aggregate_scope_targets` 只跳过 excluded/negated，再拿弱过滤的集合二次授权。 |
| R02 | **属实** | `handlerCompleted = success===true \|\| completed===true \|\| receipt!=null \|\| job_id!=null` 实测把 `{success:true,completed:false,status:'running',job_id}` 升级为完成；`_executeUIActionsWithProgress` 对 `{success:true,completed:false,dispatched:true}` 发出 `pending→done`。 |
| R03 | **属实** | 单遍 `merge` 里 `dependencies = tuple(key_map.get(d, d) ...)` 与建 `key_map` 同遍执行：C 先入图时新 A 尚未改名，`key_map.get('A','A')` 落到旧 A。实测顺序 `A→C→dose_recompute#2`。`_order_tool_calls_by_action_plan` 未调用 `validate()` 属实。 |
| R04 | **属实** | `OPACITY_WORD_PATTERNS` 逐 pattern `re.search` 一次，按 pattern 声明顺序而非原文位置出值：「不透明和半透明」得 `[50,100]`（应 `[100,50]`）；「半透明和半透明」得 `[50]`（应 `[50,50]`）。 |
| R05 | **属实** | 隔离 Flask 实测：冷会话 seq9→seq4 双 200，终值为旧值；tombstone 后 memory 已删、bucket 仍有 `deleted:'old'` 且 `state_keys` 仍含该键；(seq1,plan2)→(seq2,plan1) 被接受。根因是版本围栏只存在于 `AgentMemory._ui_state_last_seq`（冷会话无 agent 即无围栏），bucket 写入另行 `dict.update` 不走 tombstone，`plan_revision` 只记录不比较。 |
| R06 | **属实** | `asFraction = raw => Number(raw)`：`Number(null)===0` 且有限，直接短路掉 `state.doseOpacity` 回退。实测 `state={doseOpacity:0.6}` 且无 overlay 时 `increase 10` 得 base 0 / percent 10。 |
| R07 | **属实** | `failedSteps` 是单次调用内的 `Set`；`blockedBy` 只查 `failedSteps.has(dep)`，故未知前置视为已满足；`signal.aborted` 全函数未检查。实测三条反例均放行。 |

### 0B.2 实施的修复（根因 → 改动位置）

不加句子白名单、不放开任意 DOM、不削弱安全检查、不把 cap 调大冒充修复；判据均收敛到**单一权威实现**。

**R01｜单一授权谓词 + 范围来源可查**
- `agent_runtime/request_parse.py`：新增 `_subtask_can_authorize(task)`，`aggregate_scope_targets` 的 `named` 收集与 `mutating_execution_authorized` 的循环**共用同一谓词**（另加 `excluded`）。条件/引用/转述/问句只在"谈论"对象，不再借目标。
- 聚合范围解析抽为 `_aggregate_scope_resolution`，公开 `aggregate_scope_provenance()` → `named` / `count_reference` / `elliptical` / `policy_default` / `contested_scope` / `unresolved_count_reference` / `none`。**只有前三种是用户原话给出的授权**；`policy_default` 如实标注为"无来源的策略默认值"而非"有来源 scope"。
- 新增 `_AGGREGATE_GEOMETRY_TARGETS`：当同句提到几何目标却又不是显式排除（"全部更新，CTV分割了吗？"→ contested）时，**连默认族也不给**，强制澄清。显式排除（"全部更新，CTV不用动。"）不算争议，仍走默认族并扣除排除项。

**R03｜两阶段重映射 + 执行前强制校验**
- `agent_runtime/action_plan.py` `merge()`：**先为整个子图分配最终 id（phase 1），再统一重写全部依赖边（phase 2）**，前向引用因此绑定到随行到达的生产者。入图 id 重复/为空/自依赖时**整图拒收**（返回 `self`），不猜。
- `agent_runtime/llm_runtime.py` `_order_tool_calls_by_action_plan()`：执行路径与容错列举分离——`validate()` 非空则**一个工具都不调度**（两处调用点均以空返回结束本轮工具循环）。`ordered_steps()` 仍保留异常图以便诊断，但不构成执行许可。
- `agent_runtime/execution_authorization.py` `set_action_plan()`：事件轨迹记录 `merge_refused` 与 `plan_problems`，拒收不再静默。

**R02｜终态分类器，JobRef 只证明受理**
- `web/app/static/js/brachybot-ui-api.js` 新增 `_uiActionResultState(result)`：统一 `completed / failed / cancelled / stale / accepted / dispatched / running / waiting_user / …` 词表。`completed===false`、`job_id`、`dispatched`、非空 `receipt` **都不再等于完成**；嵌套 receipt 递归判定。
- `invokeMountedHandler` 的 `handlerCompleted` 改为 `state === 'completed'`；返回体新增 `status` 字段。
- `_executeUIActionsWithProgress` 用同一分类器决定进度终态：非终态发 `running` 而不是 `done`。
- `tool_factory/ui_controller/__init__.py`：`executed=len(validated)` 改为 `accepted=len(validated)` / `executed=0` / `execution_claim="accepted_pending_browser"`（该计数描述受理量，浏览器尚未执行）。
- `tool_factory/viewer_command/viewer_command.py`：同型缺陷一并修正（其 message 自称 "queued" 却报 `executed`）。

**R05｜控制面原子接收器 + 双围栏 + tombstone 同源**
- `agent_runtime/core.py` 抽出 `apply_ui_state_write()`：patch/replace/tombstone/delete-marker 的合并逻辑**只此一处**，bucket、AgentMemory、checkpoint 共用。
- `AgentMemory.set_ui_state()` 新增 `plan_revision` 围栏（`_ui_state_last_plan`），旧规划快照即使 seq 更新也拒收（`stale_plan_revision`）。
- `web/routes/planning_routes.py` `/api/ui/state` POST：**围栏移到控制面 bucket**（`bucket["version_fence"]`），冷会话无 agent 也生效；bucket 与 memory 写入同一规范化状态，tombstone 不再分裂。
- `checkpoint_ui_bridge` 持久化 `version_fence` / `state_seq` / `plan_revision`，恢复路径 `_bridge_view()` 原样带回——重启不重开围栏窗口。
- 前端 `web/app/static/js/brachybot-ui-api.js` 新增 `_currentPlanRevision()`，权威来源是 `manualPlanningState.planningVersion`（原先只读从未写入的 `state.planningRevision`，`plan_revision` 恒为 null，服务端无从比较）；`_collectUIState()` 的 `manual` 块补 `planning_version`，快照自带归属。

**R04｜按原文位置取值，保留重复**
- `agent_runtime/ui_operations.py`：`values_from_text` 改为**带 source span 的统一收集**（数字 + 文字 + 颜色），按 `match.start()` 排序，重复出现保留。
- 文字值合成单一 `_OPACITY_WORD_RE`（命名捕获组）一次 `finditer`，不再逐 pattern 声明顺序出值。
- `(?!度)` 防止属性名「不透明度」被读成数值 100。

**R06｜missing 不是 0，组内分歧不猜基准**
- `_overlayOpacityFraction` 的 `asFraction` 先判 `null/undefined/空白` 再 `Number()`，缺失回退真正生效。
- OAR 组逐器官求值：成员不一致时返回 `null`（拒绝相对操作并要求绝对值），不再无声取第一项代替全组。

**R07｜跨批账本 + 取消门**
- 新增 `_uiActionStepLedger(ownerKey)`（owner+request 维度，跨批保留）与 `_uiActionDependencySatisfied()`：**前置必须是 `completed`**，未知/未完成/失败/仍在跑一律阻断，不默认成功。R02 的分类器直接决定能否放行依赖。
- `_executeUIActionsWithProgress` 循环内与业务执行前均检查 `options.signal.aborted`。

### 0B.3 断言改动（2 处，均为收紧）

按 §0A 关闭条件"R01–R07 改为正确行为断言"，新增断言 46 项（Python 31 + Node 15）。同时有两处**既有断言本身编码了缺陷**，必须改：

1. `tests/ui-control-receipt.test.cjs`：`assert.equal(result.completed, true, 'a positive handler receipt proves completion')`——该 handler 返回的是 `{success:true, job_id:'guide-1'}`，即 JobRef。这行**就是 R02 本身**。改为 `completed === false` + `status === 'running'` + `dispatched === true`，并补一条显式终态 `{success:true, completed:true}` → `completed === true` 的正例。
2. `tests/test_screenshot_trace_integration.py:1493`：断言源码字符串 `"result.success === false || result.stale === true"`。该表达式已并入 `_uiActionResultState`，字符串不复存在。改为断言新等价标记 `state === 'failed' || state === 'stale'` + `function _uiActionResultState`，并在 `tests/ui-action-terminal-state.test.cjs` 补**行为级**断言（会话切换 → `stale` 失败、且不再执行后续动作）。

其余历史断言未改动。

### 0B.4 验证证据

| 层级 | 结果 | 边界 |
|---|---|---|
| 全仓库 pytest `--ignore=tests/test_release_access.py` | **2029 passed, 2 skipped, 2 failed** | 2 项失败为既有 `tests/test_brain_system.py`（`test_agent_chat_fallback` / `test_brain_agent_connection`），基线同样失败，本轮未触碰 |
| 新增 `tests/test_nl_parity_review_regressions.py` | **31 passed** | 覆盖 R01/R03/R04/R05，含隔离 Flask 冷/热会话 |
| 新增 `tests/ui-action-terminal-state.test.cjs` | **15/15 passed** | 覆盖 R02/R06/R07，加载**生产函数**而非复刻 |
| 既有 4 个 Node 契约套件 | 全部通过 | ui-control-receipt / ui-state-sync / ui-action-dependency / ui-action-owner（含 5 个需显式 argv 的套件） |
| §0A.5 原探针 `review_probes.py` | 七条反例**全部转为正确行为** | 见 §0B.5 说明 |

原探针实测对照（左为 §0A 观察，右为本轮后）：

| 反例 | §0A | 本轮后 |
|---|---|---|
| `全部更新；如果以后需要，重新分割CTV。` | `ctv_authorized=true` | **false**，scope `[]`，provenance `contested_scope` |
| `全部更新；他说"重新分割CTV"。` | `ctv_authorized=true` | **false**，scope `[]` |
| `全部更新，CTV分割了吗？` | `ctv_authorized=true` | **false**，scope `[]` |
| 前向依赖合并 | `order=[A, C, dose_recompute#2]`，C→旧A | **`order=[A, dose_recompute#2, C]`**，C→`dose_recompute#2` |
| 「不透明和半透明」 | `[50, 100]` → ctv,50 / oar,100 | **`[100, 50]`** → ctv,100 / oar,50 |
| 「半透明和半透明」 | `[50]` → ambiguous | **`[50, 50]`** → ctv,50 / oar,50 |
| 冷会话 seq9→seq4 | 双 200，终值 `{"value":"old"}` | **409 `stale_state_seq`**，终值 `{"value":"new"}` |
| (seq1,plan2)→(seq2,plan1) | accepted | **`stale_plan_revision` 拒收**，状态仍为 new |
| tombstone | memory 删 / bucket 留 `deleted:'old'` | **两侧一致 `{"keep":true}`**，`state_keys` 不含 `deleted` |
| incomplete receipt | `pending→done` | **`pending→running`** |
| 跨批失败依赖 | `["producer","consumer"]` | **`["producer"]`** |
| 未知前置 + aborted | `["consumer"]` | **`[]`** |
| 无 overlay 相对透明度 | base 0 / percent 10 | **base 60 / percent 70** |

### 0B.5 与 §0A 的两处边界判断差异

1. **`policy_default` 的处置**：§0A 修复方向写"无明确来源先只读解析/澄清"。本轮**未一刀切禁用**裸「全部更新」——剂量/报告/导板是可再生产物、重建不破坏几何，且已有正例回归。折衷是：(a) 用 `aggregate_scope_provenance()` 如实暴露 `policy_default` 不是授权来源，上层可据此要求澄清；(b) 一旦同句出现**未被排除的几何目标**，连默认族也收回（`contested_scope`）。这正是 §0A 三条反例的诉求（条件/引用/问句不得授权），同时不把可用路径推倒。
2. **计数指代与结构化 offer 的绑定**：§0A 的 S 级缺口——`count_scope_targets` 按前文枚举切片，未核验"确实还有那么多真实待办"，也未绑定 offer 的 case/plan revision。**本轮未修**：它需要待办完成态/产物新鲜度的权威存储（`当前明确过期产物集合`），是 §0A 修复方向里的第三类来源。半接一个无权威数据源的校验只会制造假绿。此项在 §0B.6 保留为未闭环。

**探针工具说明**：`docs/audits/nl-ui-parity-review-20260928/review_browser_probes.cjs` 用单函数切片加载 `_executeUIActionsWithProgress`。本轮把终态分类器与账本抽为共享 helper 后，该单切片不再自足（`_uiActionStepLedger is not defined`）——这是探针的加载方式限制，不是产品回归。正式断言已落在 `tests/ui-action-terminal-state.test.cjs`（按 §0A 关闭条件要求的"反例转为正确行为断言"）。`review_probes.py`（Python 侧）无需改动，仍可直接复跑。

### 0B.6 仍未闭环（不因本轮宣称解决）

- §0A 的 F04 / F06 / F08 / F09 / F11 / F13 / F14 / F15 八项原缺陷**未在本轮范围内**，状态不变。
- §0B.5-2 的计数指代/offer 版本绑定。
- 真实病例 E2E（工具→浏览器→保存→依赖→回答全链）仍未验证；本轮新增的是隔离契约断言。
- `tests/chat_screenshot_delivery.cjs`（sandbox 缺 `uiActionTasks`）与 `tests/test-report-lifecycle.cjs`（`reportCaptureAllowed().allowed` 为 true）两项既有 Node 失败原样保留，未改断言掩盖。
- 本工作树同时含另一条并行的 Monitor 粒子间距精度工作（`clearance_basis` / `finite_parallel_cylinders` 端点假阳性判据），已由同一全量门禁覆盖；其整改记录见 `docs/MONITOR_INTERACTION_AUDIT_REMEDIATION_2026-09-28.md`。

## 0. 初审给实施 agent 的结论（历史基线；最新状态见§0A）

**当前不能确认、更不能宣称：凡是用户在前端能做的操作，都能通过自然对话可靠完成。审计已确认存在阻止该目标成立的通用机制缺陷，不只是几个中文关键词漏识别。**

项目已经有相当多基础设施：动态 UI catalog、111 个注册 UI target、结构化 ActionPlan、只读指标契约、活动规划上下文、截图事务、Monitor 版本围栏和若干浏览器完成回执。不要推倒重写临床算法，也不要再维护一份庞大的“句子白名单”。应把现有基础设施统一成一个有类型、有权限、有版本、有执行回执的能力系统。

最重要的六项结论：

1. **语义模型没有真正获得通用执行通道。** UI 动作最终必须与本地词法解析器产出的动作签名逐项完全一致；模型理解了委婉请求，仍可能在归一化时被丢弃。
2. **权限同时存在过严和过宽。** 礼貌问句被当成不能执行；但无上下文的“全部更新”却在底层授权函数中放行分割、完整规划等多类变更。不能用简单“放宽关键词”修复。
3. **发出事件经常被当作业务成功。** 通用控件执行器可在处理函数返回失败、异步操作尚未完成、数值被错误转换时返回成功。这是错误最终回复的重要根源。
4. **结构化计划不等于可靠任务图。** step key 依赖可能被忽略；动作数组一项失败会停止所有后续项；跨批 UI 操作又可能并发。这些规则没有表达真正的业务依赖。
5. **状态可见性不是一个完整、可查询、可证明新鲜的模型。** DOM、Data Tree、后端活动规划、历史摘要和工具简化结果各有一部分信息；“已采集到某字段”不等于模型能发现并正确使用它。
6. **回答覆盖验证仍是局部关键词规则。** 它能守住已列举的 OAR/针粒子问题，但不能证明任意复杂需求都得到覆盖，也不能以“未识别出要求”推导“已经答全”。

实施顺序：先修授权/执行回执/任务身份等底层契约，再分模块接入，最后提升自然语言覆盖。禁止以扩大 DOM 点击权限或移除临床安全门作为“变聪明”的捷径。

## 1. 用户需求的准确含义与边界

### 1.1 本审计采用的产品目标

用户说“知道所有信息”，应落实为：

- 知道当前账户有权访问的当前病例、活动规划、可用数据、运行任务与显示状态有哪些；
- 对未预装进上下文的信息，知道通过哪种只读资源查询获得，而不是谎称没有；
- 能识别请求中的对象、动作、参数、约束、前后关系、否定、条件、引用和指代；
- 手动按钮和自然语言走同一个经过验证的业务执行器，具有相同校验、持久化和撤销语义；
- 多需求分别执行、分别报告；独立任务失败不相互吞掉，依赖任务不越过失败前置；
- 完成意味着业务完成并核验后置条件，不是模型选了工具、HTTP 返回 200 或 DOM 事件已派发；
- 回答能指向这次操作和这次版本的证据，准确区分未执行、等待确认、运行中、部分成功、失败、过期。

这不是让大模型始终携带所有体素、网格、DVH 采样点和完整事件历史，更不是让它拥有超越当前用户的权限。

### 1.2 不能伪装成“自动完成”的边界

- 浏览器文件选择、安全下载、剪贴板、全屏等可能需要真实用户激活。应返回“等待选择文件”等明确状态，不得把打开选择器当作上传成功。
- 临床批准、人工签署、目标不明确的删除、覆盖受保护报告，不应因自然语言入口而绕过既有权限/确认。
- 模糊肿瘤部位、同名对象、来自上一病例的指代，必须查询或澄清，不能猜。
- 模型未测量的噪声水平、器官几何邻近、剂量阈值、临床优劣不能从文字常识补造。
- “自然语言可做”需要声明支持范围：例如精确患者坐标定位可支持；仅说“往那边一点”而没有视角/目标引用时不能杜撰坐标。

## 2. 审计范围、方法和验证强度

> 本节记录初审基线和当时环境，不是本次复审测试清单。最新209项回归、5项浏览器测试及新增反例见§0A.3。

### 2.1 基线与清单

从远端受 Git 跟踪的 `.py/.js/.html/.css/.cjs` 建立清单；审计本地镜像与远端当前文件逐一 SHA-256 对比，**505 个文件无不一致**。工作期间另有 agent/用户修改 `docs/MONITOR_INTERACTION_AUDIT_2026-09-26.md`；未覆盖该文档。生产源文件在校验时仍与本报告基线一致。

| 清单 | 数量 | 必须理解的限定 |
|---|---:|---|
| 源文件 | 505 | 包含测试、第三方前端库；不包括全部非代码资产、外部模型权重和运行时病例 |
| 源文件行数 | 270,436 | 静态计数，不表示每行都做了人工语义证明 |
| `web/` 下 Flask route 声明 | 122 | AST 识别的 route 声明，不保证覆盖所有动态挂载机制 |
| `index.html` 静态控件/事件候选 | 264 | 有重叠/容器，不等于 264 个独立业务能力 |
| JS/HTML 事件注册或内联事件行 | 568 | 文本扫描；动态创建和委托事件仍需专项检查 |
| `CONTROL_REGISTRY` targets | 111 | “已注册”不等于“自然语言可达且业务正确” |
| target-command 对 | 212 | 不含所有参数、对象实例和组合情况 |
| Python `test_*` 函数声明 | 1,649 | 不等于本次执行测试数量 |

对应完整清单位于 `docs/audits/nl-ui-parity-20260928/`，包括所有上述条目、源文件散列、注册 schema 和探针结果。不要用 `111/264` 计算覆盖率，两者分母含义不同。

### 2.2 证据等级

- **S：静态确认**：读取实际实现、调用方和接收方后确认的代码行为。
- **P：隔离复现**：调用实际纯函数，或抽取实际 JS 函数在 inert DOM/VM 中执行；无病例变更。
- **T：现有测试通过**：只说明这些测试目前覆盖的场景成立。
- **E：真实端到端未验证**：登录浏览器、真实 Viewer/GPU、刷新恢复、跨进程等仍需验收。
- **R：风险/设计缺口**：有代码依据，但没有在真实病例复现，不表述为已发生事故。

报告中“确认”只针对明确描述的函数/路径，不能外推为所有用户请求必然失败。

### 2.3 实际执行结果

远端使用 `/home/lht/.conda/envs/brachytherapy/bin/python` 执行：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_ui_control_snapshot_contract.py \
  tests/test_guide_visibility_contract.py \
  tests/test_intent_decision_contract.py \
  tests/test_intent_shortcut_boundary.py \
  tests/test_semantic_execution_authorization.py \
  tests/test_semantic_decision_budget.py \
  tests/test_answer_coverage.py \
  tests/test_agent_workspace_state.py \
  tests/test_downstream_update.py \
  tests/test_case_question_orchestration.py \
  tests/test_ui_bridge_sidecar.py
```

结果：**139 passed，3 个 SWIG deprecation warnings，7.49 秒**；交付前再次执行同一组，仍为 **139 passed，3 warnings，5.79 秒**。不是全量测试。

本地执行 `tests/guide-visibility-browser.test.cjs`、`tests/chat_turn_lifecycle.cjs` 通过。这两项为 Node 隔离测试，不是真实浏览器临床验收。

尝试运行 `manual-step-viewer-browser.test.cjs`、`monitor-dashboard-browser.test.cjs`、`monitor-coaching-browser.test.cjs` 时，环境缺少 `playwright`，在加载依赖阶段失败；没有将其记为产品逻辑回归，也没有宣称这些浏览器测试通过。本次未安装依赖、未启动临床服务测试实例。

新增审计探针复现了下文列出的缺陷。探针目前是**基线观察脚本**，不是全绿的修复验收套件；实施时应把其观察值改成预期正确行为的断言并纳入测试。

## 3. 当前端到端结构及断点

```text
用户自然语言 + 当前病例/会话 + 历史/待办
    ↓
request_parse / turn_policy / shortcut_contract
    ↓ 快捷路由或语义模型
ActionPlan + provider tool calls
    ↓ response_tools._normalize_tool_params / execution_authorization
工具执行：后端业务工具 或 ui_controller 返回 ui_actions
    ↓ 流事件 / chat task / 浏览器接收
_executeUIActionsWithProgress → _executeUIActionRaw → 业务函数或通用 DOM 控件
    ↓
后端数据 / 浏览器局部状态 / workspace 保存 / Viewer 渲染
    ↓
状态同步、截图与证据、进度、最终回复
```

现状不是“没有工具”，而是各层使用不同的成功定义、对象身份、权限依据和状态版本：

- 请求层按词法识别，工具层按签名匹配，UI 层按 DOM/ref 查找；语义决策不能直接解决三者不一致。
- `ActionPlan` 有 `depends_on`，但排序和执行并未始终以同一个 step ID/依赖结果为准。
- 工具返回“已执行”、浏览器“事件已派发”、业务真正完成和持久化成功不是同一时刻。
- 最终文字可能来自模型预答，截图来自后续浏览器结果；若缺少同一证据版本的 finalization，容易互相否定。
- 快照中对象不存在、未加载、隐藏、父组隐藏、过期、查询被截断、查询失败，是不同状态，不能统一说“没有”。

## 4. 已确认的问题与根因（按风险排序）

> 以下F01–F16保留初审原始证据和设计要求。当前是否已修复必须查§0A.1；F01/F02/F03/F05/F07/F10/F12的原始复现部分已修复，剩余边界见R01–R07，不能照搬旧行号或宣称原样例仍全部失败。

### F01｜P0｜“全部更新”在底层变更授权中缺少作用域绑定（S/P）

位置：`agent_runtime/request_parse.py:1255` 起，特别是 `:1307` 的 `parsed.aggregate_command and expected_target in _WRITABLE_TARGETS`。

复现：没有任何历史、活动规划或前一条待更新清单，直接调用 `mutating_execution_authorized('全部更新', tool)`，对 `ctv_segmentation`、`oar_segmentation`、`planning_pipeline`、`surgical_guide`、`report_auto_fill` 均返回 true。“全部更新，不含导板”能排除导板，却仍放行其他类别。

根因：把聚合动作词作为面向所有可写目标的授权，而不是绑定到当前用户指代的对象集合。上层已有 `_downstream_update_calls` 等限制，因此本审计**没有证明真实请求一定会误启动分割**；确认的是底层防线本身不能承担它宣称的授权职责。

修复：把“全部”解析成有来源的有限集合：当前明确待更新产物、当前待办的 scope、用户指向的对象列表。每个 effect 按同一子任务验证。无可解引用集合时澄清，不重分割/重规划。图中需要的只读前置可自动执行，新的临床变更不可越界。

验收：空上下文/切病例后的“全部更新”不能授权重新分割；“把刚才三项全部更新”只更新那三项；排除项对整个执行计划生效；临床全流程明确命令仍按原确认流程工作。

### F02｜P0｜通用 UI 控件成功与真实业务结果脱节（S/P）

位置：`web/app/static/js/brachybot-ui-api.js:2659` 的 `executeGenericUIControl`；简单异步 handler 路径约 `:2727`。后端提前回执见 `tool_factory/ui_controller/__init__.py:1192–1240`、`:1474`。

复现：mock 的实际 handler `failOperation()` 返回 `{success:false,error:'business_failure'}`，执行器仍返回 `success:true`；带参数的 `generateGuide('v1')` 使用 `el.click()`，操作仍 pending 时已成功返回。后端 UIController 的 `executed` 计数发生在浏览器真正执行之前。

影响：报告/导板/分割失败也可能被解释为成功；自然语言下一步用到未生成的对象；最终回复与前端状态冲突。

修复：有业务副作用的控件必须绑定能返回 `OperationReceipt/JobRef` 的业务 handler，不以 `click` 结束状态作为成功依据。通用 DOM 路径只可证明 `dispatched`；不能自升为 `completed`。同步和异步失败都传播结构化原因。已返回 job 的操作跟踪 job 终态及版本后置条件。

验收：同步失败、异步失败、参数化 handler、保存失败、网络断开、用户取消、重复事件均不得假成功；成功回答有实际 receipt；重试同 operation ID 不重复生成临床产物。

### F03｜P0｜任务依赖身份错误，可能先消费后生产（S/P）

位置：`agent_runtime/action_plan.py:79`、`:127`、`:219–244`。

复现：步骤 `consumer(report_generator)` 依赖 `dose_recompute#2`，后者实际在计划中；`ordered_steps()` 仍先发出 consumer，因为条件用 `dep not in self.tool_names`，step key 与 tool name 混用。`from_tool_calls()` 不保留传入 `key/depends_on`；循环依赖会按原顺序输出，而不是阻止执行。`order_tool_calls()` 只按工具名首个位置排序，不能保证重复工具的步骤顺序。

修复：所有依赖引用唯一 step ID；缺失依赖、重复 ID、环在执行前报验证错误；按 step 身份而非工具名调度。计划变换/合并必须保留参数和依赖映射。业务级预置顺序仍可补充，但不能修饰为“完整 DAG”而继续用名字排序。

验收：A→B→A、两个相同工具不同对象、跨轮追加、恢复任务、未知依赖、循环依赖、第二次剂量重算均有测试；依赖失败必须阻断对应下游，不能只做到排序正确。

### F04｜P1｜语义模型的正确动作仍被本地解析器否决（S/P）

位置：`agent_runtime/response_tools.py:3229–3330`；`_ui_action_signature` 在 `:48–69`；`agent_runtime/ui_operations.py` 的 `resolve_ui_operation_request`；`request_parse.py` 的子句属性。

隔离样例使用同一份含 `guide_mesh_v1` 的 live catalog：

| 请求 | 本地结果 |
|---|---|
| 请显示导板 | 正确 `tree.visibility set guide_mesh_v1,on` |
| 能帮我把导板显示出来吗？ | `rejected_unsafe_clause`，无 action |
| Could you show the surgical guide? | 同样因问句被拒绝 |
| 把刚才藏起来的导板恢复一下 | 无解析结果 |
| 让导板重新出现在画面里 | 无解析结果 |
| 请不要显示导板 | 正确拒绝执行，必须保留 |

归一化层只允许与本地 `expected_actions` 完全相同的 `(target,command,value)`。这意味着上述本地漏识别会继续限制 provider action，而不是被后续语义理解补救。`llm_runtime.py` 约 `:2280` 的全部过滤分支可设置 `tools_executed=True` 后退出，未向模型/用户返回具体 UI 拒绝原因。

修复：区分言语行为：礼貌请求、询问能力、假设讨论、转述、明确否定、可执行前置条件。模型输出结构化任务；授权层校验证据跨度、对象 scope、effect 风险、前置条件和必要确认，**不要要求另一套关键词解析器产生相同动作签名**。模型置信度本身也不是授权凭证。

局部 parser 作为高精度快路径可保留；未命中返回 `needs_semantic_resolution`，而不是把未识别视为禁止/完成。真正拒绝的动作必须有 reason code，进入执行追踪与最终结果。

### F05｜P1｜多目标参数对应关系丢失（S/P）

位置：`agent_runtime/ui_operations.py` 的多目标/数值解析及 `response_tools.py` 后续签名门。

复现：“请把CTV和OAR分别设为30%和70%的透明度”生成 `ctv,30` 和 `oar,30`，置信度仍为 0.86。

根因：句子级参数被扩散给多个目标，缺少逐子任务 source span/value binding。进一步，“透明度”与不透明度 slider 的业务定义必须统一：不能同一界面一种用 T，一种用 alpha。

修复：每个 assignment 是 `{objectRef, property, absoluteOrDelta, value, unit, sourceSpan}`；“分别”按对齐关系验证长度；共享参数只在语义上确实共享时广播。混合动作不能取一个全句数值重复套用。存在歧义应询问而非高置信执行。

验收：2 个目标/2 个参数、3 个目标/共享参数、单位不同、否定其中一个、相对增减、同名对象、目标数量不匹配、英文 respectively。

### F06｜P1｜UI catalog 在正常大规划规模下就可能截断（S/P）

位置：`brachybot-ui-api.js:947` 虚拟 Data Tree actions、`:1238–1389` catalog、`:1389` 4096 cap；`agent_runtime/ui_operations.py:199` 展平后再次 cap；visual catalog 另有 512 上限、legacy controls 有 260 上限。

复现：合成 181 个 seed、24 个 needle、53 个 organ（共 258 节点），调用实际 `_uiOperationVirtualTreeActions()` 生成 **4464 个条目**，尚未加 DOM、导板、剂量、手动步骤和 scene actions。collector 按前 4096 截断；Python 展平再按 4096 截断，可进一步损失后部动作。

这是**合成规模探针，不是读取了患者病例**。但规模与用户实际近 200 粒子的使用相当，足以否定“这个 cap 只在异常巨大页面才影响发现”的假设。

修复：对象索引与能力 schema 分离；每个对象只保存身份/类型/状态/适用能力引用，不复制十余份动作。按用户任务查询对象和属性，分页并明确 `has_more/truncated`。模型查不到当前页时知道继续查，而不是“没有对象”。不要仅把 4096 改成更大数。

验收：200/500/1000 粒子，分页末尾对象，中文别名、guide leaf、动态新增节点，catalog 网络和 token 预算；截断不能作为不存在证据。

### F07｜P1｜前后端状态合并、同步和时序语义不统一（S/R）

位置：`agent_runtime/core.py:559` 的 `set_ui_state`；`web/routes/planning_routes.py:5133` 附近 UI state endpoint；`brachybot-ui-api.js:2137` 的 `syncUIBridgeState` 及 `:8223` 的 `ui.state`。

确认：服务端 bucket 某路径用 replace，cached agent 使用浅 `.update()`，缺失字段可能留旧值；同步函数不验证 `response.ok`，catch 吞掉错误，调用方仍可报告成功。采集/到达时间没有统一变成客户端状态序列验证。

风险：已删除对象/旧选中项/旧控件可能留在合并状态；较慢的旧快照覆盖新快照；前端觉得保存成功而服务端仍是旧状态。本次未注入真实病例网络乱序，不声称每次已发生。

修复：清楚区分全量 snapshot、typed patch、tombstone；用 case/session/browser instance/state_seq/plan_revision 验证。同步返回 accepted revision；失败显示 unsynced，后续依赖操作不能假设已持久化。浏览器显示状态与后端临床状态分别标注权威来源，不互相覆盖。

验收：切病例、删除对象、乱序 POST、断网、两标签页、浏览器恢复、401/409/500、旧请求迟到；不可回滚新状态，也不能跨病例留旧字段。

### F08｜P1｜`ui_inspector component` 查的是源码组件，不是活动场景对象（S）

位置：`tool_factory/ui_inspector/__init__.py:660–732` `_search_component`，`:863` 起 dispatch；`:734` state 分支能返回 live catalog。

确认：component/search 查询静态 HTML 和 JS 文本；`surgical_guide` 是业务对象类型时，“Found 0 matching items”不等于当前导板不存在。state 分支确实有实时内容，不能把工具显示的 `Getting current UI state` 一句状态文案误当作完整 payload。

修复：拆分 `ui.components`（开发诊断）与 `resources.resolve`（当前对象查询）；工具描述明确类型；guide→active guide artifact→Data Tree leaf→mesh/render state 映射由同一 resolver 提供。返回 `not_found/ambiguous/not_loaded/hidden/stale/query_failed`，不混成空列表。

验收：导板已保存未加载、隐藏、父组隐藏、多个版本、已删除、重命名、同名导板，均能解释且不误触发重生成。

### F09｜P1｜通用手势并不等价于手工操作（S/P）

位置：`brachybot-ui-api.js:2979` wheel、`:3017` drag；真实 MPR 交互见 `brachybot-manual-annotation.js:3735–3830`。

复现：传入 `ctrlKey:true` 的 wheel 未进入生成事件；drag 只派发 PointerEvent，而被审查的 2D 平移监听使用 mouse 事件。真实 Ctrl+wheel 是缩放，普通 wheel 是切层；丢失修饰键可执行成另一动作。合成 pointer 不会自动等价生成完整可信鼠标事件序列。

另外 `viewer.zoom` typed handler 操作全局缩放、`viewer.transform` 缺少明确 axis；用户手动只改一个 2D Viewer 的场景不能由“有 zoom 工具”证明覆盖。

修复：将单轴 zoom/pan/slice、窗宽窗位、3D camera、标注几何、手动针粒子编辑做成类型化 command，手动 gesture 也调用同一 command。优先患者/图像坐标而非屏幕像素。通用 gesture 只作为受限兼容层，明确 modifiers、target viewport、单位、结果核验。

验收：三个 2D 窗口互不误联动；Ctrl/Shift/普通 wheel、左右键、touch/pen、resize、相机变化后坐标转换、undo/redo、取消 drag。禁止“同时派发所有鼠标和 pointer 事件”造成双执行。

### F10｜P1｜控件数值/布尔值/增量转换不一致（S/P）

位置：`brachybot-ui-api.js:2740` 附近输入赋值；`:7820` 附近 overlay opacity；注册 schema 位于 `tool_factory/ui_controller/__init__.py:176–192`。

复现：无 min/max 的 number 输入设置 25，因 `Number('')=0` 被夹到 0；checkbox 字符串 `'false'` 经 `!!value` 变为 true；`overlay.ctv.opacity/oar.opacity/dose.opacity` 命令 increase=10 实际执行绝对 set10。

修复：schema 严格解析值，空边界不等于 0；布尔只接受布尔或清晰规范化；相对动作读取有效当前值后运算、夹紧并返回 applied value。absolute/delta/unit 在同一 schema 内定义，禁止前后端各自猜。

验收：无范围、单侧范围、step/浮点、百分数、0/100、非法 NaN/Infinity、false/true 字符串拒绝或正确转换、绝对/相对、透明/不透明定义。

### F11｜P1｜通用控件发现与执行存在不同的安全边界（S/R）

位置：catalog 采集 `brachybot-ui-api.js:1238` 起；`_resolveUIControlElement:2609–2657`；`applyParameterSet:156` 起。

确认：采集时有过滤；执行阶段还可按 ID/selector fallback 使用 `document.querySelector`，选首个匹配项。参数 setter 可直接按 ID 找控件。catalog 中的只读/敏感项过滤不能自动保护另一条执行入口。

本次没有尝试绕过登录或操作敏感控件；此项为边界设计风险，不是已验证远程攻击。

修复：执行仅接受当前会话发行、仍有效的 capability instance ref；重查权限/enabled/unique/revision；高风险动作不得走 generic DOM，selector 不成为模型通用权限。后端保持同样的授权约束；prompt injection 不能从文档、报告、工具文字赋予操作权限。

验收：密码/隐藏控件、重复 selector、过期 ref、其他病例 ref、非当前用户资源、报告文本中的命令、工具结果中的伪造 action 都拒绝并解释。

### F12｜P1｜独立任务失败被连坐，跨批任务又可能冲突（S/P/R）

位置：`brachybot-ui-api.js:7101–7165`；`brachybot-chat-todo.js:4618–4651`、`:1292`。

复现：同一 UI actions 数组第一项失败，第二项即使独立也完全不执行。静态可见每个流式 UI batch 可立即执行并加入 promise 列表，缺少以完整依赖/effect 范围统一协调的规则。`_awaitChatUIActions` 注释称 bounded window，实际 `Promise.allSettled` 与 abort 的 race 不提供自身超时。

修复：以任务图和 effect lock 调度；临床写操作/同 Viewer 截图/相同 workspace 保存串行或条件串行；独立只读可并行。任务失败只阻断依赖项。显式 confirmation/waiting-user 不应伪装 timeout；long job 返回 job ref。所有等待有归属、取消、离线恢复及终态。

验收：A 失败 B 独立成功；A 失败 C depends A 被跳过且有理由；多次 ui_controller、截图和报告竞争；用户切病例/取消；modal 不点；服务端任务结束但浏览器已断开。

### F13｜P1｜指标结果没有完整携带版本/新鲜度，覆盖验证有盲区（S/P）

位置：`AgenticSys.py:1514` 附近 query_metrics 注入；`web/planning_runs.py:1113–1267`；`tool_factory/viewer_command/query_metrics.py:54–85,226–312,459`；`agent_runtime/answer_coverage.py`。

已正常的部分：query_metrics 已接入 current_planning_context；OAR 剂量实际在实现中，不应继续照搬历史日志说“系统只能读取器官体积”。

仍需修复：

- direct-read metadata 不完整携带 case/plan/revision/stale；活动上下文有来源信息，却未完整贯通至回答证据。
- `metric_type=plan_score` schema 存在，但 execute 没有同名专用分支，落到 all_metrics；契约不够精确。
- `_get_dose_metrics` 中 D2 对 D2cc 的 fallback 混淆百分比体积指标与绝对体积指标，必须保留不同 key/单位，缺失不能冒名替代。
- coverage 只模型化少量方面；“脊髓受到多少辐射”没写“器官/OAR”，required 为空，target-only contract 被判 covered；“每根针有多少粒子”未识别单字“针”，只要求 seed_total。
- 未声明 `covers` 的 contract 被视为覆盖整轮。截图复合请求 required 为空也通过这一 metric helper；这不是截图整链必败的证据，而是该 helper 不能充当通用完整性证明。

修复：任务的 required outputs 来自结构化目标，不从最终问题重新跑词表；工具结果声明具体资源/字段/覆盖对象/版本/单位。未知 coverage 是 unknown，不是 covered。小型直读保留快速路径，复杂需求用结果集合对齐任务。

验收：脊髓/英文别名/左右器官、每针明细、全体 OAR、score 缺失/过期、D2 和 D2cc 同时存在/只有一个、手动编辑后旧 DVH、切换不同计划、真正零剂量与未计算区分。

### F14｜P1｜报告/参数等完成状态仍可能只代表 DOM 已设置（S/R）

位置：`brachybot-ui-api.js:8260` 参数/超参数，`:8334` report.field.set，`:8349` report.template.set；报告编辑/导出分别见 report-editor、report-shell、report-export。

确认：某些参数应用不等待异步结果，applied=0 也可能成功；report field 路径设置 DOM 并安排 autosave，并未把持久化确认纳入当前动作成功；template set 缺少完整存在性校验。`input.*.browse` 只是打开文件选择器。

修复：区分 displayed/applied/persisted；报告 dirty 与保存 revision 分开；不存在字段/template 明确失败。下载完成、导出已生成和点击下载不是同一事件。对临床字段编辑保留审计与版本，不能把直接 DOM 改字当成成功修改报告。

验收：编辑后刷新/切会话、保存失败、只读报告、模板不存在、语言切换含图注、导出与当前草稿版本一致；参数无匹配项给出明细。

### F15｜P2｜动态事件扫描不构成完整稳定的业务能力目录（S/R）

位置：`brachybot-ui-api.js:364–415` 的 EventTarget ledger；`web/app/index.html:1599–1601` 及脚本加载顺序。

确认：ledger 只记录 Element，不覆盖 document/window 上的委托交互；此前注册的事件也不可回溯。集合持有 element 强引用；disconnected 过滤与一次性/AbortSignal listener 生命周期不等同显式回收。

风险：canvas/热键/委托菜单不可发现、旧对象残留、长会话目录与内存增长。本次未做 heap profile，因此不称作已测量的内存泄漏。

修复：显式业务 capability registration 为主，DOM 扫描仅诊断/补漏；组件卸载取消注册，动态对象引用通过资源索引解析。禁止仅依赖抓所有 `addEventListener` 来宣称任意操作已覆盖。

### F16｜P2｜现有正确改进应保留，但需要跨层而非单点验收（S/T/E）

导板 leaf 显示、tree visibility 结果修正、截图顺序/恢复、Monitor fencing、manual-step results、活动规划读取等已有实现和部分测试。本报告不把历史截图中的所有问题再次列成“当前确定 bug”。

需要补的主要是集成验收：目标在相机投影范围不等于无遮挡；相机/可见性恢复应与用户并发操作协调；manual phase 的 init/refine/seed/dose 结果必须在真实 Viewer 和 reload 后一致。相关源点包括 `brachybot-ui-api.js:11887`、`:12291`，`brachybot-manual-step-results.js`，`brachybot-monitor-interaction.js`，`brachybot-monitor-dashboard.js`。

## 5. 全部前端领域的对等性矩阵

标记：**部分**表示已发现对应能力或通用入口，但不能证明端到端完整；**缺口**指本次确认的契约不足；**待 E2E**指必须真实操作验证。完整低层控件/事件/路由逐条列表见附件，下面是业务能力分解。实施 agent 必须给每项建立能力 ID，不能以“一行已有工具”销账。

| 领域 | 手动入口/动作范围 | 已有代码或通道 | 审计结论与必须补齐 |
|---|---|---|---|
| 登录与权限 | 登录、退出、角色和会话所有权 | auth JS、后端 auth routes | 应识别但不代输/泄露凭证；执行前后同样鉴权；待 E2E |
| 病例会话 | 新建、切换、重命名、删除、清空、恢复、缓存恢复 | session.*、workspace/session-cache | 部分；切换后所有对象/任务 ref 失效；删除不可借 generic UI 绕过确认 |
| 文件输入 | CT、mask、OAR、DICOM-RT、报告/STL 导入 | input.*.browse、import actions | 缺口：打开选择器≠上传；需要等待文件/进度/解析完成和稳定资源 ID |
| 输入模式 | model、site、CT phase、多卷数据、规划模式 | planning.parameter、parameter catalog | 部分；模型部位必须匹配当前病例，动态 options 要有版本 |
| 参数 | 阈值、处方、粒子、针道、规划超参数、导板参数 | parameter.set、planning.hyperparams.set 等 | 缺口：数值类型、相对量、批量明细、applied=0、异步保存 |
| 自动分割 | CTV/OAR 单项、多项、指定模型、整流程 | dedicated clinical tools | 保留专用执行器；不能因“全部更新”重新分割；模型别名不代替部位验证 |
| 手工 mask | 新建、画笔、擦除、阈值、矩形、SAT3D、结束、重命名、移动、删除 | mask.*、viewer.tool、manual-annotation | 部分；选择工具≠完成标注；需患者/体素坐标输入和提交/撤销事务 |
| Step-by-step | init/refine/seed/dose/evaluation、当前步骤产物显示和下一步隐藏 | plan.run_manual_step、manual-step-results | 部分；真结果节点/可见性/刷新恢复待 E2E；失败下一步不隐藏唯一有效结果 |
| 整体规划 | 启动、暂停/取消（如现有）、查看进度、完成、复用 | plan.run、planning_pipeline、task routes | 部分；尊重任务所有权、resource lease，禁止重试多次启动 |
| 下游更新 | 剂量、质控、评分、导板、报告、显示增量更新 | downstream_update、临床 tools、UI actions | 需要依赖图与有限 scope；report 如包含导板结果，必须在相关导板步骤后 |
| 2D 浏览 | 三轴切层、单轴缩放/平移、窗宽窗位、flip/rotate/fit/reset | slice.*、viewer.*、manual-annotation | 缺口：通用手势和 typed scope 不等价，见 F09 |
| 2D 测量 | 十字线、距离、角度、框选、历史撤销/重做 | viewer.tool/transform、canvas listeners | 部分；工具激活不代表测量已完成；单位与变换链必须核验 |
| 3D 浏览 | orbit/pan/zoom、fit、视角、全屏、重建、depth peeling | viewer actions、scene catalog、viewer-volume/layout | 部分；坐标和相机能力需显式 schema；不可只依赖拖 canvas |
| Data Tree | 单项/组显示、父组状态、2D/3D 分离、opacity/color、重命名/分类/选择 | tree.*、context action、virtual catalog | 部分；大场景截断、稳定对象引用、颜色按钮与渲染一致性要闭环 |
| Data Tree 资源操作 | 导出、删除、重建、mesh/mask 分组 | data-export、context menus | 不能一律按低风险 display 授权；对象权限/依赖失效/恢复需专用 receipt |
| 针道编辑 | 新增/选择/端点移动/删除/方向、preview→commit、取消 | manual.needle.*、3d-manual | 部分；明确哪个端点、患者坐标、geometry revision；自动投影关联粒子不计多次用户编辑 |
| 粒子编辑 | 添加、移动、删除、沿针道投影、间距校验 | manual.seed.*、manual planning routes | 部分；真正业务结果、安全限制、冲突时保留或复位、并发版本需要统一 |
| 手工重算 | 剂量预览、重算、再规划、finish | manual.dose.recompute/plan.* | 必须区分 preview/committed/dose_revision；不能为了回答偷偷跑昂贵重算 |
| Analysis/DVH | CTV/OAR 各项、单器官、每针粒子、评分、热点、曲线控制 | query_metrics、dvh-planning | 已有 OAR 查询；缺口是发现/覆盖/版本/单位，不应另造一套虚假统计 |
| 导板 | generate/analyze、参数、版本、几何 QA、显示、导出/import STL | surgical_guide、surgical-guide JS、tree.* | 保留专用路径；保存存在≠显示存在；stale 不等于不存在或不可截图 |
| 报告正文 | 字段、模板、章节开关、引用、评论/审阅/验证、布局 | report.*、report-editor/shell | 部分；持久化 ack/权限/输入消歧/语言切换必须覆盖 |
| 报告产物 | autofill、截图、快照、审计、导出 PDF/其他格式 | report.autofill/export/snapshot.* | 不把截图计划/导出开始当完成；报告专用相机策略不应污染聊天定位策略 |
| 聊天截图 | 对象定位、多个目标、Data Tree/3D/2D/DVH、标注 | ui_screenshot、visual-annotation、ui-api | 基础已改善；需按 object/step/view/evidence ID 并列，不拼接未经核验预答 |
| Monitor | start/stop/status、HUD、advice、focus、auto compare、undo/keep、summary | training.mode、monitor dashboard/interaction、training routes | 不以灯效作为 run 真相；服务端 lease/stop acknowledgement 和版本化 edit 决策贯通 |
| 聊天任务 | 发送、排队、取消、重试、断线恢复、压缩、历史、附件 | chat-core/todo、chat task/context code | 统一 turn/step/job 终态；累计调用 token≠上下文占用，显示口径清楚 |
| 全局 UI | 中英文、主题、面板/sidebar、布局 | chat.language/theme、panel/layout | 低风险快路径；locale 传至 Monitor/图注/按钮，不能被英文 keep 回复改变 |

特别说明：页面中有某按钮、registry 有名字、接口能返回 200、既有单测通过，这四个事实都不能单独把表中任一行标成“完整对等”。

## 6. 推荐底层设计：复用现有模块，建立一个业务契约

### 6.1 统一能力目录，而不是统一所有关键词

为每个业务能力定义：

```text
capability_id / schema_version
description / examples / supported_object_types
input_schema: ref, scope, axis, value, unit, absolute_or_delta, ...
read_selectors / preconditions / effects / postconditions
risk_class / permission / confirmation_policy
executor / async_job_kind / idempotency_scope
undo_policy / invalidates / locale_keys
evidence_schema / result_schema
```

数据目录只提供对象实例：`case_id, planning_id, object_id, kind, label, revision, parent, loaded, own_visible, effective_visible, stale, capabilities`。可显示的人类名称不能当唯一 ID。

`CONTROL_REGISTRY` 和前端 handler 保留兼容入口；逐步从同一 schema 生成工具说明、前端目录、校验器和 parity 测试。不能在 Python/JS/提示词分别手工维护三份含义不同的注册表。

### 6.2 任务理解 IR：把“用户要什么”和“怎么执行”分开

建议内部表示（不是要求新外部 API）：

```json
{
  "request_id": "...",
  "case_id": "...",
  "intent_source": {"turn_id": "...", "text_spans": []},
  "goals": [
    {
      "goal_id": "g1",
      "speech_act": "request",
      "object_query": {"kind": "surgical_guide", "scope": "active_plan"},
      "desired_effect": {"property": "effective_visible", "value": true},
      "constraints": {"preserve_other_objects": true},
      "polarity": "positive",
      "quoted": false,
      "precondition": null,
      "required_evidence": ["visibility_receipt"]
    }
  ]
}
```

IR 不是新增“大模型一说就执行”的后门。要用有界 schema、来源跨度、当前资源、权限规则和必要确认验证。高风险含糊请求先澄清；只读状态发现可自动完成。

本地明确请求走快捷 IR，不增加 LLM；复杂请求一次批量理解，不对子任务逐个重新识别；对象缺失时先 targeted discovery。简单意图模型不应凭置信度自行授权临床变更。

### 6.3 指代和后续指令是持久任务上下文，不是全文关键词继承

保存 `pending_goal_set`、`offered_action_set`、`approved_scope`、`case/plan_revision` 和失效时间。

- “那就全更新”引用最近相关、同病例且仍有效的产物集合。
- “为什么不执行”是解释/纠错，不从一句质问无限扩大临床授权；若此前授权仍有效，检查原任务失败原因和重试安全性。
- “保留/复位”绑定具体 edit decision，不根据回复语言改变全局 locale。
- 切病例/切计划后旧审批、旧对象和坐标必须失效或要求重新确认。
- 压缩历史保留结构化待办/授权/失败原因，不能只留泛化自然语言摘要。

### 6.4 授权策略按 effect 和风险，而非一刀切问号/工具名

建议分层：只读资源查询；低风险可逆显示；持久 UI/报告编辑；临床几何/剂量/分割变更；破坏性操作/导出敏感数据/权限操作。

“可以帮我显示导板吗”属于低风险执行请求；“你能生成导板吗”可能是能力问句；“如果将来生成导板会怎样”是假设讨论。需要语义判别与上下文，不是统一拒绝所有疑问句。

只读前置查询不需反复征求“是否允许读取”；缺少 mutation 权限不能阻止已有授权的独立只读任务。对高风险动作应有有限 scope 的明确授权/确认句柄。工具 payload、网页、报告和模型自己的建议不能作为用户授权来源。

### 6.5 一个执行账本，统一 UI 与后台任务

统一标识：`request_id → goal_id → step_id → operation_id/job_id → evidence_id`，额外带 case、plan、geometry/dose/report revision。

推荐状态：`planned / resolving / waiting_confirmation / queued / running / verifying / succeeded / failed / cancelled / blocked_by_dependency / expired`。浏览器事件派发为中间事件，不是 succeeded。

- 后端 UI tool 返回 accepted/queued；浏览器 receipt 反向进入同一任务，而不只是修补页面文本。
- step 成功需验证结果 schema、业务结果和必要持久化/显示后置条件。
- 超时不是自动“没执行”；明确 unknown outcome，先查 operation ID 再重试。
- 相同对象写操作/相同 Viewer capture 事务串行；独立读取可并行。
- 依赖图按实际版本要求构建。报告若包含导板版本/QA/截图，先满足导板结果再生成报告；不能固定写成永远“报告在导板前”。
- 取消/断线后后台任务继续与否必须明确，并可恢复跟踪，不能关闭光效就认为后端停了。

### 6.6 统一状态与证据，不把所有状态塞进 prompt

资源查询示例：`active_plan.summary`、`objects.resolve`、`oar.metrics`、`viewer.state(view_id)`、`report.fields`、`monitor.run`、`operation.status`。

每个结果带来源、revision、generated_at、stale_reason、完整性/分页、单位。请求指定字段，禁止为一个器官问题复制整个场景/所有体素。

“不存在”要求在权威资源里完整查询无结果；“未加载”由 Viewer state 证明；“隐藏”同时考虑父组；“未知”可以进一步只读发现，而不应机械地让用户再问一句。

### 6.7 最终回复必须从完成账本生成

每个 goal 记录 requested/attempted/result/evidence/remaining。最终回答只使用已接受的当前版本证据，模型的 preliminary text 不作为截图结论。

简单显示成功：“已恢复显示导板 Puncture guide v1，其他对象未改变。”只有已核验才说。

部分成功：“导板已显示；肿瘤对象有两个同名节点，需要选择一个。没有调整它们。”避免通用“没有可验证分析结果”掩盖真实阻断原因。

对剂量问题按用户粒度回答；已有 OAR 数据就读取，不能再询问“是否允许读取”。临床阈值未知可以说未知，但不妨碍报告实际测量值。字段缺失/零值/过期结果必须分别表述。

UI 的 trace、progress、发送按钮、最终回复状态取同一 turn 状态。只生成一个 final step；截图/报告保存未结束时保持相应 pending，但不能在无剩余作业时无限 pending。

## 7. 用户体验、延迟与成本要求

以下是建议验收目标，不是本次实测性能承诺：

| 场景 | 决策策略 | 建议限制 |
|---|---|---|
| 明确低风险单项显示/切层/主题 | 本地 IR + 资源引用 + 同一 executor | 不新增 LLM 往返；本地决策开销 p95 目标 <200 ms，渲染另测 |
| 复杂多需求 | 一次批量语义理解，结果缓存到 turn | 不逐子任务发独立理解请求 |
| 大 Data Tree | 对象索引 + 类型能力 + 查询/分页 | 200–1000 粒子不复制数千完整动作描述到每轮 |
| 只读剂量/状态问题 | 定向权威查询 + 直接证据合成 | 不偷偷触发规划/重算/截图；缺必要字段最多定向补读 |
| 异步长任务 | 立即返回 task accepted + 持续真实进度 | 时间拆为决策/排队/计算/渲染/保存，不伪报已完成 |
| 需要用户选择 | 一次列出必要选项和对象差异 | 不反复问已经回答过的确认；不让模型循环猜 |
| 可逆显示 | 精确修改必要对象 | 不无故改色/清空场景/改变其他窗口；用户操作优先 |

需要实际记录：local hit rate、语义解析耗时、每轮模型调用数、catalog 字节/token、查询次数、错误拒绝率、未授权执行率、首反馈时间、业务终态时间、状态同步延迟、重复操作次数。

不能用“永远多想一轮 LLM”解决所有问题，也不能用“凡有关键词就走模板”降低延迟。应使计算量随请求复杂度增长，而非随病例完整数据大小增长。

## 8. 实施工作包（给后续 agent）

> 当前进度：WP0测试基础有效；WP1部分完成，未闭环；WP2–WP5按§0A销账；WP6五项fixture浏览器测试已通过，真实病例E2E待验证。以下为完整工作包设计，不代表这些工作尚未开始。

### WP0：固定基线与建立可回归验收（先做）

- 重新读取远端当前 HEAD/dirty diff，不覆盖其他 agent 修改。
- 把附件探针转为正确行为断言；记录现有 139 项测试基线；补真实浏览器环境。
- 给每个静态控件/动态事件标 `capability_id 或 UI-only/安全例外`，禁止无理由遗漏。
- 形成正式 parity matrix：支持/部分/待实现/例外/待验证，并链接测试 ID。

### WP1：执行与结果基础契约（P0，优先于扩语言）

修复 F02/F03/F07/F12：receipt、step 身份、依赖结果、幂等、异常传播、版本同步；UI action accepted 与 completed 拆分；统一状态机。先保留旧接口适配，迁移 report/guide/manual 等关键能力。

验收后置条件：同一用户任务不会 UI 已结束而后端仍误挂；独立子任务不中断；所有假成功探针消失；失败有可读原因。

### WP2：能力和对象目录（可与 WP1 的 schema 并行）

修复 F06/F08/F11/F15：注册表单一来源、实例资源索引、分页、稳定 ref、作用域、selector 边界。保留 DOM 扫描用于发现未接入能力，不赋予其业务权威。

验收：正常大规划完整发现；查询导板不会落到源码搜索；同名/隐藏/未加载/过期区分；过期 ref 不操作新对象。

### WP3：语义任务与权限（依赖 WP1/2 契约）

修复 F01/F04/F05：快捷 IR、语义 fallback、source span、分别参数、有限聚合 scope、显式拒绝回执。给常见单意图保留零额外模型调用；不要把旧 parser 一次性全删除。

上线建议：先 shadow 比较新旧计划，仅旧路径执行；对有依据的差异分类，然后按能力启用。阴影日志去标识化，不存原始病例影像或敏感凭证。

### WP4：手动/对话共用业务执行器

按风险分批：显示/颜色/opacity → MPR 轴向控制 → 参数 → 报告 → manual editing → monitor → 临床生成/删除。修复 F09/F10/F14。每迁移一个能力，将手动按钮也接到同一 command，避免两套逻辑继续漂移。

### WP5：状态查询与回答覆盖

修复 F13：typed resource query、真实 OAR/needle breakdown、revision/units、required_outputs、evidence ledger、partial reply。把最终回复“无证据”与图像已经附加的矛盾纳入集成测试。

### WP6：全产品 E2E 与发布

完成第 9 节；用户验收真实已完成规划病例。按独立 LAN 服务流程发布，确认 listener/process/cwd/assets/健康和任务恢复。**本报告本身不授权重启服务或改动 release 部署。**

## 9. 验收矩阵：不能只测几个例句

### 9.1 语言与授权（中英双语、释义保留集）

至少包括：

1. 命令/礼貌请求/能力问句/为什么/假设讨论/引用/转述/否定/双重否定/纠正。
2. 中文标点、无标点、英文 and/then/respectively、口语错字、对象别名。
3. “分别”多目标参数绑定，共享动作，共享修饰语，混合读写，条件前置。
4. “它/刚才那个/这些/全部后续”同病例引用、跨病例失效、已有 pending confirmation。
5. 明确正向子任务可执行；否定/引用的相邻子句不能借目标或动作拼接授权。
6. 读问题自动获取必要只读数据；不以只读问题触发生成、删除、规划。
7. 任一模型 provider 输出未知 target、错误类型、伪造 ref、空工具结果、重复 calls、漏步骤时有边界响应。

不能只把探针例句加进训练/规则后重跑同句。保留一批未参与实现的用户释义和复合任务，衡量任务达成率/错误执行率。

### 9.2 业务执行等价性

每个 capability 最少有：手动入口 → receipt；对话入口 → 相同业务函数 → 相同状态变更；权限相同；失败语义相同；刷新后状态相同。需测试 0/1/多个对象、loaded/unloaded、hidden/parent hidden、valid/stale、saved/preview。

Data Tree 显示/opacity/color 应同时核验树按钮、2D/3D actor、保存与恢复；不能只验证函数被调用。患者坐标命令应核验图像方向矩阵/spacing/axis，不能仅屏幕接近。

### 9.3 调度与恢复

- 多个同名工具、不同目标、不同参数；A→B→A；独立失败继续；依赖失败阻断。
- 同 Viewer 截图串行；用户在事务中改变视角/可见性时，不用旧快照覆盖用户新操作。
- 网络断连/刷新/切病例/重复消息/按钮连点/取消/超时后恢复，无重复 clinical job。
- 确认对话关闭/未确认、真实文件选择取消、导出被浏览器拦截有正确状态。

### 9.4 Monitor 专项

监测不是简单定时聊天：每次 committed edit 有之前/之后几何、关联对象、冲突新增/消除、可比剂量版本、明确 undo/keep token。展示 screenshot 依赖对象存在和 Viewer ready；无图说明具体失败，不能只是说“已经捕获”。

起停/lease 权威在后端，UI 灯效不是状态源；stop pending 可恢复且幂等。建议区分几何事实、剂量变化、临床解释；无相同基线不归因。Auto Compare 保持 opt-in，不隐藏昂贵重算。

语言使用 run/用户设置的 locale；回复 `keep id` 不改变后续中文反馈。可视化证据、按钮、toast、progress、summary 都纳入 locale 测试。

### 9.5 报告/截图专项

- 聊天定位优先保留用户画面；目标被遮挡/隐藏时最小临时调整，说明并恢复。
- 报告图片采用自己的稳定相机/构图策略；Fig1(a)/(b) 目标占比、裁切、参照方向用实际图片验收，不只检查 camera API 被调用。
- 相同 turn 两个对象各自有附件 ID，后图不能覆盖前图；preliminary reply 不以最终回复样式泄出。
- 报告正文、图注、标题、导出语言一致；数字小数和 Markdown 表格不能被“断句清理”破坏。
- 最终回复/发送按钮/progress 基于同一终态；一次 turn 仅一个 final step。

### 9.6 性能与安全

200/500/1000 粒子目录、低带宽、慢 GPU、离线浏览器、两标签页。记录 p50/p95 而非只报告一次时间。不得以截断后误报不存在降低 token；不得把完整场景放入每次小交互请求。

## 10. 当前能保留的正确实现和禁止的“修复捷径”

保留：活动规划上下文和后端真实数组注入；不能让模型覆盖运行时数组。保留已有 Monitor run/plan/geometry 围栏、导板 leaf 解析、截图恢复、临床专用工具和医师复核边界。

禁止：

- 为每句失败中文再加一条特殊 if；
- 将所有问句都视为只读，或所有动词都视为授权；
- 扩大 `aggregate_command` 使所有 mutating tools 放行；
- 认为返回一份更长工具列表就解决能力发现；
- 让模型任意 selector/JS/shell 执行替代业务 API；
- 在点击/派发成功时汇报临床操作完成；
- 把源码文字搜索结果当作病例对象真相；
- 把未声明覆盖范围的结果视为“已答完”；
- 以“测试全绿”掩盖浏览器未跑、真实 GPU 未跑或历史断言被削弱；
- 为此覆盖独立 public-release 工作树、共用可写 runtime 或重启另一套服务。

## 11. 完成标准与交接要求

实施完成不能只说“新增智能路由”。必须交付：

1. 全部 UI 候选条目已分类，动态菜单/手势/键盘路径另有补充清单；每项映射 capability 或书面例外。
2. 注册 schema、执行器、授权/确认策略、状态来源、后置条件、receipt、测试 ID 一一可追踪。
3. F01–F15 对应缺陷已修复或有明确未完成项；不得静默删除失败探针。
4. 前端手动与对话共用执行器的证据，至少涵盖所有临床写操作与关键显示/报告/Monitor 路径。
5. 保存真实 E2E 证据：已完成规划 → 隐藏/恢复导板 → 分别定位导板/肿瘤 → 读 OAR 剂量 → 手动编辑 → Monitor 提醒/截图 → keep/undo → 必要重算 → 有限范围下游更新 → 报告导出 → 刷新恢复。
6. 部分成功、澄清、取消、网络异常、任务恢复、重复调用等不再以机械模板掩盖原因。
7. 对短请求调用数和延迟不回退，复杂请求不按子任务倍增理解轮次；报告实际测量与测试环境。

**最终判断：本次审计证明了当前“不完全对等”，并定位了跨语义、授权、状态、执行、证据的可修复根因；没有证明任意自然语言已被完全理解，也没有进行完整真实病例端到端认证。应按本报告建立可持续的能力对等验收体系，而不是宣称一次性“知道所有一切”。**

## 附件索引

新增复审附件：`docs/audits/nl-ui-parity-review-20260928/`，详见§0A.5。以下原始附件保留其初审基线含义。

- `audits/nl-ui-parity-20260928/README.md`：证据等级、复现方式与文件说明。
- `source_manifest.csv`：505 个源码文件、行数、SHA-256。
- `static_controls.csv`：264 个静态控件/事件候选及 index.html 行号。
- `control_handler_index.csv`：静态控件内联调用与 JS 函数候选位置，非完整调用图。
- `event_sites.csv`：568 个事件注册/内联事件行及源路径。
- `production_routes.csv`：122 个生产 route 声明及方法。
- `capability_registry.csv/json`：全部 111 个 UI target 的现有 schema。
- `capability_source_index.csv`：每个 target 的注册位置和前端字符串引用，需继续核验实际执行分支。
- `test_inventory.csv`：1,649 个 Python test 函数声明清单。
- `audit_probes.py/json`：语义/权限/依赖/回答覆盖隔离探针及基线结果。
- `audit_browser_probes.cjs/json`：实际前端函数的 VM 探针及基线结果。
- `inventory_summary.json`：清单汇总。

源码定位均针对文首基线。后续代码变化后必须按函数名重定位，不直接照抄旧行号修改。
