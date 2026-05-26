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

以上问题已在 V4 修复中一并解决（见下方 V4 修复记录）。

---

---

## V3 全量审计（2026-05-26 10:30）

**数据源:** 开发机 FalkorDB + LangGraph checkpoints (`ultron_wiki.db`)
**页面总量:** 892 pages, 5,263,429 chars

### V3 核心指标

| 指标 | V2 (Batch 1-2 后) | V3 (Batch 3-4 后) | 趋势 |
|------|-------------------|-------------------|------|
| 总页面数 | 71 | 892 | ↑ 全量生成 |
| domain_overview 页面 | 28 | ~420 | ↑ |
| topic 页面 | 43 | ~472 | ↑ |
| 唯一域 slug 数 | ~28 | ~420 | ❌ 严重碎片化 |
| 有 topic 的域 | — | ~94 (22%) | ❌ 78% 域无子页面 |
| overview < 1500 chars | — | ~50 | ❌ 薄弱概览 |
| topic < 1000 chars | — | ~10 | ⚠ 存在 stub |
| Hash 后缀域 (-xxxx) | — | 9 | ❌ 碰撞残留 |
| 数字后缀域 (-N) | — | ~27 | ❌ 多轮生成残留 |
| 类名 slug | — | ~16 | ❌ 不可读 |
| unnamed/domain-NN | — | 5 | ❌ fallback 失败 |

### P0 — 域碎片化（V3 核心问题）

**420 个域 slug 对应约 25-40 个真实业务域**（~35× 过度碎片化）。

根因叠加：
1. **历史页面未清理:** 多轮 wiki 生成累积，旧页面残留
2. **三层分裂机制:** HAC 子域递归 × topic planner × `_maybe_split` 标题拆分
3. **碰撞解决残留:** hash 后缀域（如 `closed-friend-relations-024d`）未被清理
4. **module-derived slug:** 类名直接作为域名（如 `userrelationship-familycoreservice`）

#### 语义重叠集群（按严重程度）

| 集群 | 域数量 | 严重度 | 典型 slug |
|------|--------|--------|-----------|
| 家族 (Family) | ~98 | 🔴 极严重 | `family-system-1~9`, `userrelationship-family*`, `tasksystem`, `clanrelation` |
| 用户 (User) | ~92 | 🔴 极严重 | `userprofile`, `userlevel`, `user-vip-*` (12+), `user-level-*` (15+) |
| 亲密度 (Intimacy) | ~58 | 🔴 极严重 | `intimacy-*` (35+), `im` (标题:亲密任务), handler slug |
| 挚友 (Close Friends) | ~48 | 🔴 极严重 | `closed-friend-relations` + 7 hash变体 + 数字变体 |
| IM/消息 | ~42 | 🔴 极严重 | `im-1/3/8`, `immessage-4/5`, `quick-message-*` (4+) |
| 送礼 (Gifts) | ~22 | 🟡 中等 | `gift-order-*`, `giftinteraction-*` |
| 关系/榜单 | ~24 | 🟡 中等 | `relation-rank*` (6+), `userrelation` |
| 基础设施/其他 | ~36 | 🟢 正常 | `infrastructure-*`, `callback-*` |

#### 挚友关系域碎片化详情（典型案例）

同一个 "挚友关系" 业务概念被拆为 **10+ 个独立域**:
- `closed-friend-relations` (canonical)
- `closed-friend-relations-024d`, `-4a30`, `-52b9`, `-6141`, `-c139`, `-c522`, `-fb73` (hash 碰撞)
- `closed-friend-relations-core`, `closed-friend-relations-1` (pass 变体)
- 另有 `closed-friend-system`, `closed-friend-service`, `closed-friend-space`, `closed-friend-market` 等 38 个相关 slug

### P0 — 78% 域无子页面

**~326/420 域仅有 overview，无 topic 展开页面**。这正是用户反馈的核心问题：
> "很多页面类似 `family-lifecycle-management/_overview` 没有任何有意义的内容，且没有更具体的展开页面"

