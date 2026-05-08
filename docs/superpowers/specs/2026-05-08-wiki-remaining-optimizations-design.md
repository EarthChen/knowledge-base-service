# Wiki 生成剩余优化项设计

**状态**: Approved
**创建时间**: 2026-05-08
**前置**: 核心功能全部完成 + Pipeline 已接入 (1858 测试通过)

---

## 1. 背景

Wiki 生成管线的核心功能（CONTEXT_GAP 清理、反幻觉域分类、Agent-Driven 生成、拓扑排序、Citation 验证、Overview 合成等）已全部实现并接入 LangGraph Pipeline。

本设计覆盖 4 项剩余优化：

| ID | 内容 | 优先级 | 类型 |
|----|------|--------|------|
| R1 | CCB 调用链修复与增强 | P2 | Bug fix + 增强 |
| R2 | 图拓扑预分组 + 目录辅助域分类 + 空图边修复 | P2 | 增强 |
| R3 | 小域页面合并 (compose 阶段) | P2 | 优化 |
| R4 | 部署验证 + 全量重新生成 | P1 | 运维 |

---

## 2. R1: CCB 调用链修复与增强

### 2.1 问题

`ContentContextBuilder._query_call_chains` (content_context_builder.py L415-439) 存在 bug：

```python
# 当前代码 — 每行 module_row 都取 method_map 中第一个有值条目
for row in module_rows:
    cm, ce = "", ""
    for (_, _), (m1, m2) in method_map.items():
        if m1 and m2:
            cm, ce = m1, m2
            break  # 总是取同一个 method pair
```

`method_map` 的匹配逻辑完全不关联 caller/callee 模块对，所有行共享同一个 method pair。

与此同时，`call_chain_cypher` 已返回 `caller_functions` 和 `callee_functions` 列（每列 collect 采样最多 5 个函数名），但 CCB 从未读取这两列。

### 2.2 方案

删除有 bug 的 `method_map` 匹配机制，改为直接从 `module_rows` 读取 `caller_functions`/`callee_functions`：

```python
for row in module_rows:
    caller = str(row.get("caller", "") or "")
    callee = str(row.get("callee", "") or "")
    caller_fns = row.get("caller_functions") or []
    callee_fns = row.get("callee_functions") or []
    steps.append(
        CallChainStep(
            caller=caller, callee=callee,
            caller_method=caller_fns[0] if caller_fns else "",
            callee_method=callee_fns[0] if callee_fns else "",
            relationship="CALLS",
        ),
    )
```

- `CallChainStep` 数据结构不变 (`caller_method: str`, `callee_method: str`)
- `METHOD_CALL_CHAIN_CY` + fallback 路径 (L440-457) 保留不变
- 改动: ~15 行删除 + ~10 行新增

### 2.3 影响范围

- `wiki/content_context_builder.py` — `_query_call_chains` 方法
- 下游消费: `format_summary_for_agent`、TopicPageComposer prompt 上下文

---

## 3. R2: 图拓扑预分组 + 目录辅助域分类 + 空图边修复

### 3.1 子任务 R2a: 连通分量预分组

**新增模块**: `wiki/graph_pre_grouper.py`

```python
@dataclass
class PreGroup:
    group_id: int
    module_names: list[str]
    directory_prefix: str  # 最长公共目录前缀

async def compute_pre_groups(
    graph_store, repositories: list[str], module_names: set[str]
) -> list[PreGroup]:
```

算法:
1. 按仓库查询 Module→Module CALLS 边（复用 `ModuleDependencyGraph._MODULE_CALLS_CYPHER` 的 Cypher 模式）
2. Union-Find 构建连通分量
3. **过滤单元素分量**（孤立模块不提供聚类信号，仅保留 >= 2 个模块的分量）
4. 对每个分量计算最长公共目录前缀（基于模块 path 字段）
5. 返回 `PreGroup` 列表

**注入点**: `classify_domains_node` (classify.py)，在 `planner.classify()` 调用前：

```python
graph_store = configurable.get("graph_store")
if graph_store:
    pre_groups = await compute_pre_groups(
        graph_store,
        list(biz_modules.keys()),
        {n.properties.get("name", "") for nodes in biz_modules.values() for n in nodes},
    )
```

### 3.2 子任务 R2b: 目录前缀信号注入 prompt

修改 `CrossRepoBusinessDomainPlanner._build_single_batch_prompt`，接受可选 `pre_groups` 参数，追加到 prompt：

```text
Pre-grouping hints (modules that call each other or share directory structure):
Group 1 (com.example.meeting.*): [MeetingService, MeetingController, MeetingDAO]
Group 2 (com.example.user.*): [UserService, UserFacade]
...
Use these groups as a REFERENCE — you may split or merge them as appropriate.
```

**多 batch 路径处理**: `classify()` 有两条路径：
- 单 batch: `_build_single_batch_prompt` 直接注入全部 `pre_groups`
- 多 batch (按 repo 分): 每个 repo 的 prompt 仅注入**该 repo 相关的** `pre_groups`（按 `PreGroup.module_names` 与该 repo 模块取交集过滤）

