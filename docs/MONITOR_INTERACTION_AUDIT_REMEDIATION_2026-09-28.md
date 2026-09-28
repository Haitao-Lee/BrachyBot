# Monitor 更新审计核实与整改（2026-09-28）

## 1. 范围、基线与结论

本报告对应 `MONITOR_INTERACTION_AUDIT_2026-09-26.md` 第 350 行开始的“实施状态复审（第二轮）”。阅读原报告后，逐项对照实际后端、浏览器执行器、HUD、截图及测试代码，而不是根据报告中的完成度百分比直接修改。

审查开始基线为 `a3aa976844526195756a36beebc2828b165e9c33` 的当前工作树，其中原审计报告有未提交更新；实施期间其他 agent 提交了自然语言/UI 契约修复。最终合并与验证基线为 `a0aaa2cb4467a7762b37620f53749bf700b360c7`。保留这些并行修改，没有覆盖 `brachybot-ui-api.js`、`brachybot-chat-todo.js` 或 agent 执行层的新代码。

结论：第二轮所述的 HUD 展示、工作流引导、空间间距标注、单对象定位和累积视角缺口属实；“约 50%/55% 完成”属于产品评价，不能作为可验证的软件指标。保留既有生命期与取证机制，在同一套已提交证据和执行器上扩展交互，而不建立第二套规划状态。

## 2. 逐项核实及处理

| 原报告项 | 核实与整改 |
|---|---|
| 1. Chat-as-Dashboard | HUD 确实缺评分、差值箭头、聚合待办与未查看截图提示。增加四指标卡、可比差值、V100 测量条、器官 Dmax 展开区和证据入口；指标只能来自当前规划版本的有效结果。 |
| 2. 空间反馈 | 原来只有框线、返回箭头，没有间距测量线。安全校验现在返回最近轴线点，HUD 定位时画测量线/标签；点击对象 ID 可单独定位，点击“查看间距”定位对应对象对。新发/加重重叠使用稳定红色描边，不采用持续闪烁。 |
| 3. 纯文本/严重度 | 原结构化反馈已存在，不重写。增加几何 `blocking`，仅由已测得的新发/加重物理重叠触发；不把默认临床阈值或未复算剂量判为临床不通过。 |
| 4. 工作流 | 原徽章缺少优先步骤及建议。改为有序清单，突出运行中或首先需要核对的未核实/过期/失败阶段，并展示相应下一步。勾号表示有可用数据，不表示医师批准或用户已完成复核。 |
| 5. 证据链 | 有界重试、后台补拍、版本隔离本来就存在，报告对此判断基本属实。沿用现有机制，增加成功截图“未查看”标记，跳转到准确聊天记录后才置为已查看。不通过重复截图补造证据。 |
| 6. 多通道 | 复位 token 确实仍会出现在新反馈正文中，已去除，改为指向本次编辑卡片的直接按钮。旧 token 解析与无结构化卡片时的回退按钮保留兼容，仍进入同一授权执行器，不直接删除导致旧会话不能复位。 |
| 7. 自动剂量 | 默认关闭是事实，但属于明确的性能/操作授权选择，不是失效。保留 opt-in 的防抖、连续编辑合并、拖动与忙时避让；不默认每次拖拽发起昂贵计算。 |
| 8. LLM 解释 | 现有按需解释入口属实。保留一次明确请求的有据解释；不默认每次编辑调用模型，不凭标量评分生成“剂量最优方向”。自动个性化临床教练仍未实现，不能宣称完成。 |
| 9. 生命周期 | stop_error 恢复与 run_mismatch 隔离已有实现，本轮不替换，回归原有结束/重试/新 run 所有权保护。 |
| 10. 累积视角 | 缺少图形趋势、时间线接入属实。增加 V100/D90/有效评分趋势与本轮事件统计，接入精简 timeline。不同计划/解剖/配置基线不连线；“编辑事件数”不冒充独立拖拽次数。 |

## 3. 空间证据的科学含义

