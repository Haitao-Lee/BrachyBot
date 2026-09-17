# CTV 肿瘤分割统一门类设计（tumor_segmentation）

日期：2026-09-17
范围：内测树 `<workspace>/BrachyBot`（发布树同步另开一轮）
状态：已批准，待用户复核 spec 后进入实现计划

## 1. 背景

当前六站肿瘤分割由三套互不相同的机制实现（引擎、调度、标签语义、目录约定、前端呈现都不一致）：

| 部位 | 路由 id | 模型 | 权重位置 | 引擎 | 输出标签 | GPU 调度 |
|---|---|---|---|---|---|---|
| 胰腺 | `nnunet_pancreatic` | nnUNet v2 Dataset005_Pancreas（3d_fullres，7 类） | `BrachyBot/VoCo/pancreatic_tumor/Dataset005_Pancreas/...` | 进程内 nnUNet | 1瘤 / 2动脉 / 3静脉 / 4胰 / 5-6未知 | DeviceManager，**无跨进程锁** |
| 肝 | `nnunet_liver_tumor` | 两级级联 stage1_liver→stage2_tumor（5 折） | `prostate_lesion_seg/trained_models/liver_cancer_seg` | 子进程 `cascade_infer_v2.py` | 1瘤 | lease + gpu_lock |
| 肾 | `nnunet_kidney_tumor` | 两级级联 stage1_kidney→stage2_tumor（5 折） | `kidney_tumor_seg/trained_models/kidney_cancer_seg` | 子进程 `cascade_infer_kidney.py` | 1瘤 | lease + gpu_lock |
| 头颈 | `nnunet_head_neck_gtv` | HECKTOR Dataset510_CT（nnUNetTrainerMax500，best fold1） | `headneck_tumor_seg/data/nnUNet_results/Dataset510_HECKTOR_CT/.../best_model` | 子进程 `infer_headneck.py` | 1 GTVp / 2 GTVn | lease + gpu_lock |
| 鼻咽平扫 | `nnunet_nasopharynx_ncct` | Dataset508_SegRapGTVnc（best fold3） | `nasopharynx_tumor_seg/trained_models/nasopharynx_cancer_seg_ncct` | 子进程 `infer_nasopharynx.py` | 1 GTVnx / 2 GTVnd | lease + gpu_lock |
| 鼻咽增强 | `nnunet_nasopharynx_cect` | Dataset511_SegRapGTVce（best fold3） | `nasopharynx_tumor_seg/trained_models/nasopharynx_cancer_seg_cect` | 子进程 `infer_nasopharynx.py` | 1 GTVnx / 2 GTVnd | lease + gpu_lock |
| 肺 | `vista3d_lung_tumor` | VISTA-3D 基础模型（MONAI/VISTA3D-HF，class 23，非微调） | `lung_tumor_seg/trained_models/vista3d_lung/vista3d_pretrained_model/model.safetensors` | 子进程 `infer_lung_vista.py` | 1肺肿瘤（二值） | lease + gpu_lock |

同门类还有结肠 `biomedparse_colon_primary`、前列腺 `biomedparse_prostate_lesion`（BiomedParse v2 文本提示），以及仅显式交互的 SAT3D 研究路由。

已确认的问题：

1. 目录约定不统一：肝权重在 `prostate_lesion_seg/` 下；头颈在 `data/nnUNet_results/` 而非 `trained_models/`。
2. 调度不统一：只有胰腺是进程内 nnUNet 且不参与跨进程 `gpu_lock`，其余走子进程 + lease + gpu_lock，存在同卡抢卡/OOM 隐患。
3. 标签语义不统一：胰腺 1-4 全套 + `label_stats`；肝/肾二值；头颈/鼻咽 1/2 双靶；肺二值。下游 `web/structure_service.py`、`web/routes/viewer_routes.py` 用字符串前缀猜语义，`vista3d_lung_tumor` 甚至未被识别为模型源（被当成上传 mask）。
4. 前端可用性不一致：`capability_state` 决定绿/红，新接入三站长期显示"待验证"，用户看到的选择项颜色/文案与已验证站点不同。
5. 路由/别名缺口：`头颈部肿瘤`、`肺部肿瘤` 直接硬失败（`Unsupported CTV tumor_type`）；`鼻咽癌` 哨兵未进路由白名单，自动路径丢失；`请分割<部位> CTV` 直执行回归为 `semantic_action`（`tests/test_image_metadata_query.py:48`）。

## 2. 目标与非目标

### 目标
- 六站**并列**为同一门类 `tumor_segmentation`，由**一份注册表**统一声明与管理。
- 前端：任意受支持肿瘤类别**交互一致**，**已支持且可用者一律绿色**。
- 后端：**统一执行边界**（一个 GPU 队列/锁 + DeviceManager lease，胰腺一并纳入）、统一取消/超时/OOM 策略、统一输出契约、统一下游语义。
- 下游（Structure Set / 2D / 3D / Data Tree / 规划 / 报告）对任意站点的 CTV mask **本质无差别**（规划恒取靶区并集；显示可带分标签）。
- 修复第 1 节第 5 条的三处缺陷。