### 3.3 子任务 R2c: 修复 decompose_hierarchy_node 空图边

当前代码 (classify.py L288):

```python
module_graph = ModuleGraph(modules=all_module_infos, edges=[], entry_points=[])
```

修改为从 FalkorDB 加载真实边：

```python
graph_store = configurable.get("graph_store")
if graph_store is not None:
    dep_graph = ModuleDependencyGraph(graph_store)
    repos = {repo_id for pairs in domain_mapping.values() for repo_id, _ in pairs}
    all_edges = []
    for repo in repos:
        repo_graph = await dep_graph.build(repo)
        all_edges.extend(repo_graph.edges)
    module_name_set = {m.name for m in all_module_infos}
    filtered_edges = [e for e in all_edges if e.source in module_name_set and e.target in module_name_set]
    entry_points = dep_graph._identify_entry_points(all_module_infos, filtered_edges)
    module_graph = ModuleGraph(modules=all_module_infos, edges=filtered_edges, entry_points=entry_points)
else:
    module_graph = ModuleGraph(modules=all_module_infos, edges=[], entry_points=[])
```

### 3.4 改动量

| 子任务 | 新文件 | 修改文件 | 行数 |
|--------|--------|----------|------|
| R2a | `wiki/graph_pre_grouper.py` | `wiki/nodes/classify.py` | ~100 |
| R2b | — | `wiki/cross_repo_domain_planner.py` | ~30 |
| R2c | — | `wiki/nodes/classify.py` | ~20 |

---

## 4. R3: 小域页面合并 (compose 阶段)

### 4.1 问题

`_collect_leaf_domains` 递归收集 `domain_tree` 的所有叶子。经过层次分解后，某些叶子可能只有 1-2 个模块。`merge_small_domains` 在分解的每个 `_single_pass` 中处理了小域，但最终树叶层级仍可能存在小叶子。每个叶子独立生成一个页面，导致碎片化。

### 4.2 方案

在 `compose_leaf_pages_node` 中，`_collect_leaf_domains` 之后新增合并步骤：

```python
def _merge_small_leaves(
    leaves: list[dict], min_modules: int = 3
) -> list[dict]:
    """Merge leaf domains with < min_modules into sibling or nearest leaf."""
    large = [l for l in leaves if len(l.get("modules", [])) >= min_modules]
    small = [l for l in leaves if len(l.get("modules", [])) < min_modules]

    for sl in small:
        same_parent = [l for l in large if l.get("parent") == sl.get("parent")]
        target = same_parent[0] if same_parent else (large[0] if large else None)
        if target is None:
            large.append(sl)
            continue
        target["modules"] = list(set(target.get("modules", []) + sl.get("modules", [])))
        log.info("compose_leaf_merged", small=sl.get("name"), into=target.get("name"), added=len(sl.get("modules", [])))

    return large
```

**注入点**: compose.py L910:

```python
leaf_domains = _collect_leaf_domains(domain_tree)
leaf_domains = _merge_small_leaves(leaf_domains, min_modules=3)  # 新增
```

### 4.3 改动量

- 新增函数: ~20 行
- 注入调用: ~2 行

---

## 5. R4: 部署验证 + 全量重新生成

运维操作，非代码变更。

检查清单:
- [ ] 部署 `feat/wiki-quality-agent-driven` 分支到测试环境
- [ ] 对 ultron-composite 执行全量索引，验证 CONTAINS 关系补全日志
- [ ] 执行全量 wiki 重新生成 (`business_id=default`, `incremental=false`)
- [ ] 质量扫描：检查 CONTEXT_GAP 残留、虚构内容、citation 验证结果
- [ ] 可选：启用 `WIKI__AGENT_DRIVEN_GENERATION=true` 对部分域测试 Agent-Driven 生成
- [ ] 更新 `docs/KNOWN-ISSUES.md` 和 `docs/IMPLEMENTATION-STATUS.md`

---

## 6. 实施顺序

```
[R1 (CCB 修复)] ─┐
                  ├─→ R2c (空图边修复) → R2a (连通分量) → R2b (prompt 注入) → R4 (部署验证)
[R3 (小域合并)] ─┘
```

- R1 和 R3 互不依赖，可并行
- R2c 独立于 R2a/R2b，但为后续图分析提供基础，应先执行
- R2a 依赖图查询能力（与 R2c 共享 `ModuleDependencyGraph`）
- R2b 依赖 R2a 的 `PreGroup` 结果
- R4 在所有代码变更之后

---

## 7. 测试策略

| 任务 | 测试类型 | 要点 |
|------|---------|------|
| R1 | 单元测试 | Mock graph query 返回带 caller_functions/callee_functions 的行；验证旧 bug 不再存在 |
| R2a | 单元测试 | Mock CALLS 边数据；验证连通分量和目录前缀计算 |
| R2b | 单元测试 | 验证 prompt 包含 "Pre-grouping hints" |
| R2c | 单元测试 | 验证 module_graph.edges 不为空 |
| R3 | 单元测试 | 构造含 1-2 模块叶子的 domain_tree；验证合并后叶子数减少 |
| 全部 | 回归 | 全量 pytest 通过 |
