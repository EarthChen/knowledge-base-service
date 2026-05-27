# V9 Wiki Quality Fix — 设计提案

**Created:** 2026-05-27 16:00
**Updated:** 2026-05-27 14:15 (基于 V21 深度审计全面更新)
**Status:** PROPOSED
**Based on:** V21 三维深度审计（Overview 7.8/10, Topic 8.0/10, 域结构 6.5/10）
**Approach:** 确定性管线修复（Batch A-D）+ Prompt 优化（Batch E，下次生成生效）

---

## 核心原则

> **业务独立性 > 模块数量。** 如果一个业务是独立的，哪怕功能少也不应该合并，需要根据业务来判断。

V20 建议的「28→12 域合并」方案已废弃。V21 分析确认 28 域中大部分是独立业务域，真正的问题是模块交叉、文档串域和后处理缺陷。

---

## 目标

修复 V21 审计中发现的 15 类问题中可通过代码确定性修复的部分，预计下次重新生成后：
- Slug 质量：11/22 bad (50%) → 0 (0%)
- H1 标题泄漏：15/28 (54%) → 0
- Meta/元节泄漏：13 overview + 5 topic → 0
- blockquote 堆叠：21 条 → 0
- 重复代码块：2 页 → 0
- 代码截断：≥20 处 → 被检测并触发 heal
- business_domain 空：27/28 → 0
- 模块交叉描述：3 组 → prompt 约束后减少（重新生成后生效）

---

## 域分解分析（V21 纠正版）

### 当前结构评估

```
__root__ (L0) → 15 个 L1 节点
├── 14 个独立 L1 域 ← 全部应保持独立
├── 家族系统 (L1 容器) → 5 个 L2 子域 ← 数量合理，但有模块交叉
└── 用户关系管理 (L1 容器) → 8 个 L2 子域 ← 边界清晰
```

### 为什么不合并？

| V20 建议 | V21 纠正 | 理由 |
|---------|---------|------|
| user-* 8 域合并为 user-system | ❌ 保持独立 | 埋点≠统计≠资料≠等级，各自是独立业务 |
| im-message + quick-message 合为 messaging | ❌ 保持独立 | IM 通道推送 ≠ 快捷消息模板 |
| payment + gift-order 合为 payment-gift | ❌ 保持独立 | 支付数据聚合 ≠ 订单回调中枢 |
| app-store-rating-popup 降级为 topic | ❌ 保持独立 | 独立触达业务，有 7 个核心模块 |
| 家族 6 域合为 1 域 | ❌ 保持 5 子域 | 各子域有独立业务意义（core/event/rank/square） |

### 实际需要解决的问题

| 问题 | 性质 | V9 解决方式 |
|------|------|-----------|
| FamilyTaskService 出现在 3 域 | 模块交叉 | Batch E: prompt 约束 Owner vs Consumer |
| user-profile overview 包含关系类 | 文档串域 | Batch E: prompt 约束模块归属 |
| family-system 壳页 214 字 | 壳域内容 | Batch E: 容器域 overview 模板 |
| 4 域无 topic 但 overview > 5000 字 | topic 覆盖 | Batch D: quality_gate 检测 |

---

## 修复清单

### Batch A: Slug Pipeline Fix（F1-F4）

**目标：** 修复 16 个 topic slug 问题（8 模块路径 + 3 拼音 + 2 碰撞 + 1 过泛 + 2 待优化）

| ID | 修复项 | 文件 | 描述 |
|----|--------|------|------|
| F1 | `_sanitize_module_path_slug()` | `wiki/path_conventions.py` | 检测 slug 包含仓库名前缀重复（如 `{repo}{repo}-*`）且长度 >30 → 剥离 repo 前缀，提取末段有意义的类名转 kebab-case，或 fallback 到 `{domain-slug}-part-{n}` |
| F2 | `_is_pinyin_slug()` 检测 | `wiki/path_conventions.py` | 检测 5+ 连字符分隔的全小写段且平均段长 <4.5 字符 → fallback 到 `{domain-slug}-topic-{n}` |
| F3 | slug 碰撞检测 | `wiki/domain_doc_agent.py` | 生成 slug 后检查同域/跨域是否已存在 → 加域前缀消歧 |
| F4 | slug 过泛检测 | `wiki/path_conventions.py` | slug 等于域 slug 或域 slug 去掉后缀后的词根 → 拒绝该 slug，fallback 到使用 topic.title 重新生成 |

**解决的 V21 问题：**
- #1: 8 个 `ultronultron-*` 模块路径 slug → 全部修复
- #2: 3 个 `zhi-you-*`/`shu-ju-*` 拼音 slug → 全部修复
- #15: `family-task` 碰撞 + `family` 过泛 → 全部修复

### Batch B: Content Guards 扩展（F5-F9）

**目标：** 扩展内容质量检测和清洗规则

