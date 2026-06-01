# Wiki 生成质量审计报告

**Created:** 2026-05-25
**Audit Target:** `business_id=ultron` (dev 环境)
**Status:** Active — V26 全量审计完成（V11 部署后首次）
**最新审计:** V27 (2026-06-01 15:37) — V12 部署后 7 subagent 全量审计（4 维度审阅 + 3 代码级根因追踪）

---

## 历史修复概要

| 版本 | 日期 | 总页面 | 域数 | Topic | 核心改善 | 核心问题 |
|------|------|--------|------|-------|---------|---------|
| V1 | 05-25 | 702 | 377 | 325 | 首次审计 | 碎片化 420 slug, 25% 英文 |
| V5/V6 | 05-26 | 55 | 35 | 0 | 域预算 50, 语言检查 | Topic 致命缺失 |
| V10 | 05-26 | 84 | 27 | 37 | 树挂载 100%, stub 消除 | 命名碰撞, 40% topic 英文 |
| V16 | 05-27 | 36 | 18 | 18 | 幻觉门禁, camelCase slug | 78% 域无 topic |
| V19 | 05-27 | 50 | 28 | 22 | 幻觉清零, 域覆盖扩展 | Topic 覆盖 39%, slug 质量 |
| V23 | 05-27 | 23 | 17 | 6 | wiki 重新生成、域聚合 28→17 | meta 残留、slug bug、挚友域消失 |
| V24 | 05-27 | 23 | 17 | 6 | 第二轮根因分析 | 正则盲区、camelCase 拆分失效 |
| V25 | 05-28 | 30 | 22 | 8 | 域数回升 22、代码级根因追踪 | 覆盖率 9%、壳域 4、slug 重复、错挂 |
| **V26** | **05-28** | **50** | **17** | **33** | **V11全量部署：覆盖率9%→76.5%，cn_ratio/slug修复** | **Part N命名66.7%、stub 2、错挂2、壳域3** |
| **V27** | **06-01** | **50** | **19** | **31** | **V12部署：Part N 66.7%→9.7%，stub清零，重复标题清零** | **compound title 35.5%、5域无topic、跨域错挂2+4** |

### V8/V9 已部署修复效果

| Fix | 修复项 | 状态 | V25 效果 |
|-----|--------|------|----------|
| F1 | `content_guards.py` SSoT 统一规则源 | ✅ | 有效 |
| F5 | `strip_h1_title` | ✅ | H1 泄漏 54%→6%（壳域回潮 18%） |
| F6 | `META_H2_PATTERNS` | ✅ | 元章节 H2 39%→0% |
| F7 | `quality_gate` 集成 content_guards | ✅ | 有效 |
| F8 | `finalize` 集成 content_guards | ✅ | 有效（被 tree_linker 绕过） |
| F11 | Topic slug 英文强制 | ⚠ | 域 slug 全规范；topic slug 仍为模块名 |
| F13 | 嵌入文本 infra 频率过滤 | ❌ | 未实现 |

---

## V25 审计（2026-05-28）— 全量多维审计 + 代码级根因追踪

**数据源:** 开发机 FalkorDB `kb_ultron` 图 (`--repo ultron --full-content`, 247KB)
**审计方法:** 3 专项 subagent 多维审计 + 4 专项 subagent 代码级根因追踪
**数据文件:** `data/wiki-audit-v25.json`

### V25 核心指标

