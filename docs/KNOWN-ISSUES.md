# Known Issues & Pending Fixes

**Last updated:** 2026-04-30

---

## Issue 1: Wiki 页面粒度过细（P0 — 核心质量问题）

**状态:** ✅ 已实现（待生产验证）  
**影响:** Wiki 为每个 Java 类/枚举创建独立页面（如 AtTypeEnum, Assertions, AssertUtil），产生 ~967 个页面，缺乏业务语义聚合。

**解决方案（Sprint 1-3 已实现）:**

1. **EntityRoleClassifier (Phase 1)** — 两阶段实体分类器 (`wiki/entity_role_classifier.py`)
   - Phase 1: 确定性规则过滤框架噪音（@Data, @Resource 注解; DTO/VO/PO 命名; 枚举; LOC<10）
   - Phase 2: 业务逻辑密度评分（方法数、图谱连接度、语义角色、代码量）→ HAS_BUSINESS_LOGIC / SUPPORTING / DATA_MODEL / FRAMEWORK_NOISE

2. **LangGraph 4 阶段管道** (`wiki/pipeline_graph.py`, `wiki/pipeline_nodes.py`)
   - Phase 1: 实体分类 → Phase 2: 域规划（LLM 驱动业务域分组）→ Phase 3: 叶子域内容生成 → Phase 4: 综合与关联
   - 非阻塞审阅：域树标记 `pending_review`，用户可在 Dashboard 后续审阅

3. **TopicPageComposer (Phase 3)** — 动态内容策略 (`wiki/topic_page_composer.py`)
   - ≤5 实体: 单页 → 6-15 实体: 概览 + 子页 → >15 实体: LLM 分组 + 子页
   - DTO/枚举内联为数据模型表格，不再独立成页

4. **Business 管理 API** — 用户显式绑定仓库 (`api/routes/business_routes.py`)
   - CRUD 管理 Business 实体
   - 显式绑定仓库到 Business，废弃自动推断

5. **Dashboard 配套** — Sprint 3 全部完成
   - 主题树导航 (`WikiTopicTreeNav`)、主题内容显示 (`WikiTopicContent`)
   - 域审阅面板 (`WikiDomainReviewPanel`)、页面审阅栏 (`WikiPageReviewBar`)
   - 知识图谱可视化 (`WikiKnowledgeGraph`)、WikiShell 集成

**参考:**
- DeepWiki: LLM 分析文件树 → 生成 XML wiki 结构（8-12 页），每页覆盖一个功能主题
- CodeWiki: 层级分解 → 特征导向模块树，递归文档生成 + 父模块综合

---

## Issue 2: 跨仓库域分类合并性能（P1 — 已修复 2026-04-29）

**状态:** ✅ 已修复  
**影响:** `mode=full` 业务 Wiki 生成在 `classifying_domains` 阶段因 LLM 连接断开而失败。

**根因:** 非流式 `generate()` 调用在等待 ~15k token 响应时 TCP 连接被中间代理断开。

**修复:**
1. `LLMPortBridge.generate()` 改为 SSE-first — 优先使用流式调用保持连接活性 (`llm/base_provider.py`)
2. 轻量域名合并 prompt — 只发送域名列表，程序化重分配模块 (`wiki/cross_repo_domain_planner.py`)
3. Per-repo 降级 — 合并失败时保留每仓库分类结果而非全部归入 `__infrastructure__`

**验证结果:**
- Per-repo 分类 13 批次全部成功（之前批次 8 耗时 106 秒通过 SSE 完成，之前版本在此 ReadError）
- 轻量合并 14 秒完成（之前 ReadError 后 fallback 到 __infrastructure__）
- 22 个业务域被正确识别：gift, quick-chat, conversation, callback, user, live, meeting 等

---

## Issue 3: HierarchicalDecomposer 批次超时（P2 — 已缓解）

**状态:** ⚠️ 已缓解，可进一步优化  
**影响:** 层级分解对 962 个模块创建 5 个批次，每批次 ~200 模块。某些批次 LLM 响应时间 >2 分钟。

**已做:**
- 添加 120 秒/批次超时，超时则跳过该批次
- 添加进度日志（batch_start/batch_done）
- SSE 流式保持连接活跃

**待优化:**
- 考虑减小 `max_tokens_per_batch`（当前 30k）以减少每批次模块数
- 或给 Per-repo 分类批次也加超时

---

## Issue 4: Qwen3 思维链导致 LLM 响应极慢（P2 — 待调查）

**状态:** 未解决  
**影响:** Local-QWen (Qwen3-Coder-Next-FP8) 在处理大批量模块分类时，某些批次耗时 100+ 秒，疑似思维链 (thinking) 模式导致。

**可能的解决方向:**
1. 检查 ai-gateway 是否支持关闭 thinking 模式的参数
2. 在 prompt 中添加 `/no_think` 或类似指令
3. 使用专门的 fast 模型用于分类任务

---

## Issue 5: _link_pages_to_tree 循环依赖导致 business_domain 视图无 WikiPage（P0 — 已修复 2026-04-30）

**状态:** ✅ 已修复  
**影响:** 业务 Wiki 生成完成后，`business_domain` 视图的树中只有 WikiSection 节点（190 个），没有 WikiPage 节点。Dashboard 的 Wiki 树展开后看不到任何文档页面。

**根因:** `_link_pages_to_tree()` 调用 `get_wiki_pages_for_business(business_id)` 来获取待链接的 WikiPage 列表。该方法通过从 `WikiSpace` 沿 `HAS_CHILD` 边遍历来查找 WikiPage 节点。但此时 HAS_CHILD 边尚未创建（正是 `_link_pages_to_tree` 要创建的），形成循环依赖。结果 `get_wiki_pages_for_business` 只返回 1 个页面（system_overview），导致 `linked_business_domain=0, linked_code_structure=0`。

**修复:** 将 `_link_pages_to_tree()` 中的页面查询从基于 HAS_CHILD 遍历改为直接按 `repository` 属性查询 WikiPage 节点：
```python
q = (
    "MATCH (wp:WikiPage {repository: $repo}) "
    "OPTIONAL MATCH (wp)-[:SOURCE_ENTITY]->(e) "
    "RETURN wp.uid AS uid, wp.title AS title, ... "
)
```

**验证结果:**
- 修复前: `wiki_tree_pages_linked  linked_business_domain=0 linked_code_structure=0 total_pages=1`
- 修复后: `wiki_tree_pages_linked  linked_business_domain=966 linked_code_structure=966 total_pages=966`
- Dashboard 树形结构完整：2118 节点（1952 WikiPage + 166 WikiSection），`__root__` 下 30 个业务大类
