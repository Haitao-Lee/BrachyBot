# 真实用户需求 benchmark：可执行开发版建设记录

日期：2026-10-03。基线：远端 BrachyBot 当前工作树；仅修改 benchmark 扩展及文档，保留原 11,969 题、原 gold、split、replay、results、MANIFEST 和生产服务。

## 1. 本轮范围和完成边界

用户明确要求“把 benchmark 构建完整即可，不用跑出测评的结果”。因此本轮交付是可构建、可执行、可独立采集、可进入既有判分框架的 **开发版测评工程**。不启动 BrachyBot/其他模型做题，不调用 provider，不运行 GPU 医疗规划，不产生 agent 性能分数或排名。

原扩展的 40 个场景族、82 个逐题场景继续保留；没有用同义句、随机数字或机械排列扩题凑量。原始场景的真实意义、失败假设、允许效果、局部条件、实际用户轮次、数据来源及 246 个负控规格仍可追溯。新结构化 gold 按逐题人工意图编写，不引用 SUT parser/policy，也不从 SUT 输出反推答案。

**建设完成 ≠ 科学/临床验收完成。** 当前是 development/exploratory；独立语义审查、judge 校准和产品级真实浏览器验证没有被虚构。所有题的 confirmatory_eligible=false；不将这些题加入正式主实验分母或 sealed split。组件自测不是 SUT 成绩。

## 2. 工程结构

位置：`benchmarks/brachybench/extensions/real_user_requests_v1/`。

| 层 | 文件/目录 | 作用 |
|---|---|---|
| 人工场景依据 | catalog.py、candidate_pack.json | 原文、状态、允许/禁止效果、验收、负控；保留 authoring 溯源 |
| 逐题可执行契约 | contracts.py | 82 个显式目标/允许效果/依赖/终态/回复事实，不按关键词生成 gold |
| 完整 fixture | fixtures_runtime.py | 完整稳定对象、真实坐标/相机、OAR 零/缺失/过期、53 明确器官行、可解析 PDF |
| 私有条件事件 | event_driver.py | 所有原始事件都有 handler；首个请求前装载、按 barrier 注入、记录未触发事件 |
| 独立环境/观察 | environment.py | 实际合成效果、attempt/commit、作业/撤销/取消、幂等、版本 fence、状态保存/恢复、交付 |
| 判分 | oracle_runtime.py | 注册 real_user_request，复用现有 OracleResult、EvaluatorContext 和 gate；独立回复评审 |
| 构建 | prepare.py、compiled/ | 确定性包装/fixture/gold/事件/复核卡和 hash manifest，支持 --check 漂移检查 |
| 将来的执行入口 | runner.py | opt-in JSONL worker；默认检查，--execute 才运行，输出 recording，不自动产生成绩 |
| 独立人审入口 | review_cli.py | 空白 review form、已认证 recording 的离线评估；null 不算 true |
| 协议 | PROTOCOL.md | 工具语义、进程/信任边界、合法替代、可比性、未来运行说明 |
| 测试 | test_runtime_contract.py、原 authoring tests | benchmark 自身的组件/反例测试，不是 agent 测评 |

构建产物逐题包括 task、fixture、private contract、event script、meaning/review card 各 82 份。index 汇总轨道、场景族、机器/语义标准数、可运行状态和探索集身份。manifest 记录每个构建 JSON 和源代码的 hash；不是只有一个“build_success=true”。

## 3. 关键契约设计

### 3.1 评测材料不进入 SUT 输入

worker 只收到真实用户轮次、可观察状态、当前工具返回及已发生的环境更新。没有未来故障脚本、gold、允许效果名单、人审答案或 reference mask。实际图像可通过 `read_artifact` 获取 PNG；PDF 通过有界分块读取。未来接入多模态 SUT 时，不必根据纯文字附件 ID 猜图。

API 隔离通过独立临时工作目录、显式环境变量传递、评测端 collector 和不传给 worker 的 HMAC key 加强。第三方恶意代码须用额外容器/账号隔离，不能声称同一用户权限的 Python 子进程已构成 OS 沙箱。

### 3.2 判实际效果，不判工具名

gold 约束稳定目标和最终状态，例如仅 guide-A 可见、仅 CTV opacity=0.3、更新指定过期产物，不规定某个产品内部工具必须叫 ui_controller。适配器可以采用受支持的等价实现，不能因此多做未请求的重算、分割、生成或跨病例操作。

所有调用保留 attempted；拒绝不把不合法尝试抹掉。read-only 也不等于可以跨 tenant/case 读取。初始已有产物不证明本轮生成，job accepted/running 不证明完成；报告依赖完成时间和实际 source artifact 必须一致。

### 3.3 时序和故障

支持 queued/running/completed/failed/cancelled、用户改口、局部取消、重试对账、precommit 版本变化、病例切换、ACK 丢失、页面恢复、provider 异常和 Monitor commit/recompute 事件。hold 不会因一般 tick 被擅自解除；取消独立任务不取消另一任务。未触发的故障分支单独保留，不能宣传为已测试的恢复能力。

