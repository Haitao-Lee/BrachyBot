# 手术导板生成延迟分析报告（Surgical Guide Latency Analysis）

- 日期：2026-09-16
- 范围：`web/surgical_guide.py`（4286 行）、`web/routes/surgical_guide_routes.py`、`tool_factory/surgical_guide/__init__.py`、前端 `brachybot-surgical-guide.js` 的触发路径
- 方法：**只读代码审查 + 现有服务器日志实测 + 1/8 规模微基准外推**（未修改任何代码，未改动病例）
- 目标：在**结果与质量不变**的前提下给出加速方案与预期效益
- 原始预测：现场观察到单次约 **250–400s**；原方案估计优化后 **60–110s（约 3–5x）**。这是基于日志和外推的预测，不是已验证的收益。下面新增实施复核与成对实测；原分析保留作为方案来源。

## 实施复核（2026-09-16，优先于原方案的等价性和收益表述）

本次以远端 `codex/session-task-recovery` 的实际工作树为基线（HEAD `d09a104ea`，包括当时尚未提交的导板修复），不是用干净 HEAD 覆盖工作树。完整旧模块保存在 `tests/data/surgical_guide_latency_reference.py`，SHA-256 为 `dad562e79d2036fb836c2656f487658bf3344675bd09f8bf08186b839f1f06ff`。外部几何依赖的哈希由 `tests/guide_latency_reference.json` / `scripts/guide_latency_reference_guard.py` 固定；依赖发生修改必须重新审核，避免两侧同时漂移。

### 对原报告的修正

1. **P0 必须覆盖公共生成入口。** 只改 HTTP route 不能合并工具直接调用。现采用 `generate_surgical_guide` 内的进程内 in-flight 合并，键包含同一 memory 实例、CT 内容/形状/类型/空间元数据、规划身份与几何、人工版本、制造参数和选择的针道。只合并重叠请求；后续明确重新生成仍重新执行，避免陈旧结果缓存。不同进程或不同 memory 实例不共享飞行中的结果。失败清理键，等待者可独立取消。
2. **P1 的窄带哨兵方案不能按原论证实现。** `_remove_truncated_cap_backed_voxels` 会读取 `signed_distance` 的实际数值，再与到截断面的距离比较；并非所有下游都只读固定阈值。原报告还未证明插值后的标签 SDF 满足所用 Lipschitz 界。完整 SDF 与原重采样路径保持不变。
3. **P2/P4 的数学等价不等于浮点逐位等价。** 未采用改变世界/索引坐标运算顺序的圆柱公式。保留原 float64 物理变换、表达式顺序和边界判断，只用广播网格与实体稀疏索引减少工作量。补片只在入口球局部盒内处理，保留原 float32 入口量化；临界带回退原 cKDTree 判定。
4. **默认网格的 blur 实际是恒等操作。** 当前 `blur_sigma=min(0.4, 0.35*min(spacing))` 是体素单位；默认 0.2 mm 得到 0.07，SciPy 默认 truncate=4 的离散核半径为零。原报告按 sigma=0.35 体素估计滤波成本不符合代码。直接生成原 MC 最终接收的 float32 二值数组严格等价；并未把非零半径 float64 滤波改成 float32。
5. **MC 裁剪须保留原坐标舍入。** 默认二值场裁剪后，先在单位网格提取整数/半整数顶点，恢复原网格偏移，再执行原 spacing 乘法及 float32 舍入，之后才平滑和变换；不是简单地在已平滑世界坐标上加 offset。非二值、非零半径 blur 等情况使用原路径。
6. **重复计算的 CPU 工作量不能直接乘成延迟收益。** 两个重叠调用共享 CPU/内存带宽，取消一份的墙钟收益必须现场测量；本次成对生成测试未将理论双跑收益计入。
7. 微基准的体积倍数不保证线性墙钟外推：MC 的输出规模、内存带宽、并发负载及拓扑修复都会影响实际结果。环境实测为 NumPy 2.4.6、SciPy 1.15.3、scikit-image 0.26.0、SimpleITK 2.5.0；原附录中的 SciPy 0.3.31 不是本环境版本。

### 已实施的优化

- 共享生成入口合并同一病例的重叠相同请求；阶段日志新增 `call_id`。
- 圆柱用稀疏广播保留原算式；切孔只对实体体素计算，辅助孔仍保持原顺序及支撑审核。
- 入口局部球替代整张皮肤壳层的最近邻批量查询；阈值附近仍用原判定。
- 连通域只标记非空包围盒，保留扫描顺序和等大组件取舍；仅需要桥接时才构建整张壳层点表。
- 默认二值场直接生成 float32 MC 输入并裁掉空白区域，保留原頂点坐标舍入、面序和平滑流程。
- 孔壁投影保留原完整轴向矩阵乘法，只对轴向和包围盒筛选后的顶点求径向距离；交叉孔保护不变。
- 追加剖析发现一个 8 针病例仍有 125 个孔壁投影、约 15,500 次交叉孔检查：改用逐坐标筛选避免 N×3 临时布尔数组，并用带保守数值余量的包围盒排除确定不相交的孔对。其余孔对的原始判定完全保留。
- Taubin 平滑复用稀疏乘积缓冲区；除法、减法、乘法和加法的执行顺序及 float64 精度保持不变，仍执行原 20 次双向迭代。
- 水密性检查将无向边无损编码为 uint64 后统计，所有边 multiplicity、开放边和非流形边判定不变。
- 拓扑修复形态学运算限制在实体包围盒加两层完整 halo，保留真实数组边界与原修复次序。
- 体表缓存使用 CT 内容与空间信息、阈值、平滑参数键，按 memory 隔离，至多保留两份、弱引用归属；原始边界体表和光滑体表一起复用。

