# Wiki 生成质量审计报告

**Created:** 2026-05-25
**Audit Target:** `business_id=ultron` (dev 环境)
**Status:** Active — V17 四维 Subagent 深度审计完成
**最新审计:** V17 (2026-05-27) — 4 subagent × 多维度代码+数据联合审计

---

## 历史修复概要

| 版本 | 日期 | 总页面 | 域数 | Topic | 核心改善 | 核心问题 |
|------|------|--------|------|-------|---------|---------|
| V1 | 05-25 | 702 | 377 | 325 | 首次审计 | 碎片化 420 slug, 25% 英文, 产物泄漏 |
| V3 | 05-26 AM | 892 | ~420 | ~472 | 全量生成 | 35× 过度碎片化, 78% 域无 topic |
| V5/V6 | 05-26 PM | 55 | 35 | 0 | 域预算 50, 碰撞清理, 语言检查 | Topic 致命缺失, 8 infra 域混入 |
| V7 | 05-26 17:40 | 82 | 28 | 34 | Topic 恢复, Infra 过滤 | 34 topic 孤儿, 35% 英文化 |
| V10 | 05-26 19:30 | 84 | 27 | 37 | 树挂载 100%, stub 消除 | 命名碰撞, 40% topic 英文, 空壳嵌套 |
| V13 | 05-26 19:31 | 63 | 19 | 24 | 域压缩, CJK path 清零, unnamed 清零 | Explore 超时跳 Topic, 87% hash slug |
| V15 | 05-27 AM | 84 | 23 | 41 | Topic 大幅恢复(+71%), 域覆盖扩展 | 幻觉内容, 术语错挂, 嵌套回归 |
| V16 | 05-27 | 36 | 18 | 18 | 幻觉门禁, 术语注入, camelCase slug, infra 过滤 | 78% 域无 topic, 壳域幻觉, 渲染损坏 |
| **V17** | **05-27** | **36** | **18** | **18** | **代码级深度审计** | **门禁逻辑缺陷, 渲染盲区, 可观测性缺失** |

### 已部署修复汇总

| Batch | 修复项 | 状态 |
|-------|--------|------|
| V4 B1-B3 | 域预算, 碰撞清理, 语言检查, summaries 加载 | ✅ |
| V5 Design | Topic 生成 hook, Infra 过滤, Skeleton gate | ✅ |
| V6 Batch A-C | CN ratio 硬门禁, slug normalize, 子域 dedup 数字后缀, 跨层去重 | ✅ |
| V6 Topic Fix | Topic prompt 中文化, `domain_topic_path` ASCII 化, slug LLM 生成 | ✅ |
| V15 Fix A | plan_topics 注入 term_glossary + prompt 示例域名中性化 | ✅ |
| V15 Fix B | finalize 幻觉检测门禁(编造%/SLA) + stub reject(1500) + CN ratio 硬门禁(0.25) | ✅ 但有逻辑缺陷 |
| V15 Fix C | `_is_infra_slug` 扩展 tracing/aspect/interceptor + 域深度限制 2 | ✅ |
| V15 Fix D | normalize_slug camelCase 拆分 (MemberStatisticsAccount→member-statistics-account) | ✅ |

---

## 历史审计归档

> **V10** (05-26): 84 页, 27 域, 37 topic。总评 4.9/10。核心成就：树挂载 100%。遗留：命名碰撞、40% 英文化。
>
> **V13** (05-26): 63 页, 19 域, 24 topic。总评 6.3/10。核心成就：深度扁平化、CJK path 清零。遗留：87% hash slug。
>
> **V15** (05-27): 84 页, 23 域, 41 topic (+71%)。总评 6.6/10。核心成就：Topic 大幅恢复、英文 H2 从 21%→7%。遗留：4 页幻觉、术语错挂 11 topic、嵌套深度 3。
>
> **V16** (05-27): 36 页, 18 域, 18 topic。总评 6.4/10。核心成就：嵌套 3→1、幻觉 4→1、slug 清零。遗留：78% 域无 topic、渲染损坏、stub 回归。
>
> 详细记录见 `docs/superpowers/specs/2026-05-26-wiki-quality-fix-v6-design.md`。

---

## V17 四维 Subagent 深度审计（2026-05-27）