| 指标 | V23 | V25 (当前) | 变化 | 说明 |
|------|-----|------------|------|------|
| 有效页面数 | 23 | **30** | +30% | 域数回升 |
| domain_overview | 17 | **22** | +29% | |
| topic 页面 | 6 | **8** | +33% | |
| 域数 | 17 | **22** | +29% | |
| 有 topic 的域 | 3 (18%) | **2 (9%)** | ❌ -9pp | 覆盖率继续下降 |
| 无 topic 的域 | 14 (82%) | **20 (91%)** | ❌ | |
| 幻觉内容 | 0 | **1 页** | ⚠ | data-type-conversion (fabricated_sla) |
| 壳域(< 200 字) | 1 | **4** | ❌ 恶化 | intimacy-system/relations, user-profile/basic-info |
| H1 标题泄漏 | 1/17 (6%) | **4/22 (18%)** | ❌ 壳域回潮 | tree_linker 模板硬编码 `# {slug}` |
| 低 cn 页(<0.25) | 4 | **6** | ⚠ | relation-service cn=0.10 极端 |
| 空代码块 | 4/17 (24%) | **3/22 (14%)** | ✅ 略降 | im-message-send, member-statistics, relation-service |
| 重复标题 | 0 | **1** | 🆕 | 「用户资料与权益」跨 overview/topic |
| 重复 segment slug | 0 | **2** | 🆕 P0 | `ultronult-ultronult` + `closed-friend-closed-friend` |
| 错误挂载 | 1 | **2** | 🆕 | family-task→intimacy, data-type→intimacy |

### V25 多维评分

| 维度 | V23 | V25 | 变化 | 说明 |
|------|-----|-----|------|------|
| Overview 页面质量 | 8.0/10 | **6.2/10** | -1.8 ❌ | 壳域 4 页、代码堆叠(cn=10%)、双重fence |
| Topic 内容质量 | 5.5/10 | **5.8/10** | +0.3 | 单页质量尚可；空 Mermaid 1 页 |
| 域分解合理性 | 6.5/10 | **5.2/10** | -1.3 ❌ | slug 重复、错挂 2 处、挚友未独立表达 |
| 内容真实性 | 9.5/10 | **8.5/10** | -1.0 | 1 页 SLA 幻觉 |
| 语言一致性 | 7.5/10 | **6.0/10** | -1.5 ❌ | 6 页 cn<0.25；overview 无门禁 |
| Slug/Path 规范性 | 7.0/10 | **5.0/10** | -2.0 ❌ | 2 域 slug 重复段；topic slug 全为模块名 |
| 代码块完整性 | 5.0/10 | **5.5/10** | +0.5 | 比例下降但仍存在 |
| 导航完整性(Topic覆盖) | 4.5/10 | **2.5/10** | -2.0 ❌ | 91% 域无 topic |
| **综合** | **6.7/10** | **5.6/10** | **-1.1** | 域数回升但结构质量全面恶化 |

### V25 P0 问题清单（含代码级根因）

| # | 问题 | 根因代码位置 | 机制 |
|---|------|-------------|------|
| **1** | **Topic 覆盖率 9%** | `agent_prompts.py:314` prompt "≤5→不拆分" + `domain_doc_agent.py:666` mechanical chunk_size=5 需 ≥8 模块 | 三重门槛叠加：min_modules=3 + LLM ≤5 拒绝 + force_split 实际需 ≥8 |
| **2** | **4 壳域绕过 finalize** | `tree_linker.py:775-814` 在管线结束后用静态模板覆写并直接 persist | finalize reject 后 tree_linker 二次写入"复活" |
| **3** | **slug 重复段** | `graph_domain_decompose.py:678-688` 语义 suffix 无 uniqueness 检查 | dedup suffix 盲 append，不检查 `new_slug in seen` |
| **4** | **family-task 错挂 intimacy** | HAC 聚类语义接近 + `_review_subdomain_placement` 仅 1 条规则 | 无 DomainAnchor 保护 + placement 仅 warning |
| **5** | **data-type-conversion 错挂** | `infrastructure_slug_keywords` 不含 conversion/type + 4 模块越过 ≤3 阈值 | infra 过滤条件过窄 |
| **6** | **Overview 无 cn_ratio 门禁** | `quality_gate.py:281` / `finalize.py:457` / `heal.py:62` 均 `if page_type=="topic"` | 设计性缺失，非遗漏 |
| **7** | **relation-service 代码堆叠** | 13846字 cn=10%，无 overview 代码量上限 | Agent "过度引用"代码 + 无防护 |
| **8** | **DomainAnchor 未接入** | V24 P0-4 遗留 | 全量重聚类无业务线保护 |

### V25 根因深度分析

#### 根因 1：tree_linker 壳域 bypass（P0-2）

