# Spec: WikiPageAgent 工具增强与上下文管理

**日期**: 2026-05-07
**状态**: Approved (2026-05-07 22:56)
**实现策略变更**: read_code 改为纯 Cypher 方案（方案A+），不依赖 SourceCodeReader

---

## 1. 背景与目标

当前 `WikiPageAgent` 有 6 个图谱查询工具，全部围绕"代码结构元数据"（方法签名、调用关系、实现关系）。缺少：

1. **完整代码逻辑读取** — `read_source_snippet` 截断到 600 字符，无法看到完整的业务流程
2. **实体搜索能力** — 无法按关键字搜索代码实体
3. **跨页面感知** — 无法读取已生成的其他 Wiki 页面
4. **语义搜索** — 无法通过自然语言搜索代码库

对比 DeepWiki（GitTool.ReadFile/ListFiles/Grep + DocTool.ReadDoc/EditDoc），我们的 Agent 工具覆盖面不足。

**目标**：新增 5 个工具 + 增强上下文管理，使 Agent 能够获取更深入的代码逻辑和跨页面信息。

---

## 2. 新增工具设计

### 2.1 `read_code`（P0）

**功能**：读取函数/类的完整源代码。

**实现路径**：纯 Cypher 查询（方案A+），直接从图谱 `code_snippet` 属性获取代码，不依赖 SourceCodeReader。

**方案选择理由**：
- Agent 的 `max_chars` 默认 3000 字符（~80行），即使从文件读取也会被截断
- 不依赖 repo_path（生产环境可能不可用）、不需改构造函数
- 未来可叠加 SourceCodeReader 集成作为增强

**Tool Schema**：
```json
{
    "name": "read_code",
    "description": "Read source code for a function or class by name. Returns code snippet with file location.",
    "parameters": {
        "type": "object",
        "properties": {
            "entity_name": {
                "type": "string",
                "description": "Function or class name to read code for"
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (default 3000)"
            }
        },
        "required": ["entity_name"]
    }
}
```

**Cypher 查询** (`ENTITY_LOCATION_CY`)：
```cypher
MATCH (f)
WHERE (f:Function OR f:Class) AND f.name = $name
RETURN f.name AS name, f.file AS file,
       coalesce(f.start_line, 0) AS start_line,
       coalesce(f.end_line, 0) AS end_line,
       coalesce(f.code_snippet, '') AS snippet,
       labels(f)[0] AS type
LIMIT 3
```

**执行逻辑**：
1. 查询图谱获取实体的 `name`, `file`, `start_line`, `end_line`, `code_snippet`, `type`
2. 返回 `code_snippet[:max_chars]`（默认 3000 字符，比现有 read_source_snippet 的 600 字符限制大幅提升）
3. 包含文件位置信息供 LLM 引用

**返回格式**：
```json
{
    "name": "processOrder",
    "type": "Function",
    "file": "com/order/OrderService.java",
    "start_line": 45,
    "end_line": 120,
    "code": "public void processOrder(Order order) {\n    ..."
}
```

### 2.2 `read_file`（P0）

**功能**：按文件路径读取任意文件（包括未索引的配置文件、不支持语言的源码等）。

**实现路径**：文件系统直接读取，需要 `repo_path` 参数。

**与 read_code 的分工**：
- `read_code` — 按实体名（函数/类）查图谱，适用于已索引代码
- `read_file` — 按文件路径读文件系统，适用于任意文件

**Tool Schema**：
```json
{
    "name": "read_file",
    "description": "Read file content by path. Supports any file type including config, source code, and documentation.",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Relative file path from repository root (e.g., 'config/application.yaml')"
            },
            "start_line": {
                "type": "integer",
                "description": "Start line number (1-based, default 1)"
            },
            "end_line": {
                "type": "integer",
                "description": "End line number (default: start_line + 100)"
            }
        },
        "required": ["file_path"]
    }
}
```

**安全约束**：
- 路径必须是相对路径，resolve 后必须在 `repo_path` 范围内
- 禁止 `../` 路径穿越（`resolved.is_relative_to(repo_root)` 检查）
- `repo_path` 不可用时返回 `{"error": "file reading unavailable"}`

**执行逻辑**：
1. 校验 `repo_path` 是否可用
2. 安全检查：resolve 路径，确保在 repo 范围内
3. 读取文件指定行范围（默认最多 100 行）
4. 截断到 `SINGLE_RESULT_LIMIT`（4000 字符）

**返回格式**：
```json
{
    "file_path": "config/application.yaml",
    "start_line": 1,
    "end_line": 50,
    "content": "server:\n  port: 8080\n  ...",
    "total_lines": 120
}
```

