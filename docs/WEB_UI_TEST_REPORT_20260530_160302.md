# BrachyBot Web UI 测试报告

**生成时间:** 2026-05-30 16:03:02

**测试方法:** API-based testing

---

## 📊 测试结果概览

| 指标 | 数值 | 百分比 |

|------|------|--------|

| 总测试数 | 1742 | - |

| ✅ 通过 | 90 | 5.2% |

| ❌ 失败 | 23 | 1.3% |

| ⚠️ 错误 | 1629 | 93.5% |



## 📁 按类别统计

| 类别 | 总数 | 通过 | 失败 | 错误 | 通过率 |

|------|------|------|------|------|--------|

| 01_greeting | 50 | 30 | 20 | 0 | 60.0% |

| 02_ct_analysis | 32 | 30 | 2 | 0 | 93.8% |

| 03_ctv_segmentation | 30 | 29 | 0 | 1 | 96.7% |

| 04_oar_segmentation | 30 | 1 | 1 | 28 | 3.3% |

| 05_treatment_planning | 30 | 0 | 0 | 30 | 0.0% |

| 06_dose_evaluation | 30 | 0 | 0 | 30 | 0.0% |

| 07_ui_interaction | 27 | 0 | 0 | 27 | 0.0% |

| 08_tool_calling | 26 | 0 | 0 | 26 | 0.0% |

| 09_edge_case | 29 | 0 | 0 | 29 | 0.0% |

| 10_adversarial | 30 | 0 | 0 | 30 | 0.0% |

| 11_hallucination | 29 | 0 | 0 | 29 | 0.0% |

| 12_medical_reasoning | 30 | 0 | 0 | 30 | 0.0% |

| 13_multilingual | 30 | 0 | 0 | 30 | 0.0% |

| 14_stress | 30 | 0 | 0 | 30 | 0.0% |

| 15_recovery | 30 | 0 | 0 | 30 | 0.0% |

| 16_clarification | 23 | 0 | 0 | 23 | 0.0% |

| 17_safety | 29 | 0 | 0 | 29 | 0.0% |

| 18_image_input | 35 | 0 | 0 | 35 | 0.0% |

| 19_workflow | 81 | 0 | 0 | 81 | 0.0% |

| 20_memory | 31 | 0 | 0 | 31 | 0.0% |

| 21_precision | 50 | 0 | 0 | 50 | 0.0% |

| 22_compliance | 30 | 0 | 0 | 30 | 0.0% |

| advanced_adversarial | 60 | 0 | 0 | 60 | 0.0% |

| advanced_imaging | 40 | 0 | 0 | 40 | 0.0% |

| clinical_decision | 50 | 0 | 0 | 50 | 0.0% |

| comparative_analysis | 49 | 0 | 0 | 49 | 0.0% |

| compliance | 25 | 0 | 0 | 25 | 0.0% |

| dose_evaluation_expert | 35 | 0 | 0 | 35 | 0.0% |

| dosimetry_physics | 50 | 0 | 0 | 50 | 0.0% |

| education | 20 | 0 | 0 | 20 | 0.0% |

| error_scenarios | 31 | 0 | 0 | 31 | 0.0% |

| innovation | 55 | 0 | 0 | 55 | 0.0% |

| integration | 55 | 0 | 0 | 55 | 0.0% |

| logistics | 15 | 0 | 0 | 15 | 0.0% |

| medical_edge_cases | 50 | 0 | 0 | 50 | 0.0% |

| medical_knowledge_deep | 50 | 0 | 0 | 50 | 0.0% |

| meta_questions | 35 | 0 | 0 | 35 | 0.0% |

| patient_communication | 20 | 0 | 0 | 20 | 0.0% |

| pediatric | 20 | 0 | 0 | 20 | 0.0% |

| precision | 35 | 0 | 0 | 35 | 0.0% |

| protocol_design | 40 | 0 | 0 | 40 | 0.0% |

| quality_assurance | 25 | 0 | 0 | 25 | 0.0% |