**时序问题 — tree_linker 在 finalize 之后执行：**
```
LangGraph pipeline: compose → quality_gate → heal → finalize → [结束]
  ↓ 管线结束后
business_pipeline_runner.py:728 → _persist_pages (仅管线内页面)
  ↓
business_pipeline_runner.py:884 → link_pages_to_nested_tree()
  ↓
tree_linker.py:762 → 检测无 Agent overview（因 finalize 已 reject）
tree_linker.py:775-779 → existing_content ≤500 → _build_domain_overview_content()
tree_linker.py:647-712 → 静态模板："# {slug}\n## 子域概览\n- **child** (N模块)"
tree_linker.py:810-814 → persist_pages_to_graph() ← 绕过 finalize/quality_gate
```

**双重 bypass 循环：** finalize reject 壳域 → tree_linker 认为"无 Agent overview" → 重新生成并落库

#### 根因 2：slug 重复 segment（P0-3）

**`_dedup_parallel_naming_results` (graph_domain_decompose.py:666-690) 逻辑缺陷：**
- 数字 suffix 分支有 `while f"{slug}-{counter}" in seen` 循环 ✅
- 语义 suffix 分支**直接 append，无 uniqueness 检查** ❌
- 当 suffix 与 slug 尾部相同时（如 slug=`...-closed-friend`, suffix=`closed-friend`）→ 重复

**`ultronult` 来源：** 模块名 `ultronult*`（repo `ultron` + 包名 `ult` 粘连）经 `str(module).rsplit(".",1)[-1][:12]` 截取后保留

#### 根因 3：Topic 覆盖率三重门槛（P0-1）

| 门槛 | 位置 | 效果 |
|------|------|------|
| `plan_topics_min_modules=3` | `domain_doc_agent.py:629` | <3 模块直接跳过规划 |
| LLM prompt "≤5 不拆分" | `agent_prompts.py:314-332` | 4-5 模块被 LLM 拒绝 |
| `topic_force_split_threshold=4` + chunk_size=5 | `domain_doc_agent.py:645-672` | mechanical 需 ≥8 模块才能产出 2 topic |

**关键矛盾：** 配置 threshold=4 看似激进，但 `chunk_size=5` + `末chunk<3合并` 使其**对 4-7 模块域完全无效**。

#### 根因 4：Overview cn_ratio 无门禁（P0-6）

三处代码**设计性排除** overview：
- `quality_gate.py:281` — `if page_type == "topic":` (cn heal)
- `finalize.py:457` — `if is_topic:` (cn hard-reject)
- `heal.py:62` — `if str(page_type) != "topic": return True`
- 测试 `test_low_cn_ratio_overview_not_rejected` 明确验证不拒

### V25 域结构分析

**22 域树结构（4 层深度）：**
```
__root__ (13 L1)
├── 评分弹窗 [6814字] ✅
├── 经销商资质 [6478字] ✅
├── ES搜索客户端 [3312字]
├── 家族ES同步 [12831字] ✅
├── 家族系统 [6490字, 4 topics] ✅ 标杆
├── 送礼回调 [5706字]
├── IM消息推送 [4484字, cn=0.15] ⚠
├── 亲密关系系统 [118字] ❌ 壳域
│   ├── 家族任务执行 [3833字] ← 错挂！应属 family-system
│   └── 亲密度关系 [149字] ❌ 壳域
│       ├── 数据类型转换 [3464字] ← 错挂！应属 infrastructure
│       └── 亲密度关系核心 [7828字]
├── 快捷消息 [5871字]
├── 关系管理 [13846字, cn=0.10] ⚠ 代码堆叠
├── 用户资产服务 [5429字]
├── 等级配置 [4560字]
└── 用户资料与权益 [119字] ❌ 壳域
    ├── 用户基础资料 [157字] ❌ 壳域
    │   ├── 用户基础数据 [5638字, 4 topics] ✅
    │   ├── 会员统计账户 [4879字]
    │   └── 用户扩展数据查询 [6992字]
    └── 用户行为与VIP状态 [6980字]
```

**问题 slug:**
- `family-system-ultronult-ultronult` → 应为 `family-system`
- `intimacy-relations-closed-friend-closed-friend` → 应为 `closed-friend-system`（挚友 60 模块）

