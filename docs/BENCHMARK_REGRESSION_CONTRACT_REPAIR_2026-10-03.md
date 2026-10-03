# BrachyBench 回归契约对齐：fixture 漂移、旧断言与缺证据分类

日期：2026-10-03。接续独立审计和基础设施修复；本轮只涉及 benchmark，不修改在线规划/UI、病例、账户或服务。

## 1. 验收必须分层

用户复测 `215 failed / 23,985 passed / 1 skipped` 表明上轮仅完成判分器加固，未完成回归契约迁移。负对照通过不能代替全量回归验收；回归套件通过也不能代替真实 SUT、临床或正式横评验证。

新增版本化 component 契约严格区分：

- `COMPLETED`：组件控制满足判分契约，不代表真实 BrachyBot 成功。
- `FAILED`：可验证的判分标准不满足，不能改为缺测。
- `BLOCKED-evidence`：没有必要的真实观测/独立参考，保持 Insufficient evidence，不给安全或完成信用。
- `SKIPPED-live`：缺少 replay，需要真实执行；不同于 BLOCKED。
- `contract_ok`：组件行为是否符合已审查契约，包括按预期拒绝缺证据；与 `ok`/任务成功分开。

E0 的 `evaluation_mode=component_self_test`、`comparable_sut_result=false`、`formal_result_count=0`、`ready_for_formal_evaluation=false`。CLI 有失败返回 1，无失败但存在 BLOCKED/SKIPPED 返回 2，不将缺证据当作正式 readiness 成功。

## 2. 204 个 coverage 失败的真实构成

上轮逐项记录为：正向 replay 134 个失败，负向 replay 70 个失败；不是全部由正式独立 collector/expected_state 要求引起。原 coverage 调用使用 component 模式，其问题主要是直接 checker 输入与新契约不匹配。

- 干涉：18 组历史正例把零距离端点接触称为无风险，负例反而正确报告接触；加固后交换了旧正负判断。
- 路径：2 个旧 POSIX 负例使用反斜线 `..\\..\\evil`，在 Linux 上是合法文件名而不是父目录穿越。
- 分割：50 组控制含 1D 玩具向量或 2D mask/3D spacing，不是合法 rank-matched mask 契约。
- 状态：5 个正例修改了 receipt journal 或 UI state_seq，却没有显式声明允许修改路径。
- DICOM：1 个 ROI-name-only 正例没有几何，不能认证 DICOM roundtrip。
- 独立参考：43 个正例的独立解析字段缺失/不完整。
- OAR：30 个正例声明 OAR 限值，却没有对应的观测剂量。

为前 76 组建立可解释的合成控制修订；后 73 组保留缺证据，未填造低剂量或复制候选值作“独立观测”。历史题目、原 replay、负例集合、gold、冻结 split 和旧结果均不重写。

## 3. 版本化修订机制

`tools/component_replay.py` 与 `tests/replay_contracts/v2.json` 保存 149 组已审查契约。每项绑定任务路径/内容 SHA256、正例 SHA256 和整份负例集合 SHA256。传入任务或候选 observation 与冻结原文不一致时拒绝应用修订，避免将组件适配施加到真实模型输出。

修订内容：

| 类型 | 项数 | 行为与边界 |
|---|---:|---|
| 合成 mask 契约 | 50 | 1D 玩具向量显式成为 2D 条带；2D mask 使用二维 spacing；不升级为患者分割证据 |
| 分离端点控制 | 18 | 已知端点 toy 控制改为 5 mm 实际间隔；内部交叉控制不变；原零距离接触仍被判失败 |
| POSIX 穿越控制 | 2 | 新负控使用真实 `/../../evil`；不把合法反斜线文件名错误地当作 Linux 越界 |
| 显式 bookkeeping 权限 | 5 | 仅允许 `plan.receipts` 和/或 `ui.version_fence.state_seq`；几何、剂量、终态、plan_revision 仍保护 |
| ROI 名称组件范围 | 1 | 使用 generic semantic checker，不声称 DICOM 几何被验证 |
| 缺独立参考 | 43 | 原 observation 不变；精确断言缺证据码，E0 标 BLOCKED |
| 缺 OAR 观测 | 30 | 原 observation 不变；精确断言缺证据码，E0 标 BLOCKED |

`tools/migrate_component_contracts.py` 按明确契约规则生成新版本，不调用 oracle 决定标签，不根据“跑出来什么”批量改预期。正式执行链不自动应用此修订。

负例集合约 277 MB。SHA256 流式计算，文件身份/大小/mtime/ctime 不变时复用结果；变化后重新校验，新增测试验证此行为。该 API 契约不是对敌对同进程代码的 OS 隔离保证。

## 4. dose_quantisation fixture/oracle 漂移

18 个历史 pass 因 independent 仅有 dims 变为不适用，是真实的 fixture 契约漂移。不能把这 18 个 pass 改写为 fail 来迎合判分器。

保留原 25 个量化 fixture，新增 `fixtures/physics_contract_v2/`：

- first/second/scaling 和整份 expected verdict/codes/score 均保持不变。
- 补齐几何、ROI 和合成完整精度参考网格，记录 little-endian float64 二进制 payload，再由 `struct` 解码。
- 与 ndarray 解码路径分开；manifest 绑定旧/新内容哈希，测试核对 payload、网格和冻结标签。
- 新生成器直接产生该完整版本，防止新 fixture 继续遗漏字段。
- 明确范围为 analytic component；不是 DICOM、TPS、MC 或真实患者剂量的独立验证，不为此伪造真实 parser receipt。

## 5. 其余断言的更新

- PDF：真实 writer 生成有效 PDF；假 `%PDF...%%EOF` 必须拒绝；缺解析依赖时只跳过该依赖测试。
- Roundtrip：完整独立字段才可通过；空 independent 仍失败；STL 合法重网格化不是证据缺口。
- StateInvariant：receipt 默认受保护，仅显式允许路径可修改。
- ICC：检验 identified=false/member/run=None，不从无索引向量编造三层方差。
- Kendall：SUT×dimension 矩阵及所有 SUT 共享权重；旧一维输入必须拒绝。
- DICOM UID：保持引用/别名图，不简单删除 SOPInstanceUID；原始 UID 更换但图一致的 toy 控制可等价。
- 场景均值：`((1+.8)/2+0)/2=.45`，不使用按题目条数加权的 .6。
- 安全上界：无完整独立审计的记录不能进入独立分母；零样本采用最保守 UCB=1；真实 invariant 事件使用非零 exact binomial bound。
- 效率扣分：owner-G 只从 G 扣，不降低 A 的质量分；不改变安全 gate。

## 6. 验证与剩余工作

验证在 `/tmp/brachybench-regression-20261003` 隔离副本和既有隔离 venv 执行，生产结果目录不作测试输出目录。原定向失败复现为 10 failed/66 passed（未含 runner/coverage）；联合 coverage/runner/panel 验证为 23,953 passed。完整套件为 **24,210 passed / 0 failed / 0 skipped**（153.06 s；3 个既有 SWIG DeprecationWarning）；新增 9 项契约保护测试。最后的流式哈希兼容性小修订再做定向验证；完整日志和发布后结果记录在 `docs/audits/benchmark-regression-2026-10-03/`。

回归通过不消除 73 个 evidence-blocked replay；它们必须补真实独立参考/OAR 观测后版本化复核，不能仅凭当前 toy 模式推导临床值。真实浏览器交付、任务执行新鲜性、独立物理参考、专家 gold、sealed 治理和各 EXT 官方环境/scorer 保真仍按此前报告待验收。本轮不宣称 benchmark 已具备论文主实验或横向排名资格。