| real_patient_scenarios | 110 | 0 | 0 | 110 | 0.0% |

| research | 25 | 0 | 0 | 25 | 0.0% |

| technology | 25 | 0 | 0 | 25 | 0.0% |

| treatment_planning_advanced | 45 | 0 | 0 | 45 | 0.0% |

| workflow | 35 | 0 | 0 | 35 | 0.0% |



---

## ❌ 失败案例详细分析

### 1. G002 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
Hello
```


**响应长度:** 540 字符

**响应时间:** 9.64秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['hello', 'welcome', 'Hi', 'Hey']


**完整响应:**

```
你好！👋 我是 **BrachyBot**，你的近距离放疗计划 AI 助手！

---

## 我能做什么

| 功能 | 说明 |
|------|------|
| 🔬 CT 分析 | 加载和分析 CT/CBCT 图像 |
| 🎯 CTV 分割 | 自动分割肿瘤靶区 |
| 🫀 OAR 分割 | 自动分割危险器官 |
| 📐 轨迹规划 | 生成最优穿刺路径 |
| 🌱 种子放置 | 放置放射性种子 |
| 📊 剂量计算 | 计算剂量分布 |

---

## 肺癌近距离治疗计划

好的，肺癌近距离治疗计划！🫁

**请在右侧 Input 标签页上传：**
- CT 图像（.nii.gz 或 .dcm 格式）

上传后我会帮你完成：

| 步骤 | 内容 |
|------|------|
| 1️⃣ | **分割 CTV** - 肺部肿瘤靶区 |
| 2️⃣ | **分割 OAR** - 肺、脊髓、心脏等 |
| 3️⃣ | **轨迹规划** - 生成穿刺路径 |
| 4️⃣ | **种子放置** - 优化种子分布 |
| 5️⃣ | **剂量计算** - 计算剂量分布 |
| 6️⃣ | **评估报告** - DVH 和质量评分 |

有文件就可以开始了！😊
```


---

### 2. G008 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
Hi there! Can you help me with brachytherapy planning?
```


**响应长度:** 529 字符

**响应时间:** 12.51秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['brachytherapy', 'planning', 'help']


**完整响应:**

```
好的，胰腺癌病例！📋

---

## 胰腺癌近距离治疗计划

**请在右侧 Input 标签页上传：**

| 文件 | 必需 | 说明 |
|------|------|------|
| CT 图像 | ✅ | .nii.gz / .dcm 格式 |
| CTV 分割 | ❓ | 如已有可上传 |
| OAR 分割 | ❓ | 如已有可上传 |

---

## 系统使用方法（3 步搞定）

**1️⃣ 上传文件**
→ 右侧 **Input** 标签页，上传 CT 文件

**2️⃣ 自动处理**
→ 我会自动分割 CTV、OAR、规划轨迹、放置种子、计算剂量

**3️⃣ 查看结果**
→ **Analysis** 标签页：看剂量评估
→ **Seeds** 标签页：看种子位置
→ **Viewers** 标签页：看 3D 可视化

---

## 胰腺癌近距离治疗流程

```
CT → CTV分割 → OAR分割 → 轨迹规划 → 种子放置 → 剂量计算 → 评估报告
```

**胰腺癌需要关注的 OAR：**
- ⭐⭐⭐ **十二指肠**（最重要）
- 胃
- 主动脉
- 门静脉

---

上传 CT 文件就可以开始了！😊
```


---

### 3. G011 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
早上好
```


**响应长度:** 40 字符

**响应时间:** 3.39秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['早上好', '你好']


**完整响应:**

```
再见！👋 有需要随时回来找我！

上传 CT 文件就可以开始近距离放疗计划～ 😊
```


---

### 4. G012 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
下午好
```


**响应长度:** 92 字符

**响应时间:** 4.31秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['下午好', '你好']


**完整响应:**

```
再见！👋 有需要随时回来找我！

上传 CT 文件就可以开始近距离放疗计划～ 😊

---

再见！👋

---

早上好！☀️

---

晚上好！🌙

---

有需要随时找我！😊
```