**数据源:** 开发机 FalkorDB `kb_ultron` 图（SSH 实时获取，含完整 Markdown 正文 402KB）
**审计方法:** 4 专项 subagent 联合审计
- **Agent A:** 内容质量深度审计（幻觉、stub、模板化、语言混杂）
- **Agent B:** 架构结构审计（域拆分、树结构、slug、覆盖缺口根因）
- **Agent C:** 管线代码审计（门禁逻辑 bug、竞态、错误处理）
- **Agent D:** 横切面审计（渲染质量、可观测性、跨仓库污染）

### V17 核心指标（与 V16 对比无变化，V17 重点在代码层面根因分析）

| 指标 | V16 | V17 (当前) | 变化 |
|------|-----|------------|------|
| 有效页面数 | 36 | **36** | 持平 |
| domain_overview | 18 | **18** | 持平 |
| topic 页面 | 18 | **18** | 持平 |
| L1 域数 | 18 | **13** (按 __root__ 子节点) | 审计口径修正 |
| 有 topic 的域 | 4 (22%) | **4 (22%)** | 持平 |
| 无 topic 的域 | 14 (78%) | **14 (78%)** | 持平 |
| 最大树深度 | 1 → 实际 3 | **3** (从 __root__ 起算) | 修正 |
| 幻觉内容 | 1 页 | **4 页 (11%)** | ❌ 恶化（V16 审计脚本漏报 3 页） |
| stub topic | 3 | **3** | 持平 |
| 渲染损坏 | 6 页 | **6 页** | 持平 |
| 低 CN ratio | 1 | **2** | ❌ 新发现 1 页 |
| 模板化套话 | 未量化 | **13/36 页 (23%)** | 🆕 量化 |
| 门禁逻辑缺陷 | 未审计 | **3 个 CRITICAL** | 🆕 代码审计发现 |

---

## V17 CRITICAL 问题（代码级根因分析）

### P0-A — stub 门禁绕过：长度测量在清理之前

**严重度:** CRITICAL — 3 个 stub topic (368/753/887 字符) 绕过了 `topic_min_publish_chars=1500` 门禁

**根因代码:** `wiki/nodes/finalize.py:316-324`

```python
raw_content_len = len(page.get("raw_content", ""))  # ← 测量清理前长度
if raw_content_len < min_publish:                      # ← 用清理前长度判断
    reject(page)
```

**机制:**
1. LLM 生成 1500+ 字符的原始内容（含 CONTEXT_GAP 标记、thinking 标签、fake source 等）
2. `_sanitize_published_content()` 清理后只剩 368-887 字符的有效内容
3. 门禁检查的是清理前的 `raw_content_len`（>= 1500），放行
4. 最终发布的是清理后的 stub 内容

**修复:** `finalize.py:317` 改为测量清理后长度 `len(content) < min_publish`

---

### P0-B — 幻觉门禁不对称：Overview 页永不拒绝

**严重度:** CRITICAL — `user-basic-data/_overview` 含 6+ 条编造指标，仅贴警告横幅，未拒绝发布

**根因代码:** `wiki/nodes/finalize.py:342-358`

```python
if is_overview or is_topic:           # 检测 overview 和 topic
    flags = _detect_fabricated_metrics(content)
    if flags:
        if is_topic and not is_topic_index:  # ← 仅 topic 拒绝
            continue                          # ← overview 只加 banner
        page["content"] = _add_warning_banner(page["content"], flags)
```

**影响:** 4 页幻觉中，2 页是 overview（`user-basic-data/_overview`, `用户基础数据` topic），overview 被允许发布含编造 SLA/P99/可用性指标的内容。

**另外:** `_FABRICATED_PERCENT_RE` (`r"[↑↓+\-]\s*\d+\.?\d*\s*%"`) 过于宽泛，会误报 "增长了 5%" 等合法中文表述，削弱门禁可信度。

**修复:** Overview 也应拒绝或至少进入 heal 循环；正则需上下文感知。

---

### P0-C — 渲染质量零检测：空代码块/空 WikiLink 无门禁

**严重度:** CRITICAL — 6 页含空代码块、空 WikiLink，管线中无任何代码检测此类问题

