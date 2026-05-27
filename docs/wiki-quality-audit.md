# Wiki 生成质量审计报告

**Created:** 2026-05-25
**Audit Target:** `business_id=ultron` (dev 环境)
**Status:** Active — V15 全文内容深度审计完成
**最新审计:** V15 (2026-05-27 10:30) — 多 subagent 全文内容逐页深度分析

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
| **V15** | **05-27** | **84** | **23** | **41** | **Topic 大幅恢复(+71%), 域覆盖扩展** | **幻觉内容, 术语错挂, 嵌套回归** |

### 已部署修复汇总

| Batch | 修复项 | 状态 |
|-------|--------|------|
| V4 B1-B3 | 域预算, 碰撞清理, 语言检查, summaries 加载 | ✅ |
| V5 Design | Topic 生成 hook, Infra 过滤, Skeleton gate | ✅ |
| V6 Batch A-C | CN ratio 硬门禁, slug normalize, 子域 dedup 数字后缀, 跨层去重 | ✅ |
| V6 Topic Fix | Topic prompt 中文化, `domain_topic_path` ASCII 化, slug LLM 生成 | ✅ |

---

## V10/V13 审计（已归档）

> **V10** (2026-05-26 19:30): 84 页, 27 域, 37 topic。核心成就：树挂载 100%、stub 清零、overview 质量提升。遗留：命名碰撞（unnamed/hash/-0d4c）、40.5% topic 英文化、66.7% 域无 topic、域错挂。总评 4.9/10。
>
> **V13** (2026-05-26 19:31): 63 页, 19 域, 24 topic。核心成就：域扁平化（最大深度 1 层）、CJK path 清零、unnamed/hash slug 清零、低 CN ratio 页 15→2。遗留：Explore 超时跳 topic（Bug 1）、Entity Role `HAS_BUSINESS_LOGIC` 恒为 0（Bug 2）、87.5% topic hash slug、Java 类型泄漏（abs/long）。总评 6.3/10。
>
> 详细记录见 `docs/superpowers/specs/2026-05-26-wiki-quality-fix-v6-design.md`。

---

## V15 全文深度审计（2026-05-27）— 当前生成

**数据源:** 开发机 FalkorDB `kb_ultron` 图（SSH 实时获取）
**审计数据:** `data/wiki-audit-v15-full.json`（639KB，含完整 Markdown 正文）
**方法:** 多专项 subagent 全文内容逐页深度分析（Overview 质量 / Topic 质量 / 域架构 / 路径规范）
**触发:** V6 代码修复 + V13 bug 修复后全量重新生成

### V15 核心指标

| 指标 | V13 (上一次) | V15 (当前) | 变化 |
|------|-------------|------------|------|
| 总页面数 | 63 | **84** | +33% |
| domain_overview | 19 | **23** | +21% |
| **topic 页面** | 24 | **41** | **+71% ✅✅** |
| module_overview (遗留) | 20 | **20** | 仍未清理 |
| L1 域数 | 19 | **15** | -21% ✅ 合并 |
| 域 slug 数（含子域） | 19 | **23** | +21% (含子域) |
| 有 topic 的域 | 6 (32%) | **9 (39%)** | +7pp ✅ |
| 无 topic 的域 | 13 (68%) | **14 (61%)** | 仍高 |
| 最大树深度 | 1 层 | **3 层** | ❌ 嵌套回归 |
| 空壳中间节点 | 0 | **4** | ❌ 新增 |
| 重复标题 | 0 | **2 组** | ❌ 回归 |
| slug 问题 | 2 (abs/long) | **3** | 仍有 |
| 幻觉内容 | 未检测 | **4 页 (5%)** | 🆕 首次检测 |
| 术语错挂 | 未检测 | **5 个** | 🆕 首次检测 |
| Section→Page 挂载 | 63/63 (100%) | **84/84 (100%)** | ✅ |
| 低 CN ratio 页面 (<0.3) | 2 | **6** | ❌ 恶化 |
| Overview 平均长度 | 6508 | **5405** | -17% |
| Overview 最小长度 | 3041 | **3128** | 持平 |
| Topic 平均长度 | 5864 | **5601** | 持平 |
| Topic 最小长度 | 363 | **586** | ✅ 改善但仍为 stub |
| 实际英文 H2 的 topic | 5/24 (21%) | **3/41 (7%)** | ✅ 大幅改善 |