默认制造网格 0.2 mm、5 mm 截断、壁厚、所有针道/孔道约束和质量拒绝条件均未修改。`BRACHYBOT_GUIDE_FAST_PATH=0` 可回退本次数值快路径和入口合并/体表缓存，便于在同一部署中对照。

### 验证方式与适用边界

`scripts/benchmark_surgical_guide_latency.py` 从保存的 Session 只读恢复 CT/针道至隔离 memory，调用完整导板生成函数，不调用 `save_guide_version`、HTTP、UI 或实际 Session checkpoint。分别运行冻结基线和当前代码，核对 snapshot/CT/参数/规划签名一致后，对顶点、三角面、辅助孔及去掉计时的全部 validation 做 SHA-256 比对。生成耗时不含加载、浏览器下载/渲染和持久化；进程峰值 RSS 包含输入恢复及摘要计算。

这能证明所测病例的生成结果逐元素一致，不等于已经测得所有病例或浏览器端到端延迟。测试期间服务器有其他工作负载，因此单次耗时有波动，不以历史拥塞日志作为同条件基线。

### 最终成对实测

以下为生成函数内部的 `stage_timings_seconds.total`，所有测试独立进程冷启动，未把体表缓存命中或并发去重收益计入：

| 输入/配置 | 冻结基线 | 优化后 | 加速比 | 进程峰值 RSS（前 → 后） | 输出比对 |
|---|---:|---:|---:|---:|---|
| 截断 FOV，最终 4 条有效针道，0.2 mm，冻结快照复测 | 19.081 s | 6.646 s | 2.87× | 6.87 → 3.92 GiB | 五项哈希全一致 |
| 8 针，0.2 mm | 27.539 s | 10.328 s | 2.67× | 8.13 → 4.19 GiB | 四项哈希全一致 |
| 50 针，包含拓扑修复，0.2 mm | 119.178 s | 43.227 s | 2.76× | 9.76 → 5.21 GiB | 四项哈希全一致 |
| 同一 8 针输入，独立测试 0.35 mm | 7.625 s | 4.205 s | 1.81× | 2.73 → 1.98 GiB | 四项哈希全一致 |

四项哈希是 vertices、faces、auxiliary_holes、删除计时字段后的完整 validation；包含孔径误差、支撑 QA、截断面判定、所有拓扑修复尝试与结果。第五项是 needle_paths。8 针另一次复测 26.178→10.527 s，五项哈希亦相同。0.35 mm 仅为隔离验证参数，不更改病例或产品默认值。另一个旧病例因保存的 CT 路径无法恢复，未列入成对样本，未修改该病例数据。

4 针病例初始基线为 27.745 s，后续在线服务更新了其 Session 快照。即使 CT/规划签名及几何结果均匹配，仍不使用跨快照的时间配对；重新固定快照清单后得到上表 19.081→6.646 s。这也说明不能将不同负载下的历史耗时作为确定收益。

在 50 针病例中，plate_patch 13.300→5.586 s，mesh_extraction_and_validation 24.528→7.658 s，mesh_topology_repair 67.899→22.390 s。追加孔壁优化前的总耗时为 64.222 s，追加后为 43.227 s；8 针病例对应为 13.930→10.328 s。

最终几何/运行时/原有导板回归：**96 passed，3 个既有 SWIG DeprecationWarning**。差分覆盖旋转/各向异性圆柱、稀疏切孔、入口球阈值、随机拓扑与坐标偏移、不同网格分辨率、连通域并列与空输入、桥接、孔壁投影及交叉保护、形态学 halo/真实边界、边计数、平滑舍入、缓存失效隔离、in-flight 失败清理/等待者取消。完整参考模块和依赖哈希都随代码保留。

可复跑脚本：

```bash
python scripts/benchmark_surgical_guide_latency.py --workspace <saved-session> --variant baseline --output /tmp/guide-before.json
python scripts/benchmark_surgical_guide_latency.py --workspace <same-saved-session> --variant current --output /tmp/guide-after.json
python scripts/summarize_guide_latency.py --pair case /tmp/guide-before.json /tmp/guide-after.json --output /tmp/guide-paired-summary.json
```