### 2.3 `search_entities`（P0）

**功能**：按关键字搜索代码实体（函数/类/模块）。

**Tool Schema**：
```json
{
    "name": "search_entities",
    "description": "Search code entities by keyword in names, docstrings, and annotations",
    "parameters": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Keyword to search for (case-insensitive)"
            },
            "entity_type": {
                "type": "string",
                "description": "Filter by type: Function, Class, Module, or all (default: all)"
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 10)"
            }
        },
        "required": ["keyword"]
    }
}
```

**Cypher 查询**：
```cypher
MATCH (n)
WHERE (n:Function OR n:Class OR n:Module)
  AND (toLower(n.name) CONTAINS toLower($keyword)
       OR toLower(coalesce(n.docstring, '')) CONTAINS toLower($keyword)
       OR toLower(coalesce(n.annotations, '')) CONTAINS toLower($keyword))
RETURN n.name AS name, labels(n)[0] AS type,
       coalesce(n.file, '') AS file,
       coalesce(n.signature, '') AS signature,
       left(coalesce(n.docstring, ''), 200) AS docstring
LIMIT $limit
```

**返回格式**：
```json
{
    "results": [
        {"name": "OrderService", "type": "Class", "file": "a.java", "signature": "", "docstring": "..."},
        {"name": "processOrder", "type": "Function", "file": "a.java", "signature": "void processOrder(Order)", "docstring": "..."}
    ],
    "total": 2
}
```

### 2.4 `read_wiki_page`（P1）

**功能**：读取已生成的 Wiki 页面内容。

**Tool Schema**：
```json
{
    "name": "read_wiki_page",
    "description": "Read an existing wiki page by path or title keyword. Helps avoid content duplication and contradictions.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Page path (e.g., /wiki/order-processing) or title keyword"
            }
        },
        "required": ["query"]
    }
}
```

**执行逻辑**：
1. 先从当前 Pipeline state 的 `pages` 列表中搜索（如果可用）
2. 如果没找到，通过图谱查询 WikiPage 节点
3. 返回页面标题 + 内容摘要（截断到 SINGLE_RESULT_LIMIT）

**数据来源优先级**：
- `enrich()` 方法新增可选参数 `existing_pages: list[dict] | None`
- 由 `_compose_single_leaf_domain` 传入当前已生成的页面列表

**Cypher fallback**：
```cypher
MATCH (w:WikiPage)
WHERE w.path CONTAINS $query OR toLower(w.title) CONTAINS toLower($query)
RETURN w.title AS title, w.path AS path, left(w.content, $limit) AS content
LIMIT 3
```

### 2.5 `semantic_search`（P2）

**功能**：通过自然语言语义搜索代码库和 Wiki。

**Tool Schema**：
```json
{
    "name": "semantic_search",
    "description": "Semantic search across code and wiki using vector embeddings. Use natural language queries.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language query"
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 5)"
            }
        },
        "required": ["query"]
    }
}
```

**执行逻辑**：
1. 调用 `HybridSearchService.search_with_context()` 
2. 需要在 `WikiPageAgent.__init__` 中接收可选的 `search_service` 参数
3. 如果 search_service 不可用，返回 "semantic search unavailable"

**返回格式**：
```json
{
    "results": [
        {"title": "OrderService", "content": "...", "source": "code", "score": 0.92},
        {"title": "订单处理", "content": "...", "source": "wiki", "score": 0.85}
    ]
}
```

---

## 3. WorkingMemory 增强

### 3.1 新增字段

```python
@dataclass
class WorkingMemory:
    # 已有字段
    discovered_call_chains: list[str]
    discovered_implementations: list[str]
    discovered_callers: list[str]
    code_snippets: list[str]
    resolved_gaps: list[str]
    # 新增字段
    wiki_references: list[str] = field(default_factory=list)
    search_findings: list[str] = field(default_factory=list)
```

### 3.2 参数调整

| 参数 | 当前值 | 新值 | 理由 |
|------|--------|------|------|
| `MAX_TOTAL_CHARS` | 6000 | 18000 | 容纳完整代码块（约 6000 tokens，占 128K 模型的 ~5%） |
| `MAX_ROUNDS` | 5 | 6 | 新增工具后需要略更多轮次 |
| `SINGLE_RESULT_LIMIT`（新增） | - | 4000 | 单个工具返回结果的最大字符数 |
| `MAX_TOOL_CALLS`（新增） | - | 15 | 总工具调用次数限制，防止无限循环 |

### 3.3 incorporate() 新增提取规则