### V15 域树结构

```
ROOT (15 L1 域, 最大深度 3 层)
├── app-store-star-popup [星标弹窗策略] ov=1 topics=0
├── closed-friend-relations [挚友关系] ov=1 topics=0  ← shell, CN=0.269
│   ├── closed-friend-behavior-events [挚友行为事件] ov=1 topics=5  ⚠ 5 topic 标题全为「家族*」
│   └── closed-friend-space [挚友空间] ov=1 topics=6  ⚠ 6 topic 用「好友」而非「挚友」
├── family-system [家族系统] ov=1 topics=0  ← shell, 幻觉内容
│   ├── family-activity-and-interactive-events [家族互动与活跃] ov=1 topics=6
│   └── distributed-tracing-and-exception-handling [链路追踪] ov=1 topics=0  ⚠ infra 错挂
├── intimacy-system [亲密度系统] ov=1 topics=0  ← shell
│   ├── closed-friend-task-execution [关闭好友任务] ov=1 topics=0  ⚠ 错挂
│   └── intimacy-growth-and-tasks [亲密度成长与任务] ov=1 topics=0  ← shell, 幻觉内容
│       ├── intimacy-growth-and-reminders [亲密度成长与提醒] ov=1 topics=4
│       └── intimacy-growth-logic [亲密度成长] ov=1 topics=3
├── gift-order-callback-handlers [送礼订单回调] ov=1 topics=4
├── guild-artist-join [艺人入会] ov=1 topics=0
├── imonelink [系统消息推送] ov=1 topics=0  ⚠ classname 泄漏 slug
├── long-domain [数据类型转换] ov=1 topics=0  ⚠ Java keyword 泄漏
├── memberstatisticsaccount [会员统计账户] ov=1 topics=0  ⚠ classname 泄漏, CN=0.202
├── prize-distribution [奖品发放] ov=1 topics=0
├── quick-message [ES客户端] ov=1 topics=0  ⚠ slug/title 不匹配
├── dealer-info-query [经销商查询] ov=1 topics=0
├── user-behavior-and-vip-status [用户行为与关系] ov=1 topics=4
├── user-core-info [用户核心信息] ov=1 topics=4
└── user-profile-and-level [用户资料与等级] ov=1 topics=5
```

### Topic 分布

| 域 | Topic 数 | 最小/最大/平均 chars |
|----|----------|---------------------|
| `closed-friend-behavior-events` | 5 | 3348/6040/4690 |
| `closed-friend-space` | 6 | 3496/7537/5361 |
| `family-activity-and-interactive-events` | 6 | 1345/8486/5582 |
| `gift-order-callback-handlers` | 4 | 3330/6707/5302 |
| `intimacy-growth-and-reminders` | 4 | 1653/8508/5988 |
| `intimacy-growth-logic` | 3 | 2666/8378/5186 |
| `user-behavior-and-vip-status` | 4 | 3814/6881/5928 |
| `user-core-info` | 4 | 6994/10261/8033 |
| `user-profile-and-level` | 5 | 586/6285/4792 |

---

### P0-1 — LLM 幻觉内容（4 页，5%）

**严重度:** Critical — 编造不存在的业务场景和虚假数据

