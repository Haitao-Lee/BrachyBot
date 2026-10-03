# 可执行接口与判分契约

本扩展评测“读懂需求、选择正确效果、基于当前状态调度、正确交付并回答”，不评测合成计算的临床准确度。临床剂量/分割/导板物理真实性仍使用原有专门轨道，不由这里的 synthetic job 冒充。

## 1. 文件隔离

`compiled/tasks` 是现有 task schema 兼容的评测端包装；`compiled/contracts`、`events`、`review_cards` 是私有评测材料。**都不要整份发送给 SUT。** Runner 只发送 start 可观察状态、逐次用户消息、环境更新以及工具返回。故障脚本在首条请求前装载，在实际 barrier 命中时触发，不是等回答后再注入。

进程运行目录是独立临时目录，默认仅继承基础系统环境。`collector.key` 不传给 worker；状态/审计/附件/响应的采集在评测进程完成，签名用于防止把 SUT 自填的 observation 当真实证据。此隔离是 API/可信进程边界，**不是恶意 Python 的 OS 沙箱**。不可信第三方请放进另一个容器/账号，不能挂载 gold、评测目录、生产病例或 collector key。Hash/HMAC 不替代独立采集和操作系统权限。

## 2. Worker：UTF-8 JSONL

每行最多 64 KiB。stdout 只能用于协议；诊断走 stderr。可见工具集合由 start 消息给出，不要求模型记住 BrachyBot 的特定工具名。SUT adapter 将自己的等价工具路径映射为相同语义效果。

评测端发送：

```json
{"type":"start","execution_id":"opaque-id","profile":"decision_sandbox","operations":["read","set","submit","poll","advance","capture"],"state":{}}
```

worker 回 `{"type":"ready"}`。随后接收逐条 `user`（含 `turn_id/text/language`）或无新增用户命令的 Monitor `environment_update`。

调用/结果：

```json
{"type":"call","id":"call-1","operation":"set","arguments":{"path":"objects.guide-A.visible","value":true,"op_id":"show-once"}}
{"type":"result","id":"call-1","result":{"status":"completed","value":true}}
```

实际回复和实际交付：

```json
{"type":"response","turn_id":1,"stage":"final","final":true,"outcome":"COMPLETED","text":"已显示现有导板。","attachments":[],"downloads":[]}
{"type":"yield"}
```

**capture/export 创建文件不算交付。** 截图可能已生成但没有进入聊天；必须在 response 的 `attachments` 中引用已解码、同病例同版本的附件 ID。PDF 必须在 `downloads` 中引用实际生成的 ID。独立 collector 才记录 delivered。图像不能靠布尔值 `screenshot_success` 代替，第二目标也不能覆盖第一目标 ID。

`yield` 允许在排队/运行阶段接收用户取消或改口，不隐含完成；可先返回 `final:false,stage:progress`。晚到的回复必须指定原 `turn_id`，不能结束新请求。最后评测端发 `finish`，worker 处理完后 `yield`；不允许无限等待。每个真正用户输入都保留实际回复与终态；恢复的历史由 fixture 提供，不作为本轮 SUT 输出。

## 3. 语义工具

| operation | 参数/含义 |
|---|---|
| `read` | 可选 `path`；当前权威状态，不把缺测替换成零 |
| `read_artifact` | `id,offset?`；实际截图 PNG base64 或 PDF 有界分块，不返回私有 reference mask |
| `capabilities` | 读取已支持动作；不授予写权限 |
| `set` | `path,value,op_id?`；对象 visible/opacity/color 或独立 2D zoom/pan |
| `submit` | `kind`：dose/quality/guide/report/report_figures/segmentation/trajectory_init/manual_next；显式分割另需 `model` |
| `poll` | 读取真实 job、monitor、附件状态；accepted/running 不等于 completed |
| `advance` | 一个确定性 tick；推进可执行作业/解码，保留 hold/cancel/version barrier；不重试无限循环 |
| `cancel` | `kind`；仅取消当前所有者未提交作业，不删除原产物 |
| `restore` | `token`；在 precommit 时核验病例/计划/当前版本，单编辑恢复并产生新版本 |
| `cancel_preview` | 取消未提交预览，不把历史编辑当刚才移动 |
| `capture` | `target,views?,hide?,camera?,annotation_anchor?,role?`；实际 raster/mask、不可变附件、finally 恢复 |
| `monitor_stop` | `run_id`；停止指定 run，ACK 丢失也保留服务端真实状态 |
| `refresh` | 刷新显示镜像，不重算临床内容 |
| `export` | `kind=report`；真实 PDF 文件，仍需显式下载交付 |
| `language` | `value=zh/en`；正文和图注文本、保存/恢复结果一致，不改剂量 |
| `provider` | 标准化 provider 调用故障入口；适配器可将它接入实际 provider/tool-argument 边界 |

