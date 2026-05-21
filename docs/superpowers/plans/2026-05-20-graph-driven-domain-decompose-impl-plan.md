# 图驱动域分解 — TDD 实施计划

**创建时间**: 2026-05-20T20:12  
**关联 Spec**: `docs/superpowers/specs/2026-05-20-cluster-summary-pre-classification-design.md`  
**方法论**: TDD + Subagent-Driven

---

## Phase 1: 核心算法（可并行）

### Task 1.1: 图构建 + 社区检测核心模块
**文件**: `wiki/graph_community_detector.py` (新建)  
**测试**: `tests/wiki/test_graph_community_detector.py` (新建)

**TDD Red→Green 序列**:
- [ ] Test: 空图返回单一社区
- [ ] Test: 2个断开子图 → 2个社区
- [ ] Test: 带权重边正确影响社区划分
- [ ] Test: 自适应 resolution — 社区数 < 5 时自动增大 resolution
- [ ] Test: 自适应 resolution — 社区数 > 15 时自动减小 resolution
- [ ] Test: 微社区合并 — ≤2模块的社区合并到最近邻
- [ ] Test: 确定性 — 同一输入同一 seed 产出相同结果
- [ ] Impl: `GraphCommunityDetector` class with `detect()` method

**接口设计**:
```python
class GraphCommunityDetector:
    def __init__(self, target_min: int = 5, target_max: int = 15, seed: int = 42): ...
    
    def detect(
        self,
        nodes: list[tuple[str, str]],  # (repo_id, module_name)
        edges: list[tuple[tuple[str, str], tuple[str, str], int]],  # (src, dst, weight)
    ) -> list[set[tuple[str, str]]]:
        """Return communities as list of sets of (repo_id, module_name) tuples."""
        ...
    
    def detect_sub_communities(
        self,
        community: set[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int]],
        max_depth: int = 3,
        max_leaf_size: int = 8,
    ) -> list[dict]:
        """Recursively split a community into sub-domains. Returns tree structure."""
        ...
```

### Task 1.2: 孤立模块归属
**文件**: `wiki/graph_community_detector.py` (同上)  
**测试**: `tests/wiki/test_graph_community_detector.py` (同上)

**TDD Red→Green 序列**:
- [ ] Test: degree=0 模块通过名字相似度归属到正确社区
- [ ] Test: 所有模块相似度都低于阈值时进入 misc 组
- [ ] Test: 带 IMPORT 边的孤立模块优先按 IMPORT 归属
- [ ] Impl: `assign_isolated_modules()` method

### Task 1.3: LLM 命名
**文件**: `wiki/graph_community_detector.py` (同上)  
**测试**: `tests/wiki/test_graph_community_detector.py` (同上)

**TDD Red→Green 序列**:
- [ ] Test: 给定模块列表，LLM 返回 slug + display_name + description (mock LLM)
- [ ] Test: LLM 失败时回退到基于首个模块名的 slug
- [ ] Impl: `name_community()` async method

---

## Phase 2: 管道集成（依赖 Phase 1）

### Task 2.1: 新节点 `graph_driven_domain_decompose`
**文件**: `wiki/nodes/graph_domain_decompose.py` (新建)  
**测试**: `tests/wiki/nodes/test_graph_domain_decompose.py` (新建)

**TDD Red→Green 序列**:
- [ ] Test: graph_store 可用时使用社区检测（mock graph_store 返回边数据）
- [ ] Test: graph_store 为 None 时退化到旧 LLM 分类
- [ ] Test: 输出 schema 完全匹配（domain_mapping, domain_display_names, domain_tree, affected_domains）
- [ ] Test: pinned modules 强制归属到指定域
- [ ] Test: 增量模式 — 全量 Louvain + diff 产出 affected_domains
- [ ] Test: DomainStabilizer 被调用
- [ ] Test: domain_tree 层级结构正确（大域有子域，小域为叶子）
- [ ] Impl: `graph_driven_domain_decompose_node` async function

**关键实现细节**:
1. 复用 `classify_domains_node` 的 BIZ 过滤逻辑（entity_roles + _is_data_model）
2. 使用新跨 repo Cypher 查询构建图
3. 调用 `GraphCommunityDetector.detect()` + `detect_sub_communities()`
4. 调用 LLM 命名每个顶级社区和子社区
5. 构建 domain_tree 格式（name/display_name/modules/children）
6. 调用 `_consolidate_split_entities` 安全网
7. 调用 `_ensure_ascii_keys`
8. 调用 `DomainStabilizer.stabilize()`
9. 处理 pinned_modules 和 domain_anchors

### Task 2.2: 管道图替换
**文件**: `wiki/pipeline_graph.py` (修改)  
**文件**: `wiki/pipeline_nodes.py` (修改 import)

**变更**:
- [ ] 新增 `graph_driven_domain_decompose` 节点
- [ ] 将 `classify_domains → persist_classification → decompose_hierarchy` 替换为 `graph_driven_domain_decompose → persist_classification`
- [ ] 更新 `_NODE_PHASE_MAP`
- [ ] 更新 imports

### Task 2.3: 依赖添加
**文件**: `pyproject.toml` 或 `requirements.txt`

- [ ] 添加 `networkx` 依赖

---

## Phase 3: 验证（依赖 Phase 2）

### Task 3.1: 集成测试
- [ ] Test: 完整管道端到端执行（mock graph_store + mock LLM）
- [ ] Test: 退化路径 — graph_store=None 时旧逻辑工作
- [ ] Test: 退化路径 — networkx ImportError 时旧逻辑工作

### Task 3.2: 部署验证
- [ ] 部署到开发机
- [ ] 触发 ultron wiki 重新生成
- [ ] 验证 Family* 全在同一域
- [ ] 验证 Intimacy* 全在同一域
- [ ] 验证域数量 5-15
- [ ] 验证无空域

---

## Subagent 并行策略

```
┌─────────────────────────────────────────────────┐
│  Phase 1 (可并行)                                │
│  ┌──────────────┐  ┌──────────────┐             │
│  │ Agent A      │  │ Agent B      │             │
│  │ Task 1.1+1.2 │  │ Task 1.3     │             │
│  │ 社区检测核心  │  │ LLM命名      │             │
│  └──────────────┘  └──────────────┘             │
└─────────────────────────────────────────────────┘
                    ↓ (合并)
┌─────────────────────────────────────────────────┐
│  Phase 2 (顺序)                                  │
│  Task 2.1 → Task 2.2 → Task 2.3                │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Phase 3 (验证)                                  │
│  Task 3.1 → Task 3.2                            │
└─────────────────────────────────────────────────┘
```

---

## 验收标准

1. 所有新增单元测试通过
2. 现有测试不破坏
3. Family*/Intimacy* 分类正确
4. 域数量合理
5. 退化路径正常工作
