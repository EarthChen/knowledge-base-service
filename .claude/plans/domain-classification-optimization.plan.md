# Plan: 域分类精度优化

**Source**: `docs/superpowers/reviews/2026-05-22-domain-classification-review.md`
**Complexity**: Large
**Phase**: 4 phases, 18 tasks

## Summary
基于全面审阅报告（19 个问题），修复域分类不精准的核心问题：嵌入文本信息量不足、小样本跳过聚类、调用图边权重被忽略、k 值搜索过窄、LLM 全局审查信息不足。同时优化管线性能：并行化查询和命名、优化 healing 流程、提高 snippet 预算上限。补充修复：关键词合并通用化、嵌入 fallback 保留语义、域稳定器阈值调整、Cypher 查询优化等。

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Logging | `wiki/domain_semantic_clusterer.py` | `log.info("key", param=val)` 结构化日志 |
| Error handling | `wiki/graph_semantic_corrector.py` | `except Exception: log.warning(..., exc_info=True); return fallback` |
| Async | `wiki/nodes/graph_domain_decompose.py` | `asyncio.gather()` 并行 LLM 调用模式 |
| Tests | `tests/wiki/` | pytest + `pytest.mark.asyncio`，mock LLM responses |
| Config | `core/config.py` | dataclass field with `default=` |

## Files to Change

| File | Action | Why |
|---|---|---|
| `wiki/domain_semantic_clusterer.py` | UPDATE | P0: 丰富嵌入文本、降低聚类阈值、扩大 k 范围、权重感知折扣 |
| `wiki/graph_semantic_corrector.py` | UPDATE | P1: 全局审查传递更多上下文；P3: 删除死代码 |
| `wiki/nodes/graph_domain_decompose.py` | UPDATE | P2: 并行化域命名 LLM 调用 |
| `wiki/graph_call_query.py` | UPDATE | P1: 并行化 Cypher 查询 |
| `wiki/nodes/heal.py` | UPDATE | P2: 优化 TargetedHealer 后的二次 LLM 调用 |
| `wiki/token_budget.py` | UPDATE | P2: 提高 snippet 预算上限 |
| `wiki/prompts.py` | UPDATE | P2: 更新 heal prompt 减少 CONTEXT_GAP 残留 |
| `wiki/nodes/classify.py` | UPDATE | P3: `_consolidate_split_entities` 前缀正则鲁棒性 |
| `wiki/domain_stabilizer.py` | UPDATE | P2: 降低相似度阈值 + 编辑距离辅助匹配 |
| `tests/wiki/test_domain_semantic_clusterer.py` | CREATE | 新增聚类阈值和 k 范围的测试 |
| `tests/wiki/test_graph_semantic_corrector.py` | UPDATE | 删除死代码相关测试、新增全局审查上下文测试 |

## Tasks

### Task 1: 丰富嵌入文本（P0）
- **File**: `wiki/domain_semantic_clusterer.py`
- **Action**:
  - `_shorten_path` 默认 `levels` 从 2 改为 4
  - `build_embedding_texts` 增加方法签名和 docstring 到嵌入文本
  - 对空摘要模块用类名+方法名列表作为 fallback
- **Validate**: 检查嵌入文本输出包含完整路径和方法信息

### Task 2: 降低聚类阈值 + 扩大 k 搜索范围（P0）
- **File**: `wiki/domain_semantic_clusterer.py`
- **Action**:
  - `_SMALL_N_THRESHOLD` 从 10 改为 3
  - `_find_best_k`: `k_min = max(3, n // 15)`，`k_max = min(n // 4, 25)`
  - 3-10 个模块时仍运行聚类
- **Validate**: 单元测试验证 5 个不同模块不会被强制合并为一个域

### Task 3: 权重感知边折扣（P1）
- **File**: `wiki/domain_semantic_clusterer.py`
- **Action**:
  - `_compute_distance_matrix` 改为权重感知折扣：`discount = 1 - 0.15 * min(w / max_w, 1.0)`
  - 保留 `_w` 参数利用
- **Validate**: 单元测试验证高权重边的折扣比低权重边更小

### Task 4: 全局审查传递更多上下文（P1）
- **File**: `wiki/graph_semantic_corrector.py`
- **Action**:
  - `review_global_consistency`: 传递 top 10 模块（含路径和摘要精简版）
  - 模块数 < 10 的域传递全部模块
  - `_shorten_path` 已在文件中定义，复用即可
- **Validate**: 检查生成的 listing 包含路径和摘要信息

### Task 5: 并行化 Cypher 查询（P1）
- **File**: `wiki/graph_call_query.py`
- **Action**:
  - 两条 Cypher 查询改为 `asyncio.gather()` 并行执行
  - 返回 `(edges, errors)` 结构，不再静默吞没异常
- **Validate**: 检查并行执行后结果与串行一致

### Task 6: 并行化域命名 LLM 调用（P2）
- **File**: `wiki/nodes/graph_domain_decompose.py`
- **Action**:
  - 域命名循环改为 `asyncio.gather()` 并行
  - 去重逻辑后置：收集所有结果后检查 slug 冲突并修正
