# 自然语言/UI 对等性审计附件

对应主报告：`../../NATURAL_LANGUAGE_UI_PARITY_AUDIT_2026-09-28.md`。

基线：`a3aa976844526195756a36beebc2828b165e9c33`。所有结果是 2026-09-28 审计时观察，不代表修复后行为。

## 内容与限制

| 文件 | 用途 |
|---|---|
| source_manifest.csv | 全部505个被扫描代码文件的路径、行数、SHA-256 |
| static_controls.csv | index.html中的264个静态交互候选，含事件属性 |
| control_handler_index.csv | 上述控件的内联调用及JS函数候选位置；不是完整调用图 |
| event_sites.csv | 568个JS/HTML事件注册/内联属性所在行，包含测试/库中匹配项 |
| production_routes.csv | web/中的122个Flask route声明 |
| capability_registry.csv/json | UI工具全部111个注册target及完整JSON schema |
| capability_source_index.csv | 每个target的注册行和前端同名字符串引用，供定位dispatcher；引用不是执行证明 |
| test_inventory.csv | 1649个Python test函数声明，不表示已执行 |
| inventory_summary.json | 计数与基线 |
| audit_probes.py/json | 实际纯函数在合成上下文中的语义、授权、依赖和coverage结果 |
| audit_browser_probes.cjs/json | 实际生产JS函数抽取到Node VM，使用惰性DOM替身测试；不访问服务器 |
| audit_inventory.py | AST/HTML/事件扫描脚本，输入为tracked_sources.txt |
| tracked_sources.txt | 审计时源文件路径基线；仅匹配代码扩展名的条目被使用 |
| validation_record.json | 实际测试范围、通过和环境阻断项 |

CSV 使用 UTF-8 BOM，方便中文表格软件读取；JSON 使用 UTF-8。控制台中文编码异常不改变 JSON 中保存的原始中文。

**本附件没有真实患者数据、截图或模型调用结果。** 合成 guide catalog 和258对象fixture只是可复现的边界输入。动态DOM、canvas内部交互、资源恢复和GPU计算需要真实端到端补验。

静态扫描不覆盖全部动态行为。`capability_source_index.csv` 无字面引用不等于无实现，有引用也不等于可执行；必须读取实际分派和后置条件。

## 复现探针

建议将脚本复制到临时审计目录运行，避免覆盖提交的基线JSON。脚本只读取指定源码、写出脚本所在目录下的审计结果；不调用临床工具、不开启服务、不写病例。

```bash
REPO=/home/lht/snap/brachyplan/BrachyBot
AUDIT_DIR=$(mktemp -d /tmp/brachybot-parity-audit.XXXXXX)
cp "$REPO/docs/audits/nl-ui-parity-20260928/"{audit_probes.py,audit_browser_probes.cjs,audit_inventory.py,tracked_sources.txt} "$AUDIT_DIR/"
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python "$AUDIT_DIR/audit_probes.py" "$REPO"
node "$AUDIT_DIR/audit_browser_probes.cjs" "$REPO"
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python "$AUDIT_DIR/audit_inventory.py" "$REPO"
```

`audit_inventory.py` 使用旧基线路径清单。审计新文件时应重新生成Git跟踪清单，并记录新HEAD、dirty diff和散列；不要把新增未跟踪文件遗漏后仍宣称全覆盖。Python纯函数probe构造包壳以避免导入时启动重型运行时，测试范围因此明确是这些函数，不是完整agent。

JS probe依赖函数名边界抽取。若源码重构导致抽取失败，先更新探针定位/使用正式导出的handler，不能解释为业务通过。

这些脚本打印的是**观察结果**，并未断言正确实现。修复时请把本报告期望行为编成正式assertions；例如handler返回false则不能返回success，第二个独立步骤必须执行，分别30/70必须分别绑定。

## 防止审计被误用

- 139 passed为11个定向Python文件，不是全仓全绿。
- 两个Node隔离回归通过，不等于真实浏览器截图/GPU/持久化通过。
- 三个Playwright测试在本地缺依赖，未进入产品断言，不应标成已通过或代码失败。
- 主报告的风险项和待E2E项不可被改写成已发生的临床事故。
- 主报告只授权后续agent有依据地制定实施；本次没有业务代码修改、服务重启或release操作。
