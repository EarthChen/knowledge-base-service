# WikiPageAgent 工具增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 WikiPageAgent 新增 5 个工具（read_code, read_file, search_entities, read_wiki_page, semantic_search）并增强 WorkingMemory 管理。

**Architecture:** 在现有 WikiPageAgent 框架上扩展，P0 工具（read_code, read_file, search_entities）使用纯 Cypher/文件系统无新外部依赖，P1/P2 工具通过可选参数注入。WorkingMemory 扩容到 18K 字符并新增工具调用计数器。

**Tech Stack:** Python 3.11+, FalkorDB Cypher, pytest + pytest-asyncio

**Spec:** `docs/proposals/SPEC_20260507_224402_agent_tools_enhancement.md`

---

### Task 1: WorkingMemory 增强

**Files:**
- Modify: `wiki/page_agent.py:17-138` (WorkingMemory dataclass)
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing tests for new WorkingMemory fields and limits**

```python
# tests/wiki/test_page_agent.py — 在 TestWorkingMemory 类中新增

def test_new_fields_exist(self):
    wm = WorkingMemory()
    assert hasattr(wm, "wiki_references")
    assert hasattr(wm, "search_findings")
    assert isinstance(wm.wiki_references, list)
    assert isinstance(wm.search_findings, list)

def test_max_total_chars_18k(self):
    assert WorkingMemory.MAX_TOTAL_CHARS == 18000

def test_incorporate_read_code(self):
    wm = WorkingMemory()
    wm.incorporate([
        ToolResult(tool="read_code", data={
            "name": "processOrder",
            "code": "public void processOrder() { /* long code */ }",
        })
    ])
    assert len(wm.code_snippets) == 1
    assert "processOrder" in wm.code_snippets[0]

def test_incorporate_read_file(self):
    wm = WorkingMemory()
    wm.incorporate([
        ToolResult(tool="read_file", data={
            "file_path": "config/app.yaml",
            "content": "server:\n  port: 8080",
        })
    ])
    assert len(wm.code_snippets) == 1
    assert "config/app.yaml" in wm.code_snippets[0]

def test_incorporate_search_entities(self):
    wm = WorkingMemory()
    wm.incorporate([
        ToolResult(tool="search_entities", data={
            "results": [
                {"name": "OrderService", "type": "Class", "file": "a.java"},
                {"name": "save", "type": "Function", "file": "b.java"},
            ],
            "total": 2,
        })
    ])
    assert len(wm.search_findings) == 2

def test_incorporate_read_wiki_page(self):
    wm = WorkingMemory()
    wm.incorporate([
        ToolResult(tool="read_wiki_page", data={
            "title": "订单处理",
            "content": "本文档描述了订单处理的完整流程...",
        })
    ])
    assert len(wm.wiki_references) == 1
    assert "订单处理" in wm.wiki_references[0]

def test_incorporate_semantic_search(self):
    wm = WorkingMemory()
    wm.incorporate([
        ToolResult(tool="semantic_search", data={
            "results": [
                {"title": "OrderService", "content": "handles orders", "source": "code"},
            ]
        })
    ])
    assert len(wm.search_findings) == 1

def test_working_memory_18k_capacity(self):
    wm = WorkingMemory()
    for i in range(200):
        wm.incorporate([
            ToolResult(tool="read_code", data={
                "name": f"func{i}",
                "code": "x" * 200,
            })
        ])
    assert wm._total_chars() <= WorkingMemory.MAX_TOTAL_CHARS

def test_to_prompt_section_includes_new_fields(self):
    wm = WorkingMemory()
    wm.wiki_references.append("[订单] 内容摘要")
    wm.search_findings.append("[code] OrderService: 处理订单")
    text = wm.to_prompt_section()
    assert "Wiki 引用" in text or "订单" in text
    assert "OrderService" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWorkingMemory -v`
