# BrachyBot Logo 设计 Prompt

> 用于发给图片生成模型(Midjourney / DALL-E / Stable Diffusion / Ideogram 等)
> 复制下方整段或最底下"Midjourney 一句话版"即可。

---

## 项目背景(让模型理解业务)

**BrachyBot** 是一个 AI 辅助的放射性粒子植入治疗规划系统(SPA),由 **上海交通大学医学院附属瑞金医院放射治疗科** 与交大联合实验室开发。系统用于胰腺癌、前列腺癌等实体肿瘤的近距离放射治疗(brachytherapy)规划:CT 影像自动分割、危及器官(OAR)勾画、穿刺针轨迹与放射性粒子(seed)分布优化、剂量计算、DVH 分析,并生成可在临床使用的治疗报告。

## 设计要求(核心 8 点)

### 1. 主元素
- **"B" 字形**:大写 B,粗壮几何,线条端庄(可参考 3D Slicer、BrachyVision 这类医学软件的硬朗线条)
- **放射性种子意象**:B 的某个笔画末端/内部嵌入一颗小的圆形或方形种子(seed),代表放射性粒子源(¹²⁵I 籽粒)。这是 BrachyBot 区别于普通 B 字母 logo 的关键

### 2. 配色
- **主色**:深蓝/海军蓝(医学专业感、科技感),建议 `#0c4a6e` 到 `#0e7490` 之间
- **强调色**:暖橙/琥珀色 `#f59e0b` 或 `#fbbf24`,**仅用于那颗种子点**
- **背景**:透明 SVG(便于在浅色和深色界面下都能用)
- 颜色对比度要够,在 A4 报告(白底)和应用界面(深色 glassmorphism)上都清晰

### 3. 形状容器
- **圆角方形**(12–16px 圆角,类似 app icon),不用纯圆形(太通用),也不用纯方形(太硬)
- 容器内放 B 字形 + 种子点
- 主尺寸 512×512(可缩放),SVG 输出

### 4. 风格
- **现代医学/科技感**:类似 Siemens Healthineers、Philips、Material Design medical
- **几何化、扁平化、clean**,不要写实或 3D 渲染
- **线条干净**,不要手绘感、不要 grunge
- 参考风格:Flat design + 极轻 gradient,可加微弱阴影或高光增加层次

### 5. 字体处理
- B 字形**自定义几何绘制**,**不依赖系统字体**(保证可移植)
- 字形比例:垂直 stem 粗壮(约 1/5 字宽),上下两个 bowl 大小略不同(上小下大,稳重感)

### 6. 关键不要(踩雷区)
- ❌ 不要绿色/红色十字(那是医院通用符号,我们已经有瑞金 logo 在旁边,不要重复)
- ❌ 不要 DNA / 螺旋 / 细胞(那是分子生物学领域,跟粒子治疗不直接相关)
- ❌ 不要心形(那是心脏专科)
- ❌ 不要写实人手 / 医生剪影(俗套)
- ❌ 不要 3–4 色复杂渐变 + 玻璃拟态(material 3 风格不适合医学专业场景)
- ❌ 不要 emoji / 卡通风格(可爱但不专业)
- ❌ 不要把 B 写成花体或装饰字(保持几何感)

### 7. 落地场景(必须能 work 的地方)
- A4 报告 letterhead(10mm × 10mm,与 SJTU、瑞金两个院徽并排)
- Web 应用顶栏(40–60px 圆角图标)
- Favicon(16×16,极简,小尺寸下种子点不能糊)
- 深色 glassmorphism 界面(深蓝半透明背景)
- 浅色报告纸张(白底)
- iOS app icon(180×180 圆角)

### 8. 输出规格
- 主交付:`512×512 SVG`,带 12–16px 圆角方形 viewBox
- 同时出:`favicon-16.png` / `favicon-32.png` / `favicon-180.png`(iOS)/ `og-image-1200x630.png`(社交分享)
- 文件名:`brachybot-logo.svg` / `brachybot-icon-{size}.png`

## 文字版本(可选,如模型支持)
- 主标识:`BrachyBot`(注意 B 双写 `Brachy` + `Bot`)
- 字体:geometric sans-serif(Inter、Manrope 风格)
- 字色:深蓝主色
- 大小写:`Brachybot`(句首大写)或 `BRACHYBOT`(全大写)都可

## 一句话总结(放 prompt 最开头)
> Design a modern medical-software logo for **BrachyBot**, an AI-assisted radioactive seed implantation planning system. A bold geometric 'B' letterform with a small glowing amber seed/particle element embedded in it, set inside a rounded-square container in deep navy blue with a single amber accent. Clean flat design, no medical clichés (no crosses, no DNA, no hearts). Must work at favicon size and in both dark and light UIs.

---

## Midjourney 一句话版(直接粘贴)

```
A modern medical software logo: bold geometric letter "B" with a small glowing amber radioactive seed embedded in the lower bowl, set inside a 12px rounded-square container in deep navy blue (#0c4a6e), flat design, clean vector style, transparent background, no medical clichés, no crosses, no DNA, no hearts --ar 1:1 --s 250 --v 6
```

## Stable Diffusion 关键词版(用于负向 prompt)

**正向**:
```
logo, medical software, geometric letter B, amber radioactive seed, rounded square, navy blue #0c4a6e, flat design, vector style, minimalist, professional, transparent background, single accent color
```

**负向**:
```
cross, dna, helix, heart, hand, doctor, stethoscope, 3d render, photorealistic, gradient, glassmorphism, cartoon, emoji, watercolor, sketch, grunge, messy
```

## DALL-E 3 描述版

```
A clean, professional medical-software logo for "BrachyBot". A bold geometric capital letter "B" in deep navy blue (#0c4a6e), with a single small glowing amber-orange circular seed embedded in the lower curve of the B, representing a radioactive brachytherapy seed. The B sits inside a rounded-square container (12–16px corner radius) with a subtle gradient from navy to teal. Flat design, vector-style, transparent background. NO crosses, NO DNA helices, NO hearts, NO hands, NO doctor silhouettes. Must remain legible at 16x16 favicon size. Modern Siemens/Philips medical-software aesthetic.
```