根因：
1. 域过多导致 `compose_domain_agents` 只处理叶子域中的一部分
2. 容器域（有 children 无 modules）跳过 DomainDocAgent
3. 旧生成 pass 产出的域未进入新 pass 的 topic 生成流程

### P1 — 薄弱概览页面

**~50 个 overview < 1500 chars**，内容仅为：
```
# {Title}
## 子域概览
- **module-name-1**
- **module-name-2**
## 章节导航
- [[link1]] | [[link2]]
```

最短的 5 个:
| Chars | Slug | Title |
|-------|------|-------|
| 691 | `intimacy-tasks` | 亲密任务 |
| 733 | `infrastructure-1` | 数据持久化 |
| 741 | `intimacy-gift-statistics` | 亲密度送礼统计 |
| 769 | `family-chest-and-task` | 家族宝箱与任务 |
| 795 | `user-vip-and-level` | 用户VIP与等级 |

### P1 — 语言混排（仍存在）

| 问题类型 | 数量 | 示例 |
|----------|------|------|
| 英文 slug 作为用户标题 | ~7 | `userprofile`, `userbase`, `userlevel`, `appstoreinteraction` |
| Java 类名 slug | ~16 | `intimacy-absintimacytaskexecutor`, `closedfriend-closedfriendtaskhandler` |
| 中文标题 + 英文正文 | ~25-30% | `家庭回调服务层` → "This service layer handles..." |
| `source://` 协议泄漏 | 存在 | 未完全清理 |
| `<!-- CODE_REF -->` 泄漏 | 存在 | finalize 未覆盖所有路径 |

### P1 — 超长异常页面

| Path | Chars | 问题 |
|------|-------|------|
| `closed-friend-commerce/亲密圈核心服务与接口层` | 36,192 | `_maybe_split` 残留 |
| `im-service-wrapper/_overview` | 17,469 | 过度生成 |
| `tasksystem/_overview` | 17,822 | 合并 topic 残留 |
| `message-processing-chain/_overview` | 16,663 | 同上 |

### P2 — Slug 命名问题清单

| 类型 | 数量 | 示例 |
|------|------|------|
| Hash 后缀 | 9 | `*-024d`, `*-4a30`, `*-55ac`, `*-ea6b` |
| 数字后缀 | 27 | `family-system-1~9`, `im-1/3/8` |
| Java 类名 | 16 | `userrelationship-familycoreservice` |
| `unnamed*` | 4 | `unnamed`, `unnamed-1/2/5` |
| `domain-NN` | 1 | `domain-01` |
| `infrastructure-N`(误标) | 4 | `infrastructure` → "家族战力与排名" |

### 理想目标 vs 现状

| 维度 | 现状 | 理想目标 |
|------|------|---------|
| 顶层业务域 | ~420 slug | 8-12 |
| 子域(叶子) | 混在 420 中 | 25-40 |
| Topic 页面 | ~472 | 75-150 |
| 总页面 | 892 | 100-190 |
| 有 topic 的域 | 22% | 90%+ |
| overview < 1500 chars | ~50 | 0 |

### V3 修复建议

#### 紧急（P0）
1. **全量清理 + 重新生成:** 删除所有 stale `__domains__/*` 页面后重跑 wiki pipeline
2. **域合并策略:** 98 家族 slug → 4 子树, 58 亲密度 → 3 子树, 48 挚友 → 1 canonical + 子页面
3. **强制 topic 生成:** overview 生成后必须跟随 topic decompose，不允许 overview-only 域

#### 短期（P1）
4. **清理 hash/数字后缀域:** 9 hash + 27 数字 = 36 个明确的旧域可安全删除
5. **module-derived slug → 人类可读名:** `userrelationship-familycoreservice` → `family-core-service`
6. **`source://` + `CODE_REF` 清理:** 补充 finalize 路径覆盖

#### 中期（P2）
7. **域预算机制:** 限制总域数在 50 以内
8. **overview 最低内容阈值:** < 2000 chars 触发重新生成
9. **语言一致性 guardrail:** compose 全链路统一 `wiki_content_language`

---

---

## V4 修复实施记录 (2026-05-26)

**方案:** B — 图为唯一 SSoT + Pipeline 无状态化