---

### 5. G017 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
你会学习吗
```


**响应长度:** 7 字符

**响应时间:** 6.07秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['学习', '进化', '经验']


**完整响应:**

```
嗨！👋 你好！
```


---

### 6. G019 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
对不起
```


**响应长度:** 39 字符

**响应时间:** 4.64秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['没关系', '不用']


**完整响应:**

```
不客气！😊 有问题随时找我～

上传 CT 文件就可以开始近距离放疗计划了！🚀
```


---

### 7. G020 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 20.0%


**原始问题:**

```
帮帮我
```


**响应长度:** 200 字符

**响应时间:** 5.88秒


**关键词匹配:** 20.0%

**匹配到的:** ['帮']

**期望的:** ['帮助', '怎么', '需要', '帮', '帮忙']


**完整响应:**

```
好的！我来帮你！👋

**我可以帮你做什么：**

| 功能 | 说明 |
|------|------|
| 📤 上传 CT 文件 | 加载医学图像 |
| 🎯 CTV 分割 | 分割肿瘤靶区 |
| 🫀 OAR 分割 | 分割危险器官 |
| 📐 轨迹规划 | 生成穿刺路径 |
| 🌱 种子放置 | 放置放射性种子 |
| 📊 剂量计算 | 计算剂量分布 |

**你想让我帮你做什么？** 😊
```


---

### 8. G024 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
你叫什么名字
```


**响应长度:** 45 字符

**响应时间:** 5.49秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['BrachyBot', '名字']


**完整响应:**

```
我很好，谢谢关心！😊

有什么我可以帮你的吗？上传 CT 文件就可以开始近距离放疗计划！🚀
```


---

### 9. G023 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
How are you?
```


**响应长度:** 248 字符

**响应时间:** 9.23秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['good', 'fine', 'well']


**完整响应:**

```
Hello! 👋 How are you doing?

I'm **BrachyBot**, your AI assistant for brachytherapy treatment planning! 😊

Need help with:
- 📤 Uploading CT files
- 🎯 CTV/OAR segmentation
- 📐 Trajectory planning
- 📊 Dose calculation

What can I help you with today?
```


---

### 10. G028 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
早上好，今天天气不错
```


**响应长度:** 619 字符

**响应时间:** 9.04秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['早上好', '你好']


**完整响应:**

```
I can help you with brachytherapy treatment planning! 🎉

**What I can do:**

| Feature | Description |
|---------|-------------|
| 🔬 **CT Analysis** | Load and analyze CT/CBCT images |
| 🎯 **CTV Segmentation** | Auto-segment tumor targets |
| 🫀 **OAR Segmentation** | Auto-segment organs at risk (40+ organs) |
| 📐 **Trajectory Planning** | Generate optimal needle paths |
| 🌱 **Seed Placement** | Place radioactive seeds |
| 📊 **Dose Calculation** | Calculate dose distribution |
| 📋 **Plan Evaluation** | Generate DVH, assess quality |

Upload CT files in the **Input** tab and I'll help you with the full workflow! 😊
```


---

### 11. G030 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
嘿，帮个忙
```


**响应长度:** 168 字符

**响应时间:** 6.75秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['你好', '帮助', '需要']


**完整响应:**

```
嘿！👋 当然可以！

**请告诉我你想做什么？**

| 选项 | 任务 |
|------|------|
| 1 | 📤 上传 CT 文件 |
| 2 | 🎯 分割 CTV/OAR |
| 3 | 📐 轨迹规划 |
| 4 | 🌱 种子放置 |
| 5 | 📊 剂量计算 |
| 6 | ❓ 其他问题 |

告诉我序号或具体需求！😊
```


---

### 12. G029 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
Good morning
```


**响应长度:** 54 字符

**响应时间:** 8.05秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['morning', 'hello', 'good']


**完整响应:**

```
早上好！☀️ 是的，天气很不错！