1. `_segment_segment_closest_points` 返回有限线段的最近点；`_segment_segment_distance` 用同一对点计算距离。处理平行、相交、端点和退化点段，不更换原校验的物理阈值。
2. 粒子证据同时提供最近轴线点、轴线距离及安全模型定义的有符号表面间隙。标签明确区分轴线距离与表面间隙，不把中心距离错误地命名为表面间隙。
3. 针道证据提供最近轴线点、距离和是否按当前针径发生物理重叠。标签不声称已定位到解剖组织接触点。
4. 只有对象引用可核实、两对象均可见、病例/规划/版本/几何匹配且不处于拖动、报告取证或其他截图占用时才能定位。
5. 画线前验证患者世界坐标、有限三维坐标以及点距与证据数值一致；缺少证据时只保留已有文字，不生成假测量线。
6. 线、框和标签是临时叠加对象，不改粒子或针道材质、透明度、可见性、几何或 Data Tree。清除定位恢复相机；连续定位先恢复上次原始相机，再开启新事务。
7. 距离标签随当前投影和窗口尺寸适配，避免固定毫米尺寸在粒子近景中遮住整个对象。叠加释放纹理、材质、几何，不影响共享 ArrowHelper 资源。

## 4. HUD 数据与历史的边界

- 评分缺失显示“—”，不复用旧版本分数、不把评分上升视为整体临床改善。
- 箭头仅显示已有有效前后对比；V100 条仅是测量值，不着色为“临床合格”。
- 当前器官展示至多五个有效、有限的最高 Dmax 记录；完整器官统计仍由既有 Analysis/查询接口提供。
- 覆盖距离仅使用病例已保存且有效的 `plan_config.DVH_rate`，没有显式配置就不显示目标；不补软件默认值当临床标准。
- 当前 HUD 的数据受病例、run、planning ID、planning version 与拖动状态保护。历史趋势明确是当时记录，不作为当前剂量结果。
- 趋势连续性键包含计划、解剖和剂量配置。缺少解剖基线或兼容键时不连线；切换基线时可独立画该次合法前后线段，不能将不同基线连接成一次编辑改善。
- 时间线显示本轮总事件数量及最近 40 条事件。旧记录超出保留范围时告知；编辑计数标为“编辑事件”，不会把关联粒子重投影或每个采样点计为用户独立拖拽。
- 未查看截图、准备中截图、当前可执行编辑决策分别计数。跳到对应消息才清除未查看提示；不是仅凭截图任务建立就宣布有图。

## 5. 接口及耗时控制

新增的是既有 `/api/training/timeline` 的 `compact=1` 投影，不新增外部依赖或工具名称。原完整导出行为不变。

- 精简响应上限 80 个事件，HUD 请求 40；只读本病例桥接记录，不 hydrate Agent、CT 或整份病例，不调用模型/剂量/几何 QA。
- 必须匹配监测 run；不匹配返回 409，非法 limit 返回 400。
- 不回传原始场景数组、逆操作几何或复位 token，仅提供事件元数据及已提交证据里的小型剂量样本。
- HUD 与现有 overview 并行读取，共用 5 秒取消、序列和 owner fence；250 ms 防抖，不逐对象请求，不逐事件调用 LLM。
- 独立读取失败不阻断另一读取、手工编辑或停止监测。

## 6. 改动节点

生产代码：

- `web/server_support.py`：有限线段最近点与粒子间距见证。
- `web/monitor_changes.py`：针道见证、blocking、评分/器官/目标投影、趋势基线键、精简 timeline、用户反馈文案。
- `web/routes/planning_routes.py`：只读 compact timeline 分支，保留并行 agent 的 UI 状态版本化改动。
- `web/app/static/js/brachybot-monitor-interaction.js`：对子对象定位引用授权、证据已查看标记。
- `web/app/static/js/brachybot-monitor-dashboard.js`：测量叠加、趋势、清单、指标和待办。
- `web/app/static/css/brachybot-monitor-dashboard.css`：响应式指标网格、层级/严重度、趋势/清单样式。
- `web/app/index.html`：仅更新本轮 Monitor 静态资产版本，保留 chat-todo v73 和 ui-api v122。

新增风险覆盖放在既有 `tests/test_monitor_dashboard.py` 与 `tests/monitor-dashboard-browser.test.cjs`，未放宽旧守卫、未清理无关文件、未修改公共发行部署。

