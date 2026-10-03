# Monitor 交互持续改进：证据一致性与操作闭环

日期：2026-10-03。审查对象：LAN 工作树 `/home/lht/snap/brachyplan/BrachyBot`，HEAD `7aa6d23086072b593beba069f8c2116d01c3c0f3`，包含审查开始时已有的未提交改动。

## 1. 结论与范围

完整阅读了 `NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`，并对照 `MONITOR_INTERACTION_AUDIT_REMEDIATION_2026-09-28.md` 的后续整改记录。旧审计不是当前故障清单：已有结构化编辑证据、截图事务、稳定对象引用、监测租约和共享复位执行器应保留。

本轮核实并修复的是现有链路中的**证据被错误当成当前事实、反馈事实在不同界面遗漏、截图结果与操作状态不闭环，以及连续交互重复刷新**。不是另建一个 Monitor 引擎，也不是为几个特定句子增加白名单。

代码链路：权威编辑端点 → `monitor_changes.capture/compare/checkpoint` → `receiveMonitorCheckpoint` → 同一编辑卡片与工作台 → 截图结果回写／`performMonitorEditDecision` → 状态同步。

没有修改临床算法、粒子或针道真实几何，没有调用在线模型或 GPU 规划，没有变更独立 public-release，也没有清理 benchmark 或其他任务的工作树。

## 2. 核实的问题与本轮处理

| 问题 | 本质原因 | 处理及用户可见变化 |
|---|---|---|
| 跨规划或无解剖基线仍可能显示“可比较”差值 | `dose_comparison` 只比较配置与 anatomy_key，缺少同一规划身份检查；两边缺失可以相等 | 规划身份必须明确且一致，解剖基线必须存在；无效对比没有 delta，并返回具体 reason。趋势序列也不为缺失身份建立连接键 |
| 结构化 stale/running/failed 状态未阻止旧剂量成为当前事实 | capture 只识别字符串状态，overview 又有自己的规范化 | 共用 `_artifact_state`，同时接受旧字符串和 `{status:...}`；outdated 统一为 stale；运行中／失败／过期剂量不可当作当前剂量 |
| 当前剂量已算好，却仍提示再次重算来获得前后对比 | “当前剂量可用”与“编辑前基线有效”被合并描述 | 明确“缺少前值”和“缺少本次重算”两类原因；前值丢失时不声称再算一次就能补造基线 |
| 针道表面间隙数值被标成轴线距离 | 卡片、工作台各自按对象种类猜测数值名称 | 共享 `monitorConflictText`；精确有限实体间隙、轴线模型下界、轴线距离分别显示；缺失值显示未核实而非 NaN/0 |
| 已有细节没有进入新版卡片 | 简化渲染遗漏关联粒子数量、原有／已消除冲突，以及针道端点返回位移 | 卡片显示这些已有证据；return_movements 精确绑定对象与端点；依赖粒子不计为独立拖动 |
| 间距告警不说明还差多少 | 最小间隙要求未随 seed pair 证据传下去 | 保留原安全检查的 minimum_clearance_mm；精确间隙可显示配置要求和差额。明确差额不是移动处方，不套用临床阈值 |
| 旋转／归属改变是真实编辑，却没有定位截图 | 截图对象筛选排除了所有 reoriented | 为实际重定向对象请求定位证据；仍排除已删除对象和仅由保存规范化产生的伪“编辑” |
| 工作台没有截图失败原因／重试入口；自动重试等待阶段也没有手动入口 | 图像状态主要存在于聊天卡片；deferred 被遗漏 | 工作台显示准备／暂缓／完成／部分完成／失败／无定位对象及具体原因；同一卡片共享重试执行器，等待重试时也可主动重试 |
| 部分截图被写成全部已交付；success 占位被当作图像完成 | 卡片只看 success 布尔值 | 必须返回非空附件数组才能记录 ready；有 omittedTargetRefs 或部分错误则为 partial，并显示未核验对象；旧回调不能完成新事件 |
| 剂量补充后，看不出卡片下旧图与新截图的区别 | 一个编辑卡片不断演进，但未保留交付事件元信息 | 保存已交付检查点的 event/version/view 元信息；新截图待完成时明确下方旧图不是本次结果。实际附件仍由原交付／持久化链路保留，不重复附图 |
| 已保留／已复位的决定在工作台消失 | chat 有 decision 字段，工作台不渲染；状态刷新没有统一发布 | 显示真实决定结果；撤销 token 被消费后取消对应操作；一次 publish 同步卡片与 HUD |
| 相同规划版本下，本地几何已不匹配，HUD 仍可借 overview 显示旧值 | 工作台只看 id/version，且备用 overview 绕过几何检查 | 同版本的卡片几何不匹配时，同时阻止卡片和 overview 的当前指标／解释入口；不能通过 fallback 绕过 fence |
| 连续编辑越来越多地重绘旧卡，阅读滚动位置被打断 | 每次提交都重画已 superseded 的所有记录，再重复 publish | 仅重画刚被替代的卡片；批量发布，取消被淘汰卡片的重试计时器；HUD 刷新保留 scrollTop；告警标题与正文分行 |

## 3. 科学和交互边界

- 几何事实、剂量对比、临床批准是三类信息。分数上升、间隙改善或截图成功不等于临床通过。
- “返回编辑前位置”只来自已提交 before/after 几何；患者坐标向量不是屏幕左右，也不是剂量最优方向。复位仍经过现有端点安全校验。
- 精确实体间隙与保守轴线下界不能互换；只有精确间隙才显示确定的 gap shortfall。该差额不是“按此向量拖动即可安全”的建议。
- Auto Compare 仍默认关闭，明确开启才会合并连续编辑后重算；没有新增逐拖动模型调用，也没有隐藏昂贵计算。
- 截图仍使用现有串行、最小临时调整、恢复与版本隔离链路。旧版本不能拿新几何补拍，部分对象无法核验必须明确说明。
- 本轮没有声称消除了所有网络阻塞、所有自然语言歧义或所有临床优化问题。