| 页面 | 幻觉类型 | 具体内容 |
|------|---------|---------|
| `family-system` overview | 场景+数据编造 | 虚构「健身挑战/儿童看护/IoT网关」功能场景，编造百分比数据 |
| `closed-friend-relations` overview | SLA+日期编造 | 编造 SLA≤3s/P95<15ms/RTO<30s、虚构故障复盘日期(2024-08-12) |
| `intimacy-growth-and-tasks` overview | 指标编造 | 编造「留存+12.3%、任务完成+21.7%」无来源业务数据 |
| `user-core-info` topic | 元数据幻觉 | 编造「中文占比45.2%」自指元数据 |

**根因:** LLM 生成时 prompt 未明确禁止编造业务指标和 SLA 数据；finalize 阶段无幻觉模式检测。

**修复方案:**
- `agent_prompts.py`: AGENT_WRITE_SYSTEM 增加禁令「严禁编造任何性能指标(SLA/P95/RTO)、业务数据(留存率/完成率)、故障复盘日期或未在代码中出现的功能场景」
- `finalize.py`: 增加幻觉模式检测门禁（正则匹配百分比数据/SLA 模式/日期模式 → 标记 `hallucination_detected`）
- `output_guardrail.py`: 增加 hallucination warning 当检测到编造模式

---

### P0-2 — 术语错挂（全文验证）

**严重度:** Critical — 页面标题/slug 与实际描述内容完全不匹配

| 域/页面 | slug/标题 | 实际内容描述 | 问题 |
|---------|----------|------------|------|
| `closed-friend-behavior-events` 的 5 个 topic | 标题全为「家族*」 | 内容 100% 描述 ClosedFriend*Handler | 标题-内容完全不匹配 |
| `closed-friend-space` 的 6 个 topic | 用「好友」 | 应为「挚友」 | 产品术语错误 |
| `closed-friend-task-execution` | 挂在 `intimacy-system` 下 | 内容描述 ClosedFriend 任务执行 | 域归属错误 |
| `distributed-tracing-and-exception-handling` | 挂在 `family-system` 下 | infra 追踪 Aspect/Configuration | infra 域混入 |

**根因:**
1. `domain_doc_agent.py` `plan_topics` 未注入 `term_glossary` → LLM 不知「挚友≠好友≠家族」的产品术语
2. `agent_prompts.py` SYSTEM_TOPIC_PLANNER 示例偏置「家族任务系统」→ LLM 将 ClosedFriend 代码也描述为「家族」
3. `graph_domain_decompose.py` `_is_infra_slug` 未覆盖 `tracing/aspect/configuration` 后缀

**修复方案:**
- `domain_doc_agent.py`: `plan_topics` 和 `write_page` 注入 `term_glossary`（`{ClosedFriend: 挚友, Family: 家族, Intimacy: 亲密度}`）
- `agent_prompts.py`: 示例替换为域名感知的中性示例
- `graph_domain_decompose.py`: `_is_infra_slug` 扩展 `tracing|aspect|configuration|interceptor` 模式

---

### P0-3 — 域错挂根因确认

| 被错挂域 | 错挂在 | 应属于 | 根因 |
|---------|--------|--------|------|
| `closed-friend-task-execution` | `intimacy-system` | `closed-friend-relations` | embedding 将 AbsClosedFriendTaskExecutor 与亲密度任务混聚 |
| `distributed-tracing-and-exception-handling` | `family-system` | 应过滤或独立 infra 域 | `_is_infra_slug` 规则不覆盖「2模块+Aspect/Configuration后缀」 |

**修复方案:**
- `graph_domain_decompose.py`: 扩展 infra 过滤规则覆盖 tracing/aspect 类模块
- 域拆分后增加 `_review_subdomain_placement()` 语义距离校验

---

### P0-4 — Stub 内容

| 页面 | 字数 | 类型 | 问题 |
|------|------|------|------|
| `user-profile-and-level/vip` topic | 586 | topic | VIP stub — 仅有骨架 |
| `family-activity-and-interactive-events/家族任务系统` topic | 1345 | topic | 接近 stub 阈值 |
| `intimacy-growth-and-reminders/亲密度任务系统` topic | 1653 | topic | 接近 stub 阈值 |