## 7. 验证与未验证范围

验证基线：最新源码隔离副本及应用修复后的远端工作树，测试均使用隔离/合成夹具，不使用真实病例进行测试。

- Python 隔离副本相关回归 **253 passed**；加入 `test_workspace_frontend.py` 后，远端实际工作树最终回归 **405 passed**：Monitor HUD、编辑证据、生命周期、training 审计、手工粒子事务、针道间距、障碍安全、Viewer 几何、manual 分步显示、前端资源，以及并行修复的 UI state/授权/参数绑定/步骤身份契约。
- 11 个 Node/浏览器脚本通过：dashboard-state、checkpoint-cards、dashboard-browser、coaching-browser、capture、edit-interaction、advice-ownership、recovery-state、stop-recovery、intent-routing、stop-presentation。
- 真实 Chrome headless WebGL + 合成对象：按钮直接执行、对象/对象对定位、精确测量标签、标签近景适配、不改色、相机恢复、跨病例/计划/拖动隔离、未查看截图和趋势断线。
- 已有的 SWIG 与 `datetime.utcnow` 弃用警告未在本轮扩大修改。
- 未声称全仓库全绿；未进行真实病例 GPU 重算、真实医师操作、外部临床阈值有效性或截图全流程网络联调。上述浏览器是实际渲染引擎上的合成夹具，不是患者生产截图。

## 8. 发布记录

已完成：

- 对九个已有目标文件逐个校验 Git 内容哈希与合并基线一致，确认没有并行未提交修改后才应用改动包；不是整仓覆盖。
- 原版备份位于 `/tmp/brachybot-monitor-originals.JbijOA/originals.tar`。这是临时恢复备份，不替代长期 Git 历史；本轮没有创建提交。
- `git diff --check`、Python AST 与两个修改后 JS 的 Node 语法检查通过。
- 重启前只读检查持久病例运行状态：running 为 0。随后按既有测试后发布约定重启 LAN 8080；独立 public-release 未操作。
- 8080 新监听 PID `3564682`，cwd 为 `/home/lht/snap/brachyplan/BrachyBot`。`/api/healthz` HTTP 200、`ok=true`，返回同一 PID；启动日志显示 Flask 已启动。
- 三个 Monitor 静态资源 HTTP 200，响应字节哈希与当前工作树一致；首页实际引用 CSS v2、interaction v3、dashboard v2，并保留 ui-api v122。
- 原审计报告保持原样。本文件记录核实与整改，避免将主观完成度改写成已验证事实。浏览器刷新后才能载入新脚本；旧页面的内存状态不会因后端重启自动更换。

---

# 独立复核（第三方验证轮）

**触发**：核实上述"实施状态复审"所列整改是否已解决、是否正确。
**方法**：不采信本文件自述，逐条读实际代码并独立算例/复跑测试。复核基线为本文件所述的
`a0aaa2cb4` 工作树（含未提交的 9 文件改动，与 §8"本轮没有创建提交"一致）。
**结论**：§2 的 10 项整改逐条复核，另核 §3 空间证据与 §7/§8 发布声明：
- **9 行核对全部属实且实现正确**（§A，覆盖原第 1/2/4/5/6/10 项与发布项）；
- **1 项不正确**（原第 3 项的 blocking 几何判据在端点场景假阳性，§B）；
- **3 项声明无法在本环境核实**（浏览器验收、测试计数、部分 Node 调用方式，§C）；
- 原第 7/8/9 项（自动剂量 opt-in、LLM 按需、生命周期）为**有意设计保留**而非缺陷，
  声明与代码一致，不计入"未达标"。

## A. 复核通过的项（9 行核对）

