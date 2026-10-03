# BrachyBot：所有后续正式 benchmark 统一使用真实用户对话入口

生效日期：2026-10-04。依据用户要求：“向用户对话框输入需求那样进行测试，模拟用户输入了该题”。适用于自建 PRV 与公开 EXT 测评；本次仅构建入口、约束与离线回归，不启动模型测评。

## 1. 要测的是完整产品，不是替它答题的底层模型

正式实验路径固定为：

`独立测试病例/会话准备 → 页面 #chatInput 输入该题 → 点击 #chatSendBtn → 页面自己的路由、会话与鉴权 → 用户需求解析与授权 → 工具执行 → 浏览器可视化/截图/报告等后处理 → 最终可见回复 → 独立采集、判分`

采用实际输入框与发送按钮，而不是直接调用 `sendChat()`、`chat_with_trace()`、LLM provider、内部工具或手工构造 `/api/chat` 请求。这样也保留页面本身对 monitor、继续任务、压缩等控制指令的识别；不能为了方便测评强迫这些指令走 LLM。

`/api/chat` 的普通用户 POST 可以作为**观察证据**，但仅调用此 API 不能证明浏览器完成截图、报告保存或渲染。服务器工具“已派发”、SSE EOF、回复第一段已出现，也都不是整个用户任务完成。

## 2. 输入边界

- 只提交当前题目的公开用户需求与合法资料；评分标签、参考答案、oracle、rubric、预期工具、未来问题不交给 BrachyBot。
- 多轮题在同一独立会话依次发送。第 N+1 轮只能接续前 N 轮的真实回复，不能以参考答案替代历史，也不能把整套未来对话提前塞入上下文。
- 图片必须经实际可用的用户上传交互进入产品；CT、病例、规划与语料必须通过经过核验的环境准备流程装载。不得把图片文件名当成已看图，不得用纯文本替代缺失影像。
- 系统/assistant/tool 消息不是用户授权。公开 injection benchmark 的恶意内容必须在真实的低信任检索/工具返回来源出现，不能改成普通用户命令后冒充原始攻击协议。
- 手动按钮事件、病例切换、后台事件可由独立环境驱动器模拟，但不可预先执行本应由 BrachyBot 根据题目完成的动作。没有相应驱动器就 BLOCKED。

## 3. 完成、失败与效率

对普通文本对话，记录实际普通用户网络请求、用户回显、request/user-message/assistant-message ID、所属 session、全部轮次的最终原文/渲染文本、附件与工具追踪。

完成需同时满足：会话未换；当前用户回显与题目一致；最终回复身份一致且唯一；最终回复/附件已挂载；追踪不再 pending；普通流、隐藏视觉续轮、pending 截图回复与停止屏障等已收尾。至少跨两个观察时刻确认，避免把同一事件循环里的短暂空闲当成完成。

独立采集器还须核验服务端任务终态、UI-action receipt、报告保存、规划版本、几何 revision、产物哈希以及临时状态恢复。浏览器入口证据**不能代替**这些任务级判据；看到一段自然语言不是医学/几何任务通过。

超时、错误病例、重复最终回复、状态不一致：记录真实失败/证据不足，不伪造完成、不自动重发题目。预算包含用户等待前端后处理的时间。报告 provider 延迟、工具延迟与用户端总耗时，避免只报 LLM 时间。测试账号、运行目录和病例必须与现有使用中的病例和公开发布服务隔离。

## 4. 代码实施范围

- `benchmarks/execution_policy.json`：PRV/EXT 共同的后续正式实验政策。
- `benchmarks/user_chat_contract.py`：输入身份、隔离、轮次与完成证据契约；EXT 的 `UserChatHandle` 只能绑定真实浏览器会话。
- `brachybench/tools/adapters/user_chat.py`：对 evaluator 准备好的 Playwright Page 进行真实 `fill` + `click`；只读采集 DOM/页面状态与网络身份。不会在导入时创建浏览器、启动服务器或调用模型。
- `run_task.py`：正式入口拒绝任意 Python/direct-agent adapter；独立采集器和回答/完成判据缺失时，在提交前拦截；正式结果需要 harness-owned 用户对话执行证据。
- `live_smoke.py`：不再因环境里有 provider key 而自动创建 BrachyAgent；没有隔离浏览器和独立评估配置则 BLOCKED。
- `external/adapter_base.py`：默认拒绝任意模型回调。离线 E0/回归必须显式 `evaluation_mode=component_self_test`；不会算正式结果。

这是一条可信 harness 的执行契约，**不是对恶意 Python adapter 的 OS 沙箱**。真正实验仍须将私有金标准与 SUT 文件系统、权限和进程隔离；不可把“有某字段”当作防篡改证明。

## 5. 当前可用范围与明确未完成事项

默认浏览器驱动器支持：已独立准备好病例/会话的普通**文本**用户对话及依次发送的纯用户多轮问题。必须配置 evaluator-owned browser session factory、fixture driver（题目有前置状态时）、独立 collector、response checker 与 completion checker。