| ID | 修复项 | 文件 | 描述 |
|----|--------|------|------|
| F5 | `strip_h1_title()` | `wiki/content_guards.py` | 检测 content 以 `# ` 开头（非代码块内）→ 删除第一行 H1 标题 |
| F6 | 扩展 `META_H2_PATTERNS` | `wiki/content_guards.py` | 新增 10 个模式：`章节导航`, `Section Navigation`, `待完善项`, `待完善与风险提示`, `补充说明`, `中文说明补充`, `CONTEXT_GAP`, `中英对照`, `术语表`, `术语表（中英对照）` |
| F7 | `strip_repeated_blockquotes()` | `wiki/content_guards.py` | 检测连续重复 `> ` 段落（相似度 >80%）→ 仅保留第一个；清除 `> **Overview**：`, `> **说明**：为提升中文读者理解` 等模式 |
| F8 | `dedup_code_fences()` | `wiki/content_guards.py` | 提取所有 fenced code block 内容 → 完全相同的仅保留第一个 |
| F9 | `strip_english_self_reflection()` | `wiki/content_guards.py` | 清除英文 LLM 自省 blockquote：`> **Note**: The headings ... are placeholders`, `> This section is` 等 |

**解决的 V21 问题：**
- #5: 15/28 overview H1 标题泄漏 → 0
- #8: 13 overview + 5 topic LLM 元节 → 0
- #9: 21 条 blockquote 堆叠 → 0
- #7: 重复代码块 → 0

### Batch C: Finalize 集成（F10-F11）

**目标：** 将 Batch A+B 的新规则集成到发布管线

| ID | 修复项 | 文件 | 描述 |
|----|--------|------|------|
| F10 | finalize 集成新清洗函数 | `wiki/nodes/finalize.py` | 在 `_sanitize_published_content` 中按序调用：`strip_h1_title()` → `strip_meta_sections()` → `strip_repeated_blockquotes()` → `dedup_code_fences()` → `strip_english_self_reflection()` |
| F11 | quality_gate 新检测 | `wiki/nodes/quality_gate.py` | 新增 heal_hint：壳域检测（overview <500 字且仅有 1 个 H2 `## 子域概览`）、零代码 topic 检测（page_type=topic 且无 fenced code block）、代码截断检测（detect_truncated_code_blocks） |

### Batch D: 元数据 + 配置（F12-F13）

| ID | 修复项 | 文件 | 描述 |
|----|--------|------|------|
| F12 | Overview 页 `business_domain` 赋值 | `wiki/domain_doc_agent.py` | 在 `_make_page()` 中为 overview 页设置 `business_domain = self.domain_name` |
| F13 | dangling wikilink 检测 | `wiki/nodes/finalize.py` | finalize 阶段从 pipeline state 获取已生成的 topic 路径集合，校验 overview 中的 wikilink 是否指向已存在的 topic → 不存在则移除链接文本保留纯文本 |

**解决的 V21 问题：**
- #14: 27/28 `business_domain` 空 → 0
- #13: 12 个 dangling wikilink → 0（链接移除）

### Batch E: Prompt 优化（F14-F16）

**目标：** 通过 prompt 约束解决模块交叉、壳域、Mermaid-only 问题（下次生成生效）
**关键约束：** prompt 内容必须保持泛化，**禁止写死当前遇到的具体域名、类名**，确保适用于任意仓库。

| ID | 修复项 | 文件 | 描述 |
|----|--------|------|------|
| F14 | Overview prompt 模块归属约束 | `wiki/agent_prompts.py` | 新增泛化约束：「模块详解节仅描述**本域直接拥有的核心模块**，对于被本域调用但归属于其他域的模块，仅在依赖关系节简要标注为外部依赖，不要详细展开其实现」 |
| F15 | 容器域 overview 专用模板 | `wiki/agent_prompts.py` + `wiki/domain_doc_agent.py` | **程序化检测**容器域（domain 有子域时自动切换模板）→ prompt：「本域是多个子域的父级容器，请生成：(1) 子域职责矩阵 (2) 跨子域协作架构图 (3) 核心数据流 (4) 子域导航链接。不要列举具体模块代码。」 |
| F16 | Topic prompt 代码要求 | `wiki/agent_prompts.py` | 新增泛化约束：「每个 topic 必须至少包含 1 个来自检索到的源码的**真实代码片段**，不要虚构或推测代码。如果检索结果中没有找到相关代码，请用文字描述实现思路而非编造代码。」 |

**泛化设计要点：**
- F14 不提及任何具体类名（如 FamilyTaskService），使用「本域直接拥有」vs「被本域调用但归属其他域」的泛化表述
- F15 通过代码检测子域存在性（`domain.has_subdomains`）自动决定使用哪个 prompt 模板，不硬编码域名
- F16 不限定语言（不写「Java 代码」），使用「来自源码的真实代码片段」适配任意语言仓库