聚合证据：`docs/benchmarks/surgical_guide_latency_2026-09-16.json`。比较脚本要求两侧输入指纹与全部输出哈希相同才生成汇总；后续重跑还会记录针道来源 `needle_paths`，避免只比较网格而遗漏针道元数据。在线病例有更新时，用 `--snapshot-file <frozen-manifest.json>` 固定两侧快照清单，资源仍从原只读 workspace 解析。

### 后续可探索但本次没有默认启用

- 更完整的空间索引可进一步减少孔壁扫描，但选点前后若更换 BLAS 矩阵乘法形状，舍入路径可能不同，必须先做新的严格差分。
- 粗细分层 SDF 需要同时维护截断面距离语义和可证明的误差界，不能直接使用原 P1 的带外哨兵。
- 跨进程任务合并以及完成结果复用需要稳定的病例身份、版本、失败/取消及持久化事务契约；本次只实现同进程同 memory 的重叠计算合并。
- 浏览器下载、STL 序列化和 checkpoint 的额外耗时需另做端到端观测，本表未把这些耗时包含进来。服务器共享负载仍会影响墙钟时间，不能承诺所有几百秒病例统一降到固定秒数。

---

## 1. 现状与实测数据

### 1.1 流水线与代码位置

`generate_surgical_guide()`（`web/surgical_guide.py:3396`）在一个线程内顺序执行：

| # | 阶段（日志名） | 代码 | 规模/说明 |
|---|---|---|---|
| 1 | `skin_envelope` | `_body_mask` 1438 / `_largest_component` 1427 / `_smooth_body_mask` 1716；3441–3461 | 全 CT（201×313×403 ≈ 25.3M 体素）阈值+连通域×3+闭运算+填洞+各向异性高斯 |
| 2 | `skin_surface_persisted` | `store_guide_skin_surface` 1454 | 持久化体表掩膜到 session |
| 3 | `local_grid_resampled` | `_resample_mask_to_local_grid` 2849；3523–3547 | 源裁剪（CT 分辨率）双 EDT → 在 **931×436×1496 = 607,250,336 体素** 的 0.2mm 网格上做三线性采样（SDF + 掩膜） |
| 4 | `skin_distance_field_reused` | 3548–3555 | 复用上一步 SDF（0.0–0.03s） |
| 5 | `plate_patch` | 3572–3612；`_connect_plate_patch_components` 2744 | 全网格布尔带（`~body & od∈[c,c+t] & safety`）、`np.argwhere` 8.79M 点、KD-tree 查询、`ndimage.label` 607M |
| 6 | `auxiliary_holes` | 3618–3661；`_auxiliary_hole_specs` 415、`_auxiliary_hole_support` 2257 | 36 针 × 2 环 × 12 孔 = **864 个候选**，逐个 SDF 盒子 + 采样校验（实测 realized 503） |
| 7 | `primary_sleeves_and_bores` | 3669–3723；`_primary_bore_cutter_specs` 339 | 36 个套筒联合 + 36 个主通道切割（跨套筒时切割长度会加长） |
| 8 | `solid_cleanup` | 3729–3804；`_retain_largest_printable_component` 2335、`_primary_sleeve_support_quality` 2407、`_face_component_count` 2632 | 截断帽剔除、`ndimage.label`、逐通道环采样 QA |
| 9 | `mesh_extraction_and_validation` | 3822–3840；`_mesh_from_mask` 3013、`_smooth_mesh_vertices` 3070、`_project_bore_walls` 3131、`mesh_validation` 3344 | 全网格 `float64` 转换 + 高斯 + `np.pad` + Marching Cubes + Taubin + 逐孔壁投影 |
| 10 | （可选）`mesh_topology_repair` | 3841–4010 | 网格不水密时的重修复路径（可放大为多次重建） |
| 11 | 持久化与返回 | 4015–4184 | QA 汇总、STL 序列化、`save_guide_version` |

### 1.2 服务器日志实测（2026-09-16 17:54–17:57，同一病例）

```
17:54:50.657 skin_envelope              5.735s
17:54:50.743 skin_surface_persisted     0.086s
17:55:28.620 local_grid_resampled      37.877s   grid_shape=(931,436,1496) 607,250,336 voxels
17:55:28.640 skin_distance_field_reused 0.021s
17:55:49.528 skin_envelope              9.025s   ← 第二次（见 1.3）
17:55:49.596 skin_surface_persisted     0.069s
17:56:07.058 plate_patch               38.418s   plate_voxels=8,793,204 initial_components=1 bridges=0
17:56:24.303 auxiliary_holes           17.244s   requested=864 realized=503
17:56:37.957 local_grid_resampled      48.360s   ← 第二次（见 1.3）
17:56:59.902 primary_sleeves_and_bores 35.599s   needle_count=36
```

同一日志的 16:40 轮：`skin_envelope` 10.36s + 10.13s、`local_grid_resampled` 75.82s（该轮被中断，未跑完）。