所有作业结果都是明确的合成测量/产物。模拟器不以 gold 阻止错误调用，错误动作即使被固有安全边界拒绝仍记录 attempted；判分器判断是否越权。等价实现可更快、不调用 provider、不做不必要读取，只要达到允许的结果并交付诚实回答。未触发的故障分支要单独记录，不能计为已测试的恢复能力。

## 4. 判分

复用 `tools.run_task.evaluate`、`EvaluatorContext`、`OracleResult` 和三态 gate，新增 checker `real_user_request`。机器部分检查范围、真实效果、当前执行的产物、版本、顺序/完成屏障、附件 mask/标注、PDF 解析和交付。初始已有产物、双边 no-op、空 observation 都不能替代本轮完成。

回复语义/读者体验由独立人审或经过校准的 judge 评估，不能凭一个中文字符、几个关键词、工具名或 SUT 自填 booleans 通过。每项评审须有场景/执行/turn 身份、实际回复 hash、引用字符范围、理由、真正的 bool 结论和评审身份。多轮中间回复有自己的 `turn-fulfillment` 标准；完整场景标准在最终回复结合全部过程核验。review form 的 `passed=null` 不是默认通过。

明确失败优先于另一项缺证据；缺 parser/采集器/独立审查为 Insufficient evidence，不伪装成功。组件 witness 的意义只是测 checker，不是测 agent，更不能校准语义 judge。

当前所有 82 题是 `development_only / power_role=exploratory / confirmatory_eligible=false`。没有独立专家复核和冻结，不进入主实验分母，不生成 sealed split。共享 fixture/故障来源必须考虑聚类，82 题不等于 82 独立患者；不因为题号不同就主张独立样本。

## 5. 可比性

默认 `decision_sandbox` 支持 alpha/beta 的任务决策比较。`tree_state/render_state/saved_state` 是合成软件的显示/持久化读数，**不是生产 BrachyBot 的 DOM**。报告里的渲染可读性、语言体验等依然需要独立审查。

产品级 gamma 需接入实际浏览器 SSE/DOM、Viewer pixels/depth、聊天附件、download、case/session/version 和持久化的独立采集器；不能拿 SUT trace 自称已捕获替代。当前 manifest 明确 `real_browser_observed=false`。原生产功能是否正确，不由本扩展组件自测 green 推出。

## 6. 构建与将来的运行

在 `benchmarks/brachybench` 下：

```bash
python -m extensions.real_user_requests_v1.prepare
python -m extensions.real_user_requests_v1.prepare --check
python -m extensions.real_user_requests_v1.runner
python -m pytest -q extensions/real_user_requests_v1/
```

以上不运行 SUT。将来只有明确指定 `--execute --case --worker --out` 才执行，输出 authenticated recording，**不自动生成性能分数**。例如：

```bash
python -m extensions.real_user_requests_v1.runner --execute \
  --case RUR-02-001 --worker '/absolute/path/to/trusted-adapter' \
  --out /absolute/path/to/new-recording-directory
```

独立审查步骤（不启动 SUT）：

```bash
python -m extensions.real_user_requests_v1.review_cli form --case RUR-02-001 \
  --recording /path/recording.json --collector-key /private/path/collector.key \
  --sut-id registered-system --out /path/new-review-form.json
```

完成真实独立人审后，`review_cli evaluate` 接受相同 recording/key、`--reviews` 和可核实的 `--source-sha256`，复用原有 gate。默认仍是开发诊断，不擅自升格 confirmatory。所有 out 目录和人审/result 文件都拒绝覆盖，旧 tasks/results/MANIFEST 不动。