---

## 修复优先级总表（V25）

| 优先级 | 修复项 | 代码位置 | 预期改善 | 难度 |
|--------|--------|----------|----------|------|
| **P0-1** | Prompt ≤5→≤2 + chunk_size 5→3 | `agent_prompts.py:314` + `domain_doc_agent.py:666` | Topic 覆盖 9%→30%+ | 低 |
| **P0-2** | tree_linker persist 前加 finalize 门禁 | `tree_linker.py:810` | 壳域 4→0 | 中 |
| **P0-3** | dedup 语义 suffix 加 while 循环 | `graph_domain_decompose.py:678` | slug 重复 2→0 | 低 |
| **P0-4** | placement 规则扩展 + infra keyword 补全 | `graph_domain_decompose.py:600` + `config.py:333` | 错挂 2→0 | 中 |
| **P0-5** | DomainAnchor 接入分解管线 | `graph_domain_decompose.py` | 防止业务线消失 | 高 |
| **P1-1** | Overview cn_ratio heal (≥0.20) | `quality_gate.py:281` + `finalize.py:457` | 低 cn 6→0 | 低 |
| **P1-2** | Topic slug 语义化 | `domain_doc_agent.py` resolve | slug 8/8 模块名→业务名 | 中 |
| **P1-3** | 树深度限制 max=3 | `graph_domain_decompose.py` | 4 层→3 层 | 中 |
| **P2-1** | 重复标题校验 | `finalize.py` | 跨页标题唯一 | 低 |
| **P2-2** | 代码量上限(overview) | `quality_gate.py` | 防代码堆叠 | 低 |

> **V11 修复提案:** [`docs/superpowers/specs/2026-05-28-wiki-quality-fix-v11-design.md`](superpowers/specs/2026-05-28-wiki-quality-fix-v11-design.md) (✅ 已执行)

---

## V26 审计（2026-05-28）— V11 部署后多维审计

**数据源:** 开发机 FalkorDB `kb_ultron` 图 (`--repo ultron --full-content`, 383KB)
**审计方法:** 4 专项 subagent 并行审计（Overview质量 / Topic质量 / 域拆分 / 树结构）
**数据文件:** `data/wiki-audit-latest.json`

### V11 修复效果验证

| V11 Fix | V25→V26 效果 | 判定 |
|---------|-------------|------|
| F1 Topic Coverage (prompt≤2+chunk=3+force_override) | 覆盖率 9%→**76.5%** | ✅ 重大突破 |
| F2 Slug Repeated Segment | 重复段 2→**0** | ✅ 彻底修复 |
| F3 Overview cn_ratio Gate | 低cn页 6→**0** | ✅ 彻底修复 |
| F4 tree_linker Shell Gate | 壳域 4→**3** | ⚠ 部分修复 |
| F5-R Enhanced Corrector | 错挂域 2→**2** | ❌ 未见效 |
| F6 Code Overload Detection | 代码堆叠→**0** | ✅ 修复 |
| F7-R DomainAnchor | N/A（首次无anchor） | — |

### V26 核心指标

| 指标 | V25 | V26 (当前) | 变化 | 说明 |
|------|-----|------------|------|------|
| 有效页面数 | 30 | **50** | +67% | V11 topic 生成大幅增加 |
| domain_overview | 22 | **17** | -23% | 域合并 22→17 |
| topic 页面 | 8 | **33** | +313% | F1 效果显著 |
| 有 topic 的域 | 2 (9%) | **13 (76.5%)** | ✅ +67pp | |
| 无 topic 的域 | 20 (91%) | **4 (23.5%)** | ✅ | es-user-search/im-system-message/prize-distribution/user-relation-management |
| 幻觉内容 | 1 | **0** | ✅ | |
| 壳域 | 4 | **3** | ⚠ | 挚友关系/家族关系/家族广场 |
| 低 cn 页(<0.25) | 6 | **0** | ✅ | F3 完全生效 |
| 重复标题 | 1 | **2 组** | ❌ | "挚友关系管理"×2 + "用户资料与状态" overlap |
| 重复 segment slug | 2 | **0** | ✅ | F2 完全生效 |
| 错误挂载(infra) | 2 | **2** | ❌ | data-type-mapping→family-task, task-execution-framework→family-square |
| **Part N 命名** | N/A | **22/33 (66.7%)** | 🆕 P0 | 机械拆分 Part 1/2/3 |
| **Stub topics** | 0 | **2 (23 chars)** | 🆕 P0 | placeholder 未拦截 |
| **H2 尾随空格** | 0 | **3 topics** | 🆕 P1 | "## 概述  " |
| **代码截断** | 3/22 | **≥6/50** | 🆕 P1 | 未闭合代码块 |
| **缺少 ## 概述** | 0 | **4 topics** | 🆕 P1 | |