| 项 | 复核方式与证据 | 判定 |
|---|---|---|
| §3.1 线段最近点算法 | 我独立实现暴力采样参照（双参数稠密采样），对 `_segment_segment_closest_points` 三组对照：**17 个结构化算例**（相交/平行/共线相离/共线重叠/反平行/斜 3D 穿越/斜 3D 偏移/T 接/点段/点点/近退化/L 角/端点-端点）+ **300 随机线段对** + **120 端点密集对**。最大偏差 1.1e-3 / 4.1e-3（采样分辨率内）；**witness 落在自身线段外的次数 = 0**；`_segment_segment_distance` 与 witness 距离逐例一致。平行、相交、端点、退化点段均正确，退化分支（`a<=1e-12`、`c<=1e-12`）的投影参数推导正确（`t=e/c`、`s=-d/a`） | ✅ 正确 |
| 轴线距离 vs 中心距离 | 同轴粒子 center=5.0mm、axis=0.5mm；`measurement.value_mm` 取 axis，测试断言 `!= center_distance_mm` | ✅ |
| 标签区分轴线/表面间隙、近景尺寸自适应 | `monitor-dashboard.js:339-357`；`visibleHeight`（正交/透视分支）决定 sprite 尺寸 | ✅ |
| 不改粒子/针道材质 | 叠加层独立 `THREE.Group('monitor-focus')` + `userData.monitorAnnotation`；`clearMonitorFocus`（:286-294）只 dispose 叠加层 geometry/material/map，未触碰 `scene3D.meshes` 的材质 | ✅ |
| §3.4 定位前置门 | `focusMonitorCheckpoint`（:301-312）依次校验：非拖动（`monitorInteractionActive`）、非截图占用、非报告取证、`planning_id` 一致、`after_version` 一致、`geometry_key` 匹配、逐 ref `locatable`、`refs` 全部命中 | ✅ |
| token 从新反馈正文移除 | `monitor_changes.py describe()` 已改为"在本次编辑卡片上选择…"，不再输出 code；`_attachMonitorEditChoices`、`handleMonitorConversation` 的 token 解析按声明保留兼容 | ✅ |
| 未查看截图标记 | `markMonitorEvidenceViewed` + `viewedCaptureEventId !== lastEventId` 判定；跳转到对应 `[data-message-id]` 后才置已查看 | ✅ |
| 清单/sparkline/compact timeline/覆盖目标/评分展示 | `aria-current="step"`、`✓/→/·`、每步 tips、免责声明"数据可用不代表临床通过"；`series_key` 基线不连线；compact 80/40 上限、409/400、无几何数组无 token、monkeypatch 禁止 `_ui_bridge_snapshot` 通过；覆盖目标仅取 `plan_config.DVH_rate`；评分缺失显示 `—` | ✅ |
| 版本/发布/语法 | `index.html` 引用 CSS v2、interaction v3、dashboard v2，保留 ui-api v122、chat-todo v73；PID `3564682` 在跑、`/api/healthz` `ok=true` 同 PID；服务端 `monitor-dashboard.js` md5 与工作树一致；`originals.tar` 含且仅含 9 个目标文件；`git diff --check`、4 个 Python AST、4 个 JS `node --check` 全过；物理阈值 `threshold_mm`/`risk` 公式与 HEAD 逐字相同 | ✅ |

## B. 不正确的一项：`blocking`"物理几何重叠"在端点场景假阳性

### B.1 问题

`surface_clearance_mm = axis_distance − 2·seed_radius`（`web/server_support.py:958`）是**两无限圆柱面的横向间隙**。
只有当最近轴点**落在两线段内部**时，它才等于实体表面间隙。当最近点落在**端点**时，真实实体间隙是
端面间距，可能为正而该式给出负值；`risk='overlap'`（`:959`，判据 `axis_distance < 2R`）随之误判。

本轮把该判据升级为 `severity='blocking'` + `blocking_scope='physical_geometry'`，并渲染横幅
**「需先处理：物理几何重叠」**（`brachybot-monitor-dashboard.js:161`）——这是一个**事实断言**，
在端点构型下不成立。

### B.2 复现（默认 length 4.5mm / radius 0.4mm）

```
同一针道相邻粒子，中心距 5.0mm（端面净空 +0.50mm，实体不接触）
  center_distance_mm = 5.0
  axis_distance_mm   = 0.5
  surface_clearance  = -0.3        <-- 负值，但实体有 0.5mm 净空
  risk               = 'overlap'
  -> severity        = 'blocking'  blocking_scope='physical_geometry'
  -> 横幅            = 「需先处理：物理几何重叠」   <-- 断言不成立
```

步距扫描（同针道 3 枚粒子）：