**已实测阶段合计（单次调用的一部分）≈ 190–200s**；日志中未捕获 `solid_cleanup`、`mesh_extraction_and_validation`、持久化等阶段，按第 1.4 节微基准外推约 **30–90s**，与用户体感"几百秒"一致。

### 1.3 关键发现：同一病例同时跑了两份生成（重复执行）

17:54–17:57 窗口内只有一次 `Executing tool: surgical_guide`（17:54:44.897），但出现了：

- 两段 `skin_envelope`（17:54:50 与 17:55:49）；
- 两段 `local_grid_resampled`（37.9s 与 48.4s）。

按每段的 duration 反推起点可复原为两条并发流水线：

- **调用 A（聊天工具）**：17:54:44.9 开始 → skin(5.7) → local_grid(37.9) → plate(38.4) → aux(17.2) → sleeves(35.6)；
- **调用 B（约 17:55:40 开始，日志无 `Executing tool`）**：skin(9.0) → local_grid(48.4) → …

两条路径的入口分别是：

- 聊天工具：`tool_factory/surgical_guide/__init__.py:217` → `generate_surgical_guide(...)`；
- 前端"自动生成"：`web/app/static/js/brachybot-surgical-guide.js:800-833` 在状态为 `not_generated/stale` 且 `autoGenerate === true` 时调用 `POST /api/surgical-guides/generate`（`web/routes/surgical_guide_routes.py:240-292`）。

前端有 `autoGeneratedSignatures`（按签名去重，`brachybot-surgical-guide.js:817`），但**服务端没有任何 in-flight/结果去重**：聊天工具与 API 各跑一份、并发写同一病例。B 至少重复了 A 的 skin+resample（≈57s），并会继续重复 plate/aux/sleeves。16:40 轮同样是双 `skin_envelope`（间隔 11.2s）。

**这是收益最大、风险最低的一项（见 P0）。**

### 1.4 资源画像与微基准

- 0.2mm 局部网格 = **607M 体素**；常驻数组估算：
  - `skin_signed_distance` float32 = **2.43 GB**
  - `body_crop` / `plate_mask` / `patch_mask` / `solid` / `boundary_safe_mask` 各 bool ≈ **0.61 GB × 5**
  - 第 5 阶段另有 `plate_voxel_indices`（8.79M×3 int64 ≈ 211 MB）与 KD-tree 结构
  - **plate_patch 时点常驻 ≈ 6–7 GB**
- `_mesh_from_mask`（3013）：`mask.astype(np.float64)`（4.86 GB）+ `gaussian_filter` 输出 float64（4.86 GB）+ `np.pad`（≈4.9 GB）+ `marching_cubes` 内部 → **峰值 >15 GB**，且长时间占用进程内存。
- 1/8 规模微基准（75.8M 体素，脚本 `/tmp/opencode/guide_bench.py`，仅外推参考）：

| 操作 | 1/8 实测 | ×8 外推 |
|---|---|---|
| `float64` 转换 | 0.30s | ≈2.4s |
| 高斯（σ=0.35 vox） | 0.74s | ≈5.9s |
| `np.pad` | 0.33s | ≈2.6s |
| Marching Cubes（lewiner） | 1.09s | ≈8.7s |
| `ndimage.label`（6-连通） | 0.46s | ≈3.7s |
| `np.argwhere` | 0.47s | ≈3.7s |
| 单次全网格 bool 运算 | 0.168s | ≈1.3s |

> 说明：微基准的掩膜比真实导板实心体稠密（argwhere/label 为悲观上界）；Marching Cubes 成本与体素数近似线性，外推可信。

---

## 2. 热点分析与优化方案

各项均标注：成本来源 → 方案 → **等价性论证** → 预期收益 → 风险。等价性分三类：
- **[逐位等价]** 操作裁剪/索引重排/批量合并，布尔结果与顶点数值路径不变；
- **[阈值等价]** 只改变未参与判定的数值（下游只用比较），判定结果一致；
- **[QA 容差内]** 浮点路径改变导致的微米级差异，需用几何容差验收（不作为首选）。

### P0 服务端生成去重与合并（风险≈0，收益最大）

- **问题**：1.3 节实测同一病例并发两份生成；前端去重只覆盖自身路径。
- **方案**：在 `web/routes/surgical_guide_routes.py` 增加**按病例的生成注册表**（`(user, session, planning_signature, parameters_hash, needle_set) → Future/结果`）：
  - 已在跑：第二个调用者直接等待同一 Future（或返回"进行中"状态），不再启动第二份；
  - 已完成且键一致：直接复用当前 guide 版本（`_resolve_guide_version` 已有签名/版本逻辑，4015–4040）；
  - 生成线程完成/失败后清理注册表；用 `threading.Lock` + 每个 key 的 `threading.Event` 实现，无需改动几何代码。