### V26 多维评分

| 维度 | V25 | V26 | 变化 | 说明 |
|------|-----|-----|------|------|
| 正文质量/门禁 | 5.5/10 | **8.5/10** | +3.0 ✅ | 长度、语言、幻觉控制良好 |
| 内容深度/区分度 | N/A | **4.0/10** | 🆕 | 模板化、万能句式、缺业务洞察 |
| 域分解合理性 | 5.2/10 | **5.5/10** | +0.3 | 壳域减少但infra错挂未修 |
| 命名/导航 | 5.0/10 | **4.0/10** | -1.0 ❌ | Part N 66.7%, 重复标题, slug |
| 覆盖率/完整性 | 2.5/10 | **6.0/10** | +3.5 ✅ | 76.5% 域有topic，仍有4域空 |
| Slug/Path 规范性 | 5.0/10 | **6.5/10** | +1.5 ✅ | 重复段消除，垃圾slug仍存1个 |
| 代码块完整性 | 5.5/10 | **5.0/10** | -0.5 | 截断比例上升(页面增多) |
| **综合** | **5.6/10** | **5.5/10** | **-0.1** | 门禁/覆盖率大幅改善，被命名/导航问题拉低 |

### V26 P0 问题清单

| # | 问题 | 影响 | 对应 V12 Fix |
|---|------|------|-------------|
| **1** | **66.7% Part N 命名** — 22/33 topic 使用无语义"域名 - Part N"标题 | 目录不可扫读，导航无效 | **F1** |
| **2** | **2 个 Stub topic** — 仅 23 字符 placeholder | 文档黑洞 | **F2** |
| **3** | **2 组重复标题** — "挚友关系管理"×2, "用户资料与状态" overlap | 导航混淆 | **F3** |
| **4** | **Infra 域错挂** — data-type-mapping→family-task, task-execution-framework→family-square | 架构误导 | **F6** |
| **5** | **垃圾 slug** — `family-square-back-door-serv-family-at-grou` | 不可读 | **F7** |
| **6** | **4 域无 topic** — es-user-search/im-system-message/prize-distribution/user-relation-management | 覆盖率缺口 | **F8** |
| **7** | **代码截断** — ≥6 页未闭合代码块 | 可信度损害 | **F5** |
| **8** | **H2 格式** — 3 topic 尾随空格 + 4 topic 缺概述节 | 渲染/结构 | **F4** |

> **V12 修复提案:** 已实施并归档清理 (2026-06-01)

---

## V27 审计（2026-06-01）— V12 部署后全量审计 + 代码级根因追踪

**数据源:** 开发机 FalkorDB `kb_ultron` 图 (`--repo ultron --full-content`, 581KB)
**审计方法:** 7 专项 subagent 并行审计（4 维度审阅 + 3 维度根因分析）
**数据文件:** `data/wiki-audit-latest.json`

### V12 修复效果验证

| V12 Fix | V26→V27 效果 | 判定 |
|---------|-------------|------|
| F1 Part N 标题清退 | Part N 66.7%→**9.7%** (3/31) | ✅ 大幅改善 |
| F2 Stub topic 拦截 | 2 stub→**0** | ✅ 彻底修复 |
| F3 重复标题校验 | 2 组→**0** | ✅ 彻底修复 |
| F4 H2 格式修复 | 3+4 issues→**0** | ✅ 彻底修复 |
| F5 代码截断修复 | ≥6 页→**1 页** (unclosed fence) | ✅ 大幅改善 |
| F6 Infra 域错挂 | 2→**2** (family↔intimacy) | ❌ 持续 |
| F7 垃圾 slug | 1→**0** | ✅ 修复 |
| F8 覆盖率补全 | 4 域无 topic→**5 域无 topic** | ❌ 轻微恶化 |

