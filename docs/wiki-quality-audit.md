# Wiki 生成质量审计报告

**Created:** 2026-05-25
**Audit Target:** `business_id=ultron` (dev 环境，管线 `biz-wiki-0ea14ce62358`)
**Status:** Active — 待修复

---

## 审计概览

| 指标 | 值 |
|------|-----|
| 总页面数 | 702 |
| domain_overview | 377 |
| topic | 325 |
| WikiSection 节点 | 50 |
| 重复标题 | 54 个标题重复（最高 7 次） |
| 待分配页面 | 110 |
| 英文主导页面 | 175 (25%) |
| 混合语言页面 | 62 (9%) |
| 英文标题比例 | 28.5% |
| 代码密集页面 | 41/80 (51%) |

---

## P0 — 阻塞性问题

### 1. Tree Linking 仍然失败

**现象:** `linked_business_domain=0`，110 页在"待分配页面"。
**根因:** Bug A-D 修复代码已部署但服务未重启，运行中进程使用旧代码。
**修复:** 重启服务后重新生成。

### 2. 域过度碎片化

**现象:** 377 个不同 overview slug，而实际只有 36 个叶子域。同一业务概念在多个 slug 下重复。

**典型案例 — 家族战力:**
- `family-power-management` → 家族战力管理
- `userrelationship-familypowerservice` → 家族战力
- `family-system-2` → 家族战力与成长
- `infrastructure` → 家族战力与排名（误标题）
- `family-power-rank` → 家族战力与排名

**根因:**
1. 历史页面未清理（旧 `__domains__/*` 页面残留）
2. `_SPLIT_THRESHOLD=10` 和 `_MAX_SPLIT_DEPTH=3` 为硬编码常量，不可配置
3. 三层分裂机制叠加：子域递归拆分 × topic planner 拆分 × `_maybe_split` 按标题拆分

**影响:** 用户在侧边栏看到大量相似/重复域，无法快速定位。

---

## P1 — 内容质量问题

### 3. 中英文混排严重

**现象:** 25% 页面英文主导，28.5% 标题为英文。典型模式：中文 H1 标题 + 全英文正文。

**典型案例:**
| 页面 | CN Ratio | 问题 |
|------|----------|------|
| 家庭回调服务层 (topic) | 4% | 中文标题，英文正文 "This service layer handles..." |
| 家族排名与展示 (topic) | 1% | 中文标题，英文 Overview/Components/Relationships |
| 家族榜单管理 (topic) | 9% | 全英文模板 Overview/Architecture/Components |

**根因:**
1. **双语言配置冲突:** `WikiConfig.language="en"` (compose 路径默认) vs `wiki_content_language="简体中文"` (仅域命名和父页面使用)
2. **Topic compose 节点未读取 `wiki_content_language`:** `DomainDocAgent` / `WikiPageAgent` 使用硬编码 agent_prompts，但部分模板（如 `SYSTEM_WIKI_AUTHOR`）指令为英文
3. **Output guardrail 不检查语言一致性:** 只检查覆盖率/深度，不检查语言

### 4. 两种 Overview 风格不一致

**现象:**
- **简约型** (~800 字): 每章一句话 + 章节导航 + Architecture mermaid（如 `family-chest-and-task`）
- **过度生成型** (5k+ 字): 像合并的 topic 页面，有结构损坏、重复段落（如 `family-callback-and-query`）

**根因:** Overview 生成路径不统一 — 有的走 `DomainDocAgent` 的 `domain_overview` 模板（简约），有的走 `_maybe_split` 后残留的首段（过度生成）。

### 5. 模板碎片化

**现象:** 同一域内相邻页面使用不同模板：
- 英文模板: `Overview / Components / Relationships / Architecture / See Also`
- 中文模板: `概述 / 核心业务流程 / 模块详解 / 依赖关系`

**根因:** `AGENT_WRITE_SYSTEM` 和 `SYSTEM_WIKI_AUTHOR` 定义了中文章节结构，但 `_maybe_split` 按 `##` 拆分后可能产生英文标题页面；heal 过程可能引入英文模板。

### 6. 幻觉/接地失败

**现象:**
- 发明不存在的类名: `FamilyServiceProxy`, `ServiceRegistry`, `RetryPolicy`
- 伪造链接: martinfowler CircuitBreaker 博客
- 占位符路径: `com/xxx/relation/...`
- 未解析 wikilink: `[[用户成长体系]]`（不存在的页面）

**根因:** Agent explore 阶段收集的上下文不足时，LLM 补充想象内容。`code_blocks_verified` 只验证代码块，不验证类名引用。

### 7. 管线产物泄漏