### 已实施修复

| Batch | Task | 修复项 | 文件 | 状态 |
|-------|------|--------|------|------|
| B1 | 1 | `domain_budget_max` 配置 (默认 50) | `core/config.py` | ✅ |
| B1 | 2 | 碰撞 slug 清理 (hash/数字后缀合并) | `wiki/nodes/graph_domain_decompose.py` | ✅ |
| B1 | 3 | 域预算执行集成 | `wiki/nodes/graph_domain_decompose.py` | ✅ |
| B2 | 4 | 质量配置 flags (overview_min, cn_ratio, auto_cleanup) | `core/config.py` | ✅ |
| B2 | 5 | 语言一致性检查 (LanguageConsistencyCheck) | `wiki/output_guardrail.py` | ✅ |
| B2 | 6 | 质量门内容长度检查 (_check_min_content_length) | `wiki/nodes/quality_gate.py` | ✅ |
| B2 | 7 | Finalize 清理增强 ([undefined] 标记) | `wiki/nodes/finalize.py` | ✅ |
| B3 | 8 | summaries 优先图加载 | `wiki/pipeline_orchestrator.py` | ✅ |
| B3 | 9 | 自动清理 checkpoint | `wiki/business_pipeline_runner.py` | ✅ |

### 新增测试

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| `tests/wiki/test_domain_budget_config.py` | 8 | ✅ |
| `tests/wiki/nodes/test_collision_slug_cleanup.py` | 4 | ✅ |
| `tests/wiki/nodes/test_domain_budget_enforcement.py` | 3 | ✅ |
| `tests/wiki/test_language_guardrail.py` (+4) | 9 | ✅ |
| `tests/wiki/nodes/test_quality_gate_content_length.py` | 4 | ✅ |
| `tests/wiki/nodes/test_finalize_sanitize.py` | 5 | ✅ |
| `tests/wiki/test_pipeline_orchestrator_summaries.py` | 2 | ✅ |
| `tests/wiki/test_force_full_run_checkpoint.py` (+2) | 4 | ✅ |
| **合计** | **39** | ✅ |

### 待 wiring 项 (下次部署后验证)

- [ ] `LanguageConsistencyCheck` 需要 caller 传递 `target_language` (当前 DomainDocAgent 传 `content_language`)
- [ ] `_check_min_content_length` 需要 wiring 到 `quality_gate_node` 以触发 heal
- [ ] `auto_cleanup_checkpoint` 默认关闭，验证稳定后开启

---

## V5 全量审计（2026-05-26 15:30）

**数据源:** 开发机 FalkorDB `kb_ultron` 图，脚本 `scripts/audit_wiki_data.py`
**审计数据:** `data/wiki-audit-v5.json`（68KB）
**触发:** 用户清除 wiki + 全量重新生成（V4 修复部署后）

### V5 核心指标

| 指标 | V3 (修复前) | V5 (V4 修复后) | 变化 |
|------|-----------|----------------|------|
| 总页面数 | 892 | **55** | ✅ 去碎片化 |
| 域 slug 数 | ~420 | **35** | ✅ 大幅改善 |
| domain_overview | ~420 | **35** (1:1) | ✅ |
| **topic 页面** | ~472 | **0** | ❌ 致命回归 |
| module_overview | — | **20** (旧遗留) | ⚠ 非本轮产出 |
| thin overview (<2000) | ~50 | **1** (3%) | ✅ |
| overview 平均长度 | — | **6553 chars** | ✅ 充实 |
| 低 CN ratio 页面 | 大量 | **1** | ✅ |
| WikiSection 数 | 50 | **38** (36 domain + 2 module) | ✅ |
| tree_edges 完整性 | — | 严重不完整 | ❌ |

### P0-1 — Topic 页面完全缺失（致命）

**现象:** 35 个域全部只有 domain_overview，**0 个 topic 子页面**。

**根因:**
1. `use_orchestrator_template=True`（默认）切断了 `_write_with_outline()` topic 写入路径
2. `DocOrchestrator.generate()` 做了 `plan_topics` 规划但**未执行** topic 分页写入
3. `_maybe_split` 兜底被 `topic_split_done=True` 错误抑制
4. 内容长度（平均 6553 chars ≈ 1638 tokens）远低于 `MAX_PAGE_TOKENS=5000` 拆分阈值