- **等价性 [逐位等价]**：只影响"谁执行"，结果仍是同一个 `generate_surgical_guide` 产物并走同一 `save_guide_version`/`publish_active_planning_guide`。
- **预期收益**：消除观测到的重复执行；单次时长里可直接省掉一份完整生成（实测至少 57s 重复 skin+resample，完整一份约等于整体时长）。若当前常态是双跑，端到端**接近 2x**。
- **风险**：需处理"生成中参数不同"（不同 `needle_ids`/参数不应合并）——按完整键区分即可；失败后必须释放 key。

### P1 `local_grid_resampled`：从"全网格 0.2mm 采样"改为**窄带 + 包围盒**（37.9–75.8s → 预计 8–20s）

- **成本来源**（`_resample_mask_to_local_grid` 2849–2947）：在 607M 个目标格点上做 `map_coordinates(order=1)` 三线性采样；`sampled_signed_distance` 本身就是 2.43GB 的写带宽。两个 EDT 只作用在源裁剪（CT 分辨率，≈6M 体素），不是瓶颈。
- **方案**（推荐组合）：
  1. **粗-细分两级**：先在 0.4–0.8mm 粗格（607M/8 或 /64）计算同一 SDF（同一 EDT + 三线性），对每个 0.2mm 格点用粗值 + 保守 Lipschitz 界（线性插值在 0.2mm 步长内的变化 ≤ √3·0.2mm，再加上粗格距）判断其是否可能落入后续阈值区间；
  2. 仅对"可能落入区间"的格点做精确 0.2mm 采样；其余按上/下界写 clamped 哨兵值（如 `+1e6` / `0`）；
  3. 采样循环保留现有分片+线程池（`_resample_worker_count` 2833、`GUIDE_RESAMPLE_MAX_WORKERS=8`），但分片只覆盖命中的子区间。
- **阈值区间**（决定窄带宽度，全部在 `generate_surgical_guide` 内可静态求出）：
  - `plate_mask`：`outside_distance ∈ [protected_clearance, protected_clearance+plate_thickness]`（3572–3577）；
  - `sleeve_mask`：`outside_distance >= protected_clearance`（3682–3686）——**单调阈值**，可用粗值保守判定；
  - `_remove_truncated_cap_backed_voxels`（2950）用的是 2D EDT+最近索引，不依赖全精度 SDF；
  - 其余 `solid` 组合件（patch/aux/bores）不读 SDF 数值。
- **等价性 [阈值等价]**：所有下游对 `outside_distance` 的使用都是 `>=`/`<=` 比较；对落在带外的格点写成严格越界的哨兵值，判定结果不变（带内格点仍走原精确采样）。需在实现时保留"带边界 ± 保守余量"并加差分测试。
- **预期收益**：带内格点通常占 10–30%（皮肤壳层 + 裁剪范围），采样与写带宽减少 **3–6x**；该阶段 38–76s → **8–20s**，同时 `sampled_signed_distance` 可改为稀疏/分块存储，常驻内存从 2.43GB 降至 <0.8GB。
- **风险**：两级判定的保守界必须正确（建议用"冻结旧实现差分"逐格点验证，见第 4 节）；不改变 0.2mm 默认分辨率（不牺牲制造精度）。
- **更低风险的变体（先做）**：仅计算**plate 带的包围盒**（用粗格或分片阈值扫描得到 bbox），把后续所有全网格算子（P2–P5）限制在 bbox 内；即使不带内细化，也能按 bbox/crop 体积比拿到 1.5–3x。

### P2 `plate_patch`：全网格扫描 + KD-tree → 包围盒 + 直接索引（38.4s → 预计 3–6s）

- **成本来源**（3572–3612）：`plate_mask` 的 3 次全网格布尔（每次 ≈1.3s）+ `np.argwhere(plate_mask)`（实测 `solid` 8.79M 点，`plate_mask` 点数 ≥ 该值；int64 索引 ≥211MB）+ `cKDTree(entry_indices).query(plate_voxel_indices)`（8.79M×36 距离）+ `_connect_plate_patch_components` 内再次 `ndimage.label(607M)` 与 `np.argwhere`。
- **方案**：
  1. 先用 P1 的 bbox（或对 `plate_mask` 做分片 bounding-box 扫描）把布尔与索引操作限制在包围盒；
  2. `np.argwhere` → `np.nonzero`（避免 (N,3) 复制）并立即转 int32；
  3. patch 判定改为**分块广播**（8.79M×36 的近似距离，chunk 处理）或直接"按 entry 盖球"（半径 24mm/0.2mm=120 体素，逐 entry 在其局部盒内 `distance<=r` 置位）——两者与现有 KD-tree 查询的布尔结果完全一致（都是"到最近 entry 的欧氏距离 ≤ patch_radius_index"）；
  4. `_connect_plate_patch_components` 只调用一次 `label` 并在同一 label 结果上复用（当前 `initial_count<=1` 时已在早期返回，未走 bridging，故 38.4s 主要来自上面 1–3）。
- **等价性 [逐位等价]**：布尔集合逐体素一致；patch 判定是同一不等式的不同求值顺序。
- **预期收益**：38.4s → **3–6s**（bbox 2–4x + 索引/查询 5–10x）。
- **风险**：低；需保证 chunk 边界/盖球半径用同一离散半径常量。