### 非目标
- 不重写用户提供的推理脚本（`infer_lung_vista.py`、`cascade_infer*.py`、`infer_headneck.py`、`infer_nasopharynx.py` 原样保留）。
- 不统一内部引擎实现（VISTA-3D 继续作为肺的基础模型）。
- 不改进模型精度；不做发布树 `BrachyBot-release` 同步（另开一轮）。
- 不改动规划/剂量/导板算法本身。

## 3. 架构

### 3.1 单一模型注册表 `tool_factory/CTV_seg/model_registry.py`

每条 `CTVRRoute` 声明（dataclass/frozen mapping）：

- `id`：规范路由名，同时作为 `tumor_type`、`ctv_source`、catalog `id`（**保持不变，避免数据迁移**）。
- `site`、`display_zh`、`display_en`、`modality`、`ct_phase`（可空）。
- `engine`：`inproc_nnunet` | `subprocess` | `text_guided`（结肠/前列腺的 BiomedParse v2；SAT3D 保持显式交互研究路由，同样登记来源但 `ui_visible=False`）。
- `script`、`model_root`、`checkpoint`、`runtime_python`、`args`、`precision`。
- `labels`（id→名称）与 `target_semantics`：`single_target` | `target_plus_anatomy` | `multi_target_gtv`。
- `availability_probe`（现在 `site_model_availability` / `cascade_availability` / 胰腺目录检查）。
- `catalog_status`（`verified`/`experimental`，仅作说明文字）、`validation` 指标、`requires_review`。

六个站点全部登记为**对等条目**；结肠/前列腺同样登记（`engine=text_guided`，BiomedParse），SAT3D 保持研究路由但登记来源。

派生关系（改为从注册表派生，对外行为不变）：
- `tool_factory/CTV_seg/__init__.py`：`TOOL_REGISTRY`、`normalize_tumor_type` 别名表、`list_tools()`、`_PREFERRED_TUMOR_TYPES`。
- `model_catalog.py`：`CTV_MODEL_CATALOG` 条目、`catalog_with_local_status`、`filter_catalog`。
- 兼容层：`site_models.SITE_MODELS`、`nnunet_cascade_tumor.CASCADE_SITE_SPECS` 保留为注册表派生视图，避免既有导入方与测试断裂。

### 3.2 统一执行边界

新增 `tool_factory/CTV_seg/executor.py`：`run_ctv_model(route_id, image, *, fast_mode=None) -> ModelOutput`。

- **引擎适配**：`InProcNNUNetEngine`（胰腺；从 `pancreatic_tumor_nnunet.py` 抽出，只加锁不改推理参数）与 `SubprocessScriptEngine`（肝/肾/头颈/鼻咽/肺，原样调用现有脚本）。
- **统一调度**：所有引擎先取 `DeviceManager` lease，再取**同一个跨进程 per-card 锁**（复用 `site_model_runtime.gpu_lock`，路径 `$TMPDIR/brachybot-ctv-gpu-<uid>/gpu-N.lock`）；锁目录不随调用方 `TMPDIR` 漂移（显式固定为系统临时目录下的用户目录）。
- **统一策略**：排队超时 `BRACHYBOT_CASCADE_QUEUE_TIMEOUT_SEC`（默认 900s）、推理超时 `BRACHYBOT_CTV_TIMEOUT_SEC`、取消轮询 `raise_if_cancelled`、CUDA OOM 仅在 `device_count>=2` 时换另一张卡重试一次且**不降精度/不降折数**。
- **几何**：输入按原 CT 网格写临时 NIfTI；输出必须与输入 `size/spacing/origin/direction` 一致（容差 1e-4），否则失败；统一转 LPI；禁止把失败输出静默重采样成"看起来可用"。

### 3.3 统一输出契约

`ModelOutput` 经 `CTVSegmentationTool` 归一为统一 metadata：

`ctv_array`（二值靶区并集，uint8）、`ctv_mask`（LPI 参考网格）、`full_label_array`（>1 标签时）、`label_map`、`label_counts`、`label_stats`（统一计算各标签体素/体积/质心）、`ctv_voxel_count`、`ctv_volume_mm3`、`tumor_type_used`、`ctv_source`=路由 id、`target_semantics`、`ct_phase`、`inference_script`、`checkpoint`、`model_validation`。

现状需补齐：胰腺缺 `ctv_source`/`tumor_type_used`（外层回退成 `"model"`）；级联与站点模型缺 `label_stats`；`ctv_source` 命名不一致（`model` / `nnunet_cascade_*` / 路由 id）。统一后**所有站点的 `ctv_source` 等于注册表 id**。

### 3.4 下游语义统一

删除 `web/structure_service.py` 的 `_is_model_ctv_source`/`is_multitarget_gtv_source` 前缀猜测与 `web/routes/viewer_routes.py` 的并行 `is_model_ctv` 分支，改为**按 `ctv_source` 查注册表 `target_semantics`**：

- `single_target` → 二值靶区（肝/肾/肺/结肠/前列腺）。
- `target_plus_anatomy` → 标签 1 为靶区，2..N 为解剖（归 OAR 源，如胰腺 2/3/4）。
- `multi_target_gtv` → 标签 1/2 均为靶区；规划取并集，Data Tree 分标签显示（头颈/鼻咽）。