**根因:** `_strip_fake_source_lines()` 清除 fake source 后留下空代码块，`_sanitize_published_content()` 仅检查代码围栏配对（偶数个 ```），不检测内容为空。

**受影响页面:**
| 页面 | 问题 |
|------|------|
| dealer-and-payment-data | 3 处空 `java` 代码块 |
| family-task-execution | 空代码块 |
| gift-order-callback-handling | 空代码块 + 5 处空 `[[]]` |
| im-one-link | 2 处空代码块 |
| 亲密关系消息与推送 | 空代码块 |
| 用户关系管理 | 空代码块 |

**修复:** 在 `_sanitize_published_content()` 添加：
```python
content = re.sub(r"```\w*\s*\n\s*```", "", content)  # 空代码块
content = re.sub(r"\[\[\s*\]\]", "", content)          # 空 WikiLink
```

---

### P0-D — CN Ratio 门禁三处不一致

**严重度:** HIGH — 同一检查在 3 个位置实现，阈值/触发条件不同

| 位置 | 阈值 | 触发条件 | 行为 |
|------|------|---------|------|
| `quality_gate.py:238` | 0.4 | 需显式 `content_language` | 软门禁 → heal |
| `finalize.py:331` | 0.25 | 回退到 state config | 硬门禁 → reject |
| `heal.py:69` | 0.25 | — | heal 后检查 |

**问题:** `quality_gate.py:236` 要求 `content_language` 显式设置且为中文才触发。如果页面无显式 `content_language`，CN ratio 检查被完全跳过。`finalize.py` 使用 `_resolve_page_content_language` 回退更健壮，但意味着 quality_gate 浪费一个 heal 周期。

**低 CN 页面:** `家族消息与事件驱动` (cn=0.159) — Overview 段落全英文（~200 词），因 `_normalize_headings_to_chinese` 只处理标题不处理段落内容。

---

## V17 HIGH 问题

### P1-A — Topic 覆盖缺口根因：`<=5` 模块硬门槛

**文件:** `wiki/domain_doc_agent.py:544-548`

```python
if len(module_names) <= 5:
    return None  # ← 5 个以下模块的域永远不会生成 Topic