### P3 `auxiliary_holes`：864 个候选逐个建盒 → 按针批量、只在 plate 体素上求值（17.2s → 预计 3–6s）

- **成本来源**（3618–3661、`_auxiliary_hole_support` 2257、`_cylinder_sdf_in_region` 2137）：864 个候选各自构造局部盒的世界坐标网格并求平底圆柱 SDF；校验阶段另做两次稀疏采样。
- **方案**：
  1. **按针共享包围盒**：同一针的 24 个孔中心都落在 entry 附近（偏移 ≤ `first_offset+ring_spacing`≈6mm，半径≈1.75mm，轴向长度 `clearance+plate+8mm`×2 ≈ 22mm），把 24 孔合并到一个 ~50×50×120 体素的盒内一次建网格，总盒体积从 ~93M 降到 ~11M（≈8x）；
  2. **只对 plate 体素求 SDF**：`removable = solid & plate_mask & hole_mask`，可在盒内先取 `plate_mask` 的非零索引，仅对这些点计算平底圆柱内外判定（解析式，无需整盒世界网格）；
  3. `_auxiliary_hole_specs` 中的 O(N²) 主套筒冲突检查（415–470：36×864 段距离）与接受阶段 O(A²)（32–41 万对）已经是小头，可用向量化/剪枝，但非必需。
- **等价性 [逐位等价]**：孔掩膜是解析 SDF 的 `<=0` 判定；盒合并与稀疏取点不改变判定集合。
- **预期收益**：17.2s → **3–6s**。
- **风险**：低；保持 `AUXILIARY_HOLE_OVERRUN_MM=8`、半径与判定常数不变即可。

### P4 `primary_sleeves_and_bores`：108 个圆柱逐一建盒 → 索引空间解析式 + 现行实心裁剪（35.6s → 预计 8–15s）

- **成本来源**（3669–3723、`_cylinder_sdf_in_region` 2137、`_subtract_cylinder_specs_from_mask` 2191）：36 套筒 + 36 主切割（跨套筒时切割长度按 `_primary_bore_cutter_specs` 扩大，盒子更大）逐个构造世界网格（float64，多数组）并求 SDF；然后对大盒做 `solid[box] |= ...` / `&= ~...`。
- **方案**：
  1. **索引空间解析式**：局部网格各向同性且轴对齐（`spacing_zyx` 均匀），圆柱 SDF 可直接在索引坐标下计算（把 start/end/axis 一次性变换到索引空间，径向距离按 spacing 缩放）；等价于世界坐标公式的仿射变换；
  2. **盒子收缩**：`lo/hi` 取"圆柱包围盒 ∩ solid 的包围盒（P1/P2 产出）"；
  3. **稀疏求值**：套筒用 `solid[box] |= sleeve_mask` 前，先取 `outside_distance[box] >= protected_clearance & boundary_safe` 的非零索引，只在候选点算 SDF；主切割同理只在 `solid[box]` 为真的体素上求 `sdf<=0`。
- **等价性 [逐位等价/阈值等价]**：SDF 的符号判定集合不变；索引空间公式是同一几何的等价表达，浮点误差 ≤1e-6mm，仅在恰好落在表面的单个体素上可能翻转（差分验证覆盖）。
- **预期收益**：35.6s → **8–15s**。
- **风险**：低-中；需保留横截套筒的加长切割语义（339–413），不得改变 `nominal/cutter` 长度与跨套筒判定。

### P5 网格与收尾：包围盒裁剪 + float32 + 逐孔盒预筛（≈30–90s → 预计 10–25s）

- **成本来源**：
  - `_mesh_from_mask`（3013）：全 607M 网格 `float64` 转换/高斯/`np.pad`/Marching Cubes，峰值 >15GB；
  - `_project_bore_walls`（3131）：对全部 ~50 万顶点、对 36 主孔 + 503 辅助孔各做一次 N×3 向量运算与 `_inside_flat_cylinder` 交叉检查（≈540 × 50 万 × 3 运算）；
  - `mesh_validation`（3344）：对 ~1.5M 面做边排序/唯一化（~1–2s，尚可）。
- **方案**：
  1. **先取 `solid` 的紧包围盒**（`np.nonzero` 一次得到 min/max，7.9–8.8M 点），把 `mask` 裁剪到 bbox+（kernel 半径 4 体素）后再做 float64 转换/高斯/pad/MC —— 高斯是局部核，裁剪边界外全 0，**保留区数值逐位不变**；
  2. **float32 字段**：blur 输出与 pad 保持 float32（MC 接受 float32），内存减半；顶点位置与 float64 路径相差在 1e-6mm 量级，属 [QA 容差内]，作为可选开关（默认保留 float64 若要求逐位一致）；
  3. **`_project_bore_walls` 预筛**：对每个孔先算"顶点落入（轴段包围盒 + 半径 + tolerance）"的稀疏索引（一次 O(N) 比较或一次性 KD-tree/网格桶），仅对候选顶点做现有投影与交叉保护计算。`selected` 条件（径向误差 ≤ tolerance 且轴向在范围内）必然落在该包围盒内，**判定集合不变**；
  4. `_smooth_mesh_vertices` 已是稀疏矩阵实现（3070–3130），无需改动。
