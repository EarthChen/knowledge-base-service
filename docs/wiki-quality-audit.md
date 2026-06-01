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
| **V28** | **06-01** | **73** | **28** | **45** | **V13部署：Part N清零，compound key清零，幻觉/stub/thin清零** | **compound serial 40%、11域无topic(60.7%)、域重复×2、跨域错挂2** |

### 已部署修复累积效果 (V8→V13)

| 版本 | 核心修复 | 状态 |
|------|---------|------|
| V8/V9 | SSoT, strip_h1, META_H2, quality_gate 集成 | ✅ 全部有效 |
| V11 | Topic 覆盖率(9%→77%), slug 去重, cn_ratio 门禁, 壳域门禁, 代码堆叠 | ✅ 重大突破 |
| V12 | Part N 消退(67%→10%), Stub 拦截, 重复标题, H2 格式, 代码截断 | ✅ 大幅改善 |
| V13 | Part N/Compound key 根治, thin overview 门禁 | ✅ 清零 |

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
>
> **V28** (06-01 晚): V13 部署后全量审计。73 页、28 域、45 topic。Part N/compound key/幻觉/stub 清零。新发现 compound serial 40%、域重复×2、覆盖率 60.7%。

---

## V28 审计（2026-06-01 晚）— V13 部署后全量审计 + 代码级根因追踪

**数据源:** 开发机 FalkorDB `kb_ultron` 图 (`--repo ultron --full-content`, 583KB)
**审计方法:** 7 专项 subagent 并行审计（4 维度审阅 + 3 维度根因分析）
**数据文件:** `data/wiki-audit-latest.json`

### V13 修复效果验证

| V13 Fix | V27→V28 效果 | 判定 |
|---------|-------------|------|
| Part N 标题清退 | 9.7%→**~0%** | ✅ 根治 |
| Compound key (repo\|ClassName) | 35.5%→**~0%** | ✅ 根治 |
| 幻觉门禁 | 0→**0** | ✅ 稳定 |
| Stub topic 拦截 | 0→**0** | ✅ 稳定 |
| 低 cn_ratio 门禁 | 0→**0** | ✅ 稳定 |
| Thin overview 门禁 | 1(666字)→**0** (min 3156字) | ✅ 修复 |
| 域覆盖率 | 74%→**60.7%** | ❌ 恶化（域数+47%） |
| 跨域错挂 | 2+4→**2** | ⚠ 减少但未根治 |

### V28 核心指标

| 指标 | V27 | V28 (当前) | 变化 | 说明 |
|------|-----|------------|------|------|
| 有效页面数 | 50 | **73** | +46% | V13 域拆分更细 |
| domain_overview | 19 | **28** | +47% | |
| topic 页面 | 31 | **45** | +45% | |
| 域数 | 19 | **28** | +47% | HAC prefix/anchor 约束 |
| 有 topic 的域 | 14 (73.7%) | **17 (60.7%)** | ❌ -13pp | |
| 无 topic 的域 | 5 (26.3%) | **11 (39.3%)** | ❌ | |
| 幻觉内容 | 0 | **0** | ✅ | |
| 壳 Section | 3 | **4** | +1 | 家族/亲密关系/用户关系/Quick |
| 低 cn 页 | 0 | **0** | ✅ | |
| **Compound serial** | 未出现 | **18/45 (40%)** | 🆕 P0 | `中文名（domain-slug·专题·N）` |
| **域重复** | 未测 | **2 组** | 🆕 P0 | relation-rank×2 + quick-message×2 |
| **只有1个H2** | 未测 | **3 topic** | 🆕 P1 | 4778/5696/3712 字长文 |
| 空代码块 | 2 | **2** | → | intimacy-mark + system-message-push |

### V28 多维评分