```

**影响:** 14/18 域无 Topic (78%)。其中 8 个域 overview > 4000 字符（内容丰富），但因模块数 ≤5 被静默跳过。

**受影响域:**
| 域 | Overview 长度 | 模块数（推断） |
|----|-------------|--------------|
| user-relation-management | 8038 | ≤5 |
| app-store-rating-popup | 7800 | ≤5 |
| relation-rank | 7251 | ≤5 |
| im-one-link | 6472 | ≤5 |
| quick-message | 6441 | ≤5 |
| user-level-trial | 4507 | ≤5 |
| prize-distribution | 4388 | ≤5 |
| family-task-execution | 4409 | ≤5 |

**修复:** 增加内容长度/实体数量作为辅助拆分信号，而非仅依赖模块计数。

---

### P1-B — Heal 循环 Off-by-One

**文件:** `wiki/pipeline_graph.py:221`

```python
if total_heal_cycles > max_total:  # 应为 >=
```

`heal_loop_max_total_attempts=10` 时实际允许 11 次循环。

---

### P1-C — Tracing Span 栈损坏

**文件:** `wiki/agents/tracing.py:78-80`

子 span 后于父 span 结束时，`end_span` 截断栈导致后续 span 的 `parent_id=None`，span 树断裂。静默数据损坏，无异常抛出。

---

### P1-D — JsonlTraceProcessor 同步阻塞事件循环

**文件:** `wiki/agents/tracing.py:108`

每次 span 结束执行同步文件 I/O `open()/write()`，在高并发 tool call 场景下阻塞 asyncio 事件循环。

---

### P1-E — PipelineConcurrency 缓存永不过期

**文件:** `wiki/pipeline_concurrency.py:18`

`_cache: ClassVar[dict[str, asyncio.Semaphore]] = {}` 类级别缓存。配置变更后旧 semaphore 持久存在，直到进程重启。`quality_l3` 错误映射到 `compose_concurrency`（默认 16），L3 LLM-as-judge 可能 16 并发打爆 rate limiter。

---

### P1-F — `_enforce_limit` 空字符串死循环

**文件:** `wiki/page_agent.py:416-425`

第二个 while 循环中，若条目为空字符串，`total -= len(lst[0])` 减 0，`total` 永不减少，循环无限。

---

## V17 MEDIUM 问题

### P2-A — 模板化套话泛滥

"高内聚、低耦合" 出现在 13/36 页 (23%)，"显著提升" 6 页，"核心价值在于" 6 页，"分层架构设计" 6 页。需在 compose prompt 中添加禁用短语列表。

### P2-B — 跨域同名 Topic

"用户基础数据" 同时出现在 `user-business-capability` 和 `user-mdp-wrapper`，标题完全相同但视角不同，导致 WikiLink 歧义。

### P2-C — 重复 H2 段落

`家族关系与权限` 有 4 个 "## 相关主题"；`用户VIP体系` 重复 "## 关键实现"；`用户关系管理` 重复 "## 相关主题" x3。去重逻辑仅检测连续重复，非连续重复漏过。

### P2-D — Slug 命名错配

| slug | title | 问题 |
|------|-------|------|
| `long-domain` | 类型转换 | Java keyword 泄漏 + 名实不符 |
| `quick-message` | ES客户端封装 | slug 与 title 完全不匹配 |
| `intimacy-relations-closed-friend-closed-friend` | 亲密度关系核心 | "closed-friend" 重复 |

### P2-E — 英文段落污染

`家族消息与事件驱动` cn_ratio=0.159，Overview 段落全英文。`_ENGLISH_TO_CHINESE_HEADINGS` 只映射标题，不处理 `> **Overview**:` 标记块。

---

## V17 LOW / 可观测性问题

### P3-A — 可观测性缺失

| 缺失项 | 影响 |
|--------|------|
| 无 run_id/correlation_id | 无法追溯坏页到特定管线运行 |
| 无每页质量评分日志 | quality_gate 仅输出聚合计数 |
| 无发布/拒绝计数器 | finalize 只打 warning，无 metrics |
| heal 效果未追踪 | 不知道 heal 是否改善了分数 |
| heal 原因未记录 | `pages_to_heal` 返回但未 log 原因 |

### P3-B — 跨仓库污染

20 个 `ultron/ultron-relation` 的 module_overview 页与 `ultron` 域页共存于同一图，污染审计指标。`ultron-basic-user` repo section 为空壳（0 子节点）。

### P3-C — `_sanitize_published_content` 步骤编号混乱

注释编号 "5." → "5.5" → "5.6" → "5.7" → "6" → "7" → "8"，不一致，信号未完成重构。

---

## V17 四维评分

| 维度 | 审计员 | V16 | V17 | 变化 | 说明 |
|------|--------|-----|-----|------|------|
| Overview 质量 | A | 6.0 | **5.5** | -0.5 | 幻觉页从 1→4（V16 漏报），壳域+渲染损坏 |
| Topic 内容质量 | B | 5.5 | **5.0** | -0.5 | 3 stub 持平，门禁代码确认有逻辑缺陷 |
| 域拆分合理性 | C | 4.0 | **4.0** | 持平 | 根因确认为 `<=5` 模块硬门槛，非策略问题 |
| 代码健壮性 | D | — | **4.5** | 🆕 | 3 个 CRITICAL 门禁缺陷，5 个 HIGH 并发/循环 bug |
| 内容真实性 | — | 8.0 | **6.5** | -1.5 ❌ | 幻觉门禁对 overview 不拒绝，正则误报率高 |
| 语言一致性 | — | 7.5 | **7.0** | -0.5 | 英文段落污染未被标题映射覆盖 |
| 嵌套/树结构 | — | 9.0 | **9.0** | 持平 | 深度 3 正常，空壳 0 |
| Path 规范性 | — | 9.0 | **8.0** | -1.0 | slug 命名错配 2 处 + 重复段 1 处 |
| **总体** | — | **6.4** | **5.7** | **-0.7** | 代码审计暴露门禁系统性缺陷，总分下调 |

---

## 修复优先级路线图

### Phase 1: 门禁修复（阻止坏内容发布）

| # | 修复 | 文件 | 预期效果 |
|---|------|------|---------|
| 1 | stub 检测改用清理后长度 | `finalize.py:317` | 3 stub 被正确拒绝 |
| 2 | 幻觉门禁对 overview 也拒绝 | `finalize.py:342-358` | 4 幻觉页全部拦截 |
| 3 | 添加空代码块/WikiLink 清理 | `finalize.py:_sanitize_published_content` | 6 渲染问题页修复 |
| 4 | CN ratio 门禁统一逻辑 | `quality_gate.py` / `finalize.py` | 消除三处不一致 |
| 5 | 修正 heal 循环 off-by-one | `pipeline_graph.py:221` | 严格限制 heal 次数 |

### Phase 2: 覆盖率提升

| # | 修复 | 文件 | 预期效果 |
|---|------|------|---------|
| 6 | 增加内容长度作为 topic 拆分信号 | `domain_doc_agent.py:544` | 78%→~40% 无 topic 率 |
| 7 | 模板化套话黑名单 | compose prompt | "高内聚低耦合" 从 23%→<5% |
| 8 | 英文段落强制中文化 | compose prompt + finalize | cn_ratio<0.25 页面清零 |

### Phase 3: 健壮性提升

| # | 修复 | 文件 | 预期效果 |
|---|------|------|---------|
| 9 | 重复 H2 全局去重（非仅连续） | `finalize.py:112-123` | 4 页重复 H2 修复 |
| 10 | tracing span 栈修复 | `tracing.py:78-80` | 消除静默数据损坏 |
| 11 | JsonlTraceProcessor 异步化 | `tracing.py:108` | 消除事件循环阻塞 |
| 12 | PipelineConcurrency 缓存刷新 | `pipeline_concurrency.py` | 配置变更生效 |
| 13 | `_enforce_limit` 空字符串防护 | `page_agent.py:416-425` | 消除死循环风险 |

### Phase 4: 可观测性

| # | 修复 | 文件 | 预期效果 |
|---|------|------|---------|
| 14 | 注入 run_id 到 WikiPipelineState | `pipeline_graph.py` | 坏页可追溯 |
| 15 | 每页质量评分日志 | `quality_gate.py` | 调试效率提升 |
| 16 | 发布/拒绝 metrics 计数器 | `finalize.py` | 运维可观测 |

---

## V17 域树结构

```
WikiSpace:ultron
├── __root__ (13 L1 域, 最大深度 3 层)
│   ├── app-store-rating-popup [评分弹窗] ov=7800 topics=0
│   ├── dealer-and-payment-data [经销商与支付] ov=5678 topics=0
│   ├── family-system [家族业务逻辑] ov=5983 topics=6
│   │   ├── 家族关系与权限 (5772)
│   │   ├── 家族核心管理 (3557)
│   │   ├── 家族任务与奖励 (1909)
│   │   ├── 家族数据同步与搜索 (753) ← stub
│   │   ├── 家族系统集成与扩展 (368) ← stub
│   │   └── 家族消息与事件驱动 (1777, cn=0.159) ← 低CN
│   ├── family-task-execution [家族任务执行] ov=4409 topics=0
│   ├── gift-order-callback-handling [送礼订单回调] ov=4205 topics=0
│   ├── im-one-link [系统消息推送] ov=6472 topics=0
│   ├── intimacy-system [亲密关系] (壳域, 3 子域)
│   │   ├── family-task-execution [家族任务执行]
│   │   └── intimacy-relations-closed-friend-closed-friend [亲密度关系核心] ov=5688 topics=6
│   ├── long-domain [类型转换] ov=3763 topics=0 ⚠ slug错配
│   ├── prize-distribution [奖品发放] ov=4388 topics=0
│   ├── quick-message [ES客户端封装] ov=6441 topics=0 ⚠ slug错配
│   ├── relation-rank [关系榜单] ov=7251 topics=0
│   ├── user-basic-data [用户基础数据] (壳域, 3 子域) ov=3833 ⚠ 幻觉
│   │   ├── user-business-capability [用户业务能力] ov=6726 topics=2
│   │   ├── user-mdp-wrapper [用户MDP封装] ov=5756 topics=4 (含 1 stub)
│   │   └── user-profile-query [用户资料查询] ov=6110 topics=0
│   ├── user-level-trial [等级试用] ov=4507 topics=0
│   └── user-relation-management [关系管理] ov=8038 topics=0
├── repo:ultron/ultron-basic-user (空壳, 0 子节点)
└── repo:ultron/ultron-relation (20 module_overview, 与域体系断链)
```

---

## V17 综合结论

> **V17 是首次代码级深度审计版本，从"数据表象"深入到"代码根因"。**
>
> **核心发现:** 3 个 CRITICAL 门禁逻辑缺陷 — stub 长度检测在清理前测量、幻觉门禁对 overview 不拒绝、渲染质量零检测。这些缺陷解释了为什么 V15/V16 部署了门禁代码但坏内容仍通过。
>
> **结构性问题不变:** 78% 域无 topic 根因是 `len(module_names) <= 5` 硬门槛，非策略问题。
>
> **新增 HIGH 问题:** tracing span 栈损坏、同步 I/O 阻塞事件循环、并发 semaphore 缓存过期、`_enforce_limit` 潜在死循环。
>
> **总分下调:** 从 6.4→5.7，因代码审计暴露门禁系统性不可信。
>
> **下一步优先:** Phase 1 门禁修复（5 项，预计 1-2 天），修复后全量重新生成验证。

---

*本文档为 wiki 质量审计的单一事实来源。修复完成后更新对应条目状态。*