| 中心距 | 端面净空 | 报 axis | 报"表面间隙" | risk | severity | 实体接触？ |
|---|---|---|---|---|---|---|
| 5.00mm | +0.50mm | 0.5 | −0.3 | overlap | **blocking** | 否 |
| 4.70mm | +0.20mm | 0.2 | −0.6 | overlap | **blocking** | 否 |
| 4.55mm | +0.05mm | 0.05 | −0.75 | overlap | **blocking** | 否 |
| 6.00mm | +1.50mm | — | — | 无报警 | — | 否 |
| 10.00mm | +5.50mm | — | — | 无报警 | — | 否 |

即 4.5–5.0mm 步距（PDR/HDR 常见布源）会**稳定误报 blocking**。随机构型蒙特卡洛中该构型罕见
（近共轴端点相邻），故不能用随机测试证明无害；该误报由构型几何决定，确定性可复现。

### B.3 归因

- 公式与判据是**既有**的（本轮 `git diff` 对 `risk`/`surface_clearance_mm` 仅**新增** `measurement`
  字典，未改公式；阈值与 HEAD 逐字一致，与"不更换原校验的物理阈值"相符）。
- 但本轮把它**升级为 blocking + 事实性断言**。旧文案只称"间距问题"（语义宽，可容纳端点近接），
  新文案断言"物理几何重叠"（语义窄，要求实体相交）。**影响面因此从"提示复核"扩大到"阻断级错误信息"**。
- 报告 §3.2 用"安全模型定义的有符号表面间隙"作了限定；**UI 横幅没有这个限定**。
- §3.2"标签明确区分轴线距离与表面间隙"——区分两个数字属实；但第二个数字在端点场景下
  **并非**表面间隙，命名本身仍不准确。

### B.4 测试覆盖缺口

本轮新增的 7 个用例：
`test_blocking_is_measured_geometry_not_unsupported_clinical_threshold`、
`test_overview_oar_cards_and_configured_target_are_current_only`、
`test_timeline_projection_is_bounded_token_free_and_cannot_attest_a_preview`、
`test_dose_trends_change_series_when_anatomy_or_prescription_changes`、
`test_spacing_witness_matches_finite_segment_check`（参数化 5 例）、
`test_seed_annotation_measures_axes_not_centroid_distance`、
`test_compact_timeline_checks_run_and_never_copies_full_case_bridge`。

其中 `test_spacing_witness_matches_finite_segment_check` 的 5 例覆盖了共线/点段/端点，
**算法层无缺口**；`test_seed_annotation_measures_axes_not_centroid_distance` 用
`z=0` 与 `z=5` 的同轴粒子，**只断言 axis≠center**，未断言 `risk`/`severity` 语义；
`test_blocking_…` 用合成 `risk:'overlap'` 直接喂 `interaction()`，**未经过
`_seed_interference_report` 的几何判定**。故 B.2 的端点假阳性不在任何用例的断言面内。

### B.5 建议判据（未实施，待定）

只在**最近点对同时落在两线段内部**（参数 `s,t ∈ (ε, 1−ε)`）时使用 `axis_distance < 2R` 判
实体重叠；端点占优时降级为 `warning`，文案改称"轴向端面间隙 ≈ X mm（安全模型的横向口径为
Y mm）"，且 `blocking_scope` 相应收窄为 `physical_geometry_interior`。需补同针道 5.0mm 步距回归
用例（期望 **不** blocking）。此改动会触碰 `_seed_interference_report` 的 `risk` 语义，
属既有校验口径，宜单独评审后实施。

## C. 无法在本环境核实的声明（3 项）

