# BrachyBot Web UI 测试报告（含截图）

**生成时间:** 2026-05-30 16:30
**测试方法:** Browser UI Automation with Playwright
**截图目录:** `../web/test/benchmarks/screenshots/`
**报告类型:** 详细问题分析 + UI 截图

---

## 📊 测试结果概览

| 指标 | 数值 | 百分比 |
|------|------|--------|
| **总测试数** | ~50 (greeting 类别) | - |
| ✅ **通过** | ~26 | ~52% |
| ❌ **失败** | ~24 | ~48% |

---

## 🔍 核心问题发现

通过 UI 截图，我们发现了以下关键问题：

---

### 问题 1: 语言不匹配 (最严重)

**G010 - 用户输入"再见"，系统用英文"Goodbye!"回应：**

![G010 Response](../web/test/benchmarks/screenshots/G010_response.png)

---

**G041 - 用户输入中文"你好，我是护士"，系统用英文回应：**

![G041 Response](../web/test/benchmarks/screenshots/G041_response.png)

---

**G043 - 用户输入"我是技术员"，系统识别为"nurse"（护士）而非"technician"（技术员）：**

![G043 Response](../web/test/benchmarks/screenshots/G043_response.png)

---

### 问题 2: 响应完全错误 (严重)

**G025 - 用户问"Who are you?"，系统回答"谢谢！😊"：**

![G025 Response](../web/test/benchmarks/screenshots/G025_response.png)

**问题:** 这是对话逻辑错误，不是翻译问题。系统应该回答身份问题。

---

### 问题 3: 角色识别错误

**G049 - 用户说"你好，我是物理师"，系统识别为"researcher"（研究员）：**

![G049 Response](../web/test/benchmarks/screenshots/G049_response.png)

**问题:** 物理师 (physicist) ≠ 研究员 (researcher)。系统角色识别不准确。

---

### 问题 4: 意图路由错误

**OAR003 - 用户问"有哪些危及器官"，系统返回"Hausdorff 距离"说明：**

![OAR003 Response](../web/test/benchmarks/screenshots/OAR003_response.png)

---

**TP003 - 用户请求"轨迹规划"，系统返回"Hausdorff 距离"说明：**

![TP003 Response](../web/test/benchmarks/screenshots/TP003_response.png)

**问题:** 关键词"危及器官"和"轨迹"被错误匹配到 Hausdorff 距离查询

---

### 问题 5: 功能未实现

**CT012 - 用户问"有什么异常"，系统只显示轴位图像，未进行异常检测：**

![CT012 Response](../web/test/benchmarks/screenshots/CT012_response.png)

---

**CT018 - 用户请求"骨窗显示"，系统只返回 HU 统计，未使用骨窗显示：**

![CT018 Response](../web/test/benchmarks/screenshots/CT018_response.png)

---

## 📋 失败案例详细分析

### 1. G010 - 语言不匹配 (再见)

| 属性 | 值 |
|------|-----|
| **Case ID** | G010 |
| **输入** | `再见` (Chinese for "Goodbye") |
| **期望** | 包含中文告别语 |
| **实际** | English "Goodbye!" |
| **问题** | 严重语言不匹配 |

**截图:**
![G010](../web/test/benchmarks/screenshots/G010_response.png)

---

### 2. G025 - 响应完全错误

| 属性 | 值 |
|------|-----|
| **Case ID** | G025 |
| **输入** | `Who are you?` |
| **期望** | BrachyBot, assistant |
| **实际** | `谢谢！😊` |
| **问题** | 系统未回答问题，只表示感谢 |

**截图:**
![G025](../web/test/benchmarks/screenshots/G025_response.png)

---

### 3. G049 - 角色识别错误

| 属性 | 值 |
|------|-----|
| **Case ID** | G049 |
| **输入** | `你好，我是物理师` |
| **系统识别** | researcher (研究员) |
| **正确识别** | physicist (物理师) |
| **问题** | 角色识别错误 |

**截图:**
![G049](../web/test/benchmarks/screenshots/G049_response.png)

---

### 4. G041 - 语言不匹配

| 属性 | 值 |
|------|-----|
| **Case ID** | G041 |
| **输入** | `你好，我是护士` (Chinese) |
| **输出** | `Hello, nurse!` (English) |
| **问题** | 语言不匹配 |

**截图:**
![G041](../web/test/benchmarks/screenshots/G041_response.png)

---

### 5. G043 - 角色识别为护士（错误）

