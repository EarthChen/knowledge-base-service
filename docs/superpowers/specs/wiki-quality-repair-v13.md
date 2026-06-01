# Wiki Quality Repair V13 — 全量修复提案

**Created:** 2026-06-01
**Audit Basis:** V27 审计 (7 subagent 并行, 4 维度审阅 + 3 代码级根因追踪)
**Target:** V27 → V28 发布后全部 P0 清零, P1 ≤ 2 项残留
**Strategy:** 仅修改管线代码，不使用临时脚本修复存量数据（测试阶段直接重新生成）

---

## 1. Executive Summary

V12 部署后 Wiki 在**正文质量门禁**（幻觉 0、cn_ratio 达标、Part N 9.7%→清退、stub 清零）上取得显著进展，综合评分从 5.5 升至 **6.3/10**。但暴露出三类新瓶颈：

1. **命名瓶颈**：35.5% topic 使用 `repo|ClassName` compound key 作标题
2. **架构瓶颈**：6 页跨域错挂 + 5 域无 topic + 消歧义括号掩盖错挂
3. **门禁缺口**：compound title 零检测 + placement 仅 warn + thin overview 逃逸

本提案覆盖 **12 个活跃问题**，分 2 个 Phase（约 8 工作日）分阶段修复，预期综合评分 6.3 → **8.0+/10**。

---

## 2. Problem Inventory

### P0 — 阻断用户体验（3 项）

| # | 问题 | 影响面 | 代码根因 |
|---|------|--------|----------|
| **P0-1** | 35.5% Compound Title | 11/31 topic 不可读 | `_extract_chunk_title` 透传 compound key + `_rename_mechanical_topic_title` 回退 `modules[0]` |
| **P0-2** | 6 页跨域错挂 | wealth 4 + intimacy 2 | HAC 无 cannot-link + `_INFRA_CLASS_SUFFIXES` 缺 RemoteService + placement 仅 warn |
| **P0-3** | 1 页未闭合代码围栏 | 738 字 prose 渲染为代码 | `content_guards`/`quality_gate` 无 unclosed fence 检测 |

### P1 — 结构性问题（5 项）

| # | 问题 | 影响面 | 代码根因 |
|---|------|--------|----------|
| **P1-1** | 5 域无 Topic | 26.3% 域为导航死胡同 | `plan_topics_min_modules=2` + 1 模块域硬拦截 + `final_overview` dead code |
| **P1-2** | 1 Thin Overview (666 字) | 低于 2000 字门禁 | `topic_index` 三重长度豁免 (quality_gate + finalize + skeleton) |
| **P1-3** | Legacy module_overview 边 | ~20+ 孤儿边 | 历史落库未清理 |
| **P1-4** | RemoteService 未纳入 infra | 门面类独立成 topic | `_INFRA_CLASS_SUFFIXES` 不含 RemoteService/Facade |
| **P1-5** | 消歧义括号后缀 | 7 页 `(domain_slug)` | `_deduplicate_exact_titles` 掩盖错挂 |

### P2 — 中期改善（4 项）

| # | 问题 | 影响面 |
|---|------|--------|
| **P2-1** | DomainAnchor 未接入 HAC | 重聚类时业务线可能漂移 |
| **P2-2** | Infra 类模块误独立成域 | timestamp-id + family-id 等 infra 独立成域 |
| **P2-3** | 壳 Section 无导航内容 | 3 个 Section 壳节点 |
| **P2-4** | 前端 nav 显示 slug 而非 title | `WikiNavigationLinks.pageLabel()` 用 path 末段 |

---

## 3. Root Cause Chain

### Chain 1: Compound Title 注入链

```
compound_key = _compound_key(repo, name)  ← graph_domain_decompose.py:707
    ↓ 传入 domain_doc_agent
module_dicts = [{"name": m, "display_name": m}]  ← domain_doc_agent.py:891
    ↓ _extract_chunk_title
单模块 chunk → return display_name (= compound key)  ← L231-241
    ↓ 或 Part N 检测回退
_rename_mechanical_topic_title → return modules[0]  ← L84-92
    ↓ 无门禁
quality_gate: 仅检测 "- Part \d+$" 不检测 "|"  ← L308
finalize: 仅 _rewrite_part_n_title 不处理 compound  ← L421
    ↓
WikiPage.title = "ultron/ultron-relation|FamilyChestService"
```