| # | 报告声明 | 实测 | 判定 |
|---|---|---|---|
| C.1 | §7"11 个 Node/浏览器脚本通过：… dashboard-browser、coaching-browser …"及"真实 Chrome headless WebGL + 合成对象：按钮直接执行、对象/对象对定位、精确测量标签、标签近景适配、不改色、相机恢复、跨病例/计划/拖动隔离、未查看截图和趋势断线" | 仓库与 `/home/lht/.conda/envs/brachytherapy` **均无 `playwright` 模块**，无 `tests/test-runtime/`。`monitor-dashboard-browser.test.cjs`、`monitor-coaching-browser.test.cjs` 在 `require` 阶段即 `Cannot find module 'playwright'` | **无法证实亦无法证伪**。§3 的测量标签/近景适配/不改色等**已在代码层逐条核对为正确**（见 A），但"实际渲染引擎上的合成夹具"运行证据缺失。请补运行环境与日志 |
| C.2 | §7"Python 隔离副本相关回归 **253 passed**…最终回归 **405 passed**" | 实测可复现计数：`test_monitor_dashboard + test_monitor_edit_evidence + test_training_monitor_audit = 62 collected`；上述三者 + `test_surgical_guide` + `test_workspace_frontend` = **273 passed**；`-k "monitor or training or manual or guide or needle or seed or dashboard or spacing or obstacle"` = **319 collected**；全量 `--ignore=test_release_access` = **1982 passed / 8 skipped / 2 failed** | **无法复现 253/405**。报告未列出文件集，无法证伪。请补文件清单 |
| C.3 | §7 将 `stop-recovery`、`intent-routing`、`stop-presentation` 列为"通过" | 三个脚本**需显式 argv**（分别传 `brachybot-3d-manual.js`、`brachybot-chat-todo.js`、`brachybot-ui-api.js`）；裸跑报错。给对参数后：三者均通过 | **成立但调用方式未记**。建议在报告写明命令行 |

C.1 中可核实的 9/11 脚本实测结果（可复现）：

| 脚本 | 结果 |
|---|---|
| monitor-dashboard-state / checkpoint-cards / capture / edit-interaction / advice-ownership / recovery-state | 通过（裸跑） |
| monitor-stop-recovery / monitor-intent-routing / monitor-stop-presentation | 通过（需 argv，见 C.3） |
| monitor-dashboard-browser / monitor-coaching-browser | **阻断**：缺 `playwright` |

## D. 措辞余量（次要）

`web/app/static/js/brachybot-ui-api.js:2328` 仍保留"可使用监测提示中的复位 token"字样
（不含 code 本身，仅指路）。§2 第 6 项称"复位 token 确实仍会出现在新反馈正文中，已去除"
——就 `describe()` 而言属实，但该残留措辞仍引导用户去寻找 token，与"交互通道收敛"方向相悖。

## E. 复核结论

1. **空间几何原语 `_segment_segment_closest_points` 正确**（独立暴力采样对照 400+ 用例，
   witness 全部落位），报告 §3.1 的科学表述成立。
2. **B 节的 blocking 假阳性是本轮引入的真实语义错误**（既有近似 + 新增断言级升级），对
   4.5–5.0mm 常见步距会稳定误报"物理几何重叠"，**建议在收尾前修正或收窄文案**。
3. **C 节三项需补充证据**后方可计入"已验收"；在此之前不应把 §7 的浏览器/计数表述
   当作已完成的真实端到端验收。
4. 其余 **9 行核对全部属实、实现正确**，与既有生命期/取证机制无冲突；原第 7/8/9 项为
   有意设计保留（自动剂量 opt-in、LLM 按需、生命周期不替换），声明与代码一致。

## F. 第三方复核后的整改与补证（2026-09-28）

本节记录在上述独立复核之后的实际修复。§B–§E 是修复前证据，不应再把其中“待实施”“缺 Playwright”当作此轮最终状态。工作树中同时存在其他 agent 对自然语言执行层的修改；本轮只改 Monitor 相关文件，未覆盖那些并行修改。

### F.1 §B 的端点假重叠已修复

`web/server_support.py` 新增 `_finite_cylinder_spacing`，明确把**轴线距离**与**有限实体表面间隙**分开：