有什么需要帮忙的吗？😊

上传 CT 文件就可以开始近距离放疗计划了！🚀
```


---

### 13. G032 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
How are you doing?
```


**响应长度:** 266 字符

**响应时间:** 6.15秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['good', 'fine', 'well']


**完整响应:**

```
Hey! 👋 

I'm doing great, thanks for asking! 😊

How can I help you today? Do you have CT files to process for brachytherapy planning?

- 📤 Upload CT files
- 🎯 Segment CTV/OAR
- 📐 Plan trajectories
- 🌱 Place seeds
- 📊 Calculate dose

Just let me know what you need! 😊
```


---

### 14. G033 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
你叫什么
```


**响应长度:** 45 字符

**响应时间:** 4.94秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['BrachyBot', '名字']


**完整响应:**

```
我很好，谢谢关心！😊

有什么我可以帮你的吗？上传 CT 文件就可以开始近距离放疗计划！🚀
```


---

### 15. G035 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 20.0%


**原始问题:**

```
帮我
```


**响应长度:** 223 字符

**响应时间:** 5.92秒


**关键词匹配:** 20.0%

**匹配到的:** ['帮']

**期望的:** ['帮助', '需要', '帮', '帮忙', 'help']


**完整响应:**

```
我是 **BrachyBot**！🤖

**我能帮你做什么：**

| 功能 | 说明 |
|------|------|
| 🔬 CT 分析 | 加载和分析 CT 图像 |
| 🎯 CTV 分割 | 自动分割肿瘤靶区 |
| 🫀 OAR 分割 | 自动分割危险器官 |
| 📐 轨迹规划 | 生成穿刺路径 |
| 🌱 种子放置 | 放置放射性种子 |
| 📊 剂量计算 | 计算剂量分布 |

---

**请告诉我你想让我帮你做什么？** 😊
```


---

### 16. G040 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
I am a patient
```


**响应长度:** 223 字符

**响应时间:** 7.34秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['patient', 'hello']


**完整响应:**

```
你好！👋

作为患者，**这个系统是专为医生和物理师设计的**，不建议您直接使用。

---

**如果您是患者，建议您：**

| 建议 | 说明 |
|------|------|
| 👨‍⚕️ 咨询您的主治医生 | 医生会根据您的病情制定治疗方案 |
| 🏥 到正规医院就诊 | 进行规范的检查和治疗 |
| 📋 了解治疗流程 | 可以让医生给您解释近距离放疗的过程 |

---

**如果您有其他问题或需要帮助，可以随时回来找我！😊**
```


---

### 17. G042 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
Hello, I am a nurse
```


**响应长度:** 260 字符

**响应时间:** 7.11秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['Hello', 'nurse', 'welcome']


**完整响应:**

```
你好，护士！👩‍⚕️

欢迎使用 **BrachyBot**！

作为护士，您可能需要协助医生完成近距离放疗计划的相关工作。

**我能帮护士做什么：**

| 功能 | 说明 |
|------|------|
| 📤 上传 CT 文件 | 协助准备患者图像 |
| 📋 查看分割结果 | 确认靶区和器官分割 |
| 📊 查看剂量信息 | 协助准备治疗 |
| 📄 生成报告 | 协助准备文档 |

---

**Upload CT files in the Input tab to get started!** 😊
```


---

### 18. G046 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
I am a researcher
```


**响应长度:** 53 字符

**响应时间:** 5.20秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['researcher', 'hello']


**完整响应:**

```
你好！👋

**我是 BrachyBot**，你的近距离放疗计划 AI 助手！🤖

有什么需要帮忙的吗？😊
```


---

### 19. G048 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
Hello, I am a student
```


**响应长度:** 247 字符

**响应时间:** 6.13秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['Hello', 'student', 'welcome']


**完整响应:**

```
你好！👋

**我是 BrachyBot**，你的近距离放疗计划 AI 助手！

---

**作为学生，你可以在这里学习：**