Expected: Multiple FAILs (new fields don't exist, MAX_TOTAL_CHARS != 18000, new tool names not handled)

- [ ] **Step 3: Implement WorkingMemory enhancements**

In `wiki/page_agent.py`, update the `WorkingMemory` dataclass:

```python
@dataclass
class WorkingMemory:
    discovered_call_chains: list[str] = field(default_factory=list)
    discovered_implementations: list[str] = field(default_factory=list)
    discovered_callers: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    resolved_gaps: list[str] = field(default_factory=list)
    wiki_references: list[str] = field(default_factory=list)
    search_findings: list[str] = field(default_factory=list)

    MAX_TOTAL_CHARS = 18000
    SINGLE_RESULT_LIMIT = 4000
```

Update `incorporate()` to handle new tools:

```python
def incorporate(self, results: list[ToolResult]) -> None:
    for r in results:
        tool = r.tool
        data = r.data
        if tool == "read_code":
            code = str(data.get("code", "") or "")
            name = str(data.get("name", "") or "")
            if code:
                self.code_snippets.append(f"[{name}]\n{code[:self.SINGLE_RESULT_LIMIT]}")
        elif tool == "read_file":
            content = str(data.get("content", "") or "")
            path = str(data.get("file_path", "") or "")
            if content:
                self.code_snippets.append(f"[{path}]\n{content[:self.SINGLE_RESULT_LIMIT]}")
        elif tool == "search_entities":
            items = data.get("results", [])
            for item in items[:5]:
                if isinstance(item, dict):
                    self.search_findings.append(
                        f"{item.get('type', '')} {item.get('name', '')} ({item.get('file', '')})"
                    )
        elif tool == "read_wiki_page":
            content = str(data.get("content", "") or "")
            title = str(data.get("title", "") or "")
            if content:
                self.wiki_references.append(f"[{title}] {content[:2000]}")
        elif tool == "semantic_search":
            items = data.get("results", [])
            for item in items[:3]:
                if isinstance(item, dict):
                    self.search_findings.append(
                        f"[{item.get('source', '')}] {item.get('title', '')}: {str(item.get('content', ''))[:500]}"
                    )
        # Keep existing handlers for old tools
        elif tool == "query_call_chain":
            # ... existing logic unchanged ...
        elif tool == "query_callers":
            # ... existing logic unchanged ...
        # ... etc ...
    self._enforce_limit()
```

Update `_enforce_limit()` and `_total_chars()` to include new fields:

```python
def _enforce_limit(self) -> None:
    total = self._total_chars()
    while total > self.MAX_TOTAL_CHARS:
        removed = False
        for lst in [
            self.code_snippets,
            self.discovered_callers,
            self.discovered_implementations,
            self.discovered_call_chains,
            self.resolved_gaps,
            self.wiki_references,
            self.search_findings,
        ]:
            if lst:
                lst.pop(0)
                removed = True
                break
        if not removed:
            break
        total = self._total_chars()

def _total_chars(self) -> int:
    total = 0
    for lst in [
        self.discovered_call_chains,
        self.discovered_implementations,
        self.discovered_callers,
        self.code_snippets,
        self.resolved_gaps,
        self.wiki_references,
        self.search_findings,
    ]:
        total += sum(len(s) for s in lst)
    return total
```

Update `to_prompt_section()` to include new fields:

```python
if self.wiki_references:
    sections.append("### 已引用的 Wiki 页面")
    sections.extend(self.wiki_references)
if self.search_findings:
    sections.append("### 搜索发现")
    sections.extend(f"- {f}" for f in self.search_findings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWorkingMemory -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agent): enhance WorkingMemory with new fields and 18K capacity"
```

---

### Task 2: Cypher 查询常量

**Files:**
- Modify: `wiki/cypher_queries.py`
- Test: (验证导入即可，无独立测试)

- [ ] **Step 1: Add new Cypher query constants**

在 `wiki/cypher_queries.py` 文件末尾添加：

```python
ENTITY_LOCATION_CY = """
MATCH (f)
WHERE (f:Function OR f:Class) AND f.name = $name
RETURN f.name AS name, coalesce(f.file, '') AS file,
       coalesce(f.start_line, 0) AS start_line,
       coalesce(f.end_line, 0) AS end_line,
       coalesce(f.code_snippet, '') AS snippet,
       labels(f)[0] AS type
LIMIT 3
""".strip()

SEARCH_ENTITIES_CY = """
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
""".strip()

WIKI_PAGE_BY_QUERY_CY = """
MATCH (w:WikiPage)
WHERE w.path CONTAINS $query OR toLower(w.title) CONTAINS toLower($query)
RETURN w.title AS title, w.path AS path, left(w.content, $limit) AS content
LIMIT 3
""".strip()
```

- [ ] **Step 2: Verify import works**

Run: `cd knowledge-base-service && python -c "from wiki.cypher_queries import ENTITY_LOCATION_CY, SEARCH_ENTITIES_CY, WIKI_PAGE_BY_QUERY_CY; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add wiki/cypher_queries.py
git commit -m "feat(cypher): add ENTITY_LOCATION_CY, SEARCH_ENTITIES_CY, WIKI_PAGE_BY_QUERY_CY"
```

---

### Task 3: read_code 工具

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_page_agent.py — 在 TestWikiPageAgent 类中新增

@pytest.mark.asyncio
async def test_read_code_returns_snippet(self):
    llm = MagicMock()
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[
        {"name": "processOrder", "file": "OrderService.java",
         "start_line": 10, "end_line": 50, "snippet": "public void processOrder() { /* code */ }",
         "type": "Function"}
    ]))
    agent = WikiPageAgent(llm, gs)
    result = await agent._execute_tool("read_code", {"entity_name": "processOrder"})
    assert result["name"] == "processOrder"
    assert result["code"] == "public void processOrder() { /* code */ }"
    assert result["file"] == "OrderService.java"

