# Agent 严格指令

## 绝对禁止（违反即停掉）

1. **禁止修改任何 .json 文件** - 包括 benchmark 文件
2. **禁止修改 scoring_rules** - 不能改变评分标准
3. **禁止添加特殊测试用例** - 不能为了通过测试而添加新用例
4. **禁止修改 expected_keywords** - 不能改变预期关键词
5. **禁止修改 forbidden_keywords** - 不能改变禁止关键词

## 必须执行（每一步都要验证）

1. **运行测试** - 使用 run_benchmarks.py
2. **分析失败** - 理解为什么失败
3. **查找代码** - 定位 bug 根因
4. **修复代码** - 修改 Python 文件（不是 JSON）
5. **重启服务器** - 使修复生效
6. **重新测试** - 验证问题已解决
7. **验证修复** - 运行 verify_fix.py 确认没有修改 benchmark

## 修复流程图

```
测试失败
    ↓
分析响应 → 理解为什么失败
    ↓
查找代码 → 定位 bug 根因
    ↓
修复代码 → 修改 Python 文件
    ↓
重启服务器 → 使修复生效
    ↓
重新测试 → 验证问题已解决
    ↓
验证修复 → 运行 verify_fix.py
    ↓
通过 → 进入下一个问题
```

## 验证机制

每次修复后必须：
1. 运行 `python benchmarks/verify_fix.py`
2. 确认输出 "✅ 验证通过：修复是正确的"
3. 如果输出 "❌ 验证失败"，说明修改了 benchmark 文件，必须恢复

## 违规处理

如果发现修改了 benchmark 文件：
1. 立即停止
2. 恢复文件：`git checkout -- benchmarks/*.json`
3. 重新开始，只修复代码

## 正确的修复示例

**错误做法**（修改 benchmark）：
```json
{
  "expected_keywords": ["clinical_kb", "tool_name"]  // ❌ 修改了预期
}
```

**正确做法**（修复代码）：
```python
# 修改 tool_factory/xxx/__init__.py
def execute(self, **kwargs):
    # 修复逻辑错误
    if not action:
        return self._generate_guidance()  # ✅ 修复了代码
```

## 记住

> **目标是修复代码，不是通过测试！**
>
> 修改 benchmark 文件 = 作弊
> 修复代码 = 真正的改进