**代码路径:**
```
compose_domain_agents → DomainDocAgent.generate_with_iterations
  → use_orchestrator_template=True → DocOrchestrator.generate()
    → plan_topics() ← 规划完成但结果未使用
    → 单体 write 循环 → post_process → _maybe_split
      → topic_split_done=True → 仅返回 1 个 overview
```

`_write_with_outline()`（真正的 topic 产出路径）仅存在于 `use_orchestrator_template=False` 的已废弃分支。

### P0-2 — 域拆分仍有碰撞残留

**评分: 4.5/10**

| 问题类型 | 数量 | 典型案例 |
|----------|------|----------|
| 碰撞 hash 后缀 | 1 | `closed-friend-relations-5b0a` vs `closed-friend-relations` |
| 技术/类名域 | 6 | `backdoorserviceimpl`, `statisticsbehaviorhandler`, `package-info` 等 |
| 基础设施升格为业务域 | 8 | `datasourceconfiguration`, `longliststringtypehandler-*`, `internalserviceaspect-*` |
| 三层父域重复 | 1 组 | `intimacy-system` / `intimacy-growth-system` / `intimacy-relations` |
| 标题误译 | 2 | `closed-friend` → "关闭好友"（应为"挚友"）; `user-props-and-prizes` → "用户ES查询" |

**建议目标架构:** 从 35 域合并为 **~12 个一级域**。

### P1-1 — Overview 内容质量

**评分: 6.4/10**

| 档位 | 数量 | 占比 |
|------|------|------|
| 充实 (>5000 chars) | 25 | 71% |
| 中等 (2000-5000) | 9 | 26% |
| 薄弱 (<2000) | 1 | 3% |

**Top 问题页面:**
1. `family-guild-rank-square`: 472 chars，空壳模板，英文 H1
2. `family-system`: 3423 chars，虚构英文组件名，"家庭/家族"混用
3. `intimacy-growth-system`: 3911 chars，英文 Warning 块，父域索引化
4. `closed-friend-relations`: 3361 chars，与 5b0a 子域职责重叠
5. `user-props-and-prizes`: 标题"用户ES查询"与内容"道具与奖品"不符

### P1-2 — Tree 结构严重不完整

| 层级 | 期望 | 实际 |
|------|------|------|
| WikiSpace → Section | 有 | 无直接边 |
| Section → Section (嵌套域) | 35 条 | 仅 18 条（扁平域） |
| Section → Page | 55 条 | **0** 条 |

- 55 个 WikiPage **全部孤立**（未接入导航树）
- 17 个嵌套域 section 无父子边（不可达）
- 2 个 `code_module` section 空子节点

### P2-1 — Module Overview 遗留孤岛

- 20 个 `module_overview` 来自 **2026-05-18**（比本轮早 8 天）
- 路径 `modules/_import_*.md`，**零域归属**
- 2 个内容错配（`DeviceInfoDTO` → 亲密关系任务；`FAMILY_HOME_GOTO_URL` → 家族任务）

### P2-2 — 术语不一致

| 原词 | 现有翻译变体 | 应统一为 |
|------|------------|---------|
| Closed Friend | 挚友 / 封闭好友 / 关闭好友 | **挚友** |
| Intimacy | 亲密度 / 亲密关系 | **亲密度** |
| Family | 家族 / 家庭 | **家族** |

### V5 修复优先级

| 优先级 | 修复项 | 说明 |
|--------|--------|------|
| **P0** | 修复 Orchestrator → `_write_with_outline` 断点 | 恢复 topic 页面生成 |
| **P0** | 消除 `closed-friend-relations-5b0a` 碰撞域 | `_cleanup_collision_slugs` 未覆盖 |
| **P1** | 下沉 8 个基础设施域到 platform-infrastructure | 减少业务域污染 |
| **P1** | 补全 tree_edges (Section→Page, 嵌套域边) | 修复导航树 |
| **P1** | 统一术语词表 (挚友/亲密度/家族) | 输出质量 |
| **P2** | 清理 20 个旧 module_overview 或重新归属 | 消除遗留孤岛 |