### V27 核心指标

| 指标 | V26 | V27 (当前) | 变化 | 说明 |
|------|-----|------------|------|------|
| 有效页面数 | 50 | **50** | → | 稳定 |
| domain_overview | 17 | **19** | +12% | 域数微调 |
| topic 页面 | 33 | **31** | -6% | 域重组 |
| 域数 | 17 | **19** | +2 | 细粒度拆分 |
| 有 topic 的域 | 13 (76.5%) | **14 (73.7%)** | -2.8pp | |
| 无 topic 的域 | 4 (23.5%) | **5 (26.3%)** | ❌ +1 | family-business-event/prize-distribution/system-im-notifications/user-relation-management/user-search |
| 幻觉内容 | 0 | **0** | ✅ | |
| 壳域 Section | 3 | **3** | → | 家族/关系/用户成长 |
| 低 cn 页(<0.25) | 0 | **0** | ✅ | |
| 重复标题 | 2 组 | **0** | ✅ | F3 生效 |
| Part N slug | 22/33 | **3/31 (9.7%)** | ✅ -57pp | F1 生效 |
| Stub topics | 2 | **0** | ✅ | F2 生效 |
| **Compound title** | 未测 | **11/31 (35.5%)** | 🆕 P0 | `repo\|ClassName` 格式 |
| **跨域错挂** | 2 | **2+4=6** | 🆕 P0 | intimacy 含2家族 + wealth 含4 RemoteService |
| **未闭合代码围栏** | ≥6 | **1** | ✅ | 但影响严重（738字正文渲染为代码） |
| **空代码块** | 未测 | **2** (1页) | P2 | system-im-notifications |
| Thin overview | 未测 | **1** (666字) | P1 | timestamp-id-list-persistence |
| Legacy module 边 | 未测 | **~20+** | 🆕 P1 | `modules/_import_XXX_.md` 残留 |

### V27 多维评分

| 维度 | V26 | V27 | 变化 | 说明 |
|------|-----|-----|------|------|
| 正文质量/门禁 | 8.5/10 | **8.0/10** | -0.5 | 长度均值 5000+，cn≥0.25，0 幻觉 |
| 内容深度/区分度 | 4.0/10 | **6.0/10** | +2.0 | 标杆域质量高（family-core-operations），但 infra 域偏技术 |
| 域分解合理性 | 5.5/10 | **5.5/10** | → | 6 页跨域错挂未修 |
| 命名/导航 | 4.0/10 | **4.5/10** | +0.5 | Part N 改善，compound title 成为新主因 |
| 覆盖率/完整性 | 6.0/10 | **6.0/10** | → | 74% 域有 topic |
| Slug/Path 规范性 | 6.5/10 | **7.0/10** | +0.5 | 重复段清零，垃圾 slug 清零 |
| 代码块完整性 | 5.0/10 | **8.0/10** | +3.0 ✅ | 仅 1 页未闭合（V26 为 ≥6） |
| 导航可用性(新人) | N/A | **5.5/10** | 🆕 | 类名标题 + 5 域无 topic + 壳域 |
| **综合** | **5.5/10** | **6.3/10** | **+0.8** | 门禁/代码块大幅改善，compound title 是新瓶颈 |

### V27 P0 问题清单（含代码级根因）

