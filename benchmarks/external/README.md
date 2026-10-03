# BrachyBot · 公开 benchmark 集合

> **2026-10-04 更新：** 后续所有正式 BrachyBot 测评统一从真实浏览器对话框输入题目并点击发送。任意模型回调默认被拒绝；E0/回归必须显式声明 `component_self_test`。详见 [统一执行契约](../../docs/BENCHMARK_USER_CHAT_EXECUTION_CONTRACT_2026-10-04.md) 与 `public_collection/user_chat_eligibility.json`。下文的 common-harness 分类是原始资产/协议背景，不是绕过产品入口的许可。

本目录用于公开能力锚点，不代替 `../brachybench/` 的原生近距离治疗、Viewer、Monitor 和产物状态测试。**数据收集成功、离线 scorer 单测通过、原版协议可运行、模型实测结果是四件不同的事。** 不合并成一个跨 benchmark 总分。

本轮收集/审查基线为 2026-10-03，收尾日期 2026-10-04。既有 11 个 legacy adapter 保留，新集合在 [`public_collection/`](public_collection/README.md)，新增 12 项 EXT-16…27。详细筛选、原版协议限制和旧项问题见 [审查报告](../../docs/BENCHMARK_PUBLIC_COLLECTION_AUDIT_2026-10-03.md)。**本轮 SUT/model/judge 调用数为 0。**

## 两层目录，不混淆实验身份

| 层 | 入口 | 含义 |
|---|---|---|
| 既有 adapter | `manifest.yaml`、`acquisition/*.yaml`、`EXT-N/adapter/` | 历史构建状态；`active`/E0 PASS 不是公开比较资格认证 |
| 新公开集合 | `public_collection/catalog.json`、`assets.lock.json`、`pool.py` | 上游版本锁定、测试集、私有参考答案/公开输入分离、原版 scorer/renderer 接口 |
| 筛选和复用规则 | `public_collection/selection.json` | 每项用途、条件、排除或重叠原因；仅收集有意义的方向 |

新集合可通过统一 common-harness 输入测试 BrachyBot 所用的模型/决策组件，但并不自动赋予产品外国工具、EHR、病理或医院系统的能力。**原生 BrachyBot、同一 mock-tool harness 的模型/agent、原版公开 leaderboard 三种结果必须分别报告。**

## 现有 11 项重新定位

| ID | 项目 | 本轮审查后的定位 |
|---|---|---|
| EXT-1 | ABRA | 影像软件操作方法/条件实验；353/655 生成题，不能声称已运行 OHIF/Orthanc 原版环境 |
| EXT-2 | HealthBench | 医学沟通、接地、诚实辅助锚点；需真实独立 rubric judge，hard/consensus 不是新独立题库 |
| EXT-3 | MedSafetyBench-BrachyAdapted | 原版安全数据与 Brachy 改编题分开报告；改编须专家签署，不能称原版安全成绩 |
| EXT-4 | MedMemoryBench | 医学对话记忆辅助；须固定 zh/en、persona/session 时间范围，不能用参考答案生成 SUT 输出 |
| EXT-9 | LongMemEval | oracle/s/m 分轨；默认 oracle 的结果不能冒充长历史能力；judge 仍为独立依赖 |
| EXT-10 | MedHallu | 医学幻觉检测辅助；上游 parser 有空答案/弃答解析问题，需同时披露 raw response 与协议版本 |
| EXT-11 | MedCalc-Bench | 临床计算辅助，不等于粒源剂量引擎验证 |
| EXT-12 | AgentClinic | **隔离，禁止旧单轮 adapter 产生 AgentClinic 成绩**；缺原版 patient/test 多轮环境，已显式 BLOCKED |
| EXT-13 | AMEGA | 指南遵循辅助；加权求和不等于 criteria 已经独立判定；需 judge/人审 |
| EXT-14 | MedPhysBench | 医学物理最贴合的公开锚点之一；97 题；不等于本产品病例计划获批 |
| EXT-15 | MedicalAgentsBench | 当前 9 套完整来源题 != 原版 `test_hard` 十切片协议；只作显式辅助基线，须逐底层数据集确认许可/重叠 |

本轮已修复既有 adapter 的**直接 `build_input` 和调用边界**参考答案泄露，包括 EXT-15 的 `reference_letter/reference_content`。采用逐项公开字段契约，保留合法临床内容和“供模型判断的候选答案”，不递归删掉所有叫 `answer/expected` 的文本。

## 不运行模型的复现命令

在 `benchmarks/external/` 中，使用单独的 benchmark Python 环境：

```bash
python -m public_collection.collect fetch
python -m public_collection.collect verify
python -m public_collection.pool inventory
python -m pytest public_collection/tests -q
python -m public_collection.pool export --id EXT-20 --out /tmp/medec-public-new
```

分别为按已审核 SHA256 获取、完整性检查、题库清单、构建/契约/scorer 正负对照测试、公开输入导出。都不会调用模型。

`fetch_all.sh --public-collection` 只触发新集合按锁获取，不触碰既有 vendor。**不要为了复用新增题库执行无参数的旧 `fetch_all.sh`**：旧脚本会重建旧 vendor/data，并有未固定 HF `main` 的历史段落。新的锁包含 canonical URL、实际下载 URL、字节数及 SHA256；使用公开镜像不绕过认证/DUA。

只把导出的公开 bundle 挂载给 SUT；不能把包含 gold/qrels/scorer 的整个仓库或 assets 目录给终端 agent。`--bootstrap-lock` 仅用于明确审核后的上游升级，本轮已经生成锁，日常复现不需要它。

本轮没有修改临床推理/规划/Viewer/Monitor 代码，没有重启服务，没有创建患者实验，也没有调用付费 judge。历史 `results/e0_summary.json` 保留为历史组件记录，不升级为本轮模型结果。
