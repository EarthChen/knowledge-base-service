# Proposal: Wiki 反幻觉三层架构

**创建时间:** 2026-05-07  
**状态:** Phase 1 已实施，Phase 2-3 待开发  
**关联 Issue:** #005（Wiki LLM 幻觉）  

---

## 1. 背景与问题

### 1.1 现象

Wiki 生成管线产出的页面存在严重幻觉问题：

- **虚构 `source://` 引用**：LLM 编造文件路径和行号（如 `LiveSendBusinessHandler.java:87`），与真实代码完全不符
- **虚构业务逻辑**：当缺乏代码上下文时，LLM 凭训练数据杜撰"幂等校验""风控调用"等实现细节
- **关联代码过少**：一个涉及多文件协作的功能，wiki 仅引用单一文件

### 1.2 根因定位

**直接原因**：`wiki/service.py` 调用 `run_langgraph_pipeline()` 时，未传递 `graph_store` 和 `wiki_store` 参数。导致 `ContentContextBuilder` 收到 `None`，所有图查询返回空列表，LLM 在**零上下文**下全面虚构。

**间接原因**：即使修复了 `graph_store` 传递，仍缺乏系统性防线来应对 LLM 在上下文不足时的臆造倾向。

---

## 2. 行业方案研究

### 2.1 Citation-Grounded Code Comprehension（Auburn University 论文）

最严谨的学术方案，实现 **92% 引用准确率、0% 幻觉率**：

| 技术 | 说明 |
|------|------|
| Hybrid Retrieval | BM25 (α=0.45) + BGE dense embeddings (β=0.55)，兼顾精确匹配与语义理解 |
| Graph Expansion | 通过 import graph 1-hop BFS 发现跨文件依赖，召回率提升 24% |
| Mechanical Citation Verification | 每个 `[file:start-end]` 引用通过区间算术验证是否与 retrieved chunks 重叠 |
| Auto-cite Fallback | LLM 未生成引用时，自动附加最高匹配 chunk 的引用 |

### 2.2 DeepWiki-Open（GitHub 15K+ stars）

| 技术 | 说明 |
|------|------|
| RAG 分层查询 | core + architecture + broader context 三层 |
| FAISS 向量检索 | 配合去重排序 |
| WikiStructureValidator | 结构化验证生成内容的完整性 |

### 2.3 CodeWiki（ACL 2026，超越 DeepWiki 4.73%）

| 技术 | 说明 |
|------|------|
| 层次化分解 | 动态规划保持架构上下文 |
| 递归多智能体 | 根据模块复杂度动态委派 |
| 跨模块引用维护 | 保持源可追溯性 |

---

## 3. 三层反幻觉架构设计

### 核心原则

> **"Never trust LLM citations — generate them mechanically."**

### 3.1 第一层：Source-Grounded Generation（输入端）— ✅ 已实施

**对应行业方案**：Auburn 论文的 Hybrid Retrieval + Graph Expansion、DeepWiki 的 RAG 分层查询、CodeWiki 的层次化分解。

**核心思想**：确保 LLM 拿到**真实源码**而非仅类名。

**已完成的工作**：

- [x] 修复 `graph_store` 传递链路：`service.py` → `pipeline_orchestrator.py` → `pipeline_nodes.py` → `ContentContextBuilder`
- [x] `ContentContextBuilder` 查询 `Function.code_snippet`（`_SNIPPETS_CY`）
- [x] `ContentContextBuilder` 查询 `Chunk.text` 作为 fallback（`_CHUNK_SNIPPETS_CY`，已修复 `PART_OF` 关系类型）
- [x] Prompt 反幻觉约束：禁止 LLM 生成 `source://` 链接，禁止在缺乏代码上下文时臆造业务逻辑

**P3 增强方向**：

- [ ] 引入向量检索（BGE embeddings + FAISS/FalkorDB vector index）
- [ ] Import graph 1-hop BFS 扩展跨文件依赖

### 3.2 第二层：Mechanical Citation Injection（输出端）— ❌ 待实现

**对应行业方案**：Auburn 论文的 Mechanical Citation Verification + Auto-cite Fallback、DeepWiki 的 Source Code Linking、CodeWiki 的跨模块引用维护。

**核心思想**：系统自动注入**经过图数据库验证**的引用，不依赖 LLM 生成。

**实现步骤**：

1. 扫描 LLM 输出中的 `ClassName` / `methodName()` 标识符
2. 在 FalkorDB 图中查找匹配实体的 `file` + `start_line` + `end_line`
3. 生成并注入验证过的 `source://` 链接
4. 对 LLM 意外生成的未验证 `source://` 链接予以移除

**Cypher 查询模板**：

```cypher
MATCH (e)
WHERE (e:Class OR e:Function)
  AND toLower(e.name) = toLower($entity_name)
  AND e.file IS NOT NULL
RETURN e.name, e.file, e.start_line, e.end_line, labels(e)[0] AS type
LIMIT 5
```

### 3.3 第三层：Post-Generation Fact Check（验证端）— ❌ 待实现

**对应行业方案**：Auburn 论文的 Hallucination Detection、DeepWiki 的 WikiStructureValidator、CodeWiki 的 LLM-based Assessment。

