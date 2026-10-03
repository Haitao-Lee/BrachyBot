# BrachyBot 公开 benchmark 集合：真实性、适用性、构建与比较协议审查

检索/源版本核验：2026-10-03；实现收尾：2026-10-04。远端基线 `/home/lht/snap/brachyplan/BrachyBot`，HEAD `7aa6d23086072b593beba069f8c2116d01c3c0f3`，以当前脏工作树为准。本轮仅修改公开 benchmark 构建/边界/文档，不修改临床产品逻辑。**不运行 BrachyBot、外部模型、付费 grader、真实病例或 GPU 测评，不提供实验排名。**

## 1. 结论和交付范围

已在既有 `benchmarks/external/` 内建立 `public_collection/`，实际收集 12 个新公开资源（EXT-16…27），下载并校验测试题、必要图像/语料以及可合法复用的上游 renderer/scorer。既有 11 项保留但重新定位，并修复参考答案暴露、AgentClinic 单轮伪协议和 E0 结果身份问题。

新集合不只是网址列表：提供固定 Git/HF revision、173 个文件的 SHA256/字节数/来源锁、公开输入与私有标签分离、任务清单、病例/来源簇、图像与检索语料接口、公开 bundle 导出、原版判分/提示词钩子和构建正负对照测试。原始资产锁内文件合计 1,383,638,541 字节（包含压缩包和解包成员，不能当作唯一数据体积）。数据文件 Git 忽略，小型 catalog/lock/provenance 可纳入版本管理。15 个有官方 HF LFS SHA256 元数据的大文件另经官方版本 API 独立交叉核验，与实际获取文件全部吻合；无 LFS 元数据的小文件不冒称通过这项独立核验。

**没有声称 12 项全部已取得原版 leaderboard 测评资格。** 本轮完成的是可复现收集、输入/标签隔离、支持的协议接口和明确的阻断条件。MedRGB 原版上下文组装未确认，直接阻断执行/导出；其他需要 judge、完整环境或额外阶段的原版协议也明确标注。数据收集成功、组件自测成功、协议认证成功、SUT 实测成功不得互换。

公开集合最有价值的方向是：何时调用工具/澄清、结构化参数、多目标/并行工具、医学文本纠错、中文多轮临床沟通、可追溯检索、长上下文及非可信工具内容安全。影像问答、知识、临床计算只是辅助证据，不替代本项目原生 UI/规划/Monitor 测试。

## 2. BrachyBot 的适用范围与公平比较身份

BrachyBot 的核心是病例/Session、CTV/OAR、针道/粒源、剂量/DVH、导板/报告、Viewer/Data Tree、截图取证及 Monitor 交互。自然语言决策还依赖事实读取、授权、指代、多需求、状态/版本及错误恢复。不能仅凭“medical/agent/oncology”词汇纳入一套外科、EHR、分子肿瘤委员会或医院行政 benchmark。

三种实验身份必须分表：

| 身份 | 可以证明什么 | 不能声称什么 |
|---|---|---|
| 原生 BrachyBot 产品 | 当前产品工具、UI、状态、真实产物与证据闭环 | 未部署的外国 FHIR/订票/银行工具能力 |
| 公平 common-harness | BrachyBot 所用模型/可接入决策组件和其他模型/agent，在相同公开输入/mock 工具/资源下的能力 | 自动等同原生 BrachyBot 完整产品表现 |
| 原版公开 benchmark 协议 | 原版环境、提示、判分、预算与版本下的结果 | 子集、改编提示或简化环境仍冒充原版 aggregate |

对于 BFCL、When2Call、InjecAgent，公开原题工具属于 foreign schemas。必须提供独立隔离、无真实外部副作用的 mock-tool harness；不能把它们直接放进患者生产工具授权空间。纯知识题可通过产品问答/同一模型测试，但要单独说明是否保留检索、记忆和工具等增益。

当前检索没有发现一套已公开、可完整获取且同时覆盖近距离治疗影像→针道→粒源→剂量→导板→UI/Monitor 的原生 agent benchmark；这是本轮检索结论，不是对全球所有未公开工作作绝对不存在断言。BrachyBench 仍是核心产品证据。

## 3. 新增集合逐项核验

数量来自固定资产的实际读取，不照抄论文广告数字。每项 license_data/license_code、Git/HF 完整 SHA 和具体资产路径见 `public_collection/catalog.json`；实际下载 URL（含公开镜像）与 canonical URL、文件 SHA 见 `assets.lock.json`。