@pytest.mark.asyncio
async def test_read_code_max_chars(self):
    llm = MagicMock()
    gs = MagicMock()
    long_code = "x" * 5000
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[
        {"name": "big", "file": "a.java", "start_line": 1, "end_line": 200,
         "snippet": long_code, "type": "Function"}
    ]))
    agent = WikiPageAgent(llm, gs)
    result = await agent._execute_tool("read_code", {"entity_name": "big", "max_chars": 100})
    assert len(result["code"]) <= 100

@pytest.mark.asyncio
async def test_read_code_not_found(self):
    llm = MagicMock()
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    agent = WikiPageAgent(llm, gs)
    result = await agent._execute_tool("read_code", {"entity_name": "nonexistent"})
    assert result["code"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_code_returns_snippet tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_code_max_chars tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_code_not_found -v`
Expected: FAIL

- [ ] **Step 3: Implement _tool_read_code**

In `wiki/page_agent.py`, add method to `WikiPageAgent`:

```python
async def _tool_read_code(self, args: dict[str, Any]) -> dict[str, Any]:
    entity_name = str(args.get("entity_name", ""))
    max_chars = int(args.get("max_chars", 3000))
    if not entity_name or not self._graph or not hasattr(self._graph, "execute_query"):
        return {"name": entity_name, "code": "", "file": "", "type": ""}
    from wiki.cypher_queries import ENTITY_LOCATION_CY

    result = await self._graph.execute_query(ENTITY_LOCATION_CY, {"name": entity_name})
    rows = getattr(result, "data", None) or []
    for row in rows:
        if isinstance(row, dict):
            snippet = str(row.get("snippet", "") or "")
            return {
                "name": str(row.get("name", "") or ""),
                "type": str(row.get("type", "") or ""),
                "file": str(row.get("file", "") or ""),
                "start_line": int(row.get("start_line", 0) or 0),
                "end_line": int(row.get("end_line", 0) or 0),
                "code": snippet[:max_chars],
            }
    return {"name": entity_name, "code": "", "file": "", "type": ""}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_code_returns_snippet tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_code_max_chars tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_code_not_found -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agent): add read_code tool with pure Cypher implementation"