以下不会偷偷降级，当前默认驱动器明确拒绝或未认证：

1. 图片/病例上传题：还需实际上传 UI 驱动与读入证据。
2. monitor/压缩/继续等前端控制题：输入路径必须仍是对话框；不能要求它们产生普通 `/api/chat` 最终回复。本版通用文本 driver 不能判这些控制题完成，需独立的控制动作终态判据再开放，当前 BLOCKED。
3. 带 UI/background/non-user event 的协议：需独立事件调度器。
4. 固定检索库、外部工具仿真、攻击工具返回：需原生环境集成；否则只保留资产，不正式运行。
5. 真实环境 factory/登录/病例导入/产物独立采集：本次没有替当前临床服务搭建测试账号或安装浏览器，也没有提供伪 fixture 安装器。不得宣称所有历史题已经能在真实页面跑。

这些是实验前提，不是把题目删掉。报告需给出 eligible / blocked / excluded 数量与原因，禁止仅展示跑得通的题造成选择偏倚。

## 6. 公开 benchmark 如何执行与命名

资产仍完整保留，原始 scorer 不随输入入口要求被放宽。逐 benchmark 的门槛见 `external/public_collection/user_chat_eligibility.json`。

| 类别 | 后续处理 |
|---|---|
| 医学文本问答、纠错、计算、安全与幻觉题 | 将原始公开题干/资料按核验过的模板作为当前 user turn，经实际页面提交；答案格式/判分/预算是否与原版一致单独认证 |
| CMB-Clin、临床记忆与长文本 | 逐轮真实发送；不得 teacher forcing；记忆初始化与文档组合需要可追溯的产品对话/上传协议 |
| 真实医学图片题 | 只有实际上传可用并验证成功才运行；Text/MM 分开 |
| R2MED / NFCorpus / SciFact 检索 | 产品须接入同一冻结公开语料并通过实际检索工具取得 ranked IDs；不可直接调用一个 retriever 冒充 BrachyBot 用户任务 |
| When2Call / BFCL | 外部工具与 likelihood/AST 原协议不能通过普通聊天自动成立；保留方法学/资产，原生产品运行 BLOCKED；若改为解释/JSON 答题，只能另名 user-chat-adapted，不能挂原 leaderboard 分数 |
| InjecAgent / ABRA / AgentClinic | 外部执行器、患者模拟器或 OHIF/Orthanc 缺失时 BLOCKED；不得以关键词、最终文本或合成场景代替完整交互环境 |

此前文档中 common-harness / raw-model 建议仅保留历史方法背景；不再是此项目后续正式 BrachyBot 测试入口。入口一致不等于原生协议一致。改编题须与原始 benchmark 名称/成绩分栏，不混总分。

横向比较：各产品都从其公开用户交互入口接收同题同资料；明确共同可完成的能力边界。若另测底层模型，那是独立模型实验，不是本政策下的 BrachyBot agent 测评。付费模型的供应商原生 API可作为对方产品的公开用户入口，但不得借其回答替代 BrachyBot 的执行；与浏览器产品的证据、UI能力和延迟口径差异要披露。

## 7. 运行配置示例（本次不执行）

```bash
cd benchmarks/brachybench
export BRACHYBENCH_BROWSER_SESSION_FACTORY=my_eval.browser:prepared_session
export BRACHYBENCH_BROWSER_FIXTURE_DRIVER=my_eval.fixtures:prepare_isolated_case
python tools/live_smoke.py --task tasks/D1-SA-007.json \
  --evaluator-config /private/evaluator.json \
  --collector my_eval.evidence:collect \
  --response-checker my_eval.grade:answer \
  --completion-checker my_eval.grade:completion
```

`prepared_session(scope)` 应返回绑定隔离页面的 `BrowserChatSession`；`prepare_isolated_case(task, initial_state)` 是私有 evaluator 环境驱动器，不是 SUT 的答题入口；`collect(session, context=...)` 只读采集该 execution 的真实状态与产物，不能改写最终回复。

旧 replay 与直接 agent 的 regression 单测仍可运行，用于验证解析/判分组件，但一律 `component_self_test`。不能将这些单测通过数、expected-positive replay 或构建验证用作实验表现。

## 8. 本次验证

仅离线回归与语法/差异检查；未连接实际页面发送问题，未调用 provider/judge/GPU，未生成临床规划，未重启现有服务。验证结果另见 `benchmarks/user_chat_validation_2026-10-04.json`。原有封存 manifest 不自动续签；发生 runner 变更后，正式实验需重新核验并冻结协议版本。

新增入口契约单测 37 项通过；自建 benchmark tests 与公开集合 tests 联合回归 **24,293 passed / 2 skipped / 0 failed**，161.55 秒。两项 skip 均因隔离验证环境缺少 `pypdf`。这不是模型成绩，也不能据此宣称真实浏览器/上传/控制类题已经完成环境认证。