- **等价性 [逐位等价] 用于 1/3；[QA 容差内] 用于 2**。
- **预期收益**：mesh+投影+QA 由 ≈30–90s 降至 **10–25s**；峰值内存由 >15GB 降至 5–8GB（float32 选项再减半），显著降低与其他服务（快照/截图/模型推理）的内存争用。
- **风险**：中（float32 选项需几何容差验收）；建议先做 1/3（逐位等价），2 作为可选。

### P6 `skin_envelope` 复用（5.7–10.4s × 重生成次数）

- **问题**：`_body_mask` + `_smooth_body_mask` 只依赖 CT、阈值与 σ=2.0mm，与针道无关；但每次生成都重算（`store_guide_skin_surface` 只持久化结果、不做复用，1454–1513）。
- **方案**：以 `(CT 内容哈希/版本, skin_threshold_hu, sigma=2.0mm)` 为键复用 `skin_surface_mask`（含裁剪前全 CT 网格）；未命中再计算。生成后仍按现有逻辑持久化与递增 `data_version`。
- **等价性 [逐位等价]**：复用同一输入产生的同一掩膜（当前实现是确定性算子）。
- **预期收益**：每次重生成省 6–10s；与 P0 叠加后，重复调用的浪费进一步下降。
- **风险**：低；需定义 CT 变更失效条件（现有 `data_version`/CT 哈希基础可复用）。

### P7 观测与环境（不改结果）

- 在 `finish_stage` 日志中补充 `call_id`（每次 `generate_surgical_guide` 生成一个随机/请求 id），可直接证实/排除 1.3 节的并发重复；
- 生成入口记录 `request_id`/`planning_signature`/`parameters_hash`/`needle_count`，便于统计与去重审计；
- 实测窗口内还有截图保存、workspace 检查点等并发负载（`Screenshot saved` 与 `checkpoint` 日志穿插），建议生成期间避免同时做报告截图/重规划；P5 的内存优化也会显著缓解。

---

## 3. 预期收益汇总（保守区间）

| 方案 | 目标阶段 | 现值（实测/外推） | 预期 | 等价性 |
|---|---|---|---|---|
| P0 服务端去重 | 整体 | 观测到 2 份并发 | 省 1 份（≈2x，视触发情况） | 逐位 |
| P1 窄带+bbox | local_grid_resampled | 37.9–75.8s | 8–20s（3–6x） | 阈值等价 |
| P2 索引化 | plate_patch | 38.4s | 3–6s（6–10x） | 逐位 |
| P3 按针批量 | auxiliary_holes | 17.2s | 3–6s（3–5x） | 逐位 |
| P4 索引+稀疏 | primary_sleeves_and_bores | 35.6s | 8–15s（2.5–4x） | 逐位/阈值等价 |
| P5 bbox+预筛(+f32) | mesh/QA/投影 | ≈30–90s（外推） | 10–25s（2–4x） | 逐位 / QA 容差 |
| P6 体表复用 | skin_envelope | 5.7–10.4s/次 | 0（命中时） | 逐位 |

**单次生成（单跑）**：≈250–400s → **≈60–110s（约 3–5x）**；
**叠加 P0（消除并发重复）**：在观测到的双跑场景下可再接近 2x。
**第一步建议**：仅做 P0+P6（零几何风险）即可省 40–70s/次并消除双跑；再做 P2→P3→P4→P5→P1（由易到难）。

---

## 4. 质量不变性验证方案（验收口径）

1. **金标准差分**：选 3–5 个代表性病例（稀疏/密集针道、含截断 FOV、不同 `geometry_resolution_mm`），改动前后各跑一次，逐项比对：
   - 阶段耗时（`validation.stage_timings_seconds`）；
   - `validation.watertight/open_edges/nonmanifold_edges/vertex_count/face_count/bounds_world_mm`；
   - `bore_quality.max_radius_error_after_mm`、`projected_vertex_count`、`cross_bore_protected_vertex_count`；
   - `primary_sleeve_support`（每通道采样与 valid）、`plate_connectivity`、`component_cleanup`；
   - `auxiliary_holes.realized/skipped`（含 skip_reason 列表）；
   - `plate_voxels`（P2 后应逐位一致）。