- 轴线平行时，依据径向圆盘距离与两个有限轴向区间计算带符号的实体间隙。相邻粒子中心距 5.00 mm、长度 4.50 mm 时，端面间隙是 **+0.50 mm**，达到当前最小间隙，不再产生冲突；4.70/4.55 mm 分别是 **+0.20/+0.05 mm**，属于间距不足但不是实体重叠；4.40 mm 时为 **−0.10 mm**，才确认实体重叠。
- 非平行线段最近轴点都在内部且距离小于直径时，可以确认侧壁重叠。端点占优时，轴距减直径只是**模型间隙下界**，不能证明实体碰撞；该类情况保留保守间距提示，`physical_overlap=None`，不升为“物理几何重叠”阻断级描述。没有将未知构型误报为已经安全。
- 粒子报告保留原 `surface_clearance_mm` 数字字段供旧调用者兼容，同时增加 `clearance_basis` 与 `physical_overlap`；非精确情形的 UI／文本必须使用“轴线模型间隙下界”名称。`overlap_count` 只计已证实重叠，另列 `possible_overlap_count`。针道对的 Monitor 物理重叠提示同样使用实体可证性，不再仅凭端点轴距判定。
- 手工编辑的前后比较在两次均为平行圆柱时改用实体表面间隙。这样从端面刚好接触移动到真正重叠，即使两次轴距都为 0，也仍判作新发／加重问题，保持原有安全阻断。实体碰撞提示和剂量／临床结论仍分开。

`web/monitor_changes.py` 的 blocking 只依据 `physical_overlap is True`；`web/app/static/js/brachybot-monitor-dashboard.js` 的红色描边、标签和卡片文案使用同一证据。`web/app/static/js/brachybot-monitor-interaction.js`、`web/app/static/js/brachybot-3d-manual.js`、`web/monitor_engine.py` 及规划建议的中英文本一并按精确值／下界区分。静态 JS 版本已在 `web/app/index.html` 更新。

**范围边界**：目前非平行端点的精确实体间隙未由这个轻量校验器求解；可能碰撞仍走保守提示和原有人工复核／安全流程。这里没有把未知当作无碰撞，也没有引入隐藏的剂量重算。不能以本修复替代独立几何 QA 或临床确认。

### F.2 §C 的验证补证

- **C.1 已解决环境阻断**：本机 bundled Playwright 运行时及 Chrome 可用。`monitor-dashboard-browser.test.cjs` 和 `monitor-coaching-browser.test.cjs` 已在真实 headless Chrome/WebGL、合成 fixture 上运行并通过。第一项夹具原先把无 `clearance_basis` 的旧数字称为实体表面间隙；补入平行圆柱和已证实重叠证据后通过。仍未做真实患者浏览器网络联调。
- **C.2 保持审慎**：上一轮“405 passed”没有可复现的确切文件清单，仍视为历史记录，**未在本轮重新宣称该数字**。本轮远端运行的明确 8 文件集：`test_monitor_dashboard.py`、`test_manual_seed_transactions.py`、`test_monitor_edit_evidence.py`、`test_training_monitor_audit.py`、`test_monitor_lifecycle_behavior.py`、`test_needle_obstacle_safety.py`、`test_seed_coordinate_contract.py`、`test_workspace_frontend.py`，结果 **316 passed**、17 个既有弃用警告。不是全仓库全绿。
- **C.3 调用参数已核实**：本机11个 Monitor Node／浏览器脚本在修改后的源码上逐个运行通过。`monitor-stop-recovery.test.cjs` 传 `web/app/static/js/brachybot-3d-manual.js`；`monitor-intent-routing.test.cjs` 传 `web/app/static/js/brachybot-chat-todo.js`；`monitor-stop-presentation.test.cjs` 传 `web/app/static/js/brachybot-ui-api.js`。其余脚本按默认路径运行。

### F.3 §D 的文案

`brachybot-ui-api.js` 中“去监测提示找复位 token”的残留句已改为指向对应监测卡片的“恢复编辑前位置”按钮；旧会话 token 解析能力未删除。若卡片／版本已失效，原有执行器的归属和安全验证继续拒绝失效恢复。

### F.4 发布核对

修复前对目标文件 SHA-256 逐一核对，并在 `/tmp/monitor-spacing-originals.hlmbCE/originals.tar` 留有可恢复备份。相关 Python 回归 316 项通过，本机11个 Node／浏览器脚本通过；JS 语法检查和 `git diff --check` 通过。真实病例 GPU 重算、患者截图和临床阈值有效性仍未验证。发布监听进程和静态资源的实际状态以本节后续的运行核对结果为准；不能只凭 HTTP 200 宣称服务已加载新代码。