```

---

### Task 4: read_file 工具

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_page_agent.py — 在 TestWikiPageAgent 类中新增

@pytest.mark.asyncio
async def test_read_file_success(self, tmp_path):
    test_file = tmp_path / "config" / "app.yaml"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("server:\n  port: 8080\n  host: localhost\n")
    llm = MagicMock()
    gs = MagicMock()
    agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
    result = await agent._execute_tool("read_file", {"file_path": "config/app.yaml"})
    assert "server:" in result["content"]
    assert result["file_path"] == "config/app.yaml"

@pytest.mark.asyncio
async def test_read_file_path_traversal_blocked(self, tmp_path):
    llm = MagicMock()
    gs = MagicMock()
    agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
    result = await agent._execute_tool("read_file", {"file_path": "../../etc/passwd"})
    assert "error" in result

@pytest.mark.asyncio
async def test_read_file_no_repo_path(self):
    llm = MagicMock()
    gs = MagicMock()
    agent = WikiPageAgent(llm, gs)
    result = await agent._execute_tool("read_file", {"file_path": "any.txt"})
    assert "error" in result
    assert "unavailable" in result["error"]

@pytest.mark.asyncio
async def test_read_file_line_range(self, tmp_path):
    test_file = tmp_path / "code.py"
    lines = [f"line {i}\n" for i in range(1, 21)]
    test_file.write_text("".join(lines))
    llm = MagicMock()
    gs = MagicMock()
    agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
    result = await agent._execute_tool("read_file", {
        "file_path": "code.py", "start_line": 5, "end_line": 10
    })
    assert "line 5" in result["content"]
    assert "line 10" in result["content"]
    assert "line 11" not in result["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_success tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_path_traversal_blocked tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_no_repo_path tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_line_range -v`
Expected: FAIL

- [ ] **Step 3: Update WikiPageAgent constructor + implement _tool_read_file**

```python
class WikiPageAgent:
    MAX_ROUNDS = 6
    MAX_TOOL_CALLS = 15
    SINGLE_RESULT_LIMIT = 4000

    def __init__(
        self,
        llm: Any,
        graph_store: Any,
        *,
        repo_path: str | None = None,
        search_service: Any | None = None,
    ) -> None:
        self._llm = llm
        self._graph = graph_store
        self._repo_path = repo_path
        self._search_service = search_service

    async def _tool_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        file_path = str(args.get("file_path", ""))
        start_line = max(1, int(args.get("start_line", 1) or 1))
        end_line = int(args.get("end_line", 0) or 0)
        if not end_line:
            end_line = start_line + 100

        if not file_path:
            return {"error": "missing file_path"}
        if not self._repo_path:
            return {"error": "file reading unavailable"}

        from pathlib import Path
        repo_root = Path(self._repo_path).resolve()
        target = (repo_root / file_path).resolve()
        if not target.is_relative_to(repo_root):
            return {"error": "path traversal not allowed"}
        if not target.is_file():
            return {"error": f"file not found: {file_path}"}

        try:
            all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(all_lines)
            selected = all_lines[max(0, start_line - 1):end_line]
            content = "\n".join(selected)
            return {
                "file_path": file_path,
                "start_line": start_line,
                "end_line": min(end_line, total_lines),
                "content": content[:self.SINGLE_RESULT_LIMIT],
                "total_lines": total_lines,
            }
        except OSError as e:
            return {"error": f"read failed: {e}"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_success tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_path_traversal_blocked tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_no_repo_path tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_file_line_range -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agent): add read_file tool with path security checks"
```

---

### Task 5: search_entities 工具

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_search_entities_by_name(self):
    llm = MagicMock()
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[
        {"name": "OrderService", "type": "Class", "file": "a.java", "signature": "", "docstring": "Handles orders"},
    ]))
    agent = WikiPageAgent(llm, gs)
    result = await agent._execute_tool("search_entities", {"keyword": "Order"})
    assert result["total"] == 1
    assert result["results"][0]["name"] == "OrderService"