| ID | 公开资源 / 本轮数据 | 对 BrachyBot 的真正意义 | 接口和原版协议限制 |
|---|---|---|---|
| EXT-16 | When2Call：3,652 MCQ + 300 judge views；1,295 来源簇 | 不机械看到关键词就调用：执行、澄清、直接答、承认没有可用工具 | 原版 MCQ 用 token log-likelihood，不可把生成字母 accuracy 称原版；原始 renderer 已接入，judge 分轨 |
| EXT-17 | BFCL v3：3,472 static/irrelevance/multiple/parallel；一个缺标签源项阻断 | 选对工具、参数绑定、多项调用、不该调用时不调用 | 固定 v3 不是 v4；原版 AST checker 已接入，输入是 canonical parsed calls；不执行 foreign 函数 |
| EXT-18 | MedXpertQA：Text 2,450、MM 2,000；2,852 个测试图像文件 | 较难医学推理/辅助视觉理解，支持视觉与非视觉模型公平分轨 | 图像真实下载，不用 placeholder；原版答案清洗和 accuracy 已接入；不是产品对象定位测试 |
| EXT-19 | CMB-Clin：74 病例、208 有序问题 | 中文复杂病例、追问和临床解释；避免上一轮答复丢失 | 保留 case-level 顺序，历史用实际模型输出而非标准答案；原版四维 judge 需配置，不借 CMB-Exam 判分 |
| EXT-20 | MEDEC-MS：597 个有效 MS test 文本 | 最终回复/临床报告中的错误识别、定位、纠错 | 不下载需 DUA 的 UW；328 个全空尾行排除；原版错误/span/correction scorer 许可和依赖仍为门槛 |
| EXT-21 | MedHALT：41,816 test views，15,991 来源簇 | 错误前提、过度自信、NOTA 和伪造/混淆引用 | FCT/NOTA 仅 test；fake 在该版本全属 train，1,858 项不纳入；4 种 IR 转换不能当独立论文样本 |
| EXT-22 | MedRGB：五子集 3,680 来源问题 | RAG 充分性、噪声、证据整合、反事实 | 数据已收集；原版上下文采样与 judge 未核实，`build_input/export` 明确 BLOCKED；不自造原版分数 |
| EXT-23 | R2MED：4 临床子集 511 query | 为当前医疗问题找到正确治疗/临床证据，不只给泛泛建议 | corpus/query/qrels 已获取；共享原版 BEIR 排名指标；不是原版八子集总分 |
| EXT-24 | NFCorpus/BEIR：323 test query、3,633 documents | 小而可复现的医学检索、分级相关性 | 用 test qrels；3,237 条全部 query 不是 3,237 道 test；不把营养检索称 brachy 指南 |
| EXT-25 | SciFact/BEIR：300 test query、5,183 abstracts | 找到支持/反驳科学陈述的证据 | 本轮仅检索，不拥有 claim-label/rationale 判分协议；不冒充 entailment 成绩 |
| EXT-26 | LongHealth task1 base：400 问题、20 虚构病例簇 | 长病历、时间顺序、干扰文档；辅助对话记忆之外的长上下文能力 | 原版 create_prompt、固定 tokenizer/context/shuffle seed；task2/3 是重复协议视图，本轮不虚报完成 |
| EXT-27 | InjecAgent：1,054 base 场景 + enhanced 重复视图 | 非可信工具/RAG 内容不得变成执行授权或泄露病例 | 已建 user/assistant-call/tool 角色化第一阶段公开场景；完整 ASR 仍需原版提示/解析和两阶段 data-stealing simulator |