- **Validate**: 验证 10 个域的命名结果无 slug 重复

### Task 7: Healing 优化（P2）
- **File**: `wiki/nodes/heal.py`
- **Action**:
  - TargetedHealer 成功后，仅当内容 < 100 字符（而非 200）才触发 enrich
  - 或增加条件：仅当 `_heal_hint` 的 `heal_type` 包含 CONTEXT_GAP 时才 enrich
- **File**: `wiki/prompts.py`
- **Action**: 在 TargetedHealer prompt 中明确要求不留下 CONTEXT_GAP 标记
- **Validate**: 验证 heal 后内容不再触发不必要的二次 LLM 调用

### Task 8: 提高 Snippet 预算上限（P2）
- **File**: `wiki/token_budget.py`
- **Action**:
  - `budget_for_snippets` 改为 `min(500 + module_count * 100, 6000)`
- **Validate**: 验证 50 个模块的域可获得 5500 tokens 预算

### Task 9: 清理死代码（P3）
- **File**: `wiki/graph_semantic_corrector.py`
- **Action**:
  - 删除 `correct_module_assignments` 方法和 `_MODULE_CORRECTION_PROMPT` 常量
  - 更新测试文件 `test_graph_semantic_corrector.py` 删除相关测试
- **Validate**: `grep -r correct_module_assignments` 确认无残留引用

### Task 10: 关键词合并通用化（P2）
- **File**: `wiki/nodes/graph_domain_decompose.py:40-43`
- **Action**:
  - 将 `_RELATED_KEYWORDS` 从硬编码改为可配置（从 `core/config.py` 读取）
  - 默认值扩充：覆盖常见业务域（auth/authentication/login, payment/pay/billing 等）
  - 子串匹配改为单词边界匹配（`re.search(r'\b' + kw + r'\b', name_lower)`）
- **Mirror**: `core/config.py` 的 dataclass 配置模式
- **Validate**: 单元测试验证 `closedLoop` 不会误匹配 `closed`，而 `ClosedFriend` 仍正确匹配

### Task 11: 嵌入失败 fallback 保留语义信号（P2）
- **File**: `wiki/nodes/graph_domain_decompose.py:289-291`
- **Action**:
  - 嵌入失败时，不直接降级到纯 Louvain，先尝试用模块名 + 路径构建 TF-IDF 向量作为替代嵌入
  - Fallback 链：嵌入向量 → TF-IDF 文本向量 → Louvain 纯图论
  - 将 `module_paths` 和 `module_summaries_raw` 传递给 fallback 路径
- **Mirror**: `wiki/nodes/graph_domain_decompose.py:270-295` 的 `_embedding_clustering` 模式
- **Validate**: 模拟嵌入服务不可用，验证 fallback 仍产生多个域（而非单个大域）

### Task 12: 域稳定器阈值调整 + 编辑距离辅助（P2）
- **File**: `wiki/domain_stabilizer.py`
- **Action**:
  - `similarity_threshold` 默认值从 0.85 降至 0.72
  - `compute_similarity` 增加 Levenshtein 编辑距离归一化作为第三级匹配
  - 优先级：精确匹配 > 子串包含 > Jaccard > 编辑距离
  - `stabilize_dual_sync` 复用同一阈值
- **Mirror**: `wiki/domain_stabilizer.py:80-107` 的 `compute_similarity` 多级匹配结构
- **Validate**: 验证 "family-system" 和 "家族管理" 在 Jaccard < 0.72 时仍可通过编辑距离匹配

### Task 13: Cypher 查询 WHERE 子句下推（P3）
- **File**: `wiki/graph_call_query.py:10-26`
- **Action**:
  - 将 `valid_modules` 过滤从 Python 侧移到 Cypher `WHERE` 子句
  - Cypher 中增加 `WHERE m1.name IN $valid_names AND m2.name IN $valid_names`
  - 减少 FalkorDB 返回的数据量
- **Validate**: 验证返回的边集合与 Python 侧过滤完全一致

### Task 14: 图查询异常不再静默吞没（P2）
- **File**: `wiki/graph_call_query.py:58-59`
- **Action**:
  - 返回 `(edges, errors)` 元组
  - `errors` 列表记录失败的查询名称和异常信息
  - 调用方可通过 `errors` 判断"无边"和"查询失败"
  - 更新 `fetch_module_call_edges` 的签名和所有调用方
- **Mirror**: `wiki/graph_semantic_corrector.py` 的 `except Exception: log.warning(..., exc_info=True)` 模式
- **Validate**: 模拟 FalkorDB 不可达，验证调用方收到 errors 而非空 edges

### Task 15: `CONTAINS*1..3` 变长路径优化（P2）
- **File**: `wiki/graph_call_query.py:10-26`
- **Action**:
  - 将 `CONTAINS*1..3` 降为 `CONTAINS*1..2`（绝大多数项目的模块嵌套不超过 2 层）
  - 如果仍需支持 3 层，改为先查 `*1..2`，对未覆盖的模块再补查 `*2..3`
  - 评估性能差异