**解决的 V21 问题：**
- #10: 模块交叉 → 泛化约束 Owner vs Consumer（适用于任意仓库的模块交叉场景）
- #11: 文档串域 → 泛化约束模块归属
- #6: 壳域 → 程序化检测容器域 + 专用模板
- #7: 虚构代码 → 泛化禁止虚构
- Mermaid-only topic → 泛化要求至少 1 个真实代码片段

---

## 依赖关系

```
Batch A (Slug)     ──┐
                     ├─→ 测试验证 → 部署 → 重新生成 → V22 审计
Batch B (Guards)   ──┤
  └─→ Batch C (Finalize 集成)
Batch D (元数据)   ──┤
Batch E (Prompt)   ──┘  ← 需要重新生成才看到效果
```

Batch A、B、D、E 互相独立，可并行实施。Batch C 依赖 Batch B。

---

## 测试计划

| 测试 | 对应修复 | 验证要点 |
|------|---------|---------|
| `test_sanitize_module_path_slug` | F1 | `ultronultron-basic-userclosed-friend-*` → `closed-friend-task-part-1` |
| `test_is_pinyin_slug` | F2 | `zhi-you-pei-zhi-yu-kuo-zhan` 被检测为拼音 slug |
| `test_slug_collision_detection` | F3 | 同名 slug `family-task` → 加域前缀消歧 |
| `test_slug_too_generic` | F4 | slug `family` == 域前缀 → 被拒绝 |
| `test_strip_h1_title` | F5 | `# 家族系统\n## 概述` → `## 概述` |
| `test_meta_section_expanded` | F6 | `## 章节导航`, `## 术语表` 等被检测并清除 |
| `test_strip_repeated_blockquotes` | F7 | 21 条重复术语说明 → 保留 1 条 |
| `test_dedup_code_fences` | F8 | 3 个相同代码块 → 保留 1 个 |
| `test_strip_english_self_reflection` | F9 | `> **Note**: The headings ...` 被清除 |
| `test_finalize_integration` | F10 | 全流程清洗后输出干净 |
| `test_quality_gate_shell_domain` | F11 | 214 字壳域 → heal_hint |
| `test_overview_business_domain` | F12 | overview 页 business_domain 非空 |
| `test_dangling_wikilink_removal` | F13 | 引用不存在的 topic → 链接被移除 |

---

## 风险评估

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| slug 转换错误 | 低 | 中 | 仅匹配精确的仓库名前缀重复模式；fallback 到 `{domain}-part-{n}` |
| H1 剥离误伤代码块内 `#` | 极低 | 高 | 仅匹配 content 首行非代码块内的 `# ` |
| blockquote dedup 误删有意义段落 | 低 | 中 | 仅对相似度 >80% 的连续段落去重 |
| 代码块 dedup 误删不同上下文的相同代码 | 低 | 低 | 仅对完全相同内容的 fenced block 去重 |
| 截断检测误判短代码块 | 中 | 低 | 仅标记 heal_hint 不自动删除 |
| Prompt 约束导致 overview 内容过短 | 低 | 中 | 约束仅限模块详解节，不影响概述和流程节 |

---

## 预期改善

| 指标 | V21 (当前) | Batch A-D 后 | Batch E 重新生成后 |
|------|-----------|-------------|------------------|
| Slug 质量 (bad/total) | 11/22 (50%) | **0/22 (0%)** | 0% |
| H1 泄漏 | 15/28 (54%) | **0/28** | 0 |
| Meta/元节泄漏 | 18 页 | **0 页** | 0 |
| blockquote 堆叠 | 21 条 | **0** | 0 |
| 重复代码块 | 2 页 | **0** | 0 |
| 代码截断 | ≥20 处 | heal_hint 标记 | **减少** |
| business_domain 空 | 27/28 | **0/28** | 0 |
| dangling wikilink | 12 个 | **0** | 0 |
| 壳域 | 214 字 | heal_hint | **重写** |
| 模块交叉描述 | 3 组 | 3 组 | **减少** |
| Mermaid-only topic | 59% | 59%(heal_hint) | **<30%** |
| 虚构代码 | 2 页 | 2 页 | **0** |
| 综合评分 | 6.8/10 | **7.5/10** | **8.5/10** |

---

## ~~V20 Batch E 域分解参数优化~~ 已废弃

原 V20 提案中的 Batch E 建议调整：
- `domain_budget_max` 50→18
- `domain_split_threshold` 20→30
- `embedding_merge_threshold` 0.8→0.72

**废弃原因：** 违反「业务独立性 > 模块数量」原则。强制合并会破坏独立业务域的边界。
**替代方案：** Batch E 改为 Prompt 优化，通过约束 LLM 行为解决模块交叉和壳域问题。