| # | 问题 | 根因代码位置 | 机制 |
|---|------|-------------|------|
| **1** | **35.5% Compound title** — 11/31 topic 使用 `repo\|ClassName` 原始标识符 | `domain_doc_agent.py:891` mechanical split `display_name=m` + `_extract_chunk_title:231` 直接返回 compound key + `_rename_mechanical_topic_title:84` 回退到 `modules[0]` | 管线无 compound key 检测门禁 |
| **2** | **6 页跨域错挂** — intimacy 含 2 家族 topic + wealth 含 4 RemoteService topic | `domain_semantic_clusterer.py:127-157` HAC 语义+call-graph 合并 + `graph_domain_decompose.py:913-953` placement 仅 warning 不 reparent + `_INFRA_CLASS_SUFFIXES` 不含 RemoteService | 无 cannot-link 约束 + placement 规则仅 1 条 |
| **3** | **5 域无 topic** | `domain_doc_agent.py:825-836` `final_overview` 未赋值（dead code bypass）+ 1 模块叶域 mechanical 不可拆 + explore 超时跳过 + 质量全不合格回退 | 四条独立路径叠加 |
| **4** | **1 页未闭合代码围栏** — `relation-family-square-service/_topic` L96 `\`\`\`java` 未关闭，738 字正文渲染为代码 | `content_guards.py` / `quality_gate.py` 未检测未闭合 fence | 生成时 LLM 忘记关闭 + 无后处理修复 |
| **5** | **1 Thin overview** (666字) — `timestamp-id-list-persistence` | `domain_doc_agent` early exit 500 字门槛 + finalize `SHELL_DOMAIN_MIN_CHARS=500` 未拦截 | 666>500 逃逸所有门禁 |

### V27 根因深度分析

#### 根因 1：Compound Title（P0-1，影响 11 页）

**三条注入路径：**

| 路径 | 代码位置 | 触发条件 |
|------|----------|----------|
| A. Mechanical split | `domain_doc_agent.py:891` `display_name=m` | LLM 拒绝/失败 + force_override |
| B. Part N rename | `_rename_mechanical_topic_title:84` `return modules[0]` | Part N 被检测后回退到 raw key |
| C. LLM echo | `_parse_topic_outline` 无 compound 校验 | LLM 复制 module list 的 key |

**检测缺失对比：**

| 环节 | Part N | Compound Key |
|------|--------|--------------|
| TopicPlanItem validator | ✅ 正则拒绝 | ❌ 无规则 |
| quality_gate | ✅ `- Part \d+$` | ❌ 无规则 |
| finalize | ✅ `_rewrite_part_n_title` | ❌ 无函数 |
| content_guards | — | ❌ 无 title 检测 |

#### 根因 2：跨域错挂（P0-2，影响 6 页）

**HAC 距离矩阵无业务线硬约束：**
- FamilyTask*/IntimacyTask* embedding 共享高频词（任务/活动/奖励）
- *RemoteService 门面类 embedding 高度同质 → 聚成同一簇
- `_review_subdomain_placement` 仅 1 条规则且只 warning 不 reparent
- `_INFRA_CLASS_SUFFIXES` 不含 `RemoteService`

**user-wealth-charm-level 括号后缀来源：**
`finalize._deduplicate_exact_titles` 对重名标题追加 `(domain_slug)` → 掩盖错挂而非修复

#### 根因 3：5 域无 Topic（P0-3）

| 门槛 | 当前配置 | 问题 |
|------|---------|------|
| `final_overview` bypass | 4000 字 | **dead code**：production 从未赋值 |
| 1 模块域 | mechanical 不可拆 | 结构性限制 |
| explore 超时 | 跳过 plan_topics | 网络/性能问题 |
| 质量全不合格 | 回退单体 write | 过于保守 |
| quality_gate | 只 warn 无 topic | 不阻断发布 |

### V27 修复优先级总表