| 维度 | V27 | V28 | 变化 | 说明 |
|------|-----|-----|------|------|
| 正文质量/门禁 | 8.0/10 | **8.2/10** | +0.2 ✅ | 0 幻觉、0 低cn、min 3156字 |
| 内容深度/区分度 | 6.0/10 | **6.3/10** | +0.3 | 标杆域质量高，模板同质化仍存 |
| 域分解合理性 | 5.5/10 | **5.0/10** | -0.5 ❌ | 域数膨胀+47%、重复×2 |
| 命名/导航 | 4.5/10 | **5.0/10** | +0.5 | Part N→compound serial（问题迁移） |
| 覆盖率/完整性 | 6.0/10 | **5.0/10** | -1.0 ❌ | 60.7%（V27 73.7%） |
| Slug/Path 规范性 | 7.0/10 | **5.5/10** | -1.5 ❌ | slug 出现在 title、域重复 |
| 代码块完整性 | 8.0/10 | **7.5/10** | -0.5 | 2 空代码块 |
| H2 结构完整性 | N/A | **6.8/10** | 🆕 | 3 topic 仅 1 个 H2 |
| 导航可用性(新人) | 5.5/10 | **3.8/10** | -1.7 ❌ | 同名Section/compound title/16 L1 |
| **综合** | **6.3/10** | **5.9/10** | **-0.4** | 门禁改善被域膨胀和命名拉低 |

### V28 P0 问题清单（含代码级根因）

| # | 问题 | 根因代码位置 | 机制 |
|---|------|-------------|------|
| **1** | **40% Compound Serial Title** | `content_guards.py:663` level 4 `{domain}核心服务` + `finalize.py:604` dedup level 2 | Mechanical split 无 summaries → 同域同名 → 硬编码消歧 |
| **2** | **域重复×2** | `graph_domain_decompose.py:1040` slug 碰撞追加 `-service` + `skip_llm_merge=True` | 并行命名碰撞造新域而非合并 |
| **3** | **覆盖率 60.7%** | `domain_doc_agent.py:913` `modules≥2` + `final_overview` dead code + 大量 1 模块叶域 | 单模块不可 mechanical 拆分 |
| **4** | **跨域错挂** | `domain_semantic_clusterer.py:46` CamelCase prefix 提取 `Relation*`→`relation` 而非 `family` | cannot-link 对同 relation 包无效 |
| **5** | **3 topic 仅 1 H2** | `quality_gate.py` 无 H2 数量下限 + `WikiPageOutput.sections` 无 min_length | 长文通过字数门禁但结构检查缺失 |

### V28 修复优先级总表

| 优先级 | 修复项 | 代码位置 | 预期改善 | 难度 |
|--------|--------|----------|----------|------|
| **P0-1** | Compound serial 根治：derive_semantic_title 传 summaries + finalize 禁 slug 进 title | `content_guards.py` + `domain_doc_agent.py` + `finalize.py` | 40%→<5% | 中 |
| **P0-2** | 域 stem 合并：`{base}` vs `{base}-service` 自动 merge | `graph_domain_decompose.py:1040` | 重复域 2→0 | 中 |
| **P0-3** | 单模块 topic + final_overview dead code 修复 | `domain_doc_agent.py:913` + `doc_orchestrator.py` | 覆盖率→85%+ | 中 |
| **P0-4** | CamelCase prefix 修复 + cannot-link + placement reparent | `domain_semantic_clusterer.py:46` + `graph_domain_decompose.py:890` | 错挂 2→0 | 中 |
| **P0-5** | Topic H2 最少 4 个门禁 | `quality_gate.py` + `structured_output.py` | 单H2 3→0 | 低 |
| **P1-1** | H2 尾随空格检测修复 | `quality_gate.py` / `finalize.py` | 2→0 | 低 |
| **P1-2** | "Quick" 壳域改中文 | `tree_linker.py` | 导航体验 | 低 |
| **P1-3** | 空代码块修复 | `content_guards.py` + `quality_gate.py` | 2→0 | 低 |
| **P2-1** | 域数压缩至 ~20 | `graph_domain_decompose.py` | 架构清晰度 | 高 |
| **P2-2** | DomainAnchor 接入 HAC | `domain_semantic_clusterer.py` | 防漂移 | 高 |

### V28 域结构分析