### Chain 2: 跨域错挂链

```
RemoteService embedding ≈ 同质（RPC 封装/接口代理语义模板）
    ↓ HAC average linkage
被吸入 user-wealth-charm-level 簇
    ↓
_INFRA_CLASS_SUFFIXES 无 RemoteService → 不走 infra 路由
    ↓
_review_subdomain_placement: 仅 1 条规则 + 只 warning
    ↓
finalize._deduplicate_exact_titles → 追加 (domain_slug) 后缀掩盖
    ↓
6 页错挂 + 7 页括号标题
```

### Chain 3: 无 Topic 域链

```
域模块数 == 1 (family-business-event, system-im-notifications)
    ↓
plan_topics(): len(module_names) < plan_topics_min_modules(2) → return None
    ↓ 且
final_overview: memory 从未赋值 → dead code → bypass 替代触发
    ↓
mechanical split: len(chunks) <= 1 → return None
    ↓
仅生成 overview，无 topic
    ↓
quality_gate_domain_no_topics: 仅 log.warning，不 block
```

---

## 4. Repair Plan

### 4.1 Phase A: 管线核心修复 (Sprint 1, Day 1-3)

修改管线代码，重新生成后问题消除。

#### Fix A1: Compound Title 管线门禁

| 文件 | 修改 |
|------|------|
| `wiki/content_guards.py` | 新增 `is_compound_module_title(title)` + `derive_semantic_title(modules, domain, summaries)` |
| `wiki/domain_doc_agent.py` | `_extract_chunk_title`: display_name 取自 summary 首句；`_rename_mechanical_topic_title`: 不回退 modules[0]，调 `derive_semantic_title` |
| `wiki/nodes/quality_gate.py` | 新增 compound_module_title 检测（与 Part N 同级） |
| `wiki/nodes/finalize.py` | 新增 `_rewrite_compound_title(title, content)` 在 `_deduplicate_titles` 前调用 |

**derive_semantic_title 策略优先级链**：
1. `summary_text` 首句（if 存在且 ≤20 字符）
2. content 中第一个 H2 标题后的首句概述（if content 存在）
3. `domain_display_name` + 模块角色关键词（如 "家族宝箱奖励核心逻辑"）
4. Fallback: CamelCase 类名拆分为空格词组（无需 LLM，纯规则）
5. 最终 Fallback: 保留模块名但去除 `repo|` 前缀

**验证**: 重新生成后 compound_title_count == 0

#### Fix A2: 未闭合围栏检测与修复