## 4. 测试与证据

测试在隔离源码目录 `/tmp/brachybot-monitor-ux-20261003.uTU2vX` 执行，使用项目 Python 环境；没有使用患者数据。首次建立隔离目录时缺少 prompt 文件和已有未跟踪模块，补齐源码依赖后取得基线，这些收集错误不是产品回归。

### Python

原 8 文件基线：**321 passed**。加入本轮 19 个风险用例后的 9 文件集：**340 passed**。扩大到截图、UI bridge、手动分步、导板显示、工作区恢复等 16 文件：**474 passed, 6 skipped, 17 warnings**。

6 个 skip 全部来自 `test_workspace_transition_runtime.py`：远端 PATH 没有 Node.js。它们不是已通过，不能由其他浏览器测试直接替代。17 条警告为已有 SWIG / datetime.utcnow 弃用警告。没有修改 latency 参考哈希或放宽安全判分。

可复跑的扩大集合：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -rs -p no:cacheprovider \
  tests/test_monitor_ux_contract.py tests/test_monitor_dashboard.py \
  tests/test_monitor_edit_evidence.py tests/test_monitor_lifecycle_behavior.py \
  tests/test_training_monitor_audit.py tests/test_manual_seed_transactions.py \
  tests/test_needle_obstacle_safety.py tests/test_seed_coordinate_contract.py \
  tests/test_workspace_frontend.py tests/test_screenshot_trace_integration.py \
  tests/test_ui_bridge_sidecar.py tests/test_manual_step_visualization.py \
  tests/test_guide_visibility_contract.py tests/test_workspace_lease_ux.py \
  tests/test_workspace_transition_runtime.py tests/test_workspace_latency_contract.py
```

既有正向 fixture 两处补全了原本隐含的有效规划／解剖身份；既有附件正向测试补齐附件数组。新增负向用例验证缺失身份、跨规划、无解剖、无附件仍不能通过，不是削弱契约。

### Node 与真实浏览器

12 个 Monitor 脚本通过：capture、checkpoint-cards、dashboard-state、edit-interaction、advice-ownership、recovery-state、stop-recovery、intent-routing、stop-presentation、dashboard-browser、coaching-browser，以及新增 ux-contract。

三个旧脚本需要参数：

```text
node tests/monitor-stop-recovery.test.cjs web/app/static/js/brachybot-3d-manual.js
node tests/monitor-intent-routing.test.cjs web/app/static/js/brachybot-chat-todo.js
node tests/monitor-stop-presentation.test.cjs web/app/static/js/brachybot-ui-api.js
```

其余脚本默认读取当前工作树。browser 脚本在 Windows 本机通过 bundled Playwright + Chrome + WebGL 运行，设置 NODE_PATH 指向已有运行库，CHROME_PATH 指向 Chrome；没有安装新生产依赖。

浏览器验证覆盖真实 DOM 按钮、失败原因／重试、部分图像状态、决定结果、滚动保持、等版本几何 mismatch、3D 描边／测量标签、相机与配色恢复。使用 synthetic fixture 和网络 stub，**不是患者病例端到端验收**。

连续编辑隔离用例：80 次提交和相应截图失败状态更新，chat upsert **239 次**，常驻卡片上限 **40**，只保留最新 **1** 个重试计时器。它说明旧卡重复重绘被消除，不是生产 DOM/GPU p95 延迟测量。

## 5. 交付与生效

修改点集中在 `web/monitor_changes.py`、两份 Monitor JS、Monitor CSS 和对应测试；`index.html` 只更新 Monitor 三个静态资源版本，保留其他任务已存在的资源版本／UI 改动。

发布采用逐文件原始 SHA-256 核对、git apply --check、原始字节备份及发布后 SHA-256 核对。原审计文档没有被改写成“所有问题已完成”。新测试、报告和补丁均可独立复核。

**本轮没有重启 8080。** 审查时 LAN listener 是 `192.168.1.113:8080`，PID 596570，启动时间 2026-10-02 06:35:05，命令使用该仓库的 web/server.py。运行中的 Python 不能被当作已经载入本轮后端修改；前端静态资源更新后需刷新页面，后端变化需在安排重启后才能生效。当前工作树还包含其他任务的大量改动，不应无条件重启并把全部未验证代码加载到生产进程。

## 6. 下一轮仍需解决／验收

1. **真实用户病例闭环**：提交粒子／针道编辑 → 定位图实际交付并刷新恢复 → 保留／复位 → 有效重算 → 对比。仍需在线验证网格重建、上传与附件持久化时序。
2. **面向用户的建议优先级**：本轮使具体事实可见，但未构建独立验证的剂量敏感度／局部优化器；不能把间距差额直接变成临床拖动建议。
3. **报告、截图与手动编辑的并发**：原事务机制保留，但长网络阻塞、切后台、用户同时改变相机／显示、断线恢复仍需要真实延迟注入验收。
4. **自然语言与能力对等**：旧审计中 F04/F06/F08/F09/F11/F13/F14/F15 的全产品范围不由本轮 Monitor 修复覆盖。无需另问授权的只读查询、复杂复合请求、稳定对象目录仍应按共同能力契约持续验证。
5. **用户体验测量**：下一步记录真实首次反馈时间、图像交付率及 p50/p95、决定点击到持久化时间、拒绝原因分布，而不是仅凭“单测绿色”宣布体验优秀。