`finish`/超时/operation budget 均有边界，不无限 spinner。预算是开发环境资源上限，不是已验证的科学延迟阈值；真实效率阈值需正式实验预注册。

### 3.4 截图和报告

合成 Viewer 使用可核验的 primitive raster/depth/target mask，而不是拿 projected bbox 当实际可见。Data Tree 输出真实合成树行 raster；标注落点需要命中对应 reference mask。图像有实际像素、独立文件 hash 和身份；同一对象的不同 view、不同目标的同一 view 都不可覆盖。

capture/export 与用户交付分离。生成/解码后，必须在实际 response 引用附件/download ID；独立 collector 才记录 delivered。最终回复以真实交付和真实失败为依据。缺文件/解析器/人审不算成功。

截图在 finally 恢复；切病例后不把原病例的相机/可见性写入新病例。报告 global/CTV_closeup 有独立 framing、占用率与 clipping 检查，PDF 嵌入真实 raster，不靠高分辨率数字或空 image ID 冒充可读。占用率范围是开发参考，未宣称经过临床读者校准。

### 3.5 完整状态、上下文、语言和 Monitor

53 个器官使用 53 个实际版本化记录，不再靠 row_count 标志通过。零/None/旧版本分开；没有未经授权的隐藏重算。压缩场景保留原始用户授权及来源 ID，不拿 assistant 摘要自行扩大权限。

透明度/颜色/局部缩放均有明确目标范围。保存状态执行实际 JSON serialization/reload；report 语言切换有正文/图注实际文本，不能只改 language 标志。合成镜像仍不是生产 DOM，故 real_browser_observed=false。

Monitor 编辑有 owned run、当前版本、提交前后状态和具体目标；dose delta 与编辑序列绑定；未重算不制造 dose/score，也不把旧偏好当当前病例自动重算授权。停止 run 与本地终态、ACK 对账分离，不能依靠隐藏光效假称服务端停止。

## 4. 语义判分和科学质量门禁

机器检查覆盖可以严格程序化的事实，开放自然语言的最终回答和读者体验保留独立 rubric。每个评审须绑定真实 delivered response 的 hash/turn/span、理由、评审者身份和严格 bool。字符串 false、缺 reviewer、错误 hash、SUT 自评以及缺校准证据都不能当人审通过。多轮不是只评价最后一句：中间轮也要有 turn-fulfillment，整体标准结合最终回答/过程检查。

三态 gate 继续区分明确失败与缺证据。明确未授权效果/错误目标/未满足结果不能被另一项缺人审覆盖；反过来，没有独立评审也不能因为机器目标满足就算成功。

全部当前题放在公开 development 集；40 个场景族不等于40个独立临床病例。共享合成 fixture、同族、相似故障与共同来源需要聚类处理，不能随机将同源题拆进 sealed 后主张泛化。正式冻结需要团队独立审查和新增的预注册 split，不回写旧 MANIFEST。

## 5. 使用

在 `benchmarks/brachybench` 下，`python -m extensions.real_user_requests_v1.prepare` 构建；`prepare --check` 查漂移；`runner` 默认只查构建；pytest 只运行组件测试。详见扩展 PROTOCOL.md。

将来执行被测系统必须显式 `runner --execute --case --worker --out`，不会因运行 build/test 误触发医学工具或模型。recording 的 key 由评测端持有；离线评估还校验 contract/fixture/protocol，不允许旧 gold 漂移后悄悄重新判分。

## 6. 本轮验证与交付记录

在完整隔离快照中合并运行原 `tests/` 和新增扩展：**24,769 passed，0 failed，0 skipped，3 个非失败 SWIG DeprecationWarning；175.87 秒**。其中原 benchmark 回归 24,210 项、新扩展自测 559 项（原 authoring 自测 135 + runtime 自测 424）。这些数字全部是 benchmark 基础设施/组件回归，不是 BrachyBot 成绩。

首轮完整快照测试曾有一项 provenance 路径解析失败：隔离目录缺少原题引用的生产源码。补齐 **179 个真实引用源码的只读快照** 后，原断言不变，重新运行完整套件全绿；没有造空占位文件或放宽 quality guard。

构建与 `--check` 无漂移；82 task 包装通过既有 task schema；原 11,969 题的路径/hash 做发布前后完整性核验。发布日志、差异及逐文件 hash 另存临时 publication archive，便于追回本轮变更。当前没有 SUT 结果，sut_runs=0。

## 7. 不在本轮伪装完成的事项

1. 独立人审/临床专家审批：需要真实合格人员，不把作者自测当独立复核。
2. 真实产品 gamma：须从真实 BrachyBot/对比系统浏览器、真实医疗产物和服务状态独立采集；此合成 beta fixture 不替代它。
3. 语义/视觉 judge 校准：需要独立 holdout 和人工标签，不用组件 witness 作为校准成绩。
4. Agent 性能、显著性和横向排名：本次按用户要求不执行，不编造。

这些是后续实验的科学验收条件，不是还没写完的题目/fixture/事件/运行/判分接口。可执行开发版已具备这些接口，同时诚实保留其尚未通过的状态。