| 文件 | 修改 |
|------|------|
| `wiki/content_guards.py` | 新增 `repair_unclosed_fences(content: str) -> str` — 逐行扫描 fence 状态，文末 in_fence=True 则追加 \`\`\` |
| `wiki/nodes/quality_gate.py` | 新增 unclosed_fence 检测，触发 heal |
| `wiki/nodes/finalize.py` | 发布前调用 `repair_unclosed_fences` + `repair_code_fences` (已有空块清理) |

**验证**: 重新生成后 unclosed_fences == 0 且 empty_code_blocks == 0

#### Fix A3: 跨域 Placement 强化（泛化方案）

**架构决策**: 方案 A — 保留 HAC 初始聚类（确定性 + 低成本），赋予 DomainReviewAgent 完全重组权（保证正确性）。

**核心思路**: 三层防线 — ① 聚类前 prefix penalty 降低错误概率；② 聚类后 prefix review 规则兜底；③ DomainReviewAgent 语义审查 + 完全重组权。不依赖硬编码域名规则，换仓库/新增域自动生效。

**第一层：prefix penalty（降低错误概率）**

| 文件 | 修改 |
|------|------|
| `wiki/domain_semantic_clusterer.py` | 新增 `_extract_business_prefix(module_name: str) -> str|None` — 从模块 slug 提取首个有意义 business token（如 `family`, `intimacy`, `guild`, `wealth`） |
| `wiki/domain_semantic_clusterer.py` | 新增 `_apply_prefix_penalty(dist, modules)` — 不同 prefix 模块间距离 × penalty_factor (1.3~1.5) |
| `wiki/domain_semantic_clusterer.py` | `_compute_distance_matrix` 在 call-graph discount 之后调用 `_apply_prefix_penalty` |

**第二层：post-clustering review（兜底修正）**

| 文件 | 修改 |
|------|------|
| `wiki/domain_semantic_clusterer.py` | 新增 `_review_cluster_placement(clusters, modules) -> clusters` — 聚类完成后执行 prefix 多数投票验证 |

Review 逻辑：
1. 对每个 cluster 计算 dominant prefix（出现次数最多的 business prefix）
2. 遍历每个模块：若模块 prefix ≠ 所在 cluster 的 dominant prefix
3. 在所有 cluster 中找 dominant prefix == 模块 prefix 的目标 cluster，reparent
4. 找不到匹配 cluster 的模块保持不动（可能是唯一 prefix）
5. reparent 操作记录 structlog 日志，便于审计

| 文件 | 修改 |
|------|------|
| `wiki/nodes/graph_domain_decompose.py` | `_review_subdomain_placement` warning→reparent；`_INFRA_CLASS_SUFFIXES` 新增 RemoteService/RpcClient/Facade/ApiClient/Proxy |

**第三层：DomainReviewAgent 统一语义审查（替代 GraphSemanticCorrector）**

用一个新的 agent 替代现有 `GraphSemanticCorrector.review_global_consistency()`，统一完成 merge + rename + placement validation：

| 文件 | 修改 |
|------|------|
| `wiki/agents/domain_review_agent.py` | 新增 `DomainReviewAgent(GenericAgent)` — 基于 agent 框架的域审查 agent |
| `wiki/nodes/graph_domain_decompose.py` | Step 5.5 替换 `corrector.review_global_consistency()` 为 `DomainReviewAgent.run()` |
| `wiki/graph_semantic_corrector.py` | 保留 `merge_similar_domains` 作为简单场景 fallback，`review_global_consistency` 标记 deprecated |

**DomainReviewAgent 设计**：

```
架构: GenericAgent + @function_tool
max_rounds: 3（允许迭代审查）
```

工具集（@function_tool）：
- `list_domains()` — 查看所有域及模块数
- `inspect_domain(slug)` — 查看某域的模块列表 + 摘要
- `get_module_detail(module_name)` — 获取模块路径、调用关系、方法列表
- `propose_move(module, from_domain, to_domain, reason)` — 提交 placement 修正
- `propose_merge(sources, target, new_display_name, reason)` — 提交域合并
- `propose_rename(slug, new_display_name, reason)` — 提交域重命名
- `validate_prefix_consistency()` — 调用第二层 prefix review 获取已知不一致列表
- `finalize()` — 确认所有决策并退出

System prompt 要点：
- 你是域分类审查员，目标是确保每个模块被归入业务含义最匹配的域
- 先用 `validate_prefix_consistency` 获取算法层面的疑似错挂列表
- 然后 `inspect_domain` 逐个审查可疑域
- 模块的包路径、类名、摘要是判断归属的关键信号
- 不设 move 上限，但每个 move 必须有明确 reason

**优势**（相比原 review_global_consistency）：
- 迭代推理：可以先 inspect 再决策，而非一次性看全部信息
- move 上限放宽：total_modules × 0.5（防止 agent 大规模重组破坏稳定性，但远高于原 0.3）
- 职责聚焦：工具化设计让 agent 按需获取信息，避免 prompt 过长
- 可审计：每个 propose_move/merge/rename 都有 reason，记录 structlog

**容错设计**：
- LLM 失败时 fallback：退回到第二层 prefix review 结果（保证至少规则层生效）
- Agent 超时/异常：捕获后 log.error + 跳过 agent 步骤，不阻塞管线
- 决策持久化：所有 propose 操作写入 pipeline state，支持后续审计
- 成本预估：3 rounds × ~5 tool_call/round ≈ 15 次 LLM 调用（约等于原 review_global_consistency 的 3 倍）

**泛化机制**:
- prefix 提取规则（双格式支持）：
  - kebab-case 输入：去除通用前缀（`relation-`, `user-`, `ultron-`）后取首个 hyphen 分段
    - 例：`relation-family-service` → `family`，`relation-intimacy-task-service` → `intimacy`
  - CamelCase 输入：按大写字母拆分后取首个业务词（跳过 I/Abstract/Base 等前缀）
    - 例：`FamilyChestService` → `family`，`IntimacyTaskService` → `intimacy`
  - 优先使用 path 中的 slug（kebab-case），path 不存在时 fallback 到 CamelCase 解析
- 无需维护域名对照表，prefix 从模块名自动推导
- penalty_factor 可配置（`AppWikiFlags.cluster_prefix_penalty_factor`）
- 前两层 review 是无损操作：只在明确 prefix 不匹配时 reparent，无 prefix 的模块不触碰
- 第三层 agent 兜底可通过 flag 关闭（`AppWikiFlags.enable_domain_review_agent`）

**验证**: 重新 decompose 后 cross_domain_misplacement == 0

#### Fix A4: 单模块域 Topic 保证

| 文件 | 修改 |
|------|------|
| `wiki/domain_doc_agent.py` | `plan_topics_min_modules` 2→1；单模块默认生成 1 topic；修复 `final_overview` dead code |
| `wiki/nodes/quality_gate.py` | `quality_gate_domain_no_topics` warn→block (非 leaf 域) |
| `wiki/nodes/finalize.py` | `SHELL_DOMAIN_MIN_CHARS` 500→2000；topic_index 纳入 min_content_chars 检查 |
| `core/config.py` | `domain_agent_early_exit_min_chars` 500→1500 |

**验证**: 重新生成后 domains_without_topics ≤ 2

#### Fix A5: Topic Slug 语义化

| 文件 | 修改 |
|------|------|
| `wiki/path_conventions.py` | `_is_module_path_slug` 条件扩展；CamelCase→kebab-case 全覆盖 |

**验证**: 无 PascalCase 或 camelCase slug 残留

---

### 4.2 Phase B: 结构优化 (Sprint 2, Day 4-7)

#### Fix B1: DomainAnchor 接入 HAC

| 文件 | 修改 |
|------|------|
| `wiki/domain_semantic_clusterer.py` | pinned modules 与非同 anchor 模块设 cannot-link (dist=2.0)；anchor seed clusters |

*注：原 B2（域分类正确性保障）已合并入 A3 DomainReviewAgent 统一处理。*

#### Fix B2: 壳 Section 补导航型 Overview

| 操作 | 内容 |
|------|------|
| 目标 | 家族/关系/用户成长 3 个 Section |
| 内容 | 子域卡片 + 一句话边界 + cross-link |

#### Fix B3: 前端 nav 显示 title 而非 slug (P2-4)

| 文件 | 修改 |
|------|------|
| `dashboard/src/components/wiki/WikiNavigationLinks.tsx` | `pageLabel()` 优先使用 node.title（从图 DB 读取），path 末段仅作 fallback |

---

## 5. Code Change Map

| 文件 | Phase | 新增/修改 | 具体函数 |
|------|-------|----------|----------|
| `wiki/content_guards.py` | A1,A2 | 新增 | `is_compound_module_title()`, `is_technical_module_title()`, `derive_semantic_title()`, `repair_unclosed_fences()` |
| `wiki/domain_doc_agent.py` | A1,A4 | 修改 | `_extract_chunk_title`, `_rename_mechanical_topic_title`, `_build_mechanical_topic_split`, `plan_topics` |
| `wiki/nodes/quality_gate.py` | A1,A2,A4 | 修改 | `_check_page_quality` 新增 compound/fence 检测；no_topics warn→block |
| `wiki/nodes/finalize.py` | A1,A2,A4 | 修改 | 新增 `_rewrite_compound_title`；集成 `repair_unclosed_fences`；`SHELL_DOMAIN_MIN_CHARS` 500→2000；topic_index 检查 |
| `wiki/nodes/graph_domain_decompose.py` | A3 | 修改 | `_review_subdomain_placement` reparent；`_INFRA_CLASS_SUFFIXES` +5；Step 5.5 替换为 DomainReviewAgent |
| `wiki/domain_semantic_clusterer.py` | A3,B1 | 新增 | `_extract_business_prefix()`，`_apply_prefix_penalty()`，`_review_cluster_placement()`；anchor seed |
| `wiki/agents/domain_review_agent.py` | A3 | 新增 | `DomainReviewAgent(GenericAgent)` — 统一域审查 agent（替代 GraphSemanticCorrector.review_global_consistency） |
| `wiki/path_conventions.py` | A5 | 修改 | `_is_module_path_slug` 扩展 |
| `core/config.py` | A4 | 修改 | `domain_agent_early_exit_min_chars` 500→1500 |

---

## 6. Regeneration Strategy

**策略：全量重建**（非增量更新）

重新生成时先清空该 repo 的所有 WikiPage 节点和边，再从头运行完整管线。这样：
- P1-3 Legacy module_overview 边自然消失（无需单独清理）
- 所有新逻辑（prefix penalty、DomainReviewAgent、compound title 门禁）完整生效
- 无需处理新旧数据并存问题

```bash
ssh dev "cd ~/review-bot/knowledge-base-service && \
  PYTHONPATH=. .venv/bin/python -m wiki.cli regenerate --repo ultron --full-rebuild"