### V5 vs V3 对比总结

| 维度 | V3 评分 | V5 评分 | 变化 |
|------|--------|--------|------|
| 域碎片化 | 1/10 | **5/10** | ✅ 大幅改善 |
| Topic 覆盖 | 3/10 | **0/10** | ❌ 致命回归 |
| Overview 质量 | 3/10 | **6.4/10** | ✅ 显著提升 |
| 语言一致性 | 3/10 | **8/10** | ✅ 显著提升 |
| Tree 完整性 | 4/10 | **2/10** | ❌ 退步 |
| **总体** | **2/10** | **4/10** | ⚠ 部分改善但 topic 缺失是致命问题 |

---

## V6 全量审计（2026-05-26 18:00）

**数据源:** 开发机 FalkorDB `kb_ultron` 图，修复版 `scripts/audit_wiki_data.py`
**审计数据:** `scripts/audit_result_v6.json`, `scripts/audit_domain_content_v6.json`, `scripts/audit_tree_hierarchy_v6.txt`
**方法:** 直连 FalkorDB + 5 个独立 subagent 多角度并行分析
**触发:** 用户清除 wiki + 全量重新生成（同一代码版本，验证 V5 审计脚本 bug 修复后的真实状态）

### V6 核心指标

| 指标 | V5 (脚本有 bug) | V6 (修正后) | 变化 |
|------|----------------|-------------|------|
| 总页面数 | 55 | **55** | 无变化 |
| 域 slug 数 | 35 | **35** | 无变化 |
| domain_overview | 35 | **35** | 无变化 |
| **topic 页面** | 0 | **0** | ❌ 确认仍为 0 |
| module_overview (遗留) | 20 | **20** | 无变化 |
| Section→Page 边 | **0 (误报)** | **55** | ✅ 脚本 bug 修复 |
| Section→Section 边 | 18 (误报) | **35** | ✅ 脚本 bug 修复 |
| Space→Section 边 | 未知 | **3** | — |
| overview 平均长度 | 6553 | **6553** | 无变化 |
| thin overview (<2000) | 1 | **1** | 无变化 |
| 低 CN ratio 页面 | 1 | **1** | 无变化 |

### 重大发现：F3 (Tree 结构) 为误报

V5 审计报告 "55 个 WikiPage 全部孤立" 是**审计脚本 bug**：
- `audit_wiki_data.py` 的 tree 查询仅查了 `WikiSection→WikiSection`，漏了 `WikiSection→WikiPage`
- 实际 FalkorDB 中 55 个 Section→Page 边全部存在，**0 个孤儿页面**
- `link_pages_to_nested_tree()` 正常工作

**修复:** 已在 `audit_wiki_data.py` 中新增 Section→Page 查询（section 3b），V5 spec 中 F3 可标记为 **RESOLVED**。

### P0 — Topic 页面仍然完全缺失

**确认 0/35 域有 topic 页面**。

根因与 V5 分析一致：
1. `use_orchestrator_template=True` → `DocOrchestrator.generate()` 调用 `plan_topics()` 后丢弃结果
2. `_write_with_outline()` 仅存在于废弃路径
3. `_topic_split_done=True` 抑制了 `_maybe_split()` 后备拆分
4. 内容平均 6553 chars (~1638 tokens) 远低于 `MAX_PAGE_TOKENS=5000`

**预计修复后产出:** 45-95 topic 页面

### P1-1 — 8 个基础设施域混入 (23%)

5 个 subagent 独立分析交叉验证，确认 10 个域应被过滤/合并：

