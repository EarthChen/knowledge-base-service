# Phase 7 完成后系统审阅报告

> **日期:** 2026-05-01  
> **范围:** Phase 7（P0 关键修复 + P1 架构整合）完成后全面审阅  
> **替代:** `SYSTEM_REVIEW_20260501_182703_comprehensive_audit.md`（已归档）

---

## 1. Phase 7 完成状态

### 全部完成项 (16 Tasks + Code Review)

| 分类 | 内容 | 状态 |
|------|------|------|
| P0-1 | `unified_knowledge_query` 接入 IterativeRAGEngine | ✅ |
| P0-3 | `GatewayLLMProviderAdapter.max_context_tokens` 动态化 | ✅ |
| P0-4 | 文档工具数量 20→22 统一 | ✅ |
| P0-5 | CODEMAPS 断裂链接修复 | ✅ |
| P1-A | LLM 抽象层统一为 2 层（BaseLLMProvider + LLMPort） | ✅ |
| P1-B | 3 套搜索系统收敛为 IterativeRAGEngine 单内核 | ✅ |
| P1-B2 | IterativeRAGEngine 3-LLM 自适应升级（plan/evaluate 节点） | ✅ |
| P1-C | Business 路由去重 + compose_concurrency 统一 | ✅ |
| CR | Code Review 修复（4 Critical + 8 Warning + 9 Info） | ✅ |

### 测试结果

- **2506 passed, 0 skipped, 0 failed** (128.95s)

---

## 2. 当前架构

### 2.1 LLM 抽象层（2 层）

```
层1: BaseLLMProvider (基础设施层)
  ├─ 方法: complete, complete_stream, complete_json, close
  ├─ 实现: OpenAIProvider, AzureOpenAIProvider, CustomOpenAIProvider
  └─ 适配: GatewayLLMProviderAdapter (包装 LLMProvider HTTP 客户端)

层2: LLMPort (统一领域端口) ← wiki/llm_port.py
  ├─ 方法: generate(prompt, system, *, model, max_tokens, reasoning_effort)
  ├─        complete(messages, **kwargs)
  └─        complete_stream(messages, **kwargs)
  └─ 适配: LLMPortBridge → _LLMPortWithDefault（注入路由模型）
```

### 2.2 搜索系统（统一内核）

```
API 端点（不变）    编排层（保留差异化）       统一内核           检索层
───────────      ─────────────────      ────────          ───────
/deep-search  →  DeepSearchEngine     →  IterativeRAG  →  HybridGraphRetriever
/ask/stream   →  WikiAskService       →  IterativeRAG  →    ├─ HybridQueryService
/wiki/research → DeepResearchService  →  IterativeRAG  →    └─ GraphQueryService(entity)
MCP tool      →  WikiMCPHandler       →  IterativeRAG  →  WikiRetriever (bootstrap path)
```

### 2.3 IterativeRAGEngine 状态机

```
initial_search → generate_draft → [route_after_draft]
                                    ├─ finalize (conf>=0.85 OR max_rounds OR no queries)
                                    ├─ evaluate (round>=3 AND conf<0.7)
                                    │    └─ [route_after_evaluate]
                                    │         ├─ finalize (is_complete)
                                    │         └─ plan
                                    ├─ plan (round>=2)
                                    │    └─ dynamic_retrieve → generate_draft
                                    └─ dynamic_retrieve (round 1)
                                         └─ generate_draft
```

---

## 3. 已知限制与技术债务

### 3.1 中等优先级

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 1 | **HybridGraphRetriever graph leg 使用 find_entity() 而非 NL→Cypher** | 图查询能力有限，仅做实体名匹配 | 实现 NLCypherService 或接入 LLM-to-Cypher 转换 |
| 2 | **DeepSearchEngine 返回空 business_flows/code_locations** | 依赖这些字段的 Dashboard 功能退化 | 从 RAG draft 中用 LLM 后处理提取结构化字段 |
| 3 | **全局 scope 无 repository 时 WikiRetriever 返回空** | 跨仓库查询不可用 | 实现跨仓库检索机制 |

### 3.2 低优先级

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 4 | **LLMPortBridge.generate 签名不匹配 LLMPort.generate** | extra_params vs reasoning_effort，被 _LLMPortWithDefault 遮蔽 | 对齐签名或在 Bridge 中添加 reasoning_effort 转换 |
| 5 | **WikiAskService._build_messages 是死代码** | 无运行时影响，维护噪声 | 删除或标记 @deprecated |
| 6 | **compose_concurrency 模块导入时固定** | 运行时修改设置不生效 | 改为每次读取 settings（性能可忽略） |

---

## 4. 建议的下一阶段优先事项

### Phase 8 候选项

1. **全局问答增强** — 跨仓库检索 + 无 repository 场景支持
2. **NL-to-Cypher 图查询** — 让 HybridGraphRetriever 的 graph leg 真正生效
3. **DeepSearch 结构化输出恢复** — 从 RAG draft 提取 business_flows / code_locations
4. **LLMPort 签名对齐** — LLMPortBridge.generate 与 LLMPort Protocol 完全一致
5. **前端 SSE 事件适配** — 确认 planning/evaluating 新事件在 Dashboard 中正确渲染

---

## 5. 文件变更汇总

### Phase 7 新建文件
- `wiki/llm_port.py` — 统一 LLMPort Protocol
- `wiki/rag/hybrid_graph_retriever.py` — HybridGraphRetriever
- `tests/wiki/test_llm_port.py`
- `tests/wiki/rag/test_hybrid_graph_retriever.py`
- `tests/wiki/test_mcp_unified_knowledge_rag.py`
- `tests/llm/test_gateway_adapter_context_tokens.py`
- `tests/integration/test_search_unification.py`
- `tests/query/test_deep_search_unified.py`
- `tests/wiki/test_deep_research_unified.py`
- `tests/wiki/rag/test_engine_3llm.py`

### Phase 7 删除文件
- `tests/test_deep_search_json_repair.py` — 死代码测试

### Phase 7 主要修改文件 (17 files in code review round)
- `wiki/rag/engine.py` — 3-LLM 自适应 + evaluate 路由修复
- `wiki/model_strategy.py` — _LLMPortWithDefault 完整实现
- `wiki/mcp_tools.py` — scope 映射 + 错误处理
- `services/kb_service.py` — rag_engine 注入
- `wiki/ask.py` — RAG-only 路径 + 清理
- `query/deep_search.py` — 委托 + 死代码删除
- `wiki/deep_research.py` — 委托 + 错误处理
- `wiki/rag/hybrid_graph_retriever.py` — find_entity 替代
- `config.py` — 新增 domain_classification_cache_enabled
- `store/wiki_store.py` — 新增 prune_orphan_sections