官方来源：[When2Call](https://github.com/NVIDIA/When2Call)、[BFCL](https://github.com/gorilla-llm/gorilla/tree/main/berkeley-function-call-leaderboard)、[MedXpertQA](https://github.com/TsinghuaC3I/MedXpertQA)、[CMB](https://github.com/FreedomIntelligence/CMB)、[MEDEC](https://github.com/abachaa/MEDEC)、[MedHALT](https://huggingface.co/datasets/openlifescienceai/Med-HALT)、[MedRGB](https://huggingface.co/datasets/ngotrnghia1811/MedRGB)、[R2MED](https://github.com/R2MED/R2MED)、[BEIR](https://github.com/beir-cellar/beir)、[LongHealth](https://github.com/kbressem/LongHealth)、[InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent)。实验复现须使用 catalog 中固定版本，而不是这里的活动首页 `main`。

### 3.1 与公开宣传数字不同的地方

- BFCL `live_multiple_1052-79-0` 在所固定 question 文件中存在，但没有匹配的 task-owned gold；记录阻断，不能按行顺序与另一个 ID 的答案 zip 配对。
- MedXpertQA 当前固定 Text/MM test 实读 4,450，而不是笼统记为 4,460。图像 ZIP 还有 dev 图像，测试实际引用 2,852 张；dev 图像不计测试问题。
- MEDEC-MS CSV 物理记录数 925，其中 328 条全空，不是新增病例，更不是 UW 数据。
- MedRGB 论文版本的四集 3,480 与当前数据卡五集 3,680 有版本差异；本轮按后者锁定，不能将同一问题的多配置膨胀为 18,400 个独立题。
- R2MED PMC-Treatment 的 145 条、MedQA-Diag 的 56 条完全相同 ID/内容重复 corpus 记录去重；若同 ID 不同内容则失败而不是覆盖。四子集有效唯一语料分别为 28,809、60,406、10,449、56,194；不将其拼为一个跨库排名空间。
- LongHealth 的 task2/3、InjecAgent enhanced、MedHALT FCT/NOTA/IR 都有共享来源，误差条/显著性必须以病例/来源簇为单位，不能当完全独立问题。

## 4. 既有 11 项：不合适之处和处理

### 4.1 所有适配器的参考答案泄露——已修复

旧 `build_input` 在多项中返回 `reference_answer`；EXT-15 还带 `reference_letter/reference_content`。之前 callback 层的黑名单没有全面隔离，而且递归删字段可能损坏合法临床嵌套内容。

修复为逐 benchmark 根级公开 schema allowlist，直接 `build_input` 和 `sut_handle` 边界一致隔离私有标签。保留 MedHallu 的待判定 candidate answer、病例 note 内合法字段、MCQ 的所有候选项。gold 保留在 evaluator 的私有记录中，不根据“字符串含 answer”误删。

**限制：进程内边界不能阻止一个有终端权限的 SUT 读整个仓库。** 后续实验必须仅挂载导出的 public bundle，把 raw assets、gold、qrels、评分代码放在独立 evaluator 文件系统。不能在生产病例目录里执行公开 benchmark。

### 4.2 各项具体定位

| ID | 审查事实 | 处理/实验要求 |
|---|---|---|
| EXT-1 ABRA | 353/655 题生成；真实 OHIF/Orthanc 和完整 TCIA/SEG 不等于生成成功 | 条件原生环境；保留参考，不声称已做视觉动作实验 |
| EXT-2 HealthBench | 5,000 eval，hard/consensus/meta-eval 相关；离线 weighted scorer 不生成真实 rubric verdict | 保留重要沟通辅助；判分需原版 rubric、固定独立 judge/抽样人审 |
| EXT-3 MedSafetyBench | 上游 900 test pairs/74k harmful 与 Brachy 改编包身份不同 | 原版/改编分表；改编临床审查 pending，不声称已完成原版执行安全测评 |
| EXT-4 MedMemoryBench | 3,878 query、40 persona、zh/en；当前历史截取依赖 query/session | 保留辅助；需另认证时间范围，不把尚未认证说成必然未来标签泄露 |
| EXT-9 LongMemEval | 已有 oracle/s，m 未收集；default oracle 不等于长历史压力 | 私有答案访问已从 `build_input` 移回内部；逐 oracle/s/m 明示分轨，judge gate |
| EXT-10 MedHallu | 原版 parser 先识别 `not/non/1` 再检查弃答；空文本回退 factual，`not sure` 先落 nonfactual；资产名为 train_labeled/train_artificial | 保留原版可复现 parser，必须披露原始输出/弃答和数据 split；不得称独立 held-out test，不静默修 parser 后称原版 |
| EXT-11 MedCalc | 1,100 test 临床公式计算 | 保留辅助；不能说明 I-125/CNN/TG-43 引擎保真 |
| EXT-12 AgentClinic | 321 text scenario 只有 doctor objective；缺 patient/test 多轮 simulator，不是只缺 judge | **运行入口已隔离为 UpstreamUnavailable/BLOCKED**；保留题库，不输出假的 AgentClinic 成绩 |
| EXT-13 AMEGA | 162 guideline 问题；criteria booleans 要独立 judge，只有加权求和 PASS 不够 | 保留指南遵循辅助，不能信任 SUT 自报判分 |
| EXT-14 MedPhysBench | 97 deterministic physics tasks，涉及 brachy、TG-263、剂量/安全 | 最高贴合度公开锚点之一；仍非患者计划临床放行 |
| EXT-15 MedicalAgentsBench | 当前 9 来源/9,274 full-test 题；当前官方 README 原版重点是 `test_hard` 十切片 | 当前只叫 source-pool MCQ auxiliary，不能冒充原版论文 hard 成绩；另核每底层许可、split、重叠；不额外计为 9 套新独立 benchmark |

MedicalAgentsBench 官方仓库明确给出 hard-subset 协议；聚合仓库 MIT 不自动覆盖全部底层数据许可。[原版来源](https://github.com/gersteinlab/MedicalAgentsBench)

### 4.3 历史状态和下载脚本

旧 README/manifest 写“4 项”，实际列 11，主表注释“3”也不一致。现已改为准确的 11 legacy + 12 new，并增加新的 collection/lock/audit 指针。历史 E0 记录不改成今天的测评数据；新 E0 运行会明确 `component_self_test`、`comparable_sut_result:false`、`protocol_fidelity_certified:false`。

旧 `fetch_all.sh` 存在重建删除 vendor 和多个 HF `main` 来源，不能宣传成全面字节锁定。**本轮不运行、不重建旧资源。** 增加 `--public-collection` 分支，新增获取器先验证已有锁定文件，发现本地修改时拒绝覆盖；安全选择性解包、拒绝路径穿越/符号链接，固定 archive SHA。

## 5. 没有纳入主集合的候选：不为数量节外生枝

详见可机器读取的 `selection.json`。以下分类不等于“论文是假”或“以后永远不能测”：

| 候选 | 当前决策与理由 |
|---|---|
| MedAgentBench / PhysicianBench / HealthAgentBench | 真实 EHR/FHIR/医院数据与 foreign action bridge 的环境、许可/门控需另建；BrachyBot 原生规划不是这些任务 |
| MedCTA | 已有记录指向 IVUL-KAUST 官方代码；当前资产闭环/付费 OCR-search 依赖未满足；不虚构下载命令 |
| MedFlowBench/MedOpenClaw | 3D Slicer/QuPath/证据范式很相关，论文可核实；本轮未认证完整可获取环境+题库+scorer，列 watchlist，不把 API 网络错误当不存在 |
| ToolSandbox / ComplexFuncBench | 状态ful/复杂工具方法值得参考，但联系人、旅店、订票/RapidAPI 不应成为医疗主实验；如未来做需单列完整 common harness |
| AgentDojo / AgentHarm | 安全方法有意义；银行/旅行/广泛网络犯罪任务不直接验证临床授权；当前优先 InjecAgent 工具内容边界，勿展平交互环境 |
| MTBBench | 分子肿瘤委员会与植入计划不同，需病理/基因组、HANCOCK/MSK-CHORD、DrugBank 等资源许可/桥接；不能只因 oncology 就纳入 |
| MedBrowseComp | 医学 web evidence 检索有价值，但明确再分发许可未认证，不复制无许可证全题库 |
| MedS-Bench/MedS-Ins / MIRAGE/MedRAG | 聚合/训练语料/检索工具，不是大量新的独立 test；有许可与底层重叠问题，不加入数量总计 |
| RadBench / 3MDBench | 影像考试许可/完整 scorer 未认证，或医生问诊角色不匹配；暂不作为植入计划核心 |
| MedRECT | 英文 MEDEC 派生重叠，不算独立新增；日语超出当前中英产品实验语言范围 |
| MedQA/MedMCQA/PubMedQA/MMLU | 已有聚合来源；可保留辅助切片，重复下载不带来新的有效能力方向 |
| VQA-RAD/SLAKE/PathVQA/OmniMedVQA | 泛诊断视觉 QA 是辅助；当前优先已获取 MedXpert MM，不能替代截图对象—真实状态绑定 |
| OpenKBP/BraTS/egs_brachy/PortPy | 剂量预测/分割/物理代码或 fixture，不是原生 agent benchmark；须分为 component/physics 独立实验 |

这些筛选以官方源码、数据卡、论文和实际获取结果为依据，不用社区综述里的名字/时间戳直接认证。[MedFlowBench 论文](https://arxiv.org/abs/2603.24649)、[ToolSandbox](https://github.com/apple/ToolSandbox)、[ComplexFuncBench](https://github.com/zai-org/ComplexFuncBench)、[AgentDojo](https://github.com/ethz-spylab/agentdojo)、[MTBBench](https://github.com/bunnelab/mtbbench)、[MedBrowseComp](https://github.com/shan23chen/MedBrowseComp)。

## 6. 支持的接口与原版判分保真

`PublicPool` 负责 list/build/public export，内部 Task 保留 source_id、cluster、subset、public/private。不新增调用生产模型的自动 runner，也不把“列出题库”写成答题成功。

支持的原版代码路径及构建检验：

| 接口 | 检验 | 不做的替代 |
|---|---|---|
| `when2call_prompt` | 原版 Dataset renderer 输出 prompt/全部 candidates，无 target index | 不以生成字母代替原版 log-likelihood |
| `score_bfcl` | 调用固定原版 AST checker；正确结构通过、错误工具拒绝、irrelevance 独立指标 | 不执行函数，不用字符串包含工具名判成功 |
| `score_medxpert` | 原版 answer_cleansing/accuracy，正确与错误选择负对照 | 不偷偷修原版 parser，也不宣称有产品视觉定位能力 |
| `score_retrieval` | BEIR nDCG/MAP/Recall/Precision，完整 query coverage、已知 document ID、有限实数 | 不把 qrels 送给 SUT；不拿 answer accuracy 替代检索 |
| `cmb_messages` | 保留有序 turn，前轮用 SUT 实际输出；默认公开输入只给第一轮，后续 schedule 保留在 evaluator | 不用 gold answer teacher-force 后续问题，不提前向 SUT 暴露未来提问 |
| `longhealth_prompt` | 原版 create_prompt；固定 tokenizer/budget/seed；恢复全局 RNG | 不公布 answer_location、不自行拼 task2/3 混称全部 LongHealth |
| `image_bytes/export` | 实际 bytes、CRC、公开 MIME/path 映射 | 不用空图、压缩答案文本或错误扩展名假装有图 |
| InjecAgent public scene | 恶意内容保持 tool role，目标标签私有 | 不触发真实删除/外发；不把第一阶段称完整 ASR |

MedXpert 原版 regex 在选项 A–J 中可能把 “I cannot select an option.” 的 I 解析成选项 I，且当 gold 为 I 时误判正确。本轮负对照明确复现它。后续可同时报告 native score 与预注册 strict-format/abstention 分析，但后者必须另命名，不能回填原版结果。

MEDEC、CMB-Clin、HealthBench、AMEGA、MedMemoryBench 等开放回答需要独立 judge/人审或原版多维指标；本轮没有用关键字规则生成一个假的 clinical score。MedHALT 数据 license 已核实，未明确授权的代码不整包再分发；MEDEC 不擅自复制许可未确认的评估仓库。

## 7. 后续横向实验的预注册要求

1. **实验对象**：明确是 native product、共享 agent harness、还是 raw backbone；保留“same backbone 不同 agent”、“same harness 不同模型”等消融。
2. **冻结身份**：完整 Git/HF SHA、asset lock、subset/split、原版/改编协议名、源 scorer/prompt/parser 的 hash，不能把 live `main` 当实验基线。
3. **资源对等**：所有模型获得同一公开输入、相同 tools/mocks/corpus；明确 web 检索可否、缓存、上下文、图像分辨率、最大工具次数/调用预算、wall time、cost。
4. **可测能力范围**：不支持图像或 token logprobs 的付费 API 不能伪补原版结果。标 capability-not-supported 或单列 adapted view，不能与 native MCQ/MM 合表。
5. **工具安全**：foreign tools 只在隔离 simulator 上执行；生产病例、文件、报告、账号、LAN/public 服务不进入公开测试。
6. **独立判分**：开放题固定 judge 版本/rubric、盲法、重复与专家抽检；禁止 SUT 自报 booleans 和自评当 gold。
7. **完整输出**：记录 raw response、parsed answer/tool call、abstention/refusal/clarification、tool receipts、预算超时和 infra failure；不能把 API 失败当答题错，也不能丢无答案记录后只算成功者。
8. **样本单位**：按病例/persona/source publication/source scenario 做 cluster bootstrap 或相应 CI；MCQ/judge、hard/base、原题/改编、base/enhanced 不重复当 N。
9. **重叠处理**：When2Call→BFCL、MedAgentsBench→MedXpert/MedQA/PubMedQA 等建立 split/文本/来源 ID 对照；同一题不同任务看成 repeated view。不能汇总“总题数”宣传独立证据规模。
10. **未满足条件**：protocol BLOCKED/unsupported/license-required 不计作 SUT failed，也不计作 completed；部分子集不产生原版总分。
11. **比较统计**：每方向预设 primary metric，报告置信区间、预算/延迟/cost，处理多重比较和数据污染风险；不以一个总分掩盖安全/执行/沟通差异。
12. **临床边界**：公开知识/医学物理分数不能推出治疗有效、规划安全或临床放行；保留 BrachyBench 真实几何/剂量/状态与证据测试。

推荐论文分层：核心原生 BrachyBench；公开决策/工具 When2Call+BFCL；物理 MedPhysBench；沟通/中文 HealthBench+CMB-Clin；纠错/幻觉 MEDEC+MedHALT/MedHallu（注明 parser/split）；检索 R2MED+NFCorpus/SciFact；长程 MedMemory/LongHealth；安全 InjecAgent。MedXpert 是医学推理/视觉辅助。MedRGB 先保留数据和条件，原版完整协议核实前不进结果表。

## 8. 操作、验证与完成标准

从远端 `benchmarks/external/` 用独立 benchmark 环境执行，不安装到临床推理环境：

```bash
python -m public_collection.collect fetch
python -m public_collection.collect verify
python -m public_collection.pool inventory
python -m public_collection.validate_collection --tests
python -m public_collection.pool export --id EXT-20 --out /tmp/medec-public-new
```

公开镜像可显式指定 `--hf-host hf-mirror.com`；两种 URL 记录于锁。不绕过登录、DUA 或商业 API。首次/明确审核升级才考虑新版本目录里的 bootstrap；既有 hash/URL 改变会拒绝覆盖，而不是悄悄更新锁。

构建校验记录于 `public_collection/construction_validation.json`，包含源/锁/selection hash、实际题库与簇清单、图像 CRC、scorer 正负对照与测试日志、`sut_runs:0`、`model_calls:0`、`paid_judge_calls:0`、`comparable_sut_result:false`。这不是一份模型成绩。

本轮目标完成标准：资产实际落地、固定版本可核验、private/public 契约有效、所有新增构建正负对照通过、相关既有回归无新增失败、文档不再把历史 E0 当 SUT 结果。**不要求、也没有启动正式比较测评。** 需要后续授权和实验配置的原版 judge/环境/受限数据明确保留条件，不用放宽评分规则掩盖。

## 9. 验证记录

| 检查 | 实测结果 | 含义 |
|---|---|---|
| 新集合 + 11 项既有真实资产的输入/回调边界 | 48 passed，3 条 datasets 弃用提示 | 包含逐题公开输入、私有 canary、官方 scorer 正负对照、图像导出、来源改动保护等；合成控制，不是模型成绩 |
| 安装后的 external/adapters + independent-audit + 新集合定向回归（早期 37 新项时） | 115 passed / 1 skipped | 缺 pypdf 的既有负对照跳过，后来加入 11 真实资产边界测试 |
| `brachybench/tests/` + 新集合完整回归 | 24,256 passed / 2 skipped，174.04 s | 两项跳过均为验证环境缺 pypdf；6 条库弃用提示；无失败 |
| 完整回归之后 CMB 私有调度/官方元数据/缓存来源记录保护的定向重验 | 48 passed | 最后的小修仅涉及新增集合；没有将此前全套测试冒充之后逐文件重新运行 |
| 完整性 / 图像 | 173 locked files，0 problems；图像 ZIP CRC passed | 资产、catalog、固定原版 Python 依赖无漂移 |
| 官方 HF LFS 大文件交叉核验 | 15/15 SHA256 与本地锁吻合 | 通过 canonical revision API；不只信任公开镜像 |
| 临床/服务副作用 | SUT/model/judge calls=0，service restarts=0 | 无病例实验、无生产模型、无付费判分、无服务重启 |

全量跳过项：`tests/test_checker_family.py:233`（real PDF parser required）、`tests/test_independent_audit_remediation.py:384`（缺 pypdf）。没有为跑绿弱化判分器，也没有向临床 conda 环境安装新依赖。验证环境单独在 `/tmp/public-collection-test-env-20261003/`。

构建证据文件：`public_collection/construction_validation.json`、`official_hf_checksum_crosscheck.json`、`validation/regression_summary.json` 和对应日志。原始长回归日志保留为组件自测证据，不进入公开模型结果表。既有文件发布前做哈希冲突检查，备份在 `/tmp/brachy-public-collection-20261003/pre-publication-backup/`；工作树没有提交、重置或清理。