| 域 | 类型 | 建议操作 |
|----|------|---------|
| `datasourceconfiguration` | Spring 配置类 | 合并到 `__infrastructure__` |
| `package-info` | Java 包元数据 | 删除 |
| `longliststringtypehandler-*` | MyBatis TypeHandler | 合并到 `user-profile-and-extend-data` |
| `internalserviceaspect-*` | AOP 切面 | 合并到 `__infrastructure__` |
| `backdoorserviceimpl` | 调试后门 | 删除或合并到 `__infrastructure__` |
| `statisticsbehaviorhandler` | 单一 Handler | 合并到 `intimacy-relations` |
| `system-message-push` | 共享 IM 通道 | 合并到 `__infrastructure__` |
| `dealer-identity-service` | 身份查询封装层 | 合并到 `user-profile-and-extend-data` |
| `intimacy-data-cleanup` | 单一 Kafka 回调 | 合并到 `intimacy-growth-system` |
| `family-data-access-and-cache` | DAL/缓存层 | 合并到 `family-core-operations` |

### P1-2 — 域碰撞/重复 (3 组)

| 重复组 | 问题 |
|--------|------|
| `closed-friend-relations` + `closed-friend-relations-5b0a` | MD5 碰撞后缀，同一业务 |
| `intimacy-system` + `intimacy-growth-system` | 语义重叠父域 |
| `closed-friend-task-execution` | 错误嵌套在 `intimacy-system` 下 |

### P1-3 — 内容质量评分矩阵

| 档位 | 数量 | 典型代表 |
|------|------|---------|
| ≥4.5/5 (优秀) | 13 (37%) | `closed-friend-relations-5b0a`, `family-core-operations`, `intimacy-relations` |
| 4.0-4.4 (良好) | 10 (29%) | `app-store-rating-popup`, `closed-friend-task-execution`, `intimacy-task-execution` |
| 2.5-3.8 (问题) | 8 (23%) | `package-info`, `intimacy-growth-system`, `closed-friend-relations` |
| ≤2.5 (严重) | 4 (11%) | `family-guild-rank-square` (1.3), `family-system` (2.3), `intimacy-system` (2.3) |

**关键质量问题:**
- `family-guild-rank-square`: 472 字空壳，agent 失败 skeleton 被发布
- `family-system`, `intimacy-system`: 父域概述中出现**代码库不存在的组件名称** (幻觉)
- `package-info`: ~50% 英文，标题 "关系管理" 与实际内容不符
- `closed-friend-task-execution`: 标题"关闭好友"应为"挚友"

### P2 — 其他问题

- **Tree 层级扁平:** 18/35 域直接挂 `__root__`，业务+基础设施混杂
- **20 个遗留 module_overview:** 来自 2026-05-18，路径 `modules/_import_*`，价值低
- **语言混排:** `package-info`、`intimacy-growth-system`、`statisticsbehaviorhandler` 有显著英文段落
- **前端 WikiTopicTreeNav key 碰撞风险:** WikiSection 节点 `path=""` 可能导致 React key 冲突

### V6 vs V5 对比

| 维度 | V5 评分 | V6 评分 | 变化 |
|------|--------|--------|------|
| 域碎片化 | 5/10 | **5/10** | 无变化（同一生成） |
| Topic 覆盖 | 0/10 | **0/10** | 确认为 0 |
| Overview 质量 | 6.4/10 | **6.4/10** | 无变化 |
| 语言一致性 | 8/10 | **8/10** | 无变化 |
| **Tree 完整性** | **2/10** | **9/10** | ✅ 重大修正（V5 为脚本 bug） |
| **总体** | **4/10** | **5.5/10** | ✅ Tree 修正后提升 |

### V6 修复优先级（更新）

| 优先级 | 修复项 | 原状态 | 新状态 |
|--------|--------|--------|--------|
| **P0** | F1: Topic 生成 (Orchestrator hook) | 待修复 | **待修复** |
| **P1** | F2: 基础设施域过滤 | 待修复 | **待修复** |
| **P1** | ~~F3: Tree 结构补全~~ | 待修复 | **✅ RESOLVED (脚本 bug)** |
| **P2** | F4: 术语一致性 | 待修复 | **待修复** |
| **P0** | 新增: 拒绝发布 skeleton 空壳页面 | — | **待修复** |
| **P1** | 新增: 父域概述增加代码溯源约束 | — | **待修复** |

---

*本文档为 wiki 质量审计的单一事实来源。修复完成后更新对应条目状态。*