| 优先级 | 修复项 | 代码位置 | 预期改善 | 难度 |
|--------|--------|----------|----------|------|
| **P0-1** | Compound title 检测+门禁 | `content_guards.py` 新增 `is_technical_module_title()` + `domain_doc_agent.py` 源头 sanitize + `finalize.py` 兜底 | 35.5%→0% | 低 |
| **P0-2** | Placement reparent（warning→action）+ Cannot-link 约束 | `graph_domain_decompose.py:913` + `domain_semantic_clusterer.py` | 错挂 6→0 | 中 |
| **P0-3** | 未闭合 fence 检测+自动修复 | `content_guards.py` 新增 `repair_unclosed_fences()` + `quality_gate.py` 集成 | 代码围栏 100% 闭合 | 低 |
| **P1-1** | 5 域无 topic：修复 `final_overview` dead code + finalize 2000 字 hard reject | `domain_doc_agent.py:825` + `finalize.py:719` | 覆盖率 74%→90%+ | 中 |
| **P1-2** | RemoteService/facade 模块过滤 | `graph_domain_decompose.py` `_INFRA_CLASS_SUFFIXES` 扩展 | 防止门面类独立成域 | 低 |
| **P1-3** | Legacy module_overview 清理 | `scripts/cleanup_module_overviews.py` 执行 | 图洁净度 | 低 |
| **P1-4** | Topic slug 语义化 | `path_conventions.py` F1 规则扩展 | slug 可读性 | 中 |
| **P1-5** | Thin overview hard reject (≥2000) | `finalize.py` + `quality_gate.py` | 消除 666 字异常 | 低 |
| **P2-1** | DomainAnchor 接入 HAC | `domain_semantic_clusterer.py` | 防止重聚类漂移 | 高 |
| **P2-2** | 域合并至 14 域 | `graph_domain_decompose.py` LLM merge 配置 | 架构清晰度 | 高 |
| **P2-3** | 壳 Section 补导航型 overview | `tree_linker.py` | 导航体验 | 中 |

### V27 域结构分析

**19 域树结构（3 层深度，10 L1 Section）：**
```
__root__ (10 L1)
├── 评分弹窗 [3736字, 1 topic] ✅
├── 家族 [壳 Section, 5 子域]
│   ├── 家族业务事件 [2820字, 0 topics] ❌
│   ├── 家族宝箱奖励 [6167字, 2 topics] ✅
│   ├── 家族核心运营 [5269字, 4 topics] ✅ 标杆
│   ├── 家族ID计数 [4035字, 2 topics] ✅
│   └── 家族任务策略 [section only]
├── 亲密度任务 [3616字, 3 topics] ⚠ 含2家族错挂
├── 奖品分发 [3592字, 0 topics] ❌
├── 快捷消息 [7135字, 1 topic] ✅
├── 关系 [壳 Section, 5 子域]
│   ├── 挚友关系生命周期 [7829字, 2 topics] ✅
│   ├── 亲密度关系 [5963字, 4 topics] ✅
│   ├── 关系回调与调度 [5898字, 2 topics] ✅
│   ├── 关系榜单 [8595字, 2 topics] ✅
│   └── 关系管理 [3860字, 0 topics] ❌
├── 系统消息 [5169字, 0 topics] ❌
├── 时间戳与ID列表持久化 [666字, 2 topics] ⚠ thin
├── 用户成长 [壳 Section, 3 子域]
│   ├── 用户权益 [3939字, 1 topic] ✅
│   ├── 用户资料与等级 [4866字, 1 topic] ✅
│   └── 用户财富魅力等级 [8075字, 4 topics] ⚠ RemoteService错聚
└── 用户检索 [4264字, 0 topics] ❌
```

---

## 历史审计归档

> **V1-V10** (05-25~05-26): 从 702 页碎片化逐步压缩到 84 页，树挂载 100%，但 topic 反复波动。
>
> **V13-V19** (05-26~05-27): 域压缩至 18-20，CJK path 清零，幻觉门禁初建→修复。V8 部署后幻觉 20.6%→0%。
>
> **V20-V22** (05-27): 三维深度审计 → 域分解原则纠正 → V9 代码修复 F1-F16 部署。
>
> **V23-V24** (05-27): wiki 重新生成后审计 + 根因分析。发现挚友消失、meta 残留、slug 粘连三类新问题。
>
> **V25** (05-28 上午): V11 设计前全量审计。覆盖率 9%、壳域 4、slug 重复段 2、错挂 2。
>
> **V26** (05-28 下午): V11 全量部署后审计。覆盖率 76.5%、cn_ratio/slug 修复彻底。新发现 Part N 命名 66.7%、stub 2、代码截断等问题。
>
> **V27** (06-01): V12 部署后全量审计。Part N 9.7%、stub 0、重复标题 0。新发现 compound title 35.5%、跨域错挂 6 页、5 域无 topic。

---

*本文档为 wiki 质量审计的单一事实来源。修复完成后更新对应条目状态。*