### F.5 针道的同源误判及当前部署状态（续查）

在 F.1 的粒子修复基础上继续检查 `web/monitor_changes.py`，发现针道对虽已区分 `physical_overlap`，冲突筛选和“加重”比较仍依赖轴线距离。两根平行有限针道的端面相距 1.50 mm、配置直径 1.20 mm／额外净空 1.00 mm 时，实体净空已经满足要求，但旧规则 `axis_distance < diameter + clearance` 会错误列为冲突；两针由端面接触变为穿透时，两次轴距均可为 0，旧比较又会漏报加重。这与 B 节是同一类“无限轴线模型代替有限实体”的问题。

现已让针道的冲突筛选、前后差值和监测文案沿用有限实体的 `clearance_mm` 与 `clearance_basis`；同时保留 `distance_mm`／`minimum_distance_mm` 作为兼容字段。平行轴精确计算实体净空，非平行端点仍只是保守下界，不能称为已证实碰撞。新增回归覆盖 1.50 mm 端面间隙不报警、0.50 mm 端面间隙为非阻断提示、端面接触后穿透判为加重且阻断。

续查时远端七个直接相关测试文件为 **165 passed**。加入 `test_workspace_frontend.py` 的八文件集为 **316 passed / 1 failed**；失败的是 `test_guide_progress_uses_one_clock_and_hides_background_auto_generation` 的旧静态字符串断言，期望回执 `{ dispatched: true, completed: false }`，而并行修改中的 `brachybot-ui-api.js` 已增加 `status: 'dispatched'` 字段。此断言与本次有限圆柱计算和 Monitor 交互无关；没有为了宣称全绿而回退并行 agent 的代码或弱化其守卫。F.2 的“316 passed”对应并行修改前的那次运行，不代表续查后的八文件集结果。`git diff --check` 仍通过。

8080 实际监听 `192.168.1.113:8080`，进程 PID 3564682 于 14:05:13 启动，工作目录是本仓库，`/api/healthz` 和首页均返回 HTTP 200。但该进程早于本节 Python 修改，**不能据此认为运行中的后端已加载新几何代码**。与此同时工作树的 `agent_runtime/` 多个文件正在被另一任务并行改动，尚未连同本修复完成整体验证；为避免重启时加载半成品或打断未核实的病例任务，本轮未重启 8080。后续部署应在并行修改稳定且确认无在途规划／导板任务后，重启并核对新 PID／启动日志／健康端点／实际 Monitor 回执。真实病例浏览器联调与临床几何 QA 仍是未完成验收项。

### F.6 统一两条针道证据路径后的最终回归

F.5 完成后又发现 `web/server_support.py` 的 `_latest_plan_snapshot` 独立使用旧的轴距阈值生成 `needle_geometry.close_pairs`，会继续把同一构型写入阶段监测和最终总结。因此新增 `_needle_interference_report` 作为**同一几何判据的唯一针道入口**：快照建议和 `web/monitor_changes.py` 的编辑前后比较均调用它；`web/monitor_engine.py` 与总结文案区分精确实体表面间隙和保守轴线模型下界。非平行端点的风险仍标为 `possible_intersection`，不能写成已证实的实体相交。保留旧的轴距和中心距阈值字段作兼容证据，但不再以其直接决定端面碰撞。

新增入口测试直接调用 `_latest_plan_snapshot`，验证 1.50 mm 端面间隙不进 `close_pairs`，0.50 mm 间隙只进入 `too_close` 且 `physical_overlap=False`；编辑比较测试验证接触到穿透仍升级为阻断。并行前端改动新增的回执 `status` 字段导致 F.5 记录的旧静态字符串测试失败；仅调整静态守卫以允许附加元数据，仍严格要求 `dispatched: true` 且 `completed: false`，没有修改业务回执行为。最后在远端执行 F.2 所列八文件集，结果 **318 passed、17 条既有弃用警告**；`git diff --check` 通过。这是当前可复现的**定向测试**结果，不代表全仓库或真实患者端到端验收通过。F.5 的 316/1 是中间状态，已被本节 318/0 取代。8080 服务仍未重启，运行时生效状态仍按 F.5 的限制解释。