**核心思想**：对生成内容中提到的技术实体做**事实核查**，标记或删除不可验证的描述。

#### 3.3.1 技术实体提取

从 Markdown 内容中提取三类实体：

| 类型 | 识别方式 | 示例 |
|------|----------|------|
| `code_ref` | 正则匹配反引号中的代码引用 `\`ClassName\``、`\`method()\`` | `LiveSendBusinessHandler`, `handleSend()` |
| `tech_stack` | 预定义关键词表匹配 | Redis, Kafka, Hystrix, Spring, gRPC |
| `arch_pattern` | 预定义模式词匹配 | 幂等校验, 熔断降级, 分布式锁 |

**提取实现**（`wiki/fact_checker.py`）：

```python
import re

_CODE_REF_RE = re.compile(r"`([A-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z_]\w*)*(?:\(\))?)`")
_TECH_KEYWORDS = {
    "redis", "kafka", "rabbitmq", "rocketmq", "mysql", "mongodb",
    "elasticsearch", "hystrix", "sentinel", "nacos", "dubbo",
    "spring", "springboot", "grpc", "thrift", "zookeeper",
    "nginx", "gateway", "minio", "oss",
}
_ARCH_PATTERNS = {
    "幂等", "熔断", "降级", "限流", "分布式锁", "事务",
    "补偿", "重试", "异步", "消息队列", "发布订阅",
    "idempotent", "circuit.breaker", "rate.limit", "distributed.lock",
}

def extract_technical_entities(markdown: str) -> dict[str, list[str]]:
    entities: dict[str, list[str]] = {
        "code_ref": [],
        "tech_stack": [],
        "arch_pattern": [],
    }
    entities["code_ref"] = list(set(_CODE_REF_RE.findall(markdown)))
    lower = markdown.lower()
    for kw in _TECH_KEYWORDS:
        if kw in lower:
            entities["tech_stack"].append(kw)
    for pat in _ARCH_PATTERNS:
        if pat.lower() in lower:
            entities["arch_pattern"].append(pat)
    return entities
```

#### 3.3.2 图数据库验证

| 实体类型 | 验证方式 | 未通过处理 |
|----------|----------|------------|
| `code_ref` | 查询 `Module`/`Class`/`Function` 节点 name 匹配 | 移除对应的 `source://` 引用 |
| `tech_stack` | 在代码 chunks/imports 中搜索关键词 | **删除**包含该技术栈的描述段落 |
| `arch_pattern` | 难以精确验证 | **添加警告标签** `[⚠️ 未经源码验证]` |

**验证 Cypher**：

```cypher
// code_ref 验证
MATCH (e) WHERE (e:Class OR e:Function OR e:Module)
  AND toLower(e.name) = toLower($name)
RETURN count(e) > 0 AS exists

// tech_stack 验证
MATCH (c:Chunk) WHERE toLower(c.text) CONTAINS toLower($keyword)
RETURN count(c) > 0 AS exists
```

---

## 4. 旧页面清理机制

### 4.1 问题

非增量全量重新生成后，旧 topic 页面仍保留在 FalkorDB 中。原因是 `persist_wiki_pages` 使用 `MERGE`（基于 UID），当新管线产出不同路径/标题的页面时，旧页面不会被删除。

### 4.2 方案

在 `WikiPersistence` 中新增 `cleanup_stale_wiki_pages` 方法：

```cypher
MATCH (w:WikiPage)
WHERE w.repository = $repo
  AND w.page_type IN ['topic', 'domain_overview']
  AND NOT w.uid IN $keep_uids
DETACH DELETE w
RETURN count(w) AS deleted
```

在 `service.py` 的 `generate_business_wiki` 中，非增量生成完成后自动调用清理。

**状态**：✅ 已实施

---

## 5. 实施路线图

| 优先级 | 层级 | 内容 | 状态 |
|--------|------|------|------|
| **P0** | Layer 1 | 修复 `graph_store` 传递链路 | ✅ 已完成 |
| **P0** | 清理 | 非增量生成后删除旧 topic 页面 | ✅ 已完成 |
| **P1** | Layer 2 | Mechanical Citation Injection | ❌ 待开发 |
| **P2** | Layer 3 | Post-Generation Fact Check | ❌ 待开发 |
| **P3** | Layer 1+ | 向量检索 + Import Graph Expansion | ❌ 未来方向 |

---

## 6. 验证计划

### 6.1 Layer 1 验证（已通过）

- 确认 `LiveSendBusinessHandler` 及其函数/chunks 存在于 `kb_default` 图
- 触发全量重新生成（`incremental: false`）
- 检查新生成页面内容：类名/方法名/服务名与真实代码吻合
- 确认 `source://` 引用的文件路径和行号准确

### 6.2 Layer 2 验证（计划）

- 验证注入的 `source://` 链接指向真实文件和行号
- 确认 LLM 原始输出中的虚假引用被过滤
- 对比注入前后的引用准确率

### 6.3 Layer 3 验证（计划）

- 抽取 wiki 页面中的技术实体，验证提取完整性
- 确认未在图数据库中验证的技术栈描述被正确处理
- 统计 fact-check 通过率作为内容质量指标