| 内容 | 说明 |
|------|------|
| 📚 **近距离治疗知识** | 了解原理和流程 |
| 🔬 **CT 图像分析** | 学习图像处理 |
| 🎯 **靶区勾画** | 理解 CTV/OAR 概念 |
| 📊 **剂量计算** | 学习剂量学原理 |

---

Upload CT files to start learning! 😊
```


---

### 20. G050 (01_greeting)

**严重程度:** low

**问题:** Low keyword match: 0.0%


**原始问题:**

```
Hello, I am a physicist
```


**响应长度:** 242 字符

**响应时间:** 6.30秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['Hello', 'physicist', 'welcome']


**完整响应:**

```
你好，物理师！👨‍🔬

欢迎使用 **BrachyBot**！

作为物理师，你可以完成近距离治疗计划的技术工作和质量控制！

**我能帮物理师做什么：**

| 功能 | 说明 |
|------|------|
| 📐 轨迹规划 | 生成最优穿刺路径 |
| 🌱 种子放置 | 优化种子分布 |
| 📊 剂量计算 | TG-43/Model-based 计算 |
| ✅ 剂量验证 | 蒙特卡洛验证 |
| 📋 OAR 限量检查 | 确保计划符合标准 |

有什么需要帮忙的吗？😊
```


---

### 21. CT018 (02_ct_analysis)

**严重程度:** medium

**问题:** Low keyword match: 0.0%


**原始问题:**

```
能用骨窗显示吗
```


**响应长度:** 593 字符

**响应时间:** 20.01秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['骨窗', '显示']


**完整响应:**

```
## 📊 CT图像质量评估

### 1️⃣ 对比度分析

根据图像生成结果：

| 指标 | 值 | 评估 |
|------|-----|------|
| **HU范围** | -1000 ~ 1498 HU | 较宽 |
| **标准差** | 485.7 HU | 较高 |
| **对比度** | ⭐⭐⭐ 中等偏上 | 良好 |

### 2️⃣ 图像质量评分

| 评估项目 | 权重 | 得分 | 等级 |
|----------|------|------|------|
| **空间分辨率** | 20% | ⭐⭐⭐⭐ (80) | 良好 |
| **对比度** | 20% | ⭐⭐⭐ (70) | 中等偏上 |
| **噪声水平** | 15% | ⭐⭐⭐ (65) | 中等 |
| **伪影** | 15% | ⭐⭐⭐⭐ (85) | 良好 |
| **信噪比** | 15% | ⭐⭐⭐ (65) | 中等 |
| **诊断价值** | 15% | ⭐⭐⭐⭐ (75) | 良好 |

### 🎯 总体评价

| 项目 | 评价 |
|------|------|
| **综合评分** | **76/100** (良好) |
| **适合近距离治疗** | ✅ 适合 |

---

**总体来说，这个CT图像质量良好，适合进行近距离治疗计划！** 😊
```


**调用的工具:** code_executor, code_executor


---

### 22. CT022 (02_ct_analysis)

**严重程度:** medium

**问题:** Low keyword match: 0.0%


**原始问题:**

```
CT的矩阵大小是多少
```


**响应长度:** 434 字符

**响应时间:** 9.04秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['矩阵', '512']


**完整响应:**

```
## 📊 CT像素尺寸

### ✅ 像素尺寸

| 方向 | 像素尺寸 |
|------|-----------|
| **X (列)** | 0.68 mm |
| **Y (行)** | 0.68 mm |
| **Z (层)** | 5.00 mm |

---

### 📐 像素详情

| 参数 | 值 |
|------|-----|
| **XY像素间距** | 0.68 mm |
| **Z层厚** | 5.00 mm |
| **XY分辨率** | 0.68 × 0.68 mm² |
| **层厚较厚** | 5.0 mm（建议≤2.5mm更佳） |

---

### 📋 评估