```

---

## 7. Verification Plan

所有验证通过全量重建后运行 `audit_wiki_data.py` 完成。

| Fix | 成功指标 | 当前值 |
|-----|----------|--------|
| A1 | compound_title_count == 0 | 11 |
| A2 | unclosed_fences == 0 且 empty_code_blocks == 0 | 1 + 2 |
| A3 | cross_domain_misplacement == 0 | 6 |
| A4 | domains_without_topics ≤ 2 | 5 |
| A5 | technical_slugs == 0 | ~8 |
| B1 | 重聚类后域稳定性（前后 domain_mapping diff < 10%） | N/A |
| B2 | shell_sections == 0 | 3 |
| B3 | 前端 nav 显示 title 而非 slug | 全部显示 slug |

**综合验证脚本**:
```bash
ssh dev "cd ~/review-bot/knowledge-base-service && \
  PYTHONPATH=. .venv/bin/python scripts/audit_wiki_data.py --repo ultron --full-content"
```

---

## 8. Test Strategy

**原则**：每个新增函数至少 3 个单元测试；修改现有函数前确保现有测试通过。

| 模块 | 测试文件 | 关键用例 |
|------|---------|----------|
| `_extract_business_prefix` | `tests/wiki/test_domain_semantic_clusterer.py` | kebab-case 提取、CamelCase 提取、无 prefix 返回 None、通用前缀过滤 |
| `_apply_prefix_penalty` | 同上 | 同 prefix 不变、不同 prefix 增大、无 prefix 不变 |
| `_review_cluster_placement` | 同上 | 正常 reparent、无匹配保持不动、空 cluster 处理 |
| `repair_unclosed_fences` | `tests/wiki/test_content_guards.py` | 单未闭合、嵌套、已闭合不变、空内容 |
| `is_compound_module_title` | 同上 | 含 `\|` 检测、纯中文不触发、边界 |
| `derive_semantic_title` | 同上 | 各优先级 fallback 路径 |
| `DomainReviewAgent` | `tests/wiki/agents/test_domain_review_agent.py` | mock LLM + tool 调用流程、失败 fallback、move 上限 |

---

## 9. Risk Matrix

| Fix | 风险 | 概率 | 影响 | 缓解措施 |
|-----|------|------|------|----------|
| A1 | derive_semantic_title 质量差 | 中 | 中 | 5 级 fallback 链 + finalize 兜底 |
| A2 | 误关闭有效代码块 | 低 | 中 | 仅文末追加，不修改块内内容 |
| A3 | prefix penalty 过强导致同业务线碎片化 | 中 | 中 | penalty_factor 可配置 (1.3~1.5) + 日志对比 |
| A3 | prefix 提取不准（CamelCase/无前缀） | 低 | 低 | 双格式支持 + 无 prefix 时不施加惩罚 |
| A3 | DomainReviewAgent LLM 失败 | 中 | 低 | fallback 到第二层 prefix review 结果 |
| A3 | DomainReviewAgent 过度重组 | 低 | 中 | move 上限 total_modules × 0.5 |
| A4 | 单模块 topic 内容空洞 | 中 | 低 | topic_min_content_chars=1000 门禁 |
| B1 | Anchor pin 限制聚类灵活性 | 低 | 中 | 仅对确认的域 pin |

---

## 10. Dependencies & Sequencing

```
Phase A (Day 1-5) — 管线核心修复
───────────────────────────────────────────
Day 1-2:
  A1 (compound title 门禁) ──┐
  A2 (fence 检测修复) ────────┼── 可并行开发（相对简单）
  A4 (单模块 topic) ──────────┘