**修复方案:**
- `finalize.py`: topic content_len < 1500 → hard reject（不发布）
- `config.py`: `topic_min_content_chars` 提到 1500

---

### P1-1 — 低 CN Ratio 页面（6 页，排除 module_overview）

| 页面 | CN ratio | 类型 | 长度 |
|------|----------|------|------|
| `memberstatisticsaccount` overview | 0.202 | overview | 3892 |
| `intimacy-growth-logic/亲密度任务系统` topic | 0.217 | topic | 8378 |
| `intimacy-growth-and-reminders/亲密度数据管理` topic | 0.241 | topic | 8318 |
| `closed-friend-relations` overview | 0.269 | overview | 5523 |
| `user-core-info/用户资产与支付数据` topic | 0.279 | topic | 7053 |
| `dealer-info-query` overview | 0.284 | overview | 7290 |

**根因:** 这些页面长度足够（非 stub），但英文叙述段落比例过高，代码注释/方法名占主体内容。

**修复方案:**
- `finalize.py`: CN ratio < 0.25 且为中文 wiki → 标记需重写 or 回退 skeleton
- `agent_prompts.py`: 强调叙述段落必须用中文

---

### P1-2 — 空壳中间节点（4 个）

4 个域仅作嵌套容器，无 topic 也无实质 overview：
- `closed-friend-relations`（做 behavior-events + space 的父节点）
- `family-system`（做 activity + distributed-tracing 的父节点，overview 有幻觉）
- `intimacy-system`（做 closed-friend-task-execution + intimacy-growth-and-tasks 的父节点）
- `intimacy-growth-and-tasks`（做 intimacy-growth-and-reminders + intimacy-growth-logic 的父节点，overview 有幻觉）

**修复方案:**
- `config.py`: `domain_split_max_depth` 限制最大深度为 2
- 空壳域合并规则：无 topic 中间层 → 内容提升到父域或合并

---

### P1-3 — 重复标题（2 组）

| 标题 | 出现位置 |
|------|---------|
| 家族任务系统 | `closed-friend-behavior-events` topic + `family-activity-and-interactive-events` topic |
| 亲密度任务系统 | `intimacy-growth-and-reminders` topic + `intimacy-growth-logic` topic |

**根因:** 跨域 topic 命名时未传入 `used_titles` 全局去重集。

**修复方案:**
- `domain_doc_agent.py`: `plan_topics` 传入 `existing_titles` 参数用于跨域去重

---

### P1-4 — Slug 质量问题（3 个）

| slug | 标题 | 问题 | 修复 |
|------|------|------|------|
| `long-domain` | 数据类型转换 | Java `Long` 类型泄漏 | denylist 加 `long` |
| `memberstatisticsaccount` | 会员统计账户 | Java 类名直接做 slug | normalize_slug 拆分 camelCase |
| `imonelink` | 系统消息推送 | 内部模块名泄漏 | normalize_slug 增强 |

---

### P2-1 — 20 个遗留 module_overview 未清理

module_overview 页面（`modules/_import_*.md`）为早期产物，全部使用英文 H2 模板（`## Overview / ## Key components / ## Relationships`），与域结构无关联，占总页面 23.8%。

**修复方案:** 批量删除或迁移脚本清理。

---

### V15 综合评分