2. **网格几何**：逐位等价方案要求 STL 顶点集合逐元素一致（或 Hausdorff 距离 = 0）；float32 可选方案要求 ≤ 制造容差（建议 ≤ 1e-3 mm 并记录最大值）。
3. **冻结旧实现差分测试**：仿照 `tests/test_planning_latency_equivalence.py`/`tests/latency_reference.json` 的做法，把旧的热函数（`_resample_mask_to_local_grid`、`_cylinder_sdf_in_region`、`_mesh_from_mask` 等）冻结为参考实现，对随机/真实输入做数值差分（布尔数组要求完全相等）。
4. **回退开关**：新增 `BRACHYBOT_GUIDE_FAST_PATH=0`（或等价参数）可回退旧路径，供现场对比与紧急回退。
5. **端到端**：同病例连续生成两次，第二次应命中 P0/P6 的复用（日志可见"reused"与总时长下降），且 guide 版本/QA 与首次一致。

---

## 5. 实施顺序建议

1. **P0**（服务端 in-flight/结果去重）+ **P7**（call_id 观测）——最小改动，直接消除重复与不可观测性；
2. **P2**（plate_patch 索引化）+ **P6**（体表复用）——低风险、收益立竿见影；
3. **P3**（aux 批量）+ **P4**（索引空间圆柱）——同一类局部盒优化，可合并为一次"圆柱 SDF 引擎"重构；
4. **P5**（mesh bbox+投影预筛，可选 float32）——收益大，需要几何容差验收；
5. **P1**（窄带两级采样）——收益最大但实现最复杂，放在前四项验证经验之后。

---

## 6. 不建议的加速方式

- **降低 `geometry_resolution_mm` 默认值（0.2→0.3/0.4mm）**：离散实体与网格都会改变，属于"结果变化"，只能在用户明确接受制造精度变化时作为参数选项，不作为默认加速手段；
- **用 SDF min/max 直接等值面化替代布尔实体**：会产生退化褶皱/非水密风险，现实现刻意规避（3013–3029 注释）；
- **更换 Marching Cubes 实现/方法（如 lorensen、GPU 版）**：拓扑与顶点会变化，破坏"逐位等价"；
- **并行化阶段间的 CSG（多进程/多线程写同一大数组）**：内存与竞态风险高，且当前瓶颈是单阶段内的算子效率，收益/风险比不划算。

---

## 附录 A：日志证据摘录

```
2026-09-16 17:54:44,897 INFO tool_factory Executing tool: surgical_guide
2026-09-16 17:54:50,657 INFO web.surgical_guide ... stage=skin_envelope duration_s=5.735
2026-09-16 17:55:28,620 INFO web.surgical_guide ... stage=local_grid_resampled duration_s=37.877 grid_shape=(931, 436, 1496) grid_voxels=607250336
2026-09-16 17:55:49,528 INFO web.surgical_guide ... stage=skin_envelope duration_s=9.025        # 第二份生成
2026-09-16 17:56:07,058 INFO web.surgical_guide ... stage=plate_patch duration_s=38.418 plate_voxels=8793204 initial_components=1 bridges=0
2026-09-16 17:56:24,303 INFO web.surgical_guide ... stage=auxiliary_holes duration_s=17.244 requested=864 realized=503
2026-09-16 17:56:37,957 INFO web.surgical_guide ... stage=local_grid_resampled duration_s=48.360  # 第二份生成
2026-09-16 17:56:59,902 INFO web.surgical_guide ... stage=primary_sleeves_and_bores duration_s=35.599 needle_count=36
```

（同窗口还有 `Screenshot saved`、`workspace checkpoint` 并发日志；16:40 轮为同类双跑：10.36s/10.13s 两次 `skin_envelope` + 75.82s `local_grid_resampled`。）

## 附录 B：代码索引

| 主题 | 位置 |
|---|---|
| 生成主流程 | `web/surgical_guide.py:3396-4184` |
| 体表提取/平滑 | `1427`、`1438`、`1716`、`3441-3461` |
| 局部网格重采样 | `2833-2947`（线程池/分片）、`3523-3547` |
| 板与补片、组件桥接 | `3572-3612`、`_connect_plate_patch_components` 2744 |
| 辅助孔 | `415-557`、`2257-2334`、`3618-3661` |
| 圆柱 SDF/布尔 | `2101-2255`、`339-413`、`3669-3723` |
| 截断帽/单件清理/支撑 QA | `2950-3012`、`2335-2392`、`2407-2568`、`2632-2642` |
| 网格提取/平滑/孔壁投影/QA | `3013-3069`、`3070-3130`、`3131-3343`、`3344-3372` |
| 入口（API/工具/前端自动） | `web/routes/surgical_guide_routes.py:240-292`、`tool_factory/surgical_guide/__init__.py:217`、`web/app/static/js/brachybot-surgical-guide.js:800-833` |

## 附录 C：微基准

- 脚本：`/tmp/opencode/guide_bench.py`（临时目录，非仓库文件）
- 规模：`(465, 218, 748)` = 75,824,760 体素（真实网格的 1/8）
- 环境：AMD Ryzen 9 5900X（24 线程）、scipy 0.3.31/OpenBLAS、`~/.conda/envs/brachytherapy`
- 说明：结果为单次测量，用于量级外推；实施时应在目标病例上按第 4 节重新采集。