- **Validate**: 对比优化前后返回的边集合差异（应 < 5%）

### Task 16: 结构检查缓存避免重复执行（P3）
- **File**: `wiki/nodes/heal.py` + `wiki/nodes/quality_gate.py`
- **Action**:
  - 在 pipeline state 中增加 `_structural_check_cache: dict[str, dict]`
  - `quality_gate_node` 将检查结果写入 cache
  - `heal_pages_node` 读取 cache，仅对 cache 中不存在或 content 已变更的页面重新检查
  - Healing 后更新 cache 对应条目
- **Validate**: 验证同一页面在同一管线运行中结构检查最多执行 2 次（而非 4 次）

### Task 17: Token 预算跨组件协调（P2）
- **File**: `wiki/token_budget.py`
- **Action**:
  - `TokenBudgetResolver` 增加 `_consumed: dict[str, int]` 记账
  - 增加 `claim(component, requested) -> granted` 方法，按比例缩减超预算申请
  - `budget_for_snippets` 上限从 3000 提高到 6000（已在 Task 8 中处理）
  - 新增 `budget_for_snippets` 按 `min(500 + module_count * 100, 6000)` 计算（已在 Task 8 中处理）
- **Validate**: 模拟多个组件同时申请预算，验证总消耗不超过 context_window * 0.8

### Task 18: `_consolidate_split_entities` 前缀正则鲁棒性（P3）
- **File**: `wiki/nodes/classify.py:117`
- **Action**:
  - `_PREFIX_RE` 改为 `re.compile(r"^([A-Z][a-z]{2,}|[A-Z]{2,}[a-z]+|[A-Z][a-z]*[A-Z][a-z]+)")`
  - 覆盖 `IOHandler`、`AJAXUtil`、`XMLParser` 等名称
  - `_GENERIC_PREFIXES` 扩充：增加 `Data`, `Info`, `Config`, `Util`, `Tool`, `System`
- **Mirror**: `wiki/nodes/classify.py:117-122` 现有模式
- **Validate**: 验证 `IOHandler`、`XMLParser` 等类名可正确提取前缀

## Validation
```bash
# 运行相关单元测试
pytest tests/wiki/test_domain_semantic_clusterer.py -v
pytest tests/wiki/test_graph_semantic_corrector.py -v
pytest tests/wiki/ -k "decompose or cluster or stabilize" -v

# 验证死代码清理
grep -r "correct_module_assignments" wiki/ tests/
grep -r "_MODULE_CORRECTION_PROMPT" wiki/ tests/

# 验证类型检查
python -m py_compile wiki/domain_semantic_clusterer.py
python -m py_compile wiki/graph_semantic_corrector.py
python -m py_compile wiki/graph_call_query.py
python -m py_compile wiki/nodes/graph_domain_decompose.py
python -m py_compile wiki/nodes/heal.py
python -m py_compile wiki/token_budget.py
python -m py_compile wiki/domain_stabilizer.py
python -m py_compile wiki/nodes/classify.py
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| 嵌入文本过长导致向量质量下降 | Low | 控制在合理长度（<1000 字符） |
| 并行 LLM 调用触发 rate limit | Medium | 使用现有 `PipelineConcurrency` 信号量 |
| k 范围扩大增加聚类耗时 | Low | 仅对 n > 10 的场景生效 |
| 权重感知折扣改变现有聚类结果 | Medium | 通过测试验证，可随时回退为固定折扣 |
| TF-IDF fallback 向量质量不如嵌入 | Medium | 仅在嵌入服务不可用时降级，优于纯 Louvain |
| 域稳定器阈值过低导致错误映射 | Low | 编辑距离仅作辅助，不替代 Jaccard 主匹配 |
| `CONTAINS*1..2` 丢失深层模块边 | Low | 评估差异 < 5%，可按需降回 `*1..3` |
| WHERE 子句下推改变返回结果 | Low | 对比验证前后结果一致 |

## Acceptance
- [ ] 嵌入文本包含路径 4 级 + 方法签名 + docstring
- [ ] 3 个以上模块即可进行聚类
- [ ] 调用图边折扣考虑权重
- [ ] 全局审查传递每个域 top 10 模块含路径和摘要
- [ ] Cypher 查询并行执行
- [ ] 域命名并行执行
- [ ] Healing 不触发不必要的二次 LLM 调用
- [ ] Snippet 预算上限提高到 6000
- [ ] 死代码已清理
- [ ] 关键词合并可配置、单词边界匹配
- [ ] 嵌入失败 fallback 使用 TF-IDF 而非纯 Louvain
- [ ] 域稳定器阈值降至 0.72、支持编辑距离
- [ ] Cypher 查询异常不再静默吞没
- [ ] `CONTAINS` 路径深度优化为 `*1..2`
- [ ] 结构检查通过 cache 避免重复执行
- [ ] Token 预算有跨组件记账
- [ ] `_consolidate_split_entities` 正则覆盖 camelCase 多段式类名
- [ ] 所有相关测试通过