| 维度 | V13 | V15 | 变化 | 说明 |
|------|-----|-----|------|------|
| **Topic 覆盖** | 4.0 | **7.0** | +3.0 ✅✅ | 24→41 topic (+71%), 39% 域有 topic |
| Overview 深度 | 7.5 | **6.5** | -1.0 | 平均 5405↓，但整体仍合格 |
| Topic 内容质量 | — | **6.5** | 🆕 | 平均 5601 字，3 stub 需修复 |
| 域碎片化/纯度 | 6.0 | **5.0** | -1.0 ❌ | 嵌套回归（深度3），4 空壳，域错挂 |
| 语言一致性 | 7.0 | **6.0** | -1.0 | 6 页低 CN，但实际英文 H2 从 21%→7% ✅ |
| Tree 完整性 | 9.0 | **9.0** | 持平 | 84/84 挂载 ✅ |
| Path 规范性 | 8.5 | **7.5** | -1.0 | 3 slug 问题 |
| 域命名质量 | 5.5 | **5.0** | -0.5 | 术语错挂严重 |
| 内容真实性 | — | **7.0** | 🆕 | 4 页幻觉(5%)，多数内容可靠 |
| **总体** | **6.3** | **6.6** | **+0.3** ✅ | Topic 覆盖大幅提升，幻觉+术语为新阻塞项 |

> **V15 结论:** Topic 覆盖是本轮最大亮点（24→41，+71%），9 个域有 topic（V13 仅 6 个），实际英文 H2 从 21%→7% 大幅改善。但新暴露三个问题：(1) LLM 幻觉编造业务数据/场景（4 页），(2) 产品术语错挂——挚友内容标为「家族」/「好友」（11 个 topic），(3) 嵌套回归（深度 3）和 4 个空壳中间节点。20 个 module_overview 仍未清理。下一步应优先修复幻觉门禁和术语注入。

---

### V15 修复优先级

| 优先级 | 修复项 | 涉及文件 | 预期效果 |
|--------|--------|---------|---------|
| **P0** | plan_topics 注入 term_glossary + prompt 示例域名感知 | `domain_doc_agent.py`, `agent_prompts.py` | 消除 11 topic 术语错挂 |
| **P0** | `_is_infra_slug` 扩展 tracing/aspect/configuration | `graph_domain_decompose.py` | 过滤 infra 域错挂 |
| **P0** | finalize 幻觉检测门禁（编造%/SLA/故障复盘） | `finalize.py` | 阻止幻觉内容发布 |
| **P0** | topic content_len < 1500 → hard reject | `finalize.py`, `config.py` | 阻止 586 字 stub |
| **P1** | closed-friend-* 不得挂 intimacy-* 下 | `graph_domain_decompose.py` | 修复域错挂 |
| **P1** | normalize_slug camelCase 拆分 + denylist | `path_conventions.py`, `domain_filters.py` | slug 质量 |
| **P1** | `domain_split_max_depth` 限制为 2 | `config.py` | 限制嵌套深度 |
| **P1** | CN ratio < 0.25 → 标记需重写 | `finalize.py` | 语言一致性 |
| **P1** | 跨域 topic title 去重 | `domain_doc_agent.py` | 消除 2 组重复标题 |
| **P2** | 批量删除 20 个遗留 module_overview | migration script | 减噪 24% |
| **P2** | 空壳域合并压缩 | `graph_domain_decompose.py` | 优化 IA |

---

### V15 关键代码路径

| 问题 | 关键文件 | 方法/行号 |
|------|---------|----------|
| 术语未注入 plan_topics | `wiki/domain_doc_agent.py` | `plan_topics()` |
| prompt 示例偏置 | `wiki/agent_prompts.py` | `SYSTEM_TOPIC_PLANNER` |
| infra 域过滤不全 | `wiki/nodes/graph_domain_decompose.py` | `_is_infra_slug()` |
| 幻觉无门禁 | `wiki/nodes/finalize.py` | finalize 主流程 |
| stub 未 reject | `wiki/nodes/finalize.py` | content_len 校验 |
| 域嵌套无深度限制 | `wiki/nodes/graph_domain_decompose.py` | `_recursive_split()` |
| slug classname 泄漏 | `wiki/path_conventions.py` | `normalize_slug()` |

---

*本文档为 wiki 质量审计的单一事实来源。修复完成后更新对应条目状态。*