| 项目 | 评价 |
|------|------|
| **XY分辨率** | ⭐⭐⭐⭐ 良好 (0.68mm) |
| **Z分辨率** | ⭐⭐⭐ 中等 (5.0mm层厚偏厚) |
| **建议** | 薄层CT (≤2.5mm) 更适合精确勾画 |
```


---

### 23. OAR004 (04_oar_segmentation)

**严重程度:** high

**问题:** Low keyword match: 0.0%


**原始问题:**

```
请分割肝脏
```


**响应长度:** 344 字符

**响应时间:** 9.06秒


**关键词匹配:** 0.0%

**匹配到的:** []

**期望的:** ['肝脏', '分割']


**完整响应:**

```
## 📊 Hausdorff 距离 (HD)

### ⚠️ 无法直接计算

**Hausdorff 距离需要与专家金标准进行对比，当前没有参考数据。**

---

### 📋 Hausdorff 距离定义

| 指标 | 说明 |
|------|------|
| **定义** | 两个集合之间最大最短距离 |
| **HD95** | 95%分位数的 Hausdorff 距离 |
| **临床标准** | HD95 ≤ 2mm |

---

### 🎯 典型模型 HD 值

| 模型 | HD95 |
|------|------|
| **VoCo** | 1.5-2.5 mm |
| **nnU-Net** | 2.0-3.0 mm |

---

有其他问题吗？😊
```


---

---

## ⚠️ 错误案例

### 1. OAR005 (04_oar_segmentation)

**错误:** ['API Error: Response ended prematurely']


**问题:** 请分割肾脏...


---

### 2. OAR001 (04_oar_segmentation)

**错误:** ['API Error: Response ended prematurely']


**问题:** 请分割这个病例的OAR...


---

### 3. CTV030 (03_ctv_segmentation)

**错误:** ['API Error: Response ended prematurely']


**问题:** CTV分割的Hausdorff距离是多少...


---

### 4. OAR006 (04_oar_segmentation)

**错误:** ['API Error: Response ended prematurely']


**问题:** Segment all OARs for this case...


---

### 5. OAR002 (04_oar_segmentation)

**错误:** ['API Error: Response ended prematurely']


**问题:** 帮我做organ at risk segmentation...


---

### 6. OAR007 (04_oar_segmentation)

**错误:** ["API Error: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"]


**问题:** 这个病例的脊髓在哪里...


---

### 7. OAR008 (04_oar_segmentation)

**错误:** ["API Error: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"]


**问题:** 请分割胃肠道...


---

### 8. OAR010 (04_oar_segmentation)

**错误:** ["API Error: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"]


**问题:** 请显示OAR分割结果...


---

### 9. OAR009 (04_oar_segmentation)

**错误:** ["API Error: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"]


**问题:** OAR分割的质量如何...


---

### 10. OAR011 (04_oar_segmentation)

**错误:** ["API Error: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"]


**问题:** 这个病例的危及器官有哪些...


---

### 11. OAR014 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675cd10>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** 小肠的分割结果怎么样...


---

### 12. OAR015 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675cc00>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** 脊髓在哪里...


---

### 13. OAR016 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675c490>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** 肝脏的分割结果...


---

### 14. OAR012 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675d150>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** 直肠在哪里...


---

### 15. OAR013 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675c8d0>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** 膀胱的位置在哪里...


---

### 16. OAR018 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675c7c0>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** OAR的勾画精度要求是什么...


---

### 17. OAR019 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675d590>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** 危及器官的限量标准是什么...


---

### 18. OAR017 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781675dae0>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** 肾脏在哪里...


---

### 19. OAR020 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781689e580>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** TotalSegmentator能分割多少个器官...


---

### 20. OAR022 (04_oar_segmentation)

**错误:** ["API Error: HTTPConnectionPool(host='localhost', port=8080): Max retries exceeded with url: /api/chat (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object at 0x76781680fce0>: Failed to establish a new connection: [Errno 111] Connection refused'))"]


**问题:** OAR分割的精度是多少...


---

---

## 📸 截图分析

截图可在以下目录找到:

`/home/lht/snap/brachyplan/BrachyBot/web/test/benchmarks/screenshots/`