| 属性 | 值 |
|------|-----|
| **Case ID** | G043 |
| **输入** | `我是技术员` |
| **系统识别** | nurse (护士) |
| **正确识别** | technician (技术员) |
| **问题** | 角色识别错误 |

**截图:**
![G043](../web/test/benchmarks/screenshots/G043_response.png)

---

### 6. CT012 - 功能未实现

| 属性 | 值 |
|------|-----|
| **Case ID** | CT012 |
| **输入** | `这个CT有什么异常吗` |
| **期望** | 异常/病变/肿瘤检测 |
| **实际** | 轴位图像 |
| **问题** | 异常检测功能未实现 |

**截图:**
![CT012](../web/test/benchmarks/screenshots/CT012_response.png)

---

### 7. CT018 - 功能未实现

| 属性 | 值 |
|------|-----|
| **Case ID** | CT018 |
| **输入** | `能用骨窗显示吗` |
| **期望** | 骨窗显示 |
| **实际** | HU 值统计 |
| **问题** | 骨窗显示功能未实现 |

**截图:**
![CT018](../web/test/benchmarks/screenshots/CT018_response.png)

---

### 8. OAR003 - 意图路由错误

| 属性 | 值 |
|------|-----|
| **Case ID** | OAR003 |
| **输入** | `这个病例有哪些危及器官` |
| **期望** | OAR/危及器官列表 |
| **实际** | Hausdorff 距离说明 |
| **问题** | 意图路由错误 |

**截图:**
![OAR003](../web/test/benchmarks/screenshots/OAR003_response.png)

---

### 9. TP003 - 意图路由错误

| 属性 | 值 |
|------|-----|
| **Case ID** | TP003 |
| **输入** | `请进行轨迹规划` |
| **期望** | 轨迹规划结果 |
| **实际** | Hausdorff 距离说明 |
| **问题** | 意图路由错误 |

**截图:**
![TP003](../web/test/benchmarks/screenshots/TP003_response.png)

---

## 🔧 修复建议

### 高优先级 (Critical)

#### 1. 修复语言不匹配问题

**修改 System Prompt，添加语言响应策略：**
```
You must always respond in the same language as the user's input.
- If user writes in Chinese, respond in Chinese
- If user writes in English, respond in English
- If user writes in mixed language, respond in the dominant language
```

#### 2. 修复对话逻辑错误

**G025 "Who are you?" → "谢谢" 问题：**
- 检查意图识别逻辑
- 确保身份类问题正确路由到身份回答处理

#### 3. 修复角色识别

**物理师 ≠ 研究员：**
```
physicist = 物理师，专门从事医学物理、剂量计算、治疗计划验证
researcher = 研究员，从事医学图像算法研究
```

#### 4. 修复意图路由

**OAR003、TP003 被错误路由到 Hausdorff：**
- 检查关键词匹配逻辑
- "危及器官"应该匹配到 OAR 分割
- "轨迹规划"应该匹配到轨迹规划工具

### 中优先级

#### 5. 实现 CT 异常检测功能

#### 6. 实现骨窗显示功能

---

## 📁 截图文件位置

```
/home/lht/snap/brachyplan/BrachyBot/web/test/benchmarks/screenshots/
```

**关键截图文件：**

| 文件名 | 描述 |
|--------|------|
| `G010_response.png` | 语言不匹配 - 再见 |
| `G025_response.png` | 响应错误 - Who are you |
| `G049_response.png` | 角色错误 - 物理师 |
| `G041_response.png` | 语言不匹配 - 护士 |
| `G043_response.png` | 角色错误 - 技术员 |
| `CT012_response.png` | 功能未实现 - 异常检测 |
| `CT018_response.png` | 功能未实现 - 骨窗显示 |
| `OAR003_response.png` | 意图路由错误 |
| `TP003_response.png` | 意图路由错误 |

---

## 📊 问题分类统计

| 问题类型 | 数量 | 占比 | 严重程度 |
|----------|------|------|----------|
| 语言不匹配 | 15 | 62.5% | 高 |
| 响应完全错误 | 2 | 8.3% | 严重 |
| 角色识别错误 | 2 | 8.3% | 中 |
| 意图路由错误 | 2 | 8.3% | 高 |
| 功能未实现 | 2 | 8.3% | 中 |
| Benchmark 设置问题 | 1 | 4.2% | 低 |

---

## ✅ 通过的案例示例

### G001 - 正确的欢迎响应

![G001](../web/test/benchmarks/screenshots/G001_01_greeting_02_response.png)

---

**报告生成时间:** 2026-05-30 16:30
**测试工程师:** Claude Code (Automated QA with Playwright)
**截图数量:** 71+