同步复核 `web/routes/planning_routes.py` 的 CTV/OAR 存储与 provenance 键，确保六站写入路径一致。

### 3.5 前端统一

- 选择器选项来源统一为注册表（服务端渲染 + `/ctv/models?include_experimental=1` 能力状态），**新增站点只改注册表**。
- **颜色统一：已支持且 `callable` 的肿瘤类别一律绿色**；不可用为红并给出原因。验证成熟度（`verified`/`experimental`）只影响帮助文字，不影响颜色。
- 统一的空结果/失败/排队/推理中提示；鼻咽的 ncct/cect 作为并列条目，禁止按图像强度猜相位。
- 别名/相位透传补齐：`brachybot-ui-api.js` 的 `updateTumorTypeSelector`、`brachybot-manual-annotation.js` 调用链，补 `鼻咽`/`头颈部肿瘤`/`肺部肿瘤` 等。

### 3.6 路由与别名修复

- `normalize_tumor_type` 补：`头颈部肿瘤`/`头颈部`、`肺部肿瘤`/`肺部`/`肺` 等（对齐现有 `头颈肿瘤`/`肺癌`）。
- `agent_runtime/response_tools.py`：`_map_tumor_type` 处理 `nasopharynx` 哨兵——已知 `ct_phase` 时直接落 ncct/cect，未知时保留"需用户选择相位"，不再记 "Unknown tumor_type" 并清空；相应调整 `_SUPPORTED_AUTOMATIC_CTV_TYPES` 判定。
- `agent_runtime/turn_policy.py`：修正 `请分割<部位> CTV` 被判 `semantic_action`（`whole_request_contract_not_satisfied`）的直执行回归，保持 review=False。
- `ct_phase` 保持 `enum: [ncct, cect]`；无相位时工具返回 `code=ct_phase_required, requires_user_input=True`。

## 4. 错误处理

- 可用性在 catalog 探测与调用时各校验一次；缺失资源 fail closed，返回统一 `code`（沿用 `site_model_inference_failed` / `cascade_*`，统一命名）。
- 空 mask 统一诊断文案（"模型跑完但未检出靶区" vs "模型不可用"），不按站点特判。
- 取消：`OperationCancelled` 向上传播，子进程组终止并清理请求目录。
- 超时：终止进程组、清理临时目录、返回可重试错误；不得遗留占卡进程。

## 5. 测试

- `tests/test_model_registry.py`：注册表完整；每个 `ui_visible` 条目的 id/`tumor_type` 均可解析到已注册工具；别名矩阵；相位分发。
- `tests/test_executor_boundary.py`：六站 mock 引擎下输出键一致；gpu_lock 参与者覆盖六站+胰腺；取消/超时/OOM 行为一致。
- `tests/test_downstream_equivalence.py`：按 `target_semantics` 合成结果分别喂给 `structure_service`/`viewer_routes`/`planning_routes`，断言表现一致且**源码中不再存在按站点前缀特判**；肺被识别为模型源。
- 前端契约：选择器选项 == 注册表；所有可用项绿色；鼻咽相位；别名；`/ctv/models` 字段。
- 更新既有：`test_site_model_deployment.py`、`test_nnunet_cascade_tumor.py`、`test_review_round6_regressions.py`、`test_runtime_contracts.py`、`test_uploaded_mask_staging.py`、`test_image_metadata_query.py`。
- 可选真实 GPU 冒烟：每站 1 例（需用户同意占用 GPU），记录时长/体素/几何。

## 6. 迁移与兼容

- 所有路由 id 不变 → 会话快照、`ui_bridge`、历史别名无需迁移。
- 胰腺仅新增 GPU 锁，推理参数/精度/折数不变。
- 权重文件不移动（目录约定不统一的问题用注册表收敛声明解决，避免大范围移动引发路径回归）。
- 兼容层保证既有 `from ...site_models import SITE_MODELS` / `CASCADE_SITE_SPECS` 导入不破。

## 7. 分阶段

1. 后端：注册表 + 执行边界 + 输出契约 + 下游语义 + 单元/等价测试。
2. 前端 + 路由/别名缺陷修复 + 前端契约测试。
3. 可选 GPU 冒烟与 catalog 成熟度文案定稿。

## 8. 风险

- 同仓存在另一会话的未提交改动（`index.html`、`response_tools.py`、`turn_policy.py`、`structure_service.py`、`viewer_routes.py`、`web/routes/planning_routes.py` 等）→ 改动需小步提交并逐项核对，避免冲突。
- GPU 锁只覆盖参与协议的适配器，不约束无关训练任务。
- VISTA-3D 在非胸部 CT 上可能假阳性（其 README 已注明）。
- 胰腺纳入锁后可能排到长任务之后；用排队超时 + 前端状态缓解。

## 9. 开放项

- 发布树 `BrachyBot-release` 同步：另开一轮。
- catalog 成熟度文案最终措辞（`verified`/`experimental` 仅说明文字）。