@pytest.mark.asyncio
async def test_search_entities_empty(self):
    llm = MagicMock()
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    agent = WikiPageAgent(llm, gs)
    result = await agent._execute_tool("search_entities", {"keyword": "xyz"})
    assert result["total"] == 0
    assert result["results"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_search_entities_by_name tests/wiki/test_page_agent.py::TestWikiPageAgent::test_search_entities_empty -v`
Expected: FAIL

- [ ] **Step 3: Implement _tool_search_entities**

```python
async def _tool_search_entities(self, args: dict[str, Any]) -> dict[str, Any]:
    keyword = str(args.get("keyword", ""))
    limit = min(int(args.get("limit", 10) or 10), 20)
    if not keyword or not self._graph or not hasattr(self._graph, "execute_query"):
        return {"results": [], "total": 0}
    from wiki.cypher_queries import SEARCH_ENTITIES_CY

    result = await self._graph.execute_query(
        SEARCH_ENTITIES_CY, {"keyword": keyword, "limit": limit},
    )
    rows = getattr(result, "data", None) or []
    results = []
    for row in rows:
        if isinstance(row, dict):
            results.append({
                "name": str(row.get("name", "") or ""),
                "type": str(row.get("type", "") or ""),
                "file": str(row.get("file", "") or ""),
                "signature": str(row.get("signature", "") or ""),
                "docstring": str(row.get("docstring", "") or ""),
            })
    return {"results": results, "total": len(results)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_search_entities_by_name tests/wiki/test_page_agent.py::TestWikiPageAgent::test_search_entities_empty -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agent): add search_entities tool with Cypher keyword search"
```

---

### Task 6: read_wiki_page 工具

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_read_wiki_page_from_existing(self):
    llm = MagicMock()
    gs = MagicMock()
    agent = WikiPageAgent(llm, gs)
    agent._existing_pages = [
        {"title": "订单处理", "path": "/wiki/order", "content": "订单处理流程..."},
        {"title": "用户管理", "path": "/wiki/user", "content": "用户管理功能..."},
    ]
    result = await agent._execute_tool("read_wiki_page", {"query": "订单"})
    assert result["title"] == "订单处理"
    assert "订单处理流程" in result["content"]

@pytest.mark.asyncio
async def test_read_wiki_page_from_graph(self):
    llm = MagicMock()
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[
        {"title": "支付模块", "path": "/wiki/payment", "content": "支付逻辑..."}
    ]))
    agent = WikiPageAgent(llm, gs)
    agent._existing_pages = None
    result = await agent._execute_tool("read_wiki_page", {"query": "payment"})
    assert result["title"] == "支付模块"

@pytest.mark.asyncio
async def test_read_wiki_page_not_found(self):
    llm = MagicMock()
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    agent = WikiPageAgent(llm, gs)
    agent._existing_pages = []
    result = await agent._execute_tool("read_wiki_page", {"query": "nonexistent"})
    assert result.get("content", "") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_wiki_page_from_existing tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_wiki_page_from_graph tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_wiki_page_not_found -v`
Expected: FAIL

- [ ] **Step 3: Update enrich() API + implement _tool_read_wiki_page**

Update `enrich()` signature:

```python
async def enrich(
    self, content: str, *,
    domain_name: str = "",
    existing_pages: list[dict] | None = None,
) -> str:
    gaps = _CONTEXT_GAP_RE.findall(content)
    if not gaps:
        return content

    self._existing_pages = existing_pages
    # ... rest of existing logic ...
```

Implement the tool:

```python
async def _tool_read_wiki_page(self, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", ""))
    if not query:
        return {"title": "", "path": "", "content": ""}

    if self._existing_pages:
        q_lower = query.lower()
        for page in self._existing_pages:
            if not isinstance(page, dict):
                continue
            title = str(page.get("title", "") or "")
            path = str(page.get("path", "") or "")
            content = str(page.get("content", "") or "")
            if q_lower in title.lower() or q_lower in path.lower():
                return {
                    "title": title,
                    "path": path,
                    "content": content[:self.SINGLE_RESULT_LIMIT],
                }

    if self._graph and hasattr(self._graph, "execute_query"):
        from wiki.cypher_queries import WIKI_PAGE_BY_QUERY_CY
        result = await self._graph.execute_query(
            WIKI_PAGE_BY_QUERY_CY, {"query": query, "limit": self.SINGLE_RESULT_LIMIT},
        )
        rows = getattr(result, "data", None) or []
        for row in rows:
            if isinstance(row, dict):
                return {
                    "title": str(row.get("title", "") or ""),
                    "path": str(row.get("path", "") or ""),
                    "content": str(row.get("content", "") or ""),
                }

    return {"title": "", "path": "", "content": ""}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_wiki_page_from_existing tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_wiki_page_from_graph tests/wiki/test_page_agent.py::TestWikiPageAgent::test_read_wiki_page_not_found -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agent): add read_wiki_page tool with dual data source"
```

---

### Task 7: semantic_search 工具

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_semantic_search_success(self):
    llm = MagicMock()
    gs = MagicMock()
    mock_search = MagicMock()
    mock_search.search_with_context = AsyncMock(return_value={
        "results": [
            {"entity_name": "OrderService", "score": 0.92, "source_type": "code",
             "entity_type": "Class", "file_path": "a.java"},
        ],
        "confidence": 0.9,
    })
    agent = WikiPageAgent(llm, gs, search_service=mock_search)
    result = await agent._execute_tool("semantic_search", {"query": "order processing"})
    assert len(result["results"]) >= 1

@pytest.mark.asyncio
async def test_semantic_search_unavailable(self):
    llm = MagicMock()
    gs = MagicMock()
    agent = WikiPageAgent(llm, gs)
    result = await agent._execute_tool("semantic_search", {"query": "test"})
    assert "error" in result
    assert "unavailable" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_semantic_search_success tests/wiki/test_page_agent.py::TestWikiPageAgent::test_semantic_search_unavailable -v`
Expected: FAIL

- [ ] **Step 3: Implement _tool_semantic_search**

```python
async def _tool_semantic_search(self, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", ""))
    limit = min(int(args.get("limit", 5) or 5), 10)
    if not query:
        return {"results": []}
    if not self._search_service:
        return {"error": "semantic search unavailable"}

    try:
        raw = await self._search_service.search_with_context(
            query, k=limit, expand_depth=1,
            include_callers=False, include_callees=False,
            use_query_expansion=False,
        )
        hits = raw.get("results", [])
        results = []
        for hit in hits[:limit]:
            if isinstance(hit, dict):
                results.append({
                    "title": str(hit.get("entity_name", "") or hit.get("name", "") or ""),
                    "content": str(hit.get("file_path", "") or ""),
                    "source": str(hit.get("source_type", "code") or "code"),
                    "score": float(hit.get("score", 0) or 0),
                })
        return {"results": results}
    except Exception as e:
        log.warning("semantic_search_failed", error=str(e))
        return {"error": str(e)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_semantic_search_success tests/wiki/test_page_agent.py::TestWikiPageAgent::test_semantic_search_unavailable -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agent): add semantic_search tool with HybridSearchService"
```

---

### Task 8: AGENT_TOOLS 注册 + _execute_tool 分发 + MAX_TOOL_CALLS

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing tests**

```python
def test_agent_tools_contains_new_tools(self):
    from wiki.page_agent import AGENT_TOOLS
    tool_names = {t["function"]["name"] for t in AGENT_TOOLS}
    assert "read_code" in tool_names
    assert "read_file" in tool_names
    assert "search_entities" in tool_names
    assert "read_wiki_page" in tool_names
    assert "semantic_search" in tool_names

@pytest.mark.asyncio
async def test_max_tool_calls_enforced(self):
    llm = MagicMock()
    call_count = 0

    async def mock_complete(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "content": None,
            "tool_calls": [
                {"function": {"name": "search_entities", "arguments": '{"keyword":"x"}'}, "id": f"c{call_count}"},
                {"function": {"name": "search_entities", "arguments": '{"keyword":"y"}'}, "id": f"d{call_count}"},
                {"function": {"name": "search_entities", "arguments": '{"keyword":"z"}'}, "id": f"e{call_count}"},
            ],
        }

    llm.complete_with_tools = mock_complete
    llm.generate = AsyncMock(return_value="fallback")
    gs = MagicMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    agent = WikiPageAgent(llm, gs)
    content = "<!-- CONTEXT_GAP: test -->"
    await agent.enrich(content, domain_name="test")
    # With 3 tool calls per round and MAX_TOOL_CALLS=15, should stop after ~5 rounds
    assert call_count <= WikiPageAgent.MAX_ROUNDS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py::TestWikiPageAgent::test_agent_tools_contains_new_tools tests/wiki/test_page_agent.py::TestWikiPageAgent::test_max_tool_calls_enforced -v`
Expected: FAIL

- [ ] **Step 3: Update AGENT_TOOLS list + _execute_tool + enrich() with MAX_TOOL_CALLS**

Add new tool definitions to `AGENT_TOOLS`:

```python
AGENT_TOOLS = [
    # ... existing 6 tools ...
    {
        "type": "function",
        "function": {
            "name": "read_code",
            "description": "Read source code for a function or class by name. Returns code snippet with file location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "Function or class name"},
                    "max_chars": {"type": "integer", "description": "Max characters (default 3000)"},
                },
                "required": ["entity_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file content by path. Supports any file type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path from repo root"},
                    "start_line": {"type": "integer", "description": "Start line (1-based, default 1)"},
                    "end_line": {"type": "integer", "description": "End line (default start+100)"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entities",
            "description": "Search code entities by keyword in names, docstrings, annotations",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Keyword (case-insensitive)"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_wiki_page",
            "description": "Read an existing wiki page by path or title keyword",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Page path or title keyword"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Semantic search across code and wiki using natural language",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
]
```

Update `_execute_tool` dispatch:

```python
async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if tool_name == "read_code":
            return await self._tool_read_code(args)
        elif tool_name == "read_file":
            return await self._tool_read_file(args)
        elif tool_name == "search_entities":
            return await self._tool_search_entities(args)
        elif tool_name == "read_wiki_page":
            return await self._tool_read_wiki_page(args)
        elif tool_name == "semantic_search":
            return await self._tool_semantic_search(args)
        # existing tools
        elif tool_name == "query_module_detail":
            return await self._tool_query_module_detail(args)
        # ... etc ...
    except Exception as e:
        log.warning("agent_tool_failed", tool=tool_name, error=str(e))
        return {"error": str(e)}
```

Update `enrich()` with `MAX_TOOL_CALLS`:

```python
async def enrich(self, content: str, *, domain_name: str = "", existing_pages: list[dict] | None = None) -> str:
    gaps = _CONTEXT_GAP_RE.findall(content)
    if not gaps:
        return content

    self._existing_pages = existing_pages
    memory = WorkingMemory()
    messages = [
        {"role": "system", "content": _AGENT_SYSTEM},
        {"role": "user", "content": self._build_user_prompt(content, gaps, memory, domain_name)},
    ]

    total_tool_calls = 0
    for round_num in range(self.MAX_ROUNDS):
        # ... existing LLM call ...
        if tool_calls:
            total_tool_calls += len(tool_calls)
            if total_tool_calls >= self.MAX_TOOL_CALLS:
                log.info("agent_max_tool_calls_reached", total=total_tool_calls)
                break
        # ... rest of existing logic ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "feat(agent): register 5 new tools, add MAX_TOOL_CALLS enforcement"
```

---

### Task 9: 回归测试

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `cd knowledge-base-service && python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20`
Expected: All tests pass, no regressions

- [ ] **Step 2: Run page_agent tests specifically**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_page_agent.py -v`
Expected: All tests pass including old and new tests

- [ ] **Step 3: Update PROPOSAL document**

Add implementation record to `docs/proposals/PROPOSAL_20260507_193240_context_augmentation_strategy.md`

- [ ] **Step 4: Final commit**

```bash
git add docs/proposals/
git commit -m "docs: update PROPOSAL with Phase 3C agent tools enhancement record"
```