**现象:**
- `<!-- CONTEXT_GAP: ... -->` 可见于发布内容
- 重复标题（`## 依赖关系` 出现两次）
- 截断的 mermaid 图
- 质量清单表格（✅/⚠️ 表格看起来像真实审核但实际未验证）

**根因:**
- `CONTEXT_GAP` 注释未被 `finalize_node` 清理
- `_maybe_split` 和 heal 过程可能导致重复标题
- Mermaid 生成未做完整性校验

---

## P1 — 前端/Dashboard 问题

### 8. 树节点图标不区分页面类型

**现象:** 只有 `FolderOpen`（域/WikiSection）和 `FileText`（其他所有页面）两种图标。无法区分 overview、topic、module。

**可用数据:** `page_type` 字段已存在于树节点（`domain_overview`, `topic`, `module_overview` 等），前端未充分利用。

**建议图标映射:**
| page_type | 建议图标 | 描述 |
|-----------|---------|------|
| WikiSection | `FolderClosed` / `FolderOpen` | 域分类节点 |
| domain_overview | `BookOpen` | 域概览 |
| topic | `FileText` | 主题页面 |
| module_overview | `Code` | 模块页面 |

### 9. 树默认展开行为

**现象:** 用户反馈"点击后全部展开"。

**代码分析 (`WikiTopicTreeNav`):**
- `initialExpanded()` 展开所有根节点（有 children 的）
- 当树数据变化（refetch）时 `useEffect` 重新调用 `initialExpanded`

**建议:** 默认只展开第一层，手动点击逐层展开。

---

## P2 — 结构/架构问题

### 10. 重复页面标题

**现象:** 54 个重复标题，最高 7 次（"家族任务系统"）。

**根因:**
1. Topic planner 无标题去重逻辑
2. 不同域 slug 下生成了相似内容
3. `_maybe_split` 按 `##` 拆分产生的标题可能重复

### 11. Overview 与 Topic 脱节

**现象:** Overview 不能概括 Topic 内容；有的 Overview 与 Topic 叙述矛盾。

**典型案例:** `family-callback-and-query` overview 使用"三层架构"叙述，但 topic 页面使用真实的 MOA/Proxy 类名，两者不一致。

### 12. Topic 内容质量参差

**现象:**
- 部分 topic 代码密集（51% 代码为主，缺少业务解释）
- 部分 topic 结构单薄（仅 2 个标题）
- 部分 topic 长度差异巨大（2k ~ 12k 字符）

---

## 修复方案优先级

### 立即可做（不需写代码）

| # | 动作 | 预期效果 |
|---|------|---------|
| A | 重启服务应用 tree linking 修复 + LLM 并发=20 | 解决 P0-1 |
| B | 清理历史 wiki 页面后重新生成 | 减少碎片化 |

### 短期代码修复

| # | 动作 | 影响范围 | 预期效果 |
|---|------|---------|---------|
| C | 统一语言配置：compose 节点读取 `wiki_content_language` | `wiki/nodes/domain_compose.py`, `wiki/domain_doc_agent.py` | 解决 P1-3 |
| D | Topic planner 标题去重 | `wiki/domain_doc_agent.py` | 解决 P2-10 |
| E | `finalize_node` 清理 CONTEXT_GAP 注释 | `wiki/nodes/finalize.py` | 解决 P1-7 |
| F | 前端树图标区分 page_type | `WikiTopicTreeNav.tsx` | 解决 P1-8 |
| G | 前端树默认只展开第一层 | `WikiTopicTreeNav.tsx` | 解决 P1-9 |
| H | Output guardrail 增加语言一致性检查 | `wiki/domain_doc_agent.py` | 加强 P1-3 |

### 中期优化

| # | 动作 | 描述 |
|---|------|------|
| I | `_SPLIT_THRESHOLD` 和 `_MAX_SPLIT_DEPTH` 可配置化 | 通过 dashboard 控制域粒度 |
| J | `_maybe_split` 与 topic planning 互斥 | 防止双重拆分 |
| K | 生成后全局页面去重 | 基于标题+内容相似度合并 |
| L | 幻觉检测 — 类名/方法名验证 | 对比图数据库中真实节点 |

---

## 关键代码路径

| 问题 | 关键文件 |
|------|---------|
| 语言配置 | `core/config.py` (AppWikiFlags.wiki_content_language), `wiki/nodes/domain_compose.py`, `wiki/agent_prompts.py` |
| 域分解 | `wiki/nodes/graph_domain_decompose.py` (_SPLIT_THRESHOLD, _MAX_SPLIT_DEPTH) |
| Topic 规划 | `wiki/domain_doc_agent.py` (_plan_topics) |
| 内容拆分 | `wiki/domain_doc_agent.py` (_maybe_split) |
| Tree linking | `wiki/tree_linker.py`, `wiki/business_pipeline_runner.py` |
| 产物清理 | `wiki/nodes/finalize.py` |
| 前端树 | `dashboard/src/components/wiki/WikiTopicTreeNav.tsx` |
| 树图标 | `dashboard/src/components/wiki/WikiTopicTreeNav.tsx` (line 178) |