```python
def incorporate(self, results: list[ToolResult]) -> None:
    for r in results:
        if r.tool == "read_code":
            code = r.data.get("code", "")
            name = r.data.get("name", "")
            if code:
                self.code_snippets.append(f"[{name}]\n{code[:SINGLE_RESULT_LIMIT]}")
        elif r.tool == "read_file":
            content = r.data.get("content", "")
            path = r.data.get("file_path", "")
            if content:
                self.code_snippets.append(f"[{path}]\n{content[:SINGLE_RESULT_LIMIT]}")
        elif r.tool == "search_entities":
            items = r.data.get("results", [])
            for item in items[:5]:
                self.search_findings.append(
                    f"{item['type']} {item['name']} ({item.get('file', '')})"
                )
        elif r.tool == "read_wiki_page":
            content = r.data.get("content", "")
            title = r.data.get("title", "")
            if content:
                self.wiki_references.append(f"[{title}] {content[:2000]}")
        elif r.tool == "semantic_search":
            items = r.data.get("results", [])
            for item in items[:3]:
                self.search_findings.append(
                    f"[{item.get('source', '')}] {item['title']}: {item['content'][:500]}"
                )
    self._enforce_limit()
```

### 3.4 工具调用计数器

在 `enrich()` 方法的工具调用循环中添加：

```python
total_tool_calls = 0
for round_num in range(self.MAX_ROUNDS):
    # ... LLM tool calling ...
    if tool_calls:
        total_tool_calls += len(tool_calls)
        if total_tool_calls >= self.MAX_TOOL_CALLS:
            break  # 强制进入 final generation
```

---

## 4. 集成点

### 4.1 WikiPageAgent 构造函数扩展

```python
class WikiPageAgent:
    MAX_ROUNDS = 6          # 从 5 调整到 6
    MAX_TOOL_CALLS = 15     # 新增
    SINGLE_RESULT_LIMIT = 4000  # 新增

    def __init__(
        self,
        llm,
        graph_store,
        *,
        repo_path: str | None = None,  # 新增：用于 read_file（可选）
        search_service=None,           # 新增：用于 semantic_search（可选）
    ):
```

> **注意**: `read_code` 和 `search_entities` 使用纯 Cypher，不需要额外参数。`read_file` 需要 `repo_path`，`semantic_search` 需要 `search_service`。

### 4.2 enrich() API 扩展

```python
async def enrich(
    self, content: str, *,
    domain_name: str = "",
    existing_pages: list[dict] | None = None,  # 新增：供 read_wiki_page 使用
) -> str:
```

### 4.3 Pipeline 集成（延后）

Pipeline 集成点 (`_compose_single_leaf_domain`) 的变更留给实施阶段处理，核心变更为：
- 传入 `existing_pages` 到 `agent.enrich()`
- 可选传入 `repo_path` 和 `search_service` 到构造函数

### 4.4 Cypher 查询集中管理

新增 Cypher 查询常量到 `wiki/cypher_queries.py`：

- `ENTITY_LOCATION_CY` — 查询实体位置（read_code 使用）
- `SEARCH_ENTITIES_CY` — 关键字搜索（search_entities 使用）
- `WIKI_PAGE_BY_QUERY_CY` — Wiki 页面查询（read_wiki_page fallback 使用）

---

## 5. 向后兼容

- `read_code` 和 `search_entities` 使用纯 Cypher，无需额外参数
- `repo_path` 是可选参数，不传入时 `read_file` 返回 "file reading unavailable"
- `search_service` 是可选参数，不传入时 `semantic_search` 返回 "service unavailable"
- `existing_pages` 是可选参数，不传入时 `read_wiki_page` 仅查图谱
- 已有 6 个工具行为不变
- 原有测试不需要修改

---

## 6. 测试计划

### 单元测试
- `test_read_code_returns_snippet` — 从图谱获取代码片段
- `test_read_code_max_chars_enforced` — max_chars 参数截断验证
- `test_read_code_empty_result` — 实体不存在时返回空结果
- `test_read_file_success` — 从文件系统读取文件
- `test_read_file_path_traversal_blocked` — 路径穿越安全检查
- `test_read_file_no_repo_path` — repo_path 不可用时返回错误
- `test_search_entities_by_name` — 按名称搜索
- `test_search_entities_by_annotation` — 按注解搜索
- `test_read_wiki_page_from_existing_pages` — 从已生成页面读取
- `test_read_wiki_page_from_graph` — 从图谱 WikiPage 节点读取
- `test_semantic_search_integration` — 语义搜索集成
- `test_max_tool_calls_enforced` — 工具调用次数限制
- `test_single_result_limit_enforced` — 单个结果大小限制
- `test_working_memory_18k_capacity` — 新容量验证