Day 2-4:
  A3 (placement 强化: prefix + review + DomainReviewAgent)
      ← 工期最长，需设计+实现+集成+测试

Day 4-5:
  A5 (slug 语义化) ←── 依赖 A1 title 清理 + A3 域确定
         │
         ▼ 全量重新生成 + 审计验证
Phase B (Day 6-8) — 结构优化
───────────────────────────────────────────
B1 (DomainAnchor 接入) ←── A3 prefix penalty 基础上叠加 anchor 约束
B2 (Section overview) ←── 依赖全量重生后的域结构
B3 (前端 nav title) ←── 独立，可并行
         │
         ▼ 全量重建 + 审计验证

注：原 B2（域分类正确性）已合并入 A3，由 DomainReviewAgent 统一保障。
```

---

## 11. Acceptance Criteria

| 指标 | V27 当前 | Phase A 目标 | Phase B 目标 |
|------|---------|-------------|-------------|
| compound_title_count | 11 | **0** | 0 |
| cross_domain_misplacement | 6 | **0** | 0 |
| unclosed_fences | 1 | **0** | 0 |
| empty_code_blocks | 2 | **0** | 0 |
| domains_without_topics | 5 | **≤ 2** | 0 |
| thin_overview (< 2000) | 1 | **0** | 0 |
| disambiguation_brackets | 7 | **≤ 2** | 0 |
| domain_count | 19 | 不限 | 不限（仅保障分类正确性） |
| 综合评分 | 6.3/10 | **7.5+** | **8.0+** |
| 导航可用性 | 5.5/10 | **7.0+** | **8.0+** |

---

## Appendix A: Compound Title 映射表

| # | 当前标题 | 建议新标题 | 提取策略 |
|---|---------|-----------|---------|
| 1 | `ultron/ultron-basic-user\|AppStoreStarPopWindowMoaService` | 应用商店评分弹窗服务 | H2 提取 |
| 2 | `ultron/ultron-relation\|FamilyChestService` | 家族宝箱奖励核心逻辑 | H2 提取 |
| 3 | `ultron/ultron-relation\|FamilyChestWebService` | 家族宝箱对外 Web 接口 | H2 提取 |
| 4 | `ultron/ultron-relation\|FamilySquareRedisDao` | 家族广场 ID 与计数存储 | domain + 模块职责 |
| 5 | `ultron/ultron-relation\|FamilyTaskRedisDao` | 家族任务 ID 与计数存储 | domain + 模块职责 |
| 6 | `ultron/ultron-basic-user\|QuickMessageRemoteService` | 快捷消息远程调用 | domain + 层 |
| 7 | `ultron/ultron-relation\|RelationRankService` | 关系榜单计算与排名 | H2 提取 |
| 8 | `ultron/ultron-relation\|RelationRankWebMoaService` | 关系榜单 Web 展示层 | domain + 层 |
| 9 | `ultron/ultron-basic-user\|LongListStringTypeHandler` | 长整型 ID 列表序列化 | 概述提取 |
| 10 | `ultron/ultron-basic-user\|LongTimestampTypeHandler` | 时间戳字段序列化 | 概述提取 |
| 11 | `ultron/ultron-basic-user\|BasicUserPrivilegeDomainRepoV2` | 用户权益领域仓储 | 概述提取 |

## Appendix B: 跨域 Reparent 映射表

| # | Topic 标题 | 源域 | 目标域 |
|---|-----------|------|--------|
| 1 | 系统消息与快捷交互 | user-wealth-charm-level | quick-message |
| 2 | 关系管理（user-wealth-charm-level） | user-wealth-charm-level | user-relation-management |
| 3 | 用户资料与等级（user-wealth-charm-level） | user-wealth-charm-level | user-profile-and-level |
| 4 | 用户权益（user-wealth-charm-level） | user-wealth-charm-level | user-privilege-and-vip |
| 5 | 家族核心服务与消息通信 | intimacy-task-execution | family-core-operations |
| 6 | 家族任务与活动运营 | intimacy-task-execution | family-core-operations |

---

*本提案基于 V27 审计数据与 7 subagent 代码级根因分析。实施后通过 `audit_wiki_data.py` 验证各指标。*