---

## Batch 1-2 实施记录

**日期:** 2026-05-26
**状态:** ✅ 已完成并部署

### 已实施修复

| Batch | 修复项 | 文件 | 状态 |
|-------|--------|------|------|
| 1 | ContentLanguage 枚举统一 | `core/config.py`, `api/models/wiki_models.py`, `wiki/pipeline_orchestrator.py` | ✅ |
| 1 | Finalize 产物清理（checklist/com-xxx/think-tag/CONTEXT_GAP/wikilink） | `wiki/nodes/finalize.py` | ✅ |
| 1 | Compose 语言解析对齐 | `wiki/nodes/domain_compose.py` | ✅ |
| 2 | 后处理语言参数化（diagram/layer） | `wiki/nodes/domain_compose.py` | ✅ |
| 2 | `_maybe_split` 语言化 + Topic cap (MAX=8) | `wiki/domain_doc_agent.py` | ✅ |
| 2 | Write user prompt 语言化 | `wiki/page_agent.py` | ✅ |
| 2 | Topic 标题 CJK bigram 去重 | `wiki/domain_doc_agent.py` | ✅ |
| 2 | Topic canonical_key + TreeLinker 叶子域优先 | `wiki/domain_doc_agent.py`, `wiki/tree_linker.py` | ✅ |

---

## Batch 1-2 部署后审计（V2 重新生成）

**日期:** 2026-05-26
**触发:** 用户手动部署 Batch 1-2 修复后重新生成全量 wiki

### 审计数据

| 指标 | V1 (修复前) | V2 (Batch 1-2 后) | 变化 |
|------|-----------|-------------------|------|
| 总页面数 | 79 | 71 | -8 ❌ |
| overview 页面 | 27 | 28 | +1 |
| topic 页面 | 52 | 43 | -9 ❌ |
| domain-01 topic 数 | 18 | 18 | 无变化 ❌ |
| closed-friend topic 数 | 17 | 17 | 无变化 ❌ |
| 家族业务域 topic | ? | 0 | 全部被清理 ❌ |
| cn_ratio < 30% 占比 | ~48% | 52% | 反而恶化 ❌ |
| `source://` 泄漏 | — | 42% 页面 | 新发现 |
| `<!-- CODE_REF -->` 泄漏 | — | 14% 页面 | 新发现 |
| `<think>` 泄漏 | 有 | 0 | ✅ 已修复 |
| quality checklist 泄漏 | 有 | 0 | ✅ 已修复 |

### 核心发现 — 三个 P0 根因

#### 1. Stale 清理误删 785/839 页（根中之根）

`_cleanup_stale_domain_pages`（`business_pipeline_runner.py` L806-808）使用 `set(domain_mapping.keys())`（~36 个顶层 slug）判断活跃域。所有嵌套子域（如 `family-core-operations`）的 slug 不在此集合中，被判定为 stale 并全部删除。

**影响链:** Agent 生成高质量中文内容 → stale 清理删除 → TreeLinker 用 static template 回填 → 用户看到空洞的 overview-only 页面 → cn_ratio 低

#### 2. 容器域 Topic Cap 未生效

`domain-01` 和 `closed-friend-relations` 已升级为容器域（有子域、无直接模块），`compose_domain_agents` 不处理容器域，`DomainDocAgent`（topic cap 所在）不被调用。18/17 个 topic 是历史残留。

#### 3. 新增产物泄漏类型

Batch 1 清理了 `<think>`/checklist/`com/xxx/`/`CONTEXT_GAP`，但遗漏了 `source://` 协议链接和 `<!-- CODE_REF -->` 注释。

### P1 发现

- **Coverage compound key bug:** `quality_report._is_module_covered` 对复合键（`repo|ClassName`）匹配失败，coverage 永远为 0
- **TreeLinker 内容覆盖:** stale 清理后 TreeLinker 用 static template 覆盖 Agent 内容，无长度保护

### 修复计划

以上问题已规划为 **Batch 2.5** 修复。详见 [`specs/2026-05-26-wiki-quality-fix-v2-design.md`](superpowers/specs/2026-05-26-wiki-quality-fix-v2-design.md) § 11。

---

*本文档为 wiki 质量审计的单一事实来源。修复完成后更新对应条目状态。*