**28 域树结构（3 层深度，16 L1 Section）：**
```
__root__ (16 L1)
├── 评分弹窗 [5432字, 2t] ✅
├── ES搜索 [4142字, 0t] ❌
├── 家族 [壳, 5 子域]
│   ├── 家族活跃与成长 [5507字, 3t] ✅ 标杆
│   ├── 家族宝箱奖励 [4816字, 0t] ❌
│   ├── 家族ID计数 [5505字, 2t] ✅
│   ├── 家族广场与推荐 [5430字, 4t] ✅
│   └── 家族任务执行 [5111字, 0t] ❌
├── 送礼逻辑 [3930字, 2t] ⚠ 仅1H2
├── 公会成员关系 [5288字, 2t] ⚠ 1t仅1H2
├── 亲密关系 [壳, 5 子域]
│   ├── 亲密印记 [5247字, 0t] ❌
│   ├── 亲密关系 [5980字, 2t] ✅
│   ├── 亲密任务 [5619字, 4t] ✅
│   ├── 亲密任务执行 [6650字, 4t] ⚠ 2错挂
│   └── 亲密度关系 [4198字, 3t] ✅
├── 会员统计 [4330字, 0t] ❌
├── 支付数据 [5459字, 0t] ❌
├── 奖励发放 [6920字, 0t] ❌
├── Quick [壳, 2 子域] ⚠ 英文名
│   ├── 在线状态 [5576字, 2t] ⚠ 域重复
│   └── 快捷消息 [5172字, 2t] ⚠ 域重复
├── 系统消息 [4276字, 0t] ❌
├── 用户状态 [5963字, 2t] ✅
├── 用户扩展 [4923字, 0t] ❌
├── 等级配置 [6737字, 0t] ❌
├── 用户关系 [壳, 4 子域]
│   ├── 挚友关系 [5750字, 4t] ✅
│   ├── 关系属性 [4751字, 0t] ❌
│   ├── 关系榜单(rank) [3356字, 2t] ⚠ 重复
│   └── 关系榜单(rank-svc) [6147字, 2t] ⚠ 重复
└── 用户VIP信息 [3156字, 3t] ✅
```

---

## 域稳定方案：多轮 Agent + 人工调整

### Dashboard 域管理能力验证

Dashboard 已具备完整的域管理 API：

| 操作 | API 端点 | 功能 |
|------|---------|------|
| **Move** | `POST /wiki/domains/hierarchy/move` | 移动域/页到新父节点 |
| **Merge** | `POST /wiki/domains/hierarchy/merge` | 合并两个域（source 子节点→target） |
| **Rename** | `PATCH /wiki/domains/hierarchy/{uid}` | 修改域名/描述 |
| **Create** | `POST /wiki/domains/hierarchy/{parent}/children` | 创建子域 |
| **Delete** | `DELETE /wiki/domains/hierarchy/{uid}` | 删除域（子节点可提升） |
| **Move Module** | `POST /wiki/domains/hierarchy/move-module` | 移动模块到新域 |

### 移动/合并时子页面行为

**结论：✅ Overview + Topics 随域移动。**

- 导航树基于 `HAS_CHILD` 图边渲染，移动 Section 后子 WikiPage 自动跟随
- `merge_domains` 时 source 子节点 reparent 到 target，source 被删除
- ~~已修复~~ `merge_domains` 后同步更新子页面 `business_domain` 属性（`wiki/domain_management_service.py`）

### user_modified 尊重机制

Pipeline 再生成时通过三处跳过用户修改的节点：

| 位置 | 逻辑 |
|------|------|
| `domain_merger.py:253` | `aggregable = [n for n in nodes if not n.get("user_modified")]` |
| `graph_domain_decompose.py:996` | `if child.get("user_modified"): continue` |
| `prefix_family_grouper.py:26,104` | `if node.get("user_modified"): return` |

### 推荐操作流程

```
第一轮：Pipeline 生成初始域结构（28 域）
    ↓
第二轮：用户在 Dashboard 人工调整
    - 合并 relation-rank × 2（slug 碰撞造成的重复域）
    - 合并 quick-message × 2
    - 移动错挂的 family topic 回家族域
    - 标记 user_modified=true
    ↓
第三轮：触发 wiki 重新生成（尊重 user_modified）
    - 已固定的域结构保持不变
    - overview/topic 内容根据新域结构重新生成
    ↓
第四轮：审计确认，微调
```

### V14 修复方向

结合 V28 分析，V14 应聚焦：

1. **域 stem 合并**（P0-2）：`{base}` vs `{base}-service` 在 decompose 阶段自动合并 → 消除重复域
2. **单模块 topic 支持**（P0-3）：修复 `final_overview` dead code + 降低 min_modules → 覆盖率 85%+
3. **CamelCase prefix 修复**（P0-4）：`_prefix_from_camel` 应提取语义前缀而非首段
4. **Dashboard path 同步**（已修复）：merge 后更新 `WikiPage.business_domain`
5. **人工调整作为兜底**：对 HAC 语义聚类无法正确分类的边缘 case（如同名不同域的类），依赖用户手动调整

---

*本文档为 wiki 质量审计的单一事实来源。修复完成后更新对应条目状态。*
